"""In-memory stores for Phase 1 stubs (sessions / tasks / knowledge)."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.spaces: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, dict[str, Any]] = {}
        self.api_keys: dict[str, dict[str, Any]] = {}
        self.plc_jobs: dict[str, dict[str, Any]] = {}


store = InMemoryStore()


def new_session(
    *,
    user_id: str,
    workspace_id: str,
    title: str | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    now = _now()
    session = {
        "id": _id("ses"),
        "user_id": user_id,
        "workspace_id": workspace_id,
        "title": title,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }
    with store._lock:
        store.sessions[session["id"]] = session
    return session


def new_task(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    task_id = _id("tsk")
    task = {
        "id": task_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        **payload,
        "stream": {
            "ws_url": f"/api/v1/ws/research/{task_id}",
            "sse_url": f"/api/v1/research/tasks/{task_id}/events",
        },
        "result": None,
        "error": None,
    }
    with store._lock:
        store.tasks[task_id] = task
    return task


def new_space(
    *,
    name: str,
    workspace_id: str | None,
    description: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    space = {
        "id": _id("kb"),
        "name": name,
        "description": description,
        "status": "ready",
        "document_count": 0,
        "documents": [],
        "workspace_id": workspace_id,
        "settings": settings or {},
        "created_at": _now(),
    }
    with store._lock:
        store.spaces[space["id"]] = space
    return space
