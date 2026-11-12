"""BrownfieldService_v2 — interface + Schema + negative rejection ONLY (Q-04).

No method here opens a TIA project, calls Openness write APIs, or emits
V19_real evidence. The original project is never modified.
"""
from __future__ import annotations

import uuid
from typing import Any

from plc_engine.changeplan.brownfield_guard import GuardIssue, evaluate_diff_plan
from plc_engine.changeplan.diff_plan import DiffOp, DiffPlan
from plc_engine.changeplan.mocked_orchestrator import mocked_orchestrate
from plc_engine.changeplan.source_binding import SourceBinding


class BrownfieldServiceV2:
    """Assemble a non-executable DiffPlan and run the negative-case guards."""

    @staticmethod
    def build_plan(
        *,
        project_id: str,
        ops: list[dict[str, Any]],
        bindings_payload: list[dict[str, Any]],
        expected_baseline_hash: str = "",
        actual_baseline_hash: str = "",
    ) -> tuple[DiffPlan, list[SourceBinding], list[GuardIssue]]:
        bindings = [SourceBinding.from_dict(dict(item)) for item in bindings_payload]
        plan = DiffPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            ops=[DiffOp.from_dict(dict(op)) for op in ops],
            baseline_hash=expected_baseline_hash,
        )
        issues = evaluate_diff_plan(
            plan, bindings,
            expected_baseline_hash=expected_baseline_hash,
            actual_baseline_hash=actual_baseline_hash,
        )
        return plan, bindings, issues

    @staticmethod
    def review(
        *,
        project_id: str,
        ops: list[dict[str, Any]],
        bindings_payload: list[dict[str, Any]],
        expected_baseline_hash: str = "",
        actual_baseline_hash: str = "",
        mocked_orchestration: bool = False,
    ) -> dict[str, Any]:
        plan, bindings, issues = BrownfieldServiceV2.build_plan(
            project_id=project_id, ops=ops, bindings_payload=bindings_payload,
            expected_baseline_hash=expected_baseline_hash,
            actual_baseline_hash=actual_baseline_hash,
        )
        payload: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "executable": False,
            "evidence_level": "mocked",
            "issues": [issue.to_dict() for issue in issues],
            "plan": plan.to_dict(),
            "source_bindings": [binding.to_dict() for binding in bindings],
            "real_tia_v19_tested": False,
            "notice": (
                "本期只留接口与 Schema；AC-02 不做实机验收；"
                "不允许任何 V19 real 增删改证据，原件不动。"
            ),
        }
        if mocked_orchestration and not issues:
            payload["mocked_orchestration"] = mocked_orchestrate(plan, bindings)
        return payload

    @staticmethod
    def assert_no_real_evidence(payload: dict[str, Any]) -> None:
        """Fail-closed guard for tests / callers: no V19 real claim is allowed."""
        if payload.get("evidence_level") == "V19_real" or payload.get("real_tia_v19_tested"):
            raise ValueError("Brownfield must never emit V19 real write evidence")
        if payload.get("plan", {}).get("executable") is True:
            raise ValueError("DiffPlan.executable must be false this batch")
