"""Locate and invoke the TIA Openness MCP / CLI host (C# net481)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def openness_server_project() -> Path:
    return (
        repo_root()
        / "tools"
        / "industrial-mcp"
        / "tia-openness"
        / "src"
        / "TiaOpenness.Server"
        / "TiaOpenness.Server.csproj"
    )


def find_openness_exe() -> Path | None:
    """Prefer an already-built Release/Debug exe; else None (caller may use `dotnet run`)."""
    override = os.getenv("RESEARCHOS_TIA_OPENNESS_EXE", "").strip()
    if override:
        p = Path(override).expanduser()
        return p if p.is_file() else None

    base = (
        repo_root()
        / "tools"
        / "industrial-mcp"
        / "tia-openness"
        / "src"
        / "TiaOpenness.Server"
        / "bin"
    )
    for cfg in ("Release", "Debug"):
        candidate = base / cfg / "net481" / "TiaOpenness.Server.exe"
        if candidate.is_file():
            return candidate
    return None


def _payload_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        parts: list[str] = []
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            parts.append(str(err["message"]))
        elif err:
            parts.append(str(err))
        for key in ("message", "export", "import", "archive", "project", "generate", "compile", "retrieve", "create", "close"):
            val = payload.get(key)
            if isinstance(val, dict):
                nested = _payload_text(val)
                if nested:
                    parts.append(nested)
            elif isinstance(val, str) and val.strip():
                parts.append(val)
        return "\n".join(parts) if parts else json.dumps(payload, ensure_ascii=False)
    return str(payload)


def is_license_error(text: str) -> bool:
    t = (text or "").lower()
    return (
        "necessary license" in t
        or ("license" in t and ("missing" in t or "step 7" in t or "step7" in t))
        or "step 7 basic" in t
        or "step7 basic" in t
    )


def is_inconsistent_export_error(text: str) -> bool:
    """True when Openness refused export because blocks/UDTs are not compiled/consistent."""
    t = (text or "").lower()
    return (
        "inconsistent" in t
        or "isconsistent=false" in t.replace(" ", "")
        or "inconsistent_blocks" in t
    )


def _looks_like_missing_powershell(text: str) -> bool:
    """Linux Docker Gateway used to spawn ``powershell`` and raise Errno 2."""
    t = (text or "").lower()
    if "powershell" not in t:
        return False
    return (
        "no such file" in t
        or "errno 2" in t
        or "winerror 2" in t
        or "the system cannot find" in t
        or "not found" in t
    )


def _looks_like_missing_windows_openness_host(text: str) -> bool:
    """C# CLI / net481 exe is absent or not executable on this host."""
    t = (text or "").lower()
    return (
        "tiaopenness.server" in t
        or ("dotnet" in t and ("no such file" in t or "errno 2" in t))
        or "exec format error" in t
    )


def format_openness_failure(
    payload_or_exc: Any,
    *,
    project_path: str | Path | None = None,
    action: str = "export",
) -> str:
    """Human-readable Openness failure; license errors are primary (not 'no XML')."""
    text = _payload_text(payload_or_exc)
    if isinstance(payload_or_exc, BaseException):
        text = str(payload_or_exc) or text
    proj = str(project_path) if project_path else ""
    if is_license_error(text):
        return (
            "TIA Openness 已打开工程，但操作失败：缺少必要许可证（如 STEP 7 Basic）。\n"
            "请在本机 Automation License Manager 安装/激活与 Portal 版本匹配的 "
            "STEP 7 / TIA 许可证后重试导出与写回。\n"
            + (f"工程: {proj}\n" if proj else "")
            + f"详情: {text}"
        )
    if _looks_like_missing_powershell(text) or (
        os.name != "nt" and _looks_like_missing_windows_openness_host(text)
    ):
        from agents.plc.tia.importer import openness_linux_unsupported_guidance

        return openness_linux_unsupported_guidance(project_path)
    if action == "export" and is_inconsistent_export_error(text):
        return (
            "TIA Openness 已打开工程，但程序块/UDT 处于**不一致（Inconsistent）**状态，"
            "无法导出 SimaticML XML。\n"
            "Siemens Openness 只能导出已成功编译且 `IsConsistent=true` 的对象。\n\n"
            "请按下列步骤处理后重新上传：\n"
            "1) 用匹配版本的 TIA Portal 打开该工程（或 Project → Retrieve 打开 .zap）\n"
            "2) 右键 PLC → 编译 → 软件（仅）或全部，消除全部编译错误（含 UDT）\n"
            "3) 保存工程，再 Archive 为新的 `.zap`，或导出 Blocks XML\n"
            "4) 将新的 `.zap` / XML 上传到 ResearchOS\n\n"
            + (f"工程: {proj}\n" if proj else "")
            + f"详情: {text}"
        )
    action_cn = {
        "export": "导出 SimaticML XML",
        "import": "写回（Import）",
        "generate_from_source": "SCL External Source → GenerateBlocksFromSource",
        "generate_source_from_block": "块 → GenerateSourceFromBlocks SCL",
        "retrieve": "Projects.Retrieve 打开 .zap",
        "compile": "编译 PLC 软件（ICompilable.Compile）",
        "archive": "归档为 .zap",
        "create": "Projects.Create",
        "close": "Project.Close",
    }.get(action, action)
    return (
        f"TIA Openness {action_cn}失败。\n"
        + (f"工程: {proj}\n" if proj else "")
        + f"详情: {text or payload_or_exc}"
    )


def _env_flag(name: str, *, default: bool = True) -> bool:
    """Parse RESEARCHOS_* env flags; empty uses ``default``."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def skip_compile_enabled() -> bool:
    """Default ON — pass ``--skip-compile`` unless RESEARCHOS_TIA_SKIP_COMPILE=0."""
    return _env_flag("RESEARCHOS_TIA_SKIP_COMPILE", default=True)


def _openness_command(*cli_args: str) -> tuple[list[str], str, bool]:
    """Return (cmd, cwd, may_retry_without_nobuild)."""
    exe = find_openness_exe()
    csproj = openness_server_project()
    if exe is not None:
        return [str(exe), "--cli", *cli_args], str(exe.parent), False
    if csproj.is_file():
        cmd = [
            "dotnet",
            "run",
            "--project",
            str(csproj),
            "-c",
            "Release",
            "--no-build",
            "--",
            "--cli",
            *cli_args,
        ]
        return cmd, str(repo_root()), True
    raise FileNotFoundError(
        "TiaOpenness.Server not found. Build tools/industrial-mcp/tia-openness "
        "or set RESEARCHOS_TIA_OPENNESS_EXE."
    )


def _payload_from_stdio(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    stdout = (stdout or "").strip()
    stderr = (stderr or "").strip()
    payload: dict[str, Any]
    try:
        line = stdout.splitlines()[-1] if stdout else "{}"
        payload = json.loads(line)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "error": {
                "code": "cli_parse_error",
                "message": stdout or stderr or "empty CLI output",
            },
        }
    if returncode != 0 and payload.get("ok") is not False:
        payload.setdefault("ok", False)
        payload.setdefault(
            "error",
            {
                "code": "cli_exit",
                "message": stderr or f"exit {returncode}",
            },
        )
    payload["_exit_code"] = returncode
    if stderr:
        payload["_stderr"] = stderr[-2000:]
    return payload


def openness_cli(
    *cli_args: str,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Run `TiaOpenness.Server --cli ...` and parse JSON stdout."""
    cmd, cwd, may_retry_build = _openness_command(*cli_args)
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        cwd=cwd,
    )
    if completed.returncode != 0 and may_retry_build and "--no-build" in cmd:
        cmd = [a for a in cmd if a != "--no-build"]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            cwd=cwd,
        )
    return _payload_from_stdio(completed.stdout or "", completed.stderr or "", completed.returncode)


def _popen_with_journal(
    cmd: list[str],
    cwd: str,
    journal: Path,
    on_export_event,
    timeout_s: int,
) -> dict[str, Any]:
    """Run Openness CLI while draining ``_exported.jsonl`` into ``on_export_event``."""
    import time

    from agents.plc.tia.extract_stream import drain_export_journal

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    offset = 0
    deadline = time.monotonic() + timeout_s
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=10)
                payload = _payload_from_stdio(stdout or "", stderr or "", proc.returncode or 1)
                payload["ok"] = False
                payload.setdefault(
                    "error",
                    {"code": "cli_timeout", "message": f"Openness CLI timed out after {timeout_s}s"},
                )
                return payload
            offset = drain_export_journal(journal, offset, on_export_event)
            time.sleep(0.05)
        stdout, stderr = proc.communicate(timeout=15)
    except Exception:
        if proc.poll() is None:
            proc.kill()
        raise
    drain_export_journal(journal, offset, on_export_event)
    return _payload_from_stdio(stdout or "", stderr or "", proc.returncode or 0)


def _merge_cli_phase_timings(
    timings: dict[str, int],
    result: dict[str, Any],
) -> None:
    """Lift compileMs/listMs/exportMs/openMs from CLI JSON into timings."""
    export = result.get("export") if isinstance(result.get("export"), dict) else {}
    project_info = result.get("project") if isinstance(result.get("project"), dict) else {}
    for src, mapping in (
        (export, {
            "compileMs": "openness_compile_ms",
            "exportMs": "openness_blocks_export_ms",
            "listMs": "openness_list_ms",
        }),
        (project_info, {"openMs": "openness_open_ms"}),
        (result, {
            "openMs": "openness_open_ms",
            "compileMs": "openness_compile_ms",
            "listMs": "openness_list_ms",
            "exportMs": "openness_blocks_export_ms",
        }),
    ):
        if not isinstance(src, dict):
            continue
        for raw_key, out_key in mapping.items():
            if raw_key in src and src[raw_key] is not None:
                try:
                    timings[out_key] = int(src[raw_key])
                except (TypeError, ValueError):
                    pass


def _invoke_export_cli(
    args: list[str],
    *,
    export_dir: Path,
    timeout_s: int,
    on_export_event,
) -> dict[str, Any]:
    """Blocking JSON CLI, or Popen + journal drain when ``on_export_event`` is set."""
    if on_export_event is None:
        return openness_cli(*args, timeout_s=timeout_s)
    cmd, cwd, may_retry_build = _openness_command(*args)
    journal = export_dir / "_exported.jsonl"
    result = _popen_with_journal(cmd, cwd, journal, on_export_event, timeout_s)
    if (
        not result.get("ok")
        and may_retry_build
        and "--no-build" in cmd
        and int(result.get("_exit_code") or 0) != 0
    ):
        on_export_event({"reset": True})
        cmd = [a for a in cmd if a != "--no-build"]
        result = _popen_with_journal(cmd, cwd, journal, on_export_event, timeout_s)
    return result


def export_project_via_openness_cli(
    project_path: str | Path,
    *,
    export_dir: str | Path,
    tia_version: str = "",
    plc_name: str = "",
    timeout_s: int = 600,
    skip_compile: bool | None = None,
    on_export_event=None,
) -> tuple[Path, list[str], dict[str, int]]:
    """Export all blocks via C# Openness CLI; returns (export_dir, notes, timings_ms).

    When skip-compile is enabled (default via RESEARCHOS_TIA_SKIP_COMPILE=1), passes
    ``--skip-compile``. On inconsistent-blocks failure, retries once with compile.

    ``on_export_event`` receives each ``_exported.jsonl`` object while Export runs
    so Python can parse XML in parallel with the still-serial Openness Export.
    """
    import time

    project = Path(project_path).expanduser().resolve()
    out = Path(export_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    use_skip = skip_compile_enabled() if skip_compile is None else bool(skip_compile)

    args = [
        "export-project",
        "--project",
        str(project),
        "--export-dir",
        str(out),
    ]
    if tia_version:
        args.extend(["--version", tia_version])
    if plc_name:
        args.extend(["--plc", plc_name])
    if use_skip:
        args.append("--skip-compile")
    if os.getenv("RESEARCHOS_TIA_EXPORT_BLOCKS_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        args.append("--blocks-only")
    else:
        args.append("--full")

    notes: list[str] = []
    if use_skip:
        notes.append("Openness skip-compile enabled (RESEARCHOS_TIA_SKIP_COMPILE)")

    t0 = time.monotonic()
    result = _invoke_export_cli(
        args, export_dir=out, timeout_s=timeout_s, on_export_event=on_export_event
    )
    wall_ms = int((time.monotonic() - t0) * 1000)

    timings: dict[str, int] = {"openness_cli_ms": wall_ms}
    if use_skip:
        timings["openness_skip_compile_ms"] = wall_ms

    failure_text = _payload_text(result)
    retried_with_compile = False
    if (
        not result.get("ok")
        and use_skip
        and is_inconsistent_export_error(failure_text)
    ):
        notes.append(
            "Openness skip-compile hit inconsistent blocks; "
            "retrying once with compile enabled"
        )
        if on_export_event is not None:
            on_export_event({"reset": True})
        retry_args = [a for a in args if a != "--skip-compile"]
        t1 = time.monotonic()
        result = _invoke_export_cli(
            retry_args,
            export_dir=out,
            timeout_s=timeout_s,
            on_export_event=on_export_event,
        )
        retry_ms = int((time.monotonic() - t1) * 1000)
        timings["openness_compile_retry_ms"] = retry_ms
        timings["openness_cli_ms"] = wall_ms + retry_ms
        retried_with_compile = True
        wall_ms = wall_ms + retry_ms

    _merge_cli_phase_timings(timings, result)

    export = result.get("export") if isinstance(result.get("export"), dict) else {}
    msg = str((export or {}).get("message") or "").strip()
    if msg:
        notes.append(msg)
    exported = (export or {}).get("exportedCount")
    failed = (export or {}).get("failedCount")
    if exported is not None or failed is not None:
        notes.append(
            f"Openness export counts: exported={exported or 0}, failed={failed or 0}"
        )
    know_how = (export or {}).get("knowHowProtectedCount")
    if know_how is not None:
        notes.append(f"Openness know-how protected blocks: {know_how}")
        try:
            timings["openness_knowhow_count"] = int(know_how)
        except (TypeError, ValueError):
            pass
    timing_bits = [
        f"{k}={v}ms"
        for k, v in timings.items()
        if k != "openness_cli_ms"
    ]
    if timing_bits:
        notes.append("Openness timings: " + ", ".join(timing_bits))
    notes.append(f"Openness CLI wall={wall_ms}ms")
    if retried_with_compile:
        notes.append(
            f"Openness compile retry wall={timings.get('openness_compile_retry_ms', 0)}ms"
        )
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=project, action="export")
        )
    return out, notes, timings


def import_block_via_openness_cli(
    project_path: str | Path,
    xml_path: str | Path,
    *,
    plc_name: str = "",
    overwrite: bool = True,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Import one SimaticML block XML via ``--cli import-block`` (save inside CLI)."""
    project = Path(project_path).expanduser().resolve()
    xml = Path(xml_path).expanduser().resolve()
    if not xml.is_file():
        raise FileNotFoundError(f"Block XML not found: {xml}")

    args = [
        "import-block",
        "--project",
        str(project),
        "--xml",
        str(xml),
    ]
    if plc_name:
        args.extend(["--plc", plc_name])
    if not overwrite:
        args.append("--no-overwrite")

    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=project, action="import")
        )
    return result


def _zap_name_for_project(project: Path, explicit: str = "") -> str:
    if explicit:
        return Path(explicit).name
    m = re.search(r"\.ap(1[789]|20)$", project.suffix.lower())
    ver = m.group(1) if m else "19"
    return f"{project.stem}.zap{ver}"


def generate_from_source_via_openness_cli(
    project_path: str | Path,
    scl_path: str | Path,
    *,
    plc_name: str = "",
    overwrite: bool = True,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Import one .scl via ``--cli generate-from-source`` (save inside CLI).

    Official Openness path: ExternalSourceGroup.ExternalSources.CreateFromFile
    + PlcExternalSource.GenerateBlocksFromSource(). Windows HostGateway only.
    """
    project = Path(project_path).expanduser().resolve()
    scl = Path(scl_path).expanduser().resolve()
    if not scl.is_file():
        raise FileNotFoundError(f"SCL source not found: {scl}")

    args = [
        "generate-from-source",
        "--project",
        str(project),
        "--scl",
        str(scl),
    ]
    if plc_name:
        args.extend(["--plc", plc_name])
    if not overwrite:
        args.append("--no-overwrite")

    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(
                result, project_path=project, action="generate_from_source"
            )
        )
    return result


def compile_plc_via_openness_cli(
    project_path: str | Path,
    *,
    plc_name: str = "",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Fail-closed PLC compile via ``--cli compile-plc``.

    If ICompilable is unreachable, the CLI returns ok=false /
    compile_api_unavailable — callers must not archive .zap.
    """
    project = Path(project_path).expanduser().resolve()
    args = ["compile-plc", "--project", str(project)]
    if plc_name:
        args.extend(["--plc", plc_name])
    result = openness_cli(*args, timeout_s=timeout_s)
    compile = result.get("compile") if isinstance(result.get("compile"), dict) else {}
    if not result.get("ok"):
        # Do not raise a generic import error — return structured fail-closed payload.
        if not compile:
            compile = {
                "ok": False,
                "apiAvailable": False,
                "error": result.get("error")
                or {"code": "compile_api_unavailable", "message": _payload_text(result)},
            }
        result = dict(result)
        result["ok"] = False
        result["compile"] = compile
        return result
    return result


def archive_project_via_openness_cli(
    project_path: str | Path,
    *,
    out: str | Path,
    tia_version: str = "",
    timeout_s: int = 600,
) -> Path:
    """Archive openable .apxx to a compressed .zap* via Openness CLI."""
    project = Path(project_path).expanduser().resolve()
    out_path = Path(out).expanduser().resolve()
    if out_path.suffix.lower().startswith(".zap") or out_path.suffix.lower() in {
        ".zap15",
        ".zap16",
        ".zap17",
        ".zap18",
        ".zap19",
        ".zap20",
    }:
        out_dir = out_path.parent
        name = out_path.name
    else:
        out_dir = out_path
        name = _zap_name_for_project(project)
    out_dir.mkdir(parents=True, exist_ok=True)

    args = [
        "archive-project",
        "--project",
        str(project),
        "--out-dir",
        str(out_dir),
        "--name",
        name,
    ]
    if tia_version:
        args.extend(["--version", tia_version])

    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=project, action="archive")
        )
    archive = result.get("archive") if isinstance(result.get("archive"), dict) else {}
    archived = Path(str((archive or {}).get("archivePath") or (out_dir / name)))
    if not archived.is_file():
        # Siemens may write without matching our exact name; pick newest zap in dir
        zaps = sorted(
            out_dir.glob("*.zap*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not zaps:
            raise RuntimeError(
                format_openness_failure(
                    {"message": f"Archive reported ok but no .zap found under {out_dir}"},
                    project_path=project,
                    action="archive",
                )
            )
        archived = zaps[0]
    return archived


def import_xml_via_openness_cli(
    project_path: str | Path,
    xml_path: str | Path,
    *,
    kind: str = "auto",
    plc_name: str = "",
    overwrite: bool = True,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Import SimaticML / AML / HMI XML via ``--cli import-xml``.

    ``kind`` is auto|block|type|tag|watch|force|hmi|hardware|cfc|to.
    Missing official Import fails closed (``no_import``).
    """
    project = Path(project_path).expanduser().resolve()
    xml = Path(xml_path).expanduser().resolve()
    if not xml.is_file():
        raise FileNotFoundError(f"XML file not found: {xml}")

    args = [
        "import-xml",
        "--project",
        str(project),
        "--xml",
        str(xml),
        "--kind",
        kind or "auto",
    ]
    if plc_name:
        args.extend(["--plc", plc_name])
    if not overwrite:
        args.append("--no-overwrite")

    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=project, action="import")
        )
    return result


def generate_source_from_block_via_openness_cli(
    project_path: str | Path,
    block_name: str,
    *,
    out: str | Path | None = None,
    plc_name: str = "",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Generate SCL from a writable non-safety block via GenerateSourceFromBlocks."""
    project = Path(project_path).expanduser().resolve()
    args = [
        "generate-source-from-block",
        "--project",
        str(project),
        "--block",
        block_name,
    ]
    if out:
        args.extend(["--out", str(Path(out).expanduser().resolve())])
    if plc_name:
        args.extend(["--plc", plc_name])
    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(
                result, project_path=project, action="generate_source_from_block"
            )
        )
    return result


def retrieve_archive_via_openness_cli(
    archive_path: str | Path,
    *,
    out: str | Path,
    plc_name: str = "",
    timeout_s: int = 600,
) -> Path:
    """Retrieve ``.zap*`` via official Openness ``Projects.Retrieve``."""
    archive = Path(archive_path).expanduser().resolve()
    out_dir = Path(out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "retrieve",
        "--archive",
        str(archive),
        "--out-dir",
        str(out_dir),
    ]
    if plc_name:
        args.extend(["--plc", plc_name])
    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=archive, action="retrieve")
        )
    retrieve = result.get("retrieve") if isinstance(result.get("retrieve"), dict) else result
    project_path = Path(str((retrieve or {}).get("projectPath") or ""))
    if not project_path.is_file():
        from agents.plc.tia.importer import find_apxx_files

        found = find_apxx_files(out_dir)
        if found:
            return found[0]
        raise RuntimeError(
            format_openness_failure(
                {"message": f"Retrieve reported ok but no .apxx under {out_dir}"},
                project_path=archive,
                action="retrieve",
            )
        )
    return project_path


def try_retrieve_archive_via_openness_cli(
    archive_path: str | Path,
    *,
    out: str | Path,
    plc_name: str = "",
    timeout_s: int = 600,
) -> Path | None:
    """Best-effort Retrieve; None when Openness/Portal/API is unavailable (Linux unzip fallback)."""
    try:
        return retrieve_archive_via_openness_cli(
            archive_path, out=out, plc_name=plc_name, timeout_s=timeout_s
        )
    except Exception:  # noqa: BLE001 — caller falls back to ZIP extract
        return None
