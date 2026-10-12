"""Logic graph = scan cycle; knowledge canvas = implementation deps."""

from __future__ import annotations

from gateway.app.services.knowledge_extract import edges_from_plc_logic, nodes_from_plc_job
from gateway.app.services.plc_jobs import _logic_graph_from_kg, refresh_logic_graph


def _sample_kg() -> dict:
    return {
        "nodes": [
            {"id": "Block::Main", "type": "Block", "props": {"name": "Main", "block_type": "OB"}},
            {"id": "Block::ce", "type": "Block", "props": {"name": "ce", "block_type": "FC"}},
            {"id": "Block::dc", "type": "Block", "props": {"name": "dc", "block_type": "FB"}},
            {"id": "Block::dc_DB", "type": "Block", "props": {"name": "dc_DB", "block_type": "DB"}},
            {"id": "Block::ceD", "type": "Block", "props": {"name": "ceD", "block_type": "DB"}},
            {"id": "Tag::ceD.x", "type": "Tag", "props": {"name": "ceD.x"}},
        ],
        "edges": [
            {"source": "Block::Main", "target": "Block::ce", "type": "CALLS", "seq": 1},
            {"source": "Block::ce", "target": "Block::dc", "type": "CALLS", "seq": 1},
            {"source": "Block::Main", "target": "Block::ceD", "type": "USES"},
            {"source": "Block::ce", "target": "Block::dc_DB", "type": "USES"},
            {"source": "Block::dc_DB", "target": "Block::dc", "type": "INSTANCE_OF"},
            {"source": "Block::Main", "target": "Tag::ceD.x", "type": "READS"},
        ],
    }


def test_logic_graph_only_ob_scan_cycle_calls():
    lg = _logic_graph_from_kg(_sample_kg())
    types = {e["type"] for e in lg["edges"]}
    assert "CALLS" in types
    assert "NEXT" in types or len([e for e in lg["edges"] if e["type"] == "CALLS"]) >= 1
    assert "USES" not in types
    assert "INSTANCE_OF" not in types
    assert "DEPENDS_ON" not in types
    pairs = {(e["source"].split("::")[-1], e["target"].split("::")[-1], e["type"]) for e in lg["edges"]}
    assert ("Main", "ce", "CALLS") in pairs
    # Nested FC→FB CALLS must NOT appear on logic graph
    assert ("ce", "dc", "CALLS") not in pairs
    labels = {n["label"] for n in lg["nodes"]}
    assert "Main" in labels and "ce" in labels
    assert "dc" not in labels  # internal callee only on knowledge graph


def test_knowledge_canvas_edges_include_calls_uses_instance():
    job = {
        "id": "plc_test",
        "project_name": "Demo",
        "blocks": [
            {"name": "Main", "type": "OB", "networks": 1},
            {"name": "ce", "type": "FC", "networks": 4},
            {"name": "dc", "type": "FB", "networks": 3},
            {"name": "dc_DB", "type": "DB", "networks": 0, "instance_of": "dc"},
            {"name": "ceD", "type": "DB", "networks": 0},
        ],
        "knowledge_graph": _sample_kg(),
        "logic_graph": {"nodes": [], "edges": []},
    }
    plc_nodes = nodes_from_plc_job(job, task_id="t1", turn_id="u1")
    edges = edges_from_plc_logic(job, plc_nodes)
    labels = {(e["label"], ) for e in edges}
    kinds = {e["label"] for e in edges}
    assert "CALLS" in kinds
    assert "USES" in kinds
    assert "INSTANCE_OF" in kinds
    # Map canvas ids back via labels
    by_id = {n["id"]: n["label"] for n in plc_nodes}
    pairs = {
        (by_id.get(e["source"]), by_id.get(e["target"]), e["label"]) for e in edges
    }
    assert ("Main", "ce", "CALLS") in pairs
    assert ("ce", "dc", "CALLS") in pairs
    assert ("Main", "ceD", "USES") in pairs
    assert ("dc_DB", "dc", "INSTANCE_OF") in pairs


def test_refresh_logic_graph_scan_only():
    job = {
        "knowledge_graph": _sample_kg(),
        "logic_graph": {"nodes": [], "edges": [{"type": "CONTAINS"}]},
        "blocks": [{"name": "Main"}, {"name": "ce"}],
    }
    refresh_logic_graph(job)
    types = {e["type"] for e in job["logic_graph"]["edges"]}
    assert "CONTAINS" not in types
    assert "CALLS" in types
    assert "USES" not in types
