"""Compatibility surface for PLC chat evidence helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from gateway.app.services.plc.chat_intents import (
    _normalize_fb_type_name,
    _strip_at_hint,
    _wants_block_explain,
)

from .evidence.blocks import (
    _block_assoc_lines,
    _block_meta,
    _block_io_lists,
    _block_network_titles,
    _call_relation_names,
    _match_block_query,
    _resolve_block_focus,
    _tag_io_for_block,
)
from .evidence.cards import (
    _describe_block_function,
    _explain_block_understanding,
    _format_block_runtime_explain,
)
from .evidence.instances import (
    _describe_instance_from_kg,
    _lookup_instance_entity,
)
from .evidence.nested import (
    _format_nested_fb_line,
    _format_typed_as_nest_lines,
    _typed_as_nest_payload,
)
from .evidence.optimize import (
    _block_risk_notes,
    _format_optimize_hints,
)
from .evidence.signal import _format_signal_trace
from .evidence.scl import (
    _expr_dict_to_scl,
    _folded_logic_lines,
    _folded_scl_dump,
    _format_block_scl_markdown,
    _format_scl_logic_block,
    _program_body_unavailable_reason,
    _purpose_from_fold,
    _resolve_block_scl_text,
    _scl_from_export_package,
    _scl_from_ir_translator,
)
from .evidence.shared import (
    _join_capped,
    _network_titles_from_scl,
    logger,
)

__all__ = [
    "Any",
    "Path",
    "re",
    "logger",
    "_block_assoc_lines",
    "_block_io_lists",
    "_block_meta",
    "_block_network_titles",
    "_block_risk_notes",
    "_call_relation_names",
    "_describe_block_function",
    "_describe_instance_from_kg",
    "_expr_dict_to_scl",
    "_explain_block_understanding",
    "_folded_logic_lines",
    "_folded_scl_dump",
    "_format_block_runtime_explain",
    "_format_block_scl_markdown",
    "_format_nested_fb_line",
    "_format_optimize_hints",
    "_format_signal_trace",
    "_format_scl_logic_block",
    "_format_typed_as_nest_lines",
    "_join_capped",
    "_lookup_instance_entity",
    "_match_block_query",
    "_network_titles_from_scl",
    "_normalize_fb_type_name",
    "_program_body_unavailable_reason",
    "_purpose_from_fold",
    "_resolve_block_focus",
    "_resolve_block_scl_text",
    "_scl_from_export_package",
    "_scl_from_ir_translator",
    "_strip_at_hint",
    "_tag_io_for_block",
    "_typed_as_nest_payload",
    "_wants_block_explain",
]
