"""PLC write-back orchestration — import bundle → Openness XML/SCL + compile gate.

Execution paths:
- Windows host: local Openness CLI directly (HostGateway mode).
- Linux/Docker Gateway with ``RESEARCHOS_OPENNESS_WORKER_URL`` configured:
  delegate the whole import+compile to the Windows Openness worker
  (``industrial/openness_worker``), keeping the same fail-closed report shape.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agents.plc.tia.changeset import PlcChangeSet, write_import_bundle
from agents.plc.tia.openness_cli import (
    compile_plc_via_openness_cli,
    generate_from_source_via_openness_cli,
    import_block_via_openness_cli,
    import_xml_via_openness_cli,
)
from agents.plc.tia.surface import classify_xml_kind, xml_looks_like_safety


def prepare_writeback(
    job_export_dir: str | Path,
    changeset: PlcChangeSet,
    source_xmls: list[str | Path] | None = None,
) -> Path:
    """Build ``{job_export_dir}/import_bundle`` and return that directory."""
    bundle = Path(job_export_dir).expanduser().resolve() / "import_bundle"
    write_import_bundle(bundle, changeset, source_xmls)
    return bundle


def _staged_xmls(bundle_dir: Path) -> list[Path]:
    manifest = bundle_dir / "staged_xmls.json"
    if manifest.is_file():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return [Path(p) for p in raw if Path(p).is_file()]
    return sorted(bundle_dir.glob("*.xml"))


def _staged_scls(bundle_dir: Path) -> list[Path]:
    manifest = bundle_dir / "staged_scls.json"
    if manifest.is_file():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return [Path(p) for p in raw if Path(p).is_file()]
    ext = bundle_dir / "external_sources"
    if ext.is_dir():
        return sorted(ext.glob("*.scl"))
    return []


def staged_files(bundle_dir: str | Path) -> tuple[list[Path], list[Path]]:
    """Public view of a prepared bundle: (staged XMLs, staged SCL sources)."""
    bundle = Path(bundle_dir).expanduser().resolve()
    return _staged_xmls(bundle), _staged_scls(bundle)


def _is_windows_local() -> bool:
    return os.name == "nt"


def _worker_preferred() -> bool:
    """True when this host cannot run Openness but a Windows worker is configured."""
    if _is_windows_local():
        return False
    try:
        from industrial.openness_worker.client import worker_base_url
    except Exception:  # noqa: BLE001 — worker client is optional at runtime
        return False
    return bool(worker_base_url())


def execute_writeback(
    project_path: str | Path,
    bundle_dir: str | Path,
    plc_name: str = "",
    *,
    compile_after: bool = True,
) -> dict[str, Any]:
    """Import staged XML (comments) and SCL (logic), then fail-closed compile.

    SCL import uses official Openness
    ``CreateFromFile`` + ``GenerateBlocksFromSource``. On a Windows host that
    runs directly against the local Openness CLI; a Linux/Docker Gateway with
    a configured worker delegates the whole operation to
    ``POST /import`` on the Windows Openness worker.
    Compile must succeed before the caller archives ``.zap``. If the compile
    API is unreachable, ``ok`` is false (fail closed) — do not archive.
    """
    bundle = Path(bundle_dir).expanduser().resolve()
    if _worker_preferred():
        from industrial.openness_worker.client import import_bundle_via_worker

        result = import_bundle_via_worker(
            project_path,
            bundle,
            plc_name=plc_name,
            compile_after=compile_after,
        )
        result["project_path"] = str(Path(project_path).expanduser().resolve())
        result["bundle_dir"] = str(bundle)
        result["via"] = "openness-worker"
        return result
    xmls = _staged_xmls(bundle)
    scls = _staged_scls(bundle)
    results: list[dict[str, Any]] = []
    scl_results: list[dict[str, Any]] = []
    import_ok = True

    for xml in xmls:
        if xml_looks_like_safety(xml):
            results.append(
                {
                    "xml": str(xml),
                    "result": {
                        "ok": False,
                        "skipReason": "safety_block",
                        "error": "Refusing Import for Safety/F-block XML. Never write F-block bodies.",
                    },
                }
            )
            import_ok = False
            continue
        kind = "block"
        try:
            head = xml.read_text(encoding="utf-8", errors="ignore")[:8192]
            kind = classify_xml_kind(xml.name, head)
        except OSError:
            kind = "block"
        try:
            if kind == "block":
                payload = import_block_via_openness_cli(
                    project_path,
                    xml,
                    plc_name=plc_name,
                    overwrite=True,
                )
            else:
                payload = import_xml_via_openness_cli(
                    project_path,
                    xml,
                    kind=kind,
                    plc_name=plc_name,
                    overwrite=True,
                )
            results.append({"xml": str(xml), "kind": kind, "result": payload})
        except Exception as exc:  # noqa: BLE001
            results.append(
                {"xml": str(xml), "kind": kind, "result": {"ok": False, "error": str(exc)}}
            )
            import_ok = False
            continue
        if not payload.get("ok"):
            import_ok = False

    for scl in scls:
        try:
            payload = generate_from_source_via_openness_cli(
                project_path,
                scl,
                plc_name=plc_name,
                overwrite=True,
            )
            scl_results.append({"scl": str(scl), "result": payload})
        except Exception as exc:  # noqa: BLE001
            scl_results.append({"scl": str(scl), "result": {"ok": False, "error": str(exc)}})
            import_ok = False
            continue
        if not payload.get("ok"):
            import_ok = False

    compile_payload: dict[str, Any] | None = None
    compiled_ok = False
    if compile_after and import_ok and (xmls or scls):
        compile_payload = compile_plc_via_openness_cli(project_path, plc_name=plc_name)
        compile = (
            compile_payload.get("compile")
            if isinstance(compile_payload.get("compile"), dict)
            else compile_payload
        )
        compiled_ok = bool(compile_payload.get("ok") and (compile or {}).get("ok", True))
        if compile and compile.get("apiAvailable") is False:
            compiled_ok = False
        if compile and compile.get("ok") is False:
            compiled_ok = False
    elif compile_after and not import_ok:
        compile_payload = {
            "ok": False,
            "skipped": True,
            "message": "Compile skipped because import failed.",
        }
    elif not compile_after:
        compile_payload = {"ok": False, "skipped": True, "message": "Compile not requested."}

    ok = import_ok and (compiled_ok if compile_after else import_ok)
    note = (
        "XML: Blocks.Import / TypeGroup.Types.Import / TagTables.Import when present + Save. "
        "SCL: ExternalSourceGroup.CreateFromFile + GenerateBlocksFromSource + Save. "
        "Compile: ICompilable.Compile (fail closed). "
        "F-block / know-how decrypt refused. Linux Docker delegates to the Windows "
        "Openness worker when RESEARCHOS_OPENNESS_WORKER_URL is configured."
    )
    return {
        "ok": ok,
        "import_ok": import_ok,
        "compiled_ok": compiled_ok,
        "project_path": str(Path(project_path).expanduser().resolve()),
        "bundle_dir": str(bundle),
        "imported": len(results),
        "scl_imported": len(scl_results),
        "results": results,
        "scl_results": scl_results,
        "compile": compile_payload,
        "note": note,
    }
