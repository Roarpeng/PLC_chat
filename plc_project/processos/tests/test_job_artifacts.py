"""§8 工件下载端点（缺口 2）：job 详情、真实 .zap19 下载（防穿越）、
pr-bundle 文件取回。mock 链无真实归档文件 → 422 BUILD_ARTIFACT_MISMATCH。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processos.api import ProjectStore, create_app
from processos.artifacts import BUNDLE_FILE_NAMES

PID = "PRJ_CLAMP"
REVIEWER = {"X-Actor-Id": "reviewer_wang", "X-Actor-Role": "Reviewer"}
BUILDER = {"X-Actor-Id": "builder_li", "X-Actor-Role": "Builder"}

_PATCH = {
    "base_revision": 1, "request_id": "chg_030", "source": "field_engineer",
    "ops": [
        {"op": "set", "path": "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms", "value": 5000},
        {"op": "set_scenario_timing", "scenario": "fault_reset",
         "index": 4, "field": "t_ms", "value": 5500},
        {"op": "set_scenario_timing", "scenario": "fault_reset",
         "index": 5, "field": "t_ms", "value": 5600},
    ],
}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    app = create_app(ProjectStore(), demo_runner=True,
                     db=tmp_path_factory.mktemp("art") / "art.sqlite3")
    client = TestClient(app)
    r = client.post("/api/processos/demo")
    assert r.status_code == 200, r.text
    client.post(f"/api/processos/projects/{PID}/questions/Q_SAFETY_STOP/resolve",
                json={"resolution": "保持原位", "by": "engineer_zhao"})
    assert client.post(f"/api/processos/projects/{PID}/patches",
                       json=_PATCH).status_code == 200
    cs = client.post(f"/api/processos/projects/{PID}/changesets").json()
    ap = client.post(f"/api/processos/projects/{PID}/changesets/{cs['id']}/approve",
                     headers=REVIEWER, json={"by": "engineer_zhao"})
    assert ap.status_code == 200, ap.text
    yield {"app": app, "client": client}
    app.state.trace.close()


def _deliver(env) -> dict:
    r = env["client"].post(f"/api/processos/projects/{PID}/deliveries", headers=BUILDER)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- job 详情 ----------

def test_job_detail_transparent_with_artifact_summary(env):
    client = env["client"]
    job = _deliver(env)
    r = client.get(f"/api/processos/projects/{PID}/jobs/{job['id']}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["id"] == job["id"]
    assert detail["status"] == "SUCCEEDED"
    assert detail["evidence_level"] == "mocked"
    summary = detail["artifact_summary"]
    assert summary is not None
    assert summary["archive_sha256"].startswith("sha256:")
    assert summary["evidence_level"] == "mocked"
    assert summary["kind"] == "zap19"

    assert client.get(f"/api/processos/projects/{PID}/jobs/JOB-NOPE").status_code == 404
    assert client.get("/api/processos/projects/NOPE/jobs/JOB-X").status_code == 404


# ---------- artifact 下载 ----------

def test_mock_job_artifact_is_honest_422(env):
    """demo/mock 链：artifact 记录是假的（C:/demo/proj.zap19），无真实文件 → 422。"""
    client = env["client"]
    job = _deliver(env)
    r = client.get(f"/api/processos/projects/{PID}/jobs/{job['id']}/artifact")
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "BUILD_ARTIFACT_MISMATCH"
    assert body["error"] == "demo chain produces no native archive"
    assert client.get(f"/api/processos/projects/{PID}/jobs/JOB-NOPE/artifact").status_code == 404
    assert client.get("/api/processos/projects/NOPE/jobs/JOB-X/artifact").status_code == 404


def test_real_workspace_archive_downloads_and_traversal_rejected(env):
    client = env["client"]
    job = _deliver(env)
    workspace = Path(job["workspace_dir"])
    archive_dir = workspace / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    payload = b"PK\x03\x04fake-but-real-file-on-disk"
    (archive_dir / f"{PID}.zap19").write_bytes(payload)

    r = client.get(f"/api/processos/projects/{PID}/jobs/{job['id']}/artifact")
    assert r.status_code == 200, r.text
    assert r.content == payload  # 下载到的是 workspace 内的真实文件

    # 篡改 artifact 记录指向 workspace 外的真实文件（绝对路径）→ 拒绝。
    # 先移除 workspace 内真实归档，确保 422 只可能来自穿越拒绝。
    (archive_dir / f"{PID}.zap19").unlink()
    outside = workspace.parent / "outside.zap19"
    outside.write_bytes(b"secret-outside")
    state = env["app"].state.store.projects[PID]
    try:
        state.jobs[job["id"]]["artifact"]["archive_path"] = str(outside)
        r2 = client.get(f"/api/processos/projects/{PID}/jobs/{job['id']}/artifact")
        assert r2.status_code == 422 and r2.json()["code"] == "BUILD_ARTIFACT_MISMATCH"
        assert r2.content[:5] != b"secre"  # 绝不泄出 workspace 外内容

        # ../ 形式穿越（解析后落在 workspace 外）→ 拒绝，绝不泄出
        dodgy = str(archive_dir / ".." / ".." / "outside.zap19")
        state.jobs[job["id"]]["artifact"]["archive_path"] = dodgy
        r3 = client.get(f"/api/processos/projects/{PID}/jobs/{job['id']}/artifact")
        assert r3.status_code == 422 and r3.json()["code"] == "BUILD_ARTIFACT_MISMATCH"
    finally:
        outside.unlink(missing_ok=True)
        state.jobs[job["id"]]["artifact"]["archive_path"] = "C:/demo/proj.zap19"
    r4 = client.get(f"/api/processos/projects/{PID}/jobs/{job['id']}/artifact")
    assert r4.status_code == 422 and r4.json()["code"] == "BUILD_ARTIFACT_MISMATCH"


# ---------- pr-bundle 文件取回 ----------

def test_pr_bundle_file_roundtrip_and_content_types(env):
    client = env["client"]
    _deliver(env)  # ensure a job exists so the bundle has real receipts
    bundle = client.post(f"/api/processos/projects/{PID}/pr-bundle").json()
    assert set(bundle["files"]) == set(BUNDLE_FILE_NAMES)

    for name in BUNDLE_FILE_NAMES:
        r = client.get(f"/api/processos/pr-bundles/{bundle['bundle_id']}/files/{name}")
        assert r.status_code == 200, name
        assert r.text == bundle["files"][name]  # 取回与生成逐字一致

    md = client.get(f"/api/processos/pr-bundles/{bundle['bundle_id']}/files/design_change.md")
    assert md.headers["content-type"].startswith("text/markdown")
    js = client.get(f"/api/processos/pr-bundles/{bundle['bundle_id']}/files/semantic_diff.json")
    assert js.headers["content-type"].startswith("application/json")

    # bundle / 文件不存在 → 404；文件名始终按 bundle 记录查表（无文件系统穿越面）
    assert client.get("/api/processos/pr-bundles/prb_nope/files/design_change.md").status_code == 404
    assert client.get(
        f"/api/processos/pr-bundles/{bundle['bundle_id']}/files/not_a_file.md").status_code == 404
    assert client.get(
        f"/api/processos/pr-bundles/{bundle['bundle_id']}/files/..%2Fdesign_change.md"
    ).status_code == 404
