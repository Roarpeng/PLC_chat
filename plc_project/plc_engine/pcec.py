"""PCEC —— 带证据的工程变更事务(契约 docs/19 §3,并行线 A 交付)。

每次写回都是一个可审计事务:``change_id`` 贯穿 UI→确认→写回→编译→账本;
工程基线变化即过期拒绝(``project_baseline`` / ``baseline_matches``),状态机
非法迁移抛 :class:`PcecTransitionError`,验证状态分级(未知≠通过)由调用方
写 ``verification`` 分级字段承载。

存储布局(风格对齐 ``gateway/app/services/plc/session_store.py``)::

    changes/<change_id>/meta.json     # id/kind/summary/status/updated_at/touched_count(列表只读这个)
    changes/<change_id>/change.json   # 完整事务(ops 超限时截断为摘要快照)

写入为 temp+rename 原子替换;列表只解析 meta,坏文件跳过不炸列表。
事务对象是纯 dict、JSON 可序列化(契约 §1)。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

VERSION = "0.1"  # parser/engine 语义版本(写入 baseline)
_MAX_CHANGE_BYTES = 10 * 1024 * 1024  # 单事务 10MB 上限;超限 ops 截断为摘要

_CHANGE_ID_RE = re.compile(r"^chg-[0-9a-f]{12}$")

STATUSES = frozenset(
    {
        "proposed",
        "analyzed",
        "validated",
        "approved",
        "applied",
        "failed",
        "expired",
        "rejected",
        "rolled_back",
    }
)
TERMINAL_STATUSES = frozenset({"applied", "failed", "expired", "rejected", "rolled_back"})
NON_TERMINAL_STATUSES = STATUSES - TERMINAL_STATUSES

#: 契约 §2 状态图;applied 虽为终态,回滚(applied→rolled_back)是唯一例外出口;
#: 任意非终态可转 expired(由调用方在基线检查失败后触发)。
ALLOWED_TRANSITIONS = (
    frozenset(
        {
            ("proposed", "analyzed"),
            ("analyzed", "validated"),
            ("analyzed", "rejected"),
            ("validated", "approved"),
            ("validated", "failed"),
            ("approved", "applied"),
            ("approved", "failed"),
            ("applied", "rolled_back"),
        }
    )
    | {(frm, "expired") for frm in NON_TERMINAL_STATUSES}
)

# 基线遍历跳过项:TIA 运行期目录 Logs/TMP/XRef(大小写不敏感)与本工具自身产物 _researchos*
_SKIP_DIR_NAMES = frozenset({"logs", "tmp", "xref"})
_SKIP_NAME_PREFIX = "_researchos"
_APXX_FILE_RE = re.compile(r"\.ap(\d+)$")  # *.ap1x 工程描述符(如 HR001.ap19 → V19)


class PcecTransitionError(Exception):
    """非法状态迁移(契约 §2:非法路径 / 终态封锁)。"""


def _now_ts() -> float:
    return time.time()


def _new_change_id() -> str:
    return f"chg-{uuid.uuid4().hex[:12]}"


def _valid_change_id(change_id: str | None) -> bool:
    return bool(_CHANGE_ID_RE.match(change_id or ""))


# ---------------------------------------------------------------- 事务对象 --


def new_change(intent_kind: str, request: str, ops: list, touched_blocks: list,
               baseline: dict, requirement_id: str = "") -> dict:
    """创建变更事务(status=proposed,events=[created]),字段结构按契约 §1。

    ``requirement_id`` 是工艺需求卡的弱关联(契约 docs/22 §2):非空时写入
    ``intent.requirement_id``;缺省(空串)**不写该字段**,既有输出字节保持
    不变(快照测试兼容)。
    """
    now = _now_ts()
    request = str(request or "")
    intent = {
        "kind": str(intent_kind or ""),
        "request": request,
        "summary": request.strip()[:80],
    }
    if requirement_id:
        intent["requirement_id"] = str(requirement_id)
    return {
        "change_id": _new_change_id(),
        "created_at": now,
        "updated_at": now,
        "project_baseline": dict(baseline or {}),
        "intent": intent,
        "ops": list(ops or []),
        "touched_blocks": [str(b) for b in (touched_blocks or [])],
        "preconditions": [],
        "impact": {"blocks": [], "signals": [], "hmi_widgets": []},
        "verification": {
            "v0_parsed": "pending",
            "v1_static": "pending",
            "v2_tia_compile": "pending",
            "v3_behavior": "pending",
            "detail": {"compile_job_id": "", "error_count": 0, "diagnostics": []},
        },
        "approval": {},
        "rollback": {"backup_path": "", "backup_hash": "", "restore_verified": False},
        "status": "proposed",
        "events": [{"ts": now, "event": "created"}],
    }


def transition(change: dict, to_status: str, *, event: str = "", **patch) -> dict:
    """状态迁移:合法性校验 + 追加事件 + updated_at;patch 合并顶层字段。

    就地更新并返回同一 dict;非法迁移抛 :class:`PcecTransitionError`(change
    保持不变)。``status`` 永远由 ``to_status`` 决定,patch 无法绕过状态机。
    event 缺省取 to_status(如 analyzed/applied/expired)。
    """
    if not isinstance(change, dict) or not isinstance(change.get("status"), str):
        raise TypeError("change.status required")
    if to_status not in STATUSES:
        raise PcecTransitionError(f"unknown status: {to_status!r}")
    frm = change["status"]
    if (frm, to_status) not in ALLOWED_TRANSITIONS:
        raise PcecTransitionError(f"illegal transition: {frm} -> {to_status}")
    change.update(patch)  # 顶层合并(verification/approval 等);status 最后覆盖
    change["status"] = to_status
    change["updated_at"] = _now_ts()
    events = change.get("events")
    if not isinstance(events, list):
        events = change["events"] = []
    events.append({"ts": change["updated_at"], "event": str(event or to_status)})
    return change


# ---------------------------------------------------------------- 基线哈希 --


def _skip_name(name: str) -> bool:
    return name.lower() in _SKIP_DIR_NAMES or name.startswith(_SKIP_NAME_PREFIX)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_baseline(project_path: str | Path) -> dict:
    """工程基线指纹:文件清单(相对路径+大小+内容sha256,排序串接)再整体 sha256。

    遍历工程根,跳过 Logs/TMP/XRef(大小写不敏感)与 ``_researchos*`` 前缀;
    tia_version 从 ``*.ap1x`` 描述符文件名推断(如 ``x.ap19`` → ``V19``),
    取不到用 ``"unknown"``。
    """
    root = Path(project_path)
    entries: list[tuple[str, int, str]] = []
    versions: list[tuple[str, str]] = []
    if root.is_file():
        _collect_entry(root.parent, root, entries, versions)
    elif root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not _skip_name(d))
            for name in sorted(filenames):
                if _skip_name(name):
                    continue
                _collect_entry(root, Path(dirpath) / name, entries, versions)
    else:
        raise FileNotFoundError(f"project path not found: {project_path}")
    entries.sort(key=lambda e: e[0])
    manifest = "".join(f"{rel}\t{size}\t{sha}\n" for rel, size, sha in entries)
    versions.sort()
    return {
        "project_hash": "sha256:" + hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
        "tia_version": f"V{versions[0][1]}" if versions else "unknown",
        "parser_version": VERSION,
    }


def _collect_entry(root: Path, path: Path,
                   entries: list[tuple[str, int, str]],
                   versions: list[tuple[str, str]]) -> None:
    try:
        if not path.is_file():
            return
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        entries.append((rel, size, _sha256_file(path)))
    except OSError:
        return  # 不可读文件无法参与指纹,跳过
    m = _APXX_FILE_RE.search(path.name.lower())
    if m:
        versions.append((rel.lower(), m.group(1)))


def baseline_matches(change: dict, project_path: str | Path) -> bool:
    """基线门禁:事务记录的 project_hash 与当前工程是否一致(异常时 fail-closed)。"""
    try:
        recorded = change["project_baseline"]["project_hash"]
    except (TypeError, KeyError, IndexError):
        return False
    if not isinstance(recorded, str) or not recorded:
        return False
    try:
        return project_baseline(project_path)["project_hash"] == recorded
    except OSError:
        return False


# -------------------------------------------------------------------- 账本 --


def changes_root(settings: Any | None = None) -> Path:
    """``<PLC_WORK_DIR>/changes``,自动创建(解析顺序同 session_store)。"""
    work = ""
    if settings is not None:
        work = str(getattr(settings, "plc_work_dir", "") or "").strip()
    if not work:
        work = os.getenv("PLC_WORK_DIR", "").strip()
    base = Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"
    root = base / "changes"
    root.mkdir(parents=True, exist_ok=True)
    return root


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


def _meta_from_change(change: dict) -> dict:
    intent = change.get("intent")
    intent = intent if isinstance(intent, dict) else {}
    touched = change.get("touched_blocks")
    return {
        "id": str(change.get("change_id") or ""),
        "kind": str(intent.get("kind") or ""),
        "summary": str(intent.get("summary") or "")[:120],
        "status": str(change.get("status") or ""),
        "updated_at": change.get("updated_at") or 0,
        "touched_count": len(touched) if isinstance(touched, list) else 0,
    }


def _truncate_ops(stored: dict) -> None:
    """10MB 超限:ops 快照替换为 touched 清单+内容哈希,并记事件 ops_truncated。"""
    ops = stored.get("ops")
    ops = ops if isinstance(ops, list) else []
    touched = [str(b) for b in (stored.get("touched_blocks") or [])]
    ops_hash = "sha256:" + hashlib.sha256(
        json.dumps(ops, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    stored["ops"] = {
        "truncated": True,
        "touched_blocks": touched,
        "ops_count": len(ops),
        "ops_hash": ops_hash,
    }
    events = stored.setdefault("events", [])
    events.append({"ts": _now_ts(), "event": "ops_truncated"})


def put_change(change: dict, settings: Any | None = None) -> dict:
    """整事务 upsert:原子写 change.json + meta.json,返回 meta。

    非法 change_id 拒绝;序列化超 10MB 时落盘快照的 ops 截断为 touched 清单+
    内容哈希并在 events 记 ``ops_truncated``(内存对象保持完整 ops,截断仅是
    存储行为);截断后仍超限则拒绝。
    """
    cid = str((change or {}).get("change_id") or "")
    if not _valid_change_id(cid):
        raise ValueError("change.change_id invalid (expected chg-<hex12>)")
    stored = json.loads(json.dumps(change, ensure_ascii=False))  # 深拷贝+可序列化校验
    payload = json.dumps(stored, ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_CHANGE_BYTES:
        _truncate_ops(stored)
        payload = json.dumps(stored, ensure_ascii=False)
        if len(payload.encode("utf-8")) > _MAX_CHANGE_BYTES:
            raise ValueError("change too large (>10MB even after ops truncation)")
    root = changes_root(settings) / cid
    _atomic_write(root / "change.json", payload)
    meta = _meta_from_change(stored)
    _atomic_write(root / "meta.json", json.dumps(meta, ensure_ascii=False))
    return meta


def get_change(change_id: str, settings: Any | None = None) -> dict | None:
    """读完整事务;非法 id / 缺失 / 坏文件返回 None。"""
    if not _valid_change_id(change_id):
        return None
    path = changes_root(settings) / change_id / "change.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_changes(settings: Any | None = None) -> list[dict]:
    """全部事务 meta,按 updated_at 降序;坏文件跳过不炸列表。"""
    metas: list[dict] = []
    for meta_file in changes_root(settings).glob("*/meta.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            metas.append(data)
    metas.sort(key=lambda m: (-(float(m.get("updated_at") or 0)), str(m.get("id"))))
    return metas
