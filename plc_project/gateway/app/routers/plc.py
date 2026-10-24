"""PLC Intelligence API — ResearchOS industrial feature module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from gateway.app.deps import PrincipalDep, RequestIdDep
from gateway.app.schemas.common import ApiResponse
from gateway.app.schemas.plc import (
    DeviceCardAnnotationRequest,
    DeviceCardListResponse,
    DeviceSensorCard,
    PlcAnalyzeRequest,
    PlcChatRequest,
    PlcChatTurn,
    PlcGraphQueryRequest,
    PlcGraphQueryResponse,
    PlcJobCreatePath,
    PlcJobDetail,
    PlcJobSummary,
    PlcOptimizeRequest,
    PlcProjectBrief,
    PlcProposeChangeRequest,
    PlcStructureRetryRequest,
    PlcWritebackRequest,
)
from gateway.app.services import plc_jobs as plc

logger = logging.getLogger("researchos.gateway.plc")

router = APIRouter(prefix="/api/v1/plc", tags=["plc"])


def _summary(job: dict[str, Any]) -> PlcJobSummary:
    return PlcJobSummary.model_validate(job)


def _detail(job: dict[str, Any]) -> PlcJobDetail:
    return PlcJobDetail.model_validate(job)


@router.post(
    "/jobs",
    response_model=ApiResponse[PlcJobSummary],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job_from_path(
    body: PlcJobCreatePath,
    background: BackgroundTasks,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[PlcJobSummary]:
    """Create ingest job from a server-visible path under PLC_PATH_ALLOWLIST."""
    try:
        resolved = plc.resolve_allowed_path(body.path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_PATH_NOT_FOUND", "message": str(exc)},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PLC_PATH_DENIED", "message": str(exc)},
        ) from exc

    job = plc.create_job_record(
        source_type="path",
        source_path=str(resolved),
        project_name=body.project_name,
        created_by=principal.subject,
    )
    background.add_task(
        plc.run_ingest_job,
        job["id"],
        publish_graph=body.publish_graph,
        plc_name=body.plc_name,
        tia_version=body.tia_version,
    )
    logger.info("plc job queued id=%s path=%s request_id=%s", job["id"], resolved, request_id)
    return ApiResponse(ok=True, data=_summary(job), request_id=request_id)


@router.post(
    "/jobs/upload",
    response_model=ApiResponse[PlcJobSummary],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job_from_upload(
    background: BackgroundTasks,
    principal: PrincipalDep,
    request_id: RequestIdDep,
    file: UploadFile = File(...),  # noqa: B008 (FastAPI dependency marker)
    project_name: str = Form(default=""),
    publish_graph: bool = Form(default=True),
    plc_name: str = Form(default=""),
    tia_version: str = Form(default=""),
) -> ApiResponse[PlcJobSummary]:
    """Upload .xml / .zip / .zap* / .ap19 and queue ingest (read-only analysis)."""
    data = await file.read()
    try:
        saved = plc.save_upload(file.filename, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_UPLOAD_INVALID", "message": str(exc)},
        ) from exc

    job = plc.create_job_record(
        source_type="upload",
        source_path=str(saved),
        project_name=project_name,
        created_by=principal.subject,
        upload_filename=file.filename,
    )
    background.add_task(
        plc.run_ingest_job,
        job["id"],
        publish_graph=publish_graph,
        plc_name=plc_name,
        tia_version=tia_version,
    )
    logger.info(
        "plc upload job queued id=%s file=%s request_id=%s",
        job["id"],
        file.filename,
        request_id,
    )
    return ApiResponse(ok=True, data=_summary(job), request_id=request_id)


@router.get("/jobs", response_model=ApiResponse[list[PlcJobSummary]])
async def list_plc_jobs(
    principal: PrincipalDep,
    request_id: RequestIdDep,
    limit: int = 20,
) -> ApiResponse[list[PlcJobSummary]]:
    _ = principal
    items = [_summary(j) for j in plc.list_jobs(limit=limit)]
    return ApiResponse(ok=True, data=items, request_id=request_id)


@router.get("/jobs/{job_id}", response_model=ApiResponse[PlcJobDetail])
async def get_plc_job(
    job_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[PlcJobDetail]:
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    # Legacy jobs may only have Project→Block CONTAINS in logic_graph; refresh in place.
    plc.refresh_logic_graph(job)
    return ApiResponse(ok=True, data=_detail(job), request_id=request_id)


def _ready_job(job_id: str) -> dict[str, Any]:
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PLC_JOB_NOT_READY",
                "message": f"Job status is {job.get('status')}, expected ready",
            },
        )
    return job


_BLOCK_SOURCE_KINDS = ("flgnet_xml", "literal_scl", "ast_trace")


@router.get(
    "/jobs/{job_id}/blocks/{block_name}/source",
    response_model=ApiResponse[dict[str, Any]],
)
async def get_plc_block_source(
    job_id: str,
    block_name: str,
    kind: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """On-demand raw block source (contract docs/15 §3) — server files only.

    kind=flgnet_xml | literal_scl | ast_trace; the file is read per request and
    never rides along in the regular job detail response.
    """
    _ = principal
    if kind not in _BLOCK_SOURCE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PLC_BLOCK_SOURCE_KIND_INVALID",
                "message": f"kind must be one of: {', '.join(_BLOCK_SOURCE_KINDS)}",
            },
        )
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    content = plc.read_block_source(job, block_name, kind)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_BLOCK_SOURCE_NOT_FOUND",
                "message": f"No {kind} artifact for block {block_name}",
            },
        )
    return ApiResponse(
        ok=True,
        data={"job_id": job_id, "block_name": block_name, "kind": kind, "content": content},
        request_id=request_id,
    )


@router.get("/jobs/{job_id}/device-cards", response_model=ApiResponse[DeviceCardListResponse])
async def list_plc_device_cards(
    job_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
    q: str = "",
    io_type: str = "",
    meaning_status: str = "",
    kind: str = "",
    limit: int = 200,
) -> ApiResponse[DeviceCardListResponse]:
    """Q1 I/O ↔ device/sensor cards. Missing comments stay meaning_unconfirmed."""
    _ = principal
    job = _ready_job(job_id)
    payload = plc.list_device_cards(
        job, q=q, io_type=io_type, meaning_status=meaning_status, kind=kind, limit=limit
    )
    return ApiResponse(
        ok=True,
        data=DeviceCardListResponse.model_validate(payload),
        request_id=request_id,
    )


@router.get(
    "/jobs/{job_id}/device-cards/{kind}/{name:path}",
    response_model=ApiResponse[DeviceSensorCard],
)
async def get_plc_device_card(
    job_id: str,
    kind: str,
    name: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[DeviceSensorCard]:
    _ = principal
    job = _ready_job(job_id)
    card = plc.get_device_card(job, f"{kind}:{name}")
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_DEVICE_CARD_NOT_FOUND", "message": f"No card {kind}:{name}"},
        )
    return ApiResponse(
        ok=True,
        data=DeviceSensorCard.model_validate(card),
        request_id=request_id,
    )


@router.put(
    "/jobs/{job_id}/device-cards/{kind}/{name:path}/annotation",
    response_model=ApiResponse[DeviceSensorCard],
)
async def annotate_plc_device_card(
    job_id: str,
    kind: str,
    name: str,
    body: DeviceCardAnnotationRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[DeviceSensorCard]:
    """Engineer annotation takes priority over cited comments / HMI text."""
    job = _ready_job(job_id)
    try:
        card = plc.set_device_card_annotation(
            job,
            f"{kind}:{name}",
            text=body.text,
            author=body.author or principal.subject,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_DEVICE_CARD_NOT_FOUND", "message": f"No card {kind}:{name}"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_DEVICE_CARD_ANNOTATION_INVALID", "message": str(exc)},
        ) from exc
    return ApiResponse(
        ok=True,
        data=DeviceSensorCard.model_validate(card),
        request_id=request_id,
    )


@router.delete(
    "/jobs/{job_id}/device-cards/{kind}/{name:path}/annotation",
    response_model=ApiResponse[DeviceSensorCard],
)
async def clear_plc_device_card_annotation(
    job_id: str,
    kind: str,
    name: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[DeviceSensorCard]:
    _ = principal
    job = _ready_job(job_id)
    try:
        card = plc.clear_device_card_annotation(job, f"{kind}:{name}")
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_DEVICE_CARD_NOT_FOUND", "message": f"No card {kind}:{name}"},
        ) from exc
    return ApiResponse(
        ok=True,
        data=DeviceSensorCard.model_validate(card),
        request_id=request_id,
    )


@router.get("/jobs/{job_id}/brief", response_model=ApiResponse[PlcProjectBrief])
async def get_plc_project_brief(
    job_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[PlcProjectBrief]:
    """Layered Project Brief — available as soon as structure snapshot exists."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    return ApiResponse(
        ok=True,
        data=PlcProjectBrief.model_validate(plc.build_project_brief(job)),
        request_id=request_id,
    )


@router.post("/jobs/{job_id}/chat", response_model=ApiResponse[PlcChatTurn])
async def chat_plc_job(
    job_id: str,
    body: PlcChatRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[PlcChatTurn]:
    """Block-focused Q&A from PLC-IR / KG (read-only; no download to PLC)."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready" and not job.get("brief_ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PLC_JOB_NOT_READY",
                "message": f"Job status is {job.get('status')}, expected ready or brief_ready",
            },
        )

    plc.append_chat_turn(
        job, role="user", content=body.message, block_name=body.block_name
    )
    answer = plc.answer_block_chat(job, body.message, body.block_name)
    citations = list(job.pop("_last_citations", None) or [])
    lower = body.message.lower()
    if plc._wants_confirm_writeback(body.message):
        pass
    elif any(k in body.message for k in ("注释", "依赖", "导入")) or any(
        k in lower for k in ("comment", "depends", "import")
    ):
        try:
            cs = plc.propose_job_changeset(job, body.message, body.block_name)
            answer += (
                "\n\n---\n已生成变更集提案 "
                f"`{cs.get('id')}`（{len(cs.get('ops') or [])} ops，status={cs.get('status')}）。"
                "请 HITL 确认后再回写 .apxx。"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("changeset propose skipped: %s", exc)
    plc.append_chat_turn(
        job, role="assistant", content=answer, block_name=body.block_name, citations=citations
    )
    turn = PlcChatTurn(
        role="assistant",
        content=answer,
        block_name=body.block_name,
        citations=citations,
        created_at=job["chat"][-1]["created_at"],
    )
    return ApiResponse(ok=True, data=turn, request_id=request_id)


@router.post("/jobs/{job_id}/query", response_model=ApiResponse[PlcGraphQueryResponse])
async def query_plc_job_graph(
    job_id: str,
    body: PlcGraphQueryRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[PlcGraphQueryResponse]:
    """Run a deterministic read-only query against a ready PLC job graph."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLC_JOB_NOT_READY", "message": f"Job status is {job.get('status')}, expected ready"},
        )
    try:
        result = plc.query_job_graph(job, body.op, **body.model_dump(exclude={"op"}, exclude_none=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_GRAPH_QUERY_INVALID", "message": str(exc)},
        ) from exc
    return ApiResponse(
        ok=True,
        data=PlcGraphQueryResponse.model_validate(result),
        request_id=request_id,
    )


@router.post("/jobs/{job_id}/analyze", response_model=ApiResponse[dict])
async def analyze_plc_job(
    job_id: str,
    body: PlcAnalyzeRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict]:
    """Return evidence-gated KG and folded-logic analysis without an LLM."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLC_JOB_NOT_READY", "message": "Job not ready"},
        )
    return ApiResponse(
        ok=True,
        data=plc.analyze_job(job, block_name=body.block_name),
        request_id=request_id,
    )


@router.post("/jobs/{job_id}/changes", response_model=ApiResponse[dict])
async def propose_plc_changes(
    job_id: str,
    body: PlcProposeChangeRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict]:
    """Propose a structured change-set from natural language (deterministic heuristics)."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLC_JOB_NOT_READY", "message": "Job not ready"},
        )
    cs = plc.propose_job_changeset(job, body.message, body.block_name)
    payload = dict(cs) if isinstance(cs, dict) else {}
    payload["optimize_plan"] = job.get("optimize_plan") or ""
    payload["scl_files"] = job.get("scl_files") or {}
    payload["scl_diffs"] = job.get("scl_diffs") or []
    payload["skipped"] = job.get("scl_skipped") or []
    return ApiResponse(ok=True, data=payload, request_id=request_id)


@router.post("/jobs/{job_id}/optimize", response_model=ApiResponse[dict])
async def optimize_plc_job(
    job_id: str,
    body: PlcOptimizeRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict]:
    """Evidence-gated optimize → changeset + SCL diffs (HITL before writeback/zap)."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLC_JOB_NOT_READY", "message": "Job not ready"},
        )
    cs = plc.propose_job_optimize(job, block_name=body.block_name, message=body.message)
    return ApiResponse(
        ok=True,
        data={
            "changeset": cs,
            "optimize_plan": job.get("optimize_plan") or "",
            "ops": len(cs.get("ops") or []) if isinstance(cs, dict) else 0,
            "scl_files": job.get("scl_files") or {},
            "scl_diffs": job.get("scl_diffs") or [],
            "skipped": job.get("scl_skipped") or [],
        },
        request_id=request_id,
    )


@router.post("/jobs/{job_id}/structure/retry", response_model=ApiResponse[PlcJobDetail])
async def retry_plc_structure(
    job_id: str,
    body: PlcStructureRetryRequest,
    background: BackgroundTasks,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[PlcJobDetail]:
    """Re-queue Openness/structure ingest so failed/pending units are not left silent."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") not in {"ready", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PLC_JOB_BUSY",
                "message": f"Job status is {job.get('status')}, expected ready or failed",
            },
        )
    job["status"] = "queued"
    job["error"] = None
    background.add_task(
        plc.retry_structure_export,
        job_id,
        names=list(body.names or []),
    )
    logger.info(
        "plc structure retry queued id=%s names=%s request_id=%s",
        job_id,
        body.names or "*",
        request_id,
    )
    return ApiResponse(ok=True, data=_detail(job), request_id=request_id)


@router.post("/jobs/{job_id}/writeback", response_model=ApiResponse[dict])
async def writeback_plc_job(
    job_id: str,
    body: PlcWritebackRequest,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict]:
    """HITL confirm: apply KG change-set and optionally Openness-import XML/SCL into .apxx."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if job.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLC_JOB_NOT_READY", "message": "Job not ready"},
        )
    try:
        result = plc.confirm_job_writeback(
            job,
            project_path=body.project_path,
            plc_name=body.plc_name,
            accept_changeset=body.accept_changeset,
            execute_openness_import=body.execute_openness_import,
            archive_zap=body.archive_zap,
            xml_paths=body.xml_paths,
            block_name=body.block_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_PATH_NOT_FOUND", "message": str(exc)},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PLC_PATH_DENIED", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_WRITEBACK_INVALID", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("PLC writeback failed job_id=%s", job_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "PLC_WRITEBACK_FAILED", "message": str(exc)},
        ) from exc
    return ApiResponse(ok=True, data=result, request_id=request_id)


@router.get("/jobs/{job_id}/export")
async def export_plc_job(
    job_id: str,
    principal: PrincipalDep,
) -> Response:
    """Download ResearchOS_PLC_Result package as ZIP (offline; no PLC download)."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    if not job.get("export_ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PLC_EXPORT_NOT_READY", "message": "Export package not ready"},
        )
    try:
        data = plc.build_export_zip(job)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_EXPORT_MISSING", "message": str(exc)},
        ) from exc

    name = (job.get("project_name") or "plc_project").replace(" ", "_")
    filename = f"ResearchOS_PLC_Result_{name}_{job_id[-8:]}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/zap")
async def download_plc_zap(
    job_id: str,
    principal: PrincipalDep,
) -> Response:
    """Download Openness-archived .zap* produced after confirmed write-back."""
    _ = principal
    job = plc.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_JOB_NOT_FOUND", "message": "PLC job not found"},
        )
    wb = job.get("writeback") or {}
    zap_path = wb.get("zap_path")
    if not zap_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PLC_ZAP_NOT_READY",
                "message": "No archived .zap yet. Confirm writeback with archive_zap=true after Openness import.",
            },
        )
    path = Path(str(zap_path))
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_ZAP_MISSING", "message": f"Archive file missing: {path}"},
        )
    return Response(
        content=path.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.post("/standalone/translate-block", response_model=ApiResponse[dict])
async def standalone_translate_block(
    body: dict[str, str],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict]:
    """100% offline SimaticML XML -> SCL translation (zero TIA Portal dependency)."""
    _ = principal
    xml_content = body.get("xml") or ""
    if not xml_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "XML_REQUIRED", "message": "xml content is required in request body"},
        )
    try:
        from plc_engine.standalone_api import translate_simaticml_to_scl

        scl = translate_simaticml_to_scl(xml_content)
        return ApiResponse(ok=True, data={"scl": scl}, request_id=request_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "TRANSLATION_FAILED", "message": str(exc)},
        ) from exc


@router.post("/standalone/parse-block", response_model=ApiResponse[dict])
async def standalone_parse_block(
    body: dict[str, str],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict]:
    """100% offline SimaticML XML block parsing into structured AST / interfaces."""
    _ = principal
    xml_content = body.get("xml") or ""
    if not xml_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "XML_REQUIRED", "message": "xml content is required in request body"},
        )
    try:
        from plc_engine.standalone_api import parse_simaticml_block_content

        data = parse_simaticml_block_content(xml_content)
        return ApiResponse(ok=True, data=data, request_id=request_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PARSE_FAILED", "message": str(exc)},
        ) from exc


@router.post("/standalone/parse-tags", response_model=ApiResponse[list[dict]])
async def standalone_parse_tags(
    body: dict[str, str],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict]]:
    """100% offline PLC TagTable XML parsing."""
    _ = principal
    xml_content = body.get("xml") or ""
    if not xml_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "XML_REQUIRED", "message": "xml content is required in request body"},
        )
    try:
        from plc_engine.standalone_api import extract_tag_table_content

        tags = extract_tag_table_content(xml_content)
        return ApiResponse(ok=True, data=tags, request_id=request_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PARSE_FAILED", "message": str(exc)},
        ) from exc


@router.post("/standalone/audit-block", response_model=ApiResponse[list[dict]])
async def standalone_audit_block(
    body: dict[str, str],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict]]:
    """100% offline PLC safety & code review audit."""
    _ = principal
    xml_content = body.get("xml") or ""
    if not xml_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "XML_REQUIRED", "message": "xml content is required in request body"},
        )
    try:
        from plc_engine.standalone_api import audit_block_content

        findings = audit_block_content(xml_content)
        return ApiResponse(ok=True, data=findings, request_id=request_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "AUDIT_FAILED", "message": str(exc)},
        ) from exc


# ---------------------------------------------------------------------------
# Interactive Canvas, Conversational Patches & 1:1 TIA Portal Closed-Loop APIs
# ---------------------------------------------------------------------------


@router.get("/canvas/default", response_model=ApiResponse[dict[str, Any]])
async def get_default_canvas(
    principal: PrincipalDep,
    request_id: RequestIdDep,
    project_name: str = "",
) -> ApiResponse[dict[str, Any]]:
    """Return a blank starting canvas.

    演示种子块已移除：打开即是空白画面，用户通过导入工程或主动选择历史
    会话进入具体项目（产品决策 2026-10-24）。
    """
    _ = principal
    from plc_engine.canvas_model import CanvasState

    canvas = CanvasState(project_name=project_name)
    return ApiResponse(ok=True, data=canvas.to_dict(), request_id=request_id)


@router.post("/canvas/patch", response_model=ApiResponse[dict[str, Any]])
async def apply_canvas_patch_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Apply conversational delta operations (add/modify logic or HMI widgets) onto canvas."""
    _ = principal
    from plc_engine.canvas_model import CanvasState, apply_canvas_patch

    canvas_raw = body.get("canvas") or {}
    operations = body.get("operations") or []
    if not isinstance(operations, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OPS", "message": "operations must be a list of patch actions"},
        )
    canvas = CanvasState.from_dict(canvas_raw)
    updated = apply_canvas_patch(canvas, operations)
    return ApiResponse(ok=True, data=updated.to_dict(), request_id=request_id)


@router.post("/canvas/to-scl", response_model=ApiResponse[dict[str, Any]])
async def canvas_to_scl_preview_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Preview 1:1 SCL compilation units and SimaticML tag tables rendered from Canvas."""
    _ = principal
    from plc_engine.canvas_model import CanvasState
    from plc_engine.canvas_tia_transpiler import preview_canvas_scl, preview_canvas_tags_xml

    canvas_raw = body.get("canvas") or {}
    canvas = CanvasState.from_dict(canvas_raw)
    scls = preview_canvas_scl(canvas)
    tags_xml = preview_canvas_tags_xml(canvas)
    return ApiResponse(
        ok=True,
        data={"scl_sources": scls, "tags_xml": tags_xml, "project_name": canvas.project_name},
        request_id=request_id,
    )


@router.get("/canvas/sessions", response_model=ApiResponse[list[dict[str, Any]]])
async def list_canvas_sessions(
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict[str, Any]]]:
    """服务端会话历史(轻量 meta 列表):历史跟服务走,不跟浏览器走。"""
    _ = principal
    from gateway.app.services.plc import session_store

    return ApiResponse(ok=True, data=session_store.list_sessions(), request_id=request_id)


@router.get("/canvas/sessions/deleted", response_model=ApiResponse[dict[str, Any]])
async def list_deleted_canvas_sessions(
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """删除墓碑表 {session_id: deleted_at}:同步方据此丢弃本地陈旧副本,防止删除复活。"""
    _ = principal
    from gateway.app.services.plc import session_store

    return ApiResponse(
        ok=True, data={"deleted": session_store.list_tombstones()}, request_id=request_id
    )


@router.get("/canvas/sessions/{session_id}", response_model=ApiResponse[dict[str, Any]])
async def get_canvas_session(
    session_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from gateway.app.services.plc import session_store

    data = session_store.get_session(session_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_SESSION_NOT_FOUND", "message": f"session {session_id} not found"},
        )
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.put("/canvas/sessions/{session_id}", response_model=ApiResponse[dict[str, Any]])
async def put_canvas_session(
    session_id: str,
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """整会话 upsert(前端变更后防抖推送)。body 即完整会话对象。"""
    _ = principal
    from gateway.app.services.plc import session_store

    session = dict(body or {})
    session["id"] = session_id
    try:
        meta = session_store.put_session(session)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_SESSION_INVALID", "message": str(exc)},
        ) from exc
    return ApiResponse(ok=True, data=meta, request_id=request_id)


@router.delete("/canvas/sessions/{session_id}", response_model=ApiResponse[dict[str, Any]])
async def delete_canvas_session(
    session_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    from gateway.app.services.plc import session_store

    removed = session_store.delete_session(session_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_SESSION_NOT_FOUND", "message": f"session {session_id} not found"},
        )
    return ApiResponse(ok=True, data={"removed": session_id}, request_id=request_id)


@router.post("/canvas/confirm-writeback", response_model=ApiResponse[dict[str, Any]])
async def confirm_canvas_writeback_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Human Confirmation Gate: schedules a compile job (or sync writeback if sync=true)."""
    _ = principal
    from plc_engine.canvas_model import CanvasState

    canvas_raw = body.get("canvas") or {}
    canvas = CanvasState.from_dict(canvas_raw)
    project_path = str(body.get("project_path") or "").strip()
    if not project_path and canvas.source:
        project_path = canvas.source.project_path
    plc_name = str(body.get("plc_name") or "").strip()
    if not plc_name and canvas.source:
        plc_name = canvas.source.plc_name
    compile_after = bool(body.get("compile_after", True))
    sync = bool(body.get("sync", False))

    if not project_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PATH_REQUIRED", "message": "project_path or canvas.source.project_path required"},
        )

    if not sync:
        from gateway.app.services.plc.compile_jobs import create_compile_job

        job = create_compile_job(
            canvas.to_dict(),
            project_path=project_path,
            plc_name=plc_name,
            compile_plc=compile_after,
            compile_hmi=bool(canvas.hmi_devices) and compile_after,
            save_on_success=True,
            reset_work=True,
        )
        # Same envelope as the sync branch (async/job/writeback/attributions/canvas) so
        # consumers switch on ``async`` alone instead of guessing the payload shape.
        return ApiResponse(
            ok=True,
            data={
                "async": True,
                "job": job,
                "writeback": None,
                "attributions": [],
                "canvas": canvas.to_dict(),
            },
            request_id=request_id,
        )

    import asyncio

    from plc_engine.canvas_tia_transpiler import execute_canvas_writeback

    result, attributions = await asyncio.to_thread(
        execute_canvas_writeback,
        canvas=canvas,
        project_path=project_path,
        plc_name=plc_name,
        compile_after=compile_after,
    )
    return ApiResponse(
        ok=True,
        data={
            "async": False,
            "job": None,
            "writeback": result,
            "attributions": attributions,
            "canvas": canvas.to_dict(),
        },
        request_id=request_id,
    )


@router.post("/canvas/compile-jobs", response_model=ApiResponse[dict[str, Any]])
async def create_compile_job_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from gateway.app.services.plc.compile_jobs import create_compile_job
    from plc_engine.canvas_model import CanvasState

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    project_path = str(body.get("project_path") or (canvas.source.project_path if canvas.source else "")).strip()
    plc_name = str(body.get("plc_name") or (canvas.source.plc_name if canvas.source else "")).strip()
    job = create_compile_job(
        canvas.to_dict(),
        project_path=project_path,
        plc_name=plc_name,
        compile_plc=bool(body.get("compile_plc", True)),
        compile_hmi=bool(body.get("compile_hmi", True)),
        save_on_success=bool(body.get("save_on_success", True)),
        reset_work=bool(body.get("reset_work", True)),
    )
    return ApiResponse(ok=True, data=job, request_id=request_id)


@router.get("/canvas/compile-jobs/{job_id}", response_model=ApiResponse[dict[str, Any]])
async def get_compile_job_endpoint(
    job_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from gateway.app.services.plc.compile_jobs import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "JOB_NOT_FOUND"})
    return ApiResponse(ok=True, data=job, request_id=request_id)


@router.post("/canvas/compile-jobs/{job_id}/cancel", response_model=ApiResponse[dict[str, Any]])
async def cancel_compile_job_endpoint(
    job_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from gateway.app.services.plc.compile_jobs import cancel_job

    job = cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "JOB_NOT_FOUND"})
    return ApiResponse(ok=True, data=job, request_id=request_id)


@router.post("/canvas/chat-ops", response_model=ApiResponse[dict[str, Any]])
async def canvas_chat_ops_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from gateway.app.services.plc.chat_ops import build_chat_ops, ops_touched_blocks
    from plc_engine.canvas_model import CanvasState, apply_canvas_patch
    from plc_engine.scl_precheck import precheck_canvas

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    prompt = str(body.get("prompt") or body.get("message") or "").strip()
    apply = bool(body.get("apply", False))
    built = build_chat_ops(prompt, canvas, context=body.get("context") or {}, use_llm=bool(body.get("use_llm", True)))
    if apply and built.get("ops"):
        canvas = apply_canvas_patch(canvas, built["ops"])
        canvas.append_revision(built["ops"], source="nl", message=prompt[:120])
        built["canvas"] = canvas.to_dict()
        # 与编译门禁同语义：只预检 ops 触及的块，导入产生的 synced 占位块不拦编辑
        built["precheck"] = precheck_canvas(canvas, block_names=ops_touched_blocks(built["ops"]))
    return ApiResponse(ok=True, data=built, request_id=request_id)


@router.post("/canvas/chat-answer", response_model=ApiResponse[dict[str, Any]])
async def canvas_chat_answer_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """分析/提问类输入 → LLM 工程师向中文回答（画布摘要作上下文）。

    未配置 LLM 返回 400 code=LLM_NOT_CONFIGURED，前端回落到编辑指令提示。
    """
    _ = principal
    import asyncio

    from gateway.app.services.plc.chat_ops import answer_project_question
    from gateway.app.services.plc.llm_explain import LlmNotConfigured
    from plc_engine.canvas_model import CanvasState

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    prompt = str(body.get("prompt") or body.get("message") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROMPT_REQUIRED", "message": "body.prompt is required"},
        )
    try:
        result = await asyncio.to_thread(
            answer_project_question, prompt, canvas, body.get("context") or {}
        )
    except LlmNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "LLM_NOT_CONFIGURED",
                "message": (
                    "回答分析类问题需要 LLM：设置 PLC_LLM_* 或 DEEPSEEK_API_KEY 后重启网关。"
                ),
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "LLM_CALL_FAILED", "message": str(exc)},
        ) from exc
    return ApiResponse(
        ok=True,
        data={
            "answer": result.get("answer") or "",
            "usage": result.get("usage") or {},
            "llm": True,
        },
        request_id=request_id,
    )


@router.post("/canvas/chat-answer/stream")
async def canvas_chat_answer_stream_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> Any:
    """chat-answer 的 SSE 流式版：data:{"delta":…} 逐段 → data:{"usage":…} → data:[DONE]。

    未配置 LLM 时以 data:{"error":{"code":"LLM_NOT_CONFIGURED"}} 事件返回（HTTP 仍 200，
    因为 StreamingResponse 状态码在首字节前就已提交），前端回落到非流式端点/提示。
    """
    _ = principal
    import json as _json

    from fastapi.responses import StreamingResponse

    from gateway.app.services.plc.chat_ops import stream_project_answer
    from gateway.app.services.plc.llm_explain import LlmNotConfigured
    from plc_engine.canvas_model import CanvasState

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    prompt = str(body.get("prompt") or body.get("message") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROMPT_REQUIRED", "message": "body.prompt is required"},
        )
    context = body.get("context") or {}

    def gen():
        try:
            for delta, usage in stream_project_answer(prompt, canvas, context):
                if delta:
                    yield f"data: {_json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                elif usage:
                    yield f"data: {_json.dumps({'usage': usage})}\n\n"
        except LlmNotConfigured:
            yield f"data: {_json.dumps({'error': {'code': 'LLM_NOT_CONFIGURED'}})}\n\n"
        except RuntimeError as exc:
            yield (
                "data: "
                + _json.dumps({"error": {"code": "LLM_CALL_FAILED", "message": str(exc)[:300]}})
                + "\n\n"
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/canvas/precheck", response_model=ApiResponse[dict[str, Any]])
async def canvas_precheck_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from plc_engine.canvas_model import CanvasState
    from plc_engine.scl_precheck import precheck_canvas

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    raw_names = body.get("block_names")
    block_names = (
        [str(n).strip() for n in raw_names if str(n).strip()] if isinstance(raw_names, list) else None
    )
    return ApiResponse(
        ok=True, data=precheck_canvas(canvas, block_names=block_names), request_id=request_id
    )


@router.post("/canvas/migrate-scl", response_model=ApiResponse[dict[str, Any]])
async def canvas_migrate_scl_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    from plc_engine.canvas_model import CanvasState, apply_canvas_patch
    from plc_engine.lad_migrate import migrate_block_to_scl, migrate_canvas_graphic_blocks

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    block_name = str(body.get("block") or "").strip()
    apply = bool(body.get("apply", False))
    if block_name:
        report = migrate_block_to_scl(canvas, block_name)
    else:
        report = migrate_canvas_graphic_blocks(canvas)
    if apply and report.get("ops"):
        canvas = apply_canvas_patch(canvas, report["ops"])
        canvas.append_revision(report["ops"], source="migrate", message="LAD/FBD→SCL")
        report["canvas"] = canvas.to_dict()
    return ApiResponse(ok=True, data=report, request_id=request_id)


@router.post("/canvas/fix-loop", response_model=ApiResponse[dict[str, Any]])
async def canvas_fix_loop_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    _ = principal
    import asyncio

    from gateway.app.services.plc.fix_loop import run_fix_loop
    from plc_engine.canvas_model import CanvasState

    canvas = CanvasState.from_dict(body.get("canvas") or {})
    project_path = str(body.get("project_path") or (canvas.source.project_path if canvas.source else "")).strip()
    result = await asyncio.to_thread(
        run_fix_loop,
        canvas,
        body.get("attributions") or [],
        project_path=project_path,
        plc_name=str(body.get("plc_name") or (canvas.source.plc_name if canvas.source else "")),
        max_rounds=int(body.get("max_rounds") or 3),
        use_llm=bool(body.get("use_llm", True)),
        auto=bool(body.get("auto", True)),
    )
    return ApiResponse(ok=True, data=result, request_id=request_id)


@router.post("/canvas/auto-fix", response_model=ApiResponse[dict[str, Any]])
async def canvas_auto_fix_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Synthesize and apply self-healing patch from TIA Portal compiler / binding errors."""
    _ = principal
    from plc_engine.canvas_model import (
        CanvasState,
        apply_canvas_patch,
        generate_canvas_autofix_patch,
    )

    canvas_raw = body.get("canvas") or {}
    attributions = body.get("attributions") or []
    canvas = CanvasState.from_dict(canvas_raw)
    fix_ops = generate_canvas_autofix_patch(canvas, attributions)
    if fix_ops:
        canvas = apply_canvas_patch(canvas, fix_ops)

    return ApiResponse(
        ok=True,
        data={"applied_operations": fix_ops, "canvas": canvas.to_dict()},
        request_id=request_id,
    )


@router.get("/canvas/import/progress/{progress_id}", response_model=ApiResponse[dict[str, Any]])
async def canvas_import_progress_endpoint(
    progress_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Poll staged progress for a long-running canvas import (Openness / parse)."""
    _ = principal
    from gateway.app.services.plc.import_progress import get as get_import_progress

    data = get_import_progress(progress_id) or {
        "progress_id": progress_id,
        "stage": "unknown",
        "message": "暂无进度（导入尚未开始或已过期）",
    }
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.post("/canvas/import", response_model=ApiResponse[dict[str, Any]])
async def canvas_import_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Import a TIA Portal Openness export (.xml file / export directory) onto a fresh canvas."""
    _ = principal
    import asyncio

    path = str(body.get("path") or "").strip()
    project_name = str(body.get("project_name") or "").strip()
    progress_id = str(body.get("progress_id") or "").strip()
    if not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PATH_REQUIRED", "message": "path is required for canvas import"},
        )
    try:
        resolved = plc.resolve_allowed_path(path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_PATH_NOT_FOUND", "message": str(exc)},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PLC_PATH_DENIED", "message": str(exc)},
        ) from exc

    from gateway.app.services.plc.canvas_import import (
        CanvasImportRejected,
        import_canvas_from_path,
    )
    from gateway.app.services.plc.import_progress import make_reporter

    on_progress = make_reporter(progress_id)

    try:
        # Openness / large trees can take minutes — keep the event loop free.
        data = await asyncio.to_thread(
            import_canvas_from_path,
            resolved,
            project_name,
            on_progress=on_progress,
        )
    except CanvasImportRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    logger.info(
        "plc canvas import path=%s blocks=%s tags=%s skipped=%s request_id=%s",
        resolved,
        data.get("blocks_parsed"),
        data.get("tags_parsed"),
        len(data.get("skipped") or []),
        request_id,
    )
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.post("/canvas/import/upload", response_model=ApiResponse[dict[str, Any]])
async def canvas_import_upload_endpoint(
    principal: PrincipalDep,
    request_id: RequestIdDep,
    file: UploadFile = File(...),  # noqa: B008 (FastAPI dependency marker)
    project_name: str = Form(default=""),
    progress_id: str = Form(default=""),
) -> ApiResponse[dict[str, Any]]:
    """Upload .xml / .zip / .zap* and import it onto a fresh interactive canvas."""
    import asyncio

    _ = principal
    data = await file.read()
    try:
        # save_upload validates suffix/size; zip/zap* are unpacked (and completeness
        # checked) beside the saved file, returning the parse root — which may be a
        # directory (SimaticML export) or a .apxx project file.
        saved = plc.save_upload(file.filename, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_UPLOAD_INVALID", "message": str(exc)},
        ) from exc

    from gateway.app.services.plc.canvas_import import (
        CanvasImportRejected,
        import_canvas_from_path,
    )
    from gateway.app.services.plc.import_progress import make_reporter

    on_progress = make_reporter(progress_id)
    on_progress("upload_saved", f"已接收 {file.filename}，开始导入…")

    try:
        # Zap unpacking + Openness export can take minutes — keep the event loop free.
        result = await asyncio.to_thread(
            import_canvas_from_path,
            saved,
            project_name,
            on_progress=on_progress,
        )
    except CanvasImportRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    logger.info(
        "plc canvas upload import file=%s blocks=%s tags=%s skipped=%s request_id=%s",
        file.filename,
        result.get("blocks_parsed"),
        result.get("tags_parsed"),
        len(result.get("skipped") or []),
        request_id,
    )
    return ApiResponse(ok=True, data=result, request_id=request_id)


@router.post("/canvas/explain-block", response_model=ApiResponse[dict[str, Any]])
async def canvas_explain_block_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """LLM 深度解释：块数据 + 规则引擎预分析 → OpenAI 兼容端点 → 工程师向中文解释。

    未配置 PLC_LLM_* 环境变量时返回 400 code=LLM_NOT_CONFIGURED（附配置指引），
    前端据此显示一次性提示而非报错。
    """
    _ = principal
    import asyncio

    from gateway.app.services.plc.llm_explain import LlmNotConfigured, deep_explain_block

    block = body.get("block")
    if not isinstance(block, dict) or not block.get("name"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BLOCK_REQUIRED", "message": "body.block is required"},
        )
    scaffold = body.get("scaffold") if isinstance(body.get("scaffold"), dict) else {}

    try:
        text = await asyncio.to_thread(deep_explain_block, block, scaffold)
    except LlmNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "LLM_NOT_CONFIGURED",
                "message": (
                    "深度解释需要 LLM：在网关进程设置环境变量 "
                    "PLC_LLM_BASE_URL（OpenAI 兼容端点）、PLC_LLM_API_KEY、PLC_LLM_MODEL，"
                    "或执行 setx DEEPSEEK_API_KEY <key> 后重启网关即可沿用 DeepSeek"
                    "（默认 deepseek-chat @ https://api.deepseek.com/v1）。"
                ),
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "LLM_CALL_FAILED", "message": str(exc)},
        ) from exc

    return ApiResponse(ok=True, data={"explanation": text}, request_id=request_id)
