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

__all__ = [
    "CanvasState",
    "StandalonePlcEngine",
    "apply_canvas_patch",
    "attribute_compiler_errors",
    "audit_block_content",
    "create_empty_canvas",
    "execute_canvas_writeback",
    "extract_tag_table_content",
    "generate_canvas_autofix_patch",
    "parse_simaticml_block_content",
    "preview_canvas_scl",
    "run",
    "translate_simaticml_to_scl",
]


def __getattr__(name: str) -> Any:
    if name == "run":
        from agents.plc.node import run

        return run
    if name in {
        "StandalonePlcEngine",
        "translate_simaticml_to_scl",
        "parse_simaticml_block_content",
        "extract_tag_table_content",
        "audit_block_content",
    }:
        import plc_engine.standalone_api as sapi

        return getattr(sapi, name)
    if name in {
        "CanvasState",
        "create_empty_canvas",
        "apply_canvas_patch",
        "attribute_compiler_errors",
        "generate_canvas_autofix_patch",
    }:
        import plc_engine.canvas_model as cmod

        return getattr(cmod, name)
    if name in {"preview_canvas_scl", "execute_canvas_writeback"}:
        import plc_engine.canvas_tia_transpiler as ctrans

        return getattr(ctrans, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
