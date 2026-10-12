"""M3 citation contract — block + locator + snippet; never invent missing bodies."""

from __future__ import annotations

from gateway.app.services.plc.citations import (
    NOT_EXPORTED,
    citations_for_block,
    finalize_grounded_answer,
    is_not_exported_or_indexed,
    normalize_citation,
)
from gateway.app.services.plc.handover import format_hitl_adjust_answer
from gateway.app.services.plc_jobs import answer_block_chat


def _job() -> dict:
    return {
        "id": "plc_cite",
        "project_name": "MotorDemo",
        "blocks": [
            {
                "name": "Main",
                "type": "OB",
                "number": 1,
                "language": "LAD",
                "networks": 1,
                "comment": "Cyclic main",
                "body_available": True,
                "export_status": "converted",
            },
            {
                "name": "FB_Locked",
                "type": "FB",
                "networks": 0,
                "interface_only": True,
                "body_available": False,
                "comment": "vendor lib",
            },
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::Main", "type": "Block", "props": {"name": "Main"}},
                {
                    "id": "Block::FB_Locked",
                    "type": "Block",
                    "props": {"name": "FB_Locked", "interface_only": True},
                },
            ],
            "edges": [
                {
                    "source": "Block::Main",
                    "target": "Block::FB_Locked",
                    "type": "CALLS",
                    "props": {"network": "Network::Main::10", "evidence": "xml_call"},
                }
            ],
        },
        "scl_sources": {
            "Main": 'ORGANIZATION_BLOCK "Main"\nBEGIN\n    #Lib();\nEND_ORGANIZATION_BLOCK',
        },
        "folded_logic": {},
        "chat": [],
    }


def test_normalize_citation_requires_locator_fields():
    c = normalize_citation(
        {"block": "Main", "network": "Network 10", "snippet": "#Lib();", "line": 3}
    )
    assert c["block"] == "Main"
    assert c["locator"]
    assert c["snippet"]
    assert c["source_status"]


def test_citations_for_exported_block_include_snippet():
    cites = citations_for_block(_job(), "Main")
    assert cites
    assert cites[0]["block"] == "Main"
    assert cites[0]["locator"] or cites[0]["network"]
    assert "#Lib" in (cites[0].get("snippet") or "") or cites[0]["locator"]


def test_locked_block_is_not_exported():
    job = _job()
    assert is_not_exported_or_indexed(job, "FB_Locked") is True
    text = finalize_grounded_answer(job, "这个块干什么", "FB_Locked", "接口开放")
    assert NOT_EXPORTED in text
    assert job["_last_citations"]
    assert job["_last_citations"][0]["source_status"] == NOT_EXPORTED


def test_answer_locked_block_forbids_invented_logic():
    job = _job()
    text = answer_block_chat(job, "@FB_Locked 请描述功能", "FB_Locked")
    assert NOT_EXPORTED in text
    cites = job.get("_last_citations") or []
    assert cites
    assert any(c.get("block") for c in cites)


def test_empty_retrieval_does_not_invent():
    job = {"id": "empty", "blocks": [], "knowledge_graph": {"nodes": [], "edges": []}, "scl_sources": {}}
    text = finalize_grounded_answer(job, "这段逻辑怎么跑的", None, "")
    assert NOT_EXPORTED in text
    assert job["_last_citations"]


def test_hitl_adjust_does_not_write_scl():
    text = format_hitl_adjust_answer(_job(), focus="Main")
    assert "不自动写回" in text or "不会导入" in text
    assert "确认反写" in text
    assert "优化SCL" in text
