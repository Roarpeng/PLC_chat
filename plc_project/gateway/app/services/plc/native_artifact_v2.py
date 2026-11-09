"""NativeTiaArtifact construction and evidence bundle (WP-01 / AC-01-6)."""
from __future__ import annotations

import uuid
from typing import Any

from gateway.app.services.plc.workspace_v2 import utc_now
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import NativeTiaArtifact
from plc_engine.process.artifact_manifest import ArtifactManifest
from plc_engine.process.source_map import SourceMap


def attach_evidence(
    artifact: NativeTiaArtifact,
    *,
    real_tia_v19_tested: bool,
    raw_evidence_path: str = "",
) -> NativeTiaArtifact:
    """Attach an evidence id, strictly derived from the real receipt flag."""
    artifact.evidence_id = f"ev_{uuid.uuid4().hex[:16]}"
    artifact.receipt["generated_at"] = utc_now()
    artifact.receipt["real_tia_v19_tested"] = bool(real_tia_v19_tested)
    artifact.receipt["raw_evidence_path"] = raw_evidence_path
    if not real_tia_v19_tested and artifact.evidence_level is EvidenceLevel.V19_REAL:
        artifact.evidence_level = EvidenceLevel.PENDING_REAL_MACHINE
    return artifact


def evidence_bundle(
    artifact: NativeTiaArtifact,
    *,
    job_events: list[dict[str, Any]] | None = None,
    manifest: ArtifactManifest | None = None,
    source_map: SourceMap | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the downloadable evidence bundle bound to one exact artifact id."""
    return {
        "artifact_id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "job_id": artifact.job_id,
        "evidence_id": artifact.evidence_id,
        "evidence_level": artifact.evidence_level.value if isinstance(artifact.evidence_level, EvidenceLevel) else str(artifact.evidence_level),
        "real_tia_v19_tested": bool(artifact.receipt.get("real_tia_v19_tested")),
        "raw_evidence_path": str(artifact.receipt.get("raw_evidence_path") or ""),
        "archive": {
            "path": artifact.archive_path,
            "sha256": artifact.archive_sha256,
            "size_bytes": artifact.size_bytes,
            "kind": artifact.kind,
            "reopen_ok": artifact.reopen_ok,
        },
        "compile": artifact.compile.to_dict(),
        "artifact_manifest": manifest.to_dict(include_content=False) if manifest else None,
        "source_map": source_map.to_dict() if source_map else None,
        "job_events": list(job_events or []),
        "diagnostics": list(diagnostics or []),
        "notice": (
            "V19 real full-chain receipt" if artifact.is_native_archived()
            else "no V19 real full-chain receipt; must never be shown as delivery complete"
        ),
    }


def assert_exact_binding(
    artifact: NativeTiaArtifact,
    *,
    project_id: str,
    job_id: str,
    sha256: str,
) -> bool:
    """Validate the ``(project_id, job_id, artifact_id, sha256)`` 4-tuple."""
    return bool(
        artifact.project_id == project_id
        and artifact.job_id == job_id
        and artifact.archive_sha256 == sha256
        and artifact.artifact_id
    )
