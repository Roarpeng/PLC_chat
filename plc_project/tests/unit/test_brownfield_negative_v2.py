"""WP-05 / Q-04: four+ classes of negative rejection, no real TIA evidence."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.app.main import app
from gateway.app.services.plc.brownfield_v2 import BrownfieldServiceV2
from gateway.app.services.plc.workspace_v2 import get_store
from plc_engine.changeplan import DiffOp, DiffPlan, SourceBinding, evaluate_diff_plan, mocked_orchestrate
from tests.v2_fixtures import build_store

BINDINGS = [
    {"source_id": "FB_Motor", "source_block_id": "FB_Motor", "block_type": "FB",
     "original_hash": "sha256:orig", "fidelity": "parsed", "writable": "requires_review",
     "referenced_by": ["OB_Main"]},
    {"source_id": "OB_Main", "source_block_id": "OB_Main", "block_type": "OB",
     "original_hash": "sha256:ob", "fidelity": "parsed", "writable": "requires_review"},
    {"source_id": "FB_Safety", "source_block_id": "FB_Safety", "block_type": "F",
     "original_hash": "sha256:f", "fidelity": "protected", "writable": "requires_review"},
    {"source_id": "FB_Unparsed", "source_block_id": "FB_Unparsed", "block_type": "FB",
     "original_hash": "sha256:u", "fidelity": "unparseable", "writable": "requires_review"},
]


def review(ops, *, expected="sha256:base", actual="sha256:base", mocked=False):
    return BrownfieldServiceV2.review(
        project_id="prj_bf", ops=ops, bindings_payload=BINDINGS,
        expected_baseline_hash=expected, actual_baseline_hash=actual,
        mocked_orchestration=mocked,
    )


def test_f_block_write_is_rejected() -> None:
    result = review([{"op": "MODIFY", "source_id": "FB_Safety"}])
    assert any(i["code"] == "WRITEBACK_FORBIDDEN" and "F-block" in i["reason"] for i in result["issues"])


def test_delete_referenced_block_is_rejected() -> None:
    result = review([{"op": "DELETE", "source_id": "FB_Motor"}])
    assert any("still referenced" in i["reason"] for i in result["issues"])


def test_baseline_drift_is_rejected() -> None:
    result = review([{"op": "KEEP"}], expected="sha256:old", actual="sha256:new")
    assert any(i["code"] == "BASELINE_HASH_MISMATCH" for i in result["issues"])


def test_original_write_is_rejected() -> None:
    for op in ("write_f_block", "modify_original", "apply_to_original", "delete_original"):
        result = review([{"op": op, "source_id": "FB_Motor"}])
        assert result["issues"], op


def test_unparseable_block_must_be_retained() -> None:
    result = review([{"op": "DELETE", "source_id": "FB_Unparsed"}])
    assert any("must be retained" in i["reason"] or "protected" in i["reason"] for i in result["issues"])


def test_executable_plan_is_rejected_by_guard() -> None:
    plan = DiffPlan(plan_id="plan_x", ops=[DiffOp(op="MODIFY", source_id="FB_Motor")], executable=True)
    # from_dict/__post_init__ clamps to False, so force the invalid state to prove the guard.
    object.__setattr__(plan, "executable", True)
    issues = evaluate_diff_plan(plan, [SourceBinding.from_dict(b) for b in BINDINGS])
    assert any(i.code == "EXECUTABLE_FORBIDDEN" for i in issues)


def test_mocked_orchestration_is_explicitly_mocked_and_not_applied() -> None:
    result = review([{"op": "KEEP"}], mocked=True)
    assert result["mocked_orchestration"]["evidence_level"] == "mocked"
    assert result["mocked_orchestration"]["applied"] is False
    assert result["mocked_orchestration"]["executable"] is False
    assert result["mocked_orchestration"]["real_tia_v19_tested"] is False
    assert result["plan"]["executable"] is False
    assert result["evidence_level"] == "mocked"
    assert result["real_tia_v19_tested"] is False


def test_no_v19_real_evidence_ever() -> None:
    payload = review([{"op": "KEEP"}])
    BrownfieldServiceV2.assert_no_real_evidence(payload)
    forged = dict(payload)
    forged["evidence_level"] = "V19_real"
    with pytest.raises(ValueError):
        BrownfieldServiceV2.assert_no_real_evidence(forged)


def test_mocked_orchestrator_never_calls_tia() -> None:
    plan = DiffPlan(plan_id="p", ops=[DiffOp(op="MODIFY", source_id="FB_Motor")])
    out = mocked_orchestrate(plan, [SourceBinding.from_dict(b) for b in BINDINGS])
    assert out["declaration_only"] is True and out["applied"] is False
    assert "no TIA ADD/MODIFY/DELETE" in out["notice"]


def test_api_placeholder_endpoint_returns_mocked_and_rejects_negatives(tmp_path) -> None:
    store = build_store(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            ok = client.post("/api/v2/brownfield/diffplan", json={
                "project_id": "prj_demo", "base_revision": 0, "request_id": "req_bf_ok",
                "ops": [{"op": "KEEP", "source_id": "OB_Main"}], "source_bindings": BINDINGS,
                "mocked_orchestration": True,
            })
            assert ok.status_code == 200
            assert ok.json()["data"]["evidence_level"] == "mocked"
            assert ok.json()["data"]["plan"]["executable"] is False

            forbidden = client.post("/api/v2/brownfield/diffplan", json={
                "project_id": "prj_demo", "base_revision": 0, "request_id": "req_bf_bad",
                "ops": [{"op": "write_f_block", "source_id": "FB_Safety"}], "source_bindings": BINDINGS,
            })
            assert forbidden.status_code == 403
            assert forbidden.json()["evidence_level"] == "mocked"
    finally:
        app.dependency_overrides.clear()
