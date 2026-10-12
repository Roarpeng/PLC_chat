"""HTTP client used by the PLC importer to reach a Windows Openness worker."""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterator

import httpx


DEFAULT_TIMEOUT_S = 600
_UPLOAD_CHUNK = 1024 * 1024


def worker_base_url() -> str:
    """Return the configured worker URL, or an empty string when disabled."""
    return os.getenv("RESEARCHOS_OPENNESS_WORKER_URL", "").strip().rstrip("/")


def _worker_token() -> str:
    return os.getenv("RESEARCHOS_OPENNESS_WORKER_TOKEN", "").strip()


def _timeout_s(timeout_s: int | None) -> int:
    raw = os.getenv("RESEARCHOS_OPENNESS_WORKER_TIMEOUT_S", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("RESEARCHOS_OPENNESS_WORKER_TIMEOUT_S must be an integer") from exc
        if value <= 0:
            raise ValueError("RESEARCHOS_OPENNESS_WORKER_TIMEOUT_S must be positive")
        return value
    return max(1, int(timeout_s or DEFAULT_TIMEOUT_S))


@contextmanager
def _archived_project(project_path: Path) -> Iterator[tuple[Path, str]]:
    """Archive a complete project tree while preserving its identifying name."""
    project = project_path.expanduser().resolve()
    if project.is_file():
        root = project.parent
        display_name = f"{project.stem}_project.zip"
    elif project.is_dir():
        root = project
        display_name = f"{project.name}.zip"
    else:
        raise FileNotFoundError(f"Openness worker project not found: {project}")

    fd, archive_name = tempfile.mkstemp(prefix="researchos_openness_worker_", suffix=".zip")
    os.close(fd)
    archive = Path(archive_name)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                zf.write(item, item.relative_to(root).as_posix())
        yield archive, display_name
    finally:
        archive.unlink(missing_ok=True)


def _decode_notes(header: str | None) -> list[str]:
    if not header:
        return []
    try:
        value = json.loads(base64.b64decode(header.encode("ascii")).decode("utf-8"))
    except (UnicodeEncodeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return ["Openness worker returned an unreadable notes header"]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _safe_member_name(member: zipfile.ZipInfo) -> bool:
    name = member.filename
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    posix_path = PurePosixPath(normalized)
    if windows_path.drive or windows_path.root or posix_path.root:
        return False
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return False
    mode = member.external_attr >> 16
    return not (mode & 0o170000 == 0o120000)


def _validate_export_zip(payload: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        bad = [info.filename for info in zf.infolist() if not _safe_member_name(info)]
        if bad:
            raise ValueError(f"Unsafe Openness worker export member rejected: {bad[0]}")


def _replace_destination(staging: Path, destination: Path) -> None:
    if destination.is_symlink():
        raise ValueError(f"Openness worker export destination is a symlink: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for child in destination.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in staging.iterdir():
        shutil.move(str(child), str(destination / child.name))


def export_project_via_worker(
    project_path: str | Path,
    *,
    export_dir: str | Path,
    timeout_s: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[Path, list[str], dict[str, int]]:
    """Export a TIA project through the Windows worker.

    The return shape matches the local Openness executors so the importer can
    treat them interchangeably.
    """
    started = time.monotonic()
    base_url = worker_base_url()
    if not base_url:
        raise RuntimeError("RESEARCHOS_OPENNESS_WORKER_URL is not configured")
    source = Path(project_path).expanduser().resolve()
    destination = Path(export_dir).expanduser()

    headers: dict[str, str] = {}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with _archived_project(source) as (archive, filename):
        with httpx.Client(timeout=_timeout_s(timeout_s), transport=transport) as client:
            with archive.open("rb") as upload:
                response = client.post(
                    f"{base_url}/export",
                    files={"project": (filename, upload, "application/zip")},
                    headers=headers,
                )

    if not 200 <= response.status_code < 300:
        detail = response.text.strip()
        raise RuntimeError(
            f"Openness worker export failed ({response.status_code}): {detail[:4000]}"
        )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/zip":
        raise RuntimeError(
            f"Openness worker returned {content_type or 'an unknown content type'}; "
            "expected application/zip"
        )

    try:
        _validate_export_zip(response.content)
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ValueError(f"Invalid Openness worker export ZIP: {exc}") from exc

    staging = Path(tempfile.mkdtemp(prefix="researchos_openness_result_"))
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(staging)
        _replace_destination(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    timings: dict[str, int] = {"openness_worker_client_ms": elapsed_ms}
    try:
        worker_ms = int(response.headers.get("X-ResearchOS-Timing-Ms", ""))
    except ValueError:
        worker_ms = 0
    if worker_ms > 0:
        timings["openness_worker_ms"] = worker_ms

    notes = _decode_notes(response.headers.get("X-ResearchOS-Notes-B64"))
    export_key = response.headers.get("X-ResearchOS-Export-Key", "").strip()
    if export_key:
        notes.append(f"Openness worker export key={export_key}")
    notes.insert(0, f"exported through Windows Openness worker {base_url}")
    return destination.resolve(), notes, timings


def _writeback_bundle_zip(
    project_path: Path, bundle_dir: Path, fd: int
) -> tuple[str, int]:
    """Build the /import upload ZIP: project/ tree + import/ staged files.

    Returns (filename, file_count). XML sources land at the archive root of
    ``import/``, SCL under ``import/external_sources/`` so the worker's
    ``execute_writeback`` fallback globs find them without manifests.
    """
    import zipfile as _zipfile

    from agents.plc.tia.writeback import staged_files

    xmls, scls = staged_files(bundle_dir)
    if not xmls and not scls:
        os.close(fd)  # never leak the temp-file handle on Windows
        raise ValueError(f"Write-back bundle has no staged XML/SCL: {bundle_dir}")

    project = project_path.expanduser().resolve()
    root = project.parent if project.is_file() else project
    count = 0
    with _zipfile.ZipFile(os.fdopen(fd, "wb"), "w", compression=_zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(root.rglob("*")):
            if not item.is_file():
                continue
            zf.write(item, f"project/{item.relative_to(root).as_posix()}")
            count += 1
        for xml in xmls:
            zf.write(xml, f"import/{Path(xml).name}")
            count += 1
        for scl in scls:
            zf.write(scl, f"import/external_sources/{Path(scl).name}")
            count += 1
    return "writeback_bundle.zip", count


def import_bundle_via_worker(
    project_path: str | Path,
    bundle_dir: str | Path,
    *,
    plc_name: str = "",
    compile_after: bool = True,
    timeout_s: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Import + compile a staged write-back bundle through the Windows worker.

    Mirrors ``agents.plc.tia.writeback.execute_writeback``'s report shape so
    callers (Gateway HITL confirm) treat local CLI and worker paths alike.
    """
    started = time.monotonic()
    base_url = worker_base_url()
    if not base_url:
        raise RuntimeError("RESEARCHOS_OPENNESS_WORKER_URL is not configured")
    source = Path(project_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Openness worker project not found: {source}")
    bundle = Path(bundle_dir).expanduser().resolve()
    if not bundle.is_dir():
        raise FileNotFoundError(f"Write-back bundle not found: {bundle}")

    headers: dict[str, str] = {}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    fd, tmp_name = tempfile.mkstemp(prefix="researchos_openness_import_", suffix=".zip")
    archive = Path(tmp_name)
    try:
        filename, _count = _writeback_bundle_zip(source, bundle, fd)
        with httpx.Client(timeout=_timeout_s(timeout_s), transport=transport) as client:
            with archive.open("rb") as upload:
                response = client.post(
                    f"{base_url}/import",
                    params={
                        "plc_name": plc_name,
                        "compile_after": "true" if compile_after else "false",
                    },
                    files={"bundle": (filename, upload, "application/zip")},
                    headers=headers,
                )
    finally:
        archive.unlink(missing_ok=True)

    if not 200 <= response.status_code < 300:
        detail = response.text.strip()
        raise RuntimeError(
            f"Openness worker import failed ({response.status_code}): {detail[:4000]}"
        )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise RuntimeError(
            f"Openness worker returned {content_type or 'an unknown content type'}; "
            "expected application/json"
        )
    try:
        report = response.json()
    except ValueError as exc:
        raise RuntimeError("Openness worker returned an unreadable import report") from exc
    if not isinstance(report, dict):
        raise RuntimeError("Openness worker import report is not a JSON object")

    elapsed_ms = int((time.monotonic() - started) * 1000)
    timings = report.get("worker") if isinstance(report.get("worker"), dict) else {}
    timings = {**timings, "openness_worker_client_ms": elapsed_ms}
    report["timings"] = timings
    results = list(report.get("results") or []) + list(report.get("scl_results") or [])
    for entry in results:
        if isinstance(entry, dict):
            entry.setdefault("result", {})
    report.setdefault(
        "note",
        "Imported through the Windows Openness worker; compile gate enforced there.",
    )
    return report


def create_device_via_worker(
    project_path: str | Path,
    type_identifier: str,
    name: str,
    *,
    device_name: str = "",
    plc_name: str = "",
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call Openness worker to create a device."""
    base_url = worker_base_url()
    if not base_url:
        from agents.plc.tia.openness_cli import create_device_via_openness_cli
        return create_device_via_openness_cli(
            project_path, type_identifier, name, device_name=device_name, plc_name=plc_name
        )

    headers = {}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=_timeout_s(timeout_s)) as client:
        resp = client.post(
            f"{base_url}/devices/create",
            params={
                "project_path": str(project_path),
                "type_identifier": type_identifier,
                "name": name,
                "device_name": device_name,
                "plc_name": plc_name,
            },
            headers=headers,
        )
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"Openness worker create_device failed: {resp.text}")
        return resp.json()


def open_library_via_worker(
    library_path: str | Path,
    *,
    read_only: bool = True,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call Openness worker to open a global library."""
    base_url = worker_base_url()
    if not base_url:
        from agents.plc.tia.openness_cli import open_library_via_openness_cli
        return open_library_via_openness_cli(library_path, read_only=read_only)

    headers = {}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=_timeout_s(timeout_s)) as client:
        resp = client.post(
            f"{base_url}/libraries/open",
            params={"library_path": str(library_path), "read_only": read_only},
            headers=headers,
        )
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"Openness worker open_library failed: {resp.text}")
        return resp.json()


def copy_from_library_via_worker(
    library_path: str | Path,
    item_name: str,
    *,
    project_path: str | Path = "",
    target_group: str = "",
    plc_name: str = "",
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call Openness worker to copy an item from global library."""
    base_url = worker_base_url()
    if not base_url:
        from agents.plc.tia.openness_cli import copy_from_library_via_openness_cli
        return copy_from_library_via_openness_cli(
            library_path, item_name, project_path=project_path, target_group=target_group, plc_name=plc_name
        )

    headers = {}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=_timeout_s(timeout_s)) as client:
        resp = client.post(
            f"{base_url}/libraries/copy",
            params={
                "library_path": str(library_path),
                "item_name": item_name,
                "project_path": str(project_path) if project_path else "",
                "target_group": target_group,
                "plc_name": plc_name,
            },
            headers=headers,
        )
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"Openness worker copy_from_library failed: {resp.text}")
        return resp.json()


def get_tags_via_worker(
    *,
    project_path: str | Path = "",
    table_name: str = "",
    plc_name: str = "",
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Call Openness worker to inspect tags."""
    base_url = worker_base_url()
    if not base_url:
        from agents.plc.tia.openness_cli import get_tags_via_openness_cli
        return get_tags_via_openness_cli(
            project_path=project_path, table_name=table_name, plc_name=plc_name
        )

    headers = {}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=_timeout_s(timeout_s)) as client:
        resp = client.get(
            f"{base_url}/tags",
            params={
                "project_path": str(project_path) if project_path else "",
                "table_name": table_name,
                "plc_name": plc_name,
            },
            headers=headers,
        )
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"Openness worker get_tags failed: {resp.text}")
        return resp.json()

