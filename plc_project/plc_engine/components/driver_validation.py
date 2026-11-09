"""Static driver validation (blueprint A2 / G2, TASK-02A negative cases)."""
from __future__ import annotations

import re

from plc_engine.components.catalog import DriverCatalog
from plc_engine.components.driver_spec import (
    CompileMode,
    ComponentDefinition,
    DriverSpec,
    PortDataType,
    PortDirection,
    PortRole,
)
from plc_engine.process.graph_validation import arbitrate_single_writer, reverse_command_pairs
from plc_engine.process.sequence_ir import Action

_PHYSICAL_ADDRESS_RE = re.compile(r"^%[IQAB][0-9]+(\.[0-9]+)?$", re.IGNORECASE)
EXPECTED_CATALOG_TYPES: tuple[str, ...] = (
    "double_acting_cylinder",
    "single_acting_actuator",
    "di_do",
    "motor_starter",
)


def validate_driver_spec(spec: DriverSpec) -> list[str]:
    """Return deterministic issues for one DriverSpec (fail-closed)."""
    issues: list[str] = []
    if not spec.id:
        issues.append("driver spec requires a stable id")
    if not spec.component_type:
        issues.append("driver spec requires a component_type")
    if not isinstance(spec.compile_mode, CompileMode):
        issues.append(f"unknown compile_mode {spec.compile_mode!r}")
    if not spec.typed_ports:
        issues.append("driver spec has no typed ports")
    if not spec.required_ports():
        issues.append("driver spec has no required ports")
    if spec.move_timeout_ms <= 0:
        issues.append("driver spec requires a positive move_timeout_ms")

    for name, port in sorted(spec.typed_ports.items()):
        if name != port.name:
            issues.append(f"port key/name mismatch: {name!r} vs {port.name!r}")
        if not isinstance(port.data_type, PortDataType):
            issues.append(f"port {name}: unknown data_type {port.data_type!r}")
        if not isinstance(port.direction, PortDirection):
            issues.append(f"port {name}: unknown direction {port.direction!r}")
        if not isinstance(port.role, PortRole):
            issues.append(f"port {name}: unknown role {port.role!r}")
        if port.role is PortRole.COMMAND and not port.writer:
            issues.append(f"command port {name}: no single writer declared")
        if port.role is PortRole.FEEDBACK and port.direction is PortDirection.OUTPUT:
            issues.append(f"feedback port {name}: must not be an OUTPUT")
        if port.role is PortRole.COMMAND and port.direction is PortDirection.OUTPUT:
            issues.append(f"command port {name}: must not be an OUTPUT")
        if port.binding is not None:
            address = str(port.binding)
            if not _PHYSICAL_ADDRESS_RE.match(address):
                issues.append(f"port {name}: binding {address!r} is not a recognised physical address")
            elif port.source.value != "imported":
                issues.append(f"port {name}: greenfield must not invent physical address {address} (use null)")
    issues.extend(spec.assert_no_fictional_address())

    if not any(port.role is PortRole.FEEDBACK for port in spec.typed_ports.values()):
        issues.append("driver FSM must expose at least one FEEDBACK typed port")
    states = set(spec.states)
    if "FAULT" not in states:
        issues.append("driver FSM must declare a FAULT state")
    if spec.safety_permit_required and not any(p.role is PortRole.SAFETY for p in spec.typed_ports.values()):
        issues.append("safety_permit_required driver must expose a SAFETY typed port")
    if not any(t.get("on") == "timeout" or "TIMEOUT" in str(t.get("on", "")).upper() for t in spec.transitions):
        issues.append("driver FSM must declare a timeout -> FAULT transition")
    if not any(str(t.get("to", "")).upper() == "FAULT" for t in spec.transitions):
        issues.append("driver FSM must reach FAULT on a failure transition")
    if not any(str(t.get("from", "")).upper() == "FAULT" for t in spec.transitions):
        issues.append("driver FSM must declare a reset path out of FAULT")

    command_names = [p.name for p in spec.command_ports]
    for left, right in reverse_command_pairs(command_names):
        left_port = spec.typed_ports.get(left)
        right_port = spec.typed_ports.get(right)
        if left_port and right_port and left_port.writer != right_port.writer:
            issues.append(f"reverse outputs {left}/{right} must share one writer")
    return sorted(set(issues))


def validate_component_binding(component: ComponentDefinition, spec: DriverSpec | None) -> list[str]:
    """Check a component and its DriverSpec form a valid, unbound pair."""
    issues: list[str] = []
    if not component.id:
        issues.append("component requires a stable id")
    if not component.name:
        issues.append("component requires a display name")
    if component.io_bindings is not None:
        for key, address in component.io_bindings.items():
            if isinstance(address, str) and address.startswith("%"):
                issues.append(f"component {component.id} must not invent physical address {address} for {key}")
    if spec is None:
        if component.driver_spec_id:
            issues.append(f"component {component.id} references missing driver_spec {component.driver_spec_id!r}")
        return issues
    if spec.id != component.driver_spec_id:
        issues.append(f"component {component.id} driver_spec_id mismatch: {component.driver_spec_id!r} vs {spec.id!r}")
    if spec.component_type != component.component_type:
        issues.append(f"component {component.id} component_type mismatch")
    return issues


def validate_actions(
    actions: list[Action],
    spec: DriverSpec,
    *,
    safety_permit: bool = True,
) -> tuple[dict[tuple[str, str], bool], list[str], list[str]]:
    """Validate a step's actions against a driver and arbitrate outputs.

    Returns ``(commands, alarms, issues)``. ``alarms`` from the shared arbitrator
    are treated as hard issues (double coil, lost safety permit).
    """
    issues: list[str] = []
    command_names = {p.name for p in spec.command_ports}
    for action in actions:
        if action.command not in command_names:
            issues.append(f"unknown command port {action.command!r} on driver {spec.id}")
    pairs = reverse_command_pairs([p.name for p in spec.command_ports])
    commands, alarms = arbitrate_single_writer(actions, safety_permit, reverse_pairs=pairs)
    for alarm in alarms:
        if alarm.startswith("reverse_outputs_interlocked") or alarm.startswith("single_writer_conflict"):
            issues.append(f"command conflict: {alarm}")
    return commands, alarms, issues


def validate_catalog(catalog: DriverCatalog) -> list[str]:
    """Assert the four standard templates are loaded and individually valid."""
    issues = list(catalog.load_errors)
    issues.extend(f"missing standard template: {name}" for name in EXPECTED_CATALOG_TYPES if name not in catalog.types())
    for name in catalog.types():
        template = catalog.get(name)
        if template is None:
            continue
        try:
            spec = catalog.create_spec(name)
        except (ValueError, KeyError) as exc:
            issues.append(f"template {name}: {exc}")
            continue
        issues.extend(f"template {name}: {problem}" for problem in validate_driver_spec(spec))
    return sorted(set(issues))
