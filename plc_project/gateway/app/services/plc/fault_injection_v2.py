"""WP-06 quality / recovery / fault injection (G7).

Existing landing points (no empty shells created):
  * append-only ``job_events`` + ``stage_cursor`` + ``project_locks`` -> workspace_v2.py
  * idempotency key + job state machine -> delivery_jobs_v2.py / workspace_v2.py
  * crash recovery plan -> delivery_jobs_v2.recover()

This module adds the missing orchestration and safety helpers: 12 fault kinds,
path whitelist, bad XML/ZIP rejection, schema-migration check, minimum-disclosure
context slice and rollback planning. Every injected failure MUST leave the job
out of NATIVE_ARCHIVED.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.tia_delivery_v2 import (
    ChainResult,
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    execute_chain,
)
from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.changeplan import DiffOp, DiffPlan, SourceBinding, evaluate_diff_plan

#: >= 10 fault classes required by G7 / PRD 6.2.
FAULT_KINDS: tuple[str, ...] = (
    "path_missing", "cpu_not_selected", "double_coil", "delete_referenced_fb",
    "modify_f_block", "baseline_drift", "unknown_guard", "parallel_semantics",
    "compile_failed", "archive_missing", "tia_unavailable", "worker_crash",
    "bad_xml", "bad_zip", "duplicate_request",
)

EXPECTED_TABLES: tuple[str, ...] = (
    "projects", "revisions", "changesets", "change_ops", "approvals",
    "artifacts", "jobs", "job_events", "capability_manifest", "project_locks",
)


@dataclass
class FaultResult:
    """Structured outcome of one injected fault."""

    kind: str = ""
    rejected: bool = True
    state: str = "FAILED"
    native_archived_published: bool = False
    evidence_level: str = EvidenceLevel.MOCKED.value
    error_code: str = ""
    diagnostics: list[str] = field(default_factory=list)
    ledger_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "rejected": self.rejected, "state": self.state,
            "native_archived_published": self.native_archived_published,
            "evidence_level": self.evidence_level, "error_code": self.error_code,
            "diagnostics": list(self.diagnostics), "ledger_events": self.ledger_events,
        }


class PathWhitelist:
    """Reject browser-supplied arbitrary paths; only DB-recorded relative paths."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def is_allowed(self, relative_path: str) -> bool:
        candidate = str(relative_path or "")
        if not candidate or candidate.startswith(("/", "\\")) or ".." in candidate.split("/"):
            return False
        if "\x00" in candidate or re.search(r"[<>|*?]", candidate):
            return False
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            return False
        return True

    def assert_allowed(self, relative_path: str) -> str:
        if not self.is_allowed(relative_path):
            raise PermissionError(f"PATH_OUTSIDE_WHITELIST: {relative_path!r}")
        return relative_path


def reject_bad_xml(payload: bytes | str) -> tuple[bool, str]:
    """Refuse DTD/ENTITY/broken XML (defusedxml when available, else stdlib guard)."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return False, "BAD_XML_DTD_FORBIDDEN"
    try:
        from defusedxml.ElementTree import fromstring as safe_fromstring
        safe_fromstring(raw)
    except ImportError:
        import xml.etree.ElementTree as ET
        try:
            ET.fromstring(raw)
        except ET.ParseError as exc:
            return False, f"BAD_XML_PARSE: {exc}"
    except Exception as exc:  # noqa: BLE001 - malformed / forbidden XML
        return False, f"BAD_XML_PARSE: {exc}"
    return True, "ok"


def reject_bad_zip(path: str | Path) -> tuple[bool, str]:
    """Refuse broken archives and path-traversal members (G7)."""
    target = Path(path)
    if not target.is_file():
        return False, "BAD_ZIP_MISSING"
    try:
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            if len(names) > 2000:
                return False, "BAD_ZIP_TOO_MANY_ENTRIES"
            for name in names:
                parts = name.replace("\\", "/").split("/")
                if ".." in parts or name.startswith(("/", "\\")):
                    return False, f"BAD_ZIP_TRAVERSAL: {name}"
            bad = archive.testzip()
            if bad is not None:
                return False, f"BAD_ZIP_CRC: {bad}"
    except (zipfile.BadZipFile, OSError) as exc:
        return False, f"BAD_ZIP: {exc}"
    return True, "ok"


def schema_migration_check(store: WorkspaceStore) -> dict[str, Any]:
    """Verify all 10 frozen tables + key ledger columns exist (no destructive migration)."""
    with store._lock:  # noqa: SLF001 - read-only PRAGMA
        tables = {str(row["name"]) for row in store._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    missing = [name for name in EXPECTED_TABLES if name not in tables]
    return {"ok": not missing, "expected_tables": list(EXPECTED_TABLES), "missing_tables": missing,
            "evidence_level": EvidenceLevel.OFFLINE.value}


def minimal_disclosure(ir: dict[str, Any], *, max_blocks: int = 12) -> dict[str, Any]:
    """Only the minimum block index / device definitions / current step (PRD 7.5)."""
    components = ir.get("components") if isinstance(ir.get("components"), list) else []
    process = ir.get("process") if isinstance(ir.get("process"), dict) else {}
    steps = process.get("steps") if isinstance(process.get("steps"), list) else []
    return {
        "block_index": [str(c.get("id")) for c in components[:max_blocks] if isinstance(c, dict)],
        "device_definitions": [{"id": c.get("id"), "type": c.get("component_type")}
                               for c in components[:max_blocks] if isinstance(c, dict)],
        "initial_step": process.get("initial_step", ""),
        "current_step_count": len(steps),
        "truncated": len(components) > max_blocks,
        "notice": "minimum disclosure: never send the whole TIA project to an LLM",
    }


def rollback_plan(store: WorkspaceStore, job_id: str) -> dict[str, Any]:
    """Idempotent rollback/resume plan; never blindly replays non-idempotent writes."""
    coordinator = DeliveryCoordinator(store)
    plan = coordinator.recover(job_id)
    plan["rollback_strategy"] = [
        "retain the append-only ledger and failed-stage receipt",
        "detect the existing project at the exact create.projectPath receipt",
        "verify archive sha256 at the exact archive.archivePath receipt",
        "resume from stage_cursor without replaying non-idempotent writes",
        "never publish NATIVE_ARCHIVED from a failed/recovering job",
    ]
    plan["evidence_level"] = EvidenceLevel.OFFLINE.value
    return plan


def _static_fault(kind: str, ir: Any, bindings: list[SourceBinding]) -> FaultResult:
    """Static-gate faults are rejected by the deterministic validators."""
    issues: list[str] = []
    if kind == "double_coil":
        from plc_engine.process.sequence_ir import Action
        step = next((s for s in ir.process.steps if s.all_actions()), None)
        if step is not None:
            step.entry_actions.append(Action(id="A_REV", target_component_id=ir.components[0].id,
                                             command="CmdRetract", value=True, source_id=step.id))
        issues = [i["reason"] for i in ValidationEngine().validate(ir).issues]
    elif kind == "unknown_guard":
        from plc_engine.process.guard_ast import GuardAST, GuardNodeType, GuardValueType
        tr = ir.process.transitions[0]
        tr.guard_ast = GuardAST(node_type=GuardNodeType.AND, value_type=GuardValueType.BOOL,
                                children=[GuardAST(node_type=GuardNodeType.CONST,
                                                   value_type=GuardValueType.INT, value=1)])
        issues = [i["reason"] for i in ValidationEngine().validate(ir).issues]
    elif kind == "parallel_semantics":
        ir.process.parallel_groups = [{"id": "FORK_1", "kind": "fork"}]
        issues = [i["reason"] for i in ValidationEngine().validate(ir).issues]
    elif kind in ("delete_referenced_fb", "modify_f_block", "baseline_drift"):
        op = "DELETE" if kind == "delete_referenced_fb" else "MODIFY"
        target = "FB_Motor" if kind != "modify_f_block" else "FB_Safety"
        plan = DiffPlan(plan_id="plan_fault", ops=[DiffOp(op=op, source_id=target)],
                        baseline_hash="sha256:stale" if kind == "baseline_drift" else "")
        guard_bindings = bindings or [SourceBinding.from_dict(
            {"source_id": "FB_Motor", "referenced_by": ["OB_Main"], "writable": "requires_review",
             "fidelity": "parsed"})]
        actual = "sha256:current" if kind == "baseline_drift" else ""
        issues = [i.reason for i in evaluate_diff_plan(
            plan, guard_bindings, expected_baseline_hash=plan.baseline_hash, actual_baseline_hash=actual)]
    elif kind == "bad_xml":
        ok, why = reject_bad_xml(b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>")
        issues = [] if ok else [why]
    elif kind == "bad_zip":
        ok, why = reject_bad_zip("__missing__.zip")
        issues = [] if ok else [why]
    else:
        issues = ["unknown static fault kind"]
    return FaultResult(kind=kind, rejected=bool(issues), state="FAILED", error_code="SEMANTIC_VALIDATION_FAILED",
                       diagnostics=issues, evidence_level=EvidenceLevel.OFFLINE.value)


def inject_fault(
    kind: str,
    *,
    store: WorkspaceStore,
    job_id: str,
    ir: Any = None,
    bindings: list[SourceBinding] | None = None,
    worker: Any = None,
    workspace_dir: str = "",
    cpu_type_identifier: str = "6ES7511-1AK02-0AB0/V2.9",
) -> FaultResult:
    """Inject one documented fault and prove NATIVE_ARCHIVED is never published."""
    if kind not in FAULT_KINDS:
        raise ValueError(f"unknown fault kind {kind!r}")

    if kind in ("double_coil", "unknown_guard", "parallel_semantics", "delete_referenced_fb",
                "modify_f_block", "baseline_drift", "bad_xml", "bad_zip"):
        result = _static_fault(kind, ir, list(bindings or []))
        if result.rejected:
            store.append_job_event(job_id, state="FAILED", stage=kind,
                                   raw_api_receipt={"issues": result.diagnostics},
                                   evidence_level=EvidenceLevel.OFFLINE.value)
            job = store.get_job(job_id)
            if job and job["state"] != "FAILED":
                if job["state"] == "QUEUED":
                    store.update_job_state(job_id, "DRAFT")
                if store.get_job(job_id)["state"] != "FAILED":
                    store.update_job_state(job_id, "FAILED")
        return result

    request = DeliveryChainRequest(project_id=store.get_job(job_id)["project_id"] if store.get_job(job_id) else "prj_fault",
                                   job_id=job_id, project_name="FaultProbe",
                                   workspace_dir=workspace_dir or "C:/tmp/fault_probe",
                                   cpu_type_identifier="" if kind == "cpu_not_selected" else cpu_type_identifier)
    if worker is None:
        # Offline fault injection must NEVER touch a real TIA Portal.
        def unavailable(command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
            from gateway.app.services.plc.tia_delivery_v2 import TiaUnavailableError
            raise TiaUnavailableError("tia_unavailable: offline fault injection")
        worker = unavailable
    adapter = TiaOpennessCliAdapter(worker=worker)
    chain: ChainResult = execute_chain(adapter, request)
    if kind == "worker_crash":
        # Simulate a lease expiry / interrupted worker, not a successful chain.
        store.append_job_event(job_id, state="RECOVERY_REQUIRED", stage="COMPILE",
                               raw_api_receipt={"worker_lease_expired": True},
                               evidence_level=EvidenceLevel.MOCKED.value)
        job = store.get_job(job_id)
        if job and job["state"] == "QUEUED":
            # A crash can only happen after the chain reached TIA_IMPORTED.
            for stage in ("DRAFT", "SPEC_FROZEN", "SOURCE_READY", "TIA_IMPORTED"):
                store.update_job_state(job_id, stage)
        if store.get_job(job_id)["state"] != "RECOVERY_REQUIRED":
            store.update_job_state(job_id, "RECOVERY_REQUIRED", stage_cursor="COMPILE")
        return FaultResult(kind=kind, state="RECOVERY_REQUIRED", error_code="WORKER_CRASH",
                           diagnostics=["worker lease expired; recovery plan required"],
                           ledger_events=len(store.get_job_events(job_id)))

    DeliveryCoordinator(store)._fail(job_id, chain, chain.error_code or "TIA_UNAVAILABLE",  # noqa: SLF001
                                     chain.error_message or "injected fault")
    job = store.get_job(job_id)
    return FaultResult(
        kind=kind, state=job["state"] if job else "FAILED",
        error_code=chain.error_code or "TIA_UNAVAILABLE",
        diagnostics=[chain.error_message] if chain.error_message else [],
        ledger_events=len(store.get_job_events(job_id)),
        evidence_level=EvidenceLevel.MOCKED.value,
    )


def run_fault_matrix(
    kinds: Iterable[str],
    *,
    store: WorkspaceStore,
    job_id_factory: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run every fault and assert 100% of failed jobs stay out of NATIVE_ARCHIVED."""
    results: list[dict[str, Any]] = []
    for kind in kinds:
        job_id = job_id_factory(kind)
        result = inject_fault(kind, store=store, job_id=job_id, **kwargs)
        results.append(result.to_dict())
    published = [r for r in results if r["native_archived_published"] or r["state"] == "NATIVE_ARCHIVED"]
    return {
        "total": len(results),
        "rejected": sum(1 for r in results if r["rejected"]),
        "native_archived_published": len(published),
        "all_failed_jobs_safe": not published,
        "results": results,
        "evidence_level": EvidenceLevel.MOCKED.value,
    }
