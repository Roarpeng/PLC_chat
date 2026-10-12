"""TaskState — single source of truth for LangGraph Runtime.

Aligned with docs/runtime/01-state-model.md
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, Any, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def add_items(left: list | None, right: list | None) -> list:
    return (left or []) + (right or [])


def merge_dict(left: dict | None, right: dict | None) -> dict:
    out = dict(left or {})
    out.update(right or {})
    return out


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Goal(TypedDict, total=False):
    raw_query: str
    normalized_objective: str
    scope: list[str]
    constraints: list[str]
    workflow: str
    priority_specialties: list[str]
    locale: str
    success_criteria: list[str]


class PlanStep(TypedDict, total=False):
    id: str
    title: str
    agent: str
    status: str
    depends_on: list[str]
    notes: str


class Plan(TypedDict, total=False):
    version: int
    approved: bool
    steps: list[PlanStep]
    summary: str


class EvidenceItem(TypedDict, total=False):
    id: str
    source_id: str
    title: str
    content: str
    url: str
    locator: str
    score: float
    meta: dict[str, Any]


class Citation(TypedDict, total=False):
    id: str
    evidence_id: str
    source_id: str
    locator: str
    quote: str
    url: str
    title: str
    trust_level: str
    publisher: str
    accessed_at: str


class AnalysisBlock(TypedDict, total=False):
    specialty: str
    content: str
    gaps: list[str]
    citation_ids: list[str]


class Budgets(TypedDict, total=False):
    max_tool_calls: int
    used_tool_calls: int
    max_tokens: int
    used_tokens: int
    max_web_pages: int
    used_web_pages: int


class InterruptRecord(TypedDict, total=False):
    id: str
    kind: str
    prompt: str
    options: list[str]
    resolution: str | None
    resolved: bool


class ReviewVerdict(TypedDict, total=False):
    verdict: str  # pass | reject | revise
    reasons: list[str]
    gaps: list[str]
    citation_issues: list[str]


class RuntimeEvent(TypedDict, total=False):
    type: str
    task_id: str
    payload: dict[str, Any]
    ts: str


class ToolTrace(TypedDict, total=False):
    tool: str
    args: dict[str, Any]
    result_summary: str
    ok: bool
    duration_ms: int


class TaskState(TypedDict, total=False):
    task_id: str
    thread_id: str
    goal: Goal
    plan: Plan
    evidence: Annotated[list[EvidenceItem], add_items]
    citations: Annotated[list[Citation], add_items]
    analysis_results: Annotated[dict[str, AnalysisBlock], merge_dict]
    result: str | None
    budgets: Budgets
    interrupts: Annotated[list[InterruptRecord], add_items]
    route: str | None
    status: TaskStatus
    messages: Annotated[list[AnyMessage], add_messages]
    events: Annotated[list[RuntimeEvent], add_items]
    tool_traces: Annotated[list[ToolTrace], add_items]
    review: ReviewVerdict | None
    meta: dict[str, Any]


def default_budgets() -> Budgets:
    return {
        "max_tool_calls": 40,
        "used_tool_calls": 0,
        "max_tokens": 200_000,
        "used_tokens": 0,
        "max_web_pages": 30,
        "used_web_pages": 0,
    }


def initial_state(
    task_id: str,
    raw_query: str,
    workflow: str = "deep_research",
    *,
    tia_export_dir: str | None = None,
    meta: dict[str, Any] | None = None,
) -> TaskState:
    export_dir = (tia_export_dir or "").strip()
    goal: dict[str, Any] = {
        "raw_query": raw_query,
        "workflow": workflow,
        "locale": "zh-CN",
    }
    if export_dir:
        goal["tia_export_dir"] = export_dir
    state_meta: dict[str, Any] = dict(meta or {})
    if export_dir:
        state_meta["plc_tia_export_dir"] = export_dir
    return {
        "task_id": task_id,
        "thread_id": task_id,
        "goal": goal,
        "plan": {"version": 1, "approved": False, "steps": []},
        "evidence": [],
        "citations": [],
        "analysis_results": {},
        "result": None,
        "budgets": default_budgets(),
        "interrupts": [],
        "route": None,
        "status": TaskStatus.PENDING.value,
        "messages": [],
        "events": [],
        "tool_traces": [],
        "review": None,
        "meta": state_meta,
    }


# Keep operator import used for potential future reducers
_ = operator.add
NotRequired  # re-export hint for callers
