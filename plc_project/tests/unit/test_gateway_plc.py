"""Unit tests for Gateway PLC Intelligence feature API."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENV", "dev")

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
FIXTURE_OB = FIXTURE_DIR / "Blocks" / "Main_OB1.xml"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
    monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(FIXTURE_DIR.parent.resolve()))
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app
    from gateway.app.services import store as mem

    mem.store.plc_jobs.clear()

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
    mem.store.plc_jobs.clear()


def test_plc_job_path_ingest_chat_export(client: TestClient) -> None:
    assert FIXTURE_OB.is_file()
    create = client.post(
        "/api/v1/plc/jobs",
        json={"path": str(FIXTURE_OB), "project_name": "fixture_ob", "publish_graph": False},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert create.status_code == 202, create.text
    job_id = create.json()["data"]["id"]
    assert job_id.startswith("plc_")

    detail = client.get(
        f"/api/v1/plc/jobs/{job_id}",
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["status"] == "ready"
    assert body["blocks"]
    assert body["logic_graph"]["nodes"] or body["knowledge_graph"]["nodes"]
    assert body["export_ready"] is True
    assert isinstance(body.get("coverage"), dict)
    assert "todo_rate" in body["coverage"]
    assert "part_histogram" in body["coverage"]
    assert "language_histogram" in body["coverage"]

    block_name = body["blocks"][0]["name"]
    chat = client.post(
        f"/api/v1/plc/jobs/{job_id}/chat",
        json={"message": "这个块做什么？", "block_name": block_name},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert chat.status_code == 200
    chat_body = chat.json()["data"]
    assert block_name in chat_body["content"]
    assert isinstance(chat_body.get("citations"), list)

    brief = client.get(
        f"/api/v1/plc/jobs/{job_id}/brief",
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert brief.status_code == 200, brief.text
    brief_body = brief.json()["data"]
    assert brief_body["brief_ready"] is True
    assert "purpose" in brief_body
    assert "run_logic_entry" in brief_body
    assert "device_sensor_summary" in brief_body
    assert "block_counts_by_status" in brief_body
    assert "export_gaps" in brief_body
    assert {p["id"] for p in brief_body["engineer_prompts"]} >= {
        "q1_hardware",
        "q2_run_logic",
        "q3_hitl_adjust",
    }

    export = client.get(
        f"/api/v1/plc/jobs/{job_id}/export",
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/zip")
    assert export.content[:2] == b"PK"


def test_plc_job_upload_xml(client: TestClient) -> None:
    data = FIXTURE_OB.read_bytes()
    upload = client.post(
        "/api/v1/plc/jobs/upload",
        files={"file": ("Main_OB1.xml", data, "application/xml")},
        data={"project_name": "upload_ob", "publish_graph": "false"},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert upload.status_code == 202, upload.text
    job_id = upload.json()["data"]["id"]
    detail = client.get(
        f"/api/v1/plc/jobs/{job_id}",
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert detail.json()["data"]["status"] == "ready"


def test_plc_path_denied_outside_allowlist(client: TestClient, tmp_path: Path) -> None:
    outsider = tmp_path / "outside.xml"
    outsider.write_text("<root/>", encoding="utf-8")
    resp = client.post(
        "/api/v1/plc/jobs",
        json={"path": str(outsider)},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 403


def test_plc_upload_zap19(client: TestClient) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "Proj/Blocks/Main_OB1.xml",
            FIXTURE_OB.read_bytes(),
        )
    resp = client.post(
        "/api/v1/plc/jobs/upload",
        files={"file": ("line.zap19", buf.getvalue(), "application/octet-stream")},
        data={"project_name": "zap_demo", "publish_graph": "false"},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["data"]["id"]
    # background may still run; poll briefly
    import time

    detail = None
    for _ in range(40):
        detail = client.get(
            f"/api/v1/plc/jobs/{job_id}",
            headers={"X-API-Key": "ros_ak_test_key"},
        ).json()["data"]
        if detail["status"] in {"ready", "failed"}:
            break
        time.sleep(0.1)
    assert detail is not None
    assert detail["status"] == "ready", detail.get("error")
    assert detail["blocks"]


def test_plc_upload_rejects_bad_suffix(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plc/jobs/upload",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 400


def test_plc_upload_rejects_bare_ap19(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plc/jobs/upload",
        files={"file": ("test1.ap19", b"lone-file", "application/octet-stream")},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    detail = body.get("detail") or body.get("error") or body
    text = str(detail)
    assert "孤立的 TIA 工程" in text or "ap19" in text.lower()


def test_plc_propose_and_writeback_kg_only(client: TestClient, tmp_path: Path) -> None:
    create = client.post(
        "/api/v1/plc/jobs",
        json={"path": str(FIXTURE_OB), "project_name": "wb", "publish_graph": False},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert create.status_code == 202, create.text
    job_id = create.json()["data"]["id"]

    propose = client.post(
        f"/api/v1/plc/jobs/{job_id}/changes",
        json={"message": "注释: writeback unit test", "block_name": "Main"},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    # block name may differ; use first block from detail if needed
    if propose.status_code != 200:
        detail0 = client.get(
            f"/api/v1/plc/jobs/{job_id}",
            headers={"X-API-Key": "ros_ak_test_key"},
        ).json()["data"]
        bname = detail0["blocks"][0]["name"]
        propose = client.post(
            f"/api/v1/plc/jobs/{job_id}/changes",
            json={"message": "注释: writeback unit test", "block_name": bname},
            headers={"X-API-Key": "ros_ak_test_key"},
        )
    assert propose.status_code == 200, propose.text
    assert propose.json()["data"]["ops"]

    # Fake .ap19 under allowlist for path sandbox (Openness import skipped)
    fake_ap = Path(FIXTURE_DIR.parent) / "dummy_writeback.ap19"
    fake_ap.write_bytes(b"not-a-real-tia-project")
    try:
        wb = client.post(
            f"/api/v1/plc/jobs/{job_id}/writeback",
            json={
                "project_path": str(fake_ap),
                "accept_changeset": True,
                "execute_openness_import": False,
            },
            headers={"X-API-Key": "ros_ak_test_key"},
        )
        assert wb.status_code == 200, wb.text
        body = wb.json()["data"]
        assert body["kg_applied"] is True
        assert body["openness"]["skipped"] is True

        detail = client.get(
            f"/api/v1/plc/jobs/{job_id}",
            headers={"X-API-Key": "ros_ak_test_key"},
        ).json()["data"]
        assert detail["changeset"]["status"] in {"accepted", "applied"}
    finally:
        if fake_ap.exists():
            fake_ap.unlink()


def test_plc_optimize_endpoint(client: TestClient) -> None:
    create = client.post(
        "/api/v1/plc/jobs",
        json={"path": str(FIXTURE_DIR), "project_name": "opt", "publish_graph": False},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert create.status_code == 202, create.text
    job_id = create.json()["data"]["id"]
    opt = client.post(
        f"/api/v1/plc/jobs/{job_id}/optimize",
        json={"message": "优化工程逻辑"},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert opt.status_code == 200, opt.text
    data = opt.json()["data"]
    assert "changeset" in data
    assert "ops" in data
    detail = client.get(
        f"/api/v1/plc/jobs/{job_id}",
        headers={"X-API-Key": "ros_ak_test_key"},
    ).json()["data"]
    assert detail.get("changeset")


def test_plc_upload_zip_slip_rejected(client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.xml", "<SW.Blocks.OB/>")
    resp = client.post(
        "/api/v1/plc/jobs/upload",
        files={"file": ("slip.zip", buf.getvalue(), "application/zip")},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 400
