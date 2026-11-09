"""V2 API envelope and shared request/response schemas (design 5.2).

Compatibility note (audited against the real v1 code): the existing v1
``gateway.app.schemas.common.ApiResponse`` is ``{ok, data, error, request_id}``
and the frontend ``gfRequest`` unwraps exactly those fields. The design prose
calls the envelope ``{code, data, message}``. V2 therefore emits BOTH shapes in
one response: ``ok/data/error/request_id`` (for v1-compatible clients) plus
``code/message/evidence_level`` (design 5.3 examples). No second backend is
created and no v1 signature is changed.
"""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gateway.app.schemas.common import ErrorBody

T = TypeVar("T")

EvidenceLevelLiteral = Literal["offline", "mocked", "V19_real", "pending_real_machine"]


class V2ApiResponse(BaseModel, Generic[T]):
    """Unified V2 envelope (superset of the v1 envelope)."""

    ok: bool = True
    code: int = 0
    data: T | None = None
    message: str = "ok"
    error: ErrorBody | None = None
    evidence_level: EvidenceLevelLiteral = "pending_real_machine"
    request_id: str | None = None


class V2RequestEnvelope(BaseModel):
    """Mandatory fields on every mutating V2 request."""

    project_id: str = ""
    base_revision: int = 0
    request_id: str = ""


def ok_response(
    data: Any,
    *,
    request_id: str = "",
    evidence_level: EvidenceLevelLiteral = "offline",
    code: int = 0,
    message: str = "ok",
) -> V2ApiResponse[dict[str, Any]]:
    """Build a successful V2 envelope."""
    return V2ApiResponse(
        ok=True,
        code=code,
        data=data,
        message=message,
        evidence_level=evidence_level,
        request_id=request_id or None,
    )


def error_response(
    status_code: int,
    error_code: str,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    request_id: str = "",
    evidence_level: EvidenceLevelLiteral = "pending_real_machine",
) -> JSONResponse:
    """Build a failure envelope with the correct HTTP status code."""
    body = V2ApiResponse(
        ok=False,
        code=status_code,
        data=data,
        message=message,
        error=ErrorBody(code=error_code, message=message, details=data),
        evidence_level=evidence_level,
        request_id=request_id or None,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=False))


def envelope_dict(response: V2ApiResponse[Any]) -> dict[str, Any]:
    """Return the plain dict of an envelope (contract-test helper)."""
    return response.model_dump(exclude_none=False)


class EvidenceMixin(BaseModel):
    """Optional evidence fields for responses."""

    evidence_level: EvidenceLevelLiteral = "offline"
    notice: str = ""


class V2ErrorCodes:
    """String constants for design 5.4 error codes."""

    BASE_REVISION_CONFLICT = "BASE_REVISION_CONFLICT"
    BASELINE_HASH_MISMATCH = "BASELINE_HASH_MISMATCH"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    SEMANTIC_VALIDATION_FAILED = "SEMANTIC_VALIDATION_FAILED"
    UNSUPPORTED_PARALLEL_SEMANTICS = "UNSUPPORTED_PARALLEL_SEMANTICS"
    WRITEBACK_FORBIDDEN = "WRITEBACK_FORBIDDEN"
    ARTIFACT_JOB_MISMATCH = "ARTIFACT_JOB_MISMATCH"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    ARCHIVE_MISSING = "ARCHIVE_MISSING"
    TIA_UNAVAILABLE = "TIA_UNAVAILABLE"
    CPU_TEMPLATE_NOT_SELECTED = "CPU_TEMPLATE_NOT_SELECTED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CHANGESET_NOT_APPROVED = "CHANGESET_NOT_APPROVED"
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
