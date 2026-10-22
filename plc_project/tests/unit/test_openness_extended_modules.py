from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.plc.tia import openness_cli
from industrial.openness_worker import client
from industrial.openness_worker.server import app


def test_openness_cli_create_device_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_openness_cli(*args: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append(list(args))
        return {
            "ok": True,
            "create": {
                "ok": True,
                "deviceName": "CPU_1511",
                "typeIdentifier": "OrderNumber:6ES7 511-1AK01-0AB0/V2.5",
                "orderNumber": "6ES7 511-1AK01-0AB0",
                "version": "V2.5",
            },
        }

    monkeypatch.setattr(openness_cli, "openness_cli", fake_openness_cli)
    proj = tmp_path / "Test.ap19"
    proj.write_text("fake")

    result = openness_cli.create_device_via_openness_cli(
        proj,
        "OrderNumber:6ES7 511-1AK01-0AB0/V2.5",
        "CPU_1511",
        device_name="Station_1",
        plc_name="PLC_1",
    )
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0] == [
        "create-device",
        "--project",
        str(proj.resolve()),
        "--type-id",
        "OrderNumber:6ES7 511-1AK01-0AB0/V2.5",
        "--name",
        "CPU_1511",
        "--device-name",
        "Station_1",
        "--plc",
        "PLC_1",
    ]


def test_openness_cli_open_library_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_openness_cli(*args: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append(list(args))
        return {
            "ok": True,
            "library": {
                "ok": True,
                "libraryName": "StandardLib",
                "masterCopiesCount": 2,
                "typesCount": 1,
            },
        }

    monkeypatch.setattr(openness_cli, "openness_cli", fake_openness_cli)
    lib = tmp_path / "StandardLib.al19"
    lib.write_text("fake")

    result = openness_cli.open_library_via_openness_cli(lib, read_only=False)
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0] == ["open-library", "--path", str(lib.resolve()), "--write"]


def test_openness_cli_copy_from_library_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_openness_cli(*args: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append(list(args))
        return {
            "ok": True,
            "copy": {
                "ok": True,
                "itemName": "MotorTemplate",
            },
        }

    monkeypatch.setattr(openness_cli, "openness_cli", fake_openness_cli)
    lib = tmp_path / "StandardLib.al19"
    lib.write_text("fake")

    result = openness_cli.copy_from_library_via_openness_cli(
        lib, "MotorTemplate", target_group="DriveBlocks"
    )
    assert result["ok"] is True
    assert calls[0] == [
        "copy-from-library",
        "--library",
        str(lib.resolve()),
        "--item",
        "MotorTemplate",
        "--target",
        "DriveBlocks",
    ]


def test_openness_cli_get_tags_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_openness_cli(*args: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append(list(args))
        return {
            "ok": True,
            "tags": {
                "ok": True,
                "tableName": "Default tag table",
                "count": 5,
            },
        }

    monkeypatch.setattr(openness_cli, "openness_cli", fake_openness_cli)
    result = openness_cli.get_tags_via_openness_cli(table_name="Default tag table")
    assert result["ok"] is True
    assert calls[0] == ["get-tags", "--table", "Default tag table"]


def test_openness_worker_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "secret-key")
    c = TestClient(app)

    # 1. Unauthenticated request rejected
    resp = c.post("/devices/create", params={"project_path": "x", "type_identifier": "y", "name": "z"})
    assert resp.status_code == 401

    auth_headers = {"Authorization": "Bearer secret-key"}

    # Mock CLI functions called by worker
    monkeypatch.setattr(
        openness_cli,
        "create_device_via_openness_cli",
        lambda *args, **kwargs: {"ok": True, "created": True},
    )
    resp = c.post(
        "/devices/create",
        params={"project_path": "test.ap19", "type_identifier": "id", "name": "CPU"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "created": True}

    monkeypatch.setattr(
        openness_cli,
        "open_library_via_openness_cli",
        lambda *args, **kwargs: {"ok": True, "library": "opened"},
    )
    resp = c.post(
        "/libraries/open",
        params={"library_path": "test.al19", "read_only": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "library": "opened"}

    monkeypatch.setattr(
        openness_cli,
        "copy_from_library_via_openness_cli",
        lambda *args, **kwargs: {"ok": True, "copied": True},
    )
    resp = c.post(
        "/libraries/copy",
        params={"library_path": "test.al19", "item_name": "BlockA"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "copied": True}

    monkeypatch.setattr(
        openness_cli,
        "get_tags_via_openness_cli",
        lambda *args, **kwargs: {"ok": True, "tags": []},
    )
    resp = c.get(
        "/tags",
        params={"table_name": "Main"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "tags": []}


def test_openness_worker_client_remote_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_URL", "http://worker:8015")
    monkeypatch.setenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "token")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer token"
        if request.url.path == "/devices/create":
            return httpx.Response(200, json={"ok": True, "device": "created"})
        if request.url.path == "/libraries/open":
            return httpx.Response(200, json={"ok": True, "library": "opened"})
        if request.url.path == "/libraries/copy":
            return httpx.Response(200, json={"ok": True, "copied": True})
        if request.url.path == "/tags":
            return httpx.Response(200, json={"ok": True, "tags": [{"name": "Start"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    real_client_cls = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client_cls(transport=transport, **kwargs))

    res1 = client.create_device_via_worker("test.ap19", "typeId", "CPU1")
    assert res1["ok"] is True
    assert res1["device"] == "created"

    res2 = client.open_library_via_worker("lib.al19")
    assert res2["ok"] is True
    assert res2["library"] == "opened"

    res3 = client.copy_from_library_via_worker("lib.al19", "Item1")
    assert res3["ok"] is True
    assert res3["copied"] is True

    res4 = client.get_tags_via_worker(table_name="Table1")
    assert res4["ok"] is True
    assert len(res4["tags"]) == 1
