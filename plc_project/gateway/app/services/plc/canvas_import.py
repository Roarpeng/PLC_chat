"""TIA Portal Openness export -> interactive Canvas import service.

Parses SimaticML XML (a single block/tag-table file, or a whole Openness
export directory — ``Blocks/`` / ``TagTables/`` subtrees or flat layouts)
into a ``CanvasState`` payload that the interactive canvas endpoints
(/canvas/patch, /canvas/to-scl, /canvas/confirm-writeback) can consume.

100% offline for XML inputs: LAD/FBD networks are summarized by their
referenced symbols; SCL networks keep the reconstructed StructuredText
produced by the SimaticML parser. ``.zap``/``.zap15``-``.zap20``/``.zip``
archives and directories holding a complete ``.ap17-.ap20`` project tree are
unpacked and classified first: SimaticML XML parses offline, complete TIA
projects go through the Openness CLI export when that host is available, and
everything else is rejected with ``OPENNESS_EXPORT_REQUIRED`` /
``NO_PARSEABLE_FILES`` guidance.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from agents.plc.tia.simaticml import parse_block_xml, parse_tag_table_xml
from plc_engine.canvas_model import (
    CanvasBlock,
    CanvasNetwork,
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


class CanvasImportRejected(ValueError):
    """Import rejected before any canvas mutation; the router maps it to HTTP 400."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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


def _block_to_canvas_block(block: Any, existing: dict[str, CanvasBlock]) -> CanvasBlock:
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

    networks: list[CanvasNetwork] = []
    for index, net in enumerate(block.networks):
        scl_text = (net.source_text or "").strip()
        if not scl_text:
            symbols = _referenced_symbols(net)
            listed = ", ".join(symbols) if symbols else "无"
            scl_text = f"// 图形网络（LAD/FBD），引用符号：{listed}"
        networks.append(
            CanvasNetwork(
                id=_network_id(net.id, index),
                title=(net.title or "").strip(),
                language=(net.programming_language or "").strip() or language or "LAD",
                scl_text=scl_text,
                status="synced",
            )
        )

    return CanvasBlock(
        name=block.name,
        block_type=block_type,
        number=number,
        language=language,
        comment=(block.header_comment or "").strip(),
        interface=interface,
        networks=networks,
        scl_body=(block.source_text or "").strip(),
        status="synced",
    )


def _openness_export_to_tempdir(apxx_path: Path) -> Path:
    """Run the Openness CLI export into a fresh temp dir and return the temp root.

    Raises ``CanvasImportRejected("OPENNESS_EXPORT_REQUIRED")`` when the C#
    Openness host is unavailable or the export fails, so the router can answer
    400 with manual-export guidance instead of a 5xx.
    """
    from agents.plc.tia.openness_cli import export_project_via_openness_cli

    tmp_root = Path(tempfile.mkdtemp(prefix="canvas_openness_export_"))
    try:
        export_project_via_openness_cli(apxx_path, export_dir=tmp_root / "export")
    except (FileNotFoundError, RuntimeError) as exc:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise CanvasImportRejected(
            "OPENNESS_EXPORT_REQUIRED",
            f"{OPENNESS_EXPORT_REQUIRED_MESSAGE}（Openness 导出失败：{exc}）",
        ) from exc
    return tmp_root


def _import_via_openness(apxx_path: Path, project_name: str) -> dict[str, Any]:
    """Export ``apxx_path`` through Openness into a temp dir and parse the result."""
    tmp_root = _openness_export_to_tempdir(apxx_path)
    try:
        return _parse_export_tree(tmp_root / "export", project_name)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _find_complete_apxx(root: Path) -> tuple[Path | None, list[Path]]:
    """Return the first complete TIA project file under ``root`` plus all .apxx found."""
    from agents.plc.tia.importer import find_apxx_files, is_complete_tia_project

    apxx_files = find_apxx_files(root)
    complete = next((ap for ap in apxx_files if is_complete_tia_project(ap)), None)
    return complete, apxx_files


def _import_archive(archive: Path, project_name: str) -> dict[str, Any]:
    """Unpack a .zap*/.zip archive into a temp dir and import whatever is inside.

    SimaticML XML exports parse offline; a complete ``.ap17-.ap20`` project
    tree goes through the Openness CLI; a bare/incomplete ``.apxx`` is
    rejected with packaging guidance.
    """
    from agents.plc.tia.importer import extract_tia_archive, has_simaticml_exports

    extract_root = Path(tempfile.mkdtemp(prefix="canvas_zap_extract_"))
    try:
        try:
            extracted = extract_tia_archive(archive, dest=extract_root)
        except ValueError as exc:  # corrupt / non-ZIP .zap* — surface as 400, not 500
            raise CanvasImportRejected("NO_PARSEABLE_FILES", str(exc)) from exc
        check_root = extracted if extracted.is_dir() else extracted.parent
        if has_simaticml_exports(check_root):
            return _parse_export_tree(check_root, project_name)
        complete, apxx_files = _find_complete_apxx(check_root)
        if complete is not None:
            return _import_via_openness(complete, project_name)
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


def _import_directory(directory: Path, project_name: str) -> dict[str, Any]:
    """Import a directory: SimaticML export XML, or a full TIA project tree via Openness."""
    from agents.plc.tia.importer import has_simaticml_exports

    if not has_simaticml_exports(directory):
        complete, apxx_files = _find_complete_apxx(directory)
        if complete is not None:
            # A .zap-unpacked project folder — same treatment as ingest.
            return _import_via_openness(complete, project_name)
        if apxx_files:
            from agents.plc.tia.importer import incomplete_apxx_guidance

            raise CanvasImportRejected(
                "OPENNESS_EXPORT_REQUIRED", incomplete_apxx_guidance(apxx_files[0])
            )
    return _parse_export_tree(directory, project_name)


def _parse_export_tree(parse_root: Path, project_name: str) -> dict[str, Any]:
    if parse_root.is_file():
        xml_files = [parse_root]
    else:
        xml_files = sorted(p for p in parse_root.rglob("*.xml") if p.is_file())

    canvas = CanvasState(project_name=project_name)
    skipped: list[dict[str, str]] = []
    blocks_parsed = 0
    tags_parsed = 0

    for xml_file in xml_files:
        reason = ""
        try:
            block = parse_block_xml(xml_file)
        except Exception as exc:  # noqa: BLE001 — one bad file must not kill the import
            block = None
            reason = f"块 XML 解析失败：{exc}"
        if block is not None and block.name:
            canvas.blocks[block.name] = _block_to_canvas_block(block, canvas.blocks)
            blocks_parsed += 1
            continue

        try:
            table = parse_tag_table_xml(xml_file)
        except Exception as exc:  # noqa: BLE001 — advisory, fall through to skipped
            table = None
            reason = reason or f"标签表解析失败：{exc}"
        if table is not None and table.tags:
            for tag in table.tags:
                canvas.tags[tag.name] = CanvasTag(
                    name=tag.name,
                    data_type=tag.data_type,
                    logical_address=tag.logical_address,
                    comment=tag.comment,
                )
            tags_parsed += len(table.tags)
            continue
        if table is not None:
            reason = reason or "空标签表（无 SW.Tags.PlcTag）"

        skipped.append(
            {"file": str(xml_file), "reason": reason or "非 SW.Blocks.* 块或 SW.Tags.PlcTagTable 标签表导出"}
        )

    if blocks_parsed == 0 and tags_parsed == 0:
        raise CanvasImportRejected(
            "NO_PARSEABLE_FILES",
            f"路径中没有可解析的 SimaticML 块/标签表 XML：{parse_root}",
        )

    return {
        "canvas": canvas.to_dict(),
        "blocks_parsed": blocks_parsed,
        "tags_parsed": tags_parsed,
        "skipped": skipped,
    }


def import_canvas_from_path(resolved: Path, project_name: str = "") -> dict[str, Any]:
    """Import a TIA export or archive onto a canvas.

    Accepts a SimaticML ``.xml`` file, an Openness export directory, a
    ``.zap``/``.zap15``-``.zap20``/``.zip`` archive (SimaticML XML exports or a
    full TIA project tree), a directory containing a complete ``.ap17-.ap20``
    project (routed through the Openness CLI), or a bare ``.apxx`` file.

    Returns ``{"canvas": CanvasState.to_dict(), "blocks_parsed": int,
    "tags_parsed": int, "skipped": [{"file": str, "reason": str}]}``.
    Imported blocks/networks carry status="synced"; HMI widgets start empty.
    """
    resolved = Path(resolved)
    name = (project_name or "").strip()
    suffix = resolved.suffix.lower()

    if resolved.is_file():
        if suffix in ZAP_SUFFIXES:
            return _import_archive(resolved, name or resolved.stem)
        if suffix in APXX_SUFFIXES:
            from agents.plc.tia.importer import incomplete_apxx_guidance

            try:
                tmp_root = _openness_export_to_tempdir(resolved)
            except CanvasImportRejected as exc:
                # A lone .apxx can never satisfy Projects.Open — point at .zap/XML.
                raise CanvasImportRejected(
                    exc.code, f"{exc.message}\n\n{incomplete_apxx_guidance(resolved)}"
                ) from None
            try:
                return _parse_export_tree(tmp_root / "export", name or resolved.stem)
            finally:
                shutil.rmtree(tmp_root, ignore_errors=True)
        return _parse_export_tree(resolved, name or resolved.stem)

    return _import_directory(resolved, name or resolved.name)
