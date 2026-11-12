"""P-14: real-machine evidence must be derived from receipts, never self-declared.

A fake worker / forged result with state=NATIVE_ARCHIVED but no real stage
receipts must NEVER produce V19_real, approved, or delivery_complete=True.
"""
from __future__ import annotations

import json

import pytest

from gateway.app.services.plc.cpu_verification_v2 import CpuVerificationReceipt
from plc_engine.engineering_ir.evidence import EvidenceLevel
from scripts.tia_delivery_chain_v2 import (
    build_chain_payload,
    derive_real_chain_evidence,
)

REAL = EvidenceLevel.V19_REAL.value
CPU = "6ES7511-1AK02-0AB0/V2.9"
STAGES = (
    "CREATE", "CREATE_DEVICE", "IMPORT", "COMPILE",
    "SAVE", "ARCHIVE", "HASH", "RETRIEVE_REOPEN",
)

COMPILE_RAW = {
    "ok": True,
    "compile": {"state": "Success", "errorCount": 0, "warningCount": 0, "staticGatePassed": True},
}
REOPEN_RAW = {
    "ok": True,
    "retrieve": {"ok": True, "reopenOk": True, "projectPath": "C:/work/reopen/proj.ap19"},
}
ARTIFACT = {
    "artifact_id": "a_deadbeef",
    "archive_path": "C:/work/archive/proj.zap19",
    "archive_sha256": "sha256:abcdef0123456789",
    "reopen_ok": True,
    "evidence_level": REAL,
    "compile": {"compile_ok": True, "error_count": 0},
}


def _stage(name: str, raw: dict | None = None, *, level: str = REAL, ok: bool = True) -> dict:
    return {
        "stage": name, "ok": ok, "state": "TIA_COMPILED", "evidence_level": level,
        "raw_api_receipt": raw if raw is not None else {"ok": True},
        "error_code": "", "message": "",
    }


def _full_result(**overrides) -> dict:
    stages = [
        _stage(
            name,
            COMPILE_RAW if name == "COMPILE" else (REOPEN_RAW if name == "RETRIEVE_REOPEN" else None),
        )
        for name in STAGES
    ]
    result = {
        "state": "NATIVE_ARCHIVED",
        "evidence_level": REAL,
        "chain": {
            "ok": True, "state": "NATIVE_ARCHIVED", "evidence_level": REAL,
            "stage_receipts": stages, "artifact": None,
        },
        "artifact": dict(ARTIFACT),
        "raw_evidence_path": "evidence/v2/T02/job_real.json",
    }
    result.update(overrides)
    return result


def _verification(**overrides) -> CpuVerificationReceipt:
    kwargs = {
        "cpu_type_identifier": CPU,
        "ok": True,
        "verified_create_with_item": True,
        "selection_status": "approved",
        "evidence_level": REAL,
        "raw_probe_receipt": {"ok": True, "probe": [{"typeId": CPU, "ok": True}]},
    }
    kwargs.update(overrides)
    return CpuVerificationReceipt(**kwargs)


def _payload(result: dict, verification=None, allowed: bool = True) -> dict:
    return build_chain_payload(
        result=result,
        verification=verification if verification is not None else _verification(),
        gate_allowed=allowed,
        probe_path="evidence/v2/T02/cpu_create_with_item_probe.json",
        cpu_type_id=CPU,
    )


def _assert_no_real_claim(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    assert payload["real_tia_v19_tested"] is False
    assert payload["evidence_level"] != REAL
    assert payload["delivery_complete"] is False
    assert payload["g5_status"] == "pending_real_machine"
    assert payload["cpu_selection"]["selection_status"] == "selected_by_lead"
    assert payload["cpu_selection"]["verified_create_with_item"] is False
    assert "V19 real full-chain receipt" not in text
    assert payload["notice"].startswith("chain FAILED or mocked")
    assert payload["evidence_gaps"]


def test_complete_real_receipts_prove_v19_real() -> None:
    """The happy path must still be reachable with genuine receipts."""
    ok, gaps = derive_real_chain_evidence(_full_result(), _verification(), True)
    assert ok, gaps
    payload = _payload(_full_result())
    assert payload["real_tia_v19_tested"] is True
    assert payload["evidence_level"] == REAL
    assert payload["delivery_complete"] is True
    assert payload["cpu_selection"]["selection_status"] == "approved"
    assert payload["notice"] == "V19 real full-chain receipt"


def test_forged_native_archived_without_stage_receipts_is_rejected() -> None:
    """The P-01/P-14 attack: fake worker claims NATIVE_ARCHIVED."""
    forged = {
        "state": "NATIVE_ARCHIVED",
        "evidence_level": REAL,
        "chain": {"ok": True, "state": "NATIVE_ARCHIVED", "evidence_level": REAL,
                  "stage_receipts": [], "artifact": None},
        "artifact": None,
        "raw_evidence_path": "",
    }
    _assert_no_real_claim(_payload(forged))


def test_adapter_real_machine_flag_alone_never_proves_real() -> None:
    """bool(adapter.real_machine) is a construction parameter, not evidence."""
    forged = _full_result(chain={"ok": True, "state": "NATIVE_ARCHIVED",
                                 "evidence_level": "mocked", "stage_receipts": [], "artifact": None})
    _assert_no_real_claim(_payload(forged))


@pytest.mark.parametrize("bad", [
    {"state": "TIA_COMPILED"},
    {"evidence_level": "mocked"},
    {"artifact": {}},
    {"artifact": {**ARTIFACT, "reopen_ok": False}},
    {"artifact": {**ARTIFACT, "archive_sha256": "not-a-hash"}},
    {"artifact": {**ARTIFACT, "compile": {"compile_ok": False, "error_count": 2}}},
])
def test_any_missing_real_receipt_is_fail_closed(bad: dict) -> None:
    _assert_no_real_claim(_payload(_full_result(**bad)))


def test_compile_errors_or_missing_reopen_block_real_claim() -> None:
    stages = [
        _stage(name, {"ok": True, "compile": {"state": "Failed", "errorCount": 2}})
        if name == "COMPILE"
        else _stage(name, {"ok": True}) if name == "RETRIEVE_REOPEN"
        else _stage(name)
        for name in STAGES
    ]
    result = _full_result(chain={"ok": True, "state": "NATIVE_ARCHIVED",
                                 "evidence_level": REAL, "stage_receipts": stages, "artifact": None})
    _assert_no_real_claim(_payload(result))


@pytest.mark.parametrize("bad_verification", [
    _verification(raw_probe_receipt={}),
    _verification(evidence_level="mocked"),
    _verification(selection_status="selected_by_lead"),
    _verification(verified_create_with_item=False),
    _verification(ok=False),
])
def test_unverified_cpu_never_produces_approved_or_real(bad_verification) -> None:
    _assert_no_real_claim(_payload(_full_result(), bad_verification))


def test_verification_gate_false_blocks_even_with_full_receipts() -> None:
    _assert_no_real_claim(_payload(_full_result(), allowed=False))
