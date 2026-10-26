"""AF V1.2 Official Code & SCL Block Generator.

Implements official Siemens Automation Framework V1.2 block generation:
- Unit Level: OB Startup (u000), OB Main (u001), OB ProDiag (u002), FB CallUnit, DB EmNodes, DB Config, DB SimulationData
- EM Level: OB Startup (uxx0), OB Main (uxx1), OB ProDiag (uxx2), FB CallEquipment, FB Sequence, FC StepToString, DB ControlNodes, DB HmiInterface, DB Config, DB Alarms
- CM Integration: LBC_TwoWayActuator, LBC_SimpleActuator, LBC_DigitalSignal, LBC_AnalogInput, LBC_AxisControl etc.
"""

from __future__ import annotations

from typing import Any

from plc_engine.af.af_model import AfCm, AfEm, AfProject, AfSequence, AfSequenceStep, AfUnit
from plc_engine.af.af_numbering import get_em0_ob_numbers, get_em_ob_numbers, get_unit_ob_numbers
from plc_engine.canvas_model import CanvasBlock, CanvasNetwork, CanvasState, CanvasVariable


def generate_af_project_blocks(project: AfProject) -> dict[str, CanvasBlock]:
    """Generate all CanvasBlocks for an entire AF V1.2 project."""
    blocks: dict[str, CanvasBlock] = {}
    for unit in project.units:
        unit_blocks = generate_af_unit_blocks(unit)
        blocks.update(unit_blocks)
    return blocks


def generate_af_unit_blocks(unit: AfUnit) -> dict[str, CanvasBlock]:
    """Generate all Software Unit blocks for a Unit (U<n>_<UnitName>) and its EMs."""
    blocks: dict[str, CanvasBlock] = {}
    unit_su = unit.unit_name
    obs = get_unit_ob_numbers(unit.unit_idx)

    # 1. Unit OBs
    blocks[f"{unit_su}::Startup"] = CanvasBlock(
        name="Startup",
        block_type="OB",
        number=obs.startup,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="OB",
        scl_body=f'// AF V1.2 Unit {unit.unit_idx} Startup\n"CallUnit_DB"();\n',
        status="draft",
    )
    blocks[f"{unit_su}::Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=obs.main,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="OB",
        scl_body=f'// AF V1.2 Unit {unit.unit_idx} Main Cyclic\n"CallUnit_DB"();\n',
        status="draft",
    )
    blocks[f"{unit_su}::ProDiag"] = CanvasBlock(
        name="ProDiag",
        block_type="OB",
        number=obs.prodiag,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="OB",
        scl_body='// AF V1.2 Unit ProDiag\n;\n',
        status="draft",
    )

    # 2. Unit DB EmNodes
    db_em_nodes_scl = f"""DATA_BLOCK "EmNodes"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
NON_RETAIN
STRUCT
    unitStatus : "LUC_typeUnitStatus";
    emFeedback : Array[0..15] of "LAF_typeEmFeedback";
    emRelations : Array[0..15] of "LAF_typeEmRelations";
    signalStack : "LUC_typeSignalStack";
END_STRUCT;
BEGIN
END_DATA_BLOCK
"""
    blocks[f"{unit_su}::EmNodes"] = CanvasBlock(
        name="EmNodes",
        block_type="DB",
        number=unit.unit_idx * 1000 + 10,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="EmNodes",
        scl_body=db_em_nodes_scl,
        status="draft",
    )

    # 3. Unit FB CallUnit
    fb_call_unit_scl = f"""FUNCTION_BLOCK "CallUnit"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR_IN_OUT
    emNodes : "EmNodes";
END_VAR
VAR
    instStatusCollector : "LUC_StatusCollector";
    instInterfaceManager : "LUC_InterfaceManager";
    instModeStateManager : "LPMLV2022_UnitModeStateManager";
    instSetUnitStatus : "LUC_SetUnitStatus";
    instUpdateHistory : "LUC_UpdateModeStateHistory";
    instStateTimes : "LPMLV2022_UnitModeStateTimes";
    instSignalStack : "LUC_SignalStack";
END_VAR
BEGIN
    // Step 1: Collect Alarms
    // "CollectAlarms"();

    // Step 2: LUC_StatusCollector
    #instStatusCollector(
        status := #emNodes.unitStatus,
        emFeedback := #emNodes.emFeedback
    );

    // Step 3: LUC_InterfaceManager
    #instInterfaceManager(
        status := #emNodes.unitStatus
    );

    // Step 4: LPMLV2022_UnitModeStateManager
    #instModeStateManager(
        status := #emNodes.unitStatus
    );

    // Step 5: LUC_SetUnitStatus
    #instSetUnitStatus(
        unitStatus => #emNodes.unitStatus
    );

    // Step 6: Mode and State Times & History
    #instUpdateHistory(
        currentMode := #emNodes.unitStatus.mode.currentMode,
        currentState := #emNodes.unitStatus.state.currentState
    );
END_FUNCTION_BLOCK
"""
    blocks[f"{unit_su}::CallUnit"] = CanvasBlock(
        name="CallUnit",
        block_type="FB",
        number=unit.unit_idx * 1000 + 1,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="CallUnit",
        scl_body=fb_call_unit_scl,
        status="draft",
    )

    # Generate EM0 General
    em0_blocks = _generate_em0_blocks(unit)
    blocks.update(em0_blocks)

    # Generate each process Equipment Module (EM1..EM99)
    for em in unit.equipment_modules:
        em.unit_idx = unit.unit_idx  # type: ignore[attr-defined]
        em_blocks = generate_af_em_blocks(unit.unit_idx, em, unit_namespace=unit.namespace)
        blocks.update(em_blocks)

    return blocks


def _generate_em0_blocks(unit: AfUnit) -> dict[str, CanvasBlock]:
    """Generate U<n>Em0_General blocks."""
    blocks: dict[str, CanvasBlock] = {}
    su = f"U{unit.unit_idx}Em0_General"
    obs = get_em0_ob_numbers(unit.unit_idx)

    blocks[f"{su}::Startup"] = CanvasBlock(
        name="Startup",
        block_type="OB",
        number=obs.startup,
        software_unit=su,
        af_role="OB",
        scl_body=f'// AF V1.2 EM0 Startup\n"CallEquipment_DB"();\n',
        status="draft",
    )
    blocks[f"{su}::Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=obs.main,
        software_unit=su,
        af_role="OB",
        scl_body=f'// AF V1.2 EM0 Main\n"CallEquipment_DB"();\n',
        status="draft",
    )
    blocks[f"{su}::ProDiag"] = CanvasBlock(
        name="ProDiag",
        block_type="OB",
        number=obs.prodiag,
        software_unit=su,
        af_role="OB",
        scl_body='// AF V1.2 EM0 ProDiag\n;\n',
        status="draft",
    )
    return blocks


def generate_af_em_blocks(unit_idx: int, em: AfEm, unit_namespace: str = "") -> dict[str, CanvasBlock]:
    """Generate all Software Unit blocks for an Equipment Module."""
    blocks: dict[str, CanvasBlock] = {}
    su = f"U{unit_idx}Em{em.em_idx}_{em.name}"
    ns = em.namespace or (f"{unit_namespace}.Em{em.em_idx}" if unit_namespace else "")
    obs = get_em_ob_numbers(unit_idx, em.em_idx)

    # 1. EM OBs
    blocks[f"{su}::Startup"] = CanvasBlock(
        name="Startup",
        block_type="OB",
        number=obs.startup,
        software_unit=su,
        namespace=ns,
        af_role="OB",
        scl_body=f'// AF V1.2 EM {em.em_idx} Startup\n"CallEquipment_DB"();\n',
        status="draft",
    )
    blocks[f"{su}::Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=obs.main,
        software_unit=su,
        namespace=ns,
        af_role="OB",
        scl_body=f'// AF V1.2 EM {em.em_idx} Main Cyclic\n"CallEquipment_DB"();\n',
        status="draft",
    )
    blocks[f"{su}::ProDiag"] = CanvasBlock(
        name="ProDiag",
        block_type="OB",
        number=obs.prodiag,
        software_unit=su,
        namespace=ns,
        af_role="OB",
        scl_body='// AF V1.2 EM ProDiag\n;\n',
        status="draft",
    )

    # 2. DB ControlNodes
    cm_fields = []
    for cm in em.control_modules:
        cm_fields.append(f'    {cm.name} : "{cm.cm_type}ControlNodes";')
    cm_fields_str = "\n".join(cm_fields)

    db_ctrl_nodes_scl = f"""DATA_BLOCK "ControlNodes"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
NON_RETAIN
STRUCT
    sequence : "LAF_typeSequence";
    jobs : "LAF_typeJobs";
{cm_fields_str}
END_STRUCT;
BEGIN
END_DATA_BLOCK
"""
    blocks[f"{su}::ControlNodes"] = CanvasBlock(
        name="ControlNodes",
        block_type="DB",
        number=unit_idx * 1000 + em.em_idx * 10 + 3,
        software_unit=su,
        namespace=ns,
        af_role="ControlNodes",
        scl_body=db_ctrl_nodes_scl,
        status="draft",
    )

    # 3. FC StepToString
    step_cases = []
    for s in em.sequence.steps:
        step_cases.append(f'        {s.step_id}: "StepToString" := \'{s.name}\';')
    step_cases_str = "\n".join(step_cases) or "        0: \"StepToString\" := 'INIT';"

    fc_step_str_scl = f"""FUNCTION "StepToString" : String
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR_INPUT
    step : DInt;
END_VAR
BEGIN
    CASE #step OF
{step_cases_str}
        ELSE
            "StepToString" := 'UNKNOWN';
    END_CASE;
END_FUNCTION
"""
    blocks[f"{su}::StepToString"] = CanvasBlock(
        name="StepToString",
        block_type="FC",
        number=unit_idx * 1000 + em.em_idx * 10 + 2,
        software_unit=su,
        namespace=ns,
        af_role="StepToString",
        scl_body=fc_step_str_scl,
        status="draft",
    )

    # 4. FB Sequence
    steps_code = []
    for s in em.sequence.steps:
        acts = "\n        ".join(s.actions) if s.actions else "// Step actions"
        trans = s.transition_condition or "TRUE"
        steps_code.append(f"""    // Step {s.step_id}: {s.name}
    {s.step_id}:
        {acts}
        IF {trans} THEN
            #statStepNext := {s.next_step_id};
        END_IF;""")

    steps_code_str = "\n\n".join(steps_code) if steps_code else """    10:
        // Default step
        IF TRUE THEN
            #statStepNext := 20;
        END_IF;"""

    fb_seq_scl = f"""FUNCTION_BLOCK "Sequence"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR_IN_OUT
    controlNodes : "ControlNodes";
END_VAR
VAR
    statStepCurrent : DInt := 0;
    statStepNext : DInt := 0;
    statSequenceControl : "LAF_typeSequenceControl";
    statSequenceStatus : "LAF_typeSequenceStatus";
    instControlSclSequence : "LAF_ControlSclSequence";
    instStatusSclSequence : "LAF_StatusSclSequence";
END_VAR
BEGIN
    // Call LAF_ControlSclSequence to manage step transitions and sequencing
    #instControlSclSequence(
        stepNext := #statStepNext,
        commands := #controlNodes.sequence.commands,
        sequenceControl => #statSequenceControl,
        stepCurrent => #statStepCurrent
    );

    // Sequence Step State Machine
    CASE #statStepCurrent OF
        0: // Initializing
            #statStepNext := 1;

        1: // Ready
            IF #controlNodes.sequence.commands.start THEN
                #statStepNext := 10;
            END_IF;

{steps_code_str}

        999: // Error step
            #controlNodes.sequence.status.error := TRUE;
    END_CASE;

    // Call LAF_StatusSclSequence
    #instStatusSclSequence(
        stepCurrent := #statStepCurrent,
        sequenceControl := #statSequenceControl,
        status => #controlNodes.sequence.status
    );
END_FUNCTION_BLOCK
"""
    blocks[f"{su}::Sequence"] = CanvasBlock(
        name="Sequence",
        block_type="FB",
        number=unit_idx * 1000 + em.em_idx * 10 + 1,
        software_unit=su,
        namespace=ns,
        af_role="Sequence",
        scl_body=fb_seq_scl,
        status="draft",
    )

    # 5. FB CallEquipment
    cm_calls = []
    for cm in em.control_modules:
        is_actuator = "actuator" in cm.cm_type.lower() or "motor" in cm.cm_type.lower() or "drive" in cm.cm_type.lower() or "axis" in cm.cm_type.lower()
        manual_bind = "\n        enableManualCmds := #statUnitStatus.mode.manual," if is_actuator else ""
        cm_calls.append(f"""    // Call CM: {cm.name} ({cm.cm_type})
    #inst_{cm.name}({manual_bind}
        controlNodes := #controlNodes.{cm.name}
    );""")
    cm_calls_str = "\n\n".join(cm_calls)

    cm_instances = "\n".join([f'    inst_{cm.name} : "{cm.cm_type}";' for cm in em.control_modules])

    fb_call_eq_scl = f"""FUNCTION_BLOCK "CallEquipment"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR_IN_OUT
    controlNodes : "ControlNodes";
END_VAR
VAR
    statUnitStatus : "LUC_typeUnitStatus";
    instInterlink : "LUC_InterlinkToParent";
    instControlEm : "LAF_ControlEm";
    instMapStatus : "LAF_MapUnitStatusToSequence";
    instSequence : "Sequence";
{cm_instances}
END_VAR
BEGIN
    // Step 1: Interlink to Parent Unit
    #instInterlink(
        unitStatus => #statUnitStatus
    );
    #instControlEm(
        unitStatus := #statUnitStatus
    );

    // Step 2 & 3: Map Unit Status to Sequence
    #instMapStatus(
        unitStatus := #statUnitStatus,
        sequenceCommands => #controlNodes.sequence.commands
    );

    // Step 4: Call FB Sequence
    #instSequence(
        controlNodes := #controlNodes
    );

    // Step 5: Call Control Modules
{cm_calls_str}

    // Step 6: Determine State Complete (SC)
    // #emFeedback.stateComplete := #controlNodes.sequence.status.stateComplete;
END_FUNCTION_BLOCK
"""
    blocks[f"{su}::CallEquipment"] = CanvasBlock(
        name="CallEquipment",
        block_type="FB",
        number=unit_idx * 1000 + em.em_idx * 10 + 0,
        software_unit=su,
        namespace=ns,
        af_role="CallEquipment",
        scl_body=fb_call_eq_scl,
        status="draft",
    )

    return blocks
