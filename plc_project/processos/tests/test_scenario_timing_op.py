"""PLAN §10 场景同步最小 op：``set_scenario_timing``（缺口 3 支撑）。

只允许改写场景输入事件的数值时序字段（t_ms），信号/期望不可触碰；
构造期与执行期双重校验，negative 全覆盖（fail-closed）。
"""
from __future__ import annotations

import pytest

from processos.contract import Patch, PatchOp, clamp_contract
from processos.contract.model import ProcessContract
from processos.contract.patch import PatchError, apply_patch
from processos.scenario import run_all

PID = "PRJ_CLAMP"


def _timeout_5000_contract():
    c = clamp_contract()
    c2, _ = apply_patch(c, Patch(base_revision=1, ops=[
        PatchOp("set", "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms", 5000)]), 1)
    return c2


def _timing_op(**overrides):
    kwargs = {"scenario": "fault_reset", "index": 4, "field": "t_ms", "value": 5500}
    kwargs.update(overrides)
    return PatchOp("set_scenario_timing", "/scenarios/" + kwargs["scenario"],
                   kwargs.pop("value"), **kwargs)


# ---------- positive ----------

def test_timing_op_changes_recorded_event_time_only():
    patched, rev = apply_patch(
        _timeout_5000_contract(),
        Patch(base_revision=2, ops=[_timing_op(), _timing_op(index=5, value=5600)]), 2)
    assert rev == 3
    fr = next(s for s in patched.scenarios if s.id == "fault_reset")
    assert fr.inputs[4]["t_ms"] == 5500 and fr.inputs[5]["t_ms"] == 5600
    assert fr.inputs[4]["signal"] == "Reset"  # 信号与期望未被触碰
    assert fr.expect == {"fault": False, "reset_ok": True,
                         "reached": ["S_FAULT", "S_WAIT"]}
    # 场景同步后全绿：复位事件晚于新超时
    results = run_all(patched)
    assert all(r.passed for r in results)


def test_timing_op_dict_roundtrip():
    op = PatchOp.from_dict({"op": "set_scenario_timing", "scenario": "fault_reset",
                            "index": 4, "field": "t_ms", "value": 5500})
    d = op.to_dict()
    assert d["op"] == "set_scenario_timing"
    assert d["scenario"] == "fault_reset" and d["index"] == 4 and d["field"] == "t_ms"
    assert d["value"] == 5500
    assert op.timing_path == "/scenarios/fault_reset/inputs/4/t_ms"
    # 普通三件套 op 的字典形状保持不变（向后兼容）
    plain = PatchOp.from_dict({"op": "set", "path": "/name", "value": "x"})
    assert plain.to_dict() == {"op": "set", "path": "/name", "value": "x"}


def test_timing_op_allows_float_value():
    patched, _ = apply_patch(
        _timeout_5000_contract(),
        Patch(base_revision=2, ops=[_timing_op(value=5500.0)]), 2)
    fr = next(s for s in patched.scenarios if s.id == "fault_reset")
    assert fr.inputs[4]["t_ms"] == 5500.0


# ---------- negative（构造期校验） ----------

@pytest.mark.parametrize("overrides", [
    {"field": "signal"},                      # 非数值字段：不得改写信号
    {"field": "value"},                       # 非时序数值字段
    {"field": ""},                            # 缺 field
    {"value": "soon"},                        # 非数值 value
    {"value": -1},                            # 负数 value
    {"value": True},                          # bool 不是数值
    {"index": -1},                            # 负 index
    {"index": "4"},                           # index 必须是 int
    {"scenario": ""},                         # 缺 scenario
])
def test_timing_op_construction_rejects_bad_input(overrides):
    with pytest.raises(PatchError):
        _timing_op(**overrides)


def test_timing_op_requires_explicit_fields_from_dict():
    with pytest.raises(PatchError):
        PatchOp.from_dict({"op": "set_scenario_timing", "index": 4,
                           "field": "t_ms", "value": 5500})  # 无 scenario


# ---------- negative（执行期校验：对 live 契约文档） ----------

def test_timing_op_unknown_scenario_rejected():
    with pytest.raises(PatchError, match="no scenario 'NOPE'"):
        apply_patch(_timeout_5000_contract(),
                    Patch(base_revision=2, ops=[_timing_op(scenario="NOPE")]), 2)


def test_timing_op_index_out_of_range_rejected():
    with pytest.raises(PatchError, match="out of range"):
        apply_patch(_timeout_5000_contract(),
                    Patch(base_revision=2, ops=[_timing_op(index=99)]), 2)


def test_timing_op_rejects_non_numeric_current_value():
    doc = _timeout_5000_contract().to_dict()
    sc = next(s for s in doc["scenarios"] if s["id"] == "fault_reset")
    sc["inputs"][4]["t_ms"] = "soon"  # 篡改：当前值已非数值
    with pytest.raises(PatchError, match="not numeric"):
        apply_patch(ProcessContract.from_dict(doc),
                    Patch(base_revision=2, ops=[_timing_op()]), 2)
