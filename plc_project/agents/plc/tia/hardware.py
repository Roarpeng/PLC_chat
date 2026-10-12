"""Best-effort hardware / Profinet parse from Openness HW XML and CAx AML.

Skip (do not fail the job) when no device/rack XML is present.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from agents.plc.tia.ir import HardwareDevice, PlcProject

_DEVICE_TAGS = {
    "Device",
    "DeviceItem",
    "HW.Devices.Device",
    "HW.Device",
    "SW.Devices.Device",
    "Rack",
    "Module",
    "InternalElement",
}

_SKIP_NAMES = {"conversionlog", "gsdml"}


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
        if _strip_ns(node.tag).lower() in want and (node.text or "").strip():
            return (node.text or "").strip()
    return ""


def _is_failsafe(el: ET.Element, dtype: str, name: str) -> bool:
    raw = (_attr(el, "Failsafe") or _child_text(el, "Failsafe", "IsFailsafe")).lower()
    if raw in {"true", "1", "yes"}:
        return True
    blob = f"{dtype} {name}".lower()
    return "f-cpu" in blob or "failsafe" in blob or name.startswith("F-")


def looks_like_hardware_xml(path: Path) -> bool:
    name = path.name.lower()
    if any(skip in name for skip in _SKIP_NAMES):
        return False
    parts = {p.lower() for p in path.parts}
    if "gsd" in parts:
        return False
    if "hardware" in parts:
        return True
    try:
        head = path.read_bytes()[:8192].decode("utf-8", errors="ignore")
    except OSError:
        return False
    markers = (
        "HW.Devices",
        "HW.Device",
        "DeviceItem",
        "ProfinetInterface",
        "Siemens.Engineering.HW",
        "<Rack",
        "CompositionName=\"Devices\"",
        "<HardwareTree",
        "<CAEXFile",
        "InternalElement",
    )
    return any(m in head for m in markers)


def _aml_attr(el: ET.Element, name: str) -> str:
    want = name.lower()
    for child in el:
        if _strip_ns(child.tag) != "Attribute":
            continue
        if (_attr(child, "Name") or "").lower() == want:
            return (child.text or "").strip() or _child_text(child, "Value")
    return ""


def parse_hardware_xml(path: Path) -> list[HardwareDevice]:
    """Extract device/rack/Profinet rows; empty list on unrecognized XML."""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError:
        return []
    devices: list[HardwareDevice] = []
    seen: set[tuple[str, str]] = set()

    if _strip_ns(root.tag) == "HardwareTree" or any(
        _strip_ns(n.tag) == "Device" and n is not root for n in root
    ):
        for device_el in root.iter():
            if _strip_ns(device_el.tag) != "Device":
                continue
            row = _device_from_tree(device_el, path)
            key = (row.name, row.device_type)
            if key in seen:
                continue
            seen.add(key)
            devices.append(row)
        if devices:
            return devices

    if _strip_ns(root.tag) == "CAEXFile" or "InternalElement" in {
        _strip_ns(n.tag) for n in list(root)[:8]
    }:
        for node in root.iter():
            if _strip_ns(node.tag) != "InternalElement":
                continue
            name = _attr(node, "Name")
            if not name:
                continue
            dtype = _aml_attr(node, "TypeIdentifier") or _aml_attr(node, "Type") or "InternalElement"
            failsafe = _is_failsafe(node, dtype, name) or _aml_attr(node, "Failsafe").lower() in {
                "true",
                "1",
            }
            modules = [
                _attr(c, "Name")
                for c in node
                if _strip_ns(c.tag) == "InternalElement" and _attr(c, "Name")
            ]
            key = (name, dtype)
            if key in seen:
                continue
            seen.add(key)
            devices.append(
                HardwareDevice(
                    name=name,
                    device_type=dtype,
                    failsafe=failsafe,
                    modules=modules,
                    source_file=str(path),
                    rack=_attr(node, "ID") or "",
                )
            )
        if devices:
            return devices

    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag not in _DEVICE_TAGS and "Device" not in tag and tag not in {"ProfinetInterface"}:
            continue
        name = _attr(node, "Name") or _child_text(node, "Name", "DeviceName")
        if not name:
            continue
        dtype = (
            _attr(node, "TypeIdentifier")
            or _attr(node, "Type")
            or _child_text(node, "TypeIdentifier", "TypeName", "Type")
            or tag
        )
        address = (
            _attr(node, "Address")
            or _child_text(node, "Address", "IpAddress", "LogicalAddress")
        )
        slot = _attr(node, "Slot") or _child_text(node, "Slot", "PositionNumber")
        comment = _child_text(node, "Comment", "Text")
        key = (name, dtype)
        if key in seen:
            continue
        seen.add(key)
        devices.append(
            HardwareDevice(
                name=name,
                device_type=dtype,
                address=address,
                slot=slot,
                comment=comment[:240],
                source_file=str(path),
                failsafe=_is_failsafe(node, dtype, name),
            )
        )
    return devices


def _device_from_tree(el: ET.Element, path: Path) -> HardwareDevice:
    name = _attr(el, "Name") or _child_text(el, "Name")
    dtype = _attr(el, "TypeIdentifier") or _attr(el, "Type") or "Device"
    modules: list[str] = []
    subnets: list[str] = []
    nics: list[str] = []
    rack = ""
    for child in el:
        tag = _strip_ns(child.tag)
        if tag == "DeviceItem":
            iname = _attr(child, "Name")
            if iname:
                modules.append(iname)
            if not rack:
                rack = _attr(child, "Slot") or _child_text(child, "Slot")
            for nested in child:
                ntag = _strip_ns(nested.tag)
                if ntag == "Subnet" and _attr(nested, "Name"):
                    subnets.append(_attr(nested, "Name"))
                elif ntag == "NetworkInterface":
                    nname = _attr(nested, "Name") or _attr(nested, "Address")
                    if nname:
                        nics.append(nname)
        elif tag == "Subnet" and _attr(child, "Name"):
            subnets.append(_attr(child, "Name"))
        elif tag == "NetworkInterface":
            nname = _attr(child, "Name") or _attr(child, "Address")
            if nname:
                nics.append(nname)
    return HardwareDevice(
        name=name,
        device_type=dtype,
        address=_attr(el, "Address") or _child_text(el, "Address"),
        slot=_attr(el, "Slot"),
        comment=_child_text(el, "Comment", "Text")[:240],
        source_file=str(path),
        failsafe=_is_failsafe(el, dtype, name),
        rack=rack,
        modules=modules,
        subnets=subnets,
        network_interfaces=nics,
    )


def attach_hardware(project: PlcProject, xml_files: list[Path]) -> PlcProject:
    """Fill ``project.hardware`` from any HW XML; never raise into the job."""
    found: list[HardwareDevice] = []
    for path in xml_files:
        if not looks_like_hardware_xml(path):
            continue
        try:
            found.extend(parse_hardware_xml(path))
        except Exception as exc:  # noqa: BLE001 — hardware is advisory
            project.extraction_notes.append(f"hardware parse skipped for {path.name}: {exc}")
    project.hardware = found
    return project
