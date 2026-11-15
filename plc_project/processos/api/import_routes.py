"""Import Agent (L) HTTP layer — /api/processos/import/* (idempotent mount).

Endpoints:
- POST /api/processos/import/parse          body {project_name, blocks[{name, xml_text, language?}]}
- POST /api/processos/import/claim          body {parse_id, project_id?, mappings[...]}
- POST /api/processos/import/baseline-check body {project_id, block_hashes?}
- GET  /api/processos/import/parses/{parse_id}

``register_routes(app)`` is idempotent (module flag) and creates
``app.state.importer`` only when absent: tests inject their own
``ImportParseService`` over a ``tmp_path`` db first; the real app wires the
trace/baselines services from its own state. SafetyError (PROTECTED claim)
surfaces as ``{error, code, details}`` via the shared handler — 403
SAFETY_SCOPE_BLOCKED is never downgraded. Route annotations reference only
module-level models, never closure variables (``from __future__ import
annotations`` resolves hints through module globals).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from processos.importer.service import ImportParseService
from processos.safety import SafetyError, register_safety_exception_handler

_ROUTES_FLAG = "_import_routes_mounted"


class BlockIn(BaseModel):
    name: str
    xml_text: str
    language: str = ""


class ParseBody(BaseModel):
    project_name: str = ""
    blocks: list[BlockIn] = Field(default_factory=list)


class MappingIn(BaseModel):
    block_name: str
    target_kind: Literal["station", "component", "em", "cm", "ob", "other"]
    station_name: str = ""
    display_name: str = ""
    driver_hint: str = ""


class ClaimBody(BaseModel):
    parse_id: str
    project_id: str = ""
    mappings: list[MappingIn] = Field(default_factory=list)


class BlockHashIn(BaseModel):
    block_name: str
    sha256: str


class BaselineCheckBody(BaseModel):
    project_id: str
    block_hashes: list[BlockHashIn] = Field(default_factory=list)


def register_routes(app: FastAPI) -> None:
    if getattr(app.state, "importer", None) is None:
        db = getattr(app.state, "db_path", None)
        app.state.importer = ImportParseService(
            trace=getattr(app.state, "trace", None),
            # baselines only exists on the app state when persistence is configured
            baselines=getattr(app.state, "baselines", None) if db is not None else None,
            db=db,
        )
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)
    register_safety_exception_handler(app)

    def svc(request: Request) -> ImportParseService:
        return request.app.state.importer

    def require_project(request: Request, pid: str) -> None:
        store = getattr(request.app.state, "store", None)
        if store is not None and pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")

    @app.post("/api/processos/import/parse")
    def post_parse(request: Request, body: ParseBody) -> dict[str, Any]:
        return svc(request).parse(body.project_name,
                                  [b.model_dump() for b in body.blocks])

    @app.post("/api/processos/import/claim")
    def post_claim(request: Request, body: ClaimBody) -> dict[str, Any]:
        if body.project_id:
            require_project(request, body.project_id)
        try:
            return svc(request).claim(body.parse_id, [m.model_dump() for m in body.mappings],
                                      project_id=body.project_id)
        except SafetyError:
            raise  # {error, code, details}; 403 SAFETY_SCOPE_BLOCKED 绝不降级
        except KeyError as exc:
            raise HTTPException(status_code=404,
                                detail=f"unknown parse {body.parse_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/processos/import/baseline-check")
    def post_baseline_check(request: Request, body: BaselineCheckBody) -> dict[str, Any]:
        require_project(request, body.project_id)
        hashes = [h.model_dump() for h in body.block_hashes] or None
        return svc(request).baseline_check(body.project_id, hashes)

    @app.get("/api/processos/import/parses/{parse_id}")
    def get_parse(request: Request, parse_id: str) -> dict[str, Any]:
        doc = svc(request).get_parse(parse_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"unknown parse {parse_id}")
        return doc
