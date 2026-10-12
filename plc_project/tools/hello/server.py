"""MCP stdio server exposing hello.echo."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from tools.hello.echo import hello_echo

server = MCPServer("researchos-hello", version="0.1.0")


@server.tool(name="hello.echo", description="Echo a message as structured JSON (Phase 2 demo tool).")
def echo_tool(message: str = "hello", task_id: str | None = None) -> str:
    payload = hello_echo(message, task_id=task_id)
    return json.dumps(payload, ensure_ascii=False)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
