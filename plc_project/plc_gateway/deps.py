"""FastAPI dependency injection helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from gateway.app.config import Settings, get_settings
from gateway.app.schemas.common import AuthPrincipal


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


RequestIdDep = Annotated[str, Depends(get_request_id)]


async def get_principal(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthPrincipal:
    """Resolve caller from Bearer JWT or API key (dev stub)."""
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if not token:
        if settings.is_dev:
            return AuthPrincipal(
                subject="usr_dev",
                workspace_id="ws_dev",
                session_id="ses_dev",
                scopes=["research:write", "knowledge:write", "knowledge:read"],
                auth_type="dev_anonymous",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_MISSING", "message": "Missing credentials"},
        )

    if settings.auth_api_keys_enabled and (
        token == settings.dev_api_key or token.startswith("ros_ak_")
    ):
        return AuthPrincipal(
            subject="usr_api_key",
            workspace_id="ws_dev",
            session_id=None,
            scopes=["research:write", "knowledge:write", "knowledge:read"],
            auth_type="api_key",
        )

    # Stub JWT: accept any non-empty token in dev; validate signature later.
    if settings.is_dev:
        return AuthPrincipal(
            subject="usr_jwt_stub",
            workspace_id="ws_dev",
            session_id="ses_stub",
            scopes=["research:write", "knowledge:write", "knowledge:read"],
            auth_type="jwt",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_INVALID_TOKEN", "message": "Invalid token"},
    )


PrincipalDep = Annotated[AuthPrincipal, Depends(get_principal)]


def get_runtime_client(request: Request):
    return request.app.state.runtime_client
