"""Parse classic HMI Screen XML and Unified screen JSON into canvas widgets."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import (
    CanvasHmiDevice,
    CanvasHmiScreen,
    CanvasHmiWidget,
)

# Classic SimaticML / Openness type → canvas widget_type
_CLASSIC_TYPE_MAP = {
    "button": "button",
    "symbolicbutton": "button",
    "iofield": "io_field",
    "textfield": "text",
    "text": "text",
    "bar": "bar",
    "gauge": "gauge",
    "slider": "slider",
    "circle": "indicator",
    "rectangle": "rect",
    "alarmview": "alarm_banner",
    "alarmviewsimple": "alarm_banner",
}

_UNIFIED_TYPE_MAP = {
    "hmibutton": "button",
    "hmiiofield": "io_field",
    "hmitext": "text",
    "hmibar": "bar",
    "hmigauge": "gauge",
    "hmislider": "slider",
    "hmicircle": "indicator",
    "hmirectangle": "rect",
    "hmialarmcontrol": "alarm_banner",
}


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _attr(el: ET.Element, *names: str) -> str:
    for n in names:
        for k, v in el.attrib.items():
            if _local(k).lower() == n.lower():
                return str(v)
        # child AttributeList/Name style
        for child in el:
            if _local(child.tag).lower() == n.lower() and (child.text or "").strip():
                return (child.text or "").strip()
    return ""


def _find_attr_list_value(el: ET.Element, name: str) -> str:
    for child in el.iter():
        if _local(child.tag) == name and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def _int(val: str, default: int = 0) -> int:
    try:
        return int(float(str(val).strip() or default))
    except (TypeError, ValueError):
        return default


def map_classic_type(type_name: str) -> tuple[str, bool]:
    key = re.sub(r"[^a-z0-9]", "", (type_name or "").lower())
    for k, v in _CLASSIC_TYPE_MAP.items():
        if k in key:
            return v, True
    return "placeholder", False


def map_unified_type(type_name: str) -> tuple[str, bool]:
    key = re.sub(r"[^a-z0-9]", "", (type_name or "").lower())
    for k, v in _UNIFIED_TYPE_MAP.items():
        if k in key:
            return v, True
    return "placeholder", False


def parse_classic_screen_xml(
    path: Path,
    *,
    device: str,
    screen: str,
) -> list[CanvasHmiWidget]:
    """Best-effort parse of Hmi.Screen Openness XML into widgets."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []

    widgets: list[CanvasHmiWidget] = []
    idx = 0
    # Walk elements that look like screen items
    for el in root.iter():
        tag = _local(el.tag)
        if not tag:
            continue
        lower = tag.lower()
        if "screenitem" not in lower and lower not in {
            "button",
            "iofield",
            "textfield",
            "bar",
            "gauge",
            "slider",
            "circle",
            "rectangle",
            "alarmview",
        }:
            # Also accept elements with CompositionName=ScreenItems
            if el.attrib.get("CompositionName") != "ScreenItems" and "Hmi.ScreenItem" not in tag:
                continue
        idx += 1
        type_name = tag
        wtype, supported = map_classic_type(type_name)
        name = (
            _find_attr_list_value(el, "Name")
            or _attr(el, "Name")
            or f"Item{idx}"
        )
        x = _int(_find_attr_list_value(el, "Left") or _find_attr_list_value(el, "X") or "0")
        y = _int(_find_attr_list_value(el, "Top") or _find_attr_list_value(el, "Y") or "0")
        w = _int(_find_attr_list_value(el, "Width") or "80", 80)
        h = _int(_find_attr_list_value(el, "Height") or "40", 40)
        text = _find_attr_list_value(el, "Text") or _find_attr_list_value(el, "Caption") or name
        # Linked tag heuristics
        hmi_tag = (
            _find_attr_list_value(el, "ProcessTag")
            or _find_attr_list_value(el, "Tag")
            or _find_attr_list_value(el, "LinkedTag")
            or ""
        )
        wid = f"{device}/{screen}/{name}".replace(" ", "_")
        widgets.append(
            CanvasHmiWidget(
                id=wid,
                widget_type=wtype,
                title=text or name,
                x=x,
                y=y,
                width=max(w, 20),
                height=max(h, 20),
                hmi_tag=hmi_tag,
                plc_tag="",  # filled later via tag resolve
                text=text,
                device=device,
                screen=screen,
                source_name=name,
                source_type=type_name,
                supported=supported,
                status="synced",
                properties={"source_file": str(path)},
            )
        )
    return widgets


def parse_unified_screens_json(
    path: Path,
    *,
    device: str,
) -> tuple[CanvasHmiDevice, list[CanvasHmiWidget]]:
    """Parse HmiUnifiedDump JSON into device + widgets."""
    data = json.loads(path.read_text(encoding="utf-8"))
    width = int(data.get("width") or data.get("screenWidth") or 800)
    height = int(data.get("height") or data.get("screenHeight") or 480)
    screens_raw = data.get("screens") or []
    screens: list[CanvasHmiScreen] = []
    widgets: list[CanvasHmiWidget] = []
    for s in screens_raw:
        if not isinstance(s, dict):
            continue
        sname = str(s.get("name") or "Screen")
        screens.append(
            CanvasHmiScreen(
                name=sname,
                start_screen=bool(s.get("startScreen") or s.get("isStart")),
                width=int(s.get("width") or width),
                height=int(s.get("height") or height),
            )
        )
        for item in s.get("items") or s.get("screenItems") or []:
            if not isinstance(item, dict):
                continue
            type_name = str(item.get("type") or item.get("typeName") or "Unknown")
            wtype, supported = map_unified_type(type_name)
            name = str(item.get("name") or "Item")
            wid = f"{device}/{sname}/{name}".replace(" ", "_")
            widgets.append(
                CanvasHmiWidget(
                    id=wid,
                    widget_type=wtype,
                    title=str(item.get("text") or name),
                    x=int(item.get("left") or item.get("x") or 0),
                    y=int(item.get("top") or item.get("y") or 0),
                    width=max(int(item.get("width") or 80), 20),
                    height=max(int(item.get("height") or 40), 20),
                    hmi_tag=str(item.get("tag") or item.get("processTag") or ""),
                    plc_tag="",
                    text=str(item.get("text") or ""),
                    device=device,
                    screen=sname,
                    source_name=name,
                    source_type=type_name,
                    supported=supported,
                    status="synced",
                    properties={"events": item.get("events") or []},
                )
            )
    device_obj = CanvasHmiDevice(
        name=device,
        kind="unified",
        width=width,
        height=height,
        screens=screens or [CanvasHmiScreen(name="Screen_1", start_screen=True)],
    )
    return device_obj, widgets


def resolve_hmi_to_plc_tags(
    widgets: list[CanvasHmiWidget],
    tag_map: dict[str, str],
) -> None:
    """Mutate widgets: set plc_tag from HMI tag → PLC tag mapping."""
    for w in widgets:
        if w.plc_tag:
            continue
        key = w.hmi_tag
        if key and key in tag_map:
            w.plc_tag = tag_map[key]
        elif key:
            # Already looks like PLC path
            w.plc_tag = key


def parse_hmi_export_tree(export_root: Path) -> tuple[list[CanvasHmiDevice], dict[str, CanvasHmiWidget]]:
    """Scan ``hmi/<device>/…`` under an Openness export root."""
    devices: list[CanvasHmiDevice] = []
    widgets: dict[str, CanvasHmiWidget] = {}
    hmi_root = export_root / "hmi"
    if not hmi_root.is_dir():
        # flat layout fallback
        hmi_root = export_root
    for device_dir in sorted(p for p in hmi_root.iterdir() if p.is_dir()) if hmi_root.is_dir() else []:
        device_name = device_dir.name
        unified_json = device_dir / "unified_screens.json"
        screens_dir = device_dir / "screens"
        device: CanvasHmiDevice | None = None
        collected: list[CanvasHmiWidget] = []

        if unified_json.is_file():
            device, collected = parse_unified_screens_json(unified_json, device=device_name)
        elif screens_dir.is_dir():
            screen_names: list[CanvasHmiScreen] = []
            for xml in sorted(screens_dir.rglob("*.xml")):
                sname = xml.stem
                screen_names.append(CanvasHmiScreen(name=sname, start_screen=len(screen_names) == 0))
                collected.extend(parse_classic_screen_xml(xml, device=device_name, screen=sname))
            device = CanvasHmiDevice(
                name=device_name,
                kind="classic",
                width=800,
                height=480,
                screens=screen_names,
            )
        if device is not None:
            # Build simple HMI→PLC map from tags xml if present
            tag_map: dict[str, str] = {}
            tags_dir = device_dir / "tags"
            if tags_dir.is_dir():
                for xml in tags_dir.rglob("*.xml"):
                    try:
                        root = ET.parse(xml).getroot()
                    except ET.ParseError:
                        continue
                    for el in root.iter():
                        if "tag" not in _local(el.tag).lower():
                            continue
                        n = _find_attr_list_value(el, "Name")
                        plc = _find_attr_list_value(el, "PlcTag") or _find_attr_list_value(el, "ControllerTag")
                        if n and plc:
                            tag_map[n] = plc
            resolve_hmi_to_plc_tags(collected, tag_map)
            devices.append(device)
            for w in collected:
                widgets[w.id] = w
    return devices, widgets
