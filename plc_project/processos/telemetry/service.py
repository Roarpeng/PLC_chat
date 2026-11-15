"""FC-15 · Read-only telemetry intake (PLAN §6.4 现场数据采集要求).

Lightweight ingest for field diagnostics: OT channel reads, manual uploads
(alarm screenshots / TIA diagnostics / engineer notes) and clearly-labelled
simulated data. Every event carries an explicit ``evidence_level`` and a
``quality`` flag; SIMULATED input is *forced* to quality=SIMULATED so mock
data can never masquerade as field evidence (PLAN §12).

Read-only semantics (FC-16 acceptance): collected events are immutable —
this service intentionally exposes NO delete/update/overwrite method and the
routes expose no such endpoint. 原件只读不覆盖。

Connection discipline: stores only a db path; one short-lived sqlite
connection per operation behind an RLock (FastAPI sync routes run on
thread-pool threads — a cached connection would raise sqlite3 errors).
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from typing import Any

from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "telemetry"

SOURCES: tuple[str, ...] = ("MANUAL_UPLOAD", "OT_CHANNEL", "SIMULATED")
EVIDENCE_BY_SOURCE: dict[str, str] = {
    "MANUAL_UPLOAD": "MANUAL",
    "OT_CHANNEL": "OT_READ",
    "SIMULATED": "SIMULATED",
}
DEFAULT_QUALITY: dict[str, str] = {
    "MANUAL_UPLOAD": "REPORTED",
    "OT_CHANNEL": "UNSPECIFIED",  # OT 帧未带质量位时不虚构 GOOD
    "SIMULATED": "SIMULATED",
}


class TelemetryService:
    """Append-only event store persisted in namespace ``telemetry``."""

    def __init__(self, db: str | Any | None = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "TelemetryService 需要数据库路径（或 None 走 PROCESSOS_DB/默认值），"
                "不接受常驻连接：FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误"
            )
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()

    def close(self) -> None:
        """No-op: operations use short-lived connections (no persistent handles)."""

    @contextlib.contextmanager
    def _session(self) -> Iterator[JsonDao]:
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            yield JsonDao(conn, NAMESPACE)

    def ingest(
        self,
        object_id: str,
        source: str,
        event_time: str,
        payload: dict[str, Any] | None,
        *,
        quality: str | None = None,
    ) -> dict[str, Any]:
        if source not in SOURCES:
            raise ValueError(f"source 必须是 {'|'.join(SOURCES)} 之一，收到: {source!r}")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError("object_id 不能为空")
        if not isinstance(event_time, str) or not event_time.strip():
            raise ValueError("event_time 不能为空（ISO-8601 带时区）")
        if source == "SIMULATED":
            # 诚实标注：模拟数据无论调用方给什么 quality，一律强制 SIMULATED（§12）。
            q: str = "SIMULATED"
        else:
            q = quality if quality is not None else DEFAULT_QUALITY[source]
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")
        event_id = "tel_" + uuid.uuid4().hex[:8]
        body: dict[str, Any] = {
            "event_id": event_id,
            "object_id": object_id,
            "source": source,
            "event_time": event_time,
            "payload": payload or {},
            "quality": q,
            "evidence_level": EVIDENCE_BY_SOURCE[source],
            "ingested_at": utcnow(),
        }
        with self._session() as dao:
            dao.put(event_id, "telemetry_event", body)
        return dict(body)

    def events_for(self, object_id: str) -> list[dict[str, Any]]:
        with self._session() as dao:
            rows = dao.list_by_kind("telemetry_event")
        selected = [self._strip(r) for r in rows if r.get("object_id") == object_id]
        selected.sort(key=lambda r: (r.get("event_time") or "", r.get("ingested_at") or "", r.get("event_id") or ""))
        return selected

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._session() as dao:
            row = dao.get(event_id)
        return self._strip(row) if row is not None else None

    @staticmethod
    def _strip(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k not in ("id", "kind")}

    # 刻意不提供 delete/update/overwrite：已采集事件原件只读（FC-16 验收）。
