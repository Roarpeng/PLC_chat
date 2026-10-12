"""Deterministic review rules — folded logic + KG edges in, findings out."""

from __future__ import annotations

from typing import Any

from agents.plc.tia.review import format_review_markdown, run_review


def _stmt(target: str, kind: str, *, enable: Any = None) -> dict[str, Any]:
    statement: dict[str, Any] = {
        "target": target,
        "kind": kind,
        "value": {"type": "ref", "name": "Cond"},
    }
    if enable is not None:
        statement["enable"] = enable
    return statement


def _job() -> dict[str, Any]:
    return {
        "blocks": [
            {
                "name": "MotorCtrl",
                "type": "FC",
                "members": ["UnusedVar : Bool", "UsedVar : Bool"],
                "body_available": True,
                "protected": False,
                "interface_only": False,
            },
            {
                "name": "AuxCtrl",
                "type": "FC",
                "members": [],
                "body_available": True,
                "protected": False,
                "interface_only": False,
            },
        ],
        "folded_logic": {
            "MotorCtrl": [
                {"network_id": "1", "statements": [_stmt('"Motor"', "coil")]},
                {"network_id": "2", "statements": [_stmt('"Motor"', "coil")]},
                {"network_id": "3", "statements": [_stmt('"Latch"', "set")]},
            ],
            "AuxCtrl": [
                {
                    "network_id": "1",
                    "statements": [
                        _stmt('"Motor"', "move"),
                        _stmt('"Guarded"', "coil", enable={"type": "lit"}),
                    ],
                },
            ],
        },
        "knowledge_graph": {
            "nodes": [
                {"id": 'Tag::"Motor"', "type": "Tag"},
                {"id": 'Tag::"Latch"', "type": "Tag"},
                {"id": 'Tag::"Start"', "type": "Tag"},
            ],
            "edges": [
                {"source": "Block::MotorCtrl", "target": 'Tag::"Motor"', "type": "WRITES"},
                {"source": "Block::AuxCtrl", "target": 'Tag::"Motor"', "type": "WRITES"},
                {"source": "Block::MotorCtrl", "target": 'Tag::"Latch"', "type": "WRITES"},
                {"source": "Block::MotorCtrl", "target": 'Tag::"Start"', "type": "READS"},
            ],
        },
        "scl_sources": {"MotorCtrl": "#UsedVar := TRUE;"},
    }


def _rules(result: dict[str, Any]) -> set[str]:
    return {str(f.get("rule")) for f in result.get("findings") or []}


def test_review_finds_double_write() -> None:
    result = run_review(_job())
    doubles = [
        f
        for f in result["findings"]
        if f["rule"] == "double_write" and f.get("block") == "MotorCtrl"
    ]
    assert doubles, result
    assert doubles[0]["severity"] == "warning"
    assert doubles[0]["target"] == '"Motor"'
    assert {e["network_id"] for e in doubles[0]["evidence"]} == {"1", "2"}


def test_review_guarded_write_not_flagged() -> None:
    result = run_review(_job())
    # "Guarded" has an enable → never a double/multi write finding
    assert not [
        f for f in result["findings"] if f.get("target") == '"Guarded"'
    ]


def test_review_multi_block_write() -> None:
    result = run_review(_job())
    multi = [f for f in result["findings"] if f["rule"] == "multi_block_write"]
    assert multi
    assert set(multi[0]["blocks"]) == {"MotorCtrl", "AuxCtrl"}


def test_review_set_reset_unpaired() -> None:
    result = run_review(_job())
    unpaired = [f for f in result["findings"] if f["rule"] == "set_reset_unpaired"]
    assert unpaired and unpaired[0]["target"] == '"Latch"'


def test_review_orphan_tags() -> None:
    result = run_review(_job())
    targets = {f.get("target"): f["rule"] for f in result["findings"]}
    assert targets.get('"Motor"') == "tag_write_never_read"
    assert targets.get('"Latch"') == "tag_write_never_read"
    assert targets.get('"Start"') == "tag_read_never_written"


def test_review_unused_member() -> None:
    result = run_review(_job())
    unused = [
        f
        for f in result["findings"]
        if f["rule"] == "unused_member" and f.get("block") == "MotorCtrl"
    ]
    assert unused
    assert unused[0]["evidence"][0]["members"] == ["UnusedVar"]


def test_review_summary_and_markdown() -> None:
    result = run_review(_job())
    summary = result["summary"]
    assert summary["total"] == len(result["findings"])
    assert summary["warning"] + summary["info"] == summary["total"]
    markdown = format_review_markdown(result)
    assert "## 确定性审查" in markdown
    assert "double_write" in markdown
