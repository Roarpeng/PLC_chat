"""§8 `POST /changesets/{csid}/preview`（缺口 1）：冻结后预览，不改状态。

semantic_diff 用打补丁时记录的真实前后值；impact 用 changeset 自己的 ops
（subject = 首个 op target 对应对象）；test_plan 来自契约场景；取不到的
字段显式 UNKNOWN，未 freeze 的 id → 404。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app

PID = "PRJ_CLAMP"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    app = create_app(ProjectStore(), db=tmp_path_factory.mktemp("preview") / "pv.sqlite3")
    client = TestClient(app)
    r = client.post("/api/processos/demo")
    assert r.status_code == 200, r.text
    yield {"app": app, "client": client, "pid": r.json()["project_id"]}
    app.state.trace.close()


_PATCH = {
    "base_revision": 1, "request_id": "chg_020", "source": "field_engineer",
    "ops": [
        {"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms", "value": 5000},
        {"op": "set_scenario_timing", "scenario": "fault_reset",
         "index": 4, "field": "t_ms", "value": 5500},
    ],
}


def test_preview_semantic_diff_impact_and_test_plan(env):
    client, pid = env["client"], env["pid"]
    assert client.post(f"/api/processos/projects/{pid}/patches",
                       json=_PATCH).status_code == 200
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    r = client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/preview")
    assert r.status_code == 200, r.text
    pv = r.json()

    assert pv["changeset_id"] == cs["id"]
    assert pv["created_at"] != "UNKNOWN" and pv["revision"] == 2

    diff = pv["semantic_diff"]
    assert diff[0]["op"] == "set"
    assert diff[0]["target"].endswith("S_EXTEND/timeout_ms")
    assert diff[0]["before"] == 3000 and diff[0]["after"] == 5000  # 真实前后值
    assert diff[1]["target"].endswith("/scenarios/fault_reset/inputs/4/t_ms")
    assert diff[1]["before"] == 4500 and diff[1]["after"] == 5500

    # impact：来自 changeset 的 ops；subject 解析到首个 op target（S_EXTEND）
    impact = pv["impact"]
    assert impact["report_id"].startswith("imp_")
    assert impact["subject"]["reason"].startswith("changeset preview")
    extend_id = env["app"].state.trace.ids_for(pid).get("S_EXTEND", "")
    assert extend_id and impact["subject"]["object_id"] == extend_id
    assert extend_id in {s["object_id"] for s in impact["affected"]["steps"]}
    assert impact["affected"]["steps"] and impact["affected"]["cms"]

    # test_plan：契约场景 -> [{name, purpose}]
    names = {t["name"] for t in pv["test_plan"]}
    assert names == {"正常循环", "伸出超时", "缩回超时", "矛盾反馈",
                     "运行许可丢失", "故障复位"}
    assert all(t["purpose"] for t in pv["test_plan"])


def test_preview_is_readonly_and_snapshot_stable(env):
    """preview 不改契约状态；freeze 后再 patch，旧 changeset 预览不变。"""
    client, pid = env["client"], env["pid"]
    cs1 = client.post(f"/api/processos/projects/{pid}/changesets").json()
    before = client.post(
        f"/api/processos/projects/{pid}/changesets/{cs1['id']}/preview").json()
    # 冻结后继续变更（revision bump），旧 changeset 的 diff 快照保持
    later = client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 2, "request_id": "chg_021",
        "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_RETRACT/timeout_ms",
                 "value": 4000}]})
    assert later.status_code == 200 and later.json()["revision"] == 3
    after = client.post(
        f"/api/processos/projects/{pid}/changesets/{cs1['id']}/preview").json()
    assert after["semantic_diff"] == before["semantic_diff"]
    assert len(after["semantic_diff"]) == 2  # 不包含冻结后的 retract 变更


def test_preview_empty_changeset_marks_impact_unknown(env):
    """无任何记录变更的 changeset：semantic_diff []、impact 显式 UNKNOWN。"""
    client, pid = env["client"], env["pid"]
    bare = client.post("/api/processos/projects", json={
        "contract": {"id": "PRJ_BARE", "name": "空变更",
                     "target_framework": "siemens-af-basic@unverified",
                     "resources": [], "operations": [], "scenarios": []}})
    assert bare.status_code == 200, bare.text
    cs = client.post("/api/processos/projects/PRJ_BARE/changesets").json()
    pv = client.post(
        f"/api/processos/projects/PRJ_BARE/changesets/{cs['id']}/preview").json()
    assert pv["semantic_diff"] == []
    assert pv["impact"]["impact_report"] == "UNKNOWN"
    assert pv["test_plan"] == []  # 无场景 -> 空计划（不伪造）


def test_preview_unknown_changeset_or_project_404(env):
    client, pid = env["client"], env["pid"]
    assert client.post(
        f"/api/processos/projects/{pid}/changesets/CS-NOPE/preview").status_code == 404
    assert client.post(
        "/api/processos/projects/NOPE/changesets/CS-1/preview").status_code == 404
