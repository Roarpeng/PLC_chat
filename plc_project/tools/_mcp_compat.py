"""No-op tool registry stub (MCP removed from product).

``tools.plc.server`` still uses ``@mcp.tool`` as a decorator for documentation
symmetry; the registry does nothing at runtime. Call the plain Python
functions directly from gateway / tests.
"""

from __future__ import annotations

from typing import Any, Callable


class _NoopMcp:
    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn

        return deco

    def run(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "MCP stdio host removed. Use gateway HTTP or call tools.plc.server functions directly."
        )


def create_mcp_server(name: str) -> Any:
    return _NoopMcp()
