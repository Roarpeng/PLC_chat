"""G2 / US-1: DriverCatalog, four standard components, NL -> CandidatePatch."""
from __future__ import annotations

import pytest

from gateway.app.services.plc.intent_service_v2 import IntentServiceV2
from plc_engine.components.catalog import CUSTOM_PENDING, DriverCatalog
from plc_engine.components.driver_spec import CompileMode
from plc_engine.components.driver_validation import validate_catalog
from tests.v2_fixtures import build_valid_demo_ir


def test_four_standard_templates_load_and_validate() -> None:
    catalog = DriverCatalog()
    assert catalog.types() == [
        "di_do", "double_acting_cylinder", "motor_starter", "single_acting_actuator"
    ]
    assert catalog.load_errors == []
    assert validate_catalog(catalog) == []


def test_same_template_serves_two_different_processes() -> None:
    catalog = DriverCatalog()
    first, spec_a = catalog.create_component("double_acting_cylinder", component_id="CM_CLAMP")
    second, spec_b = catalog.create_component("double_acting_cylinder", component_id="CM_PRESS")
    assert first.id != second.id
    assert first.driver_template == second.driver_template
    assert spec_a.component_type == spec_b.component_type
    assert {p.name for p in spec_a.command_ports} == {p.name for p in spec_b.command_ports}
    assert spec_a.typed_ports.keys() == spec_b.typed_ports.keys()
    assert spec_a.states == spec_b.states


def test_unknown_component_type_is_custom_pending_not_guessed() -> None:
    catalog = DriverCatalog()
    assert catalog.match_from_text("一个完全未知的神秘装置") == CUSTOM_PENDING
    with pytest.raises(KeyError):
        catalog.create_spec("unknown_type")
    assert catalog.get("unknown_type") is None


def test_compile_modes_are_explicitly_distinct() -> None:
    catalog = DriverCatalog()
    lbc = catalog.create_spec("double_acting_cylinder", compile_mode=CompileMode.OFFICIAL_LBC)
    local = catalog.create_spec("double_acting_cylinder", compile_mode=CompileMode.SELF_CONTAINED)
    assert lbc.compile_mode is CompileMode.OFFICIAL_LBC
    assert local.compile_mode is CompileMode.SELF_CONTAINED
    assert lbc.lbc_name == "LBC_TwoWayActuator"
    assert local.lbc_name == lbc.lbc_name
    with pytest.raises(ValueError):
        catalog.create_spec("double_acting_cylinder", compile_mode="bogus_mode")


def test_catalog_hash_is_deterministic() -> None:
    assert DriverCatalog().catalog_sha256() == DriverCatalog().catalog_sha256()


def test_nl_double_acting_cylinder_us1() -> None:
    ir = build_valid_demo_ir()
    result = IntentServiceV2().parse(
        ir=ir, message="一只双作用气缸、伸出/缩回限位、3 秒超时",
        base_revision=ir.revision, request_id="req_us1",
    )
    assert result["component_type"] == "double_acting_cylinder"
    assert result["move_timeout_ms"] == 3000
    assert result["evidence_level"] == "offline"
    assert result["questions"] == []
    component_ops = [op for op in result["ops"] if op["op"] == "add_component"]
    assert len(component_ops) == 1
    spec = component_ops[0]["payload"]["driver_spec"]
    assert spec["move_timeout_ms"] == 3000
    assert component_ops[0]["payload"]["component"]["io_bindings"] is None
    assert all(port["binding"] is None for port in spec["typed_ports"].values())
    assert not any("%I" in str(op) or "%Q" in str(op) for op in result["ops"])
    assert result["field_sources"]["move_timeout_ms"] == "user_explicit"
    assert "SCL" not in str(result["ops"])


def test_missing_slots_go_to_question_queue() -> None:
    ir = build_valid_demo_ir()
    result = IntentServiceV2().parse(ir=ir, message="加一个气缸", base_revision=ir.revision)
    assert result["questions"]
    assert any("超时" in q for q in result["questions"])
    assert any("反馈" in q for q in result["questions"])
    assert result["ops"] == []
    assert result["unchanged_ir_hash"] == ir.ir_sha256


def test_unknown_device_is_not_guessed() -> None:
    ir = build_valid_demo_ir()
    result = IntentServiceV2().parse(ir=ir, message="装一个外星装置", base_revision=ir.revision)
    assert result["component_type"] == CUSTOM_PENDING
    assert any("custom_pending" in q for q in result["questions"])


def test_intent_never_writes_ir_or_tia() -> None:
    ir = build_valid_demo_ir()
    before = ir.to_dict()
    result = IntentServiceV2().parse(ir=ir, message="一只双作用气缸、伸出/缩回限位、3 秒超时")
    assert ir.to_dict() == before
    assert "no IR write" in result["notice"]
    assert "no TIA write" in result["notice"]
