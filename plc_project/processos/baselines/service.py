"""FC-03 · Three baselines (B1/B2/B3), two comparisons and the DriftGate (PLAN §4/§11).

B1 Design Baseline — the approved/frozen process IR spec hash (``contract_spec_hash``
at freeze time) bound to a revision and AF profile.
B2 Native Baseline — the SHA256 of the TIA archive built from B1 plus a per-block
manifest ``{block_name: sha256}``; a different version appends a new record
(history is preserved, same content rewrites idempotently).
B3 Deployed Baseline — the field-verified identity of what actually runs on the
PLC. A Build-ID self-report is NOT field verification: ``SELF_REPORTED`` records
stay ``UNVERIFIED_ONLINE`` and block the gate (PLAN §4: B3 不能仅凭 Build ID 自报).

First comparison (开工前, ``gate_change``): B2 vs B3 — drift freezes all changes.
Second comparison (交付前, ``gate_delivery``): approved spec hash vs build input
hash; a stale approval invalidates delivery. Every blocked path raises
``SafetyError`` (fail-closed, §12: never downgraded to a warning); missing
evidence is reported as UNKNOWN/None, never fabricated.

Persistence: ``JsonDao`` namespace ``"baselines"`` over the shared SQLite store.
``processos.store.db.open_db`` pins its connection to the creating thread, so the
service opens — and always closes — one connection per operation: safe for
FastAPI sync routes (which run off-thread) and leaves no handle behind on
Windows temp-dir cleanup.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from processos.safety import SafetyError, register_safety_exception_handler
from processos.store import JsonDao, db_path, open_db, utcnow

NAMESPACE = "baselines"

_VERIFICATIONS = ("FIELD_VERIFIED", "SELF_REPORTED")

_B1_FIELDS = ("spec_hash", "revision", "profile_id")
_B2_FIELDS = ("build_id", "archive_sha256", "block_manifest")
_B3_FIELDS = ("deployed_build_id", "verification", "plc_checksum", "device_id",
              "operator", "commissioned_at")


def _digest(*parts: Any) -> str:
    """Content-derived record suffix: same content rewrites, new content appends."""
    return hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:16]


def _summary(record: dict[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if record is None:
        return None
    out = {k: record.get(k) for k in ("baseline_id", "kind", "project_id", "status", "created_at")}
    out.update({f: record.get(f) for f in fields})
    return out


class BaselineService:
    """SQLite-backed B1/B2/B3 ledger + DriftGate (fail-closed per PLAN §4/§11)."""

    def __init__(self, db: str | os.PathLike[str] | None = None) -> None:
        self._path = db_path(db)
        self._lock = threading.RLock()  # serialise writes in-process (gateway v2 idiom)

    # ---------- persistence helpers ----------

    @contextmanager
    def _dao(self) -> Iterator[JsonDao]:
        """One short-lived connection per operation (see module docstring)."""
        with contextlib.closing(open_db(self._path)) as conn:
            yield JsonDao(conn, NAMESPACE)

    @staticmethod
    def _records(dao: JsonDao, project_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        return [r for r in dao.list_by_kind(kind) if r.get("project_id") == project_id]

    @staticmethod
    def _latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
        return max(records, key=lambda r: r.get("seq", 0)) if records else None

    def _put(self, dao: JsonDao, item_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Idempotent upsert: same content -> same id -> rewrite (seq/created_at kept)."""
        existing = dao.get(item_id)
        if existing is None:
            seq = max((r.get("seq", 0) for r in self._records(dao, payload["project_id"])), default=0) + 1
            payload = {**payload, "seq": seq, "created_at": utcnow()}
        else:
            payload = {**payload, "seq": existing["seq"], "created_at": existing["created_at"]}
        dao.put(item_id, kind, {"baseline_id": item_id, **payload})
        return {"baseline_id": item_id, "kind": kind, **payload}

    # ---------- B1 design baseline ----------

    def record_b1(self, project_id: str, spec_hash: str, revision: int,
                  profile_id: str = "") -> dict[str, Any]:
        payload = {"kind": "B1", "project_id": project_id, "spec_hash": spec_hash,
                   "revision": revision, "profile_id": profile_id, "status": "FROZEN"}
        item_id = f"B1:{project_id}:{_digest(spec_hash, revision, profile_id)}"
        with self._lock, self._dao() as dao:
            return self._put(dao, item_id, "B1", payload)

    # ---------- B2 native baseline ----------

    def record_b2(self, project_id: str, build_id: str, archive_sha256: str,
                  block_manifest: dict[str, str] | None = None) -> dict[str, Any]:
        manifest = dict(block_manifest or {})
        payload = {"kind": "B2", "project_id": project_id, "build_id": build_id,
                   "archive_sha256": archive_sha256, "block_manifest": manifest,
                   "status": "FROZEN"}
        item_id = ("B2:" + project_id + ":" +
                   _digest(build_id, archive_sha256, json.dumps(manifest, sort_keys=True, ensure_ascii=False)))
        with self._lock, self._dao() as dao:
            return self._put(dao, item_id, "B2", payload)

    # ---------- B3 deployed baseline ----------

    def record_b3(self, project_id: str, deployed_build_id: str, *,
                  verification: Literal["FIELD_VERIFIED", "SELF_REPORTED"],
                  plc_checksum: str | None = None, device_id: str | None = None,
                  operator: str | None = None,
                  commissioned_at: str | None = None) -> dict[str, Any]:
        if verification not in _VERIFICATIONS:
            raise ValueError(f"verification must be one of {_VERIFICATIONS}, got {verification!r}")
        # B3 不能仅凭 Build ID 自报：only a field verification may claim VERIFIED.
        status = "VERIFIED" if verification == "FIELD_VERIFIED" else "UNVERIFIED_ONLINE"
        payload = {"kind": "B3", "project_id": project_id,
                   "deployed_build_id": deployed_build_id, "verification": verification,
                   "plc_checksum": plc_checksum, "device_id": device_id,
                   "operator": operator, "commissioned_at": commissioned_at,
                   "status": status}
        item_id = ("B3:" + project_id + ":" +
                   _digest(deployed_build_id, verification, plc_checksum,
                           device_id, operator, commissioned_at))
        with self._lock, self._dao() as dao:
            return self._put(dao, item_id, "B3", payload)

    # ---------- queries ----------

    def baselines(self, project_id: str) -> list[dict[str, Any]]:
        """All baseline records of a project, oldest first (B2/B3 history kept)."""
        with self._dao() as dao:
            records = self._records(dao, project_id)
        return sorted(records, key=lambda r: (r.get("seq", 0), r.get("baseline_id", "")))

    def plc_state_known(self, project_id: str) -> bool:
        """True only when a field-VERIFIED B3 exists (PLAN §11 UNKNOWN_PLC_STATE)."""
        with self._dao() as dao:
            b3 = self._latest(self._records(dao, project_id, "B3"))
        return b3 is not None and b3.get("status") == "VERIFIED"

    def compare(self, project_id: str) -> dict[str, Any]:
        """First comparison B2 vs B3; never raises — the verdict + differences speak.

        verdict: OK_TO_PROCEED (B3 field-verified, bound to a recorded B2 and
        checksum-matching) | FROZEN_DRIFT (any fail-closed mismatch/unknown) |
        UNVERIFIED_ONLINE (no B3 or Build-ID self-report only).
        """
        with self._dao() as dao:
            b1 = self._latest(self._records(dao, project_id, "B1"))
            b2_records = self._records(dao, project_id, "B2")
            b2 = self._latest(b2_records)
            b3 = self._latest(self._records(dao, project_id, "B3"))
        differences: list[dict[str, str]] = []
        b2_vs_b3 = "UNKNOWN"
        verdict = "UNVERIFIED_ONLINE"

        if b3 is None:
            differences.append({"kind": "NO_B3",
                                "detail": "no deployed baseline recorded: field PLC state unknown"})
        elif b3.get("status") != "VERIFIED":
            differences.append({"kind": "UNVERIFIED_ONLINE",
                                "detail": "B3 is a Build-ID self-report, not field verification"})
        else:
            bound = True
            if b2 is None:
                differences.append({"kind": "NO_B2",
                                    "detail": "B3 is field-verified but no native baseline (B2) exists"})
            else:
                reference = self._latest([r for r in b2_records
                                          if r.get("build_id") == b3.get("deployed_build_id")])
                if reference is None:
                    bound = False
                    reference = b2
                    differences.append({
                        "kind": "UNKNOWN_BUILD_BINDING",
                        "detail": f"deployed build {b3.get('deployed_build_id')!r} matches no "
                                  f"recorded B2; checksum only cross-checked against latest B2 "
                                  f"{b2.get('build_id')!r}"})
                checksum = b3.get("plc_checksum")
                if not checksum:
                    differences.append({"kind": "MISSING_PLC_CHECKSUM",
                                        "detail": "field verification recorded no PLC checksum"})
                elif checksum != reference.get("archive_sha256"):
                    differences.append({
                        "kind": "ARCHIVE_SHA256_MISMATCH",
                        "detail": f"plc checksum {checksum} != B2 archive "
                                  f"{reference.get('archive_sha256')} (build {reference.get('build_id')})"})
                    if bound:
                        b2_vs_b3 = "DRIFT"
                elif bound:
                    b2_vs_b3 = "MATCH"
                # unbound: a checksum match against an unproven reference proves nothing
            # Fail-closed (§12): only a bound, checksum-matched comparison may proceed.
            verdict = "OK_TO_PROCEED" if (b2 is not None and bound and b2_vs_b3 == "MATCH") \
                else "FROZEN_DRIFT"

        return {
            "project_id": project_id,
            "verdict": verdict,
            "b2_vs_b3": b2_vs_b3,
            "latest_b1": _summary(b1, _B1_FIELDS),
            "latest_b2": _summary(b2, _B2_FIELDS),
            "latest_b3": _summary(b3, _B3_FIELDS),
            "differences": differences,
        }

    # ---------- gates ----------

    def gate_change(self, project_id: str) -> dict[str, Any]:
        """DriftGate — first comparison before any work starts (PLAN §4)."""
        result = self.compare(project_id)
        verdict = result["verdict"]
        if verdict == "OK_TO_PROCEED":
            return {"ok": True, "verdict": verdict, "compare": result}
        code = "UNKNOWN_PLC_STATE" if verdict == "UNVERIFIED_ONLINE" else "DRIFT_DETECTED"
        raise SafetyError(
            code,
            f"DriftGate blocked {project_id}: {verdict}",
            details={"verdict": verdict, "differences": result["differences"]},
            http_status=409,
        )

    def gate_delivery(self, project_id: str, approved_spec_hash: str,
                      build_input_spec_hash: str) -> dict[str, Any]:
        """Second comparison before delivery: approved spec hash vs build input."""
        with self._dao() as dao:
            has_b1 = self._latest(self._records(dao, project_id, "B1")) is not None
        if not has_b1:
            raise SafetyError(
                "DRIFT_DETECTED",
                f"delivery gate blocked {project_id}: no frozen B1 design baseline",
                details={"reason": "missing B1"}, http_status=409,
            )
        if approved_spec_hash != build_input_spec_hash:
            raise SafetyError(
                "BUILD_ARTIFACT_MISMATCH",
                f"delivery gate blocked {project_id}: build input hash != approved spec hash",
                details={"approved_spec_hash": approved_spec_hash,
                         "build_input_spec_hash": build_input_spec_hash},
                http_status=409,
            )
        return {"ok": True, "approved_spec_hash": approved_spec_hash}


# ---------- HTTP layer ----------

class B1Body(BaseModel):
    spec_hash: str
    revision: int
    profile_id: str = ""


class B2Body(BaseModel):
    build_id: str
    archive_sha256: str
    block_manifest: dict[str, str] = Field(default_factory=dict)


class B3Body(BaseModel):
    deployed_build_id: str
    verification: Literal["FIELD_VERIFIED", "SELF_REPORTED"]
    plc_checksum: str | None = None
    device_id: str | None = None
    operator: str | None = None
    commissioned_at: str | None = None


_ROUTES_FLAG = "_baselines_routes_mounted"


def register_routes(app: FastAPI) -> None:
    """Idempotently mount the baseline routes on a FastAPI app.

    Creates ``app.state.baselines`` (env ``PROCESSOS_DB`` / default path) only if
    absent — tests inject their own service over a ``tmp_path`` database first.
    SafetyError is surfaced as ``{error, code, details}`` via the shared handler.
    """
    if getattr(app.state, "baselines", None) is None:
        app.state.baselines = BaselineService()
    if getattr(app.state, _ROUTES_FLAG, False):
        return
    setattr(app.state, _ROUTES_FLAG, True)
    register_safety_exception_handler(app)

    def svc(request: Request) -> BaselineService:
        return request.app.state.baselines

    def require_project(request: Request, pid: str) -> None:
        store = getattr(request.app.state, "store", None)
        if store is None or pid not in store.projects:
            raise HTTPException(status_code=404, detail=f"unknown project {pid}")

    @app.get("/api/processos/projects/{pid}/baselines")
    def list_baselines(request: Request, pid: str) -> dict[str, Any]:
        require_project(request, pid)
        return {"baselines": svc(request).baselines(pid)}

    @app.post("/api/processos/projects/{pid}/baselines/b1")
    def post_b1(request: Request, pid: str, body: B1Body) -> dict[str, Any]:
        require_project(request, pid)
        return svc(request).record_b1(pid, body.spec_hash, body.revision, body.profile_id)

    @app.post("/api/processos/projects/{pid}/baselines/b2")
    def post_b2(request: Request, pid: str, body: B2Body) -> dict[str, Any]:
        require_project(request, pid)
        return svc(request).record_b2(pid, body.build_id, body.archive_sha256, body.block_manifest)

    @app.post("/api/processos/projects/{pid}/baselines/b3")
    def post_b3(request: Request, pid: str, body: B3Body) -> dict[str, Any]:
        require_project(request, pid)
        return svc(request).record_b3(pid, body.deployed_build_id, verification=body.verification,
                                      plc_checksum=body.plc_checksum, device_id=body.device_id,
                                      operator=body.operator, commissioned_at=body.commissioned_at)

    @app.post("/api/processos/projects/{pid}/baselines/compare")
    def post_compare(request: Request, pid: str) -> dict[str, Any]:
        require_project(request, pid)
        return svc(request).compare(pid)

    @app.post("/api/processos/projects/{pid}/baselines/gate")
    def post_gate(request: Request, pid: str) -> dict[str, Any]:
        require_project(request, pid)
        return svc(request).gate_change(pid)
