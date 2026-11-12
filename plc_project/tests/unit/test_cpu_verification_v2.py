"""U-02 CPU selection + mandatory CreateWithItem probe (offline contracts)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gateway.app.services.plc.capability_v2 import apply_lead_cpu_selection
from gateway.app.services.plc.cpu_verification_v2 import (
    LEAD_SELECTED_CPU,
    verification_gate,
    verify_create_with_item,
)
from gateway.app.services.plc.tia_delivery_v2 import TiaOpennessCliAdapter
from plc_engine.engineering_ir.models import TiaCapabilityManifest

REPO = Path(__file__).resolve().parents[2]


def make_manifest() -> TiaCapabilityManifest:
    return TiaCapabilityManifest(
        probe_receipt_id="g0_contract", tia_version="V19",
        cpu_templates=[
            {"type_identifier": LEAD_SELECTED_CPU, "cpu_template": "S7-1500 CPU 1511-1 PN",
             "verified_create_with_item": False, "catalog_source": "static"},
            {"type_identifier": "6ES7513-1AL02-0AB0/V2.9", "cpu_template": "S7-1500 CPU 1513-1 PN",
             "verified_create_with_item": False, "catalog_source": "static"},
        ],
        raw_probe_receipt={"probe": {"ok": True}},
    )


def worker(probe_ok: bool = True, raise_on: str = "") -> Any:
    def call(command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
        if command == raise_on:
            raise RuntimeError("TIA Portal unavailable")
        if command == "create-project":
            return {"ok": True, "create": {"ok": True, "projectPath": "C:/tmp/cpu_probe/CPU_PROBE.ap19"}}
        if command == "probe-device-types":
            return {"ok": probe_ok, "probe": [{"typeId": LEAD_SELECTED_CPU, "ok": probe_ok,
                                               "api": "DeviceComposition.CreateWithItem"}]}
        if command == "close-project":
            return {"ok": True}
        return {"ok": False, "error": f"unexpected {command}"}
    return call


def test_lead_selection_is_never_claimed_as_approved_or_verified() -> None:
    manifest = apply_lead_cpu_selection(make_manifest(), LEAD_SELECTED_CPU, selected_by="team-lead", reason="U-02")
    assert manifest.selected_cpu_template == LEAD_SELECTED_CPU
    selected = next(c for c in manifest.cpu_templates if c["type_identifier"] == LEAD_SELECTED_CPU)
    assert selected["selection_status"] == "selected_by_lead"
    assert selected["verification_required"] is True
    assert selected["verified_create_with_item"] is False
    assert "approved" not in str(selected.get("selection_status")).lower()
    assert "NOT approved" in manifest.selection_note


def test_unknown_cpu_is_rejected_not_guessed() -> None:
    with pytest.raises(ValueError):
        apply_lead_cpu_selection(make_manifest(), "6ES7999-UNKNOWN/V1.0")


def test_create_with_item_success_upgrades_to_approved() -> None:
    receipt = verify_create_with_item(
        TiaOpennessCliAdapter(worker=worker(True)),
        cpu_type_identifier=LEAD_SELECTED_CPU, workspace_dir="C:/tmp",
    )
    assert receipt.ok is True
    assert receipt.verified_create_with_item is True
    assert receipt.selection_status == "approved"
    assert verification_gate(receipt)[0] is True


def test_probe_failure_is_fail_closed() -> None:
    receipt = verify_create_with_item(
        TiaOpennessCliAdapter(worker=worker(False)),
        cpu_type_identifier=LEAD_SELECTED_CPU, workspace_dir="C:/tmp",
    )
    assert receipt.ok is False
    assert receipt.error_code == "CPU_TEMPLATE_NOT_SELECTED"
    allowed, error = verification_gate(receipt)
    assert allowed is False and error["native_archived"] is False


def test_missing_or_foreign_cpu_never_auto_switches_model() -> None:
    for cpu in ("", "6ES7513-1AL02-0AB0/V2.9"):
        receipt = verify_create_with_item(
            TiaOpennessCliAdapter(worker=worker(True)),
            cpu_type_identifier=cpu, workspace_dir="C:/tmp",
        )
        assert receipt.error_code == "CPU_TEMPLATE_NOT_SELECTED"
        assert receipt.cpu_type_identifier == cpu  # never replaced with another model
        assert receipt.verified_create_with_item is False
        assert verification_gate(receipt)[0] is False


def test_tia_unavailable_is_explicit_and_pending_real_machine() -> None:
    receipt = verify_create_with_item(
        TiaOpennessCliAdapter(worker=worker(True, raise_on="create-project")),
        cpu_type_identifier=LEAD_SELECTED_CPU, workspace_dir="C:/tmp",
    )
    assert receipt.error_code == "TIA_UNAVAILABLE"
    assert receipt.evidence_level == "pending_real_machine"
    assert verification_gate(receipt)[0] is False


def test_cpu_selection_evidence_receipt_is_honest() -> None:
    payload = json.loads((REPO / "evidence/v2/T01/cpu_selection.json").read_text(encoding="utf-8"))
    assert payload["type_identifier"] == LEAD_SELECTED_CPU
    assert payload["selection_status"] == "selected_by_lead"
    assert payload["verification_required"] is True
    assert payload["verified_create_with_item"] is False
    assert payload["approved"] is False
    assert payload["create_with_item_probe"]["executed"] is False
    assert payload["real_tia_v19_tested"] is False
    assert "绝不冒充" in payload["notice"]


def test_real_chain_script_has_mandatory_verification_gate() -> None:
    source = (REPO / "scripts/tia_delivery_chain_v2.py").read_text(encoding="utf-8")
    assert "verify_create_with_item" in source
    assert "verification_gate" in source
    assert "cpu_verification_failed" in source
    assert "never auto-switch" in source or "no automatic fallback" in source
