"""G3: BFS reachability, Tarjan SCC, branch priority, fault paths, parallel fail-closed."""
from __future__ import annotations

from plc_engine.engineering_ir.validation import ValidationEngine
from plc_engine.process.graph_validation import (
    guards_are_provably_exclusive,
    reachable_steps,
    sccs_without_exit,
    shortest_counterexample,
    tarjan_sccs,
)
from plc_engine.process.guard_ast import guard_and, guard_not, guard_signal
from plc_engine.process.sequence_ir import Step, Transition
from tests.v2_fixtures import build_valid_demo_ir


def test_valid_demo_ir_passes_all_graph_checks() -> None:
    report = ValidationEngine().validate(build_valid_demo_ir())
    assert report.passed, report.issues


def test_bfs_reachability_marks_all_steps_reachable() -> None:
    ir = build_valid_demo_ir()
    assert reachable_steps(ir.process) == set(ir.process.step_ids())


def test_unreachable_step_is_rejected() -> None:
    ir = build_valid_demo_ir()
    ir.process.steps.append(Step(id="S_ORPHAN", name="orphan", source_id="S_ORPHAN"))
    ir.refresh_hash()
    issues = ValidationEngine().validate(ir).issues
    assert any("unreachable" in i["reason"] for i in issues)
    assert any(i["source_id"] == "S_ORPHAN" for i in issues)


def test_tarjan_scc_without_exit_is_rejected() -> None:
    ir = build_valid_demo_ir()
    # S1 <-> S2 loop with no exit edge to the rest of the graph.
    ir.process.transitions = [
        Transition(id="L1", from_step="S1", to_step="S2", guard_ast=guard_signal("A"), source_id="L1"),
        Transition(id="L2", from_step="S2", to_step="S1", guard_ast=guard_signal("B"), source_id="L2"),
        Transition(id="L3", from_step="S0", to_step="S1", guard_ast=guard_signal("C"), source_id="L3"),
    ]
    ir.process.exceptions = []
    ir.refresh_hash()
    assert any(len(c) > 1 for c in tarjan_sccs(ir.process))
    assert sccs_without_exit(ir.process)
    issues = ValidationEngine().validate(ir).issues
    assert any("non-terminating cycle" in i["reason"] for i in issues)


def test_branch_priority_or_exclusivity_proof_is_required() -> None:
    ir = build_valid_demo_ir()
    ir.process.transitions.append(
        Transition(id="T_DUP", from_step="S0", to_step="S2",
                   guard_ast=guard_signal("CmdStart"), priority=0, source_id="T_DUP")
    )
    ir.refresh_hash()
    issues = ValidationEngine().validate(ir).issues
    assert any("priority" in i["reason"] and "exclusivity" in i["reason"] for i in issues)


def test_mutually_exclusive_guards_are_proven() -> None:
    left = guard_and(guard_signal("SensorOut"), guard_not(guard_signal("Fault")))
    right = guard_and(guard_signal("SensorOut"), guard_signal("Fault"))
    assert guards_are_provably_exclusive(left, right) is True
    assert guards_are_provably_exclusive(guard_signal("A"), guard_signal("B")) is False


def test_unsupported_parallel_semantics_blocks_delivery() -> None:
    ir = build_valid_demo_ir()
    ir.process.parallel_groups = [{"id": "FORK_1", "kind": "fork", "steps": ["S1", "S3"]}]
    ir.refresh_hash()
    issues = ValidationEngine().validate(ir).issues
    assert any("UNSUPPORTED_PARALLEL_SEMANTICS" in i["reason"] for i in issues)
    assert any("FORK_1" in i.get("node_ids", []) for i in issues)


def test_missing_exception_path_is_rejected() -> None:
    ir = build_valid_demo_ir()
    ir.process.exceptions = []
    for step in ir.process.steps:
        step.failure_target = ""
    ir.refresh_hash()
    issues = ValidationEngine().validate(ir).issues
    assert any("FAULT / exception path" in i["reason"] for i in issues)
    assert any("timeout" in i["reason"] for i in issues)


def test_double_coil_in_one_step_is_rejected() -> None:
    from plc_engine.process.sequence_ir import Action

    ir = build_valid_demo_ir()
    ir.process.step_index()["S1"].entry_actions.append(
        Action(id="A_REVERSE", target_component_id="CM1", command="CmdRetract", value=True, source_id="S1")
    )
    ir.refresh_hash()
    issues = ValidationEngine().validate(ir).issues
    assert any("reverse_outputs_interlocked" in i["reason"] for i in issues)


def test_shortest_counterexample_points_at_fault() -> None:
    ir = build_valid_demo_ir()
    path = shortest_counterexample(ir)
    assert path
    assert path[-1] == "FAULT"
    assert path[0] == ir.process.initial_step


def test_illegal_guard_type_is_rejected() -> None:
    from plc_engine.process.guard_ast import GuardAST, GuardNodeType, GuardValueType

    ir = build_valid_demo_ir()
    ir.process.transition_index()["T0"].guard_ast = GuardAST(
        node_type=GuardNodeType.AND, value_type=GuardValueType.BOOL,
        children=[GuardAST(node_type=GuardNodeType.CONST, value_type=GuardValueType.INT, value=1)],
    )
    ir.refresh_hash()
    issues = ValidationEngine().validate(ir).issues
    assert any("guard" in i["reason"].lower() for i in issues)
