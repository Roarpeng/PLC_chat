"""Streaming / event helpers — publish RuntimeEvent dicts into state.events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from runtime.researchos_runtime.state import RuntimeEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event(
    event_type: str,
    task_id: str,
    payload: dict[str, Any] | None = None,
    *,
    agent: str | None = None,
) -> RuntimeEvent:
    body = dict(payload or {})
    if agent is not None:
        body.setdefault("agent", agent)
    return {
        "type": event_type,
        "task_id": task_id,
        "payload": body,
        "ts": _now_iso(),
    }


def node_start(task_id: str, agent: str, **extra: Any) -> RuntimeEvent:
    return make_event("node_start", task_id, extra, agent=agent)


def node_end(task_id: str, agent: str, **extra: Any) -> RuntimeEvent:
    return make_event("node_end", task_id, extra, agent=agent)


def interrupt_event(
    task_id: str,
    interrupt_id: str,
    interrupt_type: str,
    prompt: str,
    options: list[str] | None = None,
) -> RuntimeEvent:
    return make_event(
        "interrupt",
        task_id,
        {
            "interrupt_id": interrupt_id,
            "interrupt_type": interrupt_type,
            "prompt": prompt,
            "options": options or [],
        },
    )


def interrupt_resolved_event(
    task_id: str,
    interrupt_id: str,
    resolution: str,
) -> RuntimeEvent:
    return make_event(
        "interrupt_resolved",
        task_id,
        {"interrupt_id": interrupt_id, "resolution": resolution},
    )


def tool_call_event(task_id: str, tool: str, args: dict[str, Any]) -> RuntimeEvent:
    return make_event("tool_call", task_id, {"tool": tool, "args": args})


def tool_result_event(
    task_id: str,
    tool: str,
    ok: bool,
    summary: str,
) -> RuntimeEvent:
    return make_event(
        "tool_result",
        task_id,
        {"tool": tool, "ok": ok, "result_summary": summary},
    )


def final_event(task_id: str, status: str, **extra: Any) -> RuntimeEvent:
    return make_event("final", task_id, {"status": status, **extra})


def new_interrupt_id() -> str:
    return f"int_{uuid4().hex[:12]}"
