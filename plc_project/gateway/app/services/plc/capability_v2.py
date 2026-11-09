"""G0 TiaCapabilityManifest + read-only real-machine probe (Q-05 / U-02).

The probe calls the existing C# ``status`` command only (no project creation,
no TIA write). If the worker is unavailable the manifest is explicitly stamped
``pending_real_machine`` with the raw failure receipt — never a fake success.

Candidate CPU skeletons are STATIC, documented V19 order numbers. They are NOT
claimed as verified until a real ``probe-device-types`` CreateWithItem receipt
is attached by the serial QA schedule. The candidate list is reported back to
the team lead, who must appoint the approved CPU skeleton.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gateway.app.services.plc.workspace_v2 import WorkspaceStore, utc_now
from plc_engine.engineering_ir.contracts import TIA_VERSION
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.hashing import canonical_dumps, sha256_prefixed
from plc_engine.engineering_ir.models import TiaCapabilityManifest

#: Static, documented V19 CPU candidates. ``verified_create_with_item`` is
#: false until a real CreateWithItem probe receipt is attached.
APPROVED_CPU_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "cpu_template": "S7-1500 / CPU 1511-1 PN",
        "type_identifier": "6ES7511-1AK02-0AB0/V2.9",
        "firmware": "V2.9",
        "catalog_source": "static_approved_candidate_v19",
        "verified_create_with_item": False,
    },
    {
        "cpu_template": "S7-1500 / CPU 1513-1 PN",
        "type_identifier": "6ES7513-1AL02-0AB0/V2.9",
        "firmware": "V2.9",
        "catalog_source": "static_approved_candidate_v19",
        "verified_create_with_item": False,
    },
    {
        "cpu_template": "S7-1500 / CPU 1515-2 PN",
        "type_identifier": "6ES7515-2AM02-0AB0/V2.9",
        "firmware": "V2.9",
        "catalog_source": "static_approved_candidate_v19",
        "verified_create_with_item": False,
    },
    {
        "cpu_template": "S7-1200 / CPU 1214C DC/DC/DC",
        "type_identifier": "6ES7214-1AG40-0XB0/V4.5",
        "firmware": "V4.5",
        "catalog_source": "static_approved_candidate_v19",
        "verified_create_with_item": False,
    },
)


class CpuNotSelectedError(RuntimeError):
    """Raised when a delivery starts without an approved CPU skeleton."""


def default_status_invoker() -> dict[str, Any]:
    """Read-only C# ``status`` probe through the existing Openness CLI wrapper.

    Any failure is returned as a structured pending receipt; it is never
    converted into an ``ok=true`` result.
    """
    try:
        from agents.plc.tia.openness_cli import openness_cli
    except Exception as exc:  # noqa: BLE001 - fail-closed probe, all errors recorded
        return {
            "ok": False,
            "error": f"openness_cli import failed: {type(exc).__name__}: {exc}",
            "raw_probe_receipt": {},
            "evidence_level": EvidenceLevel.PENDING_REAL_MACHINE.value,
        }
    try:
        receipt = openness_cli("status", timeout_s=60)
        if not isinstance(receipt, dict):
            raise TypeError(f"status receipt is not an object: {type(receipt).__name__}")
        return {"ok": bool(receipt.get("ok")), "raw_probe_receipt": receipt, "error": ""}
    except Exception as exc:  # noqa: BLE001 - fail-closed probe, all errors recorded
        return {
            "ok": False,
            "error": f"status probe failed: {type(exc).__name__}: {exc}",
            "raw_probe_receipt": {},
            "evidence_level": EvidenceLevel.PENDING_REAL_MACHINE.value,
        }


def probe_capability(
    *,
    store: WorkspaceStore | None = None,
    invoker: Callable[[], dict[str, Any]] | None = None,
    write_evidence: bool = True,
    evidence_root: Path | None = None,
) -> TiaCapabilityManifest:
    """Run the G0 read-only probe and persist the manifest + raw receipt."""
    probe = (invoker or default_status_invoker)()
    raw_receipt = probe.get("raw_probe_receipt") if isinstance(probe.get("raw_probe_receipt"), dict) else {}
    status_ok = bool(probe.get("ok")) and bool(raw_receipt.get("opennessAvailable", True))
    version = str(raw_receipt.get("tiaVersion") or TIA_VERSION)
    probed_at = utc_now()

    if status_ok:
        level = EvidenceLevel.V19_REAL
        cpu_templates = [dict(item) for item in APPROVED_CPU_CANDIDATES]
        status_note = (
            "real status receipt obtained; CPU candidates are static V19 order numbers, "
            "CreateWithItem verification still pending_real_machine"
        )
    else:
        level = EvidenceLevel.PENDING_REAL_MACHINE
        cpu_templates = []
        status_note = (
            "TIA/Openness status probe unavailable; no real CPU list obtained; "
            "candidate list must be reported to the lead only after a real probe"
        )

    payload = {
        "tia_version": version,
        "probe": probe,
        "status_ok": status_ok,
        "candidate_count": len(cpu_templates),
    }
    manifest = TiaCapabilityManifest(
        probe_receipt_id="g0_" + sha256_prefixed(canonical_dumps({**payload, "probed_at": probed_at}))[7:23],
        tia_version=version,
        cpu_templates=cpu_templates,
        selected_cpu_template="",
        selection_note=status_note,
        probed_at=probed_at,
        raw_probe_receipt={"probe": probe, "status_receipt": raw_receipt},
        evidence_level=level,
        status_receipt={
            "ok": status_ok,
            "openness_available": bool(raw_receipt.get("opennessAvailable")),
            "tia_running": bool(raw_receipt.get("tiaRunning")),
            "engineering_dll": str(raw_receipt.get("engineeringDll") or ""),
            "error": str(probe.get("error") or ""),
            "note": status_note,
        },
    )
    if store is not None:
        store.save_capability_probe(manifest)
    if write_evidence:
        from gateway.app.services.plc.evidence_v2 import EvidenceService

        EvidenceService.write_ledger(
            "T01",
            "capability_probe",
            {
                "manifest": manifest.to_dict(),
                "real_tia_v19_tested": status_ok,
                "raw_evidence_path": "evidence/v2/T01/capability_probe.json",
                "candidate_cpu_templates": manifest.candidate_type_ids(),
                "note": "CPU skeleton selection awaits the lead's explicit approval (U-02)",
            },
            root=evidence_root,
        )
    return manifest


def attach_create_with_item_receipt(
    manifest: TiaCapabilityManifest,
    probe_receipt: dict[str, Any],
    *,
    store: WorkspaceStore | None = None,
) -> TiaCapabilityManifest:
    """Attach a real ``probe-device-types`` receipt and mark verified CPUs.

    This is a genuine CreateWithItem probe and must be scheduled serially by
    the lead / QA; it is never executed implicitly by the offline G0 probe.
    """
    probe_items = probe_receipt.get("probe") or []
    verified: dict[str, bool] = {
        str(item.get("typeId") or ""): bool(item.get("ok"))
        for item in probe_items
        if isinstance(item, dict)
    }
    for candidate in manifest.cpu_templates:
        type_id = str(candidate.get("type_identifier") or "")
        candidate["verified_create_with_item"] = bool(verified.get(type_id, False))
        if candidate["verified_create_with_item"]:
            candidate["verification_receipt"] = "V19_real:CreateWithItem"
    manifest.raw_probe_receipt["create_with_item_probe"] = probe_receipt
    if any(c["verified_create_with_item"] for c in manifest.cpu_templates):
        manifest.evidence_level = EvidenceLevel.V19_REAL
    if store is not None:
        store.save_capability_probe(manifest)
    return manifest


def select_approved_cpu(
    manifest: TiaCapabilityManifest,
    explicit_type_id: str = "",
) -> tuple[str | None, str]:
    """Choose the CPU skeleton: lead-appointed first, else first verified item."""
    if explicit_type_id:
        for candidate in manifest.cpu_templates:
            if candidate.get("type_identifier") == explicit_type_id:
                return explicit_type_id, f"lead_appointed:{explicit_type_id}"
        return None, f"lead_appointed type id {explicit_type_id!r} is not in the probe manifest"
    verified = manifest.verified_candidates()
    if verified:
        chosen = str(verified[0].get("type_identifier") or "")
        return chosen, "first_verified_create_with_item_in_manifest (U-02 default, logged)"
    return None, "pending_real_machine: no CreateWithItem-verified CPU and no lead appointment"


def assert_cpu_selected(type_identifier: str, device_type_identifier: str = "") -> None:
    """Fail-closed gate for T02 delivery (CPU not selected is an explicit failure)."""
    if not type_identifier or not device_type_identifier:
        raise CpuNotSelectedError(
            "CPU_TEMPLATE_NOT_SELECTED: G0 manifest has no approved CPU skeleton; "
            "delivery must fail explicitly (never guess a CPU)"
        )


def probe_cli_payload(manifest: TiaCapabilityManifest) -> dict[str, Any]:
    """Return the CLI report handed to the team lead after a G0 probe."""
    return {
        "probe_receipt_id": manifest.probe_receipt_id,
        "tia_version": manifest.tia_version,
        "probed_at": manifest.probed_at,
        "evidence_level": manifest.evidence_level.value,
        "status_receipt": manifest.status_receipt,
        "candidate_cpu_templates": manifest.candidate_type_ids(),
        "cpu_templates": manifest.cpu_templates,
        "selected_cpu_template": manifest.selected_cpu_template,
        "selection_note": manifest.selection_note,
        "real_tia_v19_tested": manifest.evidence_level is EvidenceLevel.V19_REAL,
        "raw_evidence_path": "evidence/v2/T01/capability_probe.json",
    }
