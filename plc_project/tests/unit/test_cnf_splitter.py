"""Unit tests for CNF Boolean Algebra Splitter (Tab 3 Step 3)."""

from __future__ import annotations

import pytest

from plc_engine.af.cnf_splitter import (
    CnfLogicSplitter,
    ConstBool,
    Literal,
    NotNode,
    OrNode,
    AndNode,
    parse_bool_expr,
    to_cnf,
    tokenize_bool_expr,
)


def test_tokenize_simple_and_quoted() -> None:
    tokens = tokenize_bool_expr('"DB_AxisX"."xInPos" AND NOT #i_xEstop OR (I_Sensor_1)')
    types = [t.type.name for t in tokens]
    assert "IDENT" in types
    assert "AND" in types
    assert "NOT" in types
    assert "OR" in types
    assert "LPAREN" in types
    assert "RPAREN" in types


def test_parse_and_precedence() -> None:
    # A OR B AND C -> A OR (B AND C)
    ast = parse_bool_expr("A OR B AND C")
    assert isinstance(ast, OrNode)
    assert len(ast.operands) == 2
    assert isinstance(ast.operands[0], Literal)
    assert isinstance(ast.operands[1], AndNode)


def test_de_morgan_cnf() -> None:
    # NOT (A AND B) -> NOT A OR NOT B (already CNF)
    ast = parse_bool_expr("NOT (A AND B)")
    cnf = to_cnf(ast)
    assert isinstance(cnf, OrNode)
    literals = {op.to_scl() for op in cnf.operands}
    assert literals == {"NOT A", "NOT B"}


def test_distribute_or_over_and() -> None:
    # (A AND B) OR C -> (A OR C) AND (B OR C)
    ast = parse_bool_expr("(A AND B) OR C")
    cnf = to_cnf(ast)
    assert isinstance(cnf, AndNode)
    assert len(cnf.operands) == 2


def test_split_step_and_interlock() -> None:
    splitter = CnfLogicSplitter()
    # Mixed condition: SafetyDoor + E-Stop (Interlock) + Step20/Step30 (Step)
    raw = '"I_SafetyDoor_OK" AND NOT "I_Estop" AND ("M_Step20" OR "M_Step30") AND "DB_AxisX".xInPos'
    res = splitter.split_condition(raw)

    assert res.has_step_binding is True
    assert res.has_safety_binding is True

    # Step trigger expression should only contain Step20 or Step30
    assert "M_Step20" in res.step_trigger_expr
    assert "M_Step30" in res.step_trigger_expr
    assert "SafetyDoor" not in res.step_trigger_expr

    # Release interlock should contain SafetyDoor, Estop, and AxisX
    assert "I_SafetyDoor_OK" in res.release_interlock_expr
    assert "NOT \"I_Estop\"" in res.release_interlock_expr
    assert '"DB_AxisX".xInPos' in res.release_interlock_expr
    assert "M_Step20" not in res.release_interlock_expr


def test_pure_interlock_condition() -> None:
    splitter = CnfLogicSplitter()
    raw = '"I_Guard_Closed" AND NOT "I_Emergency"'
    res = splitter.split_condition(raw)

    assert res.has_step_binding is False
    assert res.has_safety_binding is True
    assert res.step_trigger_expr == "TRUE"
    assert '"I_Guard_Closed"' in res.release_interlock_expr


def test_pure_step_condition() -> None:
    splitter = CnfLogicSplitter()
    raw = '#statStepAuto = 20 OR #statStepAuto = 30'
    res = splitter.split_condition(raw)

    assert res.has_step_binding is True
    assert res.has_safety_binding is False
    assert res.release_interlock_expr == "TRUE"
    assert "statStepAuto" in res.step_trigger_expr
