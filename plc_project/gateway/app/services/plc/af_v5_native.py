"""Create a verified TIA V19 offline archive from an AF-Studio V5 snapshot."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Callable

from gateway.app.services.plc.tia_delivery_v2 import (
    ChainResult,
    DeliveryChainRequest,
    TiaOpennessCliAdapter,
    execute_chain,
)
from plc_engine.engineering_ir.hashing import sha256_prefixed
from plc_engine.process.af_v5_offline import compile_kuka_offline
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest

OFFLINE_CPU = "OrderNumber:6ES7 511-1AK01-0AB0/V2.5"
ARCHIVE_NAME = "KUKA_V5_Offline.zap19"
_BLOCK_NAME = re.compile(r'^(?:FUNCTION_BLOCK|FUNCTION|DATA_BLOCK) "([^"]+)"', re.M)


class KukaAfAdapter(TiaOpennessCliAdapter):
    def __init__(self, plan_path: Path, groups: dict[str, str], tags: dict[str, list[dict[str, str]]]) -> None:
        super().__init__(real_machine=True)
        self.plan_path = plan_path
        self.groups = groups
        self.tags = tags

    def import_blocks(self, project_path: str, manifest: ArtifactManifest) -> dict:
        result = self._invoke("import-af-folder-plan", "--project", project_path,
                              "--plan", str(self.plan_path), timeout_s=900)
        if not result.get("ok"):
            error = ((result.get("generate") or {}).get("error") or result.get("error") or {})
            message = error.get("message") if isinstance(error, dict) else str(error)
            return {**result, "ok": False, "error": message or "TIA AF folder import failed."}
        directory = {entry["name"]: entry.get("path", "").removesuffix("/" + entry["name"])
                     for entry in result["blocks"]["blocks"]}
        actual_tags = {table["name"]: {(tag["name"], tag["address"]) for tag in table["tags"]}
                       for table in result["tagTables"]}
        expected_tags = {table: {(point["name"], point["address"]) for point in points}
                         for table, points in self.tags.items()}
        mismatched = [name for name, group in self.groups.items() if directory.get(name) != group]
        if mismatched or actual_tags != expected_tags:
            return {**result, "ok": False, "error": f"TIA tree validation failed: blocks={mismatched}, "
                                                   f"named tag tables match={actual_tags == expected_tags}"}
        return result


def archive_kuka_snapshot(
    snapshot: bytes, output: Path, cpu: str = OFFLINE_CPU, *, on_stage: Callable | None = None,
) -> ChainResult:
    af = compile_kuka_offline(json.loads(snapshot.decode("utf-8-sig")))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "workspace.json").write_bytes(snapshot)
    files = []
    grouped_sources = []
    expected_groups = {}
    for index, (group, scl) in enumerate(af.sources, 1):
        path = output / f"{index:02d}_{group.rsplit('/', 1)[-1]}.scl"
        source = scl.encode("utf-8-sig")
        path.write_bytes(source)
        files.append(ArtifactFile(path=str(path), role="FB", sha256=sha256_prefixed(source)))
        grouped_sources.append({"group": group, "file": str(path)})
        expected_groups.update({block: group for block in _BLOCK_NAME.findall(scl)})
    plan = output / "af-folder-plan.json"
    plan.write_text(json.dumps({
        "tagTables": [{"name": name, "tags": tags} for name, tags in af.tag_tables.items()],
        "sources": grouped_sources,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = ArtifactManifest(
        ir_sha256=sha256_prefixed(snapshot), files=files, import_order=[file.path for file in files],
    )
    request = DeliveryChainRequest(
        project_id="prj_kuka_v5_offline",
        job_id="v5_" + manifest.ir_sha256.removeprefix("sha256:")[:16],
        project_name="KUKA_V5_Offline",
        archive_name=ARCHIVE_NAME,
        workspace_dir=str(output),
        cpu_type_identifier=cpu,
        manifest=manifest,
    )
    adapter = KukaAfAdapter(plan, expected_groups, af.tag_tables)
    result = execute_chain(adapter=adapter, request=request, on_stage=on_stage)
    receipt = result.to_dict() | {
        "snapshot_sha256": manifest.ir_sha256,
        "source_sha256": {Path(file.path).name: file.sha256 for file in files},
        "af_profile": "SIEMENS_AF_BASIC_FOLDER_V19",
        "cpu": cpu,
        "scope": "Offline acceptance. No station or field I/O block is called by OB1.",
    }
    (output / "export-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
