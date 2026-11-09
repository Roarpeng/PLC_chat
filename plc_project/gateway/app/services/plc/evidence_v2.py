"""Four-level evidence service (PRD 6.4 / design 9.3, WP-00 definition).

Writes only to ``evidence/v2/**``. Historical ``evidence/*.json`` files are
never touched. ``compile_ok`` is only true for a real ``error_count == 0``
receipt with a passed static gate — a mock can never be upcast to V19_real.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from plc_engine.engineering_ir.evidence import EvidenceLevel, EvidenceTag, forbid_upcast, is_real

DEFAULT_EVIDENCE_ROOT = Path("evidence/v2")


def evidence_root() -> Path:
    """Resolve the v2 evidence root (env override for tests / CI)."""
    configured = os.getenv("PLC_V2_EVIDENCE_ROOT", "").strip()
    return Path(configured) if configured else DEFAULT_EVIDENCE_ROOT


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON ledger file atomically (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


class EvidenceService:
    """Generate receipts, job-event stamps and per-batch evidence ledgers."""

    @staticmethod
    def new_evidence_id() -> str:
        """Short unique evidence id."""
        return f"ev_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def receipt(
        *,
        task_id: str,
        level: EvidenceLevel | str,
        real_tia_v19_tested: bool = False,
        raw_evidence_path: str = "",
        details: dict[str, Any] | None = None,
        generated_at: str = "",
    ) -> dict[str, Any]:
        """Build a delivery receipt; level is clamped to its source evidence."""
        from gateway.app.services.plc.workspace_v2 import utc_now

        parsed = EvidenceLevel.parse(level)
        if real_tia_v19_tested is False and parsed is EvidenceLevel.V19_REAL:
            parsed = EvidenceLevel.PENDING_REAL_MACHINE
        return {
            "evidence_id": EvidenceService.new_evidence_id(),
            "task_id": task_id,
            "evidence_level": parsed.value,
            "real_tia_v19_tested": bool(real_tia_v19_tested),
            "raw_evidence_path": raw_evidence_path,
            "generated_at": generated_at or utc_now(),
            "details": dict(details or {}),
            "notice": (
                "no V19 real receipt; must never be shown as delivery complete"
                if parsed is EvidenceLevel.PENDING_REAL_MACHINE else ""
            ),
        }

    @staticmethod
    def tag(
        level: EvidenceLevel | str,
        *,
        source: str,
        receipt_id: str = "",
        raw_receipt_path: str = "",
        note: str = "",
        details: dict[str, Any] | None = None,
    ) -> EvidenceTag:
        """Create an evidence tag with strict level parsing."""
        return EvidenceTag(
            level=EvidenceLevel.parse(level),
            source=source,
            receipt_id=receipt_id,
            raw_receipt_path=raw_receipt_path,
            note=note,
            details=dict(details or {}),
        )

    @staticmethod
    def clamp(original: EvidenceLevel | str, claimed: EvidenceLevel | str) -> EvidenceLevel:
        """Prevent evidence upcasting (mock -> real is forbidden)."""
        return forbid_upcast(original, claimed)

    @staticmethod
    def compile_ok(
        *,
        error_count: int,
        static_gate_passed: bool,
        real_receipt_present: bool,
        warning_count: int = 0,
    ) -> bool:
        """Definition: error_count == 0 AND gate passed AND real receipt exists.

        ``warning_count`` is deliberately accepted but never folded into success.
        """
        return bool(error_count == 0 and static_gate_passed and real_receipt_present)

    @staticmethod
    def is_real(level: EvidenceLevel | str) -> bool:
        """True only for a genuine V19 real level."""
        return is_real(level)

    @staticmethod
    def write_ledger(task_id: str, name: str, payload: dict[str, Any], *, root: Path | None = None) -> Path:
        """Persist one batch ledger file under ``evidence/v2/<task>/``."""
        base = root or evidence_root()
        target = base / task_id / f"{name}.json"
        _atomic_json(target, payload)
        return target

    @staticmethod
    def job_event(
        *,
        state: str,
        stage: str,
        level: EvidenceLevel | str,
        raw_api_receipt: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Build a job_events row payload (timestamp added by the store)."""
        from gateway.app.services.plc.workspace_v2 import utc_now

        raw = raw_api_receipt if isinstance(raw_api_receipt, str) else json.dumps(
            raw_api_receipt or {}, ensure_ascii=False, sort_keys=True
        )
        return {
            "state": state,
            "stage": stage,
            "raw_api_receipt": raw,
            "evidence_level": EvidenceLevel.parse(level).value,
            "timestamp": utc_now(),
        }
