"""Shared API envelopes and auth principal."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    ok: bool = True
    data: T | None = None
    error: ErrorBody | None = None
    request_id: str | None = None


class AuthPrincipal(BaseModel):
    subject: str
    workspace_id: str | None = None
    session_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    auth_type: str = "unknown"
