"""Deterministic offline scan-cycle simulator (WP-03 / blueprint A3/A5).

The scan order is fixed and documented in ``contracts.SCAN_ORDER`` and is
shared with SCL lowering. Every TraceFrame is labelled as a **prediction**,
never as a real-machine waveform. Data source is always ``offline_model``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plc_engine.engineering_ir.contracts import SCAN_CYCLE_MS, SCAN_ORDER
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import EngineeringIRV2
from plc_engine.process.graph_validation import (
    arbitrate_single_writer,
    reverse_command_pairs,
    shortest_counterexample,
)
from plc_engine.process.sequence_ir import Action, EdgeType, ExceptionTrigger

NOTICE = "预测模型 Trace · 非在线 PLC 波形；预测，不是实机验证"


@dataclass
class ScenarioInput:
    """One external input change at a deterministic point in time."""

    time_ms: int = 0
    signal: str = ""
    value: Any = False

    def to_dict(self) -> dict[str, Any]:
        return {"time_ms": int(self.time_ms), "signal": self.signal, "value": self.value}


@dataclass
class Scenario:
    """A documented test scenario made of deterministic input events."""

    name: str = ""
    description: str = ""
    duration_ms: int = 2500
    inputs: list[ScenarioInput] = field(default_factory=list)
    safety_permit: bool = True
    reset_at_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "duration_ms": int(self.duration_ms),
            "inputs": [item.to_dict() for item in self.inputs],
            "safety_permit": bool(self.safety_permit),
            "reset_at_ms": self.reset_at_ms,
        }


@dataclass
class TraceFrame:
    """One scan cycle of the offline prediction."""

    cycle: int = 0
    time_ms: int = 0
    active_step: str = ""
    conditions: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    driver_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, bool] = field(default_factory=dict)
    alarms: list[str] = field(default_factory=list)
    source_map_refs: list[str] = field(default_factory=list)
    evidence_level: str = EvidenceLevel.OFFLINE.value
    data_source: str = "offline_model"
    notice: str = NOTICE

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": int(self.cycle),
            "time_ms": int(self.time_ms),
            "active_step": self.active_step,
            "conditions": dict(sorted(self.conditions.items())),
            "actions": [dict(a) for a in self.actions],
            "driver_states": {k: dict(v) for k, v in sorted(self.driver_states.items())},
            "outputs": dict(sorted(self.outputs.items())),
            "alarms": list(self.alarms),
            "source_map_refs": list(self.source_map_refs),
            "evidence_level": self.evidence_level,
            "data_source": self.data_source,
            "notice": self.notice,
        }


def build_standard_scenarios() -> dict[str, Scenario]:
    """The five required scenarios (PRD 5.4 / TASK-03A)."""
    def inp(time_ms: int, signal: str, value: Any) -> ScenarioInput:
        return ScenarioInput(time_ms=time_ms, signal=signal, value=value)

    return {
        "normal_cycle": Scenario(
            name="normal_cycle",
            description="正常循环：启动→伸出到位→保持→缩回到位→完成",
            duration_ms=2500,
            inputs=[
                inp(0, "CmdStart", True),
                inp(0, "SafetyPermit", True),
                inp(100, "SensorOut", True),
                inp(1200, "HoldDone", True),
                inp(1600, "SensorIn", True),
                inp(2200, "CmdStart", False),
            ],
        ),
        "extend_timeout": Scenario(
            name="extend_timeout",
            description="伸出不到位：SensorOut 始终为假，超时进入 FAULT",
            duration_ms=4000,
            inputs=[inp(0, "CmdStart", True), inp(0, "SafetyPermit", True)],
        ),
        "retract_timeout": Scenario(
            name="retract_timeout",
            description="缩回超时：伸出到位但 SensorIn 始终为假",
            duration_ms=4000,
            inputs=[
                inp(0, "CmdStart", True),
                inp(0, "SafetyPermit", True),
                inp(100, "SensorOut", True),
                inp(1200, "HoldDone", True),
            ],
        ),
        "safety_permit_lost": Scenario(
            name="safety_permit_lost",
            description="失去安全许可：软件联锁抑制全部命令并进入 FAULT",
            duration_ms=2000,
            inputs=[
                inp(0, "CmdStart", True),
                inp(0, "SafetyPermit", True),
                inp(100, "SensorOut", True),
                inp(500, "SafetyPermit", False),
            ],
        ),
        "fault_reset": Scenario(
            name="fault_reset",
            description="故障复位：超时进入 FAULT 后显式 Reset 重新进入待机",
            duration_ms=5000,
            inputs=[
                inp(0, "CmdStart", True),
                inp(0, "SafetyPermit", True),
                inp(3500, "Reset", True),
                inp(3500, "CmdStart", False),
                inp(4200, "Reset", False),
            ],
        ),
    }


class ScanSimulator:
    """Offline deterministic scan-cycle simulator."""

    def scan_order(self) -> tuple[str, ...]:
        """The documented fixed scan order (identical to SCL lowering)."""
        return SCAN_ORDER

    def run(self, ir: EngineeringIRV2, scenario: Scenario) -> list[TraceFrame]:
        """Run one scenario and return a deterministic list of TraceFrames."""
        from plc_engine.components.driver_fsm import DriverFSM, DriverMode

        sequence = ir.process
        signals: set[str] = set()
        for tr in sequence.transitions:
            if tr.guard_ast is not None:
                signals.update(tr.guard_ast.referenced_signals())
        for exc in sequence.exceptions:
            if exc.guard_ast is not None:
                signals.update(exc.guard_ast.referenced_signals())
        signals.update({"SafetyPermit", "Reset", "CmdStart", "SensorOut", "SensorIn"})
        snapshot: dict[str, Any] = {name: False for name in signals}
        snapshot["SafetyPermit"] = bool(scenario.safety_permit)

        drivers: dict[str, DriverFSM] = {}
        pairs_by_component: dict[str, list[tuple[str, str]]] = {}
        for component in sorted(ir.components, key=lambda c: c.id):
            spec = ir.driver_specs.get(component.driver_spec_id)
            if spec is None:
                continue
            drivers[component.id] = DriverFSM(spec, component.id)
            pairs_by_component[component.id] = reverse_command_pairs([p.name for p in spec.command_ports])

        active_step = sequence.initial_step
        step_elapsed_ms = 0
        frames: list[TraceFrame] = []
        total_cycles = max(1, int(scenario.duration_ms) // SCAN_CYCLE_MS)
        for cycle in range(total_cycles):
            time_ms = cycle * SCAN_CYCLE_MS
            # 1. FREEZE_INPUT_SNAPSHOT (deterministic event application)
            for event in sorted(scenario.inputs, key=lambda e: (e.time_ms, e.signal)):
                if event.time_ms <= time_ms:
                    snapshot[event.signal] = event.value
            if scenario.reset_at_ms is not None and time_ms == scenario.reset_at_ms:
                snapshot["Reset"] = True
            safety_permit = bool(snapshot.get("SafetyPermit", True))
            reset = bool(snapshot.get("Reset", False))

            # 2. EVALUATE_TYPED_GUARDS (no eval, fail-closed)
            conditions = {
                name: snapshot.get(name, False)
                for name in signals
            }
            alarms: list[str] = []
            actions: list[Action] = []
            step = sequence.step_index().get(active_step)
            next_step = active_step
            transition_reason = ""

            # 3. RESOLVE_PRIORITY_AND_EXCLUSIVITY (timeout/exception first)
            timed_out = bool(step and step.max_duration_ms and step_elapsed_ms >= step.max_duration_ms)
            if timed_out:
                exception = next((e for e in sequence.exceptions if e.from_step == active_step), None)
                if exception is not None:
                    next_step = exception.to_step
                    alarms.append(f"timeout:{active_step}->{next_step} ({step.max_duration_ms}ms)")
                    transition_reason = "TIMEOUT"
                else:
                    alarms.append(f"timeout_no_fault_path:{active_step}")
            elif not safety_permit:
                exception = next(
                    (e for e in sequence.exceptions
                     if (e.trigger.value if hasattr(e.trigger, "value") else str(e.trigger))
                     == ExceptionTrigger.SAFETY_PERMIT_LOST.value),
                    None,
                )
                if exception is not None and exception.to_step in sequence.step_ids():
                    next_step = exception.to_step
                    transition_reason = "SAFETY_PERMIT_LOST"
                alarms.append("safety_permit_lost:software_interlock_only")
            elif reset:
                reset_target = sequence.initial_step
                if reset_target:
                    next_step = reset_target
                    transition_reason = "RESET"
            else:
                normal_ready = bool(step is None or step.min_duration_ms <= step_elapsed_ms)
                if normal_ready:
                    for tr in sequence.outgoing(active_step):
                        edge_type = tr.edge_type.value if hasattr(tr.edge_type, "value") else str(tr.edge_type)
                        if edge_type != EdgeType.NORMAL.value:
                            continue
                        if tr.guard_ast is not None and tr.guard_ast.evaluate(snapshot):
                            next_step = tr.to_step
                            transition_reason = tr.id
                            break

            # 4. ATOMIC_TRANSITION + 5. COMPOSE_ACTIONS (documented policy)
            if step is not None:
                actions.extend(step.cyclic_actions)
                if next_step != active_step:
                    actions.extend(step.exit_actions)
            if next_step != active_step:
                target = sequence.step_index().get(next_step)
                if target is not None:
                    actions.extend(target.entry_actions)
                active_step = next_step
                step_elapsed_ms = 0
            else:
                step_elapsed_ms += SCAN_CYCLE_MS

            # 6. ARBITRATE_SINGLE_WRITER (shared with SCL lowering)
            all_pairs = [pair for pairs in pairs_by_component.values() for pair in pairs]
            commands, arbitration_alarms = arbitrate_single_writer(
                actions, safety_permit, reverse_pairs=all_pairs
            )
            alarms.extend(arbitration_alarms)
            outputs = {f"{comp}.{cmd}": bool(value) for (comp, cmd), value in sorted(commands.items())}

            # 7. TICK_DRIVER_FSMS
            driver_states: dict[str, dict[str, Any]] = {}
            for component_id, fsm in sorted(drivers.items()):
                runtime = fsm.step(
                    auto_extend=bool(commands.get((component_id, "CmdExtend"), False)),
                    auto_retract=bool(commands.get((component_id, "CmdRetract"), False)),
                    mode=DriverMode.AUTO,
                    safety_permit=safety_permit,
                    sensor_out=bool(snapshot.get("SensorOut", False)),
                    sensor_in=bool(snapshot.get("SensorIn", False)),
                    reset=reset,
                    cycle_ms=SCAN_CYCLE_MS,
                )
                driver_states[component_id] = runtime.to_dict()
                if runtime.error_id:
                    alarms.append(f"{component_id}:{runtime.error_id}")

            # 8. EMIT_OUTPUTS_AND_ALARMS
            # The transition that fired is recorded in the frame conditions so
            # a Trace interval can be located back to a concrete IR edge.
            if transition_reason:
                conditions["_selected_transition"] = transition_reason
            frames.append(
                TraceFrame(
                    cycle=cycle,
                    time_ms=time_ms,
                    active_step=active_step,
                    conditions=conditions,
                    actions=[
                        {
                            "id": a.id,
                            "target_component_id": a.target_component_id,
                            "command": a.command,
                            "value": a.value,
                            "source_id": a.source_id,
                        }
                        for a in actions
                    ],
                    driver_states=driver_states,
                    outputs=outputs,
                    alarms=sorted(set(alarms)),
                    source_map_refs=sorted({a.source_id or a.id for a in actions} | {active_step}),
                )
            )
        return frames

    def shortest_counterexample(self, ir: EngineeringIRV2) -> list[str]:
        """Shortest path from the initial step to a fault target."""
        return shortest_counterexample(ir)


def run_all_scenarios(ir: EngineeringIRV2) -> dict[str, list[dict[str, Any]]]:
    """Run the five standard scenarios and return plain dict traces."""
    simulator = ScanSimulator()
    return {
        name: [frame.to_dict() for frame in simulator.run(ir, scenario)]
        for name, scenario in sorted(build_standard_scenarios().items())
    }
