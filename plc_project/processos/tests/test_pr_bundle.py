"""PLAN §12 PR 工件测试：9 类工件齐全、mock 证据如实、UNKNOWN 显式、404。

demo runner 的 compile_receipt 必须带 ``evidence_level="mocked"``（诚实标注），
取不到的工件字段显式 UNKNOWN，绝不编造。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.artifacts import BUNDLE_FILE_NAMES
from processos.contract import clamp_contract

REVIEWER = {"X-Actor-Id": "reviewer_wang", "X-Actor-Role": "Reviewer"}
BUILDER = {"X-Actor-Id": "builder_li", "X-Actor-Role": "Builder"}


@pytest.fixture()
def env(tmp_path):
    app = create_app(ProjectStore(), demo_runner=True, db=tmp_path / "prb.sqlite3")
    client = TestClient(app)
    r = client.post("/api/processos/demo")
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    yield {"app": app, "client": client, "pid": pid}
    app.state.trace.close()


def _deliver_ok(client, pid):
    """§11 语义（BEHAVIOR_REGRESSION 门禁）下的可交付流：变更补丁必须同步
    携带场景同步 ops（fault_reset 复位事件 5500/5600 晚于新超时 5000），
    否则 deliveries 会被 409 BEHAVIOR_REGRESSION 阻断。"""
    client.post(f"/api/processos/projects/{pid}/questions/Q_SAFETY_STOP/resolve",
                json={"resolution": "许可撤销时保持原位，待人工处理", "by": "engineer_zhao"})
    client.post(f"/api/processos/projects/{pid}/patches", json={
        "base_revision": 1, "request_id": "chg_019",
        "ops": [
            {"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms", "value": 5000},
            {"op": "set_scenario_timing", "scenario": "fault_reset",
             "index": 4, "field": "t_ms", "value": 5500},
            {"op": "set_scenario_timing", "scenario": "fault_reset",
             "index": 5, "field": "t_ms", "value": 5600},
        ],
    })
    cs = client.post(f"/api/processos/projects/{pid}/changesets").json()
    ap = client.post(f"/api/processos/projects/{pid}/changesets/{cs['id']}/approve",
                     headers=REVIEWER, json={"by": "engineer_zhao"})
    assert ap.status_code == 200, ap.text
    job = client.post(f"/api/processos/projects/{pid}/deliveries", headers=BUILDER)
    assert job.status_code == 200, job.text
    return job.json()


def test_bundle_has_all_nine_artifacts_with_honest_mocked_receipt(env):
    client, pid = env["client"], env["pid"]
    job = _deliver_ok(client, pid)
    assert job["status"] == "SUCCEEDED"

    r = client.post(f"/api/processos/projects/{pid}/pr-bundle")
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert set(bundle["files"]) == set(BUNDLE_FILE_NAMES)  # exactly the §12 nine
    assert bundle["bundle_id"].startswith("prb_")
    assert bundle["generated_at"]

    # every file non-empty; the markdown names contract/revision/profile
    for name, text in bundle["files"].items():
        assert isinstance(text, str) and text.strip(), name
    md = bundle["files"]["design_change.md"]
    assert "PRJ_CLAMP" in md and "revision" in md and "profile" in md

    # compile receipt: demo runner stays mocked — never a real compile claim
    receipt = json.loads(bundle["files"]["compile_receipt.json"])
    assert receipt["job_id"] == job["id"]
    assert receipt["evidence_level"] == "mocked"
    assert receipt["status"] == "SUCCEEDED"
    assert "mocked" in receipt["note"]

    # real derived artifacts, not fabricated
    compliance = json.loads(bundle["files"]["af_compliance.json"])
    assert compliance["errors"] == []
    behavior = json.loads(bundle["files"]["behavior_test_report.json"])
    assert len(behavior["results"]) == 6
    assert all(r["evidence_level"] == "simulated" for r in behavior["results"])
    # honest report: the change patch carries its scenario-sync ops (§11 gate
    # requires it) — after the retimed fault_reset (Reset@5500 > timeout 5000)
    # all six scenarios pass; nothing is hidden, the sync is in the patch ops.
    fr = next(r for r in behavior["results"] if r["scenario_id"] == "fault_reset")
    assert fr["passed"] is True and fr["fault_reason"] == ""
    assert behavior["all_passed"] is True
    sm = json.loads(bundle["files"]["source_map.json"])
    assert sm["builds"] == ["build_219"] and sm["source_map"]
    impact = json.loads(bundle["files"]["impact_report.json"])
    assert impact["project_id"] == pid and impact["report_id"].startswith("imp_")
    diff = json.loads(bundle["files"]["semantic_diff.json"])
    assert diff["latest_patch_ops"] and \
        diff["latest_patch_ops"][0]["path"].endswith("S_EXTEND/timeout_ms")
    assert diff["patches"] and diff["patches"][-1]["request_id"] == "chg_019"
    manifest = json.loads(bundle["files"]["native_artifact_manifest.json"])
    assert manifest["manifest_sha256"] and manifest["artifact"] is not None
    handover = json.loads(bundle["files"]["handover_snapshot.json"])
    assert any(i["incident_id"] == "INC-2026-0042" for i in handover["incidents"])


def test_bundle_marks_missing_evidence_unknown(tmp_path):
    """A project with no delivery job shows explicit UNKNOWN, never a guess."""
    app = create_app(db=tmp_path / "bare.sqlite3")
    client = TestClient(app)
    r = client.post("/api/processos/projects", json={"contract": clamp_contract().to_dict()})
    pid = r.json()["project_id"]
    try:
        bundle = client.post(f"/api/processos/projects/{pid}/pr-bundle").json()
        receipt = json.loads(bundle["files"]["compile_receipt.json"])
        assert receipt["evidence_level"] == "UNKNOWN"
        assert receipt["job_id"] == "UNKNOWN"
        manifest = json.loads(bundle["files"]["native_artifact_manifest.json"])
        assert manifest["manifest_sha256"] == "UNKNOWN" and manifest["artifact"] == "UNKNOWN"
        handover = json.loads(bundle["files"]["handover_snapshot.json"])
        assert handover["handover_context"] == "UNKNOWN"
    finally:
        app.state.trace.close()


def test_bundle_unknown_project_404(env):
    r = env["client"].post("/api/processos/projects/NOPE/pr-bundle")
    assert r.status_code == 404


def test_bundle_index_persisted_and_retrievable(env):
    client, pid = env["client"], env["pid"]
    _deliver_ok(client, pid)
    bundle = client.post(f"/api/processos/projects/{pid}/pr-bundle").json()
    again = client.get(f"/api/processos/pr-bundles/{bundle['bundle_id']}")
    assert again.status_code == 200
    assert again.json()["files"] == bundle["files"]
    assert client.get("/api/processos/pr-bundles/prb_nope").status_code == 404
