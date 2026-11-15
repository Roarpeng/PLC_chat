"""PLAN §7 · 交接完成条件校验器 (HandoverReadinessService + routes).

交接完成五条件（PLAN §7 原文 → 条件 id）：

1. ``CURRENT_DEPLOYED_VERSION_KNOWN``  当前已部署版本明确 —— baselines compare 的
   latest_b3 存在且 status=VERIFIED（SELF_REPORTED 不算，B3 不能仅凭 Build ID 自报）。
2. ``OPEN_ITEMS_HAVE_OWNERS``  未关闭故障和未完成变更有负责人 —— 范围内
   status ∉ {RESOLVED, CLOSED} 的 incidents，handover.owner 必须非空（UNKNOWN 视为无）。
3. ``FIELD_DEVIATIONS_MARKED``  已知现场偏差已标明 —— fieldmods（FC-17）的
   managed native overrides 中未确认漂移为 0；无服务 → UNKNOWN。
4. ``ROLLBACK_ARTIFACT_ARCHIVED``  回退工程已归档 —— 存在已验证 B2（可回退）。
5. ``CONCLUSIONS_TRACEABLE``  最新调试结论可追溯 —— 范围内 incidents 的
   triage.fact 非空。

``ready`` 只有在**全部**条件 ``satisfied is True`` 时才为 True；任何 ``None``
（取不到证据）或 ``False``（明确不满足）都判 False。绝不伪造：取不到就
``satisfied=None`` + ``evidence="UNKNOWN..."``（PLAN §6.1/§12）。

范围：``incident_id=``（单问题单）或 ``project_id=``（项目全部）。项目范围的
incident 归属按 ``software.deployed_build_id → registry build(attributes.project)``
确定性归因；无法归因的 incident 不计入该项目（规则写入 scope 说明，不猜）。

``commissioning`` 参数按规格保留：当前五条件均不需要其证据，未使用、不伪造。

Persistence：``db`` 给定时把 readiness 快照写 namespace ``"handover_readiness"``
（短命连接 + RLock）；``db=None`` 纯内存（no-db 应用不触碰默认 SQLite 路径）。
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from processos.store.db import JsonDao, open_db, utcnow

NAMESPACE = "handover_readiness"

UNKNOWN = "UNKNOWN"

#: 已关闭状态（这些 incident 不再要求 owner 在位）。
_CLOSED_STATUSES = frozenset({"RESOLVED", "CLOSED"})

CONDITIONS: tuple[tuple[str, str], ...] = (
    ("CURRENT_DEPLOYED_VERSION_KNOWN", "当前已部署版本明确（B3 现场 VERIFIED）"),
    ("OPEN_ITEMS_HAVE_OWNERS", "未关闭故障和未完成变更有负责人"),
    ("FIELD_DEVIATIONS_MARKED", "已知现场偏差、临时旁路与风险已标明"),
    ("ROLLBACK_ARTIFACT_ARCHIVED", "回退工程与现场前置条件已归档（存在已验证 B2）"),
    ("CONCLUSIONS_TRACEABLE", "最新调试结论可追溯到对象和时间（triage.fact 非空）"),
)

_ROUTES_FLAG = "_handover_readiness_routes_registered"

ATTRIBUTION_RULE = ("incident.software.deployed_build_id -> registry build(attributes.project)"
                    " 确定性归因；无法归因的 incident 不计入该项目范围")


def _cond(cid: str, satisfied: bool | None, evidence: str) -> dict[str, Any]:
    description = next((d for i, d in CONDITIONS if i == cid), "")
    return {"id": cid, "description": description, "satisfied": satisfied, "evidence": evidence}


class HandoverReadinessService:
    """§7 交接完成条件校验：五条件逐项判定，证据取不到就是 UNKNOWN，不伪造。"""

    def __init__(self, trace: Any, baselines: Any = None, commissioning: Any = None,
                 fieldmods: Any = None, db: Any = None) -> None:
        if isinstance(db, sqlite3.Connection):
            raise TypeError(
                "HandoverReadinessService 需要数据库路径（或 None 走纯内存），不接受常驻连接："
                "FastAPI 同步路由在线程池线程中使用会触发 sqlite 跨线程错误")
        self._trace = trace
        self._baselines = baselines
        self._commissioning = commissioning  # 按规格保留；当前五条件未用（不伪造证据）
        self._fieldmods = fieldmods
        #: db=None -> 纯内存（no-db 应用不触碰默认 SQLite 路径）。
        self._db: str | None = None if db is None else str(db)
        self._lock = threading.RLock()
        self._mem: list[dict[str, Any]] = []

    # ---------- public API ----------

    def readiness(self, incident_id: str | None = None,
                  project_id: str | None = None) -> dict[str, Any]:
        """五条件逐项校验（``incident_id``/``project_id`` 二选一）。"""
        if bool(incident_id) == bool(project_id):
            raise ValueError("readiness 需要 incident_id 或 project_id 之一（且只一个）")
        incidents_service = getattr(self._trace, "incidents", None)
        registry = getattr(self._trace, "registry", None)

        if incident_id is not None:
            inc = incidents_service.get(incident_id) if incidents_service else None
            if inc is None:
                raise ValueError(f"unknown incident {incident_id}")
            scope = [inc]
            scope_project = self._project_for_incident(inc)
        else:
            assert project_id is not None
            scope = self._incidents_for_project(incidents_service, registry, project_id)
            scope_project = project_id

        conditions = [
            self._check_deployed_version(scope_project),
            self._check_open_items_have_owners(scope),
            self._check_field_deviations(scope_project),
            self._check_rollback_artifact(scope_project),
            self._check_conclusions_traceable(scope),
        ]
        result: dict[str, Any] = {
            "ready": all(c["satisfied"] is True for c in conditions),
            "conditions": conditions,
            "checked_at": utcnow(),
            "scope": {
                "incident_id": incident_id,
                "project_id": project_id,
                "incidents": [i.incident_id for i in scope],
                "resolved_project": scope_project or UNKNOWN,
                "attribution_rule": ATTRIBUTION_RULE,
            },
        }
        self._persist_snapshot(result)
        return result

    def snapshots_for(self, project_id: str) -> list[dict[str, Any]]:
        """项目历史 readiness 快照（交接台账）。"""
        if self._db is None:
            with self._lock:
                rows = list(self._mem)
        else:
            with contextlib.closing(open_db(self._db)) as conn:
                rows = JsonDao(conn, NAMESPACE).list_by_kind("readiness_snapshot")
        def _scope_project(row: dict[str, Any]) -> str | None:
            # project 范围快照记 scope.project_id；incident 范围快照靠归因结果。
            scope = row.get("scope") or {}
            return scope.get("project_id") or scope.get("resolved_project")

        out = [{k: v for k, v in r.items() if k not in ("id", "kind")}
               for r in rows if _scope_project(r) == project_id]
        out.sort(key=lambda r: (r.get("checked_at") or "", r.get("snapshot_id") or ""))
        return out

    # ---------- 范围解析 ----------

    def _project_for_incident(self, incident: Any) -> str | None:
        """incident → project（经 deployed build 的注册表属性确定性归因）。"""
        build_id = str((incident.software or {}).get("deployed_build_id", "") or "")
        if not build_id or self._trace is None:
            return None
        registry = getattr(self._trace, "registry", None)
        if registry is None:
            return None
        for build in registry.by_kind("build"):
            if build.display_name == build_id:
                project = str((build.attributes or {}).get("project", "") or "")
                return project or None
        return None

    def _incidents_for_project(self, incidents_service: Any, registry: Any,
                               project_id: str) -> list[Any]:
        """项目范围内的 incidents（确定性归因，规则见 ATTRIBUTION_RULE）。"""
        if incidents_service is None:
            return []
        build_ids: set[str] = set()
        if registry is not None:
            for build in registry.by_kind("build"):
                if str((build.attributes or {}).get("project", "") or "") == project_id:
                    build_ids.add(build.display_name)
        return [i for i in incidents_service.all_incidents()
                if str((i.software or {}).get("deployed_build_id", "") or "") in build_ids]

    # ---------- 五条件 ----------

    def _check_deployed_version(self, project_id: str | None) -> dict[str, Any]:
        if self._baselines is None:
            return _cond("CURRENT_DEPLOYED_VERSION_KNOWN", None,
                         f"{UNKNOWN}: baselines 服务不可用，无法证明已部署版本")
        if project_id is None:
            return _cond("CURRENT_DEPLOYED_VERSION_KNOWN", None,
                         f"{UNKNOWN}: 无法将范围确定性归因到项目（无 deployed build 绑定）")
        try:
            compare = self._baselines.compare(project_id)
        except Exception:
            return _cond("CURRENT_DEPLOYED_VERSION_KNOWN", None,
                         f"{UNKNOWN}: baselines 查询失败（fail-closed，不猜）")
        b3 = compare.get("latest_b3")
        if b3 is None:
            return _cond("CURRENT_DEPLOYED_VERSION_KNOWN", False,
                         "无 B3 已部署基线记录：现场运行版本未知")
        if b3.get("status") != "VERIFIED":
            return _cond("CURRENT_DEPLOYED_VERSION_KNOWN", False,
                         f"B3 {b3.get('deployed_build_id', UNKNOWN)} 为 "
                         f"{b3.get('status', UNKNOWN)}（Build ID 自报不等于现场验证）")
        return _cond("CURRENT_DEPLOYED_VERSION_KNOWN", True,
                     f"B3 {b3.get('deployed_build_id', UNKNOWN)} 现场 VERIFIED"
                     f"（verification={b3.get('verification', UNKNOWN)}）")

    @staticmethod
    def _check_open_items_have_owners(scope: list[Any]) -> dict[str, Any]:
        open_items = [i for i in scope
                      if str((i.handover or {}).get("status", "") or "").upper()
                      not in _CLOSED_STATUSES]
        missing = [i.incident_id for i in open_items
                   if not str((i.handover or {}).get("owner", "") or "").strip()
                   or str((i.handover or {}).get("owner", "")).strip().upper() == UNKNOWN]
        if missing:
            return _cond("OPEN_ITEMS_HAVE_OWNERS", False,
                         f"未关闭问题缺少负责人: {', '.join(missing)}")
        n = len(open_items)
        return _cond("OPEN_ITEMS_HAVE_OWNERS", True,
                     f"{n} 个未关闭问题全部有负责人" if n else "范围内无未关闭问题")

    def _check_field_deviations(self, project_id: str | None) -> dict[str, Any]:
        if self._fieldmods is None:
            return _cond("FIELD_DEVIATIONS_MARKED", None,
                         f"{UNKNOWN}: fieldmods 服务不可用，无法证明无未确认漂移")
        if project_id is None:
            return _cond("FIELD_DEVIATIONS_MARKED", None,
                         f"{UNKNOWN}: 无法将范围确定性归因到项目（无 deployed build 绑定）")
        try:
            overrides = self._fieldmods.overrides_for(project_id)
        except Exception:
            return _cond("FIELD_DEVIATIONS_MARKED", None,
                         f"{UNKNOWN}: fieldmods 查询失败（fail-closed，不猜）")
        # FC-17 override 尚无「已确认」字段——未确认即视为未处理漂移（保守）。
        unconfirmed = [o for o in overrides if not o.get("confirmed")]
        blocks = ", ".join(str(o.get("block_name", UNKNOWN)) for o in unconfirmed) or "无"
        return _cond("FIELD_DEVIATIONS_MARKED", not unconfirmed,
                     f"{len(unconfirmed)} 个未确认现场漂移（块: {blocks}）"
                     if unconfirmed else "0 个未确认现场漂移（overrides 均已确认或不存在）")

    def _check_rollback_artifact(self, project_id: str | None) -> dict[str, Any]:
        if self._baselines is None:
            return _cond("ROLLBACK_ARTIFACT_ARCHIVED", None,
                         f"{UNKNOWN}: baselines 服务不可用，无法证明存在可回退 B2")
        if project_id is None:
            return _cond("ROLLBACK_ARTIFACT_ARCHIVED", None,
                         f"{UNKNOWN}: 无法将范围确定性归因到项目（无 deployed build 绑定）")
        try:
            compare = self._baselines.compare(project_id)
        except Exception:
            return _cond("ROLLBACK_ARTIFACT_ARCHIVED", None,
                         f"{UNKNOWN}: baselines 查询失败（fail-closed，不猜）")
        b2 = compare.get("latest_b2")
        if b2 is None:
            return _cond("ROLLBACK_ARTIFACT_ARCHIVED", False,
                         "无 B2 原生基线归档：回退工程不可用")
        return _cond("ROLLBACK_ARTIFACT_ARCHIVED", True,
                     f"B2 {b2.get('build_id', UNKNOWN)} 已归档 "
                     f"(sha256 {str(b2.get('archive_sha256', ''))[:12]}…，可回退)")

    @staticmethod
    def _check_conclusions_traceable(scope: list[Any]) -> dict[str, Any]:
        missing = [i.incident_id for i in scope
                   if not str((i.triage or {}).get("fact", "") or "").strip()]
        if missing:
            return _cond("CONCLUSIONS_TRACEABLE", False,
                         f"缺少可追溯结论（triage.fact 为空）: {', '.join(missing)}")
        n = len(scope)
        return _cond("CONCLUSIONS_TRACEABLE", True,
                     f"{n} 个问题单均有 triage.fact 结论" if n else "范围内无问题单")

    # ---------- persistence ----------

    def _persist_snapshot(self, result: dict[str, Any]) -> None:
        snapshot_id = "hr_" + uuid.uuid4().hex[:8]
        snapshot = {"snapshot_id": snapshot_id, **result}
        if self._db is None:
            with self._lock:
                self._mem.append(snapshot)
            return
        with self._lock, contextlib.closing(open_db(self._db)) as conn:
            JsonDao(conn, NAMESPACE).put(snapshot_id, "readiness_snapshot", snapshot)


# ---------- HTTP layer ----------

def register_routes(app: FastAPI) -> None:
    """幂等挂载交接就绪路由（只读，任意角色可查——incident.read 对全员开放）。

    - GET /api/processos/incidents/{incident_id}/handover/readiness
    - GET /api/processos/projects/{pid}/handover/readiness
    """
    if getattr(app.state, "handover_readiness", None) is None:
        app.state.handover_readiness = HandoverReadinessService(
            getattr(app.state, "trace", None),
            baselines=getattr(app.state, "baselines", None),
            commissioning=getattr(app.state, "commissioning", None),
            fieldmods=getattr(app.state, "fieldmods", None),
        )
    service: HandoverReadinessService = app.state.handover_readiness
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)

    @app.get("/api/processos/incidents/{incident_id}/handover/readiness")
    def incident_handover_readiness(request: Request, incident_id: str) -> dict[str, Any]:
        incidents = getattr(request.app.state.trace, "incidents", None)
        if incidents is None or incidents.get(incident_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown incident {incident_id}")
        try:
            return service.readiness(incident_id=incident_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/processos/projects/{pid}/handover/readiness")
    def project_handover_readiness(request: Request, pid: str) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is not None and pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        try:
            return service.readiness(project_id=pid)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
