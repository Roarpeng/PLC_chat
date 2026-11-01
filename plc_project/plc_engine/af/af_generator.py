"""AF V1.2 Official Code & SCL Block Generator.

Implements official Siemens Automation Framework V1.2 block generation:
- Unit Level: OB Startup (u000), OB Main (u001), OB ProDiag (u002), FB CallUnit, DB EmNodes, DB Config, DB SimulationData
- EM Level: OB Startup (uxx0), OB Main (uxx1), OB ProDiag (uxx2), FB CallEquipment, FB Sequence, FC StepToString, DB ControlNodes, DB HmiInterface, DB Config, DB Alarms
- CM Integration: LBC_TwoWayActuator, LBC_SimpleActuator, LBC_DigitalSignal, LBC_AnalogInput, LBC_AxisControl etc.

两种生成模式(``self_contained``):
- ``False``(默认,library):实例化官方库类型(LUC_*/LAF_*/LBC_*/LPMLV2022_*),
  要求目标 TIA 工程已导入官方 AF 库(方案 B 依赖库导入通道)。
- ``True``(self_contained,自举):生成**不引用任何官方库类型**的纯 SCL——
  序列 FB 用 CASE 步进机直接读写 ControlNodes DB,CallEquipment FB 直接
  驱动 CM 命令字段,模式管理简化为单元启停 + 手/自动枚举。产物可零依赖
  编译(方案 A 自举),但属简化实现,块注释里诚实标注"自举简化实现,
  非官方库等价认证"。
"""

from __future__ import annotations

from plc_engine.af.af_model import AfCm, AfEm, AfProject, AfUnit
from plc_engine.af.af_numbering import get_em0_ob_numbers, get_em_ob_numbers, get_unit_ob_numbers
from plc_engine.canvas_model import CanvasBlock

#: 自举模式产物中禁止出现的官方库前缀(测试据此断言零库引用)
_SELF_CONTAINED_FORBIDDEN_PREFIXES = ("LUC_", "LAF_", "LBC_", "LPMLV2022_")


def generate_af_project_blocks(
    project: AfProject,
    *,
    self_contained: bool = False,
    tag_types: dict[str, str] | None = None,
) -> dict[str, CanvasBlock]:
    """Generate all CanvasBlocks for an entire AF V1.2 project.

    ``tag_types``: 画布 tag 名 → data_type(Int/Bool/…)。自举直驱线写整型
    tag 时不能发 Bool 成员(TIA 不允许 Bool→Int 隐式,真机 U1Em1 案例)。
    """
    blocks: dict[str, CanvasBlock] = {}
    for unit in project.units:
        unit_blocks = generate_af_unit_blocks(unit, self_contained=self_contained, tag_types=tag_types)
        blocks.update(unit_blocks)
    return blocks


def generate_af_unit_blocks(
    unit: AfUnit,
    *,
    self_contained: bool = False,
    tag_types: dict[str, str] | None = None,
) -> dict[str, CanvasBlock]:
    """Generate all Software Unit blocks for a Unit (U<n>_<UnitName>) and its EMs."""
    blocks: dict[str, CanvasBlock] = {}
    unit_su = unit.unit_name
    obs = get_unit_ob_numbers(unit.unit_idx)

    # 自举模式块名必须全局唯一(TIA 块名不因软件单元分组而隔离,8 个 EM 各一个
    # "Sequence" 会重名冲突):统一用 su 前缀标题,实例 DB 同前缀供 OB 调用。
    unit_call_db = f'"{unit_su}_CallUnit_DB"' if self_contained else '"CallUnit_DB"'

    # 1. Unit OBs
    blocks[f"{unit_su}::Startup"] = CanvasBlock(
        name="Startup",
        block_type="OB",
        number=obs.startup,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="OB",
        scl_body=f"// AF V1.2 Unit {unit.unit_idx} Startup\n{unit_call_db}();\n",
        status="draft",
    )
    blocks[f"{unit_su}::Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=obs.main,
        software_unit=unit_su,
        namespace=unit.namespace,
        af_role="OB",
        scl_body=f"// AF V1.2 Unit {unit.unit_idx} Main Cyclic\n{unit_call_db}();\n",
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
    if self_contained:
        # 自举模式:全部内联 Struct,零官方库类型引用;标题带 su 前缀保全局唯一
        db_em_nodes_scl = f"""DATA_BLOCK "{unit_su}_EmNodes"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
NON_RETAIN
STRUCT
    unitStatus : Struct
        mode : Struct
            off : Bool;
            manual : Bool;
            auto : Bool;
        end_struct;
        state : Struct
            currentState : Int;
            error : Bool;
        end_struct;
    end_struct;
END_STRUCT;
BEGIN
END_DATA_BLOCK
"""
    else:
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
    if self_contained:
        # 自举模式:单元启停 + 手/自动枚举的最小模式管理(非官方库等价认证)。
        # 直接绝对引用 "{unit_su}_EmNodes"(自举不生成 UDT,VAR_IN_OUT 按 UDT
        # 类型传参会引用不存在的类型)。
        fb_call_unit_scl = f"""FUNCTION_BLOCK "{unit_su}_CallUnit"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
BEGIN
    // ==============================================================
    // 自举简化实现,非官方库等价认证
    // 官方单元模式/状态管理(LUC/LPMLV2022 全家桶)的最小子集:
    // 单元启停 + 手/自动枚举互斥;不含模式历史/状态时间/信号栈。
    // ==============================================================
    // 出错优先:复位全部模式并停在错误态
    IF "{unit_su}_EmNodes".unitStatus.state.error THEN
        "{unit_su}_EmNodes".unitStatus.mode.off := TRUE;
        "{unit_su}_EmNodes".unitStatus.mode.manual := FALSE;
        "{unit_su}_EmNodes".unitStatus.mode.auto := FALSE;
        "{unit_su}_EmNodes".unitStatus.state.currentState := 4; // 出错
        RETURN;
    END_IF;

    // 模式互斥(自举简化:手动优先于自动)
    IF "{unit_su}_EmNodes".unitStatus.mode.manual THEN
        "{unit_su}_EmNodes".unitStatus.mode.auto := FALSE;
    END_IF;

    // 状态推进:停机 -> 待机;任一模式激活 -> 执行
    IF "{unit_su}_EmNodes".unitStatus.mode.off THEN
        "{unit_su}_EmNodes".unitStatus.state.currentState := 1; // 待机
    ELSIF "{unit_su}_EmNodes".unitStatus.mode.auto OR "{unit_su}_EmNodes".unitStatus.mode.manual THEN
        "{unit_su}_EmNodes".unitStatus.state.currentState := 3; // 执行
    ELSE
        "{unit_su}_EmNodes".unitStatus.state.currentState := 2; // 就绪
    END_IF;
END_FUNCTION_BLOCK
"""
    else:
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
    # 自举模式:CallUnit 实例 DB(OB 只能经实例 DB 调 FB;官方 AF 同款形态,
    # 但类型是自举的 "{unit_su}_CallUnit")
    if self_contained:
        db_call_unit_scl = f"""DATA_BLOCK "{unit_su}_CallUnit_DB"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
"{unit_su}_CallUnit"
BEGIN
END_DATA_BLOCK
"""
        blocks[f"{unit_su}::CallUnit_DB"] = CanvasBlock(
            name="CallUnit_DB",
            block_type="DB",
            number=unit.unit_idx * 1000 + 11,
            software_unit=unit_su,
            namespace=unit.namespace,
            af_role="CallUnit_DB",
            scl_body=db_call_unit_scl,
            status="draft",
        )

    # Generate EM0 General
    em0_blocks = _generate_em0_blocks(unit, self_contained=self_contained)
    blocks.update(em0_blocks)

    # Generate each process Equipment Module (EM1..EM99)
    for em in unit.equipment_modules:
        em.unit_idx = unit.unit_idx  # type: ignore[attr-defined]
        em_blocks = generate_af_em_blocks(
            unit.unit_idx, em, unit_namespace=unit.namespace,
            self_contained=self_contained, tag_types=tag_types,
        )
        blocks.update(em_blocks)

    return blocks


def _generate_em0_blocks(unit: AfUnit, *, self_contained: bool = False) -> dict[str, CanvasBlock]:
    """Generate U<n>Em0_General blocks."""
    blocks: dict[str, CanvasBlock] = {}
    su = f"U{unit.unit_idx}Em0_General"
    obs = get_em0_ob_numbers(unit.unit_idx)
    # EM0 无自举 CallEquipment:自举模式下 OB 体保持空语句(诚实最小化),
    # 库模式沿用官方 AF 的 CallEquipment_DB 调用占位(需库导入后才可编译)
    em0_body = ";\n" if self_contained else '"CallEquipment_DB"();\n'

    blocks[f"{su}::Startup"] = CanvasBlock(
        name="Startup",
        block_type="OB",
        number=obs.startup,
        software_unit=su,
        af_role="OB",
        scl_body=f"// AF V1.2 EM0 Startup\n{em0_body}",
        status="draft",
    )
    blocks[f"{su}::Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=obs.main,
        software_unit=su,
        af_role="OB",
        scl_body=f"// AF V1.2 EM0 Main\n{em0_body}",
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


def generate_af_em_blocks(
    unit_idx: int,
    em: AfEm,
    unit_namespace: str = "",
    *,
    self_contained: bool = False,
    tag_types: dict[str, str] | None = None,
) -> dict[str, CanvasBlock]:
    """Generate all Software Unit blocks for an Equipment Module."""
    blocks: dict[str, CanvasBlock] = {}
    su = f"U{unit_idx}Em{em.em_idx}_{em.name}"
    ns = em.namespace or (f"{unit_namespace}.Em{em.em_idx}" if unit_namespace else "")
    obs = get_em_ob_numbers(unit_idx, em.em_idx)
    # 自举模式:标题/实例 DB 带 su 前缀保全局唯一(真机编译教训:
    # 8 个 EM 各一个 "Sequence"/"CallEquipment"/"ControlNodes" 重名冲突)
    ctrl_db = f"{su}_ControlNodes"
    seq_fb = f"{su}_Sequence"
    call_eq_fb = f"{su}_CallEquipment"
    step_fc = f"{su}_StepToString"
    call_eq_db = f"{su}_CallEquipment_DB"
    em_call_db = f'"{call_eq_db}"' if self_contained else '"CallEquipment_DB"'

    # 1. EM OBs
    blocks[f"{su}::Startup"] = CanvasBlock(
        name="Startup",
        block_type="OB",
        number=obs.startup,
        software_unit=su,
        namespace=ns,
        af_role="OB",
        scl_body=f"// AF V1.2 EM {em.em_idx} Startup\n{em_call_db}();\n",
        status="draft",
    )
    blocks[f"{su}::Main"] = CanvasBlock(
        name="Main",
        block_type="OB",
        number=obs.main,
        software_unit=su,
        namespace=ns,
        af_role="OB",
        scl_body=f"// AF V1.2 EM {em.em_idx} Main Cyclic\n{em_call_db}();\n",
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
    if self_contained:
        # 自举模式:CM 与 sequence 全部内联 Struct,零官方库类型引用;标题带 su 前缀
        cm_structs = "\n".join(_self_contained_cm_struct(cm) for cm in em.control_modules)
        db_ctrl_nodes_scl = f"""DATA_BLOCK "{ctrl_db}"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
NON_RETAIN
STRUCT
    sequence : Struct
        commands : Struct
            start : Bool;
            stop : Bool;
            reset : Bool;
        end_struct;
        status : Struct
            stepCurrent : DInt;
            busy : Bool;
            error : Bool;
            stateComplete : Bool;
        end_struct;
    end_struct;
    jobs : Struct
        selectedJob : Int;
    end_struct;
{cm_structs}
END_STRUCT;
BEGIN
END_DATA_BLOCK
"""
    else:
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

    # 3. FC StepToString(两种模式无库类型引用;自举标题带 su 前缀保唯一)
    fc_name = step_fc if self_contained else "StepToString"
    # FC 返回值赋值必须用裸函数名标识符:带引号的 "{fc}" 是全局符号引用,
    # 编译器按未定义全局量报错(真机二分轮A:8/8 EM 的 StepToString 不一致,
    # 26 错全数来自 CASE 各分支的引号赋值)。生成名恒为合法标识符(su 前缀)。
    step_cases = []
    for s in em.sequence.steps:
        step_cases.append(f"        {s.step_id}: {fc_name} := '{s.name}';")
    step_cases_str = "\n".join(step_cases) or f"        0: {fc_name} := 'INIT';"

    fc_step_str_scl = f"""FUNCTION "{fc_name}" : String
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR_INPUT
    step : DInt;
END_VAR
BEGIN
    CASE #step OF
{step_cases_str}
        ELSE
            {fc_name} := 'UNKNOWN';
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
    first_step_id = em.sequence.steps[0].step_id if em.sequence.steps else 10

    if self_contained:
        # 自举模式:CASE 步进机直接读写 ControlNodes DB(绝对引用——自举不生成
        # UDT,VAR_IN_OUT 按 "ControlNodes" 类型传参引用的是不存在的类型),
        # 等价官方步序控制器的简化自举版(边沿/保持/监控从简)
        fb_seq_scl = f"""FUNCTION_BLOCK "{seq_fb}"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR
    statStepCurrent : DInt := 0;
    statStepNext : DInt := 0;
END_VAR
BEGIN
    // ==============================================================
    // 自举简化实现,非官方库等价认证
    // 官方步序控制器的简化自举版:CASE 步进状态机直接读写
    // ControlNodes DB;步迁移采用无条件接受(无边沿/保持/监控时间)。
    // ==============================================================
    // 复位回 Ready(自举简化)
    IF #controlNodes.sequence.commands.reset THEN
        #statStepNext := 1;
    END_IF;

    // 步迁移:接受上一周期计算出的下一步
    #statStepCurrent := #statStepNext;

    CASE #statStepCurrent OF
        0: // Initializing
            #statStepNext := 1;

        1: // Ready
            IF #controlNodes.sequence.commands.start THEN
                #statStepNext := {first_step_id};
            END_IF;

{steps_code_str}

        999: // Error step
            #controlNodes.sequence.status.error := TRUE;
    END_CASE;

    // 状态回写(自举简化)
    #controlNodes.sequence.status.stepCurrent := #statStepCurrent;
    #controlNodes.sequence.status.busy := #statStepCurrent >= {first_step_id};
    // stateComplete 由上层结合末步判定,自举实现从简恒 FALSE
    #controlNodes.sequence.status.stateComplete := FALSE;
END_FUNCTION_BLOCK
"""
        # 步序动作/条件由 mapper 以 #controlNodes. 前缀生成;在此整体替换为
        # 绝对 DB 引用,与去掉 VAR_IN_OUT 的接口保持一致
        fb_seq_scl = fb_seq_scl.replace("#controlNodes.", f'"{ctrl_db}".')
    else:
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
    if self_contained:
        cm_drive_lines = "\n".join(
            _self_contained_cm_drive_lines(cm, tag_types=tag_types or {}) for cm in em.control_modules
        )
        fb_call_eq_scl = f"""FUNCTION_BLOCK "{call_eq_fb}"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
VAR
    statUnitStatus : Struct
        mode : Struct
            manual : Bool := FALSE;
            auto : Bool := TRUE;
        end_struct;
        state : Struct
            error : Bool;
        end_struct;
    end_struct;
    instSequence : "{seq_fb}";
END_VAR
BEGIN
    // ==============================================================
    // 自举简化实现,非官方库等价认证
    // 官方 CallEquipment 的最小自举子集:
    // 1) 调用本 EM 自举 Sequence(CASE 步进机);
    // 2) 直接驱动 CM 命令字段:ControlNodes 命令 -> 物理 %Q 输出,
    //    物理输入 -> ControlNodes 状态(等价 CM 库块的内联最小实现,
    //    不含手动命令门控/监控时间)。
    // ==============================================================
    IF #statUnitStatus.mode.auto THEN
        #instSequence();
    ELSE
        #controlNodes.sequence.commands.start := FALSE; // 非自动模式暂停步序
    END_IF;

{cm_drive_lines}
END_FUNCTION_BLOCK
"""
        # CM 直驱/mapper 语句统一 #controlNodes. 前缀,替换为绝对 DB 引用
        fb_call_eq_scl = fb_call_eq_scl.replace("#controlNodes.", f'"{ctrl_db}".')
    else:
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

    # 自举模式:CallEquipment 实例 DB(EM 的 Startup/Main OB 经它调用;
    # OB 不能直接调用 FB,实例 DB 是唯一合法形态)
    if self_contained:
        db_call_eq_scl = f"""DATA_BLOCK "{call_eq_db}"
{'{ S7_Optimized_Access := \'TRUE\' }'}
VERSION : 0.1
"{call_eq_fb}"
BEGIN
END_DATA_BLOCK
"""
        blocks[f"{su}::CallEquipment_DB"] = CanvasBlock(
            name="CallEquipment_DB",
            block_type="DB",
            number=unit_idx * 1000 + em.em_idx * 10 + 5,
            software_unit=su,
            namespace=ns,
            af_role="CallEquipment_DB",
            scl_body=db_call_eq_scl,
            status="draft",
        )

    return blocks


# =============================================================================
# 自举(self_contained)模式辅助模板
# =============================================================================


def _strip_lbc_prefix(cm_type: str) -> str:
    """CM 类型通用标签(去掉官方库前缀,自举产物禁止出现 LBC_ 等 token)。"""
    t = str(cm_type or "")
    for prefix in _SELF_CONTAINED_FORBIDDEN_PREFIXES:
        if t.startswith(prefix):
            return t[len(prefix):]
    return t


def _self_contained_cm_struct(cm: AfCm) -> str:
    """自举模式 CM 的内联 Struct 声明(零官方库类型引用)。

    结构与序列动作/条件翻译使用的 #controlNodes.<cm>.commands/status
    路径严格一致,保证 CASE 步进机与 CallEquipment 直驱代码可编译。
    """
    t = str(cm.cm_type)
    if t == "LBC_TwoWayActuator":
        body = """        commands : Struct
            workPosition : Bool;
            homePosition : Bool;
        end_struct;
        status : Struct
            inWorkPosition : Bool;
            inHomePosition : Bool;
        end_struct;"""
    elif t == "LBC_SimpleActuator":
        body = """        commands : Struct
            on : Bool;
        end_struct;
        status : Struct
            on : Bool;
        end_struct;"""
    elif t == "LBC_DigitalSignal":
        body = """        status : Struct
            signal : Bool;
        end_struct;"""
    elif t == "LBC_AnalogInput":
        body = """        status : Struct
            value : Int;
            signal : Bool;
        end_struct;"""
    elif t == "LBC_AnalogOutput":
        body = """        commands : Struct
            value : Int;
        end_struct;"""
    elif t == "LBC_AxisControl":
        body = """        commands : Struct
            start : Bool;
            stop : Bool;
        end_struct;
        status : Struct
            running : Bool;
        end_struct;"""
    else:
        body = """        commands : Struct
            cmd : Bool;
        end_struct;
        status : Struct
            feedback : Bool;
        end_struct;"""
    label = _strip_lbc_prefix(t)
    # 声明区禁 // 注释(外部源约束),CM 名即自解释;诚实标注由 FB 体注释承载
    return f"    {cm.name} : Struct\n{body}\n    end_struct;"


def _self_contained_cm_drive_lines(cm: AfCm, tag_types: dict[str, str] | None = None) -> str:
    """自举模式 CallEquipment 内的 CM 命令/状态直驱语句。

    命令字段 -> 物理输出(%Q/%QW),物理输入(%I/%IW)-> 状态字段;
    符号优先(画布标签名),无标签时退回绝对地址。

    整型 tag 不发 Bool 直赋(TIA 不允许 Bool→Int 隐式,真机 U1Em1 案例
    "QW10"(Int) := …commands.on(Bool) 报 2 错)——改发 IF/ELSE 0/1 合法形态。
    """
    io = cm.io_mapping or {}
    types = tag_types or {}

    def _is_int_target(tag: str) -> bool:
        t = (types.get(tag) or "").strip().lower()
        return t in {"int", "dint", "uint", "udint", "sint", "usint", "byte", "word", "dword"}

    def _bool_write(tag: str, addr: str, cond: str) -> str:
        """Bool 命令 → tag 的合法写入:Bool tag 直赋;整型 tag 发 IF/ELSE 0/1。"""
        sym = f'"{tag}"' if tag else str(addr)
        if tag and _is_int_target(tag):
            return f"    IF {cond} THEN {sym} := 1; ELSE {sym} := 0; END_IF;"
        return f"    {sym} := {cond};"

    def _sym(tag: str, addr: str) -> str:
        return f'"{tag}"' if tag else str(addr)

    lines = [f"    // ---- CM {cm.name}({_strip_lbc_prefix(cm.cm_type)})自举内联直驱 ----"]
    t = str(cm.cm_type)
    if t == "LBC_TwoWayActuator":
        if io.get("workCmd") or io.get("workCmdTag"):
            lines.append(
                _bool_write(
                    io.get("workCmdTag", ""), io.get("workCmd", ""),
                    f"#controlNodes.{cm.name}.commands.workPosition",
                )
            )
        if io.get("homeCmd") or io.get("homeCmdTag"):
            lines.append(
                _bool_write(
                    io.get("homeCmdTag", ""), io.get("homeCmd", ""),
                    f"#controlNodes.{cm.name}.commands.homePosition",
                )
            )
        if io.get("workSensor") or io.get("workSensorTag"):
            lines.append(
                f"    #controlNodes.{cm.name}.status.inWorkPosition := {_sym(io.get('workSensorTag', ''), io.get('workSensor', ''))};"
            )
        if io.get("homeSensor") or io.get("homeSensorTag"):
            lines.append(
                f"    #controlNodes.{cm.name}.status.inHomePosition := {_sym(io.get('homeSensorTag', ''), io.get('homeSensor', ''))};"
            )
    elif t == "LBC_SimpleActuator":
        if io.get("command") or io.get("commandTag"):
            lines.append(
                _bool_write(
                    io.get("commandTag", ""), io.get("command", ""),
                    f"#controlNodes.{cm.name}.commands.on",
                )
            )
    elif t == "LBC_DigitalSignal":
        if io.get("signal") or io.get("signalTag"):
            lines.append(
                f"    #controlNodes.{cm.name}.status.signal := {_sym(io.get('signalTag', ''), io.get('signal', ''))};"
            )
    elif t == "LBC_AnalogInput":
        if io.get("value") or io.get("tag"):
            tag = str(io.get("tag", "") or "")
            sym = _sym(tag, io.get("value", ""))
            # 权威类型分流:Bool 输入写 .signal(Bool)——.value(Int) 收 Bool 是
            # TIA 非法的隐式转换(真机 U1Em1:ITempErr 画布误记 Int 实为 Bool)
            if tag and (types.get(tag) or "").strip().lower() == "bool":
                lines.append(f"    #controlNodes.{cm.name}.status.signal := {sym};")
            else:
                lines.append(f"    #controlNodes.{cm.name}.status.value := {sym};")
    elif t == "LBC_AnalogOutput":
        if io.get("value") or io.get("tag"):
            lines.append(
                f"    {_sym(io.get('tag', ''), io.get('value', ''))} := #controlNodes.{cm.name}.commands.value;"
            )
    elif t == "LBC_AxisControl":
        if io.get("io") or io.get("tag"):
            addr = str(io.get("io", ""))
            tag = str(io.get("tag", ""))
            if addr.startswith("%Q") or "Q" in tag[:2].upper():
                lines.append(
                    _bool_write(tag, addr, f"#controlNodes.{cm.name}.commands.start")
                )
            else:
                lines.append(f"    #controlNodes.{cm.name}.status.running := {_sym(tag, addr)};")
    if len(lines) == 1:
        # 无 IO 绑定的 CM:诚实标注待接线,不编造地址
        lines.append(f"    // (待接线:CM {cm.name} 无物理 IO 绑定,自举直驱留空)")
    return "\n".join(lines)
