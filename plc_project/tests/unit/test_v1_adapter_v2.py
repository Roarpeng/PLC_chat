"""G1: v1 -> v2 adapter zero-field-loss golden tests (real GreenfieldIR)."""
from __future__ import annotations

from plc_engine.af.greenfield_ir import GreenfieldIR, build_sample_ir
from plc_engine.canonical import canonical_dumps
from plc_engine.engineering_ir.v1_adapter import V1_TOP_LEVEL_FIELDS, V1ToV2Adapter


def test_real_v1_sample_has_21_top_level_fields() -> None:
    v1 = build_sample_ir()
    payload = v1.to_dict()
    assert len(V1_TOP_LEVEL_FIELDS) == 21  # source audit correction: design prose said 20
    assert set(V1_TOP_LEVEL_FIELDS) == set(payload)


def test_zero_field_loss_on_real_sample_ir() -> None:
    v1 = build_sample_ir()
    v2 = V1ToV2Adapter.to_v2(v1, project_id="prj_legacy")
    report = V1ToV2Adapter.zero_field_loss_report(v1, v2)
    assert report["zero_loss"] is True, report
    assert V1ToV2Adapter.assert_zero_field_loss(v1, v2) is True
    assert report["hash_match"] is True
    assert report["missing_keys"] == [] and report["differing_keys"] == []


def test_legacy_raw_is_byte_exact_and_opaque() -> None:
    v1 = build_sample_ir()
    v2 = V1ToV2Adapter.to_v2(v1, project_id="prj_legacy")
    assert canonical_dumps(v2.legacy_raw) == canonical_dumps(v1.to_dict())
    assert v2.legacy_raw["cms"][0]["id"] == v1.cms[0].id
    assert v2.legacy_raw["views"]["layout"] == v1.views.layout


def test_v1_roundtrip_is_unaffected() -> None:
    v1 = build_sample_ir()
    restored = GreenfieldIR.from_dict(v1.to_dict())
    assert restored.ir_sha256() == v1.ir_sha256()
    assert restored.to_dict() == v1.to_dict()
    v2 = V1ToV2Adapter.to_v2(restored, project_id="prj_roundtrip")
    assert V1ToV2Adapter.assert_zero_field_loss(restored, v2) is True


def test_to_v1_view_is_readonly() -> None:
    v1 = build_sample_ir()
    v2 = V1ToV2Adapter.to_v2(v1, project_id="prj_view")
    view = V1ToV2Adapter.to_v1_view(v2)
    assert view["_v2_readonly_view"] is True
    assert view["ir_version"] == v1.ir_version
    view["cms"] = []  # mutating the returned view must not touch legacy_raw
    assert v2.legacy_raw["cms"]


def test_free_text_expressions_are_not_invented_into_guards() -> None:
    v1 = build_sample_ir()
    v2 = V1ToV2Adapter.to_v2(v1, project_id="prj_freetext")
    unmapped = v2.receipt["unmapped_free_text"]
    assert any("transition_condition" in item for item in unmapped)
    assert any("actions" in item for item in unmapped)
    for transition in v2.process.transitions:
        assert transition.guard_ast is not None
        assert transition.guard_ast.to_dict().get("node_type") == "CONST"


def test_structured_projection_preserves_stable_ids_and_unbound_io() -> None:
    v1 = build_sample_ir()
    v2 = V1ToV2Adapter.to_v2(v1, project_id="prj_ids")
    v1_cm_ids = {cm.id for cm in v1.cms}
    assert {c.id for c in v2.components} == v1_cm_ids
    assert {s.id for s in v2.process.steps} == {s.id for s in v1.steps}
    assert all(c.io_bindings is None for c in v2.components)
    for spec in v2.driver_specs.values():
        assert spec.bound_addresses() == {}
        assert spec.assert_no_fictional_address() == []
    assert v2.process.initial_step in v2.process.step_ids()


def test_dict_fixture_input_is_supported() -> None:
    raw = build_sample_ir().to_dict()
    v2 = V1ToV2Adapter.to_v2(raw, project_id="prj_dict")
    assert V1ToV2Adapter.assert_zero_field_loss(raw, v2) is True
