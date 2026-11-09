"""Read-only adapter over the verified v1 AF kernel (design 1.3 / 2.3).

The AF generator / ``greenfield_ir.py`` public behaviour is never modified.
This adapter only reads constants, the canonical JSON helper and the
``to_af_project()`` projection. It does not write any AF file.
"""
from __future__ import annotations

from typing import Any

from plc_engine.af.greenfield_ir import AF_PROFILE as V1_AF_PROFILE
from plc_engine.af.greenfield_ir import GreenfieldIR, canonical_dumps, sha256_prefixed
from plc_engine.engineering_ir.hashing import to_plain
from plc_engine.engineering_ir.models import EngineeringIRV2


class AfLoweringAdapter:
    """Wrap the v1 AF kernel as a read-only dependency of the V2 pipeline."""

    @staticmethod
    def v1_af_profile_id() -> str:
        """Return the frozen AF profile id declared by the v1 kernel."""
        return str(V1_AF_PROFILE)

    @staticmethod
    def profile_is_consistent(ir: EngineeringIRV2) -> bool:
        """Check the V2 pinned profile matches the v1 kernel's frozen profile."""
        return ir.af_profile.profile_id == str(V1_AF_PROFILE)

    @staticmethod
    def canonical_dumps(obj: Any) -> str:
        """Reuse the v1 canonical JSON helper (read-only)."""
        return canonical_dumps(obj)

    @staticmethod
    def sha256_prefixed(payload: str | bytes) -> str:
        """Reuse the v1 hash format helper (read-only)."""
        return sha256_prefixed(payload)

    @staticmethod
    def legacy_af_project(ir: EngineeringIRV2) -> dict[str, Any] | None:
        """Project a v1 legacy IR into an ``AfProject`` view, read-only.

        Returns ``None`` when the V2 IR has no v1 legacy payload (pure Greenfield
        V2 projects). No file is written and no AF generator is mutated.
        """
        if not isinstance(ir.legacy_raw, dict):
            return None
        v1_ir = GreenfieldIR.from_dict(ir.legacy_raw)
        af_project = v1_ir.to_af_project()
        return to_plain(af_project)

    @staticmethod
    def legacy_roundtrip_hash(ir: EngineeringIRV2) -> str:
        """Hash the v1 kernel's own IR hash from the legacy payload."""
        if not isinstance(ir.legacy_raw, dict):
            return ""
        v1_ir = GreenfieldIR.from_dict(ir.legacy_raw)
        return str(v1_ir.ir_sha256())
