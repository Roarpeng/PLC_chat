"""FC-05 tests: Impact Report derivation from the real registry graph,
patch risk classification, explicit UNKNOWN fail-closed blocking, JsonDao
persistence roundtrip and the API routes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.store import ProjectStore
from processos.contract import clamp_contract
from processos.impact import ImpactReportService, register_routes
from processos.store.db import JsonDao, open_db
from processos.traceability import TraceabilityService

UNKNOWN = "UNKNOWN"


@pytest.fixture(autouse=True)
def _isolated_store_db(tmp_path, monkeypatch):
    """Unit tests never write the default store path (store/db.py rule)."""
    monkeypatch.setenv("PROCESSOS_DB", str(tmp_path / "impact_tests.sqlite3"))


def _seeded_trace() -> tuple[TraceabilityService, str, str]:
    """电池更换站夹紧气缸真实图：register_project + record_build + 报警定义。"""
    t = TraceabilityService()
    c = clamp_contract()
    t.register_project(c.id, c, physical_station="电池更换站")
    t.record_build(c.id, "build_219", c, tia_project_id="TIA_PRJ_001", tia_plc_id="PLC_1")
    cm_id = t.ids_for(c.id)["CM_CLAMP_CYL"]
    t.incidents.define_alarm("alarm_clamp_timeout", "CM_MOTION_TIMEOUT", cm_id,
                             "伸出到位信号未在规定时间内出现")
    return t, c.id, cm_id


def _closure(reg, seeds):
    """契约镜像：subject + part_of/maps_to/participates_in 双向邻域闭包。"""
    seen, frontier = set(), list(seeds)
    while frontier:
        oid = frontier.pop()
        if oid in seen or reg.get(oid) is None:
            continue
        seen.add(oid)
        for rel in ("part_of", "maps_to", "participates_in"):
            frontier.extend(n.object_id for n in reg.neighbors(oid, rel, "both"))
    return seen


# 1. 夹紧 CM 为 subject：affected/alarm/io 全部来自真实图推导
def test_clamp_cm_report_full_derivation():
    t, pid, cm_id = _seeded_trace()
    ids = t.ids_for(pid)
    rep = ImpactReportService(t).build(pid, object_id=cm_id, reason="伸出超时 3s→5s 前的影响评估")

    assert rep["report_id"].startswith("imp_")
    assert rep["project_id"] == pid
    assert rep["subject"] == {"object_id": cm_id, "display_name": "夹紧气缸（双作用）",
                              "reason": "伸出超时 3s→5s 前的影响评估"}
    assert [e["display_name"] for e in rep["affected"]["ems"]] == ["夹紧循环"]
    assert [e["display_name"] for e in rep["affected"]["units"]] == ["U_ASSEMBLY"]
    assert cm_id in {e["object_id"] for e in rep["affected"]["cms"]}
    step_ids = {e["object_id"] for e in rep["affected"]["steps"]}
    assert {ids["S_EXTEND"], ids["S_RETRACT"]} <= step_ids
    # 反向引用 subject：component maps_to + 两个 step participates_in
    assert {c["object_id"] for c in rep["callers"]} == {
        ids["component:CM_CLAMP_CYL"], ids["S_EXTEND"], ids["S_RETRACT"]}
    # 报警定义 originates_from 命中影响闭包
    assert [d["definition_id"] for d in rep["alarm_definitions"]] == ["alarm_clamp_timeout"]
    assert rep["hmi_messages"] == ["伸出到位信号未在规定时间内出现"]
    # io_db_interfaces = 闭包内 SourceMap 的 instance_db/symbol_refs 聚合
    closure = _closure(t.registry, [cm_id])
    expected = set()
    for e in t.sourcemap.all_entries():
        if e.semantic_object_id in closure:
            if e.instance_db:
                expected.add(e.instance_db)
            expected.update(e.symbol_refs)
    assert expected
    assert set(rep["io_db_interfaces"]) == expected
    assert UNKNOWN not in rep["io_db_interfaces"]
    # 只读报告（无补丁）：无保持/加载影响；但回归状态 UNKNOWN 仍 fail-closed
    assert rep["state_retention_risk"] == "NONE"
    assert rep["online_load_impact"] == "NONE"
    assert rep["blocked_high_risk_delivery"] is True


# 2. set_timeout 类补丁：state LOW、在线需重载、回归 UNKNOWN → 阻断
def test_patch_set_timeout_low_risk_blocked_on_unknown_regression():
    t, pid, _ = _seeded_trace()
    ids = t.ids_for(pid)
    rep = ImpactReportService(t).build(
        pid, patch_ops=[{"op": "set_timeout", "target": "S_EXTEND", "value": 5000}],
        reason="伸出超时由 3000ms 改 5000ms")

    assert rep["subject"]["object_id"] == UNKNOWN  # patch-only report has no object subject
    assert ids["S_EXTEND"] in {e["object_id"] for e in rep["affected"]["steps"]}
    assert [d["code"] for d in rep["alarm_definitions"]] == ["CM_MOTION_TIMEOUT"]
    assert rep["state_retention_risk"] == "LOW"
    assert rep["online_load_impact"] == "RELOAD_REQUIRED"
    assert rep["regression_tests"]
    assert all(r["status"] == UNKNOWN for r in rep["regression_tests"])
    assert any(r["name"] == "S_EXTEND" for r in rep["regression_tests"])
    assert rep["blocked_high_risk_delivery"] is True
    assert "regression_tests" in rep["unknown_fields"]


def test_patch_db_layout_is_high_risk():
    t, pid, _ = _seeded_trace()
    rep = ImpactReportService(t).build(
        pid, patch_ops=[{"op": "set", "path": "/db_layout/CM_CLAMP_CYL/instance_db", "value": "DB_NEW"}])
    assert rep["state_retention_risk"] == "HIGH"
    assert rep["blocked_high_risk_delivery"] is True


# 3. 注册了契约但无 SourceMap：io UNKNOWN、unknown_fields 非空、阻断
def test_registry_without_sourcemap_marks_unknown_and_blocks():
    t = TraceabilityService()
    c = clamp_contract()
    t.register_project(c.id, c, physical_station="电池更换站")
    cm_id = t.ids_for(c.id)["CM_CLAMP_CYL"]
    rep = ImpactReportService(t).build(c.id, object_id=cm_id)

    assert rep["io_db_interfaces"] == [UNKNOWN]
    assert "io_db_interfaces" in rep["unknown_fields"]
    assert rep["unknown_fields"]
    assert rep["blocked_high_risk_delivery"] is True


# 4. 输入校验与未知对象
def test_missing_inputs_raise_value_error():
    t, pid, _ = _seeded_trace()
    svc = ImpactReportService(t)
    with pytest.raises(ValueError):
        svc.build(pid)
    with pytest.raises(ValueError):
        svc.build(pid, object_id="", patch_ops=[])


def test_unknown_object_subject_unknown_but_reported():
    t, pid, _ = _seeded_trace()
    rep = ImpactReportService(t).build(pid, object_id="cm_NOT_REGISTERED", reason="未知对象")
    assert rep["subject"] == {"object_id": "cm_NOT_REGISTERED", "display_name": UNKNOWN,
                              "reason": "未知对象"}
    assert rep["state_retention_risk"] == UNKNOWN
    assert "state_retention_risk" in rep["unknown_fields"]
    assert rep["affected"] == {"units": [], "ems": [], "cms": [], "steps": []}
    assert rep["io_db_interfaces"] == [UNKNOWN]
    assert rep["blocked_high_risk_delivery"] is True  # 不 404：允许出报告但阻断


# 5. 持久化 roundtrip（tmp_path 库；Windows 下显式 conn.close 释放句柄）
def test_report_persistence_roundtrip(tmp_path):
    t, pid, cm_id = _seeded_trace()
    conn = open_db(tmp_path / "impact.sqlite3")
    try:
        svc = ImpactReportService(t, dao=JsonDao(conn, "impact"))
        rep = svc.build(pid, object_id=cm_id, reason="roundtrip")
        fetched = svc.get(rep["report_id"])
        assert fetched == rep
        assert svc.get("imp_missing0") is None
    finally:
        conn.close()


# 6. register_routes + TestClient：POST/GET 走通，404/422 正确
def test_routes_post_and_get(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESSOS_DB", str(tmp_path / "api_impact.sqlite3"))
    t, pid, cm_id = _seeded_trace()
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    app.state.trace = t
    register_routes(app)
    register_routes(app)  # 幂等：重复注册安全
    client = TestClient(app)

    r = client.post(f"/api/processos/projects/{pid}/impact",
                    json={"object_id": cm_id, "reason": "API 影响分析"})
    assert r.status_code == 200
    rep = r.json()
    assert rep["report_id"].startswith("imp_")
    assert rep["subject"]["object_id"] == cm_id

    g = client.get(f"/api/processos/impact/{rep['report_id']}")
    assert g.status_code == 200
    assert g.json() == rep

    assert client.get("/api/processos/impact/imp_notexist").status_code == 404
    assert client.post("/api/processos/projects/PRJ_NONE/impact",
                       json={"object_id": "x"}).status_code == 404
    assert client.post(f"/api/processos/projects/{pid}/impact", json={}).status_code == 422
    # 未知对象：不 404，返回报告但 blocked
    u = client.post(f"/api/processos/projects/{pid}/impact", json={"object_id": "cm_NOT_REGISTERED"})
    assert u.status_code == 200
    assert u.json()["subject"]["display_name"] == UNKNOWN
    assert u.json()["blocked_high_risk_delivery"] is True
