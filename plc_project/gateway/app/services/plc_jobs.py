"""Public PLC job service facade.

Routers, chat services, and focused tests import from this module.  The ``plc``
package holds the implementation boundaries while this facade keeps those
imports and test seams stable.
"""

from __future__ import annotations

import logging
import io
import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gateway.app.config import Settings, get_settings
from gateway.app.services import store as mem

from gateway.app.services.plc import changesets
from gateway.app.services.plc.changesets import (
    confirm_job_writeback,
    propose_job_optimize,
)
from gateway.app.services.plc.chat_evidence import (
    _block_assoc_lines,
    _block_io_lists,
    _block_meta,
    _block_network_titles,
    _block_risk_notes,
    _call_relation_names,
    _describe_block_function,
    _describe_instance_from_kg,
    _expr_dict_to_scl,
    _explain_block_understanding,
    _folded_logic_lines,
    _folded_scl_dump,
    _format_block_runtime_explain,
    _format_block_scl_markdown,
    _format_optimize_hints,
    _format_signal_trace,
    _format_scl_logic_block,
    _format_nested_fb_line,
    _format_typed_as_nest_lines,
    _join_capped,
    _lookup_instance_entity,
    _match_block_query,
    _network_titles_from_scl,
    _normalize_fb_type_name,
    _program_body_unavailable_reason,
    _purpose_from_fold,
    _resolve_block_focus,
    _resolve_block_scl_text,
    _scl_from_export_package,
    _scl_from_ir_translator,
    _strip_at_hint,
    _tag_io_for_block,
    _typed_as_nest_payload,
)
from gateway.app.services.plc.chat_intents import (
    _wants_brief_card,
    _wants_block_explain,
    _wants_confirm_writeback,
    _wants_full_scl,
    _wants_nest_chains,
    _wants_node_analyze,
    _wants_optimize_hints,
    _wants_optimize_logic,
    _wants_optimize_scl,
    _wants_project_interview,
    _wants_signal_trace,
    _wants_understand_logic,
)
from gateway.app.services.plc.chat_router import answer_block_chat as _answer_block_chat
from gateway.app.services.plc.brief import build_project_brief
from gateway.app.services.plc.device_cards import (
    build_device_cards,
    clear_device_card_annotation,
    find_card_by_symbol,
    get_device_card,
    list_device_cards,
    set_device_card_annotation,
)
from gateway.app.services.plc.project_brief import (
    device_sensor_summary_section,
)
from gateway.app.services.plc.ingest import (
    _annotate_block_nest_depth,
    _block_list,
    _collect_source_xmls,
    retry_structure_export,
    run_ingest_job,
)
from gateway.app.services.plc.job_store import (
    _append_progress,
    _finish_progress,
    _job_id,
    _now,
    _start_progress,
    analyze_job,
    append_chat_turn,
    build_export_zip,
    create_job_record,
    delete_job,
    get_job,
    list_jobs,
    query_job_graph,
)
from gateway.app.services.plc.logic_graph import (
    _is_ob_props,
    _logic_graph_from_kg,
    refresh_logic_graph,
)
from gateway.app.services.plc.paths import (
    ALLOWED_UPLOAD_SUFFIXES,
    _allowlist_roots,
    _safe_extract_zip,
    resolve_allowed_path,
    save_upload,
)
from gateway.app.services.plc.writeback_views import (
    _excerpt_optimize_plan,
    _format_writeback_recap,
    _openness_skip_reason,
)

logger = logging.getLogger("researchos.gateway.plc")

__all__ = [
    "ALLOWED_UPLOAD_SUFFIXES",
    "Any",
    "Path",
    "Settings",
    "datetime",
    "get_settings",
    "io",
    "json",
    "mem",
    "_allowlist_roots",
    "_annotate_block_nest_depth",
    "_append_progress",
    "_block_assoc_lines",
    "_block_io_lists",
    "_block_list",
    "_block_meta",
    "_block_network_titles",
    "_block_risk_notes",
    "_call_relation_names",
    "_collect_source_xmls",
    "_describe_block_function",
    "_describe_instance_from_kg",
    "_excerpt_optimize_plan",
    "_expr_dict_to_scl",
    "_explain_block_understanding",
    "_finish_progress",
    "_folded_logic_lines",
    "_folded_scl_dump",
    "_format_block_runtime_explain",
    "_format_block_scl_markdown",
    "_format_confirm_writeback_chat",
    "_format_nested_fb_line",
    "_format_optimize_hints",
    "_format_optimize_scl_chat",
    "_format_signal_trace",
    "_format_scl_logic_block",
    "_format_typed_as_nest_lines",
    "_format_writeback_recap",
    "_is_ob_props",
    "_job_id",
    "_join_capped",
    "_logic_graph_from_kg",
    "_lookup_instance_entity",
    "_match_block_query",
    "_network_titles_from_scl",
    "_normalize_fb_type_name",
    "_now",
    "_openness_skip_reason",
    "_program_body_unavailable_reason",
    "_purpose_from_fold",
    "_resolve_block_focus",
    "_resolve_block_scl_text",
    "_safe_extract_zip",
    "_scl_from_export_package",
    "_scl_from_ir_translator",
    "_start_progress",
    "_strip_at_hint",
    "_tag_io_for_block",
    "_typed_as_nest_payload",
    "_wants_brief_card",
    "_wants_block_explain",
    "_wants_confirm_writeback",
    "_wants_full_scl",
    "_wants_nest_chains",
    "_wants_node_analyze",
    "_wants_optimize_hints",
    "_wants_optimize_logic",
    "_wants_optimize_scl",
    "_wants_project_interview",
    "_wants_signal_trace",
    "_wants_understand_logic",
    "analyze_job",
    "answer_block_chat",
    "build_project_brief",
    "append_chat_turn",
    "build_device_cards",
    "build_export_zip",
    "build_project_brief",
    "clear_device_card_annotation",
    "device_sensor_summary_section",
    "find_card_by_symbol",
    "get_device_card",
    "list_device_cards",
    "set_device_card_annotation",
    "confirm_job_writeback",
    "create_job_record",
    "delete_job",
    "get_job",
    "list_jobs",
    "logger",
    "propose_job_changeset",
    "propose_job_optimize",
    "query_job_graph",
    "refresh_logic_graph",
    "resolve_allowed_path",
    "re",
    "retry_structure_export",
    "run_ingest_job",
    "save_upload",
    "tempfile",
    "timezone",
    "uuid4",
    "zipfile",
]


def propose_job_changeset(
    job: dict[str, Any],
    message: str,
    block_name: str | None = None,
) -> dict[str, Any]:
    return changesets.propose_job_changeset(
        job,
        message,
        block_name,
        propose_optimize=propose_job_optimize,
    )


def _format_confirm_writeback_chat(
    job: dict[str, Any],
    block_name: str | None,
    *,
    message: str = "",
) -> str:
    from gateway.app.services.plc import writeback_views

    return writeback_views._format_confirm_writeback_chat(
        job,
        block_name,
        message=message,
        confirm_writeback=confirm_job_writeback,
    )


def _format_optimize_scl_chat(
    job: dict[str, Any],
    block_name: str | None,
    *,
    message: str = "",
) -> str:
    from gateway.app.services.plc import writeback_views

    return writeback_views._format_optimize_scl_chat(
        job,
        block_name,
        message=message,
        propose_optimize=propose_job_optimize,
    )


def answer_block_chat(job: dict[str, Any], message: str, block_name: str | None) -> str:
    from gateway.app.services.plc.citations import finalize_grounded_answer

    content = _answer_block_chat(
        job,
        message,
        block_name,
        confirm_writeback=confirm_job_writeback,
        propose_optimize=propose_job_optimize,
    )
    return finalize_grounded_answer(job, message, block_name, content)
