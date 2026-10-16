"""HMI diff writeback: classic XML patch + Unified ops JSON apply."""

from __future__ import annotations

import json
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
        draft_widgets = [w for w in device_widgets if w.status == "draft" or not w.supported]
        # Always include newly added (draft) supported widgets
        changed = [w for w in device_widgets if w.status in {"draft", "error"}]
        if device.kind == "unified":
            ops_path = tmp / f"{device.name}_ops.json"
            ops = _unified_ops_from_widgets(device.name, changed)
            ops_path.write_text(json.dumps(ops, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(_apply_unified(project_path, device.name, ops_path))
        else:
            # Classic: write a minimal patch manifest; actual XML patch uses baseline when present
            patch_dir = tmp / device.name
            patch_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "device": device.name,
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
                    }
                    for w in changed
                ],
            }
            (patch_dir / "patch.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            # Attempt baseline XML patch for known widgets
            patched_files = _patch_classic_baseline(canvas, device.name, changed, patch_dir)
            for xml_file in patched_files:
                results.append(_import_hmi_xml(project_path, xml_file, device.name))

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
            ops.append(
                {
                    "action": "create",
                    "screen": w.screen or "Screen_1",
                    "type": w.widget_type,
                    "name": w.id.split("/")[-1],
                    "left": w.x,
                    "top": w.y,
                    "width": w.width,
                    "height": w.height,
                    "text": w.text or w.title,
                    "tag": w.hmi_tag or w.plc_tag,
                }
            )
        else:
            ops.append(
                {
                    "action": "update",
                    "screen": w.screen,
                    "name": w.source_name or w.id.split("/")[-1],
                    "left": w.x,
                    "top": w.y,
                    "width": w.width,
                    "height": w.height,
                    "text": w.text or w.title,
                    "tag": w.hmi_tag or w.plc_tag,
                }
            )
    return {"device": device, "ops": ops}


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
                _set_geom(root, w.source_name, w.x, w.y, w.width, w.height, w.text or w.title)
        out = out_dir / f"{screen}.xml"
        tree.write(out, encoding="utf-8", xml_declaration=True)
        written.append(out)
    return written


def _set_geom(root, name: str, x, y, w, h, text) -> None:
    import xml.etree.ElementTree as ET

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
        break


def _import_hmi_xml(project_path: Path, xml_file: Path, hmi_name: str) -> dict[str, Any]:
    try:
        from gateway.app.services.plc.openness_session import import_xml, session_enabled, ensure_session_running

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
        from gateway.app.services.plc.openness_session import compile_hmi, session_enabled, ensure_session_running

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
