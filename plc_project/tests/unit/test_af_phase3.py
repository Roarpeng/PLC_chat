"""Unit and End-to-End tests for AF V1.2 Phase 3:
Process Description -> AF V1.2 Architecture Planning -> Code Generation -> Canvas Loading.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plc_engine.af import (
    AfCm,
    AfEm,
    AfProject,
    AfUnit,
    generate_af_project_blocks,
    lint_af_canvas,
    plan_af_project_from_spec,
)
from plc_engine.canvas_model import CanvasState


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_API_KEY", "ros_ak_test_key")
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


AUTH_HEADER = {"X-API-Key": "ros_ak_test_key"}


def test_planner_from_natural_language_full_stack():
    """Test planning an AF V1.2 project from multi-device natural language process spec."""
    spec_text = """
    工位1: 进料工位 (FeederStation)
    设备配置:
    - 进料气缸: cylFeeder
    - 料位传感器: sensorPartPresent
    - 输送电机: motorConveyor
    - 顶升定位轴: axisLifter
    
    工步说明:
    10 等待料位传感器 sensorPartPresent 检测到工件
    20 进料气缸 cylFeeder 伸出推入工件
    30 顶升定位轴 axisLifter 移动到加工位
    40 输送电机 motorConveyor 正转启动运行
    50 输送电机 motorConveyor 停止
    60 进料气缸 cylFeeder 缩回原位
    """

    project = plan_af_project_from_spec(spec_text, project_name="AssemblyLine")

    assert isinstance(project, AfProject)
    assert project.name == "AssemblyLine"
    assert len(project.units) == 1

    unit = project.units[0]
    assert isinstance(unit, AfUnit)
    assert unit.unit_idx == 1
    assert len(unit.equipment_modules) == 1

    em = unit.equipment_modules[0]
    assert isinstance(em, AfEm)
    assert em.em_idx == 1
    assert "Feeder" in em.name

    # Verify CM auto-classification to LBC_* types
    cm_map = {cm.name: cm.cm_type for cm in em.control_modules}
    assert cm_map.get("cylFeeder") == "LBC_TwoWayActuator"
    assert cm_map.get("sensorPartPresent") == "LBC_DigitalSignal"
    assert cm_map.get("motorConveyor") == "LBC_MotorStarter"
    assert cm_map.get("axisLifter") == "LBC_AxisControl"

    # Verify Sequence steps and strict command via #controlNodes.<cm>.commands
    steps = em.sequence.steps
    assert len(steps) >= 5

    # Step 10: Wait sensor
    step10 = next(s for s in steps if s.step_id == 10)
    assert "sensorPartPresent" in step10.transition_condition
    assert "#controlNodes.sensorPartPresent.status.signal" in step10.transition_condition

    # Step 20: Cylinder extend
    step20 = next(s for s in steps if s.step_id == 20)
    assert any("#controlNodes.cylFeeder.commands.workPosition := TRUE;" in a for a in step20.actions)
    assert "#controlNodes.cylFeeder.status.inWorkPosition" in step20.transition_condition

    # Step 30: Axis move
    step30 = next(s for s in steps if s.step_id == 30)
    assert any("#controlNodes.axisLifter.commands.moveAbsolute := TRUE;" in a for a in step30.actions)
    assert "#controlNodes.axisLifter.status.inPosition" in step30.transition_condition

    # Step 40: Motor run
    step40 = next(s for s in steps if s.step_id == 40)
    assert any("#controlNodes.motorConveyor.commands.forward := TRUE;" in a for a in step40.actions)
    assert "#controlNodes.motorConveyor.status.running" in step40.transition_condition

    # Step 60: Cylinder retract
    step60 = next(s for s in steps if s.step_id == 60)
    assert any("#controlNodes.cylFeeder.commands.homePosition := TRUE;" in a for a in step60.actions)
    assert "#controlNodes.cylFeeder.status.inHomePosition" in step60.transition_condition


def test_planner_from_requirement_card():
    """Test planning from a RequirementStore card dict."""
    card = {
        "requirement_id": "req-112233445566",
        "project_name": "PackagingCell",
        "confirmation_status": "confirmed",
        "intent_summary": "自动装箱工位压紧与输送",
        "items": [
            {"id": "it-1", "kind": "sequence", "text": "工步10: 等待箱体到位传感器 sensorBoxPresent", "source": "user"},
            {"id": "it-2", "kind": "sequence", "text": "工步20: 压紧气缸 cylClamp 伸出夹紧", "source": "user"},
            {"id": "it-3", "kind": "sequence", "text": "工步30: 输送电机 motorBelt 启动运行", "source": "user"},
            {"id": "it-4", "kind": "sequence", "text": "工步40: 压紧气缸 cylClamp 缩回松开", "source": "user"},
        ],
        "linked_signals": ["sensorBoxPresent", "cylClamp", "motorBelt"],
    }

    project = plan_af_project_from_spec(card, project_name="PackagingCell")
    assert project.name == "PackagingCell"
    em = project.units[0].equipment_modules[0]
    cms = {c.name: c.cm_type for c in em.control_modules}
    assert cms["sensorBoxPresent"] == "LBC_DigitalSignal"
    assert cms["cylClamp"] == "LBC_TwoWayActuator"
    assert cms["motorBelt"] == "LBC_MotorStarter"

    # Verify sequence step connections
    step_ids = [s.step_id for s in em.sequence.steps]
    assert 10 in step_ids
    assert 20 in step_ids
    assert 30 in step_ids
    assert 40 in step_ids


def test_planner_from_structured_dict():
    """Test planning from a generic structured dictionary."""
    spec = {
        "name": "PressMachine",
        "description": "Two station press machine",
        "stations": [
            {
                "name": "LoadingStation",
                "control_modules": [
                    {"name": "cylLoader", "cm_type": "LBC_TwoWayActuator"},
                    {"name": "sensorPart", "cm_type": "LBC_DigitalSignal"},
                ],
                "steps": [
                    {"step_id": 10, "name": "WAIT_PART", "transition_condition": "#controlNodes.sensorPart.status.signal", "next_step_id": 20},
                    {"step_id": 20, "name": "LOAD", "actions": ["#controlNodes.cylLoader.commands.workPosition := TRUE;"], "next_step_id": 1},
                ],
            },
            {
                "name": "PressStation",
                "control_modules": [
                    {"name": "axisPress", "cm_type": "LBC_AxisControl"},
                ],
                "steps": [
                    {"step_id": 10, "name": "PRESS", "actions": ["#controlNodes.axisPress.commands.moveAbsolute := TRUE;"], "next_step_id": 1},
                ],
            },
        ],
    }

    project = plan_af_project_from_spec(spec, project_name="PressMachine")
    assert len(project.units[0].equipment_modules) == 2
    em1, em2 = project.units[0].equipment_modules
    assert em1.em_idx == 1
    assert em1.name == "LoadingStation"
    assert em2.em_idx == 2
    assert em2.name == "PressStation"


def test_generated_af_blocks_lint_clean():
    """Ensure generated Software Unit blocks satisfy all AF V1.2 architecture linter rules."""
    spec_text = """
    工位: 组装工位 (AssembleStation)
    - 进料气缸: cylFeeder
    - 检测传感器: sensorReady
    工步:
    10 等待就绪 sensorReady
    20 气缸伸出 cylFeeder
    30 气缸缩回 cylFeeder
    """
    project = plan_af_project_from_spec(spec_text, project_name="AssembleProject")
    blocks = generate_af_project_blocks(project)

    canvas = CanvasState(project_name=project.name)
    for k, b in blocks.items():
        b.status = "draft"
        canvas.blocks[k] = b

    # Run linter
    findings = lint_af_canvas(canvas)
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 0, f"Expected 0 linter errors, got {errors}"

    # Verify all expected blocks were generated
    su_unit = "U1_AssembleProject"
    su_em0 = "U1Em0_General"
    su_em1 = "U1Em1_AssembleStation"

    assert f"{su_unit}::Startup" in canvas.blocks
    assert f"{su_unit}::Main" in canvas.blocks
    assert f"{su_unit}::CallUnit" in canvas.blocks
    assert f"{su_unit}::EmNodes" in canvas.blocks

    assert f"{su_em0}::Startup" in canvas.blocks
    assert f"{su_em0}::Main" in canvas.blocks

    assert f"{su_em1}::Startup" in canvas.blocks
    assert f"{su_em1}::Main" in canvas.blocks
    assert f"{su_em1}::ControlNodes" in canvas.blocks
    assert f"{su_em1}::StepToString" in canvas.blocks
    assert f"{su_em1}::Sequence" in canvas.blocks
    assert f"{su_em1}::CallEquipment" in canvas.blocks


def test_api_generate_af_from_requirement_e2e(client: TestClient):
    """Test full e2e endpoint POST /api/v1/plc/canvas/requirements/{req_id}/generate-af."""
    from gateway.app.services.plc import requirement_store

    req_id = "req-aabbccddeeff"
    card_data = {
        "requirement_id": req_id,
        "project_name": "Line1",
        "confirmation_status": "confirmed",
        "intent_summary": "自动送料与检测工位",
        "items": [
            {"id": "it-1", "kind": "sequence", "text": "工步10: 等待工件到位检测 sensorPresent", "source": "user"},
            {"id": "it-2", "kind": "sequence", "text": "工步20: 送料气缸 cylFeed 伸出到位", "source": "user"},
            {"id": "it-3", "kind": "sequence", "text": "工步30: 送料气缸 cylFeed 缩回复位", "source": "user"},
        ],
        "linked_signals": ["sensorPresent", "cylFeed"],
    }
    requirement_store.put_requirement(card_data)

    # 1. Call generate-af endpoint
    resp = client.post(
        f"/api/v1/plc/canvas/requirements/{req_id}/generate-af",
        json={"project_name": "Line1"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200, resp.text
    res_data = resp.json()
    assert res_data["ok"] is True
    data = res_data["data"]

    assert data["ok"] is True
    assert data["project"]["name"] == "Line1"
    assert data["blocks_count"] >= 10
    assert isinstance(data["findings"], list)

    # All generated blocks should be in draft status in canvas
    blocks = data["canvas"]["blocks"]
    assert any("ControlNodes" in b for b in blocks)
    assert any("Sequence" in b for b in blocks)
    for b in blocks.values():
        assert b["status"] == "draft"

    # 2. Test 404 for non-existent requirement
    bad_resp = client.post(
        "/api/v1/plc/canvas/requirements/req-999999999999/generate-af",
        headers=AUTH_HEADER,
    )
    assert bad_resp.status_code == 404
    assert bad_resp.json()["detail"]["code"] == "PLC_REQUIREMENT_NOT_FOUND"


def test_api_new_project_with_af_template(client: TestClient):
    """Test creating a new project initialized with official AF V1.2 template."""
    resp = client.post(
        "/api/v1/plc/canvas/projects/new",
        json={"project_name": "AfAutoProject", "template": "af_v1_2"},
        headers=AUTH_HEADER,
    )

    assert resp.status_code == 200, resp.text
    res_data = resp.json()["data"]
    assert res_data["ok"] is True
    assert res_data["project_name"] == "AfAutoProject"
    assert res_data["template"] == "af_v1_2"
    assert res_data["project_path"].endswith("AfAutoProject.ap19")
    assert Path(res_data["project_path"]).is_file()


def test_api_canvas_default_af_template(client: TestClient):
    """Test GET /api/v1/plc/canvas/default?template=af_v1_2."""
    resp = client.get(
        "/api/v1/plc/canvas/default?template=af_v1_2&project_name=DefaultAf",
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200, resp.text
    canvas = resp.json()["data"]
    assert canvas["project_name"] == "DefaultAf"
    assert len(canvas["blocks"]) >= 10
    assert any("ControlNodes" in k for k in canvas["blocks"])
