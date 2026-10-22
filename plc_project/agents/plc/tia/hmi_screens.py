"""Parse classic HMI Screen XML and Unified screen JSON into canvas widgets.

Two independent pieces of TIA data are joined here:

* screen XML/JSON → widget geometry, text and colour attributes;
* ``tags/`` + ``connections/`` → HMI tag → PLC tag resolution.

Colour values in real exports are inconsistent (``#RRGGBB``, decimal
``0xRRGGBB`` as integer, ``"255, 0, 0"`` tuples, occasionally nested
``<BackColor><Value>…</Value></BackColor>``).  Every extracted colour keeps
the originating attribute name under ``properties.color_source`` and the raw
text under ``properties.color_raw`` so an unrecognised shape is never silently
reinterpreted.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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
    "checkbox": "button",
    "iofield": "io_field",
    "symboliciofield": "io_field",
    "textfield": "text",
    "statictext": "text",
    "text": "text",
    "datefield": "text",
    "timefield": "text",
    "bar": "bar",
    "gauge": "gauge",
    "slider": "slider",
    "circle": "indicator",
    "ellipse": "indicator",
    "rectangle": "rect",
    "line": "rect",
    "polygon": "rect",
    "graphicview": "rect",
    "trendview": "bar",
    "alarmview": "alarm_banner",
    "alarmviewsimple": "alarm_banner",
}

_UNIFIED_TYPE_MAP = {
    "hmibutton": "button",
    "hmiiobutton": "button",
    "hmiiofield": "io_field",
    "hmitext": "text",
    "hmibar": "bar",
    "hmigauge": "gauge",
    "hmislider": "slider",
    "hmicircle": "indicator",
    "hmirectangle": "rect",
    "hmiline": "rect",
    "hmigraphic": "rect",
    "hmitrend": "bar",
    "hmialarmcontrol": "alarm_banner",
}

# canvas property → accepted source attribute names (order = priority)
_COLOR_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "bg_color": ("BackColor", "BgColor", "BackgroundColor", "Background", "FillColor"),
    "fg_color": ("ForeColor", "FgColor", "ForegroundColor", "FontColor", "TextColor", "Foreground"),
    "border_color": ("BorderColor", "FrameColor", "LineColor"),
}

_HEX_RE = re.compile(r"^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$|^[0-9a-fA-F]{8}$")
_SKIP_ITEM_TAGS = {"screenitems", "objectlist", "attributelist", "items", "documents"}


# ---------------------------------------------------------------------------
# colour normalisation
# ---------------------------------------------------------------------------


def _color_from_int(value: int) -> str | None:
    """Decimal TIA colour (0xRRGGBB; negative/ARGB tolerated) → ``#RRGGBB``."""
    if value < 0:
        value &= 0xFFFFFF
    elif value > 0xFFFFFF:
        if value > 0xFFFFFFFF:
            return None
        value &= 0xFFFFFF  # ARGB
    return f"#{value:06X}"


def normalize_color(value: Any) -> str | None:
    """Normalise the common TIA colour shapes to ``#RRGGBB``.

    Returns ``None`` when the shape is not understood; callers keep the raw
    value so nothing is lost.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _color_from_int(value)
    if isinstance(value, float):
        return _color_from_int(int(value)) if value.is_integer() else None
    if isinstance(value, (tuple, list)):
        nums: list[int] = []
        for part in value:
            try:
                nums.append(int(float(str(part).strip())))
            except (TypeError, ValueError):
                return None
        if len(nums) in {3, 4} and all(0 <= n <= 255 for n in nums[:3]):
            return "#{:02X}{:02X}{:02X}".format(*nums[:3])
        return None

    text = str(value).strip()
    if not text:
        return None

    rgba = re.search(r"rgba?\(([^)]*)\)", text, re.IGNORECASE)
    if rgba:
        try:
            parts = [int(float(p.strip())) for p in re.split(r"[,/\s]+", rgba.group(1)) if p.strip()]
        except ValueError:
            return None
        if len(parts) >= 3 and all(0 <= n <= 255 for n in parts[:3]):
            return "#{:02X}{:02X}{:02X}".format(*parts[:3])
        return None

    if text.startswith("#"):
        body = text[1:].strip()
        if _HEX_RE.match(body):
            return _color_from_hex(body)
        return None
    if text.lower().startswith("0x"):
        try:
            return _color_from_int(int(text, 16))
        except ValueError:
            return None
    # pure decimal must be checked before hex: "16777215" is a number, not hex
    if re.fullmatch(r"[+-]?\d+", text):
        try:
            return _color_from_int(int(text))
        except ValueError:
            return None
    if _HEX_RE.match(text):
        return _color_from_hex(text)

    parts = [p for p in re.split(r"[,;\s]+", text) if p]
    if len(parts) in {3, 4} and all(re.fullmatch(r"[+-]?\d+", p) for p in parts):
        nums = [int(p) for p in parts]
        if all(0 <= n <= 255 for n in nums[:3]):
            return "#{:02X}{:02X}{:02X}".format(*nums[:3])
    return None


def _color_from_hex(body: str) -> str | None:
    body = body.strip()
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    elif len(body) == 8:
        body = body[-6:]  # ARGB
    if len(body) != 6:
        return None
    return f"#{body.upper()}"


# ---------------------------------------------------------------------------
# generic XML helpers
# ---------------------------------------------------------------------------


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


def _scalar_text(el: ET.Element) -> str:
    """Leaf-ish text of a colour/attribute node, tolerating nested ``<Value>``."""
    text = (el.text or "").strip()
    if text:
        return text
    for key in ("Value", "value", "Color", "color"):
        val = el.attrib.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    for child in el:
        got = _scalar_text(child)
        if got:
            return got
    return ""


def _find_scalar_value(el: ET.Element, names: tuple[str, ...] | list[str]) -> str:
    """Find the first descendant whose local tag matches ``names``.

    Direct children and ``AttributeList`` children win over deep descendants to
    avoid borrowing a nested template's value.
    """
    lowered = {n.lower() for n in names}

    def scan(node: ET.Element) -> str:
        for child in list(node):
            if _local(child.tag).lower() in lowered:
                got = _scalar_text(child)
                if got:
                    return got
        return ""

    for child in list(el):
        if _local(child.tag).lower() == "attributelist":
            got = scan(child)
            if got:
                return got
    got = scan(el)
    if got:
        return got
    for child in el.iter():
        if _local(child.tag).lower() in lowered:
            got = _scalar_text(child)
            if got:
                return got
    return ""


def _int(val: str, default: int = 0) -> int:
    try:
        return int(float(str(val).strip() or default))
    except (TypeError, ValueError):
        return default


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _inside_attribute_list(el: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    node = parents.get(el)
    while node is not None:
        if _local(node.tag).lower() == "attributelist":
            return True
        node = parents.get(node)
    return False


def _is_screen_item(el: ET.Element, lower: str, parents: dict[ET.Element, ET.Element]) -> bool:
    if _inside_attribute_list(el, parents):
        return False
    if lower.endswith(tuple(_SKIP_ITEM_TAGS)) or lower in _SKIP_ITEM_TAGS:
        return False
    if "screenitem" in lower:
        return True
    if lower.startswith("hmi.screen."):
        return True
    if el.attrib.get("CompositionName") == "ScreenItems":
        return True
    key = re.sub(r"[^a-z0-9]", "", lower)
    return any(k in key for k in _CLASSIC_TYPE_MAP)


# ---------------------------------------------------------------------------
# type mapping
# ---------------------------------------------------------------------------


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


def _extract_colors_xml(el: ET.Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    raw: dict[str, str] = {}
    sources: dict[str, str] = {}
    for key, names in _COLOR_ATTRIBUTES.items():
        for name in names:
            value = _find_scalar_value(el, (name,))
            if not value:
                continue
            normalized = normalize_color(value)
            raw[name] = value
            sources[key] = name
            if normalized:
                props[key] = normalized
            else:
                props[key] = value  # keep original; flagged via color_raw
                sources[key] = f"{name} (raw)"
            break
    if raw:
        props["color_raw"] = raw
    if sources:
        props["color_source"] = sources
    return props


def _extract_colors_json(item: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    raw: dict[str, str] = {}
    sources: dict[str, str] = {}
    pools: list[dict[str, Any]] = [item]
    for nest in ("colors", "Colors", "appearance", "style", "styles"):
        nested = item.get(nest)
        if isinstance(nested, dict):
            pools.append(nested)
    for key, names in _COLOR_ATTRIBUTES.items():
        for name in names:
            for pool in pools:
                match_key = next((k for k in pool if str(k).lower() == name.lower()), None)
                if match_key is None:
                    continue
                value = pool[match_key]
                if isinstance(value, dict):
                    value = value.get("value") or value.get("Value") or value.get("color")
                if value is None or str(value).strip() == "":
                    continue
                raw[name] = str(value)
                sources[key] = name
                normalized = normalize_color(value)
                props[key] = normalized if normalized else str(value)
                if not normalized:
                    sources[key] = f"{name} (raw)"
                break
            if key in props:
                break
    if raw:
        props["color_raw"] = raw
    if sources:
        props["color_source"] = sources
    return props


# ---------------------------------------------------------------------------
# screen parsers
# ---------------------------------------------------------------------------


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

    parents = _parent_map(root)
    widgets: list[CanvasHmiWidget] = []
    seen: set[str] = set()
    idx = 0
    for el in root.iter():
        tag = _local(el.tag)
        if not tag:
            continue
        lower = tag.lower()
        if not _is_screen_item(el, lower, parents):
            continue
        idx += 1
        type_name = tag
        wtype, supported = map_classic_type(type_name)
        name = _find_attr_list_value(el, "Name") or _attr(el, "Name") or f"Item{idx}"
        x = _int(_find_attr_list_value(el, "Left") or _find_attr_list_value(el, "X") or "0")
        y = _int(_find_attr_list_value(el, "Top") or _find_attr_list_value(el, "Y") or "0")
        w = _int(_find_attr_list_value(el, "Width") or "80", 80)
        h = _int(_find_attr_list_value(el, "Height") or "40", 40)
        text = _find_attr_list_value(el, "Text") or _find_attr_list_value(el, "Caption") or name
        hmi_tag = (
            _find_attr_list_value(el, "ProcessTag")
            or _find_attr_list_value(el, "Tag")
            or _find_attr_list_value(el, "LinkedTag")
            or ""
        )
        wid = f"{device}/{screen}/{name}".replace(" ", "_")
        if wid in seen:
            continue  # nested container sometimes repeats the child item
        seen.add(wid)
        properties: dict[str, Any] = {"source_file": str(path)}
        properties.update(_extract_colors_xml(el))
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
                plc_tag="",
                text=text,
                device=device,
                screen=screen,
                source_name=name,
                source_type=type_name,
                supported=supported,
                status="synced",
                properties=properties,
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
            properties: dict[str, Any] = {
                "events": item.get("events") or [],
                "source_file": str(path),
            }
            properties.update(_extract_colors_json(item))
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
                    properties=properties,
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


# ---------------------------------------------------------------------------
# connections + tag tables
# ---------------------------------------------------------------------------


@dataclass
class HmiConnection:
    """One HMI ↔ PLC connection definition from ``connections/*.xml``."""

    name: str
    controller: str = ""
    driver: str = ""
    source_file: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "controller": self.controller,
            "driver": self.driver,
            "source_file": self.source_file,
        }


def parse_connections(device_dir: Path) -> list[HmiConnection]:
    """Read ``<device>/connections/*.xml`` into connection definitions."""
    conn_dir = Path(device_dir) / "connections"
    if not conn_dir.is_dir():
        return []
    found: list[HmiConnection] = []
    for xml in sorted(conn_dir.rglob("*.xml")):
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        nodes = [
            el
            for el in root.iter()
            if _local(el.tag).lower() in {"connection", "hmi.connection", "plcconnection"}
        ]
        if not nodes:
            nodes = [root]
        for el in nodes:
            name = (
                _attr(el, "Name")
                or _find_scalar_value(el, ("Name",))
                or xml.stem
            )
            controller = _find_scalar_value(
                el,
                (
                    "Controller",
                    "ControllerName",
                    "PlcName",
                    "PLCName",
                    "PartnerName",
                    "Partner",
                    "DeviceName",
                ),
            )
            driver = _find_scalar_value(
                el, ("CommunicationDriver", "Driver", "Protocol", "ConnectionType")
            )
            found.append(
                HmiConnection(
                    name=name,
                    controller=controller,
                    driver=driver,
                    source_file=str(xml),
                )
            )
    return found


def _normalize_plc_ref(value: str) -> str:
    """``"PLC_1"\\MainDB.Start`` / ``PLC_1/MainDB.Start`` → ``PLC_1.MainDB.Start``."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace('"', "")
    text = re.sub(r"[\\/]+", ".", text)
    text = re.sub(r"\s*\.\s*", ".", text)
    text = re.sub(r"\.{2,}", ".", text)
    return text.strip(". ")


def parse_hmi_tag_tables(device_dir: Path) -> dict[str, dict[str, str]]:
    """Read ``<device>/tags/*.xml`` into ``{hmi_tag: {plc_tag, data_type}}``."""
    tags_dir = Path(device_dir) / "tags"
    result: dict[str, dict[str, str]] = {}
    if not tags_dir.is_dir():
        return result
    for xml in sorted(tags_dir.rglob("*.xml")):
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        for el in root.iter():
            if _local(el.tag).lower() not in {"tag", "hmi.tag", "hmitag", "plctag"}:
                continue
            name = _attr(el, "Name") or _find_scalar_value(el, ("Name",))
            if not name:
                continue
            plc_ref = _find_scalar_value(
                el,
                (
                    "PlcTag",
                    "PLC tag",
                    "ControllerTag",
                    "LinkedTag",
                    "TagName",
                ),
            )
            data_type = _find_scalar_value(el, ("DataType", "Data Type")) or _attr(
                el, "DataType"
            )
            connection = _find_scalar_value(
                el, ("Connection", "ConnectionName", "ConnectionRef")
            )
            result[name] = {
                "plc_tag": _normalize_plc_ref(plc_ref),
                "data_type": data_type,
                "connection": connection,
                "source_file": str(xml),
            }
    return result


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def _key_variants(key: str) -> list[str]:
    variants = [key]
    # HMI tag may be qualified with its tag table: "HmiTags".StartCmd
    stripped = key.replace('"', "")
    for sep in (".", "\\", "/"):
        if sep in stripped:
            variants.append(stripped.split(sep)[-1])
    return [v for v in dict.fromkeys(v.strip() for v in variants) if v]


def resolve_hmi_to_plc_tags(
    widgets: list[CanvasHmiWidget],
    tag_map: dict[str, str],
    *,
    controller: str = "",
    connection: str = "",
) -> None:
    """Mutate widgets: set ``plc_tag`` from the real HMI tag table.

    No guessing: an HMI tag whose PLC reference is unknown stays unbound
    (``plc_tag == ""``) and is flagged with ``properties["binding_unresolved"]``
    so the UI can show “未绑定” instead of a fake address.
    """
    exact = {str(k): v for k, v in tag_map.items() if v}
    folded = {str(k).strip().lower(): v for k, v in exact.items()}
    for w in widgets:
        if w.plc_tag:
            w.properties.setdefault("binding_unresolved", False)
            continue
        if connection:
            w.properties.setdefault("plc_connection", connection)
        if controller:
            w.properties.setdefault("controller", controller)

        resolved = ""
        key = (w.hmi_tag or "").strip()
        if key:
            for variant in _key_variants(key):
                resolved = exact.get(variant) or folded.get(variant.lower(), "")
                if resolved:
                    break
        if resolved:
            w.plc_tag = _normalize_plc_ref(resolved)
            w.properties["binding_unresolved"] = False
            w.properties["binding_source"] = "hmi_tag_table"
        else:
            w.plc_tag = ""
            w.properties["binding_unresolved"] = True


def parse_hmi_export_tree(
    export_root: Path,
) -> tuple[list[CanvasHmiDevice], dict[str, CanvasHmiWidget]]:
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
            connections = parse_connections(device_dir)
            tag_defs = parse_hmi_tag_tables(device_dir)
            connections_by_name = {c.name.lower(): c for c in connections if c.name}
            tag_map: dict[str, str] = {}
            for name, info in tag_defs.items():
                ref = info.get("plc_tag") or ""
                declared_connection = (info.get("connection") or "").strip()
                connection = connections_by_name.get(declared_connection.lower()) if declared_connection else None
                if (
                    connection
                    and connection.controller
                    and ref
                    and ref.count(".") == 1
                    and ref.split(".", 1)[0].lower() != connection.controller.lower()
                ):
                    # relative symbol resolved against the tag's declared connection
                    ref = f"{connection.controller}.{ref}"
                if ref:
                    tag_map[name] = ref
            connection_name = connections[0].name if len(connections) == 1 else ""
            controller = connections[0].controller if len(connections) == 1 else ""
            resolve_hmi_to_plc_tags(
                collected,
                tag_map,
                controller=controller,
                connection=connection_name,
            )
            for w in collected:
                if len(connections) > 1:
                    w.properties.setdefault("connection_count", len(connections))
            devices.append(device)
            for w in collected:
                widgets[w.id] = w
    return devices, widgets
