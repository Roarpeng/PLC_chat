"""Step 5 上下文切片器与 Token 预算控制的单元测试。"""

from __future__ import annotations

import json

import pytest

from plc_engine.contracts import SLOT_KEYS, BoschStationAfModel, PatchedSlotDelta
from plc_engine.slot_context_slicer import (
    ContextBudgetExceeded,
    assert_context_safe,
    estimate_tokens,
    slice_station_context,
    validate_slot_patch,
)

PROMPT = "在 ST10 步序 20 升降气缸下降前增加夹爪原位互锁"


def _model(*, interlock: dict | None = None, elements: list | None = None) -> BoschStationAfModel:
    slots = {k: [] for k in SLOT_KEYS}
    slots["slot2_OpMode"] = "LOCKED_BOSCH_TEMPLATE"
    slots["slot4_Interlock"] = interlock if interlock is not None else {
        "Cyl_Lift.releaseWork": "#i_stOpMode.xSafetyOk AND \"DB_AxisX\".xInPos"
    }
    slots["slot5_ElementCall"] = elements if elements is not None else [
        {
            "instanceName": "Cyl_Lift",
            "fbType": "FB_Bosch_Cyl2Way",
            "ioMap": {"i_xSenHome": "I_ST10_Lift_Home"},
            "timeout": "T#2000MS",
            "internalNote": "不该下发",
        }
    ]
    slots["slot3_SeqAuto"] = [
        {"stepNo": 10, "comment": "等待托盘到位", "actions": [], "transitions": []},
        {"stepNo": 20, "comment": "升降气缸下降", "actions": ["Cyl_Lift.Work"], "transitions": []},
    ]
    return BoschStationAfModel(
        station_id="ST10",
        fb_block_name="FB_ST10_Main",
        idb_block_name="IDB_ST10_Main",
        cmd_udt_name="UDT_ST10_AutoCmd",
        slots=slots,
    )


def test_estimate_tokens_basics() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("中" * 100) > estimate_tokens("a" * 100)
    assert estimate_tokens("中文中文") >= 4


def test_slice_returns_controlled_context() -> None:
    result = slice_station_context(_model(), PROMPT)
    assert result.context.target_station == "ST10"
    assert result.context.user_prompt == PROMPT
    assert "Cyl_Lift" in result.context.available_elements
    assert result.within_budget


def test_slice_excludes_locked_slot2() -> None:
    result = slice_station_context(_model(), PROMPT)
    assert "slot2_OpMode" not in result.slots
    assert set(result.included_slots) <= {"slot3_SeqAuto", "slot4_Interlock", "slot5_ElementCall"}


def test_payload_carries_actual_slots() -> None:
    """切出的槽位内容必须真的在负载里，不能只剩 DTO 空壳。"""
    result = slice_station_context(_model(), PROMPT)
    payload = result.to_payload()
    assert "slots" in payload
    assert "slot4_Interlock" in payload["slots"]
    assert payload["slots"]["slot5_ElementCall"][0]["instanceName"] == "Cyl_Lift"
    json.dumps(payload, ensure_ascii=False)


def test_element_signature_slimmed() -> None:
    result = slice_station_context(_model(), PROMPT)
    element = result.slots["slot5_ElementCall"][0]
    assert "internalNote" not in element
    assert "instanceName" in element and "fbType" in element


def test_dropped_fields_recorded() -> None:
    result = slice_station_context(_model(), PROMPT)
    assert any("internalNote" in f for f in result.dropped_fields)


def test_budget_enforced() -> None:
    tiny = slice_station_context(_model(), PROMPT, token_budget=10000)
    assert tiny.estimated_tokens <= 10000
    with pytest.raises(ContextBudgetExceeded):
        slice_station_context(_model(), PROMPT, token_budget=1)


def test_budget_degrades_instead_of_truncating_json() -> None:
    """预算紧张时按优先级裁剪（199 -> 178 -> 143），而不是把 JSON 腰斩。"""
    result = slice_station_context(_model(), PROMPT, token_budget=150)
    assert result.within_budget
    assert result.truncated
    assert result.dropped_fields
    assert result.slots  # 至少还剩互锁与元件签名
    assert "slot3_SeqAuto" not in result.slots  # 已降级到丢弃步序


def test_include_slots_narrows() -> None:
    result = slice_station_context(_model(), PROMPT, include_slots=["slot4_Interlock"])
    assert result.included_slots == ["slot4_Interlock"]
    assert "slot3_SeqAuto" not in result.slots


def test_invalid_budget() -> None:
    with pytest.raises(ValueError, match="token_budget"):
        slice_station_context(_model(), PROMPT, token_budget=0)


def test_assert_context_safe_passes_clean_slice() -> None:
    assert_context_safe(slice_station_context(_model(), PROMPT))


def test_assert_context_safe_rejects_locked_template_leak() -> None:
    model = _model(interlock={"x": "LOCKED_BOSCH_TEMPLATE"})
    with pytest.raises(ValueError, match="Slot 2"):
        assert_context_safe(slice_station_context(model, PROMPT))


def test_assert_context_safe_rejects_physical_q() -> None:
    model = _model(interlock={"Cyl_Lift.releaseWork": '"Q_ST10_Lift_Work"'})
    with pytest.raises(ValueError, match="物理输出"):
        assert_context_safe(slice_station_context(model, PROMPT))


def test_validate_slot_patch_accepts_valid() -> None:
    delta = PatchedSlotDelta(
        station_id="ST10",
        modified_slots=["slot4_Interlock"],
        patch={"Cyl_Lift.releaseWork": "a AND #Cyl_Grip.q_xInHome"},
        explanation="串联夹爪原位互锁",
    )
    validate_slot_patch(delta)


def test_validate_slot_patch_rejects_physical_q() -> None:
    delta = PatchedSlotDelta(
        station_id="ST10",
        modified_slots=["slot4_Interlock"],
        patch={"Cyl_Lift.releaseWork": '"Q_ST10_Lift_Work"'},
    )
    with pytest.raises(ValueError, match="物理输出"):
        validate_slot_patch(delta)


def test_validate_slot_patch_rejects_locked_slot() -> None:
    delta = PatchedSlotDelta(station_id="ST10", modified_slots=["slot2_OpMode"])
    with pytest.raises(Exception, match="禁止修改"):
        validate_slot_patch(delta)
