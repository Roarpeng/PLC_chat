"""回写博图的安全护栏：写前备份 / 回滚 / 内容哈希幂等清单。

只做本地文件系统编排（拷贝、哈希、JSON 清单读写），**不调用任何 Openness CLI**，
因此 Linux Gateway 与 Windows 主机上行为一致，也便于单元测试直接验证编排逻辑。

三条不变量：
1. 备份失败（含超限）必须 fail-closed —— 绝不「备份失败照样写」。
2. 还原前先把现有 target 挪到 ``.pre-rollback`` 临时位置，失败则整体回退。
3. 幂等清单只信任「内容哈希相同且上次状态为成功」的条目，失败/变更一律重跑。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKUP_DIR_NAME = "backup"
MANIFEST_NAME = "writeback_manifest.json"
BACKUP_MARKER = "backup_manifest.json"
PRE_ROLLBACK_SUFFIX = ".pre-rollback"
LOCK_SUFFIX = ".lock"

DEFAULT_BACKUP_MAX_MB = 2048.0
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0

BACKUP_ENV_MAX_MB = "RESEARCHOS_WRITEBACK_BACKUP_MAX_MB"


def utc_stamp() -> str:
    """UTC 时间戳（秒级），用于备份目录命名，避免本地时区/夏令时歧义。"""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def backup_max_mb(default: float = DEFAULT_BACKUP_MAX_MB) -> float:
    """备份体积上限（MB）。``<=0`` 表示不限制。"""
    raw = os.getenv(BACKUP_ENV_MAX_MB, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else 0.0


def content_sha256(path: str | Path) -> str:
    """文件内容 sha256；读不到时返回空串（调用方按「未知」处理，不会命中跳过）。"""
    p = Path(path)
    try:
        digest = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def dir_size_bytes(path: str | Path, *, skip: Path | None = None) -> int:
    """目录总字节数；``skip`` 子树不计入（备份目录自引用时用）。"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(Path(path)):
        current = Path(dirpath)
        if skip is not None:
            try:
                resolved_skip = skip.resolve()
            except OSError:
                resolved_skip = skip
            kept: list[str] = []
            for name in dirnames:
                try:
                    if (current / name).resolve() == resolved_skip:
                        continue
                except OSError:
                    pass
                kept.append(name)
            dirnames[:] = kept
        for name in filenames:
            try:
                total += (current / name).stat().st_size
            except OSError:
                continue
    return total


def manifest_key(kind: str, block: str) -> str:
    """幂等清单的键：``{kind}:{block}``（kind 为 block/type/tag/scl 等）。"""
    return f"{kind or 'unknown'}:{block or 'unknown'}"


def manifest_path(export_dir: str | Path) -> Path:
    return Path(export_dir).expanduser().resolve() / MANIFEST_NAME


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + LOCK_SUFFIX)


@contextmanager
def _file_lock(path: Path, timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """跨进程文件锁（O_EXCL 创建 + 陈旧锁清理）。拿不到锁时降级为不锁。

    幂等清单不是强事务：最坏情况是并发下多写一次，不会破坏「失败必重跑」的语义。
    """
    lock = _lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    owned = False
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            owned = True
            break
        except FileExistsError:
            try:
                stale = (time.time() - lock.stat().st_mtime) > LOCK_STALE_S
            except OSError:
                stale = True
            if stale:
                try:
                    lock.unlink()
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        except OSError:
            break
    try:
        yield
    finally:
        if owned:
            try:
                lock.unlink()
            except OSError:
                pass


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写 JSON：临时文件 + os.replace，避免读到半截清单。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(str(tmp), str(path))


def load_manifest(export_dir: str | Path) -> dict[str, dict[str, Any]]:
    """读取 ``{export_dir}/writeback_manifest.json``；损坏或缺失返回空字典。"""
    path = manifest_path(export_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def update_manifest(
    export_dir: str | Path,
    entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """读-改-写幂等清单（文件锁 + 原子替换）。返回合并后的完整清单。"""
    if not entries:
        return load_manifest(export_dir)
    path = manifest_path(export_dir)
    with _file_lock(path):
        data = load_manifest(export_dir)
        data.update(entries)
        _atomic_write_json(path, data)
    return data


def should_skip(manifest: dict[str, dict[str, Any]], key: str, sha256: str) -> bool:
    """哈希相同且上次状态为 ``ok`` → 跳过本次写入（幂等）。"""
    if not sha256:
        return False
    prev = manifest.get(key) or {}
    return prev.get("sha256") == sha256 and prev.get("status") == "ok"


def _marker_payload(kind: str, name: str, target: Path, size: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "name": name,
        "target": str(target),
        "bytes": size,
        "created_at": utc_stamp(),
    }


def backup_target(
    target: str | Path,
    export_dir: str | Path,
    *,
    max_mb: float | None = None,
) -> dict[str, Any]:
    """把写回目标备份到 ``{export_dir}/backup/{UTC时间戳}/``。

    ``target`` 既可能是 ``.ap17`` 这类单文件，也可能是 TIA 工程目录，两种都处理。

    Returns:
        ``{ok, path, reason, kind, bytes, limit_mb}``。``ok=False`` 时 ``path=None``，
        调用方必须中止写操作（fail-closed）。
    """
    src = Path(target).expanduser().resolve()
    root = Path(export_dir).expanduser().resolve() / BACKUP_DIR_NAME / utc_stamp()
    limit = backup_max_mb() if max_mb is None else float(max_mb)

    if not src.exists():
        return {
            "ok": False,
            "path": None,
            "reason": "backup_target_missing",
            "kind": "missing",
            "bytes": 0,
            "limit_mb": limit,
        }
    kind = "dir" if src.is_dir() else "file"
    size = dir_size_bytes(src, skip=root) if kind == "dir" else src.stat().st_size
    if limit > 0 and size > limit * 1024 * 1024:
        return {
            "ok": False,
            "path": None,
            "reason": "backup_too_large",
            "kind": kind,
            "bytes": size,
            "limit_mb": limit,
        }

    try:
        root.mkdir(parents=True, exist_ok=True)
        if kind == "file":
            shutil.copy2(src, root / src.name)
        else:
            # 备份目录若落在被备份工程内部，拷贝时必须跳过，避免自引用递归
            ignore = None
            try:
                rel = root.relative_to(src)
                if rel.parts:
                    ignore = shutil.ignore_patterns(rel.parts[0])
            except ValueError:
                ignore = None
            shutil.copytree(src, root / src.name, ignore=ignore, dirs_exist_ok=True)
        _atomic_write_json(
            root / BACKUP_MARKER, _marker_payload(kind, src.name, src, size)
        )
    except (OSError, shutil.Error) as exc:
        shutil.rmtree(root, ignore_errors=True)
        return {
            "ok": False,
            "path": None,
            "reason": "backup_failed",
            "kind": kind,
            "bytes": size,
            "limit_mb": limit,
            "error": str(exc),
        }
    return {
        "ok": True,
        "path": str(root),
        "reason": "",
        "kind": kind,
        "bytes": size,
        "limit_mb": limit,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _backup_entry_name(backup_root: Path) -> str:
    """还原源条目名：优先读标记文件，其次取目录内唯一非标记条目。"""
    marker = backup_root / BACKUP_MARKER
    if marker.is_file():
        try:
            raw = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        name = str((raw or {}).get("name") or "")
        if name:
            return name
    entries = [p.name for p in backup_root.iterdir() if p.name != BACKUP_MARKER]
    return entries[0] if len(entries) == 1 else ""


def restore_from_backup(
    backup_path: str | Path,
    target: str | Path,
    *,
    allowed_roots: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """用 ``backup_target`` 产出的备份还原 ``target``。

    步骤：校验 backup_path → 现有 target 移到 ``{name}.pre-rollback-{ts}`` →
    从备份拷贝回 target → 任一步失败则把 ``.pre-rollback`` 放回原位。

    Args:
        allowed_roots: 允许的备份根目录；为 ``None`` 时退化为「必须自带备份标记文件」，
            避免任意目录被当作还原源。

    Returns:
        ``{ok, restored_from, target, pre_rollback_path, reason}``
    """
    backup = Path(backup_path).expanduser().resolve()
    dst = Path(target).expanduser().resolve()
    out: dict[str, Any] = {
        "ok": False,
        "restored_from": str(backup),
        "target": str(dst),
        "pre_rollback_path": None,
        "reason": "",
    }

    roots = [Path(r).expanduser().resolve() for r in (allowed_roots or [])]
    if roots:
        if not any(_is_within(backup, r) for r in roots):
            out["reason"] = "backup_path_outside_allowed_roots"
            return out
    elif not (backup / BACKUP_MARKER).is_file():
        out["reason"] = "backup_marker_missing"
        return out

    if not backup.is_dir():
        out["reason"] = "backup_path_not_a_directory"
        return out

    name = _backup_entry_name(backup)
    if not name:
        out["reason"] = "backup_entry_missing"
        return out
    entry = backup / name
    if not entry.exists():
        out["reason"] = "backup_entry_missing"
        return out

    pre_rollback = dst.with_name(f"{dst.name}{PRE_ROLLBACK_SUFFIX}-{utc_stamp()}")
    moved = False
    try:
        if dst.exists():
            shutil.move(str(dst), str(pre_rollback))
            moved = True
        if moved:
            out["pre_rollback_path"] = str(pre_rollback)
        if entry.is_dir():
            shutil.copytree(entry, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dst)
    except (OSError, shutil.Error) as exc:
        # 回退：把挪走的原始 target 放回，保证不会留下「既没还原也没原文件」的状态
        if moved:
            try:
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
                shutil.move(str(pre_rollback), str(dst))
            except (OSError, shutil.Error):
                pass
        out["reason"] = "restore_failed"
        out["error"] = str(exc)
        return out

    out["ok"] = True
    return out
