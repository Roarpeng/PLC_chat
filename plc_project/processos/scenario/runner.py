"""Deterministic scan-cycle scenario runner with a counterexample engine.

Replays a Process Contract against timed input scenarios (blueprint §2 Scenario
Runner / V1 behaviour). Produces traces, property verdicts and — on failure — a
minimal counterexample trace pinpointing the offending scan cycle. This is a
rule model, NOT a PLC runtime and NOT physical simulation (evidence: simulated).
"""
from __future__ import annotations

from processos.contract import (
    Counterexample,
    ProcessContract,
    Scenario,
    ScenarioResult,
    TraceEvent,
)
from processos.semantics.guards import eval_guard

DT_MS = 50
MAX_MS = 30000
ACTIVE_STEPS_HINT = ("EXTEND", "HOLD", "RETRACT")

#: Opposing feedback pairs per device kind (mutually exclusive physical states).
CONFLICT_PAIRS = {
    "cylinder": ("Extended", "Retracted"),
    "electric_gripper": ("Gripped", "Released"),
    "pneumatic_gripper": ("Gripped", "Open"),
    "valve_island": ("Opened", "Closed"),
}


class Runner:
    """Concrete ScenarioRunner."""

    def run(self, contract: ProcessContract, scenario: Scenario) -> ScenarioResult:
        op = contract.operations[0]
        steps = {s.id: s for s in op.steps}
        entry = op.steps[0].id
        fault_step = next((s.id for s in op.steps if s.is_fault), "")
        resource = contract.resources[0]

        commands = {c: False for c in resource.commands}
        inputs: dict[str, bool] = {"SafetyPermit": True, "Start": False, "Reset": False}
        for fb in resource.feedback:
            inputs[fb] = False
        conflict_pair = CONFLICT_PAIRS.get(resource.kind)
        cmd_list = resource.commands

        def cmds_conflict() -> bool:
            return bool(resource.exclusive and len(cmd_list) == 2 and commands.get(cmd_list[0]) and commands.get(cmd_list[1]))

        def is_active(s: str) -> bool:
            return s != entry and s != fault_step and not s.endswith("DONE")
        events = sorted(scenario.inputs, key=lambda e: e.get("t_ms", 0))
        ev_idx = 0

        step = entry
        step_enter = 0
        fault_reason = ""
        reached: list[str] = [entry]
        trace: list[TraceEvent] = []
        flags = {
            "simultaneous": False,
            "simultaneous_cycle": -1,
            "reset_ok": False,
            "completed": False,
            "hold_elapsed": 0,
            "permit_stopped": False,
        }
        fault_age = 0

        def env() -> dict[str, bool]:
            return {**inputs, **commands}

        def log(t: int, event: str, fault: bool = False) -> None:
            trace.append(TraceEvent(
                t_ms=t, step=step, event=event,
                commands=dict(commands), inputs=dict(inputs), fault=fault,
            ))

        def enter(t: int, target: str, reason: str) -> None:
            nonlocal step, step_enter
            cur = steps[step]
            for a in cur.exit:
                commands[a.command] = bool(a.value)
            step = target
            step_enter = t
            if target not in reached:
                reached.append(target)
            for a in steps[target].entry:
                commands[a.command] = bool(a.value)
            log(t, f"-> {target} ({reason})")
            if cmds_conflict():
                flags["simultaneous"] = True
                if flags["simultaneous_cycle"] < 0:
                    flags["simultaneous_cycle"] = t // DT_MS

        def to_fault(t: int, reason: str) -> None:
            nonlocal fault_reason
            for c in commands:
                commands[c] = False
            fault_reason = reason
            if reason == "PERMIT_LOST":
                flags["permit_stopped"] = True
            enter(t, fault_step or step, reason)
            log(t, f"fault latch: {reason}; commands cleared", fault=True)

        log(0, f"scenario start: {scenario.id}")
        t = 0
        while t <= MAX_MS:
            while ev_idx < len(events) and events[ev_idx].get("t_ms", 0) <= t:
                e = events[ev_idx]
                inputs[str(e["signal"])] = bool(e["value"])
                ev_idx += 1

            cur = steps[step]
            if step == fault_step:
                fault_age += DT_MS
                if cur.reset_guard and eval_guard(cur.reset_guard, env()):
                    fault_reason = ""
                    flags["reset_ok"] = True
                    fault_age = 0
                    enter(t, cur.next or entry, "reset qualified")
            elif conflict_pair and inputs.get(conflict_pair[0]) and inputs.get(conflict_pair[1]):
                to_fault(t, "FEEDBACK_FAULT")
            elif not inputs.get("SafetyPermit", True) and is_active(step):
                to_fault(t, "PERMIT_LOST")
            elif cur.is_fault:
                pass
            elif step == entry:
                if not cur.guard or eval_guard(cur.guard, env()):
                    enter(t, cur.next, "start guard")
            elif cur.duration_ms:
                if t - step_enter >= cur.duration_ms:
                    flags["hold_elapsed"] = t - step_enter
                    enter(t, cur.next, f"hold {cur.duration_ms}ms elapsed")
            else:
                if cur.timeout_ms and t - step_enter >= cur.timeout_ms:
                    to_fault(t, "TIMEOUT")
                elif cur.guard and eval_guard(cur.guard, env()):
                    if cur.next and steps.get(cur.next) and steps[cur.next].id == entry:
                        flags["completed"] = True
                    enter(t, cur.next, "guard satisfied")
                elif not cur.guard and cur.next:
                    if steps.get(cur.next) and steps[cur.next].id == entry:
                        flags["completed"] = True
                    enter(t, cur.next, "unconditional")

            if cmds_conflict():
                flags["simultaneous"] = True
                if flags["simultaneous_cycle"] < 0:
                    flags["simultaneous_cycle"] = t // DT_MS

            done = False
            if scenario.expect.get("completed") and flags["completed"]:
                done = True
            if scenario.kind == "fault" and step == fault_step and fault_age >= 250:
                done = True
            if scenario.expect.get("reset_ok") and flags["reset_ok"] and step == entry:
                done = True
            if done:
                break
            t += DT_MS

        properties = self._properties(scenario, flags, fault_reason, op)
        counterexamples = self._counterexamples(scenario, flags, properties, trace)
        passed = self._passed(scenario, flags, fault_reason, reached, properties)
        return ScenarioResult(
            scenario_id=scenario.id,
            passed=passed,
            trace=trace,
            reached=reached,
            fault_reason=fault_reason,
            counterexamples=counterexamples,
            properties=properties,
            evidence_level="simulated",
        )

    def run_all(self, contract: ProcessContract) -> list[ScenarioResult]:
        return [self.run(contract, s) for s in contract.scenarios]

    def _properties(self, scenario, flags, fault_reason, op) -> dict[str, str]:
        props: dict[str, str] = {}
        props["no_simultaneous_extend_retract"] = "fail" if flags["simultaneous"] else "pass"
        if scenario.id in ("extend_timeout", "retract_timeout"):
            props["extend_timeout_causes_fault"] = "pass" if fault_reason == "TIMEOUT" else "fail"
        if scenario.id == "fault_reset":
            props["reset_requires_safe_condition"] = "pass" if flags["reset_ok"] else "fail"
            props["extend_timeout_causes_fault"] = "pass" if flags["reset_ok"] else "fail"
        if scenario.id == "permit_loss":
            props["permit_loss_stops_motion"] = "pass" if flags["permit_stopped"] else "fail"
        if scenario.id == "normal_cycle":
            hold = op.step("S_HOLD")
            if hold is not None:
                props["hold_duration_respected"] = "pass" if flags["hold_elapsed"] == hold.duration_ms else "fail"
        return props

    def _counterexamples(self, scenario, flags, properties, trace) -> list[Counterexample]:
        out: list[Counterexample] = []
        if flags["simultaneous"]:
            cyc = max(flags["simultaneous_cycle"], 0)
            window = [e for e in trace if e.t_ms // DT_MS >= max(cyc - 1, 0)][:6]
            out.append(Counterexample(
                property_id="no_simultaneous_extend_retract",
                cycle=cyc,
                description=f"第 {cyc} 个扫描周期 Extend 与 Retract 命令同时为真，违反单写者互斥。",
                trace=window,
            ))
        for pid, verdict in properties.items():
            if verdict == "fail" and pid != "no_simultaneous_extend_retract":
                out.append(Counterexample(
                    property_id=pid,
                    cycle=len(trace),
                    description=f"场景 {scenario.id} 未满足属性 {pid}。",
                    trace=trace[-6:],
                ))
        return out

    def _passed(self, scenario, flags, fault_reason, reached, properties) -> bool:
        exp = scenario.expect
        if "completed" in exp and bool(exp["completed"]) != flags["completed"]:
            return False
        if "fault" in exp and bool(exp["fault"]) != bool(fault_reason):
            return False
        if "fault_reason" in exp and exp["fault_reason"] != fault_reason:
            return False
        if "reset_ok" in exp and bool(exp["reset_ok"]) != flags["reset_ok"]:
            return False
        for r in exp.get("reached", []):
            if r not in reached:
                return False
        if any(v == "fail" for v in properties.values()):
            return False
        return True


def run(contract: ProcessContract, scenario: Scenario) -> ScenarioResult:
    return Runner().run(contract, scenario)


def run_all(contract: ProcessContract) -> list[ScenarioResult]:
    return Runner().run_all(contract)