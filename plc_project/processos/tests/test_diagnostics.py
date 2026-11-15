"""§1 L-loop tests: DiagnosticsLocateService（诊断定位 + 编译范围建议）。

纪律（PLAN §11/§12）：块名映射不回 SourceMap → UNMAPPED_NATIVE_CODE（不猜）；
块级歧义不虚构对象归属（candidates 列全，display UNKNOWN）；行号永不虚构；
compile_scope 触及接口/IO/不变量 → full 且原因明确，step 参数 → incremental +
块清单；note 恒承认当前交付链是全量编译（增量由 FastWriteback 承接，不冒充）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.diag_routes import register_routes
from processos.api.store import ProjectStore
from processos.contract import clamp_contract
from processos.diagnostics import (
    BLOCK_LEVEL_TEXT,
    UNMAPPED_NATIVE_CODE,
    DiagnosticsLocateService,
)
from processos.repair.service import RepairBoundaryService
from processos.traceability import TraceabilityService

PID = "PRJ_CLAMP"  # clamp_contract().id
CM_BLOCK = "FB_CM_CLAMP_CYL_DRV"
SEQ_BLOCK = "FB_EM_CLAMP_SEQ"


def _trace_with_build() -> TraceabilityService:
    t = TraceabilityService()
    c = clamp_contract()
    t.register_project(c.id, c, physical_station="电池更换站")
    t.record_build(c.id, "build_219", c)
    return t


def _svc(tmp_path=None) -> tuple[DiagnosticsLocateService, TraceabilityService]:
    t = _trace_with_build()
    repair = RepairBoundaryService(db=tmp_path / "repair.sqlite3" if tmp_path else None)
    svc = DiagnosticsLocateService(t, repair,
                                   db=tmp_path / "diag.sqlite3" if tmp_path else None)
    return svc, t


@pytest.fixture()
def svc_trace():
    """(service, trace) 共用同一份造数：对象 id 是每次生成的新 ULID。"""
    return _svc()


@pytest.fixture()
def svc(svc_trace) -> DiagnosticsLocateService:
    return svc_trace[0]


@pytest.fixture()
def client(tmp_path) -> TestClient:
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    app.state.trace = _trace_with_build()
    app.state.db_path = None  # 纯内存：测试不触碰默认 SQLite 路径
    register_routes(app)
    return TestClient(app)


# ---------- 1. 夹紧 FB 块名定位到 cm/step ----------

def test_locate_cm_driver_block_maps_to_cm_object(svc):
    r = svc.locate(PID, [{"block": CM_BLOCK, "message": "compile error in driver"}])
    assert r["unmapped"] == []
    m = r["mappings"][0]
    assert m["block_kind"] == "FB"
    assert m["semantic_object_id"].startswith("af_")  # CM_CLAMP_CYL -> af_cm 对象
    assert m["display_name"] == "夹紧气缸（双作用）"
    assert m["behavior_step_id"] is None  # CM 驱动块：无步骤
    assert m["scl_line_range"] is None
    assert m["scl_location"] == BLOCK_LEVEL_TEXT  # 块级定位（无行号），行号永不虚构
    assert m["located"] == "block"
    assert m["source_map_id"].startswith("src_")


def test_locate_seq_block_with_line_pins_the_step(svc_trace):
    svc, t = svc_trace
    ids = t.ids_for(PID)
    rng = t.sourcemap.resolve(ids["S_EXTEND"], "build_219")[0].scl_line_range
    mid = (rng[0] + rng[1]) // 2
    r = svc.locate(PID, [{"block": SEQ_BLOCK, "line": mid,
                          "message": "type mismatch at input"}])
    m = r["mappings"][0]
    assert m["located"] == "line"
    assert m["semantic_object_id"] == ids["S_EXTEND"]
    assert m["behavior_step_id"] == "S_EXTEND"
    assert m["scl_line_range"] == list(rng)
    assert m["scl_location"] == f"行 {rng[0]}–{rng[1]}"
    assert m["display_name"]  # 步骤显示名（经 registry.get 取）


def test_locate_seq_block_without_line_is_block_ambiguous_not_guessed(svc):
    """序列块承载 6 个 step：无行号时不得猜某一个 —— candidates 列全，UNKNOWN。"""
    r = svc.locate(PID, [{"block": SEQ_BLOCK, "message": "block compile error"}])
    m = r["mappings"][0]
    assert m["located"] == "block_ambiguous"
    assert m["semantic_object_id"] is None
    assert m["display_name"] == "UNKNOWN"
    assert m["scl_location"] == BLOCK_LEVEL_TEXT
    assert len(m["candidates"]) == 6  # S_WAIT..S_FAULT 全部候选供人工判断
    assert all(c["display_name"] != "UNKNOWN" for c in m["candidates"])


def test_locate_line_outside_any_span_falls_back_to_block_ambiguous(svc):
    """行号不落任何区间 → 不猜到邻近区间，退块级歧义。"""
    r = svc.locate(PID, [{"block": SEQ_BLOCK, "line": 99999, "message": "x"}])
    assert r["mappings"][0]["located"] == "block_ambiguous"
    assert r["mappings"][0]["candidates"]


def test_locate_prefers_latest_build(svc_trace):
    svc, t = svc_trace
    t.record_build(PID, "build_220", clamp_contract())
    ids = t.ids_for(PID)
    rng = t.sourcemap.resolve(ids["S_EXTEND"], "build_220")[0].scl_line_range
    mid = (rng[0] + rng[1]) // 2
    r = svc.locate(PID, [{"block": SEQ_BLOCK, "line": mid, "message": "x"}])
    m = r["mappings"][0]
    assert m["release_build_id"] == "build_220"  # 优先最新 build 的条目
    assert m["scl_line_range"] == list(rng)


# ---------- 2. 未知块 → unmapped + UNMAPPED_NATIVE_CODE ----------

def test_locate_unknown_block_is_unmapped_with_error_code(svc):
    r = svc.locate(PID, [
        {"block": "FB_NATIVE_HANDWRITTEN", "line": 12, "message": "name conflict: FB_X"},
        {"block": "", "message": "no block at all"},
    ])
    assert r["mappings"] == []
    assert len(r["unmapped"]) == 2
    for u in r["unmapped"]:
        assert u["error_code"] == UNMAPPED_NATIVE_CODE
        assert "不可映射不猜" in u["reason"]
    assert r["unmapped"][0]["index"] == 0
    assert r["unmapped"][1]["index"] == 1


# ---------- 3. repair proposals 附带且 auto_applied 恒空 ----------

def test_locate_attaches_repair_proposals_review_only(svc):
    r = svc.locate(PID, [
        {"block": CM_BLOCK, "message": "name conflict: FB_X"},
        {"block": CM_BLOCK, "message": "sensor intermittently offline"},  # 白名单外
    ])
    p = r["proposals"]
    assert p is not None
    assert len(p["proposals"]) == 1
    assert p["proposals"][0]["fix"]["category"] == "BLOCK_NAME_CONFLICT"
    assert p["proposals"][0]["must_return_to_review"] is True  # 恒真：候选回流审批
    assert p["auto_applied"] == []  # 永不自动应用
    assert len(p["forbidden_seen"]) == 1  # 白名单外只登记不提议


def test_locate_without_repair_service_omits_proposals():
    t = _trace_with_build()
    svc = DiagnosticsLocateService(t, None)
    r = svc.locate(PID, [{"block": CM_BLOCK, "message": "x"}])
    assert r["proposals"] is None
    assert r["mappings"]


# ---------- 4. compile_scope：step op → incremental；接口/invariant → full ----------

def test_compile_scope_step_op_is_incremental_with_block_list(svc):
    r = svc.compile_scope(PID, [
        {"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms",
         "value": 5000},
    ])
    assert r["mode"] == "incremental"
    assert SEQ_BLOCK in r["affected_blocks"]  # S_EXTEND 所在块
    assert r["reason"]
    assert "全量编译" in r["note"] and "FastWriteback" in r["note"]  # 诚实注脚


def test_compile_scope_cm_and_step_ops_union_blocks(svc_trace):
    svc, t = svc_trace
    r = svc.compile_scope(PID, [
        {"op": "set", "path": "/operations/OP_CLAMP/steps/S_HOLD/duration_ms", "value": 1},
        {"op": "set", "path": "/resources/CM_CLAMP_CYL/name", "value": "夹紧气缸 B"},
    ])
    assert r["mode"] == "incremental"
    assert sorted(r["affected_blocks"]) == sorted({SEQ_BLOCK, CM_BLOCK})


@pytest.mark.parametrize("path,op", [
    ("/resources/CM_CLAMP_CYL/io_bindings/Extended", "set"),
    ("/resources/CM_CLAMP_CYL/commands", "set"),
    ("/invariants/INV_CLAMP_SAFETY", "set"),
    ("/operations/OP_CLAMP/steps", "add"),
    ("/resources/CM_CLAMP_CYL", "remove"),
])
def test_compile_scope_interface_or_structural_ops_force_full(svc, path, op):
    r = svc.compile_scope(PID, [{"op": op, "path": path, "value": 1}])
    assert r["mode"] == "full"
    assert "增量编译不安全" in r["reason"]


def test_compile_scope_empty_or_unmappable_ops_fail_closed_to_full(svc):
    r = svc.compile_scope(PID, [])
    assert r["mode"] == "full" and r["ops_analyzed"] == 0
    r = svc.compile_scope(PID, [{"op": "set", "path": "/name", "value": "x"}])
    assert r["mode"] == "full"
    assert "UNKNOWN" in r["reason"]  # 证明不了范围就不声称增量


def test_compile_scope_note_is_honest_about_full_chain(svc):
    for ops in ([], [{"op": "set", "path": "/invariants/X", "value": 1}],
                [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_HOLD/duration_ms",
                  "value": 1}]):
        r = svc.compile_scope(PID, ops)
        assert "当前交付链为全量编译" in r["note"]
        assert "FastWriteback" in r["note"]


# ---------- 5. 持久化 roundtrip（namespace "diag_locates"） ----------

def test_locate_snapshots_persisted(tmp_path):
    svc, _ = _svc(tmp_path)
    svc.locate(PID, [{"block": CM_BLOCK, "message": "name conflict"}])
    history = DiagnosticsLocateService(
        _trace_with_build(), RepairBoundaryService(),
        db=tmp_path / "diag.sqlite3").locates_for(PID)
    assert len(history) == 1
    assert history[0]["mappings"][0]["block"] == CM_BLOCK
    assert history[0]["locate_id"].startswith("dl_")
    # 纯内存服务不落盘也不报错
    mem_svc, _ = _svc()
    mem_svc.locate(PID, [{"block": CM_BLOCK, "message": "x"}])
    assert len(mem_svc.locates_for(PID)) == 1


def test_service_rejects_live_connection():
    import sqlite3
    with pytest.raises(TypeError):
        DiagnosticsLocateService(_trace_with_build(), None, db=sqlite3.connect(":memory:"))


# ---------- 6. HTTP 路由（TestClient 走 register_routes） ----------

def test_http_locate_route(client):
    r = client.post(f"/api/processos/projects/{PID}/diagnostics/locate", json={
        "diagnostics": [
            {"block": CM_BLOCK, "message": "name conflict: FB_X"},
            {"block": "FB_UNKNOWN", "message": "weird"},
        ]})
    assert r.status_code == 200
    data = r.json()
    assert len(data["mappings"]) == 1
    assert data["mappings"][0]["display_name"] == "夹紧气缸（双作用）"
    assert data["unmapped"][0]["error_code"] == UNMAPPED_NATIVE_CODE
    assert data["proposals"]["auto_applied"] == []


def test_http_compile_scope_route(client):
    r = client.post(f"/api/processos/projects/{PID}/compile-scope", json={
        "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms",
                 "value": 5000}]})
    assert r.status_code == 200
    assert r.json()["mode"] == "incremental"
    assert SEQ_BLOCK in r.json()["affected_blocks"]


def test_http_routes_validate_body_and_project(client):
    bad = client.post(f"/api/processos/projects/{PID}/diagnostics/locate",
                      json={"diagnostics": "nope"})
    assert bad.status_code == 422
    bad = client.post(f"/api/processos/projects/{PID}/compile-scope", json={})
    assert bad.status_code == 422
    gone = client.post("/api/processos/projects/PRJ_NOPE/diagnostics/locate",
                       json={"diagnostics": []})
    assert gone.status_code == 404


def test_register_routes_idempotent(tmp_path):
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    app.state.trace = _trace_with_build()
    app.state.db_path = str(tmp_path / "diag.sqlite3")
    register_routes(app)
    before = len(app.routes)
    register_routes(app)
    assert len(app.routes) == before
