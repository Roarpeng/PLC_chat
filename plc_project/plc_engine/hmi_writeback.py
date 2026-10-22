"""HMI diff writeback: classic XML patch + Unified ops JSON apply."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import CanvasState


def apply_hmi_diff(
    canvas: CanvasState,
    *,
    project_path: str | Path,
    compile_after: bool = True,
) -> dict[str, Any]:
    """Apply HMI widget diffs to TIA via Openness.

    Classic devices: emit patched screen XML fragments under a temp bundle and
    call ``import_xml_via_openness_cli`` / session import-xml.
    Unified devices: emit ``hmi_ops.json`` and call ``hmi-unified-apply`` when available.
    """
    project_path = Path(project_path)
    devices = canvas.hmi_devices or []
    if not devices:
        return {"ok": True, "skipped": True, "message": "no HMI devices"}

    results: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    tmp = Path(tempfile.mkdtemp(prefix="hmi_writeback_"))

    for device in devices:
        device_widgets = [w for w in canvas.hmi_widgets.values() if w.device == device.name]
        # Draft/error edits plus unsupported placeholders: placeholders may only be
        # moved, but they still have to take part in the writeback.
        changed = [
            w for w in device_widgets if w.status in {"draft", "error"} or not w.supported
        ]
        if not changed:
            continue
        if device.kind == "unified":
            ops_path = tmp / f"{device.name}_ops.json"
            ops = _unified_ops_from_widgets(device.name, changed)
            ops_path.write_text(json.dumps(ops, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(_apply_unified(project_path, device.name, ops_path))
        else:
            patch_dir = tmp / device.name
            patch_dir.mkdir(parents=True, exist_ok=True)
            # Baseline XML is the real product; the manifest only exists as a
            # reported artifact when no baseline is available.
            patched_files = _patch_classic_baseline(canvas, device.name, changed, patch_dir)
            if patched_files:
                for xml_file in patched_files:
                    results.append(_import_hmi_xml(project_path, xml_file, device.name))
            else:
                manifest_path = _write_patch_manifest(device.name, changed, patch_dir)
                results.append(
                    {
                        "ok": True,
                        "applied": False,
                        "degraded": True,
                        "reason": "no_baseline",
                        "hmi": device.name,
                        "widgets": len(changed),
                        "artifact": str(manifest_path),
                        "message": "no baseline HMI screen XML; wrote patch manifest only",
                    }
                )

    compile_ok = True
    if compile_after:
        for device in devices:
            cre = _compile_hmi(project_path, device.name)
            results.append(cre)
            if not cre.get("ok"):
                compile_ok = False
            for m in cre.get("messages") or []:
                if isinstance(m, dict):
                    messages.append(m)

    ok = all(r.get("ok", True) for r in results) if results else True
    return {
        "ok": ok and compile_ok,
        "compile_ok": compile_ok,
        "results": results,
        "messages": messages,
        "message": "HMI writeback finished" if ok else "HMI writeback had errors",
    }


def _binding_value(w) -> str:
    """Never hand an unbound HMI tag to TIA as if it were a PLC address."""
    if w.plc_tag:
        return w.plc_tag
    if (w.properties or {}).get("binding_unresolved"):
        return ""
    return w.hmi_tag or ""


# canvas property → Unified ops JSON key. camelCase matches HmiUnifiedDump and
# the keys ``_extract_colors_json`` accepts, so dump → parse → writeback →
# dump round-trips without renaming.
_UNIFIED_COLOR_KEYS = {
    "bg_color": "backColor",
    "fg_color": "foreColor",
    "border_color": "borderColor",
}


def _unified_color_fields(w) -> dict[str, str]:
    """Colour fields for a Unified op, aligned with the classic XML chain.

    Only values that normalise to ``#RRGGBB`` are sent. A raw/unrecognised
    value (``GradientBrush(1)``, unknown named constants) is dropped instead
    of being re-encoded into an invented representation — same rule as
    ``_set_colors`` applies to classic screen XML.
    """
    from agents.plc.tia.hmi_screens import normalize_color

    fields: dict[str, str] = {}
    for key, json_key in _UNIFIED_COLOR_KEYS.items():
        value = (w.properties or {}).get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = normalize_color(value)
        if normalized:
            fields[json_key] = normalized
    return fields


def _unified_ops_from_widgets(device: str, widgets: list) -> dict[str, Any]:
    ops = []
    for w in widgets:
        if not w.supported and w.status != "draft":
            # placeholders: only position updates
            ops.append(
                {
                    "action": "update",
                    "screen": w.screen,
                    "name": w.source_name or w.id,
                    "left": w.x,
                    "top": w.y,
                }
            )
            continue
        if w.status == "draft" and not w.source_name:
            op = {
                "action": "create",
                "screen": w.screen or "Screen_1",
                "type": w.widget_type,
                "name": w.id.split("/")[-1],
                "left": w.x,
                "top": w.y,
                "width": w.width,
                "height": w.height,
                "text": w.text or w.title,
                "tag": _binding_value(w),
            }
            op.update(_unified_color_fields(w))
            ops.append(op)
        else:
            op = {
                "action": "update",
                "screen": w.screen,
                "name": w.source_name or w.id.split("/")[-1],
                "left": w.x,
                "top": w.y,
                "width": w.width,
                "height": w.height,
                "text": w.text or w.title,
                "tag": _binding_value(w),
            }
            op.update(_unified_color_fields(w))
            ops.append(op)
    return {"device": device, "ops": ops}


def _write_patch_manifest(device: str, widgets: list, out_dir: Path) -> Path:
    """Write the classic fallback artifact used when no baseline XML exists.

    The path is returned to ``apply_hmi_diff`` and surfaced in ``results`` so the
    manifest is actually consumed by the caller instead of being dropped.
    """
    manifest = {
        "device": device,
        "mode": "classic_patch_manifest",
        "widgets": [
            {
                "id": w.id,
                "source_name": w.source_name,
                "screen": w.screen,
                "x": w.x,
                "y": w.y,
                "width": w.width,
                "height": w.height,
                "text": w.text or w.title,
                "plc_tag": w.plc_tag,
                "hmi_tag": w.hmi_tag,
                "widget_type": w.widget_type,
                "supported": w.supported,
                "status": w.status,
                "bg_color": w.properties.get("bg_color"),
                "fg_color": w.properties.get("fg_color"),
                "border_color": w.properties.get("border_color"),
            }
            for w in widgets
        ],
    }
    path = out_dir / "patch.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _patch_classic_baseline(
    canvas: CanvasState,
    device: str,
    widgets: list,
    out_dir: Path,
) -> list[Path]:
    """If workspace baseline screen XML exists, patch Left/Top/Width/Height/Text and return paths."""
    source = canvas.source
    if not source or not source.project_id:
        return []
    try:
        from gateway.app.services.plc import workspace as ws

        base = ws.project_dir(source.project_id) / "baseline" / "hmi" / device / "screens"
    except Exception:  # noqa: BLE001
        return []
    if not base.is_dir():
        return []

    import xml.etree.ElementTree as ET

    written: list[Path] = []
    by_screen: dict[str, list] = {}
    for w in widgets:
        by_screen.setdefault(w.screen or "Screen_1", []).append(w)

    for screen, items in by_screen.items():
        src = base / f"{screen}.xml"
        if not src.is_file():
            # try any xml containing screen name
            candidates = list(base.rglob(f"*{screen}*.xml"))
            if not candidates:
                continue
            src = candidates[0]
        try:
            tree = ET.parse(src)
            root = tree.getroot()
        except ET.ParseError:
            continue
        for w in items:
            if not w.supported and w.source_name:
                # only move placeholders
                _set_geom(root, w.source_name, w.x, w.y, None, None, None)
            elif w.source_name:
                _set_geom(
                    root,
                    w.source_name,
                    w.x,
                    w.y,
                    w.width,
                    w.height,
                    w.text or w.title,
                    colors=w.properties,
                )
        out = out_dir / f"{screen}.xml"
        tree.write(out, encoding="utf-8", xml_declaration=True)
        written.append(out)
    return written


_COLOR_WRITE_TARGETS = {
    "bg_color": ("BackColor", "BgColor", "BackgroundColor", "Background", "FillColor"),
    "fg_color": ("ForeColor", "FgColor", "ForegroundColor", "FontColor", "TextColor", "Foreground"),
    "border_color": ("BorderColor", "FrameColor", "LineColor"),
}


def _set_geom(root, name: str, x, y, w, h, text, *, colors: dict | None = None) -> None:
    """Patch one classic screen item in-place (geometry, text and colours)."""

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    for el in root.iter():
        # find Name child matching
        name_el = None
        for child in list(el):
            if local(child.tag) == "Name" and (child.text or "").strip() == name:
                name_el = child
                break
        if name_el is None:
            continue
        parent = el
        # search AttributeList siblings / descendants
        for child in parent.iter():
            tag = local(child.tag)
            if tag == "Left" and x is not None:
                child.text = str(x)
            elif tag == "Top" and y is not None:
                child.text = str(y)
            elif tag == "Width" and w is not None:
                child.text = str(w)
            elif tag == "Height" and h is not None:
                child.text = str(h)
            elif tag in {"Text", "Caption"} and text is not None:
                child.text = str(text)
        if colors:
            _set_colors(parent, colors)
        break


def _find_color_node(el, names: tuple[str, ...] | list[str]):
    lowered = {n.lower() for n in names}

    def scan(node):
        for child in list(node):
            if _local_name(child.tag).lower() in lowered:
                return child
        return None

    for child in list(el):
        if _local_name(child.tag).lower() == "attributelist":
            found = scan(child)
            if found is not None:
                return found
    found = scan(el)
    if found is not None:
        return found
    for child in el.iter():
        if child is not el and _local_name(child.tag).lower() in lowered:
            return child
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _set_colors(el, colors: dict) -> None:
    """Write normalised colours back using the attribute name found on import."""
    from agents.plc.tia.hmi_screens import normalize_color

    sources = colors.get("color_source") or {}
    for key, defaults in _COLOR_WRITE_TARGETS.items():
        value = colors.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if normalize_color(value) is None:
            continue  # raw/unrecognised: never invent a representation
        names: list[str] = []
        source = sources.get(key)
        if source:
            names.append(str(source).replace(" (raw)", ""))
        names.extend(defaults)
        node = _find_color_node(el, names)
        if node is None:
            continue
        node.text = _format_color_like(node.text, value)


def _format_color_like(existing: str | None, hex_value: str) -> str:
    """Keep the baseline's colour encoding (decimal / hex / rgb tuple)."""
    red, green, blue = (int(hex_value[i : i + 2], 16) for i in (1, 3, 5))
    text = (existing or "").strip()
    if not text:
        return hex_value
    if text.lower().startswith("0x"):
        return f"0x{red:02X}{green:02X}{blue:02X}"
    if text.startswith("#"):
        return hex_value.upper()
    if re.fullmatch(r"[+-]?\d+", text):
        return str((red << 16) | (green << 8) | blue)
    parts = [p for p in re.split(r"\s*[,;]\s*", text) if p]
    if len(parts) >= 3 and all(re.fullmatch(r"[+-]?\d+", p) for p in parts[:3]):
        separator = ", " if "," in text else "; "
        if len(parts) >= 4:  # preserve alpha channel
            return separator.join([str(red), str(green), str(blue), parts[3]])
        return separator.join([str(red), str(green), str(blue)])
    if re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return f"{red:02X}{green:02X}{blue:02X}"
    return hex_value


def _import_hmi_xml(project_path: Path, xml_file: Path, hmi_name: str) -> dict[str, Any]:
    try:
        from gateway.app.services.plc.openness_session import (
            ensure_session_running,
            import_xml,
            session_enabled,
        )

        if session_enabled() and ensure_session_running():
            res = import_xml(str(project_path), str(xml_file), kind="hmi", hmi_name=hmi_name)
            if not res.get("fallback"):
                return res
        from agents.plc.tia.openness_cli import import_xml_via_openness_cli

        return import_xml_via_openness_cli(
            str(project_path),
            str(xml_file),
            kind="hmi",
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "xml": str(xml_file)}


def _apply_unified(project_path: Path, hmi_name: str, ops_path: Path) -> dict[str, Any]:
    try:
        from agents.plc.tia.openness_cli import openness_cli

        return openness_cli(
            "hmi-unified-apply",
            "--project",
            str(project_path),
            "--hmi",
            hmi_name,
            "--ops",
            str(ops_path),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "note": "hmi-unified-apply unavailable"}


def _compile_hmi(project_path: Path, hmi_name: str) -> dict[str, Any]:
    try:
        from gateway.app.services.plc.openness_session import (
            compile_hmi,
            ensure_session_running,
            session_enabled,
        )

        if session_enabled() and ensure_session_running():
            res = compile_hmi(str(project_path), hmi_name=hmi_name)
            if not res.get("fallback"):
                return res
        from agents.plc.tia.openness_cli import openness_cli

        return openness_cli(
            "compile-hmi",
            "--project",
            str(project_path),
            "--hmi",
            hmi_name,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "messages": []}
