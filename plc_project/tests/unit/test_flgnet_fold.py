"""Tests for FlgNet wire-graph folding into expression IR."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.plc.tia.flgnet_fold import (
    attach_folded,
    expr_to_scl,
    fold_network,
    fold_project,
    stmt_to_scl,
)
from agents.plc.tia.scl import translate_block_to_scl
from agents.plc.tia.simaticml import extract_project, parse_block_xml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
CE_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_ce"


def _parse_flgnet(flgnet: str) -> object:
    """Parse one FlgNet snippet embedded in a minimal LAD OB document."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.OB ID="0">
    <AttributeList><Name>OB_Fold</Name><Number>1</Number>
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
        path = Path(td) / "OB_Fold.xml"
        path.write_text(xml, encoding="utf-8")
        return parse_block_xml(path)


def test_fb_motor_self_holding_fold_matches_scl() -> None:
    project = attach_folded(extract_project(FIXTURES, project_name="MotorDemo"))
    folded = project.blocks["FB_Motor"].networks[0].folded

    assert folded is not None
    assert len(folded.statements) == 1
    statement = folded.statements[0]
    assert statement.target is not None
    assert statement.target.name == "Running"
    assert expr_to_scl(statement.value) == (
        "((#Start OR #Running) AND NOT (#Stop)) AND NOT (#Fault)"
    )


def test_fold_project_is_json_serializable() -> None:
    project = attach_folded(extract_project(FIXTURES, project_name="MotorDemo"))
    payload = fold_project(project)

    json.dumps(payload)
    statement = payload["FB_Motor"][0]["statements"][0]
    assert statement["target"] == "#Running"
    assert statement["value"]["type"] == "and"


def test_ce_live_export_fold_move_out1_and_ctu() -> None:
    """Live CE: Clock→Tag coil; in1→out1; Gt+Move out1; Contact+CTU; empty."""
    project = attach_folded(extract_project(CE_FIXTURES, project_name="CeDemo"))
    assert "ce" in project.blocks
    block = project.blocks["ce"]
    assert len(block.networks) == 5

    n1, n2, n3, n4, n5 = [n.folded for n in block.networks]
    assert n1 is not None and n1.statements
    assert stmt_to_scl(n1.statements[0]) == (
        'IF "Clock_1Hz" THEN "Tag_1" := TRUE; ELSE "Tag_1" := FALSE; END_IF;'
    )

    assert n2 is not None and n2.statements
    assert stmt_to_scl(n2.statements[0]) == (
        "IF #in1 THEN #out1 := TRUE; ELSE #out1 := FALSE; END_IF;"
    )

    assert n3 is not None and n3.statements
    assert stmt_to_scl(n3.statements[0]) == "IF (#in2 > #in3) THEN #out2 := #in4; END_IF;"

    assert n4 is not None and n4.statements
    assert n4.unresolved_parts == []
    assert stmt_to_scl(n4.statements[0]) == (
        '"IEC_Counter_0_DB"(CU := #in5, PV := 1, CV => #out3);'
    )

    assert n5 is not None
    assert n5.statements == []

    scl = translate_block_to_scl(block)
    assert 'IF "Clock_1Hz" THEN "Tag_1" := TRUE; ELSE "Tag_1" := FALSE; END_IF;' in scl
    assert "IF #in1 THEN #out1 := TRUE; ELSE #out1 := FALSE; END_IF;" in scl
    assert "IF (#in2 > #in3) THEN #out2 := #in4; END_IF;" in scl
    assert '"IEC_Counter_0_DB"(CU := #in5, PV := 1, CV => #out3);' in scl


_FLGNET_OPEN = '<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">'
_FLGNET_CLOSE = "</FlgNet>"


def _access(uid: int, name: str, scope: str = "LocalVariable") -> str:
    return f'<Access Scope="{scope}" UId="{uid}"><Symbol><Component Name="{name}" /></Symbol></Access>'


def test_coil_timer_folds_to_instance_call() -> None:
    """CoilTON (LAD coil-form TON) folds to IEC timer instance call."""
    flgnet = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "Cmd")}
    {_access(22, "TimerDb", "GlobalVariable")}
    {_access(23, "Preset", "GlobalVariable")}
    <Part Name="Contact" UId="24" />
    <Part Name="CoilTON" UId="25">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="30"><Powerrail /><NameCon UId="24" Name="in" /></Wire>
    <Wire UId="31"><IdentCon UId="21" /><NameCon UId="24" Name="operand" /></Wire>
    <Wire UId="32"><NameCon UId="24" Name="out" /><NameCon UId="25" Name="in" /></Wire>
    <Wire UId="33"><IdentCon UId="22" /><NameCon UId="25" Name="operand" /></Wire>
    <Wire UId="34"><IdentCon UId="23" /><NameCon UId="25" Name="value" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""
    block = _parse_flgnet(flgnet)
    net = block.networks[0]
    folded = fold_network(net)
    assert folded.unresolved_parts == []
    assert len(folded.statements) == 1
    scl = stmt_to_scl(folded.statements[0])
    assert '"TimerDb".TON(IN := #Cmd, PT := "Preset");' == scl


def test_math_boxes_fold_to_value_assignments() -> None:
    """Add / Mul / Sin boxes fold into arithmetic and function assignments."""
    flgnet = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "A")}
    {_access(22, "B")}
    {_access(23, "Sum")}
    {_access(24, "Scaled")}
    {_access(25, "Angle")}
    {_access(26, "SinOut")}
    <Part Name="Add" UId="30" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
      <AutomaticTyped Name="SrcType" />
    </Part>
    <Part Name="Mul" UId="31" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
      <AutomaticTyped Name="SrcType" />
    </Part>
    <Part Name="Sin" UId="32" DisabledENO="true">
      <TemplateValue Name="SrcType" Type="Type">Real</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="40"><Powerrail /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="41"><IdentCon UId="21" /><NameCon UId="30" Name="in1" /></Wire>
    <Wire UId="42"><IdentCon UId="22" /><NameCon UId="30" Name="in2" /></Wire>
    <Wire UId="43"><NameCon UId="30" Name="out" /><IdentCon UId="23" /></Wire>
    <Wire UId="44"><Powerrail /><NameCon UId="31" Name="en" /></Wire>
    <Wire UId="45"><NameCon UId="30" Name="out" /><NameCon UId="31" Name="in1" /></Wire>
    <Wire UId="46"><IdentCon UId="22" /><NameCon UId="31" Name="in2" /></Wire>
    <Wire UId="47"><NameCon UId="31" Name="out" /><IdentCon UId="24" /></Wire>
    <Wire UId="48"><Powerrail /><NameCon UId="32" Name="en" /></Wire>
    <Wire UId="49"><IdentCon UId="25" /><NameCon UId="32" Name="in" /></Wire>
    <Wire UId="50"><NameCon UId="32" Name="out" /><IdentCon UId="26" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""
    block = _parse_flgnet(flgnet)
    folded = fold_network(block.networks[0])
    assert folded.unresolved_parts == []
    rendered = [stmt_to_scl(s) for s in folded.statements]
    assert "#Sum := (#A + #B);" in rendered
    assert "#Scaled := ((#A + #B) * #B);" in rendered
    assert "#SinOut := SIN(#Angle);" in rendered


def test_calc_equation_substitutes_inputs() -> None:
    """CALCULATE box substitutes IN1..INn into its Equation."""
    flgnet = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "X")}
    {_access(22, "Y")}
    {_access(23, "Z")}
    {_access(24, "Result")}
    <Part Name="Calc" UId="30" DisabledENO="true">
      <Equation>IN1 + IN2 * IN3</Equation>
      <TemplateValue Name="Card" Type="Cardinality">3</TemplateValue>
      <TemplateValue Name="SrcType" Type="Type">Int</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="40"><Powerrail /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="41"><IdentCon UId="21" /><NameCon UId="30" Name="IN1" /></Wire>
    <Wire UId="42"><IdentCon UId="22" /><NameCon UId="30" Name="IN2" /></Wire>
    <Wire UId="43"><IdentCon UId="23" /><NameCon UId="30" Name="IN3" /></Wire>
    <Wire UId="44"><NameCon UId="30" Name="out" /><IdentCon UId="24" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""
    block = _parse_flgnet(flgnet)
    folded = fold_network(block.networks[0])
    assert folded.unresolved_parts == []
    scl = stmt_to_scl(folded.statements[0])
    assert "#Result := #X + #Y * #Z;" == scl


def test_t_conv_and_sys_time_folds() -> None:
    """T_CONV folds to typed conversion; RD_SYS_T/WR_SYS_T to SCL calls."""
    flgnet = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "CurPLCTime", "GlobalVariable")}
    {_access(22, "SyS_Time", "GlobalVariable")}
    {_access(23, "RetVal", "GlobalVariable")}
    <Part Name="T_CONV" Version="1.2" UId="30">
      <TemplateValue Name="src_type" Type="Type">DTL</TemplateValue>
      <TemplateValue Name="dest_type" Type="Type">Time_Of_Day</TemplateValue>
    </Part>
    <Part Name="RD_SYS_T" Version="1.0" UId="31">
      <TemplateValue Name="date_type" Type="Type">DTL</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="40"><Powerrail /><NameCon UId="30" Name="en" /></Wire>
    <Wire UId="41"><IdentCon UId="21" /><NameCon UId="30" Name="IN" /></Wire>
    <Wire UId="42"><NameCon UId="30" Name="OUT" /><IdentCon UId="22" /></Wire>
    <Wire UId="43"><Powerrail /><NameCon UId="31" Name="en" /></Wire>
    <Wire UId="44"><NameCon UId="31" Name="RET_VAL" /><IdentCon UId="23" /></Wire>
    <Wire UId="45"><NameCon UId="31" Name="OUT" /><IdentCon UId="21" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""
    block = _parse_flgnet(flgnet)
    folded = fold_network(block.networks[0])
    assert folded.unresolved_parts == []
    rendered = [stmt_to_scl(s) for s in folded.statements]
    assert '"SyS_Time" := "CurPLCTime"; (* T_CONV DTL → Time_Of_Day *)' in rendered
    assert 'RD_SYS_T(RET_VAL => "RetVal", OUT => "CurPLCTime");' in rendered


def test_or_gate_and_edge_contact_join_rlo() -> None:
    """FBD O-gate joins contact branches; PBox passes RLO through."""
    flgnet = f"""{_FLGNET_OPEN}
  <Parts>
    {_access(21, "A")}
    {_access(22, "B")}
    {_access(23, "Any")}
    <Part Name="Contact" UId="30" />
    <Part Name="Contact" UId="31" />
    <Part Name="O" UId="32">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="PBox" UId="33" />
    <Part Name="Coil" UId="34" />
  </Parts>
  <Wires>
    <Wire UId="40"><Powerrail /><NameCon UId="30" Name="in" /></Wire>
    <Wire UId="41"><Powerrail /><NameCon UId="31" Name="in" /></Wire>
    <Wire UId="42"><IdentCon UId="21" /><NameCon UId="30" Name="operand" /></Wire>
    <Wire UId="43"><IdentCon UId="22" /><NameCon UId="31" Name="operand" /></Wire>
    <Wire UId="44"><NameCon UId="30" Name="out" /><NameCon UId="32" Name="in1" /></Wire>
    <Wire UId="45"><NameCon UId="31" Name="out" /><NameCon UId="32" Name="in2" /></Wire>
    <Wire UId="46"><NameCon UId="32" Name="out" /><NameCon UId="33" Name="in" /></Wire>
    <Wire UId="47"><IdentCon UId="23" /><NameCon UId="33" Name="operand" /></Wire>
    <Wire UId="48"><NameCon UId="33" Name="out" /><NameCon UId="34" Name="in" /></Wire>
    <Wire UId="49"><IdentCon UId="23" /><NameCon UId="34" Name="operand" /></Wire>
  </Wires>
{_FLGNET_CLOSE}"""
    block = _parse_flgnet(flgnet)
    folded = fold_network(block.networks[0])
    assert folded.unresolved_parts == []
    assert len(folded.statements) == 1
    scl = stmt_to_scl(folded.statements[0])
    assert scl == "#Any := #A OR #B;"
