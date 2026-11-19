"""AF-Studio v5 orthogonal hypergraph API router (/api/v2/af-studio/*)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from gateway.app.services.plc.af_v5_native import ARCHIVE_NAME, archive_kuka_snapshot

from gateway.app.schemas.v2_af_studio import (
    CopilotGhostPatchIn,
    CutSetSnapshotIn,
    HyperGraphCompileIn,
    HyperGraphVerifyIn,
    MerkleSyncIn,
)
from gateway.app.schemas.v2_common import V2ErrorCodes, error_response, ok_response
from gateway.app.services.plc.af_studio_v5_service import (
    compile_hypergraph,
    get_mother_class_registry,
    get_seed_workspace,
    propose_ghost_transaction,
    sync_merkle_blocks,
    trace_cutset_snapshot,
    verify_hypergraph,
)

router = APIRouter(prefix="/api/v2/af-studio", tags=["af-studio-v5"])
logger = logging.getLogger(__name__)
_offline_export_lock = Lock()


@router.post("/export/tia-v19", response_class=FileResponse)
def export_tia_v19(workspace: dict):
    """Download a new, compiled and reopened offline V19 archive."""
    rid = _rid("")
    snapshot = json.dumps(workspace, ensure_ascii=False).encode("utf-8")
    if len(snapshot) > 1_000_000:
        return error_response(413, V2ErrorCodes.INVALID_REQUEST, "工程快照超过导出大小限制。", request_id=rid)
    if not _offline_export_lock.acquire(blocking=False):
        return error_response(409, "TIA_EXPORT_BUSY", "V19 离线导出正在运行，请稍后重试。", request_id=rid)

    temp = None
    downloaded = False
    try:
        temp = TemporaryDirectory(prefix="af5v19_", ignore_cleanup_errors=True)
        result = archive_kuka_snapshot(snapshot, Path(temp.name) / "export")
        artifact = result.artifact
        if not result.ok or result.state != "NATIVE_ARCHIVED" or artifact is None or not artifact.reopen_ok:
            stage = result.stage_receipts[-1].stage if result.stage_receipts else "TIA"
            detail = result.error_message or "编译或还原校验未通过。"
            return error_response(502, result.error_code or V2ErrorCodes.TIA_UNAVAILABLE,
                                  f"{stage} 阶段：{detail}", request_id=rid)
        response = FileResponse(
            artifact.archive_path,
            media_type="application/octet-stream",
            filename=ARCHIVE_NAME,
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(temp.cleanup),
        )
        downloaded = True
        return response
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return error_response(422, V2ErrorCodes.INVALID_REQUEST,
                              f"工程不符合此 V19 离线导出配置：{exc}", request_id=rid)
    except OSError:
        logger.exception("V5 native export failed (%s)", rid)
        return error_response(500, V2ErrorCodes.TIA_UNAVAILABLE, "无法生成归档文件。", request_id=rid)
    finally:
        if temp is not None and not downloaded:
            temp.cleanup()
        _offline_export_lock.release()


def _rid(value: str) -> str:
    return value or f"req_{uuid.uuid4().hex[:12]}"


@router.get("/mother-classes")
def get_af_mother_classes(refresh: bool = Query(False)):
    """Reflect AF driver mother classes from local STA daemon or return built-in registry."""
    data, evidence_level = get_mother_class_registry(force_refresh=refresh)
    return ok_response(data, request_id=_rid(""), evidence_level=evidence_level)


@router.get("/workspace/seed")
@router.get("/seed-workspace")
def get_af_seed_workspace():
    """Return the AssyLine_01 + ST10/ST20/ST30 spatio-temporal seed workspace."""
    return ok_response(get_seed_workspace(), request_id=_rid(""), evidence_level="offline")


@router.post("/verify")
@router.post("/verify/symbolic")
def post_verify_hypergraph(body: HyperGraphVerifyIn):
    """Run Tarjan+Kahn homing synthesis and discrete state-space BFS collision checks."""
    try:
        report = verify_hypergraph(body.station, ghost_tx=body.ghost_tx)
    except ValueError as exc:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    return ok_response(report, request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/compile")
@router.post("/compile/scl")
def post_compile_hypergraph(body: HyperGraphCompileIn):
    """Deterministically compile station orthogonal hypergraph into 4 TIA SCL blocks."""
    try:
        compiled = compile_hypergraph(body.station)
    except ValueError as exc:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    return ok_response(compiled, request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/merkle-sync")
@router.post("/merkle/sync")
@router.post("/merkle/manifest")
def post_merkle_sync(body: MerkleSyncIn):
    """Compute block-level Merkle diffs and optionally sync dirty blocks to TIA Openness STA."""
    try:
        data, evidence_level = sync_merkle_blocks(
            body.project_id,
            body.station,
            previous_hashes=body.previous_hashes,
            project_path=body.project_path,
            plc_name=body.plc_name,
            software_unit=body.software_unit,
        )
    except ValueError as exc:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    return ok_response(data, request_id=_rid(body.request_id), evidence_level=evidence_level)


@router.post("/copilot/ghost-patch")
@router.post("/copilot/intent-diff")
def post_copilot_ghost_patch(body: CopilotGhostPatchIn):
    """Synthesize GhostGraphTransaction from natural language or timing/IO table rows."""
    has_prompt = bool((body.prompt or "").strip())
    has_tables = bool(body.timing_table_rows or body.io_table_rows)
    if not has_prompt and not has_tables:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            "需要提供自然语言指令 prompt 或表格冷启动行数据。",
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    try:
        tx = propose_ghost_transaction(
            body.station,
            prompt=body.prompt,
            timing_table_rows=body.timing_table_rows,
            io_table_rows=body.io_table_rows,
        )
    except ValueError as exc:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    return ok_response(tx, request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/synthesize/homing")
def post_synthesize_homing(body: HyperGraphVerifyIn):
    """Synthesize Tarjan+Kahn layered safe homing sequence."""
    try:
        report = verify_hypergraph(body.station, ghost_tx=body.ghost_tx)
    except ValueError as exc:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    return ok_response(report.get("homingResult", {}), request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/diagnostics/cutset-snapshot")
@router.post("/cutset/trace")
def post_diagnostics_cutset_snapshot(body: CutSetSnapshotIn):
    """Evaluate minimal falsifying cut-set across station boundaries and emit 3-stage camera fly plan."""
    try:
        result = trace_cutset_snapshot(
            body.project_graph,
            body.station_graphs,
            body.fault_station_id,
            body.fault_step_no,
            live_signals=body.live_signals,
        )
    except (KeyError, LookupError) as exc:
        return error_response(
            404,
            V2ErrorCodes.PROJECT_NOT_FOUND,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    except ValueError as exc:
        return error_response(
            422,
            V2ErrorCodes.INVALID_REQUEST,
            str(exc),
            request_id=_rid(body.request_id),
            evidence_level="offline",
        )
    return ok_response(result, request_id=_rid(body.request_id), evidence_level="offline")
