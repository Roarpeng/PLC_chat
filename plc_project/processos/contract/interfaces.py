"""Frozen cross-module interfaces — the contract parallel workstreams build to.

WS2 (semantics/scenario), WS3 (frameworks/backends/codegen), WS4 (api) and WS6
(native) implement these Protocols against the WS1 contract. Keeping the shapes
here frozen lets the workstreams develop in parallel without drift.

Guard / invariant expression grammar (shared by validator, runner, codegen):
  expr   := or_expr
  or_expr:= and_expr ("OR" and_expr)*
  and_expr:= unary ("AND" unary)*
  unary  := "NOT" unary | "(" expr ")" | TOKEN
  TOKEN  := an input signal (Start, Reset, SafetyPermit, ...), a resource
            command (Extend, Retract) or a resource feedback (Extended, ...).
            Bare identifiers resolve: input signal > command > feedback.
Comparisons are boolean; timing is handled by Step.duration_ms / timeout_ms.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Protocol, runtime_checkable

from plc_engine.canonical import to_plain

from .model import ProcessContract, Scenario


def _fields_dict(value: Any) -> dict[str, Any]:
    return {f.name: to_plain(getattr(value, f.name)) for f in fields(value)}

#: Evidence levels — never skip a level without real proof (blueprint §8).
EVIDENCE_LEVELS = (
    "designed",
    "offline_verified",
    "simulated",
    "V19_compiled",
    "V20_compiled",
    "native_archived",
    "field_verified",
)


@dataclass
class Issue:
    code: str
    message: str
    node: str = ""
    severity: str = "error"  # error | warning


@dataclass
class ComplianceReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)
    evidence_level: str = "offline_verified"
    profile_id: str = ""
    ir_hash: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return _fields_dict(self)


@dataclass
class TraceEvent:
    t_ms: int
    step: str
    event: str
    commands: dict[str, bool] = field(default_factory=dict)
    inputs: dict[str, bool] = field(default_factory=dict)
    fault: bool = False


@dataclass
class Counterexample:
    """A minimal failing trace explaining *why* a property broke."""

    property_id: str
    cycle: int
    description: str
    trace: list[TraceEvent] = field(default_factory=list)


@dataclass
class ScenarioResult:
    scenario_id: str
    passed: bool
    trace: list[TraceEvent] = field(default_factory=list)
    reached: list[str] = field(default_factory=list)
    fault_reason: str = ""
    counterexamples: list[Counterexample] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)  # id -> pass/fail
    evidence_level: str = "simulated"

    def to_dict(self) -> dict[str, Any]:
        return _fields_dict(self)


@dataclass
class FrameworkProfile:
    profile_id: str
    framework: str
    tia_version: str
    library_version: str
    template_path: str
    template_sha256: str
    verified: bool = False
    block_signatures: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _fields_dict(self)


@dataclass
class AfBlock:
    name: str
    kind: str  # OB | FB | FC | DB
    role: str  # unit | em_sequence | cm_driver | instance_db | main
    source_ids: list[str] = field(default_factory=list)
    interface: dict[str, Any] = field(default_factory=dict)


@dataclass
class AfProject:
    profile_id: str
    blocks: list[AfBlock] = field(default_factory=list)
    call_order: list[str] = field(default_factory=list)
    instance_dbs: dict[str, str] = field(default_factory=dict)
    ir_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _fields_dict(self)


@dataclass
class GeneratedSource:
    files: dict[str, str] = field(default_factory=dict)  # filename -> SCL/XML
    source_map: list[dict[str, Any]] = field(default_factory=list)  # {file,line,node}
    coverage: dict[str, int] = field(default_factory=dict)  # steps/actions/guards/timers lowered
    coverage_assertions_passed: bool = False
    manifest_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _fields_dict(self)


@runtime_checkable
class SemanticValidator(Protocol):
    def validate(self, contract: ProcessContract, profile: FrameworkProfile | None = None) -> ComplianceReport: ...


@runtime_checkable
class ScenarioRunner(Protocol):
    def run(self, contract: ProcessContract, scenario: Scenario) -> ScenarioResult: ...
    def run_all(self, contract: ProcessContract) -> list[ScenarioResult]: ...


@runtime_checkable
class FrameworkBackend(Protocol):
    def lower(self, contract: ProcessContract, profile: FrameworkProfile) -> AfProject: ...


@runtime_checkable
class SourceGenerator(Protocol):
    def generate(self, project: AfProject, profile: FrameworkProfile) -> GeneratedSource: ...