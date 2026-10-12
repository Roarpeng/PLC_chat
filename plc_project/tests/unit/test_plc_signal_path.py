"""Signal-path tracing across the KG (sensor → logic chain → actuator)."""

from __future__ import annotations

import pytest

from agents.plc.tia.graph_query import query, resolve_kg_node, signal_paths


def _kg() -> dict:
    return {
        "nodes": [
            {"id": 'Tag::"DoorClosed"', "type": "Tag"},
            {"id": "Block::SafetyFB", "type": "Block"},
            {"id": "Block::Main", "type": "Block"},
            {"id": "Block::MotorCtrl", "type": "Block"},
            {"id": 'Tag::"MotorEnable"', "type": "Tag"},
        ],
        "edges": [
            {"source": "Block::SafetyFB", "target": 'Tag::"DoorClosed"', "type": "READS"},
            {"source": "Block::Main", "target": "Block::SafetyFB", "type": "CALLS"},
            {"source": "Block::Main", "target": "Block::MotorCtrl", "type": "CALLS"},
            {"source": "Block::MotorCtrl", "target": 'Tag::"MotorEnable"', "type": "WRITES"},
        ],
    }


def test_resolve_node_exact_and_tail_match() -> None:
    kg = _kg()
    assert resolve_kg_node(kg, "Main") == "Block::Main"
    assert resolve_kg_node(kg, "DoorClosed") == 'Tag::"DoorClosed"'
    # full reference and quoted tail both resolve
    assert resolve_kg_node(kg, '"PLCTable"."DoorClosed"'.split(".")[-1]) == 'Tag::"DoorClosed"'
    assert resolve_kg_node(kg, "Missing") is None


def test_signal_path_sensor_to_actuator() -> None:
    result = signal_paths(_kg(), "DoorClosed", "MotorEnable")
    assert result["paths"], result
    path = result["paths"][0]
    assert path["hops"] == 4  # SafetyFB -> Main -> MotorCtrl -> Tag
    labels = path["nodes"]
    assert labels[0] == '"DoorClosed"'
    assert labels[-1] == '"MotorEnable"'
    assert "Main" in labels
    edge_types = [edge["type"] for edge in path["edges"]]
    assert edge_types == ["READS", "CALLS", "CALLS", "WRITES"]
    assert "-[READS]->" in path["sequence"]
    assert "-[WRITES]->" in path["sequence"]


def test_signal_path_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        signal_paths(_kg(), "Nope", "Main")
    with pytest.raises(ValueError):
        signal_paths(_kg(), "Main", "Main")


def test_query_op_dispatch() -> None:
    payload = query(_kg(), "signal_path", source="DoorClosed", target="MotorEnable")
    assert payload["op"] == "signal_path"
    assert payload["result"]["paths"]
    # evidence = the edges along every returned path
    assert {"READS", "CALLS", "WRITES"} <= {e["type"] for e in payload["evidence"]}


def test_query_op_signal_path_bad_params_raise() -> None:
    with pytest.raises(ValueError):
        query(_kg(), "signal_path", source="Ghost", target="Main")
