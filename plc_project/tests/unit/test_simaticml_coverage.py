"""Regression gate: fixtures + available live exports must parse without gaps.

Fails if any NetworkSource with content yields empty IR, or FlgNet parts
remain unresolved after fold (Call / boxes / coils / moves / ST / STL).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from agents.plc.tia.flgnet_fold import fold_network
from agents.plc.tia.simaticml import parse_block_xml
from agents.plc.tia.scl import translate_block_to_scl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEMP = Path(r"C:\Users\vboxuser\AppData\Local\Temp")


def _strip(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _coverage_roots() -> list[Path]:
    roots: list[Path] = []
    if FIXTURES.is_dir():
        roots.extend(sorted(FIXTURES.glob("tia_*")))
    if TEMP.is_dir():
        roots.extend(
            sorted(TEMP.glob("researchos_tia_export_*"), key=lambda p: p.stat().st_mtime, reverse=True)[
                :8
            ]
        )
    return [r for r in roots if r.is_dir()]


def _newest_xml_by_name(roots: list[Path]) -> dict[str, Path]:
    by_name: dict[str, Path] = {}
    for root in roots:
        for xml in root.rglob("*.xml"):
            by_name[xml.name] = xml
    return by_name


def _network_source_kids(unit: ET.Element) -> list[str]:
    for node in unit.iter():
        if _strip(node.tag) == "NetworkSource":
            return [_strip(c.tag) for c in list(node)]
    return []


def _gap_messages(xml: Path) -> Iterator[str]:
    try:
        block = parse_block_xml(xml)
    except Exception as exc:  # noqa: BLE001
        yield f"FAIL {xml.name}: {exc}"
        return
    if block is None:
        return
    try:
        root = ET.parse(xml).getroot()
    except ET.ParseError as exc:
        yield f"FAIL {xml.name}: {exc}"
        return
    units = [u for u in root.iter() if _strip(u.tag) == "SW.Blocks.CompileUnit"]
    for i, net in enumerate(block.networks, 1):
        if i - 1 >= len(units):
            break
        kids = _network_source_kids(units[i - 1])
        empty_ir = not net.parts and not net.source_text and not net.wires
        if kids and empty_ir:
            yield f"GAP {xml.name} net{i}: XML={kids} IR empty"
            continue
        folded = fold_network(net)
        if net.parts and not folded.statements and not net.source_text and folded.unresolved_parts:
            names = [p.name for p in net.parts.values()]
            yield (
                f"UNRESOLVED {xml.name} net{i}: parts={names} "
                f"unresolved={folded.unresolved_parts[:10]}"
            )
            continue
        # Call / box parts must fold to statements (not silently dropped)
        callish = [
            p
            for p in net.parts.values()
            if p.name in {"Call", "CallPart", "CTU", "CTD", "CTUD", "TON", "TOF", "TP", "R_TRIG", "F_TRIG"}
            or p.template_values.get("Call")
            or p.template_values.get("calledBlock")
        ]
        if callish and not folded.statements and not net.source_text:
            yield f"NO_FOLD {xml.name} net{i}: callish={[p.name for p in callish]}"


def test_fixture_tia_exports_have_zero_parse_gaps() -> None:
    fixture_roots = [r for r in _coverage_roots() if "fixtures" in str(r)]
    assert fixture_roots, "expected tests/fixtures/tia_*"
    gaps: list[str] = []
    for xml in _newest_xml_by_name(fixture_roots).values():
        gaps.extend(_gap_messages(xml))
    assert not gaps, "\n".join(gaps)


def test_live_exports_have_zero_parse_gaps_when_present() -> None:
    live_roots = [r for r in _coverage_roots() if "researchos_tia_export_" in str(r)]
    if not live_roots:
        return
    gaps: list[str] = []
    for xml in _newest_xml_by_name(live_roots).values():
        gaps.extend(_gap_messages(xml))
    assert not gaps, "\n".join(gaps)


def test_call_part_folds_and_emits_scl() -> None:
    """Synthetic Openness V19 <Call> must fold + emit without TODO."""
    from tempfile import TemporaryDirectory

    xml = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.OB ID="0">
    <AttributeList><Name>OB_Call</Name><Number>1</Number>
      <ProgrammingLanguage>LAD</ProgrammingLanguage>
    </AttributeList>
    <ObjectList>
      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">
        <AttributeList>
          <NetworkSource><FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="GlobalVariable" UId="30">
      <Symbol><Component Name="Start"/></Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="31">
      <Symbol><Component Name="Done"/></Symbol>
    </Access>
    <Call UId="21">
      <CallInfo Name="MotorFB" BlockType="FB">
        <Instance Scope="GlobalVariable" UId="22">
          <Component Name="Motor_DB" />
        </Instance>
        <Parameter Name="Start" Section="Input" Type="Bool" />
        <Parameter Name="Done" Section="Output" Type="Bool" />
      </CallInfo>
    </Call>
  </Parts>
  <Wires>
    <Wire UId="40"><IdentCon UId="30" /><NameCon UId="21" Name="Start" /></Wire>
    <Wire UId="41"><NameCon UId="21" Name="Done" /><IdentCon UId="31" /></Wire>
  </Wires>
</FlgNet></NetworkSource>
          <ProgrammingLanguage>LAD</ProgrammingLanguage>
        </AttributeList>
      </SW.Blocks.CompileUnit>
    </ObjectList>
  </SW.Blocks.OB>
</Document>
"""
    with TemporaryDirectory() as td:
        path = Path(td) / "OB_Call.xml"
        path.write_text(xml, encoding="utf-8")
        block = parse_block_xml(path)
    assert block is not None
    net = block.networks[0]
    call = next(p for p in net.parts.values() if p.name == "Call")
    assert call.template_values.get("Call") == "MotorFB"
    assert call.template_values.get("__sec__Start") == "Input"
    assert call.template_values.get("__sec__Done") == "Output"

    folded = fold_network(net)
    assert not folded.unresolved_parts
    assert folded.statements
    scl_call = folded.statements[0].target_scl or ""
    assert '"Motor_DB"' in scl_call
    assert "Start :=" in scl_call
    assert "Done =>" in scl_call

    block.networks[0].folded = folded
    scl = translate_block_to_scl(block)
    assert "TODO" not in scl
    assert '"Motor_DB"' in scl
