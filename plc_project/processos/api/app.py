"""FastAPI modular monolith for ProcessOS (blueprint §10, single gateway).

Wraps the project store + evidence passport and mounts the wave-1 field
modules in a fixed order: rbac -> baselines -> impact -> commissioning ->
telemetry (incl. fieldmods) -> deployment (after commissioning, so the gateway
sees the ledger) -> artifacts. The AI/intent layer only proposes
CandidatePatches; approval and native delivery are human-gated.

Error mapping: NotFound->404, RevisionConflict->409, PatchError/StoreError->422,
GateBlocked->403, SafetyError->{error, code, details} (registered by the
modules). HTTPException bodies are flattened to the same ``{error, ...}``
contract so the web workbench can read machine codes; 403s are audited via
``rbac.audit_forbidden`` (module-owned hook, see its docstring).
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Annotated, Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from processos.contract import Patch, ProcessContract, RevisionConflict, contract_spec_hash
from processos.contract.patch import PatchError
from processos.frameworks import get_profile, list_profiles, register_hr001_af_v19
from processos.impact.service import ImpactReportService
from processos.locks import ProjectLockManager
from processos.rbac import (
    PERMISSIONS,
    Actor,
    assert_approver_separation,
    audit_forbidden,
    get_actor,
    require_role,
)
from processos.store.db import JsonDao, open_db, utcnow
from processos.traceability import TraceabilityService

from .store import GateBlocked, NotFound, ProjectStore, StoreError


class _MemoryAuditLog:
    """Pure-memory audit ledger for no-db apps (tests / ephemeral runs).

    Duck-types ``rbac.AuditLog.record/entries/close`` so the RBAC routes and
    the 403 audit hook keep working while ``import processos.api`` (whose
    module-level demo app has no db configured) never touches the default
    SQLite store path. Entries are process-local and lost on exit — the same
    trade-off every other no-db service in this app already makes.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._seq = 1
        self._lock = threading.RLock()

    def record(self, actor: Any, action: str, target: str, *, result: str = "OK",
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            entry = {"ts": utcnow(), "seq": self._seq, "actor_id": actor.actor_id,
                     "role": actor.role, "action": action, "target": target,
                     "result": result, "extra": extra or {}}
            self._seq += 1
            self._entries.append(entry)
            return dict(entry)

    def entries(self, *, actor_id: str | None = None, action: str | None = None,
                target: str | None = None, limit: int | None = 200) -> list[dict[str, Any]]:
        with self._lock:
            matched = [e for e in self._entries
                       if (not actor_id or e.get("actor_id") == actor_id)
                       and (not action or e.get("action") == action)
                       and (not target or e.get("target") == target)]
            matched.sort(key=lambda e: int(e.get("seq", 0)), reverse=True)
            return matched if limit is None else matched[: max(int(limit), 0)]

    def close(self) -> None:
        pass


class _PersistentTrace:
    """App-level thread-affinity adapter over ``attach_persistence``.

    SQLite connections are pinned to their creating thread, while FastAPI
    serves sync routes from a worker-thread pool. Every attribute access
    re-checks the serving thread: on a change the trace state is re-attached
    through a fresh same-thread connection (``attach_persistence`` archives the
    in-memory mirror and swaps the sub-services), and the replaced services
    drop the previous connection. Only used when a db location is configured —
    otherwise ``app.state.trace`` stays a pure in-memory TraceabilityService so
    tests never touch disk.
    """

    def __init__(self, trace: TraceabilityService, db_file: str) -> None:
        self._trace = trace
        self._db_file = db_file
        self._thread_id: int | None = None

    def _sync_thread(self) -> None:
        current = threading.get_ident()
        if current == self._thread_id:
            return
        from processos.store.persistence import attach_persistence

        attach_persistence(self._trace, self._db_file)
        self._thread_id = current

    def close(self) -> None:
        """Close the store on the calling thread (required before tmp cleanup)."""
        from processos.store.persistence import close_persistence

        self._sync_thread()
        if self._thread_id is not None:
            close_persistence(self._trace)
            self._thread_id = None

    def __getattr__(self, name: str) -> Any:
        self._sync_thread()
        return getattr(self._trace, name)


class _AppImpactService(ImpactReportService):
    """create_app-level subclass persisting impact reports on the app's db.

    Mirrors ``impact.service``'s per-call-connection discipline (never a cached
    handle — FastAPI sync routes run on thread-pool threads) while pinning the
    location to the db passed to ``create_app`` instead of env/default.
    """

    def __init__(self, trace_provider: Any, db_file: str | None) -> None:
        super().__init__(trace_provider, dao=None)
        self._app_db = db_file

    def _dao_session(self) -> tuple[JsonDao, Any | None]:  # type: ignore[override]
        if self._app_db is None:
            return super()._dao_session()
        conn = open_db(self._app_db)  # "impact" namespace, same as impact.service
        return JsonDao(conn, "impact"), conn


# Module-level gates: with ``from __future__ import annotations`` the route
# parameter hints are resolved through __globals__ only, so dependency objects
# must never live in a create_app closure.
_APPROVE_GATE = require_role(action="changeset.approve")
_BUILD_GATE = require_role(action="build.trigger")

#: §8 job-detail artifact digest fields (missing values surface as UNKNOWN).
_ARTIFACT_SUMMARY_FIELDS = ("artifact_id", "archive_path", "archive_sha256",
                            "size_bytes", "kind", "evidence_level")

#: App-layer RBAC rules for endpoints owned by wave-1 modules (their route
#: files stay untouched — the permission matrix is enforced here, fail-closed).
_RBAC_HTTP_RULES: dict[tuple[str, str], str] = {
    ("POST", "/api/processos/deployments/records"): "deployment.record",
    ("POST", "/api/processos/deployments/gateway/precheck"): "deployment.gateway.precheck",
    ("POST", "/api/processos/deployments/gateway/execute"): "deployment.gateway.execute",
}


# ---- §8 Idempotency-Key（纯 ASGI 中间件；不走 BaseHTTPMiddleware 以免 body 流被消费）----

_IDEMPOTENCY_KEY_HEADER = b"idempotency-key"
_IDEMPOTENT_FIXED_PATHS = frozenset({"/api/processos/deployments/records"})
_IDEMPOTENT_PROJECT_POST_SUFFIXES = frozenset({"patches", "deliveries"})


def _idempotency_in_scope(path: str) -> bool:
    """Only the three mutating POST endpoints take Idempotency-Key (§8)."""
    if path in _IDEMPOTENT_FIXED_PATHS:
        return True
    parts = path.split("/")
    return (len(parts) == 6 and parts[1] == "api" and parts[2] == "processos"
            and parts[3] == "projects" and bool(parts[4])
            and parts[5] in _IDEMPOTENT_PROJECT_POST_SUFFIXES)


async def _idem_replay(send: Any, entry: dict[str, Any]) -> None:
    payload: bytes = entry["body"]
    headers = [*entry["headers"],
               (b"idempotency-replayed", b"true"),
               (b"content-length", str(len(payload)).encode("ascii"))]
    await send({"type": "http.response.start", "status": entry["status"], "headers": headers})
    await send({"type": "http.response.body", "body": payload})


async def _idem_conflict(send: Any, key: str) -> None:
    payload = json.dumps({
        "error": f"Idempotency-Key {key!r} was already used with a different request",
        "code": "IDEMPOTENCY_KEY_CONFLICT",
    }).encode("utf-8")
    await send({"type": "http.response.start", "status": 409,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(payload)).encode("ascii"))]})
    await send({"type": "http.response.body", "body": payload})


class IdempotencyMiddleware:
    """§8 · ``Idempotency-Key`` replay for the mutating POST endpoints.

    Scope: POST ``/api/processos/projects/{pid}/patches`` | ``/deliveries`` and
    POST ``/api/processos/deployments/records``. Requests without the header
    pass through unchanged.

    Semantics (fail-closed):
    - same key + same body (and same X-Actor-* headers) → the first response is
      replayed verbatim with an extra ``Idempotency-Replayed: true`` header and
      **no side effects run again** (e.g. the project revision does not bump);
    - same key + different body/actor → 409 ``IDEMPOTENCY_KEY_CONFLICT``;
    - responses with status >= 500 are not cached (transient errors may retry).

    Storage is a **process-local dict** on ``app.state`` (plus per-key asyncio
    locks so concurrent duplicates serialise): NOT distributed — a multi-worker
    deployment must front this with a shared idempotency store. Implemented as
    plain ASGI (not ``@app.middleware("http")``) because buffering the request
    body inside BaseHTTPMiddleware starves the downstream handler.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if not _idempotency_in_scope(path):
            await self.app(scope, receive, send)
            return
        key = ""
        actor_bits: list[bytes] = []
        for name, value in scope.get("headers") or []:
            if name == _IDEMPOTENCY_KEY_HEADER:
                key = value.decode("latin-1").strip()
            elif name in (b"x-actor-id", b"x-actor-role"):
                actor_bits.append(name + b"=" + value)
        if not key:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:  # buffer the request body, then hand it back once downstream
            message = await receive()
            if message["type"] == "http.request":
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        fingerprint = hashlib.sha256(b"\x00".join(
            [path.encode("utf-8"), bytes(body), *sorted(actor_bits)])).hexdigest()

        state = scope["app"].state
        cache: dict[tuple[str, str], dict[str, Any]] = getattr(state, "idempotency_cache", None)
        if cache is None:
            cache = {}
            state.idempotency_cache = cache
        locks: dict[tuple[str, str], asyncio.Lock] = getattr(state, "idempotency_locks", None)
        if locks is None:
            locks = {}
            state.idempotency_locks = locks
        cache_key = (path, key)
        if cache_key not in locks:
            locks[cache_key] = asyncio.Lock()
        async with locks[cache_key]:
            entry = cache.get(cache_key)
            if entry is not None:
                if entry["fingerprint"] == fingerprint:
                    await _idem_replay(send, entry)
                else:
                    await _idem_conflict(send, key)
                return

            status_holder: dict[str, int] = {}
            headers: list[tuple[bytes, bytes]] = []
            chunks: list[bytes] = []

            async def send_wrapper(message: Any) -> None:
                if message["type"] == "http.response.start":
                    status_holder["status"] = int(message["status"])
                    headers.extend(message.get("headers") or [])
                elif message["type"] == "http.response.body":
                    chunks.append(message.get("body", b""))
                await send(message)

            served = {"done": False}

            async def replay_body() -> dict[str, Any]:
                if not served["done"]:
                    served["done"] = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return {"type": "http.disconnect"}

            await self.app(scope, replay_body, send_wrapper)
            status = status_holder.get("status", 500)
            if status < 500:
                cache[cache_key] = {
                    "fingerprint": fingerprint,
                    "status": status,
                    "headers": [(k, v) for k, v in headers
                                if k.lower() not in (b"content-length", b"idempotency-replayed")],
                    "body": b"".join(chunks),
                }


def _resolve_db_file(db: str | os.PathLike[str] | None) -> str | None:
    """Explicit arg > env ``PROCESSOS_DB`` > None (pure memory; tests pass tmp)."""
    if db is not None:
        return str(db)
    return os.environ.get("PROCESSOS_DB", "").strip() or None


# ---- §4 lease write-lock around single mutating requests --------------------

_LOCK_OWNER_HEADERS = ("x-lock-owner", "x-actor-id")


def _lock_owner_of(request: Request) -> str:
    for header in _LOCK_OWNER_HEADERS:
        value = (request.headers.get(header) or "").strip()
        if value:
            return value
    return "anonymous"


@contextlib.contextmanager
def _project_write_lock(request: Request, pid: str) -> Iterator[str]:
    """Acquire the §4 project lease for one mutating request, release at the end.

    Owner resolution: ``X-Lock-Owner`` > ``X-Actor-Id`` > ``"anonymous"``. The
    lock is taken AFTER the route's RBAC dependencies (role 403 wins over lock
    409) and released in ``finally`` when the request ends — the lease timeout
    (``processos.locks``) remains the crash-recovery fallback, mirroring the v2
    gateway ``project_locks`` semantics. Default no-header requests therefore
    self-lock/self-release per request and never block single-threaded flows.
    """
    owner = _lock_owner_of(request)
    manager: ProjectLockManager | None = getattr(request.app.state, "locks", None)
    if manager is None:  # defensive: unwired manager must not change behaviour
        yield owner
        return
    acquired = manager.acquire(pid, owner)
    if not acquired.get("ok"):
        raise HTTPException(status_code=409, detail={
            "error": f"project {pid} is locked by {acquired.get('holder', 'UNKNOWN')} "
                     f"until {acquired.get('expires_at', 'UNKNOWN')} (lease not expired)",
            "code": "LOCK_HELD",
            "holder": acquired.get("holder", "UNKNOWN"),
            "expires_at": acquired.get("expires_at", "UNKNOWN"),
        })
    try:
        yield owner
    finally:
        manager.release(pid, owner)


def _seed_baselines(baselines: Any, contract: ProcessContract) -> dict[str, Any]:
    """Seed honest demo B2/B3 baselines (PLAN §4; idempotent by content digest).

    B2's block manifest is REAL hashlib over the blocks the demo build actually
    generates — ``sha256("<block>:<generated content>")`` per block — and the
    archive digest is sha256 over the canonical manifest JSON. That makes it a
    ``derived-from-demo-build`` identifier, NOT a real ``.zap19`` archive hash:
    no real archive exists in demo mode (the native chain stays
    ``evidence_level="mocked"``). B3 is recorded ``SELF_REPORTED`` only — the
    honest no-PLC-connection state that keeps compare at UNVERIFIED_ONLINE
    (B3 不能仅凭 Build ID 自报).
    """
    from processos.backends import lower
    from processos.codegen import generate

    profile = get_profile(contract.target_framework.split("@")[-1]) or register_hr001_af_v19()
    generated = generate(lower(contract, profile), profile)
    manifest = {
        name.rsplit(".", 1)[0]: hashlib.sha256(
            f"{name.rsplit('.', 1)[0]}:{content}".encode("utf-8")
        ).hexdigest()
        for name, content in sorted(generated.files.items())
    }
    archive = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    b2 = baselines.record_b2(contract.id, "build_219", archive, manifest)
    b3 = baselines.record_b3(contract.id, "build_219", verification="SELF_REPORTED")
    return {"b2": b2, "b3": b3}


def _seed_trace(trace: TraceabilityService, contract: Any,
                baselines: Any = None) -> None:
    """Idempotent demo: battery-change station clamp-timeout incident (§10).

    With a baselines service (persistence configured) the demo also seeds the
    honest B2 (derived-from-demo-build manifest) and B3 (SELF_REPORTED →
    UNVERIFIED_ONLINE) so the whole §10 drill is walkable from POST /demo.
    """
    if trace.ids_for(contract.id):
        return
    ids = trace.register_project(contract.id, contract, physical_station="电池更换站")
    trace.record_build(contract.id, "build_219", contract, tia_project_id="TIA_PRJ_001", tia_plc_id="PLC_1")
    cm_id = ids.get("CM_CLAMP_CYL", "")
    step_id = ids.get("S_EXTEND", "")
    trace.incidents.define_alarm("alarm_clamp_timeout", "CM_MOTION_TIMEOUT", cm_id, "伸出到位信号未在规定时间内出现")
    trace.incidents.raise_alarm("evt_876", "alarm_clamp_timeout", "2026-11-15T09:17:08+08:00", "build_219", 876, "OBSERVED")
    sm = trace.sourcemap.resolve(cm_id, "build_219")
    trace.incidents.create_incident(
        "INC-2026-0042", cm_id,
        asset_id="machine_001", physical_path_at_event="设备1/电池更换站/夹紧机构/气缸A",
        af_refs={"unit_id": ids.get("U_ASSEMBLY", ""), "em_id": ids.get("EM_CLAMP", ""), "cm_id": cm_id},
        alarm={"definition_id": "alarm_clamp_timeout", "event_time": "2026-11-15T09:17:08+08:00", "sequence": 876, "quality": "OBSERVED"},
        behavior={"step_id": step_id, "expected": "extended=true within 3000ms", "observed": "extended=false at 3000ms"},
        software={"deployed_build_id": "build_219", "native_archive_sha256": "sha256:<recorded-at-release>"},
        references={"source_map_id": sm[0].source_map_id if sm else "", "change_set_ids": []},
        triage={"fact": "伸出反馈未按时出现", "hypotheses": ["气压不足", "线圈未动作", "传感器故障"], "root_cause": None},
        handover={"owner": "engineer_on_duty", "status": "INVESTIGATING", "next_action": "检查线圈输出及现场传感器"},
    )
    if baselines is not None:
        _seed_baselines(baselines, contract)


def create_app(store: ProjectStore | None = None, *, demo_runner: bool = False,
               db: str | os.PathLike[str] | None = None) -> FastAPI:
    app = FastAPI(title="aiCoPlc ProcessOS", version="0.2.0")
    app.state.store = store or ProjectStore()
    # App-level patch history (rev + real ops per project) — the semantic-diff
    # artifact reads it; anything not recorded here stays UNKNOWN, never guessed.
    app.state.patch_history: dict[str, list[dict[str, Any]]] = {}
    db_file = _resolve_db_file(db)
    app.state.db_path = db_file
    # §4 项目写锁：db 配置时租约持久化（namespace "locks"），否则进程内。
    app.state.locks = ProjectLockManager(db=db_file)
    trace: Any = TraceabilityService()
    if db_file is not None:
        trace = _PersistentTrace(trace, db_file)
    app.state.trace = trace
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

    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException):
        # 403s enter the audit ledger (rbac.audit_forbidden is a no-op without
        # an attached ledger). Dict details (ROLE_FORBIDDEN / APPROVER_SEPARATION)
        # are flattened to the app-wide {error, code, ...} contract.
        if exc.status_code == 403:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            audit_forbidden(request, str(detail.get("action") or request.url.path))
        content = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.middleware("http")
    async def _module_rbac_gate(request: Request, call_next):
        """Permission matrix for module-owned endpoints (fail-closed, audited)."""
        action = _RBAC_HTTP_RULES.get((request.method, request.url.path))
        if action is not None:
            actor = get_actor(request)
            allowed = PERMISSIONS[action]
            if actor.role not in allowed:
                audit_forbidden(request, action)
                return JSONResponse(status_code=403, content={
                    "error": f"actor '{actor.actor_id}' with role '{actor.role}' is not "
                             f"authorized (requires one of: {', '.join(allowed)})",
                    "code": "ROLE_FORBIDDEN",
                    "required": list(allowed),
                    "action": action,
                })
        return await call_next(request)

    def store_of(request: Request) -> ProjectStore:
        return request.app.state.store

    def audit_of(request: Request) -> Any:
        return getattr(request.app.state, "audit", None)

    @app.get("/api/processos/health")
    def health():
        return {"status": "ok"}

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

    def trace_of(request: Request) -> TraceabilityService:
        return request.app.state.trace

    @app.post("/api/processos/trace/register")
    def trace_register(request: Request, body: dict[str, Any]):
        contract = ProcessContract.from_dict(body["contract"])
        ids = trace_of(request).register_project(body.get("project_id", contract.id), contract, body.get("physical_station"))
        return {"ids": ids}

    @app.post("/api/processos/trace/build")
    def trace_build(request: Request, body: dict[str, Any]):
        contract = ProcessContract.from_dict(body["contract"])
        entries = trace_of(request).record_build(
            body.get("project_id", contract.id), body["build_id"], contract,
            tia_project_id=body.get("tia_project_id", ""), tia_plc_id=body.get("tia_plc_id", ""))
        return {"build_id": body["build_id"], "source_map": entries}

    @app.get("/api/processos/objects/{object_id}/context")
    def object_context(request: Request, object_id: str, build_id: str | None = None):
        ctx = trace_of(request).object_context(object_id, build_id)
        if not ctx.get("found"):
            raise NotFound(f"unknown object {object_id}")
        return ctx

    @app.get("/api/processos/objects")
    def find_object(request: Request, name: str):
        obj = trace_of(request).find_object(name)
        if obj is None:
            raise NotFound(f"no object named {name}")
        return obj

    @app.get("/api/processos/trace/graphs")
    def trace_graphs(request: Request):
        reg = trace_of(request).registry
        return {g: [o.to_dict() for o in reg.graph(g)] for g in
                ("PhysicalGraph", "AfGraph", "BehaviorGraph", "EvidenceGraph")}

    @app.get("/api/processos/projects/{pid}/sourcemap")
    def project_sourcemap(request: Request, pid: str):
        """Block inventory of a project's recorded builds (fieldmod prefill)."""
        if pid not in store_of(request).projects:
            raise NotFound(f"unknown project {pid}")
        trace = trace_of(request)
        builds = [o for o in trace.registry.by_kind("build")
                  if (o.attributes or {}).get("project") == pid]
        entries: list[dict[str, Any]] = []
        for b in builds:
            entries.extend(e.to_dict() for e in trace.sourcemap.for_build(b.display_name))
        return {"project_id": pid, "builds": [b.display_name for b in builds],
                "source_map": entries}

    @app.post("/api/processos/alarms/define")
    def alarm_define(request: Request, body: dict[str, Any]):
        d = trace_of(request).incidents.define_alarm(
            body["definition_id"], body["code"], body["originates_from"], body.get("description", ""))
        return d.to_dict()

    @app.post("/api/processos/alarms/raise")
    def alarm_raise(request: Request, body: dict[str, Any]):
        e = trace_of(request).incidents.raise_alarm(
            body["event_id"], body["definition_id"], body["event_time"], body["deployed_build_id"],
            body.get("sequence", 0), body.get("quality", "OBSERVED"))
        return e.to_dict()

    @app.post("/api/processos/incidents")
    def incident_create(request: Request, body: dict[str, Any]):
        inc = trace_of(request).incidents.create_incident(**body)
        return inc.to_dict()

    @app.get("/api/processos/incidents")
    def incident_list(request: Request):
        return {"incidents": [i.to_dict() for i in trace_of(request).incidents.all_incidents()]}

    @app.get("/api/processos/incidents/{incident_id}")
    def incident_get(request: Request, incident_id: str):
        inc = trace_of(request).incidents.get(incident_id)
        if inc is None:
            raise NotFound(f"unknown incident {incident_id}")
        return inc.to_dict()

    @app.get("/api/processos/incidents/{incident_id}/handover")
    def incident_handover(request: Request, incident_id: str):
        ctx = trace_of(request).handover(incident_id)
        if not ctx.get("incident"):
            raise NotFound(f"unknown incident {incident_id}")
        return ctx

    @app.post("/api/processos/incidents/{incident_id}/triage")
    def incident_triage(request: Request, incident_id: str, body: dict[str, Any]):
        inc = trace_of(request).incidents.update_triage(
            incident_id, body.get("fact"), body.get("hypotheses"),
            body.get("root_cause"), body.get("root_cause_verified", False))
        return inc.to_dict()

    @app.post("/api/processos/incidents/{incident_id}/handover")
    def incident_set_handover(request: Request, incident_id: str, body: dict[str, Any]):
        inc = trace_of(request).incidents.set_handover(
            incident_id, body["owner"], body["status"], body["next_action"])
        return inc.to_dict()

    @app.post("/api/processos/demo")
    def demo(request: Request):
        from processos.contract import clamp_contract
        store = store_of(request)
        c = clamp_contract()
        state = store.projects.get(c.id) or store.create_project(c)
        # Baselines are only seeded when persistence is configured, so pure
        # in-memory test apps never write to the default store path.
        baselines = getattr(request.app.state, "baselines", None) \
            if request.app.state.db_path else None
        _seed_trace(request.app.state.trace, c, baselines=baselines)
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
        profile = get_profile(state.profile_id)
        return {"contract": state.contract.to_dict(), "revision": state.revision,
                "profile_id": state.profile_id,
                "spec_hash": contract_spec_hash(
                    state.contract, profile.profile_id, profile.template_sha256)}

    @app.post("/api/processos/projects/{pid}/patches")
    def patch(request: Request, pid: str, body: dict[str, Any]):
        with _project_write_lock(request, pid):
            p = Patch.from_dict(body)
            state = store_of(request).apply_patch(pid, p)
            request.app.state.patch_history.setdefault(pid, []).append({
                "rev": state.revision, "request_id": p.request_id, "source": p.source,
                "ops": [o.to_dict() for o in p.ops],
            })
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
    def approve(request: Request, pid: str, csid: str, body: dict[str, Any],
                actor: Annotated[Actor, Depends(_APPROVE_GATE)]):
        """Human approval, role-gated (Reviewer+) with approver separation.

        ``body.by`` names the modifier; PLAN §7 treats approvals as high-risk,
        so the header identity approving must differ from the modifier.
        """
        modifier = str(body.get("by", ""))
        assert_approver_separation(actor, modifier, high_risk=True)
        with _project_write_lock(request, pid):
            result = store_of(request).approve(pid, csid, body["by"])
        audit = audit_of(request)
        if audit is not None:
            audit.record(actor, "changeset.approve", f"{pid}/{csid}",
                         extra={"modifier": modifier, "changeset_id": csid})
        return result

    @app.get("/api/processos/projects/{pid}/delivery-gate")
    def gate(request: Request, pid: str):
        return store_of(request).delivery_gate(pid)

    @app.post("/api/processos/projects/{pid}/changesets/{csid}/preview")
    def preview_changeset(request: Request, pid: str, csid: str):
        """PLAN §8 changeset preview: semantic diff + impact + test plan.

        Read-level endpoint (no extra RBAC gate). The impact report is built
        from the frozen changeset's own ops; the subject is the registry object
        behind the first op's target. Anything underivable stays an explicit
        UNKNOWN — never fabricated (§12).
        """
        store = store_of(request)
        if pid not in store.projects:
            raise NotFound(f"unknown project {pid}")
        impact = getattr(request.app.state, "impact", None)
        trace = trace_of(request)

        def subject_resolver(ops: list[dict[str, Any]]) -> str | None:
            ids_for = getattr(trace, "ids_for", None)
            ids_map: dict[str, str] = dict(ids_for(pid)) if callable(ids_for) else {}
            reg = getattr(trace, "registry", None)
            first = ops[0] if ops else {}
            for token in [t for t in str(first.get("path") or "").split("/") if t]:
                oid = ids_map.get(token) or (
                    token if reg is not None and reg.get(token) is not None else None)
                if oid:
                    return oid
            return None

        return store.preview_changeset(
            pid, csid, impact_service=impact, subject_resolver=subject_resolver)

    @app.post("/api/processos/projects/{pid}/deliveries")
    def deliver(request: Request, pid: str,
                actor: Annotated[Actor, Depends(_BUILD_GATE)]):
        with _project_write_lock(request, pid):
            job = store_of(request).create_delivery(pid)
        audit = audit_of(request)
        if audit is not None:
            audit.record(actor, "build.trigger", pid,
                         extra={"job_id": job.get("id", ""), "status": job.get("status")})
        return job

    # ---- §8 job detail + native artifact download ----------------------------

    @app.get("/api/processos/projects/{pid}/jobs/{job_id}")
    def get_job(request: Request, pid: str, job_id: str):
        state = store_of(request)._get(pid)
        job = state.jobs.get(job_id)
        if job is None:
            raise NotFound(f"unknown job {job_id}")
        detail = dict(job)
        artifact = job.get("artifact")
        if isinstance(artifact, dict):
            detail["artifact_summary"] = {
                f: artifact.get(f, "UNKNOWN") for f in _ARTIFACT_SUMMARY_FIELDS}
        else:
            detail["artifact_summary"] = None
        return detail

    @app.get("/api/processos/projects/{pid}/jobs/{job_id}/artifact")
    def job_artifact(request: Request, pid: str, job_id: str):
        """Download the job's real ``.zap19`` archive (§8), confinement-checked.

        A file is only served when it exists inside THIS job's workspace
        (resolved path must be ``is_relative_to`` the resolved workspace; the
        demo/mock chain claims a fake archive path outside any workspace and
        produces no file — that is an honest 422 BUILD_ARTIFACT_MISMATCH,
        never a synthetic download).
        """
        state = store_of(request)._get(pid)
        job = state.jobs.get(job_id)
        if job is None:
            raise NotFound(f"unknown job {job_id}")

        def _mismatch() -> HTTPException:
            return HTTPException(status_code=422, detail={
                "error": "demo chain produces no native archive",
                "code": "BUILD_ARTIFACT_MISMATCH"})

        artifact = job.get("artifact")
        workspace_raw = str(job.get("workspace_dir") or "")
        if not isinstance(artifact, dict) or not workspace_raw.strip():
            raise _mismatch()
        workspace = Path(workspace_raw).resolve()
        candidates: list[Path] = []
        archive_path = str(artifact.get("archive_path") or "")
        if archive_path.strip():
            candidates.append(Path(archive_path))
        archive_dir = workspace / "archive"
        if archive_dir.is_dir():
            candidates.extend(sorted(archive_dir.glob("*.zap19")))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.suffix != ".zap19":
                continue
            if not resolved.is_relative_to(workspace):
                continue  # traversal/outside-workspace claim: never served
            if resolved.is_file():
                return FileResponse(resolved, filename=resolved.name,
                                    media_type="application/octet-stream")
        raise _mismatch()

    @app.get("/api/processos/pr-bundles/{bundle_id}/files/{name}")
    def pr_bundle_file(request: Request, bundle_id: str, name: str):
        """Fetch one persisted §12 bundle file by name (content served from the
        stored record, never from the filesystem — traversal is impossible)."""
        svc = getattr(request.app.state, "pr_bundles", None)
        bundle = svc.get(bundle_id) if svc is not None else None
        if bundle is None:
            raise NotFound(f"unknown pr bundle {bundle_id}")
        files = bundle.get("files") or {}
        if name not in files:
            raise NotFound(f"unknown file {name!r} in bundle {bundle_id}")
        if name.endswith(".md"):
            media = "text/markdown; charset=utf-8"
        elif name.endswith(".json"):
            media = "application/json; charset=utf-8"
        else:
            media = "text/plain; charset=utf-8"
        return PlainTextResponse(files[name], media_type=media)

    @app.get("/api/processos/projects/{pid}/passport")
    def passport(request: Request, pid: str):
        state = store_of(request)._get(pid)
        from processos.contract import contract_semantic_hash
        rh = contract_semantic_hash(state.contract)
        return {"revision_hash": rh, "entries": [e.to_dict() for e in store_of(request).passport.for_revision(rh)]}

    # ---- wave-1 module mounting (fixed order; every register is idempotent) ----
    from processos import rbac

    if db_file is None and getattr(app.state, "audit", None) is None:
        # no-db apps audit in memory only — the default store path stays untouched
        app.state.audit = _MemoryAuditLog()
    rbac.register_routes(app, db_file=db_file)  # audit ledger first: 403 auditing needs it

    from processos.baselines import service as baselines_module

    if db_file is not None and getattr(app.state, "baselines", None) is None:
        app.state.baselines = baselines_module.BaselineService(db_file)
    baselines_module.register_routes(app)

    if getattr(app.state, "impact", None) is None:
        app.state.impact = _AppImpactService(app.state.trace, db_file)
    from processos.impact.service import register_routes as register_impact

    register_impact(app)

    from processos.commissioning import service as commissioning_module
    from processos.commissioning.routes import register_routes as register_commissioning

    if db_file is not None and getattr(app.state, "commissioning", None) is None:
        app.state.commissioning = commissioning_module.CommissioningLedger(db_file)
    register_commissioning(app)

    from processos.telemetry import fieldmods as fieldmods_module
    from processos.telemetry import service as telemetry_module
    from processos.telemetry.routes import register_routes as register_telemetry

    if db_file is not None:
        if getattr(app.state, "telemetry", None) is None:
            app.state.telemetry = telemetry_module.TelemetryService(db_file)
        if getattr(app.state, "fieldmods", None) is None:
            # baselines is already on app.state here, so drift checks see it.
            app.state.fieldmods = fieldmods_module.FieldModificationService(
                app.state.trace,
                baseline_provider=getattr(app.state, "baselines", None),
                db=db_file,
            )
    register_telemetry(app)

    # deployment AFTER commissioning: the gateway reads the commissioning
    # ledger as its 投产记录 evidence source.
    from processos.deployment import gateway as gateway_module
    from processos.deployment.routes import register_routes as register_deployment

    if db_file is not None and getattr(app.state, "deploy_gateway", None) is None:
        app.state.deploy_gateway = gateway_module.SiteDeploymentGateway(
            None,  # no real execution backend: execute refuses (501 SAFETY_SCOPE_BLOCKED)
            baseline_provider=getattr(app.state, "baselines", None),
            commissioning=getattr(app.state, "commissioning", None),
            db=db_file,
        )
    register_deployment(app)

    from processos.artifacts import PrBundleService
    from processos.artifacts.service import register_routes as register_artifacts

    if getattr(app.state, "pr_bundles", None) is None:
        app.state.pr_bundles = PrBundleService(
            store=app.state.store, trace=app.state.trace,
            impact=getattr(app.state, "impact", None), db=db_file,
            patch_history=app.state.patch_history)
    register_artifacts(app)

    # ---- wave-2 gap modules (expert → repair → handover_check; §3.2B/§5.2/§7) ----
    from processos.expert import register_routes as register_expert
    from processos.expert.service import ExpertSclService

    if db_file is not None and getattr(app.state, "expert_scl", None) is None:
        app.state.expert_scl = ExpertSclService(
            app.state.store, app.state.trace, db=db_file)
    register_expert(app)  # audit 早已挂在 app.state（rbac 先行），无则跳过

    from processos.repair import register_routes as register_repair
    from processos.repair.service import RepairBoundaryService

    if db_file is not None and getattr(app.state, "repair_boundary", None) is None:
        app.state.repair_boundary = RepairBoundaryService(db=db_file)
    register_repair(app)

    from processos.handover_check import register_routes as register_handover
    from processos.handover_check.service import HandoverReadinessService

    if db_file is not None and getattr(app.state, "handover_readiness", None) is None:
        app.state.handover_readiness = HandoverReadinessService(
            app.state.trace,
            baselines=getattr(app.state, "baselines", None),
            commissioning=getattr(app.state, "commissioning", None),
            fieldmods=getattr(app.state, "fieldmods", None),
            db=db_file,
        )
    register_handover(app)

    # ---- wave-3 gap modules (K/L/M：from-spec 规格构建 / 导入真解析 / 诊断定位) ----
    from processos.api.spec_routes import register_routes as register_spec
    register_spec(app)  # 无状态：仅依赖 app.state.store

    from processos.api.import_routes import register_routes as register_import
    from processos.importer.service import ImportParseService

    if db_file is not None and getattr(app.state, "importer", None) is None:
        app.state.importer = ImportParseService(
            app.state.trace, baselines=getattr(app.state, "baselines", None), db=db_file)
    register_import(app)

    from processos.api.diag_routes import register_routes as register_diag
    from processos.diagnostics.service import DiagnosticsLocateService

    if db_file is not None and getattr(app.state, "diag_locate", None) is None:
        app.state.diag_locate = DiagnosticsLocateService(
            app.state.trace,
            repair=getattr(app.state, "repair_boundary", None),
            db=db_file,
        )
    register_diag(app)

    # §8 幂等键（进程内缓存，非分布式；见 IdempotencyMiddleware docstring）。
    app.add_middleware(IdempotencyMiddleware)

    return app


app = create_app(demo_runner=True)
