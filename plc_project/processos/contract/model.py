"""Process Contract IR — the single semantic source of truth (blueprint §3).

A functional node is a *behaviour contract*, not a PLC block. Every Operation
must answer: intent, resources, commands, completion, constraints, failure
policy, temporal semantics, acceptability. Missing blocking answers keep the
contract out of the deliverable state (see ``questions.py``).

Pure standard library + ``plc_engine.canonical`` for hashing/IDs. No TIA import.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from plc_engine.canonical import assert_stable_id, to_plain

SCHEMA = "process-contract/1.0"

#: Deterministic scan-cycle order shared by validator, runner and codegen.
SCAN_ORDER: tuple[str, ...] = (
    "FREEZE_INPUT_SNAPSHOT",
    "EVALUATE_TYPED_GUARDS",
    "RESOLVE_PRIORITY_AND_EXCLUSIVITY",
    "ATOMIC_TRANSITION",
    "COMPOSE_ACTIONS",
    "ARBITRATE_SINGLE_WRITER",
    "TICK_DRIVER_FSMS",
    "EMIT_OUTPUTS_AND_ALARMS",
)


def _dict(value: Any) -> dict[str, Any]:
    # Convert by field values (not to_plain(self), which would re-enter to_dict).
    return {f.name: to_plain(getattr(value, f.name)) for f in fields(value)}


@dataclass
class Action:
    """A command issued to a resource's typed command port."""

    target: str
    command: str
    value: Any = True

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Action":
        return cls(
            target=str(data["target"]),
            command=str(data["command"]),
            value=data.get("value", True),
        )


@dataclass
class Step:
    """A deterministic sequence step with entry/cyclic/exit actions."""

    id: str
    name: str = ""
    entry: list[Action] = field(default_factory=list)
    cyclic: list[Action] = field(default_factory=list)
    exit: list[Action] = field(default_factory=list)
    guard: str = ""
    duration_ms: int = 0
    timeout_ms: int = 0
    next: str = ""
    failure_target: str = ""
    is_fault: bool = False
    reset_guard: str = ""

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "step")
        if self.duration_ms < 0 or self.timeout_ms < 0:
            raise ValueError(f"step {self.id}: durations must be non-negative")

    def all_actions(self) -> list[Action]:
        return [*self.entry, *self.cyclic, *self.exit]

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            entry=[Action.from_dict(a) for a in data.get("entry", [])],
            cyclic=[Action.from_dict(a) for a in data.get("cyclic", [])],
            exit=[Action.from_dict(a) for a in data.get("exit", [])],
            guard=str(data.get("guard", "")),
            duration_ms=int(data.get("duration_ms", 0)),
            timeout_ms=int(data.get("timeout_ms", 0)),
            next=str(data.get("next", "")),
            failure_target=str(data.get("failure_target", "")),
            is_fault=bool(data.get("is_fault", False)),
            reset_guard=str(data.get("reset_guard", "")),
        )


@dataclass
class Resource:
    """An abstract device — no physical I/O address unless explicitly bound."""

    id: str
    name: str = ""
    kind: str = "cylinder"
    commands: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=lambda: ["Busy", "Done", "Error"])
    exclusive: bool = True
    io_bindings: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "resource")
        for fb in self.feedback:
            self.io_bindings.setdefault(fb, "unbound")

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Resource":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "cylinder")),
            commands=list(data.get("commands", [])),
            feedback=list(data.get("feedback", [])),
            status=list(data.get("status", ["Busy", "Done", "Error"])),
            exclusive=bool(data.get("exclusive", True)),
            io_bindings=dict(data.get("io_bindings", {})),
            params=dict(data.get("params", {})),
        )


@dataclass
class Invariant:
    """A process property that must never be violated."""

    id: str
    expr: str
    scope: str = "global"
    severity: str = "error"

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "invariant")
        if self.severity not in ("error", "warning"):
            raise ValueError(f"invariant {self.id}: bad severity {self.severity!r}")

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Invariant":
        return cls(
            id=str(data["id"]),
            expr=str(data["expr"]),
            scope=str(data.get("scope", "global")),
            severity=str(data.get("severity", "error")),
        )


@dataclass
class FailurePolicy:
    """Explicit exception behaviour — the AI may not omit or invent it."""

    detection: list[str] = field(default_factory=lambda: ["timeout", "feedback_conflict"])
    latch: bool = True
    block_auto: bool = True
    reset_qualification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailurePolicy":
        return cls(
            detection=list(data.get("detection", ["timeout", "feedback_conflict"])),
            latch=bool(data.get("latch", True)),
            block_auto=bool(data.get("block_auto", True)),
            reset_qualification=str(data.get("reset_qualification", "")),
        )


@dataclass
class OpenQuestion:
    """A blocking ambiguity that must be resolved by a human before delivery."""

    id: str
    question: str
    affects: list[str] = field(default_factory=list)
    severity: str = "blocking"
    resolution: str | None = None
    resolved_by: str | None = None

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "open_question")
        if self.severity not in ("blocking", "advisory"):
            raise ValueError(f"question {self.id}: bad severity {self.severity!r}")

    @property
    def resolved(self) -> bool:
        return bool(self.resolution)

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenQuestion":
        return cls(
            id=str(data["id"]),
            question=str(data["question"]),
            affects=list(data.get("affects", [])),
            severity=str(data.get("severity", "blocking")),
            resolution=data.get("resolution"),
            resolved_by=data.get("resolved_by"),
        )


@dataclass
class Scenario:
    """A replayable behaviour test with timed inputs and expected outcome."""

    id: str
    name: str = ""
    description: str = ""
    kind: str = "normal"
    inputs: list[dict[str, Any]] = field(default_factory=list)
    expect: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "scenario")
        if self.kind not in ("normal", "fault"):
            raise ValueError(f"scenario {self.id}: bad kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            kind=str(data.get("kind", "normal")),
            inputs=list(data.get("inputs", [])),
            expect=dict(data.get("expect", {})),
        )


@dataclass
class Operation:
    """A process function — maps to an AF EM Job/Sequence."""

    id: str
    name: str = ""
    unit: str = ""
    em: str = ""
    resource_ids: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    fault_policy: FailurePolicy = field(default_factory=FailurePolicy)
    acceptance: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "operation")

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Operation":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            unit=str(data.get("unit", "")),
            em=str(data.get("em", "")),
            resource_ids=list(data.get("resource_ids", [])),
            preconditions=list(data.get("preconditions", [])),
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
            fault_policy=FailurePolicy.from_dict(data.get("fault_policy", {})),
            acceptance=list(data.get("acceptance", [])),
        )


@dataclass
class Provenance:
    """Traceability of a requirement / migration interpretation."""

    origin: str = "user"
    confirmed_by: str | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Provenance":
        return cls(
            origin=str(data.get("origin", "user")),
            confirmed_by=data.get("confirmed_by"),
            evidence_refs=list(data.get("evidence_refs", [])),
        )


@dataclass
class ProcessContract:
    """The frozen, versionable, testable process contract (single truth)."""

    id: str
    name: str = ""
    target_framework: str = "siemens-af-basic@unverified"
    unit: str = "U_ASSEMBLY"
    schema: str = SCHEMA
    resources: list[Resource] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    invariants: list[Invariant] = field(default_factory=list)
    open_questions: list[OpenQuestion] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        assert_stable_id(self.id, "contract")
        if self.schema != SCHEMA:
            raise ValueError(f"unsupported schema {self.schema!r}; expected {SCHEMA!r}")

    def resource(self, rid: str) -> Resource | None:
        return next((r for r in self.resources if r.id == rid), None)

    def operation(self, oid: str) -> Operation | None:
        return next((o for o in self.operations if o.id == oid), None)

    def all_steps(self) -> list[Step]:
        return [s for o in self.operations for s in o.steps]

    def validate_structure(self) -> list[str]:
        """Basic referential integrity (deep semantics live in WS2 validator)."""
        errors: list[str] = []
        rids = {r.id for r in self.resources}
        if len(rids) != len(self.resources):
            errors.append("duplicate resource ids")
        oids = {o.id for o in self.operations}
        if len(oids) != len(self.operations):
            errors.append("duplicate operation ids")
        for op in self.operations:
            for rid in op.resource_ids:
                if rid not in rids:
                    errors.append(f"{op.id}: unknown resource {rid}")
            sids = {s.id for s in op.steps}
            if len(sids) != len(op.steps):
                errors.append(f"{op.id}: duplicate step ids")
            for st in op.steps:
                for act in st.all_actions():
                    if act.target not in rids:
                        errors.append(f"{op.id}.{st.id}: action targets unknown resource {act.target}")
                    res = self.resource(act.target)
                    if res and act.command not in res.commands:
                        errors.append(f"{op.id}.{st.id}: command {act.command} not on {act.target}")
                if st.next and st.next not in sids:
                    errors.append(f"{op.id}.{st.id}: next {st.next} not in operation")
                if st.failure_target and st.failure_target not in sids:
                    errors.append(f"{op.id}.{st.id}: failure_target {st.failure_target} not in operation")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessContract":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            target_framework=str(data.get("target_framework", "siemens-af-basic@unverified")),
            unit=str(data.get("unit", "U_ASSEMBLY")),
            schema=str(data.get("schema", SCHEMA)),
            resources=[Resource.from_dict(r) for r in data.get("resources", [])],
            operations=[Operation.from_dict(o) for o in data.get("operations", [])],
            invariants=[Invariant.from_dict(i) for i in data.get("invariants", [])],
            open_questions=[OpenQuestion.from_dict(q) for q in data.get("open_questions", [])],
            scenarios=[Scenario.from_dict(s) for s in data.get("scenarios", [])],
            provenance=Provenance.from_dict(data.get("provenance", {})),
        )