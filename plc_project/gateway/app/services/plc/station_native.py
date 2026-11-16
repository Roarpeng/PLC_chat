"""Run an explicitly requested V19 compile/archive on a fresh project copy."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from gateway.app.services.plc.delivery_jobs_v2 import DeliveryCoordinator
from gateway.app.services.plc.tia_delivery_v2 import DeliveryChainRequest, TiaOpennessCliAdapter
from plc_engine.engineering_ir.hashing import sha256_prefixed
from plc_engine.engineering_ir.models import EngineeringIRV2
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest
from plc_engine.process.scl_lowering import CompilerService

logger = logging.getLogger(__name__)
CPU_IDENTIFIER = re.compile(r"OrderNumber:[A-Z0-9][A-Z0-9 -]{2,60}/V[0-9]+(?:\.[0-9]+){1,2}\Z", re.I)


def compile_station_archive(coordinator: DeliveryCoordinator, job_id: str, ir: EngineeringIRV2) -> None:
    if ir.station_design is None:
        raise ValueError("缺少工位画布。")
    store = coordinator.store
    workspace = Path(store.ir_store_root).parent / "station_tia" / job_id
    try:
        workspace.mkdir(parents=True, exist_ok=False)
        manifest, source_map = CompilerService(ir.af_profile).lower(ir)
        # One external source batch preserves the tested Siemens import path
        # and resolves inter-block references when TIA generates the blocks.
        bundle = workspace / "StationCanvas.scl"
        by_path = manifest.file_index()
        contents = "\n\n".join(by_path[path].content for path in manifest.import_order)
        offsets = {}
        line = 0
        for path in manifest.import_order:
            offsets[path] = line
            line += by_path[path].content.count("\n") + 2
        mapping = source_map.to_dict()
        for item in mapping["mappings"]:
            item["bundle_line"] = offsets[item["scl_file"]] + item["scl_line"]
        (workspace / "source-map.json").write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        compiled = contents.encode("utf-8-sig")
        bundle.write_bytes(compiled)
        native_manifest = ArtifactManifest(
            af_profile_id=manifest.af_profile_id, template_sha256=manifest.template_sha256,
            ir_sha256=manifest.ir_sha256,
            files=[ArtifactFile(path=str(bundle), role="FB", sha256=sha256_prefixed(compiled))],
            import_order=[str(bundle)],
        )
        request = DeliveryChainRequest(
            project_id=ir.project_id, job_id=job_id, project_name="Station_" + job_id[-12:],
            workspace_dir=str(workspace), cpu_type_identifier=ir.station_design["hardware"]["cpu"].strip(),
            manifest=native_manifest,
        )
        coordinator.run_chain(job_id, adapter=TiaOpennessCliAdapter(real_machine=True), request=request)
    except Exception:
        logger.exception("V19 station archive job %s terminated", job_id)
        job = store.get_job(job_id)
        if job and job["state"] not in ("FAILED", "NATIVE_ARCHIVED"):
            store.update_job_state(job_id, "FAILED", stage_cursor="WORKER")
            store.append_job_event(job_id, state="FAILED", stage="WORKER",
                                   raw_api_receipt={"message": "博途作业意外终止。"})
        store.release_project_lock(ir.project_id, job_id)


def station_delivery_diagnostics(coordinator: DeliveryCoordinator, job_id: str) -> list[dict[str, str]]:
    root = coordinator.store.ir_store_root.parent / "station_tia" / job_id
    try:
        source = json.loads((root / "source-map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    issues = []
    for event in coordinator.store.get_job_events(job_id):
        try:
            receipt = json.loads(event["raw_api_receipt"] or "{}")
        except ValueError:
            continue
        if not isinstance(receipt, dict):
            continue
        if event["stage"] == "COMPILE" or event["stage"] == "IMPORT":
            result = receipt.get("compile") or receipt.get("generate") or {}
            error = result.get("error") or {}
            for description in error.get("compilerErrors") or []:
                text = str(description)[:500]
                match = re.search(r"(?:行|line)\s+([0-9]+)", text, re.I)
                line = int(match[1]) if match else -1
                location = next((item for item in source["mappings"] if item.get("bundle_line") == line
                                 or (item.get("tia_block") and item["tia_block"] in text)), None)
                issues.append({"reason": text, "node_id": location["canvas_node_id"] if location else ""})
        if receipt.get("error_code") and receipt.get("message"):
            issues.append({"reason": str(receipt["message"])[:500], "node_id": ""})
    return issues[-30:]
