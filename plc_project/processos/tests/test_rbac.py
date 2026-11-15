"""PLAN §7 · RBAC tests: matrix integrity, actor resolution, role gating,
approver separation, audit ledger and the /api/processos/rbac routes.

Windows note: every AuditLog connection is closed explicitly (try/finally) so
tmp_path cleanup never hits WinError 32 on an open sqlite handle.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from processos.rbac import (
    PERMISSIONS,
    ROLES,
    Actor,
    AuditLog,
    assert_approver_separation,
    audit_forbidden,
    get_actor,
    register_routes,
    require_role,
    role_matrix,
)

# --- 1. matrix integrity ---------------------------------------------------


def test_role_matrix_complete_and_serializable():
    m = role_matrix()
    assert m["roles"] == list(ROLES)
    assert len(ROLES) == 7
    covered: set[str] = set()
    for action, roles in m["permissions"].items():
        assert action in PERMISSIONS
        assert len(roles) >= 1, f"action {action} has no role"
        assert set(roles) <= set(ROLES), f"action {action} has unknown roles"
        covered.update(roles)
    assert covered == set(ROLES), f"roles missing from matrix: {set(ROLES) - covered}"
    # JSON round-trip (matrix goes verbatim into API responses)
    assert json.loads(json.dumps(m)) == m


# --- 2. get_actor -----------------------------------------------------------


def _actor_app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    def who(actor: Annotated[Actor, Depends(get_actor)]):
        return {"actor_id": actor.actor_id, "role": actor.role, "details": actor.details}

    return app


def test_get_actor_with_headers():
    client = TestClient(_actor_app())
    r = client.get("/who", headers={"X-Actor-Id": "eng-1", "X-Actor-Role": "FieldEngineer"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"actor_id": "eng-1", "role": "FieldEngineer", "details": {}}


def test_get_actor_defaults_without_headers():
    client = TestClient(_actor_app())
    r = client.get("/who")
    assert r.status_code == 200
    body = r.json()
    assert body == {"actor_id": "anonymous", "role": "Viewer", "details": {}}


def test_get_actor_invalid_role_falls_back_to_viewer():
    client = TestClient(_actor_app())
    r = client.get("/who", headers={"X-Actor-Id": "eng-9", "X-Actor-Role": "Root"})
    assert r.status_code == 200
    body = r.json()
    assert body["actor_id"] == "eng-9"
    assert body["role"] == "Viewer"  # fail closed to least privilege
    assert body["details"] == {"invalid_role": "Root"}


# --- 3. require_role --------------------------------------------------------


def _gate_app() -> FastAPI:
    app = FastAPI()

    @app.get("/by-role")
    def by_role(actor: Annotated[Actor, Depends(require_role("Reviewer"))]):
        return {"actor_id": actor.actor_id}

    @app.get("/by-action")
    def by_action(actor: Annotated[Actor, Depends(require_role(action="changeset.approve"))]):
        return {"actor_id": actor.actor_id}

    return app


def test_require_role_mode_allows_and_denies():
    client = TestClient(_gate_app())
    r = client.get("/by-role", headers={"X-Actor-Role": "Reviewer"})
    assert r.status_code == 200
    r = client.get("/by-role", headers={"X-Actor-Role": "Viewer"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "ROLE_FORBIDDEN"
    assert detail["required"] == ["Reviewer"]
    assert detail["actor"]["role"] == "Viewer"


def test_require_action_mode_matrix_lookup():
    client = TestClient(_gate_app())
    for role in ("Reviewer", "ReleaseApprover", "Admin"):
        r = client.get("/by-action", headers={"X-Actor-Role": role})
        assert r.status_code == 200, role
    r = client.get("/by-action", headers={"X-Actor-Role": "Builder"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "ROLE_FORBIDDEN"
    assert detail["required"] == ["Reviewer", "ReleaseApprover", "Admin"]


def test_require_role_rejects_unknown_names_at_wiring_time():
    with pytest.raises(ValueError):
        require_role("NopeRole")
    with pytest.raises(ValueError):
        require_role(action="not.an.action")
    with pytest.raises(ValueError):
        require_role()


# --- 4. approver separation -------------------------------------------------


def test_separation_blocks_same_actor_for_high_risk():
    approver = Actor("eng-1", "Reviewer")
    with pytest.raises(HTTPException) as ei:
        assert_approver_separation(approver, "eng-1", high_risk=True)
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "APPROVER_SEPARATION"


def test_separation_allows_different_actor_or_low_risk():
    approver = Actor("eng-1", "Reviewer")
    assert_approver_separation(approver, "eng-2", high_risk=True)  # different ids
    assert_approver_separation(approver, "eng-1", high_risk=False)  # low risk


# --- 5. AuditLog ------------------------------------------------------------


def test_audit_record_filters_ordering(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite3")
    try:
        eng, adm = Actor("eng-1", "FieldEngineer"), Actor("adm-1", "Admin")
        log.record(eng, "incident.create", "INC-1")
        log.record(eng, "changeset.propose", "CS-1", extra={"high_risk": True})
        log.record(adm, "rbac.audit.read", "audit")
        log.record(adm, "incident.create", "INC-1", result="DENIED")

        all_e = log.entries()
        assert [e["action"] for e in all_e] == [
            "incident.create", "rbac.audit.read", "changeset.propose", "incident.create",
        ]  # newest first
        for e in all_e:
            assert {"ts", "seq", "actor_id", "role", "action", "target", "result", "extra"} <= set(e)
            assert e["extra"] == {} or isinstance(e["extra"], dict)

        assert [e["target"] for e in log.entries(actor_id="eng-1")] == ["CS-1", "INC-1"]
        assert [e["actor_id"] for e in log.entries(action="incident.create")] == ["adm-1", "eng-1"]
        assert log.entries(target="CS-1")[0]["extra"] == {"high_risk": True}
        denied = [e for e in all_e if e["result"] == "DENIED"]
        assert [e["actor_id"] for e in denied] == ["adm-1"]
        assert len(log.entries(limit=1)) == 1
        assert len(log.entries(limit=2)) == 2
        assert log.entries(actor_id="nobody") == []
    finally:
        log.close()


def test_audit_persistence_roundtrip(tmp_path):
    db_file = tmp_path / "audit.sqlite3"
    log = AuditLog(db_file)
    log.record(Actor("eng-1", "FieldEngineer"), "incident.create", "INC-1")
    log.close()  # Windows: release the handle before reopening
    reopened = AuditLog(db_file)
    try:
        assert [e["target"] for e in reopened.entries()] == ["INC-1"]
        # seq continues after reopen, so the new entry is newest first
        reopened.record(Actor("eng-1", "FieldEngineer"), "incident.create", "INC-2")
        assert [e["target"] for e in reopened.entries()] == ["INC-2", "INC-1"]
        assert reopened.entries()[0]["result"] == "OK"
    finally:
        reopened.close()


def test_audit_forbidden_hook_records_denial(tmp_path):
    app = FastAPI()
    register_routes(app, db_file=tmp_path / "hook.sqlite3")

    @app.get("/_demo_gate")
    def demo_gate(actor: Annotated[Actor, Depends(require_role(action="changeset.approve"))]):
        return {"ok": True}

    @app.exception_handler(HTTPException)
    async def _audit_and_default(request: Request, exc: HTTPException):
        if exc.status_code == 403 and isinstance(exc.detail, dict):
            audit_forbidden(request, exc.detail.get("action") or request.url.path)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    client = TestClient(app)
    try:
        r = client.get("/_demo_gate", headers={"X-Actor-Id": "eng-1", "X-Actor-Role": "Viewer"})
        assert r.status_code == 403
        entries = app.state.audit.entries(action="changeset.approve")
        assert len(entries) == 1
        e = entries[0]
        assert e["result"] == "FORBIDDEN"
        assert e["actor_id"] == "eng-1"
        assert e["role"] == "Viewer"
        assert e["target"] == "/_demo_gate"
        assert e["extra"]["code"] == "ROLE_FORBIDDEN"
    finally:
        app.state.audit.close()


# --- 6. register_routes + TestClient ----------------------------------------


def test_register_routes_roles_and_audit_endpoints(tmp_path):
    app = FastAPI()
    register_routes(app, db_file=tmp_path / "rbac.sqlite3")
    route_count = len(app.routes)
    register_routes(app, db_file=tmp_path / "unused.sqlite3")  # idempotent, no overwrite
    assert len(app.routes) == route_count

    client = TestClient(app)
    try:
        # roles: public metadata, no identity needed
        r = client.get("/api/processos/rbac/roles")
        assert r.status_code == 200
        assert r.json() == role_matrix()
        assert r.json()["roles"] == list(ROLES)

        # audit: Viewer (default, no headers) -> 403 ROLE_FORBIDDEN
        r = client.get("/api/processos/rbac/audit")
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "ROLE_FORBIDDEN"
        assert r.json()["detail"]["required"] == ["Admin"]

        # audit: Admin -> 200 with recorded entries
        app.state.audit.record(Actor("eng-1", "FieldEngineer"), "incident.create", "INC-1")
        app.state.audit.record(Actor("adm-1", "Admin"), "rbac.audit.read", "audit")
        r = client.get("/api/processos/rbac/audit",
                       headers={"X-Actor-Id": "adm-1", "X-Actor-Role": "Admin"})
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert [e["target"] for e in entries] == ["audit", "INC-1"]

        r = client.get("/api/processos/rbac/audit",
                       headers={"X-Actor-Role": "Admin"},
                       params={"actor_id": "eng-1", "action": "incident.create", "limit": 5})
        assert r.status_code == 200
        assert [e["actor_id"] for e in r.json()["entries"]] == ["eng-1"]
    finally:
        app.state.audit.close()


def test_register_routes_closes_audit_connection_on_shutdown(tmp_path):
    app = FastAPI()
    log = register_routes(app, db_file=tmp_path / "shutdown.sqlite3")
    with TestClient(app) as client:  # context manager runs the app lifespan
        r = client.get("/api/processos/rbac/roles")
        assert r.status_code == 200
    with pytest.raises(sqlite3.ProgrammingError):  # connection was closed
        log.record(Actor("eng-1", "FieldEngineer"), "incident.create", "INC-1")
