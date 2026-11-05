"""Limits / fail-closed behaviour for the bounded truth-table interlock checker.

These tests pin the honest contract: the checker is an exhaustive (exponential)
truth-table scan, NOT a formal prover. When the literal cap or the time budget
is hit it must return status="unknown" / is_safe=False and never a false "safe".
"""

from __future__ import annotations

from plc_engine.af.cnf_splitter import parse_bool_expr
from plc_engine.af.smt_verifier import (
    DEADLOCK_UNKNOWN_PREFIX,
    MAX_SOLVER_LITERALS,
    UNKNOWN_RULE_TYPE,
    SafetyViolation,
    SimpleDpllSatSolver,
    SmtInterlockVerifier,
    SmtVerificationResult,
    TruthTableSatSolver,
)


def _and_expr(n_literals: int) -> str:
    """Build a flat AND expression over n distinct quoted literals."""
    return " AND ".join(f'"v{i}"' for i in range(n_literals))


def test_backward_compat_alias_and_solve() -> None:
    # Old name is retained as an alias, and the legacy solve() signature works.
    assert SimpleDpllSatSolver is TruthTableSatSolver
    solver = SimpleDpllSatSolver()
    is_sat, model = solver.solve(parse_bool_expr('"a" AND "b"'))
    assert is_sat is True
    assert model == {'"a"': True, '"b"': True}


def test_solver_reports_status() -> None:
    solver = TruthTableSatSolver()
    ok = solver.solve_with_status(parse_bool_expr('"a" AND "b"'))
    assert ok.status == "verified"
    assert ok.is_sat is True

    over = solver.solve_with_status(parse_bool_expr(_and_expr(MAX_SOLVER_LITERALS + 1)))
    assert over.status == "unknown"
    assert over.is_sat is False
    assert str(MAX_SOLVER_LITERALS + 1) in over.reason  # variable count
    assert str(MAX_SOLVER_LITERALS) in over.reason  # the limit


def test_over_limit_expression_returns_unknown_not_safe() -> None:
    verifier = SmtInterlockVerifier()
    big = _and_expr(MAX_SOLVER_LITERALS + 1)  # 17 literals with the default cap of 16
    result = verifier.verify_station_safety({"dev.rel": big})

    assert result.status == "unknown"
    assert result.is_safe is False
    assert str(MAX_SOLVER_LITERALS + 1) in result.reason
    assert str(MAX_SOLVER_LITERALS) in result.reason

    d = result.to_dict()
    assert d["status"] == "unknown"
    assert d["reason"] == result.reason
    assert d["is_safe"] is False


def test_helper_entrances_fail_closed_over_limit() -> None:
    # Standalone helper entrances must not return None ("safe") when they cannot
    # conclude; they return an explicit inconclusive marker instead.
    verifier = SmtInterlockVerifier()
    big = _and_expr(MAX_SOLVER_LITERALS + 1)

    v = verifier.verify_mutual_exclusion(big, big, "A", "B")
    assert v is not None
    assert v.rule_type == UNKNOWN_RULE_TYPE
    assert "NOT proven safe" in v.description

    dl = verifier.verify_deadlock(big, "STEP_X")
    assert dl is not None
    assert dl.startswith(DEADLOCK_UNKNOWN_PREFIX)


def test_timeout_returns_unknown_not_safe() -> None:
    # A zero-second budget forces the time.monotonic() branch deterministically.
    # The 16-literal UNSAT expression is within the literal cap, so the
    # inconclusive result must come from the time budget, not the cap.
    verifier = SmtInterlockVerifier(time_budget_s=0.0)
    unsat_big = _and_expr(MAX_SOLVER_LITERALS) + ' AND NOT "v0"'
    result = verifier.verify_station_safety({}, step_transitions=[("STEP_X", unsat_big)])

    assert result.status == "unknown"
    assert result.is_safe is False
    assert "budget" in result.reason.lower()


def test_three_literal_case_still_verified() -> None:
    # A normal small station must remain fully verified and safe.
    verifier = SmtInterlockVerifier()
    interlocks = {
        "cylA.releaseHome": '"i_xSafe" AND NOT "xBusy"',
        "cylA.releaseWork": '"i_xSafe" AND "xBusy"',
    }
    result = verifier.verify_station_safety(
        interlocks,
        step_transitions=[("STEP_10_WAIT", '"t1" AND "t2"')],
    )

    assert result.status == "verified"
    assert result.is_safe is True
    assert result.reason == ""
    assert "status" in result.to_dict()
    assert "reason" in result.to_dict()


def test_instance_limit_override_is_configurable() -> None:
    # The cap is configurable per instance (in addition to the env override).
    verifier = SmtInterlockVerifier(max_literals=2)
    result = verifier.verify_station_safety({"dev.rel": '"a" AND "b" AND "c"'})
    assert result.status == "unknown"
    assert result.is_safe is False
    assert "2" in result.reason


def test_is_safe_and_status_are_consistent() -> None:
    # The dataclass itself enforces the invariant, even for direct construction.
    forced = SmtVerificationResult(is_safe=True, summary="x", status="unknown", reason="y")
    assert forced.is_safe is False
    assert forced.to_dict()["status"] == "unknown"
    assert forced.to_dict()["reason"] == "y"

    clean = SmtVerificationResult(is_safe=True, summary="x", status="verified")
    assert clean.is_safe is True

    with_violation = SmtVerificationResult(
        is_safe=True,
        summary="x",
        status="verified",
        violations=[
            SafetyViolation(
                rule_type="MUTUAL_EXCLUSION_COLLISION",
                description="d",
                counterexample_inputs={},
                involved_symbols=[],
            )
        ],
    )
    assert with_violation.is_safe is False

    # Real results from the gate: is_safe=True is forbidden unless verified.
    verifier = SmtInterlockVerifier()
    results = [
        verifier.verify_station_safety({"d.r": '"a" AND "b"'}),  # verified / safe
        verifier.verify_station_safety(  # verified / unsafe (real collision)
            {"cyl.releaseHome": '"x"', "cyl.releaseWork": '"x"'}
        ),
        verifier.verify_station_safety(  # unknown / not safe
            {"d.r": _and_expr(MAX_SOLVER_LITERALS + 1)}
        ),
    ]
    for res in results:
        assert not (res.is_safe and res.status != "verified")
        assert "status" in res.to_dict() and "reason" in res.to_dict()
