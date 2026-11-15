"""Static semantic validator (blueprint §2 Semantics Engine / V0 compliance).

Checks structural integrity, guard typing, single-writer arbitration, fault /
reset completeness, reachability and timing. Produces a ComplianceReport whose
errors block approval/delivery. Offline only — never claims runtime correctness.
"""
from __future__ import annotations

from collections import defaultdict

from processos.contract import (
    ComplianceReport,
    FrameworkProfile,
    Issue,
    ProcessContract,
    contract_semantic_hash,
)

from .guards import GuardError, parse_guard

STANDARD_INPUTS = {"Start", "Stop", "Reset", "SafetyPermit", "Auto", "Manual", "Enable"}


def _known_tokens(contract: ProcessContract) -> set[str]:
    tokens = set(STANDARD_INPUTS)
    for res in contract.resources:
        tokens.update(res.commands)
        tokens.update(res.feedback)
        tokens.update(res.status)
    return tokens


class Validator:
    """Concrete SemanticValidator."""

    def validate(
        self, contract: ProcessContract, profile: FrameworkProfile | None = None
    ) -> ComplianceReport:
        checks: list[dict] = []
        errors: list[Issue] = []
        warnings: list[Issue] = []

        def add(code: str, level: str, msg: str, node: str = "") -> None:
            checks.append({"code": code, "level": level, "msg": msg, "node": node})
            if level == "error":
                errors.append(Issue(code=code, message=msg, node=node, severity="error"))
            elif level == "warning":
                warnings.append(Issue(code=code, message=msg, node=node, severity="warning"))

        structural = contract.validate_structure()
        if structural:
            for s in structural:
                add("STRUCTURE", "error", s)
        else:
            add("STRUCTURE", "pass", "referential integrity OK")

        known = _known_tokens(contract)
        guard_ok = True
        for op in contract.operations:
            for st in op.steps:
                for expr in (st.guard, st.reset_guard):
                    if not expr:
                        continue
                    try:
                        g = parse_guard(expr)
                    except GuardError as exc:
                        guard_ok = False
                        add("GUARD_SYNTAX", "error", f"{st.id}: {exc}", st.id)
                        continue
                    unknown = g.tokens - known
                    if unknown:
                        guard_ok = False
                        add("GUARD_TOKEN", "error", f"{st.id}: unknown tokens {sorted(unknown)}", st.id)
        for inv in contract.invariants:
            try:
                g = parse_guard(inv.expr)
                unknown = g.tokens - known
                if unknown:
                    guard_ok = False
                    add("INVARIANT_TOKEN", "error", f"{inv.id}: unknown tokens {sorted(unknown)}", inv.id)
            except GuardError as exc:
                guard_ok = False
                add("INVARIANT_SYNTAX", "error", f"{inv.id}: {exc}", inv.id)
        if guard_ok:
            add("GUARD_TYPED", "pass", "all guards/invariants parse and resolve")

        writers: dict[tuple[str, str], set[str]] = defaultdict(set)
        for op in contract.operations:
            for st in op.steps:
                for act in st.all_actions():
                    writers[(act.target, act.command)].add(st.id)
        dup = {k: sorted(v) for k, v in writers.items() if len(v) > 1}
        if dup:
            for (res, cmd), steps in dup.items():
                add("DUPLICATE_OUTPUT_WRITER", "error", f"{res}.{cmd} written by {steps}", res)
        else:
            add("SINGLE_WRITER", "pass", "every command has a single writer")

        for op in contract.operations:
            for st in op.steps:
                if st.timeout_ms and not st.failure_target:
                    add("TIMEOUT_NO_EXIT", "error", f"{st.id}: timeout without failure_target", st.id)
                if st.is_fault and not st.reset_guard:
                    add("FAULT_NO_RESET", "error", f"{st.id}: fault step without reset_guard", st.id)
        add("FAULT_PATH", "pass", "timeout/fault steps checked")

        for op in contract.operations:
            if not op.steps:
                add("EMPTY_OPERATION", "error", f"{op.id}: no steps", op.id)
                continue
            sids = {s.id for s in op.steps}
            entry = op.steps[0].id
            adj: dict[str, set[str]] = {s.id: set() for s in op.steps}
            for st in op.steps:
                if st.next:
                    adj[st.id].add(st.next)
                if st.failure_target:
                    adj[st.id].add(st.failure_target)
            seen = {entry}
            stack = [entry]
            while stack:
                cur = stack.pop()
                for nxt in adj.get(cur, ()):
                    if nxt in sids and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            unreachable = sids - seen
            if unreachable:
                add("UNREACHABLE", "error", f"{op.id}: unreachable steps {sorted(unreachable)}", op.id)
            else:
                add("REACHABILITY", "pass", f"{op.id}: all steps reachable")

        has_exclusivity = any(
            "AND" in inv.expr and "NOT" in inv.expr for inv in contract.invariants
        )
        if not has_exclusivity:
            add("NO_EXCLUSIVITY_INVARIANT", "warning", "no mutual-exclusion invariant declared")

        steps = contract.all_steps()
        coverage = {
            "steps": len(steps),
            "actions": sum(len(s.all_actions()) for s in steps),
            "guards": sum(1 for s in steps if s.guard) + len(contract.invariants),
            "timers": sum(1 for s in steps if s.timeout_ms or s.duration_ms),
        }
        if profile is not None and not profile.verified:
            add("FRAMEWORK_NOT_VERIFIED", "warning", f"profile {profile.profile_id} not G0-verified", profile.profile_id)

        return ComplianceReport(
            errors=errors,
            warnings=warnings,
            checks=checks,
            coverage=coverage,
            evidence_level="offline_verified",
            profile_id=profile.profile_id if profile else "",
            ir_hash=contract_semantic_hash(contract),
        )


def validate(contract: ProcessContract, profile: FrameworkProfile | None = None) -> ComplianceReport:
    return Validator().validate(contract, profile)