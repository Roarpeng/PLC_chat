"""any2scl 语义等价 golden 回归基线（LAD→SCL，逐网络）。

背景：``docs/16-lad2scl-offline-validation.md``（2026-10-23）对真实 HR001 导出
人工等价性抽样仅 2/9 完全等价，归纳出 5 类系统性缺陷 S1~S5；修复波（§7）后
9/9 完全等价。``tests/unit/test_equivalence.py`` 验的是 AF 重构前后 IO 计数，
不覆盖 LAD→SCL 语义等价——本文件补上这个缺口。

口径（严格遵守）：
- 每条用例写明「输入（真实 FlgNet/SimaticML 片段）→ 期望 SCL 语句/布尔表达式」，
  期望值**逐字来自** docs/16 §7.2 修复后复核结论与既有 fix 测试的精确断言
  （test_tia_fold_fixes.py / test_tia_translate_fixes.py / test_tia_parse_fixes.py），
  不是凭空编造，也**不因为实现输出而放宽期望值**。
- 归一化比较：去空白 + 去无害注释后比较关键 token/整句；坏标记（TODO /
  loop guard）保留注释文本单独检测，避免被"无害注释"规则抹掉。
- 五类 S1~S5 每类至少 1 正例（真实网络语义等价）+ 1 反例（修复前坏输出
  负向对照 + fail-closed 门禁拦截）。反例坏样本逐字/按 docs 描述复现，
  并注明出处。
- 片段优先取自真实 HR001 导出（逐字节摘录或裁减到被测子电路，UId / 引脚名 /
  大小写保持导出原样），注释写明来源文件与 Network 编号；缺失环境的真实数据
  smoke 用 skipif 跳过，不影响自包含主体用例。
- 「仍未等价」项如实标 ``xfail(strict=False)``，并在基线 JSON 里说明原因。

真实片段来源（``PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/``，只读）：
- 005_Component_Cooling Fan_FB2009_CoolingFanFunction.xml  网络 1（FB2009_NET1）
- 001_KL_Standard_FB_FB5002_SafetyDoorV1.xml                 网络 1（FB5002_NET1_SELFHOLD）
- 004_AutoStep_FB1060_AutoStep.xml                            网络 1（FB1060_TON_Q_GATE / FB1060_EQ93_PRE）
- 006_ Visual Chiseling_FC2300 Time Calculation.xml          网络 5（FC2300_NET5）
- 003_HomeStep_FB1040_HomePos.xml                            网络 7（S3 TypedConstant 摘录）
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from agents.plc.tia.coverage import (
    SCL_DEFECT_PATTERNS,
    SclWritebackUnsafeError,
    assert_scl_safe_for_writeback,
    scan_scl_defects,
)
from agents.plc.tia.flgnet_fold import fold_network, stmt_to_scl
from agents.plc.tia.ir import AccessScope, PlcProject
from agents.plc.tia.scl import NetworkTranslator
from agents.plc.tia.simaticml import parse_access, parse_block_xml

# ---------------------------------------------------------------------------
# 解析 / 折叠 / 翻译 helpers（与既有 fix 测试同构：最小 LAD FB 文档包 FlgNet）
# ---------------------------------------------------------------------------

_FLGNET_OPEN = '<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">'
_FLGNET_CLOSE = "</FlgNet>"


def _parse_fragment(flgnet: str):
    """Parse one real FlgNet fragment embedded in a minimal LAD FB document."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.FB ID="0">
    <AttributeList><Name>FB_Golden</Name><Number>9999</Number>
      <ProgrammingLanguage>LAD</ProgrammingLanguage>
    </AttributeList>
    <ObjectList>
      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">
        <AttributeList>
          <NetworkSource>{flgnet}</NetworkSource>
          <ProgrammingLanguage>LAD</ProgrammingLanguage>
        </AttributeList>
      </SW.Blocks.CompileUnit>
    </ObjectList>
  </SW.Blocks.FB>
</Document>
"""
    with TemporaryDirectory() as td:
        path = Path(td) / "FB_Golden.xml"
        path.write_text(xml, encoding="utf-8")
        block = parse_block_xml(path)
    assert block is not None
    assert len(block.networks) == 1
    return block


def _fold_lines(flgnet: str) -> list[str]:
    """折叠层出口：fold_network → stmt_to_scl（与 test_tia_fold_fixes 同构）。"""
    return [stmt_to_scl(s) for s in fold_network(_parse_fragment(flgnet).networks[0]).statements]


def _translate_lines(flgnet: str) -> list[str]:
    """翻译层出口：挂载 folded 后走 NetworkTranslator.translate（镜像管线 S1 消费路径）。"""
    block = _parse_fragment(flgnet)
    network = block.networks[0]
    network.folded = fold_network(network)
    return NetworkTranslator(block, network).translate()


def _access(uid: int, *comps: str, scope: str = "LocalVariable") -> str:
    body = "".join(f'<Component Name="{c}" />' for c in comps)
    return f'<Access Scope="{scope}" UId="{uid}"><Symbol>{body}</Symbol></Access>'


def _part(name: str, uid: int, *, negated: bool = False, inner: str = "") -> str:
    neg = '<Negated Name="operand" />' if negated else ""
    return f'<Part Name="{name}" UId="{uid}">{neg}{inner}</Part>'


def _wire(uid: int, *ends: str) -> str:
    return f'<Wire UId="{uid}">' + "".join(ends) + "</Wire>"


def _powerrail() -> str:
    return "<Powerrail />"


def _ident(uid: int) -> str:
    return f'<IdentCon UId="{uid}" />'


def _nc(uid: int, pin: str) -> str:
    return f'<NameCon UId="{uid}" Name="{pin}" />'


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

_BLOCK_COMMENT_RE = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """去空白 + 去无害注释，用于比较关键 token / 表达式 / 整句。"""
    cleaned = _BLOCK_COMMENT_RE.sub("", text or "")
    cleaned = _LINE_COMMENT_RE.sub("", cleaned)
    return _WS_RE.sub("", cleaned)


def _compact(text: str) -> str:
    """仅去空白，保留注释文本——用于检测藏在 (* ... *) 里的坏标记。"""
    return _WS_RE.sub("", text or "")


# ---------------------------------------------------------------------------
# 真实 HR001 FlgNet 片段（逐字节摘录 / 裁减到被测子电路）
# ---------------------------------------------------------------------------

# 来源：005_Component_Cooling Fan_FB2009_CoolingFanFunction.xml 网络 1
# SR 自锁 + 互锁 + CoilTON×2；TypedConstant PT=T#2s；小写 s/r1/q 引脚；
# <Negated Name="operand"/> 取反触点。docs/16 §3.1/§3.2 / §7.2 判定点 ⑤。
FB2009_NET1 = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "Auto_Mode")}
    {_access(22, "I_StationToolOn_1")}
    {_access(23, "I_StationToolOn_2")}
    {_access(24, "Timer_StationToolOn")}
    <Access Scope="TypedConstant" UId="25"><Constant><ConstantValue>T#2s</ConstantValue></Constant></Access>
    {_access(26, "I_StationToolOn_1")}
    {_access(27, "I_StationToolOn_2")}
    {_access(28, "Timer_StationCoolingFan", "Q")}
    {_access(29, "Man_Mode")}
    {_access(30, "Emm_Mode")}
    {_access(31, "SR_StationTool")}
    {_access(32, "ToolAtPos")}
    {_access(33, "Timer_StationCoolingFan")}
    {_access(34, "CoolingTime")}
    {_part("Contact", 35)}
    {_part("Contact", 36)}
    {_part("Contact", 37)}
    {_part("CoilTON", 38, inner='<TemplateValue Name="time_type" Type="Type">Time</TemplateValue>')}
    {_part("Contact", 39, negated=True)}
    {_part("Contact", 40, negated=True)}
    {_part("Contact", 41)}
    {_part("Contact", 42)}
    {_part("Contact", 43)}
    {_part("O", 44, inner='<TemplateValue Name="Card" Type="Cardinality">5</TemplateValue>')}
    {_part("Sr", 45)}
    {_part("Coil", 46)}
    {_part("CoilTON", 47, inner='<TemplateValue Name="time_type" Type="Type">Time</TemplateValue>')}
  </Parts>
  <Wires>
    {_wire(48, _powerrail(), _nc(35, "in"), _nc(39, "in"), _nc(40, "in"), _nc(41, "in"), _nc(42, "in"), _nc(43, "in"))}
    {_wire(49, _ident(21), _nc(35, "operand"))}
    {_wire(50, _nc(35, "out"), _nc(36, "in"))}
    {_wire(51, _ident(22), _nc(36, "operand"))}
    {_wire(52, _nc(36, "out"), _nc(37, "in"))}
    {_wire(53, _ident(23), _nc(37, "operand"))}
    {_wire(54, _nc(37, "out"), _nc(38, "in"))}
    {_wire(55, _ident(25), _nc(38, "value"))}
    {_wire(56, _ident(24), _nc(38, "operand"))}
    {_wire(57, _nc(38, "out"), _nc(45, "s"))}
    {_wire(58, _ident(26), _nc(39, "operand"))}
    {_wire(59, _nc(39, "out"), _nc(44, "in1"))}
    {_wire(60, _ident(27), _nc(40, "operand"))}
    {_wire(61, _nc(40, "out"), _nc(44, "in2"))}
    {_wire(62, _ident(28), _nc(41, "operand"))}
    {_wire(63, _nc(41, "out"), _nc(44, "in3"))}
    {_wire(64, _ident(29), _nc(42, "operand"))}
    {_wire(65, _nc(42, "out"), _nc(44, "in4"))}
    {_wire(66, _ident(30), _nc(43, "operand"))}
    {_wire(67, _nc(43, "out"), _nc(44, "in5"))}
    {_wire(68, _nc(44, "out"), _nc(45, "r1"))}
    {_wire(69, _ident(31), _nc(45, "operand"))}
    {_wire(70, _nc(45, "q"), _nc(46, "in"), _nc(47, "in"))}
    {_wire(71, _ident(32), _nc(46, "operand"))}
    {_wire(72, _ident(34), _nc(47, "value"))}
    {_wire(73, _ident(33), _nc(47, "operand"))}
  </Wires>
{_FLGNET_CLOSE}"""

# 来源：001_KL_Standard_FB_FB5002_SafetyDoorV1.xml 网络 1（启保停子电路）
# Contact38.out 扇出到 3 个下游（共享 DAG 支路）；36/37 带 <Negated>。
# docs/16 §3.1/§3.2 / §7.2 判定点 ⑥。
FB5002_NET1_SELFHOLD = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "i_DoorOverRide")}
    {_access(22, "EMMode")}
    {_access(23, "i_AutoRunning")}
    {_access(24, "i_OpenDoorPmt")}
    {_access(25, "o_DoorOverRideRelayOn")}
    {_access(26, "Aux", "DT2")}
    {_access(28, "DB1000_StdSignal", "PLS", "PS10", scope="GlobalVariable")}
    {_access(29, "Aux", "DT2")}
    {_access(30, "Aux", "DT1")}
    {_access(31, "Aux", "DT2")}
    {_part("Contact", 35)}
    {_part("Contact", 36, negated=True)}
    {_part("Contact", 37, negated=True)}
    {_part("Contact", 38)}
    {_part("SCoil", 39)}
    {_part("Contact", 42)}
    {_part("Contact", 43)}
    {_part("O", 44, inner='<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>')}
    {_part("Contact", 45)}
    {_part("Coil", 46)}
  </Parts>
  <Wires>
    {_wire(51, _powerrail(), _nc(35, "in"))}
    {_wire(52, _ident(21), _nc(35, "operand"))}
    {_wire(53, _nc(35, "out"), _nc(36, "in"))}
    {_wire(54, _ident(22), _nc(36, "operand"))}
    {_wire(55, _nc(36, "out"), _nc(37, "in"))}
    {_wire(56, _ident(23), _nc(37, "operand"))}
    {_wire(57, _nc(37, "out"), _nc(38, "in"))}
    {_wire(58, _ident(24), _nc(38, "operand"))}
    {_wire(59, _nc(38, "out"), _nc(39, "in"), _nc(42, "in"), _nc(43, "in"))}
    {_wire(60, _ident(25), _nc(39, "operand"))}
    {_wire(64, _ident(28), _nc(42, "operand"))}
    {_wire(65, _nc(42, "out"), _nc(44, "in1"))}
    {_wire(66, _ident(29), _nc(43, "operand"))}
    {_wire(67, _nc(43, "out"), _nc(44, "in2"))}
    {_wire(68, _nc(44, "out"), _nc(45, "in"))}
    {_wire(69, _ident(30), _nc(45, "operand"))}
    {_wire(70, _nc(45, "out"), _nc(46, "in"))}
    {_wire(71, _ident(31), _nc(46, "operand"))}
  </Wires>
{_FLGNET_CLOSE}"""

# 来源：004_AutoStep_FB1060_AutoStep.xml 网络 1 — IEC TON box 的 Q 驱动 SCoil。
# docs/16 §3.1 / §7.2 判定点 ⑧（修复前无条件置位，上电即常置位）。
FB1060_TON_Q_GATE = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(30, "DB1900_Communication_PC", "Recv", "EmmMode", scope="GlobalVariable")}
    <Access Scope="TypedConstant" UId="32"><Constant><ConstantValue>T#5s</ConstantValue></Constant></Access>
    {_access(33, "DB1900_Communication_PC", "Send", "PowerOff", scope="GlobalVariable")}
    {_part("Contact", 76)}
    {_part("TON", 78, inner='<Instance Scope="GlobalVariable" UId="79"><Component Name="Timer_RecvEmmMode" /></Instance><TemplateValue Name="time_type" Type="Type">Time</TemplateValue>')}
    {_part("SCoil", 80)}
  </Parts>
  <Wires>
    {_wire(127, _powerrail(), _nc(76, "in"))}
    {_wire(129, _ident(30), _nc(76, "operand"))}
    {_wire(128, _nc(76, "out"), _nc(78, "IN"))}
    {_wire(130, _ident(32), _nc(78, "PT"))}
    {_wire(131, _nc(78, "Q"), _nc(80, "in"))}
    {_wire(133, _ident(33), _nc(80, "operand"))}
  </Wires>
{_FLGNET_CLOSE}"""

# 来源：004_AutoStep_FB1060_AutoStep.xml 网络 1 — Eq93 的 .pre 前置 RLO
# (Contact92 ← ClearHoleNoReq)。docs/16 §4 S6 / §7.2 判定点 ④。
FB1060_EQ93_PRE = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(38, "DB1900_Communication_PC", "Recv", "PosNoClear", scope="GlobalVariable")}
    {_access(49, "DB1900_Communication_PC", "Recv", "ClearHoleNoReq", scope="GlobalVariable")}
    {_access(50, "Aux", "HoleNo")}
    <Access Scope="TypedConstant" UId="51"><Constant><ConstantValue>0</ConstantValue></Constant></Access>
    {_access(52, "DB1900_Communication_PC", "Send", "ClearHoleNum", scope="GlobalVariable")}
    {_part("Contact", 84)}
    {_part("Contact", 92)}
    {_part("Eq", 93, inner='<TemplateValue Name="SrcType" Type="Type">Int</TemplateValue>')}
    {_part("Coil", 94)}
  </Parts>
  <Wires>
    {_wire(140, _powerrail(), _nc(84, "in"))}
    {_wire(141, _ident(38), _nc(84, "operand"))}
    {_wire(157, _ident(49), _nc(92, "operand"))}
    {_wire(175, _nc(84, "out"), _nc(92, "in"))}
    {_wire(158, _nc(92, "out"), _nc(93, "pre"))}
    {_wire(159, _ident(50), _nc(93, "in1"))}
    {_wire(160, _ident(51), _nc(93, "in2"))}
    {_wire(161, _nc(93, "out"), _nc(94, "in"))}
    {_wire(162, _ident(52), _nc(94, "operand"))}
  </Wires>
{_FLGNET_CLOSE}"""

# 来源：006_ Visual Chiseling_FC2300 Time Calculation.xml 网络 5（逐字节摘录）
# Mul/Add 数学框；修复前整网只剩 (* TODO[Mul] *) / (* TODO[Add] *)。
# docs/16 §3.1 / §7.2 判定点 ⑨。
FC2300_NET5 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="LocalVariable" UId="21">
      <Symbol><Component Name="High" /></Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="22">
      <Symbol>
        <Component Name="DB2500 Visual Chiseling" />
        <Component Name="PLC Time" />
        <Component Name="MINUTE" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="23">
      <Constant><ConstantType>USInt</ConstantType><ConstantValue>64</ConstantValue></Constant>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol><Component Name="Temp_PLC_Minute" /></Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="25">
      <Symbol><Component Name="Temp_PLC_Minute" /></Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="26">
      <Symbol>
        <Component Name="DB2500 Visual Chiseling" />
        <Component Name="PLC Time" />
        <Component Name="SECOND" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="27">
      <Symbol>
        <Component Name="DB2100 Modbus Value" />
        <Component Name="PLC Para" />
        <Component Name="Time Word 2" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="28" />
    <Part Name="Mul" UId="29" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
      <AutomaticTyped Name="SrcType" />
    </Part>
    <Part Name="Add" UId="30" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
      <AutomaticTyped Name="SrcType" />
    </Part>
  </Parts>
  <Wires>
    <Wire UId="31"><Powerrail /><NameCon UId="28" Name="in" /></Wire>
    <Wire UId="32"><IdentCon UId="21" /><NameCon UId="28" Name="operand" /></Wire>
    <Wire UId="33"><NameCon UId="28" Name="out" /><NameCon UId="29" Name="en" /></Wire>
    <Wire UId="34"><IdentCon UId="22" /><NameCon UId="29" Name="in1" /></Wire>
    <Wire UId="35"><IdentCon UId="23" /><NameCon UId="29" Name="in2" /></Wire>
    <Wire UId="36"><NameCon UId="29" Name="eno" /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="37"><NameCon UId="29" Name="out" /><IdentCon UId="24" /></Wire>
    <Wire UId="38"><IdentCon UId="25" /><NameCon UId="30" Name="in1" /></Wire>
    <Wire UId="39"><IdentCon UId="26" /><NameCon UId="30" Name="in2" /></Wire>
    <Wire UId="40"><NameCon UId="30" Name="out" /><IdentCon UId="27" /></Wire>
  </Wires>
</FlgNet>
"""


# ---------------------------------------------------------------------------
# 正例 golden（真实网络 → 期望 SCL 语句/布尔表达式）
# ---------------------------------------------------------------------------

_FB2009_EXACT = [
    '#Timer_StationToolOn.TON(IN := (#Auto_Mode AND #I_StationToolOn_1) AND #I_StationToolOn_2, PT := T#2s);',
    '#SR_StationTool.SR(S := #Timer_StationToolOn.Q, R1 := NOT (#I_StationToolOn_1) OR NOT (#I_StationToolOn_2) OR #Timer_StationCoolingFan.Q OR #Man_Mode OR #Emm_Mode);',
    'IF #SR_StationTool.Q THEN #ToolAtPos := TRUE; ELSE #ToolAtPos := FALSE; END_IF;',
    '#Timer_StationCoolingFan.TON(IN := #SR_StationTool.Q, PT := #CoolingTime);',
]

_FB5002_START = '((#i_DoorOverRide AND NOT (#EMMode)) AND NOT (#i_AutoRunning)) AND #i_OpenDoorPmt'
# 与 test_tia_fold_fixes.py::test_fb5002_net1_shared_dag_branches_keep_full_chain
# 的精确断言逐字一致（此处为 ((({start})，非 (((({start})）。
_FB5002_EXACT = [
    f'IF {_FB5002_START} THEN #o_DoorOverRideRelayOn := TRUE; END_IF;',
    (
        f'#Aux.DT2 := ((({_FB5002_START}) AND "DB1000_StdSignal".PLS.PS10)'
        f' OR (({_FB5002_START}) AND #Aux.DT2)) AND #Aux.DT1;'
    ),
]

_FB1060_TON_Q_EXACT = [
    '"Timer_RecvEmmMode".TON(IN := "DB1900_Communication_PC".Recv.EmmMode, PT := T#5s);',
    'IF "Timer_RecvEmmMode".Q THEN "DB1900_Communication_PC".Send.PowerOff := TRUE; END_IF;',
]

_FB1060_EQ93_EXACT = [
    (
        '"DB1900_Communication_PC".Send.ClearHoleNum := '
        '("DB1900_Communication_PC".Recv.PosNoClear AND '
        '"DB1900_Communication_PC".Recv.ClearHoleNoReq) AND (#Aux.HoleNo = 0);'
    ),
]

GOLDEN: list[dict[str, Any]] = [
    {
        "id": "S1_positive_FC2300_net5_math_restored",
        "defect": "S1_statement_loss",
        "input": "FC2300_NET5（006_ Visual Chiseling_FC2300 Time Calculation.xml 网络 5）",
        "expected": (
            "docs/16 §7.2 判定点 ⑨ + test_tia_translate_fixes.py::"
            "test_fc2300_net5_math_restored：数学链恢复，2 条语句、无 TODO"
        ),
        "flgnet": FC2300_NET5,
        "tokens": [
            "IF #High THEN #Temp_PLC_Minute :=",
            "* 64",
            "#Temp_PLC_Minute +",
            "SECOND",
        ],
        "forbidden": ["TODO[Mul]", "TODO[Add]", "TODO[translate-align]", "folded-leftover"],
    },
    {
        "id": "S2_positive_FB5002_net1_shared_dag_branches",
        "defect": "S2_loop_guard",
        "input": "FB5002_NET1_SELFHOLD（001_KL_Standard_FB_FB5002_SafetyDoorV1.xml 网络 1）",
        "expected": (
            "test_tia_fold_fixes.py::test_fb5002_net1_shared_dag_branches_keep_full_chain "
            "精确整句（2 条）+ docs/16 §7.2 判定点 ⑥：共享链完整、无 loop guard"
        ),
        "flgnet": FB5002_NET1_SELFHOLD,
        "fold_exact": _FB5002_EXACT,
        "tokens": [_FB5002_START, '"DB1000_StdSignal".PLS.PS10', "#Aux.DT1"],
        "forbidden": ["loop guard"],
    },
    {
        "id": "S3_positive_FB2009_net1_typed_constant_pt",
        "defect": "S3_empty_literal",
        "input": "FB2009_NET1（005_Component_Cooling Fan_FB2009_CoolingFanFunction.xml 网络 1）",
        "expected": (
            "test_tia_fold_fixes.py::test_fb2009_net1_sr_box_instance_and_lowercase_pins "
            "精确整句（4 条）+ docs/16 §7.2 判定点 ⑤：PT := T#2s 非空"
        ),
        "flgnet": FB2009_NET1,
        "fold_exact": _FB2009_EXACT,
        "tokens": ["PT := T#2s", "#SR_StationTool.SR(", "#Timer_StationCoolingFan.TON("],
        "forbidden": ["PT := )", "PT := ;", '"TRUE"', 'PT := (* PT *)'],
    },
    {
        "id": "S4_positive_FB5002_net1_negated_contacts",
        "defect": "S4_negation_loss",
        "input": "FB5002_NET1_SELFHOLD（001_KL_Standard_FB_FB5002_SafetyDoorV1.xml 网络 1）",
        "expected": (
            "docs/16 §7.2 判定点 ⑥ + test_tia_translate_fixes.py::"
            "test_fb5002_net1_no_loop_guard_and_polarity_kept：极性恢复 NOT (#EMMode) / "
            "NOT (#i_AutoRunning)"
        ),
        "flgnet": FB5002_NET1_SELFHOLD,
        "fold_exact": _FB5002_EXACT,
        "tokens": ["NOT (#EMMode)", "NOT (#i_AutoRunning)", "#i_DoorOverRide"],
        "forbidden": ["#i_DoorOverRide AND #EMMode AND #i_AutoRunning"],
    },
    {
        "id": "S5_positive_FB1060_net1_ton_q_gate",
        "defect": "S5_driver_loss",
        "input": "FB1060_TON_Q_GATE（004_AutoStep_FB1060_AutoStep.xml 网络 1）",
        "expected": (
            "test_tia_fold_fixes.py::test_fb1060_ton_q_gates_downstream_set_coil 精确整句 "
            "+ docs/16 §7.2 判定点 ⑧：由 TON.Q 门控，非无条件置位"
        ),
        "flgnet": FB1060_TON_Q_GATE,
        "fold_exact": _FB1060_TON_Q_EXACT,
        "tokens": ['IF "Timer_RecvEmmMode".Q THEN', "PT := T#5s"],
        "forbidden": ['"Send.PowerOff" := TRUE;', "Sr();"],
    },
    {
        "id": "S5_positive_FB1060_net1_eq_pre_rlo",
        "defect": "S5_driver_loss",
        "input": "FB1060_EQ93_PRE（004_AutoStep_FB1060_AutoStep.xml 网络 1，Eq93 .pre 子电路）",
        "expected": (
            "test_tia_fold_fixes.py::test_fb1060_eq93_pre_contact_gates_comparison 精确整句 "
            "+ docs/16 §7.2 判定点 ④：ClearHoleNoReq 前置 RLO 折入比较器"
        ),
        "flgnet": FB1060_EQ93_PRE,
        "fold_exact": _FB1060_EQ93_EXACT,
        "tokens": ["ClearHoleNoReq", "(#Aux.HoleNo = 0)", "#Aux.HoleNo = 0"],
        "forbidden": ["PT := )"],
    },
]


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_golden_positive_semantic_equivalence(case: dict[str, Any]) -> None:
    """正例：真实 FlgNet 片段 → 折叠层 + 翻译层 → 期望 SCL 语义等价。"""
    fold_lines = _fold_lines(case["flgnet"])
    translate_lines = _translate_lines(case["flgnet"])
    joined = "\n".join(fold_lines + translate_lines)
    normalized = _norm(joined)
    compact = _compact(joined)

    # ① 关键 token / 布尔表达式（去空白 + 去无害注释后比较）
    for token in case["tokens"]:
        assert _norm(token) in normalized, (
            f"{case['id']}: 期望关键表达式缺失 {token!r}\n实际输出:\n{joined}"
        )

    # ② 有据可查的精确整句（折叠层逐条归一后相等，绝不迁就实现）
    if case.get("fold_exact"):
        got = [_norm(line) for line in fold_lines]
        want = [_norm(line) for line in case["fold_exact"]]
        assert got == want, (
            f"{case['id']}: fold 语句与 golden 整句不等价\n期望: {want}\n实际: {got}"
        )
        # 翻译层消费同源折叠语句，关键 token 也必须一致
        for line in case["fold_exact"]:
            assert _norm(line) in _norm("\n".join(translate_lines)), (
                f"{case['id']}: translate 层丢失整句 {line!r}"
            )

    # ③ 该类缺陷坏标记不得出现（保留注释文本检测）
    for bad in case["forbidden"]:
        assert bad not in compact, f"{case['id']}: 命中缺陷坏标记 {bad!r}"

    # ④ 五类缺陷模式扫描：正例生成结果必须干净
    assert scan_scl_defects(joined) == {}, (
        f"{case['id']}: 生成结果仍含缺陷模式 {list(scan_scl_defects(joined))}"
    )


# ---------------------------------------------------------------------------
# 反例（每类 1 条）：修复前坏输出负向对照 + fail-closed 门禁必须拦住
# ---------------------------------------------------------------------------

NEGATIVE: list[dict[str, Any]] = [
    {
        "id": "S1_negative_FC2300_net5_todo_only",
        "defect": "S1_statement_loss",
        "flgnet": FC2300_NET5,
        "bad_scl": "(* TODO[Mul] *)\n(* TODO[Add] *)",
        "bad_source": "docs/16 §3.1 FC2300 网络 5 修复前实际输出（整网只剩两条 TODO 注释）",
        "bad_markers": ["TODO[Mul]", "TODO[Add]", "TODO[translate-align]"],
        "required_tokens": ["IF #High THEN", "* 64"],
        "gate_code": "S1_statement_loss",
    },
    {
        "id": "S2_negative_FB5002_net1_loop_guard",
        "defect": "S2_loop_guard",
        "flgnet": FB5002_NET1_SELFHOLD,
        "bad_scl": "#Aux.DT2 := ((* loop guard *) AND #i_OpenDoorPmt) AND #Aux.DT2;",
        "bad_source": "docs/16 §3.2 FB5002 网络 1 修复前实际输出（逐字）",
        "bad_markers": ["loop guard"],
        "required_tokens": ["NOT (#EMMode)", '"DB1000_StdSignal".PLS.PS10'],
        "gate_code": "S2_loop_guard",
    },
    {
        "id": "S3_negative_FB2009_net1_empty_pt",
        "defect": "S3_empty_literal",
        "flgnet": FB2009_NET1,
        "bad_scl": "#Timer_StationToolOn.TON(IN := TRUE, PT := );",
        "bad_source": "docs/16 §3.1 FB2009 网络 1 修复前实际输出（PT := ) 空，语法非法）",
        "bad_markers": ["PT := )", "PT := ;"],
        "required_tokens": ["PT := T#2s"],
        "gate_code": "S3_empty_literal",
    },
    {
        "id": "S4_negative_FB5002_net1_polarity_reversed",
        "defect": "S4_negation_loss",
        "flgnet": FB5002_NET1_SELFHOLD,
        # 按 docs/16 §3.1 对修复前坏输出的描述复现（NOT 全丢、极性反转），
        # 非逐字摘录；仅作负向对照，不作为正确期望值。
        "bad_scl": "#i_DoorOverRide AND #EMMode AND #i_AutoRunning AND #i_OpenDoorPmt",
        "bad_source": "docs/16 §3.1 描述复现：取反全部丢失，EMMode/i_AutoRunning 变正逻辑",
        "bad_markers": ["#i_DoorOverRide AND #EMMode AND #i_AutoRunning"],
        "required_tokens": ["NOT (#EMMode)", "NOT (#i_AutoRunning)"],
        "gate_code": "S4_negation_loss",
        "gate_project": True,  # 极性反转靠 PlcProject 的 negated 守恒判定
    },
    {
        "id": "S5_negative_FB1060_net1_unconditional_set",
        "defect": "S5_driver_loss",
        "flgnet": FB1060_TON_Q_GATE,
        # docs §3.1 无条件置位 + §3.2 空箱体调用（箱体输出/实例全丢）
        "bad_scl": '"Send.PowerOff" := TRUE;\nSr();',
        "bad_source": "docs/16 §3.1 FB1060 + §3.2 FB2009 修复前实际输出",
        "bad_markers": ['"Send.PowerOff" := TRUE;', "Sr();"],
        "required_tokens": ['IF "Timer_RecvEmmMode".Q THEN'],
        "gate_code": "S5_driver_loss",
    },
]


def _negated_project_from_fragment(flgnet: str) -> PlcProject:
    """把真实片段（含 <Negated> 部件）包装成门禁可读取反守恒的 PlcProject。"""
    block = _parse_fragment(flgnet)
    block.name = "FB_Bad"
    project = PlcProject(name="GoldenNeg")
    project.add_block(block)
    return project


@pytest.mark.parametrize("case", NEGATIVE, ids=[c["id"] for c in NEGATIVE])
def test_golden_negative_regression_and_gate(case: dict[str, Any]) -> None:
    """反例：坏样本与生成结果不等价 + fail-closed 门禁拦住坏样本。"""
    generated = "\n".join(
        _fold_lines(case["flgnet"]) + _translate_lines(case["flgnet"])
    )
    gen_compact = _compact(generated)
    gen_norm = _norm(generated)
    bad_compact = _compact(case["bad_scl"])

    # ① 坏样本绝不等于生成结果（不许退化成修复前坏输出）
    assert bad_compact not in gen_compact, (
        f"{case['id']}: 生成结果退化成修复前坏输出\n坏样本: {case['bad_scl']}"
    )
    # ② 生成结果不含该类坏标记
    for marker in case["bad_markers"]:
        assert marker not in gen_compact, f"{case['id']}: 生成结果含坏标记 {marker!r}"
    # ③ 生成结果含正确语义 token
    for token in case["required_tokens"]:
        assert _norm(token) in gen_norm, f"{case['id']}: 生成结果缺正确 token {token!r}"

    # ④ fail-closed 门禁必须拦住坏样本，且携带块名清单
    if case.get("gate_project"):
        gate_input: dict[str, Any] = {
            "project": _negated_project_from_fragment(case["flgnet"]),
            "scl_sources": {"FB_Bad": case["bad_scl"]},
        }
    else:
        gate_input = {"FB_Bad": case["bad_scl"]}
    with pytest.raises(SclWritebackUnsafeError) as exc:
        assert_scl_safe_for_writeback(gate_input)
    codes = {str(issue.get("code")) for issue in exc.value.issues}
    assert case["gate_code"] in codes, (
        f"{case['id']}: 门禁未命中 {case['gate_code']}，实际 {codes}"
    )
    assert "FB_Bad" in exc.value.blocks


# ---------------------------------------------------------------------------
# 覆盖声明 / 解析层 / 真实全链路 smoke / 仍未等价
# ---------------------------------------------------------------------------


def test_golden_covers_all_five_classes_with_positive_and_negative() -> None:
    """五类 S1~S5 每类至少 1 正例 + 1 反例（明确声明，防漏）。"""
    assert set(SCL_DEFECT_PATTERNS) == {
        "S1_statement_loss",
        "S2_loop_guard",
        "S3_empty_literal",
        "S4_negation_loss",
        "S5_driver_loss",
    }
    positive = {c["defect"] for c in GOLDEN}
    negative = {c["defect"] for c in NEGATIVE}
    assert positive == set(SCL_DEFECT_PATTERNS)
    assert negative == set(SCL_DEFECT_PATTERNS)
    for defect in SCL_DEFECT_PATTERNS:
        assert any(c["defect"] == defect for c in GOLDEN), f"缺 {defect} 正例"
        assert any(c["defect"] == defect for c in NEGATIVE), f"缺 {defect} 反例"


def test_s3_parse_layer_typed_constant_is_literal() -> None:
    """S3 解析层正例：Scope="TypedConstant" → LITERAL + T#5S。

    逐字节摘录自 003_HomeStep_FB1040_HomePos.xml 网络 7；期望值来自
    test_tia_parse_fixes.py::test_typed_constant_renders_time_literal。
    """
    access = parse_access(
        ET.fromstring(
            '<Access Scope="TypedConstant" UId="31">'
            "<Constant><ConstantValue>T#5S</ConstantValue></Constant>"
            "</Access>"
        )
    )
    assert access.scope is AccessScope.LITERAL
    assert access.as_scl() == "T#5S"
    assert access.as_scl() != ""


_HR001_BLOCKS = Path(
    "C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/PLC_Openness_data"
    "/hr001/export/plc/CPU_1200/blocks"
)


@pytest.mark.skipif(not _HR001_BLOCKS.is_dir(), reason="真实 HR001 导出未挂载（只读数据）")
def test_real_hr001_export_networks_defect_free() -> None:
    """真实全链路 smoke：直接读只读导出 XML，跑 fold+translate，扫五类缺陷。

    来源文件与 Network 编号逐条写明；数据缺失时 skip，不伪造。
    """
    checks = [
        ("001_KL_Standard_FB_FB5002_SafetyDoorV1.xml", 0, "网络 1",
         ["NOT (#EMMode)", "NOT (#i_AutoRunning)"], "loop guard"),
        ("005_Component_Cooling Fan_FB2009_CoolingFanFunction.xml", 0, "网络 1",
         ["PT := T#2s", "#SR_StationTool.SR("], "PT := )"),
        ("006_ Visual Chiseling_FC2300 Time Calculation.xml", 4, "网络 5",
         ["* 64", "SECOND"], "TODO["),
    ]
    for filename, index, network_label, tokens, bad in checks:
        block = parse_block_xml(_HR001_BLOCKS / filename)
        assert block is not None and len(block.networks) > index, filename
        network = block.networks[index]
        network.folded = fold_network(network)
        joined = "\n".join(NetworkTranslator(block, network).translate())
        assert scan_scl_defects(joined) == {}, f"{filename} {network_label}: 命中缺陷模式"
        assert bad not in _compact(joined), f"{filename} {network_label}: 含坏标记 {bad!r}"
        normalized = _norm(joined)
        for token in tokens:
            assert _norm(token) in normalized, (
                f"{filename} {network_label}: 缺关键 token {token!r}"
            )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "如实标注「仍未等价」：docs/16 §7.4 残留——FC2300 网络 5 的 "
        '"DB2500 Visual Chiseling".PLC Time.MINUTE 含空格成员名未加引号，'
        "TIA External Source 编译会失败；数学语义已恢复，但 SCL 文本仍非合法等价。"
        "不放宽本文件任何 golden 期望值来迁就实现。"
    ),
)
def test_known_gap_fc2300_spaced_identifiers_not_quoted() -> None:
    joined = "\n".join(_translate_lines(FC2300_NET5))
    # 正确的 SCL 应把含空格成员渲染成引号标识符 "PLC Time".MINUTE
    assert '"PLC Time".MINUTE' in joined
    assert '"PLC Time".SECOND' in joined
