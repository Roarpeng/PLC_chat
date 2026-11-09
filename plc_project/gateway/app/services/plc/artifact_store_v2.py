"""Hash-named Artifact Store + exact authorisation (WP-01 / D-2 / G5).

The store NEVER scans a directory to "find the first zap19". Downloads resolve
one ``artifact_id`` through the database and then open the exact whitelisted
relative path recorded at registration time.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from gateway.app.services.plc.workspace_v2 import WorkspaceStore
from plc_engine.engineering_ir.contracts import ErrorCode
from plc_engine.engineering_ir.hashing import compute_file_sha256


class ArtifactNotFoundError(LookupError):
    """404 ARTIFACT_NOT_FOUND."""


class ArtifactJobMismatchError(PermissionError):
    """403 ARTIFACT_JOB_MISMATCH: a job tried to fetch another job's archive."""


class ArtifactStore:
    """Content-addressed store with a strict relative-path whitelist."""

    def __init__(self, store: WorkspaceStore, root: str | Path | None = None) -> None:
        self.store = store
        self.root = Path(root or os.getenv("PLC_V2_ARTIFACT_ROOT", "artifact_store")).resolve()

    def _hash_relative_path(self, sha256: str, extension: str) -> str:
        """Build ``artifact_store/<2 hex>/<rest>.<ext>``; never accept '..'."""
        digest = sha256.removeprefix("sha256:")
        if not digest or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            raise ValueError("artifact sha256 must be a hex digest")
        safe_ext = "".join(ch for ch in extension.lstrip(".") if ch.isalnum()) or "bin"
        return f"artifact_store/{digest[:2]}/{digest[2:]}.{safe_ext}"

    def _resolve(self, relative_path: str) -> Path:
        """Resolve a DB-recorded relative path and enforce the whitelist."""
        candidate = (self.root.parent / relative_path).resolve()
        root_prefix = (self.root.parent / "artifact_store").resolve()
        if root_prefix not in candidate.parents and candidate != root_prefix:
            raise ArtifactJobMismatchError(f"path outside artifact whitelist: {relative_path}")
        if not candidate.is_file():
            raise ArtifactNotFoundError(f"artifact file missing at exact path: {relative_path}")
        return candidate

    def store_file(self, source_path: str | Path, *, kind: str = "zap19") -> dict[str, Any]:
        """Copy one exact file into the hash-named store; return its descriptor."""
        source = Path(source_path)
        if not source.is_file():
            raise ArtifactNotFoundError(f"archive_missing: exact path not found: {source}")
        sha256 = compute_file_sha256(source)
        relative = self._hash_relative_path(sha256, source.suffix.lstrip(".") or "zap19")
        target = self.root.parent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(target.name + ".tmp")
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        return {
            "path": relative,
            "sha256": sha256,
            "size_bytes": source.stat().st_size,
            "kind": kind,
        }

    def register(
        self,
        artifact: dict[str, Any],
        *,
        stored: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a native artifact under the exact 4-tuple binding."""
        descriptor = dict(stored or {})
        payload = {
            "artifact_id": artifact["artifact_id"],
            "project_id": artifact["project_id"],
            "job_id": artifact["job_id"],
            "kind": descriptor.get("kind", "zap19"),
            "sha256": artifact["archive_sha256"],
            "path": descriptor.get("path") or artifact["archive_path"],
            "size_bytes": int(artifact.get("size_bytes") or descriptor.get("size_bytes") or 0),
            "evidence_level": artifact.get("evidence_level", "pending_real_machine"),
        }
        return self.store.insert_artifact(payload)

    def authorize(self, project_id: str, job_id: str, artifact_id: str, sha256: str) -> bool:
        """Exact 4-tuple authorisation; no wildcard, no cross-job lookup."""
        return self.store.authorize_artifact(project_id, job_id, artifact_id, sha256)

    def download(
        self,
        artifact_id: str,
        *,
        project_id: str,
        job_id: str,
        sha256: str = "",
    ) -> tuple[bytes, dict[str, Any]]:
        """Return ``(bytes, metadata)`` for one exactly authorised artifact."""
        row = self.store.get_artifact(artifact_id)
        if row is None:
            raise ArtifactNotFoundError(ErrorCode.ARTIFACT_NOT_FOUND.value)
        if row["project_id"] != project_id or row["job_id"] != job_id:
            raise ArtifactJobMismatchError(ErrorCode.ARTIFACT_JOB_MISMATCH.value)
        expected = sha256 or row["sha256"]
        if expected and row["sha256"] != expected:
            raise ArtifactJobMismatchError("ARTIFACT_SHA256_MISMATCH")
        path = self._resolve(str(row["path"]))
        data = path.read_bytes()
        if compute_file_sha256(path) != row["sha256"]:
            raise ArtifactJobMismatchError("ARTIFACT_SHA256_MISMATCH: stored file hash drift")
        return data, dict(row)
