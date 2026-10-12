"""Result package writer — ResearchOS_PLC_Result layout.

Matches docs/agents/PLC Offline Analyzer Architecture.md §11–12:

ResearchOS_PLC_Result/
  converted_scl/
  plc_ir/
  knowledge_graph/
  reports/
  original/protected_blocks/   (placeholders for know-how protected units)
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from agents.plc.tia.ir import Block, PlcProject
from agents.plc.tia.kg import PlcKnowledgeGraph


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def classify_block(block: Block, scl_source: str | None) -> dict[str, Any]:
    """Assign Offline Analyzer status: parsed | converted | protected | interface_only | unknown."""
    lang = (block.programming_language or "").upper()
    has_logic = bool(block.networks) or bool(block.source_text)
    has_todo = bool(scl_source and "TODO[" in scl_source)

    if block.is_interface_only():
        status = "interface_only"
        convert = False
        reason = (
            "Program body not exported (typical Know-how / library lock); "
            "Input/Output/Static interface parsed for project understanding"
            + (" (KnowHowProtection marked)" if block.is_protected() else "")
        )
    elif block.is_protected():
        status = "protected"
        convert = False
        reason = (
            "Know-how / password protection — program body unavailable; "
            "open interface kept for call-graph / I/O understanding"
            if block.interface
            else "Know-how / password protection — original kept, no SCL conversion"
        )
    elif not has_logic and block.block_type.value not in {"DB", "UDT"}:
        status = "unknown"
        convert = False
        reason = "No networks or source text extracted"
    elif scl_source and not has_todo:
        status = "converted"
        convert = True
        reason = ""
    elif scl_source and has_todo:
        status = "parsed"
        convert = True
        reason = "Partial conversion; TODO markers remain for review"
    else:
        status = "unknown"
        convert = False
        reason = "SCL not generated"

    return {
        "block": block.name,
        "type": block.block_type.value,
        "language": lang or "UNKNOWN",
        "status": status,
        "convert": convert,
        "reason": reason,
        "networks": len(block.networks),
        "interface_members": len(block.interface),
        "source_file": block.source_file,
    }


def build_conversion_report(
    project: PlcProject, scl_sources: dict[str, str]
) -> dict[str, Any]:
    blocks = [
        classify_block(block, scl_sources.get(name))
        for name, block in project.blocks.items()
    ]
    counts = {
        "total_blocks": len(blocks),
        "converted": sum(1 for b in blocks if b["status"] == "converted"),
        "parsed": sum(1 for b in blocks if b["status"] == "parsed"),
        "protected": sum(1 for b in blocks if b["status"] == "protected"),
        "interface_only": sum(1 for b in blocks if b["status"] == "interface_only"),
        "failed": sum(1 for b in blocks if b["status"] == "unknown"),
        "tag_tables": len(project.tag_tables),
    }
    return {
        **counts,
        "project_name": project.name,
        "source_path": project.source_path,
        "blocks": blocks,
        "extraction_notes": list(project.extraction_notes),
    }


def write_result_package(
    result_dir: str | Path,
    *,
    project: PlcProject,
    knowledge_graph: PlcKnowledgeGraph,
    scl_sources: dict[str, str],
    report_md: str,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the Offline Analyzer output package; return conversion_report."""
    root = Path(result_dir)
    converted = root / "converted_scl"
    plc_ir = root / "plc_ir"
    kg_dir = root / "knowledge_graph"
    reports = root / "reports"
    protected = root / "original" / "protected_blocks"
    for d in (converted, plc_ir, kg_dir, reports, protected):
        d.mkdir(parents=True, exist_ok=True)

    conversion = build_conversion_report(project, scl_sources)

    for name, source in scl_sources.items():
        (converted / f"{_safe_filename(name)}.scl").write_text(source, encoding="utf-8")

    for entry in conversion["blocks"]:
        if entry["status"] not in {"protected", "interface_only"}:
            continue
        block = project.blocks.get(entry["block"])
        dest_base = protected / _safe_filename(entry["block"])
        stub = (
            f"(* {entry['status']} block {entry['block']} — "
            f"interface retained for understanding; body not converted. "
            f"Reason: {entry['reason']} *)\n"
        )
        (dest_base.with_suffix(".txt")).write_text(stub, encoding="utf-8")
        src = Path(block.source_file) if block and block.source_file else None
        if src and src.is_file():
            shutil.copy2(src, dest_base.with_suffix(src.suffix or ".xml"))

    (plc_ir / "project.json").write_text(
        json.dumps(_to_jsonable(project), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (kg_dir / "graph.json").write_text(
        json.dumps(knowledge_graph.to_json(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (reports / "analysis.md").write_text(report_md, encoding="utf-8")
    (reports / "conversion_report.json").write_text(
        json.dumps(conversion, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    from agents.plc.tia.coverage import build_coverage_report, coverage_markdown
    from agents.plc.tia.structure import build_structure_inventory, structure_summary

    coverage = build_coverage_report(
        project, scl_sources, timings=(extra_meta or {}).get("timings")
    )
    structure = (extra_meta or {}).get("structure") or build_structure_inventory(
        project, knowledge_graph=knowledge_graph
    )
    coverage["structure"] = (extra_meta or {}).get("structure_summary") or structure_summary(
        structure
    )
    (reports / "coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (reports / "coverage.md").write_text(coverage_markdown(coverage), encoding="utf-8")
    (reports / "structure.json").write_text(
        json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    meta = {
        "project_name": project.name,
        "source_path": project.source_path,
        "result_dir": str(root.resolve()),
        **(extra_meta or {}),
        "conversion_summary": {
            k: conversion[k]
            for k in (
                "total_blocks",
                "converted",
                "parsed",
                "protected",
                "interface_only",
                "failed",
                "tag_tables",
            )
            if k in conversion
        },
        "coverage_summary": {
            k: coverage[k]
            for k in (
                "todo_rate",
                "todo_count",
                "converted",
                "parsed",
                "protected",
                "interface_only",
                "safety_block_count",
            )
            if k in coverage
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return conversion
