"""MCP helper: FastMCP (older SDK) or MCPServer (mcp>=2)."""

from __future__ import annotations

from typing import Any


def create_mcp_server(name: str) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP(name)
    except ImportError:  # mcp 2.x
        from mcp.server.mcpserver import MCPServer

        return MCPServer(name)
