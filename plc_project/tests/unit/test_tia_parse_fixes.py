"""Parse-layer fixes for real TIA V19 (hr001) SimaticML exports — defects S3/S4.

S3: ``Scope="TypedConstant"`` accesses (timer PT constants) must map to the
    literal scope and render their ``<Constant>`` payload (``T#5S`` …), and a
    GlobalVariable symbol literally named TRUE/FALSE must render as a boolean
    literal, never the quoted identifier ``"TRUE"``.
S4: FlgNet pin-level negation ``<Negated Name="operand"/>`` (child element of
    ``<Part>``) must set ``part.negated`` and be recorded per-pin.

All XML fragments below are verbatim excerpts from
``PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/``:
- 003_HomeStep_FB1040_HomePos.xml  (network 7: three CoilTON + TypedConstant PT)
- 001_KL_Standard_FB_FB5002_SafetyDoorV1.xml (network 1: NOT contacts)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.plc.tia.ir import AccessScope
from agents.plc.tia.simaticml import parse_access, parse_block_xml

_FLGNET_NS = 'xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5"'


def _parse_access_xml(fragment: str):
    return parse_access(ET.fromstring(fragment))


def _parse_flgnet_network(flgnet_parts: str, flgnet_wires: str):
    """Parse Parts/Wires fragments embedded in a minimal LAD FB document."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.FB ID="0">
    <AttributeList><Name>FB_ParseFix</Name><Number>9999</Number>
      <ProgrammingLanguage>LAD</ProgrammingLanguage>
    </AttributeList>
    <ObjectList>
      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">
        <AttributeList>
          <NetworkSource><FlgNet {_FLGNET_NS}>
  <Parts>
{flgnet_parts}
  </Parts>
  <Wires>
{flgnet_wires}
  </Wires>
</FlgNet></NetworkSource>
          <ProgrammingLanguage>LAD</ProgrammingLanguage>
        </AttributeList>
      </SW.Blocks.CompileUnit>
    </ObjectList>
  </SW.Blocks.FB>
</Document>
"""
    with TemporaryDirectory() as td:
        path = Path(td) / "FB_ParseFix.xml"
        path.write_text(xml, encoding="utf-8")
        block = parse_block_xml(path)
    assert block is not None
    assert len(block.networks) == 1
    return block.networks[0]


# ---------------------------------------------------------------------------
# S3 — TypedConstant scope maps to literal (FB1040 net7, verbatim excerpts)
# ---------------------------------------------------------------------------

_FB1040_NET7_PARTS = """\
    <Access Scope="TypedConstant" UId="31">
      <Constant>
        <ConstantValue>T#5S</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="TypedConstant" UId="36">
      <Constant>
        <ConstantValue>T#100mS</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="TypedConstant" UId="44">
      <Constant>
        <ConstantValue>T#5S</ConstantValue>
      </Constant>
    </Access>
    <Part Name="CoilTON" UId="83">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="CoilTON" UId="86">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="CoilTON" UId="93">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>"""

_FB1040_NET7_WIRES = """\
    <Wire UId="139">
      <IdentCon UId="31" />
      <NameCon UId="83" Name="value" />
    </Wire>
    <Wire UId="146">
      <IdentCon UId="36" />
      <NameCon UId="86" Name="value" />
    </Wire>
    <Wire UId="158">
      <IdentCon UId="44" />
      <NameCon UId="93" Name="value" />
    </Wire>"""


def test_typed_constant_renders_time_literal() -> None:
    access = _parse_access_xml(
        """<Access Scope="TypedConstant" UId="31">
      <Constant>
        <ConstantValue>T#5S</ConstantValue>
      </Constant>
    </Access>"""
    )
    assert access.scope == AccessScope.LITERAL
    assert access.as_scl() == "T#5S"


def test_fb1040_net7_coil_ton_pt_non_empty() -> None:
    """All three CoilTON PT (value pin) constants must render their T# value."""
    network = _parse_flgnet_network(_FB1040_NET7_PARTS, _FB1040_NET7_WIRES)

    # Every TypedConstant access is a non-empty literal.
    for uid, expected in (("31", "T#5S"), ("36", "T#100mS"), ("44", "T#5S")):
        access = network.access_parts[uid]
        assert access.scope == AccessScope.LITERAL
        assert access.as_scl() == expected

    # Each CoilTON's `value` (PT) pin is wired to the matching IdentCon.
    pin_src = {}  # (part uid, pin) -> identcon uid
    for wire in network.wires:
        ident = [ep for ep in wire.endpoints if ep.kind == "identcon"]
        cons = [ep for ep in wire.endpoints if ep.kind == "namecon"]
        if ident and cons:
            pin_src[(cons[0].uuid, cons[0].pin)] = ident[0].uuid
    expected_pt = {"83": "T#5S", "86": "T#100mS", "93": "T#5S"}
    for ton_uid, pt_value in expected_pt.items():
        src_uid = pin_src[(ton_uid, "value")]
        assert network.access_parts[src_uid].as_scl() == pt_value


def test_literal_constant_with_type_still_numeric() -> None:
    """Regression: LiteralConstant (Byte 0, FB5002 UId=23) unchanged."""
    access = _parse_access_xml(
        """<Access Scope="LiteralConstant" UId="23">
      <Constant>
        <ConstantType>Byte</ConstantType>
        <ConstantValue>0</ConstantValue>
      </Constant>
    </Access>"""
    )
    assert access.scope == AccessScope.LITERAL
    assert access.as_scl() == "0"
    assert access.data_type == "Byte"


# ---------------------------------------------------------------------------
# S3 — GlobalVariable symbol named TRUE renders as boolean literal
# ---------------------------------------------------------------------------


def test_true_global_variable_renders_bool_literal() -> None:
    """FB5002 verbatim: <Access Scope="GlobalVariable"><Symbol>TRUE</Symbol>."""
    access = _parse_access_xml(
        """<Access Scope="GlobalVariable" UId="21">
      <Symbol>
        <Component Name="TRUE" />
      </Symbol>
    </Access>"""
    )
    assert access.scope == AccessScope.LITERAL
    assert access.as_scl() == "TRUE"
    assert access.as_scl() != '"TRUE"'


def test_false_global_variable_renders_bool_literal() -> None:
    access = _parse_access_xml(
        """<Access Scope="GlobalVariable" UId="22">
      <Symbol>
        <Component Name="FALSE" />
      </Symbol>
    </Access>"""
    )
    assert access.scope == AccessScope.LITERAL
    assert access.as_scl() == "FALSE"


def test_real_global_with_path_stays_quoted() -> None:
    """Regression: DB1000_StdSignal.PLS.PS10 (FB5002 UId=28) keeps quotes."""
    access = _parse_access_xml(
        """<Access Scope="GlobalVariable" UId="28">
      <Symbol>
        <Component Name="DB1000_StdSignal" />
        <Component Name="PLS" />
        <Component Name="PS10" />
      </Symbol>
    </Access>"""
    )
    assert access.scope == AccessScope.GLOBAL
    assert access.as_scl() == '"DB1000_StdSignal".PLS.PS10'


# ---------------------------------------------------------------------------
# S4 — <Negated Name="operand"/> child element (FB5002 net1, verbatim excerpts)
# ---------------------------------------------------------------------------

_FB5002_NET1_PARTS = """\
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="i_DoorOverRide" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="22">
      <Symbol>
        <Component Name="EMMode" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="23">
      <Symbol>
        <Component Name="i_AutoRunning" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol>
        <Component Name="i_OpenDoorPmt" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="25">
      <Symbol>
        <Component Name="o_DoorOverRideRelayOn" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="35" />
    <Part Name="Contact" UId="36">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="37">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="38" />
    <Part Name="SCoil" UId="39" />"""

_FB5002_NET1_WIRES = """\
    <Wire UId="51">
      <Powerrail />
      <NameCon UId="35" Name="in" />
    </Wire>
    <Wire UId="52">
      <IdentCon UId="21" />
      <NameCon UId="35" Name="operand" />
    </Wire>
    <Wire UId="53">
      <NameCon UId="35" Name="out" />
      <NameCon UId="36" Name="in" />
    </Wire>
    <Wire UId="54">
      <IdentCon UId="22" />
      <NameCon UId="36" Name="operand" />
    </Wire>
    <Wire UId="55">
      <NameCon UId="36" Name="out" />
      <NameCon UId="37" Name="in" />
    </Wire>
    <Wire UId="56">
      <IdentCon UId="23" />
      <NameCon UId="37" Name="operand" />
    </Wire>
    <Wire UId="57">
      <NameCon UId="37" Name="out" />
      <NameCon UId="38" Name="in" />
    </Wire>
    <Wire UId="58">
      <IdentCon UId="24" />
      <NameCon UId="38" Name="operand" />
    </Wire>
    <Wire UId="59">
      <NameCon UId="38" Name="out" />
      <NameCon UId="39" Name="in" />
    </Wire>
    <Wire UId="60">
      <IdentCon UId="25" />
      <NameCon UId="39" Name="operand" />
    </Wire>"""


def test_fb5002_net1_negated_contacts_parsed() -> None:
    """NOT(EMMode) / NOT(i_AutoRunning): negation must survive parsing."""
    network = _parse_flgnet_network(_FB5002_NET1_PARTS, _FB5002_NET1_WIRES)

    # Wire 54: Access 22 (EMMode) -> Contact 36 operand; Contact 36 is negated.
    assert network.parts["36"].negated is True
    assert network.parts["36"].negated_pins == {"operand"}
    emmode = network.access_parts["22"]
    assert emmode.as_scl() == "#EMMode"
    assert emmode.negated is False  # negation lives on the contact part

    # Wire 56: Access 23 (i_AutoRunning) -> Contact 37 operand; negated too.
    assert network.parts["37"].negated is True
    assert network.parts["37"].negated_pins == {"operand"}
    assert network.access_parts["23"].as_scl() == "#i_AutoRunning"

    # Plain contacts stay untouched.
    assert network.parts["35"].negated is False
    assert network.parts["38"].negated is False
    assert network.parts["35"].negated_pins == set()


def test_negated_non_operand_pin_recorded_per_pin() -> None:
    """A <Negated Name="q"/> output-pin negation is recorded but must not
    flip part.negated (which downstream treats as operand/RLO negation)."""
    network = _parse_flgnet_network(
        """\
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT2" />
      </Symbol>
    </Access>
    <Part Name="Coil" UId="46">
      <Negated Name="q" />
    </Part>""",
        """\
    <Wire UId="71">
      <IdentCon UId="21" />
      <NameCon UId="46" Name="operand" />
    </Wire>""",
    )
    coil = network.parts["46"]
    assert coil.negated is False
    assert coil.negated_pins == {"q"}


def test_negated_attribute_form_still_supported() -> None:
    """Legacy fixture form <Attribute Name="Negated">true</Attribute>."""
    network = _parse_flgnet_network(
        """\
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="Stop" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="30">
      <Attribute Name="Negated">true</Attribute>
    </Part>""",
        """\
    <Wire UId="31">
      <IdentCon UId="21" />
      <NameCon UId="30" Name="operand" />
    </Wire>""",
    )
    part = network.parts["30"]
    assert part.negated is True
    assert "operand" in part.negated_pins


def test_negated_element_with_false_text_not_negated() -> None:
    network = _parse_flgnet_network(
        """\
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="Run" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="30">
      <Negated Name="operand">false</Negated>
    </Part>""",
        """\
    <Wire UId="31">
      <IdentCon UId="21" />
      <NameCon UId="30" Name="operand" />
    </Wire>""",
    )
    assert network.parts["30"].negated is False
    assert network.parts["30"].negated_pins == set()


def test_local_constant_renders_named_reference() -> None:
    # hr001 FB5715: <Access Scope="LocalConstant"><Constant Name="STEP_EndScan"/></Access>
    # must render as a local #name reference (VAR CONSTANT is re-declared in the
    # generated SCL), never as an empty operand.
    access = parse_access(
        ET.fromstring(
            """\
<Access Scope="LocalConstant" UId="1380">
  <Constant Name="STEP_EndScan" UId="1381" />
</Access>"""
        )
    )
    assert access.scope is AccessScope.LOCAL
    assert access.as_scl() == "#STEP_EndScan"


def test_structured_text_callinfo_instance_name_kept() -> None:
    # hr001 FB5715: StructuredText Call access via CallInfo must keep the
    # callee name (Instance/Component), not collapse to a bare "();".
    from agents.plc.tia.simaticml import _structured_text_to_scl

    st = ET.fromstring(
        """\
<StructuredText>
  <Access Scope="Call" UId="180">
    <CallInfo UId="181" BlockType="FC">
      <Instance Scope="GlobalVariable" UId="183">
        <Component Name="FC1003_CR" UId="182" />
      </Instance>
      <Token Text="(" UId="184" />
      <Token Text=")" UId="190" />
    </CallInfo>
  </Access>
  <Token Text=";" UId="191" />
</StructuredText>"""
    )
    text = _structured_text_to_scl(st)
    assert '"FC1003_CR"();' in text
