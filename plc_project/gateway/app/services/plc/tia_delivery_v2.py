"""V2 native TIA delivery chain (WP-01 / G5). D-1 fix + strict transaction.

D-1: the C# ``create-project`` reply is ``{ok, create:{projectPath}}`` with
CamelCase naming (TiaOpenness.Models/JsonDefaults). The OLD code guessed a path
via ``created.get("path") or created.get("project") or dir/name.ap19``. This
module unpacks ``create.projectPath`` **fail-closed**: a missing key is an
explicit failure, never a guessed path.

The chain is Create -> CreateDevice -> Import -> Compile(0 error) -> Save ->
Archive(exact path + sha256) -> Retrieve/reopen(MANDATORY, Q-06). A mocked /
offline adapter can verify orchestration but can NEVER set NATIVE_ARCHIVED.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_engine.engineering_ir.contracts import DELIVERY_STAGES, ErrorCode
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.hashing import compute_file_sha256, sha256_prefixed
from plc_engine.engineering_ir.models import CompileReceipt, NativeTiaArtifact
from plc_engine.process.artifact_manifest import ArtifactManifest


class CreatePathMissingError(ValueError):
    """D-1 fail-closed: ``create.projectPath`` missing; never guess a path."""


class ArchiveMissingError(ValueError):
    """D-2 fail-closed: exact archive path missing; no directory wildcard."""


class ReopenFailedError(ValueError):
    """Q-06: Retrieve/reopen did not pass; NATIVE_ARCHIVED is forbidden."""


class TiaUnavailableError(RuntimeError):
    """Explicit ``tia_unavailable`` failure (never HTTP 200 / ok=true)."""


def unpack_create_project_path(created: dict[str, Any]) -> str:
    """Fail-closed unpack of the C# ``create-project`` receipt.

    Correct key (CamelCase): ``create.projectPath``. No fallback, no glob, no
    ``dir/name.ap19`` guess. This is the single authoritative D-1 fix and is
    reused by the legacy ``tia_delivery.py`` through a local import.
    """
    if not isinstance(created, dict):
        raise CreatePathMissingError("create-project receipt is not an object")
    if not created.get("ok"):
        raise CreatePathMissingError(f"create-project ok=false: {created.get('error') or created}")
    create = created.get("create")
    if not isinstance(create, dict):
        raise CreatePathMissingError("create-project receipt is missing the 'create' object")
    if "ok" in create and not create.get("ok"):
        raise CreatePathMissingError(f"create.create.ok=false: {create.get('error') or create}")
    project_path = create.get("projectPath")
    if not isinstance(project_path, str) or not project_path.strip():
        raise CreatePathMissingError("create-project receipt is missing create.projectPath (no path guessing allowed)")
    return project_path


def unpack_archive_path(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed unpack of ``archive-project``: exact path + hash + size."""
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise ArchiveMissingError(f"archive-project ok=false: {(payload or {}).get('error') or payload}")
    archive = payload.get("archive")
    if not isinstance(archive, dict):
        raise ArchiveMissingError("archive-project receipt is missing the 'archive' object")
    if not archive.get("ok"):
        raise ArchiveMissingError(f"archive.ok=false: {archive.get('error') or 'archive_missing'}")
    archive_path = archive.get("archivePath")
    if not isinstance(archive_path, str) or not archive_path.strip():
        raise ArchiveMissingError("archive-project receipt is missing archive.archivePath")
    return {
        "archive_path": archive_path,
        "archive_sha256": str(archive.get("archiveSha256") or ""),
        "size_bytes": int(archive.get("sizeBytes") or 0),
        "project_path": str(archive.get("projectPath") or ""),
        "raw": payload,
    }


def unpack_retrieve_reopen(payload: dict[str, Any]) -> dict[str, Any]:
    """Q-06: Retrieve/reopen MUST pass with an explicit reopen_ok receipt."""
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise ReopenFailedError(f"retrieve ok=false: {(payload or {}).get('error') or payload}")
    retrieve = payload.get("retrieve")
    if not isinstance(retrieve, dict):
        raise ReopenFailedError("retrieve receipt is missing the 'retrieve' object")
    if not retrieve.get("ok"):
        raise ReopenFailedError(f"retrieve.retrieve.ok=false: {retrieve.get('error') or 'reopen_failed'}")
    reopen_ok = retrieve.get("reopenOk", payload.get("reopenOk"))
    if reopen_ok is not True:
        raise ReopenFailedError("retrieve/reopen was not confirmed (reopenOk != true); NATIVE_ARCHIVED forbidden")
    project_path = str(retrieve.get("projectPath") or "")
    if not project_path:
        raise ReopenFailedError("retrieve receipt is missing retrieve.projectPath")
    return {"reopen_ok": True, "project_path": project_path, "raw": payload}


@dataclass
class StageReceipt:
    """One append-only stage record of the delivery chain."""

    stage: str = ""
    ok: bool = True
    state: str = ""
    evidence_level: str = EvidenceLevel.MOCKED.value
    raw_api_receipt: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "ok": self.ok, "state": self.state,
            "evidence_level": self.evidence_level,
            "raw_api_receipt": self.raw_api_receipt,
            "error_code": self.error_code, "message": self.message,
        }


@dataclass
class DeliveryChainRequest:
    """All inputs needed for one controlled delivery transaction."""

    project_id: str = ""
    job_id: str = ""
    project_name: str = ""
    workspace_dir: str = ""
    cpu_type_identifier: str = ""
    archive_name: str = ""
    manifest: ArtifactManifest | None = None
    scl_source_path: str = ""

    def __post_init__(self) -> None:
        if not self.archive_name:
            self.archive_name = f"{self.project_name or self.project_id}.zap19"


@dataclass
class ChainResult:
    """Outcome of one full chain run (never claims real without a real receipt)."""

    ok: bool = False
    state: str = "FAILED"
    stage_receipts: list[StageReceipt] = field(default_factory=list)
    artifact: NativeTiaArtifact | None = None
    error_code: str = ""
    error_message: str = ""
    evidence_level: str = EvidenceLevel.MOCKED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "state": self.state,
            "stage_receipts": [r.to_dict() for r in self.stage_receipts],
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "evidence_level": self.evidence_level,
        }


WorkerCallable = Callable[..., dict[str, Any]]


class TiaOpennessCliAdapter:
    """Thin, injectable wrapper over the real C# Openness CLI.

    ``worker`` defaults to the existing ``agents.plc.tia.openness_cli``
    wrapper. Injecting a fake worker is only allowed for offline orchestration
    tests; such an adapter has ``real_machine=False`` and can never yield
    NATIVE_ARCHIVED.
    """

    def __init__(
        self,
        worker: WorkerCallable | None = None,
        *,
        real_machine: bool = False,
        evidence_level: EvidenceLevel = EvidenceLevel.MOCKED,
    ) -> None:
        self._worker = worker
        self.real_machine = bool(real_machine)
        self.evidence_level = evidence_level if isinstance(evidence_level, EvidenceLevel) else EvidenceLevel.parse(evidence_level)
        if self.real_machine:
            self.evidence_level = EvidenceLevel.V19_REAL
        self.calls: list[dict[str, Any]] = []

    def _invoke(self, command: str, *args: str, timeout_s: int = 300) -> dict[str, Any]:
        self.calls.append({"command": command, "args": list(args)})
        if self._worker is not None:
            reply = self._worker(command, *args, timeout_s=timeout_s)
        else:
            try:
                from agents.plc.tia.openness_cli import openness_cli
            except Exception as exc:
                raise TiaUnavailableError(f"openness_cli unavailable: {type(exc).__name__}: {exc}") from exc
            reply = openness_cli(command, *args, timeout_s=timeout_s)
        if not isinstance(reply, dict):
            raise TiaUnavailableError(f"{command} returned a non-object receipt: {type(reply).__name__}")
        return reply

    def create_project(self, directory: str, name: str) -> dict[str, Any]:
        """Real ``create-project``; reply shape ``{ok, create:{projectPath}}``."""
        return self._invoke("create-project", "--dir", directory, "--name", name, timeout_s=300)

    def create_device(self, project_path: str, type_identifier: str, name: str) -> dict[str, Any]:
        """Real CPU skeleton creation; CPU must be approved beforehand."""
        return self._invoke(
            "create-device", "--project", project_path, "--type-id", type_identifier,
            "--name", name, timeout_s=300,
        )

    def import_blocks(self, project_path: str, manifest: ArtifactManifest) -> dict[str, Any]:
        """Import generated SCL/XML files in the explicit dependency order."""
        receipts: list[dict[str, Any]] = []
        for path in manifest.import_order:
            file = manifest.file_index().get(path)
            if file is None:
                raise ArchiveMissingError(f"manifest import_order references unknown file {path!r}")
            if path.endswith(".scl"):
                receipt = self._invoke(
                    "generate-from-source", "--project", project_path, "--scl", path, timeout_s=900
                )
            else:
                receipt = self._invoke(
                    "import-xml", "--project", project_path, "--xml", path, "--kind", "auto", timeout_s=300
                )
            if not receipt.get("ok"):
                return {"ok": False, "error": f"import failed for {path}", "receipts": receipts, "failed_file": path}
            receipts.append({"file": path, "sha256": file.sha256, "ok": True})
        return {"ok": True, "receipts": receipts, "import_order": list(manifest.import_order)}

    def compile(self, project_path: str) -> dict[str, Any]:
        """Real ``compile-plc``; raw receipt retained for the evidence bundle."""
        return self._invoke("compile-plc", "--project", project_path, timeout_s=900)

    def save(self, project_path: str) -> dict[str, Any]:
        """Real ``save-project`` (T02 C# incremental command)."""
        return self._invoke("save-project", "--project", project_path, timeout_s=300)

    def archive(self, project_path: str, out_dir: str, name: str) -> dict[str, Any]:
        """Real ``archive-project``; returns an EXACT archive path (D-2)."""
        return self._invoke(
            "archive-project", "--project", project_path, "--out-dir", out_dir,
            "--name", name, timeout_s=900,
        )

    def retrieve_reopen(self, archive_path: str, out_dir: str) -> dict[str, Any]:
        """Real ``retrieve`` + reopen confirmation (Q-06 mandatory)."""
        return self._invoke("retrieve", "--archive", archive_path, "--out-dir", out_dir, timeout_s=900)


def execute_chain(
    adapter: TiaOpennessCliAdapter,
    request: DeliveryChainRequest,
    *,
    on_stage: Callable[[StageReceipt], None] | None = None,
) -> ChainResult:
    """Run the strict Create->...->Retrieve/reopen transaction.

    Every stage writes a StageReceipt (ledger is written by the coordinator
    before executing). Any failure returns ``state=FAILED`` with full evidence
    and NEVER publishes NATIVE_ARCHIVED. A mocked adapter may complete the
    orchestration but is labelled ``mocked`` and stays out of NATIVE_ARCHIVED.
    """
    result = ChainResult(evidence_level=adapter.evidence_level.value)
    level = adapter.evidence_level.value

    def stage(name: str, ok: bool, state: str, raw: dict[str, Any], error_code: str = "", message: str = "") -> StageReceipt:
        receipt = StageReceipt(
            stage=name, ok=ok, state=state, evidence_level=level,
            raw_api_receipt=raw, error_code=error_code, message=message,
        )
        result.stage_receipts.append(receipt)
        if on_stage is not None:
            on_stage(receipt)
        return receipt

    def fail(name: str, state: str, code: str, message: str, raw: dict[str, Any] | None = None) -> ChainResult:
        stage(name, False, state, raw or {}, code, message)
        result.ok = False
        result.state = "FAILED"
        result.error_code = code
        result.error_message = message
        return result

    # Precondition: CPU skeleton must be explicitly selected (fail-closed).
    if not request.cpu_type_identifier:
        return fail("CREATE", "FAILED", ErrorCode.CPU_TEMPLATE_NOT_SELECTED.value,
                    "no approved CPU skeleton; delivery must fail explicitly")

    workspace = Path(request.workspace_dir)
    out_dir = str(workspace / "archive")
    reopen_dir = str(workspace / "reopen")
    project_path = ""
    created: dict[str, Any] = {}
    archived_raw: dict[str, Any] = {}
    retrieved_raw: dict[str, Any] = {}
    try:
        created = adapter.create_project(str(workspace / "tia_project"), request.project_name)
        project_path = unpack_create_project_path(created)
    except CreatePathMissingError as exc:
        return fail("CREATE", "FAILED", ErrorCode.ARCHIVE_MISSING.value, str(exc), created)
    except TiaUnavailableError as exc:
        return fail("CREATE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, str(exc))
    except Exception as exc:  # noqa: BLE001 - any worker failure is explicit
        return fail("CREATE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, f"create-project failed: {exc}")
    stage("CREATE", True, "TIA_IMPORTED", created)

    try:
        device = adapter.create_device(project_path, request.cpu_type_identifier, request.project_name)
        if not device.get("ok"):
            return fail("CREATE_DEVICE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value,
                        "create-device failed (CPU type identifier not supported?)", device)
    except Exception as exc:  # noqa: BLE001
        return fail("CREATE_DEVICE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, str(exc))
    stage("CREATE_DEVICE", True, "TIA_IMPORTED", device)

    manifest = request.manifest or ArtifactManifest(import_order=[], files=[])
    try:
        imported = adapter.import_blocks(project_path, manifest)
        if not imported.get("ok"):
            return fail("IMPORT", "FAILED", ErrorCode.TIA_UNAVAILABLE.value,
                        f"import failed: {imported.get('error')}", imported)
    except Exception as exc:  # noqa: BLE001
        return fail("IMPORT", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, str(exc))
    stage("IMPORT", True, "TIA_IMPORTED", imported)

    try:
        compiled_raw = adapter.compile(project_path)
    except Exception as exc:  # noqa: BLE001
        return fail("COMPILE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, str(exc))
    compile_receipt = CompileReceipt.from_worker(
        compiled_raw,
        raw=json.dumps(compiled_raw, ensure_ascii=False, sort_keys=True),
        evidence=adapter.evidence_level,
    )
    compile_receipt.static_gate_passed = not bool(manifest.validate_import_order()) if manifest else True
    # ``compile_ok`` in the receipt stays strict (V19 real only). The chain uses
    # the parsed error count so a MOCKED chain can validate orchestration while
    # still being forbidden from reaching NATIVE_ARCHIVED.
    if compile_receipt.error_count != 0 or compile_receipt.warning_count < 0:
        return fail("COMPILE", "FAILED", ErrorCode.COMPILE_FAILED.value,
                    f"compile error_count={compile_receipt.error_count} (warning_count={compile_receipt.warning_count} listed separately)",
                    compiled_raw)
    stage("COMPILE", True, "TIA_COMPILED", compiled_raw)

    try:
        saved = adapter.save(project_path)
        if not saved.get("ok"):
            return fail("SAVE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, "save-project failed", saved)
    except Exception as exc:  # noqa: BLE001
        return fail("SAVE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, str(exc))
    stage("SAVE", True, "TIA_COMPILED", saved)

    try:
        archived_raw = adapter.archive(project_path, out_dir, request.archive_name)
        archive = unpack_archive_path(archived_raw)
    except ArchiveMissingError as exc:
        return fail("ARCHIVE", "FAILED", ErrorCode.ARCHIVE_MISSING.value, str(exc), archived_raw)
    except Exception as exc:  # noqa: BLE001
        return fail("ARCHIVE", "FAILED", ErrorCode.TIA_UNAVAILABLE.value, str(exc))
    stage("ARCHIVE", True, "TIA_COMPILED", archived_raw)

    # HASH stage: exact file hash, never a directory scan.
    archive_path = Path(archive["archive_path"])
    if archive_path.is_file():
        computed = compute_file_sha256(archive_path)
        if archive["archive_sha256"] and archive["archive_sha256"] != computed:
            return fail("HASH", "FAILED", ErrorCode.ARCHIVE_MISSING.value,
                        f"archive sha256 mismatch: receipt={archive['archive_sha256']} computed={computed}")
        archive["archive_sha256"] = computed
        archive["size_bytes"] = archive_path.stat().st_size
    elif not archive["archive_sha256"]:
        return fail("HASH", "FAILED", ErrorCode.ARCHIVE_MISSING.value,
                    f"archive_missing: exact path not found: {archive_path}")
    elif not adapter.real_machine:
        # Offline orchestration test: receipt hash is accepted but labelled mocked.
        archive["archive_sha256"] = archive["archive_sha256"] or sha256_prefixed("mocked_archive")
    else:
        return fail("HASH", "FAILED", ErrorCode.ARCHIVE_MISSING.value,
                    f"archive_missing: exact path not found: {archive_path}")
    stage("HASH", True, "TIA_COMPILED", {"archive_sha256": archive["archive_sha256"], "size_bytes": archive["size_bytes"]})

    # Q-06: Retrieve/reopen is MANDATORY before NATIVE_ARCHIVED.
    try:
        retrieved_raw = adapter.retrieve_reopen(str(archive_path), reopen_dir)
        reopen = unpack_retrieve_reopen(retrieved_raw)
    except ReopenFailedError as exc:
        return fail("RETRIEVE_REOPEN", "FAILED", ErrorCode.REOPEN_FAILED.value, str(exc), retrieved_raw)
    except Exception as exc:  # noqa: BLE001
        return fail("RETRIEVE_REOPEN", "FAILED", ErrorCode.REOPEN_FAILED.value, str(exc))
    stage("RETRIEVE_REOPEN", True, "TIA_COMPILED", retrieved_raw)

    binding_payload = f"{request.project_id}:{request.job_id}:{archive['archive_sha256']}"
    artifact_id = "a_" + sha256_prefixed(binding_payload)[7:19]
    artifact = NativeTiaArtifact(
        artifact_id=artifact_id,
        job_id=request.job_id,
        project_id=request.project_id,
        project_path=project_path,
        archive_path=str(archive_path),
        archive_sha256=archive["archive_sha256"],
        size_bytes=int(archive["size_bytes"]),
        kind="zap19",
        compile=compile_receipt,
        evidence_id="",
        evidence_level=adapter.evidence_level,
        reopen_ok=bool(reopen["reopen_ok"]),
        receipt={
            "stage_order": list(DELIVERY_STAGES),
            "workspace_dir": request.workspace_dir,
            "cpu_type_identifier": request.cpu_type_identifier,
            "real_machine": adapter.real_machine,
        },
    )
    result.artifact = artifact
    result.ok = True
    if adapter.real_machine and artifact.is_native_archived():
        result.state = "NATIVE_ARCHIVED"
        result.evidence_level = EvidenceLevel.V19_REAL.value
    else:
        # Mocked/offline orchestration NEVER claims native delivery (PRD 6.4).
        result.state = "MOCKED_CHAIN_OK"
        result.evidence_level = EvidenceLevel.MOCKED.value
    return result
