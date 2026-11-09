"""Q-06 / G7: Retrieve/reopen is mandatory; failures never publish NATIVE_ARCHIVED."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.approval_v2 import ApprovalGate
from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.engineering_service_v2 import EngineeringServiceV2
from gateway.app.services.plc.tia_delivery_v2 import DeliveryChainRequest, TiaOpennessCliAdapter
from gateway.app.services.plc.workspace_v2 import get_store
from plc_engine.engineering_ir.evidence import EvidenceLevel
from tests.v2_fixtures import build_store, make_fake_openness_worker as make_worker


def prepared(tmp_path):
    """Store with a valid project + an approved ChangeSet + a queued job."""
    store = build_store(tmp_path)
    changeset = EngineeringServiceV2.freeze_changeset(store, "prj_demo", base_revision=0)
    baseline = store.get_project("prj_demo").baseline_hash
    ApprovalGate(store).approve(changeset.id, reviewer="qa_human", explicit=True,
                                expected_baseline_hash=baseline)
    data, status = DeliveryCoordinator(store).start({
        "project_id": "prj_demo", "approved_changeset_id": changeset.id,
        "expected_baseline_hash": baseline, "idempotency_key": "idem_chain_1",
    })
    assert status == 202
    return store, data["job_id"]


def chain_request(tmp_path, job_id: str) -> DeliveryChainRequest:
    return DeliveryChainRequest(
        project_id="prj_demo", job_id=job_id, project_name="Demo",
        workspace_dir=str(tmp_path / "ws"),
        cpu_type_identifier="6ES7511-1AK02-0AB0/V2.9", archive_name="Demo.zap19",
    )


def test_reopen_failure_keeps_job_failed_and_no_artifact(tmp_path) -> None:
    store, job_id = prepared(tmp_path)
    worker, _ = make_worker(tmp_path, reopen_ok=False)
    result = DeliveryCoordinator(store).run_chain(
        job_id, adapter=TiaOpennessCliAdapter(worker=worker, real_machine=True),
        request=chain_request(tmp_path, job_id),
    )
    assert result["state"] == "FAILED"
    assert result["error_code"] == "REOPEN_FAILED"
    job = DeliveryCoordinator(store).get_job(job_id)
    assert job["state"] == "FAILED"
    assert job["native_artifact"] is None
    assert job["evidence_level"] != EvidenceLevel.V19_REAL.value
    assert store.get_artifact("a_anything") is None


def test_compile_failure_never_reaches_native_archived(tmp_path) -> None:
    store, job_id = prepared(tmp_path)
    worker, _ = make_worker(tmp_path, error_count=2, warning_count=5)
    result = DeliveryCoordinator(store).run_chain(
        job_id, adapter=TiaOpennessCliAdapter(worker=worker, real_machine=True),
        request=chain_request(tmp_path, job_id),
    )
    assert result["state"] == "FAILED"
    assert result["error_code"] == "COMPILE_FAILED"
    assert store.get_job(job_id)["state"] == "FAILED"
    assert not any(e["state"] == "NATIVE_ARCHIVED" for e in store.get_job_events(job_id))


def test_mocked_chain_publishes_no_downloadable_artifact(tmp_path) -> None:
    store, job_id = prepared(tmp_path)
    worker, _ = make_worker(tmp_path)
    result = DeliveryCoordinator(store).run_chain(
        job_id, adapter=TiaOpennessCliAdapter(worker=worker),  # real_machine=False
        request=chain_request(tmp_path, job_id),
    )
    assert result["state"] == "TIA_COMPILED"
    assert result["evidence_level"] == "mocked"
    assert result["artifact"] is None
    assert DeliveryCoordinator(store).get_job(job_id)["native_artifact"] is None
    events = store.get_job_events(job_id)
    assert any(e["stage"] == "MOCKED_CHAIN_OK" for e in events)


def test_real_receipt_chain_publishes_native_artifact(tmp_path) -> None:
    """Orchestration contract with an explicitly real adapter; NOT a real TIA run."""
    store, job_id = prepared(tmp_path)
    worker, archive = make_worker(tmp_path)
    result = DeliveryCoordinator(store).run_chain(
        job_id, adapter=TiaOpennessCliAdapter(worker=worker, real_machine=True,
                                              evidence_level=EvidenceLevel.V19_REAL),
        request=chain_request(tmp_path, job_id),
    )
    assert result["state"] == "NATIVE_ARCHIVED"
    assert result["evidence_level"] == "V19_real"
    job = DeliveryCoordinator(store).get_job(job_id)
    assert job["native_artifact"]["reopen_ok"] is True
    assert job["compile"]["error_count"] == 0
    assert job["compile"]["warning_count"] == 2  # warnings listed separately, not folded in
    assert job["evidence_id"].startswith("ev_")
    assert store.get_artifact(result["artifact"]["artifact_id"]) is not None


def test_duplicate_delivery_request_is_idempotent(tmp_path) -> None:
    store, job_id = prepared(tmp_path)
    coordinator = DeliveryCoordinator(store)
    baseline = store.get_project("prj_demo").baseline_hash
    # Re-issue the SAME idempotency key through the coordinator start().
    again, status = coordinator.start({
        "project_id": "prj_demo",
        "approved_changeset_id": _approved_changeset_id(store),
        "expected_baseline_hash": baseline, "idempotency_key": "idem_chain_1",
    })
    assert status == 202
    assert again["job_id"] == job_id
    assert again["idempotent_hit"] is True


def _approved_changeset_id(store):
    # Changesets are keyed by id; find the approved one through the approvals table.
    with store._lock:
        rows = store._conn.execute("SELECT changeset_id FROM approvals ORDER BY signed_at DESC LIMIT 1").fetchall()
    assert rows, "expected an approved changeset"
    return str(rows[0]["changeset_id"])


def test_failed_job_download_is_404(tmp_path) -> None:
    store, job_id = prepared(tmp_path)
    worker, _ = make_worker(tmp_path, archive_ok=False)
    DeliveryCoordinator(store).run_chain(
        job_id, adapter=TiaOpennessCliAdapter(worker=worker, real_machine=True),
        request=chain_request(tmp_path, job_id),
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            response = client.get("/api/v2/artifacts/a_1/download",
                                  params={"project_id": "prj_demo", "job_id": job_id})
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
            job_body = client.get(f"/api/v2/delivery-jobs/{job_id}").json()["data"]
            assert job_body["state"] == "FAILED"
            assert job_body["native_artifact"] is None
            assert job_body["evidence_level"] != "V19_real"
            assert "NATIVE_ARCHIVED" not in json.dumps(job_body)
    finally:
        app.dependency_overrides.clear()


def test_recovery_plan_does_not_blindly_replay(tmp_path) -> None:
    store, job_id = prepared(tmp_path)
    worker, _ = make_worker(tmp_path, reopen_ok=False)
    DeliveryCoordinator(store).run_chain(
        job_id, adapter=TiaOpennessCliAdapter(worker=worker),
        request=chain_request(tmp_path, job_id),
    )
    plan = DeliveryCoordinator(store).recover(job_id)
    assert plan["native_archived_published"] is False
    assert "resume from stage cursor" in " ".join(plan["plan"]).lower()
    assert plan["evidence_level"] == "offline"
