"""mega_source 单元测试：拓扑排序、脏块过滤、合并拼接与 BOM 落盘。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_engine.mega_source import (
    BundleResult,
    CycleError,
    DuplicateBlockError,
    bundle,
    filter_dirty,
    topological_sort,
    write_bundle,
)
from plc_engine.writeback_contract import BlockArtifact


def make_udt(name: str, deps: list[str] | None = None) -> BlockArtifact:
    return BlockArtifact(
        name=name,
        kind="UDT",
        source=f'TYPE "{name}"\nSTRUCT\n   x : Bool;\nEND_STRUCT\nEND_TYPE',
        dependencies=list(deps or []),
    )


def make_fb(name: str, deps: list[str] | None = None) -> BlockArtifact:
    return BlockArtifact(
        name=name,
        kind="FB",
        source=(
            f'FUNCTION_BLOCK "{name}"\nVAR\n   stat : Bool;\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK'
        ),
        dependencies=list(deps or []),
    )


def make_idb(name: str, deps: list[str] | None = None) -> BlockArtifact:
    return BlockArtifact(
        name=name,
        kind="INSTANCE_DB",
        source=f'DATA_BLOCK "{name}"\nEND_DATA_BLOCK',
        dependencies=list(deps or []),
    )


# ---------------------------------------------------------------- 拓扑排序


def test_topological_sort_udt_fb_idb() -> None:
    """UDT 必须先于 FB，FB 必须先于实例 DB。"""
    blocks = [
        make_idb("DB_Cyl", ["FB_Cyl"]),
        make_fb("FB_Cyl", ["UDT_Cyl"]),
        make_udt("UDT_Cyl"),
    ]
    ordered = topological_sort(blocks)
    assert [b.name for b in ordered] == ["UDT_Cyl", "FB_Cyl", "DB_Cyl"]


def test_topological_sort_same_layer_sorted_by_name() -> None:
    """同层按 (type_order, name) 稳定排序，且两次调用完全一致。"""
    blocks = [
        make_fb("FB_Zeta"),
        make_fb("FB_Alpha"),
        make_udt("UDT_Step"),
        make_fb("FB_Mid", ["UDT_Step"]),
    ]
    first = [b.name for b in topological_sort(blocks)]
    second = [b.name for b in topological_sort(list(reversed(blocks)))]
    assert first == second
    # UDT 层在 FB 层之前；同层内按名字字母序
    assert first == ["UDT_Step", "FB_Alpha", "FB_Zeta", "FB_Mid"]


def test_topological_sort_keeps_dependency_before_dependent() -> None:
    """依赖链比名字序优先：FB_A 依赖 FB_Z 时 Z 必须在前。"""
    blocks = [make_fb("FB_A", ["FB_Z"]), make_fb("FB_Z")]
    assert [b.name for b in topological_sort(blocks)] == ["FB_Z", "FB_A"]


# ---------------------------------------------------------------- 成环


def test_cycle_raises_with_cycle_names() -> None:
    """A → B → C → A 必须抛 CycleError，cycle 长度 3 且覆盖三个块。"""
    blocks = [
        make_fb("FB_A", ["FB_B"]),
        make_fb("FB_B", ["FB_C"]),
        make_fb("FB_C", ["FB_A"]),
    ]
    with pytest.raises(CycleError) as excinfo:
        topological_sort(blocks)
    cycle = excinfo.value.cycle
    assert len(cycle) == 3
    assert set(cycle) == {"FB_A", "FB_B", "FB_C"}


def test_self_dependency_is_cycle() -> None:
    """块依赖自己也算环，不能被静默丢弃。"""
    with pytest.raises(CycleError) as excinfo:
        topological_sort([make_fb("FB_Self", ["FB_Self"])])
    assert excinfo.value.cycle == ["FB_Self"]


# ---------------------------------------------------------------- 外部依赖


def test_external_dependency_is_not_error() -> None:
    """依赖博世标准库 LAF_xxx 不报错，收进 external_dependencies 且去重排序。"""
    blocks = [
        make_fb("FB_A", ["LAF_ControlSclSequence", "UDT_A", "LAF_Zeta"]),
        make_fb("FB_B", ["LAF_Zeta"]),
        make_udt("UDT_A"),
    ]
    result = bundle(blocks)
    assert result.external_dependencies == ["LAF_ControlSclSequence", "LAF_Zeta"]
    # FB_A 因依赖 UDT_A 落到下一层，故排在无依赖的 FB_B 之后
    assert result.block_names == ["UDT_A", "FB_B", "FB_A"]


# ---------------------------------------------------------------- 脏块


def test_filter_dirty_all_cached_returns_empty() -> None:
    blocks = [make_udt("UDT_A"), make_fb("FB_A", ["UDT_A"])]
    _, cache = filter_dirty(blocks, {})
    dirty, new_cache = filter_dirty(blocks, cache)
    assert dirty == []
    # 未变的块也要回填，否则下一轮又全量
    assert set(new_cache) == {"UDT_A", "FB_A"}


def test_filter_dirty_only_changed_block() -> None:
    blocks = [make_udt("UDT_A"), make_fb("FB_A", ["UDT_A"]), make_fb("FB_B")]
    _, cache = filter_dirty(blocks, {})
    blocks[1].source = blocks[1].source.replace("stat : Bool", "stat : Int")
    dirty, new_cache = filter_dirty(blocks, cache)
    assert [b.name for b in dirty] == ["FB_A"]
    assert set(new_cache) == {"UDT_A", "FB_A", "FB_B"}
    assert new_cache["FB_A"] == blocks[1].sha256()


def test_filter_dirty_new_block_is_dirty() -> None:
    blocks = [make_udt("UDT_A")]
    _, cache = filter_dirty(blocks, {})
    dirty, _ = filter_dirty([*blocks, make_fb("FB_New")], cache)
    assert [b.name for b in dirty] == ["FB_New"]


def test_bundle_skips_unchanged_when_cache_given() -> None:
    """keep_unchanged=False + cache 命中时块不重复写出，但仍参与依赖图。"""
    blocks = [make_udt("UDT_A"), make_fb("FB_A", ["UDT_A"])]
    _, cache = filter_dirty(blocks, {})
    result = bundle(blocks, cache=cache)
    assert result.skipped_unchanged == ["UDT_A", "FB_A"]
    assert result.block_names == []
    assert result.text == ""
    assert result.external_dependencies == []

    kept = bundle(blocks, keep_unchanged=True, cache=cache)
    assert kept.skipped_unchanged == []
    assert kept.block_names == ["UDT_A", "FB_A"]


# ---------------------------------------------------------------- 重复块


def test_duplicate_block_name_case_insensitive() -> None:
    blocks = [make_fb("FB_A"), make_fb("fb_a")]
    with pytest.raises(DuplicateBlockError):
        bundle(blocks)
    with pytest.raises(DuplicateBlockError):
        topological_sort(blocks)


# ---------------------------------------------------------------- 拼接与落盘


def test_bundle_text_layout() -> None:
    """块之间恰好一个空行，文件末尾恰好一个换行。"""
    blocks = [make_udt("UDT_A"), make_fb("FB_A", ["UDT_A"])]
    result = bundle(blocks)
    assert isinstance(result, BundleResult)
    assert result.text == (
        'TYPE "UDT_A"\nSTRUCT\n   x : Bool;\nEND_STRUCT\nEND_TYPE\n\n'
        'FUNCTION_BLOCK "FB_A"\nVAR\n   stat : Bool;\nEND_VAR\n'
        "BEGIN\nEND_FUNCTION_BLOCK\n"
    )
    assert result.text.endswith("\n") and not result.text.endswith("\n\n")
    assert "\n\n\n" not in result.text


def test_write_bundle_has_utf8_bom(tmp_path: Path) -> None:
    blocks = [make_udt("UDT_A"), make_fb("FB_A", ["UDT_A"])]
    target = tmp_path / "out" / "mega.scl"
    written = write_bundle(blocks, target)
    assert written == target
    raw = target.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"
    assert raw.decode("utf-8-sig") == bundle(blocks).text
    # BOM 后不能出现 CRLF，否则博途会多出空行
    assert b"\r\n" not in raw


def test_write_bundle_chinese_comment_roundtrip(tmp_path: Path) -> None:
    block = BlockArtifact(
        name="FB_Cn",
        kind="FB",
        source='FUNCTION_BLOCK "FB_Cn"\n// 气缸伸出\nVAR\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK',
    )
    target = write_bundle([block], tmp_path / "cn.scl")
    assert "// 气缸伸出" in target.read_bytes().decode("utf-8-sig")


# ---------------------------------------------------------------- 名字一致性


def test_name_mismatch_raises() -> None:
    """source 里是 FB_A，artifact.name 是 FB_B → 报错并同时说明两者。"""
    block = make_fb("FB_A")
    block.name = "FB_B"
    with pytest.raises(ValueError) as excinfo:
        bundle([block])
    message = str(excinfo.value)
    assert "FB_A" in message and "FB_B" in message


def test_unparsable_source_raises() -> None:
    block = BlockArtifact(name="FB_X", kind="FB", source="// 只有注释\nx := 1;")
    with pytest.raises(ValueError, match="无法从 source 中解析出块名"):
        bundle([block])


def test_empty_source_raises() -> None:
    block = BlockArtifact(name="FB_X", kind="FB", source="   \n\n")
    with pytest.raises(ValueError, match="source 为空"):
        bundle([block])


def test_bundle_empty_input() -> None:
    result = bundle([])
    assert result.text == ""
    assert result.block_names == []
    assert result.external_dependencies == []
    assert result.skipped_unchanged == []
