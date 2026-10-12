"""Block dossiers — per-node evidence packs with preset Q&A."""

from __future__ import annotations

from typing import Any

from agents.plc.tia.dossier import build_block_dossiers, dossier_for
from agents.plc.tia.review import run_review


def _job() -> dict[str, Any]:
    job: dict[str, Any] = {
        "blocks": [
            {
                "name": "MotorFB",
                "type": "FB",
                "number": 1,
                "language": "LAD",
                "comment": "motor control",
                "instance_of": None,
                "protected": False,
                "interface_only": False,
                "body_available": True,
                "is_safety": False,
                "nest_depth": 0,
                "members": ["Speed : Int"],
            },
            {
                "name": "Main",
                "type": "OB",
                "number": 1,
                "language": "LAD",
                "members": [],
            },
        ],
        "folded_logic": {
            "MotorFB": [
                {
                    "network_id": "3",
                    "statements": [
                        {
                            "target": '"Motor"',
                            "kind": "coil",
                            "value": {"type": "ref", "name": '"Start"'},
                        }
                    ],
                }
            ]
        },
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::MotorFB", "type": "Block"},
                {"id": "Block::Main", "type": "Block"},
                {"id": "Block::MotorDB", "type": "Block"},
                {"id": 'Tag::"Start"', "type": "Tag"},
                {"id": 'Tag::"Motor"', "type": "Tag"},
            ],
            "edges": [
                {"source": "Block::Main", "target": "Block::MotorFB", "type": "CALLS"},
                {"source": "Block::MotorFB", "target": 'Tag::"Start"', "type": "READS"},
                {"source": "Block::MotorFB", "target": 'Tag::"Motor"', "type": "WRITES"},
                {"source": "Block::MotorDB", "target": "Block::MotorFB", "type": "INSTANCE_OF"},
            ],
        },
        "scl_sources": {"MotorFB": 'FUNCTION_BLOCK "MotorFB" (* TODO[X] *)'},
    }
    job["review"] = run_review(job)
    return job


def test_dossier_identity_and_relations() -> None:
    dossiers = build_block_dossiers(_job())["blocks"]
    motor = dossiers["MotorFB"]
    assert motor["identity"]["name"] == "MotorFB"
    assert motor["identity"]["type"] == "FB"
    assert motor["callers"] == ["Main"]
    assert motor["reads"] == ['"Start"']
    assert motor["writes"] == ['"Motor"']
    assert motor["instances"] == ["MotorDB"]


def test_dossier_logic_summary_and_sample() -> None:
    dossiers = build_block_dossiers(_job())["blocks"]
    motor = dossiers["MotorFB"]
    assert motor["logic"]["networks"] == 1
    assert motor["logic"]["statements"] == 1
    assert motor["logic"]["scl_todo_comments"] == 1
    assert motor["sample_scl"]  # folded statement rendered as SCL line


def test_dossier_preset_questions_cite_evidence() -> None:
    dossiers = build_block_dossiers(_job())["blocks"]
    motor = dossiers["MotorFB"]
    questions = motor["questions"]
    assert len(questions) >= 5
    joined = "\n".join(q["q"] for q in questions)
    assert "谁调用" in joined
    assert "读/写哪些信号" in joined
    assert "完整翻译" in joined
    assert "实例" in joined  # FB-only question
    for question in questions:
        assert question["a"]
        assert question["evidence"]
    ob = dossiers["Main"]
    assert not any("实例" in q["q"] for q in ob["questions"])  # OB gets no instance Q


def test_dossier_review_hits_attached() -> None:
    job = _job()
    # Motor tag is written but never read → orphan finding tied to the writer block
    dossiers = build_block_dossiers(job)["blocks"]
    assert dossiers["MotorFB"]["review"]


def test_dossier_for_on_demand() -> None:
    job = _job()
    assert dossier_for(job, "MotorFB")["identity"]["name"] == "MotorFB"
    assert dossier_for(job, "NoSuchBlock") is None
    # stored dossiers are reused, not rebuilt
    stored = {"blocks": {"MotorFB": {"identity": {"name": "cached"}}}}
    assert dossier_for({**job, "dossiers": stored}, "MotorFB")["identity"]["name"] == "cached"
