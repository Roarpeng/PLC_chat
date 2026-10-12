"""PLC Agent node: manual cross-reference, change advice, safety checks.

Phase 5 industrial extension. Strictly **read-only**: the agent only
queries the PLC docs connector (`industrial.connectors.plc_docs`) and
emits advisory analysis blocks. It never downloads programs to field
devices — see docs/industrial/02-plc-and-automation.md.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from agents.plc.tia import analyze_plc_project
from industrial.connectors.plc_docs import (
    FakePlcDocsConnector,
    PlcDocEntry,
    PlcDocsConnector,
)
from runtime.researchos_runtime.state import Budgets, TaskState

SAFETY_KEYWORDS = ("safety", "interlock", "e-stop", "estop", "安全", "联锁", "急停")

#: Hard invariant — this agent must never gain a device write path.
READ_ONLY = True


def _budgets(state: TaskState) -> Budgets:
    return dict(state.get("budgets") or {})  # type: ignore[return-value]


def _plc_query(goal: dict[str, Any]) -> str:
    """Compose a manual-search query from goal + PLC-relevant scope."""
    parts: list[str] = []
    objective = goal.get("normalized_objective") or goal.get("raw_query") or ""
    if objective:
        parts.append(str(objective))
    for item in list(goal.get("scope") or []) + list(goal.get("constraints") or []):
        text = str(item).strip()
        if text:
            parts.append(text)
    return " ".join(parts)[:400] or "plc"


def _looks_safety_related(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in SAFETY_KEYWORDS)


def _evidence_from_hits(
    state: TaskState, hits: list[PlcDocEntry], now: str
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for idx, entry in enumerate(hits, start=1):
        evidence.append(
            {
                "id": f"ev_plc_{state.get('task_id', 'task')}_{idx}",
                "source_id": f"plc_docs:{entry.id}",
                "title": entry.title,
                "content": entry.summary,
                "url": entry.url,
                "locator": entry.id,
                "score": 1.0 - 0.05 * (idx - 1),
                "meta": {
                    "retrieved_at": now,
                    "retrieved_by": "plc",
                    "provider": "plc_docs_connector",
                    "source_type": "plc_manual",
                    "vendor": entry.vendor,
                    "family": entry.family,
                    "tags": list(entry.tags),
                    "readonly": READ_ONLY,
                },
            }
        )
    return evidence


def _cites_for(
    all_hits: list[PlcDocEntry], selected: list[PlcDocEntry], task_id: str
) -> list[str]:
    """TMP placeholders keyed by evidence id (resolved by Citation agent)."""
    idx_of = {e.id: i for i, e in enumerate(all_hits, start=1)}
    return [
        f"TMP:ev_plc_{task_id or 'task'}_{idx_of[e.id]}"
        for e in selected
        if e.id in idx_of
    ]


def _manuals_block(
    goal: dict[str, Any], hits: list[PlcDocEntry], task_id: str
) -> dict[str, Any]:
    vendors = sorted({e.vendor for e in hits})
    lines = [
        f"- [{e.id}] {e.title} ({e.vendor} / {e.family}) — {e.summary}"
        for e in hits
    ]
    content = (
        "## PLC Manual Coverage\n"
        + ("Available manual references:\n" + "\n".join(lines) if lines else
           "No PLC manual matched the query in the connected catalog.")
        + "\n\nVendors covered: "
        + (", ".join(vendors) if vendors else "(none)")
    )
    gaps = [] if hits else ["no_plc_manual_matched"]
    return {
        "specialty": "plc_manuals",
        "content": content,
        "gaps": gaps,
        "citation_ids": _cites_for(hits, hits, task_id),
    }


def _change_advice_block(
    goal: dict[str, Any], hits: list[PlcDocEntry], task_id: str
) -> dict[str, Any]:
    query = goal.get("normalized_objective") or goal.get("raw_query") or "the change"
    refs = ", ".join(e.id for e in hits) or "(no manual reference found)"
    content = (
        "## PLC Change Advice\n"
        f"For «{query}»:\n"
        f"- Prepare a change proposal against referenced manuals: {refs}.\n"
        "- Produce a test checklist covering affected IO points and interlocks.\n"
        "- Route the proposal through enterprise change management (MOC) and "
        "engineer review before any download.\n\n"
        "**Guardrail:** this system does not download unreviewed programs to "
        "PLCs; `plc.program.download` is disabled by default."
    )
    gaps = [] if hits else ["missing_manual_reference_for_change_advice"]
    return {
        "specialty": "plc_change_advice",
        "content": content,
        "gaps": gaps,
        "citation_ids": _cites_for(hits, hits, task_id),
    }


def _safety_block(query: str, hits: list[PlcDocEntry], task_id: str) -> dict[str, Any]:
    safety_hits = [
        e for e in hits if _looks_safety_related(e.title + " " + e.summary) or "safety" in e.tags
    ]
    if _looks_safety_related(query):
        if safety_hits:
            refs = ", ".join(e.id for e in safety_hits)
            content = (
                "## Safety Cross-Check\n"
                f"Safety-relevant query matched manual references: {refs}.\n"
                "Safety conclusions must cite vendor safety manuals or "
                "ISO/IEC standards; the model must not 'optimize away' "
                "interlocks or safety conditions."
            )
            gaps: list[str] = []
        else:
            content = (
                "## Safety Cross-Check\n"
                "Query appears safety-related, but no safety manual reference "
                "was found. Escalate to a human engineer before proceeding; "
                "safety claims without citations are not allowed."
            )
            gaps = ["safety_reference_missing"]
    else:
        content = (
            "## Safety Cross-Check\n"
            "No safety keywords detected. Default guardrails still apply: "
            "read-only access, no field writes, audit all tool calls."
        )
        gaps = []
    return {
        "specialty": "plc_safety",
        "content": content,
        "gaps": gaps,
        "citation_ids": _cites_for(hits, safety_hits, task_id),
    }


def _tia_export_dir(state: TaskState, goal: dict[str, Any]) -> str:
    """Locate a .apxx project or Openness export dir from state / goal / env."""
    meta = state.get("meta") or {}
    for candidate in (
        meta.get("plc_tia_project"),
        meta.get("plc_tia_export_dir"),
        goal.get("tia_project"),
        goal.get("tia_export_dir"),
        os.getenv("RESEARCHOS_TIA_PROJECT", ""),
        os.getenv("RESEARCHOS_TIA_EXPORTS", ""),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _tia_analysis_block(
    state: TaskState, project_or_export: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run Offline Analyzer (.apxx / .xml / export dir); returns (block, tool trace)."""
    started = time.monotonic()
    result_dir = str((state.get("meta") or {}).get("plc_result_dir") or "").strip()
    publish = os.getenv("RESEARCHOS_PLC_PUBLISH_GRAPH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        result = analyze_plc_project(
            project_or_export,
            result_dir=result_dir,
            auto_export=True,
            publish_graph=publish,
        )
    except Exception as exc:  # advisory agent must not crash the graph
        duration_ms = int((time.monotonic() - started) * 1000)
        trace = {
            "tool": "plc.tia.ingest",
            "args": {
                "path": project_or_export,
                "result_dir": result_dir,
                "publish_graph": publish,
            },
            "result_summary": f"error={exc}",
            "ok": False,
            "duration_ms": duration_ms,
        }
        block = {
            "specialty": "plc_tia_analysis",
            "content": f"## TIA Project Analysis\nFailed to analyze "
            f"`{project_or_export}`: {exc}",
            "gaps": ["tia_analysis_failed"],
            "citation_ids": [],
        }
        return block, trace

    project = result["project"]
    duration_ms = int((time.monotonic() - started) * 1000)
    conversion = result.get("conversion_report") or {}
    trace = {
        "tool": "plc.tia.ingest",
        "args": {
            "path": project_or_export,
            "result_dir": result_dir,
            "publish_graph": publish,
        },
        "result_summary": (
            f"ok=True blocks={len(project.blocks)} "
            f"converted={conversion.get('converted', 0)} "
            f"tag_tables={len(project.tag_tables)}"
        ),
        "ok": True,
        "duration_ms": duration_ms,
    }
    gaps = list(project.extraction_notes)
    block = {
        "specialty": "plc_tia_analysis",
        "content": result["report"],
        "gaps": gaps,
        "citation_ids": [],
        "scl_sources": result["scl_sources"],
        "knowledge_graph": result["knowledge_graph"].to_json(),
        "conversion_report": conversion,
        "result_dir": result.get("result_dir") or "",
        "graph_publish": result.get("graph_publish"),
    }
    return block, trace


def run(state: TaskState, *, connector: PlcDocsConnector | None = None) -> dict[str, Any]:
    """PLC agent entry point. Inject a custom connector for tests."""
    started = time.monotonic()
    goal = state.get("goal") or {}
    connector = connector or FakePlcDocsConnector()
    query = _plc_query(goal)

    budgets = _budgets(state)
    used_tool = int(budgets.get("used_tool_calls") or 0)
    limit = 5

    hits = list(connector.search(query, limit=limit) or [])
    if not hits:
        # Fallback: broaden per scope keyword, then vendor list
        for term in list(goal.get("scope") or []):
            hits = list(connector.search(str(term), limit=limit) or [])
            if hits:
                break
    ok = bool(hits)
    duration_ms = int((time.monotonic() - started) * 1000)

    now = datetime.now(timezone.utc).isoformat()
    evidence = _evidence_from_hits(state, hits, now)
    task_id = state.get("task_id", "task")
    blocks = {
        "plc_manuals": _manuals_block(goal, hits, task_id),
        "plc_change_advice": _change_advice_block(goal, hits, task_id),
        "plc_safety": _safety_block(query, hits, task_id),
    }

    traces: list[dict[str, Any]] = [
        {
            "tool": "plc.manual.search",
            "args": {"query": query[:200], "limit": limit},
            "result_summary": f"ok={ok} n={len(hits)}",
            "ok": ok,
            "duration_ms": duration_ms,
        }
    ]

    # Optional offline TIA project analysis (SimaticML exports -> KG + SCL)
    tia_blocks: dict[str, Any] = {}
    export_dir = _tia_export_dir(state, goal)
    if export_dir:
        tia_block, tia_trace = _tia_analysis_block(state, export_dir)
        if tia_block is not None:
            tia_blocks["plc_tia_analysis"] = tia_block
        if tia_trace is not None:
            traces.append(tia_trace)
            used_tool += 1
    blocks.update(tia_blocks)

    new_budgets = {**budgets, "used_tool_calls": used_tool + 1}

    return {
        "evidence": evidence,
        "analysis_results": blocks,
        "budgets": new_budgets,
        "tool_traces": traces,
        "events": [
            {
                "type": "plc.completed",
                "task_id": state.get("task_id", ""),
                "payload": {
                    "manual_hits": len(hits),
                    "readonly": READ_ONLY,
                    "blocks": list(blocks.keys()),
                    "tia_analyzed": bool(tia_blocks),
                },
                "ts": now,
            }
        ],
        "route": "analysis",
        "meta": {
            **(state.get("meta") or {}),
            "plc_readonly": READ_ONLY,
            "plc_manual_hits": len(hits),
            "plc_tia_analyzed": bool(tia_blocks),
        },
    }
