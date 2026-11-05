"""Bounded truth-table interlock checker (exhaustive, exponential) and companion
alarm generator for the AF writeback pipeline.

What this module actually does:
  * Enumerates the full truth table of small Boolean interlock expressions to
    look for actuator collisions, unsatisfiable (deadlock) transitions and to
    emit companion HMI / ProDiag alarm texts from Slot 4 release clauses.
  * Each formula is handled by an exhaustive scan with no DPLL, no unit
    propagation and no pruning: worst-case cost is 2^N formula evaluations for
    N distinct literals. There is no latency guarantee beyond the hard bounds
    below, and the checker does not certify industrial safety.

What this module is NOT:
  * It is not an SMT / formal prover and makes no soundness claim beyond
    "an exhaustive search over <= MAX_SOLVER_LITERALS literals finished".
  * A status of "verified" means only: the bounded search completed and found
    no counterexample among the checks performed. It is NOT a proof of safety.

Fail-closed bounds (never report "safe" when a limit is hit):
  * MAX_SOLVER_LITERALS (default 16, env PLC_SMT_MAX_LITERALS) caps the number
    of distinct literals per formula.
  * SOLVER_TIME_BUDGET_S (default 2.0, env PLC_SMT_TIME_BUDGET_S) caps the
    wall-clock time of a single solve, measured with time.monotonic().
  * On either limit the result carries status="unknown", is_safe=False, and a
    reason stating the literal count and the applicable limit. is_safe=True is
    only ever produced for status="verified" with no violations or deadlocks.
"""

from __future__ import annotations

import itertools
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from plc_engine.af.cnf_splitter import (
    AndNode,
    BoolNode,
    ConstBool,
    Literal,
    NotNode,
    OrNode,
    flatten_cnf_clauses,
    parse_bool_expr,
    to_cnf,
)

DEFAULT_MAX_SOLVER_LITERALS = 16
DEFAULT_SOLVER_TIME_BUDGET_S = 2.0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


# Module-level, environment-overridable hard bounds.
MAX_SOLVER_LITERALS = _env_int("PLC_SMT_MAX_LITERALS", DEFAULT_MAX_SOLVER_LITERALS)
SOLVER_TIME_BUDGET_S = _env_float("PLC_SMT_TIME_BUDGET_S", DEFAULT_SOLVER_TIME_BUDGET_S)

# Markers used to propagate an "inconclusive" outcome from the helper entrances
# back to verify_station_safety without changing their public return types.
UNKNOWN_RULE_TYPE = "MUTUAL_EXCLUSION_UNKNOWN"
DEADLOCK_UNKNOWN_PREFIX = "INCONCLUSIVE deadlock check"


def _limit_reason(n_literals: int, cap: int) -> str:
    return (
        f"expression has {n_literals} distinct literals which exceeds "
        f"MAX_SOLVER_LITERALS={cap}; refusing unbounded truth-table scan of "
        f"up to 2^{n_literals} rows"
    )


def _timeout_reason(n_literals: int, budget: float, cap: int) -> str:
    return (
        f"time budget of {budget}s exhausted during exhaustive truth-table scan "
        f"with {n_literals} distinct literals (MAX_SOLVER_LITERALS={cap}); "
        f"result is INCONCLUSIVE"
    )


@dataclass
class SatOutcome:
    """Result of one bounded satisfiability check.

    status is "verified" only when the exhaustive search fully completed within
    the configured bounds; "unknown" means a limit was hit and no conclusion
    (neither SAT nor UNSAT) may be trusted.
    """

    is_sat: bool
    model: dict[str, bool]
    status: str  # "verified" | "unknown"
    reason: str = ""


@dataclass
class SmtVerificationResult:
    is_safe: bool
    summary: str
    violations: list[SafetyViolation] = field(default_factory=list)
    deadlocks: list[str] = field(default_factory=list)
    alarms_generated: list[CompanionAlarm] = field(default_factory=list)
    status: str = "unknown"  # "verified" | "unknown"
    reason: str = ""

    def __post_init__(self) -> None:
        # Fail-closed invariant, enforced at the data boundary so no caller can
        # construct a result that claims safety without a verified, clean check.
        if self.status != "verified" or self.violations or self.deadlocks:
            self.is_safe = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "summary": self.summary,
            "status": self.status,
            "reason": self.reason,
            "violations": [v.to_dict() for v in self.violations],
            "deadlocks": list(self.deadlocks),
            "alarms_generated": [a.to_dict() for a in self.alarms_generated],
        }


@dataclass
class SafetyViolation:
    rule_type: str
    description: str
    counterexample_inputs: dict[str, bool]
    involved_symbols: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "description": self.description,
            "counterexample_inputs": dict(self.counterexample_inputs),
            "involved_symbols": list(self.involved_symbols),
        }


@dataclass
class CompanionAlarm:
    alarm_id: str
    device_name: str
    action_type: str
    condition_clause: str
    alarm_text_zh: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "alarm_id": self.alarm_id,
            "device_name": self.device_name,
            "action_type": self.action_type,
            "condition_clause": self.condition_clause,
            "alarm_text_zh": self.alarm_text_zh,
            "suggested_action": self.suggested_action,
        }


def eval_bool_node(node: BoolNode, model: dict[str, bool]) -> bool:
    """Evaluate a BoolNode under a specific truth assignment."""
    if isinstance(node, ConstBool):
        return node.value
    if isinstance(node, Literal):
        val = model.get(node.name, False)
        return not val if node.negated else val
    if isinstance(node, NotNode):
        return not eval_bool_node(node.operand, model)
    if isinstance(node, AndNode):
        return all(eval_bool_node(op, model) for op in node.operands)
    if isinstance(node, OrNode):
        return any(eval_bool_node(op, model) for op in node.operands)
    return False


class TruthTableSatSolver:
    """Bounded truth-table interlock checker (exhaustive, exponential).

    Enumerates every truth assignment over the formula's distinct literals.
    There is no DPLL, no unit propagation and no pruning, so worst-case work is
    2^N formula evaluations. A hard literal cap and a time.monotonic() budget
    make the search fail closed (status="unknown") instead of silently running
    forever or returning a false "no counterexample / safe" conclusion.
    """

    def __init__(
        self,
        *,
        max_literals: int | None = None,
        time_budget_s: float | None = None,
    ) -> None:
        self.max_literals = MAX_SOLVER_LITERALS if max_literals is None else max_literals
        self.time_budget_s = SOLVER_TIME_BUDGET_S if time_budget_s is None else time_budget_s

    def solve_with_status(self, formula: BoolNode) -> SatOutcome:
        """Run the bounded exhaustive search and report verified/unknown status."""
        literals = sorted(formula.literals())
        n = len(literals)

        if n > self.max_literals:
            return SatOutcome(
                is_sat=False,
                model={},
                status="unknown",
                reason=_limit_reason(n, self.max_literals),
            )

        if n == 0:
            # Constant formula: nothing to enumerate.
            return SatOutcome(is_sat=eval_bool_node(formula, {}), model={}, status="verified")

        deadline = time.monotonic() + self.time_budget_s
        for combo in itertools.product([False, True], repeat=n):
            if time.monotonic() >= deadline:
                return SatOutcome(
                    is_sat=False,
                    model={},
                    status="unknown",
                    reason=_timeout_reason(n, self.time_budget_s, self.max_literals),
                )
            assignment = dict(zip(literals, combo))
            if eval_bool_node(formula, assignment):
                return SatOutcome(is_sat=True, model=assignment, status="verified")
        return SatOutcome(is_sat=False, model={}, status="verified")

    def solve(self, formula: BoolNode) -> tuple[bool, dict[str, bool]]:
        """Backward-compatible wrapper returning (is_sat, model).

        Limitation: on status="unknown" (over-limit/timeout) this returns
        (False, {}), indistinguishable from a proven-UNSAT result. Callers that
        need the distinction -- including the safety gate -- must use
        ``solve_with_status``. Direct callers of this wrapper must not treat a
        (False, {}) result as a safety certificate.
        """
        outcome = self.solve_with_status(formula)
        return outcome.is_sat, outcome.model


# Backward-compatible alias for the previous (misleadingly named) class.
SimpleDpllSatSolver = TruthTableSatSolver


class SmtInterlockVerifier:
    """Bounded truth-table interlock checker: fails closed on limits, emits alarms.

    All public entrances route SAT work through the bounded solver. When a limit
    is hit they return an inconclusive result (never a "safe" one), and
    verify_station_safety aggregates that into status="unknown" / is_safe=False.
    """

    def __init__(
        self,
        *,
        max_literals: int | None = None,
        time_budget_s: float | None = None,
    ) -> None:
        self.solver = TruthTableSatSolver(max_literals=max_literals, time_budget_s=time_budget_s)

    def verify_mutual_exclusion(
        self,
        cond_a_scl: str,
        cond_b_scl: str,
        device_a: str,
        device_b: str,
        description: str = "Mutual exclusion conflict",
    ) -> SafetyViolation | None:
        """Check whether A and B can ever both be TRUE.

        Returns None only when the bounded search *proved* the collision
        formula UNSAT. On an over-limit/timeout it returns an inconclusive
        SafetyViolation (rule_type=UNKNOWN_RULE_TYPE) so callers never read a
        false "safe" (None) result.
        """
        node_a = parse_bool_expr(cond_a_scl)
        node_b = parse_bool_expr(cond_b_scl)
        collision_formula = AndNode((node_a, node_b))
        outcome = self.solver.solve_with_status(collision_formula)

        if outcome.status == "unknown":
            return SafetyViolation(
                rule_type=UNKNOWN_RULE_TYPE,
                description=f"Inconclusive mutual-exclusion check (NOT proven safe): {outcome.reason}",
                counterexample_inputs={},
                involved_symbols=sorted(collision_formula.literals()),
            )
        if outcome.is_sat:
            return SafetyViolation(
                rule_type="MUTUAL_EXCLUSION_COLLISION",
                description=f"Mechanical collision hazard: {device_a} and {device_b} can simultaneously activate! {description}",
                counterexample_inputs=outcome.model,
                involved_symbols=sorted(collision_formula.literals()),
            )
        return None

    def verify_deadlock(self, transition_scl: str, step_name: str) -> str | None:
        """Detect a logically unsatisfiable (always FALSE) transition.

        Returns None only when the bounded search proved the condition SAT. On
        an over-limit/timeout it returns an INCONCLUSIVE string rather than a
        false "healthy" (None) result.
        """
        node = parse_bool_expr(transition_scl)
        outcome = self.solver.solve_with_status(node)
        if outcome.status == "unknown":
            return (
                f"{DEADLOCK_UNKNOWN_PREFIX} for step '{step_name}' "
                f"(NOT proven healthy): {outcome.reason}"
            )
        if not outcome.is_sat:
            return f"Deadlock detected in step '{step_name}': transition condition '{transition_scl}' is logically UNSATISFIABLE (always FALSE)."
        return None

    def verify_station_safety(
        self,
        slot4_interlocks: dict[str, str],
        step_transitions: list[tuple[str, str]] | None = None,
        custom_mutex_pairs: list[tuple[str, str, str]] | None = None,
    ) -> SmtVerificationResult:
        """Run bounded checks over a station's interlocks and transitions.

        The result is status="verified" only when every constituent check
        completed within the configured limits. Any inconclusive check forces
        status="unknown" and is_safe=False (fail-closed).
        """
        violations: list[SafetyViolation] = []
        deadlocks: list[str] = []
        alarms: list[CompanionAlarm] = []
        unknown_reasons: list[str] = []

        # Pre-flight over every raw expression. This also covers the
        # alarm-generation path, which never invokes the SAT solver but can
        # still blow up during CNF conversion on a large formula.
        exprs_to_check = list(slot4_interlocks.values())
        if step_transitions:
            exprs_to_check.extend(cond for _, cond in step_transitions)
        if custom_mutex_pairs:
            for act_a, act_b, _ in custom_mutex_pairs:
                exprs_to_check.append(slot4_interlocks.get(act_a, "TRUE"))
                exprs_to_check.append(slot4_interlocks.get(act_b, "TRUE"))
        for expr in exprs_to_check:
            n = len(parse_bool_expr(expr).literals())
            if n > self.solver.max_literals:
                unknown_reasons.append(_limit_reason(n, self.solver.max_literals))

        # 1. Automatic cylinder Home vs Work mutual exclusion verification.
        device_releases: dict[str, dict[str, str]] = {}
        for key, expr in slot4_interlocks.items():
            if "." in key:
                dev, action = key.split(".", 1)
                device_releases.setdefault(dev, {})[action] = expr

        for dev, actions in device_releases.items():
            if "releaseHome" in actions and "releaseWork" in actions:
                v = self.verify_mutual_exclusion(
                    actions["releaseHome"],
                    actions["releaseWork"],
                    f"{dev}.Home",
                    f"{dev}.Work",
                    description=f"Double valve command conflict on actuator '{dev}'",
                )
                if v is not None:
                    if v.rule_type == UNKNOWN_RULE_TYPE:
                        unknown_reasons.append(v.description)
                    else:
                        violations.append(v)

        # 2. Custom mechanical mutex pairs (e.g. Press down vs Shuttle move).
        if custom_mutex_pairs:
            for act_a, act_b, desc in custom_mutex_pairs:
                expr_a = slot4_interlocks.get(act_a, "TRUE")
                expr_b = slot4_interlocks.get(act_b, "TRUE")
                v = self.verify_mutual_exclusion(expr_a, expr_b, act_a, act_b, description=desc)
                if v is not None:
                    if v.rule_type == UNKNOWN_RULE_TYPE:
                        unknown_reasons.append(v.description)
                    else:
                        violations.append(v)

        # 3. Check transition deadlocks.
        if step_transitions:
            for step_name, cond in step_transitions:
                dl = self.verify_deadlock(cond, step_name)
                if dl is not None:
                    if dl.startswith(DEADLOCK_UNKNOWN_PREFIX):
                        unknown_reasons.append(dl)
                    else:
                        deadlocks.append(dl)

        # 4. Generate companion alarms from Slot 4 clauses.
        for key, expr in slot4_interlocks.items():
            device_name = key.split(".")[0] if "." in key else key
            action_name = key.split(".")[1] if "." in key else "Release"
            dev_alarms = self.generate_companion_alarms(device_name, action_name, expr)
            alarms.extend(dev_alarms)

        # Deduplicate while preserving order, then decide the verdict.
        unknown_reasons = list(dict.fromkeys(unknown_reasons))
        if unknown_reasons:
            status = "unknown"
            reason = "; ".join(unknown_reasons)
            is_safe = False
            summary = "INCONCLUSIVE (fail-closed): solver limits exceeded; NOT proven safe."
        else:
            status = "verified"
            reason = ""
            is_safe = len(violations) == 0 and len(deadlocks) == 0
            summary = (
                "Bounded truth-table check PASSED within limits: 0 collisions, 0 deadlocks."
                if is_safe
                else f"Bounded truth-table check FAILED: {len(violations)} collisions, {len(deadlocks)} deadlocks detected!"
            )

        return SmtVerificationResult(
            is_safe=is_safe,
            summary=summary,
            violations=violations,
            deadlocks=deadlocks,
            alarms_generated=alarms,
            status=status,
            reason=reason,
        )

    def generate_companion_alarms(
        self,
        device_name: str,
        action_name: str,
        release_expr_scl: str,
    ) -> list[CompanionAlarm]:
        """Invert each clause of Slot 4 condition tree to generate human-readable diagnostics.

        Fail-closed: if the expression exceeds the literal cap, return no alarms
        rather than attempting an unbounded CNF expansion or emitting partial
        (potentially misleading) diagnostics.
        """
        node = parse_bool_expr(release_expr_scl)
        if len(node.literals()) > self.solver.max_literals:
            return []
        cnf = to_cnf(node)
        clauses = flatten_cnf_clauses(cnf)

        alarms: list[CompanionAlarm] = []
        clause_idx = 1

        for cl in clauses:
            cl_str = " OR ".join(lit.to_scl() for lit in cl)
            # Create user-friendly Chinese diagnosis
            zh_text, suggestion = self._generate_diagnostic_text(device_name, action_name, cl)
            clean_act = re.sub(r"[^A-Za-z0-9]", "_", action_name).upper()
            alarm_id = f"ALM_{device_name.upper()}_{clean_act}_C{clause_idx}"

            alarms.append(
                CompanionAlarm(
                    alarm_id=alarm_id,
                    device_name=device_name,
                    action_type=action_name,
                    condition_clause=cl_str,
                    alarm_text_zh=zh_text,
                    suggested_action=suggestion,
                )
            )
            clause_idx += 1

        return alarms

    def _generate_diagnostic_text(
        self,
        device_name: str,
        action_name: str,
        clause_literals: list[Literal],
    ) -> tuple[str, str]:
        """Translate Boolean literal into intuitive operational fault description."""
        names = [lit.name.lower() for lit in clause_literals]
        clause_repr = " OR ".join(lit.to_scl() for lit in clause_literals)

        # Human-friendly device names
        dev_zh = device_name
        if "cyl" in dev_zh.lower():
            dev_zh = f"气缸【{device_name}】"
        elif "motor" in dev_zh.lower() or "axis" in dev_zh.lower():
            dev_zh = f"电机/轴【{device_name}】"

        act_zh = "工作" if "work" in action_name.lower() else "原位" if "home" in action_name.lower() else action_name

        # Semantic keywords
        if any("safety" in n or "estop" in n or "guard" in n for n in names):
            return (
                f"{dev_zh}{act_zh}动作释放受阻：安全保护回路未就绪",
                "请检查急停按钮、安全门锁或安全光幕是否已复位",
            )
        if any("axis" in n or "inpos" in n for n in names):
            return (
                f"{dev_zh}{act_zh}动作释放受阻：伺服轴未到达指定防撞安全位置",
                "请检查上道工序轴定位状态及防撞互锁信号",
            )
        if any("clamp" in n or "grip" in n for n in names):
            return (
                f"{dev_zh}{act_zh}动作释放受阻：夹爪/夹紧机构未就位",
                "请确认夹爪原位或夹紧到位磁开信号是否触发",
            )
        if any("sensor" in n or "pe" in n or "part" in n for n in names):
            return (
                f"{dev_zh}{act_zh}动作释放受阻：工件检测光电信号缺失",
                "请检查工位是否有料或清洁光电传感器表面",
            )

        return (
            f"{dev_zh}{act_zh}动作释放受阻：前置条件缺失 [{clause_repr}]",
            f"请在博途监控画面中核对信号 [{clause_repr}] 状态",
        )
