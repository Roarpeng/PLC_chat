"""PLC Agent (Phase 5 industrial extension).

Read-only engineering assistant: searches PLC manuals via the
`industrial.connectors.plc_docs` connector and produces analysis blocks
(manual coverage, change advice, safety checks). Never writes to field
devices — see docs/industrial/02-plc-and-automation.md.

Keep this package import-side-effect free: Gateway PLC ingest must not
eagerly pull ``agents.plc.node`` / ``TaskState`` (langchain_core).
"""

from __future__ import annotations

from typing import Any

__all__ = ["run"]


def __getattr__(name: str) -> Any:
    if name == "run":
        from agents.plc.node import run

        return run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
