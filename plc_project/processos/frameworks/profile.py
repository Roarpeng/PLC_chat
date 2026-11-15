"""Framework Profile registry — locks REAL template assets by content hash.

G0 honesty: a profile is ``verified=False`` until the Windows Openness worker
proves a real compile/save/archive/reopen (WS6). Naming a constant or folder
"AF" never counts as official compatibility. Official AF Basic V2.2.2 ships V20;
the V19 baseline here is the local HR001_AF archive, pending real verification.
"""
from __future__ import annotations

from pathlib import Path

from plc_engine.canonical import compute_file_sha256
from processos.contract import FrameworkProfile

_REPO_ROOT = Path(__file__).resolve().parents[3]
HR001_AF_V19_PATH = _REPO_ROOT / "PLC_Openness_data" / "hr001" / "HR001_AF_V1_2.zap19"

_REGISTRY: dict[str, FrameworkProfile] = {}


def lock_template(
    path: str | Path,
    *,
    profile_id: str,
    framework: str = "siemens-af-basic",
    tia_version: str = "V19",
    library_version: str = "",
    notes: str = "",
) -> FrameworkProfile:
    """Hash the actual template file content; never trust a placeholder string."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"AF template asset not found: {p}")
    profile = FrameworkProfile(
        profile_id=profile_id,
        framework=framework,
        tia_version=tia_version,
        library_version=library_version,
        template_path=str(p),
        template_sha256=compute_file_sha256(p),
        verified=False,
        notes=notes,
    )
    register_profile(profile)
    return profile


def register_profile(profile: FrameworkProfile) -> None:
    _REGISTRY[profile.profile_id] = profile


def get_profile(profile_id: str) -> FrameworkProfile | None:
    return _REGISTRY.get(profile_id)


def list_profiles() -> list[FrameworkProfile]:
    return list(_REGISTRY.values())


def mark_verified(profile_id: str, evidence_receipt: str) -> FrameworkProfile:
    """Only WS6 may call this, with a real native-compile receipt reference."""
    profile = _REGISTRY[profile_id]
    if not evidence_receipt:
        raise ValueError("verification requires a real native-compile receipt")
    profile.verified = True
    profile.notes = (profile.notes + " | verified: " + evidence_receipt).strip(" |")
    return profile


def register_hr001_af_v19() -> FrameworkProfile:
    return lock_template(
        HR001_AF_V19_PATH,
        profile_id="SIEMENS_AF_BASIC_FOLDER_V19_HR001",
        framework="siemens-af-basic",
        tia_version="V19",
        library_version="HR001_AF_V1_2",
        notes="Local HR001 AF V19 archive; G0 pending real V19 compile (WS6). "
        "Official AF Basic V2.2.2 is V20 — not claimed V19-compatible.",
    )