"""Server-side chat session store: history follows the account, not the browser.

会话历史此前只存浏览器 localStorage——换浏览器/清缓存即"丢历史"。本模块把
会话持久化到网关文件系统(``PLC_WORK_DIR/sessions/<id>/``),提供轻量 meta 列表
与整会话读写,前端启动时合并、变更时防抖推送。

存储布局::

    sessions/<id>/meta.json      # id/title/createdAt/updatedAt/msgCount(列表只读这个)
    sessions/<id>/session.json   # 完整会话(messages + canvas 快照)

写入为 temp+rename 原子替换;读列表只解析 meta,单会话体积(含 89 块画布
~2MB)不拖慢列表。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_SESSION_BYTES = 20 * 1024 * 1024  # 单会话 20MB 上限,防异常画布撑爆磁盘


def sessions_root(settings: Any | None = None) -> Path:
    work = ""
    if settings is not None:
        work = str(getattr(settings, "plc_work_dir", "") or "").strip()
    if not work:
        work = os.getenv("PLC_WORK_DIR", "").strip()
    base = Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"
    root = base / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _valid_id(session_id: str) -> bool:
    return bool(_SESSION_ID_RE.match(session_id or ""))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _meta_from_session(session: dict[str, Any]) -> dict[str, Any]:
    msgs = session.get("messages")
    return {
        "id": str(session.get("id") or ""),
        "title": str(session.get("title") or "")[:120],
        "createdAt": session.get("createdAt") or 0,
        "updatedAt": session.get("updatedAt") or 0,
        "msgCount": len(msgs) if isinstance(msgs, list) else 0,
    }


def list_sessions(settings: Any | None = None) -> list[dict[str, Any]]:
    """全部会话 meta,按 updatedAt 降序;坏文件跳过不炸列表。"""
    metas: list[dict[str, Any]] = []
    for meta_file in sessions_root(settings).glob("*/meta.json"):
        try:
            metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    metas.sort(key=lambda m: (-(float(m.get("updatedAt") or 0)), str(m.get("id"))))
    return metas


def _tombstones_path(settings: Any | None = None) -> Path:
    return sessions_root(settings) / "_deleted.json"


def list_tombstones(settings: Any | None = None) -> dict[str, float]:
    """删除墓碑 {session_id: deleted_at}。同步方据此刻意丢弃本地副本且不再上传,
    解决"删除后从其他设备的陈旧本地副本复活"的问题。"""
    try:
        data = json.loads(_tombstones_path(settings).read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_tombstone(session_id: str, settings: Any | None = None) -> None:
    if not _valid_id(session_id):
        return
    tombstones = list_tombstones(settings)
    tombstones[session_id] = _now_ts()
    _atomic_write(_tombstones_path(settings), json.dumps(tombstones, ensure_ascii=False))


def clear_tombstone(session_id: str, settings: Any | None = None) -> None:
    """会话被重新创建(同 id 复活)时清除墓碑。"""
    tombstones = list_tombstones(settings)
    if session_id in tombstones:
        tombstones.pop(session_id)
        _atomic_write(_tombstones_path(settings), json.dumps(tombstones, ensure_ascii=False))


def get_session(session_id: str, settings: Any | None = None) -> dict[str, Any] | None:
    if not _valid_id(session_id):
        return None
    path = sessions_root(settings) / session_id / "session.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def put_session(session: dict[str, Any], settings: Any | None = None) -> dict[str, Any]:
    """整会话 upsert。非法 id / 缺字段拒绝;超限拒绝。"""
    sid = str((session or {}).get("id") or "")
    if not _valid_id(sid):
        raise ValueError("session.id invalid")
    if not isinstance(session.get("messages"), list) or not isinstance(session.get("canvas"), dict):
        raise ValueError("session.messages/canvas required")
    payload = json.dumps(session, ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_SESSION_BYTES:
        raise ValueError("session too large (>20MB)")
    root = sessions_root(settings) / sid
    _atomic_write(root / "session.json", payload)
    meta = _meta_from_session(session)
    _atomic_write(root / "meta.json", json.dumps(meta, ensure_ascii=False))
    # 同 id 重新创建 = 合法复活,清除墓碑
    clear_tombstone(sid, settings)
    return meta


def _now_ts() -> float:
    import time

    return time.time()


def delete_session(session_id: str, settings: Any | None = None) -> bool:
    if not _valid_id(session_id):
        return False
    # 先写墓碑再删目录:即使目录不存在(已在别处删过),墓碑也持续阻止
    # 陈旧副本重新上传。
    record_tombstone(session_id, settings)
    import shutil

    path = sessions_root(settings) / session_id
    if not path.is_dir():
        return True
    shutil.rmtree(path, ignore_errors=True)
    return True
