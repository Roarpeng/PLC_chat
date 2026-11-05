"""Unit tests for P0-A: Fast writeback engine integration & static linter gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gateway.app.services.plc import openness_session
from agents.plc.tia import openness_cli
from plc_engine.canvas_model import CanvasBlock, CanvasState
from plc_engine.canvas_tia_transpiler import (
    execute_canvas_writeback,
    precheck_canvas_for_writeback,
)


def test_openness_session_fast_writeback_normalizes_payload(monkeypatch):
    recorded_calls = []

    def fake_post(path, body, timeout_s=120.0):
        recorded_calls.append((path, body))
        return {"success": True, "writtenBlockCount": 2}

    monkeypatch.setattr(openness_session, "ensure_session_running", lambda: True)
    monkeypatch.setattr(openness_session, "_post", fake_post)

    req = {
        "scl_path": "C:/test/AF_Batch.scl",
        "project_path": "C:/test/Line.ap19",
        "software_unit": "Unit1",
        "interfaceChanged": True,
        "hasUdtOrGlobalDbChange": True,
        "blockNames": ["FB_A", "FB_B"],
    }
    resp = openness_session.fast_writeback(req)
    assert resp["ok"] is True
    assert resp["success"] is True
    assert len(recorded_calls) == 1
    path, body = recorded_calls[0]
    assert path == "/fast-writeback"
    assert body["scl"] == "C:/test/AF_Batch.scl"
    assert body["project"] == "C:/test/Line.ap19"
    assert body["unit"] == "Unit1"


def test_openness_session_fast_writeback_fails_closed_when_session_unavailable(monkeypatch):
    monkeypatch.setattr(openness_session, "ensure_session_running", lambda: False)
    resp = openness_session.fast_writeback({"scl": "AF_Batch.scl"})
    assert resp["ok"] is False
    assert resp["fallback"] is True
    assert resp["error"] == "session unavailable"


def test_fast_writeback_via_openness_cli_uses_session_when_available(monkeypatch):
    monkeypatch.setattr(openness_session, "session_enabled", lambda: True)
    monkeypatch.setattr(openness_session, "ensure_session_running", lambda: True)

    session_mock = MagicMock(return_value={"success": True, "compileScope": "incremental_blocks", "errors": []})
    monkeypatch.setattr(openness_session, "fast_writeback", session_mock)

    cli_fallback_mock = MagicMock()
    monkeypatch.setattr(openness_cli, "generate_from_source_via_openness_cli", cli_fallback_mock)

    result = openness_cli.fast_writeback_via_openness_cli(
        project_path="C:/test/Line.ap19",
        scl_path="C:/test/AF_Batch.scl",
        body={"interfaceChanged": False},
    )

    assert result["ok"] is True
    assert result["success"] is True
    assert session_mock.called
    assert not cli_fallback_mock.called


def test_fast_writeback_via_openness_cli_falls_back_when_session_unreachable(monkeypatch):
    monkeypatch.setattr(openness_session, "session_enabled", lambda: True)
    monkeypatch.setattr(openness_session, "ensure_session_running", lambda: True)
    monkeypatch.setattr(openness_session, "fast_writeback", lambda body, **k: {"ok": False, "fallback": True})

    gen_mock = MagicMock(return_value={"ok": True, "generate": {"ok": True}})
    compile_mock = MagicMock(return_value={"ok": True, "compile": {"ok": True}})
    monkeypatch.setattr(openness_cli, "generate_from_source_via_openness_cli", gen_mock)
    monkeypatch.setattr(openness_cli, "compile_plc_via_openness_cli", compile_mock)

    result = openness_cli.fast_writeback_via_openness_cli(
        project_path="C:/test/Line.ap19",
        scl_path="C:/test/AF_Batch.scl",
        compile_after=True,
    )

    assert result["ok"] is True
    assert result["fallback"] is True
    assert gen_mock.called
    assert compile_mock.called


def test_precheck_canvas_for_writeback_intercepts_r2_violation():
    # R2: Physical output %Q assigned directly on LHS of :=
    bad_scl = '''FUNCTION_BLOCK "FB_ValveControl"
VAR
    xOpen : Bool;
END_VAR
BEGIN
    "Q_Valve_Open" := #xOpen;
END_FUNCTION_BLOCK
'''
    canvas = CanvasState(project_name="TestProj")
    canvas.blocks["FB_ValveControl"] = CanvasBlock(
        name="FB_ValveControl",
        block_type="FB",
        scl_body=bad_scl,
        status="draft",
    )

    precheck = precheck_canvas_for_writeback(canvas)
    assert precheck["ok"] is False
    assert len(precheck["errors"]) >= 1
    rules = [e.get("rule") for e in precheck["errors"]]
    assert "R2" in rules
    assert "本地预检" in precheck["summary"]


def test_precheck_canvas_for_writeback_passes_clean_canvas():
    clean_scl = '''FUNCTION_BLOCK "FB_Clean"
VAR
    statStep : Int := 10;
END_VAR
BEGIN
    #statStep := 20;
END_FUNCTION_BLOCK
'''
    canvas = CanvasState(project_name="TestProj")
    canvas.blocks["FB_Clean"] = CanvasBlock(
        name="FB_Clean",
        block_type="FB",
        scl_body=clean_scl,
        status="draft",
    )

    precheck = precheck_canvas_for_writeback(canvas)
    assert precheck["ok"] is True
    assert len(precheck["errors"]) == 0


def test_execute_canvas_writeback_fails_closed_on_static_gate_error(tmp_path: Path):
    bad_scl = '''FUNCTION_BLOCK "FB_BadGate"
VAR
    xCmd : Bool;
END_VAR
BEGIN
    "Q_Actuator" := #xCmd;
END_FUNCTION_BLOCK
'''
    canvas = CanvasState(project_name="TestProj")
    canvas.blocks["FB_BadGate"] = CanvasBlock(
        name="FB_BadGate",
        block_type="FB",
        scl_body=bad_scl,
        status="draft",
    )

    result, attributions = execute_canvas_writeback(
        canvas=canvas,
        project_path=tmp_path / "Dummy.ap19",
        temp_bundle_parent=tmp_path,
    )

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["error"] == "precheck_failed"
    assert canvas.blocks["FB_BadGate"].status == "error"
    assert len(attributions) >= 1
