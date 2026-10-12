"""LangGraph StateGraph for ResearchOS Runtime — full agent pipeline."""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.planner import planner_node
from agents.registry import get_agent_registry
from agents.supervisor import supervisor_node
from runtime.researchos_runtime.checkpoint import create_checkpointer
from runtime.researchos_runtime.events import (
    interrupt_resolved_event,
    make_event,
    node_end,
    node_start,
)
from runtime.researchos_runtime.settings import get_settings
from runtime.researchos_runtime.state import TaskState, TaskStatus

logger = logging.getLogger("researchos.runtime.graph")

WORKER_AGENTS = (
    "research",
    "etl",
    "analysis",
    "citation",
    "reviewer",
    "writer",
    "memory",
    "plc",
)

RouteName = Literal[
    "supervisor",
    "planner",
    "research",
    "etl",
    "analysis",
    "citation",
    "reviewer",
    "writer",
    "memory",
    "plc",
    "human_interrupt",
    "end",
]


def _mark_step_status(plan: dict[str, Any], step_id: str | None, status: str) -> dict[str, Any]:
    if not step_id:
        return plan
    steps = []
    for step in plan.get("steps") or []:
        if step.get("id") == step_id:
            steps.append({**step, "status": status})
        else:
            steps.append(dict(step))
    return {**plan, "steps": steps}


def _current_step_for_agent(state: TaskState, agent_name: str) -> dict[str, Any] | None:
    plan = state.get("plan") or {}
    for step in plan.get("steps") or []:
        if step.get("status", "pending") != "pending":
            continue
        agent = str(step.get("agent") or "")
        base = agent.split(":", 1)[0]
        if base == agent_name:
            return step
    for step in plan.get("steps") or []:
        if step.get("status", "pending") == "pending":
            return step
    return None


def _wrap_agent(agent_name: str):
    """Wrap a registry agent so plan steps are marked and events are emitted."""

    def _node(state: TaskState) -> dict[str, Any]:
        task_id = state.get("task_id") or "unknown"
        step = _current_step_for_agent(state, agent_name)
        step_id = (step or {}).get("id")
        events = [node_start(task_id, agent_name, step_id=step_id)]

        registry = get_agent_registry()
        run_fn = registry[agent_name]
        updates = dict(run_fn(state) or {})

        # Agents may set a hint route; Supervisor is authoritative — clear for re-decide
        updates.pop("route", None)

        plan = dict(state.get("plan") or {})
        review = updates.get("review") if "review" in updates else state.get("review")

        if agent_name == "reviewer" and isinstance(review, dict) and review.get("verdict") == "reject":
            meta = dict(updates.get("meta") or state.get("meta") or {})
            retries = int(meta.get("review_retries") or 0) + 1
            meta["review_retries"] = retries
            if retries >= 2:
                # Exhausted retries — complete step and allow draft writer
                plan = _mark_step_status(plan, step_id, "completed")
                meta["writer_draft_mode"] = True
            else:
                # Reset research chain for one more pass
                reset_agents = {"research", "etl", "analysis", "citation", "reviewer", "plc"}
                plan = {
                    **plan,
                    "steps": [
                        {
                            **s,
                            "status": (
                                "pending"
                                if str(s.get("agent") or "").split(":", 1)[0] in reset_agents
                                else s.get("status", "pending")
                            ),
                        }
                        for s in (plan.get("steps") or [])
                    ],
                }
            updates["meta"] = meta
        else:
            plan = _mark_step_status(plan, step_id, "completed")

        updates["plan"] = plan
        prior_events = list(updates.get("events") or [])
        events.extend(prior_events)
        events.append(node_end(task_id, agent_name, step_id=step_id))
        updates["events"] = events
        return updates

    _node.__name__ = f"{agent_name}_node"
    return _node


def human_interrupt_node(state: TaskState) -> dict[str, Any]:
    """HITL node — pause via langgraph interrupt; apply resolution on resume."""
    from uuid import uuid4

    task_id = state.get("task_id") or "unknown"
    pending = None
    for item in reversed(state.get("interrupts") or []):
        if not item.get("resolved"):
            pending = item
            break

    if pending is None:
        pending = {
            "id": f"int_{uuid4().hex[:12]}",
            "kind": "clarification",
            "prompt": "Human input required",
            "options": ["continue", "abort"],
            "resolution": None,
            "resolved": False,
        }

    payload = {
        "interrupt_id": pending.get("id"),
        "kind": pending.get("kind"),
        "prompt": pending.get("prompt"),
        "options": pending.get("options") or [],
    }

    decision = interrupt(payload)

    resolution = "approve"
    if isinstance(decision, dict):
        resolution = str(
            decision.get("action")
            or decision.get("resolution")
            or decision.get("decision")
            or "approve"
        )
    elif decision is not None:
        resolution = str(decision)

    updates: dict[str, Any] = {
        "status": TaskStatus.RUNNING.value,
        "route": None,
        "events": [
            node_start(task_id, "human_interrupt"),
            interrupt_resolved_event(task_id, str(pending.get("id")), resolution),
            node_end(task_id, "human_interrupt", resolution=resolution),
        ],
        "interrupts": [
            {
                **pending,
                "resolution": resolution,
                "resolved": True,
            }
        ],
    }

    kind = pending.get("kind")
    if kind == "plan_approval":
        if resolution in {"approve", "approved", "yes"}:
            plan = dict(state.get("plan") or {})
            plan["approved"] = True
            updates["plan"] = plan
        elif resolution in {"abort", "cancel", "cancelled"}:
            updates["status"] = TaskStatus.CANCELLED.value
            updates["route"] = "end"
        elif resolution == "edit":
            plan = dict(state.get("plan") or {})
            plan["approved"] = False
            updates["plan"] = plan
    elif kind == "budget_exceeded":
        if resolution == "increase_budget":
            budgets = dict(state.get("budgets") or {})
            budgets["max_tool_calls"] = int(budgets.get("max_tool_calls") or 40) * 2
            budgets["max_tokens"] = int(budgets.get("max_tokens") or 200_000) * 2
            updates["budgets"] = budgets
        elif resolution in {"abort", "cancel"}:
            updates["status"] = TaskStatus.CANCELLED.value
            updates["route"] = "end"

    return updates


def end_node(state: TaskState) -> dict[str, Any]:
    task_id = state.get("task_id") or "unknown"
    status = state.get("status")
    if status not in {
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }:
        status = TaskStatus.COMPLETED.value
    return {
        "status": status,
        "route": "end",
        "events": [
            make_event(
                "final",
                task_id,
                {
                    "status": str(status),
                    "has_result": bool(state.get("result")),
                    "steps": len((state.get("plan") or {}).get("steps") or []),
                    "memory_write": bool((state.get("meta") or {}).get("memory_write")),
                },
            )
        ],
    }


def _route_from_supervisor(state: TaskState) -> str:
    route = state.get("route") or "end"
    allowed = {
        "planner",
        *WORKER_AGENTS,
        "human_interrupt",
        "end",
    }
    if route in allowed:
        return route
    # Legacy Phase-2 alias
    if route == "research_stub":
        return "research"
    return "end"


def _after_worker(state: TaskState) -> str:
    if state.get("status") in {TaskStatus.CANCELLED, TaskStatus.CANCELLED.value}:
        return "end"
    if state.get("route") == "end":
        return "end"
    return "supervisor"


def build_graph(checkpointer: Any | None = None) -> Any:
    """Compile the ResearchOS StateGraph with Phase 4 agents."""
    settings = get_settings()
    saver = checkpointer if checkpointer is not None else create_checkpointer(
        settings.database_url
    )

    graph = StateGraph(TaskState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    for name in WORKER_AGENTS:
        graph.add_node(name, _wrap_agent(name))
    graph.add_node("human_interrupt", human_interrupt_node)
    graph.add_node("end", end_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "planner": "planner",
            **{name: name for name in WORKER_AGENTS},
            "human_interrupt": "human_interrupt",
            "end": "end",
        },
    )
    graph.add_conditional_edges(
        "planner",
        _after_worker,
        {"supervisor": "supervisor", "end": "end"},
    )
    for name in WORKER_AGENTS:
        graph.add_conditional_edges(
            name,
            _after_worker,
            {"supervisor": "supervisor", "end": "end"},
        )
    graph.add_conditional_edges(
        "human_interrupt",
        _after_worker,
        {"supervisor": "supervisor", "end": "end"},
    )
    graph.add_edge("end", END)

    return graph.compile(checkpointer=saver)


_compiled = None


def get_compiled_graph(checkpointer: Any | None = None) -> Any:
    global _compiled
    if checkpointer is not None:
        return build_graph(checkpointer=checkpointer)
    if _compiled is None:
        _compiled = build_graph()
    return _compiled
