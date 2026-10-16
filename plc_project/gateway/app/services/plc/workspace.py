"""Persistent PLC/HMI engineering workspace under PLC_WORK_DIR/projects/<id>.

Layout::

    projects/<project_id>/
      original/          # read-only snapshot of imported TIA tree / .apxx
      work/              # mutable working copy used for Openness writeback
      baseline/          # exported XML/JSON baselines for 1:1 diff writeback
      meta.json          # {project_id, project_name, project_path, created_at, …}
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

APXX_SUFFIXES = {".ap17", ".ap18", ".ap19", ".ap20"}


def projects_root(settings: Any | None = None) -> Path:
    work = ""
    if settings is not None:
        work = str(getattr(settings, "plc_work_dir", "") or "").strip()
    if not work:
        work = os.getenv("PLC_WORK_DIR", "").strip()
    base = Path(work).expanduser() if work else Path(tempfile.gettempdir()) / "researchos_plc"
    root = base / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


def project_dir(project_id: str, settings: Any | None = None) -> Path:
    return projects_root(settings) / project_id


def _find_apxx(root: Path) -> Path | None:
    if root.is_file() and root.suffix.lower() in APXX_SUFFIXES:
        return root
    candidates = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in APXX_SUFFIXES)
    return candidates[0] if candidates else None


def persist_imported_project(
    source: Path,
    *,
    project_name: str = "",
    settings: Any | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Copy an imported TIA tree / .apxx into a durable workspace.

    Returns meta dict including ``project_id`` and absolute ``project_path`` (.apxx).
    """
    source = Path(source).expanduser().resolve()
    pid = (project_id or new_project_id()).strip()
    root = project_dir(pid, settings)
    original = root / "original"
    work = root / "work"
    baseline = root / "baseline"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    original.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    baseline.mkdir(parents=True, exist_ok=True)

    if source.is_file():
        dest_file = original / source.name
        shutil.copy2(source, dest_file)
        # Only copy the Siemens sibling folder named like the .apxx stem (not entire parent).
        sibling = source.parent / source.stem
        if sibling.is_dir():
            shutil.copytree(sibling, original / sibling.name, dirs_exist_ok=True)
    else:
        shutil.copytree(source, original, dirs_exist_ok=True)

    # Working copy starts as a clone of original
    for child in original.iterdir():
        target = work / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)

    apxx = _find_apxx(work)
    meta = {
        "project_id": pid,
        "project_name": (project_name or (apxx.stem if apxx else source.stem)).strip(),
        "project_path": str(apxx) if apxx else "",
        "original_path": str(original),
        "work_path": str(work),
        "baseline_path": str(baseline),
        "created_at": time.time(),
    }
    (root / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def load_meta(project_id: str, settings: Any | None = None) -> dict[str, Any] | None:
    meta_path = project_dir(project_id, settings) / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_work_project_path(project_id: str, settings: Any | None = None) -> Path | None:
    meta = load_meta(project_id, settings)
    if not meta:
        return None
    path = Path(str(meta.get("project_path") or ""))
    return path if path.is_file() else _find_apxx(Path(str(meta.get("work_path") or "")))


def reset_work_copy(project_id: str, settings: Any | None = None) -> Path | None:
    """Re-clone original → work before a compile job (fail-closed isolation)."""
    meta = load_meta(project_id, settings)
    if not meta:
        return None
    original = Path(str(meta["original_path"]))
    work = Path(str(meta["work_path"]))
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    for child in original.iterdir():
        target = work / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)
    apxx = _find_apxx(work)
    meta["project_path"] = str(apxx) if apxx else ""
    meta["updated_at"] = time.time()
    (project_dir(project_id, settings) / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return apxx


def save_baseline_file(project_id: str, relative: str, content: str | bytes, settings: Any | None = None) -> Path:
    base = project_dir(project_id, settings) / "baseline"
    target = base / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def is_workspace_path(path: str | Path, settings: Any | None = None) -> bool:
    """True when path resolves under projects_root (safe writeback target)."""
    try:
        resolved = Path(path).expanduser().resolve()
        root = projects_root(settings).resolve()
        return root in resolved.parents or resolved == root
    except OSError:
        return False
