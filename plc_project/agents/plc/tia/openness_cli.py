"""Locate and invoke the TIA Openness one-shot CLI host (C# net481, no MCP)."""

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
    root = repo_root()
    candidates = (
        root / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server" / "TiaOpenness.Server.csproj",
        root / "industrial" / "tia_openness_mcp" / "src" / "TiaOpenness.Server" / "TiaOpenness.Server.csproj",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]



def find_openness_exe() -> Path | None:
    """Prefer an already-built Release/Debug exe; else None (caller may use `dotnet run`)."""
    override = os.getenv("RESEARCHOS_TIA_OPENNESS_EXE", "").strip()
    if override:
        p = Path(override).expanduser()
        if not p.is_absolute():
            p = (repo_root() / p).resolve()
        return p if p.is_file() else None

    bases = (
        repo_root() / "industrial" / "tia_openness_cli" / "src" / "TiaOpenness.Server" / "bin",
        repo_root() / "industrial" / "tia_openness_mcp" / "src" / "TiaOpenness.Server" / "bin",
    )
    for base in bases:
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


# ---------------------------------------------------------------------------
# Openness 错误详情提取（只增信息、不做截断）
#
# 溯源结论：真机 GenerateBlocksFromSource 失败时，C# Host 只回传
# ``Unwrap(ex).Message`` —— 即 ``EngineeringTargetInvocationException`` 的
# 包装语 "Error when calling method 'X' of type 'Y'"（常在类型名中途戛然而止，
# 本层 Python 侧没有任何 [:N] 切片）；SCL 行号/语法诊断藏在
# InnerException 全链与 EngineeringCompilationError 集合
# （Path/LineNumber/Text）里，只有它们被塞进 payload 时才有得提取。
# 本节把 CLI/worker payload 或 Python 异常中携带的这些结构完整取出、
# 逐行追加到失败消息尾部；展示层截断（画布 300 字符 / 流水线 50 条上限）
# 由消费方负责，提取层保证不丢信息。
# ---------------------------------------------------------------------------

# InnerException 链在 JSON payload 中可能的键名（C# camelCase 序列化）
_INNER_EXCEPTION_KEYS = ("innerException", "inner", "innerExceptions", "innerMessages")
# EngineeringCompilationError 集合可能的键名
_COMPILE_ERROR_KEYS = (
    "compilerErrors",
    "compilationErrors",
    "compileErrors",
    "engineeringCompilationErrors",
    "compilerMessages",
)
# 单条编译诊断的行号/文本/路径字段（各自按优先级取第一个非空）
_LINE_KEYS = ("lineNumber", "line", "lineStart", "ln")
_TEXT_KEYS = ("text", "description", "message", "msg")
_PATH_KEYS = ("path", "file", "fileName", "source")


def _iter_payload_dicts(node: Any, *, _depth: int = 0):
    """深度优先遍历 payload 里所有 dict（深度封顶，防御畸形嵌套）。"""
    if _depth > 10:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_payload_dicts(value, _depth=_depth + 1)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _iter_payload_dicts(value, _depth=_depth + 1)


def _normalize_line_number(raw: Any) -> int | None:
    """'000014'/'14'/14 → 14；无法解析返回 None。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.isdigit():
        return None
    stripped = text.lstrip("0")
    return int(stripped) if stripped else 0


def format_compilation_error_entry(entry: Any, *, default_path: str = "") -> str:
    """一条 EngineeringCompilationError → ``<文件> 行 N: 文本``。

    行号缺失时只留文本；Path 缺失时用 ``default_path``（外部源 .scl 文件名）
    兜底，保证每条诊断都能自证出自哪个源文件。未知 dict 结构整体 JSON
    序列化兜底——宁可冗长不可丢信息。
    """
    if isinstance(entry, dict):
        line = None
        for key in _LINE_KEYS:
            line = _normalize_line_number(entry.get(key))
            if line is not None:
                break
        text = ""
        for key in _TEXT_KEYS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text:
            text = json.dumps(entry, ensure_ascii=False)
        path = ""
        for key in _PATH_KEYS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                path = Path(value).name or value.strip()
                break
        if not path:
            path = default_path
        body = f"行 {line}: {text}" if line is not None else text
        if path:
            return f"{path} {body}"
        return body
    line_text = str(entry).strip() if entry is not None else ""
    if not line_text:
        return ""
    return f"{default_path} {line_text}" if default_path else line_text


def exception_chain_messages(exc: BaseException) -> list[str]:
    """Python 异常链（等价 .NET InnerException）全链消息。

    逐层取 ``__cause__``，无 cause 再看 ``__context__``；带环保护。
    ``str(exc)`` 只有最外层，修复循环需要的根因在链上。
    """
    messages: list[str] = []
    seen: set[int] = {id(exc)}
    current: BaseException | None = exc.__cause__ or exc.__context__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).strip()
        if message:
            messages.append(message)
        current = current.__cause__ or current.__context__
    return messages


def openness_error_details(
    payload_or_exc: Any,
    *,
    scl_path: str | Path | None = None,
) -> list[str]:
    """提取失败 payload / 异常中的附加错误详情行（不截断、不改动既有正文）。

    覆盖三类信息：
    (a) InnerException 全链消息 —— ``innerException`` 等键，逐层
        ``内部异常[N]: …``（Python 异常输入走 ``__cause__`` 链）；
    (b) 编译错误集合（EngineeringCompilationError：Path/LineNumber/Text）
        —— 逐条 ``<文件> 行 N: 文本``，整组并入单行（消费方的前瞻正则
        不接受条目间换行），兼容「行 N:」解析；
    (c) 外部源 .scl 文件名与首条诊断关联 —— ``外部源: <name>`` 置于诊断前。
    另附带 CLI ``_stderr`` 尾部（若有）。返回行只用于追加，展示层截断
    留给消费方。
    """
    inner_lines: list[str] = []
    compile_lines: list[str] = []

    # 外部源文件名：优先显式 scl_path，其次 payload 里的 sclPath/sourceName
    scl_name = Path(scl_path).name if scl_path else ""
    if not scl_name and not isinstance(payload_or_exc, BaseException):
        for node in _iter_payload_dicts(payload_or_exc):
            for key in ("sclPath", "sourceName"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    scl_name = Path(value).name
                    break
            if scl_name:
                break

    if isinstance(payload_or_exc, BaseException):
        # (a) Python 异常链：内部异常[1]/[2]/… 逐层带出根因
        for index, message in enumerate(exception_chain_messages(payload_or_exc), start=1):
            inner_lines.append(f"内部异常[{index}]: {message}")
    else:
        # 递归遍历：inner_depth 记录当前节点位于 InnerException 链的第几层，
        # 普通子结构重置为 0，避免链上 dict 被重复计数
        def _walk(node: Any, inner_depth: int) -> None:
            if inner_depth > 8 or node is None:
                return
            if isinstance(node, (str, int, float, bool)):
                if inner_depth > 0:
                    text = str(node).strip()
                    if text:
                        inner_lines.append(f"内部异常[{inner_depth}]: {text}")
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    _walk(item, 0)
                return
            if not isinstance(node, dict):
                return
            if inner_depth > 0:
                message = ""
                for key in _TEXT_KEYS:
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        message = value.strip()
                        break
                if not message:
                    message = json.dumps(node, ensure_ascii=False)
                inner_lines.append(f"内部异常[{inner_depth}]: {message}")
            for key, value in node.items():
                if key in _INNER_EXCEPTION_KEYS and value:
                    items = value if isinstance(value, (list, tuple)) else [value]
                    for item in items:
                        _walk(item, inner_depth + 1)
                elif key in _COMPILE_ERROR_KEYS:
                    entries = value
                    if isinstance(entries, dict):
                        entries = entries.get("errors") or entries.get("items") or []
                    if isinstance(entries, (list, tuple)):
                        for entry in entries:
                            line = format_compilation_error_entry(
                                entry, default_path=scl_name
                            )
                            if line:
                                compile_lines.append(line)
                    elif isinstance(entries, str) and entries.strip():
                        compile_lines.append(entries.strip())
                else:
                    _walk(value, 0)

        _walk(payload_or_exc, 0)

    details: list[str] = []
    if scl_name:
        details.append(f"外部源: {scl_name}")
    details.extend(inner_lines)
    # CLI stderr 尾部（_payload_from_stdio 收集，正文不会重复包含）
    if isinstance(payload_or_exc, dict):
        stderr = str(payload_or_exc.get("_stderr") or "").strip()
        if stderr:
            details.append(f"CLI stderr: {stderr}")
    # 编译诊断固定放在最后一行、整组并入单行：消费方
    # （plc_engine.attribute_compiler_errors）用前瞻
    # ``(?=行\s*0*\d+[:：]|$)`` 切分条目，``$`` 只匹配串尾——条目之间一旦
    # 换行就会整条丢失，故按 TIA 原生风格用三个空格串联全部条目
    if compile_lines:
        details.append(
            f"编译诊断（{len(compile_lines)} 条）: " + "   ".join(compile_lines)
        )
    return details


def format_openness_failure(
    payload_or_exc: Any,
    *,
    project_path: str | Path | None = None,
    action: str = "export",
    scl_path: str | Path | None = None,
) -> str:
    """Human-readable Openness failure; license errors are primary (not 'no XML').

    兼容约束：消息前缀格式与历史版本完全一致（"TIA Openness …失败。
    /工程: /详情: "），InnerException 链、编译诊断、外部源关联等新增
    详情行只追加在尾部——消费方（compile_jobs 归因 / fix_loop /
    refactor_pipeline）按 message 字符串解析，只允许信息量单调增加。
    """
    text = _payload_text(payload_or_exc)
    if isinstance(payload_or_exc, BaseException):
        text = str(payload_or_exc) or text
    proj = str(project_path) if project_path else ""
    extra_lines = openness_error_details(payload_or_exc, scl_path=scl_path)
    extra = ("\n" + "\n".join(extra_lines)) if extra_lines else ""
    if is_license_error(text):
        return (
            "TIA Openness 已打开工程，但操作失败：缺少必要许可证（如 STEP 7 Basic）。\n"
            "请在本机 Automation License Manager 安装/激活与 Portal 版本匹配的 "
            "STEP 7 / TIA 许可证后重试导出与写回。\n"
            + (f"工程: {proj}\n" if proj else "")
            + f"详情: {text}"
            + extra
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
            + extra
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
        + extra
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
        "TiaOpenness.Server not found. Build industrial/tia_openness_cli "
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
    blocks_only: bool | None = None,
    on_export_event=None,
) -> tuple[Path, list[str], dict[str, int]]:
    """Export via C# Openness CLI; returns (export_dir, notes, timings_ms).

    When skip-compile is enabled (default via RESEARCHOS_TIA_SKIP_COMPILE=1), passes
    ``--skip-compile``. On inconsistent-blocks failure, retries once with compile.

    ``blocks_only`` (default True for canvas speed): exports blocks+types+tags only.
    Set False or RESEARCHOS_TIA_EXPORT_BLOCKS_ONLY=0 for full HMI/hardware surface.

    ``on_export_event`` receives each ``_exported.jsonl`` object while Export runs
    so Python can parse XML in parallel with the still-serial Openness Export.
    """
    import time

    project = Path(project_path).expanduser().resolve()
    out = Path(export_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    use_skip = skip_compile_enabled() if skip_compile is None else bool(skip_compile)
    env_mode = os.getenv("RESEARCHOS_TIA_EXPORT_MODE", "").strip().lower()
    env_blocks = os.getenv("RESEARCHOS_TIA_EXPORT_BLOCKS_ONLY", "").strip().lower()
    # Mode resolution: env mode wins; else blocks_only kwarg; else legacy blocks-only default.
    if env_mode == "canvas":
        export_flag = "--canvas"
    elif env_mode == "full":
        export_flag = "--full"
    elif env_mode == "blocks-only" or env_mode == "blocks_only" or blocks_only is True:
        export_flag = "--blocks-only"
    elif blocks_only is False or env_blocks in {"0", "false", "no", "off"}:
        export_flag = "--full"
    else:
        export_flag = "--blocks-only"

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
    args.append(export_flag)
    notes_mode = export_flag.lstrip("-")

    notes: list[str] = [f"Openness export mode={notes_mode}"]
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
    software_unit: str = "",
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
    if software_unit:
        args.extend(["--unit", software_unit])
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
    software_unit: str = "",
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
    if software_unit:
        args.extend(["--unit", software_unit])
    if not overwrite:
        args.append("--no-overwrite")

    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        # 外部源生成失败：带上 scl_path，让提取层把 .scl 文件名与
        # 首条编译诊断关联（payload 里的 InnerException 链 /
        # EngineeringCompilationError 全部追加，不截断）
        raise RuntimeError(
            format_openness_failure(
                result,
                project_path=project,
                action="generate_from_source",
                scl_path=scl,
            )
        )
    return result


def fast_writeback_via_openness_cli(
    project_path: str | Path,
    scl_path: str | Path | None = None,
    *,
    body: dict[str, Any] | None = None,
    plc_name: str = "",
    software_unit: str = "",
    overwrite: bool = True,
    timeout_s: int = 600,
    compile_after: bool = True,
) -> dict[str, Any]:
    """通过常驻 Session 服务执行 /fast-writeback；若服务不可用则通过 CLI 回退或启动。

    返回归一化的回写与编译结果字典（兼容 FastWritebackResult 契约）。
    """
    if isinstance(project_path, dict) and body is None:
        body = project_path
        project_path = body.get("project") or body.get("project_path") or ""
        scl_path = scl_path or body.get("scl") or body.get("scl_path") or ""

    project = Path(project_path).expanduser().resolve()
    scl = Path(scl_path or (body.get("scl") if body else "") or (body.get("scl_path") if body else "")).expanduser().resolve()

    req_body: dict[str, Any] = dict(body or {})
    req_body.setdefault("project", str(project))
    req_body.setdefault("scl", str(scl))
    req_body.setdefault("scl_path", str(scl))
    if plc_name:
        req_body.setdefault("plc", plc_name)
    if software_unit:
        req_body.setdefault("unit", software_unit)
        req_body.setdefault("software_unit", software_unit)

    # 1. 优先检查并调用 openness_session.fast_writeback（若未运行则由 ensure_session_running 启动）
    try:
        from gateway.app.services.plc.openness_session import (
            ensure_session_running,
            fast_writeback,
            session_enabled,
        )

        if session_enabled() and ensure_session_running():
            res = fast_writeback(req_body, timeout_s=float(timeout_s))
            if not res.get("fallback") and not res.get("unreachable"):
                if "ok" not in res and "success" in res:
                    res["ok"] = bool(res.get("success"))
                return res
    except Exception:
        # 服务异常或未运行且启动失败，降级到 CLI 回退
        pass

    # 2. CLI 回退：单次 generate-from-source (+ compile-plc)
    gen_res = generate_from_source_via_openness_cli(
        project,
        scl,
        plc_name=plc_name,
        software_unit=software_unit,
        overwrite=overwrite,
        timeout_s=timeout_s,
    )
    compile_res: dict[str, Any] = {}
    compile_ok = True
    if compile_after and gen_res.get("ok"):
        compile_res = compile_plc_via_openness_cli(
            project,
            plc_name=plc_name,
            timeout_s=timeout_s,
        )
        compile_sub = compile_res.get("compile") if isinstance(compile_res.get("compile"), dict) else compile_res
        compile_ok = bool(compile_res.get("ok") and (compile_sub or {}).get("ok", True))
        if compile_sub and compile_sub.get("apiAvailable") is False:
            compile_ok = False
        if compile_sub and compile_sub.get("ok") is False:
            compile_ok = False

    ok = bool(gen_res.get("ok") and (compile_ok if compile_after else True))
    errors = []
    if isinstance(compile_res.get("compile"), dict):
        errors = compile_res["compile"].get("errors") or compile_res["compile"].get("inconsistentBlocks") or []
    return {
        "ok": ok,
        "success": ok,
        "fallback": True,
        "generate": gen_res,
        "compile": compile_res if compile_after else {"skipped": True},
        "errors": errors,
        "writtenBlockCount": req_body.get("writtenBlockCount") or 1,
        "skippedUnchangedBlocks": req_body.get("skippedUnchangedBlocks") or 0,
    }


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
    software_unit: str = "",
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
    if software_unit:
        args.extend(["--unit", software_unit])
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


def create_device_via_openness_cli(
    project_path: str | Path,
    type_identifier: str,
    name: str,
    *,
    device_name: str = "",
    plc_name: str = "",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Create a device / CPU via ``--cli create-device``."""
    project = Path(project_path).expanduser().resolve()
    args = [
        "create-device",
        "--project",
        str(project),
        "--type-id",
        type_identifier,
        "--name",
        name,
    ]
    if device_name:
        args.extend(["--device-name", device_name])
    if plc_name:
        args.extend(["--plc", plc_name])
    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=project, action="create_device")
        )
    return result


def open_library_via_openness_cli(
    library_path: str | Path,
    *,
    read_only: bool = True,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Open a Siemens Global Library (.al*) via ``--cli open-library``."""
    lib = Path(library_path).expanduser().resolve()
    args = ["open-library", "--path", str(lib)]
    if not read_only:
        args.append("--write")
    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=lib, action="open_library")
        )
    return result


def copy_from_library_via_openness_cli(
    library_path: str | Path,
    item_name: str,
    *,
    project_path: str | Path = "",
    target_group: str = "",
    plc_name: str = "",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Copy a master copy or library type into the project via ``--cli copy-from-library``."""
    lib = Path(library_path).expanduser().resolve()
    args = ["copy-from-library", "--library", str(lib), "--item", item_name]
    if project_path:
        project = Path(project_path).expanduser().resolve()
        args.extend(["--project", str(project)])
    if target_group:
        args.extend(["--target", target_group])
    if plc_name:
        args.extend(["--plc", plc_name])
    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=lib, action="copy_from_library")
        )
    return result


def get_tags_via_openness_cli(
    *,
    project_path: str | Path = "",
    table_name: str = "",
    plc_name: str = "",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Inspect and list PLC tags from a TagTable via ``--cli get-tags``."""
    args = ["get-tags"]
    if project_path:
        project = Path(project_path).expanduser().resolve()
        args.extend(["--project", str(project)])
    if table_name:
        args.extend(["--table", table_name])
    if plc_name:
        args.extend(["--plc", plc_name])
    result = openness_cli(*args, timeout_s=timeout_s)
    if not result.get("ok"):
        raise RuntimeError(
            format_openness_failure(result, project_path=Path(project_path) if project_path else None, action="get_tags")
        )
    return result


# ---------------------------------------------------------------------------
# WP-02 / P0-G：SessionServer 会话入口（批次 2 增量回写真机地基）
#
# 纯新增：Greenfield 迭代路径从「每次 create-project」改为「SessionServer
# /open 一次并保持会话」。这两个函数只走现有 HTTP 路由 /open 与 /close，
# 不调用 create-project / archive-project / close-project CLI 命令、不新建项目。
# 供 tia_delivery.SessionModeTiaPort 复用；不改 C# 源码、不改 FastWriteback.cs。
# ---------------------------------------------------------------------------


def open_session_project_via_openness_cli(
    project_path: str | Path, *, plc_name: str = ""
) -> dict[str, Any]:
    """会话模式：POST /open 打开既有项目一次并保持常驻会话。

    与 ``generate_from_source_via_openness_cli`` / ``create-project`` 路径不同，
    本函数不新建、不归档、不重载项目；同一 HTTP 会话内后续增量复用该句柄。
    返回结构化 dict（含 route / session_mode / project_path），失败信号由上层
    ``openness_session.classify_session_failure`` 统一 fail-closed 归类。
    """
    from gateway.app.services.plc import openness_session

    resp = openness_session.ensure_project_open(str(project_path), plc_name=plc_name)
    out = dict(resp) if isinstance(resp, dict) else {"ok": False}
    out.setdefault("route", "/open")
    out["session_mode"] = True
    out["project_path"] = str(project_path)
    return out


def close_session_project_via_openness_cli() -> dict[str, Any]:
    """会话生命周期结束时显式 POST /close（三次增量过程中不调用）。"""
    from gateway.app.services.plc import openness_session

    return openness_session.close_project()

