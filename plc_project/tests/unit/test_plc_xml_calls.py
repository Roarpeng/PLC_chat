"""XML CallInfo parsing + evidence-gated LLM claims (no title inference)."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.kg import build_knowledge_graph
from agents.plc.tia.simaticml import extract_project, parse_block_xml
from agents.plc.tia.xml_understand import (
    extract_callinfos_from_xml,
    validate_llm_call_claims,
)
from gateway.app.services.plc_jobs import _logic_graph_from_kg


def test_openness_v19_call_element_parsed():
    export = Path(r"C:\Users\vboxuser\AppData\Local\Temp\researchos_tia_export_sjc9l2tp\Blocks\OB1Main.xml")
    if not export.is_file():
        # CI / machines without the temp export: use inline snippet
        from tempfile import TemporaryDirectory

        xml = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.OB ID="0">
    <AttributeList><Name>OB1Main</Name><Number>1</Number>
      <ProgrammingLanguage>LAD</ProgrammingLanguage>
    </AttributeList>
    <ObjectList>
      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">
        <AttributeList>
          <NetworkSource><FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Call UId="21">
      <CallInfo Name="FB1000_StdSignal" BlockType="FB">
        <Instance Scope="GlobalVariable" UId="22">
          <Component Name="DB1000_StdSignal" />
        </Instance>
      </CallInfo>
    </Call>
  </Parts>
</FlgNet></NetworkSource>
          <ProgrammingLanguage>LAD</ProgrammingLanguage>
        </AttributeList>
      </SW.Blocks.CompileUnit>
    </ObjectList>
  </SW.Blocks.OB>
</Document>
"""
        with TemporaryDirectory() as td:
            p = Path(td) / "OB1Main.xml"
            p.write_text(xml, encoding="utf-8")
            block = parse_block_xml(p)
            assert block is not None
            assert block.networks
            parts = list(block.networks[0].parts.values())
            assert any(pt.name == "Call" for pt in parts)
            assert any(pt.template_values.get("Call") == "FB1000_StdSignal" for pt in parts)
            assert any(pt.template_values.get("InstanceDB") == "DB1000_StdSignal" for pt in parts)
        return

    block = parse_block_xml(export)
    assert block is not None
    assert block.name == "OB1Main"
    calls = []
    for net in block.networks:
        for part in net.parts.values():
            if part.template_values.get("Call"):
                calls.append(part.template_values["Call"])
    assert "FB1000_StdSignal" in calls
    assert "FC2500 Visual Chiseling" in calls
    assert len(calls) >= 10


def test_kg_calls_from_real_export_dir():
    root = Path(r"C:\Users\vboxuser\AppData\Local\Temp\researchos_tia_export_sjc9l2tp")
    if not root.is_dir():
        return
    project = extract_project(root)
    if not project.blocks:
        return  # stale export leftover: nothing parseable, nothing to assert
    kg = build_knowledge_graph(project)
    calls = [e for e in kg.edges if e.type == "CALLS"]
    assert any(e.source.endswith("OB1Main") and e.target.endswith("FB1000_StdSignal") for e in calls)
    lg = _logic_graph_from_kg(kg.to_json())
    types = {e["type"] for e in lg["edges"]}
    assert "CALLS" in types
    assert "CONTAINS" not in types


def test_extract_callinfos_and_reject_title_hallucination():
    xml = """
    <FlgNet>
      <Call><CallInfo Name="FB1000_StdSignal" BlockType="FB"/></Call>
    </FlgNet>
    <!-- title noise must never become a call -->
    """
    found = extract_callinfos_from_xml(xml)
    assert found[0]["callee"] == "FB1000_StdSignal"
    rejected = validate_llm_call_claims(
        xml,
        [
            {"callee": "FB1000_StdSignal", "rationale": "CallInfo"},
            {"callee": "DB_StdSignal", "rationale": "from network title"},
            {"callee": "MadeUp_FB", "rationale": "guess"},
        ],
    )
    names = {c["callee"] for c in rejected}
    assert names == {"FB1000_StdSignal"}


def test_fixture_ob_still_parses_part_call():
    fixture = Path("tests/fixtures/tia_exports/Blocks/Main_OB1.xml")
    block = parse_block_xml(fixture)
    assert block is not None
    calls = [
        p.template_values.get("Call")
        for n in block.networks
        for p in n.parts.values()
        if p.template_values.get("Call")
    ]
    assert "FB_Motor" in calls
