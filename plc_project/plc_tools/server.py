"""mcp-plc server — read-only PLC manual tools (Phase 5 industrial).

Aligned with docs/industrial/02-plc-and-automation.md:

- `plc.manual.search` / `plc.manual.get` / `plc.vendors.list` — open
- `plc.alarm.explain` — open; every explanation carries a manual citation
- `plc.st.parse` / `plc.ld.summarize` / `plc.diff.routines` — open (offline analysis)
- `plc.opcua.read` — disabled by default (no endpoint configured)
- `plc.program.download` — disabled by default (high risk, never on)
- `plc.program.upload_suggest` — disabled unless explicitly flagged

The server depends on the `PlcDocsConnector` protocol, not a vendor SDK.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from industrial.connectors.plc_docs import (
    FakePlcDocsConnector,
    KnowledgeBackedPlcDocsConnector,
)
from tools._mcp_compat import create_mcp_server

mcp = create_mcp_server("plc")


def _make_connector() -> Any:
    """PLC docs connector selected by ``PLC_DOCS_CONNECTOR`` (knowledge|fake).

    Defaults to ``knowledge`` (KB-first); ``fake`` restores the legacy catalog-only
    connector.
    """
    mode = os.getenv("PLC_DOCS_CONNECTOR", "knowledge").strip().lower()
    if mode == "fake":
        return FakePlcDocsConnector()
    return KnowledgeBackedPlcDocsConnector()


_connector = _make_connector()

#: Sample alarm knowledge base — explanations must always cite a manual.
ALARM_CATALOG: dict[str, dict[str, Any]] = {
    "E2304": {
        "description": "Packaging line servo drive communication fault",
        "candidates": [
            "PROFINET/EtherNet/IP link instability on the drive segment",
            "Drive firmware mismatch with controller configuration",
            "Cable/shielding degradation near high-power lines",
        ],
        "manual_ref": "plc_siemens_s7",
    },
    "F0002": {
        "description": "DC bus overvoltage",
        "candidates": [
            "Regenerative energy without braking resistor",
            "Deceleration ramp too short for load inertia",
        ],
        "manual_ref": "plc_beck_compactlogix",
    },
}


def _alarm_kb_passages(code: str, info: dict[str, Any]) -> list[dict[str, Any]]:
    """Knowledge-layer passages relevant to an alarm (empty when KB unavailable)."""
    fn = getattr(_connector, "kb_passages", None)
    if not callable(fn):
        return []
    parts = [code, str(info.get("description") or "")]
    parts.extend(str(c) for c in (info.get("candidates") or []))
    return list(fn(" ".join(parts)) or [])


def _flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@mcp.tool(name="plc.vendors.list")
def plc_vendors_list() -> dict[str, Any]:
    """List PLC manual vendors available in the connected catalog."""
    return {"ok": True, "readonly": True, "vendors": _connector.list_vendors()}


@mcp.tool(name="plc.manual.search")
def plc_manual_search(query: str, limit: int = 10) -> dict[str, Any]:
    """Search ingested PLC manuals (read-only)."""
    hits = _connector.search(query, limit=limit)
    return {
        "ok": True,
        "readonly": True,
        "count": len(hits),
        "results": [_connector.as_dict(e) for e in hits],
    }


@mcp.tool(name="plc.manual.get")
def plc_manual_get(doc_id: str) -> dict[str, Any]:
    """Fetch one PLC manual entry by id (read-only)."""
    entry = _connector.get(doc_id)
    if entry is None:
        return {"ok": False, "error": "not_found", "doc_id": doc_id}
    return {"ok": True, "readonly": True, "document": _connector.as_dict(entry)}


@mcp.tool(name="plc.alarm.explain")
def plc_alarm_explain(alarm_code: str) -> dict[str, Any]:
    """Explain an alarm code with candidate causes; citations required."""
    code = (alarm_code or "").strip().upper()
    info = ALARM_CATALOG.get(code)
    if info is None:
        return {
            "ok": False,
            "error": "unknown_alarm_code",
            "alarm_code": code,
            "hint": "No curated explanation; retrieve manuals via plc.manual.search.",
        }
    kb_passages = _alarm_kb_passages(code, info)
    manual = _connector.get(info["manual_ref"])
    citation = _connector.as_dict(manual) if manual else None
    payload: dict[str, Any] = {
        "ok": True,
        "readonly": True,
        "alarm_code": code,
        "description": info["description"],
        "candidate_causes": info["candidates"],
        "citation": citation,
        "disclaimer": "Advisory only; follow enterprise change management (MOC).",
    }
    if kb_passages:
        payload["kb_passages"] = kb_passages
    return payload


@mcp.tool(name="plc.tia.analyze")
def plc_tia_analyze(
    export_dir: str,
    project_name: str = "",
    publish_graph: bool = False,
) -> dict[str, Any]:
    """Analyze a TIA Portal Openness export folder -> KG + SCL (read-only).

    `export_dir` must contain SimaticML XML produced by Openness
    `PlcBlock.Export(...)` (see industrial/tia_adapter or tia-openness MCP).
    Returns the interpretation report, generated SCL sources and the
    knowledge graph; never writes to any TIA project.
    Set `publish_graph=true` to upsert PLC nodes into Neo4j/memory KG.
    """
    export_path = Path(export_dir).expanduser()
    if not export_path.is_dir():
        return {
            "ok": False,
            "error": "export_dir_not_found",
            "export_dir": str(export_dir),
        }
    from agents.plc.tia import analyze_tia_exports

    result = analyze_tia_exports(
        str(export_path),
        project_name=project_name,
        publish_graph=publish_graph,
    )
    project = result["project"]
    payload: dict[str, Any] = {
        "ok": True,
        "readonly": True,
        "project_name": project.name,
        "summary": project.summary(),
        "extraction_notes": project.extraction_notes,
        "report": result["report"],
        "scl_sources": result["scl_sources"],
        "knowledge_graph": result["knowledge_graph"].to_json(),
        "conversion_report": result.get("conversion_report"),
    }
    if "graph_publish" in result:
        payload["graph_publish"] = result["graph_publish"]
    return payload


@mcp.tool(name="plc.tia.ingest")
def plc_tia_ingest(
    path: str,
    project_name: str = "",
    result_dir: str = "",
    publish_graph: bool = True,
    tia_version: str = "",
    plc_name: str = "",
) -> dict[str, Any]:
    """Bridge: XML | .apxx | export dir → Parser → PLC-IR → KG → (Neo4j) → Agent payload.

    Preferred Milestone-1 follow-on tool after `tia.export_block` / `tia.export_project`.
    """
    target = Path(path).expanduser()
    if not target.exists():
        return {"ok": False, "error": "path_not_found", "path": str(path)}
    from agents.plc.tia import analyze_plc_project

    try:
        result = analyze_plc_project(
            str(target),
            project_name=project_name,
            result_dir=result_dir,
            tia_version=tia_version,
            plc_name=plc_name,
            publish_graph=publish_graph,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "error": "not_found", "message": str(exc)}
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "error": "ingest_failed", "message": str(exc)}

    project = result["project"]
    return {
        "ok": True,
        "readonly": True,
        "pipeline": "XML→PLC-IR→KG→Neo4j→Agent",
        "project_name": project.name,
        "import": result.get("import"),
        "result_dir": result.get("result_dir") or "",
        "summary": project.summary(),
        "conversion_report": result.get("conversion_report"),
        "report": result["report"],
        "scl_sources": result["scl_sources"],
        "knowledge_graph": result["knowledge_graph"].to_json(),
        "graph_publish": result.get("graph_publish"),
        "extraction_notes": project.extraction_notes,
    }


@mcp.tool(name="plc.project.analyze")
def plc_project_analyze(
    path: str,
    result_dir: str = "",
    project_name: str = "",
    tia_version: str = "",
    plc_name: str = "",
    export_dir: str = "",
    publish_graph: bool = False,
) -> dict[str, Any]:
    """One-shot Offline Analyzer: .apxx or export folder -> SCL result package.

    For `.ap17`/`.ap18`/`.ap19`/`.ap20`, runs Openness export then offline
    parse/understand/convert. For an export directory, skips Openness.
    Optionally writes `ResearchOS_PLC_Result` layout under `result_dir`.
    """
    target = Path(path).expanduser()
    if not target.exists():
        return {"ok": False, "error": "path_not_found", "path": str(path)}
    from agents.plc.tia import analyze_plc_project

    try:
        result = analyze_plc_project(
            str(target),
            project_name=project_name,
            result_dir=result_dir,
            export_dir=export_dir,
            tia_version=tia_version,
            plc_name=plc_name,
            publish_graph=publish_graph,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "error": "not_found", "message": str(exc)}
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "error": "analyze_failed", "message": str(exc)}

    project = result["project"]
    return {
        "ok": True,
        "readonly": True,
        "project_name": project.name,
        "import": result.get("import"),
        "result_dir": result.get("result_dir") or "",
        "summary": project.summary(),
        "conversion_report": result.get("conversion_report"),
        "report": result["report"],
        "scl_sources": result["scl_sources"],
        "knowledge_graph": result["knowledge_graph"].to_json(),
        "graph_publish": result.get("graph_publish"),
        "extraction_notes": project.extraction_notes,
    }


@mcp.tool(name="plc.program.download")
def plc_program_download(**kwargs: Any) -> dict[str, Any]:
    """HIGH RISK — disabled by default and never auto-enabled."""
    if not _flag_enabled("RESEARCHOS_PLC_ALLOW_DOWNLOAD"):
        return {
            "ok": False,
            "error": "forbidden",
            "code": "PLC_DOWNLOAD_DISABLED",
            "message": (
                "Downloading programs to PLCs is disabled by default. "
                "ResearchOS output is advisory; apply changes via your "
                "change management process."
            ),
        }
    # Even with the flag, we intentionally do not implement device writes here.
    return {
        "ok": False,
        "error": "not_implemented",
        "code": "PLC_DOWNLOAD_NOT_IMPLEMENTED",
        "message": "Device write paths are intentionally absent from this stub.",
    }


@mcp.tool(name="plc.program.upload_suggest")
def plc_program_upload_suggest(**kwargs: Any) -> dict[str, Any]:
    """Generate a downloadable artifact for manual engineer import (flagged)."""
    if not _flag_enabled("RESEARCHOS_PLC_ALLOW_UPLOAD_SUGGEST"):
        return {
            "ok": False,
            "error": "forbidden",
            "code": "PLC_UPLOAD_SUGGEST_DISABLED",
            "message": "Disabled by default; enable explicitly and approve via HITL.",
        }
    return {
        "ok": False,
        "error": "not_implemented",
        "code": "PLC_UPLOAD_SUGGEST_NOT_IMPLEMENTED",
        "message": "Artifact generation is not implemented in this stub.",
    }


# ---------------------------------------------------------------------------
# plc.st.parse — offline SCL/ST text analysis (reuses scl.explain_scl_statement)
# ---------------------------------------------------------------------------

_LOCAL_SYMBOL_RE = re.compile(r"#\w+(?:\.\w+)*")
_GLOBAL_SYMBOL_RE = re.compile(r'"[^"]+"(?:\.\w+)*')
_ABSOLUTE_SYMBOL_RE = re.compile(r"%[A-Za-z0-9_.]+")
_BLOCK_COMMENT_RE = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_DECL_RE = re.compile(
    r"^(?:VAR_IN_OUT|VAR_INPUT|VAR_OUTPUT|VAR_TEMP|VAR_CONSTANT|END_VAR|BEGIN|"
    r"FUNCTION_BLOCK|ORGANIZATION_BLOCK|DATA_BLOCK|FUNCTION|"
    r"END_FUNCTION_BLOCK|END_ORGANIZATION_BLOCK|END_DATA_BLOCK|END_FUNCTION|"
    r"END_TYPE|TYPE|STRUCT|END_STRUCT|CONSTANT|VAR)\b",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(
    r"^(?:END_WHILE|END_REPEAT|END_FOR|END_IF|END_CASE|ELSIF|ELSE|"
    r"REPEAT|UNTIL|WHILE|CONTINUE|RETURN|GOTO|JMP|FOR|CASE|IF)\b",
    re.IGNORECASE,
)
_CALL_STMT_RE = re.compile(
    r'^\s*(?:#\w+(?:\.\w+)*|"[^"]+"(?:\.\w+)*|[A-Za-z_]\w*)(?:\.\w+)*\s*\(.*\)\s*$'
)

#: Edge types compared by plc.diff.routines (routine-level logic, not structure).
_ROUTINE_EDGE_TYPES = {"CALLS", "USES", "INSTANCE_OF", "TYPED_AS", "READS", "WRITES", "NEXT"}


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub("", text or "")
    return _LINE_COMMENT_RE.sub("", text)


def _split_statements(text: str) -> list[str]:
    cleaned = _strip_comments(text)
    return [part.strip() for part in re.split(r"[;\r\n]+", cleaned) if part.strip()]


def _extract_symbols(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    found.extend((name, "local") for name in _LOCAL_SYMBOL_RE.findall(text))
    found.extend((name, "global") for name in _GLOBAL_SYMBOL_RE.findall(text))
    found.extend((name, "absolute") for name in _ABSOLUTE_SYMBOL_RE.findall(text))
    return found


def _classify_statement(text: str) -> str:
    if _DECL_RE.match(text):
        return "declaration"
    if _CONTROL_RE.match(text):
        return "control"
    if _CALL_STMT_RE.match(text):
        return "call"
    if ":=" in text:
        return "assignment"
    return "other"


def _write_regions(text: str) -> list[str]:
    """Text spans that write symbols: assignment LHS and call ``=>`` outputs."""
    regions: list[str] = []
    if ":=" in text:
        regions.append(text.split(":=", 1)[0])
    for match in re.finditer(r"(?:^|,)\s*\w+\s*=>\s*([^,()]+)", text):
        regions.append(match.group(1))
    return regions


def _build_symbol_table(statements: list[str]) -> list[dict[str, Any]]:
    ref_counts: dict[str, int] = {}
    write_counts: dict[str, int] = {}
    kinds: dict[str, str] = {}
    for text in statements:
        for name, kind in _extract_symbols(text):
            ref_counts[name] = ref_counts.get(name, 0) + 1
            kinds.setdefault(name, kind)
        for region in _write_regions(text):
            for name, _kind in _extract_symbols(region):
                write_counts[name] = write_counts.get(name, 0) + 1
    out: list[dict[str, Any]] = []
    for name in sorted(ref_counts):
        writes = write_counts.get(name, 0)
        roles: list[str] = []
        if writes > 0:
            roles.append("write")
        if ref_counts[name] > writes:
            roles.append("read")
        out.append(
            {
                "name": name,
                "kind": kinds[name],
                "references": ref_counts[name],
                "writes": writes,
                "roles": roles,
            }
        )
    return out


def _pair_check(
    diags: list[dict[str, str]],
    text: str,
    open_re: str,
    close_re: str,
    open_name: str,
    close_name: str,
) -> None:
    opened = len(re.findall(open_re, text, flags=re.IGNORECASE))
    closed = len(re.findall(close_re, text, flags=re.IGNORECASE))
    if opened == closed:
        return
    level = "error" if opened > closed else "warning"
    diags.append(
        {
            "level": level,
            "code": f"unbalanced_{open_name.lower()}",
            "message": f"{open_name}/{close_name} mismatch ({opened} open vs {closed} close).",
        }
    )


def _diagnose(text: str) -> list[dict[str, str]]:
    diags: list[dict[str, str]] = []
    stripped = _strip_comments(text)
    if not stripped.strip():
        diags.append(
            {"level": "warning", "code": "empty_source", "message": "No SCL/ST content after removing comments."}
        )
        return diags
    if stripped.count("(") != stripped.count(")"):
        diags.append(
            {"level": "error", "code": "unbalanced_parens", "message": "Mismatched parentheses."}
        )
    if stripped.count("[") != stripped.count("]"):
        diags.append(
            {"level": "error", "code": "unbalanced_brackets", "message": "Mismatched square brackets."}
        )
    if stripped.count("'") % 2 != 0:
        diags.append(
            {"level": "error", "code": "unterminated_string", "message": "Unterminated string literal."}
        )
    _pair_check(diags, stripped, r"\bIF\b", r"\bEND_IF\b", "IF", "END_IF")
    _pair_check(diags, stripped, r"\bCASE\b", r"\bEND_CASE\b", "CASE", "END_CASE")
    _pair_check(diags, stripped, r"\bFOR\b", r"\bEND_FOR\b", "FOR", "END_FOR")
    _pair_check(diags, stripped, r"\bWHILE\b", r"\bEND_WHILE\b", "WHILE", "END_WHILE")
    _pair_check(diags, stripped, r"\bREPEAT\b", r"\bEND_REPEAT\b", "REPEAT", "END_REPEAT")
    return diags


@mcp.tool(name="plc.st.parse")
def plc_st_parse(source_text: str) -> dict[str, Any]:
    """Parse an SCL/ST text fragment into symbols, statements and diagnostics (read-only)."""
    from agents.plc.tia.scl import explain_scl_statement

    raw_statements = _split_statements(source_text or "")
    statements: list[dict[str, Any]] = []
    for idx, chunk in enumerate(raw_statements, start=1):
        statements.append(
            {
                "index": idx,
                "kind": _classify_statement(chunk),
                "text": chunk,
                "meaning": explain_scl_statement(chunk),
            }
        )
    return {
        "ok": True,
        "readonly": True,
        "language": "SCL/ST",
        "statements": statements,
        "symbols": _build_symbol_table(raw_statements),
        "diagnostics": _diagnose(source_text or ""),
    }


# ---------------------------------------------------------------------------
# plc.ld.summarize — folded per-network logic summary (flgnet_fold + stmt_to_scl)
# ---------------------------------------------------------------------------

def _summarize_block(block: Any) -> dict[str, Any]:
    from agents.plc.tia.flgnet_fold import fold_network, stmt_to_scl
    from agents.plc.tia.ir import Network

    networks: list[dict[str, Any]] = []
    for idx, net in enumerate(block.networks, start=1):
        folded = fold_network(net)
        networks.append(
            {
                "title": (net.title or "").strip() or f"Network {idx}",
                "statements": [stmt_to_scl(statement) for statement in folded.statements],
                "unresolved_parts": list(folded.unresolved_parts),
            }
        )
    if not block.networks and (block.source_text or "").strip():
        pseudo = Network(id="source", title="(SCL body)")
        pseudo.source_text = block.source_text
        folded = fold_network(pseudo)
        networks.append(
            {
                "title": "(SCL body)",
                "statements": [stmt_to_scl(statement) for statement in folded.statements],
                "unresolved_parts": list(folded.unresolved_parts),
            }
        )
    return {"block": block.name, "networks": networks}


@mcp.tool(name="plc.ld.summarize")
def plc_ld_summarize(path: str, block: str = "") -> dict[str, Any]:
    """Summarize folded logic per network for a block or TIA export directory (read-only)."""
    target = Path(path).expanduser()
    if not target.exists():
        return {"ok": False, "readonly": True, "error": "path_not_found", "path": str(path)}
    from agents.plc.tia.simaticml import parse_block_xml

    if target.is_file():
        parsed = parse_block_xml(target)
        if parsed is None:
            return {"ok": False, "readonly": True, "error": "block_not_found", "path": str(path)}
        return {"ok": True, "readonly": True, **_summarize_block(parsed)}

    from agents.plc.tia.simaticml import extract_project

    project = extract_project(str(target))
    if block:
        parsed = project.blocks.get(block)
        if parsed is None:
            return {"ok": False, "readonly": True, "error": "block_not_found", "block": block}
        return {"ok": True, "readonly": True, **_summarize_block(parsed)}
    blocks = [_summarize_block(project.blocks[name]) for name in sorted(project.blocks)]
    return {"ok": True, "readonly": True, "blocks": blocks}


# ---------------------------------------------------------------------------
# plc.diff.routines — edge set diff between two TIA export directories
# ---------------------------------------------------------------------------

@mcp.tool(name="plc.diff.routines")
def plc_diff_routines(dir_a: str, dir_b: str, limit: int = 64) -> dict[str, Any]:
    """Compare two TIA export dirs' knowledge graphs; returns added/removed edges (read-only)."""
    path_a = Path(dir_a).expanduser()
    path_b = Path(dir_b).expanduser()
    if not path_a.is_dir():
        return {"ok": False, "readonly": True, "error": "dir_a_not_found", "dir_a": str(dir_a)}
    if not path_b.is_dir():
        return {"ok": False, "readonly": True, "error": "dir_b_not_found", "dir_b": str(dir_b)}

    from agents.plc.tia.kg import build_knowledge_graph
    from agents.plc.tia.simaticml import extract_project

    def _routine_edges(dir_path: Path) -> set[tuple[str, str, str]]:
        project = extract_project(str(dir_path))
        kg = build_knowledge_graph(project)
        return {
            (edge.source, edge.target, edge.type)
            for edge in kg.edges
            if edge.type in _ROUTINE_EDGE_TYPES
        }

    edges_a = _routine_edges(path_a)
    edges_b = _routine_edges(path_b)
    added = sorted(edges_b - edges_a)
    removed = sorted(edges_a - edges_b)
    try:
        cap = max(0, int(limit))
    except (TypeError, ValueError):
        cap = 64

    def _fmt(key: tuple[str, str, str]) -> dict[str, str]:
        return {"source": key[0], "target": key[1], "type": key[2]}

    return {
        "ok": True,
        "readonly": True,
        "dir_a": str(path_a),
        "dir_b": str(path_b),
        "added": [_fmt(key) for key in added[:cap]],
        "removed": [_fmt(key) for key in removed[:cap]],
        "added_total": len(added),
        "removed_total": len(removed),
        "limit": cap,
        "truncated": {"added": len(added) > cap, "removed": len(removed) > cap},
    }


# ---------------------------------------------------------------------------
# plc.opcua.read — safe placeholder (never connects; read-only policy enforced)
# ---------------------------------------------------------------------------

@mcp.tool(name="plc.opcua.read")
def plc_opcua_read(node_id: str = "", **kwargs: Any) -> dict[str, Any]:
    """Read an OPC UA node value — disabled by default; never initiates a connection."""
    return {
        "ok": False,
        "readonly": True,
        "error": "opcua_read_disabled",
        "code": "OPCUA_READ_DISABLED",
        "node_id": node_id or "",
        "message": (
            "OPC UA read is disabled by default. ResearchOS enforces a read-only "
            "field-access policy and no OPC UA endpoint is configured in this "
            "workspace. No network connection is initiated."
        ),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
