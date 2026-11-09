"""G2 negative cases: ports, timeout, feedback, reverse coils, single writer."""
from __future__ import annotations

import copy

import pytest

from plc_engine.components.catalog import DriverCatalog
from plc_engine.components.driver_spec import FieldSource, PortDataType, PortRole, TypedPort
from plc_engine.components.driver_validation import (
    validate_actions,
    validate_component_binding,
    validate_driver_spec,
)
from plc_engine.process.graph_validation import arbitrate_single_writer, reverse_command_pairs
from plc_engine.process.sequence_ir import Action
from tests.v2_fixtures import build_valid_demo_ir


def base_spec():
    return DriverCatalog().create_spec("double_acting_cylinder")


def test_valid_spec_has_no_issues() -> None:
    assert validate_driver_spec(base_spec()) == []


def test_missing_timeout_is_rejected() -> None:
    spec = base_spec()
    spec.move_timeout_ms = 0
    assert any("move_timeout_ms" in i for i in validate_driver_spec(spec))


def test_missing_feedback_port_is_rejected() -> None:
    spec = base_spec()
    for name in [p.name for p in spec.feedback_ports]:
        del spec.typed_ports[name]
    issues = validate_driver_spec(spec)
    assert any("FEEDBACK" in i for i in issues)
    assert spec.feedback_ports == []


def test_wrong_port_type_is_rejected() -> None:
    spec = base_spec()
    spec.typed_ports["CmdExtend"].data_type = "MYSTERY_TYPE"
    assert any("unknown data_type" in i for i in validate_driver_spec(spec))


def test_fictional_physical_address_is_rejected() -> None:
    spec = base_spec()
    spec.typed_ports["CmdExtend"].binding = "%Q0.0"
    issues = validate_driver_spec(spec)
    assert any("invent physical address" in i for i in issues)
    spec.typed_ports["CmdExtend"].source = FieldSource.IMPORTED
    assert not any("invent physical address" in i for i in validate_driver_spec(spec))


def test_component_io_bindings_must_stay_null() -> None:
    ir = build_valid_demo_ir()
    component = ir.components[0]
    spec = ir.driver_specs[component.driver_spec_id]
    assert validate_component_binding(component, spec) == []
    component.io_bindings = {"CmdExtend": "%Q0.0"}
    assert any("invent physical address" in i for i in validate_component_binding(component, spec))


def test_reverse_coils_are_interlocked() -> None:
    spec = base_spec()
    pairs = reverse_command_pairs([p.name for p in spec.command_ports])
    assert ("CmdExtend", "CmdRetract") in pairs
    actions = [
        Action(id="a1", target_component_id="CM1", command="CmdExtend", value=True, source_id="S1"),
        Action(id="a2", target_component_id="CM1", command="CmdRetract", value=True, source_id="S1"),
    ]
    commands, alarms, issues = validate_actions(actions, spec)
    assert commands[("CM1", "CmdExtend")] is False
    assert commands[("CM1", "CmdRetract")] is False
    assert any("reverse_outputs_interlocked" in a for a in alarms)
    assert issues


def test_single_writer_conflict_is_detected() -> None:
    actions = [
        Action(id="a1", target_component_id="CM1", command="CmdExtend", value=True, source_id="S1"),
        Action(id="a2", target_component_id="CM1", command="CmdExtend", value=False, source_id="S2"),
    ]
    commands, alarms = arbitrate_single_writer(actions, True)
    assert commands[("CM1", "CmdExtend")] is False
    assert any("single_writer_conflict" in a for a in alarms)


def test_safety_permit_loss_inhibits_every_command() -> None:
    actions = [Action(id="a1", target_component_id="CM1", command="CmdExtend", value=True, source_id="S1")]
    commands, alarms = arbitrate_single_writer(actions, False)
    assert commands[("CM1", "CmdExtend")] is False
    assert any("safety_permit_lost" in a for a in alarms)


def test_unknown_command_port_is_rejected() -> None:
    spec = base_spec()
    actions = [Action(id="a1", target_component_id="CM1", command="CmdTeleport", value=True)]
    _, _, issues = validate_actions(actions, spec)
    assert any("unknown command port" in i for i in issues)


def test_official_lbc_and_self_contained_are_distinct_in_compiler() -> None:
    from plc_engine.components.driver_compiler import DriverCompiler

    catalog = DriverCatalog()
    component_lbc, spec_lbc = catalog.create_component(
        "double_acting_cylinder", component_id="CM_LBC", compile_mode="official_lbc")
    component_local, spec_local = catalog.create_component(
        "double_acting_cylinder", component_id="CM_LOCAL", compile_mode="self_contained")
    compiler = DriverCompiler(catalog)
    lbc = compiler.compile(spec_lbc, component_lbc)
    local = compiler.compile(spec_local, component_local)
    assert lbc["implementation"] == "official_lbc_reference_only"
    assert local["implementation"] == "self_contained_local_fb"
    assert lbc["scl_body"] == "" and local["scl_body"]
    assert lbc["physical_addresses"] == [] and local["physical_addresses"] == []
    assert lbc["block_number"] is None and local["block_number"] is None
