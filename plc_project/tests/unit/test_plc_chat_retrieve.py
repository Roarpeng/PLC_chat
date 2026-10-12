"""Chat retrieve citations — extend answer_query_pack, never invent CALLs."""

from __future__ import annotations

from agents.plc.tia.chat_retrieve import answer_query_pack, citations_for_retrieval, retrieve_kg_for_query


def _job() -> dict:
    return {
        "project_name": "MotorDemo",
        "summary": {"FB": 1, "OB": 1},
        "blocks": [
            {"name": "Main", "type": "OB", "number": 1, "language": "LAD", "networks": 1, "comment": "Cyclic main"},
            {
                "name": "FB_Motor",
                "type": "FB",
                "number": 100,
                "language": "LAD",
                "networks": 1,
                "comment": "self-holding motor",
                "is_safety": False,
            },
        ],
        "knowledge_graph": {
            "nodes": [
                {"id": "Block::Main", "type": "Block", "props": {"name": "Main"}},
                {"id": "Block::FB_Motor", "type": "Block", "props": {"name": "FB_Motor"}},
                {"id": "Tag::Running", "type": "Tag", "props": {"name": "Running"}},
            ],
            "edges": [
                {
                    "source": "Block::Main",
                    "target": "Block::FB_Motor",
                    "type": "CALLS",
                    "props": {"network": "Network::Main::10", "evidence": "xml_call"},
                },
                {
                    "source": "Block::FB_Motor",
                    "target": "Tag::Running",
                    "type": "WRITES",
                    "props": {"network": "Network::FB_Motor::10", "evidence": "coil"},
                },
                {"source": "Block::FB_Motor", "target": "Tag::Running", "type": "READS"},
            ],
        },
        "scl_sources": {
            "FB_Motor": 'FUNCTION_BLOCK "FB_Motor"\nBEGIN\n    #Running := ((#Start OR #Running) AND NOT (#Stop));\nEND_FUNCTION_BLOCK',
            "Main": 'ORGANIZATION_BLOCK "Main"\nBEGIN\n    #MotorInst(Start := "HMI".StartCmd);\nEND_ORGANIZATION_BLOCK',
        },
        "folded_logic": {
            "FB_Motor": [{"title": "Self-holding motor start", "statements": []}],
        },
    }


def test_retrieve_writes_hits_coil_not_invented_calls():
    retrieval = retrieve_kg_for_query(_job(), "who writes Running coil")
    names = [h["name"] for h in retrieval["hits"]]
    assert "FB_Motor" in names
    citations = retrieval["citations"]
    assert any(c.get("edge_type") == "WRITES" and "Running" in str(c.get("target")) for c in citations)
    assert all(c.get("edge_type") != "INVENTED" for c in citations)


def test_answer_query_pack_returns_citations():
    pack = answer_query_pack(_job(), "Main 调用了谁？")
    assert pack["content"]
    assert pack["citations"]
    assert any(c.get("edge_type") == "CALLS" for c in pack["citations"])
    assert "证据" in pack["content"] or "CALLS" in pack["content"]


def test_empty_hits_say_not_exported():
    job = {
        "project_name": "Empty",
        "blocks": [],
        "knowledge_graph": {"nodes": [], "edges": []},
        "scl_sources": {},
    }
    pack = answer_query_pack(job, "主循环怎么跑？")
    assert "未导出/未索引" in pack["content"]


def test_citations_for_retrieval_include_scl_snippet():
    job = _job()
    retrieval = retrieve_kg_for_query(job, "FB_Motor 自锁")
    cites = citations_for_retrieval(job, retrieval)
    motor = [c for c in cites if c.get("block") == "FB_Motor"]
    assert motor
    assert any("#Running" in str(c.get("snippet") or "") for c in motor)
