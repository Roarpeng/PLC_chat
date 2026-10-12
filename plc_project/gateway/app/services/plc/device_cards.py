"""Q1 Device/Sensor cards — cited I/O meaning, never invented process text.

Built from Openness tag tables, hardware Device nodes, HMI links, and KG
READS/WRITES. Engineer annotations override cited comments. Missing comment
and HMI text → ``meaning_unconfirmed`` (empty meaning_text).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

CARD_SCHEMA = "researchos.device_sensor_card.v1"
BRIEF_SECTION_SCHEMA = "researchos.brief.device_sensor_summary.v1"
BRIEF_SCHEMA = "researchos.project_brief.v1"

MeaningStatus = Literal["cited", "annotated", "meaning_unconfirmed"]
CardKind = Literal["tag", "device"]
IoType = Literal["DI", "DO", "AI", "AO", "M", "DB", "CONSTANT", "UNKNOWN"]

_IO_RANK = {
    "DI": 0,
    "DO": 1,
    "AI": 2,
    "AO": 3,
    "M": 4,
    "DB": 5,
    "CONSTANT": 6,
    "UNKNOWN": 7,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(node: Any) -> dict[str, Any]:
    if isinstance(node, dict):
        return node
    props = getattr(node, "props", None)
    return {
        "id": getattr(node, "id", ""),
        "type": getattr(node, "type", ""),
        "props": props if isinstance(props, dict) else {},
    }


def _kg_payload(job: dict[str, Any]) -> dict[str, Any]:
    kg = job.get("knowledge_graph") or {}
    if hasattr(kg, "to_json") and callable(kg.to_json):
        kg = kg.to_json()
    if not isinstance(kg, dict):
        return {"nodes": [], "edges": []}
    return kg


def _nodes(kg: dict[str, Any]) -> list[dict[str, Any]]:
    return [_as_dict(n) for n in (kg.get("nodes") or [])]


def _edges(kg: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in kg.get("edges") or []:
        if isinstance(raw, dict):
            out.append(raw)
            continue
        out.append(
            {
                "source": getattr(raw, "source", ""),
                "target": getattr(raw, "target", ""),
                "type": getattr(raw, "type", ""),
                "props": getattr(raw, "props", {}) or {},
            }
        )
    return out


def classify_io_type(address: str, data_type: str = "", *, constant: bool = False) -> str:
    """Siemens address → DI/DO/AI/AO/M/DB. Does not guess process meaning."""
    if constant:
        return "CONSTANT"
    addr = (address or "").upper().replace(" ", "")
    dt = (data_type or "").lower()
    analog_dt = any(tok in dt for tok in ("int", "word", "real", "dint", "dword", "lreal"))
    if addr.startswith(("%IW", "%PIW", "%ID", "%PID")):
        return "AI"
    if addr.startswith(("%QW", "%PQW", "%QD", "%PQD")):
        return "AO"
    if addr.startswith(("%I", "%PI")):
        return "AI" if analog_dt else "DI"
    if addr.startswith(("%Q", "%PQ")):
        return "AO" if analog_dt else "DO"
    if addr.startswith("%M"):
        return "M"
    if addr.startswith(("%DB", "DB")):
        return "DB"
    return "UNKNOWN"


def card_id_for(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def parse_card_id(card_id: str) -> tuple[str, str]:
    raw = unquote((card_id or "").strip())
    if ":" not in raw:
        raise ValueError("card_id must be kind:name")
    kind, name = raw.split(":", 1)
    kind = kind.strip().lower()
    name = name.strip()
    if kind not in {"tag", "device"} or not name:
        raise ValueError("card_id must be tag:<symbol> or device:<name>")
    return kind, name


def _clean(text: Any) -> str:
    return str(text or "").strip()


# Parser sentinel on PlcConstant rows — classification, not process meaning.
_NON_MEANING_COMMENTS = frozenset({"constant", "const", "plcconstant"})


def _process_comment(comment: str) -> str:
    """Return comment only when it can stand as cited process meaning."""
    text = _clean(comment)
    if not text or text.lower() in _NON_MEANING_COMMENTS:
        return ""
    return text


def _looks_like_constant(props: dict[str, Any], _address: str, data_type: str, comment: str) -> bool:
    if str(props.get("scope") or "").lower() == "constant":
        return True
    if data_type.upper() == "CONSTANT":
        return True
    return comment.lower() in _NON_MEANING_COMMENTS


def _load_project_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """Optional IR snapshot from the export package — HMI / hardware comments."""
    cached = job.get("plc_ir_snapshot")
    if isinstance(cached, dict) and cached:
        return cached
    export_dir = job.get("export_dir")
    if not export_dir:
        return {}
    path = Path(str(export_dir)) / "plc_ir" / "project.json"
    if not path.is_file():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _hmi_index(job: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """symbol → [{device, screen, text}] from job.hmi_index or project.json."""
    ready = job.get("hmi_index")
    if isinstance(ready, dict):
        out: dict[str, list[dict[str, str]]] = {}
        for key, rows in ready.items():
            if not key:
                continue
            out[str(key)] = [r for r in (rows or []) if isinstance(r, dict)]
        return out

    project = _load_project_snapshot(job)
    index: dict[str, list[dict[str, str]]] = {}

    def add(symbol: str, row: dict[str, str]) -> None:
        name = _clean(symbol)
        if not name:
            return
        index.setdefault(name, []).append(row)

    for device in project.get("hmi_devices") or []:
        if not isinstance(device, dict):
            continue
        dname = _clean(device.get("name") or "HMI")
        tables = device.get("tag_tables") or {}
        if isinstance(tables, dict):
            for table in tables.values():
                if not isinstance(table, dict):
                    continue
                for tag in table.get("tags") or []:
                    if not isinstance(tag, dict):
                        continue
                    add(
                        str(tag.get("name") or ""),
                        {
                            "device": dname,
                            "screen": _clean(table.get("name") or "HmiTags"),
                            "text": _clean(tag.get("comment")),
                        },
                    )
        for screen in device.get("screens") or []:
            if not isinstance(screen, dict):
                continue
            sname = _clean(screen.get("name") or "screen")
            for linked in screen.get("linked_tags") or []:
                add(
                    str(linked),
                    {"device": dname, "screen": sname, "text": ""},
                )
    return index


def _hardware_extra(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    project = _load_project_snapshot(job)
    extra: dict[str, dict[str, Any]] = {}
    for hw in project.get("hardware") or []:
        if not isinstance(hw, dict):
            continue
        name = _clean(hw.get("name"))
        if not name:
            continue
        extra[name] = hw
    return extra


def _network_titles(kg: dict[str, Any]) -> dict[tuple[str, str], str]:
    titles: dict[tuple[str, str], str] = {}
    for node in _nodes(kg):
        if str(node.get("type") or "") != "Network":
            continue
        nid = str(node.get("id") or "")
        props = node.get("props") or {}
        title = _clean(props.get("title"))
        parts = nid.split("::")
        if len(parts) >= 3 and parts[0] == "Network":
            titles[(parts[1], "::".join(parts[2:]))] = title
            titles[(parts[1], parts[-1])] = title
    return titles


def _tag_aliases(name: str, table: str = "") -> list[str]:
    """Qualified Openness refs (HMI.StartCmd) alias the table symbol (StartCmd)."""
    aliases = [name]
    if table and not name.startswith(f"{table}."):
        aliases.append(f"{table}.{name}")
    if "." in name:
        aliases.append(name.split(".", 1)[-1])
    if name.startswith("#"):
        aliases.append(name[1:])
    return list(dict.fromkeys(a for a in aliases if a))


def _used_by(kg: dict[str, Any], tag_name: str, table: str = "") -> list[dict[str, Any]]:
    wanted = {f"Tag::{alias}" for alias in _tag_aliases(tag_name, table)}
    titles = _network_titles(kg)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in _edges(kg):
        et = str(edge.get("type") or "")
        if et not in {"READS", "WRITES"}:
            continue
        if str(edge.get("target") or "") not in wanted:
            continue
        src = str(edge.get("source") or "")
        if not src.startswith("Block::"):
            continue
        block = src.split("::", 1)[-1]
        props = edge.get("props") or {}
        net = _clean(props.get("network"))
        title = titles.get((block, net), "") if net else ""
        key = (block, et, net or title)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "block": block,
                "access": et,
                "network_id": net,
                "network_title": title,
                "part": _clean(props.get("part")),
            }
        )
    rows.sort(key=lambda r: (r["block"], r["access"], r["network_id"]))
    return rows


def _annotations(job: dict[str, Any]) -> dict[str, Any]:
    store = job.get("device_card_annotations")
    if not isinstance(store, dict):
        store = {}
        job["device_card_annotations"] = store
    return store


def _resolve_meaning(
    *,
    comment: str,
    hmi_texts: list[dict[str, str]],
    annotation: dict[str, Any] | None,
) -> tuple[str, str, str]:
    """Return (status, meaning_text, meaning_source). Never invents text."""
    if annotation and _clean(annotation.get("text")):
        return "annotated", _clean(annotation.get("text")), "engineer_annotation"
    if comment:
        return "cited", comment, "tag_comment"
    for row in hmi_texts:
        text = _clean(row.get("text"))
        if text:
            return "cited", text, "hmi_text"
    return "meaning_unconfirmed", "", "none"


def _tag_table_of(kg: dict[str, Any], tag_id: str) -> str:
    for edge in _edges(kg):
        if str(edge.get("type") or "") != "CONTAINS":
            continue
        if str(edge.get("target") or "") != tag_id:
            continue
        src = str(edge.get("source") or "")
        if src.startswith("TagTable::"):
            return src.split("::", 1)[-1]
    return ""


def _skip_local_pin(name: str, address: str, in_table: bool) -> bool:
    """Interface locals (#Var) are not sensors unless they have an address or table row."""
    if not name.startswith("#"):
        return False
    return not address and not in_table


def _build_tag_card(
    job: dict[str, Any],
    *,
    name: str,
    props: dict[str, Any],
    kg: dict[str, Any],
    hmi: dict[str, list[dict[str, str]]],
) -> dict[str, Any] | None:
    address = _clean(props.get("address") or props.get("logical_address"))
    raw_comment = _clean(props.get("comment"))
    comment = _process_comment(raw_comment)
    data_type = _clean(props.get("data_type"))
    tag_id = f"Tag::{name}"
    table = _tag_table_of(kg, tag_id)
    if _skip_local_pin(name, address, bool(table)):
        return None
    constant = _looks_like_constant(props, address, data_type, raw_comment)
    # PlcConstant parser stores the numeric value in logical_address — not an I/O addr.
    if constant and address and not address.upper().startswith(("%", "DB")):
        address = ""
    cid = card_id_for("tag", name)
    annotation = _annotations(job).get(cid)
    if annotation is not None and not isinstance(annotation, dict):
        annotation = None
    hmi_texts = list(hmi.get(name) or [])
    if name.startswith("#") and not hmi_texts:
        hmi_texts = list(hmi.get(name[1:]) or [])
    status, meaning, source = _resolve_meaning(
        comment=comment, hmi_texts=hmi_texts, annotation=annotation
    )
    used = _used_by(kg, name, table)
    citations: list[dict[str, str]] = []
    if comment:
        citations.append(
            {
                "kind": "tag_comment",
                "locator": f"TagTable::{table}/{name}" if table else f"Tag::{name}",
                "quote": comment,
            }
        )
    for row in hmi_texts:
        text = _clean(row.get("text"))
        if text:
            citations.append(
                {
                    "kind": "hmi_text",
                    "locator": f"HMI::{row.get('device')}/{row.get('screen')}",
                    "quote": text,
                }
            )
    if annotation and _clean(annotation.get("text")):
        citations.append(
            {
                "kind": "engineer_annotation",
                "locator": cid,
                "quote": _clean(annotation.get("text")),
            }
        )
    for use in used[:8]:
        citations.append(
            {
                "kind": "kg_edge",
                "locator": f"{use['block']}:{use['access']}:{name}",
                "quote": f"{use['access']} by {use['block']}"
                + (f" ({use['network_title']})" if use.get("network_title") else ""),
            }
        )
    io_type = classify_io_type(address, data_type, constant=constant)
    return {
        "schema": CARD_SCHEMA,
        "id": cid,
        "kind": "tag",
        "symbol_name": name,
        "address": address,
        "comment": raw_comment,
        "io_type": io_type,
        "data_type": data_type,
        "tag_table": table,
        "meaning_status": status,
        "meaning_text": meaning,
        "meaning_source": source,
        "hmi_texts": hmi_texts,
        "used_by": used,
        "hardware": None,
        "annotation": annotation,
        "citations": citations,
    }


def _build_device_card(
    job: dict[str, Any],
    *,
    name: str,
    props: dict[str, Any],
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    hw = extra or {}
    address = _clean(props.get("address") or hw.get("address"))
    comment = _clean(hw.get("comment") or props.get("comment"))
    device_type = _clean(props.get("type") or hw.get("device_type"))
    cid = card_id_for("device", name)
    annotation = _annotations(job).get(cid)
    if annotation is not None and not isinstance(annotation, dict):
        annotation = None
    status, meaning, source = _resolve_meaning(
        comment=comment, hmi_texts=[], annotation=annotation
    )
    citations: list[dict[str, str]] = []
    if device_type or address:
        citations.append(
            {
                "kind": "hardware",
                "locator": f"Device::{name}",
                "quote": " · ".join(p for p in (device_type, address) if p),
            }
        )
    if comment:
        citations.append({"kind": "tag_comment", "locator": f"Device::{name}", "quote": comment})
    if annotation and _clean(annotation.get("text")):
        citations.append(
            {
                "kind": "engineer_annotation",
                "locator": cid,
                "quote": _clean(annotation.get("text")),
            }
        )
    return {
        "schema": CARD_SCHEMA,
        "id": cid,
        "kind": "device",
        "symbol_name": name,
        "address": address,
        "comment": comment,
        "io_type": "UNKNOWN",
        "data_type": device_type,
        "tag_table": "",
        "meaning_status": status,
        "meaning_text": meaning,
        "meaning_source": source,
        "hmi_texts": [],
        "used_by": [],
        "hardware": {
            "name": name,
            "type": device_type,
            "address": address,
            "rack": _clean(props.get("rack") or hw.get("rack")),
            "slot": _clean(hw.get("slot")),
            "failsafe": bool(props.get("failsafe") if "failsafe" in props else hw.get("failsafe")),
        },
        "annotation": annotation,
        "citations": citations,
    }


def build_device_cards(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize Q1 cards from the job KG (+ optional HMI snapshot)."""
    kg = _kg_payload(job)
    hmi = _hmi_index(job)
    extra = _hardware_extra(job)
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    table_symbols: set[str] = set()
    for node in _nodes(kg):
        if str(node.get("type") or "") != "Tag":
            continue
        nid = str(node.get("id") or "")
        props = node.get("props") or {}
        name = _clean(props.get("name") or (nid.split("::", 1)[-1] if "::" in nid else nid))
        if name and _tag_table_of(kg, nid or f"Tag::{name}"):
            table_symbols.add(name)

    for node in _nodes(kg):
        ntype = str(node.get("type") or "")
        props = node.get("props") or {}
        nid = str(node.get("id") or "")
        if ntype == "Tag":
            name = _clean(props.get("name") or (nid.split("::", 1)[-1] if "::" in nid else nid))
            if not name or name in seen:
                continue
            if "." in name and name.split(".", 1)[-1] in table_symbols:
                continue
            card = _build_tag_card(job, name=name, props=props, kg=kg, hmi=hmi)
            if card is None:
                continue
            seen.add(name)
            cards.append(card)
        elif ntype == "Device":
            name = _clean(props.get("name") or (nid.split("::", 1)[-1] if "::" in nid else nid))
            if not name:
                continue
            cid = card_id_for("device", name)
            if cid in seen:
                continue
            seen.add(cid)
            cards.append(_build_device_card(job, name=name, props=props, extra=extra.get(name)))

    cards.sort(
        key=lambda c: (
            0 if c["kind"] == "tag" else 1,
            _IO_RANK.get(str(c.get("io_type")), 9),
            str(c.get("symbol_name") or ""),
        )
    )
    return cards


def get_device_card(job: dict[str, Any], card_id: str) -> dict[str, Any] | None:
    kind, name = parse_card_id(card_id)
    wanted = card_id_for(kind, name)
    for card in build_device_cards(job):
        if card["id"] == wanted or (
            card["kind"] == kind and card["symbol_name"] == name
        ):
            return card
    return None


def find_card_by_symbol(job: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    token = _clean(symbol).lstrip("@")
    if not token:
        return None
    for card in build_device_cards(job):
        if card["symbol_name"] == token or card["symbol_name"] == f"#{token}":
            return card
        if card["id"] == token or card["id"] == card_id_for("tag", token):
            return card
    return None


def list_device_cards(
    job: dict[str, Any],
    *,
    q: str = "",
    io_type: str = "",
    meaning_status: str = "",
    kind: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    cards = build_device_cards(job)
    query = q.strip().lower()
    io_f = io_type.strip().upper()
    st_f = meaning_status.strip().lower()
    kind_f = kind.strip().lower()
    filtered: list[dict[str, Any]] = []
    for card in cards:
        if kind_f and card["kind"] != kind_f:
            continue
        if io_f and str(card.get("io_type") or "").upper() != io_f:
            continue
        if st_f and str(card.get("meaning_status") or "") != st_f:
            continue
        if query:
            blob = " ".join(
                [
                    str(card.get("symbol_name") or ""),
                    str(card.get("address") or ""),
                    str(card.get("comment") or ""),
                    str(card.get("meaning_text") or ""),
                    str(card.get("tag_table") or ""),
                ]
            ).lower()
            if query not in blob:
                continue
        filtered.append(card)
    cap = max(1, min(int(limit or 200), 500))
    counts = {
        "total": len(cards),
        "returned": min(len(filtered), cap),
        "cited": sum(1 for c in cards if c["meaning_status"] == "cited"),
        "annotated": sum(1 for c in cards if c["meaning_status"] == "annotated"),
        "meaning_unconfirmed": sum(
            1 for c in cards if c["meaning_status"] == "meaning_unconfirmed"
        ),
    }
    return {
        "schema": CARD_SCHEMA,
        "job_id": job.get("id"),
        "project_name": job.get("project_name") or "",
        "counts": counts,
        "cards": filtered[:cap],
    }


def set_device_card_annotation(
    job: dict[str, Any],
    card_id: str,
    *,
    text: str,
    author: str = "",
) -> dict[str, Any]:
    card = get_device_card(job, card_id)
    if card is None:
        raise KeyError(card_id)
    note = {
        "text": _clean(text),
        "author": _clean(author) or "engineer",
        "updated_at": _now_iso(),
    }
    if not note["text"]:
        raise ValueError("annotation text must not be empty")
    _annotations(job)[card["id"]] = note
    job["updated_at"] = datetime.now(UTC)
    refreshed = get_device_card(job, card["id"])
    assert refreshed is not None
    return refreshed


def clear_device_card_annotation(job: dict[str, Any], card_id: str) -> dict[str, Any]:
    card = get_device_card(job, card_id)
    if card is None:
        raise KeyError(card_id)
    _annotations(job).pop(card["id"], None)
    job["updated_at"] = datetime.now(UTC)
    refreshed = get_device_card(job, card["id"])
    assert refreshed is not None
    return refreshed
