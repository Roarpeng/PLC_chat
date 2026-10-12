"""Unit tests — PLC change-set propose / KG apply / import bundle."""

from __future__ import annotations

import json
from pathlib import Path

from agents.plc.tia.changeset import (
    PlcChangeOp,
    PlcChangeSet,
    apply_changeset_to_kg,
    propose_changeset_from_message,
    write_import_bundle,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tia_exports"
FB_MOTOR_XML = FIXTURES / "Blocks" / "FB_Motor.xml"


def test_propose_comment_heuristic():
    cs = propose_changeset_from_message(
        "请添加注释: 电机自保持启动逻辑",
        block_name="FB_Motor",
    )
    assert cs.status == "proposed"
    assert len(cs.ops) == 1
    assert cs.ops[0].kind == "set_block_comment"
    assert cs.ops[0].payload["block_name"] == "FB_Motor"
    assert "电机自保持" in cs.ops[0].payload["comment"]


def test_propose_depends_heuristic():
    cs = propose_changeset_from_message(
        "FB_Motor depends on FC_Safety",
        block_name="FB_Motor",
    )
    assert any(o.kind == "add_edge" for o in cs.ops)
    edge = next(o for o in cs.ops if o.kind == "add_edge")
    assert edge.payload["source"] == "Block::FB_Motor"
    assert edge.payload["target"] == "Block::FC_Safety"
    assert edge.payload["type"] == "DEPENDS_ON"


def test_propose_import_xml_heuristic():
    cs = propose_changeset_from_message(
        f"导入 xml {FB_MOTOR_XML}",
        block_name="FB_Motor",
    )
    assert any(o.kind == "stage_xml_import" for o in cs.ops)
    op = next(o for o in cs.ops if o.kind == "stage_xml_import")
    assert op.payload["xml_path"].endswith("FB_Motor.xml")


def test_apply_changeset_to_kg_comment_and_edge():
    kg = {
        "nodes": [
            {
                "id": "Block::FB_Motor",
                "type": "Block",
                "props": {"name": "FB_Motor", "comment": "old"},
            }
        ],
        "edges": [],
    }
    cs = PlcChangeSet(
        id="test1",
        ops=[
            PlcChangeOp(
                kind="set_block_comment",
                payload={"block_name": "FB_Motor", "comment": "updated note"},
            ),
            PlcChangeOp(
                kind="add_edge",
                payload={
                    "source": "Block::FB_Motor",
                    "target": "Block::FC_Safety",
                    "type": "DEPENDS_ON",
                },
            ),
            PlcChangeOp(
                kind="set_node_prop",
                payload={
                    "node_id": "Block::FB_Motor",
                    "prop": "language",
                    "value": "LAD",
                },
            ),
        ],
        status="accepted",
    )
    out = apply_changeset_to_kg(kg, cs)
    assert kg["nodes"][0]["props"]["comment"] == "old"  # original untouched
    node = next(n for n in out["nodes"] if n["id"] == "Block::FB_Motor")
    assert node["props"]["comment"] == "updated note"
    assert node["props"]["language"] == "LAD"
    assert out["edges"] == [
        {
            "source": "Block::FB_Motor",
            "target": "Block::FC_Safety",
            "type": "DEPENDS_ON",
            "props": {},
        }
    ]


def test_apply_remove_edge_and_annotate():
    kg = {
        "nodes": [
            {"id": "Block::A", "type": "Block", "props": {"name": "A"}},
            {"id": "Block::B", "type": "Block", "props": {"name": "B"}},
        ],
        "edges": [
            {"source": "Block::A", "target": "Block::B", "type": "DEPENDS_ON", "props": {}},
            {"source": "Block::A", "target": "Block::B", "type": "CALLS", "props": {}},
        ],
    }
    cs = PlcChangeSet(
        id="test2",
        ops=[
            PlcChangeOp(
                kind="remove_edge",
                payload={
                    "source": "Block::A",
                    "target": "Block::B",
                    "type": "DEPENDS_ON",
                },
            ),
            PlcChangeOp(
                kind="annotate",
                payload={"block_name": "A", "text": "reviewed"},
            ),
        ],
    )
    out = apply_changeset_to_kg(kg, cs)
    assert len(out["edges"]) == 1
    assert out["edges"][0]["type"] == "CALLS"
    a = next(n for n in out["nodes"] if n["id"] == "Block::A")
    assert a["props"]["annotations"] == ["reviewed"]


def test_write_import_bundle(tmp_path: Path):
    assert FB_MOTOR_XML.is_file()
    cs = propose_changeset_from_message(
        "注释: MVP sidecar comment",
        block_name="FB_Motor",
    )
    staged = write_import_bundle(tmp_path / "import_bundle", cs, [FB_MOTOR_XML])
    assert len(staged) == 1
    assert staged[0].name == "FB_Motor.xml"
    assert staged[0].is_file()

    bundle = tmp_path / "import_bundle"
    assert (bundle / "changeset.json").is_file()
    assert (bundle / "comments.json").is_file()
    assert (bundle / "staged_xmls.json").is_file()

    meta = json.loads((bundle / "changeset.json").read_text(encoding="utf-8"))
    assert meta["ops"][0]["kind"] == "set_block_comment"
    comments = json.loads((bundle / "comments.json").read_text(encoding="utf-8"))
    assert comments["FB_Motor"] == "MVP sidecar comment"


def test_filter_changeset_for_focus_unit():
    from agents.plc.tia.changeset import (
        PlcChangeOp,
        PlcChangeSet,
        filter_changeset_for_focus,
    )

    cs = PlcChangeSet(
        id="f",
        ops=[
            PlcChangeOp(kind="rewrite_scl", payload={"block_name": "FB_A", "scl_text": "A"}),
            PlcChangeOp(
                kind="stage_scl_source",
                payload={"block_name": "FC_H", "scl_text": "H", "new_block": True},
            ),
            PlcChangeOp(
                kind="add_edge",
                payload={
                    "source": "Block::FB_A",
                    "target": "Block::FC_H",
                    "type": "CALLS",
                    "props": {"evidence": "decouple_extract"},
                },
            ),
            PlcChangeOp(kind="annotate", payload={"block_name": "Dead", "text": "x"}),
        ],
        notes=["optimize:decouple:FB_A->FC_H"],
    )
    focused = filter_changeset_for_focus(cs, "FB_A")
    names = {o.payload.get("block_name") for o in focused.ops if o.payload.get("block_name")}
    assert names == {"FB_A", "FC_H"}
    assert filter_changeset_for_focus(cs, "").ops == cs.ops


def test_filter_scl_diffs_for_focus_keeps_helpers():
    from agents.plc.tia.changeset import PlcChangeOp, PlcChangeSet, filter_scl_diffs_for_focus

    cs = PlcChangeSet(
        id="d",
        ops=[
            PlcChangeOp(kind="rewrite_scl", payload={"block_name": "FB_A", "scl_text": "A"}),
            PlcChangeOp(
                kind="stage_scl_source",
                payload={"block_name": "FC_H", "scl_text": "H", "new_block": True},
            ),
            PlcChangeOp(
                kind="add_edge",
                payload={
                    "source": "Block::FB_A",
                    "target": "Block::FC_H",
                    "type": "CALLS",
                    "props": {"evidence": "decouple_extract"},
                },
            ),
        ],
        notes=["optimize:decouple:FB_A->FC_H"],
    )
    diffs = [
        {"block": "FB_A", "diff": "-a\n+b\n", "after": "b"},
        {"block": "FC_H", "diff": "+new\n", "after": "new", "new_block": True},
        {"block": "Dead", "diff": "-x\n"},
    ]
    kept = filter_scl_diffs_for_focus(diffs, cs, "FB_A")
    assert [d["block"] for d in kept] == ["FB_A", "FC_H"]
    assert [d["block"] for d in filter_scl_diffs_for_focus(diffs, cs, None)] == [
        "FB_A",
        "FC_H",
        "Dead",
    ]
