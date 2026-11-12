"""Atomic, optimistic-concurrency Patch engine (G1 / US-2 / US-6).

A patch either applies completely to a candidate IR copy or leaves the
authoritative IR byte-identical. ``base_revision`` mismatch raises a 409-style
conflict; any semantic/type/reference failure raises a 422-style error.
"""
from __future__ import annotations

import copy
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from plc_engine.components.driver_spec import ComponentDefinition, DriverSpec
from plc_engine.engineering_ir.address_policy import imported_address_is_backed, source_value
from plc_engine.engineering_ir.contracts import (
    PATCH_OPS,
    PATCHABLE_COMPONENT_FIELDS,
    PATCHABLE_STEP_FIELDS,
    ErrorCode,
    assert_stable_id,
)
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import (
    CandidatePatch,
    ChangeOp,
    EngineeringIRV2,
    PatchResultV2,
)
from plc_engine.process.guard_ast import GuardAST, GuardValidationError
from plc_engine.process.sequence_ir import Action, SequenceException, Step, Transition


class PatchConflictError(Exception):
    """409 BASE_REVISION_CONFLICT: client base_revision is stale."""

    def __init__(self, current_revision: int, requested_revision: int) -> None:
        super().__init__(
            f"base_revision {requested_revision} != current_revision {current_revision}"
        )
        self.code = ErrorCode.BASE_REVISION_CONFLICT.value
        self.current_revision = int(current_revision)
        self.requested_revision = int(requested_revision)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "current_revision": self.current_revision,
            "requested_revision": self.requested_revision,
        }


class SemanticValidationError(Exception):
    """422 SEMANTIC_VALIDATION_FAILED: IR stays unchanged."""

    def __init__(self, issues: list[dict[str, Any]], unchanged_ir_hash: str) -> None:
        super().__init__(f"semantic validation failed with {len(issues)} issue(s)")
        self.code = ErrorCode.SEMANTIC_VALIDATION_FAILED.value
        self.issues = issues
        self.unchanged_ir_hash = unchanged_ir_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "issues": self.issues,
            "unchanged_ir_hash": self.unchanged_ir_hash,
        }


@dataclass
class SequencePatch(CandidatePatch):
    """A SequenceCanvas-originated patch; identical atomic semantics."""

    canvas_view: str = "sequence"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["canvas_view"] = self.canvas_view
        payload["extra"] = dict(self.extra)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequencePatch:
        base = CandidatePatch.from_dict(data)
        return cls(
            candidate_id=base.candidate_id,
            project_id=base.project_id,
            base_revision=base.base_revision,
            request_id=base.request_id,
            before_hash=base.before_hash,
            after_hash=base.after_hash,
            ops=base.ops,
            explanation=base.explanation,
            questions=base.questions,
            evidence_level=base.evidence_level,
            canvas_view=str(data.get("canvas_view") or "sequence"),
            extra=dict(data.get("extra") or {}),
        )


def new_request_id() -> str:
    """Generate a short request id used for idempotency."""
    return f"req_{uuid.uuid4().hex[:16]}"


#: P-10: reject absurd revisions instead of letting them flow into the DB.
MAX_BASE_REVISION = 2**31 - 1


def validate_base_revision(value: Any) -> int:
    """Strict, structured validation of ``base_revision`` (P-10).

    ``type(x) is int`` rejects bool (a subclass of int), floats such as 1.5,
    strings and None. Out-of-range / negative values raise the SAME structured
    422 exception as any other semantic validation failure, never a bare
    ``ValueError`` or ``TypeError`` at the API boundary.
    """
    if type(value) is not int or value < 0 or value > MAX_BASE_REVISION:
        raise SemanticValidationError(
            [{
                "source_id": "base_revision",
                "node_id": "base_revision",
                "field": "base_revision",
                "reason": (
                    f"base_revision must be a non-negative int <= {MAX_BASE_REVISION} "
                    f"(got {value!r}, type={type(value).__name__})"
                ),
            }],
            "",
        )
    return value


def make_patch(
    project_id: str,
    base_revision: int,
    ops: list[dict[str, Any] | ChangeOp],
    *,
    request_id: str = "",
    explanation: str = "",
    questions: list[str] | None = None,
) -> CandidatePatch:
    """Build a CandidatePatch from plain op dicts (schema-facing helper)."""
    normalised: list[ChangeOp] = []
    for raw in ops:
        if isinstance(raw, ChangeOp):
            normalised.append(raw)
            continue
        if not isinstance(raw, dict):
            raise SemanticValidationError(
                [{"source_id": "", "reason": "op must be an object"}], ""
            )
        op_name = str(raw.get("op") or "")
        payload = {k: v for k, v in raw.items() if k not in ("op", "target_source_id", "ir_id", "source_id")}
        normalised.append(
            ChangeOp(
                op=op_name,
                target_source_id=str(raw.get("target_source_id") or ""),
                ir_id=str(raw.get("ir_id") or ""),
                payload=payload,
                source_id=str(raw.get("source_id") or raw.get("ir_id") or raw.get("step_id") or ""),
            )
        )
    revision = validate_base_revision(base_revision)
    return CandidatePatch(
        candidate_id=f"cand_{uuid.uuid4().hex[:16]}",
        project_id=project_id,
        base_revision=revision,
        request_id=request_id or new_request_id(),
        ops=normalised,
        explanation=explanation,
        questions=list(questions or []),
        evidence_level=EvidenceLevel.OFFLINE,
    )


def _issue(source_id: str, reason: str, field_name: str = "") -> dict[str, Any]:
    return {"source_id": source_id, "node_id": source_id, "field": field_name, "reason": reason}


def _apply_op(candidate: EngineeringIRV2, op: ChangeOp) -> list[str]:
    """Apply one whitelisted op to the candidate IR; return changed IR ids."""
    name = op.op
    payload = op.payload
    if name not in PATCH_OPS:
        raise ValueError(f"unknown patch op: {name!r} (fail-closed)")

    if name == "set_step_parameter":
        step_id = str(payload.get("step_id") or op.ir_id)
        field_name = str(payload.get("field") or "")
        step = candidate.process.step_index().get(step_id)
        if step is None:
            raise ValueError(f"unknown step {step_id!r}")
        if field_name not in PATCHABLE_STEP_FIELDS:
            raise ValueError(f"field {field_name!r} is not patchable on a step")
        value = payload.get("value")
        if field_name in ("min_duration_ms", "max_duration_ms"):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative int")
            if field_name == "min_duration_ms" and step.max_duration_ms and value > step.max_duration_ms:
                raise ValueError("min_duration_ms must not exceed max_duration_ms")
            if field_name == "max_duration_ms" and value and value < step.min_duration_ms:
                raise ValueError("max_duration_ms must not be below min_duration_ms")
        elif field_name == "name":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("step name must be a non-empty string")
        elif field_name == "failure_target":
            if value and value not in candidate.process.step_ids():
                raise ValueError(f"unknown failure_target {value!r}")
        elif field_name in ("entry_actions", "cyclic_actions", "exit_actions"):
            if not isinstance(value, list):
                raise ValueError(f"{field_name} must be a list of actions")
            value = [a if isinstance(a, Action) else Action.from_dict(a) for a in value if isinstance(a, (Action, dict))]
        setattr(step, field_name, value)
        return [step_id]

    if name == "set_component_parameter":
        component_id = str(payload.get("component_id") or op.ir_id)
        field_name = str(payload.get("field") or "")
        component = next((c for c in candidate.components if c.id == component_id), None)
        if component is None:
            raise ValueError(f"unknown component {component_id!r}")
        if field_name not in PATCHABLE_COMPONENT_FIELDS:
            raise ValueError(f"field {field_name!r} is not patchable on a component")
        value = payload.get("value")
        if field_name == "io_bindings":
            if value is not None and not isinstance(value, dict):
                raise ValueError("io_bindings must be null or an object")
            if isinstance(value, dict):
                for key, address in value.items():
                    if isinstance(address, str) and address.startswith("%"):
                        # P-09: identical fail-closed policy as ValidationEngine.
                        # source=imported alone is NOT sufficient; the original
                        # source_binding must be present in the IR.
                        if not imported_address_is_backed(
                            candidate, component_id, source_value(component), address
                        ):
                            raise ValueError(
                                f"greenfield component must not invent physical address {address} "
                                "(imported address requires an original source_binding)"
                            )
        elif field_name == "name":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("component name must be a non-empty string")
        elif field_name == "parameters":
            if not isinstance(value, dict):
                raise ValueError("parameters must be an object")
        setattr(component, field_name, value)
        return [component_id]

    if name == "set_component_name":
        component_id = str(payload.get("component_id") or op.ir_id)
        component = next((c for c in candidate.components if c.id == component_id), None)
        if component is None:
            raise ValueError(f"unknown component {component_id!r}")
        new_name = str(payload.get("name") or "")
        if not new_name.strip():
            raise ValueError("component name must be a non-empty string")
        component.name = new_name  # id is intentionally untouched
        return [component_id]

    if name == "add_component":
        raw = payload.get("component")
        if not isinstance(raw, dict):
            raise ValueError("add_component requires a 'component' object")
        component = ComponentDefinition.from_dict(raw)
        if not component.id:
            raise ValueError("add_component requires a stable component id")
        if any(c.id == component.id for c in candidate.components):
            raise ValueError(f"duplicate component id {component.id!r}")
        candidate.components.append(component)
        raw_spec = payload.get("driver_spec")
        if isinstance(raw_spec, dict):
            spec = DriverSpec.from_dict(raw_spec)
            if not spec.id:
                spec.id = f"DRV_{component.id}"
            candidate.driver_specs[spec.id] = spec
            component.driver_spec_id = spec.id
        return [component.id]

    if name == "remove_component":
        component_id = str(payload.get("component_id") or op.ir_id)
        component = next((c for c in candidate.components if c.id == component_id), None)
        if component is None:
            raise ValueError(f"unknown component {component_id!r}")
        referenced = [
            action.id
            for step in candidate.process.steps
            for action in step.all_actions()
            if action.target_component_id == component_id
        ]
        if referenced:
            raise ValueError(f"cannot remove component {component_id!r}: referenced by actions {referenced}")
        candidate.components.remove(component)
        if component.driver_spec_id in candidate.driver_specs:
            del candidate.driver_specs[component.driver_spec_id]
        return [component_id]

    if name == "add_step":
        raw = payload.get("step")
        if not isinstance(raw, dict):
            raise ValueError("add_step requires a 'step' object")
        step = Step.from_dict(raw)
        if not step.id:
            raise ValueError("add_step requires a stable step id")
        if step.id in candidate.process.step_ids():
            raise ValueError(f"duplicate step id {step.id!r}")
        candidate.process.steps.append(step)
        if not candidate.process.initial_step:
            candidate.process.initial_step = step.id
        return [step.id]

    if name == "add_transition":
        raw = dict(payload)
        transition_id = str(raw.pop("id", "") or op.ir_id)
        if not transition_id:
            raise ValueError("add_transition requires a stable transition id")
        assert_stable_id(transition_id, "transition")
        if transition_id in candidate.process.transition_index():
            raise ValueError(f"duplicate transition id {transition_id!r}")
        guard_raw = raw.get("guard") if "guard" in raw else raw.get("guard_ast")
        guard = GuardAST.from_dict(guard_raw) if isinstance(guard_raw, dict) else (guard_raw if isinstance(guard_raw, GuardAST) else None)
        transition = Transition(
            id=transition_id,
            from_step=str(raw.get("from_step") or raw.get("from") or ""),
            to_step=str(raw.get("to_step") or raw.get("to") or ""),
            guard_ast=guard,
            priority=int(raw.get("priority") or 0),
            source_id=str(raw.get("source_id") or transition_id),
        )
        candidate.process.transitions.append(transition)
        return [transition_id]

    if name == "remove_transition":
        transition_id = str(payload.get("transition_id") or op.ir_id)
        transition = candidate.process.transition_index().get(transition_id)
        if transition is None:
            raise ValueError(f"unknown transition {transition_id!r}")
        candidate.process.transitions.remove(transition)
        return [transition_id]

    if name == "set_guard":
        transition_id = str(payload.get("transition_id") or op.ir_id)
        transition = candidate.process.transition_index().get(transition_id)
        if transition is None:
            raise ValueError(f"unknown transition {transition_id!r}")
        guard_raw = payload.get("guard") if "guard" in payload else payload.get("guard_ast")
        if isinstance(guard_raw, dict):
            transition.guard_ast = GuardAST.from_dict(guard_raw)
        elif isinstance(guard_raw, GuardAST):
            transition.guard_ast = guard_raw
        else:
            raise ValueError("set_guard requires a structured GuardAST object (free text forbidden)")
        return [transition_id]

    if name == "add_exception":
        raw = payload.get("exception")
        if not isinstance(raw, dict):
            raise ValueError("add_exception requires an 'exception' object")
        exception = SequenceException.from_dict(raw)
        if not exception.id:
            raise ValueError("add_exception requires a stable id")
        candidate.process.exceptions.append(exception)
        return [exception.id]

    if name == "set_view_layout":
        layout = payload.get("layout")
        if not isinstance(layout, dict):
            raise ValueError("set_view_layout requires an object layout")
        candidate.views["layout"] = copy.deepcopy(layout)
        return []  # UI-only change: no semantic id is dirty

    if name == "set_hardware_intent":
        field_name = str(payload.get("field") or "")
        if field_name not in ("cpu_template", "device_type_identifier", "io_binding", "capability_receipt_id"):
            raise ValueError(f"hardware field {field_name!r} is not patchable")
        value = payload.get("value")
        if field_name == "io_binding" and value not in (None, "unbound"):
            raise ValueError("greenfield hardware io_binding must stay 'unbound'/null")
        setattr(candidate.hardware, field_name, value)
        return [f"hardware.{field_name}"]

    if name == "set_sequence_mode":
        mode = str(payload.get("mode") or "")
        if not mode:
            raise ValueError("mode must be non-empty")
        candidate.process.mode = mode
        return [candidate.process.id]

    raise ValueError(f"unhandled patch op: {name!r}")


def apply_patch_atomic(
    ir: EngineeringIRV2,
    patch: CandidatePatch,
) -> tuple[EngineeringIRV2, PatchResultV2]:
    """Apply a patch to a copy and return ``(new_ir, result)``.

    Raises:
        PatchConflictError: 409 when ``base_revision`` is stale.
        SemanticValidationError: 422 for any schema/type/reference/graph issue.
    """
    if patch.project_id and patch.project_id != ir.project_id:
        raise SemanticValidationError(
            [_issue(ir.project_id, "patch.project_id does not match the workspace")],
            ir.ir_sha256,
        )
    if int(patch.base_revision) != int(ir.revision):
        raise PatchConflictError(ir.revision, int(patch.base_revision))

    unchanged_hash = ir.ir_sha256 or ir.semantic_hash()
    candidate = EngineeringIRV2.from_dict(ir.to_dict())
    changed: list[str] = []
    issues: list[dict[str, Any]] = []
    for index, op in enumerate(patch.ops):
        try:
            changed.extend(_apply_op(candidate, op))
        except (ValueError, TypeError, KeyError, GuardValidationError) as exc:
            issues.append(_issue(op.source_id or op.ir_id or f"ops[{index}]", str(exc), op.op))
    if issues:
        raise SemanticValidationError(issues, unchanged_hash)

    from plc_engine.engineering_ir.validation import ValidationEngine

    report = ValidationEngine().validate(candidate)
    if not report.passed:
        raise SemanticValidationError(report.issues, unchanged_hash)

    candidate.revision = int(ir.revision) + 1
    candidate.refresh_hash()
    result = PatchResultV2(
        revision=candidate.revision,
        ir_sha256=candidate.ir_sha256,
        changed_ir_ids=sorted(set(changed)),
        source_map_dirty=_source_map_dirty(changed),
        warnings=list(report.warnings),
        evidence_level=EvidenceLevel.OFFLINE,
        request_id=patch.request_id,
        idempotent_hit=False,
    )
    return candidate, result


def _source_map_dirty(changed_ir_ids: list[str]) -> list[str]:
    """Determine which generated TIA blocks need re-derivation."""
    dirty: set[str] = set()
    for ident in changed_ir_ids:
        if ident.startswith("hardware."):
            continue
        if ident.startswith("S") or ident.startswith("tr") or ident.startswith("T"):
            dirty.add("FB_Sequence")
        else:
            dirty.add("FB_Drivers")
    return sorted(dirty)


def random_atomic_patch(ir: EngineeringIRV2, rng: random.Random) -> CandidatePatch:
    """Generate one deterministic-in-seed, always-valid random patch.

    Used by the 100-patch atomicity test; produces a ``set_view_layout`` or a
    ``set_step_parameter`` op depending on available steps.
    """
    steps = ir.process.step_ids()
    if steps and rng.random() < 0.5:
        step_id = rng.choice(steps)
        value = rng.choice([0, 100, 500, 1000, 1500, 2000, 3000])
        return make_patch(
            ir.project_id,
            ir.revision,
            [{"op": "set_step_parameter", "step_id": step_id, "field": "min_duration_ms", "value": value}],
        )
    return make_patch(
        ir.project_id,
        ir.revision,
        [{"op": "set_view_layout", "layout": {"x": rng.randint(0, 9999), "y": rng.randint(0, 9999)}}],
    )
