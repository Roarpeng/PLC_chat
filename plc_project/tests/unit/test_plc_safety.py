"""Failsafe F-block detection — flag only, no invented bodies."""

from __future__ import annotations

from pathlib import Path

from agents.plc.tia.ir import Block, BlockType
from agents.plc.tia.safety import apply_safety_flags, detect_block_safety, is_safety_name
from agents.plc.tia.simaticml import parse_block_xml
from agents.plc.tia.ir import PlcProject
from agents.plc.tia.analyst import analyze_project
from gateway.app.services.plc_jobs import _logic_graph_from_kg

PARTS = Path(__file__).resolve().parents[1] / "fixtures" / "tia_parts"


def test_detect_by_name_and_language():
    assert is_safety_name("F-FB_EStop")
    assert is_safety_name("FOB_Safety")
    assert detect_block_safety(Block(name="Main", programming_language="F-LAD"))
    assert not detect_block_safety(Block(name="FB_Motor", programming_language="LAD"))


def test_parse_isfailsafe_attribute():
    block = parse_block_xml(PARTS / "FB_FSafety.xml")
    assert block is not None
    assert block.is_safety
    assert block.programming_language == "F-LAD"


def test_apply_safety_flags_project():
    project = PlcProject(name="x")
    project.add_block(Block(name="F-FC_Door", block_type=BlockType.FC, programming_language="LAD"))
    project.add_block(Block(name="FB_Motor", block_type=BlockType.FB, programming_language="LAD"))
    apply_safety_flags(project)
    assert project.blocks["F-FC_Door"].is_safety
    assert not project.blocks["FB_Motor"].is_safety


def test_logic_graph_does_not_mix_standard_ob_with_f_blocks():
    kg = {
        "nodes": [
            {"id": "Block::Main", "type": "Block", "props": {"name": "Main", "block_type": "OB", "safety": False}},
            {"id": "Block::FB_Motor", "type": "Block", "props": {"name": "FB_Motor", "block_type": "FB", "safety": False}},
            {"id": "Block::F-FB_EStop", "type": "Block", "props": {"name": "F-FB_EStop", "block_type": "FB", "safety": True}},
        ],
        "edges": [
            {"source": "Block::Main", "target": "Block::FB_Motor", "type": "CALLS", "props": {"seq": 1}},
            {"source": "Block::Main", "target": "Block::F-FB_EStop", "type": "CALLS", "props": {"seq": 2}},
        ],
    }
    logic = _logic_graph_from_kg(kg)
    targets = {(e["source"], e["target"]) for e in logic["edges"] if e["type"] == "CALLS"}
    assert ("Block::Main", "Block::FB_Motor") in targets
    assert ("Block::Main", "Block::F-FB_EStop") not in targets


def test_analyst_safety_outputs_and_standard_writes():
    job = {
        "project_name": "Safe",
        "blocks": [
            {"name": "Main", "type": "OB", "is_safety": False},
            {"name": "F-FB_EStop", "type": "FB", "is_safety": True},
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::Main", "type": "Block", "props": {"name": "Main", "block_type": "OB", "safety": False}},
                {
                    "id": "Block::F-FB_EStop",
                    "type": "Block",
                    "props": {"name": "F-FB_EStop", "block_type": "FB", "safety": True},
                },
                {"id": "Tag::SafeOut", "type": "Tag", "props": {"name": "SafeOut"}},
            ],
            "edges": [
                {"source": "Block::F-FB_EStop", "target": "Tag::SafeOut", "type": "WRITES"},
                {"source": "Block::Main", "target": "Tag::SafeOut", "type": "WRITES"},
            ],
        },
        "folded_logic": {},
        "scl_sources": {},
    }
    result = analyze_project(job)
    codes = {f["code"] for f in result["findings"]}
    assert "SAFETY_OUTPUTS" in codes
    assert "STANDARD_WRITES_SAFETY" in codes
    std = next(f for f in result["findings"] if f["code"] == "STANDARD_WRITES_SAFETY")
    assert std["evidence"]
