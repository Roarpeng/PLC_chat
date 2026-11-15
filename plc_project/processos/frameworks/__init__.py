"""Framework profiles + AF target semantics (G0-gated, real template hashes)."""
from __future__ import annotations

from . import af_semantics
from .profile import (
    HR001_AF_V19_PATH,
    get_profile,
    list_profiles,
    lock_template,
    mark_verified,
    register_hr001_af_v19,
    register_profile,
)

__all__ = [
    "af_semantics", "HR001_AF_V19_PATH", "lock_template", "register_profile",
    "get_profile", "list_profiles", "mark_verified", "register_hr001_af_v19",
]