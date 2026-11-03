"""编译错误自愈闭环（writeback_heal）测试。

全部样本内联，不读外部文件、不连网络、不写盘 —— repair_fn 是可注入的，
因此整条闭环可以在零依赖下被完整驱动。
"""

from __future__ import annotations

import itertools
import json

import pytest

from plc_engine.contracts import (
    AvailableStructDefinition,
    CompileErrorItem,
    PatchedSlotDelta,
    to_dict,
)
from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_heal import (
    CircuitBreaker,
    HealCircuitOpen,
    HealOutcome,
    SlotPatchRejected,
    apply_slot_patch,
    build_self_heal_request,
    heal_loop,
)

# --------------------------------------------------------------------------
# 内联 SCL 样本
# --------------------------------------------------------------------------

UDT_SRC = """TYPE "UDT_ST10_AutoCmd"
VERSION : 0.1
   STRUCT
      xHome : Bool;
      xWork : Bool;
   END_STRUCT;
END_TYPE
"""

CLEAN_FB_SRC = """FUNCTION_BLOCK "FB_ST10_Main"
VAR
   statStep : Int := 10;
   statCmd : "UDT_ST10_AutoCmd";
END_VAR
BEGIN
   #statStep := 20;
END_FUNCTION_BLOCK
"""

IDB_SRC = """DATA_BLOCK "IDB_ST10_Main"
"FB_ST10_Main"
BEGIN
END_DATA_BLOCK
"""

# Slot 3 里直写物理输出 —— writeback_linter 规则 R2 必报 error
BAD_FB_SRC = """FUNCTION_BLOCK "FB_ST10_Main"
VAR
   xGo : Bool;
END_VAR
BEGIN
   "Q_Test_Valve" := #xGo;
END_FUNCTION_BLOCK
"""

BAD_LINE = '"Q_Test_Valve" := #xGo;'

STRUCT = AvailableStructDefinition(
    type_name="UDT_ST10_AutoCmd", fields=["xHome", "xWork", "xInPos"]
)


def _clean_blocks() -> list[BlockArtifact]:
    return [
        BlockArtifact(
            name="UDT_ST10_AutoCmd", kind="UDT", source=UDT_SRC, interface_changed=True
        ),
        BlockArtifact(
            name="FB_ST10_Main",
            kind="FB",
            source=CLEAN_FB_SRC,
            dependencies=["UDT_ST10_AutoCmd"],
        ),
        BlockArtifact(
            name="IDB_ST10_Main",
            kind="INSTANCE_DB",
            source=IDB_SRC,
            dependencies=["FB_ST10_Main"],
        ),
    ]


def _bad_source(name: str = "FB_ST10_Main") -> str:
    if name == "FB_ST10_Main":
        return BAD_FB_SRC
    return BAD_FB_SRC.replace('"FB_ST10_Main"', f'"{name}"')


def _bad_blocks() -> list[BlockArtifact]:
    return [BlockArtifact(name="FB_ST10_Main", kind="FB", source=_bad_source())]


def _err(
    block: str = "FB_ST10_Main",
    line: str = "L6",
    desc: str = "组件 'xInTargetPos' 未在类型 'UDT_ST10_AutoCmd' 中定义。",
) -> CompileErrorItem:
    return CompileErrorItem(
        block_name=block, network_or_line=line, tia_description=desc, timestamp="2026-01-01T00:00:00+00:00"
    )


def _delta(old: str, new: str, station: str = "FB_ST10_Main") -> PatchedSlotDelta:
    return PatchedSlotDelta(
        station_id=station,
        modified_slots=["slot3_SeqAuto"],
        patch={old: new},
        explanation="把物理 Q 直写改到 HMI 适配层",
    )


# --------------------------------------------------------------------------
# 用例
# --------------------------------------------------------------------------


def test_clean_on_first_round_without_any_error() -> None:
    outcome = heal_loop(_clean_blocks(), [], lambda _req: None)
    assert outcome.success is True
    assert outcome.attempts == 0
    assert outcome.stop_reason == "clean"
    assert outcome.requests == []
    assert outcome.final_errors == []


def test_repair_once_fixes_the_block() -> None:
    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"DB_Hmi_Old".ValveCmd := #xGo;')

    outcome = heal_loop(_bad_blocks(), [_err()], repair)
    assert outcome.success is True
    assert outcome.attempts == 1
    assert outcome.stop_reason == "clean"
    assert outcome.repaired_blocks == ["FB_ST10_Main"]
    assert outcome.final_errors == []


def test_source_is_actually_patched() -> None:
    captured: list[str] = []

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"DB_Hmi_Old".ValveCmd := #xGo;')

    blocks = _bad_blocks()

    def spy(req: object) -> PatchedSlotDelta:
        delta = repair(req)
        captured.append(blocks[0].source)
        return delta

    heal_loop(blocks, [_err()], spy)
    assert BAD_LINE in captured[0]  # 打补丁前
    assert '"DB_Hmi_Old".ValveCmd := #xGo;' in blocks[0].source
    assert BAD_LINE not in blocks[0].source


def test_never_healing_hits_max_retries() -> None:
    counter = itertools.count(1)

    def repair(_req: object) -> PatchedSlotDelta:
        n = next(counter)
        old = BAD_LINE if n == 1 else f'"Q_Test_Valve_R{n - 1}" := #xGo;'
        return _delta(old, f'"Q_Test_Valve_R{n}" := #xGo;')

    outcome = heal_loop(_bad_blocks(), [_err()], repair, max_retries=3)
    assert outcome.success is False
    assert outcome.attempts == 3
    assert outcome.stop_reason == "max_retries"
    assert len(outcome.final_errors) == 1
    assert "Q_Test_Valve_R3" in outcome.final_errors[0].tia_description


def test_circuit_breaker_opens_on_repeated_same_error() -> None:
    """补丁只是把出错行往下挪了一行，错误类别没变 —— 第 3 轮起熔断。"""

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"DB_Hmi_Old".ValveCmd := #xGo;\n   ' + BAD_LINE)

    outcome = heal_loop(_bad_blocks(), [_err()], repair, max_retries=3)
    assert outcome.success is False
    assert outcome.stop_reason == "circuit_breaker"


def test_circuit_breaker_wins_over_max_retries() -> None:
    """熔断先于 max_retries 生效：attempts 用不完就停。"""

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"DB_Hmi_Old".ValveCmd := #xGo;\n   ' + BAD_LINE)

    outcome = heal_loop(_bad_blocks(), [_err()], repair, max_retries=5)
    assert outcome.stop_reason == "circuit_breaker"
    assert outcome.attempts < 5
    assert outcome.attempts == 2


def test_no_progress_stops_when_error_set_is_identical() -> None:
    """补丁只加了个行尾注释，错误集合一字未变。"""

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, BAD_LINE + " // 待人工确认")

    # 第 1 轮修完门禁报错 E1，第 2 轮再修一次还是 E1 —— 到此判定无进展
    outcome = heal_loop(_bad_blocks(), [_err()], repair, max_retries=3)
    assert outcome.success is False
    assert outcome.stop_reason == "no_progress"
    assert outcome.attempts == 2


def test_patch_key_not_found_is_rejected() -> None:
    def repair(_req: object) -> PatchedSlotDelta:
        return _delta("这块根本不在源码里", '"DB_Hmi_Old".ValveCmd := #xGo;')

    outcome = heal_loop(_bad_blocks(), [_err()], repair)
    assert outcome.success is False
    assert outcome.stop_reason == "repair_rejected"
    assert outcome.attempts == 1
    assert outcome.repaired_blocks == []


def test_repair_fn_giving_up_stops_the_loop() -> None:
    outcome = heal_loop(_bad_blocks(), [_err()], lambda _req: None)
    assert outcome.success is False
    assert outcome.stop_reason == "repair_rejected"
    assert outcome.attempts == 1
    assert len(outcome.requests) == 1


def test_requests_carry_increasing_attempt_and_pass_validate() -> None:
    counter = itertools.count(1)

    def repair(_req: object) -> PatchedSlotDelta:
        n = next(counter)
        old = BAD_LINE if n == 1 else f'"Q_Test_Valve_R{n - 1}" := #xGo;'
        return _delta(old, f'"Q_Test_Valve_R{n}" := #xGo;')

    outcome = heal_loop(
        _bad_blocks(), [_err()], repair, max_retries=3, struct_definition=STRUCT
    )
    assert [r.retry_attempt for r in outcome.requests] == [1, 2, 3]
    assert all(r.max_retries == 3 for r in outcome.requests)
    for request in outcome.requests:
        request.validate()  # 结构性必填项齐备
    # 第 2 轮喂给 LLM 的必须是第 1 轮门禁跑出来的真实错误，而不是原始报错
    assert outcome.requests[0].compiler_errors[0].tia_description.endswith("中定义。")
    assert "[R2]" in outcome.requests[1].compiler_errors[0].tia_description


def test_instruction_pins_struct_fields_and_slot_only_rule() -> None:
    request = build_self_heal_request(
        [_err()], attempt=1, max_retries=3, struct_definition=STRUCT, station_id="ST10"
    )
    assert "仅输出修正后的 JSON 槽位" in request.instruction
    assert "禁止触碰底层状态机外壳与物理 Q 映射" in request.instruction
    for field_name in STRUCT.fields:
        assert field_name in request.instruction
    assert "ST10" in request.instruction
    request.validate()


def test_instruction_without_struct_definition_forbids_new_names() -> None:
    request = build_self_heal_request([_err()], attempt=2, max_retries=3)
    assert "禁止引入任何新的成员名" in request.instruction
    assert request.available_struct_definition.fields == []
    request.validate()


def test_outcome_is_json_serializable() -> None:
    outcome = heal_loop(_bad_blocks(), [_err()], lambda _req: None)
    payload = json.dumps(to_dict(outcome), ensure_ascii=False)
    assert "repair_rejected" in payload
    assert "SELF_HEAL_COMPILE_ERROR" in payload


def test_gate_findings_are_fed_into_the_next_round() -> None:
    """门禁（lint）报的错必须转成 CompileErrorItem，不能跳过。"""

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"Q_ST10_LiftWork" := #xGo;')

    outcome = heal_loop(_bad_blocks(), [_err()], repair, max_retries=1)
    assert outcome.stop_reason == "max_retries"
    assert len(outcome.final_errors) == 1
    item = outcome.final_errors[0]
    assert item.block_name == "FB_ST10_Main"
    assert item.network_or_line.startswith("L")
    assert item.tia_description.startswith("[R2]")
    assert "Q_ST10_LiftWork" in item.tia_description


def test_gate_runs_even_with_empty_initial_errors() -> None:
    """没有编译报错也要先跑门禁；门禁脏就照样进闭环。"""

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"DB_Hmi_Old".ValveCmd := #xGo;')

    outcome = heal_loop(_bad_blocks(), [], repair)
    assert outcome.success is True
    assert outcome.attempts == 1
    assert outcome.repaired_blocks == ["FB_ST10_Main"]


def test_station_scoped_patch_and_unknown_seed_degrades_to_full() -> None:
    """station_id 命中哪个块就改哪个块；种子块不存在时退化为全量重建。"""
    blocks = _clean_blocks() + [
        BlockArtifact(name="FB_ST20_Main", kind="FB", source=_bad_source("FB_ST20_Main"))
    ]

    def repair(_req: object) -> PatchedSlotDelta:
        return _delta(BAD_LINE, '"DB_Hmi_Old".ValveCmd := #xGo;', station="FB_ST20_Main")

    outcome = heal_loop(blocks, [], repair, seeds=["幽灵块"])
    assert outcome.success is True
    assert outcome.repaired_blocks == ["FB_ST20_Main"]


def test_circuit_breaker_unit_and_reset() -> None:
    breaker = CircuitBreaker()
    breaker.update([_err()])
    assert breaker.streaks
    with pytest.raises(HealCircuitOpen):
        breaker.update([_err()])

    fresh = CircuitBreaker()
    fresh.update([_err()])
    fresh.update([_err(desc="完全不同的另一条错")])  # 类别变了 -> 重新计数
    fresh.update([_err()])
    assert max(fresh.streaks.values()) == 1


def test_apply_slot_patch_rejects_empty_and_missing_keys() -> None:
    blocks = _bad_blocks()
    with pytest.raises(SlotPatchRejected):
        apply_slot_patch(blocks, PatchedSlotDelta(station_id="FB_ST10_Main", modified_slots=["slot3_SeqAuto"]))
    with pytest.raises(SlotPatchRejected):
        apply_slot_patch(blocks, _delta("不存在的槽位", "x"))
    with pytest.raises(SlotPatchRejected):
        apply_slot_patch(blocks, _delta("   ", "x"))


def test_apply_slot_patch_prefers_station_block() -> None:
    blocks = [
        BlockArtifact(name="FB_A", kind="FB", source=BAD_FB_SRC.replace("FB_ST10_Main", "FB_A")),
        BlockArtifact(name="FB_B", kind="FB", source=BAD_FB_SRC.replace("FB_ST10_Main", "FB_B")),
    ]
    changed = apply_slot_patch(blocks, _delta(BAD_LINE, '"DB_Hmi_Old".V := #xGo;', station="FB_B"))
    assert changed == ["FB_B"]
    assert BAD_LINE in blocks[0].source
    assert BAD_LINE not in blocks[1].source


def test_heal_outcome_defaults() -> None:
    outcome = HealOutcome(success=True, attempts=0)
    assert outcome.stop_reason == "clean"
    assert outcome.final_errors == []
    assert outcome.requests == []
    assert outcome.repaired_blocks == []
