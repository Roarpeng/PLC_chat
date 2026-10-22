"""PLC project ingestion orchestration."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from gateway.app.config import get_settings
from gateway.app.services.plc.job_store import (
    _append_progress,
    _finish_progress,
    _now,
    _start_progress,
    get_job,
)
from gateway.app.services.plc.logic_graph import (
    _logic_graph_from_kg,
)

logger = logging.getLogger("researchos.gateway.plc")


def _publish_plc_graph_background(
    job_id: str,
    project_name: str,
    kg: dict[str, Any],
) -> None:
    """Best-effort persistence; interactive PLC work uses the in-memory job KG."""
    import time

    from agents.plc.tia.kg import PlcKnowledgeGraph
    from agents.plc.tia.neo4j_publish import publish_plc_knowledge_graph

    job = get_job(job_id)
    if job is None:
        return
    started = time.monotonic()
    try:
        graph = PlcKnowledgeGraph.from_json(kg)
        result = publish_plc_knowledge_graph(graph, project_name=project_name)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        result["background_ms"] = elapsed_ms
        job["graph_publish"] = result
        job["timings"] = {**(job.get("timings") or {}), "neo4j_background_ms": elapsed_ms}
        job["updated_at"] = _now()
        logger.info(
            "PLC background graph publish job_id=%s entities=%s relations=%s ms=%s",
            job_id,
            result.get("entities"),
            result.get("relations"),
            elapsed_ms,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.monotonic() - started) * 1000)
        job["graph_publish"] = {
            "ok": False,
            "status": "failed",
            "error": str(exc),
            "background_ms": elapsed_ms,
        }
        job["updated_at"] = _now()
        logger.warning("PLC background graph publish failed job_id=%s: %s", job_id, exc)


def _annotate_blocks_from_structure(
    blocks: list[dict[str, Any]],
    structure: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Copy M1 export status onto parsed blocks and append omitted units."""
    units = (structure or {}).get("units") or []
    by_name = {
        str(u.get("name") or ""): u
        for u in units
        if u.get("name") and u.get("kind") in {"block", "db", "udt"}
    }
    for row in blocks:
        unit = by_name.get(str(row.get("name") or ""))
        if not unit:
            row.setdefault("status", "exported")
            row.setdefault("status_reason", "")
            row.setdefault("status_detail", "")
            row.setdefault("retryable", False)
            continue
        row["status"] = unit.get("status") or "exported"
        row["status_reason"] = unit.get("reason") or ""
        row["status_detail"] = unit.get("detail") or ""
        row["retryable"] = bool(unit.get("retryable"))
    seen = {str(b.get("name") or "") for b in blocks}
    for name, unit in by_name.items():
        if name in seen:
            continue
        blocks.append(
            {
                "name": name,
                "type": unit.get("type") or unit.get("kind") or "Block",
                "number": unit.get("number"),
                "language": unit.get("language"),
                "networks": 0,
                "comment": (unit.get("detail") or unit.get("reason") or "")[:240],
                "inputs": [],
                "outputs": [],
                "inouts": [],
                "statics": [],
                "members": [],
                "instance_of": unit.get("instance_of"),
                "protected": bool(unit.get("protected")),
                "interface_only": bool(unit.get("interface_only")),
                "body_available": bool(unit.get("body_available")),
                "is_safety": bool(unit.get("is_safety")),
                "status": unit.get("status") or "pending",
                "status_reason": unit.get("reason") or "",
                "status_detail": unit.get("detail") or "",
                "retryable": bool(unit.get("retryable")),
            }
        )
    blocks.sort(key=lambda b: (b.get("type") or "", b.get("name") or ""))
    return blocks


def _block_list(project: Any, structure: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for name, block in (getattr(project, "blocks", {}) or {}).items():
        interface = getattr(block, "interface", None) or []
        inputs: list[str] = []
        outputs: list[str] = []
        inouts: list[str] = []
        statics: list[str] = []
        members: list[str] = []
        for v in interface:
            section = getattr(v, "section", None)
            sec = getattr(section, "value", None) or str(section or "")
            var_name = getattr(v, "name", "") or ""
            dtype = getattr(v, "data_type", "") or ""
            if not var_name:
                continue
            label = f"#{var_name}"
            member = f"{var_name} : {dtype}" if dtype else var_name
            members.append(member)
            if sec == "Input":
                inputs.append(label)
            elif sec == "Output":
                outputs.append(label)
            elif sec == "InOut":
                inouts.append(label)
            elif sec == "Static":
                statics.append(f"{label} : {dtype}" if dtype else label)
        attrs = getattr(block, "attributes", None) or {}
        instance_of = (
            str(attrs.get("InstanceOfName") or "").strip()
            or str(attrs.get("OfType") or "").strip()
            or str(attrs.get("OfBlock") or "").strip()
            or None
        )
        is_protected = bool(getattr(block, "is_protected", lambda: False)())
        is_iface_only = bool(getattr(block, "is_interface_only", lambda: False)())
        body_ok = bool(getattr(block, "has_program_body", lambda: True)())
        blocks.append(
            {
                "name": name,
                "type": getattr(getattr(block, "block_type", None), "value", str(getattr(block, "block_type", ""))),
                "number": getattr(block, "number", None),
                "language": getattr(block, "programming_language", None),
                "networks": len(getattr(block, "networks", []) or []),
                "comment": (getattr(block, "header_comment", None) or "")[:240],
                "inputs": inputs,
                "outputs": outputs,
                "inouts": inouts,
                "statics": statics,
                "members": members,
                "instance_of": instance_of,
                "protected": is_protected,
                "interface_only": is_iface_only,
                "body_available": body_ok,
                "is_safety": bool(getattr(block, "is_safety", False)),
                "status": "exported",
                "status_reason": "",
                "status_detail": "",
                "retryable": False,
                "export_status": (
                    "interface_only"
                    if is_iface_only
                    else "protected"
                    if is_protected and not body_ok
                    else "unknown"
                ),
            }
        )
    return _annotate_blocks_from_structure(blocks, structure)


def _annotate_block_nest_depth(job: dict[str, Any]) -> None:
    """Copy TYPED_AS nest_depth onto job.blocks for node cards / chat."""
    from agents.plc.tia.typed_as import nest_depth_of

    kg = job.get("knowledge_graph") or {}
    memo: dict[str, int] = {}
    for block in job.get("blocks") or []:
        name = str(block.get("name") or "")
        if not name:
            continue
        block["nest_depth"] = nest_depth_of(kg, name, _memo=memo)






def _degradation_warnings(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten coverage warnings + review truncation into one visible list."""
    warnings: list[dict[str, Any]] = [
        item
        for item in (job.get("coverage") or {}).get("warnings") or []
        if isinstance(item, dict)
    ]
    review = job.get("review") or {}
    if review.get("truncated"):
        warnings.append(
            {
                "level": "info",
                "code": "review.truncated",
                "message": (
                    f"确定性审查报告被截断：实际命中 {int(review.get('total_count') or 0)} 处，"
                    "每条规则只展示前若干条，别把报告里的条数当成问题总数。"
                ),
                "affected_blocks": sorted(
                    {
                        str(finding.get("block"))
                        for finding in review.get("findings") or []
                        if isinstance(finding, dict)
                        and finding.get("truncated")
                        and finding.get("block")
                    }
                ),
                "count": int(review.get("total_count") or 0),
            }
        )
    return warnings


def _degradation_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Compact rollup for the UI — coverage numbers plus every honest warning."""
    coverage = job.get("coverage") or {}
    warnings = _degradation_warnings(job)
    export_dir = str(job.get("export_dir") or "")
    return {
        "count": len(warnings),
        "warnings": warnings,
        "todo_rate": coverage.get("todo_rate", 0.0),
        "translated_rate": coverage.get("translated_rate"),
        "review_truncated": bool((job.get("review") or {}).get("truncated")),
        "review_total_count": int((job.get("review") or {}).get("total_count") or 0),
        "coverage_path": str(Path(export_dir) / "reports" / "coverage.json") if export_dir else None,
    }


def run_ingest_job(
    job_id: str,
    *,
    publish_graph: bool = True,
    plc_name: str = "",
    tia_version: str = "",
    result_root: str | None = None,
) -> dict[str, Any]:
    """Synchronously run plc.tia.ingest pipeline into the job record."""
    import time

    from agents.plc.tia.timings import timings_summary

    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)

    job["status"] = "running"
    job["progress"] = []
    job["timings"] = {}
    job["updated_at"] = _now()
    t_all = time.monotonic()
    _start_progress(
        job,
        "detect",
        "检测工程输入",
        detail=str(job.get("source_path") or ""),
    )

    settings = get_settings()
    work = Path(result_root or settings.plc_work_dir or tempfile.gettempdir()) / "researchos_plc_jobs" / job_id
    work.mkdir(parents=True, exist_ok=True)

    try:
        from agents.plc.tia.importer import resolve_project_input
        from agents.plc.tia.package import write_result_package
        from agents.plc.tia.pipeline import analyze_tia_exports, interpretation_report
        from agents.plc.tia.timings import merge_timings

        _finish_progress(job)
        _start_progress(
            job,
            "resolve",
            "解析输入（.zap / .apxx / XML）",
            detail="必要时调用 TIA Openness 导出 SimaticML",
        )
        t_resolve = time.monotonic()
        imported = resolve_project_input(
            job["source_path"],
            tia_version=tia_version,
            plc_name=plc_name,
            auto_export=True,
        )
        resolve_wall_ms = int((time.monotonic() - t_resolve) * 1000)
        pipeline_timings: dict[str, int] = merge_timings(
            {"resolve_wall_ms": resolve_wall_ms},
            imported.timings,
        )
        resolve_detail = (
            f"source_kind={imported.source_kind}; export_dir={imported.export_dir}"
        )[:240]
        fine = {
            k: pipeline_timings[k]
            for k in (
                "unzip_ms",
                "stage_copy_ms",
                "openness_cli_ms",
                "openness_open_ms",
                "openness_compile_ms",
                "openness_list_ms",
                "openness_blocks_export_ms",
                "openness_export_ms",
                "openness_skip_compile_ms",
                "openness_compile_retry_ms",
                "openness_cache_hit_ms",
                "openness_cache_hit",
                "resolve_wall_ms",
            )
            if k in pipeline_timings
        }
        if fine:
            resolve_detail = (resolve_detail + " | " + timings_summary(fine)).strip(" |")[:400]
        _finish_progress(job, detail=resolve_detail)

        if imported.project_path:
            job["project_path"] = str(imported.project_path)
        elif Path(str(job["source_path"])).suffix.lower() in {
            ".ap17", ".ap18", ".ap19", ".ap20", ".apxx",
        }:
            job["project_path"] = str(Path(str(job["source_path"])).resolve())
        job["openness_export_dir"] = str(imported.export_dir)

        name = job.get("project_name") or (
            imported.project_path.stem
            if imported.project_path
            else imported.export_dir.name
        )
        _start_progress(
            job,
            "structure",
            "结构先行：块清单 / 接口 / 调用图（不等待全文翻译）",
        )

        def _on_structure(project_obj: Any, kg_obj: Any) -> None:
            from gateway.app.services.plc.brief import persist_structure_snapshot
            from gateway.app.services.plc.job_store import _finish_progress, _start_progress

            job["blocks"] = _block_list(project_obj)
            persist_structure_snapshot(job, project_obj, kg_obj, phase="structure")
            job["ingest_phase"] = "bodies_queued"
            _finish_progress(
                job,
                detail=f"brief_ready blocks={len(job.get('blocks') or [])}",
            )
            _start_progress(
                job,
                "bodies",
                "排队拉取 SCL/LAD 程序体",
                detail=f"queued={len(job.get('body_pull_queue') or [])}",
            )

        from agents.plc.tia.ir import PlcProject

        pre_project = imported.project if isinstance(imported.project, PlcProject) else None
        result = analyze_tia_exports(
            str(imported.export_dir),
            project_name=name,
            publish_graph=publish_graph,
            project=pre_project,
            on_structure=_on_structure,
        )
        pipeline_timings = merge_timings(pipeline_timings, result.get("timings"))
        project = result["project"]
        for note in imported.notes or []:
            project.extraction_notes.append(note)
        if imported.tia_version:
            project.tia_version = imported.tia_version
        if imported.project_path:
            project.source_path = str(imported.project_path)

        t_pkg = time.monotonic()
        write_result_package(
            str(work / "package"),
            project=project,
            knowledge_graph=result["knowledge_graph"],
            scl_sources=result.get("scl_sources") or {},
            report_md=interpretation_report(project, result["knowledge_graph"]),
            extra_meta={
                "source_kind": imported.source_kind,
                "export_dir": str(imported.export_dir),
                "tia_version": imported.tia_version,
                "timings": pipeline_timings,
                "structure": result.get("structure") or {},
            },
        )
        pipeline_timings["package_ms"] = int((time.monotonic() - t_pkg) * 1000)

        kg = result["knowledge_graph"].to_json()
        job["project_name"] = project.name
        job["summary"] = project.summary()
        job["extraction_notes"] = list(project.extraction_notes or [])
        job["knowledge_graph"] = kg
        job["scl_sources"] = result.get("scl_sources") or {}
        job["folded_logic"] = result.get("folded_logic") or {}
        job["report"] = interpretation_report(project, result["knowledge_graph"])
        job["graph_publish"] = result.get("graph_publish")
        job["structure"] = result.get("structure") or {}
        job["blocks"] = _block_list(project, job["structure"])
        from gateway.app.services.plc.brief import hardware_rows, refresh_brief_artifacts

        job["hardware"] = hardware_rows(job, project)
        job["coverage"] = result.get("coverage") or {}
        refresh_brief_artifacts(job)
        job["export_dir"] = str(work / "package")
        job["export_ready"] = True
        ir_bits = {
            k: pipeline_timings[k]
            for k in (
                "extract_ms",
                "fold_attach_ms",
                "kg_ms",
                "scl_ms",
                "fold_serialize_ms",
                "package_ms",
                "neo4j_ms",
                "report_ms",
            )
            if k in pipeline_timings
        }
        _finish_progress(
            job,
            detail=(
                f"块数={len(job['blocks'])}"
                + (f" | {timings_summary(ir_bits)}" if ir_bits else "")
            )[:400],
        )

        # Prefer Openness export XMLs for write-back staging
        xml_root = job.get("openness_export_dir") or job["source_path"]
        job["source_xmls"] = _collect_source_xmls(str(xml_root))
        from agents.plc.tia.xml_understand import enrich_kg_calls_from_xml_files

        _start_progress(
            job,
            "enrich",
            "XML CallInfo 补全 CALLS",
            detail=f"xmls={len(job['source_xmls'] or [])}",
        )
        t_enrich = time.monotonic()
        kg = enrich_kg_calls_from_xml_files(
            kg,
            xml_paths=job["source_xmls"] or [],
            known_blocks={str(b.get("name")) for b in job["blocks"] if b.get("name")},
            # Deterministic CallInfo extraction is enough for ingest. LLM assist is
            # opt-in because a large project can otherwise spend minutes on 429s.
            use_llm=os.getenv("RESEARCHOS_XML_UNDERSTAND_LLM", "").strip().lower()
            in {"1", "true", "yes", "on"},
        )
        enrich_ms = int((time.monotonic() - t_enrich) * 1000)
        pipeline_timings["enrich_ms"] = enrich_ms
        job["knowledge_graph"] = kg
        _finish_progress(job, detail=f"edges={len(kg.get('edges') or [])}; enrich_ms={enrich_ms}")

        _start_progress(job, "graph", "生成逻辑图")
        t_logic = time.monotonic()
        job["logic_graph"] = _logic_graph_from_kg(kg)
        logic_ms = int((time.monotonic() - t_logic) * 1000)
        pipeline_timings["logic_graph_ms"] = logic_ms
        _annotate_block_nest_depth(job)
        _finish_progress(
            job,
            detail=(
                f"KG nodes={len(kg.get('nodes') or [])}, "
                f"edges={len(kg.get('edges') or [])}; "
                f"logic edges={len((job.get('logic_graph') or {}).get('edges') or [])}; "
                f"logic_graph_ms={logic_ms}"
            )[:400],
        )
        try:
            from agents.plc.tia.dossier import build_block_dossiers
            from agents.plc.tia.review import run_review

            _start_progress(job, "review", "确定性审查与节点档案")
            t_review = time.monotonic()
            job["review"] = run_review(job)
            job["dossiers"] = build_block_dossiers(job)
            pipeline_timings["review_ms"] = int((time.monotonic() - t_review) * 1000)
            review_summary = (job.get("review") or {}).get("summary") or {}
            _finish_progress(
                job,
                detail=(
                    f"审查发现={review_summary.get('total', 0)}"
                    f"（警告 {review_summary.get('warning', 0)}）"
                    f"；档案={len((job.get('dossiers') or {}).get('blocks') or {})}"
                )[:400],
            )
        except Exception as exc:  # noqa: BLE001 — review/dossier must not sink ingest
            logger.debug("deterministic review skipped: %s", exc)
        try:
            from agents.plc.tia.understanding import ensure_understanding

            ensure_understanding(job)
        except Exception as exc:  # noqa: BLE001
            logger.debug("engineer understanding seed skipped: %s", exc)
        # Empty IR after ingesting a raw .zap/.apxx tree is a hard failure, not "ready".
        # Skipped/failed program units still count — M1 forbids omitting them.
        if not job["blocks"]:
            from agents.plc.tia.importer import (
                find_apxx_files,
                openness_unavailable_guidance,
            )
            from agents.plc.tia.openness_cli import format_openness_failure, is_license_error

            notes_blob = " ".join(job["extraction_notes"] or [])
            if is_license_error(notes_blob):
                raise RuntimeError(
                    format_openness_failure(
                        notes_blob,
                        project_path=job.get("project_path"),
                        action="export",
                    )
                )

            src = Path(str(job.get("project_path") or job["source_path"]))
            scan = src if src.is_dir() else src.parent
            apxx = find_apxx_files(scan) if scan.is_dir() else (
                [src] if src.suffix.lower() in {".ap17", ".ap18", ".ap19", ".ap20", ".apxx"} else []
            )
            if apxx:
                raise RuntimeError(openness_unavailable_guidance(apxx[0]))
            notes = "; ".join(job["extraction_notes"][:3]) if job["extraction_notes"] else ""
            raise RuntimeError(
                "未识别到任何 PLC 程序块或标签表，无法生成逻辑图/知识图谱。"
                + (f" 备注: {notes}" if notes else " 请上传 Openness 导出的 Blocks XML 或含 Blocks 的 ZIP。")
            )
        total_ms = int((time.monotonic() - t_all) * 1000)
        pipeline_timings["total_ms"] = total_ms
        job["timings"] = pipeline_timings
        job["degradations"] = _degradation_summary(job)
        if job["degradations"]["count"]:
            logger.info(
                "PLC ingest degradations job_id=%s count=%s codes=%s",
                job_id,
                job["degradations"]["count"],
                [w.get("code") for w in job["degradations"]["warnings"]],
            )
        if publish_graph:
            job["graph_publish"] = {"ok": True, "status": "queued"}
            threading.Thread(
                target=_publish_plc_graph_background,
                args=(job_id, name, kg),
                name=f"plc-graph-publish-{job_id}",
                daemon=True,
            ).start()
        _append_progress(
            job,
            "ready",
            "解析完成，可对话确认与写回",
            status="done",
            duration_ms=total_ms,
            detail=timings_summary(pipeline_timings)[:400],
        )
        logger.info(
            "PLC ingest timings job_id=%s %s",
            job_id,
            timings_summary(pipeline_timings),
        )
        job["status"] = "ready"
        job["ingest_phase"] = "ready"
        job["brief_ready"] = True
        job["error"] = None
    except Exception as exc:
        logger.exception("PLC ingest failed job_id=%s", job_id)
        job["status"] = "failed"
        job["ingest_phase"] = "failed"
        job["error"] = str(exc)
        # Close any running progress step
        if (job.get("progress") or []) and job["progress"][-1].get("status") == "running":
            _finish_progress(job, detail=str(exc)[:240], status="failed")
        _append_progress(job, "failed", "解析失败", detail=str(exc)[:400], status="failed")
        job["timings"] = {
            **dict(job.get("timings") or {}),
            "total_ms": int((time.monotonic() - t_all) * 1000),
        }
    job["updated_at"] = _now()
    return job


def _collect_source_xmls(source_path: str) -> list[str]:
    p = Path(source_path)
    if p.is_file() and p.suffix.lower() == ".xml":
        return [str(p.resolve())]
    if p.is_dir():
        return [str(x.resolve()) for x in sorted(p.rglob("*.xml"))][:200]
    return []


def retry_structure_export(
    job_id: str,
    *,
    names: list[str] | None = None,
    publish_graph: bool = True,
) -> dict[str, Any]:
    """Re-run Openness/structure ingest so failed/pending units can recover.

    Unit names are recorded on the job for diagnostics. The export CLI is
    project-wide (list + export), so retry always re-walks the source rather
    than silently dropping units that were previously skipped.
    """
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.get("status") not in {"ready", "failed", "queued"}:
        raise ValueError(f"Job status is {job.get('status')}, expected ready, failed, or queued")
    wanted = [str(n).strip() for n in (names or []) if str(n).strip()]
    job["structure_retry"] = {
        "names": wanted,
        "requested_at": _now().isoformat(),
    }
    logger.info(
        "PLC structure retry job_id=%s names=%s",
        job_id,
        wanted or "*",
    )
    return run_ingest_job(
        job_id,
        publish_graph=publish_graph,
        plc_name=str(job.get("plc_name") or ""),
        tia_version=str(job.get("tia_version") or ""),
    )
