"""Four+ classes of Brownfield negative rejection (Q-04 / AC-02 negative cases)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from plc_engine.changeplan.diff_plan import DiffPlan
from plc_engine.changeplan.impact_closure import referenced_by_kept_blocks
from plc_engine.changeplan.source_binding import SourceBinding


@dataclass
class GuardIssue:
    code: str = ""
    source_id: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "source_id": self.source_id, "reason": self.reason}


FORBIDDEN_WRITE_OPS = frozenset({"write_f_block", "modify_original", "apply_to_original", "delete_original"})


def evaluate_diff_plan(
    plan: DiffPlan,
    bindings: Iterable[SourceBinding],
    *,
    expected_baseline_hash: str = "",
    actual_baseline_hash: str = "",
) -> list[GuardIssue]:
    """Return every rejection reason; an empty list means the DECLARATION is safe.

    NOTE: even an empty list NEVER makes the plan executable this batch and
    NEVER authorises a real TIA write (Q-04).
    """
    issues: list[GuardIssue] = []
    records = list(bindings)
    by_id = {record.source_id: record for record in records}
    kept_ids = {record.source_id for record in records}

    if plan.executable:
        issues.append(GuardIssue("EXECUTABLE_FORBIDDEN", plan.plan_id,
                                 "DiffPlan.executable must be false this batch"))
    if expected_baseline_hash and actual_baseline_hash and expected_baseline_hash != actual_baseline_hash:
        issues.append(GuardIssue("BASELINE_HASH_MISMATCH", plan.project_id,
                                 f"baseline drift: expected {expected_baseline_hash}, actual {actual_baseline_hash}"))
    if plan.baseline_hash and actual_baseline_hash and plan.baseline_hash != actual_baseline_hash:
        issues.append(GuardIssue("BASELINE_HASH_MISMATCH", plan.plan_id,
                                 "plan baseline does not match the current project baseline"))

    for op in plan.ops:
        source_id = op.source_id or op.target
        binding = by_id.get(source_id)
        if op.op in FORBIDDEN_WRITE_OPS:
            issues.append(GuardIssue("WRITEBACK_FORBIDDEN", source_id,
                                     "write to the original / protected object is out of scope"))
        if op.op == "DELETE":
            if binding is None:
                issues.append(GuardIssue("WRITEBACK_FORBIDDEN", source_id,
                                         "cannot delete an unknown source block"))
            else:
                callers = referenced_by_kept_blocks(binding, kept_ids)
                if callers:
                    issues.append(GuardIssue("WRITEBACK_FORBIDDEN", source_id,
                                             f"block is still referenced by kept blocks: {', '.join(callers)}"))
                if binding.is_protected():
                    issues.append(GuardIssue("WRITEBACK_FORBIDDEN", source_id,
                                             "protected / F-block / unparseable block must be preserved"))
        if op.op in ("MODIFY", "ADD") and binding is not None and binding.is_protected():
            issues.append(GuardIssue("WRITEBACK_FORBIDDEN", source_id,
                                     "F-block or unparseable block is writable=requires_review"))
        if binding is not None and binding.fidelity in ("unparseable", "protected"):
            if op.op == "DELETE":
                issues.append(GuardIssue("WRITEBACK_FORBIDDEN", source_id,
                                         "unparseable/protected block must be retained, not removed"))

    # Unparseable / protected blocks must still be present in the binding index.
    for record in records:
        if record.is_protected() and record.source_id not in kept_ids:
            issues.append(GuardIssue("WRITEBACK_FORBIDDEN", record.source_id,
                                     "protected block disappeared from the source binding index"))
    return issues
