"""Inspect portable AF workspace exports without extracting archives."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from plc_engine.engineering_ir.models import AFProfile
from plc_engine.engineering_ir.station_design import StationDesign, design_issues

MAX_IMPORT_BYTES = 12 * 1024 * 1024


def inspect_native_archive(filename: str, data: bytes) -> dict:
    from gateway.app.services.plc.af_import import ROLE_EM, ROLE_UNKNOWN, analyze_import
    from gateway.app.services.plc.canvas_import import CanvasImportRejected, import_canvas_from_path
    from gateway.app.services.plc.paths import save_upload
    from plc_engine.canvas_model import CanvasState

    try:
        saved = save_upload(filename, data)
        imported = import_canvas_from_path(saved, Path(filename).stem)
    except CanvasImportRejected as exc:
        raise ValueError(exc.message) from exc
    canvas = CanvasState.from_dict(imported.get("canvas") or {})
    if not canvas.blocks:
        raise ValueError("归档未读取到 PLC 程序块。")
    report = analyze_import(canvas)
    roles = report.get("roles", {})
    matching = {canvas.blocks[key].software_unit for key, role in roles.items()
                if role == ROLE_EM and key in canvas.blocks and canvas.blocks[key].software_unit}
    questions = [{"reason": f"{key} 未匹配 AF 角色。"} for key, role in roles.items() if role == ROLE_UNKNOWN]
    questions.append({"reason": "归档中的程序块已识别。编辑原逻辑需要匹配的 AF 画布 JSON 或可回导源码包。"})
    return {"name": canvas.project_name or Path(filename).stem, "station_count": len(matching),
            "device_count": None, "questions": questions, "af_profile": AFProfile().profile_id,
            "compatible": bool(report.get("conformant") and matching), "can_import": False}


def inspect_station_export(data: bytes) -> tuple[StationDesign, dict]:
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError("工程文件超过 12 MB。")
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo("af-canvas.json")
                if info.file_size > MAX_IMPORT_BYTES:
                    raise ValueError("工程画布超过 12 MB。")
                data = archive.read(info)
        except KeyError as exc:
            raise ValueError("归档缺少 af-canvas.json。请选择有 AF 画布定义的导出包。") from exc
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError("无法读取 AF 导出包。") from exc
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("请选择 AF 画布 JSON 或包含 af-canvas.json 的源码包。") from exc
    if not isinstance(payload, dict) or payload.get("format") != "af-station-canvas/1":
        raise ValueError("工程格式不符合 AF 工位画布规范。")
    if payload.get("af_profile") != AFProfile().to_dict():
        raise ValueError("工程的 AF Profile、模板或博途版本与当前支持的基准不一致。")
    design = StationDesign.model_validate(payload.get("station_design"))
    issues = design_issues(design)
    if issues:
        raise ValueError(issues[0]["reason"])
    return design, {
        "name": design.name,
        "station_count": len(design.stations),
        "device_count": sum(len(item.devices) for item in design.stations),
        "source_ir_sha256": str(payload.get("source_ir_sha256") or "")[:80],
        "questions": design_issues(design, release=True),
        "af_profile": AFProfile().profile_id,
        "can_import": True,
    }
