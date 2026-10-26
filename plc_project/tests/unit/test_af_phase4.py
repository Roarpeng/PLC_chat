from __future__ import annotations

import pytest
from fastapi import HTTPException

from gateway.app.routers.plc import canvas_refactor_to_af_endpoint
from plc_engine.af import (
    LegacyAnalysis,
    LegacyToAfMapper,
    lint_af_canvas,
    refactor_canvas_to_af,
)
from plc_engine.canvas_model import (
    CanvasBlock,
    CanvasNetwork,
    CanvasState,
    CanvasTag,
    CanvasVariable,
)


def _build_hr001_mock_canvas() -> CanvasState:
    """Construct a mock legacy flat canvas mimicking HR001."""
    canvas = CanvasState(project_name="HR001_PLC")

    # 1. Tags: physical I/O mapping
    canvas.tags = {
        "I_Cyl_WorkPos": CanvasTag(
            name="I_Cyl_WorkPos",
            data_type="Bool",
            logical_address="%I0.0",
            comment="Feeder cylinder work position sensor (extend到位)",
        ),
        "I_Cyl_HomePos": CanvasTag(
            name="I_Cyl_HomePos",
            data_type="Bool",
            logical_address="%I0.1",
            comment="Feeder cylinder home position sensor (retract原点)",
        ),
        "I_Sensor_PartPresent": CanvasTag(
            name="I_Sensor_PartPresent",
            data_type="Bool",
            logical_address="%I0.2",
            comment="Optical sensor for workpiece detection (有料光电)",
        ),
        "I_EmergencyStop": CanvasTag(
            name="I_EmergencyStop",
            data_type="Bool",
            logical_address="%I0.3",
            comment="Emergency stop button normally closed contact (急停常闭)",
        ),
        "Q_Cyl_Extend": CanvasTag(
            name="Q_Cyl_Extend",
            data_type="Bool",
            logical_address="%Q0.0",
            comment="Feeder cylinder solenoid valve extend (伸出电磁阀)",
        ),
        "Q_Cyl_Retract": CanvasTag(
            name="Q_Cyl_Retract",
            data_type="Bool",
            logical_address="%Q0.1",
            comment="Feeder cylinder solenoid valve retract (缩回电磁阀)",
        ),
    }

    # 2. Legacy Block: FB1000_MainControl (Mode & Unit Master)
    canvas.blocks["FB1000_MainControl"] = CanvasBlock(
        name="FB1000_MainControl",
        block_type="FB",
        number=1000,
        interface=[
            CanvasVariable(name="AutoMode", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="ManualMode", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="EmergencyStop", data_type="Bool", section="VAR_INPUT"),
        ],
        scl_body="""// FB1000 Main Control Logic
IF #EmergencyStop THEN
    #AutoMode := FALSE;
END_IF;
""",
        status="synced",
    )

    # 3. Legacy Block: FB1060_AutoStep (Auto State Machine)
    fb1060_scl = """// FB1060 Auto Step Sequencer
CASE #iStep OF
    10: // WAIT_FOR_PART
        IF "I_Sensor_PartPresent" THEN
            #iStep := 20;
        END_IF;

    20: // CYL_EXTEND
        "Q_Cyl_Extend" := TRUE;
        "Q_Cyl_Retract" := FALSE;
        IF "I_Cyl_WorkPos" THEN
            #iStep := 30;
        END_IF;

    30: // CYL_RETRACT
        "Q_Cyl_Extend" := FALSE;
        "Q_Cyl_Retract" := TRUE;
        IF "I_Cyl_HomePos" THEN
            #iStep := 1;
        END_IF;
END_CASE;
"""
    canvas.blocks["FB1060_AutoStep"] = CanvasBlock(
        name="FB1060_AutoStep",
        block_type="FB",
        number=1060,
        interface=[
            CanvasVariable(name="iStep", data_type="DInt", section="VAR"),
        ],
        scl_body=fb1060_scl,
        status="synced",
    )

    # 4. Legacy Block: FB1080_Cylinders (Actuator manual logic)
    canvas.blocks["FB1080_Cylinders"] = CanvasBlock(
        name="FB1080_Cylinders",
        block_type="FB",
        number=1080,
        interface=[
            CanvasVariable(name="ManualExtend", data_type="Bool", section="VAR_INPUT"),
        ],
        scl_body="""// FB1080 Cylinder Manual Logic
IF #ManualExtend THEN
    "Q_Cyl_Extend" := TRUE;
END_IF;
""",
        status="synced",
    )

    return canvas


def test_legacy_to_af_mapper_hr001_mock():
    """Verify that LegacyToAfMapper successfully reverse engineers HR001 flat canvas."""
    canvas = _build_hr001_mock_canvas()
    mapper = LegacyToAfMapper(canvas, target_unit_name="U1_HR001")
    analysis = mapper.analyze()

    assert analysis.project_name == "HR001_PLC"
    assert analysis.target_unit_name == "U1_HR001"
    assert len(analysis.units) == 1

    unit = analysis.units[0]
    assert unit.unit_idx == 1
    assert "FB1000_MainControl" in unit.mode_control_blocks

    # Check EMs
    assert len(unit.ems) >= 1
    em = unit.ems[0]
    assert em.name == "AutoStep"
    assert len(em.steps) == 3

    # Check extracted steps
    step10 = next(s for s in em.steps if s.step_id == 10)
    assert step10.name == "WAIT_FOR_PART"
    assert step10.next_step_id == 20
    assert "#controlNodes.sensorPartPresent.status.signal" in step10.transition_condition

    step20 = next(s for s in em.steps if s.step_id == 20)
    assert step20.name == "CYL_EXTEND"
    assert step20.next_step_id == 30
    assert any("#controlNodes.cyl.commands.workPosition := TRUE;" in a for a in step20.actions)
    assert "#controlNodes.cyl.status.inWorkPosition" in step20.transition_condition

    step30 = next(s for s in em.steps if s.step_id == 30)
    assert step30.name == "CYL_RETRACT"
    assert step30.next_step_id == 1
    assert any("#controlNodes.cyl.commands.homePosition := TRUE;" in a for a in step30.actions)
    assert "#controlNodes.cyl.status.inHomePosition" in step30.transition_condition

    # Check Control Modules
    cm_types = {cm.cm_type for cm in em.control_modules}
    assert "LBC_TwoWayActuator" in cm_types
    assert "LBC_DigitalSignal" in cm_types

    # Check 100% I/O Retention Rate
    assert analysis.total_ios_detected == 6
    assert analysis.retained_ios_count == 6
    assert analysis.io_retention_rate == 100.0

    # Check Safety Interlocks
    assert len(analysis.interlocks_detected) >= 1
    assert any("EmergencyStop" in ic.name or "I_EmergencyStop" in ic.expression for ic in analysis.interlocks_detected)


def test_refactor_canvas_to_af():
    """Verify end-to-end refactor_canvas_to_af transformation and AF compliance."""
    canvas = _build_hr001_mock_canvas()
    new_canvas, report = refactor_canvas_to_af(canvas, target_unit_name="U1_HR001")

    # 1. Report verification
    assert report["status"] == "success"
    assert report["target_unit_name"] == "U1_HR001"
    assert report["io_retention"]["percentage"] == 100.0
    assert report["io_retention"]["total_ios"] == 6
    assert report["io_retention"]["retained_ios"] == 6
    assert len(report["ems"]) == 1
    assert len(report["block_mapping"]) == len(canvas.blocks)

    # 2. Check that legacy blocks are marked superseded
    assert new_canvas.blocks["FB1000_MainControl"].af_role == "legacy_superseded"
    assert new_canvas.blocks["FB1060_AutoStep"].af_role == "legacy_superseded"
    assert new_canvas.blocks["FB1080_Cylinders"].af_role == "legacy_superseded"
    assert "[AF-REFACTORED:" in new_canvas.blocks["FB1060_AutoStep"].comment

    # 3. Check generated AF blocks exist
    expected_af_blocks = [
        "U1_HR001::Startup",
        "U1_HR001::Main",
        "U1_HR001::ProDiag",
        "U1_HR001::CallUnit",
        "U1_HR001::EmNodes",
        "U1Em0_General::Startup",
        "U1Em0_General::Main",
        "U1Em0_General::ProDiag",
        "U1Em1_AutoStep::Startup",
        "U1Em1_AutoStep::Main",
        "U1Em1_AutoStep::ProDiag",
        "U1Em1_AutoStep::ControlNodes",
        "U1Em1_AutoStep::Sequence",
        "U1Em1_AutoStep::StepToString",
        "U1Em1_AutoStep::CallEquipment",
    ]
    for b_key in expected_af_blocks:
        assert b_key in new_canvas.blocks, f"Missing expected AF block: {b_key}"

    # 4. Verify Sequence SCL adheres to AF-02 (no direct %Q, via #controlNodes)
    seq_scl = new_canvas.blocks["U1Em1_AutoStep::Sequence"].scl_body
    assert "%Q" not in seq_scl
    assert "#controlNodes.cyl.commands.workPosition := TRUE;" in seq_scl
    assert "#controlNodes.cyl.status.inWorkPosition" in seq_scl

    # 5. Verify CallEquipment SCL adheres to AF-03 and contains I/O bindings
    call_eq_scl = new_canvas.blocks["U1Em1_AutoStep::CallEquipment"].scl_body
    assert "enableManualCmds := #statUnitStatus.mode.manual" in call_eq_scl
    assert "Hardware I/O Binding & Safety Interlocks" in call_eq_scl
    assert "%Q0.0" in call_eq_scl
    assert "%I0.0" in call_eq_scl

    # 6. Static Linter Verification: 0 architecture errors
    findings = lint_af_canvas(new_canvas)
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 0, f"Found linter errors: {errors}"


@pytest.mark.asyncio
async def test_refactor_api_endpoint():
    """Verify POST /api/v1/plc/canvas/refactor-to-af endpoint."""
    canvas = _build_hr001_mock_canvas()

    class FakePrincipal:
        subject = "test-engineer"

    body = {
        "canvas": canvas.to_dict(),
        "target_unit_name": "U1_HR001_Refactored",
    }

    resp = await canvas_refactor_to_af_endpoint(
        body=body,
        principal=FakePrincipal(),  # type: ignore[arg-type]
        request_id="req-test-af-phase4",
    )

    assert resp.ok is True
    assert resp.data is not None
    data = resp.data
    assert "canvas" in data
    assert "report" in data
    assert data["report"]["target_unit_name"] == "U1_HR001_Refactored"
    assert data["report"]["io_retention"]["percentage"] == 100.0


@pytest.mark.asyncio
async def test_refactor_api_endpoint_bad_request():
    """Verify endpoint rejects requests missing body.canvas."""
    class FakePrincipal:
        subject = "test-engineer"

    with pytest.raises(HTTPException) as exc_info:
        await canvas_refactor_to_af_endpoint(
            body={},
            principal=FakePrincipal(),  # type: ignore[arg-type]
            request_id="req-test-bad",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "CANVAS_REQUIRED"


def test_refactor_with_analog_and_motor():
    """Verify that analog inputs and motor axes are classified and retained 100%."""
    canvas = CanvasState(project_name="MachineWithMotorAndAnalog")
    canvas.tags = {
        "AI_TankPressure": CanvasTag(
            name="AI_TankPressure",
            data_type="Int",
            logical_address="%IW64",
            comment="Pressure sensor 4-20mA (压力模拟量)",
        ),
        "Q_Motor_Conveyor": CanvasTag(
            name="Q_Motor_Conveyor",
            data_type="Bool",
            logical_address="%Q1.0",
            comment="Conveyor drive start output (皮带电机启动)",
        ),
    }
    canvas.blocks["Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=1,
        scl_body="// Main cyclic",
    )

    new_canvas, report = refactor_canvas_to_af(canvas, target_unit_name="U1_ConveyorLine")

    assert report["io_retention"]["total_ios"] == 2
    assert report["io_retention"]["retained_ios"] == 2
    assert report["io_retention"]["percentage"] == 100.0

    em_cms = report["ems"][0]["cms"]
    types = {cm["cm_type"] for cm in em_cms}
    assert "LBC_AnalogInput" in types
    assert "LBC_AxisControl" in types
