"""§3.2 B tests: expert mode controlled SCL changes (ExpertSclService).

断言的纪律（PLAN §12）：语义候选**不落盘**（ir_written=False，必须走审批）；
黑盒原文保留且显式所有权保护；官方库/F-Safety/保护块 fail-closed 403；
未知块/空 reason 422；无角色头 403；黑盒持久化 roundtrip。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.store import ProjectStore
from processos.contract import clamp_contract
from processos.expert import ExpertSclService, register_routes
from processos.safety.errors import SafetyError
from processos.sourcemap import SourceMapEntry
from processos.traceability import TraceabilityService

PID = "PRJ_CLAMP"
# record_build 对 clamp 契约真实生成的 EM 顺序块（含 S_EXTEND 行为绑定）。
SEQ_BLOCK = "FB_EM_CLAMP_SEQ"
DRV_BLOCK = "FB_CM_CLAMP_CYL_DRV"

FE = {"X-Actor-Id": "eng-1", "X-Actor-Role": "FieldEngineer"}


def _rig(tmp_path=None) -> tuple[ProjectStore, TraceabilityService, object]:
    store = ProjectStore()
    contract = clamp_contract()
    store.create_project(contract)
    trace = TraceabilityService()
    trace.register_project(PID, contract, physical_station="电池更换站")
    trace.record_build(PID, "build_219", contract, tia_project_id="TIA_PRJ_001", tia_plc_id="PLC_1")
    return store, trace, contract


def _client(store: ProjectStore, trace: TraceabilityService, service: ExpertSclService) -> TestClient:
    app = FastAPI()
    app.state.store = store
    app.state.trace = trace
    app.state.expert_scl = service
    register_routes(app)
    return TestClient(app)


def _add_entry(trace: TraceabilityService, block_name: str, *, ownership: str = "GENERATED",
               behavior_step_id: str = "", block_kind: str = "FB",
               symbol_refs: list[str] | None = None) -> None:
    trace.sourcemap.add(SourceMapEntry(
        source_map_id=f"src_t_{block_name}_{behavior_step_id or 'blk'}",
        semantic_object_id="", release_build_id="build_219",
        block_name=block_name, block_kind=block_kind,
        behavior_step_id=behavior_step_id,
        symbol_refs=symbol_refs or [], ownership=ownership))


# ---------- 1. 可解析赋值 → SEMANTIC_CANDIDATE，且不落盘 ----------

def test_parseable_assignment_yields_semantic_candidate_without_writing():
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace)
    result = svc.submit(PID, block_name=SEQ_BLOCK,
                        scl_diff="ExtendTimeout := T#5000ms;",
                        reason="现场伸出耗时变长", actor="eng-1")
    assert result["mode"] == "SEMANTIC_CANDIDATE"
    assert result["requires_approval"] is True
    assert result["ir_written"] is False
    assert result["semantic_ops"] == [
        {"op": "set_param", "block": SEQ_BLOCK, "param": "ExtendTimeout", "value": "T#5000ms"}]
    assert result["patch"]["ops"][0] == {
        "op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms", "value": 5000}
    # 未落盘：store revision 不动，契约里超时仍是 3000ms。
    state = store.projects[PID]
    assert state.revision == 1
    assert state.contract.operation("OP_CLAMP").step("S_EXTEND").timeout_ms == 3000
    # 语义候选不是黑盒：不产生 override。
    assert svc.overrides_for(PID) == []


def test_semantic_candidate_http_requires_approval_and_skips_ir_write(tmp_path):
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace, db=tmp_path / "expert.sqlite3")
    client = _client(store, trace, svc)
    body = {"block_name": SEQ_BLOCK, "scl_diff": "ExtendTimeout := T#5s;",
            "reason": "工艺节拍调整", "actor": "eng-1"}
    r = client.post(f"/api/processos/projects/{PID}/scl-changes", json=body, headers=FE)
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "SEMANTIC_CANDIDATE" and data["ir_written"] is False
    assert data["patch"]["ops"][0]["value"] == 5000  # T#5s -> 5000ms
    assert store.projects[PID].revision == 1  # 无副作用
    assert client.get(f"/api/processos/projects/{PID}/scl-overrides").json()["overrides"] == []


def test_cm_driver_param_maps_to_resource_params():
    store, trace, contract = _rig()
    svc = ExpertSclService(store, trace)
    result = svc.submit(PID, block_name=DRV_BLOCK,
                        scl_diff="MaxForce := 120;",
                        reason="夹紧力上限调整", actor="eng-1")
    assert result["mode"] == "SEMANTIC_CANDIDATE"
    assert result["patch"]["ops"][0]["path"] == "/resources/CM_CLAMP_CYL/params/MaxForce"
    assert result["patch"]["ops"][0]["value"] == 120
    assert contract.resource("CM_CLAMP_CYL").params == {}  # 原件未动


# ---------- 2. 控制语句/不可解析 → MANAGED_NATIVE_OVERRIDE 原文保留 + 保护 ----------

def test_control_statement_diff_becomes_protected_blackbox():
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace)
    diff = ("IF NOT Extended THEN\n"
            "    ExtendTimeout := T#9000ms;\n"
            "    AlarmAck := TRUE;\n"
            "END_IF;")
    result = svc.submit(PID, block_name=SEQ_BLOCK, scl_diff=diff,
                        reason="现场临时逻辑", actor="eng-2")
    assert result["mode"] == "MANAGED_NATIVE_OVERRIDE"
    ov = result["override"]
    assert ov["scl_diff"] == diff  # 原文逐字节保留
    assert ov["ownership"] == "MANAGED_NATIVE_OVERRIDE"
    assert ov["protected_by"] == "EXPLICIT_OWNERSHIP"
    assert ov["semantic_understood"] is False
    assert ov["reason"] == "现场临时逻辑" and ov["actor"] == "eng-2"
    assert "禁止" in ov["note"]
    assert svc.overrides_for(PID) == [ov]


def test_unparseable_value_becomes_blackbox():
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace)
    result = svc.submit(PID, block_name=SEQ_BLOCK,
                        scl_diff="ExtendTimeout := TimeoutBase * 2;",
                        reason="表达式不可确定性解析", actor="eng-1")
    assert result["mode"] == "MANAGED_NATIVE_OVERRIDE"


# ---------- 3. 官方库 / F-Safety / 保护块 → 403 SAFETY_SCOPE_BLOCKED ----------

@pytest.mark.parametrize("kwargs", [
    {"ownership": "OFFICIAL_LIBRARY"},
    {"ownership": "MANAGED_NATIVE_OVERRIDE"},  # 既有黑盒同样禁止 AI 再写入
    {"block_kind": "F_FB"},
    {"symbol_refs": ["f_safety"]},
])
def test_blocked_ownership_or_markers_raise_safety_error(kwargs):
    store, trace, _ = _rig()
    _add_entry(trace, "FB_Guarded", **kwargs)
    svc = ExpertSclService(store, trace)
    with pytest.raises(SafetyError) as ei:
        svc.submit(PID, block_name="FB_Guarded", scl_diff="A := 1;",
                   reason="x", actor="eng-1")
    assert ei.value.code == "SAFETY_SCOPE_BLOCKED"
    assert ei.value.http_status == 403


def test_official_library_block_http_403(tmp_path):
    store, trace, _ = _rig()
    _add_entry(trace, "FB_LibOfficial", ownership="OFFICIAL_LIBRARY")
    svc = ExpertSclService(store, trace, db=tmp_path / "expert.sqlite3")
    client = _client(store, trace, svc)
    r = client.post(f"/api/processos/projects/{PID}/scl-changes", headers=FE,
                    json={"block_name": "FB_LibOfficial", "scl_diff": "A := 1;",
                          "reason": "试试官方库", "actor": "eng-1"})
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "SAFETY_SCOPE_BLOCKED"
    assert body["details"]["block_name"] == "FB_LibOfficial"
    assert svc.overrides_for(PID) == []  # 被拒的提交不产生黑盒


def test_safety_block_name_prefix_blocked():
    store, trace, _ = _rig()
    _add_entry(trace, "F_SafetyZone")
    svc = ExpertSclService(store, trace)
    with pytest.raises(SafetyError) as ei:
        svc.submit(PID, block_name="F_SafetyZone", scl_diff="A := 1;",
                   reason="x", actor="eng-1")
    assert ei.value.code == "SAFETY_SCOPE_BLOCKED"


# ---------- 4. 未知块 / 空 reason / 空 diff → 422 ----------

@pytest.mark.parametrize("payload", [
    {"block_name": "FB_Unknown_Block", "scl_diff": "A := 1;", "reason": "r"},
    {"block_name": SEQ_BLOCK, "scl_diff": "A := 1;", "reason": "   "},
    {"block_name": SEQ_BLOCK, "scl_diff": "   ", "reason": "r"},
    {"block_name": SEQ_BLOCK, "scl_diff": "A := 1;", "reason": "r", "actor": ""},
])
def test_invalid_submissions_are_422(payload):
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace)
    with pytest.raises(ValueError):
        svc.submit(PID, actor=payload.get("actor", "eng-1"),
                   block_name=payload["block_name"], scl_diff=payload["scl_diff"],
                   reason=payload["reason"])


def test_invalid_submission_http_422():
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace)
    client = _client(store, trace, svc)
    r = client.post(f"/api/processos/projects/{PID}/scl-changes", headers=FE,
                    json={"block_name": "FB_Nope", "scl_diff": "A := 1;", "reason": "r"})
    assert r.status_code == 422
    r = client.post(f"/api/processos/projects/{PID}/scl-changes", headers=FE,
                    json={"block_name": SEQ_BLOCK, "scl_diff": "A := 1;", "reason": ""})
    assert r.status_code == 422
    r = client.post(f"/api/processos/projects/{PID}/scl-changes", headers=FE,
                    json={"block_name": SEQ_BLOCK, "reason": "r"})  # 缺字段
    assert r.status_code == 422
    assert client.post("/api/processos/projects/PRJ_NOPE/scl-changes",
                       headers=FE, json={"block_name": SEQ_BLOCK, "scl_diff": "A := 1;",
                                         "reason": "r"}).status_code == 404


# ---------- 5. 持久化 roundtrip ----------

def test_blackbox_persistence_roundtrip(tmp_path):
    db = tmp_path / "expert.sqlite3"
    store, trace, _ = _rig()
    svc1 = ExpertSclService(store, trace, db=db)
    diff = "IF Broken THEN Stop := TRUE; END_IF;"
    out = svc1.submit(PID, block_name=SEQ_BLOCK, scl_diff=diff, reason="r", actor="eng-9")
    assert out["mode"] == "MANAGED_NATIVE_OVERRIDE"
    svc2 = ExpertSclService(store, trace, db=db)  # 短命连接：重开读回
    restored = svc2.overrides_for(PID)
    assert len(restored) == 1
    assert restored[0]["scl_diff"] == diff
    assert restored[0]["override_id"] == out["override"]["override_id"]
    assert svc2.overrides_for("PRJ_OTHER") == []


# ---------- 6. RBAC：无角色头 → 403 ----------

def test_no_role_header_is_403_with_body_code(tmp_path):
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace, db=tmp_path / "expert.sqlite3")
    client = _client(store, trace, svc)
    r = client.post(f"/api/processos/projects/{PID}/scl-changes",
                    json={"block_name": SEQ_BLOCK, "scl_diff": "A := 1;", "reason": "r"})
    assert r.status_code == 403
    # 裸 FastAPI 测试 app 无 create_app 的展平 handler：detail 即角色拒绝结构。
    assert r.json()["detail"]["code"] == "ROLE_FORBIDDEN"
    # Viewer 同样被拒；FieldEngineer 放行。
    r = client.post(f"/api/processos/projects/{PID}/scl-changes",
                    headers={"X-Actor-Role": "Viewer"},
                    json={"block_name": SEQ_BLOCK, "scl_diff": "A := 1;", "reason": "r"})
    assert r.status_code == 403
    r = client.post(f"/api/processos/projects/{PID}/scl-changes", headers=FE,
                    json={"block_name": SEQ_BLOCK, "scl_diff": "A := 1;", "reason": "r"})
    assert r.status_code == 200


# ---------- 7. 幂等注册 + 审计可选 ----------

def test_register_routes_idempotent_and_service_reused(tmp_path):
    store, trace, _ = _rig()
    svc = ExpertSclService(store, trace, db=tmp_path / "expert.sqlite3")
    app = FastAPI()
    app.state.store = store
    app.state.trace = trace
    app.state.expert_scl = svc
    register_routes(app)
    before = len(app.routes)
    register_routes(app)
    assert len(app.routes) == before
    assert app.state.expert_scl is svc


def test_submit_audits_when_ledger_attached(tmp_path):
    from processos.rbac import AuditLog, Actor

    store, trace, _ = _rig()
    log = AuditLog(tmp_path / "audit.sqlite3")
    svc = ExpertSclService(store, trace, db=tmp_path / "expert.sqlite3", audit=log)
    svc.submit(PID, block_name=SEQ_BLOCK, scl_diff="IF X THEN A := 1; END_IF;",
               reason="r", actor=Actor(actor_id="eng-7", role="FieldEngineer"))
    entries = log.entries(action="expert.scl.submit")
    assert len(entries) == 1
    assert entries[0]["extra"]["mode"] == "MANAGED_NATIVE_OVERRIDE"
    assert entries[0]["actor_id"] == "eng-7"
    # 无审计环境：跳过不炸。
    ExpertSclService(store, trace).submit(
        PID, block_name=SEQ_BLOCK, scl_diff="IF X THEN A := 1; END_IF;",
        reason="r", actor="eng-8")
