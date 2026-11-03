"""七步数据契约基座的单元测试。

契约是所有 lane 的共享真源，这里重点验证：
- 七步索引完整且输入输出类型闭合
- to_dict / from_dict 对嵌套 dataclass 递归正确
- validate() 能拦住 LLM 越界编辑（尤其 Slot 2 锁定）
"""

from __future__ import annotations

import json

import pytest

from plc_engine.contracts import (
    CONTRACT_VERSION,
    SLOT_KEYS,
    STEP_CONTRACTS,
    AfBatchSource,
    Assignment,
    AvailableStructDefinition,
    BlockInterface,
    BoschStationAfModel,
    CompileErrorItem,
    ContractViolation,
    DependencyGraphMatrix,
    NetworkAst,
    NormalizedBlockAst,
    PatchedSlotDelta,
    PlcTag,
    RawProjectBundle,
    SelfHealRequest,
    StationCluster,
    TagTable,
    WritebackResult,
    contract_summary,
    from_dict,
    step_contract,
    to_dict,
)


def _sample(cls):
    """给每个契约类型构造一个带嵌套内容的代表性实例。"""
    return {
        RawProjectBundle: RawProjectBundle(
            project_path="D:/work/Line01.ap17",
            plc_name="PLC_1 [CPU 1516F-3 PN/DP]",
            tag_tables=[TagTable(name="IO_Station10", tags=[PlcTag(name="I_Home", data_type="Bool", logical_address="%I10.0")])],
        ),
        NormalizedBlockAst: NormalizedBlockAst(
            block_name="FC10_ST10_Logic",
            original_language="LAD",
            interface=BlockInterface(temps=["xTempCond"]),
            networks=[NetworkAst(network_no=1, title="升降气缸", scl_statements=['"Q_Work" := TRUE;'])],
        ),
        DependencyGraphMatrix: DependencyGraphMatrix(
            station_clusters=[StationCluster(station_prefix="ST10")],
        ),
        BoschStationAfModel: BoschStationAfModel(
            station_id="ST10",
            fb_block_name="FB_ST10_Main",
            idb_block_name="IDB_ST10_Main",
            cmd_udt_name="UDT_ST10_AutoCmd",
            slots={k: [] for k in SLOT_KEYS},
        ),
        PatchedSlotDelta: PatchedSlotDelta(
            station_id="ST10",
            modified_slots=["slot4_Interlock"],
            patch={"Cyl_Lift.releaseWork": "a AND b"},
            explanation="串联夹爪原位互锁",
        ),
        AfBatchSource: AfBatchSource(path="D:/tmp/AF_Batch.scl", sha256="abc", block_names=["FB_ST10_Main"]),
        WritebackResult: WritebackResult(
            success=False,
            errors=[CompileErrorItem(block_name="FB_ST10_Main", network_or_line="Line 42", tia_description="字段未定义")],
        ),
    }[cls]


def test_seven_steps_are_registered() -> None:
    assert len(STEP_CONTRACTS) == 7
    assert [s.index for s in STEP_CONTRACTS] == [1, 2, 3, 4, 5, 6, 7]


def test_step_io_types_chain() -> None:
    """相邻步骤的输入输出类型闭合。

    例外：Step 5 -> Step 6 不是直接链接。Step 5 产出的是 PatchedSlotDelta
    （槽位补丁），必须先应用回 BoschStationAfModel，Step 6 才能以更新后的
    模型为输入打包。这个"apply-patch 合并点"是文档 Tab2 的语义，不是缺陷。
    """
    for i in (2, 3, 4, 6):
        assert STEP_CONTRACTS[i - 1].output_type is not None
        assert STEP_CONTRACTS[i].input_type is STEP_CONTRACTS[i - 1].output_type
    assert STEP_CONTRACTS[4].output_type is PatchedSlotDelta  # Step 5
    assert STEP_CONTRACTS[5].input_type is BoschStationAfModel  # Step 6


def test_step_contract_lookup() -> None:
    assert step_contract(4).name.startswith("博世")
    with pytest.raises(KeyError):
        step_contract(8)


def test_contract_summary_is_json_serializable() -> None:
    rows = contract_summary()
    assert len(rows) == 7
    assert all(isinstance(r["output"], str) for r in rows)
    json.dumps(rows)


def test_all_output_types_roundtrip() -> None:
    for step in STEP_CONTRACTS:
        cls = step.output_type
        assert cls is not None
        original = _sample(cls)
        restored = from_dict(cls, to_dict(original))
        assert to_dict(restored) == to_dict(original), f"Step {step.index} 往返失败"


def test_nested_dataclass_is_reconstructed_not_dict() -> None:
    restored = from_dict(RawProjectBundle, to_dict(_sample(RawProjectBundle)))
    assert isinstance(restored.tag_tables[0], TagTable)
    assert isinstance(restored.tag_tables[0].tags[0], PlcTag)
    assert isinstance(from_dict(NormalizedBlockAst, to_dict(_sample(NormalizedBlockAst))).interface, BlockInterface)


def test_from_dict_handles_none_and_unknown_keys() -> None:
    assert from_dict(RawProjectBundle, None) is None
    restored = from_dict(RawProjectBundle, {"project_path": "x", "bogus_key": 1})
    assert restored.project_path == "x"
    assert restored.tag_tables == []


def test_to_dict_handles_plain_values() -> None:
    assert to_dict([1, {"a": 2}, None]) == [1, {"a": 2}, None]
    assert to_dict("s") == "s"


def test_validate_rejects_missing_required_fields() -> None:
    with pytest.raises(ContractViolation):
        RawProjectBundle(plc_name="PLC_1").validate()
    with pytest.raises(ContractViolation):
        NormalizedBlockAst(block_name="FC10").validate()


def test_bosch_model_requires_all_six_slots() -> None:
    BoschStationAfModel(station_id="ST10", fb_block_name="FB_ST10", slots={k: [] for k in SLOT_KEYS}).validate()
    with pytest.raises(ContractViolation, match="缺少槽位"):
        BoschStationAfModel(station_id="ST10", fb_block_name="FB_ST10", slots={"slot1_InPeriphery": []}).validate()


def test_editable_slots_excludes_locked_ones() -> None:
    model = _sample(BoschStationAfModel)
    editable = model.editable_slots()
    assert "slot3_SeqAuto" in editable
    assert "slot2_OpMode" not in editable


def test_patch_cannot_touch_locked_slot() -> None:
    _sample(PatchedSlotDelta).validate()
    with pytest.raises(ContractViolation, match="禁止修改"):
        PatchedSlotDelta(station_id="ST10", modified_slots=["slot2_OpMode"]).validate()
    with pytest.raises(ContractViolation, match="非法槽位"):
        PatchedSlotDelta(station_id="ST10", modified_slots=["slot99_Bogus"]).validate()


def test_self_heal_request_validation() -> None:
    req = SelfHealRequest(
        retry_attempt=1,
        max_retries=3,
        compiler_errors=[CompileErrorItem(block_name="FB_ST10", tia_description="字段未定义")],
        available_struct_definition=AvailableStructDefinition(type_name="UDT_AxisStatus", fields=["xInPos"]),
    )
    req.validate()
    with pytest.raises(ContractViolation, match="retry_attempt"):
        SelfHealRequest(retry_attempt=4, max_retries=3, compiler_errors=[CompileErrorItem()]).validate()
    with pytest.raises(ContractViolation, match="不能为空"):
        SelfHealRequest().validate()


def test_writeback_result_failed_blocks_deduplicated() -> None:
    result = from_dict(WritebackResult, to_dict(_sample(WritebackResult)))
    result.errors.append(CompileErrorItem(block_name="FB_ST10_Main", tia_description="另一处错误"))
    assert result.failed_block_names == ["FB_ST10_Main"]


def test_normalized_ast_all_writes() -> None:
    ast = from_dict(NormalizedBlockAst, to_dict(_sample(NormalizedBlockAst)))
    assert ast.all_writes == []  # 样本只有语句没有 assignments
    ast.networks[0].assignments.append(Assignment(lhs_symbol='"Q_Work"'))
    assert ast.all_writes == ['"Q_Work"']


def test_version_marker() -> None:
    assert CONTRACT_VERSION == "3.0"
