"""S7-GRAPH → executable CASE state-machine SCL rebuild."""

from __future__ import annotations

from agents.plc.tia.graph_scl import (
    graph_network_to_scl,
    graph_state_var_name,
    graph_unresolved_count,
    has_graph_sequence,
)
from agents.plc.tia.ir import (
    Block,
    BlockType,
    GraphStep,
    GraphTransition,
    Network,
)
from agents.plc.tia.scl import translate_block_to_scl


def _graph_block() -> Block:
    block = Block(name="Seq", number=7, block_type=BlockType.FB, programming_language="GRAPH")
    network = Network(id="4", title="sequence", programming_language="GRAPH")
    network.graph_steps = [
        GraphStep(
            name="Init",
            number=1,
            actions=["'Motor' := FALSE"],
            comment="homing",
            interlock="\"EStop\" = FALSE",
        ),
        GraphStep(name="Run", number=2, actions=["'Motor' := TRUE"]),
        GraphStep(name="Done", number=3),
    ]
    network.graph_transitions = [
        GraphTransition(name="T1", source_step="Init", target_step="Run", condition='"Start"'),
        GraphTransition(
            name="T2", source_step="Run", target_step="Done", condition='"Busy" = FALSE'
        ),
        GraphTransition(name="T3", source_step="Run", target_step="Ghost", condition='"X"'),
        GraphTransition(name="T4", source_step="Run", target_step="Done", condition=""),
    ]
    block.networks = [network]
    return block


def test_has_graph_sequence_and_naming() -> None:
    network = Network(id="1")
    assert not has_graph_sequence(network)
    network.graph_steps = [GraphStep(name="S1")]
    assert has_graph_sequence(network)
    assert graph_state_var_name(1) == "GraphStep"
    assert graph_state_var_name(3) == "GraphStep3"


def test_graph_network_to_scl_builds_case_machine() -> None:
    network = _graph_block().networks[0]
    lines = graph_network_to_scl(network, "GraphStep")
    assert lines is not None
    text = "\n".join(lines)
    assert "IF #GraphStep = 0 THEN" in text
    assert "#GraphStep := 1;  // init → Init" in text
    assert "CASE #GraphStep OF" in text
    assert 'IF ("Start") THEN' in text
    assert "#GraphStep := 2;" in text
    assert "END_CASE;" in text
    # unresolved transition target and empty condition surface as TODO
    assert "TODO[graph_target]" in text
    assert "TODO[graph_condition]" in text
    # interlock / supervision stay comments — never invented as code
    assert '// Interlock: "EStop" = FALSE' in text
    # action tokens stay comments
    assert "// 动作: 'Motor' := FALSE" in text


def test_graph_unresolved_count() -> None:
    network = _graph_block().networks[0]
    assert graph_unresolved_count(network) == 2  # unknown target + empty condition


def test_translate_block_injects_state_var_and_case() -> None:
    scl = translate_block_to_scl(_graph_block())
    assert "GraphStep : Int" in scl  # STATIC injection
    assert "CASE #GraphStep OF" in scl
    assert "FUNCTION_BLOCK" in scl
    assert "END_FUNCTION_BLOCK" in scl


def test_two_graph_networks_get_distinct_state_vars() -> None:
    block = _graph_block()
    second = Network(id="9", programming_language="GRAPH")
    second.graph_steps = [GraphStep(name="A", number=1), GraphStep(name="B", number=2)]
    second.graph_transitions = [
        GraphTransition(name="T", source_step="A", target_step="B", condition="TRUE")
    ]
    block.networks.append(second)
    scl = translate_block_to_scl(block)
    assert "GraphStep : Int" in scl
    assert "GraphStep2 : Int" in scl
    assert "CASE #GraphStep2 OF" in scl


def test_no_steps_returns_none() -> None:
    network = Network(id="1", programming_language="GRAPH")
    assert graph_network_to_scl(network, "GraphStep") is None
