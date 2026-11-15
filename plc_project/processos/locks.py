"""PLAN §4 租约式项目写锁（processos 侧，与 v2 网关 project_locks 语义对齐）。

锁语义（lease + 故障恢复 = 超时自动释放）：

- 一个项目同一时刻最多一个持有者；acquire 立即返回、不阻塞等待——
  被他人持有时返回 ``{ok: False, holder, expires_at}``，调用方映射 409
  ``LOCK_HELD``；
- 锁是带 ``expires_at`` 的租约（默认 900s）：持有者崩溃后无需人工清理，
  租约到期（按 utcnow 判定）即可被下一个请求夺取；损坏/无法解析的租约
  记录按已过期处理（可恢复，不造成永久死锁）；
- release 仅持有者本人可执行；renew 延长租约（仅持有者、未过期时）；
- 同一 owner 重复 acquire 是幂等重入：沿用原 lock_id 并刷新租约。

存储：默认进程内（dict + RLock）；传入 db 路径时持久化到 JsonDao
namespace ``"locks"``（每操作开短命 sqlite 连接，遵守本仓连接纪律），
进程重启后仍能看到未过期租约。API 路由层（app.py）对 patches /
deliveries / approve 三个变更端点自动 acquire → 请求结束 release（X-Lock-Owner
> X-Actor-Id > "anonymous"）；租约超时是崩溃场景的兜底恢复路径。
"""
from __future__ import annotations

import contextlib
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from processos.store.db import JsonDao, open_db

NAMESPACE = "locks"
DEFAULT_LEASE_SECONDS = 900
_LOCK_KIND = "lock"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse(ts: str) -> datetime:
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _validate_lease(lease_seconds: Any) -> float:
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) \
            or lease_seconds < 0:
        raise ValueError("lease_seconds must be a non-negative number")
    return float(lease_seconds)


def _clean_owner(owner: Any) -> str:
    text = str(owner or "").strip()
    return text or "anonymous"


class ProjectLockManager:
    """Lease-based single-writer locks per project (in-memory or JsonDao-backed)."""

    def __init__(self, db: str | None = None) -> None:
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()
        self._mem: dict[str, dict[str, Any]] = {}

    # ---- storage (short-lived connection per operation) ----------------------

    def _load(self, project_id: str) -> dict[str, Any] | None:
        if self._db is None:
            rec = self._mem.get(project_id)
            return dict(rec) if rec is not None else None
        with contextlib.closing(open_db(self._db)) as conn:
            row = JsonDao(conn, NAMESPACE).get(project_id)
        if row is None:
            return None
        return {k: v for k, v in row.items() if k not in ("id", "kind")}

    def _store(self, project_id: str, record: dict[str, Any] | None) -> None:
        if self._db is None:
            if record is None:
                self._mem.pop(project_id, None)
            else:
                self._mem[project_id] = dict(record)
            return
        with contextlib.closing(open_db(self._db)) as conn:
            dao = JsonDao(conn, NAMESPACE)
            if record is None:
                dao.delete(project_id)
            else:
                dao.put(project_id, _LOCK_KIND, dict(record))

    @staticmethod
    def _expired(record: dict[str, Any], now: datetime) -> bool:
        try:
            return _parse(str(record["expires_at"])) <= now
        except (KeyError, TypeError, ValueError):
            return True  # corrupt record: recoverable takeover, never a deadlock

    # ---- lease API ------------------------------------------------------------

    def acquire(self, project_id: str, owner: str,
                lease_seconds: float = DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
        owner = _clean_owner(owner)
        lease = _validate_lease(lease_seconds)
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._load(project_id)
            if record is not None and record.get("holder") != owner \
                    and not self._expired(record, now):
                return {"ok": False, "holder": record.get("holder", "UNKNOWN"),
                        "expires_at": record.get("expires_at", "UNKNOWN"),
                        "lock_id": record.get("lock_id", "")}
            reentrant = record is not None and record.get("holder") == owner
            lock_id = (record or {}).get("lock_id") if reentrant \
                else "LCK-" + uuid.uuid4().hex[:8]
            new_record = {
                "lock_id": lock_id, "holder": owner,
                "acquired_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=lease)),
            }
            self._store(project_id, new_record)
            return {"ok": True, "lock_id": lock_id, "holder": owner,
                    "expires_at": new_record["expires_at"]}

    def release(self, project_id: str, owner: str) -> dict[str, Any]:
        owner = _clean_owner(owner)
        with self._lock:
            record = self._load(project_id)
            if record is None:
                return {"ok": True, "released": False, "note": "no lock held"}
            if record.get("holder") != owner:
                return {"ok": False, "released": False,
                        "holder": record.get("holder", "UNKNOWN"),
                        "expires_at": record.get("expires_at", "UNKNOWN"),
                        "note": "only the holder may release"}
            self._store(project_id, None)
            return {"ok": True, "released": True, "lock_id": record.get("lock_id", "")}

    def renew(self, project_id: str, owner: str,
              lease_seconds: float = DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
        owner = _clean_owner(owner)
        lease = _validate_lease(lease_seconds)
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._load(project_id)
            if record is None or record.get("holder") != owner \
                    or self._expired(record, now):
                return {"ok": False, "released": False,
                        "holder": (record or {}).get("holder", "UNKNOWN"),
                        "expires_at": (record or {}).get("expires_at", "UNKNOWN"),
                        "note": "no live lease held by this owner"}
            record["expires_at"] = _iso(now + timedelta(seconds=lease))
            self._store(project_id, record)
            return {"ok": True, "lock_id": record.get("lock_id", ""),
                    "expires_at": record["expires_at"]}

    def status(self, project_id: str) -> dict[str, Any]:
        record = self._load(project_id)
        if record is None:
            return {"locked": False}
        expired = self._expired(record, datetime.now(timezone.utc))
        return {"locked": not expired, "expired": expired,
                "holder": record.get("holder", "UNKNOWN"),
                "lock_id": record.get("lock_id", ""),
                "expires_at": record.get("expires_at", "UNKNOWN")}
