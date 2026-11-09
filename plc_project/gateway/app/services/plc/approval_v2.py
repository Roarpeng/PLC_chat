"""PcecApprovalAdapter — READ-ONLY wrapper over plc_engine/pcec.py (WP-01).

The verified approval-gate kernel is never modified: ``new_change``,
``transition``, ``project_baseline``, ``baseline_matches``, ``put_change`` and
``get_change`` are only called. This adapter adds explicit human sign-off and
baseline recheck semantics on top, without building a second backend.
"""
from __future__ import annotations

from typing import Any

from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine import pcec
from plc_engine.engineering_ir.contracts import ErrorCode
from plc_engine.engineering_ir.models import ChangeSet


class ApprovalRejectedError(RuntimeError):
    """Explicit rejection (baseline drift / missing human approval)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PcecApprovalAdapter:
    """Read-only pcec.py facade for change transaction + baseline checks."""

    @staticmethod
    def new_change(intent_kind: str, request: str, ops: list[Any], touched_blocks: list[str], baseline: dict[str, Any]) -> dict[str, Any]:
        """Create a pcec change transaction (kernel untouched)."""
        return pcec.new_change(intent_kind, request, ops, touched_blocks, baseline)

    @staticmethod
    def transition(change: dict[str, Any], to_status: str, *, event: str = "", **patch: Any) -> dict[str, Any]:
        """Apply a legal pcec state transition (kernel validates legality)."""
        return pcec.transition(change, to_status, event=event, **patch)

    @staticmethod
    def project_baseline(project_path: str) -> dict[str, Any]:
        """Compute a pcec project baseline fingerprint."""
        return pcec.project_baseline(project_path)

    @staticmethod
    def baseline_matches(change: dict[str, Any], project_path: str) -> bool:
        """Fail-closed baseline recheck provided by the kernel."""
        return pcec.baseline_matches(change, project_path)

    @staticmethod
    def put_change(change: dict[str, Any]) -> dict[str, Any]:
        """Persist a pcec transaction through the kernel ledger."""
        return pcec.put_change(change)

    @staticmethod
    def get_change(change_id: str) -> dict[str, Any] | None:
        """Read a pcec transaction through the kernel ledger."""
        return pcec.get_change(change_id)


class ApprovalGate:
    """Freeze / explicitly approve / recheck baseline for a ChangeSet."""

    def __init__(self, store: WorkspaceStore) -> None:
        self.store = store

    def freeze(self, changeset: ChangeSet) -> ChangeSet:
        """Persist a frozen ChangeSet, rejecting a failed validation report."""
        if not changeset.validation.passed:
            raise ApprovalRejectedError(
                ErrorCode.SEMANTIC_VALIDATION_FAILED.value,
                "cannot freeze a ChangeSet with validation issues",
            )
        transaction = PcecApprovalAdapter.new_change(
            "v2_delivery",
            f"freeze {changeset.id}",
            [op.to_dict() for op in changeset.ops],
            [],
            {"project_hash": changeset.before_hash, "tia_version": "V19", "parser_version": pcec.VERSION},
        )
        changeset.impacts["pcec_change_id"] = str(transaction.get("change_id") or "")
        return self.store.insert_changeset(changeset)

    def approve(
        self,
        changeset_id: str,
        *,
        reviewer: str,
        explicit: bool,
        expected_baseline_hash: str,
    ) -> ChangeSet:
        """Explicit human sign-off; LLM never holds this method."""
        if not explicit or not reviewer:
            raise ApprovalRejectedError(
                ErrorCode.WRITEBACK_FORBIDDEN.value,
                "approval requires explicit=True and a human reviewer",
            )
        changeset = self.store.get_changeset(changeset_id)
        if changeset is None:
            raise ApprovalRejectedError(ErrorCode.PROJECT_NOT_FOUND.value, f"unknown changeset {changeset_id!r}")
        if not changeset.validation.passed:
            raise ApprovalRejectedError(
                ErrorCode.SEMANTIC_VALIDATION_FAILED.value, "cannot approve a failed ChangeSet"
            )
        project = self.store.get_project(changeset.project_id)
        actual = project.baseline_hash or ""
        if expected_baseline_hash and actual != expected_baseline_hash:
            raise ApprovalRejectedError(
                ErrorCode.BASELINE_HASH_MISMATCH.value,
                f"baseline drift: expected {expected_baseline_hash}, actual {actual}",
            )
        transaction = PcecApprovalAdapter.new_change(
            "v2_approval", f"approve {changeset_id}", [], [],
            {"project_hash": actual, "tia_version": "V19", "parser_version": pcec.VERSION},
        )
        PcecApprovalAdapter.transition(transaction, "analyzed")
        PcecApprovalAdapter.transition(transaction, "validated")
        PcecApprovalAdapter.transition(transaction, "approved", event="explicit_human_signoff")
        PcecApprovalAdapter.put_change(transaction)
        return self.store.approve_changeset(
            changeset_id,
            reviewer=reviewer,
            explicit=True,
            expected_baseline_hash=expected_baseline_hash,
        )

    def recheck_baseline(self, change: dict[str, Any], project_path: str) -> bool:
        """Kernel-level baseline recheck before any write."""
        return PcecApprovalAdapter.baseline_matches(change, project_path)
