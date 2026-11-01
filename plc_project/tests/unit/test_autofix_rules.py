"""canvas autofix 规则库扩充回归测试（HR001 缺陷清单回流，治存量）。

覆盖 ``generate_canvas_autofix_patch`` 新增规则与向后兼容契约：

- R1  自实例 DB 绝对引用 → ``#`` 前缀补丁（FB 编号相同才改；
      不同编号的跨块引用绝不能改——FB1040 引用 DB1080 是合法访问）；
- R2-lite  常见数组成员名裸访问 → 仅 diagnostic 标注（不自动改、
      不产生 op、不触发 clear_errors）；
- R2-full  evidence_dir 提供 TIA Openness XML 证据时：确证数组自动补
      下标（含 1 起界数组补下界、双维、幂等、无证据不动）；
- R4  接口对账：body ``#X`` 未声明按 XML 补 add_variable（Struct 展开 /
      多实例 FB 引用），证据缺失仅 warning；
- 返回值 ``AutofixPatch`` 是 list 子类：fix_loop 的 ``list(result)`` /
      ``apply_canvas_patch(result)`` 等既有消费方式零改动。

R3（多实例调用形态 ``#SR.SR(R1:=..)`` 手写锁存、``.TON(`` 参数形态重建）
明确跳过——理由见 canvas_model.generate_canvas_autofix_patch 注释
（需被调 FB 接口/接线证据才能等价重写，无证据规则化会静默翻转语义）。
"""

from __future__ import annotations

import inspect

from plc_engine.canvas_model import (
    ARRAY_MEMBER_HINTS,
    AutofixPatch,
    CanvasBlock,
    CanvasHmiWidget,
    CanvasNetwork,
    CanvasState,
    CanvasVariable,
    apply_canvas_patch,
    generate_canvas_autofix_patch,
)


def _canvas_with_block(
    name: str,
    *,
    block_type: str = "FB",
    scl_body: str = "",
    networks: list[CanvasNetwork] | None = None,
    protected: bool = False,
) -> CanvasState:
    canvas = CanvasState(project_name="AutofixTest")
    canvas.blocks[name] = CanvasBlock(
        name=name,
        block_type=block_type,
        number=1,
        language="SCL",
        interface=[CanvasVariable(name="x", data_type="Bool", section="VAR")],
        networks=networks or [],
        scl_body=scl_body,
        protected=protected,
    )
    return canvas


# ---------------------------------------------------------------------------
# R1：自实例 DB 绝对引用 → # 前缀
# ---------------------------------------------------------------------------


def test_r1_self_instance_ref_patched_in_scl_body() -> None:
    """FB1080 体内 ``"DB1080_Component".x`` → ``#x``（成员链完整保留）。"""
    body = (
        'IF "DB1080_Component".Robot.Cmd.Auto.ProgStart THEN\n'
        '    "DB1080_Component".Done := TRUE;\n'
        "END_IF;\n"
    )
    canvas = _canvas_with_block("FB1080_CompFunc", scl_body=body)

    result = generate_canvas_autofix_patch(canvas, [])
    ops = [op for op in result if op.get("op") == "update_block_scl"]
    assert len(ops) == 1
    assert ops[0]["name"] == "FB1080_CompFunc"
    assert "#Robot.Cmd.Auto.ProgStart" in ops[0]["scl_body"]
    assert "#Done := TRUE" in ops[0]["scl_body"]
    assert '"DB1080_Component"' not in ops[0]["scl_body"]

    healed = apply_canvas_patch(canvas, list(result))
    assert '"DB1080_Component"' not in healed.blocks["FB1080_CompFunc"].scl_body
    assert "#Robot.Cmd.Auto.ProgStart" in healed.blocks["FB1080_CompFunc"].scl_body


def test_r1_cross_block_reference_never_touched() -> None:
    """误报防护：FB1040 引用 DB1080 是合法跨块引用，绝不能改。"""
    body = '"DB1080_Component".Robot.Cmd.Auto.ProgStart := TRUE;\n'
    canvas = _canvas_with_block("FB1040_HomePos", scl_body=body)

    result = generate_canvas_autofix_patch(canvas, [])
    assert list(result) == []
    assert hasattr(result, "diagnostics")
    # 原文一字不动
    assert canvas.blocks["FB1040_HomePos"].scl_body == body


def test_r1_number_must_match_exactly() -> None:
    """误报防护：DB 编号是 FB 编号前缀的更长数字（FB108 vs DB1080）不匹配。"""
    body = '"DB1080_Component".x := TRUE;\n'
    canvas = _canvas_with_block("FB108_Comp", scl_body=body)
    result = generate_canvas_autofix_patch(canvas, [])
    assert list(result) == []


def test_r1_network_scl_text_patched_via_update_network() -> None:
    """scl_body 为空、逻辑在网络 scl_text 时 → update_network op。"""
    canvas = _canvas_with_block(
        "FB1080_CompFunc",
        networks=[
            CanvasNetwork(
                id=3, title="net3", language="SCL", scl_text='"DB1080_Component".Start := TRUE;'
            )
        ],
    )
    result = generate_canvas_autofix_patch(canvas, [])
    ops = [op for op in result if op.get("op") == "update_network"]
    assert len(ops) == 1
    assert ops[0]["block"] == "FB1080_CompFunc" and ops[0]["network_id"] == 3
    assert ops[0]["scl_text"] == "#Start := TRUE;"

    healed = apply_canvas_patch(canvas, list(result))
    assert healed.blocks["FB1080_CompFunc"].networks[0].scl_text == "#Start := TRUE;"


def test_r1_protected_block_skipped() -> None:
    """know-how 加密块（protected）绝不能改写。"""
    body = '"DB1080_Component".x := TRUE;\n'
    canvas = _canvas_with_block("FB1080_CompFunc", scl_body=body, protected=True)
    result = generate_canvas_autofix_patch(canvas, [])
    assert list(result) == []
    assert canvas.blocks["FB1080_CompFunc"].scl_body == body


def test_r1_only_applies_to_fb_blocks() -> None:
    """FC/OB/DB 块即使名字带同编号引用也不适用本规则。"""
    body = '"DB9_X".x := TRUE;\n'
    for btype in ("FC", "OB", "DB"):
        canvas = _canvas_with_block("FB9_NotFB", block_type=btype, scl_body=body)
        result = generate_canvas_autofix_patch(canvas, [])
        assert list(result) == [], f"block_type={btype}"


def test_r1_idempotent_after_apply() -> None:
    """补丁幂等：应用后再跑一轮不再产 R1 op（修复循环收敛）。"""
    body = '"DB1080_Component".x := TRUE;\n'
    canvas = _canvas_with_block("FB1080_CompFunc", scl_body=body)
    first = generate_canvas_autofix_patch(canvas, [])
    assert any(op.get("op") == "update_block_scl" for op in first)
    healed = apply_canvas_patch(canvas, list(first))
    second = generate_canvas_autofix_patch(healed, [])
    assert not any(op.get("op") in {"update_block_scl", "update_network"} for op in second)


def test_r1_unnumbered_fb_name_is_inert() -> None:
    """块名无 FB<数字> 前缀 → 规则不适用，不崩溃。"""
    canvas = _canvas_with_block("MyLogic", scl_body='"DB1080_Component".x := TRUE;\n')
    result = generate_canvas_autofix_patch(canvas, [])
    assert list(result) == []


# ---------------------------------------------------------------------------
# R2-lite：疑似数组未下标 → 仅 diagnostic
# ---------------------------------------------------------------------------


def test_r2_lite_bare_member_access_diagnosed_not_patched() -> None:
    """裸 ``.Pulse`` 访问 → diagnostic 条目；绝不产生修改 op。"""
    body = (
        "#Step := #Aux.Index + 1;\n"  # 干扰行（Index 不在清单）
        "#p := #EdgeDetc.Pulse;\n"  # 命中：裸访问
        "#q := #Arr.Pulse[0];\n"  # 已下标：不命中
        "// 旧注释 .Pulse\n"  # 注释行：不命中
    )
    canvas = _canvas_with_block("FB5002_SafetyDoorV1", scl_body=body)

    result = generate_canvas_autofix_patch(canvas, [])
    assert isinstance(result, AutofixPatch) and isinstance(result, list)
    # 仅诊断 → 无任何修改 op（也就不该有 clear_errors）
    assert list(result) == []

    diags = result.diagnostics
    pulse_diags = [d for d in diags if d["member"] == "Pulse"]
    assert len(pulse_diags) == 1
    d = pulse_diags[0]
    assert d["rule"] == "R2_lite_array_unindexed"
    assert d["block"] == "FB5002_SafetyDoorV1"
    assert d["network"] is None  # scl_body 命中时无网络号
    assert d["line_no"] == 2
    assert "#EdgeDetc.Pulse" in d["evidence"]
    assert d["severity"] == "warning"
    assert "未自动修改" in d["message"]

    # 正文一字不动（诊断绝不修改块体）
    assert canvas.blocks["FB5002_SafetyDoorV1"].scl_body == body


def test_r2_lite_configured_member_list_and_prefix_no_false_positive() -> None:
    """清单成员逐一命中；相似名（PulseTime/Auto_Force2）不误报。"""
    assert "Pulse" in ARRAY_MEMBER_HINTS and "Para" in ARRAY_MEMBER_HINTS
    assert "Auto_Force" in ARRAY_MEMBER_HINTS
    body = (
        "#a := #S.Para;\n"
        "#b := #F.Auto_Force;\n"
        "#c := #S.PulseTime;\n"  # 前缀重叠：非清单成员
        "#d := #F.Auto_Force2;\n"  # 前缀重叠：非清单成员
    )
    canvas = _canvas_with_block("FB1_X", scl_body=body)
    diags = generate_canvas_autofix_patch(canvas, []).diagnostics
    members = {d["member"] for d in diags}
    assert members == {"Para", "Auto_Force"}
    assert {d["line_no"] for d in diags} == {1, 2}


def test_r2_lite_network_text_diagnosed_with_network_id() -> None:
    """网络 scl_text 命中时 diagnostic 带网络号。"""
    canvas = _canvas_with_block(
        "FB2_X",
        networks=[CanvasNetwork(id=7, title="net", language="SCL", scl_text="#p := #E.Pulse;")],
    )
    diags = generate_canvas_autofix_patch(canvas, []).diagnostics
    assert len(diags) == 1
    assert diags[0]["network"] == 7 and diags[0]["member"] == "Pulse"


# ---------------------------------------------------------------------------
# 向后兼容：既有 HMI add_variable 规则 + fix_loop 消费方式
# ---------------------------------------------------------------------------


def _hmi_canvas() -> CanvasState:
    canvas = CanvasState(project_name="Compat")
    canvas.blocks["DataDB"] = CanvasBlock(
        name="DataDB",
        block_type="DB",
        number=5,
        interface=[CanvasVariable(name="Existing", data_type="Bool", section="VAR")],
    )
    canvas.hmi_widgets["btn_heater"] = CanvasHmiWidget(
        id="btn_heater", widget_type="button", title="加热", plc_tag="DataDB.HeaterEnable"
    )
    return canvas


def test_existing_hmi_add_variable_rule_still_works() -> None:
    """既有规则回归：HMI 缺变量 → add_variable + clear_errors 收尾。"""
    canvas = _hmi_canvas()
    attributions = [
        {
            "target_type": "hmi_widget",
            "target_id": "btn_heater",
            "severity": "error",
            "message": "HMI 变量绑定错误：块 [DataDB] 中未声明变量 [HeaterEnable]",
        }
    ]
    result = generate_canvas_autofix_patch(canvas, attributions)

    assert any(
        op.get("op") == "add_variable" and op.get("variable", {}).get("name") == "HeaterEnable"
        for op in result
    )
    assert result[-1] == {"op": "clear_errors"}

    healed = apply_canvas_patch(canvas, list(result))
    assert any(v.name == "HeaterEnable" for v in healed.blocks["DataDB"].interface)


def test_result_backward_compatible_with_fix_loop_consumption() -> None:
    """fix_loop 消费契约：list(result) 可直接喂 apply_canvas_patch，
    diagnostics 不混入 ops 列表。"""
    canvas = _canvas_with_block("FB1080_C", scl_body='#p := #E.Pulse;\n"DB1080_C".x := TRUE;\n')
    result = generate_canvas_autofix_patch(canvas, [])

    ops = list(result)  # fix_loop.py:37 的消费方式
    assert all(isinstance(op, dict) and "op" in op for op in ops)
    assert any(op["op"] == "update_block_scl" for op in ops)
    assert ops[-1] == {"op": "clear_errors"}
    # diagnostics 只挂在属性上，不进入 ops（不会被 apply_canvas_patch 执行）
    assert not any(str(op.get("op", "")).startswith("diagnostic") for op in ops)
    assert len(result.diagnostics) == 1

    patched = apply_canvas_patch(deepcopy_canvas(canvas), ops)
    assert "#x := TRUE" in patched.blocks["FB1080_C"].scl_body


def deepcopy_canvas(canvas: CanvasState) -> CanvasState:
    """测试辅助：复制画布（模拟 fix_loop 的 deepcopy(current)）。"""
    from copy import deepcopy

    return deepcopy(canvas)


# ---------------------------------------------------------------------------
# XML 证据驱动：R2-full（数组补下标）/ R4（接口对账）
# ---------------------------------------------------------------------------

_INTERFACE_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"

#: 最小 SimaticML 证据 fixture（贴近 HR001 真机导出形态，离线可跑）
_EVIDENCE_FB_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V19" />
  <SW.Blocks.FB ID="0">
    <AttributeList>
      <Name>FB990_Test</Name>
      <Interface><Sections xmlns="{_INTERFACE_NS}">
  <Section Name="Input" />
  <Section Name="Output" />
  <Section Name="InOut" />
  <Section Name="Static">
    <Member Name="Aux" Datatype="Struct">
      <Member Name="HoleNo" Datatype="Int" />
      <Member Name="Heart" Datatype="IEC_TIMER" Version="1.0">
        <Sections>
          <Section Name="None">
            <Member Name="PT" Datatype="Time" />
            <Member Name="ET" Datatype="Time" />
            <Member Name="IN" Datatype="Bool" />
            <Member Name="Q" Datatype="Bool" />
          </Section>
        </Sections>
      </Member>
    </Member>
    <Member Name="EdgeDetc" Datatype="Struct">
      <Member Name="Pulse" Datatype="Array[0..15] of Bool" />
    </Member>
    <Member Name="Cfg" Datatype="Struct">
      <Member Name="Para" Datatype="Array[0..2, 1..5] of Int" />
    </Member>
    <Member Name="SafetyDoor" Datatype="&quot;FB5002_SafetyDoorV1&quot;">
      <Sections>
        <Section Name="Input">
          <Member Name="i_DoorOverRide" Datatype="Bool" />
        </Section>
      </Sections>
    </Member>
  </Section>
  <Section Name="Temp">
    <Member Name="StepPls" Datatype="Bool" />
  </Section>
</Sections></Interface>
    </AttributeList>
  </SW.Blocks.FB>
</Document>
"""

_EVIDENCE_DB_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V19" />
  <SW.Blocks.GlobalDB ID="0">
    <AttributeList>
      <Name>DB950_Comm</Name>
      <Interface><Sections xmlns="{_INTERFACE_NS}">
  <Section Name="Static">
    <Member Name="Para" Datatype="Struct">
      <Member Name="Auto_Force" Datatype="Array[1..200] of Real" />
      <Member Name="HorConcreteZ" Datatype="Real" />
    </Member>
  </Section>
</Sections></Interface>
    </AttributeList>
  </SW.Blocks.GlobalDB>
</Document>
"""


def _write_evidence_dir(tmp_path) -> str:
    """把 fixture XML 写成 ``<CPU>/blocks/*.xml`` 导出目录并返回路径。"""
    blocks_dir = tmp_path / "CPU_1200" / "blocks"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "a_FB990_Test.xml").write_text(_EVIDENCE_FB_XML, encoding="utf-8")
    (blocks_dir / "b_DB950_Comm.xml").write_text(_EVIDENCE_DB_XML, encoding="utf-8")
    return str(tmp_path)


def _canvas_with_iface(name: str, interface: list[CanvasVariable], **kwargs) -> CanvasState:
    canvas = CanvasState(project_name="EvidenceTest")
    canvas.blocks[name] = CanvasBlock(
        name=name, block_type="FB", number=1, interface=interface, **kwargs
    )
    return canvas


# --- R2-full：数组补下标 ---------------------------------------------------


def test_r2_full_bare_member_fixed_with_evidence(tmp_path) -> None:
    """证据确证 ``EdgeDetc.Pulse`` 实为 Array[0..15] → 自动补 [0]。

    画布接口带 ``Struct`` 空壳（损坏信号）→ R5 先整块重建，R2-full 在
    重建后的完整单元上补下标——同块两条 update op，apply 末条胜出，
    最终文本 = 重建单元 + 补下标 body。
    """
    body = "#p := #EdgeDetc.Pulse;\n"
    canvas = _canvas_with_iface(
        "FB990_Test",
        [CanvasVariable(name="Status", data_type="Struct", section="VAR")],
        scl_body=body,
    )
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))

    ops = [op for op in result if op.get("op") == "update_block_scl" and op["name"] == "FB990_Test"]
    assert ops, "必须产生 FB990_Test 的补丁"
    final_text = ops[-1]["scl_body"]  # 同块多条 op,apply 时末条胜出
    assert "#p := #EdgeDetc.Pulse[0];" in final_text
    assert result[-1] == {"op": "clear_errors"}

    fixed = [d for d in result.diagnostics if d["rule"] == "R2_array_evidence_fixed"]
    assert len(fixed) == 1
    d = fixed[0]
    assert d["block"] == "FB990_Test" and d["network"] is None
    assert d["member"] == "Pulse" and d["path"] == "EdgeDetc.Pulse"
    assert d["evidence"] == "Array[0..15] of Bool"
    assert d["subscript"] == "[0]"
    # R5 先整块重建后,行号是重建单元内的绝对行(body 在声明区之后),不再恒为 1
    assert isinstance(d["line_no"], int) and d["line_no"] >= 1

    healed = apply_canvas_patch(canvas, list(result))
    assert "#p := #EdgeDetc.Pulse[0];" in healed.blocks["FB990_Test"].scl_body


def test_r2_full_two_dim_and_one_based_db_array(tmp_path) -> None:
    """双维补 [0,1]；全局 DB 引用按 DB 证据修；1 起界数组补下界 [1]
    （机械补 [0] 会越界——DB1900.Para.Auto_Force 真机形态）。"""
    body = (
        "#g := #Cfg.Para;\n"
        'v := "DB950_Comm".Para.Auto_Force;\n'
        'z := "DB950_Comm".Para.HorConcreteZ;\n'
    )
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))

    healed_body = apply_canvas_patch(canvas, list(result)).blocks["FB990_Test"].scl_body
    assert healed_body.splitlines()[0] == "#g := #Cfg.Para[0,1];"
    assert healed_body.splitlines()[1] == 'v := "DB950_Comm".Para.Auto_Force[1];'
    # 非数组成员（HorConcreteZ : Real）不动
    assert healed_body.splitlines()[2] == 'z := "DB950_Comm".Para.HorConcreteZ;'

    fixed = {d["path"]: d for d in result.diagnostics if d["rule"] == "R2_array_evidence_fixed"}
    assert set(fixed) == {"Cfg.Para", "Para.Auto_Force"}
    assert fixed["Cfg.Para"]["evidence"] == "Array[0..2, 1..5] of Int"
    assert fixed["Cfg.Para"]["subscript"] == "[0,1]"
    assert fixed["Para.Auto_Force"]["subscript"] == "[1]"
    # Struct 中转段 .Para 本身未被确证为数组 → 保持 R2-lite 警告而非乱补
    lite = [d for d in result.diagnostics if d["rule"] == "R2_lite_array_unindexed"]
    assert all(d["member"] == "Para" for d in lite)


def test_r2_full_already_subscripted_and_idempotent(tmp_path) -> None:
    """已带 [ 的不重复处理；应用后再跑一轮不再产 R2 op（幂等收敛）。"""
    body = "#a := #EdgeDetc.Pulse[3];\n#b := #EdgeDetc.Pulse;\n"
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body)
    evidence_dir = _write_evidence_dir(tmp_path)

    first = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
    healed = apply_canvas_patch(canvas, list(first))
    assert healed.blocks["FB990_Test"].scl_body == (
        "#a := #EdgeDetc.Pulse[3];\n#b := #EdgeDetc.Pulse[0];\n"
    )
    # 第一轮只有一处待修（已下标那处负向前瞻直接跳过）
    assert len([d for d in first.diagnostics if d["rule"] == "R2_array_evidence_fixed"]) == 1


# --- R6：数组下标提升（翻译层拍平 `[idx]` → 尾段 `.idx` 的还原） ------------

_R6_DB_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V19" />
  <SW.Blocks.GlobalDB ID="0">
    <AttributeList>
      <Name>DB960_R6</Name>
      <Interface><Sections xmlns="{_INTERFACE_NS}">
  <Section Name="Static">
    <Member Name="AryTypePara" Datatype="Array[0..300] of &quot;UDT_TypePara&quot;" />
  </Section>
</Sections></Interface>
    </AttributeList>
  </SW.Blocks.GlobalDB>
</Document>
"""


def _write_r6_evidence_dir(tmp_path) -> str:
    blocks_dir = tmp_path / "plc" / "CPU_1200" / "blocks"
    blocks_dir.mkdir(parents=True)
    (blocks_dir / "db960.xml").write_text(_R6_DB_XML, encoding="utf-8")
    return str(tmp_path)


def test_r6_array_subscript_promotion(tmp_path) -> None:
    """`"DB960_R6".AryTypePara.Aux.WriteTypeParaDBL.Index`（拍平形态）
    → `"DB960_R6".AryTypePara[index].Aux.WriteTypeParaDBL`。

    三重证据门：首段为数组类型 ✓、尾段是本块整型变量 ✓、
    路径按成员解析必失败 ✓；正常可解析访问绝不动。
    """
    body = (
        "DSTBLK => \"DB960_R6\".AryTypePara.Aux.WriteTypeParaDBL.Index);\n"
        "\"DB960_R6\".AryTypePara := 0;\n"
    )
    canvas = _canvas_with_iface(
        "FB970_R6",
        [CanvasVariable(name="index", data_type="Int", section="VAR_TEMP")],
        scl_body=body,
    )
    evidence_dir = _write_r6_evidence_dir(tmp_path)

    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
    healed = apply_canvas_patch(canvas, list(result))
    text = healed.blocks["FB970_R6"].scl_body
    assert '"DB960_R6".AryTypePara[index].Aux.WriteTypeParaDBL' in text
    # 正常访问(整段数组赋值)不被改写
    assert '"DB960_R6".AryTypePara := 0;' in text
    r6 = [d for d in result.diagnostics if d["rule"] == "R6_array_subscript_promoted"]
    assert len(r6) == 1 and r6[0]["subscript"] == "[index]"

    # 幂等:修复后再跑无新增提升
    result2 = generate_canvas_autofix_patch(healed, [], evidence_dir=evidence_dir)
    assert not [d for d in result2.diagnostics if d["rule"] == "R6_array_subscript_promoted"]

    second = generate_canvas_autofix_patch(healed, [], evidence_dir=evidence_dir)
    assert not any(op.get("op") in {"update_block_scl", "update_network"} for op in second)
    assert not any(d["rule"] == "R2_array_evidence_fixed" for d in second.diagnostics)


def test_r2_full_without_evidence_stays_lite(tmp_path) -> None:
    """证据查不到（成员不在 XML / 块不在 XML）→ 保持 R2-lite 仅诊断。"""
    body = "#p := #Ghost.Pulse;\n"  # 块在 XML 但 Ghost 不在
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body)
    evidence_dir = _write_evidence_dir(tmp_path)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)

    assert list(result) == []  # 无任何修改 op（clear_errors 也不该有）
    lite = [d for d in result.diagnostics if d["rule"] == "R2_lite_array_unindexed"]
    assert len(lite) == 1 and lite[0]["member"] == "Pulse"
    assert lite[0]["severity"] == "warning" and "未自动修改" in lite[0]["message"]
    assert canvas.blocks["FB990_Test"].scl_body == body

    # 块完全不在 XML（无块级证据上下文）→ 同样仅诊断
    canvas2 = _canvas_with_iface("FB777_NoEvidence", [], scl_body="#q := #E.Pulse;\n")
    result2 = generate_canvas_autofix_patch(canvas2, [], evidence_dir=evidence_dir)
    assert list(result2) == []
    assert [d["rule"] for d in result2.diagnostics] == ["R2_lite_array_unindexed"]


def test_r2_full_network_text_patched_via_update_network(tmp_path) -> None:
    """scl_body 为空、逻辑在网络 scl_text → update_network op + 诊断带网络号。"""
    canvas = _canvas_with_iface(
        "FB990_Test",
        [],
        networks=[
            CanvasNetwork(id=9, title="net", language="SCL", scl_text="#p := #EdgeDetc.Pulse;")
        ],
    )
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))
    ops = [op for op in result if op.get("op") == "update_network"]
    assert len(ops) == 1
    assert ops[0]["block"] == "FB990_Test" and ops[0]["network_id"] == 9
    assert ops[0]["scl_text"] == "#p := #EdgeDetc.Pulse[0];"

    fixed = [d for d in result.diagnostics if d["rule"] == "R2_array_evidence_fixed"]
    assert len(fixed) == 1 and fixed[0]["network"] == 9


def test_evidence_dir_defaults_to_none_for_fix_loop_compat() -> None:
    """fix_loop 零改动兼容：evidence_dir 是默认 None 的可选参数。"""
    sig = inspect.signature(generate_canvas_autofix_patch)
    assert sig.parameters["evidence_dir"].default is None
    # 位置传参与旧签名完全兼容（canvas, attributions）
    canvas = _canvas_with_block("FB1_X", scl_body="#a := #S.Para;\n")
    result = generate_canvas_autofix_patch(canvas, [])
    assert list(result) == []
    assert [d["rule"] for d in result.diagnostics] == ["R2_lite_array_unindexed"]


# --- R4：接口对账 -----------------------------------------------------------


def test_r4_missing_struct_with_timer_member_declared(tmp_path) -> None:
    """body 引用 ``#Aux.Heart.TON(...)`` 未声明 → 按证据补
    ``Aux : Struct … End_Struct``（含 IEC_TIMER 成员，内联展开）。"""
    body = "#Aux.Heart.TON(IN := TRUE, PT := T#1S);\n"
    canvas = _canvas_with_iface(
        "FB990_Test",
        [CanvasVariable(name="Status", data_type="Struct", section="VAR")],
        scl_body=body,
    )
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))

    adds = [
        op for op in result if op.get("op") == "add_variable" and op["variable"]["name"] == "Aux"
    ]
    assert len(adds) == 1
    var = adds[0]["variable"]
    assert var["section"] == "VAR_STAT"
    assert var["data_type"].startswith("Struct\n")
    assert "    HoleNo : Int;" in var["data_type"]
    assert "    Heart : IEC_TIMER;" in var["data_type"]
    assert var["data_type"].endswith("End_Struct")
    # 声明串渲染进外部源后恰闭合为合法句法（{name} : {type}; → End_Struct;）
    assert f"Aux : {var['data_type']};".endswith("End_Struct;")

    healed = apply_canvas_patch(canvas, list(result))
    aux = next(v for v in healed.blocks["FB990_Test"].interface if v.name == "Aux")
    assert "Heart : IEC_TIMER;" in aux.data_type
    # 诊断记录（info 级，证据串为 XML 原始类型）
    added = [d for d in result.diagnostics if d["rule"] == "R4_interface_member_added"]
    assert len(added) == 1
    assert added[0]["member"] == "Aux" and added[0]["evidence"] == "Struct"
    assert added[0]["severity"] == "info"


def test_r4_multiinstance_fb_reference_declared_as_quoted_type(tmp_path) -> None:
    """多实例 FB 引用按 XML 原样补 ``"FB5002_SafetyDoorV1"``（不展开成员）。"""
    body = "#SafetyDoor.i_DoorOverRide := TRUE;\n"
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))

    adds = [op for op in result if op.get("op") == "add_variable"]
    assert len(adds) == 1
    assert adds[0]["variable"]["name"] == "SafetyDoor"
    assert adds[0]["variable"]["data_type"] == '"FB5002_SafetyDoorV1"'
    assert adds[0]["variable"]["section"] == "VAR_STAT"


def test_r4_member_without_evidence_only_warns(tmp_path) -> None:
    """证据也没有的成员：只出 warning 诊断，绝盲补。"""
    body = "#Ghost.Member := TRUE;\n"
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))

    assert not any(op.get("op") == "add_variable" for op in result)
    warns = [d for d in result.diagnostics if d["rule"] == "R4_interface_member_no_evidence"]
    assert len(warns) == 1
    assert warns[0]["member"] == "Ghost" and warns[0]["severity"] == "warning"
    assert "接口缺失且无证据" in warns[0]["message"]


def test_r4_declared_members_untouched_and_idempotent(tmp_path) -> None:
    """已声明（含大小写漂移）不重复补；应用后再跑不重复添加（幂等）。"""
    body = "#Aux.HoleNo := 1;\n"
    canvas = _canvas_with_iface(
        "FB990_Test",
        [CanvasVariable(name="aux", data_type="Struct", section="VAR")],
        scl_body=body,
    )
    evidence_dir = _write_evidence_dir(tmp_path)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
    assert not any(op.get("op") == "add_variable" for op in result)

    # 空接口场景：一轮补齐后二轮不再补
    canvas2 = _canvas_with_iface("FB990_Test", [], scl_body=body)
    first = generate_canvas_autofix_patch(canvas2, [], evidence_dir=evidence_dir)
    assert sum(1 for op in first if op.get("op") == "add_variable") == 1
    healed = apply_canvas_patch(canvas2, list(first))
    second = generate_canvas_autofix_patch(healed, [], evidence_dir=evidence_dir)
    assert not any(op.get("op") == "add_variable" for op in second)


def test_r4_only_fb_fc_body_and_skips_protected(tmp_path) -> None:
    """防误伤：只对 FB/FC 的 body；protected 块、无块级证据块、全局 DB
    引用一律不管。"""
    evidence_dir = _write_evidence_dir(tmp_path)
    body = "#Ghost.x := TRUE;\n"

    # 非 FB/FC（OB/DB）不适用
    for btype in ("OB", "DB", "UDT"):
        canvas = CanvasState(project_name="T")
        canvas.blocks["FB990_Test"] = CanvasBlock(
            name="FB990_Test", block_type=btype, scl_body=body
        )
        result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
        assert not any(op.get("op") == "add_variable" for op in result), btype
        assert not any(d["rule"].startswith("R4") for d in result.diagnostics), btype

    # protected 块跳过
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body, protected=True)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
    assert not any(op.get("op") == "add_variable" for op in result)
    assert not any(d["rule"].startswith("R4") for d in result.diagnostics)

    # 块不在 XML 证据里 → 整块跳过（不制造逐符号告警噪音）
    canvas = _canvas_with_iface("FB777_NoEvidence", [], scl_body="#A.B := TRUE;\n")
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
    assert list(result) == [] and result.diagnostics == [
        d for d in result.diagnostics if not d["rule"].startswith("R4")
    ]

    # 全局 DB 引用（"DB950_Comm".Para）不补进本块接口
    canvas = _canvas_with_iface(
        "FB990_Test", [], scl_body='"DB950_Comm".Para.HorConcreteZ := 1.0;\n'
    )
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=evidence_dir)
    assert not any(op.get("op") == "add_variable" for op in result)


def test_r4_network_text_roots_and_comment_lines(tmp_path) -> None:
    """网络 scl_text 中的 #X 同样对账；注释行引用忽略。"""
    canvas = _canvas_with_iface(
        "FB990_Test",
        [],
        networks=[
            CanvasNetwork(
                id=1, language="SCL", scl_text="#Aux.HoleNo := 1;\n// #Ghost.comment := 1;"
            ),
        ],
    )
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))
    adds = [op for op in result if op.get("op") == "add_variable"]
    assert [op["variable"]["name"] for op in adds] == ["Aux"]
    assert not any(d["member"] == "Ghost" for d in result.diagnostics)


def test_r2_full_and_r4_compose_with_r1_on_same_text(tmp_path) -> None:
    """R1 改写暴露出的引用，R2-full/R4 必须基于改写后的文本计算，
    三条规则同块协作不互相覆盖（历史丢补丁根因）。"""
    body = (
        '"DB990_Test".EdgeDetc.Pulse := TRUE;\n'  # R1 → #EdgeDetc.Pulse → R2 补 [0]
        '"DB990_Test".Aux.HoleNo := 2;\n'  # R1 → #Aux.HoleNo   → R4 补 Aux
    )
    canvas = _canvas_with_iface("FB990_Test", [], scl_body=body)
    result = generate_canvas_autofix_patch(canvas, [], evidence_dir=_write_evidence_dir(tmp_path))

    healed = apply_canvas_patch(canvas, list(result))
    lines = healed.blocks["FB990_Test"].scl_body.splitlines()
    assert lines[0] == "#EdgeDetc.Pulse[0] := TRUE;"
    assert lines[1] == "#Aux.HoleNo := 2;"
    added = {op["variable"]["name"] for op in result if op.get("op") == "add_variable"}
    assert {"EdgeDetc", "Aux"} <= added
