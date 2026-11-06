"""spec_diff.py 单测（WP-04 / F17 / F6 / 契约 §2.3 / UC-14）。

零耦合：用 SimpleNamespace 构造 mock 规格，不 import A 的 FrozenSpec / GreenfieldIR。
覆盖：changed/added/removed 带 source_id、compute_spec_diff 版本传递、
F6 派生层纯函数（唯一 source_id / 分栏 / baseline_manifest）与可复现性。
"""
from __future__ import annotations

from types import SimpleNamespace

from plc_engine.af.spec_diff import (
    DERIVED_PARTITION,
    FRAMEWORK_BASELINE_PARTITION,
    SourceBlock,
    SpecDiff,
    build_baseline_manifest,
    canonical_hash,
    compute_spec_diff,
    diff_source_blocks,
    extract_source_blocks,
    partition_for_block,
    sha256_prefixed,
    spec_version_of,
    stable_source_id,
)


def test_diff_changed_added_removed_carry_source_ids():
    base = {
        "UNIT_1": SourceBlock("UNIT_1", "unit", {"label": "A"}),
        "EM_2": SourceBlock("EM_2", "em", {"label": "B"}),
        "CM_9": SourceBlock("CM_9", "cm", {"label": "OLD"}),
    }
    target = {
        "UNIT_1": SourceBlock("UNIT_1", "unit", {"label": "A"}),
        "EM_2": SourceBlock("EM_2", "em", {"label": "B_MODIFIED"}),
        "CM_10": SourceBlock("CM_10", "cm", {"label": "NEW"}),
    }
    d = diff_source_blocks(base, target, 1, 2)

    assert isinstance(d, SpecDiff)
    assert [b.source_id for b in d.changed] == ["EM_2"]
    assert [b.source_id for b in d.added] == ["CM_10"]
    assert [b.source_id for b in d.removed] == ["CM_9"]
    assert d.base_spec_version == 1
    assert d.target_spec_version == 2
    assert set(d.changed_source_ids) == {"EM_2", "CM_10", "CM_9"}
    for blk in d.changed + d.added + d.removed:
        assert blk.source_id


def test_identical_blocks_produce_empty_diff():
    blocks = {"A": SourceBlock("A", "unit", {"v": 1})}
    d = diff_source_blocks(blocks, dict(blocks), 3, 4)
    assert d.changed == ()
    assert d.added == ()
    assert d.removed == ()
    assert d.changed_source_ids == ()


def test_compute_spec_diff_with_mock_specs():
    v1 = SimpleNamespace(
        version=1, project_id="P", spec_hash="sha256:x",
        ir_snapshot={"source_objects": [
            {"source_id": "U1", "kind": "unit", "label": "v1"},
            {"source_id": "E1", "kind": "edge"},
        ]},
    )
    v2 = SimpleNamespace(
        version=2, project_id="P", spec_hash="sha256:y",
        ir_snapshot={"source_objects": [
            {"source_id": "U1", "kind": "unit", "label": "v2"},
            {"source_id": "E1", "kind": "edge"},
            {"source_id": "C1", "kind": "cm"},
        ]},
    )
    d = compute_spec_diff(v1, v2)
    assert d.base_spec_version == 1
    assert d.target_spec_version == 2
    assert "U1" in [b.source_id for b in d.changed]
    assert "C1" in [b.source_id for b in d.added]
    assert "C1" in d.changed_source_ids


def test_compute_spec_diff_explicit_blocks_bypass_ir():
    """显式传入 blocks 即完全绕过 A 的 IR 结构（并行期零耦合）。"""
    base = {"X": SourceBlock("X", "unit", {"v": 1})}
    target = {"X": SourceBlock("X", "unit", {"v": 2})}
    d = compute_spec_diff(
        SimpleNamespace(version=5),
        SimpleNamespace(version=6),
        base_blocks=base,
        target_blocks=target,
    )
    assert d.base_spec_version == 5
    assert d.target_spec_version == 6
    assert [b.source_id for b in d.changed] == ["X"]


def test_extract_source_blocks_explicit_ids_and_fallback():
    spec = SimpleNamespace(
        ir_snapshot={"expected_source_ids": ["UNIT_1", "EDGE_7"]},
    )
    blocks = extract_source_blocks(spec)
    assert set(blocks) == {"UNIT_1", "EDGE_7"}
    assert all(isinstance(b, SourceBlock) for b in blocks.values())

    fallback = SimpleNamespace(
        ir_snapshot={"units": [{"name": "U9"}]},
    )
    assert "U9" in extract_source_blocks(fallback)


def test_stable_source_id_unique_and_reproducible():
    a = stable_source_id("U1_Unit", "FB", "unit", 1)
    assert a == stable_source_id("U1_Unit", "FB", "unit", 1)
    assert a != stable_source_id("U2_Unit", "FB", "unit", 2)
    assert "U1_Unit" in a


def test_partition_for_block():
    assert partition_for_block("01_AF_Standard_Library", "LAF_Base", "lib", "FB") == FRAMEWORK_BASELINE_PARTITION
    assert partition_for_block("00_Types_UDT", "UDT_A", "", "UDT") == FRAMEWORK_BASELINE_PARTITION
    assert partition_for_block("10_Unit_Supervision", "U1", "unit", "FB") == DERIVED_PARTITION


def test_build_baseline_manifest_deterministic_uc14():
    entries = [
        {"source_id": "LAF_B", "name": "LAF_B", "sha256": sha256_prefixed("B")},
        {"source_id": "LAF_A", "name": "LAF_A", "sha256": sha256_prefixed("A")},
    ]
    m1 = build_baseline_manifest(entries, "af-basic-folder-1.0")
    m2 = build_baseline_manifest(list(reversed(entries)), "af-basic-folder-1.0")
    assert m1["manifest_sha256"] == m2["manifest_sha256"]
    assert m1["framework_baseline_version"] == "af-basic-folder-1.0"
    assert m1["entry_count"] == 2
    assert [e["source_id"] for e in m1["entries"]] == ["LAF_A", "LAF_B"]
    for e in m1["entries"]:
        assert e["content_sha256"].startswith("sha256:")
        assert "content" not in e


def test_canonical_hash_deterministic():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert canonical_hash({"a": 1}).startswith("sha256:")


def test_spec_version_of_tolerant():
    assert spec_version_of(SimpleNamespace(version=7)) == 7
    assert spec_version_of(SimpleNamespace(spec_version=3)) == 3
    assert spec_version_of({"version": "v9"}) == 9
