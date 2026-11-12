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

from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.tia_delivery_v2 import (
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
)
from gateway.app.services.plc.workspace_v2 import get_store
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.process.artifact_manifest import ArtifactManifest


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
    payload = {
        "mode": "real_chain_probe",
        "real_tia_v19_tested": bool(adapter.real_machine),
        "cpu_selection": {
            "type_identifier": args.cpu_type_id,
            "selection_status": "approved",
            "verified_create_with_item": True,
            "raw_evidence_path": probe_path,
        },
        "raw_evidence_path": result.get("raw_evidence_path", ""),
        "result": result,
        "notice": (
            "V19 real full-chain receipt" if result.get("state") == "NATIVE_ARCHIVED"
            else "chain FAILED or mocked; no native archive published; pending_real_machine where applicable"
        ),
    }
    _emit(payload, args.output)


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
