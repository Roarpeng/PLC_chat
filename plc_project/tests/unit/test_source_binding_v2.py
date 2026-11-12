"""WP-05: SourceBinding / DiffPlan / reverse closure schema contracts (offline)."""
from __future__ import annotations

from plc_engine.changeplan import (
    DiffOp,
    DiffPlan,
    SourceBinding,
    reverse_reference_closure,
)


def test_source_binding_roundtrip_preserves_all_q04_fields() -> None:
    raw = {
        "source_id": "FB_Motor", "source_block_id": "FB_Motor", "tia_path": "PLC_1/FB_Motor",
        "block_type": "FB", "block_number": 12, "original_hash": "sha256:orig",
        "original_xml_sha256": "sha256:xml", "source_span": {"start": 1, "end": 42},
        "ir_ids": ["CM1", "S2"], "ir_entities": ["CM1", "S2"],
        "referenced_by": ["OB_Main"], "writable": "requires_review", "fidelity": "parsed",
    }
    binding = SourceBinding.from_dict(raw)
    restored = SourceBinding.from_dict(binding.to_dict())
    assert restored.to_dict() == binding.to_dict()
    for key in ("source_block_id", "original_hash", "source_span", "ir_ids", "writable", "referenced_by", "fidelity"):
        assert key in binding.to_dict()
    assert binding.to_dict()["ir_ids"] == ["CM1", "S2"]


def test_f_block_and_unparseable_are_always_protected() -> None:
    for raw in (
        {"source_id": "FB_Safety", "block_type": "F", "writable": "requires_review", "fidelity": "parsed"},
        {"source_id": "FB_Unknown", "block_type": "FB", "writable": "requires_review", "fidelity": "unparseable"},
        {"source_id": "FB_Protected", "block_type": "FB", "writable": "requires_review", "fidelity": "protected"},
    ):
        assert SourceBinding.from_dict(raw).is_protected() is True


def test_diff_plan_executable_is_always_false() -> None:
    plan = DiffPlan(plan_id="plan_1", ops=[DiffOp(op="MODIFY", source_id="FB_Motor")], executable=True)
    assert plan.executable is False
    assert plan.to_dict()["executable"] is False
    assert DiffPlan.from_dict(plan.to_dict()).executable is False
    assert plan.evidence_level == "mocked"


def test_reverse_reference_closure_is_deterministic() -> None:
    bindings = [
        SourceBinding.from_dict({"source_id": "FB_A", "referenced_by": ["OB_Main"]}),
        SourceBinding.from_dict({"source_id": "FB_B", "referenced_by": ["FB_A"]}),
        SourceBinding.from_dict({"source_id": "FB_C", "referenced_by": ["FB_B"]}),
        SourceBinding.from_dict({"source_id": "FB_D", "referenced_by": []}),
    ]
    assert reverse_reference_closure(bindings, ["FB_A"]) == ["FB_A", "FB_B", "FB_C"]
    assert reverse_reference_closure(bindings, ["FB_D"]) == ["FB_D"]
