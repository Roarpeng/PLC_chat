"""HTTP routes for the FC-14 commissioning ledger.

Pattern shared by the three field-side sub-packages (commissioning /
telemetry / deployment): ``register_routes(app)`` is idempotent, hangs the
service on ``app.state`` only when missing (tests pre-inject a service bound
to a tmp_path store), tolerates a missing ``app.state.store``/``app.state.trace``
(404 only where a route actually depends on them), and always wires the
fail-closed SafetyError -> JSON handler. Services are constructed with a db
*path* (or None -> env/default) and open short-lived connections per
operation, so nothing here holds a persistent sqlite handle.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from processos.safety.errors import SafetyError, register_safety_exception_handler

from .service import CommissioningLedger

_ROUTES_FLAG = "_commissioning_routes_registered"
_SERVICE_ATTR = "commissioning"

_REQUIRED_FIELDS = ("project_id", "build_id", "artifact_sha256", "device_id", "operator")


def _ledger_of(app: FastAPI) -> CommissioningLedger:
    ledger = getattr(app.state, _SERVICE_ATTR, None)
    if ledger is None:
        ledger = CommissioningLedger()  # PROCESSOS_DB env > default path
        setattr(app.state, _SERVICE_ATTR, ledger)
    return ledger


def register_routes(app: FastAPI) -> None:
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    ledger = _ledger_of(app)
    register_safety_exception_handler(app)

    @app.post("/api/processos/deployments/records")
    def create_record(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        for field in _REQUIRED_FIELDS:
            if field not in body:
                raise HTTPException(status_code=422, detail=f"missing required field: {field}")
        store = getattr(request.app.state, "store", None)
        if store is not None and body["project_id"] not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {body['project_id']}")
        try:
            return ledger.record(
                body["project_id"], body["build_id"], body["artifact_sha256"],
                body["device_id"], body["operator"],
                plc_checksum=body.get("plc_checksum", ""),
                commissioned_at=body.get("commissioned_at"),
                tests=body.get("tests"),
                result=body.get("result", "COMMISSIONED"),
            )
        except SafetyError:
            raise  # SafetyError subclasses ValueError; keep fail-closed mapping
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/processos/deployments/records")
    def list_records(project_id: str) -> dict[str, Any]:
        return {"records": ledger.records_for(project_id)}

    setattr(app.state, _ROUTES_FLAG, True)
