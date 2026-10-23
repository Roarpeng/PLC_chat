"""Regression tests for flgnet_fold fixes S2/S5/S6/S7/S9/S10 (docs/16 §4).

Every FlgNet fragment below is a real hr001 export network
(PLC_Openness_data/hr001/export), embedded verbatim or trimmed to the
subcircuit under test (UIds, pin casing and names kept as exported).
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from agents.plc.tia.flgnet_fold import FoldStmt, fold_network, folded_to_dict, stmt_to_scl
from agents.plc.tia.ir import And, AssignStmt, Or
from agents.plc.tia.simaticml import parse_block_xml

_FLGNET_OPEN = '<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">'
_FLGNET_CLOSE = "</FlgNet>"


def _parse_flgnet(flgnet: str):
    """Parse one FlgNet snippet embedded in a minimal LAD OB document."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.OB ID="0">
    <AttributeList><Name>OB_FoldFixes</Name><Number>1</Number>
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
  </SW.Blocks.OB>
</Document>
"""
    with TemporaryDirectory() as td:
        path = Path(td) / "OB_FoldFixes.xml"
        path.write_text(xml, encoding="utf-8")
        return parse_block_xml(path)


def _fold_lines(flgnet: str) -> list[str]:
    return [stmt_to_scl(s) for s in fold_network(_parse_flgnet(flgnet).networks[0]).statements]


def _access(uid: int, *comps: str, scope: str = "LocalVariable") -> str:
    body = "".join(f'<Component Name="{c}" />' for c in comps)
    return f'<Access Scope="{scope}" UId="{uid}"><Symbol>{body}</Symbol></Access>'


def _part(name: str, uid: int, *, negated: bool = False, inner: str = "") -> str:
    neg = '<Negated Name="operand" />' if negated else ""
    return f'<Part Name="{name}" UId="{uid}">{neg}{inner}</Part>'


def _wire(uid: int, *ends: str) -> str:
    body = "".join(ends)
    return f'<Wire UId="{uid}">{body}</Wire>'


def _powerrail() -> str:
    return "<Powerrail />"


def _ident(uid: int) -> str:
    return f'<IdentCon UId="{uid}" />'


def _nc(uid: int, pin: str) -> str:
    return f'<NameCon UId="{uid}" Name="{pin}" />'


# ---------------------------------------------------------------------------
# S2 + S5 + S10: FB2009 net1 verbatim — SR box (lowercase s/r1/q pins,
# operand instance), CoilTON chain, timer/latch outputs as downstream drivers.
# ---------------------------------------------------------------------------

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


def test_fb2009_net1_sr_box_instance_and_lowercase_pins() -> None:
    """S10: Sr box reads its operand instance and s/r1/q pins (was `Sr();`)."""
    lines = _fold_lines(FB2009_NET1)
    assert lines == [
        "#Timer_StationToolOn.TON(IN := (#Auto_Mode AND #I_StationToolOn_1) AND #I_StationToolOn_2, PT := T#2s);",
        "#SR_StationTool.SR(S := #Timer_StationToolOn.Q, R1 := NOT (#I_StationToolOn_1)"
        " OR NOT (#I_StationToolOn_2) OR #Timer_StationCoolingFan.Q OR #Man_Mode OR #Emm_Mode);",
        "IF #SR_StationTool.Q THEN #ToolAtPos := TRUE; ELSE #ToolAtPos := FALSE; END_IF;",
        "#Timer_StationCoolingFan.TON(IN := #SR_StationTool.Q, PT := #CoolingTime);",
    ]


def test_fb2009_net1_statements_carry_part_provenance() -> None:
    """Contract extension: every statement is an AssignStmt with part uid."""
    folded = fold_network(_parse_flgnet(FB2009_NET1).networks[0])
    by_uid = {s.part_uuid: s for s in folded.statements if isinstance(s, FoldStmt)}
    assert set(by_uid) == {"38", "45", "46", "47"}
    assert all(isinstance(s, AssignStmt) for s in folded.statements)
    assert by_uid["45"].part_name == "Sr"
    assert by_uid["38"].kind == "call"
    payload = folded_to_dict(folded)
    assert [st["part_uuid"] for st in payload["statements"]] == ["38", "45", "46", "47"]


# ---------------------------------------------------------------------------
# S2: FB5002 net1 self-hold subcircuit — Contact38.out fans out to three
# sinks; the shared chain must appear in every branch, never a loop guard.
# ---------------------------------------------------------------------------

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


def test_fb5002_net1_shared_dag_branches_keep_full_chain() -> None:
    """S2: shared contact chain folds into every branch (no `(* loop guard *)`)."""
    lines = _fold_lines(FB5002_NET1_SELFHOLD)
    start = "((#i_DoorOverRide AND NOT (#EMMode)) AND NOT (#i_AutoRunning)) AND #i_OpenDoorPmt"
    assert lines == [
        f"IF {start} THEN #o_DoorOverRideRelayOn := TRUE; END_IF;",
        f'#Aux.DT2 := ((({start}) AND "DB1000_StdSignal".PLS.PS10)'
        f" OR (({start}) AND #Aux.DT2)) AND #Aux.DT1;",
    ]
    assert not any("loop guard" in line for line in lines)


def test_fb5002_net1_shared_subgraph_is_reused_not_refolded() -> None:
    """S2 memoization: both OR branches share one expression object."""
    folded = fold_network(_parse_flgnet(FB5002_NET1_SELFHOLD).networks[0])
    dt2 = folded.statements[1].value  # And((Or((branch1, branch2)), DT1))
    assert isinstance(dt2, And)
    (or_join, _dt1) = dt2.operands
    assert isinstance(or_join, Or)
    branch_ps10, branch_dt2 = or_join.operands
    # Same DAG node (Contact38.out chain) → identical expression instance.
    assert branch_ps10.operands[0] is branch_dt2.operands[0]


# ---------------------------------------------------------------------------
# S6: FB1060 net1 comparators with `.pre` (Eq93 ← Contact92, Eq98 ← O97).
# ---------------------------------------------------------------------------

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


def test_fb1060_eq93_pre_contact_gates_comparison() -> None:
    lines = _fold_lines(FB1060_EQ93_PRE)
    pre = '("DB1900_Communication_PC".Recv.PosNoClear AND "DB1900_Communication_PC".Recv.ClearHoleNoReq)'
    assert lines == [
        f'"DB1900_Communication_PC".Send.ClearHoleNum := {pre} AND (#Aux.HoleNo = 0);'
    ]


FB1060_EQ98_PRE = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(53, "DB1900_Communication_PC", "Para", "DrillDirection1", scope="GlobalVariable")}
    {_access(54, "DB1900_Communication_PC", "Para", "DrillDirection3", scope="GlobalVariable")}
    {_access(55, "DB1900_Communication_PC", "Para", "Auto_Force", scope="GlobalVariable")}
    <Access Scope="TypedConstant" UId="56"><Constant><ConstantValue>0.0</ConstantValue></Constant></Access>
    {_access(57, "DB1148_PromptBeeper", "Public", "ForceCannotZero", scope="GlobalVariable")}
    {_part("Contact", 95)}
    {_part("Contact", 96)}
    {_part("O", 97, inner='<TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>')}
    {_part("Eq", 98, inner='<TemplateValue Name="SrcType" Type="Type">Real</TemplateValue>')}
    {_part("Coil", 99)}
  </Parts>
  <Wires>
    {_wire(163, _powerrail(), _nc(95, "in"))}
    {_wire(164, _ident(53), _nc(95, "operand"))}
    {_wire(165, _powerrail(), _nc(96, "in"))}
    {_wire(166, _ident(54), _nc(96, "operand"))}
    {_wire(167, _nc(95, "out"), _nc(97, "in1"))}
    {_wire(168, _nc(96, "out"), _nc(97, "in2"))}
    {_wire(169, _nc(97, "out"), _nc(98, "pre"))}
    {_wire(170, _ident(55), _nc(98, "in1"))}
    {_wire(171, _ident(56), _nc(98, "in2"))}
    {_wire(172, _nc(98, "out"), _nc(99, "in"))}
    {_wire(173, _ident(57), _nc(99, "operand"))}
  </Wires>
{_FLGNET_CLOSE}"""


def test_fb1060_eq98_pre_or_gate_gates_comparison() -> None:
    lines = _fold_lines(FB1060_EQ98_PRE)
    pre = '("DB1900_Communication_PC".Para.DrillDirection1 OR "DB1900_Communication_PC".Para.DrillDirection3)'
    assert lines == [
        f'"DB1148_PromptBeeper".Public.ForceCannotZero := {pre}'
        ' AND ("DB1900_Communication_PC".Para.Auto_Force = 0.0);'
    ]


# ---------------------------------------------------------------------------
# S5: FB1060 net1 IEC TON box — Q output gates the downstream set coil
# (was `Send.PowerOff := TRUE;` unconditionally).
# ---------------------------------------------------------------------------

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


def test_fb1060_ton_q_gates_downstream_set_coil() -> None:
    lines = _fold_lines(FB1060_TON_Q_GATE)
    assert lines == [
        '"Timer_RecvEmmMode".TON(IN := "DB1900_Communication_PC".Recv.EmmMode, PT := T#5s);',
        'IF "Timer_RecvEmmMode".Q THEN "DB1900_Communication_PC".Send.PowerOff := TRUE; END_IF;',
    ]


# ---------------------------------------------------------------------------
# S5: FB1040 net7 — SCoil `out` RLO passthrough conditions the Move EN
# (was `ProgNo := 255;` unconditionally).
# ---------------------------------------------------------------------------

FB1040_SCOIL_OUT_MOVE_EN = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "MainStep", "S2")}
    {_access(22, "MainStep", "S6")}
    {_access(23, "DB1042_Timer", "DrillMemory", scope="GlobalVariable")}
    {_access(24, "DB1080_Component", "Robot", "Cmd", "Auto", "GoHome", scope="GlobalVariable")}
    <Access Scope="LiteralConstant" UId="25"><Constant><ConstantType>Int</ConstantType><ConstantValue>255</ConstantValue></Constant></Access>
    {_access(26, "DB1080_Component", "Robot", "CTRL_IN", "ProgNo", scope="GlobalVariable")}
    {_part("Contact", 75)}
    {_part("Contact", 76, negated=True)}
    {_part("Contact", 77, negated=True)}
    {_part("SCoil", 78)}
    {_part("Move", 79, inner='<TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>')}
  </Parts>
  <Wires>
    {_wire(123, _powerrail(), _nc(75, "in"))}
    {_wire(124, _ident(21), _nc(75, "operand"))}
    {_wire(125, _nc(75, "out"), _nc(76, "in"))}
    {_wire(126, _ident(22), _nc(76, "operand"))}
    {_wire(127, _nc(76, "out"), _nc(77, "in"))}
    {_wire(128, _ident(23), _nc(77, "operand"))}
    {_wire(129, _nc(77, "out"), _nc(78, "in"))}
    {_wire(130, _ident(24), _nc(78, "operand"))}
    {_wire(131, _nc(78, "out"), _nc(79, "en"))}
    {_wire(132, _ident(25), _nc(79, "in"))}
    {_wire(133, _nc(79, "out1"), _ident(26))}
  </Wires>
{_FLGNET_CLOSE}"""


def test_fb1040_scoil_out_conditions_move_en() -> None:
    lines = _fold_lines(FB1040_SCOIL_OUT_MOVE_EN)
    rlo = '(#MainStep.S2 AND NOT (#MainStep.S6)) AND NOT ("DB1042_Timer".DrillMemory)'
    assert lines == [
        f'IF {rlo} THEN "DB1080_Component".Robot.Cmd.Auto.GoHome := TRUE; END_IF;',
        f'IF {rlo} THEN "DB1080_Component".Robot.CTRL_IN.ProgNo := 255; END_IF;',
    ]


# ---------------------------------------------------------------------------
# S7: FB5009 net2 — Convert box EN conditions the assignment.
# ---------------------------------------------------------------------------

FB5009_NET2_CONVERT_EN = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "TRUE", scope="GlobalVariable")}
    {_access(22, "Cmd", "Read1")}
    {_access(23, "IW")}
    {_access(24, "Ctrl_IN", "TP_ActualAI_1")}
    {_part("Contact", 28)}
    {_part("Contact", 29)}
    {_part("Convert", 30, inner='<TemplateValue Name="SrcType" Type="Type">Int</TemplateValue><TemplateValue Name="DestType" Type="Type">Real</TemplateValue>')}
  </Parts>
  <Wires>
    {_wire(33, _powerrail(), _nc(28, "in"))}
    {_wire(34, _ident(21), _nc(28, "operand"))}
    {_wire(35, _nc(28, "out"), _nc(29, "in"))}
    {_wire(36, _ident(22), _nc(29, "operand"))}
    {_wire(37, _nc(29, "out"), _nc(30, "en"))}
    {_wire(38, _ident(23), _nc(30, "in"))}
    {_wire(39, _nc(30, "out"), _ident(24))}
  </Wires>
{_FLGNET_CLOSE}"""


def test_fb5009_net2_convert_en_folds_to_if_form() -> None:
    lines = _fold_lines(FB5009_NET2_CONVERT_EN)
    assert lines == [
        "IF TRUE AND #Cmd.Read1 THEN #Ctrl_IN.TP_ActualAI_1 := #IW; END_IF; (* Convert → Real *)",
    ]


def test_convert_with_powerrail_en_stays_unconditional() -> None:
    """Powerrail EN (unconditional box) keeps Convert a plain assignment."""
    flgnet = FB5009_NET2_CONVERT_EN.replace(
        f'{_nc(29, "out")}{_nc(30, "en")}', f'{_powerrail()}{_nc(30, "en")}'
    )
    lines = _fold_lines(flgnet)
    assert lines == ["#Ctrl_IN.TP_ActualAI_1 := #IW; (* Convert → Real *)"]


# ---------------------------------------------------------------------------
# S9: SCL source_text networks pass through verbatim (no per-line ';').
# ---------------------------------------------------------------------------

def test_scl_source_text_network_lines_stay_verbatim() -> None:
    from agents.plc.tia.ir import Network

    net = Network(id="7", source_text="IF #Confirm THEN\n    #Done := 1;\nEND_IF;")
    folded = fold_network(net)
    assert [s.target_scl for s in folded.statements] == [
        "IF #Confirm THEN",
        "#Done := 1;",
        "END_IF;",
    ]


# ---------------------------------------------------------------------------
# ast_trace contract (docs/15 §4) still holds and reflects shared-branch reuse.
# ---------------------------------------------------------------------------

def test_ast_trace_reports_reuse_of_shared_subgraph() -> None:
    trace: list[str] = []
    fold_network(_parse_flgnet(FB5002_NET1_SELFHOLD).networks[0], trace=trace)
    assert any(line.startswith("[net ") and "#Aux.DT2 :=" in line for line in trace)
    assert any("汇入" in line or "并联 OR 归约" in line for line in trace)
    assert any("复用已折叠共享支路" in line for line in trace)
    assert not any("loop guard" in line for line in trace)


def test_box_pin_ref_builds_instance_member_access() -> None:
    """Timer / latch Q references render as instance members (翻译层同形约定)."""
    folded = fold_network(_parse_flgnet(FB2009_NET1).networks[0])
    ton_stmt = next(s for s in folded.statements if s.part_uuid == "47")
    # CoilTON47 IN is driven by Sr45.q → #SR_StationTool.Q member access
    in_txt = ton_stmt.target_scl.split("IN := ")[1].split(",")[0]
    assert in_txt == "#SR_StationTool.Q"
