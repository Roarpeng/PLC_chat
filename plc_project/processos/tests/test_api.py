"""WS4 API integration tests — full HTTP flow with human-gated delivery."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.contract import clamp_contract


@pytest.fixture()
def client():
    return TestClient(create_app(ProjectStore()))


def _create(client):
    r = client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    assert r.status_code == 200, r.text
    return r.json()["project_id"]


def test_create_and_get(client):
    pid = _create(client)
    r = client.get(f"/api/processos/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["revision"] == 1
    assert r.json()["contract"]["id"] == pid


def test_frameworks_listed(client):
    _create(client)
    r = client.get("/api/processos/frameworks")
    assert r.status_code == 200
    assert any(p["tia_version"] == "V19" for p in r.json()["profiles"])


def test_patch_bumps_revision(client):
    pid = _create(client)
    r = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 1, "request_id": "r1",
        "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_HOLD/duration_ms", "value": 4000}],
    })
    assert r.status_code == 200
    assert r.json()["revision"] == 2


def test_patch_conflict_409(client):
    pid = _create(client)
    r = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 99, "ops": [{"op": "set", "path": "/name", "value": "x"}],
    })
    assert r.status_code == 409


def test_patch_invalid_422(client):
    pid = _create(client)
    r = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 1,
        "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/entry",
                 "value": [{"target": "CM_CLAMP_CYL", "command": "Bogus", "value": True}]}],
    })
    assert r.status_code == 422


def test_validate_simulate_generate(client):
    pid = _create(client)
    assert client.post(f"/api/processos/projects/{pid}/validate").json()["errors"] == []
    sim = client.post(f"/api/processos/projects/{pid}/simulate").json()
    assert sim["all_passed"]
    gen = client.post(f"/api/processos/projects/{pid}/generate").json()
    assert gen["coverage_assertions_passed"]


def test_delivery_blocked_without_approval(client):
    pid = _create(client)
    gate = client.get(f"/api/processos/projects/{pid}/delivery-gate").json()
    assert not gate["ready"]
    r = client.post(f"/api/processos/projects/{pid}/deliveries")
    assert r.status_code == 403


def test_blocking_question_blocks_delivery(client):
    pid = _create(client)
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve", json={"by": "工程师"})
    gate = client.get(f"/api/processos/projects/{pid}/delivery-gate").json()
    assert not gate["checks"]["no_blocking_questions"]
    assert not gate["ready"]


def test_full_approval_flow_unblocks_delivery(client):
    pid = _create(client)
    client.post(f"/api/processos/projects/{pid}/questions/Q_SAFETY_STOP/resolve",
                json={"resolution": "许可撤销时保持原位", "by": "工程师张三"})
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    ap = client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve", json={"by": "工程师张三"})
    assert ap.status_code == 200
    gate = client.get(f"/api/processos/projects/{pid}/delivery-gate").json()
    assert gate["ready"], gate
    job = client.post(f"/api/processos/projects/{pid}/deliveries")
    assert job.status_code == 200
    assert job.json()["status"] == "QUEUED"


def test_approval_stale_after_patch(client):
    pid = _create(client)
    client.post(f"/api/processos/projects/{pid}/questions/Q_SAFETY_STOP/resolve",
                json={"resolution": "保持", "by": "工程师"})
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 1, "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_HOLD/duration_ms", "value": 5000}],
    })
    r = client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve", json={"by": "工程师"})
    assert r.status_code == 403


def test_passport_records_chain(client):
    pid = _create(client)
    client.post(f"/api/processos/projects/{pid}/validate")
    client.post(f"/api/processos/projects/{pid}/simulate")
    pp = client.get(f"/api/processos/projects/{pid}/passport").json()
    kinds = {e["kind"] for e in pp["entries"]}
    assert {"validation", "simulation"} <= kinds


def test_unknown_project_404(client):
    assert client.get("/api/processos/projects/NOPE").status_code == 404