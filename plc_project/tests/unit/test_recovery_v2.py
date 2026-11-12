"""WP-06: worker-crash recovery, ledger retention, no blind replay."""
from __future__ import annotations

from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.fault_injection_v2 import inject_fault, rollback_plan
from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine.engineering_ir.contracts import can_transition
from tests.v2_fixtures import build_valid_demo_ir, make_fake_openness_worker


def setup_job(tmp_path, name: str = "job_recover") -> tuple[WorkspaceStore, str]:
    store = WorkspaceStore(db_path=str(tmp_path / "rec.db"), ir_store_dir=str(tmp_path / "ir"))
    store.insert_job(name, project_id="prj_rec", changeset_id="cs_rec",
                     idempotency_key=f"idem_{name}", expected_baseline_hash="sha256:base")
    return store, name


def test_worker_crash_leaves_recovery_required_with_ledger(tmp_path) -> None:
    store, jid = setup_job(tmp_path)
    worker, _ = make_fake_openness_worker(tmp_path)
    result = inject_fault("worker_crash", store=store, job_id=jid,
                          ir=build_valid_demo_ir("prj_rec"), worker=worker,
                          workspace_dir=str(tmp_path / "ws"))
    assert result.state == "RECOVERY_REQUIRED"
    events = store.get_job_events(jid)
    assert any(e["state"] == "RECOVERY_REQUIRED" and e["stage"] == "COMPILE" for e in events)
    assert result.native_archived_published is False


def test_recovery_plan_must_not_blindly_replay_non_idempotent_writes(tmp_path) -> None:
    store, jid = setup_job(tmp_path)
    worker, _ = make_fake_openness_worker(tmp_path)
    inject_fault("worker_crash", store=store, job_id=jid,
                 ir=build_valid_demo_ir("prj_rec"), worker=worker,
                 workspace_dir=str(tmp_path / "ws"))
    plan = DeliveryCoordinator(store).recover(jid)
    assert plan["native_archived_published"] is False
    assert "resume from stage cursor" in " ".join(plan["plan"]).lower()
    rollback = rollback_plan(store, jid)
    assert any("without replaying" in step for step in rollback["rollback_strategy"])
    assert rollback["evidence_level"] == "offline"


def test_failed_job_retains_full_evidence(tmp_path) -> None:
    store, jid = setup_job(tmp_path, "job_failed")
    worker, _ = make_fake_openness_worker(tmp_path, archive_ok=False)
    inject_fault("archive_missing", store=store, job_id=jid,
                 ir=build_valid_demo_ir("prj_rec"), worker=worker,
                 workspace_dir=str(tmp_path / "ws"))
    events = store.get_job_events(jid)
    assert any(e["state"] == "FAILED" for e in events)
    assert store.get_job(jid)["state"] == "FAILED"
    assert store.get_artifact("a_anything") is None


def test_state_machine_allows_resume_from_recovery() -> None:
    assert can_transition("TIA_IMPORTED", "RECOVERY_REQUIRED") is True
    assert can_transition("TIA_COMPILED", "RECOVERY_REQUIRED") is True
    assert can_transition("RECOVERY_REQUIRED", "TIA_IMPORTED") is True
    assert can_transition("FAILED", "NATIVE_ARCHIVED") is False
    assert can_transition("RECOVERY_REQUIRED", "NATIVE_ARCHIVED") is False


def test_recovery_never_publishes_native_artifact(tmp_path) -> None:
    store, jid = setup_job(tmp_path, "job_rec2")
    worker, _ = make_fake_openness_worker(tmp_path)
    inject_fault("worker_crash", store=store, job_id=jid,
                 ir=build_valid_demo_ir("prj_rec"), worker=worker,
                 workspace_dir=str(tmp_path / "ws"))
    job_view = DeliveryCoordinator(store).get_job(jid)
    assert job_view["state"] != "NATIVE_ARCHIVED"
    assert job_view["native_artifact"] is None
    assert job_view["evidence_level"] != "V19_real"
