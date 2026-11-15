"""WS7 end-to-end clamp vertical slice (offline, full ProcessOS pipeline).

Proves the whole closed loop as a system: contract -> validate -> simulate ->
codegen -> human review -> approve -> delivery gate -> native orchestration ->
evidence passport. Native step uses the mocked runner (labelled mocked, never
NATIVE_ARCHIVED); the real V19 compile is exercised by scripts/processos_real_compile.py.
"""
from __future__ import annotations

import pytest

from processos.api import ProjectStore
from processos.contract import Patch, PatchOp, clamp_contract
from processos.native import make_demo_runner


@pytest.fixture()
def store():
    s = ProjectStore()
    s.runner = make_demo_runner()
    s.create_project(clamp_contract())
    return s


PID = "PRJ_CLAMP"


def test_full_clamp_closed_loop(store):
    report = store.validate(PID)
    assert report["errors"] == []

    sim = store.simulate(PID)
    assert sim["all_passed"]
    assert len(sim["results"]) == 6

    gen = store.generate(PID)
    assert gen["coverage_assertions_passed"]
    assert "OB_Main.scl" in gen["files"]

    gate0 = store.delivery_gate(PID)
    assert not gate0["ready"]

    store.resolve_question(PID, "Q_SAFETY_STOP", "许可撤销时保持原位", "工程师张三")
    cs = store.freeze_changeset(PID)
    store.approve(PID, cs["id"], "工程师张三")

    gate1 = store.delivery_gate(PID)
    assert gate1["ready"], gate1

    job = store.create_delivery(PID)
    assert job["status"] == "SUCCEEDED"
    assert job["evidence_level"] == "mocked"
    assert job["ob_main_included"] is True
    assert job["chain_state"] == "MOCKED_CHAIN_OK"
    assert job["artifact"] is not None


def test_evidence_passport_full_chain(store):
    from processos.contract import contract_semantic_hash, contract_spec_hash
    from processos.frameworks import get_profile

    store.validate(PID)
    store.simulate(PID)
    store.generate(PID)
    rh = contract_semantic_hash(store.projects[PID].contract)
    derived_kinds = {e.kind for e in store.passport.for_revision(rh)}
    assert {"validation", "simulation", "codegen"} <= derived_kinds

    store.resolve_question(PID, "Q_SAFETY_STOP", "保持原位", "工程师")
    cs = store.freeze_changeset(PID)
    store.approve(PID, cs["id"], "工程师")
    store.create_delivery(PID)

    profile = get_profile(store.projects[PID].profile_id)
    spec = contract_spec_hash(store.projects[PID].contract, profile.profile_id, profile.template_sha256)
    approval_kinds = {e.kind for e in store.passport.for_revision(spec)}
    assert {"changeset_frozen", "human_approval"} <= approval_kinds
    job_kinds = {e.kind for e in store.passport.all() if e.job_id}
    assert "delivery_queued" in job_kinds


def test_patch_invalidates_approval_and_blocks_delivery(store):
    store.resolve_question(PID, "Q_SAFETY_STOP", "保持原位", "工程师")
    cs = store.freeze_changeset(PID)
    store.approve(PID, cs["id"], "工程师")
    assert store.delivery_gate(PID)["ready"]

    store.apply_patch(PID, Patch(base_revision=1, ops=[
        PatchOp("set", "/operations/OP_CLAMP/steps/S_HOLD/duration_ms", 5000)
    ]))
    gate = store.delivery_gate(PID)
    assert not gate["checks"]["approved_and_hash_match"]
    assert not gate["ready"]


def test_counterexample_available_on_broken_contract(store):
    from processos.contract import Action
    c = store.projects[PID].contract
    c.operations[0].step("S_EXTEND").entry.append(Action("CM_CLAMP_CYL", "Retract", True))
    results = store.simulate(PID)
    broken = [r for r in results["results"] if r["counterexamples"]]
    assert broken
    assert any(ce["property_id"] == "no_simultaneous_extend_retract"
               for r in broken for ce in r["counterexamples"])
