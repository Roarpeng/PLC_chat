"""In-process hello.echo implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def hello_echo(message: str = "hello", *, task_id: str | None = None) -> dict[str, Any]:
    """Return structured JSON for the hello.echo tool."""
    return {
        "ok": True,
        "tool": "hello.echo",
        "message": message,
        "echo": f"echo:{message}",
        "task_id": task_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
