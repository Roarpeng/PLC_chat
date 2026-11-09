"""SQLite WAL persistence for V2 workspaces (design 6 / G1).

Standard library ``sqlite3`` only — no ORM, no new dependency. Ten tables are
created exactly as frozen in the design; ``revisions.result_json`` is a T01
column addition required to return the FIRST PatchResult on an idempotent retry.

Every write is serialised by an in-process lock plus ``BEGIN IMMEDIATE``; the
IR itself is stored as an immutable, versioned JSON file whose filename embeds
its content hash.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from plc_engine.engineering_ir.contracts import assert_stable_id, can_transition
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import (
    CandidatePatch,
    ChangeOp,
    ChangeSet,
    EngineeringIRV2,
    NativeTiaArtifact,
    PatchResultV2,
    ProjectWorkspace,
    TiaCapabilityManifest,
    ValidationReport,
)
from plc_engine.engineering_ir.patch import apply_patch_atomic

SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, origin TEXT NOT NULL, tia_version TEXT NOT NULL DEFAULT 'V19',
  af_profile TEXT NOT NULL, library_version TEXT NOT NULL, template_sha256 TEXT NOT NULL,
  current_revision INTEGER NOT NULL DEFAULT 0, baseline_hash TEXT,
  base_artifact_id TEXT, state TEXT NOT NULL DEFAULT 'DRAFT',
  evidence_level TEXT NOT NULL DEFAULT 'pending_real_machine',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
  project_id TEXT NOT NULL, revision INTEGER NOT NULL, ir_hash TEXT NOT NULL,
  ir_artifact_id TEXT NOT NULL, author TEXT, request_id TEXT,
  result_json TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (project_id, revision),
  FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS changesets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, base_revision INTEGER NOT NULL,
  before_hash TEXT NOT NULL, after_hash TEXT NOT NULL, spec_hash TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS change_ops (
  changeset_id TEXT NOT NULL, seq INTEGER NOT NULL,
  op_type TEXT NOT NULL, target_source_id TEXT, ir_id TEXT,
  payload_json TEXT NOT NULL, source_id TEXT,
  PRIMARY KEY (changeset_id, seq),
  FOREIGN KEY (changeset_id) REFERENCES changesets(id)
);
CREATE TABLE IF NOT EXISTS approvals (
  changeset_id TEXT PRIMARY KEY, reviewer TEXT NOT NULL,
  signed_spec_hash TEXT NOT NULL, signed_baseline_hash TEXT NOT NULL,
  explicit INTEGER NOT NULL DEFAULT 1, signed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, job_id TEXT NOT NULL,
  kind TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL, evidence_level TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (project_id, job_id, id, sha256)
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, changeset_id TEXT NOT NULL,
  state TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  expected_baseline_hash TEXT NOT NULL, stage_cursor TEXT,
  worker_lease_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
  job_id TEXT NOT NULL, seq INTEGER NOT NULL, state TEXT NOT NULL,
  stage TEXT, raw_api_receipt TEXT, evidence_level TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS capability_manifest (
  probe_receipt_id TEXT PRIMARY KEY, tia_version TEXT NOT NULL,
  cpu_templates_json TEXT NOT NULL, probed_at TEXT NOT NULL,
  raw_probe_receipt TEXT NOT NULL, evidence_level TEXT NOT NULL DEFAULT 'V19_real'
);
CREATE TABLE IF NOT EXISTS project_locks (
  project_id TEXT PRIMARY KEY, owner_job_id TEXT, lease_until TEXT
);
CREATE INDEX IF NOT EXISTS idx_revisions_project ON revisions(project_id, revision DESC);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, seq);
CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(project_id, job_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_revisions_request
  ON revisions(project_id, request_id) WHERE request_id IS NOT NULL AND request_id <> '';
"""


def utc_now() -> str:
    """ISO 8601 UTC timestamp (receipts / ledger only, never semantic files)."""
    return datetime.now(UTC).isoformat()


class ProjectNotFoundError(LookupError):
    """Raised when a project id is unknown (routed to HTTP 404)."""


class StateTransitionError(RuntimeError):
    """Raised on an illegal delivery state transition (fail-closed)."""


class WorkspaceStore:
    """Thread-safe SQLite WAL store for V2 workspaces, jobs and artifacts."""

    def __init__(self, db_path: str | Path | None = None, ir_store_dir: str | Path | None = None) -> None:
        raw_db = db_path or os.getenv("PLC_V2_DB_PATH") or ""
        self.db_path = str(raw_db) if raw_db else ":memory:"
        if ir_store_dir:
            self.ir_store_root = Path(ir_store_dir)
        elif self.db_path == ":memory:":
            self.ir_store_root = Path(os.getenv("PLC_V2_IR_STORE", "evidence/v2/_ir_store"))
        else:
            self.ir_store_root = Path(self.db_path).resolve().parent / "ir_store"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass  # :memory: has no WAL mode; still fully functional
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA_SQL)

    # -------------------------------------------------------------- helpers --
    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._conn.close()

    @contextmanager
    def _transaction(self):
        """Explicit BEGIN IMMEDIATE write transaction with rollback on failure."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _project_dir(self, project_id: str) -> Path:
        assert_stable_id(project_id, "project")
        return self.ir_store_root / project_id

    def _write_ir_file(self, ir: EngineeringIRV2) -> str:
        """Persist one immutable, hash-named IR JSON file; return its id."""
        folder = self._project_dir(ir.project_id)
        folder.mkdir(parents=True, exist_ok=True)
        digest = ir.ir_sha256 or ir.refresh_hash()
        short = digest[7:15] if digest.startswith("sha256:") else digest[:8]
        artifact_id = f"{ir.revision}-{short}.json"
        target = folder / artifact_id
        if not target.exists():
            temporary = folder / f".{artifact_id}.tmp"
            temporary.write_text(
                json.dumps(ir.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, target)
        return artifact_id

    # ------------------------------------------------------------- projects --
    def create_project(
        self,
        project_id: str,
        ir: EngineeringIRV2,
        *,
        origin: str = "greenfield",
        author: str = "system",
    ) -> ProjectWorkspace:
        """Create a project and its revision-0 IR snapshot."""
        assert_stable_id(project_id, "project")
        if ir.project_id != project_id:
            raise ValueError("ir.project_id must equal the requested project_id")
        ir.revision = 0
        ir.refresh_hash()
        now = utc_now()
        with self._transaction():
            existing = self._conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
            if existing is not None:
                raise ValueError(f"project {project_id!r} already exists")
            artifact_id = self._write_ir_file(ir)
            self._conn.execute(
                "INSERT INTO projects (id, origin, tia_version, af_profile, library_version, "
                "template_sha256, current_revision, baseline_hash, state, evidence_level, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    project_id, origin, ir.af_profile.tia_version, ir.af_profile.profile_id,
                    ir.af_profile.library_version, ir.af_profile.template_sha256, 0,
                    ir.ir_sha256, "DRAFT", EvidenceLevel.PENDING_REAL_MACHINE.value, now, now,
                ),
            )
            self._conn.execute(
                "INSERT INTO revisions (project_id, revision, ir_hash, ir_artifact_id, author, request_id, result_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (project_id, 0, ir.ir_sha256, artifact_id, author, "", None, now),
            )
        workspace = self.get_project(project_id)
        workspace.bind_store(self)
        return workspace

    def get_project(self, project_id: str) -> ProjectWorkspace:
        """Load project metadata; raises ProjectNotFoundError when absent."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        workspace = ProjectWorkspace(
            project_id=row["id"],
            origin=row["origin"],
            tia_version=row["tia_version"],
            baseline_hash=row["baseline_hash"] or "",
            current_revision=int(row["current_revision"]),
            state=row["state"],
            evidence_level=EvidenceLevel.parse(row["evidence_level"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        workspace.bind_store(self)
        return workspace

    def project_exists(self, project_id: str) -> bool:
        """Return whether a project exists."""
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
        return row is not None

    def get_ir(self, project_id: str, revision: int | None = None) -> EngineeringIRV2:
        """Read the authoritative IR at a given revision (latest by default)."""
        with self._lock:
            if revision is None:
                row = self._conn.execute(
                    "SELECT * FROM revisions WHERE project_id=? ORDER BY revision DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM revisions WHERE project_id=? AND revision=?",
                    (project_id, int(revision)),
                ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        path = self._project_dir(project_id) / row["ir_artifact_id"]
        if not path.is_file():
            raise FileNotFoundError(f"IR artifact missing: {path}")
        return EngineeringIRV2.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def next_revision(self, project_id: str) -> int:
        """Return the revision that a successful next patch would produce."""
        project = self.get_project(project_id)
        return int(project.current_revision) + 1

    def list_revisions(self, project_id: str) -> list[dict[str, Any]]:
        """List all revisions (newest first)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT revision, ir_hash, request_id, author, created_at FROM revisions "
                "WHERE project_id=? ORDER BY revision DESC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- patches --
    def commit_patch(self, project_id: str, patch: CandidatePatch) -> PatchResultV2:
        """Atomically validate and commit a patch (409/422 raised by kernel)."""
        with self._transaction():
            row = self._conn.execute("SELECT current_revision FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise ProjectNotFoundError(project_id)
            current = int(row["current_revision"])
            if patch.request_id:
                prior = self._conn.execute(
                    "SELECT revision, ir_hash, result_json FROM revisions "
                    "WHERE project_id=? AND request_id=? AND request_id<>''",
                    (project_id, patch.request_id),
                ).fetchone()
                if prior is not None:
                    if prior["result_json"]:
                        result = PatchResultV2.from_dict(json.loads(prior["result_json"]))
                        result.idempotent_hit = True
                        return result
                    return PatchResultV2(
                        revision=int(prior["revision"]),
                        ir_sha256=str(prior["ir_hash"]),
                        request_id=patch.request_id,
                        idempotent_hit=True,
                    )
            ir = self.get_ir(project_id, current)
            candidate, result = apply_patch_atomic(ir, patch)
            artifact_id = self._write_ir_file(candidate)
            self._conn.execute(
                "INSERT INTO revisions (project_id, revision, ir_hash, ir_artifact_id, author, request_id, result_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    project_id, result.revision, result.ir_sha256, artifact_id,
                    "api", patch.request_id, json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True), utc_now(),
                ),
            )
            self._conn.execute(
                "UPDATE projects SET current_revision=?, baseline_hash=?, updated_at=? WHERE id=?",
                (result.revision, result.ir_sha256, utc_now(), project_id),
            )
            return result

    # ------------------------------------------------------------ changesets --
    def insert_changeset(self, changeset: ChangeSet) -> ChangeSet:
        """Persist a frozen ChangeSet and its ops atomically."""
        with self._transaction():
            self._conn.execute(
                "INSERT INTO changesets (id, project_id, base_revision, before_hash, after_hash, spec_hash, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    changeset.id, changeset.project_id, changeset.base_revision,
                    changeset.before_hash, changeset.after_hash, changeset.spec_hash,
                    changeset.status, changeset.created_at or utc_now(),
                ),
            )
            for seq, op in enumerate(changeset.ops):
                self._conn.execute(
                    "INSERT INTO change_ops (changeset_id, seq, op_type, target_source_id, ir_id, payload_json, source_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        changeset.id, seq, op.op, op.target_source_id, op.ir_id,
                        json.dumps(op.payload, ensure_ascii=False, sort_keys=True), op.source_id,
                    ),
                )
        return changeset

    def get_changeset(self, changeset_id: str) -> ChangeSet | None:
        """Load a ChangeSet with its ops (validation report is reconstructed)."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM changesets WHERE id=?", (changeset_id,)).fetchone()
            if row is None:
                return None
            ops = self._conn.execute(
                "SELECT * FROM change_ops WHERE changeset_id=? ORDER BY seq", (changeset_id,)
            ).fetchall()
            approval = self._conn.execute(
                "SELECT * FROM approvals WHERE changeset_id=?", (changeset_id,)
            ).fetchone()
        return ChangeSet(
            id=row["id"], project_id=row["project_id"], base_revision=int(row["base_revision"]),
            before_hash=row["before_hash"], after_hash=row["after_hash"], spec_hash=row["spec_hash"],
            status=row["status"], created_at=row["created_at"],
            ops=[
                ChangeOp(
                    op=op["op_type"], target_source_id=op["target_source_id"] or "",
                    ir_id=op["ir_id"] or "", payload=json.loads(op["payload_json"]),
                    source_id=op["source_id"] or "",
                )
                for op in ops
            ],
            validation=ValidationReport(passed=row["status"] != "FAILED"),
            review_approved=approval is not None,
            approved_by=approval["reviewer"] if approval else "",
            signed_spec_hash=approval["signed_spec_hash"] if approval else "",
            signed_baseline_hash=approval["signed_baseline_hash"] if approval else "",
            signed_at=approval["signed_at"] if approval else "",
            explicit=bool(approval["explicit"]) if approval else False,
        )

    def approve_changeset(
        self,
        changeset_id: str,
        *,
        reviewer: str,
        explicit: bool,
        expected_baseline_hash: str,
    ) -> ChangeSet:
        """Explicit human approval with baseline recheck (409 on drift)."""
        from plc_engine.engineering_ir.contracts import ErrorCode

        changeset = self.get_changeset(changeset_id)
        if changeset is None:
            raise ProjectNotFoundError(changeset_id)
        if not explicit:
            raise PermissionError("approval requires explicit=True (human sign-off)")
        project = self.get_project(changeset.project_id)
        actual = project.baseline_hash or ""
        if expected_baseline_hash and actual != expected_baseline_hash:
            raise ValueError(f"{ErrorCode.BASELINE_HASH_MISMATCH.value}: expected {expected_baseline_hash}, actual {actual}")
        now = utc_now()
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO approvals (changeset_id, reviewer, signed_spec_hash, signed_baseline_hash, explicit, signed_at) "
                "VALUES (?,?,?,?,?,?)",
                (changeset_id, reviewer, changeset.spec_hash, actual, 1 if explicit else 0, now),
            )
            self._conn.execute(
                "UPDATE changesets SET status='APPROVED' WHERE id=?", (changeset_id,)
            )
        approved = self.get_changeset(changeset_id)
        assert approved is not None
        return approved

    # -------------------------------------------------------------------- jobs --
    def insert_job(
        self,
        job_id: str,
        *,
        project_id: str,
        changeset_id: str,
        idempotency_key: str,
        expected_baseline_hash: str,
        state: str = "QUEUED",
    ) -> tuple[dict[str, Any], bool]:
        """Insert a job; an existing idempotency_key returns ``(existing, False)``."""
        with self._transaction():
            existing = self._conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                return dict(existing), False
            now = utc_now()
            self._conn.execute(
                "INSERT INTO jobs (id, project_id, changeset_id, state, idempotency_key, "
                "expected_baseline_hash, stage_cursor, worker_lease_until, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (job_id, project_id, changeset_id, state, idempotency_key,
                 expected_baseline_hash, None, None, now, now),
            )
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row), True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Load a job row."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def update_job_state(
        self,
        job_id: str,
        state: str,
        *,
        stage_cursor: str | None = None,
        worker_lease_until: str | None = None,
    ) -> dict[str, Any]:
        """Advance a job state with fail-closed transition checking."""
        current = self.get_job(job_id)
        if current is None:
            raise ProjectNotFoundError(job_id)
        if current["state"] != state and not can_transition(str(current["state"]), state):
            raise StateTransitionError(f"illegal job transition {current['state']} -> {state}")
        with self._transaction():
            self._conn.execute(
                "UPDATE jobs SET state=?, stage_cursor=COALESCE(?, stage_cursor), "
                "worker_lease_until=?, updated_at=? WHERE id=?",
                (state, stage_cursor, worker_lease_until, utc_now(), job_id),
            )
        updated = self.get_job(job_id)
        assert updated is not None
        return updated

    def append_job_event(
        self,
        job_id: str,
        *,
        state: str,
        stage: str = "",
        raw_api_receipt: str | dict[str, Any] | None = "",
        evidence_level: str = EvidenceLevel.OFFLINE.value,
        timestamp: str = "",
    ) -> int:
        """Append one immutable ledger entry; returns its sequence number."""
        if isinstance(raw_api_receipt, dict):
            raw_text = json.dumps(raw_api_receipt, ensure_ascii=False, sort_keys=True)
        else:
            raw_text = str(raw_api_receipt or "")
        with self._transaction():
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS next FROM job_events WHERE job_id=?", (job_id,)
            ).fetchone()
            seq = int(row["next"])
            self._conn.execute(
                "INSERT INTO job_events (job_id, seq, state, stage, raw_api_receipt, evidence_level, timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, seq, state, stage, raw_text, evidence_level, timestamp or utc_now()),
            )
        return seq

    def get_job_events(self, job_id: str) -> list[dict[str, Any]]:
        """Read the append-only ledger for a job."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_events WHERE job_id=? ORDER BY seq", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- artifacts --
    def insert_artifact(self, artifact: NativeTiaArtifact | dict[str, Any]) -> dict[str, Any]:
        """Register a real archive under the exact 4-tuple binding."""
        data = artifact.to_dict() if isinstance(artifact, NativeTiaArtifact) else dict(artifact)
        sha256 = str(data.get("archive_sha256") or data.get("sha256") or "")
        stored_path = str(data.get("archive_path") or data.get("path") or "")
        with self._transaction():
            self._conn.execute(
                "INSERT INTO artifacts (id, project_id, job_id, kind, sha256, path, size_bytes, evidence_level, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    data["artifact_id"], data["project_id"], data["job_id"], data.get("kind", "zap19"),
                    sha256, stored_path, int(data.get("size_bytes") or 0),
                    data.get("evidence_level", EvidenceLevel.PENDING_REAL_MACHINE.value), utc_now(),
                ),
            )
        return self.get_artifact(str(data["artifact_id"])) or {}

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        """Load an artifact by its exact id (never by path scanning)."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        return dict(row) if row else None

    def authorize_artifact(
        self, project_id: str, job_id: str, artifact_id: str, sha256: str
    ) -> bool:
        """Four-tuple exact authorisation; no directory wildcard is ever used."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM artifacts WHERE id=? AND project_id=? AND job_id=? AND sha256=?",
                (artifact_id, project_id, job_id, sha256),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------- capability --
    def save_capability_probe(self, manifest: TiaCapabilityManifest) -> str:
        """Persist a G0 probe receipt."""
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO capability_manifest "
                "(probe_receipt_id, tia_version, cpu_templates_json, probed_at, raw_probe_receipt, evidence_level) "
                "VALUES (?,?,?,?,?,?)",
                (
                    manifest.probe_receipt_id, manifest.tia_version,
                    json.dumps(manifest.cpu_templates, ensure_ascii=False, sort_keys=True),
                    manifest.probed_at,
                    json.dumps(manifest.raw_probe_receipt, ensure_ascii=False, sort_keys=True),
                    manifest.evidence_level.value if isinstance(manifest.evidence_level, EvidenceLevel) else str(manifest.evidence_level),
                ),
            )
        return manifest.probe_receipt_id

    def latest_capability_probe(self) -> TiaCapabilityManifest | None:
        """Load the most recent G0 probe receipt."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM capability_manifest ORDER BY probed_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return TiaCapabilityManifest(
            probe_receipt_id=row["probe_receipt_id"],
            tia_version=row["tia_version"],
            cpu_templates=json.loads(row["cpu_templates_json"]),
            probed_at=row["probed_at"],
            raw_probe_receipt=json.loads(row["raw_probe_receipt"]),
            evidence_level=EvidenceLevel.parse(row["evidence_level"]),
        )

    # ------------------------------------------------------------------ locks --
    def acquire_project_lock(self, project_id: str, owner_job_id: str, lease_seconds: int = 900) -> bool:
        """Acquire (or renew) the per-project exclusive lock."""
        now = datetime.now(UTC)
        with self._transaction():
            row = self._conn.execute(
                "SELECT owner_job_id, lease_until FROM project_locks WHERE project_id=?", (project_id,)
            ).fetchone()
            if row is not None:
                lease = row["lease_until"] or ""
                if lease and lease > now.isoformat() and row["owner_job_id"] != owner_job_id:
                    return False
            self._conn.execute(
                "INSERT OR REPLACE INTO project_locks (project_id, owner_job_id, lease_until) VALUES (?,?,?)",
                (project_id, owner_job_id, (now + timedelta(seconds=lease_seconds)).isoformat()),
            )
        return True

    def release_project_lock(self, project_id: str, owner_job_id: str) -> bool:
        """Release a lock only when owned by the calling job."""
        with self._transaction():
            row = self._conn.execute(
                "SELECT owner_job_id FROM project_locks WHERE project_id=?", (project_id,)
            ).fetchone()
            if row is None or row["owner_job_id"] != owner_job_id:
                return False
            self._conn.execute("DELETE FROM project_locks WHERE project_id=?", (project_id,))
        return True


_STORE: WorkspaceStore | None = None


def get_store() -> WorkspaceStore:
    """Process-wide store singleton used by the FastAPI dependencies."""
    global _STORE
    if _STORE is None:
        _STORE = WorkspaceStore()
    return _STORE


def reset_store_for_tests(store: WorkspaceStore | None = None) -> WorkspaceStore | None:
    """Replace the singleton (contract tests with a temporary database)."""
    global _STORE
    previous = _STORE
    _STORE = store
    return previous
