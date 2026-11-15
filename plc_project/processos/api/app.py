"""FastAPI modular monolith for ProcessOS (blueprint §10, single gateway).

Wraps the project store + evidence passport. The AI/intent layer only proposes
CandidatePatches; approval and native delivery are human-gated. Error mapping:
NotFound->404, RevisionConflict->409, PatchError/StoreError->422, GateBlocked->403.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from processos.contract import Patch, ProcessContract, RevisionConflict
from processos.contract.patch import PatchError
from processos.frameworks import list_profiles

from .store import GateBlocked, NotFound, ProjectStore, StoreError


def create_app(store: ProjectStore | None = None, *, demo_runner: bool = False) -> FastAPI:
    app = FastAPI(title="aiCoPlc ProcessOS", version="0.1.0")
    app.state.store = store or ProjectStore()
    if demo_runner and app.state.store.runner is None:
        from processos.native import make_demo_runner
        app.state.store.runner = make_demo_runner()

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(RevisionConflict)
    async def _conflict(_: Request, exc: RevisionConflict):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(GateBlocked)
    async def _blocked(_: Request, exc: GateBlocked):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(PatchError)
    async def _patch_error(_: Request, exc: PatchError):
        return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.exception_handler(StoreError)
    async def _store_error(_: Request, exc: StoreError):
        return JSONResponse(status_code=422, content={"error": str(exc)})

    def store_of(request: Request) -> ProjectStore:
        return request.app.state.store

    @app.get("/api/processos/frameworks")
    def frameworks():
        return {"profiles": [p.to_dict() for p in list_profiles()]}

    @app.get("/api/processos/projects")
    def list_projects(request: Request):
        store = store_of(request)
        return {"projects": [
            {"project_id": pid, "name": s.contract.name, "revision": s.revision,
             "profile_id": s.profile_id, "steps": len(s.contract.all_steps())}
            for pid, s in store.projects.items()
        ]}

    @app.get("/api/processos/device-catalog")
    def device_catalog():
        from processos.device_catalog import catalog_payload
        return catalog_payload()

    @app.post("/api/processos/projects/from-hardware")
    def from_hardware(request: Request, body: dict[str, Any]):
        from processos.device_catalog import build_contract_from_hardware
        config = dict(body)
        config.setdefault("id", "PRJ_" + uuid.uuid4().hex[:8].upper())
        contract = ProcessContract.from_dict(build_contract_from_hardware(config))
        state = store_of(request).create_project(contract, body.get("profile_id", ""))
        return {"project_id": state.contract.id, "revision": state.revision,
                "profile_id": state.profile_id, "contract": state.contract.to_dict()}

    @app.post("/api/processos/demo")
    def demo(request: Request):
        from processos.contract import clamp_contract
        store = store_of(request)
        c = clamp_contract()
        state = store.projects.get(c.id) or store.create_project(c)
        return {"project_id": state.contract.id, "revision": state.revision,
                "profile_id": state.profile_id, "contract": state.contract.to_dict()}

    @app.post("/api/processos/projects")
    def create_project(request: Request, body: dict[str, Any]):
        contract = ProcessContract.from_dict(body["contract"])
        state = store_of(request).create_project(contract, body.get("profile_id", ""))
        return {"project_id": state.contract.id, "revision": state.revision,
                "profile_id": state.profile_id}

    @app.get("/api/processos/projects/{pid}")
    def get_project(request: Request, pid: str):
        state = store_of(request)._get(pid)
        return {"contract": state.contract.to_dict(), "revision": state.revision,
                "profile_id": state.profile_id}

    @app.post("/api/processos/projects/{pid}/patches")
    def patch(request: Request, pid: str, body: dict[str, Any]):
        p = Patch.from_dict(body)
        state = store_of(request).apply_patch(pid, p)
        return {"revision": state.revision, "contract": state.contract.to_dict()}

    @app.post("/api/processos/projects/{pid}/validate")
    def validate_project(request: Request, pid: str):
        return store_of(request).validate(pid)

    @app.post("/api/processos/projects/{pid}/simulate")
    def simulate(request: Request, pid: str):
        return store_of(request).simulate(pid)

    @app.post("/api/processos/projects/{pid}/generate")
    def generate(request: Request, pid: str):
        return store_of(request).generate(pid)

    @app.post("/api/processos/projects/{pid}/questions/{qid}/resolve")
    def resolve(request: Request, pid: str, qid: str, body: dict[str, Any]):
        state = store_of(request).resolve_question(pid, qid, body["resolution"], body["by"])
        return {"revision": state.revision, "questions": [q.to_dict() for q in state.contract.open_questions]}

    @app.post("/api/processos/projects/{pid}/changesets")
    def freeze(request: Request, pid: str):
        return store_of(request).freeze_changeset(pid)

    @app.post("/api/processos/projects/{pid}/changesets/{csid}/approve")
    def approve(request: Request, pid: str, csid: str, body: dict[str, Any]):
        return store_of(request).approve(pid, csid, body["by"])

    @app.get("/api/processos/projects/{pid}/delivery-gate")
    def gate(request: Request, pid: str):
        return store_of(request).delivery_gate(pid)

    @app.post("/api/processos/projects/{pid}/deliveries")
    def deliver(request: Request, pid: str):
        return store_of(request).create_delivery(pid)

    @app.get("/api/processos/projects/{pid}/passport")
    def passport(request: Request, pid: str):
        state = store_of(request)._get(pid)
        from processos.contract import contract_semantic_hash
        rh = contract_semantic_hash(state.contract)
        return {"revision_hash": rh, "entries": [e.to_dict() for e in store_of(request).passport.for_revision(rh)]}

    return app


app = create_app(demo_runner=True)