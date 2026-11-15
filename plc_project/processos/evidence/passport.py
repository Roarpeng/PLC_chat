"""Build Evidence Passport — the immutable audit chain (blueprint §10 moat #4).

Every approval, validation, simulation, codegen and native receipt is bound to
(project_revision_hash, framework_profile, build_job_id, artifact_sha256). No
download is trustworthy without this chain; "AI said it's done" is never evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

from plc_engine.canonical import to_plain


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class EvidenceEntry:
    kind: str
    revision_hash: str
    profile_id: str
    evidence_level: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=_now)
    job_id: str = ""
    artifact_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: to_plain(getattr(self, f.name)) for f in fields(self)}


class EvidencePassport:
    """Append-only ledger; entries are never mutated or deleted."""

    def __init__(self) -> None:
        self._entries: list[EvidenceEntry] = []

    def record(
        self,
        kind: str,
        *,
        revision_hash: str,
        profile_id: str = "",
        evidence_level: str,
        payload: dict[str, Any] | None = None,
        job_id: str = "",
        artifact_sha256: str = "",
    ) -> EvidenceEntry:
        entry = EvidenceEntry(
            kind=kind,
            revision_hash=revision_hash,
            profile_id=profile_id,
            evidence_level=evidence_level,
            payload=payload or {},
            job_id=job_id,
            artifact_sha256=artifact_sha256,
        )
        self._entries.append(entry)
        return entry

    def for_revision(self, revision_hash: str) -> list[EvidenceEntry]:
        return [e for e in self._entries if e.revision_hash == revision_hash]

    def chain_for_job(self, job_id: str) -> list[EvidenceEntry]:
        return [e for e in self._entries if e.job_id == job_id]

    def all(self) -> list[EvidenceEntry]:
        return list(self._entries)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in self._entries]}