from __future__ import annotations

from pathlib import Path

from plc_engine.af import (
    AfCm,
    AfEm,
    AfProject,
    AfSequence,
    AfSequenceStep,
    AfUnit,
    generate_af_project_blocks,
    get_em0_ob_numbers,
    get_em_ob_numbers,
    get_startup_zip,
    get_unit_ob_numbers,
    lint_af_canvas,
    validate_af_ob_number,
)
from plc_engine.canvas_model import CanvasBlock, CanvasState


def test_af_numbering():
    # Unit 1
    u1_obs = get_unit_ob_numbers(1)
    assert u1_obs.startup == 1000
    assert u1_obs.main == 1001
    assert u1_obs.prodiag == 1002
    assert validate_af_ob_number(1001, "unit", unit_idx=1)

    # Unit 1 EM0
    em0_obs = get_em0_ob_numbers(1)
    assert em0_obs.startup == 1005
    assert em0_obs.main == 1006
    assert em0_obs.prodiag == 1007
    assert validate_af_ob_number(1006, "em0", unit_idx=1)

    # Unit 1 EM1
    em1_obs = get_em_ob_numbers(1, 1)
    assert em1_obs.startup == 1010
    assert em1_obs.main == 1011
    assert em1_obs.prodiag == 1012
    assert validate_af_ob_number(1011, "em", unit_idx=1, em_idx=1)

    # Unit 2 EM5
    u2em5_obs = get_em_ob_numbers(2, 5)
    assert u2em5_obs.startup == 2050
    assert u2em5_obs.main == 2051
    assert u2em5_obs.prodiag == 2052
    assert validate_af_ob_number(2051, "em", unit_idx=2, em_idx=5)


def test_af_model_and_generator():
    em1 = AfEm(
        em_idx=1,
        name="Feeder",
        description="Parts feeder station",
        sequence=AfSequence(
            steps=[
                AfSequenceStep(
                    step_id=10,
                    name="WAIT_FOR_PART",
                    actions=["// wait"],
                    transition_condition="#controlNodes.sensorPartPresent.status.signal",
                    next_step_id=20,
                ),
                AfSequenceStep(
                    step_id=20,
                    name="CYL_EXTEND",
                    actions=["#controlNodes.cylFeeder.commands.workPosition := TRUE;"],
                    transition_condition="#controlNodes.cylFeeder.status.inWorkPosition",
                    next_step_id=30,
                ),
                AfSequenceStep(
                    step_id=30,
                    name="CYL_RETRACT",
                    actions=["#controlNodes.cylFeeder.commands.homePosition := TRUE;"],
                    transition_condition="#controlNodes.cylFeeder.status.inHomePosition",
                    next_step_id=1,
                ),
            ]
        ),
        control_modules=[
            AfCm(
                name="cylFeeder",
                cm_type="LBC_TwoWayActuator",
                description="Pneumatic feed cylinder",
            ),
            AfCm(
                name="sensorPartPresent",
                cm_type="LBC_DigitalSignal",
                description="Photoelectric sensor for part detection",
            ),
        ],
    )

    unit1 = AfUnit(
        unit_idx=1,
        name="AssemblyLine",
        description="Main assembly cell",
        equipment_modules=[em1],
    )

    project = AfProject(
        name="AF_Project",
        units=[unit1],
    )

    # Test serialization
    data = project.to_dict()
    restored = AfProject.from_dict(data)
    assert len(restored.units) == 1
    assert restored.units[0].equipment_modules[0].name == "Feeder"

    # Test generation
    blocks = generate_af_project_blocks(project)

    # Check Unit blocks
    assert "U1_AssemblyLine::Startup" in blocks
    assert blocks["U1_AssemblyLine::Startup"].number == 1000
    assert "U1_AssemblyLine::Main" in blocks
    assert blocks["U1_AssemblyLine::Main"].number == 1001
    assert "U1_AssemblyLine::CallUnit" in blocks
    assert "U1_AssemblyLine::EmNodes" in blocks

    # Check EM0 blocks
    assert "U1Em0_General::Startup" in blocks
    assert blocks["U1Em0_General::Startup"].number == 1005
    assert "U1Em0_General::Main" in blocks
    assert blocks["U1Em0_General::Main"].number == 1006

    # Check EM1 Feeder blocks
    assert "U1Em1_Feeder::Startup" in blocks
    assert blocks["U1Em1_Feeder::Startup"].number == 1010
    assert "U1Em1_Feeder::Main" in blocks
    assert blocks["U1Em1_Feeder::Main"].number == 1011
    assert "U1Em1_Feeder::ControlNodes" in blocks
    assert "U1Em1_Feeder::Sequence" in blocks
    assert "U1Em1_Feeder::StepToString" in blocks
    assert "U1Em1_Feeder::CallEquipment" in blocks

    # Verify ControlNodes has both CMs
    cn_scl = blocks["U1Em1_Feeder::ControlNodes"].scl_body
    assert 'cylFeeder : "LBC_TwoWayActuatorControlNodes";' in cn_scl
    assert 'sensorPartPresent : "LBC_DigitalSignalControlNodes";' in cn_scl

    # Verify Sequence SCL contains steps and conditions
    seq_scl = blocks["U1Em1_Feeder::Sequence"].scl_body
    assert "CYL_EXTEND" in seq_scl
    assert "#controlNodes.cylFeeder.commands.workPosition := TRUE;" in seq_scl

    # Verify CallEquipment binds manual mode for actuator
    call_eq_scl = blocks["U1Em1_Feeder::CallEquipment"].scl_body
    assert "enableManualCmds := #statUnitStatus.mode.manual" in call_eq_scl


def test_af_linter_clean_and_violations():
    # 1. Clean project
    em1 = AfEm(
        em_idx=1,
        name="Station1",
        sequence=AfSequence(
            steps=[
                AfSequenceStep(step_id=10, name="STEP10", actions=["#controlNodes.cyl.commands.workPosition := TRUE;"], next_step_id=1)
            ]
        ),
        control_modules=[AfCm(name="cyl", cm_type="LBC_TwoWayActuator")],
    )
    unit1 = AfUnit(unit_idx=1, name="Cell", equipment_modules=[em1])
    proj = AfProject(name="CleanProj", units=[unit1])
    blocks = generate_af_project_blocks(proj)

    canvas = CanvasState(project_name="CleanProj")
    canvas.blocks = blocks

    findings = lint_af_canvas(canvas)
    # Generated blocks should have zero errors
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 0

    # 2. Trigger Rule AF-02 (Direct %Q in sequence)
    bad_seq = CanvasBlock(
        name="Sequence",
        block_type="FB",
        software_unit="U1Em1_Station1",
        af_role="Sequence",
        scl_body="%Q0.0 := TRUE;",
        status="draft",
    )
    canvas.blocks["U1Em1_Station1::BadSeq"] = bad_seq

    findings2 = lint_af_canvas(canvas)
    af02_findings = [f for f in findings2 if f.rule_id == "AF-02"]
    assert len(af02_findings) >= 1
    assert "Direct access to physical %Q in Sequence is prohibited" in af02_findings[0].message

    # 3. Trigger Rule AF-04 (Bad OB number)
    bad_ob = CanvasBlock(
        name="Main",
        block_type="OB",
        number=999,  # invalid for U1Em1
        software_unit="U1Em1_Station1",
        af_role="OB",
        status="draft",
    )
    canvas.blocks["U1Em1_Station1::BadOB"] = bad_ob
    findings3 = lint_af_canvas(canvas)
    af04_findings = [f for f in findings3 if f.rule_id == "AF-04"]
    assert len(af04_findings) >= 1
    assert "does not match AF V1.2 EM OB numbering" in af04_findings[0].message


def test_get_startup_zip():
    zip_path = get_startup_zip()
    assert zip_path.is_file()
    assert zip_path.name.endswith(".zip")
