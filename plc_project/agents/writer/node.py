"""Writer Agent node: assemble Markdown report into state.result."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from runtime.researchos_runtime.state import TaskState


def _marker(cid: str, style: str) -> str:
    if style == "bracket":
        return f"[citation:{cid}]"
    return f"[^{cid}]"


def run(state: TaskState) -> dict[str, Any]:
    review = state.get("review") or {}
    verdict = review.get("verdict")
    meta = dict(state.get("meta") or {})
    draft_mode = bool(meta.get("writer_draft_mode"))

    if verdict not in (None, "pass", "pass_with_warnings") and not draft_mode:
        # Allow writing when review not yet run only in draft mode
        if verdict == "reject":
            return {
                "meta": {**meta, "writer_skipped": True, "writer_reason": "review rejected"},
                "route": "supervisor",
            }

    goal = state.get("goal") or {}
    query = goal.get("raw_query") or "Research report"
    locale = goal.get("locale") or "zh-CN"
    style = meta.get("citation_style") or "footnote"
    citations = list(state.get("citations") or [])
    analysis = dict(state.get("analysis_results") or {})
    plan = state.get("plan") or {}
    now = datetime.now(timezone.utc).isoformat()

    title = f"ResearchOS Report — {query[:80]}"
    lines: list[str] = [
        "---",
        f'title: "{title.replace(chr(34), "")}"',
        f"task_id: {state.get('task_id', '')}",
        f"locale: {locale}",
        f"generated_at: {now}",
        "generator: ResearchOS Writer Agent",
        "---",
        "",
        f"# {title}",
        "",
        "## 摘要",
    ]

    if verdict == "pass_with_warnings":
        lines.append("")
        lines.append("> **Reviewer warnings:** " + "; ".join(review.get("reasons") or []))
        lines.append("")

    # Opening summary with first citations
    lead_cites = [str(c.get("id")) for c in citations[:3] if c.get("id")]
    markers = "".join(_marker(cid, style) for cid in lead_cites)
    lines.append(
        f"本报告围绕「{query}」整理公开与内部可得证据，"
        f"并给出竞品、风险与决策要点。{markers}"
    )
    lines.append("")

    lines.append("## 范围与方法")
    steps = (plan.get("steps") or []) if isinstance(plan, dict) else []
    if steps:
        for step in steps:
            lines.append(f"- {step.get('id', '')}: {step.get('title', '')} ({step.get('agent', '')})")
    else:
        lines.append("- Research → Analysis → Citation → Review → Write（MVP 默认流水线）")
    lines.append("")

    specialty_titles = {
        "competitors": "竞品格局",
        "risks": "风险",
        "decision": "结论与建议",
        "specs": "规格对比",
        "pricing": "定价与商业条款",
    }

    for specialty, block in analysis.items():
        heading = specialty_titles.get(specialty, specialty.title())
        lines.append(f"## {heading}")
        content = str((block or {}).get("content") or "").strip()
        # Strip leading ## heading from analysis content if present
        content_lines = content.splitlines()
        if content_lines and content_lines[0].startswith("## "):
            content_lines = content_lines[1:]
        body = "\n".join(content_lines).strip()
        cite_ids = [str(x) for x in ((block or {}).get("citation_ids") or [])]
        suffix = "".join(_marker(cid, style) for cid in cite_ids[:5])
        lines.append(body + (suffix if body else suffix))
        gaps = (block or {}).get("gaps") or []
        if gaps:
            lines.append("")
            lines.append("**Gaps:** " + "; ".join(str(g) for g in gaps))
        lines.append("")

    lines.append("## 引用与来源")
    lines.append("")
    if not citations:
        lines.append("_（无引用）_")
    else:
        for cit in citations:
            cid = cit.get("id")
            title_c = cit.get("title") or "untitled"
            url = cit.get("url") or ""
            quote = (cit.get("quote") or "").replace("\n", " ")[:160]
            if style == "bracket":
                lines.append(f"- **{cid}**: {title_c} — {url}")
                if quote:
                    lines.append(f"  - > {quote}")
            else:
                lines.append(f"[^{cid}]: {title_c}, {url}")
                if quote:
                    lines.append(f"    Quote: {quote}")
    lines.append("")
    lines.append("## 附录")
    lines.append("")
    lines.append(f"- Evidence count: {len(state.get('evidence') or [])}")
    lines.append(f"- Citation count: {len(citations)}")
    lines.append(f"- Review verdict: {verdict or 'n/a'}")

    markdown = "\n".join(lines)
    return {
        "result": markdown,
        "route": "memory",
        "meta": {**meta, "writer_completed": True, "report_format": "markdown"},
        "events": [
            {
                "type": "writer.completed",
                "task_id": state.get("task_id", ""),
                "payload": {"chars": len(markdown), "citations": len(citations)},
                "ts": now,
            }
        ],
    }
