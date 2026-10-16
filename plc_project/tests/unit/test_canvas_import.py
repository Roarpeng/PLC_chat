"""Unit tests for TIA Portal Openness export -> interactive Canvas import."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.app.services.plc.canvas_import import (
    CanvasImportRejected,
    import_canvas_from_path,
)
from plc_engine.canvas_model import CanvasState

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"


def test_import_progress_stages_reported() -> None:
    stages: list[str] = []

    def on_progress(stage: str, message: str, **_extra) -> None:
        stages.append(stage)

    data = import_canvas_from_path(
        FIXTURE_DIR, project_name="progress_project", on_progress=on_progress
    )
    assert data["blocks_parsed"] >= 3
    assert "start" in stages
    assert "parse" in stages
    assert "done" in stages


def test_import_canvas_from_export_directory() -> None:
    data = import_canvas_from_path(FIXTURE_DIR, project_name="fixture_project")

    # Blocks/FB_Motor.xml + Blocks/DB_MotorInst.xml + Blocks/Main_OB1.xml
    assert data["blocks_parsed"] >= 3
    # TagTables/HMI.xml (StartCmd, StopCmd) + TagTables/Safety.xml (FaultOk)
    assert data["tags_parsed"] >= 3
    assert data["skipped"] == []

    canvas = data["canvas"]
    assert canvas["project_name"] == "fixture_project"
    assert canvas["hmi_widgets"] == {}

    blocks = canvas["blocks"]
    assert {"FB_Motor", "MotorInst", "Main"} <= set(blocks)

    fb = blocks["FB_Motor"]
    assert fb["block_type"] == "FB"
    assert fb["number"] == 100
    assert fb["language"] == "LAD"
    assert fb["comment"] == "Motor control with self-holding circuit"
    assert fb["status"] == "synced"
    iface = {v["name"]: v for v in fb["interface"]}
    assert iface["Start"]["section"] == "VAR_INPUT"
    assert iface["Start"]["data_type"] == "Bool"
    assert iface["Start"]["comment"] == "Start pushbutton NO"
    assert iface["Stop"]["section"] == "VAR_INPUT"
    assert iface["Running"]["section"] == "VAR_OUTPUT"

    assert len(fb["networks"]) == 1
    net = fb["networks"][0]
    assert net["title"] == "Self-holding motor start"
    assert net["language"] == "LAD"
    assert net["status"] == "synced"
    # NetworkTranslator fills IEC-style SCL (not the old graphic placeholder).
    assert "Running" in net["scl_text"] and "Start" in net["scl_text"] and "Stop" in net["scl_text"]
    assert ":=" in net["scl_text"] or "图形" in net["scl_text"]
    assert fb["scl_body"], "full-block translate_block_to_scl body should populate scl_body"

    db = blocks["MotorInst"]
    assert db["block_type"] == "DB"
    assert db["number"] == 200
    assert db["comment"] == "Background instance of FB_Motor"
    assert db["status"] == "synced"
    assert {v["name"] for v in db["interface"]} == {"Start", "Stop", "Fault", "Running"}
    assert all(v["section"] == "VAR" for v in db["interface"])

    ob = blocks["Main"]
    assert ob["block_type"] == "OB"
    assert ob["number"] == 1
    assert ob["comment"] == "Cyclic main OB"
    ob_net = ob["networks"][0]
    assert ob_net["title"] == "Run motor control"
    # NetworkTranslator emits Siemens SCL quoted namespaces: "HMI".StartCmd
    assert "StartCmd" in ob_net["scl_text"]
    assert "FaultOk" in ob_net["scl_text"]
    assert "MotorInst" in ob_net["scl_text"]

    tags = canvas["tags"]
    assert {"StartCmd", "StopCmd", "FaultOk"} <= set(tags)
    assert tags["StartCmd"]["data_type"] == "Bool"
    assert tags["StartCmd"]["logical_address"] == "%I0.0"
    assert tags["StartCmd"]["comment"] == "HMI start pushbutton"

    # Round-trip: the payload must be consumable by the other canvas endpoints.
    state = CanvasState.from_dict(canvas)
    assert state.blocks["FB_Motor"].number == 100
    assert state.tags["FaultOk"].logical_address == "%I0.4"


def test_import_canvas_single_block_file_default_project_name() -> None:
    data = import_canvas_from_path(FIXTURE_DIR / "Blocks" / "FB_Motor.xml")
    assert data["blocks_parsed"] == 1
    assert data["tags_parsed"] == 0
    assert data["skipped"] == []
    assert data["canvas"]["project_name"] == "FB_Motor"
    assert set(data["canvas"]["blocks"]) == {"FB_Motor"}


def test_import_canvas_rejects_directory_without_parseable_files(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("not an xml export", encoding="utf-8")
    (tmp_path / "empty.xml").write_text("<root><not-a-block/></root>", encoding="utf-8")
    with pytest.raises(CanvasImportRejected) as exc_info:
        import_canvas_from_path(tmp_path)
    assert exc_info.value.code == "NO_PARSEABLE_FILES"


def test_import_canvas_apxx_requires_openness_export(tmp_path: Path) -> None:
    fake_ap = tmp_path / "demo.ap19"
    fake_ap.write_bytes(b"not-a-real-tia-project")
    with pytest.raises(CanvasImportRejected) as exc_info:
        import_canvas_from_path(fake_ap)
    assert exc_info.value.code == "OPENNESS_EXPORT_REQUIRED"
    assert "请先在博图中通过 Openness 导出块 XML 或直接提供导出目录" in exc_info.value.message


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
    monkeypatch.setenv("PLC_PATH_ALLOWLIST", str(FIXTURE_DIR.parent.resolve()))
    monkeypatch.setenv("PLC_WORK_DIR", str(tmp_path / "plc_work"))
    from fastapi.testclient import TestClient

    from gateway.app.config import get_settings

    get_settings.cache_clear()
    from gateway.app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_canvas_import_endpoint_directory(client) -> None:
    resp = client.post(
        "/api/v1/plc/canvas/import",
        json={"path": str(FIXTURE_DIR), "project_name": "via_endpoint"},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["blocks_parsed"] >= 3
    assert data["tags_parsed"] >= 3
    assert data["skipped"] == []
    assert data["canvas"]["project_name"] == "via_endpoint"
    assert {"FB_Motor", "MotorInst", "Main"} <= set(data["canvas"]["blocks"])


def test_canvas_import_endpoint_denied_outside_allowlist(client, tmp_path: Path) -> None:
    outsider = tmp_path / "outside.xml"
    outsider.write_text("<root/>", encoding="utf-8")
    resp = client.post(
        "/api/v1/plc/canvas/import",
        json={"path": str(outsider)},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PLC_PATH_DENIED"


# ---------------------------------------------------------------------------
# .zap*/.zip archive import + /canvas/import/upload endpoint
# ---------------------------------------------------------------------------


def _fixture_xml_zip_bytes() -> bytes:
    """Flat ZIP of every fixture SimaticML XML (no directory structure)."""
    import io
    import zipfile

    buf = io.BytesIO()
    xml_files = sorted(FIXTURE_DIR.rglob("*.xml"))
    assert xml_files, f"fixture XML exports missing under {FIXTURE_DIR}"
    with zipfile.ZipFile(buf, "w") as zf:
        for xml in xml_files:
            zf.writestr(xml.name, xml.read_bytes())
    return buf.getvalue()


def test_import_canvas_from_zip_archive_of_exports(tmp_path: Path) -> None:
    demo_zip = tmp_path / "demo.zip"
    demo_zip.write_bytes(_fixture_xml_zip_bytes())

    data = import_canvas_from_path(demo_zip)

    assert data["blocks_parsed"] >= 3
    assert data["tags_parsed"] >= 2
    assert data["skipped"] == []
    # project_name defaults to the archive file name minus suffix
    assert data["canvas"]["project_name"] == "demo"
    assert {"FB_Motor", "MotorInst", "Main"} <= set(data["canvas"]["blocks"])
    assert {"StartCmd", "StopCmd", "FaultOk"} <= set(data["canvas"]["tags"])


def test_import_canvas_from_zap19_with_incomplete_project(tmp_path: Path) -> None:
    import zipfile

    zap = tmp_path / "fake.zap19"
    with zipfile.ZipFile(zap, "w") as zf:
        zf.writestr("Bin/", "")  # empty directory entry
        zf.writestr("Demo.ap19", b"")  # fake empty project file, not a real tree

    with pytest.raises(CanvasImportRejected) as exc_info:
        import_canvas_from_path(zap)
    assert exc_info.value.code == "OPENNESS_EXPORT_REQUIRED"
    # Either direct packaging guidance or the Openness-failure guidance.
    assert (
        "孤立的 TIA 工程文件" in exc_info.value.message
        or "Openness 导出失败" in exc_info.value.message
    )


def test_import_canvas_from_archive_without_parseable_content(tmp_path: Path) -> None:
    import zipfile

    zap = tmp_path / "empty.zip"
    with zipfile.ZipFile(zap, "w") as zf:
        zf.writestr("notes.txt", "no xml, no apxx")

    with pytest.raises(CanvasImportRejected) as exc_info:
        import_canvas_from_path(zap)
    assert exc_info.value.code == "NO_PARSEABLE_FILES"


def test_import_canvas_directory_with_project_tree_requires_openness(tmp_path: Path) -> None:
    # .zap-style unpacked project folder: .ap19 + System/ sidecar, no SimaticML XML.
    project_dir = tmp_path / "Demo"
    project_dir.mkdir()
    (project_dir / "System").mkdir()
    (project_dir / "Demo.ap19").write_bytes(b"fake-binary-project")

    with pytest.raises(CanvasImportRejected) as exc_info:
        import_canvas_from_path(project_dir)
    assert exc_info.value.code == "OPENNESS_EXPORT_REQUIRED"


def test_canvas_import_upload_endpoint_zip(client) -> None:
    resp = client.post(
        "/api/v1/plc/canvas/import/upload",
        files={"file": ("demo.zip", _fixture_xml_zip_bytes(), "application/zip")},
        data={"project_name": "uploaded"},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["blocks_parsed"] >= 3
    assert data["tags_parsed"] >= 2
    assert data["skipped"] == []
    assert data["canvas"]["project_name"] == "uploaded"
    assert {"FB_Motor", "MotorInst", "Main"} <= set(data["canvas"]["blocks"])
    assert {"StartCmd", "StopCmd", "FaultOk"} <= set(data["canvas"]["tags"])


def test_canvas_import_upload_endpoint_rejects_bare_apxx(client) -> None:
    resp = client.post(
        "/api/v1/plc/canvas/import/upload",
        files={"file": ("demo.ap19", b"not-a-real-project", "application/octet-stream")},
        data={"project_name": ""},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "PLC_UPLOAD_INVALID"


def test_canvas_import_upload_endpoint_zap19_without_project_tree(client) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Demo.ap19", b"")  # lone .ap19, no sidecar dirs
    resp = client.post(
        "/api/v1/plc/canvas/import/upload",
        files={"file": ("fake.zap19", buf.getvalue(), "application/zip")},
        data={"project_name": ""},
        headers={"X-API-Key": "ros_ak_test_key"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "PLC_UPLOAD_INVALID"
    assert "孤立的 TIA 工程文件" in detail["message"]
