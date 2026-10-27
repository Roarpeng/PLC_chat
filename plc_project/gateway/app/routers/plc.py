"""PLC Intelligence API — ResearchOS industrial feature module."""

from __future__ import annotations

import logging
import time
from collections import deque
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
    template: str = "",
) -> ApiResponse[dict[str, Any]]:
    """Return a blank starting canvas or initialized with an architecture template.

    演示种子块已移除：打开即是空白画面，用户通过导入工程或主动选择历史
    会话进入具体项目（产品决策 2026-10-24）。支持 template=af_v1_2 初始化 AF 架构。
    """
    _ = principal
    from plc_engine.canvas_model import CanvasState

    canvas = CanvasState(project_name=project_name)
    if template.lower() == "af_v1_2":
        from plc_engine.af.af_generator import generate_af_project_blocks
        from plc_engine.af.planner import plan_af_project_from_spec

        p_name = project_name or "AF_Project"
        plan = plan_af_project_from_spec("Unit1 ProcessStation", project_name=p_name)
        canvas.blocks = generate_af_project_blocks(plan)

    return ApiResponse(ok=True, data=canvas.to_dict(), request_id=request_id)


@router.post("/canvas/projects/new", response_model=ApiResponse[dict[str, Any]])
@router.post("/projects/new", response_model=ApiResponse[dict[str, Any]])
async def create_new_project_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Create a new PLC project workspace, supporting the af_v1_2 architecture template."""
    _ = principal
    import uuid

    from gateway.app.services.plc import workspace
    from plc_engine.canvas_model import CanvasSource, CanvasState

    project_name = str(body.get("project_name") or "AF_Project").strip()
    template = str(body.get("template") or "af_v1_2").strip().lower()
    target_dir = body.get("target_dir")

    project_path = ""
    workspace_meta: dict[str, Any] = {}

    if template == "af_v1_2":
        from plc_engine.af.baseline import clone_startup_template

        dest_dir = (
            Path(target_dir).expanduser().resolve()
            if target_dir
            else workspace.projects_root() / f"new_{uuid.uuid4().hex[:8]}"
        )
        ap19_path = clone_startup_template(dest_dir, project_name)
        project_path = str(ap19_path)
        try:
            workspace_meta = workspace.persist_imported_project(ap19_path, project_name=project_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist_imported_project skipped: %s", exc)
            workspace_meta = {"project_name": project_name, "project_path": project_path}

    canvas = CanvasState(project_name=project_name)
    if project_path:
        canvas.source = CanvasSource(
            project_id=str(workspace_meta.get("project_id") or ""),
            project_path=project_path,
            plc_name=project_name,
        )

    return ApiResponse(
        ok=True,
        data={
            "ok": True,
            "project_name": project_name,
            "template": template,
            "project_path": project_path,
            "workspace": workspace_meta,
            "canvas": canvas.to_dict(),
        },
        request_id=request_id,
    )


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


@router.get("/canvas/download-package")
async def download_canvas_package_endpoint(
    project_name: str = "",
    package_type: str = "zip",
    session_id: str = "",
) -> Response:
    """Direct HTTP download of the compiled/verified project package (.zip or .zap19)."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    candidates: list[Path] = []

    if session_id:
        from gateway.app.services.plc import session_store

        sess = session_store.get_session(session_id)
        if sess and isinstance(sess.get("canvas"), dict):
            src_path = (sess["canvas"].get("source") or {}).get("project_path")
            if src_path:
                p = Path(src_path)
                p_dir = p if p.is_dir() else p.parent
                candidates.extend([p_dir, p_dir.parent])

    repo_root = Path(r"C:\Users\vboxuser\Desktop\Project\Code\PLC_chat")
    candidates.extend([
        repo_root / "PLC_Openness_data" / "hr001",
        repo_root / "release_packages" / "HR001_AF_V1_2_Package",
        repo_root / "release_packages",
    ])

    ptype = package_type.lower().strip()
    target_file: Path | None = None

    if ptype in {"zap", "zap19"}:
        for c in candidates:
            if not c.exists():
                continue
            for pattern in ("*AF*.zap19", "*.zap19"):
                found = list(c.glob(pattern))
                if found:
                    target_file = found[0]
                    break
            if target_file:
                break
        if not target_file or not target_file.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PACKAGE_NOT_FOUND", "message": "Compiled .zap19 archive not found"},
            )
        return FileResponse(
            path=str(target_file),
            filename=target_file.name,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{target_file.name}"'},
        )
    elif ptype == "receipt":
        for c in candidates:
            if not c.exists():
                continue
            f = c / "compile_receipt.json"
            if f.is_file():
                target_file = f
                break
        if not target_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "RECEIPT_NOT_FOUND", "message": "Compile receipt not found"},
            )
        return FileResponse(
            path=str(target_file),
            filename="compile_receipt.json",
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="compile_receipt.json"'},
        )
    else:  # default zip
        for c in candidates:
            if not c.exists():
                continue
            for pattern in ("*AF*.zip", "*.zip"):
                found = list(c.glob(pattern))
                if found:
                    target_file = found[0]
                    break
            if target_file:
                break
        if not target_file or not target_file.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PACKAGE_NOT_FOUND", "message": "Compiled .zip package not found"},
            )
        return FileResponse(
            path=str(target_file),
            filename=target_file.name,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{target_file.name}"'},
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


# —— 会话批量删除护栏:60s 内 >8 次删除视为异常(2026-10-24 21:01 曾有 30 条
# 会话在 15s 内被顺序删除、无法溯源的批量丢失事故;正常使用不可能达到该速率)
_session_delete_times: deque[float] = deque(maxlen=16)
_SESSION_DELETE_WINDOW_S = 60.0
_SESSION_DELETE_MAX = 8


def _session_delete_rate_ok() -> bool:
    now = time.time()
    while _session_delete_times and now - _session_delete_times[0] > _SESSION_DELETE_WINDOW_S:
        _session_delete_times.popleft()
    if len(_session_delete_times) >= _SESSION_DELETE_MAX:
        return False
    _session_delete_times.append(now)
    return True


@router.delete("/canvas/sessions/{session_id}", response_model=ApiResponse[dict[str, Any]])
async def delete_canvas_session(
    session_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    if not _session_delete_rate_ok():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "PLC_SESSION_DELETE_RATE_LIMITED",
                "message": "会话删除过于频繁(60 秒内超过 8 次),已拦截。若为误操作请检查是否有自动化在批量删除。",
            },
        )
    from gateway.app.services.plc import session_store

    removed = session_store.delete_session(session_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLC_SESSION_NOT_FOUND", "message": f"session {session_id} not found"},
        )
    return ApiResponse(ok=True, data={"removed": session_id}, request_id=request_id)


@router.get("/canvas/requirements", response_model=ApiResponse[list[dict[str, Any]]])
async def list_canvas_requirements(
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict[str, Any]]]:
    """工艺需求卡 meta 列表(id/summary/status/updated_at/task_kind,updated_at 降序)。"""
    _ = principal
    from gateway.app.services.plc import requirement_store

    return ApiResponse(ok=True, data=requirement_store.list_requirements(), request_id=request_id)


@router.post("/canvas/requirements/draft", response_model=ApiResponse[dict[str, Any]])
async def draft_canvas_requirement(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """LLM 生成工艺需求卡草稿(契约 docs/22 §2)——**不落盘**,工程师确认后由前端 PUT。

    body: {prompt, canvas, task_kind?}。未配置 LLM → 400 code=LLM_NOT_CONFIGURED;
    返回结构不合契约(重试一次仍不符)→ 502 code=LLM_CALL_FAILED。草稿硬规则:
    confirmation_status 恒 proposed;未知数值参数(超时等)由提示词约束写入
    open_questions,绝不编造数值;linked_blocks 从 items 提及的画布块名匹配。
    """
    _ = principal
    import asyncio

    from gateway.app.services.plc import requirement_store
    from gateway.app.services.plc.llm_explain import chat_completion_raw, llm_settings
    from plc_engine.canvas_model import CanvasState

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROMPT_REQUIRED", "message": "body.prompt is required"},
        )
    task_kind = str(body.get("task_kind") or "").strip()
    canvas = CanvasState.from_dict(body.get("canvas") or {})
    block_names = list(canvas.blocks.keys())
    settings = llm_settings()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "LLM_NOT_CONFIGURED",
                "message": (
                    "生成需求卡草稿需要 LLM：在网关进程设置环境变量 "
                    "PLC_LLM_BASE_URL（OpenAI 兼容端点）、PLC_LLM_API_KEY、PLC_LLM_MODEL，"
                    "或执行 setx DEEPSEEK_API_KEY <key> 后重启网关即可沿用 DeepSeek。"
                ),
            },
        )
    messages = requirement_store.build_draft_messages(prompt, block_names, task_kind)
    last_error = ""
    for attempt in (1, 2):  # 结构不符重试一次,再不符按 LLM_CALL_FAILED 语义 502
        try:
            text, _usage = await asyncio.to_thread(
                chat_completion_raw,
                messages,
                settings,
                timeout_s=60.0,
                max_tokens=2048,
                json_mode=True,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "LLM_CALL_FAILED", "message": str(exc)},
            ) from exc
        try:
            draft = requirement_store.requirement_from_llm_payload(
                text,
                prompt=prompt,
                block_names=block_names,
                task_kind=task_kind,
                project_name_fallback=canvas.project_name,
            )
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("requirement draft malformed (attempt %s): %s", attempt, last_error)
            continue
        return ApiResponse(ok=True, data=draft, request_id=request_id)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "LLM_CALL_FAILED",
            "message": f"LLM 返回的需求卡不符合结构契约（已重试一次）：{last_error[:300]}",
        },
    )


@router.get("/canvas/requirements/{requirement_id}", response_model=ApiResponse[dict[str, Any]])
async def get_canvas_requirement(
    requirement_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """单个需求卡完整对象(含 items/open_questions 等全部 §1 字段)。"""
    _ = principal
    from gateway.app.services.plc import requirement_store

    data = requirement_store.get_requirement(requirement_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_REQUIREMENT_NOT_FOUND",
                "message": f"requirement {requirement_id} not found",
            },
        )
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.put("/canvas/requirements/{requirement_id}", response_model=ApiResponse[dict[str, Any]])
async def put_canvas_requirement(
    requirement_id: str,
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """整卡 upsert(工程师编辑/确认工艺意图后回推)。body 即完整需求卡对象。

    铁律:confirmation_status=confirmed 只改状态,不触发任何 ops/写回。
    """
    _ = principal
    from gateway.app.services.plc import requirement_store

    requirement = dict(body or {})
    requirement["requirement_id"] = requirement_id
    try:
        stored = requirement_store.put_requirement(requirement)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_REQUIREMENT_INVALID", "message": str(exc)},
        ) from exc
    return ApiResponse(ok=True, data=stored, request_id=request_id)


@router.delete("/canvas/requirements/{requirement_id}", response_model=ApiResponse[dict[str, Any]])
async def delete_canvas_requirement(
    requirement_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """删除需求卡(幂等:已删除的合法 id 再删仍 200;非法 id 404)。"""
    _ = principal
    from gateway.app.services.plc import requirement_store

    removed = requirement_store.delete_requirement(requirement_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_REQUIREMENT_NOT_FOUND",
                "message": f"requirement {requirement_id} not found",
            },
        )
    return ApiResponse(ok=True, data={"removed": requirement_id}, request_id=request_id)


@router.post("/canvas/requirements/{req_id}/generate", response_model=ApiResponse[dict[str, Any]])
@router.post("/canvas/requirements/{req_id}/generate-af", response_model=ApiResponse[dict[str, Any]])
async def generate_af_from_requirement_endpoint(
    req_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
    body: dict[str, Any] | None = None,
) -> ApiResponse[dict[str, Any]]:
    """Generate official Siemens AF V1.2 Software Unit architecture from a process requirement card.

    1. Reads requirement card via RequirementStore (404 if missing);
    2. Calls planner.plan_af_project_from_spec to plan AfProject domain model;
    3. Calls generate_af_project_blocks to generate full set of AF V1.2 blocks;
    4. Injects blocks into current CanvasState (status='draft');
    5. Runs af_linter.lint_af_canvas for static rule precheck;
    6. Returns {ok: true, project: af_project.to_dict(), blocks_count: len(generated), findings: linter_findings}.
    """
    _ = principal
    from dataclasses import asdict

    from gateway.app.services.plc import requirement_store
    from plc_engine.af.af_generator import generate_af_project_blocks
    from plc_engine.af.af_linter import lint_af_canvas
    from plc_engine.af.planner import plan_af_project_from_spec
    from plc_engine.canvas_model import CanvasState

    card = requirement_store.get_requirement(req_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_REQUIREMENT_NOT_FOUND",
                "message": f"requirement {req_id} not found",
            },
        )

    payload = body or {}
    project_name = str(card.get("project_name") or payload.get("project_name") or "AF_Project").strip()
    af_project = plan_af_project_from_spec(card, project_name=project_name)

    generated = generate_af_project_blocks(af_project)

    canvas_raw = payload.get("canvas")
    session_id = payload.get("session_id")

    if canvas_raw and isinstance(canvas_raw, dict):
        canvas = CanvasState.from_dict(canvas_raw)
    elif session_id:
        from gateway.app.services.plc import session_store

        sess = session_store.get_session(session_id)
        if sess and isinstance(sess.get("canvas"), dict):
            canvas = CanvasState.from_dict(sess["canvas"])
        else:
            canvas = CanvasState(project_name=af_project.name)
    else:
        canvas = CanvasState(project_name=af_project.name)

    # Inject blocks with status 'draft'
    for key, block in generated.items():
        block.status = "draft"
        canvas.blocks[key] = block

    findings = lint_af_canvas(canvas)
    linter_findings = [asdict(f) if hasattr(f, "__dataclass_fields__") else f for f in findings]

    # If session_id provided, sync canvas back into server-side session store
    if session_id:
        try:
            from gateway.app.services.plc import session_store

            sess = session_store.get_session(session_id)
            if sess:
                sess["canvas"] = canvas.to_dict()
                session_store.put_session(sess)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to sync canvas to session %s: %s", session_id, exc)

    return ApiResponse(
        ok=True,
        data={
            "ok": True,
            "project": af_project.to_dict(),
            "blocks_count": len(generated),
            "findings": linter_findings,
            "canvas": canvas.to_dict(),
        },
        request_id=request_id,
    )


@router.post("/canvas/generate-from-requirement", response_model=ApiResponse[dict[str, Any]])
async def canvas_generate_from_requirement_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Generate a canvas draft of AF V1.2 blocks from a confirmed inline requirement card.

    N 线契约(docs/23 §3):body {requirement(完整对象,须 confirmed),
    project_name, target_dir?}。只产画布草稿——**不做任何写回**,工程
    落盘/编译/PCEC 仍走既有确认链;target_dir 仅由创建链透传,本端点不使用。
    复用 planner → generate_af_project_blocks → lint_af_canvas + scl_precheck
    双门禁,逻辑收敛在 gateway.app.services.plc.af_generate。
    """
    _ = principal
    from gateway.app.services.plc import af_generate

    requirement = body.get("requirement")
    if not isinstance(requirement, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "REQUIREMENT_REQUIRED",
                "message": "body.requirement must be the full requirement-card object",
            },
        )
    project_name = str(body.get("project_name") or "").strip()
    _target_dir = body.get("target_dir")  # 只透传不使用:本端点零写回(契约 §3)

    try:
        result = af_generate.generate_from_requirement(requirement, project_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": str(exc) or "REQUIREMENT_INVALID",
                "message": "requirement.confirmation_status must be 'confirmed' before generation",
            },
        ) from exc
    except Exception as exc:
        logger.exception("canvas/generate-from-requirement failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "AF_GENERATION_FAILED",
                "message": f"failed to generate canvas draft from requirement: {exc}",
            },
        ) from exc

    return ApiResponse(
        ok=True,
        data={
            "canvas": result["canvas"],
            "blocks_created": result["blocks_created"],
            "linter_findings": result["linter_findings"],
            "iec_violations": result["iec_violations"],
        },
        request_id=request_id,
    )


@router.post("/canvas/confirm-writeback", response_model=ApiResponse[dict[str, Any]])
async def confirm_canvas_writeback_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Human Confirmation Gate: schedules a compile job (or sync writeback if sync=true).

    确认即建事务（PCEC docs/19 §4）：创建编译作业**之前**按契约建立变更事务
    （new_change → 预检 v1_static → approval 由本次确认承载 → approved → 账本），
    change_id 随作业与响应下发。事务全程 try/except：任何异常只记 warning，
    绝不阻塞写回主流程（PCEC 只做记账员，不做新故障点）。
    """
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

    # --- PCEC 确认即建事务（契约 §4）：异常只 warning，写回照旧 ---
    change_id = ""
    try:
        from gateway.app.services.plc.compile_jobs import open_writeback_change

        change_id = open_writeback_change(
            canvas, project_path=project_path, reviewer=principal.subject or "engineer"
        )
    except Exception as exc:  # noqa: BLE001 - 记账失败不阻塞确认/写回
        logger.warning("pcec change skipped at confirm-writeback: %s", exc)

    # --- 需求卡弱关联（契约 docs/22 §2）：可选 requirement_id 补进事务 intent ---
    # compile_jobs.open_writeback_change 签名不可改（并行线边界），这里在它建账
    # 之后、作业创建之前读改写账本：get_change → intent.requirement_id → put_change。
    # 弱关联失败只 warning，绝不阻塞写回；不带/非法格式的 requirement_id 零额外动作。
    requirement_id = str(body.get("requirement_id") or "").strip()
    if change_id and requirement_id:
        try:
            from gateway.app.services.plc import requirement_store

            if requirement_store.is_valid_requirement_id(requirement_id):
                from plc_engine import pcec

                chg = pcec.get_change(change_id)
                if chg is not None:
                    intent = chg.get("intent")
                    if not isinstance(intent, dict):
                        intent = chg["intent"] = {}
                    intent["requirement_id"] = requirement_id
                    pcec.put_change(chg)
        except Exception as exc:  # noqa: BLE001 - 弱关联失败只 warning
            logger.warning("pcec requirement link skipped at confirm-writeback: %s", exc)

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
            change_id=change_id,
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
                "change_id": change_id,
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
    # 同步分支没有作业收敛点，这里直接按结果落账（异常只 warning）
    try:
        from gateway.app.services.plc.compile_jobs import settle_change_from_result

        settle_change_from_result(
            change_id,
            ok=bool(result.get("ok")),
            writeback=result,
            attributions=list(attributions or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pcec settle skipped at confirm-writeback (sync): %s", exc)
    return ApiResponse(
        ok=True,
        data={
            "async": False,
            "job": None,
            "writeback": result,
            "attributions": attributions,
            "canvas": canvas.to_dict(),
            "change_id": change_id,
        },
        request_id=request_id,
    )


@router.get("/canvas/changes", response_model=ApiResponse[list[dict[str, Any]]])
async def list_canvas_changes(
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict[str, Any]]]:
    """PCEC 变更事务 meta 列表（updated_at 降序）。

    账本不可用（pcec 未交付/损坏）时返回空列表，不报错——前端 Mock-first
    拿到空列表回落内置示例（契约 §5）。
    """
    _ = principal
    from gateway.app.services.plc.compile_jobs import list_pcec_changes

    return ApiResponse(ok=True, data=list_pcec_changes(), request_id=request_id)


@router.get("/canvas/changes/{change_id}", response_model=ApiResponse[dict[str, Any]])
async def get_canvas_change(
    change_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """单个 PCEC 变更事务的完整 JSON（状态机/四 V 验证/审批/回滚证据）。"""
    _ = principal
    from gateway.app.services.plc.compile_jobs import get_pcec_change

    data = get_pcec_change(change_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_CHANGE_NOT_FOUND",
                "message": f"change {change_id} not found",
            },
        )
    return ApiResponse(ok=True, data=data, request_id=request_id)


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
    if built.get("refactored_canvas"):
        canvas = CanvasState.from_dict(built["refactored_canvas"])
        canvas.append_revision([], source="af_refactor", message=prompt[:120])
        built["canvas"] = canvas.to_dict()
    elif apply and built.get("ops"):
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
            "mode": result.get("mode") or "direct",
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


@router.post("/canvas/refactor", response_model=ApiResponse[dict[str, Any]])
@router.post("/canvas/refactor-to-af", response_model=ApiResponse[dict[str, Any]])
async def canvas_refactor_to_af_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Legacy-to-AF Mapper and behavior-preserving refactoring engine.

    Reverse engineers a legacy flat PLC canvas into official Siemens AF V1.2 Software
    Units architecture (Unit -> EMs -> CMs) with 100% physical I/O retention.
    """
    _ = principal
    from plc_engine.af.refactor import refactor_canvas_to_af
    from plc_engine.canvas_model import CanvasState

    canvas_raw = body.get("canvas")
    if not isinstance(canvas_raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "CANVAS_REQUIRED", "message": "body.canvas is required"},
        )
    canvas = CanvasState.from_dict(canvas_raw)
    target_unit_name = str(body.get("target_unit_name") or f"U1_{canvas.project_name or 'Refactored'}").strip()

    new_canvas, report = refactor_canvas_to_af(canvas, target_unit_name=target_unit_name)

    logger.info(
        "plc canvas refactor-to-af unit=%s ems=%d blocks=%d io_retention=%.1f%% request_id=%s",
        target_unit_name,
        len(report.get("ems") or []),
        len(report.get("af_blocks_created") or []),
        (report.get("io_retention") or {}).get("percentage", 0.0),
        request_id,
    )
    return ApiResponse(
        ok=True,
        data={
            "canvas": new_canvas.to_dict(),
            "report": report,
        },
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
    # af_analysis 兜底:服务层 AF 标注异常时保证字段仍存在(conformant=null)
    data.setdefault(
        "af_analysis", {"conformant": None, "roles_count": 0, "pending_count": 0}
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
    # af_analysis 兜底:服务层 AF 标注异常时保证字段仍存在(conformant=null)
    result.setdefault(
        "af_analysis", {"conformant": None, "roles_count": 0, "pending_count": 0}
    )
    return ApiResponse(ok=True, data=result, request_id=request_id)


@router.get("/canvas/af/report/latest", response_model=ApiResponse[dict[str, Any]])
async def canvas_af_report_latest_endpoint(
    principal: PrincipalDep,
    request_id: RequestIdDep,
    project: str = "",
) -> ApiResponse[dict[str, Any]]:
    """取项目最新的导入分析报告(``PLC_WORK_DIR/af_reports/``);无报告 404。

    ``project`` 为空时取目录内最新一份。报告内容为纯分析数据(角色映射/
    pending 清单/覆盖率),不含任何画布物理变更。
    """
    _ = principal
    from gateway.app.services.plc import af_import

    report = af_import.latest_report(project)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "AF_REPORT_NOT_FOUND",
                "message": f"项目 {project or '(任意)'} 尚无导入分析报告",
            },
        )
    return ApiResponse(ok=True, data=report, request_id=request_id)


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


@router.post("/canvas/db/import", response_model=ApiResponse[dict[str, Any]])
async def canvas_db_import_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """Import SCL DATA_BLOCK text onto the canvas as DB blocks (docs/24 B 线).

    body: ``{db_text (SCL 文本) 或 file_path, project_name, canvas?}`` — 传入上次
    响应的 ``canvas`` 可合并多个 DB（多次调用/一段文本多个 DATA_BLOCK 均可）。
    Returns ``{blocks_created, canvas}``.
    """
    _ = principal
    import asyncio

    db_text = str(body.get("db_text") or "").strip()
    file_path = str(body.get("file_path") or "").strip()
    project_name = str(body.get("project_name") or "").strip()
    if not db_text and not file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "DB_TEXT_REQUIRED",
                "message": "db_text（SCL 文本）或 file_path 必填其一",
            },
        )

    resolved = None
    if not db_text:
        try:
            resolved = plc.resolve_allowed_path(file_path)
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

    from gateway.app.services.plc.db_import import (
        DBImportRejected,
        import_db_path,
        import_db_text,
    )
    from plc_engine.canvas_model import CanvasState

    canvas = None
    canvas_raw = body.get("canvas")
    if isinstance(canvas_raw, dict) and canvas_raw:
        canvas = CanvasState.from_dict(canvas_raw)

    try:
        if resolved is not None:
            data = await asyncio.to_thread(
                import_db_path, resolved, project_name, canvas
            )
        else:
            data = await asyncio.to_thread(
                import_db_text, db_text, project_name, canvas
            )
    except DBImportRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    logger.info(
        "plc canvas db import blocks=%s project=%s request_id=%s",
        data.get("blocks_created"),
        (data.get("canvas") or {}).get("project_name"),
        request_id,
    )
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.post("/canvas/mermaid/generate", response_model=ApiResponse[dict[str, Any]])
async def canvas_mermaid_generate_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """LLM 生成工艺 Mermaid 时序图（契约 docs/24 C 线）：对话 + 画布 → sequenceDiagram。

    body: {prompt, canvas}。空 prompt → 400 code=PROMPT_REQUIRED；
    未配置 PLC_LLM_* / DEEPSEEK_API_KEY → 400 code=LLM_NOT_CONFIGURED（附配置指引）；
    LLM 调用失败或输出非法（缺 sequenceDiagram 声明）→ 502 code=LLM_CALL_FAILED。
    成功返回 {mermaid, description}——前端 ChatDock 检测 ```mermaid 围栏后内联渲染 SVG。
    """
    _ = principal
    import asyncio

    from gateway.app.services.plc.llm_explain import LlmNotConfigured
    from gateway.app.services.plc.mermaid_gen import generate_mermaid_sequence
    from plc_engine.canvas_model import CanvasState

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROMPT_REQUIRED", "message": "body.prompt is required"},
        )
    canvas = CanvasState.from_dict(body.get("canvas") or {})
    try:
        result = await asyncio.to_thread(generate_mermaid_sequence, prompt, canvas)
    except LlmNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "LLM_NOT_CONFIGURED",
                "message": (
                    "生成 Mermaid 时序图需要 LLM：在网关进程设置环境变量 "
                    "PLC_LLM_BASE_URL（OpenAI 兼容端点）、PLC_LLM_API_KEY、PLC_LLM_MODEL，"
                    "或执行 setx DEEPSEEK_API_KEY <key> 后重启网关即可沿用 DeepSeek。"
                ),
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "LLM_CALL_FAILED", "message": str(exc)},
        ) from exc

    logger.info(
        "plc canvas mermaid generated blocks=%s request_id=%s",
        len(canvas.blocks),
        request_id,
    )
    return ApiResponse(ok=True, data=result, request_id=request_id)


@router.post("/canvas/generate-from-mermaid", response_model=ApiResponse[dict[str, Any]])
async def canvas_generate_from_mermaid_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """D 线契约(docs/24 §D):Mermaid sequenceDiagram → AF V1.2 画布草稿。

    body ``{mermaid, project_name}``;链路纯文本解析(零 LLM):
    ``mermaid_parser.plan_from_mermaid``(participant→CM、消息/alt/Note→步序)
    → ``af_generator.generate_af_project_blocks``(官方 V1.2 块)→ 合成画布
    (全部 draft,零写回)→ ``af_linter.lint_af_canvas`` 静态预检。
    返回 ``{canvas, blocks_created, linter_findings}``;空/非法 Mermaid → 400。
    """
    _ = principal
    from dataclasses import asdict

    from plc_engine.af.af_generator import generate_af_project_blocks
    from plc_engine.af.af_linter import lint_af_canvas
    from plc_engine.af.mermaid_parser import MermaidParseError, plan_from_mermaid
    from plc_engine.canvas_model import CanvasState

    mermaid_text = body.get("mermaid")
    if not isinstance(mermaid_text, str) or not mermaid_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MERMAID_REQUIRED",
                "message": "body.mermaid (Mermaid sequenceDiagram text) is required",
            },
        )
    project_name = str(body.get("project_name") or "").strip() or "AF_Project"

    try:
        af_project = plan_from_mermaid(mermaid_text, project_name=project_name)
    except MermaidParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": str(exc) or "MERMAID_INVALID",
                "message": f"invalid Mermaid sequenceDiagram: {exc}",
            },
        ) from exc
    except Exception as exc:
        logger.exception("canvas/generate-from-mermaid failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "AF_GENERATION_FAILED",
                "message": f"failed to plan AF project from Mermaid: {exc}",
            },
        ) from exc

    generated = generate_af_project_blocks(af_project)
    canvas = CanvasState(project_name=af_project.name)
    for key, block in generated.items():
        block.status = "draft"
        canvas.blocks[key] = block

    findings = lint_af_canvas(canvas)
    linter_findings = [
        asdict(f) if hasattr(f, "__dataclass_fields__") else f for f in findings
    ]

    logger.info(
        "plc canvas generate-from-mermaid blocks=%s project=%s request_id=%s",
        len(generated),
        af_project.name,
        request_id,
    )
    return ApiResponse(
        ok=True,
        data={
            "canvas": canvas.to_dict(),
            "blocks_created": len(generated),
            "linter_findings": linter_findings,
        },
        request_id=request_id,
    )


@router.post("/canvas/io/import", response_model=ApiResponse[dict[str, Any]])
async def canvas_io_import_endpoint(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """IO 表导入（契约 docs/24 · A 线）：PLCTags.xlsx 路径或 CSV 文本 → 画布标签。

    body: ``{file_path``（服务器路径，走 PLC_PATH_ALLOWLIST 校验）或
    ``file_content``（CSV 文本），``project_name``；可选 ``canvas``（上次响应
    的画布 dict，传入则增量合并，否则新建空白画布）``}``。同名标签不覆盖、
    blocks/HMI 不动，导入标签 status="draft"。返回
    ``{tags_created, tags_skipped, tags_total, canvas}``。
    """
    _ = principal
    import asyncio

    from gateway.app.services.plc.io_import import IoImportRejected, import_io_table

    file_path = str(body.get("file_path") or "").strip()
    file_content = body.get("file_content")
    csv_text = file_content if isinstance(file_content, str) else ""
    project_name = str(body.get("project_name") or "").strip()

    if not file_path and not csv_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "IO_SOURCE_REQUIRED",
                "message": "file_path 或 file_content（CSV 文本）至少提供一个",
            },
        )

    resolved: Path | None = None
    if file_path:
        try:
            resolved = plc.resolve_allowed_path(file_path)
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

    canvas = None
    canvas_raw = body.get("canvas")
    if isinstance(canvas_raw, dict) and canvas_raw:
        from plc_engine.canvas_model import CanvasState

        canvas = CanvasState.from_dict(canvas_raw)

    try:
        # file_path 与 file_content 同时给出时以文件路径为准
        result = await asyncio.to_thread(
            import_io_table,
            resolved,
            canvas,
            project_name,
            csv_text="" if resolved is not None else csv_text,
        )
    except IoImportRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    logger.info(
        "plc canvas io import file=%s created=%s skipped=%s total=%s request_id=%s",
        resolved or "(csv_text)",
        result.get("tags_created"),
        result.get("tags_skipped"),
        result.get("tags_total"),
        request_id,
    )
    return ApiResponse(ok=True, data=result, request_id=request_id)


# —— P 线:Project / Conversation 两层模型(契约 docs/25 §1)——
# Session(消息+画布耦合)拆为 Project(画布唯一权威容器)+ Conversation
# (纯消息流);旧 /canvas/sessions 端点保留读旧数据,新代码一律走下面这组。


@router.get("/canvas/projects", response_model=ApiResponse[list[dict[str, Any]]])
async def list_canvas_projects(
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict[str, Any]]]:
    """工程列表(轻量 meta:name/updated_at/conversation_count,不含画布)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    return ApiResponse(ok=True, data=project_store.list_projects(), request_id=request_id)


@router.post("/canvas/projects", response_model=ApiResponse[dict[str, Any]])
async def create_canvas_project(
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """新建工程。body: ``{project_name, canvas?}``;未传 canvas 则建空白画布。"""
    _ = principal
    from gateway.app.services.plc import project_store

    project_name = str(body.get("project_name") or "").strip()
    canvas = body.get("canvas")
    if not project_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_PROJECT_INVALID", "message": "project_name required"},
        )
    if not isinstance(canvas, dict) or not canvas:
        canvas = {
            "project_name": project_name,
            "blocks": {},
            "hmi_widgets": {},
            "tags": {},
        }
    now = time.time()
    project = {
        "id": project_store.new_project_id(),
        "project_name": project_name,
        "canvas": canvas,
        "created_at": now,
        "updated_at": now,
    }
    project_store.put_project(project)
    logger.info("plc project created id=%s name=%s request_id=%s", project["id"], project_name, request_id)
    return ApiResponse(ok=True, data=project_store.get_project(project["id"]), request_id=request_id)


@router.post("/canvas/projects/migrate", response_model=ApiResponse[dict[str, Any]])
async def migrate_canvas_projects(
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """旧 sessions → projects/conversations 手动触发迁移(幂等,可重复调用)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    stats = project_store.migrate_from_sessions()
    logger.info(
        "plc projects migrated projects=%s conversations=%s request_id=%s",
        stats.get("projects_migrated"),
        stats.get("conversations_migrated"),
        request_id,
    )
    return ApiResponse(ok=True, data=stats, request_id=request_id)


@router.get("/canvas/projects/{project_id}", response_model=ApiResponse[dict[str, Any]])
async def get_canvas_project(
    project_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """单工程完整对象(含画布与 conversation_count)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    data = project_store.get_project(project_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_PROJECT_NOT_FOUND",
                "message": f"project {project_id} not found",
            },
        )
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.put("/canvas/projects/{project_id}", response_model=ApiResponse[dict[str, Any]])
async def put_canvas_project(
    project_id: str,
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """整工程 upsert(body 即完整工程对象,画布唯一权威写入口)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    project = dict(body or {})
    project["id"] = project_id
    try:
        meta = project_store.put_project(project)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_PROJECT_INVALID", "message": str(exc)},
        ) from exc
    return ApiResponse(ok=True, data=meta, request_id=request_id)


@router.delete("/canvas/projects/{project_id}", response_model=ApiResponse[dict[str, Any]])
async def delete_canvas_project(
    project_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """删除工程并级联删除其全部对话(幂等)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    cascaded = project_store.delete_project(project_id)
    if cascaded is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_PROJECT_NOT_FOUND",
                "message": f"project {project_id} not found",
            },
        )
    logger.info(
        "plc project deleted id=%s conversations_cascaded=%s request_id=%s",
        project_id,
        cascaded,
        request_id,
    )
    return ApiResponse(
        ok=True, data={"removed": project_id, "conversations_removed": cascaded}, request_id=request_id
    )


@router.get("/canvas/projects/{project_id}/conversations", response_model=ApiResponse[list[dict[str, Any]]])
async def list_canvas_conversations(
    project_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[list[dict[str, Any]]]:
    """某工程下对话 meta 列表(id/project_id/title/updated_at,无消息体)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    return ApiResponse(
        ok=True, data=project_store.list_conversations(project_id), request_id=request_id
    )


@router.post("/canvas/projects/{project_id}/conversations", response_model=ApiResponse[dict[str, Any]])
async def create_canvas_conversation(
    project_id: str,
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """在工程下新建空对话。body: ``{title?}``(缺省「新对话」)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    if project_store.get_project(project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_PROJECT_NOT_FOUND",
                "message": f"project {project_id} not found",
            },
        )
    now = time.time()
    conversation = {
        "id": project_store.new_conversation_id(),
        "project_id": project_id,
        "title": (str(body.get("title") or "").strip() or "新对话")[:120],
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    project_store.put_conversation(conversation)
    return ApiResponse(
        ok=True, data=project_store.get_conversation(conversation["id"]), request_id=request_id
    )


@router.get("/canvas/conversations/{conversation_id}", response_model=ApiResponse[dict[str, Any]])
async def get_canvas_conversation(
    conversation_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """单对话完整对象(含 messages,不含画布)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    data = project_store.get_conversation(conversation_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_CONVERSATION_NOT_FOUND",
                "message": f"conversation {conversation_id} not found",
            },
        )
    return ApiResponse(ok=True, data=data, request_id=request_id)


@router.put("/canvas/conversations/{conversation_id}", response_model=ApiResponse[dict[str, Any]])
async def put_canvas_conversation(
    conversation_id: str,
    body: dict[str, Any],
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """整对话 upsert(body 即完整对话对象,只带消息不带画布)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    conversation = dict(body or {})
    conversation["id"] = conversation_id
    try:
        meta = project_store.put_conversation(conversation)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PLC_CONVERSATION_INVALID", "message": str(exc)},
        ) from exc
    return ApiResponse(ok=True, data=meta, request_id=request_id)


@router.delete("/canvas/conversations/{conversation_id}", response_model=ApiResponse[dict[str, Any]])
async def delete_canvas_conversation(
    conversation_id: str,
    principal: PrincipalDep,
    request_id: RequestIdDep,
) -> ApiResponse[dict[str, Any]]:
    """删对话并同步所属工程 conversation_count(幂等)。"""
    _ = principal
    from gateway.app.services.plc import project_store

    removed = project_store.delete_conversation(conversation_id)
    if removed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PLC_CONVERSATION_NOT_FOUND",
                "message": f"conversation {conversation_id} not found",
            },
        )
    return ApiResponse(ok=True, data={"removed": conversation_id}, request_id=request_id)
