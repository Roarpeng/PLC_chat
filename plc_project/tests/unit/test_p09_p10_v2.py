"""P-09 imported-address policy + P-10 strict base_revision boundary (T09)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.workspace_v2 import get_store
from plc_engine.components.driver_spec import FieldSource
from plc_engine.engineering_ir.models import SourceBinding
from plc_engine.engineering_ir.patch import (
    SemanticValidationError,
    apply_patch_atomic,
    make_patch,
)
from plc_engine.engineering_ir.validation import ValidationEngine
from tests.v2_fixtures import build_store, build_valid_demo_ir

ADDRESS_OP = {
    "op": "set_component_parameter",
    "component_id": "CM1",
    "field": "io_bindings",
    "value": {"CmdExtend": "%Q0.0"},
    "source_id": "CM1",
}


def original_binding(component_id: str) -> SourceBinding:
    return SourceBinding.from_dict({
        # A distinct stable id: source_bindings.source_id must not collide with
        # component ids in ir.stable_ids(); the link is via ir_entities.
        "source_id": f"SB_{component_id}",
        "tia_path": "PLC_1/FB_Imported",
        "block_type": "FB",
        "original_xml_sha256": "sha256:original_xml",
        "original_hash": "sha256:original",
        "ir_entities": [component_id],
        "referenced_by": ["OB_Main"],
        "writable": "requires_review",
        "fidelity": "parsed",
    })


def test_p09_negative_imported_address_without_source_binding_is_rejected() -> None:
    """Negative: imported + %Q but NO original source_binding => fail-closed."""
    ir = build_valid_demo_ir()
    component = ir.components[0]
    component.source = FieldSource.IMPORTED
    component.io_bindings = {"CmdExtend": "%Q0.0"}
    report = ValidationEngine().validate(ir)
    assert not report.passed
    assert any("physical address" in issue["reason"] for issue in report.issues)
    with pytest.raises(SemanticValidationError):
        apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [ADDRESS_OP]))


def test_p09_positive_imported_address_with_source_binding_is_accepted() -> None:
    """Positive: imported + %Q + original source_binding => allowed, warning only."""
    ir = build_valid_demo_ir()
    component = ir.components[0]
    component.source = FieldSource.IMPORTED
    component.io_bindings = {"CmdExtend": "%Q0.0"}
    ir.source_bindings.append(original_binding(component.id))
    report = ValidationEngine().validate(ir)
    assert report.passed, report.issues
    assert any("source_binding" in warning for warning in report.warnings)
    new_ir, result = apply_patch_atomic(ir, make_patch(ir.project_id, ir.revision, [ADDRESS_OP]))
    assert result.revision == 1
    assert new_ir.components[0].io_bindings == {"CmdExtend": "%Q0.0"}


def test_p09_greenfield_address_stays_always_rejected() -> None:
    ir = build_valid_demo_ir()
    ir.components[0].source = FieldSource.USER_EXPLICIT
    ir.components[0].io_bindings = {"CmdExtend": "%Q0.0"}
    ir.source_bindings.append(original_binding(ir.components[0].id))
    assert not ValidationEngine().validate(ir).passed  # binding does not legalise greenfield invention


@pytest.mark.parametrize("bad_revision", [1.5, True, "1", 2**64, -1, None, "abc"])
def test_p10_make_patch_rejects_illegal_base_revision(bad_revision) -> None:
    with pytest.raises(SemanticValidationError) as exc:
        make_patch("prj_x", bad_revision, [{"op": "set_view_layout", "layout": {}}])
    assert exc.value.code == "SEMANTIC_VALIDATION_FAILED"
    assert exc.value.issues[0]["field"] == "base_revision"


def test_p10_valid_non_negative_int_still_accepted() -> None:
    patch = make_patch("prj_x", 0, [{"op": "set_view_layout", "layout": {}}])
    assert patch.base_revision == 0


def test_p10_api_returns_structured_422_and_no_half_applied_state(tmp_path) -> None:
    store = build_store(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            for bad in (1.5, True, "abc", 2**64):
                response = client.post("/api/v2/projects/prj_demo/patches", json={
                    "project_id": "prj_demo", "base_revision": bad, "request_id": f"req_bad_{bad}",
                    "ops": [{"op": "set_view_layout", "layout": {}}],
                })
                assert response.status_code == 422, (bad, response.text[:200])
                body = response.json()
                assert body["ok"] is False
                assert body["data"]["code"] == "SEMANTIC_VALIDATION_FAILED"
                assert body["data"]["issues"][0]["field"] == "base_revision"
            # No transaction was opened / no revision was written by the failures.
            assert len(store.list_revisions("prj_demo")) == 1
    finally:
        app.dependency_overrides.clear()
