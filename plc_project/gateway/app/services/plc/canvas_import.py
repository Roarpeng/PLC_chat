"""TIA Portal Openness export -> interactive Canvas import service.

Parses SimaticML XML (a single block/tag-table file, or a whole Openness
export directory — ``Blocks/`` / ``TagTables/`` subtrees or flat layouts)
into a ``CanvasState`` payload that the interactive canvas endpoints
(/canvas/patch, /canvas/to-scl, /canvas/confirm-writeback) can consume.

Offline for XML inputs: LAD/FBD networks are translated via
``translate_block_to_scl`` / ``NetworkTranslator`` into IEC 61131-3-style SCL;
UDT/DB get full STRUCT units. ``.zap``/``.zap15``-``.zap20``/``.zip`` archives
and complete ``.ap17-.ap20`` trees go through the Openness CLI (blocks+types+tags).
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.plc.tia.simaticml import parse_block_xml, parse_tag_table_xml
from plc_engine.canvas_model import (
    CanvasBlock,
    CanvasNetwork,
    CanvasSource,
    CanvasState,
    CanvasTag,
    CanvasVariable,
)

APXX_SUFFIXES = {".ap17", ".ap18", ".ap19", ".ap20"}

# Siemens compressed project archives (.zap is a ZIP) and plain .zip exports.
ZAP_SUFFIXES = {".zap", ".zap15", ".zap16", ".zap17", ".zap18", ".zap19", ".zap20", ".zip"}

OPENNESS_EXPORT_REQUIRED_MESSAGE = "请先在博图中通过 Openness 导出块 XML 或直接提供导出目录"

# XML Section@Name / IR InterfaceSection -> canvas VAR_* section.
# None->VAR, Input->VAR_INPUT, Output->VAR_OUTPUT, InOut->VAR_IN_OUT,
# Static->VAR_STAT, Temp->VAR_TEMP, Constant->VAR; Return acts as an output.
_SECTION_TO_CANVAS = {
    "": "VAR",
    "None": "VAR",
    "Constant": "VAR",
    "Input": "VAR_INPUT",
    "Output": "VAR_OUTPUT",
    "Return": "VAR_OUTPUT",
    "InOut": "VAR_IN_OUT",
    "Static": "VAR_STAT",
    "Temp": "VAR_TEMP",
}

ProgressCb = Callable[..., None]


class CanvasImportRejected(ValueError):
    """Import rejected before any canvas mutation; the router maps it to HTTP 400."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _noop_progress(stage: str, message: str, **extra: Any) -> None:
    _ = (stage, message, extra)


def _section_name(section: Any) -> str:
    return str(getattr(section, "value", section) or "")


def _canvas_section(block_type: str, section: Any) -> str:
    # DB/UDT members are plain STRUCT data — the canvas renders them without sections.
    if str(block_type).upper() in {"DB", "UDT"}:
        return "VAR"
    return _SECTION_TO_CANVAS.get(_section_name(section), "VAR")


def _network_id(raw_id: Any, index: int) -> int:
    try:
        return int(str(raw_id).strip())
    except (TypeError, ValueError):
        return index + 1


def _referenced_symbols(network: Any) -> list[str]:
    """Unique FlgNet symbol names (Component@Name chains) referenced by one network."""
    symbols: list[str] = []
    for acc in network.accesses():
        if _section_name(acc.scope) == "literal":
            continue
        parts = [acc.root, *acc.path] if acc.root else []
        symbol = ".".join(p for p in parts if p) or acc.absolute or ""
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _next_block_number(blocks: dict[str, CanvasBlock], block_type: str) -> int:
    numbers = [b.number for b in blocks.values() if b.block_type.upper() == block_type]
    return max(numbers) + 1 if numbers else 1


def _extract_begin_body(full_scl: str) -> str:
    """Slice statements between BEGIN and the closing END_* keyword."""
    lines = full_scl.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().upper() == "BEGIN"), None)
    if start is None:
        return full_scl.strip()
    end = next(
        (
            i
            for i in range(len(lines) - 1, start, -1)
            if lines[i].strip().upper().startswith("END_")
        ),
        None,
    )
    body = lines[start + 1 : end if end is not None else None]
    return "\n".join(body).strip()


def _network_scl_text(block: Any, net: Any, index: int, language: str) -> str:
    """Prefer NetworkTranslator / source_text; fall back to symbol summary."""
    from agents.plc.tia.scl import NetworkTranslator

    source = (net.source_text or "").strip()
    if source:
        return source
    try:
        statements = NetworkTranslator(block, net).translate()
        usable = [
            s
            for s in statements
            if s and s.strip() and s.strip() != "(* empty network *)"
        ]
        if usable:
            return "\n".join(usable)
    except Exception:  # noqa: BLE001 — keep import resilient
        pass
    symbols = _referenced_symbols(net)
    listed = ", ".join(symbols) if symbols else "无"
    lang = (net.programming_language or language or "LAD").upper()
    return f"// {lang} 网络 {index + 1}（图形折叠占位），引用符号：{listed}"


def _detect_software_unit(path: Path) -> str:
    parts = list(path.parts)
    if "units" in parts:
        idx = parts.index("units")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _infer_af_role(name: str, software_unit: str = "") -> str:
    n = name.lower()
    if "callunit" in n:
        return "CallUnit"
    if "callequipment" in n:
        return "CallEquipment"
    if "emnodes" in n:
        return "EmNodes"
    if "controlnodes" in n:
        return "ControlNodes"
    if "steptostring" in n:
        return "StepToString"
    if "sequence" in n:
        return "Sequence"
    if "collectalarms" in n:
        return "CollectAlarms"
    if "simulationdata" in n:
        return "SimulationData"
    if "hmiinterface" in n:
        return "HmiInterface"
    if n.startswith("ob") or "startup" in n or "main" in n or "prodiag" in n:
        return "OB"
    if "config" in n:
        return "Config"
    if "alarms" in n:
        return "Alarms"
    return ""

def _block_to_canvas_block(
    block: Any,
    existing: dict[str, CanvasBlock],
    software_unit: str = "",
    af_role: str = "",
) -> CanvasBlock:
    from agents.plc.tia.scl import translate_block_to_scl

    block_type = str(getattr(block.block_type, "value", block.block_type) or "FB").upper()
    number = int(block.number or 0)
    if number <= 0:
        number = _next_block_number(existing, block_type)
    language = (block.programming_language or "").strip() or ("DB" if block_type == "DB" else "SCL")

    interface = [
        CanvasVariable(
            name=v.name,
            data_type=v.data_type,
            section=_canvas_section(block_type, v.section),
            comment=v.comment,
        )
        for v in block.interface
    ]

    full_scl = ""
    try:
        full_scl = (translate_block_to_scl(block) or "").strip()
    except Exception:  # noqa: BLE001
        full_scl = ""

    networks: list[CanvasNetwork] = []
    for index, net in enumerate(block.networks):
        networks.append(
            CanvasNetwork(
                id=_network_id(net.id, index),
                title=(net.title or "").strip(),
                language=(net.programming_language or "").strip() or language or "LAD",
                scl_text=_network_scl_text(block, net, index, language),
                status="synced",
            )
        )

    if block_type in {"DB", "UDT"}:
        scl_body = full_scl or (block.source_text or "").strip()
    elif full_scl:
        scl_body = _extract_begin_body(full_scl)
    else:
        scl_body = (block.source_text or "").strip()

    # UDT with no networks: expose TYPE unit as a single pseudo-network for SCL pane.
    if block_type == "UDT" and not networks and scl_body:
        networks.append(
            CanvasNetwork(
                id=1,
                title="TYPE",
                language="SCL",
                scl_text=scl_body,
                status="synced",
            )
        )

    return CanvasBlock(
        name=block.name,
        block_type=block_type,
        number=number,
        language="SCL" if block_type == "UDT" else language,
        comment=(block.header_comment or "").strip(),
        interface=interface,
        networks=networks,
        scl_body=scl_body,
        status="synced",
        software_unit=software_unit,
        af_role=af_role,
        # Bug1:know-how/体未导出块标记 protected —— scl_body 是空壳,
        # 写回侧必须跳过,否则 TIA 原始内容被覆盖。
        protected=bool(getattr(block, "interface_only", False)),
    )


def _openness_export_to_tempdir(
    apxx_path: Path, *, on_progress: ProgressCb = _noop_progress
) -> Path:
    """Run Openness export (with export-cache) into a temp dir; return the temp root.

    Uses ``export_apxx_via_openness`` so repeated imports hit the content-addressed
    cache and skip the Openness open/export. Product path uses ``--canvas``
    (blocks + types + tags + HMI) via RESEARCHOS_TIA_EXPORT_MODE.

    Raises ``CanvasImportRejected("OPENNESS_EXPORT_REQUIRED")`` when the host is
    unavailable or the export fails, so the router can answer 400 with guidance.
    """
    import os

    from agents.plc.tia.importer import export_apxx_via_openness

    tmp_root = Path(tempfile.mkdtemp(prefix="canvas_openness_export_"))
    prev_mode = os.environ.get("RESEARCHOS_TIA_EXPORT_MODE")
    os.environ["RESEARCHOS_TIA_EXPORT_MODE"] = "canvas"
    try:
        on_progress(
            "openness_export",
            "Openness 导出中（canvas：PLC + HMI，可走导出缓存）…",
            path=str(apxx_path),
        )
        _path, notes, _timings = export_apxx_via_openness(
            apxx_path, export_dir=tmp_root / "export"
        )
        if any("cache HIT" in n for n in notes):
            on_progress("openness_export", "导出缓存命中，跳过 Openness")
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise CanvasImportRejected(
            "OPENNESS_EXPORT_REQUIRED",
            f"{OPENNESS_EXPORT_REQUIRED_MESSAGE}（Openness 导出失败：{exc}）",
        ) from exc
    finally:
        if prev_mode is None:
            os.environ.pop("RESEARCHOS_TIA_EXPORT_MODE", None)
        else:
            os.environ["RESEARCHOS_TIA_EXPORT_MODE"] = prev_mode
    return tmp_root


def _import_via_openness(
    apxx_path: Path, project_name: str, *, on_progress: ProgressCb = _noop_progress
) -> dict[str, Any]:
    """Export ``apxx_path`` through Openness into a temp dir and parse the result."""
    tmp_root = _openness_export_to_tempdir(apxx_path, on_progress=on_progress)
    try:
        return _parse_export_tree(tmp_root / "export", project_name, on_progress=on_progress)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _find_complete_apxx(root: Path) -> tuple[Path | None, list[Path]]:
    """Return the first complete TIA project file under ``root`` plus all .apxx found."""
    from agents.plc.tia.importer import find_apxx_files, is_complete_tia_project

    apxx_files = find_apxx_files(root)
    complete = next((ap for ap in apxx_files if is_complete_tia_project(ap)), None)
    return complete, apxx_files


def _import_archive(
    archive: Path, project_name: str, *, on_progress: ProgressCb = _noop_progress
) -> dict[str, Any]:
    """Unpack a .zap*/.zip archive into a temp dir and import whatever is inside.

    SimaticML XML exports parse offline; a complete ``.ap17-.ap20`` project
    tree goes through the Openness CLI; a bare/incomplete ``.apxx`` is
    rejected with packaging guidance.
    """
    from agents.plc.tia.importer import extract_tia_archive, has_simaticml_exports

    on_progress("unpack", f"解包归档 {archive.name}…")
    extract_root = Path(tempfile.mkdtemp(prefix="canvas_zap_extract_"))
    try:
        try:
            extracted = extract_tia_archive(archive, dest=extract_root)
        except ValueError as exc:  # corrupt / non-ZIP .zap* — surface as 400, not 500
            raise CanvasImportRejected("NO_PARSEABLE_FILES", str(exc)) from exc
        check_root = extracted if extracted.is_dir() else extracted.parent
        if has_simaticml_exports(check_root):
            return _parse_export_tree(check_root, project_name, on_progress=on_progress)
        complete, apxx_files = _find_complete_apxx(check_root)
        if complete is not None:
            return _import_via_openness(complete, project_name, on_progress=on_progress)
        if apxx_files:
            from agents.plc.tia.importer import incomplete_apxx_guidance

            raise CanvasImportRejected(
                "OPENNESS_EXPORT_REQUIRED", incomplete_apxx_guidance(apxx_files[0])
            )
        raise CanvasImportRejected(
            "NO_PARSEABLE_FILES",
            f"归档 {archive.name} 解压后既没有 SimaticML 块/标签表 XML，"
            "也没有 TIA 工程文件（.ap17-.ap20）",
        )
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def _import_directory(
    directory: Path, project_name: str, *, on_progress: ProgressCb = _noop_progress
) -> dict[str, Any]:
    """Import a directory: SimaticML export XML, or a full TIA project tree via Openness."""
    from agents.plc.tia.importer import has_simaticml_exports

    if not has_simaticml_exports(directory):
        complete, apxx_files = _find_complete_apxx(directory)
        if complete is not None:
            # A .zap-unpacked project folder — same treatment as ingest.
            return _import_via_openness(complete, project_name, on_progress=on_progress)
        if apxx_files:
            from agents.plc.tia.importer import incomplete_apxx_guidance

            raise CanvasImportRejected(
                "OPENNESS_EXPORT_REQUIRED", incomplete_apxx_guidance(apxx_files[0])
            )
    return _parse_export_tree(directory, project_name, on_progress=on_progress)


def _parse_one_xml(xml_file: Path) -> dict[str, Any]:
    """Parse one SimaticML XML into a block, tag-table, or skip record."""
    reason = ""
    try:
        block = parse_block_xml(xml_file)
    except Exception as exc:  # noqa: BLE001 — one bad file must not kill the import
        block = None
        reason = f"块 XML 解析失败：{exc}"
    if block is not None and block.name:
        su = _detect_software_unit(xml_file)
        return {"kind": "block", "block": block, "file": xml_file, "software_unit": su}

    try:
        table = parse_tag_table_xml(xml_file)
    except Exception as exc:  # noqa: BLE001 — advisory, fall through to skipped
        table = None
        reason = reason or f"标签表解析失败：{exc}"
    if table is not None and table.tags:
        return {"kind": "tags", "table": table, "file": xml_file}
    if table is not None:
        reason = reason or "空标签表（无 SW.Tags.PlcTag）"
    return {
        "kind": "skip",
        "file": xml_file,
        "reason": reason or "非 SW.Blocks.* 块或 SW.Tags.PlcTagTable 标签表导出",
    }


def _parse_export_tree(
    parse_root: Path, project_name: str, *, on_progress: ProgressCb = _noop_progress
) -> dict[str, Any]:
    if parse_root.is_file():
        xml_files = [parse_root]
    else:
        xml_files = sorted(p for p in parse_root.rglob("*.xml") if p.is_file())

    total = len(xml_files)
    on_progress("parse", f"解析 SimaticML（0/{total}）…", current=0, total=total)

    from agents.plc.tia.parallel import map_parallel

    parsed_rows = list(map_parallel(_parse_one_xml, xml_files, min_items=8))

    canvas = CanvasState(project_name=project_name)
    skipped: list[dict[str, str]] = []
    blocks_parsed = 0
    tags_parsed = 0

    for i, row in enumerate(parsed_rows, start=1):
        if i == 1 or i == total or i % 5 == 0:
            on_progress(
                "parse",
                f"解析 SimaticML（{i}/{total}）…",
                current=i,
                total=total,
            )
        kind = row.get("kind")
        if kind == "block":
            block = row["block"]
            su = row.get("software_unit", "")
            role = _infer_af_role(block.name, su)
            key = f"{su}::{block.name}" if su else block.name
            canvas.blocks[key] = _block_to_canvas_block(
                block, canvas.blocks, software_unit=su, af_role=role
            )
            blocks_parsed += 1
            continue
        if kind == "tags":
            table = row["table"]
            for tag in table.tags:
                canvas.tags[tag.name] = CanvasTag(
                    name=tag.name,
                    data_type=tag.data_type,
                    logical_address=tag.logical_address,
                    comment=tag.comment,
                )
            tags_parsed += len(table.tags)
            continue
        skipped.append({"file": str(row["file"]), "reason": str(row.get("reason") or "")})

    # Scan for unit_manifest.json files under units/
    try:
        import json
        units_dir = parse_root / "units" if parse_root.is_dir() else None
        if units_dir and units_dir.is_dir():
            for m_file in units_dir.glob("*/unit_manifest.json"):
                try:
                    data = json.loads(m_file.read_text(encoding="utf-8"))
                    uname = data.get("name") or m_file.parent.name
                    canvas.software_unit_manifests[uname] = data
                except Exception:
                    pass
    except Exception:
        pass

    # HMI screens (classic XML / Unified JSON) under hmi/
    hmi_count = 0
    try:
        on_progress("hmi_parse", "解析 HMI 画面…")
        from agents.plc.tia.hmi_screens import parse_hmi_export_tree

        devices, widgets = parse_hmi_export_tree(parse_root)
        canvas.hmi_devices = devices
        canvas.hmi_widgets.update(widgets)
        hmi_count = len(widgets)
        on_progress("hmi_parse", f"HMI：{len(devices)} 设备 · {hmi_count} 控件")
    except Exception as exc:  # noqa: BLE001
        on_progress("hmi_parse", f"HMI 解析跳过：{exc}")

    if blocks_parsed == 0 and tags_parsed == 0 and hmi_count == 0:
        raise CanvasImportRejected(
            "NO_PARSEABLE_FILES",
            f"路径中没有可解析的 SimaticML 块/标签表 XML：{parse_root}",
        )

    on_progress(
        "done",
        f"导入完成：{blocks_parsed} 块 · {tags_parsed} 标签 · {hmi_count} HMI 控件",
        blocks_parsed=blocks_parsed,
        tags_parsed=tags_parsed,
        hmi_parsed=hmi_count,
    )
    return {
        "canvas": canvas.to_dict(),
        "blocks_parsed": blocks_parsed,
        "tags_parsed": tags_parsed,
        "hmi_parsed": hmi_count,
        "skipped": skipped,
        "_export_root": str(parse_root),
    }


def import_canvas_from_path(
    resolved: Path,
    project_name: str = "",
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Import a TIA export or archive onto a canvas.

    Accepts a SimaticML ``.xml`` file, an Openness export directory, a
    ``.zap``/``.zap15``-``.zap20``/``.zip`` archive (SimaticML XML exports or a
    full TIA project tree), a directory containing a complete ``.ap17-.ap20``
    project (routed through the Openness CLI), or a bare ``.apxx`` file.

    Returns ``{"canvas": CanvasState.to_dict(), "blocks_parsed": int,
    "tags_parsed": int, "hmi_parsed": int, "skipped": [...],
    "af_analysis": {conformant, roles_count, pending_count}}``.
    Imported blocks/networks/HMI carry status="synced". When an .apxx tree is
    available it is persisted under PLC_WORK_DIR/projects/<id> and
    ``canvas.source`` is filled for real writeback paths. On success the canvas
    additionally gets the AF role overlay (af_role annotation only — physical
    layout/SCL/interfaces/tags/OB untouched; AF analysis failure falls back to
    ``af_analysis={conformant: null, ...}`` without blocking the import).
    """
    progress = on_progress or _noop_progress
    resolved = Path(resolved)
    name = (project_name or "").strip()
    suffix = resolved.suffix.lower()
    progress("start", f"开始导入 {resolved.name}…")

    result: dict[str, Any]
    apxx_for_workspace: Path | None = None

    if resolved.is_file():
        if suffix in ZAP_SUFFIXES:
            result = _import_archive(resolved, name or resolved.stem, on_progress=progress)
            # Best-effort: locate complete apxx from a side extract for workspace
            apxx_for_workspace = _try_find_apxx_from_archive(resolved)
        elif suffix in APXX_SUFFIXES:
            from agents.plc.tia.importer import incomplete_apxx_guidance

            try:
                tmp_root = _openness_export_to_tempdir(resolved, on_progress=progress)
            except CanvasImportRejected as exc:
                raise CanvasImportRejected(
                    exc.code, f"{exc.message}\n\n{incomplete_apxx_guidance(resolved)}"
                ) from None
            try:
                result = _parse_export_tree(
                    tmp_root / "export", name or resolved.stem, on_progress=progress
                )
            finally:
                shutil.rmtree(tmp_root, ignore_errors=True)
            apxx_for_workspace = resolved
        else:
            result = _parse_export_tree(resolved, name or resolved.stem, on_progress=progress)
    else:
        result = _import_directory(resolved, name or resolved.name, on_progress=progress)
        complete, _ = _find_complete_apxx(resolved)
        apxx_for_workspace = complete

    # Persist engineering workspace for 1:1 writeback
    if apxx_for_workspace is not None:
        try:
            progress("workspace", "持久化工程工作区…")
            from gateway.app.services.plc import workspace as ws

            meta = ws.persist_imported_project(
                apxx_for_workspace,
                project_name=name or apxx_for_workspace.stem,
            )
            canvas_dict = result.get("canvas") or {}
            canvas = CanvasState.from_dict(canvas_dict)
            canvas.source = CanvasSource(
                project_id=str(meta["project_id"]),
                project_path=str(meta.get("project_path") or ""),
                plc_name="",
                hmi_device_names=[d.name for d in canvas.hmi_devices],
                export_mode="canvas",
            )
            # Save HMI baselines for classic patch writeback
            export_root = result.pop("_export_root", None)
            if export_root:
                hmi_src = Path(export_root) / "hmi"
                if hmi_src.is_dir():
                    baseline_hmi = Path(str(meta["baseline_path"])) / "hmi"
                    if baseline_hmi.exists():
                        shutil.rmtree(baseline_hmi, ignore_errors=True)
                    shutil.copytree(hmi_src, baseline_hmi, dirs_exist_ok=True)
            result["canvas"] = canvas.to_dict()
            result["workspace"] = meta
            progress("workspace", f"工作区已就绪：{meta['project_id']}")
        except Exception as exc:  # noqa: BLE001
            progress("workspace", f"工作区持久化跳过：{exc}")
    else:
        result.pop("_export_root", None)

    # AF 角色覆盖层(导入自动 AF 化,契约 docs/23 §2):分析→标注→报告→PCEC。
    # 物理冻结铁律:overlay 只加 af_role 与 pending 文案,SCL/接口/标签/OB 一字不动;
    # 任何失败仅提示,绝不阻塞导入(响应摘要兜底 conformant=null)。
    result["af_analysis"] = {
        "conformant": None,
        "roles_count": 0,
        "pending_count": 0,
    }
    try:
        from gateway.app.services.plc import af_import

        af_canvas = CanvasState.from_dict(result.get("canvas") or {})
        if af_canvas.blocks or af_canvas.tags:
            af_report = af_import.analyze_import(af_canvas)
            af_canvas = af_import.apply_af_overlay(af_canvas, af_report)
            result["canvas"] = af_canvas.to_dict()
            af_project_path = ""
            if af_canvas.source is not None:
                af_project_path = str(af_canvas.source.project_path or "")
            af_import.write_report(
                af_canvas.project_name or name or resolved.stem, af_report
            )
            af_import.record_pcec(af_canvas, af_report, af_project_path or None)
            result["af_analysis"] = af_import.summarize(af_report)
    except Exception as exc:  # noqa: BLE001 — AF 失败绝不阻塞导入
        progress("af_import", f"AF 角色标注跳过:{exc}")

    return result


def _try_find_apxx_from_archive(archive: Path) -> Path | None:
    """Unpack briefly to find a complete .apxx for workspace persistence."""
    from agents.plc.tia.importer import extract_tia_archive

    extract_root = Path(tempfile.mkdtemp(prefix="canvas_ws_probe_"))
    try:
        extracted = extract_tia_archive(archive, dest=extract_root)
        check_root = extracted if extracted.is_dir() else extracted.parent
        complete, _ = _find_complete_apxx(check_root)
        if complete is None:
            return None
        # Copy apxx (+ sibling) out of temp before cleanup — persist_imported_project copies again
        stable = Path(tempfile.mkdtemp(prefix="canvas_apxx_stable_")) / complete.name
        shutil.copy2(complete, stable)
        sibling = complete.parent / complete.stem
        if sibling.is_dir():
            shutil.copytree(sibling, stable.parent / sibling.name, dirs_exist_ok=True)
        return stable
    except Exception:  # noqa: BLE001
        return None
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)
