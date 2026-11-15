"""WS2 scenario runner tests — 6 clamp scenarios + counterexample engine."""
from __future__ import annotations

from processos.contract import Action, clamp_contract
from processos.scenario import Runner, run_all


def _results_by_id():
    return {r.scenario_id: r for r in run_all(clamp_contract())}


def test_normal_cycle_completes():
    r = _results_by_id()["normal_cycle"]
    assert r.passed, r.counterexamples
    assert not r.fault_reason
    assert {"S_EXTEND", "S_HOLD", "S_RETRACT", "S_DONE"} <= set(r.reached)
    assert r.properties["hold_duration_respected"] == "pass"
    assert r.properties["no_simultaneous_extend_retract"] == "pass"


def test_extend_timeout_faults():
    r = _results_by_id()["extend_timeout"]
    assert r.passed
    assert r.fault_reason == "TIMEOUT"
    assert "S_FAULT" in r.reached
    assert r.properties["extend_timeout_causes_fault"] == "pass"


def test_retract_timeout_faults():
    r = _results_by_id()["retract_timeout"]
    assert r.passed
    assert r.fault_reason == "TIMEOUT"
    assert {"S_RETRACT", "S_FAULT"} <= set(r.reached)


def test_conflicting_feedback_faults():
    r = _results_by_id()["conflicting_feedback"]
    assert r.passed
    assert r.fault_reason == "FEEDBACK_FAULT"
    assert "S_FAULT" in r.reached
    assert r.properties["no_simultaneous_extend_retract"] == "pass"


def test_permit_loss_stops_motion():
    r = _results_by_id()["permit_loss"]
    assert r.passed
    assert r.fault_reason == "PERMIT_LOST"
    assert {"S_HOLD", "S_FAULT"} <= set(r.reached)
    assert r.properties["permit_loss_stops_motion"] == "pass"


def test_fault_reset_qualifies():
    r = _results_by_id()["fault_reset"]
    assert r.passed
    assert not r.fault_reason
    assert {"S_FAULT", "S_WAIT"} <= set(r.reached)
    assert r.properties["reset_requires_safe_condition"] == "pass"


def test_all_six_pass():
    results = run_all(clamp_contract())
    assert len(results) == 6
    assert all(r.passed for r in results), [(r.scenario_id, r.fault_reason) for r in results if not r.passed]


def test_counterexample_on_command_conflict():
    c = clamp_contract()
    c.operations[0].step("S_EXTEND").entry.append(Action("CM_CLAMP_CYL", "Retract", True))
    runner = Runner()
    r = runner.run(c, c.scenarios[0])
    assert r.properties["no_simultaneous_extend_retract"] == "fail"
    assert r.counterexamples
    ce = r.counterexamples[0]
    assert ce.property_id == "no_simultaneous_extend_retract"
    assert ce.cycle >= 0
    assert ce.trace
    assert not r.passed


def test_trace_is_nonempty_and_timed():
    r = _results_by_id()["normal_cycle"]
    assert len(r.trace) > 3
    assert r.trace[0].t_ms == 0
    assert all(e.t_ms >= 0 for e in r.trace)
    assert r.evidence_level == "simulated"