"""PLC write-back orchestration — import bundle → Openness XML/SCL + compile gate.

Execution paths:
- Windows host: local Openness CLI directly (HostGateway mode).
- Linux/Docker Gateway with ``RESEARCHOS_OPENNESS_WORKER_URL`` configured:
  delegate the whole import+compile to the Windows Openness worker
  (``industrial/openness_worker``), keeping the same fail-closed report shape.

Safety rails (see ``writeback_safety``) layered on top of the import logic:
- ``dry_run=True``: stage/plan only, never call import/generate/compile.
- pre-write backup: fail closed when the target cannot be backed up (含超限).
- rollback: every successful write path reports ``backup_path`` + restore hint.
- idempotency: content sha256 manifest, unchanged + previously ok → skip.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agents.plc.tia.changeset import PlcChangeSet, write_import_bundle
from agents.plc.tia.openness_cli import (
    compile_plc_via_openness_cli,
    generate_from_source_via_openness_cli,
    import_block_via_openness_cli,
    import_xml_via_openness_cli,
)
from agents.plc.tia.surface import classify_xml_kind, xml_looks_like_safety
from agents.plc.tia.writeback_safety import (
    backup_target,
    content_sha256,
    load_manifest,
    manifest_key,
    restore_from_backup,
    should_skip,
    update_manifest,
    utc_stamp,
)

__all__ = [
    "execute_writeback",
    "plan_writeback",
    "prepare_writeback",
    "restore_from_backup",
    "staged_files",
]

WRITE_ACTIONS = frozenset({"import_block_xml", "import_xml", "generate_from_source"})

_NOTE = (
    "XML: Blocks.Import / TypeGroup.Types.Import / TagTables.Import when present + Save. "
    "SCL: ExternalSourceGroup.CreateFromFile + GenerateBlocksFromSource + Save. "
    "Compile: ICompilable.Compile (fail closed). "
    "F-block / know-how decrypt refused. Linux Docker delegates to the Windows "
    "Openness worker when RESEARCHOS_OPENNESS_WORKER_URL is configured. "
    "Safety rails: dry-run plan / pre-write backup (fail closed) / restore_from_backup / "
    "content-sha256 idempotency manifest."
)


def prepare_writeback(
    job_export_dir: str | Path,
    changeset: PlcChangeSet,
    source_xmls: list[str | Path] | None = None,
) -> Path:
    """Build ``{job_export_dir}/import_bundle`` and return that directory."""
    bundle = Path(job_export_dir).expanduser().resolve() / "import_bundle"
    write_import_bundle(bundle, changeset, source_xmls)
    return bundle


def _staged_xmls(bundle_dir: Path) -> list[Path]:
    manifest = bundle_dir / "staged_xmls.json"
    if manifest.is_file():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return [Path(p) for p in raw if Path(p).is_file()]
    return sorted(bundle_dir.glob("*.xml"))


def _staged_scls(bundle_dir: Path) -> list[Path]:
    manifest = bundle_dir / "staged_scls.json"
    if manifest.is_file():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return [Path(p) for p in raw if Path(p).is_file()]
    ext = bundle_dir / "external_sources"
    if ext.is_dir():
        return sorted(ext.glob("*.scl"))
    return []


def staged_files(bundle_dir: str | Path) -> tuple[list[Path], list[Path]]:
    """Public view of a prepared bundle: (staged XMLs, staged SCL sources)."""
    bundle = Path(bundle_dir).expanduser().resolve()
    return _staged_xmls(bundle), _staged_scls(bundle)


def _is_windows_local() -> bool:
    return os.name == "nt"


def _worker_preferred() -> bool:
    """True when this host cannot run Openness but a Windows worker is configured."""
    if _is_windows_local():
        return False
    try:
        from industrial.openness_worker.client import worker_base_url
    except Exception:  # noqa: BLE001 — worker client is optional at runtime
        return False
    return bool(worker_base_url())


def _classify_xml(xml: Path) -> str:
    try:
        head = xml.read_text(encoding="utf-8", errors="ignore")[:8192]
        return classify_xml_kind(xml.name, head)
    except OSError:
        return "block"


def plan_writeback(
    project_path: str | Path,
    bundle_dir: str | Path,
    plc_name: str = "",
    *,
    compile_after: bool = True,
) -> list[dict[str, Any]]:
    """Dry-run plan: what ``execute_writeback`` *would* do, without touching TIA.

    Each entry is ``{action, block, target, kind, reason}`` — ``action`` is one of
    ``import_block_xml`` / ``import_xml`` / ``generate_from_source`` / ``compile`` /
    ``refuse`` (F-block, never written).
    """
    bundle = Path(bundle_dir).expanduser().resolve()
    project = Path(project_path).expanduser().resolve()
    planned: list[dict[str, Any]] = []
    for xml in _staged_xmls(bundle):
        kind = _classify_xml(xml)
        if xml_looks_like_safety(xml):
            planned.append(
                {
                    "action": "refuse",
                    "block": xml.stem,
                    "target": str(xml),
                    "kind": kind,
                    "reason": "safety_block",
                }
            )
            continue
        planned.append(
            {
                "action": "import_block_xml" if kind == "block" else "import_xml",
                "block": xml.stem,
                "target": str(xml),
                "kind": kind,
                "reason": "",
            }
        )
    for scl in _staged_scls(bundle):
        planned.append(
            {
                "action": "generate_from_source",
                "block": scl.stem,
                "target": str(scl),
                "kind": "scl",
                "reason": "",
            }
        )
    if compile_after:
        planned.append(
            {
                "action": "compile",
                "block": plc_name or "",
                "target": str(project),
                "kind": "compile",
                "reason": "",
            }
        )
    return planned


def _restore_hint(backup_path: str | None, project: Path) -> str:
    if not backup_path:
        return ""
    return f"restore_from_backup({backup_path!r}, {str(project)!r})"


def _record_manifest(
    export_dir: Path,
    status_by_key: dict[str, str],
    digest_by_key: dict[str, str],
) -> None:
    """把本次执行结果写进幂等清单（失败条目下次会重跑）。"""
    if not status_by_key:
        return
    ts = utc_stamp()
    entries = {
        key: {"sha256": digest_by_key.get(key, ""), "ts": ts, "status": status}
        for key, status in status_by_key.items()
    }
    try:
        update_manifest(export_dir, entries)
    except OSError:  # 清单写失败不该掩盖导入结果
        pass


def _dry_run_result(
    project: Path,
    bundle: Path,
    planned: list[dict[str, Any]],
) -> dict[str, Any]:
    refused = [p for p in planned if p["action"] == "refuse"]
    return {
        "ok": not refused,
        "dry_run": True,
        "written": False,
        "import_ok": not refused,
        "compiled_ok": False,
        "project_path": str(project),
        "bundle_dir": str(bundle),
        "imported": 0,
        "scl_imported": 0,
        "results": [],
        "scl_results": [],
        "compile": {
            "ok": False,
            "skipped": True,
            "message": "dry-run：只生成计划，未执行任何 Openness 写操作。",
        },
        "planned": planned,
        "skipped_items": [],
        "backup_path": None,
        "rollback": {"backup_path": None, "restore_hint": ""},
        "note": _NOTE,
    }


def _skipped_result(
    project: Path,
    bundle: Path,
    planned: list[dict[str, Any]],
    unchanged: list[dict[str, Any]],
    *,
    compile_after: bool,
) -> dict[str, Any]:
    """所有待写内容哈希未变且上次成功 → 不写、不编译，保持幂等。"""
    return {
        "ok": True,
        "dry_run": False,
        "written": False,
        "skipped": "unchanged",
        "import_ok": True,
        "compiled_ok": bool(compile_after),
        "project_path": str(project),
        "bundle_dir": str(bundle),
        "imported": 0,
        "scl_imported": 0,
        "results": [],
        "scl_results": [],
        "compile": {
            "ok": True,
            "skipped": True,
            "message": "内容哈希未变化且上次已成功，跳过导入与编译门禁。",
        },
        "planned": planned,
        "skipped_items": unchanged,
        "backup_path": None,
        "rollback": {"backup_path": None, "restore_hint": ""},
        "note": _NOTE,
    }


def _backup_blocked_result(
    project: Path,
    bundle: Path,
    planned: list[dict[str, Any]],
    unchanged: list[dict[str, Any]],
    backup: dict[str, Any],
) -> dict[str, Any]:
    """备份失败/超限 → fail-closed：一个字节都不写。"""
    return {
        "ok": False,
        "dry_run": False,
        "written": False,
        "skipped": True,
        "skippedReason": str(backup.get("reason") or "backup_failed"),
        "import_ok": False,
        "compiled_ok": False,
        "project_path": str(project),
        "bundle_dir": str(bundle),
        "imported": 0,
        "scl_imported": 0,
        "results": [],
        "scl_results": [],
        "compile": {
            "ok": False,
            "skipped": True,
            "message": "备份未完成，已中止写回（fail-closed）。",
        },
        "planned": planned,
        "skipped_items": unchanged,
        "backup_path": None,
        "rollback": {"backup_path": None, "restore_hint": ""},
        "note": _NOTE,
    }


def execute_writeback(
    project_path: str | Path,
    bundle_dir: str | Path,
    plc_name: str = "",
    *,
    compile_after: bool = True,
    dry_run: bool = False,
    skip_backup: bool = False,
    skip_unchanged: bool = True,
    changeset: PlcChangeSet | None = None,
    source_xmls: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Import staged XML (comments) and SCL (logic), then fail-closed compile.

    SCL import uses official Openness
    ``CreateFromFile`` + ``GenerateBlocksFromSource``. On a Windows host that
    runs directly against the local Openness CLI; a Linux/Docker Gateway with
    a configured worker delegates the whole operation to
    ``POST /import`` on the Windows Openness worker.
    Compile must succeed before the caller archives ``.zap``. If the compile
    API is unreachable, ``ok`` is false (fail closed) — do not archive.

    Safety rails:
    - ``dry_run=True`` — build the plan (``planned``) and return before any
      import/generate/compile CLI call; nothing is written.
    - ``skip_backup=False`` (default) — copy the target project to
      ``{bundle_dir}/../backup/{UTC}/`` first; if the backup fails (or exceeds
      ``RESEARCHOS_WRITEBACK_BACKUP_MAX_MB``) the write is refused.
    - ``skip_unchanged=True`` (default) — entries whose sha256 is unchanged and
      previously succeeded are skipped (``skipped_items``).
    - ``changeset`` — optional; when given the bundle is (re)staged first, so a
      single ``execute_writeback(..., dry_run=True)`` call covers the whole
      prepare→plan path.
    """
    bundle = Path(bundle_dir).expanduser().resolve()
    project = Path(project_path).expanduser().resolve()
    export_dir = bundle.parent
    if changeset is not None:
        write_import_bundle(bundle, changeset, source_xmls)

    planned = plan_writeback(project, bundle, plc_name, compile_after=compile_after)
    if dry_run:
        return _dry_run_result(project, bundle, planned)

    xmls = _staged_xmls(bundle)
    scls = _staged_scls(bundle)

    # 幂等：哈希相同且上次成功 → 跳过；失败/变更 → 照常执行
    manifest = load_manifest(export_dir)
    pending: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    digest_by_key: dict[str, str] = {}
    for entry in planned:
        if entry["action"] == "compile":
            continue  # 编译是门禁，不是待写入条目
        if entry["action"] in WRITE_ACTIONS:
            key = manifest_key(str(entry["kind"]), str(entry["block"]))
            digest_by_key[key] = content_sha256(Path(str(entry["target"])))
            if skip_unchanged and should_skip(manifest, key, digest_by_key[key]):
                unchanged.append({**entry, "skipped": "unchanged"})
                continue
        pending.append(entry)

    planned_writes = [e for e in planned if e["action"] in WRITE_ACTIONS]
    pending_writes = [e for e in pending if e["action"] in WRITE_ACTIONS]
    if planned_writes and not pending_writes:
        return _skipped_result(
            project, bundle, planned, unchanged, compile_after=compile_after
        )

    backup: dict[str, Any] = {"ok": True, "path": None, "reason": ""}
    if pending_writes and not skip_backup:
        backup = backup_target(project, export_dir)
    if not backup.get("ok"):
        return _backup_blocked_result(project, bundle, planned, unchanged, backup)

    results: list[dict[str, Any]] = []
    scl_results: list[dict[str, Any]] = []
    import_ok = True
    payload_ok_by_key: dict[str, bool] = {}

    if _worker_preferred():
        from industrial.openness_worker.client import import_bundle_via_worker

        result = import_bundle_via_worker(
            project_path,
            bundle,
            plc_name=plc_name,
            compile_after=compile_after,
        )
        worker_ok = bool(result.get("ok"))
        status_by_key = {
            manifest_key(str(entry["kind"]), str(entry["block"])): (
                "ok" if worker_ok else "failed"
            )
            for entry in pending
            if entry["action"] in WRITE_ACTIONS
        }
        _record_manifest(export_dir, status_by_key, digest_by_key)
        result["project_path"] = str(project)
        result["bundle_dir"] = str(bundle)
        result["via"] = "openness-worker"
        result["dry_run"] = False
        result["written"] = True
        result["planned"] = planned
        result["skipped_items"] = unchanged
        result["backup_path"] = backup.get("path")
        result["rollback"] = {
            "backup_path": backup.get("path"),
            "restore_hint": _restore_hint(backup.get("path"), project),
        }
        return result

    for entry in pending:
        action = str(entry["action"])
        target = Path(str(entry["target"]))
        if action == "refuse":
            results.append(
                {
                    "xml": str(target),
                    "kind": entry["kind"],
                    "result": {
                        "ok": False,
                        "skipReason": "safety_block",
                        "error": "Refusing Import for Safety/F-block XML. Never write F-block bodies.",
                    },
                }
            )
            import_ok = False
            continue
        try:
            if action == "import_block_xml":
                payload = import_block_via_openness_cli(
                    project_path,
                    target,
                    plc_name=plc_name,
                    overwrite=True,
                )
                results.append({"xml": str(target), "kind": entry["kind"], "result": payload})
            elif action == "import_xml":
                payload = import_xml_via_openness_cli(
                    project_path,
                    target,
                    kind=str(entry["kind"]),
                    plc_name=plc_name,
                    overwrite=True,
                )
                results.append({"xml": str(target), "kind": entry["kind"], "result": payload})
            else:  # generate_from_source
                payload = generate_from_source_via_openness_cli(
                    project_path,
                    target,
                    plc_name=plc_name,
                    overwrite=True,
                )
                scl_results.append({"scl": str(target), "result": payload})
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": str(exc)}
            if action == "generate_from_source":
                scl_results.append({"scl": str(target), "result": payload})
            else:
                results.append(
                    {"xml": str(target), "kind": entry["kind"], "result": payload}
                )
        key = manifest_key(str(entry["kind"]), str(entry["block"]))
        payload_ok_by_key[key] = bool(payload.get("ok"))
        if not payload.get("ok"):
            import_ok = False

    compile_payload: dict[str, Any] | None = None
    compiled_ok = False
    if compile_after and import_ok and (xmls or scls):
        compile_payload = compile_plc_via_openness_cli(project_path, plc_name=plc_name)
        compile = (
            compile_payload.get("compile")
            if isinstance(compile_payload.get("compile"), dict)
            else compile_payload
        )
        compiled_ok = bool(compile_payload.get("ok") and (compile or {}).get("ok", True))
        if compile and compile.get("apiAvailable") is False:
            compiled_ok = False
        if compile and compile.get("ok") is False:
            compiled_ok = False
    elif compile_after and not import_ok:
        compile_payload = {
            "ok": False,
            "skipped": True,
            "message": "Compile skipped because import failed.",
        }
    elif not compile_after:
        compile_payload = {"ok": False, "skipped": True, "message": "Compile not requested."}

    ok = import_ok and (compiled_ok if compile_after else import_ok)
    # 只有「整体成功」才记为 ok：编译门禁没过时，下次必须重跑，不能让幂等跳过掩盖失败
    status_by_key = {
        key: ("ok" if (entry_ok and ok) else "failed")
        for key, entry_ok in payload_ok_by_key.items()
    }
    _record_manifest(export_dir, status_by_key, digest_by_key)
    return {
        "ok": ok,
        "dry_run": False,
        "written": True,
        "import_ok": import_ok,
        "compiled_ok": compiled_ok,
        "project_path": str(project),
        "bundle_dir": str(bundle),
        "imported": len(results),
        "scl_imported": len(scl_results),
        "results": results,
        "scl_results": scl_results,
        "compile": compile_payload,
        "planned": planned,
        "skipped_items": unchanged,
        "backup_path": backup.get("path"),
        "rollback": {
            "backup_path": backup.get("path"),
            "restore_hint": _restore_hint(backup.get("path"), project),
        },
        "note": _NOTE,
    }
