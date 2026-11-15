"""FC-14 tests: commissioning ledger record shape, sha validation (422),
sqlite persistence roundtrip, project filtering/ordering and HTTP routes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.store import ProjectStore
from processos.commissioning import CommissioningLedger, register_routes
from processos.contract import clamp_contract

PROJECT_ID = clamp_contract().id  # PRJ_CLAMP
_ARTIFACT = "a" * 64  # validated shape (hex); value itself is test data, not field evidence


def _store_with_project() -> ProjectStore:
    from processos.contract import ProcessContract
    store = ProjectStore()
    store.create_project(clamp_contract())
    other = clamp_contract().to_dict()
    other["id"] = "PRJ_OTHER"
    store.create_project(ProcessContract.from_dict(other))
    return store


@pytest.fixture()
def env(tmp_path):
    app = FastAPI()
    app.state.store = _store_with_project()
    ledger = CommissioningLedger(tmp_path / "commissioning.sqlite3")
    app.state.commissioning = ledger
    register_routes(app)
    yield TestClient(app), ledger
    ledger.close()  # no-op by design: per-op short-lived connections, no残留句柄


def test_record_via_api_returns_full_record(env):
    client, ledger = env
    resp = client.post("/api/processos/deployments/records", json={
        "project_id": PROJECT_ID, "build_id": "build_219", "artifact_sha256": "sha256:" + _ARTIFACT,
        "device_id": "PLC_1", "operator": "engineer_zhang",
        "plc_checksum": "0x1A2B", "commissioned_at": "2026-11-15T10:00:00+08:00",
        "tests": [{"name": "伸出到位复测", "passed": True, "note": "5 次循环 OK"},
                  {"name": "急停恢复", "passed": True}],
        "result": "COMMISSIONED",
    })
    assert resp.status_code == 200, resp.text
    rec = resp.json()
    assert rec["record_id"].startswith("dep_")
    assert rec["created_at"]  # server-side utcnow stamp
    assert rec["artifact_sha256"] == "sha256:" + _ARTIFACT
    assert rec["tests"][0]["note"] == "5 次循环 OK"
    assert ledger.get(rec["record_id"])["result"] == "COMMISSIONED"


def test_invalid_checksum_rejected_422(env):
    client, ledger = env
    body = {"project_id": PROJECT_ID, "build_id": "build_219", "artifact_sha256": "deadbeef",
            "device_id": "PLC_1", "operator": "engineer_zhang"}
    assert client.post("/api/processos/deployments/records", json=body).status_code == 422
    with pytest.raises(ValueError):
        ledger.record(PROJECT_ID, "build_219", "z" * 64, "PLC_1", "engineer_zhang")
    # 前缀写法但长度不对同样拒绝
    with pytest.raises(ValueError):
        ledger.record(PROJECT_ID, "build_219", "sha256:abc", "PLC_1", "engineer_zhang")


def test_invalid_result_and_tests_rejected(env):
    client, _ = env
    body = {"project_id": PROJECT_ID, "build_id": "build_219", "artifact_sha256": _ARTIFACT,
            "device_id": "PLC_1", "operator": "x", "result": "SHIPPED"}
    assert client.post("/api/processos/deployments/records", json=body).status_code == 422
    body2 = {**body, "result": "FAILED", "tests": [{"name": "t", "passed": "yes"}]}
    assert client.post("/api/processos/deployments/records", json=body2).status_code == 422
    # ROLLED_BACK / FAILED 属合法结果枚举
    ok = {**body, "result": "ROLLED_BACK"}
    assert client.post("/api/processos/deployments/records", json=ok).status_code == 200


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "roundtrip.sqlite3"
    ledger = CommissioningLedger(path)
    ledger.record(PROJECT_ID, "build_219", _ARTIFACT, "PLC_1", "engineer_zhang",
                  commissioned_at="2026-11-15T08:00:00+08:00")
    ledger.record(PROJECT_ID, "build_220", "b" * 64, "PLC_1", "engineer_li",
                  commissioned_at="2026-11-15T09:00:00+08:00")
    ledger.close()
    # “重启”后数据仍在（新服务实例、新连接）
    revived = CommissioningLedger(path)
    recs = revived.records_for(PROJECT_ID)
    assert [r["build_id"] for r in recs] == ["build_219", "build_220"]
    assert revived.get(recs[0]["record_id"])["operator"] == "engineer_zhang"
    revived.close()


def test_records_for_filters_by_project_and_sorts_ascending(env):
    client, _ = env
    other_project = "PRJ_OTHER"
    for ts, pid in [("2026-11-15T09:00:00+08:00", PROJECT_ID),
                    ("2026-11-15T07:00:00+08:00", PROJECT_ID),
                    ("2026-11-15T10:00:00+08:00", other_project)]:
        r = client.post("/api/processos/deployments/records", json={
            "project_id": pid, "build_id": "build_219", "artifact_sha256": _ARTIFACT,
            "device_id": "PLC_1", "operator": "op", "commissioned_at": ts,
        })
        assert r.status_code == 200
    listed = client.get("/api/processos/deployments/records", params={"project_id": PROJECT_ID}).json()
    times = [r["commissioned_at"] for r in listed["records"]]
    assert times == sorted(times) and len(times) == 2  # 升序 + 项目过滤
    other = client.get("/api/processos/deployments/records", params={"project_id": other_project}).json()
    assert len(other["records"]) == 1


def test_unknown_project_404_and_idempotent_registration(env):
    client, _ = env
    body = {"project_id": "PRJ_NOPE", "build_id": "build_219", "artifact_sha256": _ARTIFACT,
            "device_id": "PLC_1", "operator": "x"}
    assert client.post("/api/processos/deployments/records", json=body).status_code == 404
    # register_routes 幂等：重复注册不产生重复路由
    app = client._transport.app  # noqa: SLF001 - test introspection only
    register_routes(app)
    register_routes(app)
    same = [r for r in app.routes if getattr(r, "path", "") == "/api/processos/deployments/records"]
    assert len(same) == 2  # POST + GET 各一条
