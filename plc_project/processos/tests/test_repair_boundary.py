"""§5.2 tests: auto-repair boundary (RepairBoundaryService).

纪律（PLAN §12）：五类 ALLOWED 只能作为候选回流审查（must_return_to_review 恒真、
auto_applied 恒空）；七类 FORBIDDEN fail-closed 拒绝且理由明确；未知类别默认拒绝；
「编译通过」的话术不能把禁改项洗白；白名单外诊断只登记不提议。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.store import ProjectStore
from processos.contract import clamp_contract
from processos.repair import (
    ALLOWED_CATEGORIES,
    FORBIDDEN_CATEGORIES,
    RepairBoundaryService,
    register_routes,
)

PID = "PRJ_CLAMP"
FE = {"X-Actor-Id": "eng-1", "X-Actor-Role": "FieldEngineer"}


@pytest.fixture()
def svc() -> RepairBoundaryService:
    return RepairBoundaryService()


@pytest.fixture()
def client(tmp_path) -> TestClient:
    app = FastAPI()
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())
    app.state.repair_boundary = RepairBoundaryService(db=tmp_path / "repair.sqlite3")
    register_routes(app)
    return TestClient(app)


# ---------- 1. 五类 ALLOWED 通过 ----------

@pytest.mark.parametrize("category", ALLOWED_CATEGORIES)
def test_allowed_categories_pass(svc, category):
    verdict = svc.classify({"category": category, "description": "编译诊断"})
    assert verdict["allowed"] is True
    assert verdict["category"] == category
    assert "候选变更" in verdict["reason"]


# ---------- 2. 七类 FORBIDDEN 拒绝且理由明确 ----------

@pytest.mark.parametrize("category", FORBIDDEN_CATEGORIES)
def test_forbidden_categories_rejected_with_explicit_reason(svc, category):
    verdict = svc.classify({"category": category, "description": "某修复"})
    assert verdict["allowed"] is False
    assert verdict["category"] == category
    assert verdict["reason"] and verdict["reason"] != "unknown fix category"
    assert "禁止" in verdict["reason"]


# ---------- 3. 未知类别默认拒绝（fail-closed） ----------

def test_unknown_category_defaults_to_forbidden(svc):
    for bad in ({"category": "RENAME_EVERYTHING"}, {"category": ""},
                {"category": "block_name_conflict"}, {}):  # 大小写不同也算未知：精确匹配
        verdict = svc.classify(bad)
        assert verdict["allowed"] is False
        assert verdict["reason"] == "unknown fix category"


# ---------- 4. increase_timeout_to_clear_fault 即便「编译通过」也拒 ----------

def test_increase_timeout_rejected_even_when_claiming_compile_pass(svc):
    verdict = svc.classify({"category": "INCREASE_TIMEOUT_TO_CLEAR_FAULT",
                            "description": "编译通过，超时从 3s 加到 9s 即可消除报警",
                            "touches": ["S_EXTEND"]})
    assert verdict["allowed"] is False
    assert "超时" in verdict["reason"]


# ---------- 5. propose：候选回流审查、forbidden_seen、auto_applied 恒空 ----------

def test_propose_whitelisted_diagnostics_yield_review_only_proposals(svc):
    result = svc.propose(PID, [
        {"code": "C001", "message": "block name conflict: FB_X", "block": "FB_X"},
        {"code": "C002", "message": "block FB_Y not called in OB_Main", "block": "FB_Y"},
        {"code": "C003", "message": "type mismatch at input"},
        {"code": "C004", "message": "invalid xml in export"},
        {"code": "C005", "message": "library interface mismatch vs profile"},
    ])
    assert len(result["proposals"]) == 5
    assert all(p["allowed"] is True for p in result["proposals"])
    # §5.2：全部候选修复必须回流人工审查——恒真。
    assert all(p["must_return_to_review"] is True for p in result["proposals"])
    assert {p["fix"]["category"] for p in result["proposals"]} == set(ALLOWED_CATEGORIES)
    assert all(p["fix"]["action"] for p in result["proposals"])
    assert result["auto_applied"] == []
    assert result["forbidden_seen"] == []


def test_propose_registers_forbidden_and_unmapped_without_proposing(svc):
    result = svc.propose(PID, [
        # 显式给出的禁改类别 → forbidden_seen，理由明确。
        {"code": "C100", "message": "timeout still faults", "block": "FB_SEQ",
         "category": "INCREASE_TIMEOUT_TO_CLEAR_FAULT"},
        # 白名单之外的诊断 → 只登记不提议。
        {"code": "C200", "message": "delete interlock to keep line running"},
        {"code": "C300", "message": "sensor intermittently offline"},
    ])
    assert result["proposals"] == []
    assert result["auto_applied"] == []
    assert len(result["forbidden_seen"]) == 3
    explicit = result["forbidden_seen"][0]
    assert explicit["category"] == "INCREASE_TIMEOUT_TO_CLEAR_FAULT"
    assert "超时" in explicit["reason"]
    for entry in result["forbidden_seen"][1:]:
        assert entry["category"] is None  # 不猜类别


def test_propose_auto_applied_always_empty_even_on_clean_compile(svc):
    result = svc.propose(PID, [{"code": "OK", "message": "compile passed"}])
    assert result["proposals"] == [] and result["auto_applied"] == []
    assert len(result["forbidden_seen"]) == 1


# ---------- 6. 持久化 + 历史 ----------

def test_propose_snapshots_persisted(tmp_path):
    db = tmp_path / "repair.sqlite3"
    RepairBoundaryService(db).propose(PID, [{"code": "C1", "message": "name conflict"}])
    history = RepairBoundaryService(db).proposals_for(PID)
    assert len(history) == 1
    assert history[0]["proposals"][0]["fix"]["category"] == "BLOCK_NAME_CONFLICT"
    assert RepairBoundaryService(db).proposals_for("PRJ_OTHER") == []


# ---------- 7. HTTP 路由 + RBAC ----------

def test_http_repair_proposals_route(client):
    r = client.post(f"/api/processos/projects/{PID}/repair-proposals", headers=FE,
                    json={"diagnostics": [{"code": "C1", "message": "name conflict: FB_X"}]})
    assert r.status_code == 200
    data = r.json()
    assert len(data["proposals"]) == 1
    assert data["proposals"][0]["must_return_to_review"] is True
    assert data["auto_applied"] == []
    assert data["proposals"][0]["fix"]["category"] == "BLOCK_NAME_CONFLICT"


def test_http_route_requires_role_and_valid_body(client):
    r = client.post(f"/api/processos/projects/{PID}/repair-proposals",
                    json={"diagnostics": []})
    assert r.status_code == 403  # 无角色头 fail-closed
    r = client.post(f"/api/processos/projects/{PID}/repair-proposals", headers=FE,
                    json={"diagnostics": "not-a-list"})
    assert r.status_code == 422
    r = client.post("/api/processos/projects/PRJ_NOPE/repair-proposals", headers=FE,
                    json={"diagnostics": []})
    assert r.status_code == 404


def test_register_routes_idempotent(tmp_path):
    app = FastAPI()
    app.state.repair_boundary = RepairBoundaryService(db=tmp_path / "r.sqlite3")
    register_routes(app)
    before = len(app.routes)
    register_routes(app)
    assert len(app.routes) == before
