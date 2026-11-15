"""FC-05 · Impact Report — every change ships an explicit impact analysis.

PLAN §3.3: a change without an Impact Report is not a change. The report
derives, from the object-registry graph closure around the subject (and the
patch-op targets), the affected Unit/EM/CM/Step, reverse callers, alarm
definitions, I/O & DB interfaces (SourceMap aggregation), HMI messages,
state-retention risk, online-load impact, regression tests and deployment
notes. Anything underivable stays an explicit ``UNKNOWN``, is recorded in
``unknown_fields`` and blocks high-risk delivery — fail-closed per §12,
never fabricated, never silently guessed.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException, Request
from processos.safety.errors import SafetyError, register_safety_exception_handler
from processos.store.db import JsonDao, open_db, utcnow

UNKNOWN = "UNKNOWN"

#: relations traversed (both directions) to derive the affected closure.
_CLOSURE_RELATIONS = ("part_of", "maps_to", "participates_in")

#: patch-op classification tokens, matched against op/target/path text.
_DB_LAYOUT_TOKENS = ("instance_db", "db_layout", "db_init", "init_db",
                     "retain", "initializ", "memory_layout")
_TIMING_GUARD_TOKENS = ("timeout", "interlock", "guard")

_NAMESPACE = "impact"
_REPORT_KIND = "impact_report"


def _op_text(op: dict[str, Any]) -> str:
    """Raw op/target/path text, original case (ids are case-sensitive)."""
    return " ".join(str(op[k]) for k in ("op", "target", "path") if op.get(k))


def _split_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[/\s.]+", text) if t]


class ImpactReportService:
    """Builds and persists UNKNOWN-blocking impact reports for a change.

    ``trace_provider`` is a TraceabilityService (or duck type) exposing
    ``.registry`` / ``.sourcemap`` / ``.incidents`` and optionally
    ``ids_for(project_id)`` to resolve contract-local patch targets.
    """

    def __init__(self, trace_provider: Any, dao: JsonDao | None = None) -> None:
        self._provider = trace_provider
        self._dao = dao

    # -- provider accessors (duck-typed TraceabilityService) ------------------

    @property
    def registry(self) -> Any:
        return self._provider.registry

    @property
    def sourcemap(self) -> Any:
        return getattr(self._provider, "sourcemap", None)

    @property
    def incidents(self) -> Any:
        return getattr(self._provider, "incidents", None)

    # -- report construction ---------------------------------------------------

    def build(self, project_id: str, *, object_id: str | None = None,
              patch_ops: list[dict[str, Any]] | None = None,
              reason: str = "") -> dict[str, Any]:
        if not object_id and not patch_ops:
            raise ValueError("impact report requires object_id or patch_ops")
        if object_id is not None and not isinstance(object_id, str):
            raise ValueError("object_id must be a string")
        if patch_ops is not None and (
            not isinstance(patch_ops, list) or not patch_ops
            or not all(isinstance(o, dict) for o in patch_ops)
        ):
            raise ValueError("patch_ops must be a non-empty list of op objects")

        reg = self.registry
        subject_obj = reg.get(object_id) if object_id else None
        subject_resolved = subject_obj is not None

        # -- seeds: subject + patch-op id tokens resolvable to registry objects
        ids_for = getattr(self._provider, "ids_for", None)
        ids_map: dict[str, str] = dict(ids_for(project_id)) if callable(ids_for) else {}
        op_texts = [_op_text(op) for op in (patch_ops or [])]
        seeds: set[str] = set()
        if subject_resolved:
            seeds.add(object_id)
        for raw in op_texts:
            for token in _split_tokens(raw):
                target = ids_map.get(token) or (token if reg.get(token) is not None else None)
                if target is not None:
                    seeds.add(target)

        closure = self._closure(seeds)

        lowered = [text.lower() for text in op_texts]
        db_op = any(tok in text for text in lowered for tok in _DB_LAYOUT_TOKENS)
        timing_op = any(tok in text for text in lowered for tok in _TIMING_GUARD_TOKENS)

        unknown_fields: list[str] = []

        # -- affected Unit/EM/CM/Step buckets from the graph closure
        affected: dict[str, list[dict[str, Any]]] = {"units": [], "ems": [], "cms": [], "steps": []}
        bucket_of = {"af_unit": "units", "af_em": "ems", "af_cm": "cms", "behavior_step": "steps"}
        for oid in sorted(closure):
            obj = reg.get(oid)
            bucket = bucket_of.get(obj.kind)
            if bucket:
                affected[bucket].append(
                    {"object_id": oid, "display_name": obj.display_name or oid, "kind": obj.kind})

        # -- callers: objects holding a reverse relation INTO the subject
        callers: list[dict[str, Any]] = []
        if subject_resolved:
            for rel in sorted(reg.relationships(), key=lambda r: (r.from_id, r.relation)):
                if rel.to_id == object_id and rel.from_id != object_id:
                    caller = reg.get(rel.from_id)
                    callers.append({"object_id": rel.from_id,
                                    "display_name": (caller.display_name if caller else None) or rel.from_id,
                                    "relation": rel.relation})

        # -- alarm definitions whose origin object is inside the closure
        inc = self.incidents
        if inc is None:
            alarm_definitions: list[dict[str, Any]] = []
            unknown_fields.append("alarm_definitions")
        else:
            defs = getattr(inc, "_defs", {}) or {}
            alarm_definitions = [d.to_dict() for _, d in sorted(defs.items())
                                 if d.originates_from in closure]
        hmi_messages = [d["description"] for d in alarm_definitions if d.get("description")]

        # -- I/O & DB interfaces: SourceMap aggregation over the closure
        sm = self.sourcemap
        entries = sm.all_entries() if sm is not None else []
        matched = [e for e in entries if e.semantic_object_id in closure]
        if not entries or not matched:
            io_db_interfaces: list[str] = [UNKNOWN]  # no mapping -> UNKNOWN, never empty-invented
            unknown_fields.append("io_db_interfaces")
        else:
            aggregate: set[str] = set()
            for e in matched:
                if e.instance_db:
                    aggregate.add(e.instance_db)
                aggregate.update(e.symbol_refs)
            io_db_interfaces = sorted(aggregate)

        # -- regression tests: registry "test" objects covering a step make it
        #    PLANNED; anything else the closure demands stays UNKNOWN (there is
        #    no test-run evidence to claim).
        planned_by_test: set[str] = set()
        for rel in reg.relationships():
            src = reg.get(rel.from_id)
            if src is not None and src.kind == "test":
                planned_by_test.add(rel.to_id)
        regression_tests: list[dict[str, Any]] = []
        for s in affected["steps"]:
            obj = reg.get(s["object_id"])
            attrs = obj.attributes or {}
            timing_step = bool(attrs.get("timeout_ms")) or bool(attrs.get("interlock"))
            if not (timing_step or attrs.get("is_fault")):
                continue
            regression_tests.append({
                "name": attrs.get("step") or obj.display_name or obj.object_id,
                "status": "PLANNED" if obj.object_id in planned_by_test else UNKNOWN,
            })
        if timing_op and not regression_tests:
            first = patch_ops[0] if patch_ops else {}
            regression_tests.append({"name": str(first.get("target") or first.get("path") or "patch"),
                                     "status": UNKNOWN})
        regression_unknown = any(r["status"] == UNKNOWN for r in regression_tests)
        if regression_unknown:
            unknown_fields.append("regression_tests")

        # -- state retention / online load
        if patch_ops:
            state_risk = "HIGH" if db_op else "LOW"
        elif subject_resolved:
            state_risk = "NONE"  # query-only report: no change proposed
        else:
            state_risk = UNKNOWN  # unknown object, nothing analyzable
            unknown_fields.append("state_retention_risk")

        if not patch_ops:
            online = "NONE"
        elif io_db_interfaces == [UNKNOWN]:
            online = UNKNOWN  # no SourceMap coverage -> reload scope unknown
            unknown_fields.append("online_load_impact")
        else:
            online = "RELOAD_REQUIRED"

        # -- blocking rule (fail-closed): unknown retention/load risk, or a
        #    timeout/interlock-relevant closure without confirmed regression.
        timing_in_closure = timing_op or any(
            bool((reg.get(s["object_id"]).attributes or {}).get("timeout_ms"))
            or bool((reg.get(s["object_id"]).attributes or {}).get("interlock"))
            for s in affected["steps"])
        blocked = (state_risk == UNKNOWN or online == UNKNOWN
                   or (timing_in_closure and regression_unknown))

        # -- deployment notes (human-readable, code-referenced)
        notes: list[str] = []
        if object_id and not subject_resolved:
            notes.append(f"subject {object_id} 未在对象注册表解析（UNKNOWN）：无法确认影响范围，阻断高风险交付。")
        if state_risk == "HIGH":
            notes.append("RETAIN_DATA_RISK：补丁含 DB 布局/初始化类操作，须独立数据保持评估并人工批准后才能上线。")
        elif state_risk == "LOW":
            notes.append("补丁触及运行行为（超时/互锁/看护或其它语义）：上线前确认保持性数据与复位行为不受影响。")
        elif state_risk == UNKNOWN:
            notes.append("状态保持风险 UNKNOWN：无法分析，阻断高风险交付。")
        if online == "RELOAD_REQUIRED":
            notes.append("在线加载影响 RELOAD_REQUIRED：重新生成并重载受影响块；下载工程 ≠ 现场部署。")
        elif online == UNKNOWN:
            notes.append("在线加载影响 UNKNOWN：缺少 SourceMap 覆盖，无法确定重载范围。")
        if regression_unknown:
            notes.append("回归测试状态 UNKNOWN：完成回归验证并复扫影响报告前，阻断高风险交付。")
        if io_db_interfaces == [UNKNOWN]:
            notes.append("I/O/DB 接口 UNKNOWN：无 SourceMap，不得据此声称接口已核对。")
        if not closure:
            notes.append("影响闭包为空：受影响对象/调用者/报警定义均不可推导（见 unknown_fields）。")

        if not closure:
            unknown_fields.extend(["affected", "callers", "alarm_definitions", "hmi_messages"])

        report = {
            "report_id": "imp_" + uuid.uuid4().hex[:8],
            "project_id": project_id,
            "generated_at": utcnow(),
            "subject": {
                "object_id": object_id or UNKNOWN,
                "display_name": subject_obj.display_name if subject_resolved else UNKNOWN,
                "reason": reason,
            },
            "affected": affected,
            "callers": callers,
            "alarm_definitions": alarm_definitions,
            "io_db_interfaces": io_db_interfaces,
            "hmi_messages": hmi_messages,
            "state_retention_risk": state_risk,
            "online_load_impact": online,
            "regression_tests": regression_tests,
            "deployment_notes": notes,
            "unknown_fields": list(dict.fromkeys(unknown_fields)),
            "blocked_high_risk_delivery": blocked,
        }
        self._persist(report)
        return report

    def _closure(self, seeds: set[str]) -> set[str]:
        """BFS over part_of/maps_to/participates_in (both directions)."""
        reg = self.registry
        seen: set[str] = set()
        frontier = [s for s in seeds if reg.get(s) is not None]
        while frontier:
            oid = frontier.pop()
            if oid in seen:
                continue
            seen.add(oid)
            for rel in _CLOSURE_RELATIONS:
                for neighbor in reg.neighbors(oid, rel, "both"):
                    if neighbor.object_id not in seen:
                        frontier.append(neighbor.object_id)
        return seen

    # -- persistence (JsonDao namespace "impact") ------------------------------

    def _dao_session(self) -> tuple[JsonDao, Any | None]:
        """Return (dao, owned_connection); the owned conn is closed per call."""
        if self._dao is not None:
            return self._dao, None
        conn = open_db()  # explicit/env location (PROCESSOS_DB); never in unit tests without it
        return JsonDao(conn, _NAMESPACE), conn

    def _persist(self, report: dict[str, Any]) -> None:
        dao, conn = self._dao_session()
        try:
            dao.put(report["report_id"], _REPORT_KIND, report)
        finally:
            if conn is not None:
                conn.close()

    def get(self, report_id: str) -> dict[str, Any] | None:
        dao, conn = self._dao_session()
        try:
            row = dao.get(report_id)
        finally:
            if conn is not None:
                conn.close()
        if row is None:
            return None
        row.pop("id", None)
        row.pop("kind", None)
        return row


def register_routes(app: Any) -> None:
    """Attach FC-05 impact routes + the safety error handler (idempotent).

    Safe to call on any FastAPI app: the trace provider comes from
    ``app.state.trace`` (lazily created if missing) and the project store from
    ``app.state.store`` — create_app itself is never modified here.
    """
    if getattr(app.state, "impact_routes_registered", False):
        return
    app.state.impact_routes_registered = True
    register_safety_exception_handler(app)

    def service_of(request: Request) -> ImpactReportService:
        state = request.app.state
        trace = getattr(state, "trace", None)
        if trace is None:
            from processos.traceability import TraceabilityService
            trace = TraceabilityService()
            state.trace = trace
        service = getattr(state, "impact", None)
        if service is None:
            service = ImpactReportService(trace)
            state.impact = service
        return service

    @app.post("/api/processos/projects/{pid}/impact")
    def create_impact_report(request: Request, pid: str, body: dict[str, Any]) -> dict[str, Any]:
        store = getattr(request.app.state, "store", None)
        if store is None or pid not in getattr(store, "projects", {}):
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")
        try:
            return service_of(request).build(
                pid,
                object_id=body.get("object_id"),
                patch_ops=body.get("patch_ops"),
                reason=str(body.get("reason") or ""),
            )
        except SafetyError:
            raise  # mapped by register_safety_exception_handler -> {error, code, details}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/processos/impact/{report_id}")
    def get_impact_report(request: Request, report_id: str) -> dict[str, Any]:
        report = service_of(request).get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"unknown impact report {report_id}")
        return report
