"""G3: strong-typed GuardAST, no eval(), fail-closed unknown references."""
from __future__ import annotations

import pytest

from plc_engine.process.guard_ast import (
    GuardNodeType,
    GuardValidationError,
    GuardValueType,
    guard_and,
    guard_compare,
    guard_const,
    guard_not,
    guard_or,
    guard_signal,
)
from plc_engine.process.scl_lowering import guard_to_scl


def test_bool_signal_and_logical_operators() -> None:
    guard = guard_and(guard_signal("A"), guard_not(guard_signal("B")))
    assert guard.validate_types() == []
    assert guard.evaluate({"A": True, "B": False}) is True
    assert guard.evaluate({"A": True, "B": True}) is False
    assert guard.evaluate({"A": False, "B": False}) is False
    assert guard_or(guard_signal("A"), guard_signal("B")).evaluate({"A": False, "B": True}) is True


def test_unknown_signal_is_fail_closed() -> None:
    guard = guard_signal("Missing")
    result, issues = guard.evaluate_detailed({"A": True})
    assert result is False
    assert any("unknown signal" in i for i in issues)


def test_type_mismatch_is_fail_closed() -> None:
    guard = guard_signal("A", GuardValueType.INT)
    assert guard.validate_types() == []
    # A BOOL value in an INT slot is rejected at evaluation time (fail-closed).
    result, issues = guard.evaluate_detailed({"A": True})
    assert result is False
    assert issues
    assert guard.evaluate({"A": 2500}) is True


def test_const_types() -> None:
    assert guard_const(True).validate_types() == []
    assert guard_const(3000, GuardValueType.TIME).validate_types() == []
    assert guard_const("TRUE").validate_types()  # bool CONST requires bool
    assert guard_const(True, GuardValueType.INT).validate_types()  # int CONST requires int


def test_comparison_requires_matching_numeric_types() -> None:
    good = guard_compare(GuardNodeType.GE, guard_signal("elapsed", GuardValueType.TIME),
                         guard_const(2000, GuardValueType.TIME))
    assert good.validate_types() == []
    assert good.evaluate({"elapsed": 2500}) is True
    assert good.evaluate({"elapsed": 1000}) is False
    bad = guard_compare(GuardNodeType.GE, guard_signal("elapsed", GuardValueType.INT),
                        guard_const(True, GuardValueType.BOOL))
    assert bad.validate_types()


def test_elapsed_ge_guard() -> None:
    from plc_engine.process.guard_ast import GuardAST

    guard = GuardAST(
        node_type=GuardNodeType.ELAPSED_GE, value_type=GuardValueType.BOOL,
        children=[guard_signal("stepElapsed", GuardValueType.TIME),
                  guard_const(2000, GuardValueType.TIME)],
    )
    assert guard.validate_types() == []
    assert guard.evaluate({"stepElapsed": 2000}) is True
    assert guard.evaluate({"stepElapsed": 1999}) is False


def test_free_text_expression_is_forbidden() -> None:
    with pytest.raises(GuardValidationError):
        guard_free = {"node_type": "SIGNAL", "expression": "A AND NOT B; os.system('rm -rf /')"}
        from plc_engine.process.guard_ast import GuardAST
        GuardAST.from_dict(guard_free)
    with pytest.raises(GuardValidationError):
        from plc_engine.process.guard_ast import GuardAST
        GuardAST.from_dict({"node_type": "EVAL", "value_type": "BOOL"})


def test_no_eval_or_exec_in_guard_module() -> None:
    """AST-level check: no direct eval()/exec() Call node exists (comments are fine)."""
    import ast
    import inspect
    from plc_engine.process import guard_ast

    tree = ast.parse(inspect.getsource(guard_ast))
    forbidden = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("eval", "exec", "compile")
    ]
    assert forbidden == []
    assert "os.system" not in inspect.getsource(guard_ast)


def test_guard_to_scl_is_deterministic_and_typed() -> None:
    guard = guard_and(guard_signal("CmdStart"), guard_not(guard_signal("SensorIn")))
    scl = guard_to_scl(guard)
    assert scl == "(#CmdStart AND NOT (#SensorIn))"
    assert guard_to_scl(None) == "TRUE"
    timing = guard_compare(GuardNodeType.GE, guard_signal("elapsed", GuardValueType.TIME),
                           guard_const(2000, GuardValueType.TIME))
    assert "T#2000ms" in guard_to_scl(timing)


def test_referenced_signals_are_sorted() -> None:
    guard = guard_or(guard_and(guard_signal("Z"), guard_signal("A")), guard_not(guard_signal("M")))
    assert guard.referenced_signals() == ["A", "M", "Z"]
