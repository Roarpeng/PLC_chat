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

PATCH_OPS = ("set", "add", "remove")


class PatchError(ValueError):
    """Invalid patch (maps to HTTP 422)."""


class RevisionConflict(RuntimeError):
    """base_revision does not match current revision (maps to HTTP 409)."""


@dataclass
class PatchOp:
    op: str
    path: str
    value: Any = None

    def __post_init__(self) -> None:
        if self.op not in PATCH_OPS:
            raise PatchError(f"unsupported op {self.op!r}; allowed {PATCH_OPS}")
        if not self.path.startswith("/"):
            raise PatchError(f"path must start with '/': {self.path!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "path": self.path, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatchOp":
        return cls(op=str(data["op"]), path=str(data["path"]), value=data.get("value"))


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