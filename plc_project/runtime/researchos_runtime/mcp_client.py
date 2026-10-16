"""MCP client wrapper — in-process hello/plc tools or stdio MCP servers."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from runtime.researchos_runtime.settings import RuntimeSettings, get_settings
from tools.hello.echo import hello_echo

logger = logging.getLogger("researchos.runtime.mcp")


class MCPClient:
    """Thin wrapper around MCP tools used by the runtime."""

    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = settings or get_settings()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        args = dict(arguments or {})
        if task_id and "task_id" not in args:
            args["task_id"] = task_id

        started = time.perf_counter()
        try:
            if name in ("hello.echo", "hello_echo", "echo"):
                result = self._call_hello_echo(args)
            elif name.startswith("plc."):
                result = self._call_plc(name, args)
            elif name.startswith("tia."):
                result = self._call_tia(name, args)
            else:
                raise ValueError(f"Unsupported MCP tool: {name}")
            duration_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "tool": name,
                "result": result,
                "duration_ms": duration_ms,
            }
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception("MCP tool %s failed", name)
            return {
                "ok": False,
                "tool": name,
                "error": str(exc),
                "duration_ms": duration_ms,
            }

    def _call_hello_echo(self, args: dict[str, Any]) -> dict[str, Any]:
        mode = (self.settings.mcp_hello_mode or "inprocess").lower()
        message = str(args.get("message", "hello"))
        task_id = args.get("task_id")
        if mode == "stdio":
            return self._call_hello_stdio(message=message, task_id=task_id)
        return hello_echo(message, task_id=task_id)

    def _call_plc(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch plc.* tools to the in-process mcp-plc implementation."""
        from tools.plc import server as plc_server

        args = {k: v for k, v in args.items() if k != "task_id"}
        dispatch = {
            "plc.vendors.list": plc_server.plc_vendors_list,
            "plc.manual.search": plc_server.plc_manual_search,
            "plc.manual.get": plc_server.plc_manual_get,
            "plc.alarm.explain": plc_server.plc_alarm_explain,
            "plc.tia.analyze": plc_server.plc_tia_analyze,
            "plc.tia.ingest": plc_server.plc_tia_ingest,
            "plc.project.analyze": plc_server.plc_project_analyze,
            "plc.program.download": plc_server.plc_program_download,
            "plc.program.upload_suggest": plc_server.plc_program_upload_suggest,
        }
        fn = dispatch.get(name)
        if fn is None:
            raise ValueError(f"Unsupported PLC tool: {name}")
        return fn(**args)

    def _call_tia(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch tia.* via Siemens Openness one-shot CLI (no MCP stdio session)."""
        from agents.plc.tia.openness_cli import openness_cli

        args = {k: v for k, v in args.items() if k != "task_id"}
        if name == "tia.get_status":
            return openness_cli("status", timeout_s=60)

        if name == "tia.open_project":
            project = str(args.get("project_path") or args.get("project") or "")
            if not project:
                return {
                    "ok": False,
                    "error": {"code": "invalid_argument", "message": "project_path is required"},
                }
            cli_args = ["open-project", "--project", project]
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.list_blocks":
            project = str(args.get("project_path") or args.get("project") or "")
            if not project:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "project_path is required (one-shot Openness CLI)",
                    },
                }
            cli_args = ["list-blocks", "--project", project]
            if args.get("type"):
                cli_args.extend(["--type", str(args["type"])])
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.export_block":
            project = str(args.get("project_path") or args.get("project") or "")
            block = str(args.get("block_name") or args.get("block") or "")
            if not project or not block:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "project_path and block_name are required",
                    },
                }
            cli_args = ["export-block", "--project", project, "--block", block]
            if args.get("export_path") or args.get("out"):
                cli_args.extend(["--out", str(args.get("export_path") or args.get("out"))])
            if args.get("type"):
                cli_args.extend(["--type", str(args["type"])])
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.close_project":
            project = str(args.get("project_path") or args.get("project") or "")
            if not project:
                return {
                    "ok": False,
                    "error": {"code": "invalid_argument", "message": "project_path is required"},
                }
            cli_args = ["close-project", "--project", project]
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.export_project":
            project = str(args.get("project_path") or args.get("project") or "")
            export_dir = str(args.get("export_dir") or "")
            if not project or not export_dir:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "project_path and export_dir are required",
                    },
                }
            cli_args = [
                "export-project",
                "--project",
                project,
                "--export-dir",
                export_dir,
            ]
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            if args.get("tia_version") or args.get("version"):
                cli_args.extend(
                    ["--version", str(args.get("tia_version") or args.get("version"))]
                )
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.archive_project":
            project = str(args.get("project_path") or args.get("project") or "")
            out_dir = str(args.get("out_dir") or args.get("outDir") or "")
            if not project or not out_dir:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "project_path and out_dir are required",
                    },
                }
            cli_args = [
                "archive-project",
                "--project",
                project,
                "--out-dir",
                out_dir,
            ]
            if args.get("name"):
                cli_args.extend(["--name", str(args["name"])])
            if args.get("tia_version") or args.get("version"):
                cli_args.extend(
                    ["--version", str(args.get("tia_version") or args.get("version"))]
                )
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.import_xml":
            project = str(args.get("project_path") or args.get("project") or "")
            xml = str(args.get("xml_path") or args.get("xml") or "")
            if not project or not xml:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "project_path and xml_path are required",
                    },
                }
            cli_args = ["import-xml", "--project", project, "--xml", xml]
            if args.get("kind"):
                cli_args.extend(["--kind", str(args["kind"])])
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            if args.get("overwrite") is False:
                cli_args.append("--no-overwrite")
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.generate_source_from_block":
            project = str(args.get("project_path") or args.get("project") or "")
            block = str(args.get("block_name") or args.get("block") or "")
            if not project or not block:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "project_path and block_name are required",
                    },
                }
            cli_args = [
                "generate-source-from-block",
                "--project",
                project,
                "--block",
                block,
            ]
            if args.get("source_path") or args.get("out"):
                cli_args.extend(["--out", str(args.get("source_path") or args.get("out"))])
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.retrieve_project":
            archive = str(args.get("archive_path") or args.get("archive") or "")
            out_dir = str(args.get("out_dir") or args.get("outDir") or "")
            if not archive or not out_dir:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "archive_path and out_dir are required",
                    },
                }
            cli_args = ["retrieve", "--archive", archive, "--out-dir", out_dir]
            if args.get("plc_name"):
                cli_args.extend(["--plc", str(args["plc_name"])])
            return openness_cli(*cli_args, timeout_s=int(args.get("timeout_s") or 600))

        if name == "tia.create_project":
            directory = str(args.get("target_directory") or args.get("dir") or "")
            pname = str(args.get("project_name") or args.get("name") or "")
            if not directory or not pname:
                return {
                    "ok": False,
                    "error": {
                        "code": "invalid_argument",
                        "message": "target_directory and project_name are required",
                    },
                }
            return openness_cli(
                "create-project",
                "--dir",
                directory,
                "--name",
                pname,
                timeout_s=int(args.get("timeout_s") or 600),
            )

        return {
            "ok": False,
            "error": {
                "code": "unsupported_tia_tool",
                "message": (
                    f"{name} is not mapped to the Openness CLI. "
                    "Use tia.export_project / plc.tia.ingest / gateway canvas import."
                ),
            },
        }

def _call_hello_stdio(self, *, message: str, task_id: str | None) -> dict[str, Any]:
        """Invoke tools/hello CLI (MCP package removed — subprocess JSON)."""
        import subprocess

        root = Path(__file__).resolve().parents[2]
        server_script = root / "tools" / "hello" / "server.py"
        cmd = [sys.executable, str(server_script), "--message", message]
        if task_id:
            cmd.extend(["--task-id", str(task_id)])
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        raw = (proc.stdout or "").strip() or (proc.stderr or "").strip() or "{}"
        try:
            return json.loads(raw.splitlines()[-1])
        except json.JSONDecodeError:
            return {"ok": proc.returncode == 0, "raw": raw}


_default_client: MCPClient | None = None


def get_mcp_client(settings: RuntimeSettings | None = None) -> MCPClient:
    global _default_client
    if settings is not None:
        return MCPClient(settings)
    if _default_client is None:
        _default_client = MCPClient()
    return _default_client
