"""ProcessOS native delivery — reuses the verified Openness chain (R3 D-10).

Wraps gateway.tia_delivery_v2.execute_chain (real C# CLI, anti-forgery) and feeds
it the WS3-generated executable SCL. Unlike the legacy attempt_04 shortcut, this
path NEVER excludes OB_Main: full-logic compile or explicit FAILED. A mocked
adapter can validate orchestration but is labelled ``mocked`` and can never reach
NATIVE_ARCHIVED; only the real C# CLI yields V19_real.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from plc_engine.canonical import sha256_prefixed
from plc_engine.process.artifact_manifest import ArtifactFile, ArtifactManifest

from processos.contract import AfProject, FrameworkProfile, GeneratedSource, ProcessContract

DEFAULT_CPU_TYPE_ID = "6ES7511-1AK02-0AB0/V2.9"
_ROLE_RANK = {"FB": 0, "FC": 1, "DB": 2, "OB": 3}


def ensure_openness_cli_importable() -> None:
    """Load the real C# CLI wrapper without the heavy agents.plc.tia package init.

    agents/plc/tia/__init__ eagerly imports the analysis pipeline (kg/importer/
    simaticml) which can hang on optional deps. The Openness CLI wrapper itself
    is stdlib-only; load it straight from file so the real-machine adapter path
    (worker=None -> V19_real) works without pulling the analysis stack.
    """
    import importlib.util
    import sys
    import types

    if "agents.plc.tia.openness_cli" in sys.modules:
        return
    for name in ("agents", "agents.plc", "agents.plc.tia"):
        sys.modules.setdefault(name, types.ModuleType(name))
    path = Path(__file__).resolve().parents[2] / "agents" / "plc" / "tia" / "openness_cli.py"
    spec = importlib.util.spec_from_file_location("agents.plc.tia.openness_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load openness_cli from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agents.plc.tia.openness_cli"] = mod
    spec.loader.exec_module(mod)


def _role_of(filename: str) -> str:
    if filename.startswith("OB_"):
        return "OB"
    if filename.endswith(".db"):
        return "DB"
    return "FB"


def build_manifest(
    gen: GeneratedSource,
    project: AfProject,
    profile: FrameworkProfile,
    workspace: Path,
) -> ArtifactManifest:
    """Write generated sources to an isolated workspace; order FB -> DB -> OB."""
    src_dir = workspace / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    files: list[ArtifactFile] = []
    for name, content in gen.files.items():
        role = _role_of(name)
        scl_name = name if name.endswith(".scl") else name.rsplit(".", 1)[0] + ".scl"
        path = src_dir / scl_name
        path.write_text(content, encoding="utf-8")
        node_ids = sorted({m["node"] for m in gen.source_map if m["file"] == name and m["node"]})
        files.append(ArtifactFile(
            path=str(path), sha256=sha256_prefixed(content), role=role,
            content=content, source_ids=node_ids, tia_block=name.rsplit(".", 1)[0],
        ))
    files.sort(key=lambda f: (_ROLE_RANK.get(f.role, 9), f.path))
    manifest = ArtifactManifest(
        af_profile_id=profile.profile_id,
        template_sha256=profile.template_sha256,
        ir_sha256=project.ir_hash,
        files=files,
        import_order=[f.path for f in files],
    )
    manifest.sha256 = manifest.compute_sha256()
    return manifest


class NativeDeliveryRunner:
    """DeliveryRunner for the project store; real or offline-orchestration mode."""

    def __init__(
        self,
        *,
        real: bool = False,
        cpu_type_id: str = DEFAULT_CPU_TYPE_ID,
        workspace_root: str | Path | None = None,
        worker: Any = None,
    ):
        self.real = real
        self.cpu_type_id = cpu_type_id
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self.worker = worker

    def run(
        self, job: dict, contract: ProcessContract, profile: FrameworkProfile, gen: GeneratedSource
    ) -> dict:
        from gateway.app.services.plc.tia_delivery_v2 import (
            DeliveryChainRequest,
            TiaOpennessCliAdapter,
            execute_chain,
        )
        from processos.backends import lower

        if self.real and self.worker is None:
            ensure_openness_cli_importable()

        root = self.workspace_root or Path(tempfile.gettempdir()) / "processos_native"
        root.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix=f"{job['id']}_", dir=root))
        project = lower(contract, profile)
        manifest = build_manifest(gen, project, profile, workspace)

        adapter = TiaOpennessCliAdapter(self.worker, real_machine=self.real)
        request = DeliveryChainRequest(
            project_id=contract.id,
            job_id=job["id"],
            project_name=contract.id,
            workspace_dir=str(workspace),
            cpu_type_identifier=self.cpu_type_id,
            archive_name=f"{contract.id}.zap19",
            manifest=manifest,
        )
        result = execute_chain(adapter, request)
        job["status"] = "SUCCEEDED" if result.ok else "FAILED"
        job["chain_state"] = result.state
        job["evidence_level"] = result.evidence_level
        job["events"] = [r.to_dict() for r in result.stage_receipts]
        job["workspace_dir"] = str(workspace)
        job["manifest_sha256"] = manifest.sha256
        job["ob_main_included"] = any(f.role == "OB" for f in manifest.files)
        if result.artifact is not None:
            job["artifact"] = result.artifact.to_dict()
        if not result.ok:
            job["diagnostics"] = [
                {"stage": r.stage, "code": r.error_code, "message": r.message}
                for r in result.stage_receipts if not r.ok
            ]
        return job


def run_native_delivery(
    contract: ProcessContract,
    profile: FrameworkProfile,
    *,
    real: bool = False,
    cpu_type_id: str = DEFAULT_CPU_TYPE_ID,
    worker: Any = None,
) -> dict:
    """One-shot native delivery for scripts/E2E (returns the job dict)."""
    from processos.backends import lower
    from processos.codegen import generate

    gen = generate(lower(contract, profile), profile)
    job = {"id": "JOB-native", "project_id": contract.id, "status": "QUEUED",
           "spec_hash": "", "events": [], "diagnostics": [], "artifact": None}
    runner = NativeDeliveryRunner(real=real, cpu_type_id=cpu_type_id, worker=worker)
    return runner.run(job, contract, profile, gen)


def _demo_worker(command: str, *args: str, timeout_s: int = 300) -> dict:
    """Offline orchestration receipts for the standalone demo UI (labelled mocked)."""
    if command == "create-project":
        return {"ok": True, "create": {"projectPath": "C:/demo/proj.ap19"}}
    if command == "create-device":
        return {"ok": True}
    if command == "generate-from-source":
        return {"ok": True}
    if command == "compile-plc":
        return {"ok": True, "compile": {"ok": True, "state": "Success", "errorCount": 0,
                "warningCount": 0, "apiAvailable": True,
                "message": "Compile State=Success errors=0 warnings=0",
                "inconsistentBlocks": ["Compiling finished (errors: 0; warnings: 0)"]}}
    if command == "save-project":
        return {"ok": True}
    if command == "archive-project":
        return {"ok": True, "archive": {"ok": True, "archivePath": "C:/demo/proj.zap19",
                "archiveSha256": "sha256:" + "cd" * 32, "sizeBytes": 2048, "projectPath": "C:/demo/proj.ap19"}}
    if command == "retrieve":
        return {"ok": True, "retrieve": {"ok": True, "reopenOk": True, "projectPath": "C:/demo/reopen.ap19"}}
    return {"ok": False, "error": f"unexpected command {command}"}


def make_demo_runner() -> NativeDeliveryRunner:
    """Mocked runner for the demo workbench; never yields NATIVE_ARCHIVED."""
    return NativeDeliveryRunner(real=False, worker=_demo_worker)