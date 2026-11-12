"""CPU skeleton CreateWithItem verification (U-02 lead ruling, WP-01/WP-06).

The lead selected `6ES7511-1AK02-0AB0/V2.9` as the TARGET skeleton, but the
candidate list is static and unverified. Its state MUST stay
`selected_by_lead` + `verification_required=true` + `verified_create_with_item=false`
until a real `CreateWithItem` probe on a TEMPORARY project copy passes.

This module NEVER auto-selects another model, NEVER guesses, and NEVER writes
to the real delivery project. A failed/unavailable probe is fail-closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from gateway.app.services.plc.evidence_v2 import EvidenceService
from gateway.app.services.plc.tia_delivery_v2 import (
    TiaOpennessCliAdapter,
    TiaUnavailableError,
    unpack_create_project_path,
)
from gateway.app.services.plc.workspace_v2 import utc_now
from plc_engine.engineering_ir.evidence import EvidenceLevel

LEAD_SELECTED_CPU = "6ES7511-1AK02-0AB0/V2.9"
CPU_TEMPLATE_NOT_SELECTED = "CPU_TEMPLATE_NOT_SELECTED"


@dataclass
class CpuVerificationReceipt:
    """One real or failed CreateWithItem verification receipt."""

    cpu_type_identifier: str = ""
    ok: bool = False
    verified_create_with_item: bool = False
    selection_status: str = "selected_by_lead"
    error_code: str = ""
    error_message: str = ""
    evidence_level: str = EvidenceLevel.PENDING_REAL_MACHINE.value
    probed_at: str = ""
    raw_probe_receipt: dict[str, Any] = field(default_factory=dict)
    temporary_project_path: str = ""
    notice: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_type_identifier": self.cpu_type_identifier,
            "ok": self.ok,
            "verified_create_with_item": self.verified_create_with_item,
            "selection_status": self.selection_status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "evidence_level": self.evidence_level,
            "probed_at": self.probed_at,
            "raw_probe_receipt": self.raw_probe_receipt,
            "temporary_project_path": self.temporary_project_path,
            "notice": self.notice,
        }


def verify_create_with_item(
    adapter: TiaOpennessCliAdapter,
    *,
    cpu_type_identifier: str,
    workspace_dir: str,
) -> CpuVerificationReceipt:
    """Run a REAL CreateWithItem probe on a disposable temporary project copy.

    Steps (all on a temporary copy, never the delivery project):
      create-project -> probe-device-types --type-ids <cpu> -> close-project
    A matching `probe[].ok == true` is the ONLY accepted verification.
    """
    receipt = CpuVerificationReceipt(
        cpu_type_identifier=cpu_type_identifier,
        probed_at=utc_now(),
    )
    if not cpu_type_identifier:
        receipt.error_code = CPU_TEMPLATE_NOT_SELECTED
        receipt.error_message = "no CPU skeleton supplied; delivery must fail explicitly"
        receipt.notice = "no automatic fallback to any other model"
        return receipt
    if cpu_type_identifier != LEAD_SELECTED_CPU:
        receipt.error_code = CPU_TEMPLATE_NOT_SELECTED
        receipt.error_message = (
            f"CPU {cpu_type_identifier!r} is not the lead-appointed skeleton {LEAD_SELECTED_CPU!r}; "
            "never auto-switch models"
        )
        receipt.notice = "no automatic fallback to any other model"
        return receipt

    try:
        created = adapter.create_project(str(workspace_dir) + "/cpu_probe", "CPU_PROBE")
        project_path = unpack_create_project_path(created)
        receipt.temporary_project_path = project_path
        probe = adapter._invoke(  # noqa: SLF001 - controlled single entry for this probe
            "probe-device-types", "--project", project_path,
            "--type-ids", cpu_type_identifier, timeout_s=300,
        )
        receipt.raw_probe_receipt = probe
        items = probe.get("probe") if isinstance(probe.get("probe"), list) else []
        matched = [
            item for item in items
            if isinstance(item, dict)
            and str(item.get("typeId") or "") == cpu_type_identifier
            and bool(item.get("ok"))
        ]
        try:
            adapter._invoke("close-project", "--project", project_path, timeout_s=120)  # noqa: SLF001
        except Exception:  # noqa: BLE001 - probe cleanup must not mask the verdict
            pass
        if matched:
            receipt.ok = True
            receipt.verified_create_with_item = True
            receipt.selection_status = "approved"
            receipt.evidence_level = EvidenceLevel.V19_REAL.value if adapter.real_machine else EvidenceLevel.MOCKED.value
            receipt.notice = "CreateWithItem verified on a temporary copy; skeleton may be used for the delivery chain"
        else:
            receipt.error_code = CPU_TEMPLATE_NOT_SELECTED
            receipt.error_message = "CreateWithItem probe did not confirm the lead-appointed CPU skeleton"
            receipt.notice = "fail-closed: no delivery chain, no automatic fallback"
    except (TiaUnavailableError, ValueError) as exc:
        receipt.error_code = "TIA_UNAVAILABLE" if isinstance(exc, TiaUnavailableError) else CPU_TEMPLATE_NOT_SELECTED
        receipt.error_message = str(exc)
        receipt.evidence_level = EvidenceLevel.PENDING_REAL_MACHINE.value
        receipt.notice = "TIA unavailable or receipt malformed; pending_real_machine, no delivery chain"
    except Exception as exc:  # noqa: BLE001 - any worker error is fail-closed
        receipt.error_code = "TIA_UNAVAILABLE"
        receipt.error_message = f"CreateWithItem probe failed: {exc}"
        receipt.notice = "fail-closed: no delivery chain"
    return receipt


def persist_verification_receipt(receipt: CpuVerificationReceipt) -> str:
    """Write the verification receipt separately (never overwrite historical evidence)."""
    path = EvidenceService.write_ledger(
        "T02", "cpu_create_with_item_probe",
        {
            "receipt": receipt.to_dict(),
            "real_tia_v19_tested": receipt.evidence_level == EvidenceLevel.V19_REAL.value,
            "notice": receipt.notice,
        },
    )
    return str(path)


def verification_gate(receipt: CpuVerificationReceipt) -> tuple[bool, dict[str, Any]]:
    """Return (allowed, error_payload) for the delivery chain precondition."""
    if receipt.ok and receipt.verified_create_with_item and receipt.selection_status == "approved":
        return True, {}
    return False, {
        "code": receipt.error_code or CPU_TEMPLATE_NOT_SELECTED,
        "message": receipt.error_message or "CPU skeleton is not verified",
        "evidence_level": receipt.evidence_level,
        "pending_real_machine": receipt.evidence_level == EvidenceLevel.PENDING_REAL_MACHINE.value,
        "native_archived": False,
    }


def receipt_json(receipt: CpuVerificationReceipt) -> str:
    """Deterministic JSON for CLI output / evidence."""
    return json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
