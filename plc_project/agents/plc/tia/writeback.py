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
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agents.plc.tia.changeset import PlcChangeSet, write_import_bundle
from agents.plc.tia.openness_cli import (
    compile_plc_via_openness_cli,
    exception_chain_messages,
    generate_from_source_via_openness_cli,
    import_block_via_openness_cli,
    import_xml_via_openness_cli,
    openness_cli,
)
from agents.plc.tia.surface import classify_xml_kind, xml_looks_like_safety
from plc_engine.writeback_contract import BlockArtifact, scl_block_name

logger = logging.getLogger(__name__)

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


def _staged_scl_entries(bundle_dir: Path) -> list[dict[str, Any]]:
    manifest = bundle_dir / "staged_scls.json"
    if manifest.is_file():
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            raw = []
        entries = []
        for item in raw:
            if isinstance(item, dict):
                p = Path(item.get("path", ""))
                if p.is_file():
                    entries.append({"path": p, "software_unit": str(item.get("software_unit") or item.get("unit") or "")})
            elif isinstance(item, str) and Path(item).is_file():
                entries.append({"path": Path(item), "software_unit": ""})
        return entries
    ext = bundle_dir / "external_sources"
    if ext.is_dir():
        return [{"path": p, "software_unit": p.parent.name if p.parent != ext else ""} for p in ext.rglob("*.scl") if p.is_file()]
    return []


def _staged_scls(bundle_dir: Path) -> list[Path]:
    return [e["path"] for e in _staged_scl_entries(bundle_dir)]


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
    for entry in _staged_scl_entries(bundle):
        scl = entry["path"]
        planned.append(
            {
                "action": "generate_from_source",
                "block": scl.stem,
                "target": str(scl),
                "kind": "scl",
                "software_unit": entry.get("software_unit", ""),
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


def _knowhow_block_names(project_path: str | Path, plc_name: str = "") -> set[str]:
    """list-blocks 一次,返回工程里 know-how 保护块名(保原件过滤依据)。

    best-effort:CLI 不可用/超时/返回异常 → 空集(不过滤,维持旧行为);
    不抛错——本查询只为剔除毒块,不允许它自己变成写回故障点。
    """
    args = ["list-blocks", "--project", str(project_path)]
    if plc_name:
        args.extend(["--plc", plc_name])
    try:
        result = openness_cli(*args, timeout_s=240)
    except Exception as exc:  # noqa: BLE001
        logger.warning("list-blocks 查询 know-how 名单失败(跳过过滤): %s", exc)
        return set()
    names: set[str] = set()
    listed = result.get("blocks")
    if isinstance(listed, dict):
        for item in listed.get("blocks") or []:
            if isinstance(item, dict) and item.get("knowHowProtected"):
                nm = str(item.get("name") or "").strip()
                if nm:
                    names.add(nm)
    return names


def _exception_result(exc: BaseException) -> dict[str, Any]:
    """异常 → 失败 result payload（错误收集专用）。

    ``str(exc)`` 只含最外层消息；这里把 Python 异常链
    （``__cause__``/``__context__``，等价 .NET InnerException）逐层追加为
    ``内部异常: …`` 行，并同步给出结构化 ``error_chain``。只增信息、
    不改既有前缀——compile_jobs 归因 / fix_loop / refactor_pipeline
    均按 message 字符串消费，追加详情行不会破坏解析。
    """
    text = str(exc)
    chain = exception_chain_messages(exc)
    if chain:
        text += "\n" + "\n".join(f"内部异常: {message}" for message in chain)
    payload: dict[str, Any] = {"ok": False, "error": text}
    if chain:
        payload["error_chain"] = chain
    return payload


def resolve_block_dependencies(blocks: Sequence[BlockArtifact]) -> list[BlockArtifact]:
    """根据 SCL 源码中的符号引用自动分析正向依赖 (dependencies)，供 Kahn 拓扑排序生成。"""
    out_blocks = list(blocks)
    name_to_block = {b.name.strip('"'): b for b in out_blocks}
    for b in out_blocks:
        cur_clean = b.name.strip('"')
        for other_name in name_to_block:
            if other_name == cur_clean:
                continue
            pat = r'(?:"' + re.escape(other_name) + r'"|\b' + re.escape(other_name) + r'\b)'
            if re.search(pat, b.source):
                if other_name not in b.dependencies:
                    b.dependencies.append(other_name)
    return out_blocks


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

    xml_pending = [e for e in pending if e["action"] != "generate_from_source"]
    scl_pending = [e for e in pending if e["action"] == "generate_from_source"]
    # 修①配套:legacy 批次被剔除的 know-how 加密块名单(结果字段,无 SCL 通道时为空)
    knowhow_skipped: list[str] = []

    for entry in xml_pending:
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
        except Exception as exc:  # noqa: BLE001
            payload = _exception_result(exc)
            results.append({"xml": str(target), "kind": entry["kind"], "result": payload})

        key = manifest_key(str(entry["kind"]), str(entry["block"]))
        payload_ok_by_key[key] = bool(payload.get("ok"))
        if not payload.get("ok"):
            import_ok = False

    batch_payload: dict[str, Any] | None = None
    if scl_pending and import_ok:
        from agents.plc.tia.writeback_batch import (
            BATCH_FILE_NAME,
            infer_kind,
            prepare_batch_writeback,
        )
        blocks: list[BlockArtifact] = []
        for entry in scl_pending:
            target = Path(str(entry["target"]))
            try:
                src = target.read_text(encoding="utf-8-sig")
                kind = infer_kind(src) or "FB"
                name = scl_block_name(src) or str(entry.get("block") or target.stem)
                blocks.append(BlockArtifact(name=name, kind=kind, source=src))
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取 SCL 外部源失败 %s: %s", target, exc)

        # 分批回写保障：AF 架构核心块与 UDT（批次 1，高可靠零错误通道） vs 旧块（批次 2，隔离通道）
        af_blocks = [b for b in blocks if "::" in b.name or b.name.startswith("U1") or b.name.startswith("AF_type")]
        legacy_blocks = [b for b in blocks if b not in af_blocks]

        # 修①(真机 HR002 案例 51c23082…):legacy 批次可能混有 know-how 加密块——
        # 导入侧 XML 未携带保护属性、画布 protected=False 时,用翻译体覆盖加密块
        # 会被 TIA 在 GenerateBlocksFromSource 整批拒绝(报错戛然而止难定位)。
        # 保原件语义:加密块不参与覆盖生成,留在工程里不动。list-blocks 一次取
        # 真机保护名单(best-effort:CLI 不可用/超时则不过滤,维持旧行为)。
        if legacy_blocks:
            knowhow_names = _knowhow_block_names(project_path, plc_name)
            if knowhow_names:
                keep_blocks: list[BlockArtifact] = []
                for b in legacy_blocks:
                    if b.name in knowhow_names:
                        knowhow_skipped.append(b.name)
                    else:
                        keep_blocks.append(b)
                legacy_blocks = keep_blocks
                if knowhow_skipped:
                    logger.info(
                        "legacy 批次剔除 know-how 加密块 %d 个(保原件不覆盖): %s",
                        len(knowhow_skipped),
                        ", ".join(knowhow_skipped[:8]),
                    )

        batches_to_run: list[tuple[str, list[BlockArtifact]]] = []
        if af_blocks and not legacy_blocks:
            batches_to_run.append((BATCH_FILE_NAME, af_blocks))
        elif legacy_blocks and not af_blocks:
            batches_to_run.append((BATCH_FILE_NAME, legacy_blocks))
        elif af_blocks and legacy_blocks:
            batches_to_run.append((BATCH_FILE_NAME, af_blocks))
            batches_to_run.append(("01_Legacy_Batch.scl", legacy_blocks))
        elif blocks:
            batches_to_run.append((BATCH_FILE_NAME, blocks))

        overall_batch_ok = True
        for batch_filename, sub_blocks in batches_to_run:
            sub_blocks = resolve_block_dependencies(sub_blocks)
            sub_plan = prepare_batch_writeback(sub_blocks, output_dir=export_dir)
            if not sub_plan.bundle_path:
                continue

            sub_batch_path = Path(sub_plan.bundle_path)
            # 重命名为对应的批次文件名，避免覆盖
            dest_batch_path = export_dir / batch_filename
            if sub_batch_path.is_file() and sub_batch_path.resolve() != dest_batch_path.resolve():
                if dest_batch_path.exists():
                    dest_batch_path.unlink()
                sub_batch_path.rename(dest_batch_path)
                sub_batch_path = dest_batch_path

            sub_payload = None
            try:
                payload = generate_from_source_via_openness_cli(
                    project,
                    sub_batch_path,
                    plc_name=plc_name,
                    software_unit="",
                    overwrite=True,
                )
                sub_payload = {
                    "ok": bool(payload.get("ok")),
                    "success": bool(payload.get("ok")),
                    "generate": payload,
                }
            except Exception as exc:  # noqa: BLE001
                sub_payload = _exception_result(exc)

            sub_ok = bool(sub_payload.get("ok") or sub_payload.get("success"))
            if not sub_ok:
                overall_batch_ok = False
                logger.warning("批次生成告警 [%s]: %s", batch_filename, sub_payload.get("error"))

            # 记录批次结果
            batch_payload = sub_payload
            scl_results.append({
                "scl": str(sub_batch_path),
                "result": sub_payload,
                "blocks": [b.name for b in sub_blocks],
            })

            # 更新 manifest
            for entry in scl_pending:
                key = manifest_key(str(entry["kind"]), str(entry["block"]))
                payload_ok_by_key[key] = sub_ok

        import_ok = overall_batch_ok

    compile_payload: dict[str, Any] | None = None
    compiled_ok = False
    if compile_after and import_ok and (xmls or scls):
        if (
            batch_payload
            and batch_payload.get("compileScope")
            and batch_payload.get("compileScope") != "not_run"
            and not batch_payload.get("fallback")
        ):
            compiled_ok = bool(batch_payload.get("success"))
            compile_payload = {
                "ok": compiled_ok,
                "compile": {
                    "ok": compiled_ok,
                    "scope": batch_payload.get("compileScope"),
                    "note": batch_payload.get("compileScopeNote"),
                    "errors": batch_payload.get("errors") or [],
                    "errorCount": len(batch_payload.get("errors") or []),
                },
            }
        else:
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
        "knowhow_skipped": knowhow_skipped,
        "backup_path": backup.get("path"),
        "rollback": {
            "backup_path": backup.get("path"),
            "restore_hint": _restore_hint(backup.get("path"), project),
        },
        "note": _NOTE,
    }
