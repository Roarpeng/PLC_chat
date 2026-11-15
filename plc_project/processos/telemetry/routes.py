"""HTTP routes for the telemetry sub-package: FC-15 read-only telemetry events
plus the FC-17 field-modification recovery endpoint. Read-only semantics:
no route may overwrite or delete an already-collected event (原件只读不覆盖).
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from processos.safety.errors import SafetyError, register_safety_exception_handler

from .fieldmods import FieldModificationService
from .service import TelemetryService

_TELEMETRY_FLAG = "_telemetry_routes_registered"
_FIELDMODS_FLAG = "_fieldmods_routes_registered"


def _telemetry_of(app: FastAPI) -> TelemetryService:
    svc = getattr(app.state, "telemetry", None)
    if svc is None:
        svc = TelemetryService()  # PROCESSOS_DB env > default path; short-lived conns
        app.state.telemetry = svc
    return svc


def _fieldmods_of(app: FastAPI) -> FieldModificationService:
    svc = getattr(app.state, "fieldmods", None)
    if svc is None:
        svc = FieldModificationService(
            getattr(app.state, "trace", None),
            baseline_provider=getattr(app.state, "baselines", None),
        )
        app.state.fieldmods = svc
    return svc


def register_routes(app: FastAPI) -> None:
    """Idempotent registration of FC-15 + FC-17 routes."""
    if not getattr(app.state, _TELEMETRY_FLAG, False):
        _register_telemetry_routes(app)
        setattr(app.state, _TELEMETRY_FLAG, True)
    if not getattr(app.state, _FIELDMODS_FLAG, False):
        _register_fieldmods_routes(app)
        setattr(app.state, _FIELDMODS_FLAG, True)
    register_safety_exception_handler(app)


def _register_telemetry_routes(app: FastAPI) -> None:
    telemetry = _telemetry_of(app)

    @app.post("/api/processos/telemetry/events")
    def ingest_event(body: dict[str, Any]) -> dict[str, Any]:
        for field in ("object_id", "source", "event_time"):
            if field not in body:
                raise HTTPException(status_code=422, detail=f"missing required field: {field}")
        try:
            return telemetry.ingest(
                body["object_id"], body["source"], body["event_time"], body.get("payload"),
                quality=body.get("quality"),
            )
        except SafetyError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/processos/objects/{object_id}/telemetry")
    def object_telemetry(object_id: str) -> dict[str, Any]:
        return {"object_id": object_id, "events": telemetry.events_for(object_id)}

    # 刻意不注册 DELETE/PUT/PATCH —— 只读语义（FC-16 验收）。


def _register_fieldmods_routes(app: FastAPI) -> None:
    fieldmods = _fieldmods_of(app)

    @app.post("/api/processos/projects/{pid}/field-modifications")
    def recover_field_modifications(request: Request, pid: str,
                                    body: dict[str, Any]) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is not None and pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        if "field_state" not in body:
            raise HTTPException(status_code=422, detail="missing required field: field_state")
        try:
            return fieldmods.recover(
                pid, body["field_state"],
                captured_at=body.get("captured_at"),
                source=body.get("source", "MANUAL_UPLOAD"),
                b2_manifest=body.get("b2_manifest"),
            )
        except SafetyError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
