"""G1 / US-2 / US-6: atomic Patch, 409 conflict, 422 validation, idempotency."""
from __future__ import annotations

import random

import pytest

from plc_engine.engineering_ir.patch import (
    PatchConflictError,
    SemanticValidationError,
    apply_patch_atomic,
    make_patch,
    random_atomic_patch,
)
from plc_engine.engineering_ir.validation import ValidationEngine
from tests.v2_fixtures import build_store, build_valid_demo_ir


def test_stale_base_revision_returns_409_with_current_revision() -> None:
    ir = build_valid_demo_ir()
    patch = make_patch(ir.project_id, ir.revision - 1, [{"op": "set_view_layout", "layout": {}}])
    with pytest.raises(PatchConflictError) as exc:
        apply_patch_atomic(ir, patch)
    assert exc.value.code == "BASE_REVISION_CONFLICT"
    assert exc.value.current_revision == ir.revision
    assert exc.value.to_dict()["current_revision"] == 0


def test_unknown_op_returns_422_and_ir_is_unchanged() -> None:
    ir = build_valid_demo_ir()
    before = ir.to_dict()
    with pytest.raises(SemanticValidationError) as exc:
        apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [{"op": "eval_free_scl"}]))
    assert exc.value.code == "SEMANTIC_VALIDATION_FAILED"
    assert exc.value.issues[0]["source_id"]
    assert exc.value.unchanged_ir_hash == ir.ir_sha256
    assert ir.to_dict() == before


def test_illegal_guard_free_text_is_rejected() -> None:
    ir = build_valid_demo_ir()
    patch = make_patch(ir.project_id, ir.revision, [
        {"op": "set_guard", "transition_id": "T0", "guard": {"expression": "A AND NOT B; DROP TABLE"}}
    ])
    with pytest.raises(SemanticValidationError) as exc:
        apply_patch_atomic(ir, patch)
    assert any("free-text" in i["reason"] or "forbidden" in i["reason"] for i in exc.value.issues)


def test_100_random_patches_are_atomic() -> None:
    rng = random.Random(20261109)
    ir = build_valid_demo_ir()
    for iteration in range(100):
        patch = random_atomic_patch(ir, rng)
        snapshot = ir.to_dict()
        try:
            new_ir, result = apply_patch_atomic(ir, patch)
        except SemanticValidationError:
            assert ir.to_dict() == snapshot  # rejected => byte-identical
            continue
        assert result.revision == ir.revision + 1
        assert new_ir.ir_sha256 == new_ir.semantic_hash()
        assert ir.to_dict() == snapshot  # source IR never mutated
        assert ValidationEngine().validate(new_ir).passed
        ir = new_ir
    assert ir.revision > 50  # most random patches were valid and committed


def test_request_id_is_idempotent_in_store(tmp_path) -> None:
    store = build_store(tmp_path)
    patch = make_patch("prj_demo", 0, [{"op": "set_view_layout", "layout": {"x": 1}}], request_id="req_fixed_1")
    first = store.commit_patch("prj_demo", patch)
    second = store.commit_patch("prj_demo", patch)
    assert first.revision == second.revision == 1
    assert second.idempotent_hit is True
    assert len(store.list_revisions("prj_demo")) == 2  # revision 0 + revision 1 only


def test_ui_layout_patch_does_not_change_semantic_hash() -> None:
    ir = build_valid_demo_ir()
    before = ir.semantic_hash()
    new_ir, result = apply_patch_atomic(
        ir, make_patch(ir.project_id, ir.revision, [{"op": "set_view_layout", "layout": {"S2": {"x": 777}}}])
    )
    assert new_ir.semantic_hash() == before
    assert result.changed_ir_ids == []


def test_three_way_sync_ir_trace_scl() -> None:
    ir = build_valid_demo_ir()
    bundle_before = ir.derive_all()
    assert "T#1000ms" in bundle_before.scl_files["scl/FB_Sequence.scl"]

    new_ir, result = apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [
        {"op": "set_step_parameter", "step_id": "S2", "field": "min_duration_ms", "value": 2000}
    ]))
    bundle_after = new_ir.derive_all()
    assert result.revision == 1
    assert "S2" in result.changed_ir_ids
    assert new_ir.process.step_index()["S2"].min_duration_ms == 2000
    assert "T#2000ms" in bundle_after.scl_files["scl/FB_Sequence.scl"]
    assert bundle_after.trace != bundle_before.trace
    assert bundle_after.manifest.sha256 != bundle_before.manifest.sha256
    assert new_ir.ir_sha256 != ir.ir_sha256


def test_rename_component_keeps_stable_id() -> None:
    ir = build_valid_demo_ir()
    original_id = ir.components[0].id
    new_ir, _ = apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [
        {"op": "set_component_name", "component_id": original_id, "name": "夹紧气缸 A"}
    ]))
    assert new_ir.components[0].id == original_id
    assert new_ir.components[0].name == "夹紧气缸 A"


def test_remove_referenced_component_is_rejected() -> None:
    ir = build_valid_demo_ir()
    with pytest.raises(SemanticValidationError) as exc:
        apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [
            {"op": "remove_component", "component_id": "CM1"}
        ]))
    assert any("referenced by actions" in i["reason"] for i in exc.value.issues)


def test_fictional_physical_address_is_rejected() -> None:
    ir = build_valid_demo_ir()
    with pytest.raises(SemanticValidationError):
        apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [
            {"op": "set_component_parameter", "component_id": "CM1", "field": "io_bindings",
             "value": {"CmdExtend": "%Q0.0"}}
        ]))
