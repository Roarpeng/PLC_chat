"""G7 / WP-06: >=10 fault classes, 100% failed jobs stay out of NATIVE_ARCHIVED."""
from __future__ import annotations

from pathlib import Path

from gateway.app.services.plc.fault_injection_v2 import (
    FAULT_KINDS,
    inject_fault,
    run_fault_matrix,
)
from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine.changeplan import SourceBinding
from plc_engine.engineering_ir.evidence import EvidenceLevel
from tests.v2_fixtures import build_valid_demo_ir, make_fake_openness_worker

BINDINGS = [
    {"source_id": "FB_Motor", "referenced_by": ["OB_Main"], "writable": "requires_review", "fidelity": "parsed"},
    {"source_id": "FB_Safety", "block_type": "F", "writable": "requires_review", "fidelity": "protected"},
]


def make_store(tmp_path: Path) -> WorkspaceStore:
    store = WorkspaceStore(db_path=str(tmp_path / "fault.db"), ir_store_dir=str(tmp_path / "ir"))
    return store


def create_job(store: WorkspaceStore, job_id: str) -> str:
    store.insert_job(job_id, project_id="prj_fault", changeset_id="cs_fault",
                     idempotency_key=f"idem_{job_id}", expected_baseline_hash="sha256:base")
    return job_id


def test_at_least_ten_fault_kinds_are_declared() -> None:
    assert len(FAULT_KINDS) >= 10


def test_full_fault_matrix_never_publishes_native_archived(tmp_path) -> None:
    from pathlib import Path
    store = make_store(tmp_path)
    kinds = [k for k in FAULT_KINDS if k != "duplicate_request"]
    worker, _ = make_fake_openness_worker(tmp_path, error_count=0)
    job_ids: dict[str, str] = {}

    def factory(kind: str) -> str:
        jid = create_job(store, f"job_{kind}")
        job_ids[kind] = jid
        return jid

    matrix = run_fault_matrix(
        kinds, store=store, job_id_factory=factory,
        ir=build_valid_demo_ir("prj_fault"),
        bindings=[SourceBinding.from_dict(b) for b in BINDINGS],
        worker=worker,
        workspace_dir=str(tmp_path / "ws"),
    )
    assert matrix["total"] == len(kinds) >= 10
    assert matrix["all_failed_jobs_safe"] is True
    assert matrix["native_archived_published"] == 0
    for item in matrix["results"]:
        assert item["rejected"] is True, item
        assert item["state"] != "NATIVE_ARCHIVED", item
        assert item["native_archived_published"] is False
        assert item["evidence_level"] != EvidenceLevel.V19_REAL.value
    for kind, jid in job_ids.items():
        state = store.get_job(jid)["state"]
        assert state in ("FAILED", "RECOVERY_REQUIRED"), (kind, state)
        assert any(e["state"] in ("FAILED", "RECOVERY_REQUIRED") for e in store.get_job_events(jid))


def test_compile_failure_keeps_evidence_and_no_artifact(tmp_path) -> None:
    from pathlib import Path
    store = make_store(tmp_path)
    jid = create_job(store, "job_compile")
    worker, _ = make_fake_openness_worker(tmp_path, error_count=3)
    result = inject_fault("compile_failed", store=store, job_id=jid,
                          ir=build_valid_demo_ir("prj_fault"), worker=worker,
                          workspace_dir=str(tmp_path / "ws"))
    assert result.state == "FAILED"
    assert result.native_archived_published is False
    assert result.ledger_events >= 1
    assert store.get_job(jid)["state"] == "FAILED"


def test_worker_crash_enters_recovery_required(tmp_path) -> None:
    from pathlib import Path
    store = make_store(tmp_path)
    jid = create_job(store, "job_crash")
    worker, _ = make_fake_openness_worker(tmp_path)
    result = inject_fault("worker_crash", store=store, job_id=jid,
                          ir=build_valid_demo_ir("prj_fault"), worker=worker,
                          workspace_dir=str(tmp_path / "ws"))
    assert result.state == "RECOVERY_REQUIRED"
    assert result.native_archived_published is False


def test_tia_unavailable_without_worker_is_offline_fail_closed(tmp_path) -> None:
    from pathlib import Path
    store = make_store(tmp_path)
    jid = create_job(store, "job_tia")
    result = inject_fault("tia_unavailable", store=store, job_id=jid,
                          ir=build_valid_demo_ir("prj_fault"))
    assert result.error_code in ("TIA_UNAVAILABLE", "CPU_TEMPLATE_NOT_SELECTED", "REOPEN_FAILED")
    assert result.native_archived_published is False
    assert result.evidence_level == "mocked"


def test_bad_xml_and_bad_zip_are_rejected() -> None:
    from gateway.app.services.plc.fault_injection_v2 import reject_bad_xml, reject_bad_zip
    ok, why = reject_bad_xml(b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>")
    assert ok is False and "BAD_XML" in why
    ok2, _ = reject_bad_xml(b"<root><a>1</a></root>")
    assert ok2 is True
    bad, why2 = reject_bad_zip("__nonexistent__.zip")
    assert bad is False and "BAD_ZIP" in why2
