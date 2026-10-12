"""Optimization and risk findings for PLC chat."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("researchos.gateway.plc")

__all__ = [
    "_format_optimize_hints",
    "_block_risk_notes",
]


def _format_optimize_hints(job: dict[str, Any], block_name: str | None = None) -> list[str]:
    """Short actionable hints from evidence-gated analysis (no LLM dump)."""
    try:
        from agents.plc.tia.analyst import analyze_block, analyze_project

        result = analyze_block(job, block_name) if block_name else analyze_project(job)
    except Exception as exc:  # noqa: BLE001
        logger.warning("optimize hints skipped: %s", exc)
        return ["优化：分析暂不可用。"]
    findings = result.get("findings") or []
    lines = ["**优化提示**" + (f"（`{block_name}`）" if block_name else "（工程）")]
    actionable = 0
    for f in findings:
        sev = str(f.get("severity") or "")
        if sev not in {"warn", "risk"}:
            continue
        msg = str(f.get("message") or "").strip()
        code = str(f.get("code") or "")
        if not msg:
            continue
        tip = {
            "DEAD_BLOCK": "核对是否仍需保留，或补上从 OB 的 CALLS。",
            "UNREACHABLE_FROM_OB": "检查调用链是否缺失 / 仅被注释掉。",
            "NESTED_FB_TYPE": "审查块内多实例成员类型；这不是父 FB CALL 子 FB。",
            "MULTI_INSTANCE_CHAIN": "记录嵌套链；勿为改数字扁平化多实例。不可写体则只出 HITL 计划。",
        }.get(code, "结合调用与 IO 再确认是否可简化。")
        lines.append(f"- [{sev}] {msg} → {tip}")
        actionable += 1
        if actionable >= 5:
            break
    if not actionable:
        lines.append("- 未发现 warn/risk 级发现；可点「优化提案」做逻辑级改写预览。")
    return lines


def _block_risk_notes(job: dict[str, Any], block_name: str) -> list[str]:
    """Compact risk/warn lines for chat (no full evidence appendix)."""
    try:
        from agents.plc.tia.analyst import analyze_block

        findings = analyze_block(job, block_name).get("findings") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("PLC risk notes skipped: %s", exc)
        return []
    notes: list[str] = []
    for f in findings:
        sev = str(f.get("severity") or "")
        if sev not in {"warn", "risk"}:
            continue
        msg = str(f.get("message") or "").strip()
        if msg:
            notes.append(msg)
    return notes[:4]
