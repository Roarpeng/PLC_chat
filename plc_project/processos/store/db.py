"""Shared SQLite helpers for ProcessOS ledgers.

Follows the v2 gateway idiom (``gateway/app/services/plc/workspace_v2.py``):
stdlib ``sqlite3`` + WAL, JSON bodies in a ``data`` column. Every statement is
an inline string literal at its execute call site with bound ``?`` parameters —
namespaces ride in a bound ``namespace`` column (single generic ``records``
table) instead of dynamic table names, so no SQL text is ever assembled. The
schema version lives in a meta record row, not in interpolated PRAGMAs.

The on-disk location comes from env ``PROCESSOS_DB`` (tests must pass an
explicit ``tmp_path`` — never write to the default path from unit tests).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROCESSOS_DB_ENV = "PROCESSOS_DB"
META_NAMESPACE = "__meta__"
SCHEMA_VERSION = 1  # bump on additive schema changes


def db_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the store file: explicit arg > env PROCESSOS_DB > default."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(PROCESSOS_DB_ENV, "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / ".processos" / "store.sqlite3"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema_version(conn: sqlite3.Connection) -> int:
    """Read the stored schema version (0 = fresh/empty database)."""
    row = conn.execute(
        "SELECT data FROM records WHERE namespace=? AND id=?",
        (META_NAMESPACE, "schema_version"),
    ).fetchone()
    return int(json.loads(row["data"])["version"]) if row else 0


def open_db(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open (and create) the store with WAL; idempotently ensure schema."""
    p = db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    # 完全静态的建表语句：所有服务共用一张 records 表，用 namespace 列隔离。
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            namespace  TEXT NOT NULL,
            id         TEXT NOT NULL,
            kind       TEXT NOT NULL,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(namespace, id)
        );
        CREATE INDEX IF NOT EXISTS idx_records_ns_kind ON records(namespace, kind);
        CREATE INDEX IF NOT EXISTS idx_records_ns_created ON records(namespace, created_at);
        """
    )
    if schema_version(conn) < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO records(namespace, id, kind, data, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(namespace, id) DO UPDATE SET "
            "data=excluded.data, updated_at=excluded.updated_at",
            (META_NAMESPACE, "schema_version", "meta",
             json.dumps({"version": SCHEMA_VERSION}), utcnow(), utcnow()),
        )
    conn.commit()
    return conn


class JsonDao:
    """Namespaced id/kind/data JSON records with upsert + kind scans.

    One instance owns one namespace (service-owned logical table); bodies live
    in the ``data`` JSON column, so additive field changes never migrate SQL.
    """

    def __init__(self, conn: sqlite3.Connection, namespace: str) -> None:
        self.conn = conn
        self.namespace = namespace

    def put(self, item_id: str, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(data, ensure_ascii=False, sort_keys=True)
        now = utcnow()
        self.conn.execute(
            "INSERT INTO records(namespace, id, kind, data, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(namespace, id) DO UPDATE SET "
            "kind=excluded.kind, data=excluded.data, updated_at=excluded.updated_at",
            (self.namespace, item_id, kind, body, now, now),
        )
        self.conn.commit()
        return {"id": item_id, "kind": kind, **data}

    def get(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, kind, data FROM records WHERE namespace=? AND id=?",
            (self.namespace, item_id),
        ).fetchone()
        return self._row(row)

    def list_by_kind(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is None:
            rows = self.conn.execute(
                "SELECT id, kind, data FROM records WHERE namespace=? ORDER BY created_at, id",
                (self.namespace,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, kind, data FROM records WHERE namespace=? AND kind=? "
                "ORDER BY created_at, id",
                (self.namespace, kind),
            ).fetchall()
        return [r for r in map(self._row, rows) if r is not None]

    def delete(self, item_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM records WHERE namespace=? AND id=?", (self.namespace, item_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def iter_all(self) -> Iterator[dict[str, Any]]:
        yield from self.list_by_kind()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {"id": row["id"], "kind": row["kind"], **json.loads(row["data"])}
