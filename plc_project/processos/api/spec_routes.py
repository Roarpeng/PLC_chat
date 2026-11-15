"""POST /api/processos/projects/from-spec — explicit wizard spec -> project.

The step-orchestration wizard (§b) submits an explicit spec (devices +
authored operations/steps); ``processos.spec_builder`` lowers it to a typed
contract. Fail-closed: any ValueError -> 422 {error}. The 422 body is returned
directly (JSONResponse) so the {error} contract holds even on a bare app that
did not install app.py's exception handlers.

Registration is idempotent (flag on app.state). Services come from
``app.state`` — the store is attached by the host app (app.py's create_app /
tests). Route annotations reference module-level imports only, never closure
variables.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from processos.contract import ProcessContract
from processos.spec_builder import build_contract_from_spec

_SPEC_ROUTES_FLAG = "_spec_routes_registered"


def register_routes(app: FastAPI) -> None:
    """Idempotent registration of the from-spec route (safe to call twice)."""
    if getattr(app.state, _SPEC_ROUTES_FLAG, False):
        return
    setattr(app.state, _SPEC_ROUTES_FLAG, True)

    @app.post("/api/processos/projects/from-spec")
    def create_from_spec(request: Request, body: dict[str, Any]) -> Any:
        spec = dict(body)
        spec.setdefault("id", "PRJ_" + uuid.uuid4().hex[:8].upper())
        try:
            contract = ProcessContract.from_dict(build_contract_from_spec(spec))
            structural = contract.validate_structure()
            if structural:
                raise ValueError("; ".join(structural))
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        state = request.app.state.store.create_project(contract, body.get("profile_id", ""))
        return {"project_id": state.contract.id, "revision": state.revision,
                "profile_id": state.profile_id, "contract": state.contract.to_dict()}
