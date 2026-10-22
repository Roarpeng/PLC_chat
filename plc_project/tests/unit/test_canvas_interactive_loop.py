"""Unit tests for Interactive Canvas, Conversational Patches, 1:1 TIA Writeback, and Auto-Fix Closed Loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import create_app
from plc_engine.canvas_model import (
    apply_canvas_patch,
    attribute_compiler_errors,
    create_empty_canvas,
    generate_canvas_autofix_patch,
)
from plc_engine.canvas_tia_transpiler import (
    canvas_to_tia_bundle,
    execute_canvas_writeback,
    preview_canvas_scl,
    preview_canvas_tags_xml,
)


def test_create_default_canvas_and_structure() -> None:
    canvas = create_empty_canvas(project_name="WaterTreatment")
    assert canvas.project_name == "WaterTreatment"
    assert "MainDB" in canvas.blocks
    assert "MotorCtrl" in canvas.blocks
    assert "btn_start" in canvas.hmi_widgets
    assert "lamp_run" in canvas.hmi_widgets
    assert "Start_PB" in canvas.tags

    main_db = canvas.blocks["MainDB"]
    assert main_db.block_type == "DB"
    assert any(v.name == "StartCmd" for v in main_db.interface)


def test_conversational_patch_application() -> None:
    canvas = create_empty_canvas()

    # Simulate conversational patch operations
    ops = [
        {
            "op": "add_variable",
            "block": "MainDB",
            "variable": {
                "name": "ValveOpen",
                "data_type": "Bool",
                "section": "VAR",
                "comment": "Valve 1 opened",
            },
        },
        {
            "op": "add_hmi_widget",
            "widget": {
                "id": "lamp_valve",
                "widget_type": "indicator",
                "title": "阀门开指示 (Valve)",
                "x": 300,
                "y": 150,
                "plc_tag": "MainDB.ValveOpen",
                "data_type": "Bool",
            },
        },
        {
            "op": "add_network",
            "block": "MotorCtrl",
            "network": {
                "id": 2,
                "title": "Valve Interlock",
                "scl_text": 'IF "MainDB".ValveOpen THEN #RunOut := TRUE; END_IF;',
            },
        },
    ]

    updated = apply_canvas_patch(canvas, ops)

    assert any(v.name == "ValveOpen" for v in updated.blocks["MainDB"].interface)
    assert updated.blocks["MainDB"].status == "draft"
    assert "lamp_valve" in updated.hmi_widgets
    assert updated.hmi_widgets["lamp_valve"].status == "draft"
    assert len(updated.blocks["MotorCtrl"].networks) == 2


def test_1to1_scl_transpiler_and_bundle(tmp_path: Path) -> None:
    canvas = create_empty_canvas(project_name="AssemblyLine")

    # 1. Preview SCL
    scl_map = preview_canvas_scl(canvas)
    assert "MainDB" in scl_map
    assert "MotorCtrl" in scl_map
    assert 'DATA_BLOCK "MainDB"' in scl_map["MainDB"]
    assert 'FUNCTION_BLOCK "MotorCtrl"' in scl_map["MotorCtrl"]
    assert "VAR_INPUT" in scl_map["MotorCtrl"]
    assert "END_FUNCTION_BLOCK" in scl_map["MotorCtrl"]

    # 2. Preview Tag Table XML
    tags_xml = preview_canvas_tags_xml(canvas)
    assert "SW.Tags.PlcTagTable" in tags_xml
    assert "Start_PB" in tags_xml
    assert "%I0.0" in tags_xml

    # 3. Build bundle
    bundle_dir = canvas_to_tia_bundle(canvas, tmp_path / "bundle")
    assert bundle_dir.is_dir()
    assert (bundle_dir / "external_sources" / "MainDB.scl").is_file()
    assert (bundle_dir / "external_sources" / "MotorCtrl.scl").is_file()
    assert (bundle_dir / "CanvasTags.xml").is_file()
    assert (bundle_dir / "staged_scls.json").is_file()
    assert (bundle_dir / "staged_xmls.json").is_file()


def test_compiler_error_attribution_and_autofix() -> None:
    canvas = create_empty_canvas()

    # Intentionally add an HMI widget bound to non-existent DB variable
    apply_canvas_patch(
        canvas,
        [
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": "btn_heater",
                    "widget_type": "button",
                    "title": "加热器开关",
                    "plc_tag": "MainDB.HeaterEnable",
                    "data_type": "Bool",
                },
            }
        ],
    )

    # Simulated TIA Portal compiler feedback
    fake_compile_result = {
        "ok": False,
        "compile": {
            "ok": False,
            "ErrorCount": 1,
            "InconsistentBlocks": ["MotorCtrl"],
            "Message": "Block 'MotorCtrl': Line 4, Variable 'EmergencyStop' not defined",
        },
    }

    # 1. Test attribution
    attributions = attribute_compiler_errors(canvas, fake_compile_result)
    assert len(attributions) >= 2

    # Verify Block marked as error
    assert canvas.blocks["MotorCtrl"].status == "error"
    assert len(canvas.blocks["MotorCtrl"].errors) >= 1

    # Verify HMI widget marked as error
    assert canvas.hmi_widgets["btn_heater"].status == "error"
    assert any("HeaterEnable" in err for err in canvas.hmi_widgets["btn_heater"].errors)

    # 2. Test Auto-Fix generation
    auto_fix_ops = generate_canvas_autofix_patch(canvas, attributions)
    assert len(auto_fix_ops) >= 1
    assert any(
        op.get("op") == "add_variable" and op.get("variable", {}).get("name") == "HeaterEnable"
        for op in auto_fix_ops
    )

    # Apply auto-fix and verify healing
    healed_canvas = apply_canvas_patch(canvas, auto_fix_ops)
    assert any(v.name == "HeaterEnable" for v in healed_canvas.blocks["MainDB"].interface)
    assert healed_canvas.hmi_widgets["btn_heater"].status != "error"


def test_execute_canvas_writeback_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canvas = create_empty_canvas()

    def fake_execute_writeback(project_path: Any, bundle_dir: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "import_ok": True,
            "compiled_ok": True,
            "compile": {"ok": True, "ErrorCount": 0, "InconsistentBlocks": []},
        }

    monkeypatch.setattr(
        "plc_engine.canvas_tia_transpiler.execute_writeback",
        fake_execute_writeback,
    )

    result, attributions = execute_canvas_writeback(
        canvas=canvas,
        project_path="dummy.ap19",
        plc_name="PLC_1",
        temp_bundle_parent=tmp_path,
    )

    assert result["ok"] is True
    assert len(attributions) == 0
    assert canvas.blocks["MainDB"].status == "synced"
    assert canvas.blocks["MotorCtrl"].status == "synced"


def test_gateway_rest_canvas_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    client = TestClient(app)

    # 1. GET /canvas/default
    resp1 = client.get("/api/v1/plc/canvas/default")
    assert resp1.status_code == 200
    canvas_dict = resp1.json()["data"]
    assert "MainDB" in canvas_dict["blocks"]

    # 2. POST /canvas/patch
    resp2 = client.post(
        "/api/v1/plc/canvas/patch",
        json={
            "canvas": canvas_dict,
            "operations": [
                {
                    "op": "add_variable",
                    "block": "MainDB",
                    "variable": {"name": "TestVar", "data_type": "DInt", "section": "VAR"},
                }
            ],
        },
    )
    assert resp2.status_code == 200
    patched_canvas = resp2.json()["data"]
    assert any(v["name"] == "TestVar" for v in patched_canvas["blocks"]["MainDB"]["interface"])

    # 3. POST /canvas/to-scl
    resp3 = client.post("/api/v1/plc/canvas/to-scl", json={"canvas": patched_canvas})
    assert resp3.status_code == 200
    scl_data = resp3.json()["data"]
    assert "MainDB" in scl_data["scl_sources"]
    assert "TestVar : DInt;" in scl_data["scl_sources"]["MainDB"]

    # 4. POST /canvas/confirm-writeback (sync branch, with mock)
    def fake_wb(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return {"ok": True, "compile": {"ok": True}}, []

    monkeypatch.setattr(
        "plc_engine.canvas_tia_transpiler.execute_canvas_writeback",
        fake_wb,
    )

    resp4 = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={
            "canvas": patched_canvas,
            "project_path": "test.ap19",
            "plc_name": "PLC_1",
            "sync": True,
        },
    )
    assert resp4.status_code == 200
    wb_data = resp4.json()["data"]
    # Envelope shared with the async branch: async/job/writeback/attributions/canvas.
    assert wb_data["async"] is False
    assert wb_data["job"] is None
    assert wb_data["writeback"]["ok"] is True
    assert wb_data["attributions"] == []
    assert "MainDB" in wb_data["canvas"]["blocks"]

    # 4b. Async branch (default) keeps the same envelope so the UI polling path
    # (`data.async && data.job.id`) and the sync path share one contract.
    monkeypatch.setattr(
        "gateway.app.services.plc.compile_jobs.create_compile_job",
        lambda *a, **k: {"id": "job-1", "status": "queued", "canvas": None, "attributions": []},
    )
    resp4b = client.post(
        "/api/v1/plc/canvas/confirm-writeback",
        json={"canvas": patched_canvas, "project_path": "test.ap19", "plc_name": "PLC_1"},
    )
    assert resp4b.status_code == 200
    job_data = resp4b.json()["data"]
    assert job_data["async"] is True
    assert job_data["job"]["id"] == "job-1"
    assert job_data["writeback"] is None
    assert job_data["attributions"] == []
    assert "MainDB" in job_data["canvas"]["blocks"]

    # 5. POST /canvas/auto-fix
    resp5 = client.post(
        "/api/v1/plc/canvas/auto-fix",
        json={
            "canvas": patched_canvas,
            "attributions": [
                {
                    "target_type": "hmi_widget",
                    "target_id": "widget_1",
                    "message": "块 [MainDB] 中未声明变量 [CoolingPump]",
                }
            ],
        },
    )
    assert resp5.status_code == 200
    fixed_canvas = resp5.json()["data"]["canvas"]
    assert any(v["name"] == "CoolingPump" for v in fixed_canvas["blocks"]["MainDB"]["interface"])
