"""AF 重构引擎加固(refactor hardening)单元测试。

覆盖五项诚实性约束:
1. 自举模式(self_contained=True)产物不引用任何官方库类型
   (LUC_/LAF_/LBC_/LPMLV2022_),并诚实标注"自举简化实现,非官方库等价认证";
2. 识别不出任何步序块时**完全降级**——不生成假 Station1 EM,
   旧块保持原样标 af_pending_manual,报告 degraded/degrade_reasons/pending_blocks;
3. 部分块无法映射时这些块进 pending 而非 superseded,可映射块照常迁移;
4. io_retention 拆分 retained_direct / retained_fallback,兜底 CM 标记 fallback;
5. pending 块保持原始形态(af_role 标注不破坏 SCL/接口)。
"""

from __future__ import annotations

import re

from plc_engine.af import LegacyToAfMapper, refactor_canvas_to_af
from plc_engine.canvas_model import (
    CanvasBlock,
    CanvasState,
    CanvasTag,
    CanvasVariable,
)

#: 官方库类型前缀——自举模式产物中一个都不许出现(含注释)
FORBIDDEN_LIBRARY_TOKEN_RE = re.compile(r"(?:LUC_|LAF_|LBC_|LPMLV2022_)\w*")

PENDING_ROLE = "af_pending_manual"


def _hr001_style_canvas() -> CanvasState:
    """HR001 风格 mock 画布(气缸 + 光电 + 急停 + AutoStep 步进机)。"""
    canvas = CanvasState(project_name="HR001_PLC")
    canvas.tags = {
        "I_Cyl_WorkPos": CanvasTag("I_Cyl_WorkPos", "Bool", "%I0.0", "", "cylinder work position sensor (extend到位)"),
        "I_Cyl_HomePos": CanvasTag("I_Cyl_HomePos", "Bool", "%I0.1", "", "cylinder home position sensor (retract原点)"),
        "I_Sensor_PartPresent": CanvasTag("I_Sensor_PartPresent", "Bool", "%I0.2", "", "Optical sensor (有料光电)"),
        "I_EmergencyStop": CanvasTag("I_EmergencyStop", "Bool", "%I0.3", "", "Emergency stop (急停常闭)"),
        "Q_Cyl_Extend": CanvasTag("Q_Cyl_Extend", "Bool", "%Q0.0", "", "cylinder solenoid extend (伸出电磁阀)"),
        "Q_Cyl_Retract": CanvasTag("Q_Cyl_Retract", "Bool", "%Q0.1", "", "cylinder solenoid retract (缩回电磁阀)"),
    }
    canvas.blocks["FB1000_MainControl"] = CanvasBlock(
        name="FB1000_MainControl",
        block_type="FB",
        number=1000,
        interface=[
            CanvasVariable(name="AutoMode", data_type="Bool", section="VAR_INPUT"),
            CanvasVariable(name="EmergencyStop", data_type="Bool", section="VAR_INPUT"),
        ],
        scl_body="IF #EmergencyStop THEN\n    #AutoMode := FALSE;\nEND_IF;",
        status="synced",
    )
    canvas.blocks["FB1060_AutoStep"] = CanvasBlock(
        name="FB1060_AutoStep",
        block_type="FB",
        number=1060,
        interface=[CanvasVariable(name="iStep", data_type="DInt", section="VAR")],
        scl_body="""CASE #iStep OF
    10: // WAIT_FOR_PART
        IF "I_Sensor_PartPresent" THEN
            #iStep := 20;
        END_IF;
    20: // CYL_EXTEND
        "Q_Cyl_Extend" := TRUE;
        IF "I_Cyl_WorkPos" THEN
            #iStep := 30;
        END_IF;
    30: // CYL_RETRACT
        "Q_Cyl_Retract" := TRUE;
        IF "I_Cyl_HomePos" THEN
            #iStep := 1;
        END_IF;
END_CASE;
""",
        status="synced",
    )
    return canvas


# ---------------------------------------------------------------- 自举模式 --


def test_self_contained_mode_no_library_tokens():
    """自举模式:全部生成块零官方库类型引用,且带诚实简化标注。"""
    canvas = _hr001_style_canvas()
    new_canvas, report = refactor_canvas_to_af(
        canvas, target_unit_name="U1_HR001", self_contained=True
    )

    assert report["generator_mode"] == "self_contained"
    assert report["degraded"] is False

    generated = {k: b for k, b in new_canvas.blocks.items() if "::" in k}
    assert generated, "自举模式必须生成 AF 块"

    offenders: dict[str, str] = {}
    for key, block in generated.items():
        for m in FORBIDDEN_LIBRARY_TOKEN_RE.finditer(block.scl_body or ""):
            offenders.setdefault(key, m.group(0))
    assert not offenders, f"自举模式产物出现官方库类型引用: {offenders}"

    # 核心块带诚实简化标注(自举实现 ≠ 官方库等价认证)
    seq = new_canvas.blocks["U1Em1_AutoStep::Sequence"].scl_body
    assert "自举简化实现,非官方库等价认证" in seq
    assert "CASE #statStepCurrent OF" in seq  # CASE 步进机直接读写 ControlNodes
    assert '"U1Em1_AutoStep_ControlNodes".sequence.status.stepCurrent' in seq

    call_eq = new_canvas.blocks["U1Em1_AutoStep::CallEquipment"].scl_body
    assert "自举简化实现,非官方库等价认证" in call_eq
    # CallEquipment 直接驱动 CM 命令字段 -> 物理 %Q 符号
    assert '"Q_Cyl_Extend" := "U1Em1_AutoStep_ControlNodes".cyl.commands.workPosition;' in call_eq
    # 物理输入 -> 状态回读
    assert '"U1Em1_AutoStep_ControlNodes".cyl.status.inWorkPosition := "I_Cyl_WorkPos";' in call_eq

    call_unit = new_canvas.blocks["U1_HR001::CallUnit"].scl_body
    assert "自举简化实现,非官方库等价认证" in call_unit
    assert '"U1_HR001_EmNodes".unitStatus.mode.manual' in call_unit  # 手/自动枚举

    # 自举产物同样必须过 AF 静态架构 linter(0 error)
    errors = [
        f for f in report["lint_findings"] if f["severity"] == "error"
    ]
    assert errors == []


def test_library_mode_default_and_backward_compatible_signature():
    """默认 library 模式不变:签名 (canvas, target) 位置调用仍可用。"""
    canvas = _hr001_style_canvas()
    new_canvas, report = refactor_canvas_to_af(canvas, "U1_HR001")

    assert report["generator_mode"] == "library"
    assert report["status"] == "success"
    # library 模式仍实例化官方库类型(A4 场景由此模式自身承担)
    assert '"LAF_ControlSclSequence"' in new_canvas.blocks["U1Em1_AutoStep::Sequence"].scl_body
    # 旧行为:HR001 mock 全部块可映射 → 全部 superseded
    assert report["pending_blocks"] == []
    assert new_canvas.blocks["FB1060_AutoStep"].af_role == "legacy_superseded"


# ---------------------------------------------------------------- 完全降级 --


def test_degraded_no_fake_em_when_no_sequence_block():
    """无任何步序块:不再生成假 Station1,完全降级 + 全部块 pending。"""
    canvas = CanvasState(project_name="NoSequence")
    canvas.tags = {
        "Q_Lamp": CanvasTag("Q_Lamp", "Bool", "%Q0.5", "", "indicator lamp 指示灯"),
    }
    canvas.blocks["FB900_Blink"] = CanvasBlock(
        name="FB900_Blink",
        block_type="FB",
        number=900,
        interface=[CanvasVariable(name="cnt", data_type="Int", section="VAR")],
        scl_body="#cnt := #cnt + 1;\nIF #cnt > 10 THEN #cnt := 0; END_IF;",
        status="synced",
    )

    new_canvas, report = refactor_canvas_to_af(canvas, target_unit_name="U1_NoSeq")

    # 完全降级:状态、原因、待人工块三件套
    assert report["status"] == "degraded"
    assert report["degraded"] is True
    assert "no_sequence_block" in report["degrade_reasons"]
    assert report["pending_blocks"] == ["FB900_Blink"]

    # 不生成任何 AF 块,更没有假 Station1
    assert report["af_blocks_created"] == []
    assert report["ems"] == []
    assert not any("Station1" in key for key in new_canvas.blocks)
    assert not any("::" in key for key in new_canvas.blocks)

    # 旧块保持原样:仅标 af_role,scl_body/接口一字不动
    blk = new_canvas.blocks["FB900_Blink"]
    assert blk.af_role == PENDING_ROLE
    assert blk.scl_body == canvas.blocks["FB900_Blink"].scl_body
    assert [v.__dict__ for v in blk.interface] == [
        v.__dict__ for v in canvas.blocks["FB900_Blink"].interface
    ]

    # 未迁移就不做保留记账(恒 100% 是假验证)
    assert report["io_retention"]["retained_ios"] == 0
    assert report["io_retention"]["retained_direct"] == 0
    assert report["io_retention"]["retained_fallback"] == 0
    assert report["io_retention"]["percentage"] == 0.0


def test_degraded_mapper_analysis_flags():
    """映射器层面:无步序块 → ems 为空 + degraded 标记。"""
    canvas = CanvasState(project_name="EmptySeq")
    canvas.blocks["FB901_Mixer"] = CanvasBlock(
        name="FB901_Mixer",
        block_type="FB",
        number=901,
        scl_body='"Q_Motor" := TRUE;',
        status="synced",
    )
    analysis = LegacyToAfMapper(canvas, target_unit_name="U1_E").analyze()
    assert analysis.units[0].ems == []
    assert analysis.degraded is True
    assert "no_sequence_block" in analysis.degrade_reasons


# ---------------------------------------------------------------- 部分待定 --


def test_partial_unmappable_blocks_go_pending():
    """部分块无法映射:pending 保留原样,可映射块照常迁移。"""
    canvas = _hr001_style_canvas()
    mystery_scl = "#a := #b + 1;\n#c := #a * 2;"
    canvas.blocks["FB999_Mystery"] = CanvasBlock(
        name="FB999_Mystery",
        block_type="FB",
        number=999,
        interface=[CanvasVariable(name="a", data_type="Int", section="VAR")],
        scl_body=mystery_scl,
        status="synced",
    )

    new_canvas, report = refactor_canvas_to_af(canvas, target_unit_name="U1_HR001")

    assert report["degraded"] is False  # 有步序块,仅部分块 pending
    assert report["status"] == "success"
    assert "unmapped_blocks_pending" in report["degrade_reasons"]
    assert report["pending_blocks"] == ["FB999_Mystery"]

    # 无法映射块:af_pending_manual 且 SCL 保持原样
    mystery = new_canvas.blocks["FB999_Mystery"]
    assert mystery.af_role == PENDING_ROLE
    assert mystery.scl_body == mystery_scl

    # 可映射块照常迁移(superseded)
    assert new_canvas.blocks["FB1060_AutoStep"].af_role == "legacy_superseded"
    assert new_canvas.blocks["FB1000_MainControl"].af_role == "legacy_superseded"

    # AF 块正常生成
    assert "U1Em1_AutoStep::Sequence" in new_canvas.blocks
    errors = [f for f in report["lint_findings"] if f["severity"] == "error"]
    assert errors == []


# ------------------------------------------------------------ fallback 记账 --


def test_io_retention_fallback_split():
    """io_retention 拆分 direct/fallback:兜底 CM 收编的 IO 逐项可辨。"""
    canvas = _hr001_style_canvas()
    _, report = refactor_canvas_to_af(canvas, target_unit_name="U1_HR001")

    io = report["io_retention"]
    # 4 个气缸 IO 精确映射到双作用执行器;光电 + 急停由数字信号兜底收编
    assert io["retained_direct"] == 4
    assert io["retained_fallback"] == 2
    assert io["retained_ios"] == io["retained_direct"] + io["retained_fallback"] == 6
    assert io["percentage"] == 100.0  # 兼容字段保留

    fallback_details = [d for d in io["details"] if d["fallback"]]
    assert len(fallback_details) == 2
    assert {d["address"] for d in fallback_details} == {"%I0.2", "%I0.3"}
    assert all(d["cm_type"] == "LBC_DigitalSignal" for d in fallback_details)
    # details 每项都带 fallback 布尔标记
    assert all("fallback" in d for d in io["details"])

    # ems 摘要里的 CM 也带 fallback 标记
    cms = {cm["name"]: cm for cm in report["ems"][0]["cms"]}
    assert cms["cyl"]["fallback"] is False
    assert any(c["fallback"] for c in cms.values())


# ------------------------------------------------------------ 联锁诚实化 --


def test_no_placeholder_interlock_injection():
    """联锁一个都没扫到:不注入 GlobalEmergencyStop,记 degrade_reasons。"""
    canvas = CanvasState(project_name="NoSafety")
    canvas.tags = {
        "I_Start": CanvasTag("I_Start", "Bool", "%I0.0", "", "start button 启动按钮"),
        "Q_Run": CanvasTag("Q_Run", "Bool", "%Q0.0", "", "run output 运行输出"),
    }
    canvas.blocks["FB10_Sequence"] = CanvasBlock(
        name="FB10_Sequence",
        block_type="FB",
        number=10,
        interface=[CanvasVariable(name="iStep", data_type="DInt", section="VAR")],
        scl_body="""CASE #iStep OF
    10: // IDLE
        IF "I_Start" THEN #iStep := 20; END_IF;
    20: // RUN
        "Q_Run" := TRUE;
END_CASE;
""",
        status="synced",
    )

    _, report = refactor_canvas_to_af(canvas, target_unit_name="U1_NoSafety")

    assert report["interlocks"] == []
    assert not any("EmergencyStop" in ic["name"] for ic in report["interlocks"])
    assert "no_interlock_detected" in report["degrade_reasons"]
    # 有步序块 → 不因缺联锁而完全降级
    assert report["degraded"] is False
