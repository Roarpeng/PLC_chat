"""Unit tests for SMT Interlock Verifier and Companion Alarm Generator (Tab 5 / Milestone 2)."""

from __future__ import annotations

import pytest

from plc_engine.af.smt_verifier import (
    SmtInterlockVerifier,
    eval_bool_node,
    SimpleDpllSatSolver,
)
from plc_engine.af.cnf_splitter import parse_bool_expr


def test_dpll_sat_solver_sat_and_unsat() -> None:
    solver = SimpleDpllSatSolver()

    # SAT: A AND B
    sat_formula = parse_bool_expr("A AND B")
    is_sat, model = solver.solve(sat_formula)
    assert is_sat is True
    assert model["A"] is True
    assert model["B"] is True

    # UNSAT: A AND NOT A
    unsat_formula = parse_bool_expr("A AND NOT A")
    is_sat, _ = solver.solve(unsat_formula)
    assert is_sat is False


def test_verify_mutual_exclusion_safe_case() -> None:
    verifier = SmtInterlockVerifier()
    # Safe pair: Home requires CylinderAtWork=False, Work requires CylinderAtHome=False
    # If cond_a = "xSafe AND NOT xBusy", cond_b = "xSafe AND xBusy" -> collision is impossible!
    cond_a = '"i_xSafe" AND NOT "xBusy"'
    cond_b = '"i_xSafe" AND "xBusy"'

    violation = verifier.verify_mutual_exclusion(
        cond_a,
        cond_b,
        device_a="Cyl.Home",
        device_b="Cyl.Work",
    )
    # Proof: (Safe AND NOT Busy) AND (Safe AND Busy) = UNSAT -> Safe!
    assert violation is None


def test_verify_mutual_exclusion_collision_detected() -> None:
    verifier = SmtInterlockVerifier()
    # Flawed logic: both conditions can be satisfied when SafetyOk is TRUE
    cond_a = '"i_xSafetyOk" AND "i_xAuto"'
    cond_b = '"i_xSafetyOk" AND NOT "i_xManual"'

    violation = verifier.verify_mutual_exclusion(
        cond_a,
        cond_b,
        device_a="PressCylinder.Down",
        device_b="SlideTable.Forward",
    )
    # Collision is SAT when SafetyOk=True, Auto=True, Manual=False
    assert violation is not None
    assert violation.rule_type == "MUTUAL_EXCLUSION_COLLISION"
    assert "Mechanical collision hazard" in violation.description
    assert violation.counterexample_inputs['"i_xSafetyOk"'] is True
    assert violation.counterexample_inputs['"i_xAuto"'] is True
    assert violation.counterexample_inputs['"i_xManual"'] is False


def test_verify_deadlock_detection() -> None:
    verifier = SmtInterlockVerifier()
    # Deadlock transition: SensorWork AND NOT SensorWork
    deadlock_cond = '"I_PartPresent" AND NOT "I_PartPresent"'
    res = verifier.verify_deadlock(deadlock_cond, "STEP_20_FEED")
    assert res is not None
    assert "Deadlock detected" in res
    assert "UNSATISFIABLE" in res

    # Healthy transition
    ok_cond = '"I_PartPresent" AND "I_CylAtHome"'
    res_ok = verifier.verify_deadlock(ok_cond, "STEP_10_WAIT")
    assert res_ok is None


def test_companion_alarm_generation_human_readable() -> None:
    verifier = SmtInterlockVerifier()
    expr = '#i_stOpMode.xSafetyOk AND "DB_AxisX".xInPos AND #cylGrip.q_xInHome'
    alarms = verifier.generate_companion_alarms("cylLoader", "releaseWork", expr)

    assert len(alarms) == 3
    # Check IDs
    ids = [a.alarm_id for a in alarms]
    assert "ALM_CYLLOADER_RELEASEWORK_C1" in ids
    assert "ALM_CYLLOADER_RELEASEWORK_C2" in ids
    assert "ALM_CYLLOADER_RELEASEWORK_C3" in ids

    # Check semantic explanations
    zh_texts = [a.alarm_text_zh for a in alarms]
    # Clause 1 (safety)
    assert any("安全保护回路未就绪" in t for t in zh_texts)
    # Clause 2 (axis)
    assert any("伺服轴未到达指定防撞安全位置" in t for t in zh_texts)
    # Clause 3 (clamp / grip)
    assert any("夹爪/夹紧机构未就位" in t for t in zh_texts)

    # Check suggested actions
    actions = [a.suggested_action for a in alarms]
    assert any("急停按钮" in act for act in actions)
    assert any("防撞互锁" in act for act in actions)
