"""回写链路编排层测试。

样本尽量贴近真实博世 AF 产物：UDT ← 工站 FB ← 背景 DB ← OB。
"""

from __future__ import annotations

import pytest

from plc_engine.writeback_contract import BlockArtifact
from plc_engine.writeback_pipeline import (
    WritebackBlocked,
    build_plan,
    materialize,
    plan_for_block_names,
)

UDT_SRC = """TYPE "UDT_ST10_AutoCmd"
VERSION : 0.1
   STRUCT
      xHome : Bool;
      xWork : Bool;
   END_STRUCT;
END_TYPE
"""

FB_SRC = """FUNCTION_BLOCK "FB_ST10_Main"
{ S7_Optimized_Access := 'TRUE' }
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

OB_SRC = """ORGANIZATION_BLOCK "OB1_Main"
BEGIN
   "IDB_ST10_Main"();
END_ORGANIZATION_BLOCK
"""

BAD_SRC = """FUNCTION_BLOCK "FB_Bad"
VAR
   xGo : Bool;
END_VAR
BEGIN
   "Q_Test_Valve" := #xGo;
END_FUNCTION_BLOCK
"""


def _blocks() -> list[BlockArtifact]:
    return [
        BlockArtifact(
            name="UDT_ST10_AutoCmd", kind="UDT", source=UDT_SRC, interface_changed=True
        ),
        BlockArtifact(
            name="FB_ST10_Main",
            kind="FB",
            source=FB_SRC,
            dependencies=["UDT_ST10_AutoCmd"],
        ),
        BlockArtifact(
            name="IDB_ST10_Main",
            kind="INSTANCE_DB",
            source=IDB_SRC,
            dependencies=["FB_ST10_Main"],
        ),
        # OB 只通过背景 DB 调用工站，不直连 FB —— 与博世 AF 产物一致
        BlockArtifact(
            name="OB1_Main",
            kind="OB",
            source=OB_SRC,
            dependencies=["IDB_ST10_Main"],
        ),
    ]


def test_interface_seed_pulls_whole_chain() -> None:
    plan = build_plan(_blocks(), seeds=["UDT_ST10_AutoCmd"])
    assert set(plan.selected) == {
        "UDT_ST10_AutoCmd",
        "FB_ST10_Main",
        "IDB_ST10_Main",
        "OB1_Main",
    }
    assert plan.max_depth >= 3
    assert plan.reasons["UDT_ST10_AutoCmd"] == "seed"


def test_bundle_puts_udt_before_dependents() -> None:
    plan = build_plan(_blocks(), seeds=["UDT_ST10_AutoCmd"])
    assert plan.writable
    text = plan.planned_text or ""
    assert text.index("TYPE") < text.index("FUNCTION_BLOCK") < text.index("ORGANIZATION_BLOCK")


def test_full_rebuild_selects_everything() -> None:
    plan = build_plan(_blocks())
    assert len(plan.selected) == 4
    assert set(plan.reasons.values()) == {"seed"}


def test_no_cache_means_nothing_skipped() -> None:
    plan = build_plan(_blocks(), seeds=["FB_ST10_Main"])
    assert plan.skipped_unchanged == []
    assert "FB_ST10_Main" in plan.block_names


def test_second_run_skips_everything() -> None:
    first = build_plan(_blocks(), seeds=["UDT_ST10_AutoCmd"])
    second = build_plan(_blocks(), seeds=["UDT_ST10_AutoCmd"], cache=first.cache)
    assert set(second.skipped_unchanged) == set(first.selected)
    assert second.planned_text == ""


def test_cache_holds_all_blocks_not_only_dirty() -> None:
    plan = build_plan(_blocks(), seeds=["FB_ST10_Main"])
    assert set(plan.cache) == {"FB_ST10_Main", "IDB_ST10_Main", "OB1_Main"}


def test_lint_error_blocks_writeback() -> None:
    blocks = [
        BlockArtifact(name="FB_Bad", kind="FB", source=BAD_SRC),
        *_blocks(),
    ]
    plan = build_plan(blocks, seeds=["FB_Bad"])
    assert plan.has_errors
    assert not plan.writable
    assert plan.planned_text is None


def test_materialize_refuses_dirty_plan() -> None:
    blocks = [BlockArtifact(name="FB_Bad", kind="FB", source=BAD_SRC)]
    plan = build_plan(blocks)
    with pytest.raises(WritebackBlocked):
        materialize(plan, "unused.scl")


def test_materialize_writes_utf8_bom(tmp_path) -> None:
    plan = build_plan(_blocks(), seeds=["FB_ST10_Main"])
    out = materialize(plan, tmp_path / "AF_Batch.scl")
    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"
    assert b"\r\n" not in raw


def test_unknown_seed_raises() -> None:
    with pytest.raises(KeyError):
        build_plan(_blocks(), seeds=["FB_NotExist"])


def test_empty_input_is_noop() -> None:
    plan = build_plan([])
    assert plan.selected == []
    assert not plan.writable


def test_external_dependency_recorded() -> None:
    src = FB_SRC.replace(
        "#statStep := 20;",
        '#statStep := 20;\n   "LAF_ControlSclSequence"();',
    )
    blocks = [
        BlockArtifact(
            name="FB_ST10_Main",
            kind="FB",
            source=src,
            dependencies=["UDT_ST10_AutoCmd", "LAF_ControlSclSequence"],
        )
    ]
    plan = build_plan(blocks, seeds=["FB_ST10_Main"])
    assert "LAF_ControlSclSequence" in plan.external_dependencies
    assert "LAF_ControlSclSequence" not in plan.selected


def test_plan_for_block_names_shorthand() -> None:
    plan = plan_for_block_names(_blocks(), ["IDB_ST10_Main"])
    assert "IDB_ST10_Main" in plan.selected
    assert "OB1_Main" in plan.selected
    assert "UDT_ST10_AutoCmd" not in plan.selected
