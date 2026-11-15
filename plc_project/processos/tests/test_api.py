"""WS4 API integration tests — full HTTP flow with human-gated delivery.

Approval and delivery endpoints are RBAC-gated (PLAN §7): tests send the
X-Actor-Id / X-Actor-Role headers — this is the intended contract tightening.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.contract import clamp_contract

REVIEWER = {"X-Actor-Id": "reviewer_wang", "X-Actor-Role": "Reviewer"}
BUILDER = {"X-Actor-Id": "builder_li", "X-Actor-Role": "Builder"}


@pytest.fixture()
def client(tmp_path):
    # tmp db: the audit ledger / baselines never touch the default store path
    return TestClient(create_app(ProjectStore(), db=tmp_path / "api.sqlite3"))


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
    r = client.post(f"/api/processos/projects/{pid}/deliveries", headers=BUILDER)
    assert r.status_code == 403


def test_delivery_requires_builder_role(client):
    pid = _create(client)
    r = client.post(f"/api/processos/projects/{pid}/deliveries")  # no actor headers
    assert r.status_code == 403
    assert r.json()["code"] == "ROLE_FORBIDDEN"


def test_approve_requires_reviewer_role_and_separation(client):
    pid = _create(client)
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    url = f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve"
    r = client.post(url, json={"by": "工程师张三"})  # no actor headers -> Viewer
    assert r.status_code == 403
    assert r.json()["code"] == "ROLE_FORBIDDEN"
    # approver identity (header) must differ from the modifier (body.by)
    same = client.post(url, headers=REVIEWER | {"X-Actor-Id": "eng_zhao"},
                       json={"by": "eng_zhao"})
    assert same.status_code == 403
    assert same.json()["code"] == "APPROVER_SEPARATION"


def test_blocking_question_blocks_delivery(client):
    pid = _create(client)
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve",
                headers=REVIEWER, json={"by": "工程师"})
    gate = client.get(f"/api/processos/projects/{pid}/delivery-gate").json()
    assert not gate["checks"]["no_blocking_questions"]
    assert not gate["ready"]


def test_full_approval_flow_unblocks_delivery(client):
    pid = _create(client)
    client.post(f"/api/processos/projects/{pid}/questions/Q_SAFETY_STOP/resolve",
                json={"resolution": "许可撤销时保持原位", "by": "工程师张三"})
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    ap = client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve",
                     headers=REVIEWER, json={"by": "工程师张三"})
    assert ap.status_code == 200
    gate = client.get(f"/api/processos/projects/{pid}/delivery-gate").json()
    assert gate["ready"], gate
    job = client.post(f"/api/processos/projects/{pid}/deliveries", headers=BUILDER)
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
    r = client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve",
                    headers=REVIEWER, json={"by": "工程师"})
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