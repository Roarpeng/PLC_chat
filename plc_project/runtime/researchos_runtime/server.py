"""ResearchOS Runtime HTTP server — Phase 2 Agent Runtime API."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from runtime.researchos_runtime.events import make_event
from runtime.researchos_runtime.graph import get_compiled_graph
from runtime.researchos_runtime.settings import get_settings
from runtime.researchos_runtime.state import TaskStatus, initial_state

logger = logging.getLogger("researchos.runtime.server")

app = FastAPI(title="ResearchOS Runtime", version="0.1.0")

# task_id -> last known summary (checkpoint is authoritative when available)
_RUNS: dict[str, dict[str, Any]] = {}


class StartRunRequest(BaseModel):
    goal: str = Field(..., min_length=1, description="Raw research goal / query")
    workflow: str = "deep_research"
    task_id: str | None = None
    auto_approve: bool | None = None
    tia_export_dir: str | None = Field(
        default=None,
        description="Optional path to TIA Openness SimaticML export folder for PLC agent",
    )


class ResumeRequest(BaseModel):
    resolution: str | dict[str, Any] = "approve"
    interrupt_id: str | None = None


def _thread_config(task_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": task_id}}


def _state_summary(values: dict[str, Any]) -> dict[str, Any]:
    plan = values.get("plan") or {}
    return {
        "task_id": values.get("task_id"),
        "status": values.get("status"),
        "route": values.get("route"),
        "plan": {
            "version": plan.get("version"),
            "approved": plan.get("approved"),
            "summary": plan.get("summary"),
            "steps": plan.get("steps") or [],
        },
        "evidence_count": len(values.get("evidence") or []),
        "tool_traces": values.get("tool_traces") or [],
        "interrupts": values.get("interrupts") or [],
        "events": values.get("events") or [],
        "result": values.get("result"),
        "review": values.get("review"),
        "budgets": values.get("budgets"),
        "meta": values.get("meta") or {},
    }


def _extract_interrupts(result: dict[str, Any] | None, snap: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if result and result.get("__interrupt__"):
        for item in result["__interrupt__"]:
            value = getattr(item, "value", item)
            if isinstance(value, dict):
                out.append(value)
            else:
                out.append({"payload": value})
    interrupts = getattr(snap, "interrupts", None) or ()
    for item in interrupts:
        value = getattr(item, "value", None)
        if isinstance(value, dict) and value not in out:
            out.append(value)
    return out


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "researchos-runtime",
        "env": settings.env,
        "dev_auto_approve": settings.dev_auto_approve,
    }


@app.post("/runs")
def start_run(body: StartRunRequest) -> dict[str, Any]:
    settings = get_settings()
    task_id = body.task_id or f"tsk_{uuid.uuid4().hex[:16]}"
    if body.auto_approve is not None:
        # Per-request override via process env for supervisor helper
        import os

        os.environ["DEV_AUTO_APPROVE"] = "true" if body.auto_approve else "false"

    state = initial_state(
        task_id,
        body.goal,
        workflow=body.workflow,
        tia_export_dir=body.tia_export_dir,
    )
    state["status"] = TaskStatus.RUNNING.value
    state["events"] = [
        make_event("task_started", task_id, {"workflow": body.workflow})
    ]

    graph = get_compiled_graph()
    config = _thread_config(task_id)
    try:
        result = graph.invoke(state, config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("run failed task_id=%s", task_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    snap = graph.get_state(config)
    values = dict(snap.values or {})
    pending = _extract_interrupts(result if isinstance(result, dict) else None, snap)
    if pending:
        values["status"] = TaskStatus.WAITING_HUMAN.value

    summary = _state_summary(values)
    summary["pending_interrupts"] = pending
    summary["next"] = list(snap.next or ())
    _RUNS[task_id] = summary
    return summary


@app.get("/runs/{task_id}")
def get_run(task_id: str) -> dict[str, Any]:
    graph = get_compiled_graph()
    config = _thread_config(task_id)
    snap = graph.get_state(config)
    if snap is None or (not snap.values and task_id not in _RUNS):
        if task_id in _RUNS:
            return _RUNS[task_id]
        raise HTTPException(status_code=404, detail="run not found")
    values = dict(snap.values or {})
    summary = _state_summary(values)
    summary["pending_interrupts"] = _extract_interrupts(None, snap)
    summary["next"] = list(snap.next or ())
    if summary["pending_interrupts"]:
        summary["status"] = TaskStatus.WAITING_HUMAN.value
    _RUNS[task_id] = summary
    return summary


@app.post("/runs/{task_id}/resume")
def resume_run(task_id: str, body: ResumeRequest) -> dict[str, Any]:
    graph = get_compiled_graph()
    config = _thread_config(task_id)
    snap = graph.get_state(config)
    if snap is None or not snap.values:
        raise HTTPException(status_code=404, detail="run not found")
    if not snap.next and not getattr(snap, "interrupts", None):
        raise HTTPException(status_code=400, detail="run is not waiting for resume")

    if isinstance(body.resolution, dict):
        resume_value: Any = dict(body.resolution)
        if body.interrupt_id:
            resume_value.setdefault("interrupt_id", body.interrupt_id)
    else:
        resume_value = {
            "action": body.resolution,
            "resolution": body.resolution,
            "interrupt_id": body.interrupt_id,
        }

    try:
        result = graph.invoke(Command(resume=resume_value), config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("resume failed task_id=%s", task_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    snap = graph.get_state(config)
    values = dict(snap.values or {})
    pending = _extract_interrupts(result if isinstance(result, dict) else None, snap)
    if pending:
        values["status"] = TaskStatus.WAITING_HUMAN.value
    summary = _state_summary(values)
    summary["pending_interrupts"] = pending
    summary["next"] = list(snap.next or ())
    _RUNS[task_id] = summary
    return summary


@app.post("/runs/{task_id}/cancel")
def cancel_run(task_id: str) -> dict[str, Any]:
    graph = get_compiled_graph()
    config = _thread_config(task_id)
    snap = graph.get_state(config)
    if snap is None or (not snap.values and task_id not in _RUNS):
        raise HTTPException(status_code=404, detail="run not found")

    values = dict(snap.values or {}) if snap.values else dict(_RUNS.get(task_id) or {})
    values["status"] = TaskStatus.CANCELLED.value
    values["route"] = "end"
    _RUNS[task_id] = {
        "task_id": task_id,
        "status": TaskStatus.CANCELLED.value,
        "result": values.get("result"),
        "events": values.get("events") or [],
    }
    return {"task_id": task_id, "status": "cancelled"}


def run() -> None:
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    uvicorn.run(
        "runtime.researchos_runtime.server:app",
        host=settings.runtime_host,
        port=settings.runtime_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
