"""SFC-like SequenceIR entities (WP-03 / design 3).

First edition deliberately implements **deterministic serial steps** with
prioritised branches and exception paths. ``parallel_groups`` is display-only:
before Fork/Join run semantics exist, graph validation rejects delivering it
(fail-closed, PRD 2.2 out-of-scope item 3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from plc_engine.canonical import assert_stable_id
from plc_engine.process.guard_ast import GuardAST, parse_guard


class EdgeType(str, Enum):
    NORMAL = "NORMAL"
    EXCEPTION = "EXCEPTION"
    TIMEOUT = "TIMEOUT"
    RESET = "RESET"


class ExceptionTrigger(str, Enum):
    TIMEOUT = "TIMEOUT"
    SAFETY_PERMIT_LOST = "SAFETY_PERMIT_LOST"
    FEEDBACK_FAULT = "FEEDBACK_FAULT"
    RESET = "RESET"


@dataclass
class Action:
    """A command issued to a component's typed command port."""

    id: str = ""
    target_component_id: str = ""
    command: str = ""
    value: Any = True
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_component_id": self.target_component_id,
            "command": self.command,
            "value": self.value,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        return cls(
            id=str(data.get("id") or ""),
            target_component_id=str(data.get("target_component_id") or ""),
            command=str(data.get("command") or ""),
            value=data.get("value", True),
            source_id=str(data.get("source_id") or ""),
        )


@dataclass
class Step:
    """A deterministic sequence step with entry/cyclic/exit actions."""

    id: str = ""
    name: str = ""
    entry_actions: list[Action] = field(default_factory=list)
    cyclic_actions: list[Action] = field(default_factory=list)
    exit_actions: list[Action] = field(default_factory=list)
    min_duration_ms: int = 0
    max_duration_ms: int = 0
    failure_target: str = ""
    source_id: str = ""
    layout: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.id:
            assert_stable_id(self.id, "step")
        if self.min_duration_ms < 0 or self.max_duration_ms < 0:
            raise ValueError("step durations must be non-negative")
        if self.max_duration_ms and self.min_duration_ms > self.max_duration_ms:
            raise ValueError("min_duration_ms must not exceed max_duration_ms")

    def all_actions(self) -> list[Action]:
        """All actions of the step in documented order."""
        return [*self.entry_actions, *self.cyclic_actions, *self.exit_actions]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entry_actions": [a.to_dict() for a in self.entry_actions],
            "cyclic_actions": [a.to_dict() for a in self.cyclic_actions],
            "exit_actions": [a.to_dict() for a in self.exit_actions],
            "min_duration_ms": int(self.min_duration_ms),
            "max_duration_ms": int(self.max_duration_ms),
            "failure_target": self.failure_target,
            "source_id": self.source_id,
            "layout": dict(self.layout),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            entry_actions=_actions(data.get("entry_actions")),
            cyclic_actions=_actions(data.get("cyclic_actions")),
            exit_actions=_actions(data.get("exit_actions")),
            min_duration_ms=int(data.get("min_duration_ms") or 0),
            max_duration_ms=int(data.get("max_duration_ms") or 0),
            failure_target=str(data.get("failure_target") or ""),
            source_id=str(data.get("source_id") or ""),
            layout=dict(data.get("layout") or {}),
        )


@dataclass
class Transition:
    """A guarded, prioritised edge between two steps."""

    id: str = ""
    from_step: str = ""
    to_step: str = ""
    guard_ast: GuardAST | None = None
    priority: int = 0
    edge_type: EdgeType = EdgeType.NORMAL
    source_id: str = ""

    def __post_init__(self) -> None:
        if self.id:
            assert_stable_id(self.id, "transition")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_step": self.from_step,
            "to_step": self.to_step,
            "guard_ast": self.guard_ast.to_dict() if self.guard_ast is not None else None,
            "priority": int(self.priority),
            "edge_type": self.edge_type.value if isinstance(self.edge_type, EdgeType) else str(self.edge_type),
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transition:
        raw_type = data.get("edge_type") or EdgeType.NORMAL.value
        try:
            edge_type = EdgeType(str(raw_type))
        except ValueError:
            edge_type = str(raw_type)
        return cls(
            id=str(data.get("id") or ""),
            from_step=str(data.get("from_step") or ""),
            to_step=str(data.get("to_step") or ""),
            guard_ast=parse_guard(data.get("guard_ast")),
            priority=int(data.get("priority") or 0),
            edge_type=edge_type,
            source_id=str(data.get("source_id") or ""),
        )


@dataclass
class SequenceException:
    """Exception path (timeout / safety permit lost / feedback fault / reset)."""

    id: str = ""
    from_step: str = ""
    to_step: str = ""
    trigger: ExceptionTrigger = ExceptionTrigger.TIMEOUT
    guard_ast: GuardAST | None = None
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_step": self.from_step,
            "to_step": self.to_step,
            "trigger": self.trigger.value if isinstance(self.trigger, ExceptionTrigger) else str(self.trigger),
            "guard_ast": self.guard_ast.to_dict() if self.guard_ast is not None else None,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceException:
        raw = data.get("trigger") or ExceptionTrigger.TIMEOUT.value
        try:
            trigger = ExceptionTrigger(str(raw))
        except ValueError:
            trigger = str(raw)
        return cls(
            id=str(data.get("id") or ""),
            from_step=str(data.get("from_step") or ""),
            to_step=str(data.get("to_step") or ""),
            trigger=trigger,
            guard_ast=parse_guard(data.get("guard_ast")),
            source_id=str(data.get("source_id") or ""),
        )


@dataclass
class Mode:
    """Operating mode declaration."""

    id: str = ""
    name: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "enabled": bool(self.enabled)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mode:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class SequenceIR:
    """The process half of the single writable semantic truth."""

    id: str = "SEQ_1"
    mode: str = "AUTO"
    initial_step: str = ""
    steps: list[Step] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    exceptions: list[SequenceException] = field(default_factory=list)
    modes: list[Mode] = field(default_factory=list)
    parallel_groups: list[dict[str, Any]] = field(default_factory=list)
    source_id: str = ""

    def step_ids(self) -> list[str]:
        """All step IDs in declaration order."""
        return [step.id for step in self.steps]

    def step_index(self) -> dict[str, Step]:
        """Map step id to step object."""
        return {step.id: step for step in self.steps}

    def transition_index(self) -> dict[str, Transition]:
        """Map transition id to transition object."""
        return {tr.id: tr for tr in self.transitions}

    def outgoing(self, step_id: str) -> list[Transition]:
        """Outgoing transitions sorted by (priority desc, id asc) — deterministic."""
        edges = [tr for tr in self.transitions if tr.from_step == step_id]
        return sorted(edges, key=lambda tr: (-int(tr.priority), tr.id))

    def validate_references(self) -> list[str]:
        """Static unknown-reference checks; every issue names its source id."""
        issues: list[str] = []
        ids = set(self.step_ids())
        if self.initial_step and self.initial_step not in ids:
            issues.append(f"initial_step {self.initial_step!r} does not reference a known step")
        for step in self.steps:
            if step.failure_target and step.failure_target not in ids:
                issues.append(f"step {step.id}: failure_target {step.failure_target!r} is unknown")
        for tr in self.transitions:
            if tr.from_step not in ids:
                issues.append(f"transition {tr.id}: from_step {tr.from_step!r} is unknown")
            if tr.to_step not in ids:
                issues.append(f"transition {tr.id}: to_step {tr.to_step!r} is unknown")
        for exc in self.exceptions:
            if exc.from_step and exc.from_step not in ids:
                issues.append(f"exception {exc.id}: from_step {exc.from_step!r} is unknown")
            if exc.to_step not in ids:
                issues.append(f"exception {exc.id}: to_step {exc.to_step!r} is unknown")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "initial_step": self.initial_step,
            "steps": [step.to_dict() for step in self.steps],
            "transitions": [tr.to_dict() for tr in self.transitions],
            "exceptions": [exc.to_dict() for exc in self.exceptions],
            "modes": [mode.to_dict() for mode in self.modes],
            "parallel_groups": [dict(group) for group in self.parallel_groups],
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceIR:
        return cls(
            id=str(data.get("id") or "SEQ_1"),
            mode=str(data.get("mode") or "AUTO"),
            initial_step=str(data.get("initial_step") or ""),
            steps=[Step.from_dict(x) if isinstance(x, dict) else x for x in (data.get("steps") or [])],
            transitions=[Transition.from_dict(x) if isinstance(x, dict) else x for x in (data.get("transitions") or [])],
            exceptions=[SequenceException.from_dict(x) if isinstance(x, dict) else x for x in (data.get("exceptions") or [])],
            modes=[Mode.from_dict(x) if isinstance(x, dict) else x for x in (data.get("modes") or [])],
            parallel_groups=[dict(x) for x in (data.get("parallel_groups") or []) if isinstance(x, dict)],
            source_id=str(data.get("source_id") or ""),
        )


def _actions(raw: Any) -> list[Action]:
    """Normalise a list of action dicts / Action objects."""
    result: list[Action] = []
    for item in raw or []:
        if isinstance(item, Action):
            result.append(item)
        elif isinstance(item, dict):
            result.append(Action.from_dict(item))
    return result
