"""HTTP routes for the FC-18 site deployment gateway.

Fail-closed: precheck validates conditions server-side; execute requires an
existing ready precheck + explicit human confirm, and refuses (501
SAFETY_SCOPE_BLOCKED) when no real execution backend is configured. There is
deliberately no one-click online path (PLAN §5.3).
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from processos.safety.errors import SafetyError, register_safety_exception_handler

from .gateway import PrecheckNotFound, SiteDeploymentGateway

_ROUTES_FLAG = "_deployment_routes_registered"


def _gateway_of(app: FastAPI) -> SiteDeploymentGateway:
    gw = getattr(app.state, "deploy_gateway", None)
    if gw is None:
        gw = SiteDeploymentGateway(
            None,  # 生产默认：无真实执行后端 -> execute 501 SAFETY_SCOPE_BLOCKED
            baseline_provider=getattr(app.state, "baselines", None),
            commissioning=getattr(app.state, "commissioning", None),
        )
        app.state.deploy_gateway = gw
    return gw


def register_routes(app: FastAPI) -> None:
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    gateway = _gateway_of(app)
    register_safety_exception_handler(app)

    @app.post("/api/processos/deployments/gateway/precheck")
    def gateway_precheck(body: dict[str, Any]) -> dict[str, Any]:
        for field in ("project_id", "build_id", "device_id"):
            if not str(body.get(field, "") or "").strip():
                raise HTTPException(status_code=422, detail=f"missing required field: {field}")
        return gateway.precheck(
            body["project_id"], body["build_id"], body["device_id"], body.get("window", ""),
            online_compare=body.get("online_compare"),
            retain_assessment=body.get("retain_assessment"),
            second_person=body.get("second_person"),
            rollback_plan=body.get("rollback_plan"),
            authorized_window=bool(body.get("authorized_window", False)),
        )

    @app.post("/api/processos/deployments/gateway/execute")
    def gateway_execute(body: dict[str, Any]) -> dict[str, Any]:
        precheck_id = str(body.get("precheck_id", "") or "")
        if not precheck_id:
            raise HTTPException(status_code=422, detail="missing required field: precheck_id")
        try:
            return gateway.execute(
                precheck_id,
                confirm=body.get("confirm", False),
                actor=body.get("actor", ""),
            )
        except PrecheckNotFound:
            raise HTTPException(status_code=404, detail=f"unknown precheck {precheck_id}") from None
        # SafetyError 由 register_safety_exception_handler 统一映射
        # （403 需人工确认/预检未通过；501 无真实执行后端），绝不降级。

    setattr(app.state, _ROUTES_FLAG, True)
