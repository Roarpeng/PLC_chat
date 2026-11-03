"""to_fast_writeback_request 的接线契约测试。

真机背景（TIA Portal V19 / HR001）：C# FastWriteback 用
``InterfaceChanged || HasUdtOrGlobalDbChange`` 决定编译范围。漏传接口变更标记
会走 incremental_blocks，GenerateBlocksFromSource 不刷新已存在的 Instance DB，
编译报 928 条 "The data block is not up-to-date..."；正确标记后走
full_software_interface_changed，同类错误降为 0。
"""

from __future__ import annotations

import pytest

from agents.plc.tia.writeback_batch import (
    BatchWritebackPlan,
    to_fast_writeback_request,
)
from plc_engine.contracts import AfBatchSource
from plc_engine.writeback_contract import BlockArtifact

_SCL = 'FUNCTION_BLOCK "FB_A"\nBEGIN\nEND_FUNCTION_BLOCK\n'


def _block(name: str, *, kind: str = "FB", interface_changed: bool = False) -> BlockArtifact:
    return BlockArtifact(
        name=name,
        kind=kind,
        source=_SCL,
        interface_changed=interface_changed,
    )


def _plan(
    names: list[str],
    *,
    blocked: bool = False,
    bundle: str = "AF_Batch.scl",
    skipped: list[str] | None = None,
) -> BatchWritebackPlan:
    return BatchWritebackPlan(
        bundle_path=bundle,
        af_batch=AfBatchSource(
            path=bundle,
            sha256="deadbeef",
            block_names=list(names),
            skipped_unchanged=list(skipped or []),
            has_utf8_bom=True,
        ),
        block_count=len(names),
        skipped_count=len(skipped or []),
        blocked=blocked,
    )


def test_no_interface_change_stays_incremental() -> None:
    plan = _plan(["FB_A", "FB_B"])
    blocks = [_block("FB_A"), _block("FB_B")]
    req = to_fast_writeback_request(plan, blocks)
    assert req["interfaceChanged"] is False
    assert req["hasUdtOrGlobalDbChange"] is False


def test_interface_change_triggers_full_compile() -> None:
    plan = _plan(["FB_A", "FB_B"])
    blocks = [_block("FB_A"), _block("FB_B", interface_changed=True)]
    req = to_fast_writeback_request(plan, blocks)
    assert req["interfaceChanged"] is True
    assert req["hasUdtOrGlobalDbChange"] is True


def test_udt_in_batch_triggers_full_compile() -> None:
    plan = _plan(["UDT_Station", "FB_A"])
    blocks = [_block("UDT_Station", kind="UDT"), _block("FB_A")]
    req = to_fast_writeback_request(plan, blocks)
    assert req["interfaceChanged"] is False
    assert req["hasUdtOrGlobalDbChange"] is True


def test_global_db_in_batch_triggers_full_compile() -> None:
    plan = _plan(["DB_Global"])
    blocks = [_block("DB_Global", kind="GLOBAL_DB")]
    req = to_fast_writeback_request(plan, blocks)
    assert req["hasUdtOrGlobalDbChange"] is True


def test_force_full_compile_override() -> None:
    plan = _plan(["FB_A"])
    req = to_fast_writeback_request(plan, [_block("FB_A")], force_full_compile=True)
    assert req["hasUdtOrGlobalDbChange"] is True
    # 不谎报接口变更：仅编译策略被强制。
    assert req["interfaceChanged"] is False


def test_blocked_plan_is_rejected() -> None:
    plan = _plan(["FB_A"], blocked=True)
    with pytest.raises(ValueError, match="门禁"):
        to_fast_writeback_request(plan, [_block("FB_A")])


def test_empty_bundle_is_rejected() -> None:
    plan = _plan(["FB_A"], bundle="")
    with pytest.raises(ValueError, match="无需回写"):
        to_fast_writeback_request(plan, [_block("FB_A")])


def test_payload_shape_and_counts() -> None:
    plan = _plan(["FB_A", "FB_B"], skipped=["FB_C"])
    req = to_fast_writeback_request(
        plan,
        [_block("FB_A"), _block("FB_B")],
        exclusive_access_reason="真机验收",
    )
    assert req["scl"] == "AF_Batch.scl"
    assert req["blockNames"] == ["FB_A", "FB_B"]
    assert req["writtenBlockCount"] == 2
    assert req["skippedUnchangedBlocks"] == 1
    assert req["exclusiveAccessReason"] == "真机验收"
    # 字段名必须是 C# FastWritebackRequest.FromJson 认得的 camelCase。
    assert set(req) == {
        "scl",
        "interfaceChanged",
        "hasUdtOrGlobalDbChange",
        "blockNames",
        "skippedUnchangedBlocks",
        "writtenBlockCount",
        "exclusiveAccessReason",
    }


def test_block_name_matching_is_case_insensitive() -> None:
    plan = _plan(["FB_A", "FB_B"])
    blocks = [_block("fb_a", interface_changed=True), _block("fb_b")]
    req = to_fast_writeback_request(plan, blocks)
    assert req["interfaceChanged"] is True


def test_unknown_block_names_do_not_break_inference() -> None:
    """blockNames 里的块不在 blocks 集合中（如标准库）时不能崩，只是不参与推断。"""
    plan = _plan(["FB_A", "LAF_ControlSclSequence"])
    req = to_fast_writeback_request(plan, [_block("FB_A")])
    assert req["interfaceChanged"] is False
    assert "LAF_ControlSclSequence" in req["blockNames"]
