"""DeliveryCoordinator: 202 + job_id, ledger, project lock, strict state machine.

Real-machine chain execution is a SEPARATE explicit call (``run_chain``) so the
lead / QA can schedule TIA Portal V19 serially. This batch does NOT silently
execute a real chain on job creation: without a V19 real receipt the job stays
``pending_real_machine`` and no download button is ever offered.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from gateway.app.services.plc.artifact_store_v2 import ArtifactStore
from gateway.app.services.plc.evidence_v2 import EvidenceService
from gateway.app.services.plc.native_artifact_v2 import attach_evidence, evidence_bundle
from gateway.app.services.plc.tia_delivery_v2 import (
    ChainResult,
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    execute_chain,
)
from gateway.app.services.plc.validation_v2 import ValidationServiceV2
from gateway.app.services.plc.workspace_v2 import ProjectNotFoundError, WorkspaceStore
from plc_engine.engineering_ir.contracts import ErrorCode
from plc_engine.engineering_ir.evidence import EvidenceLevel


class DeliveryStartError(RuntimeError):
    """Structured delivery-start rejection (HTTP status + code)."""

    def __init__(self, status_code: int, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.data = dict(data or {})


class DeliveryCoordinator:
    """Authoritative job state machine and single-writer delivery orchestrator."""

    def __init__(self, store: WorkspaceStore, *, artifact_store: ArtifactStore | None = None) -> None:
        self.store = store
        # Keep the artifact store next to the workspace data directory, never
        # at the repository root (tests and multi-workspace setups stay isolated).
        default_root = store.ir_store_root.parent / "artifact_store"
        self.artifact_store = artifact_store or ArtifactStore(store, root=default_root)

    def start(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Accept a delivery request: returns ``(data, 202)`` or a structured error."""
        project_id = str(payload.get("project_id") or "")
        changeset_id = str(payload.get("approved_changeset_id") or "")
        expected_baseline = str(payload.get("expected_baseline_hash") or "")
        idem_key = str(payload.get("idempotency_key") or "")
        if not project_id or not changeset_id or not idem_key:
            raise DeliveryStartError(422, ErrorCode.INVALID_REQUEST.value,
                                    "project_id / approved_changeset_id / idempotency_key are required")
        if not self.store.project_exists(project_id):
            raise DeliveryStartError(404, ErrorCode.PROJECT_NOT_FOUND.value, f"unknown project {project_id!r}")

        project = self.store.get_project(project_id)
        changeset = self.store.get_changeset(changeset_id)
        if changeset is None or not changeset.review_approved or not changeset.explicit or changeset.status != "APPROVED":
            raise DeliveryStartError(403, ErrorCode.CHANGESET_NOT_APPROVED.value,
                                    "delivery requires an approved, explicitly signed ChangeSet")
        if expected_baseline and (project.baseline_hash or "") != expected_baseline:
            raise DeliveryStartError(409, ErrorCode.BASELINE_HASH_MISMATCH.value,
                                    "baseline drift detected before delivery",
                                    {"expected_baseline_hash": expected_baseline,
                                     "actual_baseline_hash": project.baseline_hash or ""})

        gate = ValidationServiceV2.static_gate(self.store.get_ir(project_id))
        if not gate["passed"]:
            raise DeliveryStartError(422, ErrorCode.SEMANTIC_VALIDATION_FAILED.value,
                                    "static gate failed; delivery refused",
                                    {"issues": gate["issues"], "unchanged_ir_hash": gate["unchanged_ir_hash"]})

        job_id = f"job_{uuid.uuid4().hex[:16]}"
        row, created = self.store.insert_job(
            job_id,
            project_id=project_id,
            changeset_id=changeset_id,
            idempotency_key=idem_key,
            expected_baseline_hash=expected_baseline,
        )
        if created:
            self.store.acquire_project_lock(project_id, row["id"])
            self.store.append_job_event(
                row["id"], state="QUEUED", stage="ACCEPTED",
                raw_api_receipt={"idempotency_key": idem_key, "changeset_id": changeset_id},
                evidence_level=EvidenceLevel.PENDING_REAL_MACHINE.value,
            )
        return (
            {
                "job_id": row["id"],
                "state": row["state"],
                "artifact_id": None,
                "evidence_level": EvidenceLevel.PENDING_REAL_MACHINE.value,
                "idempotent_hit": not created,
                "notice": "accepted; no V19 real chain executed yet (pending_real_machine)",
            },
            202,
        )

    def run_chain(
        self,
        job_id: str,
        *,
        adapter: TiaOpennessCliAdapter,
        request: DeliveryChainRequest,
    ) -> dict[str, Any]:
        """Explicitly run the strict chain (serial TIA schedule only)."""
        job = self.store.get_job(job_id)
        if job is None:
            raise ProjectNotFoundError(job_id)
        if not self.store.acquire_project_lock(job["project_id"], job_id):
            raise DeliveryStartError(409, "PROJECT_LOCKED", "another job owns the project lock")

        # Advance the state machine to SOURCE_READY before any TIA write.
        for state in ("DRAFT", "SPEC_FROZEN", "SOURCE_READY"):
            if self.store.get_job(job_id)["state"] != state:
                self.store.update_job_state(job_id, state)
                self.store.append_job_event(
                    job_id, state=state, stage="PRECONDITION",
                    raw_api_receipt={"static_gate": "passed"},
                    evidence_level=EvidenceLevel.OFFLINE.value,
                )

        state_by_stage = {
            "CREATE": "TIA_IMPORTED",
            "CREATE_DEVICE": "TIA_IMPORTED",
            "IMPORT": "TIA_IMPORTED",
            "COMPILE": "TIA_COMPILED",
            "SAVE": "TIA_COMPILED",
            "ARCHIVE": "TIA_COMPILED",
            "HASH": "TIA_COMPILED",
            "RETRIEVE_REOPEN": "TIA_COMPILED",
        }

        def on_stage(receipt: Any) -> None:
            target = state_by_stage.get(receipt.stage)
            if target and self.store.get_job(job_id)["state"] != target and receipt.ok:
                self.store.update_job_state(job_id, target, stage_cursor=receipt.stage)
            self.store.append_job_event(
                job_id,
                state=receipt.state or (target or self.store.get_job(job_id)["state"]),
                stage=receipt.stage,
                raw_api_receipt=receipt.raw_api_receipt,
                evidence_level=receipt.evidence_level,
            )

        chain: ChainResult = execute_chain(adapter, request, on_stage=on_stage)
        evidence_path = f"evidence/v2/T02/job_{job_id}.json"

        if chain.state == "NATIVE_ARCHIVED" and chain.artifact is not None:
            artifact = chain.artifact
            try:
                stored = self.artifact_store.store_file(artifact.archive_path, kind="zap19")
            except (FileNotFoundError, LookupError) as exc:
                return self._fail(job_id, chain, ErrorCode.ARCHIVE_MISSING.value,
                                  f"archive_missing at exact path: {exc}")
            self.artifact_store.register(artifact.to_dict(), stored=stored)
            attach_evidence(
                artifact,
                real_tia_v19_tested=bool(adapter.real_machine),
                raw_evidence_path=evidence_path,
            )
            bundle = evidence_bundle(artifact, job_events=self.store.get_job_events(job_id))
            raw_path = EvidenceService.write_ledger(
                "T02", f"job_{job_id}", {"chain": chain.to_dict(), "evidence_bundle": bundle}
            )
            self.store.update_job_state(job_id, "NATIVE_ARCHIVED", stage_cursor="RETRIEVE_REOPEN")
            self.store.append_job_event(
                job_id, state="NATIVE_ARCHIVED", stage="EVIDENCE",
                raw_api_receipt={
                    "evidence_id": artifact.evidence_id,
                    "artifact_id": artifact.artifact_id,
                    "artifact": artifact.to_dict(),
                },
                evidence_level=EvidenceLevel.V19_REAL.value,
            )
            self.store.release_project_lock(job["project_id"], job_id)
            return {
                "job_id": job_id, "state": "NATIVE_ARCHIVED",
                "artifact": artifact.to_dict(), "evidence_id": artifact.evidence_id,
                "evidence_level": EvidenceLevel.V19_REAL.value,
                "raw_evidence_path": str(raw_path), "chain": chain.to_dict(),
            }

        if chain.state == "MOCKED_CHAIN_OK":
            # A mocked chain must NEVER produce a downloadable native artifact.
            raw_path = EvidenceService.write_ledger(
                "T02", f"job_{job_id}_mocked",
                {
                    "chain": chain.to_dict(),
                    "real_tia_v19_tested": False,
                    "notice": "mocked orchestration only; NATIVE_ARCHIVED forbidden (PRD 6.4)",
                },
            )
            self.store.append_job_event(
                job_id, state="TIA_COMPILED", stage="MOCKED_CHAIN_OK",
                raw_api_receipt={"notice": "mocked orchestration, not a real machine"},
                evidence_level=EvidenceLevel.MOCKED.value,
            )
            self.store.release_project_lock(job["project_id"], job_id)
            return {
                "job_id": job_id, "state": "TIA_COMPILED",
                "artifact": None, "evidence_level": EvidenceLevel.MOCKED.value,
                "raw_evidence_path": str(raw_path), "chain": chain.to_dict(),
                "notice": "mocked chain completed; no native archive published and no download offered",
            }
        return self._fail(job_id, chain, chain.error_code, chain.error_message)

    def _fail(self, job_id: str, chain: ChainResult, code: str, message: str) -> dict[str, Any]:
        """Record a failed chain, keep full evidence, never publish an artifact."""
        job = self.store.get_job(job_id)
        current = job["state"] if job else "QUEUED"
        if current == "QUEUED":
            self.store.update_job_state(job_id, "DRAFT")
            current = "DRAFT"
        if current != "FAILED":
            self.store.update_job_state(job_id, "FAILED")
        self.store.append_job_event(
            job_id, state="FAILED", stage=chain.stage_receipts[-1].stage if chain.stage_receipts else "UNKNOWN",
            raw_api_receipt={"error_code": code, "message": message},
            evidence_level=EvidenceLevel.MOCKED.value,
        )
        raw_path = EvidenceService.write_ledger(
            "T02", f"job_{job_id}_failed",
            {"chain": chain.to_dict(), "real_tia_v19_tested": False,
             "notice": "FAILED: no native archive published; logs and editable design retained"},
        )
        if job:
            self.store.release_project_lock(job["project_id"], job_id)
        return {
            "job_id": job_id, "state": "FAILED", "error_code": code, "error_message": message,
            "evidence_level": EvidenceLevel.MOCKED.value,
            "raw_evidence_path": str(raw_path), "chain": chain.to_dict(),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Read job state plus artifact / evidence metadata from the ledger."""
        job = self.store.get_job(job_id)
        if job is None:
            raise ProjectNotFoundError(job_id)
        events = self.store.get_job_events(job_id)
        artifact_data: dict[str, Any] | None = None
        if job["state"] == "NATIVE_ARCHIVED":
            for event in reversed(events):
                if event["stage"] != "EVIDENCE":
                    continue
                try:
                    payload = json.loads(event["raw_api_receipt"] or "{}")
                except (TypeError, ValueError):
                    continue
                candidate = payload.get("artifact")
                if isinstance(candidate, dict):
                    artifact_data = candidate
                    break
        has_mocked = any(e["stage"] == "MOCKED_CHAIN_OK" for e in events)
        if job["state"] == "NATIVE_ARCHIVED":
            level = EvidenceLevel.V19_REAL
        elif has_mocked:
            level = EvidenceLevel.MOCKED
        else:
            level = EvidenceLevel.PENDING_REAL_MACHINE
        return {
            "job_id": job_id,
            "state": job["state"],
            "compile": artifact_data["compile"] if artifact_data else None,
            "native_artifact": {
                "artifact_id": artifact_data["artifact_id"],
                "kind": artifact_data["kind"],
                "sha256": artifact_data["archive_sha256"],
                "size_bytes": artifact_data["size_bytes"],
                "reopen_ok": artifact_data["reopen_ok"],
            } if artifact_data else None,
            "evidence_id": artifact_data["evidence_id"] if artifact_data else "",
            "evidence_level": level.value,
            "stage_cursor": job["stage_cursor"],
            "events": len(events),
            "notice": (
                "V19 real full chain" if job["state"] == "NATIVE_ARCHIVED"
                else "pending_real_machine: no compile receipt; this state must never be shown as a completed delivery"
            ),
        }

    def events(self, job_id: str) -> list[dict[str, Any]]:
        """Return the append-only ledger for SSE streaming."""
        if self.store.get_job(job_id) is None:
            raise ProjectNotFoundError(job_id)
        return self.store.get_job_events(job_id)

    def recover(self, job_id: str) -> dict[str, Any]:
        """Inspect an interrupted job and produce an idempotent recovery plan.

        No non-idempotent write is blindly replayed (design 6.3 / G7). Full
        worker-crash recovery is WP-06; this returns real, deterministic plan
        data from the ledger and stage cursor.
        """
        job = self.store.get_job(job_id)
        if job is None:
            raise ProjectNotFoundError(job_id)
        events = self.store.get_job_events(job_id)
        stages = [e["stage"] for e in events if e["stage"]]
        completed = [stage for stage in ("CREATE", "IMPORT", "COMPILE", "SAVE", "ARCHIVE", "HASH", "RETRIEVE_REOPEN") if stage in stages]
        recoverable = job["state"] in ("TIA_IMPORTED", "TIA_COMPILED", "RECOVERY_REQUIRED")
        return {
            "job_id": job_id,
            "state": job["state"],
            "stage_cursor": job["stage_cursor"],
            "completed_stages": completed,
            "recoverable": bool(recoverable),
            "resume_from": completed[-1] if completed else "CREATE",
            "plan": [
                "detect existing project at the exact create.projectPath receipt",
                "verify archive sha256 at the exact archive.archivePath receipt",
                "resume from stage cursor without replaying non-idempotent writes",
            ],
            "native_archived_published": job["state"] == "NATIVE_ARCHIVED",
            "evidence_level": EvidenceLevel.OFFLINE.value,
            "notice": "recovery plan only; no TIA write performed by this call",
        }
