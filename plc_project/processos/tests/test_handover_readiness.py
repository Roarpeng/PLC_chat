"""§7 tests: handover readiness conditions (HandoverReadinessService).

五条件独立开关造数断言 + ready 联合判定 + 无依赖服务时 UNKNOWN（不伪造）。
所有 sha256 均真实计算；条件取不到证据时 satisfied=None 且 evidence 含 UNKNOWN。
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.baselines import BaselineService
from processos.contract import clamp_contract
from processos.handover_check import HandoverReadinessService, register_routes
from processos.telemetry.fieldmods import FieldModificationService
from processos.traceability import TraceabilityService

PID = "PRJ_CLAMP"
INC = "INC-2026-0042"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _trace_with_incident(*, fact: str = "伸出反馈未按时出现",
                         owner: str = "engineer_on_duty",
                         status: str = "INVESTIGATING") -> TraceabilityService:
    trace = TraceabilityService()
    contract = clamp_contract()
    ids = trace.register_project(PID, contract, physical_station="电池更换站")
    trace.record_build(PID, "build_219", contract,
                       tia_project_id="TIA_PRJ_001", tia_plc_id="PLC_1")
    trace.incidents.create_incident(
        INC, ids["CM_CLAMP_CYL"],
        software={"deployed_build_id": "build_219"},
        triage={"fact": fact, "hypotheses": ["气压不足"], "root_cause": None},
        handover={"owner": owner, "status": status, "next_action": "检查线圈"},
    )
    return trace


def _good_baselines(db) -> BaselineService:
    """B1 + B2 + 现场 VERIFIED 且 checksum 匹配的 B3。"""
    svc = BaselineService(db)
    arc = sha(b"zap19-archive-v1")
    svc.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    svc.record_b2(PID, "build_219", arc, {"FB_X": sha(b"fb-x-v1")})
    svc.record_b3(PID, "build_219", verification="FIELD_VERIFIED",
                  plc_checksum=arc, device_id="PLC_1", operator="eng-1")
    return svc


def _clean_fieldmods(trace, baselines, db) -> FieldModificationService:
    """无漂移的 fieldmods：现场块与 B2 manifest 完全一致。"""
    svc = FieldModificationService(trace, baseline_provider=baselines, db=db)
    svc.recover(PID, {"blocks": [{"block_name": "FB_X",
                                  "content_sha256": sha(b"fb-x-v1")}]})
    return svc


def _by_id(result: dict) -> dict:
    return {c["id"]: c for c in result["conditions"]}


# ---------- 全部满足 → ready True ----------

def test_all_conditions_satisfied_means_ready(tmp_path):
    trace = _trace_with_incident()
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    fieldmods = _clean_fieldmods(trace, baselines, tmp_path / "f.sqlite3")
    svc = HandoverReadinessService(trace, baselines=baselines, fieldmods=fieldmods,
                                   db=tmp_path / "h.sqlite3")
    result = svc.readiness(incident_id=INC)
    assert result["ready"] is True
    assert all(c["satisfied"] is True for c in result["conditions"])
    by = _by_id(result)
    assert "VERIFIED" in by["CURRENT_DEPLOYED_VERSION_KNOWN"]["evidence"]
    assert "有负责人" in by["OPEN_ITEMS_HAVE_OWNERS"]["evidence"]
    assert "0 个未确认" in by["FIELD_DEVIATIONS_MARKED"]["evidence"]
    assert "可回退" in by["ROLLBACK_ARTIFACT_ARCHIVED"]["evidence"]
    assert "triage.fact" in by["CONCLUSIONS_TRACEABLE"]["evidence"]


# ---------- 条件 1：B3 必须 FIELD_VERIFIED ----------

def test_condition1_self_reported_b3_is_not_known(tmp_path):
    trace = _trace_with_incident()
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    baselines.record_b3(PID, "build_219", verification="SELF_REPORTED",
                        plc_checksum=sha(b"zap19-archive-v1"))
    svc = HandoverReadinessService(trace, baselines=baselines)
    c = _by_id(svc.readiness(incident_id=INC))["CURRENT_DEPLOYED_VERSION_KNOWN"]
    assert c["satisfied"] is False
    assert "UNVERIFIED_ONLINE" in c["evidence"]


def test_condition1_no_b3_is_false_not_unknown(tmp_path):
    trace = _trace_with_incident()
    baselines = BaselineService(tmp_path / "b.sqlite3")
    svc = HandoverReadinessService(trace, baselines=baselines)
    c = _by_id(svc.readiness(incident_id=INC))["CURRENT_DEPLOYED_VERSION_KNOWN"]
    assert c["satisfied"] is False
    assert c["evidence"].startswith("无 B3")


# ---------- 条件 2：未关闭问题必须有负责人 ----------

@pytest.mark.parametrize("owner", ["", "UNKNOWN"])
def test_condition2_open_item_without_owner_blocks(owner, tmp_path):
    trace = _trace_with_incident(owner=owner)
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    fieldmods = _clean_fieldmods(trace, baselines, tmp_path / "f.sqlite3")
    svc = HandoverReadinessService(trace, baselines=baselines, fieldmods=fieldmods)
    c = _by_id(svc.readiness(incident_id=INC))["OPEN_ITEMS_HAVE_OWNERS"]
    assert c["satisfied"] is False
    assert INC in c["evidence"]


def test_condition2_resolved_item_does_not_need_owner(tmp_path):
    trace = _trace_with_incident(owner="", status="RESOLVED")
    svc = HandoverReadinessService(trace)
    c = _by_id(svc.readiness(incident_id=INC))["OPEN_ITEMS_HAVE_OWNERS"]
    assert c["satisfied"] is True
    assert "无未关闭问题" in c["evidence"]


# ---------- 条件 3：fieldmods 未确认漂移为 0 ----------

def test_condition3_unconfirmed_field_override_blocks(tmp_path):
    trace = _trace_with_incident()
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    fieldmods = FieldModificationService(trace, baseline_provider=baselines,
                                         db=tmp_path / "f.sqlite3")
    # 现场冒出 B2/SourceMap 都没有的块 → unmapped native code → 受控黑盒 override。
    fieldmods.recover(PID, {"blocks": [
        {"block_name": "FB_X", "content_sha256": sha(b"fb-x-v1")},
        {"block_name": "FB_FIELD_LOCAL", "content_sha256": sha(b"field-local-edited")},
    ]})
    svc = HandoverReadinessService(trace, baselines=baselines, fieldmods=fieldmods)
    c = _by_id(svc.readiness(incident_id=INC))["FIELD_DEVIATIONS_MARKED"]
    assert c["satisfied"] is False
    assert "FB_FIELD_LOCAL" in c["evidence"]


def test_condition3_no_fieldmods_service_is_unknown(tmp_path):
    trace = _trace_with_incident()
    svc = HandoverReadinessService(trace)  # 无 fieldmods
    c = _by_id(svc.readiness(incident_id=INC))["FIELD_DEVIATIONS_MARKED"]
    assert c["satisfied"] is None
    assert c["evidence"].startswith("UNKNOWN")


# ---------- 条件 4：回退 B2 ----------

def test_condition4_missing_b2_blocks(tmp_path):
    trace = _trace_with_incident()
    baselines = BaselineService(tmp_path / "b.sqlite3")
    baselines.record_b1(PID, "sha256:" + sha(b"spec-v1"), 1)
    baselines.record_b3(PID, "build_219", verification="FIELD_VERIFIED",
                        plc_checksum=sha(b"zap19-archive-v1"))
    svc = HandoverReadinessService(trace, baselines=baselines)
    c = _by_id(svc.readiness(incident_id=INC))["ROLLBACK_ARTIFACT_ARCHIVED"]
    assert c["satisfied"] is False
    assert "回退" in c["evidence"]


# ---------- 条件 5：triage.fact 可追溯 ----------

def test_condition5_empty_fact_blocks(tmp_path):
    trace = _trace_with_incident(fact="")
    svc = HandoverReadinessService(trace)
    c = _by_id(svc.readiness(incident_id=INC))["CONCLUSIONS_TRACEABLE"]
    assert c["satisfied"] is False
    assert INC in c["evidence"]


# ---------- ready 联合判定：一个不满足即 False ----------

def test_ready_requires_all_true(tmp_path):
    trace = _trace_with_incident()
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    fieldmods = _clean_fieldmods(trace, baselines, tmp_path / "f.sqlite3")
    svc = HandoverReadinessService(trace, baselines=baselines, fieldmods=fieldmods)
    assert svc.readiness(incident_id=INC)["ready"] is True
    # 任何一个条件翻 False → ready False。
    trace.incidents.update_triage(INC, fact="")
    result = svc.readiness(incident_id=INC)
    assert result["ready"] is False
    assert _by_id(result)["CONCLUSIONS_TRACEABLE"]["satisfied"] is False


# ---------- 无依赖服务 → UNKNOWN，绝不伪造 ----------

def test_no_dependency_services_yield_unknown_conditions():
    trace = _trace_with_incident()
    svc = HandoverReadinessService(trace)  # 无 baselines / fieldmods / db
    result = svc.readiness(incident_id=INC)
    assert result["ready"] is False
    by = _by_id(result)
    for cid in ("CURRENT_DEPLOYED_VERSION_KNOWN", "FIELD_DEVIATIONS_MARKED",
                "ROLLBACK_ARTIFACT_ARCHIVED"):
        assert by[cid]["satisfied"] is None
        assert by[cid]["evidence"].startswith("UNKNOWN")
    # 纯 trace 可判的条件照常判定。
    assert by["OPEN_ITEMS_HAVE_OWNERS"]["satisfied"] is True
    assert by["CONCLUSIONS_TRACEABLE"]["satisfied"] is True


# ---------- 项目范围 + 归因规则 ----------

def test_project_scope_attributed_via_deployed_build(tmp_path):
    trace = _trace_with_incident()
    # 无关 incident：deployed build 无法归因到本项目 → 不计入范围。
    trace.incidents.create_incident(
        "INC-OTHER", trace.ids_for(PID)["CM_CLAMP_CYL"],
        software={"deployed_build_id": "build_999"},
        triage={"fact": ""}, handover={"owner": "", "status": "OPEN"})
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    fieldmods = _clean_fieldmods(trace, baselines, tmp_path / "f.sqlite3")
    svc = HandoverReadinessService(trace, baselines=baselines, fieldmods=fieldmods)
    result = svc.readiness(project_id=PID)
    assert result["scope"]["incidents"] == [INC]
    assert result["ready"] is True
    assert "deployed_build_id" in result["scope"]["attribution_rule"]


def test_incident_without_build_binding_resolves_project_unknown():
    trace = TraceabilityService()
    contract = clamp_contract()
    ids = trace.register_project(PID, contract)
    trace.incidents.create_incident(
        INC, ids["CM_CLAMP_CYL"], software={},
        triage={"fact": "x"}, handover={"owner": "e", "status": "OPEN"})
    svc = HandoverReadinessService(trace)
    result = svc.readiness(incident_id=INC)
    by = _by_id(result)
    assert by["CURRENT_DEPLOYED_VERSION_KNOWN"]["satisfied"] is None  # 归因不出 → UNKNOWN
    assert result["scope"]["resolved_project"] == "UNKNOWN"


def test_scope_arguments_validated():
    svc = HandoverReadinessService(TraceabilityService())
    with pytest.raises(ValueError):
        svc.readiness()
    with pytest.raises(ValueError):
        svc.readiness(incident_id="INC-1", project_id=PID)
    with pytest.raises(ValueError):
        svc.readiness(incident_id="INC-MISSING")


# ---------- 持久化 + HTTP 路由 ----------

def test_snapshots_persisted(tmp_path):
    db = tmp_path / "h.sqlite3"
    trace = _trace_with_incident()
    HandoverReadinessService(trace, db=db).readiness(incident_id=INC)
    history = HandoverReadinessService(trace, db=db).snapshots_for(PID)
    assert len(history) == 1
    assert history[0]["ready"] is False  # 无 baselines → UNKNOWN → False


def test_http_routes(tmp_path):
    trace = _trace_with_incident()
    baselines = _good_baselines(tmp_path / "b.sqlite3")
    fieldmods = _clean_fieldmods(trace, baselines, tmp_path / "f.sqlite3")
    app = FastAPI()
    app.state.trace = trace
    svc = HandoverReadinessService(trace, baselines=baselines, fieldmods=fieldmods,
                                   db=tmp_path / "h.sqlite3")
    app.state.handover_readiness = svc
    register_routes(app)
    client = TestClient(app)

    r = client.get(f"/api/processos/incidents/{INC}/handover/readiness")
    assert r.status_code == 200 and r.json()["ready"] is True
    r = client.get(f"/api/processos/projects/{PID}/handover/readiness")
    assert r.status_code == 200 and r.json()["ready"] is True
    assert r.json()["scope"]["incidents"] == [INC]
    assert client.get("/api/processos/incidents/INC-NOPE/handover/readiness").status_code == 404


def test_http_project_route_404_for_unknown_project(tmp_path):
    app = FastAPI()
    from processos.api.store import ProjectStore

    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    app.state.trace = _trace_with_incident()
    register_routes(app)
    client = TestClient(app)
    assert client.get("/api/processos/projects/PRJ_NOPE/handover/readiness").status_code == 404
    assert client.get(f"/api/processos/projects/{PID}/handover/readiness").status_code == 200


def test_register_routes_idempotent(tmp_path):
    app = FastAPI()
    app.state.trace = _trace_with_incident()
    svc = HandoverReadinessService(app.state.trace, db=tmp_path / "h.sqlite3")
    app.state.handover_readiness = svc
    register_routes(app)
    before = len(app.routes)
    register_routes(app)
    assert len(app.routes) == before
    assert app.state.handover_readiness is svc
