"""PLAN §7 · Role-based access control, audit ledger and approver separation.

Identity is carried by the ``X-Actor-Id`` / ``X-Actor-Role`` headers through the
``get_actor`` dependency. That is a DEVELOPMENT / DEMO identity channel, not
production authentication: any client can forge those headers. A real
deployment must front this with real auth (SSO / mTLS / session) and only map
the *verified* identity into these roles. No API keys or credentials live in
this module; if a future integration needs secrets they must be read from
environment variables only, never hardcoded.

Components:
- ``ROLES`` / ``PERMISSIONS``: the locked permission matrix (action -> roles).
- ``Actor`` + ``get_actor``: header-derived identity; roles outside ``ROLES``
  fail closed to ``Viewer`` with ``details["invalid_role"]`` recorded.
- ``require_role(...)``: FastAPI dependency factory — positional role names or
  ``action=`` matrix lookup; denies with 403 ``ROLE_FORBIDDEN``.
- ``assert_approver_separation``: high-risk changes cannot be approved by the
  same actor that made them (403 ``APPROVER_SEPARATION``).
- ``AuditLog``: append-only audit entries in the shared SQLite store
  (``JsonDao`` namespace ``audit``), newest-first filtered via ``entries()``.
- ``audit_forbidden``: hook for integrators to audit 403s from an exception
  handler (see its docstring for why the dependency does not audit itself).
- ``role_matrix`` / ``register_routes``: public matrix endpoint and the
  Admin-only audit query endpoint.

The db file location follows ``processos.store.db.db_path``: explicit arg >
env ``PROCESSOS_DB`` > default. Tests MUST pass an explicit ``tmp_path``.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Request

from processos.store.db import JsonDao, open_db, utcnow

ROLES: tuple[str, ...] = (
    "Viewer",
    "FieldEngineer",
    "Reviewer",
    "Builder",
    "ReleaseApprover",
    "CommissioningEngineer",
    "Admin",
)

# PLAN §7 / §8 —— action -> 允许角色（只读动作对所有角色开放；写/审批按链路收敛）。
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "incident.create": ("FieldEngineer", "Admin"),
    "incident.triage": ("FieldEngineer", "Admin"),
    "incident.read": ROLES,
    "project.read": ROLES,
    "object.read": ROLES,
    "artifact.download": ROLES,
    "changeset.propose": ("FieldEngineer", "Admin"),
    "changeset.approve": ("Reviewer", "ReleaseApprover", "Admin"),
    "build.trigger": ("Builder", "Admin"),
    "release.approve": ("ReleaseApprover", "Admin"),
    "deployment.record": ("CommissioningEngineer", "Admin"),
    "deployment.gateway.precheck": ("CommissioningEngineer", "ReleaseApprover", "Admin"),
    "deployment.gateway.execute": ("CommissioningEngineer", "Admin"),
    "telemetry.ingest": ("FieldEngineer", "CommissioningEngineer", "Admin"),
    "fieldmod.report": ("FieldEngineer", "CommissioningEngineer", "Admin"),
    "project.manage": ("FieldEngineer", "Builder", "Admin"),
    "rbac.audit.read": ("Admin",),
}

_ACTOR_ID_HEADER = "X-Actor-Id"
_ACTOR_ROLE_HEADER = "X-Actor-Role"
_DEFAULT_ACTOR_ID = "anonymous"
_DEFAULT_ROLE = "Viewer"
AUDIT_NAMESPACE = "audit"


@dataclass
class Actor:
    """Identity used for authorization decisions and audit records.

    ``details`` carries non-authoritative diagnostics, e.g.
    ``{"invalid_role": "Root"}`` when the supplied role was rejected and the
    actor fell back to ``Viewer``.
    """

    actor_id: str
    role: str
    details: dict[str, Any] = field(default_factory=dict)


def _actor_payload(actor: Actor) -> dict[str, Any]:
    payload: dict[str, Any] = {"actor_id": actor.actor_id, "role": actor.role}
    if actor.details:
        payload["details"] = dict(actor.details)
    return payload


def get_actor(request: Request) -> Actor:
    """FastAPI dependency: derive the dev/demo identity from request headers.

    Reads ``X-Actor-Id`` (default ``"anonymous"``) and ``X-Actor-Role``
    (default ``"Viewer"``). A role outside ``ROLES`` is NOT an error: the actor
    fails closed to the least-privileged ``Viewer`` role and the rejected value
    is kept in ``Actor.details["invalid_role"]`` so denials and audit entries
    stay explainable. Remember: headers are caller-controlled demo identity,
    not authentication (see module docstring).
    """
    actor_id = (request.headers.get(_ACTOR_ID_HEADER) or "").strip() or _DEFAULT_ACTOR_ID
    raw_role = (request.headers.get(_ACTOR_ROLE_HEADER) or "").strip()
    role = raw_role or _DEFAULT_ROLE
    details: dict[str, Any] = {}
    if role not in ROLES:
        if raw_role:
            details["invalid_role"] = raw_role
        role = _DEFAULT_ROLE
    return Actor(actor_id=actor_id, role=role, details=details)


def _resolve_required(targets: tuple[str, ...], action: str | None) -> list[str]:
    """Expand role names / matrix actions into one ordered list of roles."""
    required: set[str] = set()
    for t in targets:
        if t in ROLES:
            required.add(t)
        elif t in PERMISSIONS:
            required.update(PERMISSIONS[t])
        else:
            raise ValueError(f"require_role: unknown role or action {t!r}")
    if action is not None:
        if action not in PERMISSIONS:
            raise ValueError(f"require_role: unknown action {action!r}")
        required.update(PERMISSIONS[action])
    if not required:
        raise ValueError("require_role: expected at least one role or action")
    return sorted(required, key=ROLES.index)


def require_role(*targets: str, action: str | None = None) -> Callable[..., Actor]:
    """FastAPI dependency factory enforcing roles or permission-matrix actions.

    Two locked usages (may be combined; semantics are any-of):
    - ``Depends(require_role("Reviewer"))`` — direct role names.
    - ``Depends(require_role(action="changeset.approve"))`` — expand the
      ``PERMISSIONS`` matrix entry.

    Unknown names raise ``ValueError`` at wiring time (fail-closed before the
    server ever answers). A denied actor gets ``HTTPException(403)`` with
    ``detail = {"error", "code": "ROLE_FORBIDDEN", "required", "actor",
    "action"}``. The dependency does not write audit records itself — see
    ``audit_forbidden`` for the integrator-side 403 audit hook.
    """
    required = _resolve_required(targets, action)
    allowed = frozenset(required)
    action_label = action or next((t for t in targets if t in PERMISSIONS), None)

    def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        if actor.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": f"actor '{actor.actor_id}' with role '{actor.role}' is not "
                             f"authorized (requires one of: {', '.join(required)})",
                    "code": "ROLE_FORBIDDEN",
                    "required": list(required),
                    "actor": _actor_payload(actor),
                    "action": action_label,
                },
            )
        return actor

    return dependency


def assert_approver_separation(approver: Actor, modifier_actor_id: str, *, high_risk: bool) -> None:
    """PLAN §7: approver and modifier must differ for high-risk changes.

    No-op for ``high_risk=False`` (low-risk self-approval is allowed). When
    ``high_risk`` and ``approver.actor_id == modifier_actor_id`` raises
    ``HTTPException(403)`` with ``code="APPROVER_SEPARATION"``. Two
    ``"anonymous"`` ids count as the same (unknown) person — fail closed.
    """
    if not high_risk:
        return
    if approver.actor_id == modifier_actor_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "high-risk change: approver must differ from the modifier "
                         "(审批者与修改者分离)",
                "code": "APPROVER_SEPARATION",
                "actor": _actor_payload(approver),
                "modifier_actor_id": modifier_actor_id,
            },
        )


class AuditLog:
    """Append-only audit ledger on the shared SQLite store (namespace ``audit``).

    Each entry is ``{ts, seq, actor_id, role, action, target, result, extra}``.
    ``seq`` is a monotonic per-database counter (re-seeded from stored entries
    on reopen, assigned under a lock) so newest-first ordering stays
    deterministic even when many entries share the same ``ts`` second.

    Threading: ``open_db`` (locked shared contract) creates connections with
    sqlite3's default thread affinity, and FastAPI serves sync endpoints from
    a worker thread pool. The ledger therefore uses **per-call connections**:
    every operation opens, runs and closes its connection in the calling
    thread (WAL + busy_timeout, both set by ``open_db``, keep this safe). No
    SQLite handle outlives a call, so cross-thread close failures and leaked
    Windows file locks (WinError 32 on tmp cleanup) cannot happen.

    Use one ``AuditLog`` per database path at a time; ``register_routes``
    guarantees a single ledger on ``app.state.audit``.
    """

    def __init__(self, db_file: str | os.PathLike[str] | None = None) -> None:
        self._db_file = db_file
        self._lock = threading.RLock()
        self._closed = False

        def _max_seq(dao: JsonDao) -> int:
            return max((int(e.get("seq", 0)) for e in dao.list_by_kind("entry")), default=0)

        with self._lock:
            self._seq = self._connect(_max_seq) + 1

    def _connect(self, fn: Callable[[JsonDao], Any]) -> Any:
        """Run ``fn(dao)`` on a short-lived same-thread connection.

        Aligned with the gateway v2 idiom: never cache a connection in the
        service — open with ``open_db``, use, close via ``contextlib.closing``.
        """
        if self._closed:
            raise sqlite3.ProgrammingError("AuditLog is closed")
        with closing(open_db(self._db_file)) as conn:
            return fn(JsonDao(conn, AUDIT_NAMESPACE))

    def record(self, actor: Actor, action: str, target: str, *, result: str = "OK",
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append one entry and return the stored record (with id/kind)."""
        entry = {
            "ts": utcnow(),
            "seq": 0,  # assigned under the lock below
            "actor_id": actor.actor_id,
            "role": actor.role,
            "action": action,
            "target": target,
            "result": result,
            "extra": extra or {},
        }
        with self._lock:  # serialize writes: seq assignment + insert
            entry["seq"] = self._seq
            self._seq += 1
            return self._connect(
                lambda dao: dao.put(f"entry_{entry['seq']:08d}", "entry", entry)
            )

    def entries(self, *, actor_id: str | None = None, action: str | None = None,
                target: str | None = None, limit: int | None = 200) -> list[dict[str, Any]]:
        """Filtered entries, newest first (``None``/empty filter values mean any)."""

        def _query(dao: JsonDao) -> list[dict[str, Any]]:
            matched = [
                e for e in dao.list_by_kind("entry")
                if (not actor_id or e.get("actor_id") == actor_id)
                and (not action or e.get("action") == action)
                and (not target or e.get("target") == target)
            ]
            matched.sort(key=lambda e: int(e.get("seq", 0)), reverse=True)
            return matched if limit is None else matched[: max(int(limit), 0)]

        return self._connect(_query)

    def close(self) -> None:
        """Mark the ledger closed (idempotent, thread-safe).

        Connections are per-call and already released, so there is no
        persistent handle to free; after ``close()`` further operations raise
        ``sqlite3.ProgrammingError``, mirroring a closed sqlite3 connection.
        """
        with self._lock:
            self._closed = True


def audit_forbidden(request: Request, action: str) -> None:
    """Record a denial into ``request.app.state.audit`` (best effort, no-op if absent).

    ``require_role`` / ``get_actor`` raise plain FastAPI ``HTTPException``(403)
    and do not audit by themselves: the audit log may not be attached when the
    dependency runs, and double-writing is worse than integrator-owned writes.
    Integrators that want 403s audited should call this helper from a FastAPI
    exception handler, e.g.::

        @app.exception_handler(HTTPException)
        async def _forbidden(request, exc):
            if exc.status_code == 403 and isinstance(exc.detail, dict):
                audit_forbidden(request, exc.detail.get("action") or request.url.path)
            ...return the default JSON response...

    The entry is stored with ``result="FORBIDDEN"`` and the request path as
    target, so Admins can query it via ``GET /api/processos/rbac/audit``.
    """
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    actor = get_actor(request)
    audit.record(actor, action, request.url.path, result="FORBIDDEN",
                 extra={"code": "ROLE_FORBIDDEN", "method": request.method})


def role_matrix() -> dict[str, Any]:
    """Serializable view of ``ROLES`` / ``PERMISSIONS`` for the workbench UI."""
    return {
        "roles": list(ROLES),
        "permissions": {a: list(roles) for a, roles in PERMISSIONS.items()},
    }


# Module-level (not a closure var) so postponed annotations inside
# ``register_routes`` can resolve it via the function's globals.
_AUDIT_READ_GATE = require_role(action="rbac.audit.read")


def _register_shutdown_close(app: Any, close: Callable[[], None]) -> None:
    """Best-effort hook: run ``close()`` when the app shuts down.

    Older FastAPI/Starlette expose ``app.add_event_handler("shutdown", ...)``;
    newer builds removed it in favour of lifespans, so fall back to wrapping
    ``app.router.lifespan_context`` (chaining the previous one). If neither
    mechanism is available, the owner must close ``app.state.audit`` explicitly
    — tests always do, because a leaked SQLite handle blocks tmp_path cleanup
    on Windows (WinError 32).
    """
    if hasattr(app, "add_event_handler"):
        app.add_event_handler("shutdown", close)
        return
    router = getattr(app, "router", None)
    if hasattr(router, "add_event_handler"):
        router.add_event_handler("shutdown", close)
        return
    prev = getattr(router, "lifespan_context", None) if router is not None else None
    if prev is None:
        return

    @asynccontextmanager
    async def _audit_close_lifespan(app_arg: Any):
        async with prev(app_arg):
            try:
                yield
            finally:
                close()

    router.lifespan_context = _audit_close_lifespan


def register_routes(app: Any, *, audit: AuditLog | None = None,
                    db_file: str | os.PathLike[str] | None = None) -> AuditLog:
    """Attach the RBAC endpoints to a FastAPI app (idempotent per app).

    - reuses ``app.state.audit`` when already present (never overwrites an
      integrator-provided ledger), otherwise builds ``AuditLog(audit or db_file)``
      (db path: explicit arg > env ``PROCESSOS_DB`` > default; tests MUST pass
      ``tmp_path``);
    - registering twice adds no duplicate routes;
    - closes the audit connection on app shutdown (best-effort hook, see
      ``_register_shutdown_close``) so hosted deployments do not leak the
      SQLite handle.

    Endpoints:
    - ``GET /api/processos/rbac/roles``  → ``role_matrix()`` (public metadata).
    - ``GET /api/processos/rbac/audit?actor_id=&action=&target=&limit=``
      → ``{"entries": [...]}``, requires ``rbac.audit.read`` (Admin only).
    """
    if getattr(app.state, "audit", None) is None:
        app.state.audit = audit or AuditLog(db_file)
    if getattr(app.state, "rbac_routes_registered", False):
        return app.state.audit
    app.state.rbac_routes_registered = True

    @app.get("/api/processos/rbac/roles")
    def rbac_roles() -> dict[str, Any]:
        return role_matrix()

    @app.get("/api/processos/rbac/audit")
    def rbac_audit(request: Request,
                   actor: Annotated[Actor, Depends(_AUDIT_READ_GATE)],
                   actor_id: str | None = Query(default=None),
                   action: str | None = Query(default=None),
                   target: str | None = Query(default=None),
                   limit: int = Query(default=200, ge=1, le=5000)) -> dict[str, Any]:
        log: AuditLog = request.app.state.audit
        return {"entries": log.entries(actor_id=actor_id or None, action=action or None,
                                       target=target or None, limit=limit)}

    def _close_on_shutdown() -> None:
        log = getattr(app.state, "audit", None)
        if log is not None:
            log.close()

    _register_shutdown_close(app, _close_on_shutdown)
    return app.state.audit
