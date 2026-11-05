"""Greenfield 通道独立 APIRouter（T05）。

前缀 ``/api/v1/plc/canvas/greenfield``；与既有 ``plc.router`` 完全隔离，
不注册进 smartRoute 七 tab、不产生 canvas ops、不建 PCEC 事务、
不触碰 §2.3 存量重构链与回写链。所有响应统一 ``ApiResponse`` 信封。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gateway.app.schemas.common import ApiResponse, ErrorBody
from gateway.app.services.plc import greenfield_service as svc
from plc_engine.af.greenfield_ports import GreenfieldError

router = APIRouter(prefix="/api/v1/plc/canvas/greenfield", tags=["greenfield"])


def _rid() -> str:
    return uuid.uuid4().hex[:12]


def _ok(data: Any) -> ApiResponse[dict[str, Any]]:
    return ApiResponse(ok=True, data=data, request_id=_rid())


def _error_status(code: str) -> int:
    """§3.8 错误码映射：门禁/不可变 409，连线/投影 422，其余 400。"""
    if code.startswith("GF_GATE") or code.startswith("GF_SPEC_IMMUTABLE"):
        return 409
    if code.startswith("GF_EDGE") or code.startswith("GF_VIEW"):
        return 422
    return 400


def _fail(exc: GreenfieldError) -> JSONResponse:
    """统一 ApiResponse 信封 + 正确 HTTP 语义状态码。"""
    body = ApiResponse(
        ok=False,
        data=None,
        error=ErrorBody(**exc.to_dict()),
        request_id=_rid(),
    )
    return JSONResponse(status_code=_error_status(exc.code), content=body.model_dump())


class SessionIn(BaseModel):
    session_id: str | None = None


class UploadIn(SessionIn):
    items: list[dict[str, Any]] = Field(default_factory=list)


class DraftIn(SessionIn):
    prompt: str = ""
    project_name: str = "AssemblyCell"


class LinkIn(SessionIn):
    op: str = "add_edge"
    edge: dict[str, Any] | None = None
    edge_id: str | None = None
    src_id: str = ""
    dst_id: str = ""
    field_path: str = ""
    value: Any = None


class ConfirmIn(SessionIn):
    explicit: bool = False
    frozen_by: str = "user"


class DraftImportIn(SessionIn):
    payload: dict[str, Any] = Field(default_factory=dict)


def _session(session_id: str | None):
    return svc.session_for(session_id)


@router.get("/state")
def get_state(session_id: str | None = None) -> ApiResponse[dict[str, Any]]:
    return _ok(svc.state_payload(_session(session_id)))


@router.get("/whitelist")
def get_whitelist() -> ApiResponse[dict[str, Any]]:
    return _ok(svc.whitelist_payload())


@router.post("/upload")
def upload(body: UploadIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"receipt": svc.upload(_session(body.session_id), body.items)})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/receipt/confirm")
def receipt_confirm(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"contract": svc.confirm_receipt_action(_session(body.session_id))})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/draft")
def create_draft(body: DraftIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.draft_from_prompt(_session(body.session_id), body.prompt, body.project_name))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/links")
def apply_link(body: LinkIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        payload = body.model_dump(exclude={"session_id"})
        return _ok(svc.apply_link_patch(_session(body.session_id), payload))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/validate")
def validate(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.revalidate(_session(body.session_id)))
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/views")
def views(session_id: str | None = None) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.get_views(_session(session_id)))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/engineering-summary")
def engineering_summary(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    return _ok(svc.engineering_summary(_session(body.session_id)))


@router.post("/confirm")
def confirm(body: ConfirmIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(
            svc.confirm_and_freeze(
                _session(body.session_id),
                explicit=body.explicit,
                frozen_by=body.frozen_by,
            )
        )
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/begin-edit")
def begin_edit(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.begin_edit(_session(body.session_id)))
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/export/mermaid")
def export_mermaid(session_id: str | None = None) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"markdown": svc.export_first_mermaid(_session(session_id))})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/draft/export")
def export_draft(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    return _ok({"payload": _session(body.session_id).export_draft()})


@router.post("/draft/import")
def import_draft(body: DraftImportIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    session = _session(body.session_id)
    try:
        session.import_draft(body.payload)
        return _ok(svc.state_payload(session))
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/specs/{version}")
def get_spec(version: int, session_id: str | None = None) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"spec": svc.load_frozen_spec(session_id or "", version).to_dict()})
    except GreenfieldError as exc:
        return _fail(exc)
    except (OSError, KeyError, ValueError) as exc:
        return ApiResponse(
            ok=False,
            error=ErrorBody(code="GF_SPEC_NOT_FOUND", message=str(exc)),
            request_id=_rid(),
        )
