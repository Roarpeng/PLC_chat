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
    file: UploadFile = File(...),
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
    except Exception as exc:  # noqa: BLE001
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
