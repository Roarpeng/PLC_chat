"""Honest conversion coverage — every block, every leftover TODO named."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from agents.plc.tia.ir import Block, BlockType, PlcProject
from agents.plc.tia.package import build_conversion_report, classify_block
from agents.plc.tia.surface import OFFICIAL_CATEGORIES

_TODO_RE = re.compile(r"TODO\[([^\]]+)\]")

_SKIP_REASONS = (
    "know_how",
    "inconsistent",
    "no_license",
    "no_export",
    "no_import",
    "password_protected",
    "safety_login",
    "openness_error",
)


def _empty_category() -> dict[str, Any]:
    return {
        "exported": 0,
        "parsed": 0,
        "skipped": 0,
        "skipped_reasons": [],
    }


def build_category_coverage(project: PlcProject) -> dict[str, Any]:
    """Official Openness chapter-6 categories: exported vs parsed vs skipped+reason."""
    cats = {name: _empty_category() for name in OFFICIAL_CATEGORIES}
    udt = [b for b in project.blocks.values() if b.block_type == BlockType.UDT]
    prog = [b for b in project.blocks.values() if b.block_type != BlockType.UDT]
    cats["blocks"]["parsed"] = len(prog)
    cats["types"]["parsed"] = len(udt)
    cats["tags"]["parsed"] = len(project.tag_tables)
    cats["watch"]["parsed"] = len(getattr(project, "watch_tables", {}) or {})
    cats["force"]["parsed"] = len(getattr(project, "force_tables", {}) or {})
    cats["to"]["parsed"] = len(getattr(project, "technology_objects", None) or [])
    cats["alarms"]["parsed"] = len(getattr(project, "alarms", None) or []) + len(
        getattr(project, "prodiag", None) or []
    )
    cats["cfc"]["parsed"] = len(getattr(project, "cfc_charts", None) or [])
    cats["safety"]["parsed"] = len(getattr(project, "safety_units", None) or [])
    cats["hardware"]["parsed"] = len(getattr(project, "hardware", None) or [])
    cats["hmi"]["parsed"] = len(getattr(project, "hmi_devices", None) or [])
    cats["opcua"]["parsed"] = len(getattr(project, "opcua_nodes", None) or [])
    cats["project"]["parsed"] = 1 if getattr(project, "project_texts", None) else 0

    manifest = getattr(project, "export_manifest", None) or {}
    counts = manifest.get("counts") if isinstance(manifest, dict) else None
    if isinstance(counts, dict):
        for name, row in counts.items():
            key = str(name).lower()
            if key not in cats or not isinstance(row, dict):
                continue
            cats[key]["exported"] = int(row.get("exported") or 0)
            cats[key]["skipped"] = int(row.get("skipped") or 0)
    else:
        for row in cats.values():
            row["exported"] = row["parsed"]

    skipped = manifest.get("skipped") if isinstance(manifest, dict) else None
    if isinstance(skipped, list):
        for item in skipped:
            if not isinstance(item, dict):
                continue
            key = str(item.get("category") or "").lower()
            if key not in cats:
                continue
            reason = str(item.get("reason") or "openness_error")
            if reason not in _SKIP_REASONS:
                reason = "openness_error"
            cats[key]["skipped_reasons"].append(
                {
                    "name": item.get("name") or "",
                    "reason": reason,
                    "detail": item.get("detail") or item.get("message") or "",
                }
            )
            if not counts:
                cats[key]["skipped"] = len(cats[key]["skipped_reasons"])

    for name, row in cats.items():
        if row["exported"] == 0 and row["parsed"] == 0 and not row["skipped_reasons"]:
            row["skipped"] = max(int(row["skipped"] or 0), 1)
            row["skipped_reasons"].append(
                {
                    "name": name,
                    "reason": "no_export",
                    "detail": (
                        "no objects exported or parsed for this category "
                        "(composition empty, API absent, or not in this export)"
                    ),
                }
            )
        elif int(row["exported"] or 0) > 0 and int(row["parsed"] or 0) == 0 and not row["skipped_reasons"]:
            row["skipped_reasons"].append(
                {
                    "name": name,
                    "reason": "openness_error",
                    "detail": "exported XML present but parser produced no IR",
                }
            )
    return cats


def _language_of(block: Block) -> str:
    lang = (block.programming_language or "").strip() or "UNKNOWN"
    if getattr(block, "is_safety", False) and not lang.upper().startswith("F"):
        return f"F-{lang}" if lang != "UNKNOWN" else "F"
    return lang


def _todo_names_from_scl(scl: str) -> list[str]:
    return _TODO_RE.findall(scl or "")


def _instruction_count(block: Block) -> int:
    n = 0
    for network in block.networks:
        n += len(network.parts)
        if network.source_text:
            n += sum(1 for line in network.source_text.splitlines() if line.strip())
        n += len(getattr(network, "graph_steps", None) or [])
        n += len(getattr(network, "graph_transitions", None) or [])
    if not block.networks and block.source_text:
        n += sum(1 for line in block.source_text.splitlines() if line.strip())
    return n


def build_coverage_report(
    project: PlcProject,
    scl_sources: dict[str, str],
    *,
    timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Machine-readable coverage for a Siemens engineer review."""
    conversion = build_conversion_report(project, scl_sources)
    language_hist: Counter[str] = Counter()
    part_hist: Counter[str] = Counter()
    todo_hist: Counter[str] = Counter()
    todo_total = 0
    instruction_total = 0
    per_block: list[dict[str, Any]] = []

    classified = {row["block"]: row for row in conversion["blocks"]}
    for name, block in project.blocks.items():
        lang = _language_of(block)
        language_hist[lang] += 1
        scl = scl_sources.get(name) or ""
        todos = _todo_names_from_scl(scl)
        todo_total += len(todos)
        todo_hist.update(todos)
        inst = _instruction_count(block)
        instruction_total += inst
        for network in block.networks:
            for part in network.parts.values():
                pname = (part.name or part.part_type or "unknown").strip() or "unknown"
                part_hist[pname] += 1
        row = dict(classified.get(name) or classify_block(block, scl or None))
        row["is_safety"] = bool(getattr(block, "is_safety", False))
        row["todo_parts"] = todos
        row["todo_count"] = len(todos)
        row["instruction_count"] = inst
        per_block.append(row)

    todo_rate = (todo_total / instruction_total) if instruction_total else 0.0
    top_untranslated = [
        {"name": part, "count": count} for part, count in todo_hist.most_common(20)
    ]
    safety_blocks = [b.name for b in project.blocks.values() if getattr(b, "is_safety", False)]

    return {
        "project_name": project.name,
        "source_path": project.source_path,
        "tia_version": project.tia_version,
        "language_histogram": dict(language_hist),
        "part_histogram": dict(part_hist.most_common()),
        "todo_histogram": dict(todo_hist.most_common()),
        "todo_count": todo_total,
        "instruction_count": instruction_total,
        "todo_rate": round(todo_rate, 4),
        "converted": conversion.get("converted", 0),
        "parsed": conversion.get("parsed", 0),
        "protected": conversion.get("protected", 0),
        "interface_only": conversion.get("interface_only", 0),
        "unknown": conversion.get("failed", 0),
        "total_blocks": conversion.get("total_blocks", len(per_block)),
        "safety_blocks": safety_blocks,
        "safety_block_count": len(safety_blocks),
        "tag_tables": len(project.tag_tables),
        "hardware_devices": len(getattr(project, "hardware", None) or []),
        "top_untranslated_parts": top_untranslated,
        "blocks": per_block,
        "categories": build_category_coverage(project),
        "extraction_notes": list(project.extraction_notes),
        "timings": timings or {},
        "structure": {},
    }


def coverage_markdown(coverage: dict[str, Any]) -> str:
    """Human-readable coverage that would survive a Siemens engineer review."""
    lines: list[str] = []
    lines.append(f"# Conversion coverage: {coverage.get('project_name') or 'TIA project'}")
    lines.append("")
    total = coverage.get("total_blocks") or 0
    converted = coverage.get("converted") or 0
    parsed = coverage.get("parsed") or 0
    protected = coverage.get("protected") or 0
    interface_only = coverage.get("interface_only") or 0
    unknown = coverage.get("unknown") or 0
    lines.append("## Status")
    lines.append(
        f"- Blocks: **{total}** · converted={converted} · parsed={parsed} "
        f"(TODO left) · protected={protected} · interface_only={interface_only} "
        f"· unknown={unknown}"
    )
    inst = coverage.get("instruction_count") or 0
    todos = coverage.get("todo_count") or 0
    rate = float(coverage.get("todo_rate") or 0)
    lines.append(f"- Instructions counted: {inst}; leftover TODOs: {todos} (**{rate:.1%}**)")
    lines.append(f"- Safety F-blocks: {coverage.get('safety_block_count') or 0}")
    lines.append(f"- Tag tables: {coverage.get('tag_tables') or 0}")
    lines.append(f"- Hardware devices (best-effort): {coverage.get('hardware_devices') or 0}")
    lines.append("")
    lines.append("## Official Openness categories (chapter 6)")
    cats = coverage.get("categories") or {}
    if cats:
        for name in OFFICIAL_CATEGORIES:
            row = cats.get(name) or {}
            skipped = row.get("skipped") or 0
            reasons = row.get("skipped_reasons") or []
            reason_txt = ""
            if reasons:
                uniq = sorted({str(r.get("reason") or "") for r in reasons if r.get("reason")})
                reason_txt = " (" + ", ".join(uniq) + ")"
            lines.append(
                f"- `{name}`: exported={row.get('exported') or 0} "
                f"parsed={row.get('parsed') or 0} skipped={skipped}{reason_txt}"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Language histogram")
    hist = coverage.get("language_histogram") or {}
    if hist:
        for lang, count in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- {lang}: {count}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Part / instruction histogram")
    parts = coverage.get("part_histogram") or {}
    if parts:
        for name, count in list(parts.items())[:30]:
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- (no FlgNet parts — SCL/STL/GRAPH or empty)")
    lines.append("")
    lines.append("## Top untranslated Parts")
    top = coverage.get("top_untranslated_parts") or []
    if not top:
        lines.append("- None — fixture / project fully named or converted.")
    else:
        for row in top:
            lines.append(f"- `TODO[{row.get('name')}]` × {row.get('count')}")
    lines.append("")
    lines.append("## Per-block status")
    for row in coverage.get("blocks") or []:
        extra = ""
        if row.get("is_safety"):
            extra += " [F]"
        todos_b = row.get("todo_parts") or []
        if todos_b:
            extra += " TODOs: " + ", ".join(f"`{t}`" for t in todos_b[:8])
        lines.append(
            f"- `{row.get('block')}` ({row.get('type')} / {row.get('language')}): "
            f"**{row.get('status')}**{extra}"
        )
        if row.get("reason"):
            lines.append(f"  - {row['reason']}")
    timings = coverage.get("timings") or {}
    if timings:
        lines.append("")
        lines.append("## Timings")
        if "openness_ms" in timings:
            lines.append(f"- Openness export: {timings.get('openness_ms')} ms")
        if "extract_ms" in timings:
            lines.append(f"- Extract/parse: {timings.get('extract_ms')} ms")
        if "cache_hit" in timings or "openness_cache_hit" in timings:
            hit = timings.get("cache_hit", timings.get("openness_cache_hit"))
            lines.append(f"- Export cache hit: {hit}")
    lines.append("")
    structure = coverage.get("structure") or {}
    if structure:
        lines.append("")
        lines.append("## Trusted structure (M1)")
        lines.append(
            f"- Units: **{structure.get('total') or 0}** · "
            f"exported={structure.get('exported') or 0} · "
            f"failed={structure.get('failed') or 0} · "
            f"skipped={structure.get('skipped') or 0} · "
            f"pending={structure.get('pending') or 0}"
        )
        if structure.get("complete"):
            lines.append("- Inventory complete: no silent gaps recorded")
        else:
            lines.append(
                f"- Incomplete units visible: {structure.get('incomplete_count') or 0} "
                "(failed / skipped / pending — never omitted)"
            )
    lines.append("")
    lines.append(
        "> Know-how protected bodies are never decrypted or guessed. "
        "Writeback stays HITL; default optimize is comments / dead-block notes only."
    )
    return "\n".join(lines)
