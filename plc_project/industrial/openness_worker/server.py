"""Small loopback FastAPI service that executes Windows-only TIA exports."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import zipfile
from typing import Annotated
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from agents.plc.tia.importer import (
    APXX_SUFFIXES,
    _safe_extract_zip,
    export_apxx_via_openness,
    find_apxx_files,
    has_simaticml_exports,
    incomplete_apxx_guidance,
    is_complete_tia_project,
    is_tia_archive_suffix,
    pick_project_root_from_extracted,
)


app = FastAPI(title="ResearchOS Openness Worker", version="1.1.0")
#: One TIA Portal instance per worker — exports and imports serialize on it.
_OPENNESS_LOCK = threading.Lock()
_UPLOAD_CHUNK = 1024 * 1024


def _bearer_token() -> str:
    return os.getenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "").strip()


def _max_upload_bytes() -> int:
    raw = os.getenv("RESEARCHOS_OPENNESS_WORKER_MAX_UPLOAD_MB", "").strip()
    megabytes = int(raw) if raw.isdigit() and int(raw) > 0 else 500
    return megabytes * 1024 * 1024


def require_bearer(authorization: Annotated[str | None, Header()] = None) -> None:
    token = _bearer_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Openness worker token is not configured; set "
                "RESEARCHOS_OPENNESS_WORKER_TOKEN before accepting exports"
            ),
        )
    supplied = authorization or ""
    expected = f"Bearer {token}"
    if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid Openness worker bearer token")


@app.get("/health")
def health() -> dict[str, object]:
    from agents.plc.tia.openness_cli import find_openness_exe

    root = Path(__file__).resolve().parents[2]
    return {
        "ok": True,
        "service": "researchos-openness-worker",
        "windows": os.name == "nt",
        "auth_required": bool(_bearer_token()),
        "openness_cli_available": find_openness_exe() is not None,
        "powershell_adapter_available": (
            root / "industrial" / "tia_adapter" / "ExportProject.ps1"
        ).is_file(),
        "tia_version_hint": os.getenv("RESEARCHOS_TIA_VERSION", ""),
    }


def _save_upload(upload, *, filename: str, max_bytes: int) -> tuple[Path, int]:
    suffix = Path(filename).suffix.lower()
    fd, path = tempfile.mkstemp(prefix="researchos_openness_upload_", suffix=suffix)
    os.close(fd)
    archive = Path(path)
    size = 0
    try:
        with archive.open("wb") as output:
            while chunk := upload.read(_UPLOAD_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Openness worker upload exceeds {max_bytes} bytes",
                    )
                output.write(chunk)
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    if size == 0:
        archive.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Openness worker project upload is empty")
    return archive, size


def _choose_project(root: Path, *, direct_file: Path | None = None) -> Path:
    if direct_file is not None:
        return direct_file
    candidates = find_apxx_files(root)
    complete = [candidate for candidate in candidates if is_complete_tia_project(candidate)]
    if complete:
        return complete[0]
    picked = pick_project_root_from_extracted(root)
    if picked.is_dir() and has_simaticml_exports(picked):
        return picked
    if candidates:
        raise HTTPException(status_code=400, detail=incomplete_apxx_guidance(candidates[0]))
    raise HTTPException(
        status_code=422,
        detail="Uploaded project contains neither a complete .apxx tree nor SimaticML XML",
    )


def _write_manifest(
    source_name: str, source_kind: str, notes: list[str], timings: dict[str, int]
) -> dict[str, object]:
    return {
        "source": source_name,
        "source_kind": source_kind,
        "worker": "researchos-openness-worker",
        "notes": notes,
        "timings_ms": timings,
    }


def _export_without_remote_loopback(
    project: Path, *, export_dir: Path
) -> tuple[Path, list[str], dict[str, int]]:
    """Prevent a worker that inherited the Gateway env from calling itself."""
    configured_url = os.environ.pop("RESEARCHOS_OPENNESS_WORKER_URL", None)
    try:
        return export_apxx_via_openness(
            project,
            export_dir=export_dir,
            plc_name=os.getenv("RESEARCHOS_DEFAULT_PLC_NAME", ""),
        )
    finally:
        if configured_url is not None:
            os.environ["RESEARCHOS_OPENNESS_WORKER_URL"] = configured_url


def _zip_export_tree(root: Path, manifest: dict[str, object]) -> Path:
    manifest_path = root / "_researchos_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fd, path = tempfile.mkstemp(prefix="researchos_openness_export_", suffix=".zip")
    os.close(fd)
    archive = Path(path)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    zf.write(item, item.relative_to(root).as_posix())
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    return archive


def _file_response(
    archive: Path, *, export_key: str, timing_ms: int, notes: list[str]
) -> StreamingResponse:
    encoded_notes = base64.b64encode(
        json.dumps(notes, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    def stream():
        try:
            with archive.open("rb") as payload:
                while chunk := payload.read(_UPLOAD_CHUNK):
                    yield chunk
        finally:
            archive.unlink(missing_ok=True)

    return StreamingResponse(
        stream(),
        media_type="application/zip",
        headers={
            "X-ResearchOS-Export-Key": export_key,
            "X-ResearchOS-Timing-Ms": str(timing_ms),
            "X-ResearchOS-Notes-B64": encoded_notes,
            "Content-Disposition": 'attachment; filename="simaticml-export.zip"',
        },
    )


@app.post("/export", dependencies=[Depends(require_bearer)])
def export_project(project: UploadFile = File(...)):
    filename = Path(project.filename or "").name
    suffix = Path(filename).suffix.lower()
    is_apxx = suffix in APXX_SUFFIXES
    is_archive = suffix == ".zip" or is_tia_archive_suffix(suffix)
    if not is_apxx and not is_archive:
        raise HTTPException(
            status_code=415,
            detail="project must be .ap17-.ap20/.apxx, .zap*, or a ZIP project tree",
        )

    if not _OPENNESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Another Openness operation is active; retry after it finishes",
        )

    work = Path(tempfile.mkdtemp(prefix="researchos_openness_work_"))
    result_archive: Path | None = None
    source: Path | None = None
    started = time.monotonic()
    try:
        upload_path, _size = _save_upload(
            project.file, filename=filename, max_bytes=_max_upload_bytes()
        )
        if is_archive:
            extracted = work / "extracted"
            extracted.mkdir()
            try:
                _safe_extract_zip(upload_path, extracted)
            except (zipfile.BadZipFile, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            source = _choose_project(extracted)
            source_kind = "archive"
        else:
            source = _choose_project(work, direct_file=upload_path)
            source_kind = "apxx"

        if source.is_file():
            export_dir = work / "export"
            export_dir.mkdir()
            _path, notes, timings = _export_without_remote_loopback(
                source, export_dir=export_dir
            )
            exported = export_dir
        else:
            exported = source
            notes = ["Uploaded archive already contains a SimaticML export"]
            timings = {"openness_worker_export_ms": 0}

        if not has_simaticml_exports(exported):
            raise HTTPException(status_code=502, detail="Openness produced no SimaticML XML")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        timings.setdefault("openness_worker_total_ms", elapsed_ms)
        export_key = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:24]
        result_archive = _zip_export_tree(
            exported,
            _write_manifest(filename, source_kind, notes, timings),
        )
        return _file_response(
            result_archive,
            export_key=export_key,
            timing_ms=elapsed_ms,
            notes=notes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        from agents.plc.tia.openness_cli import format_openness_failure

        detail = format_openness_failure(exc, project_path=source, action="export")
        raise HTTPException(status_code=502, detail=detail) from exc
    finally:
        _OPENNESS_LOCK.release()
        shutil.rmtree(work, ignore_errors=True)


@app.post("/import", dependencies=[Depends(require_bearer)])
def import_writeback_bundle(
    bundle: UploadFile = File(...),
    plc_name: str = "",
    compile_after: bool = True,
) -> dict[str, object]:
    """Import a staged write-back bundle into the TIA project, then compile.

    The upload is one ZIP built by ``industrial.openness_worker.client``:

        project/   complete .apxx project tree
        import/    staged bundle — XML at the root, SCL under external_sources/

    Delegates to ``agents.plc.tia.writeback.execute_writeback`` so the worker
    keeps the same safety refusals (F-block / know-how) and fail-closed
    compile gate as the Windows HostGateway path. Returns the write-back
    report as JSON (``ok`` reflects import + compile outcome).
    """
    filename = Path(bundle.filename or "").name
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=415, detail="bundle must be a ZIP archive")
    if not _OPENNESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Another Openness operation is active; retry after it finishes",
        )
    work = Path(tempfile.mkdtemp(prefix="researchos_openness_import_"))
    source: Path | None = None
    started = time.monotonic()
    try:
        upload_path, _size = _save_upload(
            bundle.file, filename=filename, max_bytes=_max_upload_bytes()
        )
        extracted = work / "bundle"
        extracted.mkdir()
        try:
            _safe_extract_zip(upload_path, extracted)
        except (zipfile.BadZipFile, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        project_root = extracted / "project"
        search_root = project_root if project_root.is_dir() else extracted
        candidates = find_apxx_files(search_root)
        complete = [c for c in candidates if is_complete_tia_project(c)]
        if not complete:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Bundle contains no complete .apxx project tree; "
                    "project/ must hold the archived TIA project"
                ),
            )
        source = complete[0]

        staged_root = extracted / "import"
        if not staged_root.is_dir():
            raise HTTPException(
                status_code=422,
                detail="Bundle contains no import/ directory with staged XML/SCL",
            )
        from agents.plc.tia.writeback import execute_writeback

        report = execute_writeback(
            source,
            staged_root,
            plc_name=plc_name or os.getenv("RESEARCHOS_DEFAULT_PLC_NAME", ""),
            compile_after=compile_after,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        report["via"] = "openness-worker"
        report["worker"] = {
            "service": "researchos-openness-worker",
            "project": source.name,
            "bundle": filename,
            "total_ms": elapsed_ms,
        }
        return report
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        from agents.plc.tia.openness_cli import format_openness_failure

        detail = format_openness_failure(exc, project_path=source, action="import")
        raise HTTPException(status_code=502, detail=detail) from exc
    finally:
        _OPENNESS_LOCK.release()
        shutil.rmtree(work, ignore_errors=True)


@app.post("/devices/create", dependencies=[Depends(require_bearer)])
def create_device_endpoint(
    project_path: str,
    type_identifier: str,
    name: str,
    device_name: str = "",
    plc_name: str = "",
) -> dict[str, object]:
    """Create a device/CPU via Openness."""
    from agents.plc.tia.openness_cli import create_device_via_openness_cli

    if not _OPENNESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="Another Openness operation is active; retry after it finishes"
        )
    try:
        return create_device_via_openness_cli(
            project_path, type_identifier, name, device_name=device_name, plc_name=plc_name
        )
    finally:
        _OPENNESS_LOCK.release()


@app.post("/libraries/open", dependencies=[Depends(require_bearer)])
def open_library_endpoint(
    library_path: str,
    read_only: bool = True,
) -> dict[str, object]:
    """Open a Global Library via Openness."""
    from agents.plc.tia.openness_cli import open_library_via_openness_cli

    if not _OPENNESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="Another Openness operation is active; retry after it finishes"
        )
    try:
        return open_library_via_openness_cli(library_path, read_only=read_only)
    finally:
        _OPENNESS_LOCK.release()


@app.post("/libraries/copy", dependencies=[Depends(require_bearer)])
def copy_from_library_endpoint(
    library_path: str,
    item_name: str,
    project_path: str = "",
    target_group: str = "",
    plc_name: str = "",
) -> dict[str, object]:
    """Copy an item from a Global Library into the project via Openness."""
    from agents.plc.tia.openness_cli import copy_from_library_via_openness_cli

    if not _OPENNESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="Another Openness operation is active; retry after it finishes"
        )
    try:
        return copy_from_library_via_openness_cli(
            library_path, item_name, project_path=project_path, target_group=target_group, plc_name=plc_name
        )
    finally:
        _OPENNESS_LOCK.release()


@app.get("/tags", dependencies=[Depends(require_bearer)])
def get_tags_endpoint(
    project_path: str = "",
    table_name: str = "",
    plc_name: str = "",
) -> dict[str, object]:
    """Inspect and list tags from a TagTable via Openness."""
    from agents.plc.tia.openness_cli import get_tags_via_openness_cli

    if not _OPENNESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="Another Openness operation is active; retry after it finishes"
        )
    try:
        return get_tags_via_openness_cli(
            project_path=project_path, table_name=table_name, plc_name=plc_name
        )
    finally:
        _OPENNESS_LOCK.release()


def run() -> None:
    """Run the worker from the repository virtual environment."""
    uvicorn.run(
        app,
        host=os.getenv("RESEARCHOS_OPENNESS_WORKER_HOST", "0.0.0.0"),
        port=int(os.getenv("RESEARCHOS_OPENNESS_WORKER_PORT", "8015")),
    )


if __name__ == "__main__":
    run()
