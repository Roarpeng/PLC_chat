"""Explicit process spec -> typed Process Contract (new-project wizard §b).

The wizard's step-orchestration stage submits an *explicit* spec: the typed
devices plus operations whose steps the engineer authored in the UI (name /
guard / actions / timeout / failure exit / next — no free-form wiring). This
module lowers that spec to a contract dict (``ProcessContract.from_dict``
compatible) with the same fail-closed posture as the rest of the API:

* next / failure_target must reference an existing step id (or be empty);
* every action command must be offered by the command set of the operation's
  resources (type contract from ``device_catalog``) — unambiguous target;
* timeout_ms, when present, must be > 0;
* each operation needs >= 1 step and only existing resource ids;
* guard must be ``{signal, op: "==", value: bool}``.

Any violation raises ValueError; the HTTP route maps that to 422 {error}.

Type contracts and device->resource assembly are REUSED from
``device_catalog`` via import (``build_contract_from_hardware`` harvests the
resources / conflict invariants) — nothing re-declared here.
"""
from __future__ import annotations

from typing import Any

from processos.device_catalog import DEVICE_TYPES, build_contract_from_hardware

#: Same assembly-line defaults build_contract_from_hardware applies to every
#: synthesized operation (kept identical so both entrances agree).
UNIT_PRECONDITIONS = ["unit.auto_permit", "air.ok", "guard.closed"]

#: Steps authored in the UI carry no scenario — we never synthesize replay
#: tests for sequences a human has not confirmed (honest empty list, §0).
SCENARIOS: list[dict[str, Any]] = []


def _guard_expr(op_id: str, step_id: str, guard: Any) -> str:
    """{signal, op, value} -> guard expression string; "" when absent."""
    if guard is None or guard == "":
        return ""
    if not isinstance(guard, dict):
        raise ValueError(f"{op_id}.{step_id}: guard must be an object {{signal, op, value}}")
    signal = str(guard.get("signal", ""))
    if not signal:
        raise ValueError(f"{op_id}.{step_id}: guard.signal is required")
    if guard.get("op") != "==":
        raise ValueError(f"{op_id}.{step_id}: guard.op must be '==' (got {guard.get('op')!r})")
    value = guard.get("value")
    if not isinstance(value, bool):
        raise ValueError(f"{op_id}.{step_id}: guard.value must be a boolean")
    return signal if value else f"NOT {signal}"


def _resolve_action_target(op_id: str, step_id: str, command: str,
                           resources_by_id: dict[str, dict[str, Any]],
                           rids: list[str]) -> str:
    """The unique op resource whose typed command set contains ``command``.

    Fail-closed: zero owners -> unknown command; two owners -> ambiguous (the
    wizard offers no per-action wiring, so we refuse to guess §3.1).
    """
    if not isinstance(command, str) or not command:
        raise ValueError(f"{op_id}.{step_id}: action.command must be a non-empty string")
    owners = [rid for rid in rids if command in resources_by_id[rid]["commands"]]
    if not owners:
        owned = sorted({c for rid in rids for c in resources_by_id[rid]["commands"]})
        raise ValueError(
            f"{op_id}.{step_id}: command {command!r} not offered by any resource of "
            f"this operation (available: {', '.join(owned) or 'none'})")
    if len(owners) > 1:
        raise ValueError(
            f"{op_id}.{step_id}: command {command!r} is ambiguous between resources "
            f"{', '.join(owners)} — keep one owning resource per operation")
    return owners[0]


def _step_of(op_id: str, raw: dict[str, Any], index: int,
             resources_by_id: dict[str, dict[str, Any]], rids: list[str],
             step_ids: list[str]) -> dict[str, Any]:
    sid = str(raw.get("id") or f"S_{index + 1:02d}")
    actions = raw.get("actions") or []
    if not isinstance(actions, list):
        raise ValueError(f"{op_id}.{sid}: actions must be a list")
    entry: list[dict[str, Any]] = []
    exit_: list[dict[str, Any]] = []
    for a in actions:
        command = a.get("command") if isinstance(a, dict) else None
        target = _resolve_action_target(op_id, sid, command, resources_by_id, rids)
        # Pulse convention shared with device_catalog: set on entry, clear on
        # exit of the SAME step so the single-writer invariant holds.
        entry.append({"target": target, "command": command, "value": True})
        exit_.append({"target": target, "command": command, "value": False})
    raw_timeout = raw.get("timeout_ms")
    timeout = int(raw_timeout) if raw_timeout is not None else 0
    if raw_timeout is not None and timeout <= 0:
        raise ValueError(f"{op_id}.{sid}: timeout_ms must be > 0 (got {timeout})")
    nxt = str(raw.get("next") or "")
    failure = str(raw.get("failure_target") or "")
    for field, ref in (("next", nxt), ("failure_target", failure)):
        if ref and ref not in step_ids:
            raise ValueError(f"{op_id}.{sid}: {field} {ref!r} does not reference a step of this operation")
    return {
        "id": sid, "name": str(raw.get("name", "")),
        "entry": entry, "cyclic": [], "exit": exit_,
        "guard": _guard_expr(op_id, sid, raw.get("guard")),
        "duration_ms": 0, "timeout_ms": timeout,
        "next": nxt, "failure_target": failure,
        "is_fault": False, "reset_guard": "",
    }


def _operation_of(raw: dict[str, Any], index: int, unit: str,
                  resources_by_id: dict[str, dict[str, Any]],
                  seen_ids: set[str]) -> dict[str, Any]:
    em = str(raw.get("em") or f"EM_{index + 1:02d}")
    op_id = f"OP_{em}"
    if op_id in seen_ids:
        raise ValueError(f"duplicate operation em {em!r} (operation ids would collide)")
    seen_ids.add(op_id)
    rids = [str(r) for r in (raw.get("resource_ids") or [])]
    if not rids:
        raise ValueError(f"{op_id}: at least one resource_id is required")
    for rid in rids:
        if rid not in resources_by_id:
            raise ValueError(f"{op_id}: resource_ids references unknown resource {rid!r}")
    raw_steps = raw.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"{op_id}: at least 1 step is required")
    step_ids = [str(s.get("id") or f"S_{j + 1:02d}") for j, s in enumerate(raw_steps)]
    if len(set(step_ids)) != len(step_ids):
        raise ValueError(f"{op_id}: duplicate step ids")
    steps = [_step_of(op_id, s, j, resources_by_id, rids, step_ids)
             for j, s in enumerate(raw_steps)]
    return {
        "id": op_id, "name": str(raw.get("name", "")), "unit": unit, "em": em,
        "resource_ids": rids, "preconditions": list(UNIT_PRECONDITIONS),
        "steps": steps, "acceptance": [],
    }


def build_contract_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Lower an explicit wizard spec into a ProcessContract-compatible dict.

    Spec shape (locked, submitted verbatim by the wizard):
    {id, name, profile_id?, cpu/device_name/network?, devices: [{type, name,
    id, params}], operations: [{em, name?, resource_ids, steps: [{id, name,
    guard?: {signal, op, value}, actions: [{command}], timeout_ms?,
    failure_target?, next?}]}], invariants?: [{id, expr, scope, severity}]}
    """
    devices = spec.get("devices") or []
    if not devices:
        raise ValueError("spec.devices: at least 1 device is required")
    for i, dev in enumerate(devices):
        kind = str(dev.get("type", ""))
        if kind not in DEVICE_TYPES:
            raise ValueError(f"device {i}: unknown device type {kind!r} (not in catalog)")
        rid = str(dev.get("id") or f"CM_{i + 1:02d}")
        if not rid:
            raise ValueError(f"device {i}: id must not be empty")
    device_ids = [str(d.get("id") or f"CM_{i + 1:02d}") for i, d in enumerate(devices)]
    if len(set(device_ids)) != len(device_ids):
        raise ValueError("spec.devices: duplicate device ids")

    operations_raw = spec.get("operations") or []
    if not operations_raw:
        raise ValueError("spec.operations: at least 1 operation is required")

    # Reuse from-hardware assembly: typed resources (commands/feedback/status,
    # io_bindings unbound, param defaults) + conflict invariants per type.
    # (cpu key omitted when absent: from-hardware reads it unconditionally.)
    hw_config: dict[str, Any] = {
        "id": spec.get("id", "PRJ_SPEC"), "name": spec.get("name", "新建项目"),
        "devices": devices,
    }
    if spec.get("cpu"):
        hw_config["cpu"] = spec.get("cpu")
    base = build_contract_from_hardware(hw_config)
    resources = base["resources"]
    resources_by_id = {r["id"]: r for r in resources}

    unit = str(spec.get("unit", "U_ASSEMBLY"))
    seen_op_ids: set[str] = set()
    operations = [_operation_of(raw, i, unit, resources_by_id, seen_op_ids)
                  for i, raw in enumerate(operations_raw)]

    invariants: list[dict[str, Any]] = list(base["invariants"])
    invariant_ids = {inv["id"] for inv in invariants}
    for raw_inv in spec.get("invariants") or []:
        inv = {
            "id": str(raw_inv.get("id", "")), "expr": str(raw_inv.get("expr", "")),
            "scope": str(raw_inv.get("scope", "global")),
            "severity": str(raw_inv.get("severity", "error")),
        }
        if not inv["id"] or not inv["expr"]:
            raise ValueError("spec.invariants: id and expr are required")
        if inv["id"] in invariant_ids:
            raise ValueError(f"spec.invariants: duplicate invariant id {inv['id']!r}")
        if inv["severity"] not in ("error", "warning"):
            raise ValueError(f"spec.invariants: bad severity {inv['severity']!r} on {inv['id']!r}")
        invariant_ids.add(inv["id"])
        invariants.append(inv)

    cpu = spec.get("cpu") or {}
    return {
        "id": spec.get("id", "PRJ_SPEC"),
        "name": str(spec.get("name", "新建项目")) + "工艺契约",
        "target_framework": "siemens-af-basic@unverified",
        "unit": unit, "schema": "process-contract/1.0",
        "resources": resources, "operations": operations, "invariants": invariants,
        "open_questions": [{
            "id": "Q_SAFETY_STOP",
            "question": "全局安全许可撤销时设备应保持还是退回？须现场工程决策。",
            "affects": [op["id"] for op in operations],
            "severity": "blocking", "resolution": None, "resolved_by": None,
        }],
        "scenarios": list(SCENARIOS),
        "provenance": {"origin": "explicit-spec", "confirmed_by": None,
                       "evidence_refs": [f"CPU:{cpu.get('order_no', '')}"] if cpu else []},
        "hardware": {"cpu": spec.get("cpu"), "io_modules": [], "expansion": [],
                     "network": spec.get("network", {})},
    }
