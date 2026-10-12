"""Trusted M1 structure inventory — every exportable unit has an explicit status.

Statuses: ``exported`` | ``failed`` | ``skipped`` | ``pending``.
Silent omission is forbidden: listed, journaled, parsed, or category-empty
units all appear with a reason when not exported.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agents.plc.tia.ir import PlcProject
from agents.plc.tia.surface import OFFICIAL_CATEGORIES

STRUCTURE_STATUSES = ("exported", "failed", "skipped", "pending")

FAILED_REASONS = frozenset({"inconsistent", "no_license", "openness_error"})
SKIPPED_REASONS = frozenset(
    {
        "know_how",
        "no_export",
        "no_import",
        "password_protected",
        "safety_login",
        "unrecognized",
        "blocks_only_filter",
    }
)
RETRYABLE_REASONS = frozenset({"inconsistent", "no_license", "openness_error"})

_KIND_LAYERS = {
    "device": "device_tree",
    "block": "program_blocks",
    "db": "interface_dbs",
    "udt": "interface_dbs",
    "tag_table": "tags",
    "tag": "tags",
    "watch": "tags",
    "force": "tags",
}


def normalize_skip_reason(raw: str) -> str:
    """Map Openness / parse error text onto the official skip-reason vocabulary."""
    t = (raw or "").strip()
    if t in SKIPPED_REASONS or t in FAILED_REASONS:
        return t
    low = t.lower()
    if "know" in low and "how" in low:
        return "know_how"
    if "inconsistent" in low or "isconsistent=false" in low.replace(" ", ""):
        return "inconsistent"
    if "license" in low:
        return "no_license"
    if "password" in low:
        return "password_protected"
    if "safety" in low and "login" in low:
        return "safety_login"
    if "unrecognized" in low:
        return "unrecognized"
    if "no_export" in low or ("export" in low and "not found" in low):
        return "no_export"
    if "no_import" in low or ("import" in low and "not found" in low):
        return "no_import"
    if t:
        return "openness_error"
    return ""


def status_from_reason(reason: str, *, exported: bool = False) -> str:
    """Classify a unit. Parsed structure wins over a body-only skip reason."""
    if exported:
        return "exported"
    if reason in FAILED_REASONS:
        return "failed"
    if reason in SKIPPED_REASONS:
        return "skipped"
    if reason:
        return "failed"
    return "pending"


def is_retryable(unit: dict[str, Any]) -> bool:
    status = str(unit.get("status") or "")
    reason = str(unit.get("reason") or "")
    if status == "pending":
        return True
    return status == "failed" and (reason in RETRYABLE_REASONS or not reason)


def _unit(
    *,
    name: str,
    kind: str,
    status: str,
    reason: str = "",
    detail: str = "",
    type_name: str = "",
    category: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "type": type_name or kind,
        "category": category or _category_for_kind(kind, type_name),
        "status": status if status in STRUCTURE_STATUSES else "pending",
        "reason": reason,
        "detail": detail,
        "retryable": False,
    }
    if extra:
        row.update(extra)
    row["retryable"] = is_retryable(row)
    return row


def _category_for_kind(kind: str, type_name: str = "") -> str:
    if kind in {"block", "db"} or type_name in {"OB", "FB", "FC", "DB"}:
        return "blocks"
    if kind == "udt" or type_name == "UDT":
        return "types"
    mapping = {
        "tag_table": "tags",
        "tag": "tags",
        "device": "hardware",
        "watch": "watch",
        "force": "force",
        "to": "to",
        "alarm": "alarms",
        "cfc": "cfc",
        "safety": "safety",
        "hmi": "hmi",
        "opcua": "opcua",
        "project": "project",
        "category": "",
    }
    return mapping.get(kind, "")


def _block_kind(block_type: str) -> str:
    upper = (block_type or "").upper()
    if upper == "UDT":
        return "udt"
    if upper == "DB":
        return "db"
    return "block"


def _key(kind: str, name: str) -> tuple[str, str]:
    return (kind.lower(), (name or "").strip().lower())


def _stem(rel: str) -> str:
    return Path(str(rel or "")).stem or str(rel or "")


def load_export_journal(export_path: str | Path) -> list[dict[str, Any]]:
    """Read ``_exported.jsonl`` if present. Incomplete last line is ignored."""
    path = Path(export_path) / "_exported.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            import json

            obj = json.loads(stripped)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("name"):
            events.append(obj)
    return events


def attach_export_journal(project: PlcProject, export_path: str | Path) -> None:
    """Fold journal events onto the project so ingest cannot drop failed exports."""
    events = load_export_journal(export_path)
    if not events:
        return
    seen = {
        (str(row.get("name") or ""), str(row.get("path") or ""))
        for row in project.export_journal
        if isinstance(row, dict)
    }
    for obj in events:
        marker = (str(obj.get("name") or ""), str(obj.get("path") or ""))
        if marker in seen:
            continue
        seen.add(marker)
        project.export_journal.append(obj)


def _upsert(
    by_key: dict[tuple[str, str], dict[str, Any]],
    unit: dict[str, Any],
) -> None:
    key = _key(str(unit.get("kind") or ""), str(unit.get("name") or ""))
    if not key[1]:
        return
    existing = by_key.get(key)
    if existing is None:
        by_key[key] = unit
        return
    rank = {s: i for i, s in enumerate(("exported", "failed", "skipped", "pending"))}
    # Prefer a more complete record. Exported wins (structure present, body may be empty).
    # Otherwise keep the more severe status (failed > skipped > pending).
    if existing.get("status") == "exported":
        if unit.get("detail") and not existing.get("detail"):
            existing["detail"] = unit["detail"]
        return
    if unit.get("status") == "exported":
        unit.setdefault("detail", existing.get("detail") or "")
        if existing.get("reason") and not unit.get("reason"):
            unit["reason"] = existing["reason"]
        by_key[key] = unit
        return
    if rank.get(str(unit.get("status")), 9) < rank.get(str(existing.get("status")), 9):
        by_key[key] = unit


def _units_from_parsed(project: PlcProject) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for name, block in (project.blocks or {}).items():
        btype = getattr(getattr(block, "block_type", None), "value", str(getattr(block, "block_type", "")))
        iface_only = bool(getattr(block, "is_interface_only", lambda: False)())
        protected = bool(getattr(block, "is_protected", lambda: False)())
        body_ok = bool(getattr(block, "has_program_body", lambda: True)())
        detail = ""
        if iface_only or (protected and not body_ok):
            detail = "interface exported; program body empty (Know-how / lock)"
        elif protected:
            detail = "Know-how marked; structure present"
        units.append(
            _unit(
                name=name,
                kind=_block_kind(str(btype)),
                status="exported",
                type_name=str(btype or ""),
                extra={
                    "language": getattr(block, "programming_language", None),
                    "number": getattr(block, "number", None),
                    "protected": protected,
                    "interface_only": iface_only,
                    "body_available": body_ok,
                    "is_safety": bool(getattr(block, "is_safety", False)),
                    "instance_of": (
                        str((getattr(block, "attributes", None) or {}).get("InstanceOfName") or "").strip()
                        or None
                    ),
                },
                detail=detail,
            )
        )
    for name, table in (project.tag_tables or {}).items():
        tags = getattr(table, "tags", None) or []
        units.append(
            _unit(
                name=name,
                kind="tag_table",
                status="exported",
                type_name="TagTable",
                extra={"tag_count": len(tags)},
            )
        )
    for device in getattr(project, "hardware", None) or []:
        units.append(
            _unit(
                name=getattr(device, "name", "") or "Device",
                kind="device",
                status="exported",
                type_name=getattr(device, "device_type", "") or "Device",
                extra={
                    "address": getattr(device, "address", "") or "",
                    "modules": list(getattr(device, "modules", None) or []),
                    "network_interfaces": list(getattr(device, "network_interfaces", None) or []),
                    "failsafe": bool(getattr(device, "failsafe", False)),
                },
            )
        )
    for name, table in (getattr(project, "watch_tables", None) or {}).items():
        units.append(_unit(name=name, kind="watch", status="exported", type_name="WatchTable"))
        _ = table
    for name in (getattr(project, "force_tables", None) or {}):
        units.append(_unit(name=name, kind="force", status="exported", type_name="ForceTable"))
    for obj in getattr(project, "technology_objects", None) or []:
        units.append(
            _unit(
                name=getattr(obj, "name", "") or "TO",
                kind="to",
                status="exported",
                type_name=getattr(obj, "to_type", "") or "TO",
            )
        )
    for obj in list(getattr(project, "alarms", None) or []) + list(getattr(project, "prodiag", None) or []):
        units.append(
            _unit(
                name=getattr(obj, "name", "") or "Alarm",
                kind="alarm",
                status="exported",
                type_name=getattr(obj, "kind", "") or "Alarm",
            )
        )
    for chart in getattr(project, "cfc_charts", None) or []:
        locked = bool(getattr(chart, "password_protected", False))
        units.append(
            _unit(
                name=getattr(chart, "name", "") or "Chart",
                kind="cfc",
                status="exported",
                type_name="CFC",
                detail="password protected; listed, not decrypted" if locked else "",
                extra={"password_protected": locked},
            )
        )
    for unit_info in getattr(project, "safety_units", None) or []:
        skip = str(getattr(unit_info, "skipped_reason", "") or "")
        units.append(
            _unit(
                name=getattr(unit_info, "name", "") or "Safety",
                kind="safety",
                status=status_from_reason(normalize_skip_reason(skip), exported=not skip),
                reason=normalize_skip_reason(skip),
                type_name="SafetyUnit",
            )
        )
    for device in getattr(project, "hmi_devices", None) or []:
        units.append(
            _unit(
                name=getattr(device, "name", "") or "HMI",
                kind="hmi",
                status="exported",
                type_name=getattr(device, "kind", "") or "hmi",
            )
        )
    if getattr(project, "opcua_nodes", None):
        units.append(
            _unit(
                name="OPC UA",
                kind="opcua",
                status="exported",
                type_name="OpcUa",
                extra={"node_count": len(project.opcua_nodes)},
            )
        )
    if getattr(project, "project_texts", None):
        units.append(_unit(name="ProjectTexts", kind="project", status="exported", type_name="ProjectTexts"))
    return units


def _units_from_manifest(project: PlcProject) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    manifest = getattr(project, "export_manifest", None) or {}
    skipped = manifest.get("skipped") if isinstance(manifest, dict) else None
    if isinstance(skipped, list):
        for item in skipped:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            category = str(item.get("category") or "").lower()
            reason = normalize_skip_reason(str(item.get("reason") or item.get("detail") or ""))
            kind = _kind_from_category(category, name)
            units.append(
                _unit(
                    name=name,
                    kind=kind,
                    status=status_from_reason(reason),
                    reason=reason,
                    detail=str(item.get("detail") or item.get("message") or ""),
                    category=category,
                    type_name=str(item.get("type") or category or kind),
                )
            )
    listed = manifest.get("listed") if isinstance(manifest, dict) else None
    if isinstance(listed, list):
        for item in listed:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            st = str(item.get("status") or "").strip().lower()
            reason = normalize_skip_reason(str(item.get("reason") or item.get("error") or ""))
            if st not in STRUCTURE_STATUSES:
                ok = item.get("ok")
                if ok is True:
                    st = "exported"
                elif ok is False:
                    st = status_from_reason(reason)
                else:
                    st = status_from_reason(reason)
            kind = _block_kind(str(item.get("type") or ""))
            units.append(
                _unit(
                    name=name,
                    kind=kind,
                    status=st,
                    reason=reason,
                    detail=str(item.get("detail") or item.get("error") or ""),
                    type_name=str(item.get("type") or ""),
                )
            )
    return units


def _kind_from_category(category: str, name: str) -> str:
    cat = (category or "").lower()
    mapping = {
        "blocks": "block",
        "types": "udt",
        "tags": "tag_table",
        "watch": "watch",
        "force": "force",
        "to": "to",
        "alarms": "alarm",
        "cfc": "cfc",
        "safety": "safety",
        "hardware": "device",
        "hmi": "hmi",
        "opcua": "opcua",
        "project": "project",
    }
    if cat in mapping:
        return mapping[cat]
    return "category" if not name else "block"


def _units_from_journal(project: PlcProject) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for obj in getattr(project, "export_journal", None) or []:
        if not isinstance(obj, dict) or obj.get("reset"):
            continue
        name = str(obj.get("name") or "").strip()
        if not name:
            continue
        ok = obj.get("ok")
        err = str(obj.get("error") or "")
        reason = normalize_skip_reason(err)
        if ok is True:
            status = "exported"
            reason = ""
        else:
            status = status_from_reason(reason)
        type_name = str(obj.get("type") or obj.get("category") or "")
        units.append(
            _unit(
                name=name,
                kind=_block_kind(type_name) if type_name in {"OB", "FB", "FC", "DB", "UDT"} else _kind_from_category(type_name, name),
                status=status,
                reason=reason,
                detail=err,
                type_name=type_name,
                extra={"know_how": bool(obj.get("knowHow") or obj.get("know_how"))},
            )
        )
    return units


def _units_from_parse_gaps(project: PlcProject) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for gap in getattr(project, "parse_gaps", None) or []:
        if not isinstance(gap, dict):
            continue
        name = str(gap.get("name") or _stem(str(gap.get("rel") or ""))).strip()
        if not name:
            continue
        reason = normalize_skip_reason(str(gap.get("reason") or gap.get("detail") or ""))
        status = str(gap.get("status") or status_from_reason(reason))
        units.append(
            _unit(
                name=name,
                kind=str(gap.get("kind") or "block"),
                status=status if status in STRUCTURE_STATUSES else status_from_reason(reason),
                reason=reason,
                detail=str(gap.get("detail") or gap.get("rel") or ""),
                type_name=str(gap.get("type") or ""),
            )
        )
    return units


def _parsed_category_counts(project: PlcProject) -> dict[str, int]:
    from agents.plc.tia.ir import BlockType

    udt = [b for b in project.blocks.values() if b.block_type == BlockType.UDT]
    prog = [b for b in project.blocks.values() if b.block_type != BlockType.UDT]
    return {
        "blocks": len(prog),
        "types": len(udt),
        "tags": len(project.tag_tables or {}),
        "watch": len(getattr(project, "watch_tables", {}) or {}),
        "force": len(getattr(project, "force_tables", {}) or {}),
        "to": len(getattr(project, "technology_objects", None) or []),
        "alarms": len(getattr(project, "alarms", None) or []) + len(getattr(project, "prodiag", None) or []),
        "cfc": len(getattr(project, "cfc_charts", None) or []),
        "safety": len(getattr(project, "safety_units", None) or []),
        "hardware": len(getattr(project, "hardware", None) or []),
        "hmi": len(getattr(project, "hmi_devices", None) or []),
        "opcua": len(getattr(project, "opcua_nodes", None) or []),
        "project": 1 if getattr(project, "project_texts", None) else 0,
    }


def _units_from_empty_categories(project: PlcProject, by_key: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    """Official chapter-6 categories with neither export nor parse still get a row."""
    parsed = _parsed_category_counts(project)
    manifest = getattr(project, "export_manifest", None) or {}
    counts = manifest.get("counts") if isinstance(manifest, dict) else None
    units: list[dict[str, Any]] = []
    present_cats: Counter[str] = Counter()
    for unit in by_key.values():
        cat = str(unit.get("category") or "")
        if cat:
            present_cats[cat] += 1
    for name in OFFICIAL_CATEGORIES:
        exported = 0
        if isinstance(counts, dict) and isinstance(counts.get(name), dict):
            exported = int(counts[name].get("exported") or 0)
        if exported or parsed.get(name) or present_cats.get(name):
            continue
        units.append(
            _unit(
                name=name,
                kind="category",
                status="skipped",
                reason="no_export",
                detail="no objects exported or parsed for this category",
                category=name,
                type_name=name,
            )
        )
    return units


def _call_graph_layer(kg: Any, by_key: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    edges_in: list[dict[str, Any]] = []
    if kg is None:
        return {"edges": [], "missing_callees": []}
    raw_edges = kg.get("edges") if isinstance(kg, dict) else getattr(kg, "edges", None)
    if raw_edges is None and hasattr(kg, "to_json"):
        raw_edges = (kg.to_json() or {}).get("edges")
    missing: list[dict[str, Any]] = []
    seen_missing: set[str] = set()
    for edge in raw_edges or []:
        if isinstance(edge, dict):
            et = str(edge.get("type") or "")
            src = str(edge.get("source") or "")
            tgt = str(edge.get("target") or "")
        else:
            et = str(getattr(edge, "type", "") or "")
            src = str(getattr(edge, "source", "") or "")
            tgt = str(getattr(edge, "target", "") or "")
        if et != "CALLS":
            continue
        src_name = src.split("::")[-1] if src else ""
        tgt_name = tgt.split("::")[-1] if tgt else ""
        if not src_name or not tgt_name:
            continue
        edges_in.append({"source": src_name, "target": tgt_name, "type": "CALLS"})
        found = None
        for kind in ("block", "db", "udt"):
            found = by_key.get(_key(kind, tgt_name))
            if found:
                break
        if found is None and tgt_name not in seen_missing:
            seen_missing.add(tgt_name)
            unit = _unit(
                name=tgt_name,
                kind="block",
                status="pending",
                reason="",
                detail=f"CALLS target listed in graph but not in export inventory (caller={src_name})",
                type_name="OTHER",
            )
            missing.append(unit)
            _upsert(by_key, unit)
        elif found is not None and found.get("status") != "exported":
            if tgt_name not in seen_missing:
                seen_missing.add(tgt_name)
                missing.append(found)
    return {"edges": edges_in, "missing_callees": missing}


def build_structure_inventory(
    project: PlcProject,
    *,
    knowledge_graph: Any = None,
) -> dict[str, Any]:
    """Reconcile parsed IR + Openness manifest/journal into a trusted map."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for unit in _units_from_parsed(project):
        _upsert(by_key, unit)
    for unit in _units_from_journal(project):
        _upsert(by_key, unit)
    for unit in _units_from_manifest(project):
        _upsert(by_key, unit)
    for unit in _units_from_parse_gaps(project):
        _upsert(by_key, unit)
    for unit in _units_from_empty_categories(project, by_key):
        _upsert(by_key, unit)

    call_graph = _call_graph_layer(knowledge_graph, by_key)
    units = sorted(
        by_key.values(),
        key=lambda u: (
            STRUCTURE_STATUSES.index(u["status"]) if u.get("status") in STRUCTURE_STATUSES else 9,
            str(u.get("kind") or ""),
            str(u.get("name") or ""),
        ),
    )
    counts = {status: 0 for status in STRUCTURE_STATUSES}
    for unit in units:
        counts[str(unit["status"])] = counts.get(str(unit["status"]), 0) + 1
    counts["total"] = len(units)
    incomplete = counts["failed"] + counts["skipped"] + counts["pending"]
    layers = {
        "device_tree": [u for u in units if u.get("kind") == "device"],
        "program_blocks": [
            u
            for u in units
            if u.get("kind") == "block" or str(u.get("type") or "").upper() in {"OB", "FB", "FC"}
        ],
        "interface_dbs": [u for u in units if u.get("kind") in {"db", "udt"}],
        "tags": [u for u in units if u.get("kind") in {"tag_table", "tag", "watch", "force"}],
        "call_graph": call_graph,
    }
    return {
        "units": units,
        "counts": counts,
        "layers": layers,
        "complete": incomplete == 0,
        "incomplete_count": incomplete,
    }


def structure_summary(inventory: dict[str, Any]) -> dict[str, Any]:
    """Compact counts for coverage.json / job summary."""
    counts = dict(inventory.get("counts") or {})
    return {
        "total": counts.get("total", 0),
        "exported": counts.get("exported", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "pending": counts.get("pending", 0),
        "complete": bool(inventory.get("complete")),
        "incomplete_count": inventory.get("incomplete_count", 0),
    }
