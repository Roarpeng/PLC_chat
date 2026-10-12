"""Planner Agent — rule-based multi-step plans (optional LiteLLM)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from runtime.researchos_runtime.events import node_end, node_start
from runtime.researchos_runtime.state import Plan, PlanStep, TaskState

logger = logging.getLogger("researchos.agents.planner")


DEFAULT_STEPS: list[tuple[str, str, str]] = [
    ("S1", "Gather evidence", "research"),
    ("S2", "ETL ingest knowledge", "etl"),
    ("S3", "Domain analysis", "analysis"),
    ("S4", "Normalize citations", "citation"),
    ("S5", "Quality review", "reviewer"),
    ("S6", "Write report", "writer"),
    ("S7", "Persist memory", "memory"),
]

# Industrial mode (Phase 5): ETL right after research, then read-only PLC
# manual cross-reference so knowledge + manuals both precede analysis.
INDUSTRIAL_STEPS: list[tuple[str, str, str]] = [
    ("S1", "Gather evidence", "research"),
    ("S2", "ETL ingest knowledge", "etl"),
    ("S3", "PLC manual cross-reference", "plc"),
    ("S4", "Domain analysis", "analysis"),
    ("S5", "Normalize citations", "citation"),
    ("S6", "Quality review", "reviewer"),
    ("S7", "Write report", "writer"),
    ("S8", "Persist memory", "memory"),
]

# Continuous Learning (Phase: incremental signals) — lightweight pipeline:
# ingest already-gathered evidence (no-op when absent), delta analysis, memory.
# No writer/report so a subscription batch stays cheap.
CONTINUOUS_LEARNING_STEPS: list[tuple[str, str, str]] = [
    ("S1", "ETL ingest batch", "etl"),
    ("S2", "Delta analysis (reviews/specs)", "analysis"),
    ("S3", "Persist memory", "memory"),
]


def _steps_for_workflow(workflow: str) -> list[tuple[str, str, str]]:
    wf = str(workflow or "").strip().lower()
    if wf in {"industrial", "engineering"}:
        return INDUSTRIAL_STEPS
    if wf in {"continuous_learning", "rss_update", "incremental"}:
        return CONTINUOUS_LEARNING_STEPS
    return DEFAULT_STEPS


def build_rule_based_plan(
    raw_query: str, *, version: int = 1, workflow: str = "deep_research"
) -> Plan:
    """Produce a rule-based plan for the requested workflow."""
    query = (raw_query or "").strip() or "Untitled research goal"
    wf = str(workflow or "").strip().lower() or "deep_research"
    steps: list[PlanStep] = []
    prev_id: str | None = None
    for step_id, title, agent in _steps_for_workflow(wf):
        step: PlanStep = {
            "id": step_id,
            "title": title,
            "agent": agent,
            "status": "pending",
            "depends_on": [prev_id] if prev_id else [],
            "notes": "",
        }
        steps.append(step)
        prev_id = step_id

    return {
        "version": version,
        "approved": False,
        "summary": f"[{wf}] Plan for: {query[:200]}",
        "steps": steps,
    }


def _try_llm_plan(raw_query: str, *, version: int) -> Plan | None:
    base = os.getenv("LITELLM_BASE_URL", "").strip()
    if not base:
        return None
    model = os.getenv("LITELLM_DEFAULT_MODEL", "default")
    api_key = os.getenv("LITELLM_MASTER_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    prompt = (
        "Return ONLY JSON with keys summary (str) and steps "
        "(list of {id,title,agent,depends_on}). "
        "Agents must be among: research, etl, analysis, citation, reviewer, writer, memory, plc. "
        f"Goal: {raw_query}"
    )
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"{base.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a research planner."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            # Strip optional markdown fences
            text = content.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            data = json.loads(text)
            steps_in = data.get("steps") or []
            steps: list[PlanStep] = []
            for i, s in enumerate(steps_in):
                steps.append(
                    {
                        "id": str(s.get("id") or f"S{i + 1}"),
                        "title": str(s.get("title") or f"Step {i + 1}"),
                        "agent": str(s.get("agent") or "research"),
                        "status": "pending",
                        "depends_on": list(s.get("depends_on") or []),
                        "notes": "",
                    }
                )
            if not steps:
                return None
            return {
                "version": version,
                "approved": False,
                "summary": str(data.get("summary") or f"Plan for: {raw_query[:200]}"),
                "steps": steps,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("LiteLLM planner failed, using rule-based plan: %s", exc)
        return None


def plan_from_goal(state: TaskState) -> Plan:
    goal = state.get("goal") or {}
    raw_query = str(goal.get("raw_query") or "")
    workflow = str(goal.get("workflow") or "deep_research")
    current = state.get("plan") or {}
    version = int(current.get("version") or 0) + 1
    llm_plan = _try_llm_plan(raw_query, version=version)
    if llm_plan is not None:
        return llm_plan
    return build_rule_based_plan(raw_query, version=version, workflow=workflow)


def planner_node(state: TaskState) -> dict[str, Any]:
    task_id = state.get("task_id") or "unknown"
    plan = plan_from_goal(state)
    goal = dict(state.get("goal") or {})
    if not goal.get("normalized_objective"):
        goal["normalized_objective"] = str(goal.get("raw_query") or "").strip()

    return {
        "plan": plan,
        "goal": goal,
        "route": None,
        "events": [
            node_start(task_id, "planner"),
            node_end(
                task_id,
                "planner",
                steps=len(plan.get("steps") or []),
                summary=plan.get("summary"),
            ),
        ],
    }


__all__ = ["build_rule_based_plan", "plan_from_goal", "planner_node"]
