"""Parse official Openness chapter-6 export folders into PLC-IR (export/parse only).

Does not decrypt know-how or CFC passwords. Missing AML / SafetyUnit / OPC UA
must not fail block ingest.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.plc.tia.ir import (
    AlarmObject,
    CfcChart,
    HmiDevice,
    HmiScreen,
    SafetyUnitInfo,
    Tag,
    TagTable,
    TechnologyObject,
    WatchEntry,
    WatchTable,
)

OFFICIAL_CATEGORIES = (
    "blocks",
    "types",
    "tags",
    "watch",
    "force",
    "to",
    "alarms",
    "cfc",
    "safety",
    "hardware",
    "hmi",
    "opcua",
    "project",
)

_SURFACE_FOLDERS = {
    "watch": "watch",
    "force": "force",
    "to": "to",
    "alarms": "alarms",
    "cfc": "cfc",
    "safety": "safety",
    "hardware": "hardware",
    "hmi": "hmi",
    "opcua": "opcua",
    "project": "project",
}

_MARKER_KIND: tuple[tuple[str, str], ...] = (
    ("PlcWatchTable", "watch"),
    ("SW.WatchAndForceTables.PlcWatchTable", "watch"),
    ("PlcForceTable", "force"),
    ("SW.WatchAndForceTables.PlcForceTable", "force"),
    ("TechnologicalObject", "to"),
    ("SW.TechnologicalObjects", "to"),
    ("TO_PositioningAxis", "to"),
    ("TO_PID_Compact", "to"),
    ("ProDiag", "alarms"),
    ("SW.ProDiag", "alarms"),
    ("AlarmTextList", "alarms"),
    ("SW.Alarm", "alarms"),
    ("SW.Cfc", "cfc"),
    ("CfcChart", "cfc"),
    ("SafetyUnit", "safety"),
    ("SW.Safety", "safety"),
    ("OpcUa", "opcua"),
    ("Hmi.Screen", "hmi"),
    ("Hmi.Tag", "hmi"),
    ("Hmi.Cycle", "hmi"),
    ("HmiUnified", "hmi"),
    ("ProjectTexts", "project"),
    ("HardwareTree", "hardware"),
    ("CAEXFile", "hardware"),
)


@dataclass
class SurfaceHit:
    kind: str
    payload: Any = None
    hardware: list[Any] | None = None
    note: str = ""


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _attr(el: ET.Element, name: str) -> str:
    return el.get(name) or ""


def _child_text(el: ET.Element, *names: str) -> str:
    want = {n.lower() for n in names}
    for child in el:
        if _strip_ns(child.tag).lower() in want and (child.text or "").strip():
            return (child.text or "").strip()
    for node in el.iter():
        tag = _strip_ns(node.tag).lower()
        if tag in want and (node.text or "").strip():
            return (node.text or "").strip()
    return ""


def _folder_category(rel: str) -> str | None:
    parts = [p.lower() for p in Path(rel).parts]
    for part in parts:
        mapped = _SURFACE_FOLDERS.get(part)
        if mapped:
            return mapped
    return None


def classify_export_rel(rel: str, head: str = "") -> str | None:
    """Return a surface category from relative path and/or XML head, else None."""
    folder = _folder_category(rel)
    if folder:
        return folder
    blob = head or ""
    for marker, kind in _MARKER_KIND:
        if marker in blob:
            return kind
    return None


def classify_xml_kind(rel: str = "", head: str = "") -> str:
    """Classify SimaticML / AML / HMI XML for Openness Import routing."""
    blob = f"{rel} {head}"
    if "CAEXFile" in blob or "HardwareTree" in blob:
        return "hardware"
    if "PlcWatchTable" in blob or "SW.WatchAndForceTables.PlcWatchTable" in blob:
        return "watch"
    if "PlcForceTable" in blob or "SW.WatchAndForceTables.PlcForceTable" in blob:
        return "force"
    if "SW.Types.PlcStruct" in blob or "PlcStruct" in blob or "TypeTable" in blob:
        return "type"
    if "SW.Tags.PlcTagTable" in blob or "PlcTagTable" in blob:
        return "tag"
    if "Hmi." in blob or "HmiUnified" in blob:
        return "hmi"
    if "CfcChart" in blob or "SW.Cfc" in blob:
        return "cfc"
    if "TechnologicalObject" in blob or "TO_PositioningAxis" in blob:
        return "to"
    folder = _folder_category(rel)
    if folder in {"watch", "force", "to", "cfc", "hardware", "hmi"}:
        return folder
    if folder == "types":
        return "type"
    if folder == "tags":
        return "tag"
    return "block"


def xml_looks_like_safety(xml_path: Path | str) -> bool:
    """Mirror C# XmlLooksLikeSafety — refuse F-block write without decrypting."""
    import re

    from agents.plc.tia.safety import is_safety_name

    path = Path(xml_path)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if re.search(r"<(?:ProgrammingLanguage)>\s*F[-_]", text, re.I):
        return True
    for m in re.finditer(r"<Name>\s*([^<]+)\s*</Name>", text, re.I):
        if is_safety_name(m.group(1).strip()):
            return True
    return bool(
        re.search(
            r"<(?:ProgrammingLanguage)>\s*(?:F-LAD|F-FBD|F-SCL|F-STL|FSCL|FLAD)\s*</",
            text,
            re.I,
        )
    )


def try_parse_surface(xml_file: Path, export_path: Path, rel: str) -> SurfaceHit | None:
    """Parse watch/force/TO/alarms/CFC/safety/HMI/OPC UA/project texts. None = not surface."""
    try:
        head = xml_file.read_bytes()[:8192].decode("utf-8", errors="ignore")
    except OSError:
        head = ""
    kind = classify_export_rel(rel, head)
    if kind is None:
        return None
    if kind == "hardware":
        from agents.plc.tia.hardware import parse_hardware_xml

        devices = parse_hardware_xml(xml_file)
        return SurfaceHit(kind="hardware", hardware=devices)

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except ET.ParseError as exc:
        return SurfaceHit(kind="error", note=f"surface parse error in {rel}: {exc}")

    parsers = {
        "watch": lambda: _parse_watch(root, xml_file, kind="watch"),
        "force": lambda: _parse_watch(root, xml_file, kind="force"),
        "to": lambda: _parse_to(root, xml_file),
        "alarms": lambda: _parse_alarm(root, xml_file),
        "cfc": lambda: _parse_cfc(root, xml_file, rel),
        "safety": lambda: _parse_safety(root, xml_file),
        "hmi": lambda: _parse_hmi(root, xml_file, rel),
        "opcua": lambda: _parse_opcua(root),
        "project": lambda: _parse_project_texts(root),
    }
    parser = parsers.get(kind)
    if parser is None:
        return None
    payload = parser()
    if payload is None:
        return SurfaceHit(kind="skip", note=f"empty {kind} in {rel}")
    out_kind = kind
    if kind == "alarms" and isinstance(payload, AlarmObject) and payload.kind in {"prodiag", "supervision"}:
        out_kind = "prodiag"
    return SurfaceHit(kind=out_kind, payload=payload)


def _named(el: ET.Element) -> str:
    return (
        _attr(el, "Name")
        or _child_text(el, "Name")
        or ""
    )


def _parse_watch(root: ET.Element, path: Path, *, kind: str) -> WatchTable | None:
    table_el = None
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if "WatchTable" in tag or "ForceTable" in tag:
            table_el = node
            if "Force" in tag:
                kind = "force"
            break
    if table_el is None:
        table_el = root
    name = _named(table_el) or path.stem
    entries: list[WatchEntry] = []
    for node in (table_el.iter() if table_el is not None else []):
        tag = _strip_ns(node.tag)
        if "Entry" not in tag and "WatchTag" not in tag and tag not in {"Item", "Tag"}:
            continue
        if node is table_el:
            continue
        ename = _named(node) or _attr(node, "Tag")
        addr = _attr(node, "Address") or _child_text(node, "Address", "LogicalAddress")
        tag_name = _attr(node, "Tag") or _child_text(node, "Tag", "Name")
        if not ename and not addr and not tag_name:
            continue
        entries.append(
            WatchEntry(
                name=ename or tag_name or addr,
                address=addr,
                tag=tag_name or ename,
                comment=_child_text(node, "Comment", "Text"),
            )
        )
    if not name:
        return None
    return WatchTable(name=name, kind=kind, entries=entries, source_file=str(path))


def _parse_to(root: ET.Element, path: Path) -> TechnologyObject | None:
    obj = None
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if "Technological" in tag or tag.startswith("TO_") or "TechnologyObject" in tag:
            obj = node
            break
    if obj is None:
        obj = root
    name = _named(obj) or path.stem
    to_type = (
        _attr(obj, "Type")
        or _attr(obj, "TypeName")
        or _child_text(obj, "Type", "TypeName")
        or _strip_ns(obj.tag)
    )
    version = _attr(obj, "Version") or _child_text(obj, "Version")
    params: dict[str, str] = {}
    for node in obj.iter():
        tag = _strip_ns(node.tag)
        if tag not in {"Parameter", "Attribute"}:
            continue
        key = _attr(node, "Name") or _child_text(node, "Name")
        val = _attr(node, "Value") or (node.text or "").strip() or _child_text(node, "Value")
        if key:
            params[key] = val
    return TechnologyObject(
        name=name, to_type=to_type, version=version, parameters=params, source_file=str(path)
    )


def _parse_alarm(root: ET.Element, path: Path) -> AlarmObject | None:
    kind = "text_list"
    obj = root
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if "ProDiag" in tag:
            kind = "prodiag"
            obj = node
            break
        if "Supervision" in tag:
            kind = "supervision"
            obj = node
            break
        if "AlarmClass" in tag:
            kind = "class"
            obj = node
            break
        if "AlarmInstance" in tag:
            kind = "instance"
            obj = node
            break
        if "AlarmText" in tag or "Alarm" in tag:
            kind = "text_list"
            obj = node
            break
    name = _named(obj) or path.stem
    texts: list[str] = []
    for node in obj.iter():
        if _strip_ns(node.tag) in {"Text", "AlarmText", "Message"}:
            t = (node.text or "").strip() or _attr(node, "Name")
            if t:
                texts.append(t)
    return AlarmObject(name=name, kind=kind, texts=texts, source_file=str(path))


def _parse_cfc(root: ET.Element, path: Path, rel: str) -> CfcChart | None:
    chart = None
    for node in root.iter():
        if "Chart" in _strip_ns(node.tag):
            chart = node
            break
    if chart is None:
        chart = root
    name = _named(chart) or path.stem
    protected = False
    blob = ET.tostring(root, encoding="unicode").lower()
    if "password" in blob:
        protected = True
    blocks: list[str] = []
    wires: list[str] = []
    for node in chart.iter():
        tag = _strip_ns(node.tag)
        if tag in {"Block", "CfcBlock", "ChartBlock"}:
            bname = _named(node)
            if bname:
                blocks.append(bname)
        if tag in {"Wire", "CfcWire"}:
            frm = _attr(node, "From") or _attr(node, "Source")
            to = _attr(node, "To") or _attr(node, "Target")
            if frm or to:
                wires.append(f"{frm}->{to}")
    folder = str(Path(rel).parent).replace("\\", "/")
    return CfcChart(
        name=name,
        folder=folder,
        blocks=blocks,
        wires=wires,
        password_protected=protected,
        source_file=str(path),
    )


def _parse_safety(root: ET.Element, path: Path) -> SafetyUnitInfo | None:
    unit = None
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if "Safety" in tag or "Failsafe" in tag:
            unit = node
            break
    if unit is None:
        unit = root
    name = _named(unit) or path.stem
    supervisions: list[str] = []
    for node in unit.iter():
        if "Supervision" in _strip_ns(node.tag):
            sname = _named(node)
            if sname:
                supervisions.append(sname)
    return SafetyUnitInfo(name=name, failsafe=True, supervisions=supervisions, source_file=str(path))


def _hmi_device_name(rel: str, path: Path) -> str:
    parts = Path(rel).parts
    lower = [p.lower() for p in parts]
    if "hmi" in lower:
        idx = lower.index("hmi")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return path.parent.name or "HMI"


def _screen_kind(rel: str, tag: str) -> str:
    blob = f"{rel} {tag}".lower()
    if "template" in blob:
        return "template"
    if "popup" in blob:
        return "popup"
    if "slide" in blob:
        return "slidein"
    if "faceplate" in blob:
        return "faceplate"
    if "permanent" in blob:
        return "permanent"
    if "cycle" in blob:
        return "cycle"
    if "script" in blob or "vbscript" in blob:
        return "script"
    if "textlist" in blob:
        return "textlist"
    if "graphiclist" in blob:
        return "graphiclist"
    if "connection" in blob:
        return "connection"
    if "tag" in blob:
        return "tags"
    return "screen"


def _parse_hmi(root: ET.Element, path: Path, rel: str) -> HmiDevice:
    device = HmiDevice(name=_hmi_device_name(rel, path), source_file=str(path))
    kind = _screen_kind(rel, _strip_ns(root.tag))
    if kind == "tags":
        tags: list[Tag] = []
        table_name = path.stem
        for node in root.iter():
            tag = _strip_ns(node.tag)
            if tag in {"Hmi.Tag", "Tag", "HmiTag", "SW.Tags.PlcTag"}:
                tname = _named(node)
                if tname:
                    tags.append(
                        Tag(
                            name=tname,
                            data_type=_attr(node, "DataType") or _child_text(node, "DataType"),
                            logical_address=_attr(node, "Address") or _child_text(node, "Address"),
                        )
                    )
        if tags:
            device.tag_tables[table_name] = TagTable(name=table_name, tags=tags)
            return device
    primary = _named(root) or path.stem
    if kind == "script":
        device.scripts.append(primary)
        return device
    if kind == "textlist":
        device.text_lists.append(primary)
        return device
    if kind == "graphiclist":
        device.graphic_lists.append(primary)
        return device
    if kind == "connection":
        device.connections.append(primary)
        return device
    if kind == "cycle":
        device.cycles.append(primary)
        return device
    linked: list[str] = []
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag in {"Tag", "Hmi.Tag", "LinkedTag"}:
            tname = _named(node) or (node.text or "").strip()
            if tname:
                linked.append(tname)
    device.screens.append(
        HmiScreen(
            name=primary,
            folder=str(Path(rel).parent).replace("\\", "/"),
            kind=kind if kind != "tags" else "screen",
            linked_tags=linked,
            source_file=str(path),
        )
        )
    return device


def _parse_opcua(root: ET.Element) -> list[str]:
    nodes: list[str] = []
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if "Node" in tag or tag in {"BrowseName", "DisplayName"}:
            name = _named(node) or (node.text or "").strip()
            if name:
                nodes.append(name)
    return nodes


def _parse_project_texts(root: ET.Element) -> dict[str, str]:
    texts: dict[str, str] = {}
    for node in root.iter():
        if _strip_ns(node.tag) != "Text":
            continue
        culture = _attr(node, "Culture") or _child_text(node, "Culture") or "und"
        body = (node.text or "").strip()
        if body:
            texts[culture] = body if culture not in texts else texts[culture] + "\n" + body
    return texts
