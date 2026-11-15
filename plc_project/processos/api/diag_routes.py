"""HTTP layer for the §1 L-loop diagnostics module (read-level, no RBAC gate).

- POST /api/processos/projects/{pid}/diagnostics/locate
  body ``{"diagnostics": [{block, line?, message}, ...]}`` →
  ``{mappings, unmapped, proposals}``（读级：定位与候选提案只是信息，
  不改变任何工程状态，无门禁）。
- POST /api/processos/projects/{pid}/compile-scope
  body ``{"ops": [...]}`` → ``{mode, affected_blocks, reason, note}``（同上，
  只是建议范围）。

``register_routes(app)`` 幂等；服务缺省时从 ``app.state.trace`` /
``app.state.repair_boundary`` 组装（db 取 ``app.state.db_path``，无则纯内存）。
路由注解不引闭包变量（模块级解析 __globals__），处理器经 ``request.app.state``
取服务。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from processos.diagnostics.service import DiagnosticsLocateService
from processos.repair.service import RepairBoundaryService

_ROUTES_FLAG = "_diagnostics_routes_registered"


def register_routes(app: FastAPI) -> None:
    """幂等挂载诊断定位 / 编译范围路由。"""
    if getattr(app.state, "diagnostics", None) is None:
        repair = getattr(app.state, "repair_boundary", None)
        if repair is None:
            repair = RepairBoundaryService()
        app.state.diagnostics = DiagnosticsLocateService(
            app.state.trace, repair, db=getattr(app.state, "db_path", None))
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)

    @app.post("/api/processos/projects/{pid}/diagnostics/locate")
    def diagnostics_locate(request: Request, pid: str, body: dict[str, Any]) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is not None and pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        diagnostics = body.get("diagnostics")
        if not isinstance(diagnostics, list):
            raise HTTPException(status_code=422,
                                detail="missing required field: diagnostics (list)")
        service: DiagnosticsLocateService = request.app.state.diagnostics
        return service.locate(pid, diagnostics)

    @app.post("/api/processos/projects/{pid}/compile-scope")
    def compile_scope(request: Request, pid: str, body: dict[str, Any]) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is not None and pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        ops = body.get("ops")
        if not isinstance(ops, list):
            raise HTTPException(status_code=422,
                                detail="missing required field: ops (list)")
        service: DiagnosticsLocateService = request.app.state.diagnostics
        return service.compile_scope(pid, ops)
