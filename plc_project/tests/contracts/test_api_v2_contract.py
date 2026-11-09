"""V2 API contract tests: envelope, 409/422/202, evidence levels, v1 compatibility."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.approval_v2 import ApprovalGate
from gateway.app.services.plc.engineering_service_v2 import EngineeringServiceV2
from gateway.app.services.plc.workspace_v2 import get_store
from tests.v2_fixtures import build_store

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path):
    store = build_store(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client, store
    app.dependency_overrides.clear()


def test_envelope_is_superset_of_v1_and_has_evidence_level(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/v2/projects/prj_demo/ir")
    assert response.status_code == 200
    body = response.json()
    for key in ("ok", "data", "error", "request_id", "code", "message", "evidence_level"):
        assert key in body
    assert body["ok"] is True
    assert body["evidence_level"] == "offline"
    assert body["data"]["schema_version"] == "engineering-ir/2.0"


def test_409_conflict_carries_current_revision(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v2/projects/prj_demo/patches", json={
        "project_id": "prj_demo", "base_revision": 999, "request_id": "req_conflict",
        "ops": [{"op": "set_view_layout", "layout": {}}],
    })
    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["data"]["code"] == "BASE_REVISION_CONFLICT"
    assert body["data"]["current_revision"] == 0


def test_422_carries_issues_and_unchanged_ir_hash(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v2/projects/prj_demo/patches", json={
        "project_id": "prj_demo", "base_revision": 0, "request_id": "req_invalid",
        "ops": [{"op": "unknown_op"}],
    })
    assert response.status_code == 422
    body = response.json()
    assert body["data"]["code"] == "SEMANTIC_VALIDATION_FAILED"
    assert body["data"]["issues"]
    assert body["data"]["unchanged_ir_hash"].startswith("sha256:")


def test_patch_200_returns_revision_and_derived(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v2/projects/prj_demo/patches", json={
        "project_id": "prj_demo", "base_revision": 0, "request_id": "req_ok",
        "ops": [{"op": "set_step_parameter", "step_id": "S2", "field": "min_duration_ms", "value": 2000}],
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["revision"] == 1
    assert data["changed_ir_ids"] == ["S2"]
    assert data["ir_sha256"].startswith("sha256:")
    assert data["derived"]["manifest_sha256"].startswith("sha256:")


def test_delivery_is_202_queued_and_stays_pending_real_machine(client) -> None:
    test_client, store = client
    changeset = EngineeringServiceV2.freeze_changeset(store, "prj_demo", base_revision=0)
    baseline = store.get_project("prj_demo").baseline_hash
    ApprovalGate(store).approve(changeset.id, reviewer="qa_human", explicit=True,
                                expected_baseline_hash=baseline)
    payload = {
        "project_id": "prj_demo", "base_revision": 0, "request_id": "req_deliver",
        "approved_changeset_id": changeset.id, "expected_baseline_hash": baseline,
        "idempotency_key": "delivery-prj_demo-v0", "artifact_type": "native_tia_archive",
        "tia_version": "V19",
    }
    first = test_client.post("/api/v2/projects/prj_demo/deliveries", json=payload)
    assert first.status_code == 202
    data = first.json()["data"]
    assert data["state"] == "QUEUED"
    assert data["artifact_id"] is None
    assert data["evidence_level"] == "pending_real_machine"

    second = test_client.post("/api/v2/projects/prj_demo/deliveries", json=payload)
    assert second.status_code == 202
    assert second.json()["data"]["job_id"] == data["job_id"]  # idempotent

    job = test_client.get(f"/api/v2/delivery-jobs/{data['job_id']}").json()["data"]
    assert job["state"] == "QUEUED"
    assert job["native_artifact"] is None
    assert job["evidence_level"] == "pending_real_machine"
    assert job["state"] == "QUEUED"
    assert job["native_artifact"] is None
    assert "NATIVE_ARCHIVED" not in json.dumps(job)


def test_unapproved_delivery_is_403(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v2/projects/prj_demo/deliveries", json={
        "project_id": "prj_demo", "base_revision": 0, "request_id": "req_no_approval",
        "approved_changeset_id": "cs_missing", "expected_baseline_hash": "",
        "idempotency_key": "k2", "artifact_type": "native_tia_archive", "tia_version": "V19",
    })
    assert response.status_code == 403
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "CHANGESET_NOT_APPROVED"


def test_v1_routes_are_still_registered(client) -> None:
    test_client, _ = client
    root = test_client.get("/")
    assert root.status_code == 200
    assert "/api/v1/plc/jobs" in root.json()["plc_api"]
    # app.routes may contain lazy _IncludedRouter wrappers, so the generated
    # OpenAPI document is the authoritative registry check.
    paths = set(app.openapi()["paths"])
    assert any(path.startswith("/api/v1/plc/canvas/greenfield") for path in paths)
    assert any(path.startswith("/api/v2/") for path in paths)


def test_openapi_contract_has_all_v2_paths() -> None:
    schema = json.loads((REPO / "docs/v2/contracts/api_v2.openapi.json").read_text(encoding="utf-8"))
    paths = schema["paths"]
    assert len(paths) >= 18
    for expected in ("/api/v2/projects", "/api/v2/projects/{project_id}/patches",
                     "/api/v2/projects/{project_id}/deliveries",
                     "/api/v2/artifacts/{artifact_id}/download", "/api/v2/capability"):
        assert expected in paths


def test_source_package_is_explicitly_not_native(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/v2/projects/prj_demo/source-package")
    assert response.status_code == 200
    assert response.headers["X-Artifact-Kind"] == "source_import_package_not_native"
    assert response.headers["X-Evidence-Level"] == "offline"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        notice = archive.read("NOTICE.txt").decode("utf-8")
        assert "非原生工程" in notice
        assert "SOURCE_READY != NATIVE_ARCHIVED" in notice
        assert any(name.endswith(".scl") for name in archive.namelist())


def test_brownfield_placeholders_reject_writes_and_stay_mocked(client) -> None:
    test_client, _ = client
    forbidden = test_client.post("/api/v2/projects/prj_demo/brownfield/diffplan", json={
        "project_id": "prj_demo", "base_revision": 0, "request_id": "req_bf1",
        "ops": [{"op": "write_f_block", "source_id": "FB_Safety"}],
    })
    assert forbidden.status_code == 403
    assert forbidden.json()["evidence_level"] == "mocked"

    placeholder = test_client.post("/api/v2/projects/prj_demo/brownfield/diffplan", json={
        "project_id": "prj_demo", "base_revision": 0, "request_id": "req_bf2",
        "ops": [{"op": "inspect", "source_id": "FB_Motor"}],
        "source_bindings": [{"source_id": "FB_Motor", "block_type": "FB", "writable": "requires_review"}],
    })
    assert placeholder.status_code == 200
    data = placeholder.json()["data"]
    assert data["executable"] is False
    assert data["evidence_level"] == "mocked"


def test_capability_endpoint_shape(client) -> None:
    test_client, store = client
    # Deterministic offline probe injection (no real machine in contract tests).
    from plc_engine.engineering_ir.evidence import EvidenceLevel
    from plc_engine.engineering_ir.models import TiaCapabilityManifest

    manifest = TiaCapabilityManifest(
        probe_receipt_id="g0_contract", tia_version="V19",
        cpu_templates=[{"type_identifier": "6ES7511-1AK02-0AB0/V2.9",
                        "verified_create_with_item": False, "catalog_source": "static"}],
        evidence_level=EvidenceLevel.PENDING_REAL_MACHINE,
        raw_probe_receipt={"probe": {"ok": False}},
    )
    store.save_capability_probe(manifest)
    body = test_client.get("/api/v2/capability").json()
    assert body["ok"] is True
    assert body["data"]["evidence_level"] == "pending_real_machine"
    assert body["data"]["candidate_cpu_templates"]
