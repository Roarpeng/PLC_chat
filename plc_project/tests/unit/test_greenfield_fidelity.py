"""fidelity.py 单测（WP-05 / F7 / F19 / 契约 §2.5 / UC-08～UC-11、UC-14）。

只读校验器：零耦合 A 的模块，用 SimpleNamespace 构造 mock 规格、用 JSON 描述符
构造 mock 产物。覆盖：最小样例 fidelity_ok、漏映射、臆造孤儿、基线漂移、
SpecDiff 联动增量字段、tia_side_drift fail-closed、ob_number_deviations 留痕、
可复现性、离线 pending_real_machine。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from plc_engine.af.fidelity import FidelityChecker, FidelityReport
from plc_engine.af.spec_diff import (
    SourceBlock,
    SpecDiff,
    build_baseline_manifest,
    sha256_prefixed,
    stable_source_id,
)

SPEC_HASH = "sha256:spec-v1"


def _spec(expected_ids, version=2):
    return SimpleNamespace(
        project_id="P1",
        version=version,
        ir_snapshot={"expected_source_ids": list(expected_ids)},
        spec_hash=SPEC_HASH,
        framework_baseline_version="af-basic-folder-1.0",
    )


def _content(sid):
    return f"CONTENT_{sid}"


def _descriptor(sid, *, content=None, expected_hash=None, framework_baseline=False, ob=None):
    content = content if content is not None else _content(sid)
    data = {
        "source_id": sid,
        "source_kind": "unit",
        "content": content,
        "content_hash": sha256_prefixed(content),
        "spec_hash": SPEC_HASH,
        "framework_baseline": framework_baseline,
    }
    if expected_hash:
        data["expected_hash"] = expected_hash
    if ob:
        data["ob_number"] = ob
    return data


def _artifacts(ids):
    return {
        f"derived/blocks/10_Unit_Supervision/{sid}.scl": json.dumps(
            _descriptor(sid), ensure_ascii=False
        )
        for sid in ids
    }


def _tia_snapshot(ids):
    return {sid: sha256_prefixed(_content(sid)) for sid in ids}


def test_minimal_sample_fidelity_ok_uc08():
    ids = ["UNIT_1", "EM_2", "EDGE_7"]
    r = FidelityChecker().check(_spec(ids), _artifacts(ids))
    assert isinstance(r, FidelityReport)
    assert r.fidelity_ok is True
    assert r.coverage == 1.0
    assert r.orphan == 0
    assert r.drift == 0
    assert r.tia_side_drift == 0
    assert set(r.coverage_matrix) == set(ids)
    for sid in ids:
        assert r.coverage_matrix[sid].startswith("derived/")


def test_missing_artifact_reduces_coverage_uc09():
    ids = ["UNIT_1", "EM_2", "EDGE_7"]
    arts = _artifacts(ids)
    del arts["derived/blocks/10_Unit_Supervision/EM_2.scl"]
    r = FidelityChecker().check(_spec(ids), arts)
    assert r.coverage < 1.0
    assert "EM_2" in r.unmapped_spec_objects
    assert r.fidelity_ok is False


def test_orphan_block_uc10():
    ids = ["UNIT_1", "EM_2"]
    arts = _artifacts(ids)
    arts["derived/blocks/30_Equipment_Modules/Rogue.scl"] = (
        "FUNCTION_BLOCK Rogue BEGIN END_FUNCTION_BLOCK"
    )
    r = FidelityChecker().check(_spec(ids), arts)
    assert r.orphan == 1
    assert r.fidelity_ok is False
    assert any("Rogue" in b for b in r.orphan_blocks)


def test_baseline_content_change_drift_uc11():
    ids = ["UNIT_1"]
    arts = _artifacts(ids)
    arts["framework_baseline/blocks/01_AF_Standard_Library/LAF_Base.scl"] = json.dumps(
        {
            "source_id": "LAF_Base",
            "framework_baseline": True,
            "content": "BASELINE_V2_TAMPERED",
            "expected_hash": sha256_prefixed("BASELINE_V1"),
        },
        ensure_ascii=False,
    )
    r = FidelityChecker().check(_spec(ids), arts)
    assert r.drift != 0
    assert r.fidelity_ok is False
    assert any(d["type"] == "baseline_or_mapping_hash_mismatch" for d in r.drift_items)


def test_spec_hash_mismatch_is_drift():
    ids = ["UNIT_1"]
    arts = _artifacts(ids)
    data = _descriptor("UNIT_1")
    data["spec_hash"] = "sha256:TAMPERED_SPEC"
    arts["derived/blocks/10_Unit_Supervision/UNIT_1.scl"] = json.dumps(data, ensure_ascii=False)
    r = FidelityChecker().check(_spec(ids), arts)
    assert r.drift != 0
    assert r.fidelity_ok is False


def test_ob_number_deviations_recorded_not_silent():
    ids = ["UNIT_1"]
    arts = _artifacts(ids)
    data = _descriptor(
        "UNIT_1",
        ob={"expected": "OB2001", "assigned_by_tia": "OB1", "mitigation": "pre_created_blank_ob"},
    )
    arts["derived/blocks/10_Unit_Supervision/UNIT_1.scl"] = json.dumps(data, ensure_ascii=False)
    r = FidelityChecker().check(_spec(ids), arts)
    assert len(r.ob_number_deviations) == 1
    assert r.fidelity_ok is True  # 不纳入 1:1 判定
    assert hasattr(r, "ob_number_deviations")
    assert any("ob_number_deviations" in n for n in r.notes)  # 禁止静默


def test_offline_pending_real_machine():
    ids = ["UNIT_1"]
    r = FidelityChecker().check(_spec(ids), _artifacts(ids))
    assert r.pending_real_machine is True
    assert r.reverse_protection["status"] == "pending_real_machine"
    assert r.reverse_protection["allowed"] is None


def test_tia_side_drift_marks_not_ok_and_blocks():
    ids = ["UNIT_1", "EM_2"]
    tia = _tia_snapshot(ids)
    tia["EM_2"] = "sha256:HAND_EDITED"
    r = FidelityChecker().check(_spec(ids), _artifacts(ids), tia_side_snapshot=tia)
    assert r.tia_side_drift >= 1
    assert r.fidelity_ok is False
    assert r.reverse_protection["allowed"] is False
    assert "EM_2" in r.reverse_protection["blocked_source_ids"]


def test_incremental_report_fields_complete():
    ids = ["UNIT_1", "EM_2", "CM_3"]
    diff = SpecDiff(
        base_spec_version=1,
        target_spec_version=2,
        changed=(SourceBlock("EM_2", "em", {}),),
        added=(SourceBlock("CM_3", "cm", {}),),
        removed=(),
        changed_source_ids=("EM_2", "CM_3"),
    )
    r = FidelityChecker().check(
        _spec(ids, version=2),
        _artifacts(ids),
        mode="incremental",
        base_spec_version=1,
        diff=diff,
        tia_side_snapshot=_tia_snapshot(ids),
    )
    assert r.mode == "incremental"
    assert r.base_spec_version == 1
    assert set(r.changed_source_ids) == {"EM_2", "CM_3"}
    assert r.reverse_protection["status"] == "evaluated"
    assert r.reverse_protection["allowed"] is True
    assert r.tia_side_drift == 0
    assert r.fidelity_ok is True
    for field in (
        "coverage_matrix", "orphan_blocks", "drift_items",
        "unmapped_spec_objects", "ob_number_deviations",
        "reverse_protection", "changed_source_ids",
    ):
        assert hasattr(r, field)
    assert any("变更块 100%" in n for n in r.notes)


def test_incremental_missing_changed_block_not_ok():
    """增量模式：变更块漏映射时 coverage<1、fidelity_ok=false。"""
    ids = ["UNIT_1", "EM_2"]
    diff = SpecDiff(
        base_spec_version=1, target_spec_version=2,
        changed=(SourceBlock("EM_2", "em", {}),),
        added=(), removed=(), changed_source_ids=("EM_2",),
    )
    arts = _artifacts(ids)
    del arts["derived/blocks/10_Unit_Supervision/EM_2.scl"]
    r = FidelityChecker().check(
        _spec(ids, version=2), arts, mode="incremental", diff=diff,
    )
    assert r.fidelity_ok is False
    assert r.coverage < 1.0
    assert any("变更块 100% 校验未通过" in n for n in r.notes)


def test_reproducible_product_hash_uc14():
    ids = ["UNIT_1", "EM_2"]
    r1 = FidelityChecker().check(_spec(ids), _artifacts(ids))
    r2 = FidelityChecker().check(_spec(ids), _artifacts(ids))
    assert r1.product_hash == r2.product_hash
    # F6 派生层纯函数确定性
    m1 = build_baseline_manifest(
        [{"source_id": "LAF_Base", "sha256": sha256_prefixed("X")}], "af-basic-folder-1.0"
    )
    m2 = build_baseline_manifest(
        [{"source_id": "LAF_Base", "sha256": sha256_prefixed("X")}], "af-basic-folder-1.0"
    )
    assert m1["manifest_sha256"] == m2["manifest_sha256"]
    assert stable_source_id("U1", "FB", "unit", 1) == stable_source_id("U1", "FB", "unit", 1)


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        FidelityChecker().check(_spec(["A"]), _artifacts(["A"]), mode="bogus")
