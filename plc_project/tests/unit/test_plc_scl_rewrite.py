"""Unit tests — importable SCL rewrite + safety/protected refuse."""

from __future__ import annotations

from agents.plc.tia.flgnet_fold import attach_folded
from agents.plc.tia.ir import (
    Access,
    AccessScope,
    Block,
    BlockType,
    InterfaceSection,
    Network,
    Part,
    PlcProject,
    Variable,
    Wire,
    WireEndpoint,
)
from agents.plc.tia.scl import convert_project_to_scl
from agents.plc.tia.scl_rewrite import (
    SKIP_PROTECTED,
    SKIP_SAFETY,
    convert_project_to_importable_scl,
    refuse_body_write_reason,
    rewrite_block_to_importable_scl,
    rewrite_job_to_importable_scl,
)


def _folded_lad_hold() -> Block:
    """Small LAD self-hold: Start OR Running, AND NOT Stop → Running coil."""
    start = Access(scope=AccessScope.LOCAL, root="Start")
    running = Access(scope=AccessScope.LOCAL, root="Running")
    stop = Access(scope=AccessScope.LOCAL, root="Stop")
    return Block(
        name="FB_Hold",
        number=10,
        block_type=BlockType.FB,
        programming_language="LAD",
        interface=[
            Variable(name="Start", section=InterfaceSection.INPUT, data_type="Bool"),
            Variable(name="Stop", section=InterfaceSection.INPUT, data_type="Bool"),
            Variable(name="Running", section=InterfaceSection.OUTPUT, data_type="Bool"),
        ],
        networks=[
            Network(
                id="1",
                title="self hold",
                programming_language="LAD",
                parts={
                    "31": Part(name="Contact", part_type="Contact", uuid="31"),
                    "32": Part(name="Contact", part_type="Contact", uuid="32"),
                    "33": Part(name="NegContact", part_type="Contact", uuid="33"),
                    "35": Part(name="Coil", part_type="Coil", uuid="35"),
                },
                access_parts={"21": start, "22": running, "23": stop, "25": running},
                wires=[
                    Wire(
                        "w1",
                        [
                            WireEndpoint("powerrail"),
                            WireEndpoint("namecon", "31", "in"),
                            WireEndpoint("namecon", "32", "in"),
                        ],
                    ),
                    Wire(
                        "w2",
                        [
                            WireEndpoint("identcon", "21"),
                            WireEndpoint("namecon", "31", "operand"),
                        ],
                    ),
                    Wire(
                        "w3",
                        [
                            WireEndpoint("identcon", "22"),
                            WireEndpoint("namecon", "32", "operand"),
                        ],
                    ),
                    Wire(
                        "w4",
                        [
                            WireEndpoint("namecon", "31", "out"),
                            WireEndpoint("namecon", "32", "out"),
                            WireEndpoint("namecon", "33", "in"),
                        ],
                    ),
                    Wire(
                        "w5",
                        [
                            WireEndpoint("identcon", "23"),
                            WireEndpoint("namecon", "33", "operand"),
                        ],
                    ),
                    Wire(
                        "w6",
                        [
                            WireEndpoint("namecon", "33", "out"),
                            WireEndpoint("namecon", "35", "in"),
                        ],
                    ),
                    Wire(
                        "w7",
                        [
                            WireEndpoint("identcon", "25"),
                            WireEndpoint("namecon", "35", "operand"),
                        ],
                    ),
                ],
            )
        ],
    )


def test_rewrite_folded_lad_to_importable_scl():
    block = _folded_lad_hold()
    project = PlcProject(name="LadDemo")
    project.add_block(block)
    attach_folded(project)
    scl = rewrite_block_to_importable_scl(project.blocks["FB_Hold"])
    assert 'FUNCTION_BLOCK "FB_Hold"' in scl
    assert "VAR_INPUT" in scl
    assert "Start" in scl and "Running" in scl
    assert "END_FUNCTION_BLOCK" in scl
    assert "BEGIN" in scl
    # Honest translation — coil assignment or IF form, not silently empty
    assert ":=" in scl or "IF " in scl


def test_convert_project_skips_safety_and_protected():
    open_b = Block(
        name="FB_Open",
        block_type=BlockType.FB,
        programming_language="SCL",
        source_text="A := B;",
    )
    secret = Block(
        name="FB_Secret",
        block_type=BlockType.FB,
        programming_language="LAD",
        attributes={"KnowHowProtection": "true"},
        source_text="should not emit",
    )
    safety = Block(
        name="F-FB_EStop",
        block_type=BlockType.FB,
        programming_language="F-LAD",
        is_safety=True,
        source_text="Q := I;",
        networks=[Network(id="1", source_text="Q := I;")],
    )
    project = PlcProject(name="SkipDemo")
    project.add_block(open_b)
    project.add_block(secret)
    project.add_block(safety)

    scl = convert_project_to_scl(project)
    assert "FB_Open" in scl
    assert "FB_Secret" not in scl
    assert "F-FB_EStop" not in scl

    result = convert_project_to_importable_scl(project)
    reasons = {s.block_name: s.reason for s in result.skipped}
    assert reasons["FB_Secret"] == SKIP_PROTECTED
    assert reasons["F-FB_EStop"] == SKIP_SAFETY
    assert "FB_Open" in result.files
    assert "F-FB_EStop" not in result.files


def test_refuse_body_write_job_metadata():
    assert refuse_body_write_reason({"name": "F-FB_X", "is_safety": True}) == SKIP_SAFETY
    assert refuse_body_write_reason({"name": "FB_L", "protected": True}) == SKIP_PROTECTED
    assert refuse_body_write_reason({"name": "FB_I", "interface_only": True}) == "interface_only"
    assert refuse_body_write_reason({"name": "FB_N", "body_available": False}) == "no_body"
    assert refuse_body_write_reason({"name": "FB_Ok", "body_available": True}) is None


def test_rewrite_job_refuses_safety_without_xml():
    job = {
        "blocks": [
            {"name": "F-FB_EStop", "type": "FB", "is_safety": True, "body_available": True},
            {"name": "FB_Motor", "type": "FB", "body_available": True},
        ],
        "scl_sources": {
            "F-FB_EStop": 'FUNCTION_BLOCK "F-FB_EStop"\nBEGIN\nEND_FUNCTION_BLOCK',
            "FB_Motor": 'FUNCTION_BLOCK "FB_Motor"\nVAR_INPUT\n    Start : Bool;\nEND_VAR\nBEGIN\n    #Q := #Start;\nEND_FUNCTION_BLOCK\n',
        },
        "source_xmls": [],
    }
    result = rewrite_job_to_importable_scl(job)
    skipped = {s.block_name: s.reason for s in result.skipped}
    assert skipped["F-FB_EStop"] == SKIP_SAFETY
    assert "FB_Motor" in result.files
    assert "F-FB_EStop" not in result.files
    assert any(d.block_name == "FB_Motor" and d.unified_diff for d in result.diffs)
