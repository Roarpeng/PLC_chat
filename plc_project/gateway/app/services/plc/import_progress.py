"""In-memory canvas-import progress (poll by progress_id).

Frontend posts ``progress_id`` with import/upload and polls
``GET /api/v1/plc/canvas/import/progress/{id}`` while the long Openness
export runs in a worker thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}
_TTL_S = 600.0


def report(progress_id: str | None, stage: str, message: str, **extra: Any) -> None:
    """Update progress for ``progress_id`` (no-op when id is empty)."""
    pid = (progress_id or "").strip()
    if not pid:
        return
    payload = {
        "progress_id": pid,
        "stage": stage,
        "message": message,
        "updated_at": time.time(),
        **extra,
    }
    with _lock:
        _store[pid] = payload


def get(progress_id: str) -> dict[str, Any] | None:
    pid = (progress_id or "").strip()
    if not pid:
        return None
    with _lock:
        _purge_locked()
        item = _store.get(pid)
        return dict(item) if item else None


def clear(progress_id: str | None) -> None:
    pid = (progress_id or "").strip()
    if not pid:
        return
    with _lock:
        _store.pop(pid, None)


def make_reporter(progress_id: str | None) -> Callable[..., None]:
    """Return a callback ``(stage, message, **extra)`` bound to ``progress_id``."""

    def _cb(stage: str, message: str, **extra: Any) -> None:
        report(progress_id, stage, message, **extra)

    return _cb


def _purge_locked() -> None:
    now = time.time()
    dead = [k for k, v in _store.items() if now - float(v.get("updated_at") or 0) > _TTL_S]
    for k in dead:
        _store.pop(k, None)
