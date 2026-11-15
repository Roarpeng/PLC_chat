"""Versioned atomic Patches over a Process Contract (blueprint §2 / R3 D-09).

Every edit is a structured Patch carrying ``base_revision`` + ``request_id``.
A stale base revision raises :class:`RevisionConflict` (HTTP 409); an invalid
op or resulting contract raises :class:`PatchError` (HTTP 422). The contract is
the only writable truth — derived SCL/Trace/graph are never patched directly.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .model import ProcessContract

PATCH_OPS = ("set", "add", "remove", "set_scenario_timing", "set_operation_schedule")

#: numeric-only scenario input-event fields ``set_scenario_timing`` may change
#: (fail-closed: a timing op can never rewrite signals/expectations, only when
#: a recorded event fires — PLAN §10 场景同步 with the changed step timing).
SCENARIO_TIMING_FIELDS = ("t_ms",)

#: entry keys a ``set_operation_schedule`` declaration accepts (fail-closed:
#: no free-form payload — the op declares EM run order / resource occupation /
#: parallel groups only, 需求 c).
SCHEDULE_ENTRY_FIELDS = ("em", "order", "resource_ids", "mode", "parallel_with")


class PatchError(ValueError):
    """Invalid patch (maps to HTTP 422)."""


class RevisionConflict(RuntimeError):
    """base_revision does not match current revision (maps to HTTP 409)."""


@dataclass
class PatchOp:
    op: str
    path: str
    value: Any = None
    #: ``set_scenario_timing`` only — names the scenario, the input-event index
    #: and the numeric field to retime (validated in ``__post_init__``).
    scenario: str = ""
    index: int = -1
    field: str = ""

    def __post_init__(self) -> None:
        if self.op not in PATCH_OPS:
            raise PatchError(f"unsupported op {self.op!r}; allowed {PATCH_OPS}")
        if self.op == "set_scenario_timing":
            self._validate_scenario_timing()
        elif self.op == "set_operation_schedule":
            if not self.path:
                self.path = "/schedule"  # canonical audit/diff target
            self._validate_operation_schedule()
        elif not self.path.startswith("/"):
            raise PatchError(f"path must start with '/': {self.path!r}")

    def _validate_scenario_timing(self) -> None:
        if not self.scenario:
            raise PatchError("set_scenario_timing requires 'scenario'")
        if self.field not in SCENARIO_TIMING_FIELDS:
            raise PatchError(
                f"set_scenario_timing field must be one of {SCENARIO_TIMING_FIELDS}, "
                f"got {self.field!r} (only numeric timing fields may be retimed)")
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise PatchError("set_scenario_timing requires a non-negative integer 'index'")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or self.value < 0:
            raise PatchError(
                f"set_scenario_timing requires a non-negative numeric value, got {self.value!r}")

    @property
    def timing_path(self) -> str:
        """Canonical doc path of a timing op (used for diff/audit records)."""
        return f"/scenarios/{self.scenario}/inputs/{self.index}/{self.field}"

    def _validate_operation_schedule(self) -> None:
        """Shape + intra-schedule validation of a unit orchestration declaration.

        Constructor-time half of the double validation (fail-closed). Live-contract
        references (em / resource existence) are re-checked against the doc in
        :func:`_apply_operation_schedule`.
        """
        if not isinstance(self.value, list):
            raise PatchError("set_operation_schedule requires a 'schedule' list")
        seen_em: set[str] = set()
        seen_order: set[int] = set()
        for i, entry in enumerate(self.value):
            if not isinstance(entry, dict):
                raise PatchError(f"set_operation_schedule entry[{i}] must be an object")
            unknown = set(entry) - set(SCHEDULE_ENTRY_FIELDS)
            if unknown:
                raise PatchError(
                    f"set_operation_schedule entry[{i}] has unknown fields {sorted(unknown)}; "
                    f"allowed {sorted(SCHEDULE_ENTRY_FIELDS)}")
            em = entry.get("em")
            if not isinstance(em, str) or not em:
                raise PatchError(f"set_operation_schedule entry[{i}] requires a non-empty 'em'")
            if em in seen_em:
                raise PatchError(f"set_operation_schedule: duplicate em {em!r}")
            seen_em.add(em)
            order = entry.get("order")
            if isinstance(order, bool) or not isinstance(order, int) or order < 0:
                raise PatchError(
                    f"set_operation_schedule entry[{i}] ({em}): 'order' must be a "
                    f"non-negative integer, got {order!r}")
            if order in seen_order:
                raise PatchError(f"set_operation_schedule: duplicate order {order}")
            seen_order.add(order)
            rids = entry.get("resource_ids")
            if not isinstance(rids, list) or any(not isinstance(r, str) for r in rids):
                raise PatchError(
                    f"set_operation_schedule entry[{i}] ({em}): 'resource_ids' must be a list of strings")
            if entry.get("mode", "") != "" and not isinstance(entry.get("mode"), str):
                raise PatchError(
                    f"set_operation_schedule entry[{i}] ({em}): 'mode' must be a string")
            parallel = entry.get("parallel_with", [])
            if not isinstance(parallel, list) or any(not isinstance(p, str) for p in parallel):
                raise PatchError(
                    f"set_operation_schedule entry[{i}] ({em}): 'parallel_with' must be a list of strings")
            if em in parallel:
                raise PatchError(
                    f"set_operation_schedule entry[{i}] ({em}): 'parallel_with' must not name itself")
            if len(set(parallel)) != len(parallel):
                raise PatchError(
                    f"set_operation_schedule entry[{i}] ({em}): duplicate ems in 'parallel_with'")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"op": self.op, "path": self.path, "value": self.value}
        if self.op == "set_scenario_timing":
            d.update({"scenario": self.scenario, "index": self.index, "field": self.field})
        if self.op == "set_operation_schedule":
            d["schedule"] = self.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatchOp":
        op = str(data["op"])
        if op == "set_scenario_timing":
            scenario = str(data.get("scenario", ""))
            return cls(
                op=op,
                path=str(data.get("path") or f"/scenarios/{scenario}"),
                value=data.get("value"),
                scenario=scenario,
                index=data.get("index", -1),
                field=str(data.get("field", "")),
            )
        if op == "set_operation_schedule":
            return cls(
                op=op,
                path=str(data.get("path") or "/schedule"),
                value=data.get("value", data.get("schedule")),
            )
        return cls(op=op, path=str(data["path"]), value=data.get("value"))


@dataclass
class Patch:
    base_revision: int
    ops: list[PatchOp] = field(default_factory=list)
    request_id: str = ""
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_revision": self.base_revision,
            "request_id": self.request_id,
            "source": self.source,
            "ops": [o.to_dict() for o in self.ops],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Patch":
        return cls(
            base_revision=int(data["base_revision"]),
            request_id=str(data.get("request_id", "")),
            source=str(data.get("source", "user")),
            ops=[PatchOp.from_dict(o) for o in data.get("ops", [])],
        )


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def _navigate(doc: Any, segments: list[str]) -> Any:
    cur = doc
    for seg in segments:
        if isinstance(cur, list):
            item = next((x for x in cur if isinstance(x, dict) and x.get("id") == seg), None)
            if item is None:
                raise PatchError(f"no item with id {seg!r} in list")
            cur = item
        elif isinstance(cur, dict):
            if seg not in cur:
                raise PatchError(f"unknown field {seg!r}")
            cur = cur[seg]
        else:
            raise PatchError(f"cannot navigate into {type(cur).__name__} at {seg!r}")
    return cur


def _apply_op(doc: dict[str, Any], op: PatchOp) -> None:
    segs = _segments(op.path)
    if not segs:
        raise PatchError("empty path")
    if op.op == "set":
        parent = _navigate(doc, segs[:-1])
        if not isinstance(parent, dict):
            raise PatchError(f"set target parent is not an object: {op.path}")
        parent[segs[-1]] = op.value
    elif op.op == "add":
        target = _navigate(doc, segs)
        if not isinstance(target, list):
            raise PatchError(f"add target is not a list: {op.path}")
        if not isinstance(op.value, dict):
            raise PatchError(f"add value must be an object: {op.path}")
        if "id" in op.value and any(
            isinstance(x, dict) and x.get("id") == op.value["id"] for x in target
        ):
            raise PatchError(f"duplicate id {op.value['id']!r} at {op.path}")
        target.append(op.value)
    elif op.op == "remove":
        parent = _navigate(doc, segs[:-1])
        if not isinstance(parent, list):
            raise PatchError(f"remove target parent is not a list: {op.path}")
        before = len(parent)
        parent[:] = [x for x in parent if not (isinstance(x, dict) and x.get("id") == segs[-1])]
        if len(parent) == before:
            raise PatchError(f"remove found no item {segs[-1]!r} at {op.path}")
    elif op.op == "set_scenario_timing":
        _apply_scenario_timing(doc, op)
    elif op.op == "set_operation_schedule":
        _apply_operation_schedule(doc, op)


def _apply_scenario_timing(doc: dict[str, Any], op: PatchOp) -> None:
    """Retime one recorded input event of a scenario (numeric fields only).

    PLAN §10 场景同步：a step-timing change (e.g. timeout 3000→5000) must be
    mirrored in the scenarios that assert it, otherwise the fault-reset replay
    fires its Reset event before the new timeout and honestly regresses. This
    op only moves ``when`` a recorded event fires — never signals, never
    expectations (fail-closed, validated in PatchOp + against the live doc).
    """
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list):
        raise PatchError("set_scenario_timing: contract has no scenarios list")
    sc = next((s for s in scenarios
               if isinstance(s, dict) and s.get("id") == op.scenario), None)
    if sc is None:
        raise PatchError(f"set_scenario_timing: no scenario {op.scenario!r}")
    inputs = sc.get("inputs")
    if not isinstance(inputs, list):
        raise PatchError(f"set_scenario_timing: scenario {op.scenario!r} has no inputs list")
    if op.index >= len(inputs):
        raise PatchError(
            f"set_scenario_timing: scenario {op.scenario!r} input index "
            f"{op.index} out of range (0..{len(inputs) - 1})")
    event = inputs[op.index]
    if not isinstance(event, dict):
        raise PatchError(
            f"set_scenario_timing: scenario {op.scenario!r} input[{op.index}] is not an object")
    current = event.get(op.field)
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        raise PatchError(
            f"set_scenario_timing: scenario {op.scenario!r} input[{op.index}].{op.field} "
            f"is not numeric; only numeric timing fields may be retimed")
    event[op.field] = op.value


def _apply_operation_schedule(doc: dict[str, Any], op: PatchOp) -> None:
    """Declare the unit-level EM orchestration (需求 c — 工位运行步序).

    Writes the schedule declaration to the contract-level ``schedule`` field and
    materializes each entry's ``resource_ids`` onto the matching operation
    (``operations[].resource_ids``). Execution order / parallel groups stay a
    *declaration*: the current Unit generator is a deterministic pass-through
    shell, so cross-station sequencing semantics do not enter generated SCL
    (honest boundary — they take effect once the generator is extended).

    Execution-time half of the double validation: every em / resource /
    ``parallel_with`` reference is checked against the live contract doc;
    schedule-internal consistency (unique em, unique non-negative order) is
    re-verified here as well. Fail-closed: any error aborts the whole patch.
    """
    operations = doc.get("operations")
    if not isinstance(operations, list):
        raise PatchError("set_operation_schedule: contract has no operations list")
    resources = doc.get("resources")
    if not isinstance(resources, list):
        raise PatchError("set_operation_schedule: contract has no resources list")
    rids = {r.get("id") for r in resources if isinstance(r, dict)}

    by_em: dict[str, dict[str, Any]] = {}
    for o in operations:
        if not isinstance(o, dict):
            continue
        em = str(o.get("em") or "")
        if not em:
            continue
        if em in by_em:
            raise PatchError(f"set_operation_schedule: ambiguous em {em!r} (multiple operations)")
        by_em[em] = o

    declared = {str(e.get("em")) for e in op.value}
    seen_order: set[int] = set()
    for entry in op.value:
        order = entry["order"]
        if order in seen_order:
            raise PatchError(f"set_operation_schedule: duplicate order {order}")
        seen_order.add(order)
    normalized: list[dict[str, Any]] = []
    for entry in op.value:
        em = str(entry["em"])
        target = by_em.get(em)
        if target is None:
            raise PatchError(f"set_operation_schedule: no operation with em {em!r}")
        for rid in entry["resource_ids"]:
            if rid not in rids:
                raise PatchError(
                    f"set_operation_schedule: em {em!r} references unknown resource {rid!r}")
        for other in entry.get("parallel_with", []):
            if other not in declared:
                raise PatchError(
                    f"set_operation_schedule: em {em!r} declares parallel_with "
                    f"unknown em {other!r} (not part of this schedule)")
        target["resource_ids"] = list(entry["resource_ids"])
        normalized.append({
            "em": em,
            "order": entry["order"],
            "resource_ids": list(entry["resource_ids"]),
            "mode": str(entry.get("mode", "")),
            "parallel_with": list(entry.get("parallel_with", [])),
        })
    normalized.sort(key=lambda e: e["order"])
    doc["schedule"] = normalized


def read_doc_path(doc: dict[str, Any], path: str) -> tuple[Any, bool]:
    """Best-effort read of a patch path on a contract dict (never raises).

    Returns ``(value, found)``. List segments navigate by ``id`` first; a
    purely numeric segment falls back to a positional index so recorded event
    paths (``/scenarios/X/inputs/3/t_ms``) stay diffable. ``found=False`` means
    the path does not resolve on this document — callers must surface that as
    an explicit UNKNOWN, never guess (§12).
    """
    cur: Any = doc
    for seg in _segments(path):
        if isinstance(cur, list):
            item = next((x for x in cur if isinstance(x, dict) and x.get("id") == seg), None)
            if item is None and seg.isdigit():
                idx = int(seg)
                item = cur[idx] if 0 <= idx < len(cur) else None
            if item is None:
                return None, False
            cur = item
        elif isinstance(cur, dict):
            if seg not in cur:
                return None, False
            cur = cur[seg]
        else:
            return None, False
    return cur, True


def apply_patch(
    contract: ProcessContract, patch: Patch, current_revision: int
) -> tuple[ProcessContract, int]:
    """Atomically apply a patch; return (new_contract, new_revision).

    The original contract is never mutated. On any failure the caller keeps the
    previous contract and revision (fail-closed).
    """
    if patch.base_revision != current_revision:
        raise RevisionConflict(
            f"base_revision {patch.base_revision} != current {current_revision}"
        )
    doc = copy.deepcopy(contract.to_dict())
    for op in patch.ops:
        _apply_op(doc, op)
    try:
        new_contract = ProcessContract.from_dict(doc)
    except (ValueError, KeyError, TypeError) as exc:
        raise PatchError(f"patch produced an invalid contract: {exc}") from exc
    structural = new_contract.validate_structure()
    if structural:
        raise PatchError("patch broke referential integrity: " + "; ".join(structural))
    return new_contract, current_revision + 1