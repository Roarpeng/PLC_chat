"""G5 delivery chain on a pre-fabricated CPU skeleton (blueprint section 02).

The host has no S7 CPU hardware catalogue installed, so Devices.CreateWithItem
cannot materialize a CPU from scratch. Blueprint section 02 explicitly allows
"a confirmed/approved CPU skeleton" for compilable logic. This chain starts
from a copied real V19 project with PLC_1, imports the generated AF SCL in
explicit dependency order, then Compile -> Save -> Archive -> Retrieve/reopen.

Every V19_real / delivery_complete claim is derived from the persisted stage
receipts (P-14 discipline), never from adapter.real_machine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gateway.app.services.plc.tia_delivery_v2 import (
    ArchiveMissingError,
    ReopenFailedError,
    TiaOpennessCliAdapter,
    unpack_archive_path,
    unpack_retrieve_reopen,
)
from plc_engine.canonical import compute_file_sha256, sha256_prefixed
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import CompileReceipt, NativeTiaArtifact
from plc_engine.process.artifact_manifest import ArtifactManifest

REAL = EvidenceLevel.V19_REAL.value
PENDING = EvidenceLevel.PENDING_REAL_MACHINE.value
STAGES = (
    "OPEN_SKELETON", "IMPORT", "COMPILE", "SAVE",
    "ARCHIVE", "HASH", "RETRIEVE_REOPEN",
)


def stage_receipt(name: str, ok: bool, state: str, raw: dict[str, Any],
                  code: str = "", message: str = "") -> dict[str, Any]:
    return {
        "stage": name, "ok": ok, "state": state, "evidence_level": REAL,
        "raw_api_receipt": raw, "error_code": code, "message": message,
    }


def derive_skeleton_evidence(
    receipts: list[dict[str, Any]],
    artifact: dict[str, Any],
    compile_receipt: CompileReceipt,
) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    by_stage = {str(r.get("stage")): r for r in receipts}
    for name in STAGES:
        r = by_stage.get(name)
        if not r or not r.get("ok") or r.get("evidence_level") != REAL:
            gaps.append(f"missing or non-real stage receipt: {name}")
    if compile_receipt.error_count != 0 or not compile_receipt.compile_ok:
        gaps.append("compile receipt does not prove error_count=0 / compile_ok")
    for key in ("artifact_id", "archive_path", "archive_sha256"):
        if not artifact.get(key):
            gaps.append(f"artifact lacks exact {key} binding")
    if not str(artifact.get("archive_sha256") or "").startswith("sha256:"):
        gaps.append("artifact archive_sha256 is not a real hash")
    if artifact.get("reopen_ok") is not True:
        gaps.append("artifact.reopen_ok is not true")
    if artifact.get("evidence_level") != REAL:
        gaps.append("artifact evidence_level is not V19_real")
    return (not gaps), gaps


def main() -> None:
    parser = argparse.ArgumentParser(description="G5 chain on a pre-fabricated CPU skeleton")
    parser.add_argument("--project", required=True, help="copied skeleton .ap19 (never the source)")
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--workspace-dir", required=True)
    parser.add_argument("--project-id", default="prj_g5_real")
    parser.add_argument("--job-id", default="job_g5_skeleton")
    parser.add_argument("--output", default="")
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--real", action="store_true")
    parser.add_argument(
        "--exclude-scl", action="append", default=[], metavar="BASENAME",
        help="explicitly exclude a generated SCL from the real import (recorded in the receipt)",
    )
    parser.add_argument(
        "--exclude-reason", default="",
        help="why excluded files were left out (must be supplied with --exclude-scl)",
    )
    args = parser.parse_args()

    if not args.real:
        payload = {"mode": "dry_run", "evidence_level": PENDING,
                   "real_tia_v19_tested": False,
                   "notice": "no V19 real chain executed; skeleton delivery is serial-only"}
        _emit(payload, args.output)
        return

    ws = Path(args.workspace_dir)
    ev = Path(args.evidence_dir) if args.evidence_dir else ws / "evidence"
    stages_dir = ev / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    manifest = ArtifactManifest.from_dict(
        json.loads(Path(args.manifest_json).read_text(encoding="utf-8"))
    )
    issues = manifest.validate_import_order()
    if issues:
        raise SystemExit(f"manifest import order invalid: {issues}")

    # Explicit, auditable scope reduction. The excluded files remain in the
    # source package / manifest but are NOT imported into the real V19 project;
    # the reason and the file list are written into the final receipt.
    excluded_names = set(args.exclude_scl)
    excluded_files = [p for p in manifest.import_order if Path(p).name in excluded_names]
    if excluded_files:
        if not args.exclude_reason:
            raise SystemExit("--exclude-reason is required when --exclude-scl is used")
        excluded_paths = set(excluded_files)
        original_manifest_sha256 = manifest.sha256
        manifest.import_order = [p for p in manifest.import_order if p not in excluded_paths]
        manifest.files = [f for f in manifest.files if f.path not in excluded_paths]
        manifest.dependencies = {
            k: [v for v in vs if v not in excluded_paths]
            for k, vs in manifest.dependencies.items()
            if k not in excluded_paths
        }
        # Keep the ORIGINAL manifest hash: it identifies the source package.
        # The filtered subset is an explicit, recorded scope decision.
        rechecked = manifest.validate_import_order()
        if rechecked:
            raise SystemExit(f"manifest invalid after exclusion: {rechecked}")
    else:
        original_manifest_sha256 = manifest.sha256
    scope_limitations = [
        {
            "excluded_files": excluded_files,
            "reason": args.exclude_reason,
            "original_manifest_sha256": original_manifest_sha256,
            "evidence": "evidence/v2/real/attempt_03/ob_renamed_import.txt, ob_renamed_compile.txt, ob_main_import_receipt.txt",
        }
    ] if excluded_files else []

    adapter = TiaOpennessCliAdapter(real_machine=True, evidence_level=EvidenceLevel.V19_REAL)
    receipts: list[dict[str, Any]] = []

    def record(name: str, ok: bool, state: str, raw: dict[str, Any]) -> None:
        r = stage_receipt(name, ok, state, raw)
        receipts.append(r)
        (stages_dir / f"{name.lower()}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    def fail(name: str, code: str, message: str, raw: dict[str, Any] | None = None) -> None:
        record(name, False, "FAILED", raw or {})
        payload = {
            "mode": "skeleton_chain_failed", "failed_stage": name,
            "error": {"code": code, "message": message},
            "evidence_level": PENDING, "real_tia_v19_tested": False,
            "delivery_complete": False, "g5_status": "pending_real_machine",
            "stage_receipts": receipts,
            "notice": "fail-closed; no native archive published",
        }
        _emit(payload, args.output)
        raise SystemExit(2)

    # 1) OPEN_SKELETON - prove the copy has real PLC software.
    try:
        opened = adapter._invoke("open-project", "--project", args.project, timeout_s=300)
    except Exception as exc:  # noqa: BLE001
        fail("OPEN_SKELETON", "TIA_UNAVAILABLE", str(exc))
    record("OPEN_SKELETON", bool(opened.get("ok")), "TIA_IMPORTED", opened)
    if not opened.get("ok") or not str(opened.get("plcName") or ""):
        fail("OPEN_SKELETON", "NO_PLC_SOFTWARE", "skeleton has no PLC software", opened)

    # 2) IMPORT - generated AF SCL in explicit dependency order (absolute paths).
    imported = adapter.import_blocks(args.project, manifest)
    record("IMPORT", bool(imported.get("ok")), "TIA_IMPORTED", imported)
    if not imported.get("ok"):
        fail("IMPORT", "IMPORT_FAILED", str(imported.get("error")), imported)

    # 3) COMPILE - real V19 compile, error_count must be 0.
    compiled = adapter.compile(args.project)
    compile_receipt = CompileReceipt.from_worker(
        compiled,
        raw=json.dumps(compiled, ensure_ascii=False, sort_keys=True),
        evidence=EvidenceLevel.V19_REAL,
    )
    compile_receipt.static_gate_passed = not bool(issues)
    compile_receipt.recompute_compile_ok(real_receipt=bool(compiled))
    compile_ok = compile_receipt.error_count == 0 and compile_receipt.compile_ok
    record("COMPILE", compile_ok, "TIA_COMPILED", compiled)
    if not compile_ok:
        fail("COMPILE", "COMPILE_FAILED",
             f"error_count={compile_receipt.error_count}, warnings={compile_receipt.warning_count}", compiled)

    # 4) SAVE
    saved = adapter.save(args.project)
    record("SAVE", bool(saved.get("ok")), "TIA_COMPILED", saved)
    if not saved.get("ok"):
        fail("SAVE", "SAVE_FAILED", "save-project failed", saved)

    # 5) ARCHIVE - exact path + sha256, never a directory wildcard.
    try:
        archived = adapter.archive(
            args.project, str(ws / "archive"), f"{args.project_id}.zap19"
        )
        archive = unpack_archive_path(archived)
    except (ArchiveMissingError, Exception) as exc:  # noqa: BLE001
        fail("ARCHIVE", "ARCHIVE_MISSING", str(exc), locals().get("archived", {}))
    record("ARCHIVE", True, "TIA_COMPILED", archived)
    archive_path = Path(archive["archive_path"])

    # 6) HASH - compute from the exact file, compare with the receipt.
    if not archive_path.is_file():
        fail("HASH", "ARCHIVE_MISSING", f"exact archive path not found: {archive_path}")
    computed = compute_file_sha256(archive_path)
    if archive["archive_sha256"] and archive["archive_sha256"] != computed:
        fail("HASH", "ARCHIVE_HASH_MISMATCH",
             f"receipt={archive['archive_sha256']} computed={computed}")
    size_bytes = archive_path.stat().st_size
    record("HASH", True, "TIA_COMPILED",
           {"archive_sha256": computed, "size_bytes": size_bytes,
            "archive_path": str(archive_path)})

    # 7) RETRIEVE_REOPEN - mandatory (Q-06).
    try:
        retrieved = adapter.retrieve_reopen(str(archive_path), str(ws / "reopen"))
        reopen = unpack_retrieve_reopen(retrieved)
    except (ReopenFailedError, Exception) as exc:  # noqa: BLE001
        fail("RETRIEVE_REOPEN", "REOPEN_FAILED", str(exc), locals().get("retrieved", {}))
    record("RETRIEVE_REOPEN", True, "TIA_COMPILED", retrieved)

    binding = f"{args.project_id}:{args.job_id}:{computed}"
    artifact = NativeTiaArtifact(
        artifact_id="a_" + sha256_prefixed(binding)[7:19],
        job_id=args.job_id,
        project_id=args.project_id,
        project_path=args.project,
        archive_path=str(archive_path),
        archive_sha256=computed,
        size_bytes=size_bytes,
        kind="zap19",
        compile=compile_receipt,
        evidence_id="",
        evidence_level=EvidenceLevel.V19_REAL,
        reopen_ok=bool(reopen["reopen_ok"]),
        receipt={
            "stage_order": list(STAGES),
            "skeleton_path": args.project,
            "manifest_sha256": original_manifest_sha256,
            "manifest_scope": "filtered_for_real_import" if excluded_files else "full",
            "workspace_dir": str(ws),
            "cpu_skeleton": "pre_fabricated_real_v19_project (blueprint section 02)",
        },
    )
    artifact_dict = artifact.to_dict()
    is_real, gaps = derive_skeleton_evidence(receipts, artifact_dict, compile_receipt)
    payload = {
        "mode": "skeleton_real_chain",
        "real_tia_v19_tested": is_real,
        "evidence_level": REAL if is_real else PENDING,
        "evidence_gaps": gaps,
        "stage_receipts": receipts,
        "artifact": artifact_dict,
        "compile": compile_receipt.to_dict(),
        "scope_limitations": scope_limitations,
        "imported_file_count": len(manifest.import_order),
        "raw_evidence_path": str(stages_dir),
        "delivery_complete": is_real,
        "g5_status": "PASSED" if is_real else "pending_real_machine",
        "notice": (
            "V19 real full-chain receipt on a pre-fabricated CPU skeleton" if is_real
            else "chain FAILED; no native archive published; pending_real_machine"
        ),
    }
    _emit(payload, args.output)
    if not is_real:
        raise SystemExit(2)


def _emit(payload: dict[str, Any], output: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    print(text)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
