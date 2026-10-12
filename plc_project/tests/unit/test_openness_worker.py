from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient


def _complete_apxx(root: Path, name: str = "Line.ap19") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    project = root / name
    project.write_bytes(b"fake-ap19")
    sidecar = root / project.stem
    sidecar.mkdir(exist_ok=True)
    (sidecar / "project.bin").write_bytes(b"sidecar")
    return project


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return output.getvalue()


def _b64_notes(notes: list[str]) -> str:
    return base64.b64encode(json.dumps(notes).encode("utf-8")).decode("ascii")


def test_client_success_and_safe_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from industrial.openness_worker import client

    project = _complete_apxx(tmp_path / "project")
    destination = tmp_path / "out"
    destination.mkdir()
    (destination / "stale.txt").write_text("remove", encoding="utf-8")
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret")

    export_zip = _zip_bytes({"Blocks/Line.xml": b"<xml/>"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/export"
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert b'filename="Line_project.zip"' in request.content
        return httpx.Response(
            200,
            content=export_zip,
            headers={
                "Content-Type": "application/zip",
                "X-ResearchOS-Export-Key": "abc123",
                "X-ResearchOS-Timing-Ms": "123",
                "X-ResearchOS-Notes-B64": _b64_notes(["worker export complete"]),
            },
        )

    path, notes, timings = client.export_project_via_worker(
        project,
        export_dir=destination,
        transport=httpx.MockTransport(handler),
    )
    assert path == destination.resolve()
    assert (destination / "Blocks" / "Line.xml").read_bytes() == b"<xml/>"
    assert not (destination / "stale.txt").exists()
    assert "worker export complete" in notes
    assert any("abc123" in note for note in notes)
    assert timings["openness_worker_ms"] == 123
    assert timings["openness_worker_client_ms"] >= 0


def test_client_rejects_unsafe_export_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from industrial.openness_worker import client

    project = _complete_apxx(tmp_path / "project")
    destination = tmp_path / "out"
    destination.mkdir()
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")
    unsafe_zip = _zip_bytes({"../escape.txt": b"no"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=unsafe_zip,
            headers={"Content-Type": "application/zip"},
        )

    with pytest.raises(ValueError, match="Unsafe Openness worker export"):
        client.export_project_via_worker(
            project,
            export_dir=destination,
            transport=httpx.MockTransport(handler),
        )
    assert list(destination.iterdir()) == []
    assert not (tmp_path / "escape.txt").exists()


def test_importer_uses_configured_worker_before_local_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import importer as imp
    from industrial.openness_worker import client as worker_client

    project = _complete_apxx(tmp_path / "project")
    out = tmp_path / "out"
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "0")
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda *_a, **_k: pytest.fail("must not stage"))

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("local CLI must not run when worker is configured")

    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli", boom
    )

    def fake_worker(project_path: Path, *, export_dir: Path, timeout_s: int):
        assert project_path == project.resolve()
        assert timeout_s == 611
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "Blocks").mkdir()
        (Path(export_dir) / "Blocks" / "Line.xml").write_text("<xml/>", encoding="utf-8")
        return Path(export_dir), ["worker export complete"], {"openness_worker_ms": 44}

    monkeypatch.setattr(worker_client, "export_project_via_worker", fake_worker)
    path, notes, timings = imp.export_apxx_via_openness(
        project,
        export_dir=out,
        timeout_s=611,
    )
    assert (path / "Blocks" / "Line.xml").is_file()
    assert "worker export complete" in notes
    assert timings["openness_worker_ms"] == 44
    assert "openness_worker_call_ms" in timings


def test_importer_preserves_linux_behavior_without_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import importer as imp
    from industrial.openness_worker import client as worker_client

    project = _complete_apxx(tmp_path / "project")
    monkeypatch.delenv("RESEARCHOS_OPENNESS_WORKER_URL", raising=False)
    monkeypatch.setenv("RESEARCHOS_TIA_EXPORT_CACHE", "0")
    monkeypatch.setattr(imp, "_is_windows", lambda: False)
    monkeypatch.setattr(imp, "stage_tia_project_tree", lambda p, **_k: Path(p))

    def worker_boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("worker must not run without URL")

    def cli_boom(*_a: Any, **_k: Any) -> None:
        raise FileNotFoundError("TiaOpenness.Server.exe")

    def subprocess_boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("subprocess.run must not run on Linux")

    monkeypatch.setattr(worker_client, "export_project_via_worker", worker_boom)
    monkeypatch.setattr(
        "agents.plc.tia.openness_cli.export_project_via_openness_cli", cli_boom
    )
    monkeypatch.setattr(imp.subprocess, "run", subprocess_boom)
    with pytest.raises(RuntimeError, match="Linux cannot run TIA Openness"):
        imp.export_apxx_via_openness(project, export_dir=tmp_path / "out")


def test_worker_health_auth_upload_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from industrial.openness_worker import server

    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret")
    monkeypatch.setattr(server, "_max_upload_bytes", lambda: 16)

    def fake_export(project_path: Path, *, export_dir: Path, **_kwargs):
        assert project_path.is_file()
        blocks = Path(export_dir) / "Blocks"
        blocks.mkdir(parents=True, exist_ok=True)
        (blocks / "Line.xml").write_text("<xml/>", encoding="utf-8")
        return Path(export_dir), ["fake Openness export"], {"openness_cli_ms": 5}

    monkeypatch.setattr(server, "export_apxx_via_openness", fake_export)
    client = TestClient(server.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["auth_required"] is True

    denied = client.post("/export", files={"project": ("Line.zip", b"not-zip")})
    assert denied.status_code == 401
    wrong = client.post(
        "/export",
        files={"project": ("Line.zip", b"not-zip")},
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401
    monkeypatch.delenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", raising=False)
    unconfigured = client.post(
        "/export",
        files={"project": ("Line.zip", b"not-zip")},
    )
    assert unconfigured.status_code == 503
    assert "token is not configured" in unconfigured.json()["detail"]
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret")
    invalid = client.post(
        "/export",
        files={"project": ("Line.exe", b"no")},
        headers={"Authorization": "Bearer secret"},
    )
    assert invalid.status_code == 415
    oversized = client.post(
        "/export",
        files={"project": ("Line.zip", b"0" * 17)},
        headers={"Authorization": "Bearer secret"},
    )
    assert oversized.status_code == 413
    monkeypatch.setattr(server, "_max_upload_bytes", lambda: 100 * 1024 * 1024)

    project = _complete_apxx(tmp_path / "source")
    upload = _zip_bytes(
        {
            "Line.ap19": project.read_bytes(),
            "Line/project.bin": b"sidecar",
        }
    )
    response = client.post(
        "/export",
        files={"project": ("Line.zap19", upload)},
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["X-ResearchOS-Export-Key"]
    assert response.headers["X-ResearchOS-Timing-Ms"].isdigit()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert "Blocks/Line.xml" in zf.namelist()
        assert "_researchos_manifest.json" in zf.namelist()
        manifest = json.loads(zf.read("_researchos_manifest.json"))
        assert manifest["source_kind"] == "archive"
        assert "fake Openness export" in manifest["notes"]


def test_worker_rejects_concurrent_export_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from industrial.openness_worker import server

    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret")
    with server._OPENNESS_LOCK:
        client = TestClient(server.app)
        response = client.post(
            "/export",
            files={"project": ("Line.zip", b"queued")},
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status_code == 409
        assert "Another Openness operation" in response.json()["detail"]


def _import_bundle_bytes(project: Path) -> bytes:
    return _zip_bytes(
        {
            "project/Line.ap19": project.read_bytes(),
            "project/Line/project.bin": b"sidecar",
            "import/Foo.xml": b"<block-xml/>",
            "import/external_sources/Bar.scl": b"FUNCTION_BLOCK \"Bar\"\nEND_FUNCTION_BLOCK",
        }
    )


def test_worker_import_endpoint_runs_writeback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from industrial.openness_worker import server

    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret")
    recorded: dict[str, Any] = {}

    def fake_execute(project_path, bundle_dir, plc_name="", *, compile_after=True):
        recorded["project"] = Path(project_path).name
        recorded["plc_name"] = plc_name
        recorded["compile_after"] = compile_after
        staged = Path(bundle_dir)
        recorded["xmls"] = sorted(p.name for p in staged.glob("*.xml"))
        recorded["scls"] = sorted(p.name for p in (staged / "external_sources").glob("*.scl"))
        return {
            "ok": True,
            "import_ok": True,
            "compiled_ok": True,
            "results": [],
            "scl_results": [],
            "compile": {"ok": True},
            "note": "fake",
        }

    monkeypatch.setattr("agents.plc.tia.writeback.execute_writeback", fake_execute)
    client = TestClient(server.app)

    denied = client.post("/import", files={"bundle": ("b.zip", b"x")})
    assert denied.status_code == 401
    wrong_type = client.post(
        "/import",
        files={"bundle": ("b.tar", b"x")},
        headers={"Authorization": "Bearer secret"},
    )
    assert wrong_type.status_code == 415
    no_project = client.post(
        "/import",
        files={"bundle": ("b.zip", _zip_bytes({"import/Foo.xml": b"<x/>"}))},
        headers={"Authorization": "Bearer secret"},
    )
    assert no_project.status_code == 422
    no_import = client.post(
        "/import",
        files={"bundle": ("b.zip", _zip_bytes({"project/empty": b""}))},
        headers={"Authorization": "Bearer secret"},
    )
    assert no_import.status_code == 422

    project = _complete_apxx(tmp_path / "source")
    response = client.post(
        "/import",
        files={"bundle": ("b.zip", _import_bundle_bytes(project))},
        params={"plc_name": "PLC_1", "compile_after": "false"},
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["via"] == "openness-worker"
    assert data["worker"]["project"] == "Line.ap19"
    assert recorded["project"] == "Line.ap19"
    assert recorded["plc_name"] == "PLC_1"
    assert recorded["compile_after"] is False
    assert recorded["xmls"] == ["Foo.xml"]
    assert recorded["scls"] == ["Bar.scl"]


def test_client_import_bundle_via_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from industrial.openness_worker import client

    project = _complete_apxx(tmp_path / "project")
    bundle = tmp_path / "bundle"
    (bundle / "external_sources").mkdir(parents=True)
    (bundle / "Foo.xml").write_text("<xml/>", encoding="utf-8")
    (bundle / "external_sources" / "Bar.scl").write_text(
        'FUNCTION_BLOCK "Bar"\nEND_FUNCTION_BLOCK', encoding="utf-8"
    )
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret")

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["plc_name"] = request.url.params.get("plc_name")
        seen["compile_after"] = request.url.params.get("compile_after")
        seen["auth"] = request.headers.get("authorization")
        payload = zipfile.ZipFile(io.BytesIO(request.content))
        seen["members"] = sorted(payload.namelist())
        return httpx.Response(
            200,
            json={
                "ok": True,
                "import_ok": True,
                "compiled_ok": True,
                "results": [],
                "scl_results": [],
                "compile": {"ok": True},
            },
        )

    report = client.import_bundle_via_worker(
        project,
        bundle,
        plc_name="PLC_1",
        compile_after=False,
        transport=httpx.MockTransport(handler),
    )
    assert report["ok"] is True
    assert report["timings"]["openness_worker_client_ms"] >= 0
    assert seen["path"] == "/import"
    assert seen["plc_name"] == "PLC_1"
    assert seen["compile_after"] == "false"
    assert seen["auth"] == "Bearer secret"
    assert seen["members"] == [
        "import/Foo.xml",
        "import/external_sources/Bar.scl",
        "project/Line.ap19",
        "project/Line/project.bin",
    ]


def test_client_import_requires_staged_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from industrial.openness_worker import client

    project = _complete_apxx(tmp_path / "project")
    empty_bundle = tmp_path / "bundle"
    empty_bundle.mkdir()
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")
    with pytest.raises(ValueError, match="no staged XML/SCL"):
        client.import_bundle_via_worker(project, empty_bundle)


def test_execute_writeback_delegates_to_worker_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.plc.tia import writeback

    project = _complete_apxx(tmp_path / "project")
    bundle = tmp_path / "bundle"
    (bundle / "external_sources").mkdir(parents=True)
    (bundle / "Foo.xml").write_text("<xml/>", encoding="utf-8")
    (bundle / "external_sources" / "Bar.scl").write_text(
        'FUNCTION_BLOCK "Bar"\nEND_FUNCTION_BLOCK', encoding="utf-8"
    )
    monkeypatch.setattr(writeback, "_is_windows_local", lambda: False)
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")

    def fake_worker(project_path, bundle_dir, *, plc_name="", compile_after=True):
        return {
            "ok": True,
            "import_ok": True,
            "compiled_ok": compile_after,
            "results": [],
            "scl_results": [],
            "compile": {"ok": compile_after},
            "note": "worker",
        }

    monkeypatch.setattr(
        "industrial.openness_worker.client.import_bundle_via_worker", fake_worker
    )
    result = writeback.execute_writeback(project, bundle, plc_name="PLC_1")
    assert result["via"] == "openness-worker"
    assert result["project_path"] == str(project.resolve())
    assert result["bundle_dir"] == str(bundle.resolve())


def test_worker_preference_off_for_windows_or_without_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.plc.tia import writeback

    monkeypatch.setattr(writeback, "_is_windows_local", lambda: True)
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://127.0.0.1:8015")
    assert writeback._worker_preferred() is False

    monkeypatch.setattr(writeback, "_is_windows_local", lambda: False)
    monkeypatch.delenv("RESEARCHOS_OPENNESS_WORKER_URL", raising=False)
    assert writeback._worker_preferred() is False
