"""PLC input path authorization and upload extraction."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from gateway.app.config import Settings, get_settings


ALLOWED_UPLOAD_SUFFIXES = {
    ".xml",
    ".zip",
    ".zap",
    ".zap15",
    ".zap16",
    ".zap17",
    ".zap18",
    ".zap19",
    ".zap20",
    ".ap17",
    ".ap18",
    ".ap19",
    ".ap20",
    ".apxx",
}


def _allowlist_roots(settings: Settings) -> list[Path]:
    raw = (settings.plc_path_allowlist or "").strip()
    if not raw:
        # Dev default: temp + common project roots on the gateway host
        defaults = [
            Path(tempfile.gettempdir()),
            Path.cwd(),
            Path.home() / "Desktop" / "Project",
        ]
        return [p.resolve() for p in defaults if p.exists()]
    roots: list[Path] = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        roots.append(Path(part).expanduser().resolve())
    return roots


def resolve_allowed_path(path: str, settings: Settings | None = None) -> Path:
    """Resolve path and enforce allowlist sandbox."""
    settings = settings or get_settings()
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    roots = _allowlist_roots(settings)
    for root in roots:
        try:
            target.relative_to(root)
            return target
        except ValueError:
            continue
    raise PermissionError(
        f"Path not under PLC_PATH_ALLOWLIST. Allowed roots: {[str(r) for r in roots]}"
    )
def save_upload(filename: str | None, data: bytes, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    name = Path(filename or "upload.bin").name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError(
            f"Unsupported upload type '{suffix}'. Allowed: {sorted(ALLOWED_UPLOAD_SUFFIXES)}"
        )
    if not data:
        raise ValueError("Uploaded file is empty")
    max_mb = int(settings.plc_upload_max_mb or 200)
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"Upload exceeds {max_mb} MB limit")

    # Lone .apxx cannot be Open()'d — require .zap or a zip of the full project tree.
    from agents.plc.tia.importer import APXX_SUFFIXES, incomplete_apxx_guidance

    if suffix in APXX_SUFFIXES:
        raise ValueError(incomplete_apxx_guidance(name))

    root = Path(settings.plc_work_dir or tempfile.gettempdir()) / "researchos_plc_uploads"
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{uuid4().hex[:12]}_{name}"
    dest.write_bytes(data)

    if suffix == ".zip" or suffix == ".zap" or (
        suffix.startswith(".zap") and len(suffix) > 4 and suffix[4:].isdigit()
    ):
        from agents.plc.tia.importer import (
            extract_tia_archive,
            find_apxx_files,
            has_simaticml_exports,
            incomplete_apxx_guidance,
            is_complete_tia_project,
        )

        extract_dir = root / f"{dest.stem}_extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        extracted = extract_tia_archive(dest, dest=extract_dir)
        # After unpack: SimaticML XML is fine; bare incomplete .apxx is not.
        check_root = extracted if extracted.is_dir() else extracted.parent
        if not has_simaticml_exports(check_root):
            apxx = find_apxx_files(check_root)
            if apxx and not any(is_complete_tia_project(ap) for ap in apxx):
                raise ValueError(incomplete_apxx_guidance(apxx[0]))
        return extracted
    return dest


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract zip members, rejecting path traversal (zip slip)."""
    dest_root = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        try:
            target.relative_to(dest_root)
        except ValueError as exc:
            raise ValueError(f"Zip slip rejected: {member.filename}") from exc
    zf.extractall(dest)
