"""WS3 framework profile + AF backend tests (real template hash, G0 honesty)."""
from __future__ import annotations

import re

import pytest

from processos.backends import lower
from processos.contract import clamp_contract
from processos.frameworks import (
    HR001_AF_V19_PATH,
    get_profile,
    lock_template,
    mark_verified,
    register_hr001_af_v19,
)


def test_real_template_hash_locked():
    if not HR001_AF_V19_PATH.exists():
        pytest.skip("HR001 AF archive not present")
    profile = register_hr001_af_v19()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", profile.template_sha256)
    assert profile.verified is False
    assert profile.tia_version == "V19"
    assert get_profile(profile.profile_id) is profile


def test_lock_missing_template_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        lock_template(tmp_path / "nope.zap19", profile_id="X")


def test_mark_verified_requires_receipt():
    profile = register_hr001_af_v19()
    with pytest.raises(ValueError):
        mark_verified(profile.profile_id, "")
    mark_verified(profile.profile_id, "evidence/v19_real/receipt.json")
    assert get_profile(profile.profile_id).verified is True


def test_lower_produces_af_blocks():
    profile = register_hr001_af_v19()
    project = lower(clamp_contract(), profile)
    roles = {b.role for b in project.blocks}
    assert {"unit", "em_sequence", "cm_driver", "main"} <= roles
    assert any(b.kind == "OB" and b.name == "OB_Main" for b in project.blocks)
    assert project.instance_dbs
    assert project.call_order
    seq = next(b for b in project.blocks if b.role == "em_sequence")
    assert "S_EXTEND" in seq.source_ids
    assert "sequence" in seq.interface


def test_lower_ir_hash_bound():
    profile = register_hr001_af_v19()
    project = lower(clamp_contract(), profile)
    assert project.ir_hash.startswith("sha256:")
    assert project.profile_id == profile.profile_id