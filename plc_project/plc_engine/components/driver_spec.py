"""Strong-typed component / driver specification entities (WP-02 / G2).

Design invariants:
  * object ``id`` is immutable, ``name`` is a mutable display label;
  * every port has an explicit data type, direction and role;
  * ``io_bindings = None`` means unbound; a fictional ``%I0.0``/``%Q0.0`` is
    never generated for Greenfield (PRD 7.9 / design 9.7);
  * official LBC and self-contained compile modes are explicitly distinct.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from plc_engine.canonical import assert_stable_id

_PHYSICAL_ADDRESS_RE = re.compile(r"^%[IQAB][0-9]+(\.[0-9]+)?$", re.IGNORECASE)


class PortDataType(str, Enum):
    """Allowed typed-port data types (GuardAST shares BOOL/TIME/INT)."""

    BOOL = "BOOL"
    TIME = "TIME"
    INT = "INT"
    REAL = "REAL"
    WORD = "WORD"


class PortDirection(str, Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    INOUT = "INOUT"
    PARAMETER = "PARAMETER"


class PortRole(str, Enum):
    COMMAND = "COMMAND"
    FEEDBACK = "FEEDBACK"
    STATUS = "STATUS"
    SAFETY = "SAFETY"
    MODE = "MODE"
    PARAMETER = "PARAMETER"


class FieldSource(str, Enum):
    """Where a field value came from (blueprint A1)."""

    USER_EXPLICIT = "user_explicit"
    INFERRED = "inferred"
    IMPORTED = "imported"
    LIBRARY_DEFAULT = "library_default"


class CompileMode(str, Enum):
    """Official LBC versus self-contained generation (TASK-02A)."""

    OFFICIAL_LBC = "official_lbc"
    SELF_CONTAINED = "self_contained"


class FailurePolicy(str, Enum):
    ENTER_FAULT_REQUIRE_RESET = "enter_fault_require_reset"
    ENTER_FAULT_AUTO_RETRY = "enter_fault_auto_retry"


def _parse_enum(enum_cls: type[Enum], value: Any, default: Enum) -> Any:
    """Strict-ish enum parse: unknown values are preserved for validation to reject."""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except (ValueError, TypeError):
        return str(value) if value not in (None, "") else default


@dataclass
class TypedPort:
    """A named, strongly typed driver port."""

    name: str = ""
    data_type: PortDataType = PortDataType.BOOL
    direction: PortDirection = PortDirection.INPUT
    role: PortRole = PortRole.COMMAND
    required: bool = True
    source: FieldSource = FieldSource.LIBRARY_DEFAULT
    description: str = ""
    binding: str | None = None
    writer: str = ""
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type.value if isinstance(self.data_type, PortDataType) else str(self.data_type),
            "direction": self.direction.value if isinstance(self.direction, PortDirection) else str(self.direction),
            "role": self.role.value if isinstance(self.role, PortRole) else str(self.role),
            "required": bool(self.required),
            "source": self.source.value if isinstance(self.source, FieldSource) else str(self.source),
            "description": self.description,
            "binding": self.binding,
            "writer": self.writer,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TypedPort:
        return cls(
            name=str(data.get("name") or ""),
            data_type=_parse_enum(PortDataType, data.get("data_type"), PortDataType.BOOL),
            direction=_parse_enum(PortDirection, data.get("direction"), PortDirection.INPUT),
            role=_parse_enum(PortRole, data.get("role"), PortRole.COMMAND),
            required=bool(data.get("required", True)),
            source=_parse_enum(FieldSource, data.get("source"), FieldSource.LIBRARY_DEFAULT),
            description=str(data.get("description") or ""),
            binding=data.get("binding"),
            writer=str(data.get("writer") or ""),
            default=data.get("default"),
        )

    def is_bound(self) -> bool:
        """True only when an explicit physical binding exists."""
        return self.binding is not None and str(self.binding).strip() != ""


@dataclass
class ComponentDefinition:
    """A concrete engineering component instance (stable id + mutable name)."""

    id: str = ""
    name: str = ""
    component_type: str = ""
    driver_template: str = ""
    driver_spec_id: str = ""
    source: FieldSource = FieldSource.USER_EXPLICIT
    io_bindings: dict[str, Any] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.id:
            assert_stable_id(self.id, "component")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "component_type": self.component_type,
            "driver_template": self.driver_template,
            "driver_spec_id": self.driver_spec_id,
            "source": self.source.value if isinstance(self.source, FieldSource) else str(self.source),
            "io_bindings": self.io_bindings,
            "parameters": dict(self.parameters),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentDefinition:
        raw_bindings = data.get("io_bindings")
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            component_type=str(data.get("component_type") or ""),
            driver_template=str(data.get("driver_template") or ""),
            driver_spec_id=str(data.get("driver_spec_id") or ""),
            source=_parse_enum(FieldSource, data.get("source"), FieldSource.USER_EXPLICIT),
            io_bindings=dict(raw_bindings) if isinstance(raw_bindings, dict) else None,
            parameters=dict(data.get("parameters") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class DriverSpec:
    """Behavioural driver specification: ports, FSM, timeout, failure policy."""

    id: str = ""
    component_type: str = ""
    typed_ports: dict[str, TypedPort] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    states: list[str] = field(default_factory=lambda: ["IDLE"])
    transitions: list[dict[str, Any]] = field(default_factory=list)
    failure_policy: FailurePolicy = FailurePolicy.ENTER_FAULT_REQUIRE_RESET
    compile_mode: CompileMode = CompileMode.SELF_CONTAINED
    safety_permit_required: bool = True
    move_timeout_ms: int = 3000
    lbc_name: str = ""
    field_sources: dict[str, str] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.id:
            assert_stable_id(self.id, "driver_spec")

    @property
    def command_ports(self) -> list[TypedPort]:
        """All ports with role COMMAND, sorted by name for determinism."""
        return sorted((p for p in self.typed_ports.values() if p.role is PortRole.COMMAND), key=lambda p: p.name)

    @property
    def feedback_ports(self) -> list[TypedPort]:
        """All ports with role FEEDBACK, sorted by name."""
        return sorted((p for p in self.typed_ports.values() if p.role is PortRole.FEEDBACK), key=lambda p: p.name)

    def required_ports(self) -> list[str]:
        """Names of required ports, deterministically ordered."""
        return sorted(name for name, port in self.typed_ports.items() if port.required)

    def bound_addresses(self) -> dict[str, str]:
        """Explicit physical bindings only; unbound ports are simply absent."""
        return {name: str(port.binding) for name, port in self.typed_ports.items() if port.is_bound()}

    def assert_no_fictional_address(self) -> list[str]:
        """Return issues for any non-imported physical address (fail-closed)."""
        issues: list[str] = []
        for name, port in sorted(self.typed_ports.items()):
            if not port.is_bound():
                continue
            address = str(port.binding)
            if _PHYSICAL_ADDRESS_RE.match(address) and port.source is not FieldSource.IMPORTED:
                issues.append(
                    f"port {name}: greenfield driver must not invent physical address {address} (use null/unbound)"
                )
            if not _PHYSICAL_ADDRESS_RE.match(address):
                issues.append(f"port {name}: binding {address!r} is not a recognised physical address")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "component_type": self.component_type,
            "typed_ports": {k: v.to_dict() for k, v in sorted(self.typed_ports.items())},
            "parameters": dict(self.parameters),
            "states": list(self.states),
            "transitions": [dict(t) for t in self.transitions],
            "failure_policy": self.failure_policy.value if isinstance(self.failure_policy, FailurePolicy) else str(self.failure_policy),
            "compile_mode": self.compile_mode.value if isinstance(self.compile_mode, CompileMode) else str(self.compile_mode),
            "safety_permit_required": bool(self.safety_permit_required),
            "move_timeout_ms": int(self.move_timeout_ms),
            "lbc_name": self.lbc_name,
            "field_sources": dict(self.field_sources),
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriverSpec:
        raw_ports = data.get("typed_ports") or {}
        ports: dict[str, TypedPort] = {}
        for name, raw in raw_ports.items():
            if isinstance(raw, TypedPort):
                ports[str(name)] = raw
            elif isinstance(raw, dict):
                port = TypedPort.from_dict(raw)
                ports[str(name)] = port
        return cls(
            id=str(data.get("id") or ""),
            component_type=str(data.get("component_type") or ""),
            typed_ports=ports,
            parameters=dict(data.get("parameters") or {}),
            states=[str(x) for x in (data.get("states") or ["IDLE"])],
            transitions=[dict(x) for x in (data.get("transitions") or []) if isinstance(x, dict)],
            failure_policy=_parse_enum(FailurePolicy, data.get("failure_policy"), FailurePolicy.ENTER_FAULT_REQUIRE_RESET),
            compile_mode=_parse_enum(CompileMode, data.get("compile_mode"), CompileMode.SELF_CONTAINED),
            safety_permit_required=bool(data.get("safety_permit_required", True)),
            move_timeout_ms=int(data.get("move_timeout_ms") or 3000),
            lbc_name=str(data.get("lbc_name") or ""),
            field_sources={str(k): str(v) for k, v in (data.get("field_sources") or {}).items()},
            open_questions=[str(x) for x in (data.get("open_questions") or [])],
        )
