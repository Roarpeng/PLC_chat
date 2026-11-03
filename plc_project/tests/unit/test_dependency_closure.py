"""dependency_closure 单测：反向依赖闭包 / 接口传播 / 环与外部块边界。

全部用手写 BlockArtifact 驱动，离线可跑，不碰 mega_source 导入管线。
"""

from __future__ import annotations

import pytest

from plc_engine.dependency_closure import (
    ClosureResult,
    build_reverse_index,
    dependents_closure,
    interface_closure,
    mark_interface_change,
)
from plc_engine.writeback_contract import BlockArtifact


def _blk(
    name: str,
    kind: str,
    deps: list[str] | None = None,
    *,
    interface_changed: bool = False,
) -> BlockArtifact:
    return BlockArtifact(
        name=name,
        kind=kind,
        source=f"// {name}\n",
        dependencies=list(deps or []),
        interface_changed=interface_changed,
    )


def _chain_4() -> list[BlockArtifact]:
    """UDT_ST10_AutoCmd <- FB_ST10 <- FB_Line <- OB1（4 层真实链路）。"""
    return [
        _blk("UDT_ST10_AutoCmd", "UDT", interface_changed=True),
        _blk("FB_ST10", "FB", ["UDT_ST10_AutoCmd"]),
        _blk("FB_Line", "FB", ["FB_ST10"]),
        _blk("OB1", "OB", ["FB_Line"]),
    ]


# --------------------------------------------------------------------------- #
# 反向索引
# --------------------------------------------------------------------------- #
def test_build_reverse_index_flips_edges_and_keeps_original_names() -> None:
    blocks = _chain_4()
    reverse = build_reverse_index(blocks)

    assert reverse["UDT_ST10_AutoCmd"] == {"FB_ST10"}
    assert reverse["FB_ST10"] == {"FB_Line"}
    assert reverse["FB_Line"] == {"OB1"}
    assert "OB1" not in reverse  # 没有下游就没有条目


def test_build_reverse_index_is_case_insensitive() -> None:
    blocks = [
        _blk("FB_Pump", "FB", ["udt_motor"]),
        _blk("UDT_Motor", "UDT"),
    ]
    reverse = build_reverse_index(blocks)

    # 键用块自身的原始写法，不跟随依赖串的大小写
    assert reverse == {"UDT_Motor": {"FB_Pump"}}


# --------------------------------------------------------------------------- #
# 传递闭包
# --------------------------------------------------------------------------- #
def test_chain_closure_reaches_four_levels() -> None:
    result = dependents_closure(_chain_4(), ["UDT_ST10_AutoCmd"])

    assert isinstance(result, ClosureResult)
    assert result.selected == ["UDT_ST10_AutoCmd", "FB_Line", "FB_ST10", "OB1"]
    assert result.max_depth == 3
    assert result.reasons["UDT_ST10_AutoCmd"] == "seed"
    # 接口源头是 UDT，下游全部指回源头
    assert result.reasons["FB_ST10"] == "interface-propagation:UDT_ST10_AutoCmd"
    assert result.reasons["FB_Line"] == "interface-propagation:UDT_ST10_AutoCmd"
    assert result.reasons["OB1"] == "interface-propagation:UDT_ST10_AutoCmd"


def test_closure_from_middle_only_walks_downstream() -> None:
    result = dependents_closure(_chain_4(), ["FB_Line"])

    assert result.selected == ["FB_Line", "OB1"]  # 上游 UDT/FB_ST10 不在内
    assert result.reasons["OB1"] == "depends-on:FB_Line"


def test_dependents_reason_when_no_interface_change() -> None:
    blocks = [
        _blk("FB_A", "FB"),
        _blk("FB_B", "FB", ["FB_A"]),
    ]
    result = dependents_closure(blocks, ["FB_A"])

    assert result.reasons["FB_B"] == "depends-on:FB_A"


def test_diamond_dependency_is_deduped() -> None:
    blocks = [
        _blk("UDT_Station", "UDT"),
        _blk("FB_A", "FB", ["UDT_Station"]),
        _blk("FB_B", "FB", ["UDT_Station"]),
        _blk("OB1", "OB", ["FB_A", "FB_B"]),
    ]
    result = dependents_closure(blocks, ["UDT_Station"])

    assert result.selected == ["UDT_Station", "FB_A", "FB_B", "OB1"]
    assert len(result.selected) == len(set(result.selected))
    # 菱形汇合点只记首次发现的那条路径（遍历顺序固定 -> FB_A 在前）
    assert result.reasons["OB1"] == "depends-on:FB_A"


def test_multiple_seeds_are_merged_and_ordered() -> None:
    blocks = [
        _blk("UDT_A", "UDT"),
        _blk("UDT_B", "UDT"),
        _blk("FB_A", "FB", ["UDT_A"]),
        _blk("OB1", "OB", ["FB_A", "UDT_B"]),
    ]
    result = dependents_closure(blocks, ["FB_A", "UDT_B"])

    # 先 type_order（UDT 1 -> FB 3 -> OB 4），同序按名字
    assert result.selected == ["UDT_B", "FB_A", "OB1"]
    assert result.reasons["FB_A"] == "seed"
    assert result.reasons["UDT_B"] == "seed"


def test_seed_lookup_is_case_insensitive_but_output_keeps_original() -> None:
    result = dependents_closure(_chain_4(), ["udt_st10_autocmd"])

    assert result.selected[0] == "UDT_ST10_AutoCmd"


def test_result_is_deterministic_across_calls() -> None:
    blocks = _chain_4()
    first = dependents_closure(blocks, ["UDT_ST10_AutoCmd"])
    second = dependents_closure(blocks, ["UDT_ST10_AutoCmd"])

    assert first == second


# --------------------------------------------------------------------------- #
# 环
# --------------------------------------------------------------------------- #
def test_cycle_does_not_hang() -> None:
    blocks = [
        _blk("FB_A", "FB", ["FB_B"]),
        _blk("FB_B", "FB", ["FB_A"]),
    ]
    result = dependents_closure(blocks, ["FB_A"])

    assert result.selected == ["FB_A", "FB_B"]
    assert result.max_depth == 1
    assert result.reasons["FB_B"] == "depends-on:FB_A"


def test_long_cycle_with_tail_terminates() -> None:
    blocks = [
        _blk("FB_A", "FB", ["FB_B"]),
        _blk("FB_B", "FB", ["FB_C"]),
        _blk("FB_C", "FB", ["FB_A"]),
        _blk("OB1", "OB", ["FB_C"]),
    ]
    result = dependents_closure(blocks, ["OB1"])  # OB1 不在环里，环也不在它的下游
    assert result.selected == ["OB1"]

    result = dependents_closure(blocks, ["FB_A"])
    assert result.selected == ["FB_A", "FB_B", "FB_C", "OB1"]


# --------------------------------------------------------------------------- #
# max_depth
# --------------------------------------------------------------------------- #
def test_max_depth_boundary_is_inclusive() -> None:
    result = dependents_closure(_chain_4(), ["UDT_ST10_AutoCmd"], max_depth=3)
    assert len(result.selected) == 4


def test_max_depth_exceeded_raises_with_chain() -> None:
    blocks = [
        _blk("UDT_X", "UDT"),
        _blk("FB_1", "FB", ["UDT_X"]),
        _blk("FB_2", "FB", ["FB_1"]),
        _blk("FB_3", "FB", ["FB_2"]),
        _blk("OB1", "OB", ["FB_3"]),
    ]
    with pytest.raises(RecursionError) as excinfo:
        dependents_closure(blocks, ["UDT_X"], max_depth=2)

    message = str(excinfo.value)
    assert "max_depth=2" in message
    # 链路上的块名都要能看见，方便定位
    assert "UDT_X -> FB_1 -> FB_2 -> FB_3" in message


def test_negative_max_depth_is_rejected() -> None:
    with pytest.raises(ValueError):
        dependents_closure(_chain_4(), ["OB1"], max_depth=-1)


# --------------------------------------------------------------------------- #
# 未知种子 / 空输入
# --------------------------------------------------------------------------- #
def test_unknown_seed_raises_key_error() -> None:
    with pytest.raises(KeyError):
        dependents_closure(_chain_4(), ["FB_NotExist"])


def test_unknown_seed_among_valid_ones_raises_before_building() -> None:
    with pytest.raises(KeyError):
        dependents_closure(_chain_4(), ["FB_Line", "FB_NotExist"])


def test_empty_input_returns_empty_result() -> None:
    empty = dependents_closure([], [])

    assert empty.selected == []
    assert empty.reasons == {}
    assert empty.max_depth == 0
    assert build_reverse_index([]) == {}
    assert interface_closure([]) == ClosureResult()


def test_empty_seeds_with_blocks_returns_empty_result() -> None:
    result = dependents_closure(_chain_4(), [])

    assert result.selected == []
    assert result.max_depth == 0


# --------------------------------------------------------------------------- #
# 外部标准库依赖
# --------------------------------------------------------------------------- #
def test_external_dependency_recorded_in_reasons_only() -> None:
    blocks = [
        _blk("UDT_Station", "UDT"),
        _blk("FB_Line", "FB", ["UDT_Station"]),
        _blk("OB1", "OB", ["FB_Line", "LAF_ControlSclSequence"]),
    ]
    result = dependents_closure(blocks, ["UDT_Station"])

    assert "LAF_ControlSclSequence" not in result.selected
    assert result.reasons["LAF_ControlSclSequence"] == "external:LAF_ControlSclSequence"
    assert result.selected == ["UDT_Station", "FB_Line", "OB1"]


def test_external_dependency_is_case_preserved_and_quotes_stripped() -> None:
    blocks = [
        _blk("FB_Line", "FB", ['"LAF_ControlSclSequence"']),
    ]
    result = dependents_closure(blocks, ["FB_Line"])

    assert result.reasons["LAF_ControlSclSequence"] == "external:LAF_ControlSclSequence"


def test_external_blocks_not_pulled_into_closure() -> None:
    """外部块即使被引用，也不能成为可遍历的下游节点。"""
    blocks = [
        _blk("FB_A", "FB", ["FB_Std"]),
        _blk("OB1", "OB", ["FB_A"]),
    ]
    result = dependents_closure(blocks, ["FB_A"], max_depth=1)

    assert result.selected == ["FB_A", "OB1"]
    assert "FB_Std" in result.reasons  # 记账
    assert "FB_Std" not in result.selected


# --------------------------------------------------------------------------- #
# interface_closure
# --------------------------------------------------------------------------- #
def test_interface_closure_uses_flagged_blocks_as_seeds() -> None:
    blocks = _chain_4()  # 只有 UDT 带 interface_changed
    result = interface_closure(blocks)

    assert result.selected == ["UDT_ST10_AutoCmd", "FB_Line", "FB_ST10", "OB1"]
    assert result.reasons["FB_ST10"] == "interface-propagation:UDT_ST10_AutoCmd"


def test_interface_closure_accepts_explicit_changed_list() -> None:
    blocks = [
        _blk("UDT_A", "UDT"),
        _blk("FB_A", "FB", ["UDT_A"]),
        _blk("FB_Other", "FB"),
    ]
    result = interface_closure(blocks, changed=["udt_a"])  # 大小写不敏感

    assert result.selected == ["UDT_A", "FB_A"]
    assert result.reasons["UDT_A"] == "seed"


def test_interface_closure_empty_changed_list_is_empty() -> None:
    result = interface_closure(_chain_4(), changed=[])

    assert result.selected == []
    assert result.max_depth == 0


def test_interface_closure_unknown_name_raises_key_error() -> None:
    with pytest.raises(KeyError):
        interface_closure(_chain_4(), changed=["UDT_NotExist"])


# --------------------------------------------------------------------------- #
# mark_interface_change
# --------------------------------------------------------------------------- #
def test_mark_interface_change_returns_new_objects_and_leaves_input_intact() -> None:
    blocks = [
        _blk("UDT_X", "UDT", interface_changed=True),
        _blk("FB_X", "FB", ["UDT_X"]),
        _blk("OB1", "OB", ["FB_X"]),
        _blk("FB_Isolated", "FB"),
    ]
    marked = mark_interface_change(blocks)

    assert [b.name for b in marked] == [b.name for b in blocks]  # 顺序不变
    for original, new in zip(blocks, marked, strict=True):
        assert id(original) != id(new)  # 全量 replace，不共享可变对象
        assert new.dependencies is not original.dependencies

    # 入参没被改：FB_X / OB1 原对象仍是 False
    assert blocks[1].interface_changed is False
    assert blocks[2].interface_changed is False

    # 出参沿正向依赖传播
    assert marked[0].interface_changed is True
    assert marked[1].interface_changed is True
    assert marked[2].interface_changed is True
    assert marked[3].interface_changed is False


def test_mark_interface_change_handles_cycle() -> None:
    blocks = [
        _blk("FB_A", "FB", ["FB_B"], interface_changed=True),
        _blk("FB_B", "FB", ["FB_A"]),
    ]
    marked = mark_interface_change(blocks)

    assert all(b.interface_changed for b in marked)
    assert blocks[1].interface_changed is False


def test_mark_interface_change_then_interface_closure_full_chain() -> None:
    """先标注再取闭包：标记后的下游块自己就能当种子，结果一致。"""
    blocks = [
        _blk("UDT_X", "UDT", interface_changed=True),
        _blk("FB_X", "FB", ["UDT_X"]),
        _blk("OB1", "OB", ["FB_X"]),
    ]
    marked = mark_interface_change(blocks)
    result = interface_closure(marked)

    assert result.selected == ["UDT_X", "FB_X", "OB1"]


def test_mark_interface_change_empty_input() -> None:
    assert mark_interface_change([]) == []


# --------------------------------------------------------------------------- #
# 真实场景推演：改 UDT_ST10_AutoCmd 的一个字段
# --------------------------------------------------------------------------- #
def test_real_scenario_udt_field_change_brings_whole_line() -> None:
    blocks = [
        _blk("UDT_ST10_AutoCmd", "UDT", interface_changed=True),
        _blk("FB_ST10", "FB", ["UDT_ST10_AutoCmd"]),
        _blk("FB_ST11", "FB", ["UDT_ST10_AutoCmd"]),
        _blk("FB_Line", "FB", ["FB_ST10", "FB_ST11"]),
        _blk("DB_ST10_AutoCmd", "INSTANCE_DB", ["FB_ST10"]),
        _blk("OB1", "OB", ["FB_Line", "DB_ST10_AutoCmd"]),
    ]
    result = interface_closure(blocks)

    assert result.selected == [
        "UDT_ST10_AutoCmd",
        "FB_Line",
        "FB_ST10",
        "FB_ST11",
        "DB_ST10_AutoCmd",
        "OB1",
    ]
    assert result.max_depth == 3
    assert result.reasons["FB_Line"] == "interface-propagation:UDT_ST10_AutoCmd"
    assert result.reasons["DB_ST10_AutoCmd"] == "interface-propagation:UDT_ST10_AutoCmd"
