"""§11 显式运行时门禁（缺口 3）：AF_PROFILE_MISMATCH / BEHAVIOR_REGRESSION
在 create_delivery 前强制阻断（HTTP 409 + store 直调 SafetyError 双验证）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.contract import Patch, PatchOp, clamp_contract
from processos.safety.errors import SafetyError

PID = "PRJ_CLAMP"
REVIEWER = {"X-Actor-Id": "reviewer_wang", "X-Actor-Role": "Reviewer"}
BUILDER = {"X-Actor-Id": "builder_li", "X-Actor-Role": "Builder"}

_TIMEOUT_PATCH = {
    "base_revision": 1, "request_id": "chg_040", "source": "field_engineer",
    "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms",
             "value": 5000}],
}
_SYNC_OPS = [
    {"op": "set_scenario_timing", "scenario": "fault_reset",
     "index": 4, "field": "t_ms", "value": 5500},
    {"op": "set_scenario_timing", "scenario": "fault_reset",
     "index": 5, "field": "t_ms", "value": 5600},
]


# ---------- BEHAVIOR_REGRESSION ----------

def test_behavior_regression_blocks_store_level():
    """回归存在时阻断先于 gate 403（§11 优先显式语义）。"""
    store = ProjectStore()
    store.create_project(clamp_contract())
    store.apply_patch(PID, Patch.from_dict(_TIMEOUT_PATCH))
    cs = store.freeze_changeset(PID)
    store.approve(PID, cs["id"], "工程师张三")  # 已审批：非 gate 403 场景
    with pytest.raises(SafetyError) as ei:
        store.create_delivery(PID)
    exc = ei.value
    assert exc.code == "BEHAVIOR_REGRESSION" and exc.http_status == 409
    failed = exc.details["failed_scenarios"]
    assert [f["name"] for f in failed] == ["fault_reset"]
    assert "extend_timeout_causes_fault" in failed[0]["counterexample"]["property_ids"]


def test_behavior_regression_http_shape_then_sync_unblocks(tmp_path):
    app = create_app(ProjectStore(), db=tmp_path / "beh.sqlite3")
    client = TestClient(app)
    try:
        r = client.post("/api/processos/projects", json={
            "contract": clamp_contract().to_dict()})
        assert r.status_code == 200
        client.post(f"/api/processos/projects/{PID}/questions/Q_SAFETY_STOP/resolve",
                    json={"resolution": "保持原位", "by": "engineer_zhao"})
        client.post(f"/api/processos/projects/{PID}/patches", json=_TIMEOUT_PATCH)
        cs = client.post(f"/api/processos/projects/{PID}/changesets").json()
        assert client.post(
            f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve",
            headers=REVIEWER, json={"by": "engineer_zhao"}).status_code == 200

        blocked = client.post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
        assert blocked.status_code == 409, blocked.text
        body = blocked.json()
        assert body["code"] == "BEHAVIOR_REGRESSION"
        assert body["details"]["failed_scenarios"][0]["name"] == "fault_reset"
        assert len(app.state.store.projects[PID].jobs) == 0  # 未创建任何 job

        # 场景同步 -> 重新走查放行（与 §10 演练同一语义）
        sync = client.post(f"/api/processos/projects/{PID}/patches", json={
            "base_revision": 2, "request_id": "chg_040_sync",
            "source": "field_engineer", "ops": _SYNC_OPS})
        assert sync.status_code == 200 and sync.json()["revision"] == 3
        cs2 = client.post(f"/api/processos/projects/{PID}/changesets").json()
        assert client.post(
            f"/api/processos/projects/{PID}/changesets/{cs2['id']}/approve",
            headers=REVIEWER, json={"by": "engineer_zhao"}).status_code == 200
        ok = client.post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
        assert ok.status_code == 200 and ok.json()["status"] == "QUEUED"
    finally:
        app.state.trace.close()


# ---------- AF_PROFILE_MISMATCH ----------

def _approved_store() -> tuple[ProjectStore, str]:
    store = ProjectStore()
    store.create_project(clamp_contract(with_blocking_question=False))
    cs = store.freeze_changeset(PID)
    store.approve(PID, cs["id"], "工程师张三")
    return store, cs["id"]


def test_af_profile_mismatch_on_tampered_frozen_template():
    store, cs_id = _approved_store()
    store.projects[PID].changesets[cs_id]["template_sha256"] = "sha256:tampered"
    with pytest.raises(SafetyError) as ei:
        store.create_delivery(PID)
    assert ei.value.code == "AF_PROFILE_MISMATCH" and ei.value.http_status == 409
    d = ei.value.details
    assert d["frozen_template_sha256"] == "sha256:tampered"
    assert d["current_template_sha256"] != "sha256:tampered"
    assert d["changeset_id"] == cs_id


def test_af_profile_mismatch_on_unregistered_profile():
    store, _ = _approved_store()
    store.projects[PID].profile_id = "GHOST_PROFILE"  # 注册表已无此 profile
    with pytest.raises(SafetyError) as ei:
        store.create_delivery(PID)
    assert ei.value.code == "AF_PROFILE_MISMATCH"
    assert ei.value.details["profile_id"] == "GHOST_PROFILE"


def test_af_profile_mismatch_on_legacy_changeset_without_template_record():
    """旧 changeset 未记录 template_sha256 -> 按 UNKNOWN 比对失败（fail-closed）。"""
    store, cs_id = _approved_store()
    del store.projects[PID].changesets[cs_id]["template_sha256"]
    with pytest.raises(SafetyError) as ei:
        store.create_delivery(PID)
    assert ei.value.code == "AF_PROFILE_MISMATCH"
    assert ei.value.details["frozen_template_sha256"] == "UNKNOWN"


def test_af_profile_mismatch_http_shape(tmp_path):
    app = create_app(ProjectStore(), db=tmp_path / "afp.sqlite3")
    client = TestClient(app)
    try:
        assert client.post("/api/processos/projects", json={
            "contract": clamp_contract(with_blocking_question=False).to_dict()}).status_code == 200
        cs = client.post(f"/api/processos/projects/{PID}/changesets").json()
        assert client.post(
            f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve",
            headers=REVIEWER, json={"by": "engineer_zhao"}).status_code == 200
        state = app.state.store.projects[PID]
        state.changesets[cs["id"]]["template_sha256"] = "sha256:tampered"

        r = client.post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "AF_PROFILE_MISMATCH"
        assert "tampered" in r.json()["error"] or \
            r.json()["details"]["frozen_template_sha256"] == "sha256:tampered"
    finally:
        app.state.trace.close()


def test_clean_profile_passes_gate_and_delivers():
    from processos.native import make_demo_runner

    store = ProjectStore()
    store.runner = make_demo_runner()
    store.create_project(clamp_contract(with_blocking_question=False))
    cs = store.freeze_changeset(PID)
    store.approve(PID, cs["id"], "工程师张三")
    job = store.create_delivery(PID)  # 门禁不误伤：干净流程照常交付
    assert job["status"] == "SUCCEEDED"
