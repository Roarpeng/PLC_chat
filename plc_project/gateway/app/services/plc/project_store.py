"""Server-side Project / Conversation store(契约 docs/25 §1 · P 线).

Session 时代消息与画布耦合在同一实体;Gemini 式重构把工程提升为一等容器:
Project 持有唯一权威画布,Conversation 只挂消息流,多个对话共享一张画布。
旧 ``sessions/`` 目录保留为迁移源,`migrate_from_sessions()` 幂等搬入新结构。

存储布局(风格对齐 ``session_store.py``)::

    projects/<id>/meta.json              # id/name/updated_at/conversation_count(列表只读这个)
    projects/<id>/project.json           # 完整(project_name/canvas/created_at/updated_at)
    conversations/<id>/meta.json         # id/project_id/title/updated_at
    conversations/<id>/conversation.json # created_at + messages(绝不存画布)

写入为 temp+rename 原子替换;读列表只解析 meta;坏文件跳过不炸列表;
``delete_project`` 级联删除其全部 conversations;conversation 增删会同步
所属工程的 ``conversation_count``。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_BYTES = 20 * 1024 * 1024  # 单对象 20MB 上限(画布可到 ~2MB,防异常撑爆磁盘)
_UNNAMED = "未命名工程"


def _base_dir(settings: Any | None = None) -> Path:
    work = ""
    if settings is not None:
        work = str(getattr(settings, "plc_work_dir", "") or "").strip()
    if not work:
        work = os.getenv("PLC_WORK_DIR", "").strip()
    return Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"


def projects_root(settings: Any | None = None) -> Path:
    root = _base_dir(settings) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def conversations_root(settings: Any | None = None) -> Path:
    root = _base_dir(settings) / "conversations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _valid_id(entity_id: str) -> bool:
    return bool(_ID_RE.match(entity_id or ""))


def new_project_id() -> str:
    """``prj-<hex12>``(契约 §1)。"""
    return f"prj-{uuid.uuid4().hex[:12]}"


def new_conversation_id() -> str:
    """``cv-<hex12>``(契约 §1)。"""
    return f"cv-{uuid.uuid4().hex[:12]}"


def _now_ts() -> float:
    return time.time()


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


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _blank_canvas(project_name: str) -> dict[str, Any]:
    return {"project_name": project_name, "blocks": {}, "hmi_widgets": {}, "tags": {}}


# ---------------- Project CRUD ----------------


def _all_conversation_metas(settings: Any | None = None) -> list[dict[str, Any]]:
    metas: list[dict[str, Any]] = []
    for meta_file in conversations_root(settings).glob("*/meta.json"):
        meta = _read_json(meta_file)
        if meta is not None:
            metas.append(meta)
    return metas


def _conversation_count(project_id: str, settings: Any | None = None) -> int:
    return sum(1 for m in _all_conversation_metas(settings) if str(m.get("project_id") or "") == project_id)


def _write_project_meta(full: dict[str, Any], settings: Any | None = None) -> dict[str, Any]:
    pid = str(full["id"])
    meta = {
        "id": pid,
        "name": str(full.get("project_name") or ""),
        "updated_at": float(full.get("updated_at") or 0.0),
        "conversation_count": _conversation_count(pid, settings),
    }
    _atomic_write(
        projects_root(settings) / pid / "meta.json", json.dumps(meta, ensure_ascii=False)
    )
    return meta


def _refresh_project_meta(project_id: str, settings: Any | None = None) -> None:
    """conversation 增删后只重算所属工程的 count(不动 project.json / updated_at)。"""
    if not _valid_id(project_id):
        return
    meta = _read_json(projects_root(settings) / project_id / "meta.json")
    if meta is None:
        return  # 孤儿对话(工程已删/未建):容忍,不计入任何工程
    meta["conversation_count"] = _conversation_count(project_id, settings)
    _atomic_write(
        projects_root(settings) / project_id / "meta.json",
        json.dumps(meta, ensure_ascii=False),
    )


def list_projects(settings: Any | None = None) -> list[dict[str, Any]]:
    """全部工程 meta,按 updated_at 降序;坏文件跳过不炸列表。"""
    metas: list[dict[str, Any]] = []
    for meta_file in projects_root(settings).glob("*/meta.json"):
        meta = _read_json(meta_file)
        if meta is not None:
            metas.append(meta)
    metas.sort(key=lambda m: (-(float(m.get("updated_at") or 0)), str(m.get("id"))))
    return metas


def get_project(project_id: str, settings: Any | None = None) -> dict[str, Any] | None:
    if not _valid_id(project_id):
        return None
    full = _read_json(projects_root(settings) / project_id / "project.json")
    if full is None:
        return None
    full["conversation_count"] = _conversation_count(project_id, settings)
    return full


def put_project(project: dict[str, Any], settings: Any | None = None) -> dict[str, Any]:
    """整工程 upsert(画布唯一权威)。非法 id / 缺 project_name / 缺 canvas 拒绝。"""
    pid = str((project or {}).get("id") or "")
    if not _valid_id(pid):
        raise ValueError("project.id invalid")
    name = str(project.get("project_name") or "").strip()
    if not name:
        raise ValueError("project.project_name required")
    canvas = project.get("canvas")
    if not isinstance(canvas, dict):
        raise ValueError("project.canvas required")
    full = {
        "id": pid,
        "project_name": name,
        "canvas": canvas,
        "created_at": float(project.get("created_at") or _now_ts()),
        "updated_at": float(project.get("updated_at") or _now_ts()),
    }
    payload = json.dumps(full, ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("project too large (>20MB)")
    _atomic_write(projects_root(settings) / pid / "project.json", payload)
    return _write_project_meta(full, settings)


def delete_project(project_id: str, settings: Any | None = None) -> int | None:
    """级联删除工程及其全部 conversations;返回级联删除的对话数(None=非法 id)。

    幂等:目录已不存在时返回 0 且不报错。
    """
    if not _valid_id(project_id):
        return None
    cascaded = 0
    for meta in _all_conversation_metas(settings):
        if str(meta.get("project_id") or "") != project_id:
            continue
        cid = str(meta.get("id") or "")
        if not _valid_id(cid):
            continue
        shutil.rmtree(conversations_root(settings) / cid, ignore_errors=True)
        cascaded += 1
    shutil.rmtree(projects_root(settings) / project_id, ignore_errors=True)
    return cascaded


# ---------------- Conversation CRUD ----------------


def list_conversations(
    project_id: str, settings: Any | None = None
) -> list[dict[str, Any]]:
    """某工程下对话 meta 列表,按 updated_at 降序。"""
    metas = [
        m
        for m in _all_conversation_metas(settings)
        if str(m.get("project_id") or "") == project_id
    ]
    metas.sort(key=lambda m: (-(float(m.get("updated_at") or 0)), str(m.get("id"))))
    return metas


def get_conversation(conversation_id: str, settings: Any | None = None) -> dict[str, Any] | None:
    """完整对话 = meta + messages(不返回画布——画布永远属于 Project)。"""
    if not _valid_id(conversation_id):
        return None
    meta = _read_json(conversations_root(settings) / conversation_id / "meta.json")
    if meta is None:
        return None
    body = _read_json(conversations_root(settings) / conversation_id / "conversation.json") or {}
    return {
        "id": str(meta.get("id") or conversation_id),
        "project_id": str(meta.get("project_id") or ""),
        "title": str(meta.get("title") or ""),
        "created_at": float(body.get("created_at") or 0.0),
        "updated_at": float(meta.get("updated_at") or 0.0),
        "messages": body.get("messages") if isinstance(body.get("messages"), list) else [],
    }


def put_conversation(
    conversation: dict[str, Any], settings: Any | None = None
) -> dict[str, Any]:
    """整对话 upsert;只存消息(缺 messages / project_id 拒绝)。"""
    cid = str((conversation or {}).get("id") or "")
    if not _valid_id(cid):
        raise ValueError("conversation.id invalid")
    pid = str(conversation.get("project_id") or "")
    if not _valid_id(pid):
        raise ValueError("conversation.project_id invalid")
    if not isinstance(conversation.get("messages"), list):
        raise ValueError("conversation.messages required")
    body = {
        "created_at": float(conversation.get("created_at") or _now_ts()),
        "messages": conversation.get("messages"),
    }
    payload = json.dumps(body, ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("conversation too large (>20MB)")
    meta = {
        "id": cid,
        "project_id": pid,
        "title": str(conversation.get("title") or "")[:120],
        "updated_at": float(conversation.get("updated_at") or _now_ts()),
    }
    root = conversations_root(settings) / cid
    _atomic_write(root / "conversation.json", payload)
    _atomic_write(root / "meta.json", json.dumps(meta, ensure_ascii=False))
    _refresh_project_meta(pid, settings)
    return meta


def delete_conversation(conversation_id: str, settings: Any | None = None) -> bool | None:
    """删对话并同步所属工程 count;None=非法 id;幂等成功。"""
    if not _valid_id(conversation_id):
        return None
    meta = _read_json(conversations_root(settings) / conversation_id / "meta.json")
    shutil.rmtree(conversations_root(settings) / conversation_id, ignore_errors=True)
    if meta is not None:
        _refresh_project_meta(str(meta.get("project_id") or ""), settings)
    return True


# ---------------- 旧 sessions → 新结构迁移 ----------------


def _project_name_from_session(session: dict[str, Any]) -> str:
    """工程名优先级:session.project_name → canvas.project_name → 标题「·」后段 → 标题。"""
    candidates: list[Any] = [session.get("project_name")]
    canvas = session.get("canvas")
    if isinstance(canvas, dict):
        candidates.append(canvas.get("project_name"))
    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            return cand.strip()[:120]
    title = str(session.get("title") or "")
    if "·" in title:
        part = title.split("·")[-1].strip()
        if part:
            return part[:120]
    return (title.strip() or _UNNAMED)[:120]


def migrate_from_sessions(settings: Any | None = None) -> dict[str, int]:
    """旧 ``sessions/<id>/session.json`` → Project(取画布)+ Conversation(取消息)。

    幂等:工程按 ``project_name`` 匹配已存在则跳过创建;对话沿用原 session id,
    已存在则跳过。返回 ``{projects_migrated, conversations_migrated}``(仅计新建)。
    """
    from gateway.app.services.plc import session_store

    existing_by_name = {
        str(m.get("name") or ""): str(m.get("id") or "") for m in list_projects(settings)
    }
    projects_migrated = 0
    conversations_migrated = 0
    for meta in session_store.list_sessions(settings):
        sid = str(meta.get("id") or "")
        if not sid:
            continue
        session = session_store.get_session(sid, settings)
        if not session:
            continue
        name = _project_name_from_session(session)
        pid = existing_by_name.get(name)
        if not pid:
            pid = new_project_id()
            canvas = session.get("canvas")
            if not isinstance(canvas, dict) or not canvas:
                canvas = _blank_canvas(name)
            put_project(
                {
                    "id": pid,
                    "project_name": name,
                    "canvas": canvas,
                    "created_at": float(session.get("createdAt") or 0.0),
                    "updated_at": float(session.get("updatedAt") or 0.0),
                },
                settings,
            )
            existing_by_name[name] = pid
            projects_migrated += 1
        if get_conversation(sid, settings) is not None:
            continue  # 已迁移(沿用原 session id 即幂等锚点)
        put_conversation(
            {
                "id": sid,  # 保留原 id:二次运行可识别已迁移
                "project_id": pid,
                "title": str(session.get("title") or "")[:120] or "新对话",
                "messages": session.get("messages")
                if isinstance(session.get("messages"), list)
                else [],
                "created_at": float(session.get("createdAt") or 0.0),
                "updated_at": float(session.get("updatedAt") or 0.0),
            },
            settings,
        )
        conversations_migrated += 1
    return {"projects_migrated": projects_migrated, "conversations_migrated": conversations_migrated}
