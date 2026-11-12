"""Executable V19 real delivery-chain transaction / probe (WP-01 / G5).

Default (no ``--real``) is a DRY RUN: it reports ``pending_real_machine`` and
does NOT connect to TIA Portal. Real chain execution is reserved for the
team-lead / QA serial schedule because TIA Portal V19 is an exclusive resource.

Real usage (serial, on the Windows V19 host):
  uv run python scripts/tia_delivery_chain_v2.py \
      --project-id prj_001 --job-id job_xxx --workspace-dir C:/work/prj_001 \
      --cpu-type-id 6ES7511-1AK02-0AB0/V2.9 --real

The chain is Create -> CreateDevice -> Import -> Compile(0 error) -> Save ->
Archive(exact path + sha256) -> Retrieve/reopen(MANDATORY). A missing CPU, a
missing create.projectPath, a compile error, a missing archive or a failed
reopen all produce an explicit FAILED receipt and NEVER NATIVE_ARCHIVED.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.tia_delivery_v2 import (
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    unpack_retrieve_reopen,
)
from gateway.app.services.plc.workspace_v2 import get_store
from plc_engine.engineering_ir.contracts import DELIVERY_STAGES
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import CompileReceipt
from plc_engine.process.artifact_manifest import ArtifactManifest


def derive_real_chain_evidence(
    result: dict[str, Any],
    verification: Any,
    gate_allowed: bool,
) -> tuple[bool, list[str]]:
    """P-14: prove V19_real from persisted receipts, NEVER from a boolean flag.

    ``adapter.real_machine`` is a construction parameter we set ourselves; using
    it as evidence lets a fake worker self-declare a real machine. Every claim
    here is derived from the job result, the stage receipts and the CPU probe
    receipt. Any gap makes the whole chain fail-closed to pending_real_machine.
    """
    reasons: list[str] = []
    real = EvidenceLevel.V19_REAL.value

    # CPU skeleton must be confirmed by a real CreateWithItem probe receipt.
    if not gate_allowed:
        reasons.append("CPU CreateWithItem verification gate did not pass")
    if not getattr(verification, "ok", False) or not getattr(verification, "verified_create_with_item", False):
        reasons.append("verification receipt has no CreateWithItem confirmation")
    if getattr(verification, "selection_status", "") != "approved":
        reasons.append("verification selection_status is not approved")
    if getattr(verification, "evidence_level", "") != real:
        reasons.append("verification evidence_level is not V19_real")
    if not getattr(verification, "raw_probe_receipt", None):
        reasons.append("verification has no raw C# probe receipt")

    if result.get("state") != "NATIVE_ARCHIVED":
        reasons.append("job state is not NATIVE_ARCHIVED")
    if result.get("evidence_level") != real:
        reasons.append("job evidence_level is not V19_real")

    chain = result.get("chain") if isinstance(result.get("chain"), dict) else {}
    if not chain.get("ok") or chain.get("state") != "NATIVE_ARCHIVED":
        reasons.append("chain result is not a successful NATIVE_ARCHIVED chain")
    if chain.get("evidence_level") != real:
        reasons.append("chain evidence_level is not V19_real")

    receipts = [r for r in (chain.get("stage_receipts") or []) if isinstance(r, dict)]
    by_stage = {str(r.get("stage")): r for r in receipts}
    required = ("CREATE", "CREATE_DEVICE", *DELIVERY_STAGES)
    for stage_name in dict.fromkeys(required):
        r = by_stage.get(stage_name)
        if not r or not r.get("ok") or r.get("evidence_level") != real:
            reasons.append(f"missing or non-real stage receipt: {stage_name}")

    # Compile: parsed through the same fail-closed parser used by the chain.
    compile_raw = (by_stage.get("COMPILE") or {}).get("raw_api_receipt") or {}
    try:
        parsed = CompileReceipt.from_worker(
            compile_raw,
            raw=json.dumps(compile_raw, ensure_ascii=False, sort_keys=True),
            evidence=EvidenceLevel.V19_REAL,
        )
        if parsed.error_count != 0:
            reasons.append("compile receipt does not prove error_count=0")
    except Exception as exc:  # noqa: BLE001 - fail-closed
        reasons.append(f"compile receipt unparsable: {exc}")

    # Retrieve/reopen is MANDATORY (Q-06), parsed through the chain's own unpacker.
    reopen_raw = (by_stage.get("RETRIEVE_REOPEN") or {}).get("raw_api_receipt") or {}
    try:
        unpack_retrieve_reopen(reopen_raw)
    except Exception as exc:  # noqa: BLE001 - fail-closed
        reasons.append(f"retrieve/reopen receipt unparsable: {exc}")

    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
    if not artifact.get("artifact_id") or not artifact.get("archive_path"):
        reasons.append("artifact lacks exact artifact_id / archive_path binding")
    if not str(artifact.get("archive_sha256") or "").startswith("sha256:"):
        reasons.append("artifact lacks a real sha256 archive hash")
    if artifact.get("reopen_ok") is not True:
        reasons.append("artifact.reopen_ok is not true")
    if artifact.get("evidence_level") != real:
        reasons.append("artifact evidence_level is not V19_real")
    artifact_compile = artifact.get("compile") if isinstance(artifact.get("compile"), dict) else {}
    if artifact_compile.get("compile_ok") is not True or artifact_compile.get("error_count") != 0:
        reasons.append("artifact compile receipt does not prove compile_ok / 0 errors")

    return (not reasons), reasons


def build_chain_payload(
    *,
    result: dict[str, Any],
    verification: Any,
    gate_allowed: bool,
    probe_path: str,
    cpu_type_id: str,
) -> dict[str, Any]:
    """P-14: derive the entire receipt from persisted evidence, never from a flag."""
    is_real, evidence_gaps = derive_real_chain_evidence(result, verification, gate_allowed)
    cpu_verified = bool(
        is_real
        and gate_allowed
        and verification.ok
        and verification.verified_create_with_item
        and verification.selection_status == "approved"
        and verification.evidence_level == EvidenceLevel.V19_REAL.value
        and verification.raw_probe_receipt
    )
    return {
        "mode": "real_chain_probe",
        "real_tia_v19_tested": is_real,
        "evidence_level": (
            EvidenceLevel.V19_REAL.value if is_real
            else EvidenceLevel.PENDING_REAL_MACHINE.value
        ),
        "evidence_gaps": evidence_gaps,
        "cpu_selection": {
            "type_identifier": cpu_type_id,
            "selection_status": "approved" if cpu_verified else "selected_by_lead",
            "verified_create_with_item": cpu_verified,
            "raw_evidence_path": probe_path,
        },
        "raw_evidence_path": result.get("raw_evidence_path", ""),
        "result": result,
        "delivery_complete": is_real,
        "g5_status": "PASSED" if is_real else "pending_real_machine",
        "notice": (
            "V19 real full-chain receipt" if is_real
            else "chain FAILED or mocked; no native archive published; pending_real_machine where applicable"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PLC Agent V2 native TIA delivery chain")
    parser.add_argument("--project-id", default="prj_v2_real")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--workspace-dir", default="")
    parser.add_argument("--cpu-type-id", default="", help="LEAD-APPROVED CPU skeleton (U-02)")
    parser.add_argument("--manifest-json", default="", help="optional ArtifactManifest JSON")
    parser.add_argument("--real", action="store_true", help="execute the real V19 chain (serial schedule only)")
    parser.add_argument("--output", default="", help="optional raw receipt output path")
    args = parser.parse_args()

    if not args.real:
        payload = {
            "mode": "dry_run",
            "evidence_level": EvidenceLevel.PENDING_REAL_MACHINE.value,
            "real_tia_v19_tested": False,
            "notice": "no V19 real chain executed; must never be shown as delivery complete",
            "next": "team lead / QA must schedule the serial real-machine run with --real",
        }
        _emit(payload, args.output)
        return

    if not args.cpu_type_id:
        raise SystemExit("CPU_TEMPLATE_NOT_SELECTED: --cpu-type-id is required (lead-appointed skeleton)")
    if not args.workspace_dir:
        raise SystemExit("--workspace-dir is required for a real chain")
    if not args.job_id:
        raise SystemExit("--job-id is required (create a delivery job through the v2 API first)")

    # U-02: the lead-appointed skeleton is selected_by_lead, NOT approved.
    # A real CreateWithItem probe on a TEMPORARY project copy is MANDATORY
    # before the delivery chain. Failure / TIA unavailable = fail-closed,
    # never auto-switch to another model, never guess.
    from gateway.app.services.plc.cpu_verification_v2 import (
        persist_verification_receipt,
        verification_gate,
        verify_create_with_item,
    )

    probe_adapter = TiaOpennessCliAdapter(real_machine=True, evidence_level=EvidenceLevel.V19_REAL)
    verification = verify_create_with_item(
        probe_adapter,
        cpu_type_identifier=args.cpu_type_id,
        workspace_dir=args.workspace_dir,
    )
    probe_path = persist_verification_receipt(verification)
    allowed, gate_error = verification_gate(verification)
    if not allowed:
        _emit({
            "mode": "cpu_verification_failed",
            "cpu_type_identifier": args.cpu_type_id,
            "error": gate_error,
            "verification_receipt": verification.to_dict(),
            "raw_evidence_path": probe_path,
            "real_tia_v19_tested": False,
            "notice": "fail-closed: no delivery chain started; no automatic fallback to another CPU model",
        }, args.output)
        raise SystemExit(2)

    manifest = ArtifactManifest()
    if args.manifest_json:
        manifest = ArtifactManifest.from_dict(json.loads(Path(args.manifest_json).read_text(encoding="utf-8")))

    store = get_store()
    adapter = TiaOpennessCliAdapter(real_machine=True, evidence_level=EvidenceLevel.V19_REAL)
    request = DeliveryChainRequest(
        project_id=args.project_id,
        job_id=args.job_id,
        project_name=f"{args.project_id}_V19",
        workspace_dir=args.workspace_dir,
        cpu_type_identifier=args.cpu_type_id,
        manifest=manifest,
    )
    result = DeliveryCoordinator(store).run_chain(args.job_id, adapter=adapter, request=request)
    payload = build_chain_payload(
        result=result,
        verification=verification,
        gate_allowed=allowed,
        probe_path=probe_path,
        cpu_type_id=args.cpu_type_id,
    )
    _emit(payload, args.output)
    if payload["evidence_level"] != EvidenceLevel.V19_REAL.value:
        raise SystemExit(2)


def _emit(payload: dict, output: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    print(text)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
