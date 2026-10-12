"""Instruction coverage fixtures: known Parts must not grow TODO rate."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia import analyze_tia_exports
from agents.plc.tia.parts import canon_part, format_todo
from agents.plc.tia.simaticml import parse_block_xml, parse_export_xml

PARTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_parts"

KNOWN = {
    "FC_Contacts.xml": ("FC_Contacts", ("#Run", "#Latched", "TRUE", "FALSE")),
    "FC_Latch.xml": ("FC_Latch", ("#Q1", "#Q2", "SR1", "RS1")),
    "FC_Timers.xml": ("FC_Timers", ("TOn", "TOff", "TPulse", "TOnR")),
    "FC_Counters.xml": ("FC_Counters", ("CUp", "CDn", "CUd")),
    "FC_Move.xml": ("FC_Move", (":=", "ROUND", "Mux", "Demux")),
    "FC_Compare.xml": ("FC_Compare", ("#Ok",)),
    "FC_Jump.xml": ("FC_Jump", ("JMP", "RETURN")),
    "FC_CallEno.xml": ("FC_CallEno", ("ENO", "MotorInst")),
    "FC_NativeScl.xml": ("FC_NativeScl", ("#Out := #In",)),
    "FC_Stl.xml": ("FC_Stl", ("#Start", "#Stop", "#Run")),
    "FB_Graph.xml": ("FB_Graph", ("GRAPH", "Init", "Run")),
}


def test_canon_part_aliases():
    assert canon_part("CtU") == "CTU"
    assert canon_part("SetCoil") == "Set"
    assert canon_part("TON_R") == "TONR"


def test_format_todo_names_part():
    from agents.plc.tia.ir import Part

    text = format_todo(Part(name="MysteriousBox", part_type="MysteriousBox", uuid="31"))
    assert "TODO[MysteriousBox]" in text
    assert "uid=31" in text


def test_known_parts_have_no_todos():
    result = analyze_tia_exports(str(PARTS), project_name="PartsKit")
    scl = result["scl_sources"]
    coverage = result["coverage"]
    for xml_name, (block, needles) in KNOWN.items():
        src = scl[block]
        assert "TODO[" not in src, f"{xml_name} / {block} leaked TODO:\n{src}"
        for needle in needles:
            assert needle in src, f"{xml_name} missing {needle!r} in:\n{src}"
    # Unknown Part is the only expected leftover among these fixtures
    assert "MysteriousBox" in (coverage.get("todo_histogram") or {})
    assert coverage["todo_histogram"].keys() <= {"MysteriousBox"}


def test_unknown_part_structured_todo():
    block = parse_block_xml(PARTS / "FC_Unknown.xml")
    assert block is not None
    result = analyze_tia_exports(str(PARTS), project_name="PartsKit")
    src = result["scl_sources"]["FC_Unknown"]
    assert "TODO[MysteriousBox]" in src
    assert "uid=" in src


def test_native_scl_passthrough_no_networks():
    block = parse_block_xml(PARTS / "FC_NativeScl.xml")
    assert block is not None
    assert block.programming_language == "SCL"
    assert not block.networks
    assert "#Out := #In;" in block.source_text


def test_graph_steps_and_transitions():
    block = parse_block_xml(PARTS / "FB_Graph.xml")
    assert block is not None
    net = block.networks[0]
    assert net.graph_steps
    assert net.graph_transitions
    assert net.graph_steps[0].name == "Init"
    assert "GRAPH" in (net.source_text or "")
    assert net.folded is not None
    assert net.folded.evidence == "graph_sequence"


def test_graph_sequence_interlock_is_ir_evidence():
    block = parse_block_xml(PARTS / "FB_Graph_Sequence.xml")
    assert block is not None
    net = block.networks[0]
    assert [s.name for s in net.graph_steps] == ["Idle", "Move"]
    assert net.graph_steps[0].interlock == "#Permissive"
    assert net.graph_steps[0].supervision == "#Watchdog"
    assert net.graph_steps[0].evidence == "graph_xml"
    assert net.graph_transitions[0].condition == "#Start"
    assert net.folded is not None
    assert net.folded.evidence == "graph_sequence"
    assert "not executable" in (net.source_text or "")


def test_stl_rlo_fold():
    block = parse_block_xml(PARTS / "FC_Stl.xml")
    assert block is not None
    src = block.networks[0].source_text or ""
    assert "#Start" in src and "#Stop" in src
    assert "#Run :=" in src


def test_hardware_best_effort():
    item = parse_export_xml(PARTS / "HW_Device.xml", PARTS)
    assert item.kind == "hardware"
    assert item.hardware
    assert item.hardware[0].name == "PLC_1"


def test_safety_f_block_flag():
    block = parse_block_xml(PARTS / "FB_FSafety.xml")
    assert block is not None
    assert block.is_safety
    result = analyze_tia_exports(str(PARTS), project_name="PartsKit")
    assert "F-FB_EStop" in result["coverage"]["safety_blocks"]
    kg = result["knowledge_graph"].to_json()
    node = next(n for n in kg["nodes"] if n["id"] == "Block::F-FB_EStop")
    assert node["props"]["safety"] is True
