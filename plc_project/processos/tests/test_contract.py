"""WS1 contract spine tests — the foundation every workstream depends on."""
from __future__ import annotations

import pytest

from processos.contract import (
    OpenQuestion,
    Patch,
    PatchError,
    PatchOp,
    ProcessContract,
    RevisionConflict,
    apply_patch,
    clamp_contract,
    contract_semantic_hash,
    contract_spec_hash,
    evaluate_questions,
    resolve_question,
)


def test_clamp_fixture_structure_valid():
    c = clamp_contract()
    assert c.validate_structure() == []
    assert len(c.operations[0].steps) == 6
    assert c.resource("CM_CLAMP_CYL").io_bindings["Extended"] == "unbound"


def test_roundtrip_serialization():
    c = clamp_contract()
    restored = ProcessContract.from_dict(c.to_dict())
    assert restored.to_dict() == c.to_dict()
    assert contract_semantic_hash(restored) == contract_semantic_hash(c)


def test_semantic_hash_deterministic_and_sensitive():
    c = clamp_contract()
    h1 = contract_semantic_hash(c)
    h2 = contract_semantic_hash(clamp_contract())
    assert h1 == h2 and h1.startswith("sha256:")
    c2 = clamp_contract()
    c2.operations[0].step("S_HOLD").duration_ms = 4000
    assert contract_semantic_hash(c2) != h1


def test_spec_hash_binds_profile_and_template():
    c = clamp_contract()
    a = contract_spec_hash(c, "AF_V19_PIN", "sha256:aaa")
    b = contract_spec_hash(c, "AF_V19_PIN", "sha256:bbb")
    assert a != b


def test_structure_rejects_unknown_resource():
    c = clamp_contract()
    c.operations[0].steps[1].entry[0].target = "CM_GHOST"
    errs = c.validate_structure()
    assert any("unknown resource" in e for e in errs)


def test_patch_set_duration_bumps_revision():
    c = clamp_contract()
    p = Patch(base_revision=3, request_id="r1", ops=[
        PatchOp("set", "/operations/OP_CLAMP/steps/S_HOLD/duration_ms", 4000)
    ])
    new, rev = apply_patch(c, p, 3)
    assert rev == 4
    assert new.operations[0].step("S_HOLD").duration_ms == 4000
    assert c.operations[0].step("S_HOLD").duration_ms == 2000  # original untouched
    assert contract_semantic_hash(new) != contract_semantic_hash(c)


def test_patch_revision_conflict():
    c = clamp_contract()
    p = Patch(base_revision=1, ops=[PatchOp("set", "/name", "x")])
    with pytest.raises(RevisionConflict):
        apply_patch(c, p, 3)


def test_patch_invalid_command_rejected():
    c = clamp_contract()
    p = Patch(base_revision=3, ops=[
        PatchOp("set", "/operations/OP_CLAMP/steps/S_EXTEND/entry",
                [{"target": "CM_CLAMP_CYL", "command": "Bogus", "value": True}])
    ])
    with pytest.raises(PatchError):
        apply_patch(c, p, 3)


def test_patch_add_remove_scenario():
    c = clamp_contract()
    n = len(c.scenarios)
    add = Patch(base_revision=3, ops=[
        PatchOp("add", "/scenarios", {"id": "SC_NEW", "name": "extra", "kind": "normal"})
    ])
    c2, _ = apply_patch(c, add, 3)
    assert len(c2.scenarios) == n + 1
    rem = Patch(base_revision=4, ops=[PatchOp("remove", "/scenarios/SC_NEW")])
    c3, _ = apply_patch(c2, rem, 4)
    assert len(c3.scenarios) == n


def test_patch_duplicate_id_rejected():
    c = clamp_contract()
    p = Patch(base_revision=3, ops=[
        PatchOp("add", "/resources", {"id": "CM_CLAMP_CYL", "kind": "cylinder"})
    ])
    with pytest.raises(PatchError):
        apply_patch(c, p, 3)


def test_blocking_question_gates_delivery():
    c = clamp_contract(with_blocking_question=True)
    gate = evaluate_questions(c)
    assert not gate.deliverable
    assert "Q_SAFETY_STOP" in gate.blocking_open
    resolve_question(c, "Q_SAFETY_STOP", "许可撤销时保持原位，待人工处理", "工程师张三")
    gate2 = evaluate_questions(c)
    assert gate2.deliverable


def test_advisory_question_does_not_block():
    c = clamp_contract(with_blocking_question=False)
    c.open_questions.append(
        OpenQuestion(id="Q_NICE", question="命名偏好？", severity="advisory")
    )
    assert evaluate_questions(c).deliverable


def test_resolve_unknown_question_raises():
    c = clamp_contract()
    with pytest.raises(KeyError):
        resolve_question(c, "Q_NOPE", "x", "y")