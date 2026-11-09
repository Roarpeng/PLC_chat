"""Four-level evidence tagging (PRD 6.4 / design 9.3).

Evidence levels are first-class citizens of every API reply, job event and
artifact. They never upgrade implicitly: offline != mocked != V19_real, and a
missing real-machine receipt is always ``pending_real_machine``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceLevel(str, Enum):
    """Allowed evidence levels."""

    OFFLINE = "offline"
    MOCKED = "mocked"
    V19_REAL = "V19_real"
    PENDING_REAL_MACHINE = "pending_real_machine"

    @classmethod
    def parse(cls, value: Any) -> EvidenceLevel:
        """Strict parse; unknown input is fail-closed to pending_real_machine."""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (ValueError, TypeError):
            return cls.PENDING_REAL_MACHINE


@dataclass
class EvidenceTag:
    """Structured evidence stamp attached to receipts, jobs and artifacts."""

    level: EvidenceLevel = EvidenceLevel.PENDING_REAL_MACHINE
    source: str = "offline_kernel"
    receipt_id: str = ""
    raw_receipt_path: str = ""
    note: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain JSON-serialisable dict."""
        return {
            "level": self.level.value,
            "source": self.source,
            "receipt_id": self.receipt_id,
            "raw_receipt_path": self.raw_receipt_path,
            "note": self.note,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceTag:
        """Rebuild a tag from its dict representation."""
        return cls(
            level=EvidenceLevel.parse(data.get("level")),
            source=str(data.get("source") or "offline_kernel"),
            receipt_id=str(data.get("receipt_id") or ""),
            raw_receipt_path=str(data.get("raw_receipt_path") or ""),
            note=str(data.get("note") or ""),
            details=dict(data.get("details") or {}),
        )


OFFLINE_TAG = EvidenceTag(level=EvidenceLevel.OFFLINE, note="offline static/pure-function result")
MOCKED_TAG = EvidenceTag(level=EvidenceLevel.MOCKED, note="mocked orchestration, not a real machine")
PENDING_TAG = EvidenceTag(
    level=EvidenceLevel.PENDING_REAL_MACHINE,
    note="no V19 real receipt; must never be shown as delivery complete",
)


def is_real(level: EvidenceLevel | str) -> bool:
    """Return True only for a genuine V19 real receipt."""
    return EvidenceLevel.parse(level) is EvidenceLevel.V19_REAL


def make_tag(
    level: EvidenceLevel | str,
    *,
    source: str = "offline_kernel",
    receipt_id: str = "",
    raw_receipt_path: str = "",
    note: str = "",
    details: dict[str, Any] | None = None,
) -> EvidenceTag:
    """Build an evidence tag with strict level parsing."""
    return EvidenceTag(
        level=EvidenceLevel.parse(level),
        source=source,
        receipt_id=receipt_id,
        raw_receipt_path=raw_receipt_path,
        note=note,
        details=dict(details or {}),
    )


def forbid_upcast(original: EvidenceLevel | str, claimed: EvidenceLevel | str) -> EvidenceLevel:
    """Clamp a claim so it can never exceed its source level.

    Only an explicit ``V19_real`` source may yield ``V19_real``. This is the
    programmatic guard against "mock compiled == real success" (PRD 6.4).
    """
    src = EvidenceLevel.parse(original)
    want = EvidenceLevel.parse(claimed)
    if want is EvidenceLevel.V19_REAL and src is not EvidenceLevel.V19_REAL:
        return src if src is not EvidenceLevel.OFFLINE else EvidenceLevel.PENDING_REAL_MACHINE
    if src is EvidenceLevel.PENDING_REAL_MACHINE and want is EvidenceLevel.MOCKED:
        return EvidenceLevel.PENDING_REAL_MACHINE
    return want
