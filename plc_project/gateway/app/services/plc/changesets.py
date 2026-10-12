"""PLC changeset proposal and HITL writeback orchestration."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from gateway.app.config import get_settings

from gateway.app.services.plc.chat_intents import (
    _wants_confirm_writeback,
    _wants_optimize_scl,
)
from gateway.app.services.plc.job_store import _now
from gateway.app.services.plc.logic_graph import _logic_graph_from_kg
from gateway.app.services.plc.paths import resolve_allowed_path
from gateway.app.services.plc.writeback_views import _openness_skip_reason

logger = logging.getLogger("researchos.gateway.plc")

def propose_job_changeset(
    job: dict[str, Any],
    message: str,
    block_name: str | None = None,
    *,
    propose_optimize: Any,
) -> dict[str, Any]:
    from agents.plc.tia.changeset import propose_changeset_from_message

    text = (message or "").strip()
    # Explicit confirm is HITL writeback, never a silent re-propose.
    if _wants_confirm_writeback(text):
        existing = job.get("changeset")
        if not isinstance(existing, dict) or not existing:
            raise ValueError("No proposed changeset; preview 优化SCL first, then 确认反写")
        return existing
    # Route optimization intents to evidence-gated optimizer (not bare「反写」alone)
    if _wants_optimize_scl(text) or any(
        k in text for k in ("优化", "optimize", "死块", "dead block")
    ):
        return propose_optimize(job, block_name=block_name, message=text)
    if ("反写" in text or "writeback" in text.lower()) and any(
        k in text for k in ("优化", "逻辑", "工程", "项目")
    ):
        return propose_optimize(job, block_name=block_name, message=text)

    cs = propose_changeset_from_message(
        message,
        block_name=block_name or "",
        job_context={"project_name": job.get("project_name"), "blocks": job.get("blocks")},
    )
    job["changeset"] = cs.to_dict()
    job["updated_at"] = _now()
    return job["changeset"]


def propose_job_optimize(
    job: dict[str, Any],
    *,
    block_name: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    """Propose optimization changeset (dead + decouple + SCL rewrite)."""
    from agents.plc.tia.optimize import propose_optimization_changeset

    _ = message
    cs = propose_optimization_changeset(job, focus_block=block_name or None)
    job["changeset"] = cs.to_dict()
    job["optimize_plan"] = next(
        (n[len("optimize_plan:") :] for n in cs.notes if str(n).startswith("optimize_plan:")),
        "",
    )
    job["updated_at"] = _now()
    return job["changeset"]


def confirm_job_writeback(
    job: dict[str, Any],
    *,
    project_path: str | None = None,
    plc_name: str = "",
    accept_changeset: bool = True,
    execute_openness_import: bool = True,
    archive_zap: bool = True,
    xml_paths: list[str] | None = None,
    block_name: str | None = None,
) -> dict[str, Any]:
    """HITL: apply KG changeset, stage import bundle, optionally Openness import+save+archive.

    ``block_name`` scopes to that block plus helper FCs created for it. Empty
    focus applies the full changeset (whole-project confirm).
    """
    from agents.plc.tia.changeset import (
        PlcChangeSet,
        apply_changeset_to_kg,
        filter_changeset_for_focus,
        helper_block_names_for_focus,
    )
    from agents.plc.tia.openness_cli import archive_project_via_openness_cli
    from agents.plc.tia.understanding import filter_optimize_ops
    from agents.plc.tia.writeback import execute_writeback, prepare_writeback

    settings = get_settings()
    focus = (block_name or "").strip() or None
    raw_cs = job.get("changeset")
    if not raw_cs:
        raise ValueError("No proposed changeset; call propose first")
    original = PlcChangeSet.from_dict(raw_cs)
    scoped = filter_changeset_for_focus(original, focus)
    kept_ops, eng_skips = filter_optimize_ops(job, list(scoped.ops))
    cs = PlcChangeSet(id=original.id, ops=kept_ops, status=original.status, notes=list(original.notes))
    helpers = sorted(helper_block_names_for_focus(original, focus)) if focus else []
    scope = f"block:{focus}" if focus else "project"
    skip_reason = _openness_skip_reason(job, cs, focus=focus, extra_skips=eng_skips)

    result: dict[str, Any] = {
        "project_path": None,
        "changeset_id": cs.id,
        "kg_applied": False,
        "openness": None,
        "bundle_dir": None,
        "zap_path": None,
        "zap_archive": None,
        "scope": scope,
        "focus_block": focus,
        "helper_blocks": helpers,
        "applied_ops": len(cs.ops),
        "skipped_ops": eng_skips,
    }

    resolved_project = (project_path or job.get("project_path") or "").strip()
    target: Path | None = None
    if resolved_project:
        target = resolve_allowed_path(resolved_project, settings)
        if target.suffix.lower() not in {".ap17", ".ap18", ".ap19", ".ap20", ".apxx"}:
            raise ValueError(f"Write-back target must be a TIA .apxx project, got {target.suffix}")
    result["project_path"] = str(target) if target else None

    if accept_changeset:
        cs.status = "accepted"
        kg = apply_changeset_to_kg(job.get("knowledge_graph") or {}, cs)
        job["knowledge_graph"] = kg
        job["logic_graph"] = _logic_graph_from_kg(kg)
        # Mirror comments onto block list
        for op in cs.ops:
            if op.kind == "set_block_comment":
                name = op.payload.get("block_name")
                for b in job.get("blocks") or []:
                    if b.get("name") == name:
                        b["comment"] = str(op.payload.get("comment") or "")[:240]
        result["kg_applied"] = True

    export_root = job.get("export_dir") or tempfile.mkdtemp(prefix="ros_plc_wb_")
    staged_ops = [op for op in cs.ops if op.kind == "stage_xml_import"]
    comment_ops = [op for op in cs.ops if op.kind == "set_block_comment"]
    if xml_paths:
        sources = list(xml_paths)
    elif staged_ops or comment_ops:
        # Lookup pool for comment→XML resolve; bundle only stages matched files
        sources = list(job.get("source_xmls") or [])
        for op in staged_ops:
            if op.payload.get("xml_path"):
                sources.append(str(op.payload["xml_path"]))
    else:
        # SCL-only: do not legacy-stage the whole source XML pool
        sources = []

    bundle = prepare_writeback(export_root, cs, sources)
    result["bundle_dir"] = str(bundle)
    result["staged_scls"] = [
        str(p) for p in (bundle / "external_sources").glob("*.scl")
    ] if (bundle / "external_sources").is_dir() else []

    has_xml = list(bundle.glob("*.xml"))
    has_scl = (
        list((bundle / "external_sources").glob("*.scl"))
        if (bundle / "external_sources").is_dir()
        else []
    )
    if execute_openness_import and not has_xml and not has_scl:
        why = skip_reason or (
            f"`{focus}` 没有可落地的 XML/SCL 写回，不调用 Openness。"
            if focus
            else "当前变更集没有可导入的 XML/SCL，不调用 Openness。"
        )
        result["skipped"] = True
        result["skip_reason"] = why
        result["openness"] = {"ok": False, "skipped": True, "reason": why}
        result["zap_archive"] = {"ok": False, "skipped": True, "reason": why}
        job["changeset"] = original.to_dict()
        job["writeback"] = result
        job["updated_at"] = _now()
        return result

    if execute_openness_import:
        if target is None:
            raise ValueError("project_path required for Openness import")
        openness = execute_writeback(target, bundle, plc_name=plc_name)
        result["openness"] = openness
        result["compile"] = openness.get("compile")
        if not openness.get("import_ok", openness.get("ok")):
            raise RuntimeError(f"Openness import failed: {openness}")
        if openness.get("ok"):
            cs.status = "applied"
        else:
            # Import may have succeeded; compile gate failed — do not archive.
            compile = openness.get("compile") or {}
            inner = compile.get("compile") if isinstance(compile, dict) else None
            inconsistent = None
            if isinstance(inner, dict):
                inconsistent = inner.get("inconsistentBlocks")
            elif isinstance(compile, dict):
                inconsistent = compile.get("inconsistentBlocks")
            result["zap_archive"] = {
                "ok": False,
                "skipped": True,
                "reason": "compile_failed",
                "compile": compile,
                "inconsistent_blocks": inconsistent,
            }
            stored = original.to_dict()
            stored["status"] = cs.status
            job["changeset"] = stored
            job["writeback"] = result
            job["updated_at"] = _now()
            return result

        if archive_zap and openness.get("ok"):
            out_dir = Path(export_root) / "archived"
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                zap_file = archive_project_via_openness_cli(target, out=out_dir)
                result["zap_path"] = str(zap_file)
                result["zap_archive"] = {"ok": True, "path": str(zap_file)}
            except Exception as exc:  # noqa: BLE001 — import succeeded; surface archive separately
                logger.exception("PLC zap archive failed job_id=%s", job.get("id"))
                result["zap_archive"] = {"ok": False, "error": str(exc)}
    else:
        cs.status = "accepted" if accept_changeset else cs.status
        result["openness"] = {
            "ok": True,
            "skipped": True,
            "note": "KG/bundle only; Openness import not requested",
        }

    stored = original.to_dict()
    stored["status"] = cs.status
    job["changeset"] = stored
    job["writeback"] = result
    job["updated_at"] = _now()
    return result
