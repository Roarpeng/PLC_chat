"""PLAN §10 最小端到端验收演练：电池更换站夹紧气缸超时变更八关。

端到端走 HTTP API（TestClient + create_app(db, demo_runner=True) + POST /demo
种子）。所有哈希用真实 hashlib 计算，绝不编造；证据非猜测（root_cause 保持
null 直到人工验证）；demo 编译回执如实标注 mocked。

关卡：
1 报警定位（证据链，不猜根因）；2 版本确认（UNVERIFIED_ONLINE 阻断）；
3 变更提案（语义 patch + 影响分析）；4 影响分析（受影响 steps/alarms）；
5 行为仿真（超时/反馈类场景，回归如实暴露）；6 受控审批+构建（RBAC+分离；
§11 语义升级：fault_reset 回归先 409 BEHAVIOR_REGRESSION 阻断构建，
应用 set_scenario_timing 场景同步后重审批放行）；
7 归档验证（job 回执 + PR 9 工件）；8 投产+交接（B3 现场验证 + 台账 + handover）。
负路径：篡改现场块 sha -> DRIFT_DETECTED + frozen。
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.artifacts import BUNDLE_FILE_NAMES

PID = "PRJ_CLAMP"
ENGINEER = {"X-Actor-Id": "engineer_zhao", "X-Actor-Role": "FieldEngineer"}
REVIEWER = {"X-Actor-Id": "reviewer_wang", "X-Actor-Role": "Reviewer"}
BUILDER = {"X-Actor-Id": "builder_li", "X-Actor-Role": "Builder"}
COMMISSIONER = {"X-Actor-Id": "comm_chen", "X-Actor-Role": "CommissioningEngineer"}

_PATCH_BODY = {
    "base_revision": 1,
    "request_id": "chg_019",
    "source": "field_engineer",
    "ops": [{"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms",
             "value": 5000}],
}
_IMPACT_REASON = ("现场反馈伸出到位偶发超过 3s；经工艺评估允许 5s。"
                  "验收标准：extend_timeout 场景复测通过、无互锁/复位行为回归。")


@pytest.fixture(scope="module")
def drill(tmp_path_factory):
    db = tmp_path_factory.mktemp("drill") / "drill.sqlite3"
    app = create_app(ProjectStore(), demo_runner=True, db=db)
    client = TestClient(app)
    r = client.post("/api/processos/demo")
    assert r.status_code == 200, r.text
    state: dict = {"app": app, "client": client}
    yield state
    app.state.trace.close()


# ---------- 关卡 1 · 报警定位 ----------

def test_gate1_alarm_locates_full_evidence_chain(drill):
    client = drill["client"]
    incidents = client.get("/api/processos/incidents").json()["incidents"]
    inc = next(i for i in incidents if i["incident_id"] == "INC-2026-0042")
    # 证据而非猜测：观测事实在，根因保持 null（未验证不升级）
    assert inc["triage"]["fact"] == "伸出反馈未按时出现"
    assert inc["triage"]["root_cause"] is None
    assert inc["behavior"]["observed"] == "extended=false at 3000ms"

    cm = inc["object_id"]
    ctx = client.get(f"/api/processos/objects/{cm}/context").json()
    # physical / AF / behavior / source 四链齐全（按发生时版本解析）
    assert ctx["found"] and ctx["kind"] == "af_cm"
    assert "电池更换站" in ctx["physical_path"]
    assert ctx["af"].get("cm") and ctx["af"].get("em") and ctx["af"].get("unit")
    assert ctx["behavior"], "behavior steps missing from context"
    assert ctx["source_map"] and ctx["source_map"][0]["release_build_id"] == "build_219"
    assert any(d["definition_id"] == "alarm_clamp_timeout"
               for d in ctx["alarm_definitions"])
    drill["cm_id"] = cm
    drill["step_id"] = inc["behavior"]["step_id"]


# ---------- 关卡 2 · 版本确认 ----------

def test_gate2_unknown_plc_state_blocks_change(drill):
    client = drill["client"]
    cmp = client.post(f"/api/processos/projects/{PID}/baselines/compare").json()
    assert cmp["verdict"] == "UNVERIFIED_ONLINE"  # B3 SELF_REPORTED: honest state
    assert cmp["latest_b3"]["verification"] == "SELF_REPORTED"
    assert cmp["latest_b3"]["status"] == "UNVERIFIED_ONLINE"
    assert cmp["latest_b2"]["build_id"] == "build_219"
    assert cmp["latest_b2"]["block_manifest"]  # real per-block sha256 manifest

    gate = client.post(f"/api/processos/projects/{PID}/baselines/gate")
    assert gate.status_code == 409  # 版本未知 -> 阻止自动变更（fail-closed）
    assert gate.json()["code"] == "UNKNOWN_PLC_STATE"


# ---------- 关卡 3 · 变更提案 + 影响分析入口 ----------

def test_gate3_semantic_patch_and_impact(drill):
    client = drill["client"]
    r = client.post(f"/api/processos/projects/{PID}/patches", json=_PATCH_BODY)
    assert r.status_code == 200 and r.json()["revision"] == 2
    assert r.json()["contract"]["operations"][0]["steps"][1]["timeout_ms"] == 5000

    impact = client.post(f"/api/processos/projects/{PID}/impact", json={
        "object_id": drill["cm_id"], "patch_ops": _PATCH_BODY["ops"],
        "reason": _IMPACT_REASON,
    }).json()
    # 运行行为变化 -> 状态保持风险需评估；回归未证实前阻断高风险交付
    assert impact["state_retention_risk"] == "LOW"
    assert impact["blocked_high_risk_delivery"] is True
    assert "regression_tests" in impact["unknown_fields"]
    drill["impact"] = impact


# ---------- 关卡 4 · 影响分析内容 ----------

def test_gate4_impact_covers_steps_and_alarms(drill):
    impact = drill["impact"]
    assert any(s["object_id"] == drill["step_id"] for s in impact["affected"]["steps"])
    assert impact["affected"]["cms"] and impact["affected"]["ems"]
    assert any(d["definition_id"] == "alarm_clamp_timeout"
               for d in impact["alarm_definitions"])
    assert impact["io_db_interfaces"] != ["UNKNOWN"]  # SourceMap 覆盖可推导


# ---------- 关卡 5 · 行为仿真 ----------

def test_gate5_simulation_reports_timeout_and_feedback_scenarios(drill):
    sim = drill["client"].post(f"/api/processos/projects/{PID}/simulate").json()
    by_id = {r["scenario_id"]: r for r in sim["results"]}
    assert {"normal_cycle", "extend_timeout", "retract_timeout",
            "conflicting_feedback", "permit_loss", "fault_reset"} <= set(by_id)
    assert by_id["extend_timeout"]["passed"] and by_id["extend_timeout"]["fault_reason"] == "TIMEOUT"
    assert by_id["conflicting_feedback"]["passed"] \
        and by_id["conflicting_feedback"]["fault_reason"] == "FEEDBACK_FAULT"
    # 诚实回归：timeout 3000->5000 后 fault_reset（Reset@4500 早于新超时）失败，
    # 仿真如实暴露（BEHAVIOR_REGRESSION 证据），绝不静默宣称全绿。
    fr = by_id["fault_reset"]
    assert fr["passed"] is False and fr["fault_reason"] == "TIMEOUT"
    assert any(c["property_id"] == "extend_timeout_causes_fault"
               for c in fr["counterexamples"])
    assert sim["all_passed"] is False


# ---------- 关卡 6 · 受控审批 + 构建（§11：回归先阻断，场景同步后放行） ----------

def test_gate6_regression_blocks_then_scenario_sync_unblocks(drill):
    client = drill["client"]
    client.post(f"/api/processos/projects/{PID}/questions/Q_SAFETY_STOP/resolve",
                json={"resolution": "许可撤销时保持原位，待人工处理", "by": "engineer_zhao"})
    cs = client.post(f"/api/processos/projects/{PID}/changesets").json()
    url = f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve"

    no_role = client.post(url, json={"by": "engineer_zhao"})
    assert no_role.status_code == 403 and no_role.json()["code"] == "ROLE_FORBIDDEN"
    self_approve = client.post(url, headers=ENGINEER | {"X-Actor-Role": "Reviewer"},
                               json={"by": "engineer_zhao"})
    assert self_approve.status_code == 403 \
        and self_approve.json()["code"] == "APPROVER_SEPARATION"

    ap = client.post(url, headers=REVIEWER, json={"by": "engineer_zhao"})
    assert ap.status_code == 200 and ap.json()["by"] == "engineer_zhao"
    # 审批者真实身份（Reviewer 头）进入审计账本（Admin 可查）
    audit = client.get("/api/processos/rbac/audit",
                       headers={"X-Actor-Id": "admin_root", "X-Actor-Role": "Admin"},
                       params={"action": "changeset.approve"}).json()["entries"]
    assert audit and audit[0]["actor_id"] == "reviewer_wang" \
        and audit[0]["role"] == "Reviewer"

    no_builder = client.post(f"/api/processos/projects/{PID}/deliveries")
    assert no_builder.status_code == 403 and no_builder.json()["code"] == "ROLE_FORBIDDEN"

    # ① §11 BEHAVIOR_REGRESSION：关 5 暴露的 fault_reset 回归必须阻断构建
    blocked = client.post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "BEHAVIOR_REGRESSION"
    failed = blocked.json()["details"]["failed_scenarios"]
    assert [f["name"] for f in failed] == ["fault_reset"]
    assert "extend_timeout_causes_fault" in failed[0]["counterexample"]["property_ids"]

    # ② 场景同步修复：timeout 5000 后复位事件必须晚于新超时（5500/5600 > 5000）
    sync = client.post(f"/api/processos/projects/{PID}/patches", json={
        "base_revision": 2, "request_id": "chg_019_sync", "source": "field_engineer",
        "ops": [
            {"op": "set_scenario_timing", "scenario": "fault_reset",
             "index": 4, "field": "t_ms", "value": 5500},
            {"op": "set_scenario_timing", "scenario": "fault_reset",
             "index": 5, "field": "t_ms", "value": 5600},
        ]})
    assert sync.status_code == 200 and sync.json()["revision"] == 3, sync.text

    sim = client.post(f"/api/processos/projects/{PID}/simulate").json()
    assert sim["all_passed"] is True  # 同步后六场景全绿（修复真实生效）

    # ③ 重冻结 + 重审批（旧审批 spec_hash 已过期）→ 构建放行
    cs2 = client.post(f"/api/processos/projects/{PID}/changesets").json()
    ap2 = client.post(f"/api/processos/projects/{PID}/changesets/{cs2['id']}/approve",
                      headers=REVIEWER, json={"by": "engineer_zhao"})
    assert ap2.status_code == 200, ap2.text
    job = client.post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
    assert job.status_code == 200, job.text
    job = job.json()
    assert job["status"] == "SUCCEEDED"
    assert job["evidence_level"] == "mocked"  # 诚实：demo 编译永不冒充真机
    assert job["ob_main_included"] is True
    drill["job"] = job


# ---------- 关卡 7 · 归档验证 + PR 工件 ----------

def test_gate7_artifacts_and_pr_bundle(drill):
    client, job = drill["client"], drill["job"]
    assert job["artifact"] and job["artifact"].get("archive_sha256", "").startswith("sha256:")
    assert job["chain_state"] == "MOCKED_CHAIN_OK"

    bundle = client.post(f"/api/processos/projects/{PID}/pr-bundle").json()
    assert set(bundle["files"]) == set(BUNDLE_FILE_NAMES)
    receipt = json.loads(bundle["files"]["compile_receipt.json"])
    assert receipt["evidence_level"] == "mocked" and receipt["job_id"] == job["id"]
    manifest = json.loads(bundle["files"]["native_artifact_manifest.json"])
    assert manifest["manifest_sha256"] != "UNKNOWN"
    drill["bundle"] = bundle


# ---------- 关卡 8 · 投产 + 交接 ----------

def test_gate8_field_verification_handover_and_match(drill):
    client, job = drill["client"], drill["job"]

    # 现场验证 B3：checksum 用 B2 的真实 archive_sha256（hashlib 派生），对齐 build_219
    baselines = client.get(f"/api/processos/projects/{PID}/baselines").json()["baselines"]
    b2 = max((b for b in baselines if b["kind"] == "B2"), key=lambda b: b["seq"])
    drill["b2"] = b2
    r = client.post(f"/api/processos/projects/{PID}/baselines/b3", json={
        "deployed_build_id": "build_219", "verification": "FIELD_VERIFIED",
        "plc_checksum": b2["archive_sha256"], "device_id": "PLC_1",
        "operator": "comm_chen", "commissioned_at": "2026-11-15T14:00:00+08:00",
    })
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED"
    cmp = client.post(f"/api/processos/projects/{PID}/baselines/compare").json()
    assert cmp["verdict"] == "OK_TO_PROCEED" and cmp["b2_vs_b3"] == "MATCH"

    # 调试台账：无头 403 -> CommissioningEngineer 登记
    artifact_sha = job["artifact"]["archive_sha256"].removeprefix("sha256:")
    assert len(artifact_sha) == 64
    no_role = client.post("/api/processos/deployments/records", json={
        "project_id": PID, "build_id": "build_219", "artifact_sha256": artifact_sha,
        "device_id": "PLC_1", "operator": "comm_chen"})
    assert no_role.status_code == 403 and no_role.json()["code"] == "ROLE_FORBIDDEN"
    rec = client.post("/api/processos/deployments/records", headers=COMMISSIONER, json={
        "project_id": PID, "build_id": "build_219", "artifact_sha256": artifact_sha,
        "device_id": "PLC_1", "operator": "comm_chen", "plc_checksum": b2["archive_sha256"],
        "commissioned_at": "2026-11-15T14:00:00+08:00",
        "tests": [{"name": "extend_timeout 现场复测", "passed": True, "note": "5s 内到位"},
                  {"name": "复位路径复测", "passed": True}],
        "result": "COMMISSIONED"})
    assert rec.status_code == 200 and rec.json()["result"] == "COMMISSIONED"

    # 新工程师交接上下文：位置/AF/行为/源码/历史/行动，无需聊天记录
    ho = client.get("/api/processos/incidents/INC-2026-0042/handover").json()
    assert ho["incident"]["incident_id"] == "INC-2026-0042"
    oc = ho["object_context"]
    assert "电池更换站" in oc["physical_path"] and oc["af"].get("cm")
    assert oc["behavior"] and oc["source_map"]
    assert ho["handover"]["next_action"]  # 行动
    assert "root_cause" in ho["incident"]["triage"]

    # 现场修改上报：块清单与 B2 manifest 一致（真实 sha，来自种子 manifest）-> MATCH 不冻结
    blocks = [{"block_name": name, "content_sha256": sha}
              for name, sha in sorted(b2["block_manifest"].items())]
    fm = client.post(f"/api/processos/projects/{PID}/field-modifications", json={
        "field_state": {"blocks": blocks}, "source": "MANUAL_UPLOAD",
        "captured_at": "2026-11-15T15:00:00+08:00"}).json()
    assert fm["b2_vs_b3"] == "MATCH" and fm["drift_detected"] is False
    assert fm["frozen"] is False and fm["error_code"] is None


# ---------- 负路径 · 现场漂移 ----------

def test_negative_tampered_block_sha_freezes(drill):
    client, b2 = drill["client"], drill["b2"]
    tampered = hashlib.sha256("现场被直接改写的块内容".encode("utf-8")).hexdigest()
    blocks = [{"block_name": name, "content_sha256": tampered if i == 0 else sha}
              for i, (name, sha) in enumerate(sorted(b2["block_manifest"].items()))]
    fm = client.post(f"/api/processos/projects/{PID}/field-modifications", json={
        "field_state": {"blocks": blocks}}).json()
    assert fm["b2_vs_b3"] == "DRIFT" and fm["drift_detected"] is True
    assert fm["frozen"] is True and fm["error_code"] == "DRIFT_DETECTED"
    assert fm["changed_blocks"] and fm["changed_blocks"][0]["reason"] == "content_differs"
