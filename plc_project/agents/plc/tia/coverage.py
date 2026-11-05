"""Honest conversion coverage — every block, every leftover TODO named."""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

from agents.plc.tia.ir import Block, BlockType, PlcProject
from agents.plc.tia.package import build_conversion_report, classify_block
from agents.plc.tia.surface import OFFICIAL_CATEGORIES

_TODO_RE = re.compile(r"TODO\[([^\]]+)\]")

#: untranslated-Part share above which a block-level warning is raised
TODO_RATE_WARN_THRESHOLD = 0.05
TODO_RATE_WARN_ENV = "RESEARCHOS_PLC_TODO_RATE_WARN"
#: how many block names a warning carries (UI shows a compact list)
_MAX_AFFECTED_BLOCKS = 12
#: how many block names are spelled out inside the human message
_MAX_NAMED_IN_MESSAGE = 5

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


def todo_rate_warn_threshold() -> float:
    """Warn threshold for ``todo_rate``; overridable via env, never above 1."""
    raw = (os.getenv(TODO_RATE_WARN_ENV) or "").strip()
    if not raw:
        return TODO_RATE_WARN_THRESHOLD
    try:
        return min(1.0, max(0.0, float(raw)))
    except ValueError:
        return TODO_RATE_WARN_THRESHOLD


def _warning(
    level: str,
    code: str,
    message: str,
    affected_blocks: list[str],
    count: int,
) -> dict[str, Any]:
    """One engineer-readable degradation record; names are capped for the UI."""
    return {
        "level": level,
        "code": code,
        "message": message,
        "affected_blocks": list(affected_blocks[:_MAX_AFFECTED_BLOCKS]),
        "count": int(count),
    }


def _named(blocks: list[str], limit: int = _MAX_NAMED_IN_MESSAGE) -> str:
    shown = "、".join(f"`{name}`" for name in blocks[:limit])
    if len(blocks) > limit:
        shown += f" 等 {len(blocks)} 个块"
    return shown


def _fallback_family(language: str) -> str:
    """STL / FBD / GRAPH are best-effort translations — LAD/SCL are not."""
    core = language.upper().removeprefix("F-")
    for family in ("STL", "FBD", "GRAPH"):
        if core.startswith(family):
            return family
    return ""


def _graph_network_count(block: Block) -> int:
    total = 0
    for network in block.networks:
        language = (network.programming_language or "").upper()
        if language == "GRAPH" or getattr(network, "graph_steps", None):
            total += 1
    return total


def _unresolved_part_count(block: Block) -> int:
    total = 0
    for network in block.networks:
        folded = getattr(network, "folded", None)
        total += len(getattr(folded, "unresolved_parts", None) or [])
    return total


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


def _degradation_warnings(
    *,
    todo_rate: float,
    todo_total: int,
    instruction_total: int,
    blocks_with_todos: list[str],
    graph_blocks: list[str],
    graph_networks: int,
    unresolved_blocks: list[str],
    unresolved_total: int,
    fallback_todo_blocks: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Turn silent parser fallbacks into warnings a Siemens engineer can act on."""
    warnings: list[dict[str, Any]] = []

    if graph_blocks:
        nets = (
            f"{graph_networks} 个步序网络"
            if graph_networks
            else "但没有解析到任何步序/转换"
        )
        warnings.append(
            _warning(
                "warning",
                "coverage.graph_not_executable",
                (
                    f"工程含 {len(graph_blocks)} 个 S7-GRAPH 块（{nets}）。当前只把它降级成 "
                    "CASE 状态机 + 注释：动作限定符、互锁/监控、并发分支的语义已经丢失，"
                    "与博图 GRAPH 语义不等价，不能直接回写。请按原始步序人工复核："
                    f"{_named(graph_blocks)}。"
                ),
                graph_blocks,
                len(graph_blocks),
            )
        )

    threshold = todo_rate_warn_threshold()
    if todo_total and todo_rate > threshold:
        translated = round(max(0.0, 1.0 - todo_rate) * 100, 1)
        untranslated = round(todo_rate * 100, 1)
        warnings.append(
            _warning(
                "warning",
                "coverage.todo_rate_high",
                (
                    f"解析翻译完成度只有 {translated}%：{instruction_total} 条语句里还有 "
                    f"{todo_total} 条是 TODO 占位注释（未翻译 {untranslated}%，超过 "
                    f"{round(threshold * 100, 1)}% 告警阈值）。这些位置不会产生可执行逻辑，"
                    f"回写博图前必须人工补齐；涉及 {len(blocks_with_todos)} 个块："
                    f"{_named(blocks_with_todos)}。"
                ),
                blocks_with_todos,
                len(blocks_with_todos),
            )
        )

    if unresolved_blocks:
        warnings.append(
            _warning(
                "warning",
                "coverage.unresolved_parts",
                (
                    f"{len(unresolved_blocks)} 个块共有 {unresolved_total} 个网络部件无法折叠成语句"
                    "（只能落成 TODO 注释），这些网络的逻辑等于空白，请优先人工确认："
                    f"{_named(unresolved_blocks)}。"
                ),
                unresolved_blocks,
                len(unresolved_blocks),
            )
        )

    for family, names in sorted(fallback_todo_blocks.items()):
        warnings.append(
            _warning(
                "info",
                f"coverage.{family.lower()}_fallback",
                (
                    f"{len(names)} 个 {family} 块含未翻译指令：{family} 是逐个助记符映射成 SCL 的，"
                    "映射表以外的指令只会留下 TODO 注释、不会报错，生成的 SCL 不能当作等价逻辑："
                    f"{_named(names)}。"
                ),
                names,
                len(names),
            )
        )

    return warnings


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
    blocks_with_todos: list[str] = []
    graph_blocks: list[str] = []
    graph_networks = 0
    unresolved_blocks: list[str] = []
    unresolved_total = 0
    fallback_todo_blocks: dict[str, list[str]] = {}

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

        if todos:
            blocks_with_todos.append(name)
            family = _fallback_family(lang)
            if family in {"STL", "FBD"}:
                fallback_todo_blocks.setdefault(family, []).append(name)
        graph_nets = _graph_network_count(block)
        if graph_nets or _fallback_family(lang) == "GRAPH":
            graph_blocks.append(name)
            graph_networks += graph_nets
        unresolved = _unresolved_part_count(block)
        if unresolved:
            unresolved_blocks.append(name)
            unresolved_total += unresolved

    todo_rate = (todo_total / instruction_total) if instruction_total else 0.0
    top_untranslated = [
        {"name": part, "count": count} for part, count in todo_hist.most_common(20)
    ]
    safety_blocks = [b.name for b in project.blocks.values() if getattr(b, "is_safety", False)]
    warnings = _degradation_warnings(
        todo_rate=todo_rate,
        todo_total=todo_total,
        instruction_total=instruction_total,
        blocks_with_todos=blocks_with_todos,
        graph_blocks=graph_blocks,
        graph_networks=graph_networks,
        unresolved_blocks=unresolved_blocks,
        unresolved_total=unresolved_total,
        fallback_todo_blocks=fallback_todo_blocks,
    )

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
        "translated_rate": round(max(0.0, 1.0 - todo_rate), 4),
        "warnings": warnings,
        "warning_count": len(warnings),
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
    warnings = coverage.get("warnings") or []
    if warnings:
        lines.append("## ⚠ 解析降级告警（先看这里）")
        for item in warnings:
            level = str(item.get("level") or "warning").upper()
            lines.append(f"- **[{level}]** `{item.get('code')}` {item.get('message')}")
            affected = item.get("affected_blocks") or []
            if affected:
                lines.append(
                    "  - 受影响块："
                    + "、".join(f"`{name}`" for name in affected)
                    + (
                        f"（共 {item.get('count')} 个）"
                        if int(item.get("count") or 0) > len(affected)
                        else ""
                    )
                )
        lines.append("")
    else:
        lines.append("> 未检测到解析降级：TODO 未翻译比例在阈值内，也没有 GRAPH/不可折叠部件。")
        lines.append("")
    lines.append("## Status")
    total = coverage.get("total_blocks") or 0
    converted = coverage.get("converted") or 0
    parsed = coverage.get("parsed") or 0
    protected = coverage.get("protected") or 0
    interface_only = coverage.get("interface_only") or 0
    unknown = coverage.get("unknown") or 0
    lines.append(
        f"- Blocks: **{total}** · converted={converted} · parsed={parsed} "
        f"(TODO left) · protected={protected} · interface_only={interface_only} "
        f"· unknown={unknown}"
    )
    inst = coverage.get("instruction_count") or 0
    todos = coverage.get("todo_count") or 0
    rate = float(coverage.get("todo_rate") or 0)
    translated = float(coverage.get("translated_rate", max(0.0, 1.0 - rate)) or 0)
    lines.append(
        f"- Instructions counted: {inst}; leftover TODOs: {todos} (**{rate:.1%}**) "
        f"→ 已翻译 **{translated:.1%}**"
    )
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


# ---------------------------------------------------------------------------
# fail-closed writeback gate (any2scl golden regression, docs/16 §4 / §7)
#
# 追加段：不改动 build_category_coverage / build_coverage_report /
# coverage_markdown / _degradation_warnings 等任何现有函数或其返回结构。
# ---------------------------------------------------------------------------

#: 五类系统性缺陷在最终 SCL 文本里留下的确定性坏痕迹
#: (docs/16 §3.1 修复前实际输出 / §4 问题清单 / §7.1 修复波清零项)。
#: 只收录"可从 SCL 文本可靠判定"的模式；S4 极性反转在文本上没有稳定
#: token，由 assert_scl_safe_for_writeback 借 PlcProject 的 negated 部件做
#: 取反守恒检查（见下）。修复波后 hr001 全量扫描五类均为 0 文件。
SCL_DEFECT_PATTERNS: dict[str, tuple[str, ...]] = {
    "S1_statement_loss": (
        r"TODO\[translate-align\]",
        r"folded-leftover",
        (
            r"TODO\[(?:CoilTON|CoilTOF|CoilTP|Add|Sub|Mul|Div|Mod|Pow|Abs|Calc|Swap|"
            r"Sin|Cos|Sqrt|RD_SYS_T|RD_LOC_T|WR_SYS_T|WR_LOC_T|READ_CLK|TIME_TCK|"
            r"T_CONV|SYS_TIME)\]"
        ),
    ),
    "S2_loop_guard": (r"loop guard",),
    "S3_empty_literal": (
        r"PT\s*:=\s*\)",
        r"PT\s*:=\s*;",
        r":=\s*\)",
        r":=\s*;",
        r'"TRUE"',
        r'"FALSE"',
    ),
    "S4_negation_loss": (r"TODO\[Negated\]",),
    "S5_driver_loss": (
        r"\b(?:Sr|Rs|CtU|CtD|CtUD|CTU|CTD|CTUD|TON|TOF|TP|SR|RS)\s*\(\s*\)\s*;",
        r"(?m)^[ \t]*\(\s*\)\s*;",
    ),
}

_COMPILED_DEFECT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    code: tuple(re.compile(pattern) for pattern in patterns)
    for code, patterns in SCL_DEFECT_PATTERNS.items()
}
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_HAS_NOT_RE = re.compile(r"\bNOT\s*\(")


def scan_scl_defects(scl: str) -> dict[str, list[str]]:
    """Scan one SCL source for the five defect families, return only hits.

    Pure function (never mutates, never raises on malformed text). ``//`` line
    comments are stripped before matching so an explanatory comment containing
    ``"TRUE"`` cannot trigger S3; ``(* ... *)`` block comments are kept because
    the S1/S2 leftovers live inside them.
    """
    text = _LINE_COMMENT_RE.sub("", scl or "")
    hits: dict[str, list[str]] = {}
    for code, patterns in _COMPILED_DEFECT_PATTERNS.items():
        found: list[str] = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                snippet = match.group(0).strip()
                if snippet and snippet not in found:
                    found.append(snippet)
        if found:
            hits[code] = found[:8]
    return hits


class SclWritebackUnsafeError(RuntimeError):
    """Raised when generated SCL must not be written back to TIA (fail-closed).

    ``issues`` keeps each blocking category; ``blocks`` is the deduped, sorted
    block-name list carried by the exception for the writeback chain's UI.
    """

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = list(issues)
        blocks = sorted(
            {str(name) for issue in issues for name in (issue.get("blocks") or []) if name}
        )
        self.blocks = blocks
        lines = ["SCL 回写门禁失败（fail-closed），禁止写入 TIA："]
        for issue in issues:
            affected = [str(b) for b in (issue.get("blocks") or []) if b]
            shown = "、".join(f"`{name}`" for name in affected[:_MAX_AFFECTED_BLOCKS])
            if len(affected) > _MAX_AFFECTED_BLOCKS:
                shown += f" 等 {len(affected)} 个块"
            lines.append(
                f"- [{issue.get('code')}] {issue.get('detail')}"
                + (f"（受影响块：{shown}）" if shown else "（块名不可定位）")
            )
        lines.append(
            f"受影响块清单（去重，共 {len(blocks)} 个）："
            + ("、".join(blocks) if blocks else "(无)")
        )
        super().__init__("\n".join(lines))


def _extract_scl_sources(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("scl_sources")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
    report_keys = {"coverage", "conversion_report", "warnings", "todo_count", "project"}
    bare_mapping = bool(data) and all(isinstance(v, str) for v in data.values())
    if bare_mapping and not (report_keys & data.keys()):
        return {str(k): str(v) for k, v in data.items()}
    return {}


def _extract_coverage(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("coverage")
    if isinstance(raw, dict):
        return raw
    coverage_markers = (
        "warning_count",
        "warnings",
        "todo_histogram",
        "todo_rate",
        "todo_count",
        "translated_rate",
        "top_untranslated_parts",
        "language_histogram",
    )
    if any(key in data for key in coverage_markers):
        return data
    return {}


def _negated_blocks(project: Any) -> list[str]:
    """Block names carrying a pin-level negated part (<Negated Name="operand"/>)."""
    if project is None or not hasattr(project, "blocks"):
        return []
    out: list[str] = []
    for name, block in project.blocks.items():
        found = False
        for network in getattr(block, "networks", None) or []:
            parts = getattr(network, "parts", None) or {}
            for part in parts.values():
                negated = bool(getattr(part, "negated", False))
                pins = getattr(part, "negated_pins", None) or set()
                if negated or "operand" in pins:
                    found = True
                    break
            if found:
                break
        if found:
            out.append(str(name))
    return out


def assert_scl_safe_for_writeback(report_or_coverage: Any) -> bool:
    """Fail-closed gate: never write unsafe SCL back to TIA.

    Accepted inputs:
      * ``analyze_tia_exports`` result (has ``scl_sources`` / ``coverage`` / ``project``),
      * ``build_coverage_report`` output (no SCL text — structural signals only),
      * ``build_conversion_report`` output (structural signals only),
      * a bare ``{block_name: scl_text}`` mapping.

    Raises :class:`SclWritebackUnsafeError` (with a deduped block-name list) when
    any is present: untranslated ``TODO[...]`` markers, unfoldable parts
    (``coverage.unresolved_parts``), S7-GRAPH downgrade, or any of the five
    defect families in :data:`SCL_DEFECT_PATTERNS`. Returns ``True`` only when
    the evidence is conclusive and clean. S4 (polarity reversal) has no stable
    text token, so it is additionally checked by negated-part / ``NOT (``
    conservation when a ``PlcProject`` is available.

    This function only reads its input; it does not change any
    ``build_coverage*`` return shape (backward compatible).
    """
    if not isinstance(report_or_coverage, dict):
        raise SclWritebackUnsafeError(
            [{"code": "no_evidence", "blocks": [], "detail": "入参不是 dict，无法确认 SCL 安全"}]
        )
    data = report_or_coverage
    scl_sources = _extract_scl_sources(data)
    coverage = _extract_coverage(data)
    conversion = data.get("conversion_report")
    if not isinstance(conversion, dict):
        conversion = {}
    project = data.get("project")

    issues: list[dict[str, Any]] = []

    # (1) 未翻译 TODO：文本优先 + coverage/conversion 结构化信号兜底
    todo_blocks: set[str] = set()
    for name, text in scl_sources.items():
        if _TODO_RE.search(text):
            todo_blocks.add(name)
    cov_blocks = coverage.get("blocks")
    if isinstance(cov_blocks, list):
        for row in cov_blocks:
            if not isinstance(row, dict):
                continue
            name = str(row.get("block") or "")
            has_todo = row.get("todo_count") or row.get("todo_parts")
            if name and (has_todo or row.get("status") == "parsed"):
                todo_blocks.add(name)
    if not scl_sources and conversion:
        for row in conversion.get("blocks") or []:
            if isinstance(row, dict) and row.get("status") == "parsed":
                name = str(row.get("block") or "")
                if name:
                    todo_blocks.add(name)
    todo_total = int(coverage.get("todo_count") or 0)
    if todo_blocks or todo_total > 0:
        issues.append(
            {
                "code": "untranslated_todo",
                "blocks": sorted(b for b in todo_blocks if b),
                "detail": (
                    f"仍有 {todo_total} 个未翻译 TODO[...] 占位"
                    if todo_total
                    else "SCL 文本仍含未翻译 TODO[...] 占位"
                ),
            }
        )

    # (2) 不可折叠部件 / GRAPH 降级（coverage warnings 是既有公开结构）
    for warn in coverage.get("warnings") or []:
        if not isinstance(warn, dict):
            continue
        code = str(warn.get("code") or "")
        affected = [str(b) for b in (warn.get("affected_blocks") or []) if b]
        if code == "coverage.unresolved_parts":
            issues.append(
                {
                    "code": "unfoldable_parts",
                    "blocks": affected,
                    "detail": f"{int(warn.get('count') or 0)} 个块含无法折叠成语句的网络部件",
                }
            )
        elif code == "coverage.graph_not_executable":
            issues.append(
                {
                    "code": "graph_not_executable",
                    "blocks": affected,
                    "detail": "S7-GRAPH 降级为注释序列，语义不等价，不能直接回写",
                }
            )

    # (3) 五类缺陷模式：文本扫描 + S4 取反守恒
    by_code: dict[str, set[str]] = {}
    for name, text in scl_sources.items():
        for defect_code in scan_scl_defects(text):
            by_code.setdefault(defect_code, set()).add(name)
    if project is not None:
        for name in _negated_blocks(project):
            if name in scl_sources and not _HAS_NOT_RE.search(scl_sources[name]):
                by_code.setdefault("S4_negation_loss", set()).add(name)
    for defect_code in sorted(by_code):
        issues.append(
            {
                "code": defect_code,
                "blocks": sorted(by_code[defect_code]),
                "detail": f"命中 docs/16 五类缺陷模式 {defect_code}",
            }
        )

    # (4) fail-closed：既无 SCL 文本也无结构化证据，一律拦下
    if not scl_sources and not coverage and not conversion:
        issues.append(
            {
                "code": "no_evidence",
                "blocks": [],
                "detail": "无 scl_sources / coverage / conversion_report，无法确认 SCL 安全",
            }
        )

    if issues:
        raise SclWritebackUnsafeError(issues)
    return True
