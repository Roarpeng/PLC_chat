"""Official TIA Openness chapter-6 export surface — extract + coverage (no real TIA)."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia import analyze_tia_exports
from agents.plc.tia.coverage import build_coverage_report, coverage_markdown
from agents.plc.tia.importer import has_simaticml_exports
from agents.plc.tia.ir import BlockType
from agents.plc.tia.simaticml import extract_project
from agents.plc.tia.surface import OFFICIAL_CATEGORIES

SURFACE = Path(__file__).resolve().parents[1] / "fixtures" / "tia_openness_surface"


def test_has_simaticml_detects_official_layout():
    assert has_simaticml_exports(SURFACE)
    assert (SURFACE / "manifest.json").is_file()


def test_extract_project_fills_official_ir():
    project = extract_project(SURFACE, project_name="OpennessSurface")
    assert "Main" in project.blocks
    assert project.blocks["Main"].block_type == BlockType.OB
    assert "UDT_Motor" in project.blocks
    assert project.blocks["UDT_Motor"].block_type == BlockType.UDT
    assert "Default tag table" in project.tag_tables
    tags = {t.name: t for t in project.tag_tables["Default tag table"].tags}
    assert "StartCmd" in tags
    assert "MAX_SPEED" in tags
    assert tags["MAX_SPEED"].comment == "constant"

    assert "Watch_Main" in project.watch_tables
    assert project.watch_tables["Watch_Main"].entries
    assert "Force_Main" in project.force_tables
    assert project.technology_objects
    assert project.technology_objects[0].name == "Axis_1"
    assert project.technology_objects[0].to_type == "TO_PositioningAxis"
    assert project.technology_objects[0].parameters.get("Modulo") == "360"
    assert project.alarms
    assert project.prodiag
    assert {c.name for c in project.cfc_charts} >= {"Chart1", "Chart_Locked"}
    locked = next(c for c in project.cfc_charts if c.name == "Chart_Locked")
    assert locked.password_protected
    assert project.safety_units
    assert project.safety_units[0].name == "F-Runtime"
    assert "F-ESTOP" in project.safety_units[0].supervisions
    assert any(d.failsafe for d in project.hardware)
    assert any(d.modules for d in project.hardware)
    assert any(getattr(d, "network_interfaces", None) for d in project.hardware)
    assert project.hmi_devices
    hmi = project.hmi_devices[0]
    assert hmi.name == "HMI_1"
    assert any(s.name == "Screen_Main" for s in hmi.screens)
    screen = next(s for s in hmi.screens if s.name == "Screen_Main")
    assert "StartCmd" in screen.linked_tags
    assert hmi.tag_tables
    assert hmi.scripts
    assert hmi.text_lists
    assert hmi.connections
    assert hmi.cycles
    assert "Cycle_100" in hmi.cycles
    assert "CompleteRestart" in project.blocks
    assert "Motor.Running" in project.opcua_nodes
    assert project.project_texts.get("en-US") == "Line 1"
    assert project.export_manifest.get("mode") == "full"


def test_coverage_lists_each_official_category():
    project = extract_project(SURFACE, project_name="OpennessSurface")
    cov = build_coverage_report(project, {})
    cats = cov["categories"]
    for name in OFFICIAL_CATEGORIES:
        assert name in cats, name
        row = cats[name]
        assert "exported" in row and "parsed" in row and "skipped" in row
        assert "skipped_reasons" in row
    assert cats["blocks"]["parsed"] >= 1
    assert cats["types"]["parsed"] >= 1
    assert cats["tags"]["parsed"] >= 1
    assert cats["watch"]["parsed"] >= 1
    assert cats["force"]["parsed"] >= 1
    assert cats["to"]["parsed"] >= 1
    assert cats["alarms"]["parsed"] >= 2
    assert cats["cfc"]["parsed"] >= 2
    assert cats["safety"]["parsed"] >= 1
    assert cats["hardware"]["parsed"] >= 1
    assert cats["hmi"]["parsed"] >= 1
    assert cats["opcua"]["parsed"] >= 1
    assert cats["project"]["parsed"] >= 1
    reasons = {r["reason"] for r in cats["blocks"]["skipped_reasons"]}
    assert "know_how" in reasons
    cfc_reasons = {r["reason"] for r in cats["cfc"]["skipped_reasons"]}
    assert "password_protected" in cfc_reasons
    md = coverage_markdown(cov)
    assert "Official Openness categories" in md
    assert "`watch`" in md


def test_analyze_pipeline_accepts_full_layout():
    result = analyze_tia_exports(str(SURFACE), project_name="OpennessSurface")
    assert result["coverage"]["categories"]["hardware"]["parsed"] >= 1
    assert result["project"].hmi_devices


def test_missing_aml_does_not_fail_block_parse(tmp_path: Path):
    dest = tmp_path / "plc" / "PLC_1" / "blocks"
    dest.mkdir(parents=True)
    (dest / "OB1.xml").write_text(
        '<?xml version="1.0"?><Document><SW.Blocks.OB Name="Main">'
        "<AttributeList><Name>Main</Name><Number>1</Number>"
        "<ProgrammingLanguage>LAD</ProgrammingLanguage></AttributeList>"
        "</SW.Blocks.OB></Document>",
        encoding="utf-8",
    )
    project = extract_project(tmp_path, project_name="NoHw")
    assert "Main" in project.blocks
    assert project.hardware == []
