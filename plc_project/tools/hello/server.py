"""CLI / in-process hello.echo (MCP stdio host removed)."""

from __future__ import annotations

import argparse
import json
import sys

from tools.hello.echo import hello_echo


def echo_tool(message: str = "hello", task_id: str | None = None) -> str:
    payload = hello_echo(message, task_id=task_id)
    return json.dumps(payload, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hello.echo (no MCP)")
    parser.add_argument("--message", default="hello")
    parser.add_argument("--task-id", default=None)
    args = parser.parse_args(argv)
    sys.stdout.write(echo_tool(args.message, task_id=args.task_id) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
