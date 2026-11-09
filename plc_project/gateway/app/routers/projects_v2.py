"""V2 unified API router (design 5, endpoints 1-15 + A-1/A-2/A-3).

Single gateway, no third backend. v1 routers stay registered unchanged. Every
response uses the V2 envelope that is a superset of the v1 ApiResponse, and
carries an explicit ``evidence_level``.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

from gateway.app.schemas.v2_common import V2ErrorCodes, error_response, ok_response
from gateway.app.schemas.v2_delivery import DeliveryIn
from gateway.app.schemas.v2_ir import (
    ApproveIn,
    BrownfieldDiffPlanIn,
    ChangesetIn,
    CreateProjectIn,
    IntentIn,
    PatchIn,
    PreviewIn,
    SimulateIn,
    ValidateIn,
)
from gateway.app.services.plc.approval_v2 import ApprovalGate, ApprovalRejectedError
from gateway.app.services.plc.artifact_store_v2 import (
    ArtifactJobMismatchError,
    ArtifactNotFoundError,
    ArtifactStore,
)
from gateway.app.services.plc.capability_v2 import probe_capability, probe_cli_payload
from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator, DeliveryStartError
from gateway.app.services.plc.derivation_v2 import DerivationServiceV2
from gateway.app.services.plc.engineering_service_v2 import EngineeringServiceV2
from gateway.app.services.plc.intent_service_v2 import IntentServiceV2
from gateway.app.services.plc.validation_v2 import ValidationServiceV2
from gateway.app.services.plc.workspace_v2 import ProjectNotFoundError, WorkspaceStore, get_store
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import new_project_ir
from plc_engine.engineering_ir.patch import (
    PatchConflictError,
    SemanticValidationError,
    make_patch,
)
from plc_engine.engineering_ir.v1_adapter import V1ToV2Adapter

router = APIRouter(prefix="/api/v2", tags=["v2"])

StoreDep = Depends(get_store)


def _rid(value: str) -> str:
    return value or f"req_{uuid.uuid4().hex[:12]}"


def _require_project(store: WorkspaceStore, project_id: str):
    """Return the project or a 404 envelope."""
    if not store.project_exists(project_id):
        return error_response(404, V2ErrorCodes.PROJECT_NOT_FOUND, f"unknown project {project_id!r}")
    return None


# --------------------------------------------------------------------------- #
# 1-4: workspace reads
# --------------------------------------------------------------------------- #


@router.post("/projects", status_code=201)
def create_project(body: CreateProjectIn, store: WorkspaceStore = StoreDep):
    """Create/import a V2 workspace at revision 0."""
    project_id = body.project_id or f"prj_{uuid.uuid4().hex[:12]}"
    try:
        if body.legacy_ir or body.v1_fixture:
            ir = V1ToV2Adapter.to_v2(body.legacy_ir or body.v1_fixture or {}, project_id=project_id)
        else:
            ir = new_project_ir(project_id)
        data = EngineeringServiceV2.create_project(store, project_id, ir=ir, origin=body.origin)
    except ValueError as exc:
        return error_response(422, V2ErrorCodes.INVALID_REQUEST, str(exc), request_id=_rid(body.request_id))
    return ok_response(data, request_id=_rid(body.request_id), evidence_level="offline", code=0, message="created")


@router.get("/projects/{project_id}")
def get_project(project_id: str, store: WorkspaceStore = StoreDep):
    """Project metadata + capability + delivery state + evidence level."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    workspace = store.get_project(project_id)
    manifest = store.latest_capability_probe()
    return ok_response(
        {
            **workspace.to_dict(),
            "capability": probe_cli_payload(manifest) if manifest else None,
            "ir_sha256": store.get_ir(project_id).ir_sha256,
        },
        evidence_level=workspace.evidence_level.value
        if isinstance(workspace.evidence_level, EvidenceLevel) else str(workspace.evidence_level),
    )


@router.get("/projects/{project_id}/ir")
def get_ir(project_id: str, store: WorkspaceStore = StoreDep):
    """Read the authoritative EngineeringIR v2."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    ir = store.get_ir(project_id)
    report = ValidationServiceV2.validate_ir(ir)
    return ok_response(
        {
            "project_id": project_id,
            "revision": ir.revision,
            "ir_sha256": ir.ir_sha256,
            "ir": ir.to_dict(),
            "derived_dirty": not report.passed,
            "schema_version": ir.schema_version,
        },
        evidence_level="offline",
    )


@router.get("/projects/{project_id}/blocks")
def get_blocks(project_id: str, store: WorkspaceStore = StoreDep):
    """v1-compatible read-only block index."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    return ok_response(EngineeringServiceV2.blocks(store, project_id), evidence_level="offline")


# --------------------------------------------------------------------------- #
# 5-9: intent / patch / validate / simulate / preview
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/intent")
def post_intent(project_id: str, body: IntentIn, store: WorkspaceStore = StoreDep):
    """NL -> CandidatePatch only (no IR write, no TIA write, no free SCL)."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    ir = store.get_ir(project_id)
    result = IntentServiceV2().parse(
        ir=ir, message=body.message, context_slice=body.context_slice,
        base_revision=body.base_revision, request_id=_rid(body.request_id),
    )
    return ok_response(result, request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/projects/{project_id}/patches")
def post_patch(project_id: str, body: PatchIn, store: WorkspaceStore = StoreDep):
    """Atomic semantic patch: 409 on stale revision, 422 on validation failure."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    request_id = _rid(body.request_id)
    patch = make_patch(project_id, body.base_revision, body.ops, request_id=request_id)
    try:
        result = store.commit_patch(project_id, patch)
    except PatchConflictError as exc:
        return error_response(
            409, V2ErrorCodes.BASE_REVISION_CONFLICT, str(exc),
            data={"code": V2ErrorCodes.BASE_REVISION_CONFLICT, "current_revision": exc.current_revision},
            request_id=request_id, evidence_level="offline",
        )
    except SemanticValidationError as exc:
        return error_response(
            422, V2ErrorCodes.SEMANTIC_VALIDATION_FAILED, str(exc),
            data={"code": V2ErrorCodes.SEMANTIC_VALIDATION_FAILED,
                  "issues": exc.issues, "unchanged_ir_hash": exc.unchanged_ir_hash},
            request_id=request_id, evidence_level="offline",
        )
    bundle = DerivationServiceV2(store).derive_all(project_id)
    payload = result.to_dict()
    payload["derived"] = {
        "manifest_sha256": bundle.manifest.sha256,
        "trace_frames": len(bundle.trace),
        "scl_files": sorted(bundle.scl_files),
        "source_map_entries": len(bundle.source_map.mappings),
    }
    payload["derived_dirty"] = not bundle.validation.passed
    return ok_response(payload, request_id=request_id, evidence_level="offline")


@router.post("/projects/{project_id}/validate")
def post_validate(project_id: str, body: ValidateIn, store: WorkspaceStore = StoreDep):
    """Full deterministic static validation (9 check families)."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    gate = DerivationServiceV2(store).validate(project_id)
    payload = {
        "passed": gate["passed"], "issues": gate["issues"],
        "unchanged_ir_hash": gate["unchanged_ir_hash"],
        "manifest_sha256": gate["manifest_sha256"],
        "unsupported_parallel_semantics": gate["unsupported_parallel_semantics"],
        "evidence_level": "offline",
    }
    if not gate["passed"]:
        return error_response(
            422, V2ErrorCodes.SEMANTIC_VALIDATION_FAILED, "static validation failed",
            data=payload, request_id=_rid(body.request_id), evidence_level="offline",
        )
    return ok_response(payload, request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/projects/{project_id}/simulate")
def post_simulate(project_id: str, body: SimulateIn, store: WorkspaceStore = StoreDep):
    """Deterministic offline Trace (explicitly labelled a prediction)."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    try:
        payload = DerivationServiceV2(store).simulate(project_id, body.scenario)
    except KeyError as exc:
        return error_response(422, V2ErrorCodes.INVALID_REQUEST, str(exc),
                              request_id=_rid(body.request_id), evidence_level="offline")
    return ok_response(payload, request_id=_rid(body.request_id), evidence_level="offline")


@router.post("/projects/{project_id}/preview")
def post_preview(project_id: str, body: PreviewIn, store: WorkspaceStore = StoreDep):
    """IR -> generated SCL / SourceMap / ArtifactManifest (one-way)."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    payload = DerivationServiceV2(store).preview(project_id, include_scl=body.include_scl)
    return ok_response(payload, request_id=_rid(body.request_id), evidence_level="offline")


# --------------------------------------------------------------------------- #
# 10-11: changesets / explicit approval
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/changesets", status_code=201)
def post_changeset(project_id: str, body: ChangesetIn, store: WorkspaceStore = StoreDep):
    """Freeze a diff + review pack (no TIA write)."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    changeset = EngineeringServiceV2.freeze_changeset(
        store, project_id, base_revision=body.base_revision, ops=body.ops
    )
    if changeset.status == "FAILED":
        return error_response(
            422, V2ErrorCodes.SEMANTIC_VALIDATION_FAILED, "cannot freeze a failed validation",
            data=changeset.validation.to_dict(), request_id=_rid(body.request_id), evidence_level="offline",
        )
    payload = {
        "changeset_id": changeset.id,
        "before_hash": changeset.before_hash,
        "after_hash": changeset.after_hash,
        "spec_hash": changeset.spec_hash,
        "impacts": changeset.impacts,
        "status": changeset.status,
        "evidence_level": "offline",
    }
    return ok_response(payload, request_id=_rid(body.request_id), evidence_level="offline", code=0, message="created")


@router.post("/changesets/{changeset_id}/approve")
def post_approve(changeset_id: str, body: ApproveIn, store: WorkspaceStore = StoreDep):
    """Explicit human approval (LLM never holds this tool)."""
    try:
        approved = ApprovalGate(store).approve(
            changeset_id, reviewer=body.reviewer_id, explicit=body.explicit,
            expected_baseline_hash=body.expected_baseline_hash,
        )
    except ApprovalRejectedError as exc:
        status = 409 if exc.code == V2ErrorCodes.BASELINE_HASH_MISMATCH else 403
        return error_response(status, exc.code, str(exc), request_id=_rid(body.request_id), evidence_level="offline")
    return ok_response(
        {
            "approved_changeset_id": approved.id,
            "signed_spec_hash": approved.signed_spec_hash,
            "signed_at": approved.signed_at,
            "reviewer": approved.approved_by,
            "explicit": approved.explicit,
            "evidence_level": "offline",
        },
        request_id=_rid(body.request_id), evidence_level="offline",
    )


# --------------------------------------------------------------------------- #
# 12-15 + A-2: deliveries / jobs / events / exact download / source package
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/deliveries")
def post_delivery(project_id: str, body: DeliveryIn, store: WorkspaceStore = StoreDep):
    """Accept a delivery: 202 + job_id. No real chain is executed implicitly."""
    payload = body.model_dump()
    payload["project_id"] = project_id
    try:
        data, status = DeliveryCoordinator(store).start(payload)
    except DeliveryStartError as exc:
        return error_response(exc.status_code, exc.code, str(exc), data=exc.data,
                              request_id=_rid(body.request_id), evidence_level="pending_real_machine")
    return Response(
        content=json.dumps(
            ok_response(data, request_id=_rid(body.request_id), evidence_level="pending_real_machine",
                        code=0, message="accepted").model_dump(), ensure_ascii=False
        ),
        status_code=status, media_type="application/json",
    )


@router.get("/delivery-jobs/{job_id}")
def get_delivery_job(job_id: str, store: WorkspaceStore = StoreDep):
    """Persistent job state (frontend reads this; never marks success locally)."""
    try:
        data = DeliveryCoordinator(store).get_job(job_id)
    except ProjectNotFoundError:
        return error_response(404, V2ErrorCodes.PROJECT_NOT_FOUND, f"unknown job {job_id!r}",
                              evidence_level="pending_real_machine")
    return ok_response(data, evidence_level=data["evidence_level"])


@router.get("/delivery-jobs/{job_id}/events")
def get_delivery_events(job_id: str, store: WorkspaceStore = StoreDep):
    """SSE stream of the append-only job ledger."""
    try:
        events = DeliveryCoordinator(store).events(job_id)
    except ProjectNotFoundError:
        return error_response(404, V2ErrorCodes.PROJECT_NOT_FOUND, f"unknown job {job_id!r}",
                              evidence_level="pending_real_machine")

    def stream():
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    project_id: str = Query(..., description="exact project binding (never a file path)"),
    job_id: str = Query(..., description="exact owning job (no cross-job archives)"),
    sha256: str = Query("", description="optional exact sha256 binding"),
    store: WorkspaceStore = StoreDep,
):
    """Exact 4-tuple authorisation; no directory scan and no path parameter."""
    artifact_store = ArtifactStore(store)
    try:
        data, meta = artifact_store.download(
            artifact_id, project_id=project_id, job_id=job_id, sha256=sha256
        )
    except ArtifactNotFoundError:
        return error_response(404, V2ErrorCodes.ARTIFACT_NOT_FOUND, f"unknown artifact {artifact_id!r}",
                              evidence_level="pending_real_machine")
    except ArtifactJobMismatchError as exc:
        return error_response(403, V2ErrorCodes.ARTIFACT_JOB_MISMATCH, str(exc),
                              data={"job_id": job_id, "artifact_id": artifact_id},
                              evidence_level="pending_real_machine")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact_id}.zap19"',
            "X-Evidence-Level": str(meta.get("evidence_level") or "pending_real_machine"),
            "X-Artifact-Sha256": str(meta.get("sha256") or ""),
            "X-Artifact-Kind": "native_tia_archive",
        },
    )


@router.get("/projects/{project_id}/source-package")
def get_source_package(project_id: str, store: WorkspaceStore = StoreDep):
    """A-2: offline source import package ZIP — explicitly NOT a native project."""
    missing = _require_project(store, project_id)
    if missing:
        return missing
    gate = DerivationServiceV2(store).validate(project_id)
    if not gate["passed"]:
        return error_response(
            409, V2ErrorCodes.SEMANTIC_VALIDATION_FAILED,
            "SOURCE_READY not reached (static gate failed)",
            data={"issues": gate["issues"]}, evidence_level="offline",
        )
    bundle = DerivationServiceV2(store).derive_all(project_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(bundle.scl_files.items()):
            archive.writestr(path, content)
        archive.writestr(
            "manifest.json",
            json.dumps(bundle.manifest.to_dict(include_content=False), ensure_ascii=False, sort_keys=True),
        )
        archive.writestr(
            "NOTICE.txt",
            "源码包就绪（非原生工程）; SOURCE_READY != NATIVE_ARCHIVED; "
            "this ZIP is an offline source import package, not a TIA .zap19 archive.\n",
        )
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_source_package.zip"',
            "X-Artifact-Kind": "source_import_package_not_native",
            "X-Evidence-Level": "offline",
        },
    )


# --------------------------------------------------------------------------- #
# A-1 / A-3: G0 capability / Brownfield interface-only placeholder
# --------------------------------------------------------------------------- #


@router.get("/capability")
def get_capability(store: WorkspaceStore = StoreDep):
    """G0 TiaCapabilityManifest (real status probe receipt or pending_real_machine)."""
    manifest = store.latest_capability_probe()
    if manifest is None:
        manifest = probe_capability(store=store, write_evidence=True)
    payload = probe_cli_payload(manifest)
    return ok_response(payload, evidence_level=payload["evidence_level"])


@router.post("/projects/{project_id}/brownfield/diffplan")
def post_brownfield_diffplan(project_id: str, body: BrownfieldDiffPlanIn, store: WorkspaceStore = StoreDep):
    """A-3 placeholder: interface + schema + negative rejection ONLY (Q-04).

    This batch performs NO real TIA ADD/MODIFY/DELETE and never emits V19_real.
    """
    missing = _require_project(store, project_id)
    if missing:
        return missing
    forbidden_ops = {"write_f_block", "delete_referenced_block", "modify_original", "apply_to_original"}
    for op in body.ops:
        if str(op.get("op") or "") in forbidden_ops:
            return error_response(
                403, V2ErrorCodes.WRITEBACK_FORBIDDEN,
                "Brownfield real write is out of scope; protected/original blocks stay untouched",
                data={"source_id": str(op.get("source_id") or ""), "reason": "writable=requires_review"},
                request_id=_rid(body.request_id), evidence_level="mocked",
            )
    for binding in body.source_bindings:
        if str(binding.get("block_type") or "").upper() in ("F", "SAFETY", "FB_SAFETY") and binding.get("writable") != "requires_review":
            return error_response(
                403, V2ErrorCodes.WRITEBACK_FORBIDDEN, "F-block is not writable",
                data={"source_id": str(binding.get("source_id") or ""), "reason": "F-block protected"},
                request_id=_rid(body.request_id), evidence_level="mocked",
            )
    return ok_response(
        {
            "plan_id": f"plan_{uuid.uuid4().hex[:12]}",
            "project_id": project_id,
            "executable": False,
            "ops": body.ops,
            "source_bindings": body.source_bindings,
            "impact_closure": [],
            "evidence_level": "mocked",
            "notice": "interface + schema only (WP-05); no real TIA write, no V19_real evidence",
        },
        request_id=_rid(body.request_id), evidence_level="mocked",
    )
