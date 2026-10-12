"""PLC Offline Analyzer pipeline orchestration.

User contract (docs/agents/PLC Offline Analyzer Architecture.md):

    .apxx | export dir
           |
    importer (Openness if .apxx)
           |
    SimaticML extract -> PLC-IR
           |
    Knowledge Graph + SCL + logic report
           |
    ResearchOS_PLC_Result package
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.plc.tia.importer import resolve_project_input
from agents.plc.tia.flgnet_fold import attach_folded, fold_project
from agents.plc.tia.ir import BlockType, PlcProject
from agents.plc.tia.kg import PlcKnowledgeGraph, build_knowledge_graph
from agents.plc.tia.package import build_conversion_report, write_result_package
from agents.plc.tia.scl import convert_project_to_scl
from agents.plc.tia.simaticml import extract_project
from agents.plc.tia.timings import merge_timings, timed_step


def analyze_tia_exports(
    export_dir: str,
    *,
    project_name: str = "",
    publish_graph: bool = False,
    project: PlcProject | None = None,
    on_structure: Any | None = None,
) -> dict[str, Any]:
    """Offline path: parse Openness exports, build KG, convert to SCL.

    When `publish_graph=True`, also upsert PLC nodes/edges into the configured
    KnowledgeGraph backend (Neo4j if NEO4J_* is set, else in-memory).

    Pass a pre-parsed ``project`` (journal overlap / cache-hit extract) to skip
    a second XML walk. KG still waits until every block is present.

    ``on_structure(project, kg)`` fires after the call graph exists and **before**
    full SCL/LAD body conversion, so a Project Brief can be served first.
    """
    timings: dict[str, int] = {}
    if project is None:
        with timed_step(timings, "extract_ms"):
            project = extract_project(export_dir, project_name=project_name)
    else:
        timings["extract_ms"] = 0
        timings["extract_overlapped"] = 1
    from agents.plc.tia.safety import apply_safety_flags

    apply_safety_flags(project)
    with timed_step(timings, "fold_attach_ms"):
        project = attach_folded(project)
    with timed_step(timings, "kg_ms"):
        kg = build_knowledge_graph(project)
    if callable(on_structure):
        with timed_step(timings, "structure_ms"):
            on_structure(project, kg)
    with timed_step(timings, "scl_ms"):
        scl_sources = convert_project_to_scl(project)
    with timed_step(timings, "report_ms"):
        report = interpretation_report(project, kg)
        conversion = build_conversion_report(project, scl_sources)
    with timed_step(timings, "fold_serialize_ms"):
        folded = fold_project(project)
    from agents.plc.tia.coverage import build_coverage_report
    from agents.plc.tia.structure import build_structure_inventory, structure_summary

    coverage = build_coverage_report(project, scl_sources, timings=timings)
    structure = build_structure_inventory(project, knowledge_graph=kg)
    coverage["structure"] = structure_summary(structure)
    result: dict[str, Any] = {
        "project": project,
        "folded_logic": folded,
        "knowledge_graph": kg,
        "scl_sources": scl_sources,
        "report": report,
        "conversion_report": conversion,
        "coverage": coverage,
        "structure": structure,
        "timings": timings,
    }
    if publish_graph:
        from agents.plc.tia.neo4j_publish import publish_plc_knowledge_graph

        with timed_step(timings, "neo4j_ms"):
            result["graph_publish"] = publish_plc_knowledge_graph(
                kg, project_name=project.name or project_name or "plc_project"
            )
    return result


def analyze_plc_project(
    path: str,
    *,
    project_name: str = "",
    result_dir: str = "",
    export_dir: str = "",
    tia_version: str = "",
    plc_name: str = "",
    auto_export: bool = True,
    publish_graph: bool = False,
) -> dict[str, Any]:
    """One-shot: accept .apxx / .xml / export folder → parse → understand → SCL package.

    `.apxx` requires TIA Portal Openness on this host (C# CLI or PowerShell adapter).
    Export folders and single SimaticML `.xml` files are fully offline.
    """
    timings: dict[str, int] = {}
    with timed_step(timings, "resolve_wall_ms"):
        imported = resolve_project_input(
            path,
            export_dir=export_dir or None,
            tia_version=tia_version,
            plc_name=plc_name,
            auto_export=auto_export,
        )
    # Fine-grained import steps (unzip / stage / openness) — not added into resolve_wall_ms
    timings = merge_timings(timings, imported.timings)

    name = project_name or (
        imported.project_path.stem if imported.project_path else imported.export_dir.name
    )
    analyzed = analyze_tia_exports(
        str(imported.export_dir),
        project_name=name,
        publish_graph=publish_graph,
        project=imported.project if isinstance(imported.project, PlcProject) else None,
    )
    timings = merge_timings(timings, analyzed.get("timings"))
    project: PlcProject = analyzed["project"]
    for note in imported.notes or []:
        project.extraction_notes.append(note)
    if imported.tia_version:
        project.tia_version = imported.tia_version
    if imported.project_path:
        project.source_path = str(imported.project_path)

    # Refresh report/conversion after notes mutation
    with timed_step(timings, "report_refresh_ms"):
        analyzed["report"] = interpretation_report(project, analyzed["knowledge_graph"])
        analyzed["conversion_report"] = build_conversion_report(
            project, analyzed["scl_sources"]
        )

    package_root = ""
    if result_dir:
        with timed_step(timings, "package_ms"):
            conversion = write_result_package(
                result_dir,
                project=project,
                knowledge_graph=analyzed["knowledge_graph"],
                scl_sources=analyzed["scl_sources"],
                report_md=analyzed["report"],
                extra_meta={
                    "source_kind": imported.source_kind,
                    "export_dir": str(imported.export_dir),
                    "tia_version": imported.tia_version,
                    "timings": timings,
                },
            )
        analyzed["conversion_report"] = conversion
        package_root = str(Path(result_dir).resolve())

    from agents.plc.tia.coverage import build_coverage_report

    analyzed["coverage"] = build_coverage_report(
        project, analyzed["scl_sources"], timings=timings
    )

    analyzed["import"] = {
        "source_kind": imported.source_kind,
        "export_dir": str(imported.export_dir),
        "project_path": str(imported.project_path) if imported.project_path else "",
        "tia_version": imported.tia_version,
        "timings": dict(imported.timings or {}),
    }
    analyzed["result_dir"] = package_root
    analyzed["timings"] = timings
    return analyzed


def interpretation_report(project: PlcProject, kg: PlcKnowledgeGraph) -> str:
    """Human/LLM-readable summary explaining the parsed project (logic understanding)."""
    lines: list[str] = []
    lines.append(f"# TIA Project Interpretation: {project.name}")
    lines.append("")

    summary = project.summary()
    lines.append("## Overview")
    lines.append(
        f"- Blocks: {summary.get('FB', 0)} FB / {summary.get('FC', 0)} FC / "
        f"{summary.get('OB', 0)} OB / {summary.get('DB', 0)} DB / {summary.get('UDT', 0)} UDT"
    )
    lines.append(
        f"- Tag tables: {summary.get('TagTables', 0)}, Networks: {summary.get('Networks', 0)}"
    )
    if project.source_path:
        lines.append(f"- Source: `{project.source_path}`")
    if project.tia_version:
        lines.append(f"- TIA version hint: {project.tia_version}")
    if project.extraction_notes:
        lines.append("- Extraction notes:")
        lines.extend(f"  - {note}" for note in project.extraction_notes)
    lines.append("")

    lines.append("## Program Architecture")
    for block in project.blocks.values():
        title = f"- **{block.block_type.value} {block.name}**"
        if block.number:
            title += f" ({block.block_type.value}{block.number})"
        if block.programming_language:
            title += f" [{block.programming_language}]"
        if block.header_comment:
            title += f" — {block.header_comment}"
        lines.append(title)
        callees = kg.callees_of(block.name)
        if callees:
            lines.append(f"  - Calls: {', '.join(callees)}")
        if block.block_type == BlockType.FB:
            instances = sorted(
                e.source.split("::")[1]
                for e in kg.in_edges(f"Block::{block.name}", "INSTANCE_OF")
                if "::" in e.source
            )
            if instances:
                lines.append(f"  - Instances: {', '.join(instances)}")
    lines.append("")

    tag_reads: dict[str, set[str]] = {}
    tag_writes: dict[str, set[str]] = {}
    for edge in kg.edges:
        if edge.type == "READS" and edge.target.startswith("Tag::"):
            tag_reads.setdefault(edge.target[5:], set()).add(
                edge.source.split("::", 1)[1] if "::" in edge.source else edge.source
            )
        elif edge.type == "WRITES" and edge.target.startswith("Tag::"):
            tag_writes.setdefault(edge.target[5:], set()).add(
                edge.source.split("::", 1)[1] if "::" in edge.source else edge.source
            )
    if tag_reads or tag_writes:
        lines.append("## Signal Flow (logic understanding)")
        for ref in sorted(set(tag_reads) | set(tag_writes)):
            readers = sorted(tag_reads.get(ref, set()))
            writers = sorted(tag_writes.get(ref, set()))
            lines.append(
                f"- `{ref}` — read by {', '.join(readers) or '-'}; "
                f"written by {', '.join(writers) or '-'}"
            )
        lines.append("")

    lines.append("## Conversion Notes")
    lines.append("- SCL is an importable External Source artifact (HITL review required).")
    lines.append(
        "- Writeback path (Windows HostGateway): External Source (.scl) → "
        "PlcSoftware.ExternalSourceGroup.ExternalSources.CreateFromFile → "
        "GenerateBlocksFromSource(); then ICompilable.Compile() before Archive."
    )
    lines.append("- Linux Docker can stage .scl packages; it cannot run Openness import/compile.")
    lines.append("- Untranslated instructions are marked with `(* TODO[...] *)` comments.")
    lines.append("- Protected / Safety / interface-only blocks are listed in conversion_report.json.")
    return "\n".join(lines)
