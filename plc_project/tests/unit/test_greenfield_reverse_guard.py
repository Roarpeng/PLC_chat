"""reverse_guard.py 单测（WP-04 / F18 / D10 / 契约 §2.4 / UC-12 负例）。

纯 mock 块快照哈希比对，不调用 TIA / CLI / Openness。
覆盖：一致放行、手工改无关块阻止（UC-12）、fail-closed、阻止语义措辞。
"""
from __future__ import annotations

from plc_engine.af.reverse_guard import ReverseGuardVerdict, check_reverse_guard


def test_identical_snapshots_allowed():
    gen = {"A": "sha256:aaa", "B": "sha256:bbb", "C": "sha256:ccc"}
    verdict = check_reverse_guard(gen, dict(gen))
    assert isinstance(verdict, ReverseGuardVerdict)
    assert verdict.allowed is True
    assert verdict.drift_count == 0
    assert verdict.tia_side_drift == 0
    assert verdict.blocked_source_ids == ()


def test_manual_edit_unrelated_block_blocks_uc12():
    """UC-12 负例：TIA 侧手工改动一个无关块 -> 阻止并提示，不得覆盖。"""
    gen = {"A": "sha256:aaa", "B": "sha256:bbb", "C": "sha256:ccc"}
    tia = dict(gen)
    tia["C"] = "sha256:HAND_EDITED"
    verdict = check_reverse_guard(gen, tia)
    assert verdict.allowed is False
    assert verdict.tia_side_drift >= 1
    assert "C" in verdict.blocked_source_ids
    assert "阻止" in verdict.reason
    assert "禁止覆盖" in verdict.reason
    assert "不是先覆盖再提示" in verdict.reason


def test_fail_closed_on_any_tia_side_drift():
    cases = [
        ({"A": "sha256:1"}, {"A": "sha256:2"}),
        ({"A": "sha256:1"}, {}),
        ({"A": "sha256:1"}, {"A": "sha256:1", "B": "sha256:x"}),
        ({}, {"X": "sha256:1"}),
    ]
    for gen, tia in cases:
        v = check_reverse_guard(gen, tia)
        assert v.tia_side_drift > 0
        assert v.allowed is False


def test_reason_is_prevent_not_overwrite():
    v = check_reverse_guard({"A": "sha256:1"}, {"A": "sha256:2"})
    assert v.allowed is False
    assert "阻止并提示" in v.reason
    assert "禁止覆盖" in v.reason


def test_empty_tia_side_is_fail_closed():
    gen = {"A": "sha256:1", "B": "sha256:2"}
    v = check_reverse_guard(gen, {})
    assert v.allowed is False
    assert v.tia_side_drift == 2
    assert set(v.blocked_source_ids) == {"A", "B"}


def test_drift_count_is_subset_of_tia_side_drift():
    gen = {"A": "sha256:1", "B": "sha256:2"}
    tia = {"A": "sha256:CHANGED", "B": "sha256:2", "X": "sha256:EXTRA"}
    v = check_reverse_guard(gen, tia)
    assert v.drift_count == 1
    assert v.tia_side_drift == 2
    assert v.allowed is False
