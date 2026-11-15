"""FC-18 tests: fail-closed SiteDeploymentGateway — full precheck condition
matrix, execute gating (no confirm -> 403, no backend -> 501, fake backend ->
only then success with precheck binding), HTTP routes, and the explicit
absence of any one-click online path (PLAN 5.3)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.commissioning import CommissioningLedger, register_routes as register_commissioning
from processos.contract import clamp_contract
from processos.deployment import PrecheckNotFound, SiteDeploymentGateway, register_routes
from processos.safety.errors import SafetyError

PROJECT_ID = clamp_contract().id  # PRJ_CLAMP
_ARTIFACT = "c" * 64


class FakeBackend:
    """Test-only execution backend: records the precheck it was handed."""

    name = "fake_backend"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, precheck: dict) -> dict:
        self.calls.append(precheck)
        return {"downloaded": True, "online_compare_repeat": True, "receipt": "RCT-1"}


@pytest.fixture()
def env(tmp_path):
    app = FastAPI()
    ledger = CommissioningLedger(tmp_path / "commissioning.sqlite3")
    app.state.commissioning = ledger
    app.state.deploy_gateway = SiteDeploymentGateway(
        commissioning=ledger, db=tmp_path / "deployment.sqlite3")
    register_commissioning(app)
    register_routes(app)
    yield TestClient(app), app.state.deploy_gateway, ledger
    ledger.close()
    app.state.deploy_gateway.close()


def _commissioned(ledger: CommissioningLedger, build_id: str = "build_219") -> None:
    rec = ledger.record(PROJECT_ID, build_id, _ARTIFACT, "PLC_1", "engineer_zhang")
    assert rec["result"] == "COMMISSIONED"


def _full_kwargs() -> dict:
    return {
        "online_compare": {"match": True, "mode": "online_compare"},
        "retain_assessment": {"retain_risk": "none", "reviewed_by": "process_owner"},
        "second_person": "reviewer_wang",
        "rollback_plan": {"artifact": "build_218.zap19", "steps": ["re-download", "verify"]},
        "authorized_window": True,
    }


def test_precheck_with_all_conditions_missing_fails_closed(env):
    client, gw, ledger = env
    resp = client.post("/api/processos/deployments/gateway/precheck", json={
        "project_id": PROJECT_ID, "build_id": "build_219", "device_id": "PLC_1", "window": ""})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["ready"] is False
    assert out["precheck_id"].startswith("dgp_")
    assert set(out["missing"]) == {
        "AUTHORIZED_WINDOW", "ONLINE_COMPARE", "RETAIN_ASSESSMENT",
        "SECOND_PERSON", "ROLLBACK_PLAN", "COMMISSIONING_RECORD",
    }
    assert "UNKNOWN_PLC_STATE" in out["blocked_by"] and "RETAIN_DATA_RISK" in out["blocked_by"]
    assert "DRIFT_DETECTED" in out["blocked_by"]  # 有台账但无投产记录 -> 漂移阻断
    assert out["one_click_online"] is False  # 无网页一键上线
    assert gw.get_precheck(out["precheck_id"]) is not None  # precheck 已落库


def test_precheck_ready_when_all_conditions_satisfied(env):
    client, gw, ledger = env
    _commissioned(ledger)
    out = client.post("/api/processos/deployments/gateway/precheck", json={
        "project_id": PROJECT_ID, "build_id": "build_219", "device_id": "PLC_1",
        "window": "2026-11-16 02:00-04:00 停机窗口", **_full_kwargs()}).json()
    assert out["ready"] is True
    assert out["missing"] == [] and out["blocked_by"] == []
    assert set(out["satisfied"]) == {
        "AUTHORIZED_WINDOW", "ONLINE_COMPARE", "RETAIN_ASSESSMENT",
        "SECOND_PERSON", "ROLLBACK_PLAN", "COMMISSIONING_RECORD",
    }


def test_execute_without_confirm_blocked_403(env):
    client, gw, ledger = env
    _commissioned(ledger)
    pc = client.post("/api/processos/deployments/gateway/precheck", json={
        "project_id": PROJECT_ID, "build_id": "build_219", "device_id": "PLC_1",
        "window": "w", **_full_kwargs()}).json()
    resp = client.post("/api/processos/deployments/gateway/execute",
                       json={"precheck_id": pc["precheck_id"], "confirm": False, "actor": "zhang"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "SAFETY_SCOPE_BLOCKED"
    # 服务层同样 fail-closed
    with pytest.raises(SafetyError) as err:
        gw.execute(pc["precheck_id"])
    assert err.value.code == "SAFETY_SCOPE_BLOCKED" and err.value.http_status == 403


def test_execute_with_confirm_but_no_backend_blocked_501(env):
    client, _, ledger = env
    _commissioned(ledger)
    pc = client.post("/api/processos/deployments/gateway/precheck", json={
        "project_id": PROJECT_ID, "build_id": "build_219", "device_id": "PLC_1",
        "window": "w", **_full_kwargs()}).json()
    resp = client.post("/api/processos/deployments/gateway/execute",
                       json={"precheck_id": pc["precheck_id"], "confirm": True, "actor": "zhang"})
    assert resp.status_code == 501
    assert resp.json()["code"] == "SAFETY_SCOPE_BLOCKED"
    assert "人工流程" in resp.json()["error"]


def test_execute_not_ready_precheck_blocked_with_details(env):
    client, _, _ = env
    pc = client.post("/api/processos/deployments/gateway/precheck", json={
        "project_id": PROJECT_ID, "build_id": "build_219", "device_id": "PLC_1",
        "window": "w"}).json()
    resp = client.post("/api/processos/deployments/gateway/execute",
                       json={"precheck_id": pc["precheck_id"], "confirm": True})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "SAFETY_SCOPE_BLOCKED"
    assert body["details"]["missing"] == pc["missing"]


def test_execute_unknown_precheck_404(env):
    client, gw, _ = env
    resp = client.post("/api/processos/deployments/gateway/execute",
                       json={"precheck_id": "dgp_nope", "confirm": True})
    assert resp.status_code == 404
    with pytest.raises(PrecheckNotFound):
        gw.execute("dgp_nope", confirm=True)


def test_execute_with_fake_backend_succeeds_and_binds_precheck(tmp_path):
    ledger = CommissioningLedger(tmp_path / "backend_comm.sqlite3")
    backend = FakeBackend()
    gw = SiteDeploymentGateway(backend, commissioning=ledger, db=tmp_path / "backend_gw.sqlite3")
    try:
        _commissioned(ledger)
        pc = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "night window", **_full_kwargs())
        assert pc["ready"] is True
        receipt = gw.execute(pc["precheck_id"], confirm=True, actor="engineer_zhang")
        assert receipt["precheck_id"] == pc["precheck_id"]
        assert receipt["result"]["downloaded"] is True
        assert gw.executions_for(pc["precheck_id"])[0]["actor"] == "engineer_zhang"
        # fake backend 只被调用一次，且收到的正是绑定的 precheck（含 precheck_id）
        assert len(backend.calls) == 1
        assert backend.calls[0]["precheck_id"] == pc["precheck_id"]
        assert backend.calls[0]["build_id"] == "build_219"
    finally:
        gw.close()
        ledger.close()


def test_build_without_commissioned_record_blocks_with_drift(tmp_path):
    ledger = CommissioningLedger(tmp_path / "drift_comm.sqlite3")
    gw = SiteDeploymentGateway(commissioning=ledger, db=tmp_path / "drift_gw.sqlite3")
    try:
        ledger.record(PROJECT_ID, "build_219", _ARTIFACT, "PLC_1", "engineer_zhang",
                      result="FAILED")  # 有记录但未 COMMISSIONED
        out = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "w", **_full_kwargs())
        assert out["ready"] is False
        assert "COMMISSIONING_RECORD" in out["missing"]
        assert "DRIFT_DETECTED" in out["blocked_by"]
    finally:
        gw.close()
        ledger.close()


def test_no_commissioning_and_no_baseline_means_unknown_plc_state(tmp_path):
    gw = SiteDeploymentGateway(db=tmp_path / "bare.sqlite3")  # 裸网关：无台账、无 baseline、无后端
    try:
        out = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "w", **_full_kwargs())
        assert out["missing"] == ["COMMISSIONING_RECORD"]
        assert out["blocked_by"] == ["UNKNOWN_PLC_STATE"]  # 状态未知，不猜
        assert out["ready"] is False
    finally:
        gw.close()


def test_baseline_provider_plc_state_known_used_when_no_ledger(tmp_path):
    class BP:
        def plc_state_known(self, project_id: str, build_id: str):
            return (project_id, build_id) == (PROJECT_ID, "build_219")

    gw = SiteDeploymentGateway(baseline_provider=BP(), db=tmp_path / "bp.sqlite3")
    try:
        ok = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "w", **_full_kwargs())
        assert ok["ready"] is True  # plc_state_known=True 视作 B3 证据
        bad = gw.precheck(PROJECT_ID, "build_999", "PLC_1", "w", **_full_kwargs())
        assert bad["blocked_by"] == ["UNKNOWN_PLC_STATE"]  # 未证实的状态 -> 未知，不虚构漂移
    finally:
        gw.close()


def test_gateway_persistence_roundtrip(tmp_path):
    path = tmp_path / "gw_roundtrip.sqlite3"
    ledger = CommissioningLedger(tmp_path / "gw_roundtrip_comm.sqlite3")
    gw = SiteDeploymentGateway(commissioning=ledger, db=path)
    _commissioned(ledger)
    pc = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "w", **_full_kwargs())
    gw.close()
    ledger.close()
    # “重启”后 precheck 仍在
    gw2 = SiteDeploymentGateway(commissioning=CommissioningLedger(tmp_path / "gw_roundtrip_comm.sqlite3"),
                                db=path)
    try:
        revived = gw2.get_precheck(pc["precheck_id"])
        assert revived is not None and revived["ready"] is True
        assert revived["build_id"] == "build_219"
    finally:
        gw2.close()
        gw2.commissioning.close()


def test_duck_typed_bridge_to_real_baseline_service(tmp_path):
    """集成兼容：真实 BaselineService.plc_state_known(pid)（单参签名）可直接注入。"""
    from processos.baselines import BaselineService

    baselines = BaselineService(tmp_path / "b3_ledger.sqlite3")
    baselines.record_b2(PROJECT_ID, "build_219", "f" * 64)
    gw = SiteDeploymentGateway(baseline_provider=baselines, db=tmp_path / "bridge_gw.sqlite3")
    try:
        # 未登记 FIELD_VERIFIED B3 -> 状态未知
        out = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "w", **_full_kwargs())
        assert out["blocked_by"] == ["UNKNOWN_PLC_STATE"] and out["ready"] is False
        # 现场验证过的 B3 -> 视作 B3 证据
        baselines.record_b3(PROJECT_ID, "build_219", verification="FIELD_VERIFIED",
                            device_id="PLC_1", operator="engineer_zhang")
        ok = gw.precheck(PROJECT_ID, "build_219", "PLC_1", "w", **_full_kwargs())
        assert ok["ready"] is True
    finally:
        gw.close()
