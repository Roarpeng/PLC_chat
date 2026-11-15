"""FC-14 · CommissioningRecord ledger (PLAN §5.3 step 2).

A ``CommissioningLedger`` records what a CommissioningEngineer actually did
on site with the downloaded TIA archive: device, program checksum result,
time, operator, field tests and outcome. The ledger is append-only evidence
of a *manual* site action — writing a record never claims the PLC is online
by itself, and no record ever mutates engineering files.

Connection discipline (gateway v2 idiom): the service stores only a db path
and opens one short-lived sqlite connection per operation (guarded by an
in-process RLock), because FastAPI sync routes run on thread-pool threads —
a connection cached at construction time would raise sqlite3.ProgrammingError.
"""
from __future__ import annotations

import contextlib
import re
import threading
import uuid
from collections.abc import Iterator
from typing import Any

from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "commissioning"
RESULTS: tuple[str, ...] = ("COMMISSIONED", "FAILED", "ROLLED_BACK")

# artifact_sha256: bare 64-hex or sha256:-prefixed 64-hex (case-insensitive).
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


def valid_artifact_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.match(value.strip()))


def _normalize_tests(tests: Any) -> list[dict[str, Any]]:
    """Validate tests=[{name, passed, note?}] entries; raise ValueError on junk."""
    if tests is None:
        return []
    if not isinstance(tests, list):
        raise ValueError("tests 必须是 [{name, passed, note?}] 列表")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(tests):
        if not isinstance(item, dict):
            raise ValueError(f"tests[{i}] 必须是对象")
        name = item.get("name")
        passed = item.get("passed")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"tests[{i}].name 必须是非空字符串")
        if not isinstance(passed, bool):
            raise ValueError(f"tests[{i}].passed 必须是布尔值")
        entry: dict[str, Any] = {"name": name, "passed": passed}
        note = item.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise ValueError(f"tests[{i}].note 必须是字符串")
            entry["note"] = note
        out.append(entry)
    return out


class CommissioningLedger:
    """Append-only site-commissioning ledger persisted in namespace
    ``commissioning`` (JsonDao over the shared sqlite store)."""

    def __init__(self, db: str | Any | None = None) -> None:
        import sqlite3
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "CommissioningLedger 需要数据库路径（或 None 走 PROCESSOS_DB/默认值），"
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

    # ---- write path (append-only; no update/delete API on purpose) ----

    def record(
        self,
        project_id: str,
        build_id: str,
        artifact_sha256: str,
        device_id: str,
        operator: str,
        *,
        plc_checksum: str = "",
        commissioned_at: str | None = None,
        tests: list[dict[str, Any]] | None = None,
        result: str = "COMMISSIONED",
    ) -> dict[str, Any]:
        if not valid_artifact_sha256(artifact_sha256):
            raise ValueError(
                f"artifact_sha256 必须是 64 位十六进制 sha256（可带 sha256: 前缀），收到: {artifact_sha256!r}"
            )
        if result not in RESULTS:
            raise ValueError(f"result 必须是 {'|'.join(RESULTS)} 之一，收到: {result!r}")
        if not str(project_id or "").strip():
            raise ValueError("project_id 不能为空")
        if not str(build_id or "").strip():
            raise ValueError("build_id 不能为空")
        record_id = "dep_" + uuid.uuid4().hex[:8]
        body: dict[str, Any] = {
            "record_id": record_id,
            "project_id": project_id,
            "build_id": build_id,
            "artifact_sha256": artifact_sha256.strip(),
            "device_id": device_id,
            "operator": operator,
            # plc_checksum: TIA 现场程序校验结果，格式由工程师回填，不作 sha256 假设。
            "plc_checksum": plc_checksum,
            "commissioned_at": commissioned_at or utcnow(),
            "tests": _normalize_tests(tests),
            "result": result,
            "created_at": utcnow(),
        }
        with self._session() as dao:
            dao.put(record_id, "commissioning_record", body)
        return dict(body)

    # ---- read paths ----

    def records_for(self, project_id: str) -> list[dict[str, Any]]:
        with self._session() as dao:
            rows = dao.list_by_kind("commissioning_record")
        selected = [self._strip(r) for r in rows if r.get("project_id") == project_id]
        selected.sort(key=lambda r: (r.get("commissioned_at") or "", r.get("created_at") or "", r.get("record_id") or ""))
        return selected

    def get(self, record_id: str) -> dict[str, Any] | None:
        with self._session() as dao:
            row = dao.get(record_id)
        return self._strip(row) if row is not None else None

    @staticmethod
    def _strip(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k not in ("id", "kind")}
