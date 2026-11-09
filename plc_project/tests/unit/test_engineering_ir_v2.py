"""G1: EngineeringIR v2 roundtrip, semantic hash, stable IDs, derivation."""
from __future__ import annotations

import pytest

from plc_engine.engineering_ir import (
    AF_PROFILE_ID,
    SCHEMA_VERSION,
    EvidenceLevel,
    ValidationEngine,
    forbid_upcast,
)
from plc_engine.engineering_ir.models import EngineeringIRV2, new_project_ir
from plc_engine.process.scl_lowering import assert_deterministic
from tests.v2_fixtures import build_valid_demo_ir


def test_roundtrip_is_lossless() -> None:
    ir = build_valid_demo_ir()
    restored = EngineeringIRV2.from_dict(ir.to_dict())
    assert restored.to_dict() == ir.to_dict()
    assert restored.ir_sha256 == ir.ir_sha256
    assert restored.semantic_hash() == ir.ir_sha256


def test_semantic_hash_excludes_ui_layout() -> None:
    ir = build_valid_demo_ir()
    before = ir.semantic_hash()
    ir.views["layout"] = {"S2": {"x": 999, "y": -12, "zoom": 3.5, "color": "red"}}
    assert ir.semantic_hash() == before
    assert ir.ir_sha256 == before


def test_semantic_hash_excludes_timestamps_and_receipt() -> None:
    ir = build_valid_demo_ir()
    before = ir.semantic_hash()
    ir.created_at = "2030-01-01T00:00:00+00:00"
    ir.updated_at = "2030-01-02T00:00:00+00:00"
    ir.receipt = {"generated_at": "2030-01-03T00:00:00+00:00", "elapsed_ms": 12345}
    ir.spec_meta["frozen_at"] = "2030-01-04T00:00:00+00:00"
    assert ir.semantic_hash() == before


def test_schema_version_and_af_profile_are_pinned() -> None:
    ir = build_valid_demo_ir()
    assert ir.schema_version == SCHEMA_VERSION == "engineering-ir/2.0"
    assert ir.af_profile.profile_id == AF_PROFILE_ID == "SIEMENS_AF_BASIC_FOLDER_V19"
    with pytest.raises(ValueError):
        EngineeringIRV2(project_id="prj_bad", schema_version="engineering-ir/9.9")
    with pytest.raises(ValueError):
        other = build_valid_demo_ir()
        other.af_profile.library_version = "AF-V3.0-LATEST"
        ir.af_profile.assert_consistent_with(other.af_profile)


def test_stable_id_is_separate_from_display_name() -> None:
    ir = build_valid_demo_ir()
    component = ir.components[0]
    original_id = component.id
    component.name = " renamed display label "
    assert component.id == original_id
    assert ir.semantic_hash() != ir.ir_sha256  # name is semantic, id is not renamed
    assert ir.refresh_hash() == ir.semantic_hash()
    assert ValidationEngine().validate(ir).passed


def test_duplicate_stable_ids_are_rejected() -> None:
    ir = build_valid_demo_ir()
    ir.process.steps[1].id = ir.process.steps[0].id
    report = ValidationEngine().validate(ir)
    assert not report.passed
    assert any("duplicate stable ID" in i["reason"] for i in report.issues)


def test_derived_bundle_is_deterministic() -> None:
    ir = build_valid_demo_ir()
    first = ir.derive_all()
    second = ir.derive_all()
    assert first.manifest.sha256 == second.manifest.sha256
    assert first.scl_files == second.scl_files
    assert first.source_map.to_dict() == second.source_map.to_dict()
    assert first.evidence_level is EvidenceLevel.OFFLINE
    assert "预测" in first.notice or "prediction" in first.notice
    assert assert_deterministic(ir)["deterministic"] is True


def test_manifest_hash_changes_only_on_semantic_edit() -> None:
    ir = build_valid_demo_ir()
    before = ir.derive_all().manifest.sha256
    ir.views["layout"] = {"x": 42}
    assert ir.derive_all().manifest.sha256 == before
    ir.process.step_index()["S2"].min_duration_ms = 2000
    ir.refresh_hash()
    assert ir.derive_all().manifest.sha256 != before


def test_evidence_levels_never_upcast() -> None:
    assert forbid_upcast(EvidenceLevel.MOCKED, EvidenceLevel.V19_REAL) is not EvidenceLevel.V19_REAL
    assert forbid_upcast(EvidenceLevel.OFFLINE, EvidenceLevel.V19_REAL) is EvidenceLevel.PENDING_REAL_MACHINE
    assert forbid_upcast(EvidenceLevel.V19_REAL, EvidenceLevel.V19_REAL) is EvidenceLevel.V19_REAL


def test_new_project_ir_has_revision_zero() -> None:
    ir = new_project_ir("prj_fresh")
    assert ir.revision == 0
    assert ir.ir_sha256.startswith("sha256:")
    assert ir.process.steps == []
