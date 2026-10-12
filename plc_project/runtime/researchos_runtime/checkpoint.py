"""Checkpointer factory — MemorySaver by default; Postgres when DATABASE_URL is set."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, urlunparse

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("researchos.runtime.checkpoint")

_postgres_cm: Any = None
_postgres_saver: Any = None


def normalize_postgres_url(url: str) -> str:
    """Convert SQLAlchemy-style URLs to psycopg-compatible DSN."""
    raw = url.strip()
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgres+asyncpg://"):
        if raw.startswith(prefix):
            raw = "postgresql://" + raw.split("://", 1)[1]
            break
    parsed = urlparse(raw)
    if parsed.scheme in ("postgres", "postgresql"):
        return urlunparse(parsed)
    return raw


def create_checkpointer(database_url: str | None = None) -> Any:
    """Return a LangGraph checkpointer.

    Prefers Postgres when DATABASE_URL is available; falls back to MemorySaver
    on missing URL or connection/setup errors.
    """
    global _postgres_cm, _postgres_saver

    if not database_url:
        logger.info("checkpointer=MemorySaver (no DATABASE_URL)")
        return MemorySaver()

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError:
        logger.warning("langgraph-checkpoint-postgres missing; using MemorySaver")
        return MemorySaver()

    dsn = normalize_postgres_url(database_url)
    try:
        # Keep the context manager alive for process lifetime.
        if _postgres_saver is not None:
            return _postgres_saver
        _postgres_cm = PostgresSaver.from_conn_string(dsn)
        saver = _postgres_cm.__enter__()
        saver.setup()
        _postgres_saver = saver
        logger.info("checkpointer=PostgresSaver")
        return saver
    except Exception as exc:  # noqa: BLE001 — graceful fallback is intentional
        logger.warning("Postgres checkpointer unavailable (%s); using MemorySaver", exc)
        return MemorySaver()
