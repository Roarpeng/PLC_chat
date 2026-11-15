"""WS2 semantic validator + guard parser tests."""
from __future__ import annotations

import pytest

from processos.contract import Action, clamp_contract
from processos.semantics import GuardError, eval_guard, parse_guard, validate


def test_guard_parser_basic():
    assert eval_guard("Start AND SafetyPermit", {"Start": True, "SafetyPermit": True})
    assert not eval_guard("Start AND SafetyPermit", {"Start": True, "SafetyPermit": False})
    assert eval_guard("NOT (Extend AND Retract)", {"Extend": True, "Retract": False})
    assert not eval_guard("NOT (Extend AND Retract)", {"Extend": True, "Retract": True})
    assert eval_guard("Reset AND Retracted AND NOT Extended",
                      {"Reset": True, "Retracted": True, "Extended": False})
    assert eval_guard("A OR B", {"A": False, "B": True})
    assert eval_guard("", {}) is True


def test_guard_parser_rejects_bad_syntax():
    with pytest.raises(GuardError):
        parse_guard("Start AND")
    with pytest.raises(GuardError):
        parse_guard("(Start")
    with pytest.raises(GuardError):
        parse_guard("Start @@ B")


def test_guard_unresolved_token_raises():
    g = parse_guard("Ghost")
    with pytest.raises(GuardError):
        g.evaluate({})


def test_clamp_validates_clean():
    report = validate(clamp_contract())
    assert report.ok, [e.message for e in report.errors]
    assert report.evidence_level == "offline_verified"
    assert report.coverage["steps"] == 6
    assert report.ir_hash.startswith("sha256:")


def test_missing_failure_target_is_error():
    c = clamp_contract()
    c.operations[0].step("S_EXTEND").failure_target = ""
    report = validate(c)
    assert any(e.code == "TIMEOUT_NO_EXIT" for e in report.errors)


def test_duplicate_writer_is_error():
    c = clamp_contract()
    c.operations[0].step("S_HOLD").entry.append(Action("CM_CLAMP_CYL", "Extend", True))
    report = validate(c)
    assert any(e.code == "DUPLICATE_OUTPUT_WRITER" for e in report.errors)


def test_unknown_guard_token_is_error():
    c = clamp_contract()
    c.operations[0].step("S_WAIT").guard = "Start AND GhostSignal"
    report = validate(c)
    assert any(e.code == "GUARD_TOKEN" for e in report.errors)


def test_dangling_next_is_error():
    c = clamp_contract()
    c.operations[0].step("S_DONE").next = "S_NOWHERE"
    report = validate(c)
    assert any(e.code in ("STRUCTURE", "UNREACHABLE") for e in report.errors)


def test_fault_without_reset_guard_is_error():
    c = clamp_contract()
    c.operations[0].step("S_FAULT").reset_guard = ""
    report = validate(c)
    assert any(e.code == "FAULT_NO_RESET" for e in report.errors)