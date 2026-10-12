"""Supervisor Agent — sole routing authority for ResearchOS Runtime."""

from __future__ import annotations

import os
from typing import Any

from runtime.researchos_runtime.events import make_event, new_interrupt_id, node_end, node_start
from runtime.researchos_runtime.state import TaskState, TaskStatus


KNOWN_WORKER_ROUTES = {
    "planner",
    "research",
    "research_stub",
    "etl",
    "analysis",
    "citation",
    "reviewer",
    "writer",
    "memory",
    "plc",
    "human_interrupt",
    "end",
}

# Map plan agent names onto LangGraph node ids
AGENT_TO_NODE = {
    "planner": "planner",
    "research": "research",
    "research_stub": "research",
    "etl": "etl",
    "analysis": "analysis",
    "citation": "citation",
    "reviewer": "reviewer",
    "writer": "writer",
    "memory": "memory",
    "plc": "plc",
    "human_interrupt": "human_interrupt",
    "end": "end",
}


def _auto_approve_enabled() -> bool:
    raw = os.getenv("DEV_AUTO_APPROVE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _budget_exhausted(state: TaskState) -> bool:
    budgets = state.get("budgets") or {}
    checks = (
        ("used_tool_calls", "max_tool_calls"),
        ("used_tokens", "max_tokens"),
        ("used_web_pages", "max_web_pages"),
    )
    for used_key, max_key in checks:
        used = int(budgets.get(used_key) or 0)
        maximum = int(budgets.get(max_key) or 0)
        if maximum > 0 and used >= maximum:
            return True
    return False


def _plan_steps(state: TaskState) -> list[dict[str, Any]]:
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    return list(steps)


def _has_plan(state: TaskState) -> bool:
    return bool(_plan_steps(state))


def _plan_approved(state: TaskState) -> bool:
    plan = state.get("plan") or {}
    return bool(plan.get("approved"))


def _deps_satisfied(step: dict[str, Any], steps_by_id: dict[str, dict[str, Any]]) -> bool:
    for dep in step.get("depends_on") or []:
        dep_step = steps_by_id.get(dep)
        if not dep_step or dep_step.get("status") != "completed":
            return False
    return True


def next_executable_step(state: TaskState) -> dict[str, Any] | None:
    steps = _plan_steps(state)
    by_id = {s.get("id"): s for s in steps if s.get("id")}
    for step in steps:
        if step.get("status", "pending") != "pending":
            continue
        if _deps_satisfied(step, by_id):
            return step
    return None


# --- deep_research multi-round extension -------------------------------------

# Analysis gaps that indicate evidence deficiency and therefore justify one
# extra directed research round. Citation-only gaps are left to the Reviewer.
_HIGH_PRIORITY_GAP_MARKERS = (
    "missing_",
    "thin_evidence",
    "insufficient",
    "no evidence",
)


def _max_research_rounds(meta: dict[str, Any]) -> int:
    """Resolve max_research_rounds: meta override first, then env, default 1."""
    if "max_research_rounds" in meta:
        try:
            return max(0, int(meta.get("max_research_rounds") or 0))
        except (TypeError, ValueError):
            return 0
    raw = os.getenv("DEEP_RESEARCH_ROUNDS", "1")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 1


def _is_high_priority_gap(gap: str) -> bool:
    text = (gap or "").strip().lower()
    return any(marker in text for marker in _HIGH_PRIORITY_GAP_MARKERS)


def _high_priority_gaps(analysis_results: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for block in (analysis_results or {}).values():
        for gap in (block or {}).get("gaps") or []:
            if _is_high_priority_gap(str(gap)):
                found.append(str(gap))
    return found


def _analysis_steps_completed(steps: list[dict[str, Any]]) -> bool:
    analysis_steps = [
        s
        for s in steps
        if str(s.get("agent") or "").split(":", 1)[0] == "analysis"
    ]
    return bool(analysis_steps) and all(
        s.get("status") == "completed" for s in analysis_steps
    )


def _insert_research_round(
    steps: list[dict[str, Any]], *, round_number: int, gap_hint: str
) -> list[dict[str, Any]]:
    """Insert R{round_number} (agent=research) before the first citation step and
    reset that citation step and every later step back to pending."""
    out: list[dict[str, Any]] = []
    inserted = False
    prev_id: str | None = None
    for step in steps:
        base = str(step.get("agent") or "").split(":", 1)[0]
        if not inserted and base == "citation":
            out.append(
                {
                    "id": f"R{round_number}",
                    "title": f"Directed research round {round_number}",
                    "agent": "research",
                    "status": "pending",
                    "depends_on": [prev_id] if prev_id else [],
                    "notes": (
                        f"deep_research follow-up; gaps: {gap_hint}"
                        if gap_hint
                        else "deep_research follow-up for high-priority gaps"
                    ),
                }
            )
            inserted = True
        if inserted:
            out.append({**step, "status": "pending"})
        else:
            out.append(dict(step))
        prev_id = step.get("id")
    return out


def plan_deep_research_round(
    state: TaskState, *, max_rounds: int | None = None
) -> dict[str, Any] | None:
    """Return plan/meta deltas to append a directed research round, or None.

    Applies only to the ``deep_research`` workflow when every analysis step has
    completed, high-priority analysis gaps remain, and the insertion budget
    (``meta.deep_research_round`` < ``max_research_rounds``) is not exhausted.
    Returns ``{"plan": new_plan, "meta": {"deep_research_round": round}}`` where
    ``round`` is the newly incremented counter, or ``None`` when nothing changes.
    """
    goal = state.get("goal") or {}
    if str(goal.get("workflow") or "").strip().lower() != "deep_research":
        return None
    plan = state.get("plan") or {}
    steps = list(plan.get("steps") or [])
    meta = dict(state.get("meta") or {})
    if max_rounds is None:
        max_rounds = _max_research_rounds(meta)
    round_no = int(meta.get("deep_research_round") or 0)
    if round_no >= max_rounds:
        return None
    if not _analysis_steps_completed(steps):
        return None
    gaps = _high_priority_gaps(state.get("analysis_results") or {})
    if not gaps:
        return None
    next_round = round_no + 1
    new_steps = _insert_research_round(
        steps, round_number=next_round, gap_hint="; ".join(gaps)[:160]
    )
    return {
        "plan": {**plan, "steps": new_steps},
        "meta": {"deep_research_round": next_round},
    }


def decide_route(state: TaskState, *, auto_approve: bool | None = None) -> tuple[str, dict[str, Any]]:
    """Return (route, side_effects) without mutating status for interrupt payload.

    side_effects may include:
      - approve_plan: bool
      - interrupt: InterruptRecord dict
      - status: TaskStatus
      - reason: str
    """
    auto = _auto_approve_enabled() if auto_approve is None else auto_approve
    side: dict[str, Any] = {}

    status = state.get("status")
    if status == TaskStatus.WAITING_HUMAN or status == TaskStatus.WAITING_HUMAN.value:
        side["reason"] = "waiting_human"
        return "human_interrupt", side

    # Unresolved interrupts (append-only: a later resolved twin with same id clears it)
    items = list(state.get("interrupts") or [])
    resolved_ids = {i.get("id") for i in items if i.get("resolved") and i.get("id")}
    unresolved = [
        i for i in items if not i.get("resolved") and i.get("id") not in resolved_ids
    ]
    if unresolved:
        side["reason"] = "unresolved_interrupt"
        return "human_interrupt", side

    if _budget_exhausted(state):
        interrupt = {
            "id": new_interrupt_id(),
            "kind": "budget_exceeded",
            "prompt": "Tool/token budget exhausted. Increase budget or shrink scope?",
            "options": ["increase_budget", "shrink_scope", "deliver_partial", "abort"],
            "resolution": None,
            "resolved": False,
        }
        side["interrupt"] = interrupt
        side["status"] = TaskStatus.WAITING_HUMAN.value
        side["reason"] = "budget_exhausted"
        return "human_interrupt", side

    hops = int((state.get("meta") or {}).get("supervisor_hops") or 0)
    max_hops = int((state.get("meta") or {}).get("max_supervisor_hops") or 32)
    if hops >= max_hops:
        side["status"] = TaskStatus.FAILED.value
        side["reason"] = "max_supervisor_hops"
        return "end", side

    if not _has_plan(state):
        side["reason"] = "no_plan"
        return "planner", side

    if not _plan_approved(state):
        if auto:
            side["approve_plan"] = True
            side["reason"] = "auto_approve"
            # Fall through to next step after approval
        else:
            interrupt = {
                "id": new_interrupt_id(),
                "kind": "plan_approval",
                "prompt": "Approve the research plan?",
                "options": ["approve", "edit", "abort"],
                "resolution": None,
                "resolved": False,
            }
            side["interrupt"] = interrupt
            side["status"] = TaskStatus.WAITING_HUMAN.value
            side["reason"] = "plan_approval"
            return "human_interrupt", side

    # After auto-approve, treat as approved for step selection
    effective = dict(state)
    if side.get("approve_plan"):
        plan = dict(state.get("plan") or {})
        plan["approved"] = True
        effective["plan"] = plan

    # deep_research: append a directed research round when analysis is complete
    # but high-priority gaps remain and the round budget allows.
    extension = plan_deep_research_round(effective)  # type: ignore[arg-type]
    if extension is not None:
        effective = {
            **effective,
            "plan": extension["plan"],
            "meta": {**(effective.get("meta") or {}), **(extension.get("meta") or {})},
        }
        side["plan"] = extension["plan"]
        side["meta"] = extension["meta"]

    step = next_executable_step(effective)  # type: ignore[arg-type]
    if step:
        agent = str(step.get("agent") or "research")
        # Strip specialty suffix e.g. analysis:competitors
        base = agent.split(":", 1)[0]
        route = AGENT_TO_NODE.get(base, "research")
        side["reason"] = f"next_step:{step.get('id')}"
        side["step_id"] = step.get("id")
        side["agent"] = agent
        return route, side

    # All planned steps done — still require a result when writer ran
    if state.get("result"):
        side["reason"] = "done_with_result"
        side["status"] = TaskStatus.COMPLETED.value
        return "end", side

    side["reason"] = "no_pending_steps"
    side["status"] = TaskStatus.COMPLETED.value
    return "end", side


def supervisor_node(state: TaskState) -> dict[str, Any]:
    """LangGraph node: decide next route and emit events."""
    task_id = state.get("task_id") or "unknown"
    updates: dict[str, Any] = {
        "events": [node_start(task_id, "supervisor")],
        "status": TaskStatus.RUNNING.value,
    }

    meta = dict(state.get("meta") or {})
    hops = int(meta.get("supervisor_hops") or 0) + 1
    meta["supervisor_hops"] = hops
    if "max_supervisor_hops" not in meta:
        meta["max_supervisor_hops"] = int(os.getenv("MAX_SUPERVISOR_HOPS", "32"))
    if "max_research_rounds" not in meta:
        meta["max_research_rounds"] = _max_research_rounds(meta)
    updates["meta"] = meta

    route, side = decide_route(state)

    if side.get("approve_plan"):
        plan = dict(state.get("plan") or {})
        plan["approved"] = True
        updates["plan"] = plan
        # Re-decide after approval so we don't loop on approve forever
        state_after = {**state, "plan": plan, "meta": meta}
        route, side = decide_route(state_after, auto_approve=True)

    if side.get("plan") is not None:
        updates["plan"] = side["plan"]
    if side.get("meta"):
        updates["meta"] = {**(updates.get("meta") or {}), **side["meta"]}

    if side.get("interrupt"):
        updates["interrupts"] = [side["interrupt"]]
        updates["events"] = updates.get("events", []) + [
            make_event(
                "interrupt",
                task_id,
                {
                    "interrupt_id": side["interrupt"]["id"],
                    "interrupt_type": side["interrupt"]["kind"],
                    "prompt": side["interrupt"]["prompt"],
                    "options": side["interrupt"].get("options") or [],
                },
                agent="supervisor",
            )
        ]

    if side.get("status"):
        updates["status"] = side["status"]

    updates["route"] = route
    updates["events"] = updates.get("events", []) + [
        node_end(
            task_id,
            "supervisor",
            route=route,
            reason=side.get("reason"),
            step_id=side.get("step_id"),
        )
    ]
    return updates


__all__ = [
    "AGENT_TO_NODE",
    "decide_route",
    "next_executable_step",
    "plan_deep_research_round",
    "supervisor_node",
]
