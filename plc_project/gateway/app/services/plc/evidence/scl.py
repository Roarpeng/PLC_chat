"""Folded logic rendering and SCL source resolution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .blocks import _block_meta
from .shared import logger

__all__ = [
    "_expr_dict_to_scl",
    "_folded_logic_lines",
    "_purpose_from_fold",
    "_format_scl_logic_block",
    "_program_body_unavailable_reason",
    "_folded_scl_dump",
    "_scl_from_ir_translator",
    "_scl_from_export_package",
    "_resolve_block_scl_text",
    "_format_block_scl_markdown",
]


def _expr_dict_to_scl(value: object) -> str:
    """Render folded_logic JSON expression trees back to SCL-like text."""
    if value is None:
        return "?"
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if not isinstance(value, dict):
        return str(value)
    kind = str(value.get("type") or value.get("kind") or "").lower()
    if kind in {"literal", "lit"}:
        lit = value.get("value")
        if lit is True:
            return "TRUE"
        if lit is False:
            return "FALSE"
        return str(lit)
    if kind == "ref":
        acc = value.get("access")
        if isinstance(acc, str):
            return acc
        if isinstance(acc, dict):
            return str(acc.get("scl") or acc.get("name") or "?")
        return str(value.get("scl") or "?")
    if kind == "not":
        return f"NOT ({_expr_dict_to_scl(value.get('operand'))})"
    if kind == "and":
        ops = value.get("operands") or []
        if not ops:
            return "?"
        if len(ops) == 1:
            return _expr_dict_to_scl(ops[0])
        return " AND ".join(f"({_expr_dict_to_scl(o)})" for o in ops)
    if kind == "or":
        ops = value.get("operands") or []
        if not ops:
            return "?"
        if len(ops) == 1:
            return _expr_dict_to_scl(ops[0])
        return " OR ".join(f"({_expr_dict_to_scl(o)})" for o in ops)
    if kind == "compare":
        return f"({_expr_dict_to_scl(value.get('lhs'))} {value.get('op')} {_expr_dict_to_scl(value.get('rhs'))})"
    if kind == "arith":
        op = str(value.get("op") or "?").strip()
        operands = value.get("operands") or []
        if not isinstance(operands, list) or not operands:
            return f"(* arithmetic {op} *)"
        rendered = [_expr_dict_to_scl(item) for item in operands]
        if len(rendered) == 1:
            return f"{op}({rendered[0]})"
        return "(" + f" {op} ".join(rendered) + ")"
    if kind == "func":
        name = str(value.get("name") or value.get("function") or "FUNC").upper()
        args = value.get("args") or []
        if not isinstance(args, list):
            args = [args]
        return f"{name}(" + ", ".join(_expr_dict_to_scl(arg) for arg in args) + ")"
    if kind == "convert":
        source = _expr_dict_to_scl(value.get("source") or value.get("operand"))
        target_type = str(value.get("target_type") or value.get("to") or "").strip()
        return (f"{target_type}({source})" if target_type else f"CONVERT({source})")
    if value.get("scl"):
        return str(value["scl"])
    return str(value)


def _folded_logic_lines(job: dict[str, Any], block_name: str) -> list[str]:
    folded = job.get("folded_logic") or {}
    networks = folded.get(block_name) if isinstance(folded, dict) else None
    if not isinstance(networks, list):
        return []
    out: list[str] = []
    for net in networks[:8]:
        if not isinstance(net, dict):
            continue
        title = str(net.get("title") or net.get("network_id") or "")
        for stmt in (net.get("statements") or [])[:12]:
            if not isinstance(stmt, dict):
                continue
            target = str(stmt.get("target") or stmt.get("target_scl") or "?")
            expr = _expr_dict_to_scl(stmt.get("value"))
            kind = str(stmt.get("kind") or "coil")
            if kind == "call":
                line = target.rstrip(";")
            elif kind == "move":
                en = stmt.get("enable")
                if en:
                    line = f"IF {_expr_dict_to_scl(en)} THEN {target} := {expr}; END_IF"
                else:
                    line = f"{target} := {expr}"
            elif kind == "neg_coil":
                line = f"{target} := NOT ({expr})"
            elif kind == "set":
                line = f"IF {expr} THEN {target} := TRUE; END_IF"
            elif kind == "reset":
                line = f"IF {expr} THEN {target} := FALSE; END_IF"
            elif kind == "coil" and " AND " not in expr and " OR " not in expr and expr not in {
                "TRUE",
                "FALSE",
                "?",
            }:
                line = f"IF {expr} THEN {target} := TRUE; ELSE {target} := FALSE; END_IF"
            else:
                line = f"{target} := {expr}"
            out.append(f"[{title}] {line}" if title else line)
            if len(out) >= 16:
                return out
    return out


def _purpose_from_fold(folded: list[str], reads: list[str], writes: list[str]) -> str:
    """One-line purpose guess from folded assignments / IO (evidence only)."""
    if len(folded) == 1 and ":=" in folded[0]:
        return f"将 `{folded[0].split(':=', 1)[0].strip()}` 赋值为 `{folded[0].split(':=', 1)[1].strip()}`。"
    if len(folded) > 1:
        return f"含 {len(folded)} 条已折叠赋值/布尔表达式。"
    if writes and reads:
        return f"读取 {', '.join(reads[:8])}，写入 {', '.join(writes[:8])}。"
    if writes:
        return f"写入 {', '.join(writes[:8])}。"
    if reads:
        return f"读取 {', '.join(reads[:8])}。"
    return "当前无足够 READS/WRITES 或折叠逻辑可归纳作用。"


def _format_scl_logic_block(statements: list[str]) -> list[str]:
    """Render folded statements as commented SCL fragment (fallback)."""
    if not statements:
        return []
    try:
        from agents.plc.tia.scl import explain_scl_statement
    except Exception:  # noqa: BLE001
        explain_scl_statement = lambda _s: ""  # type: ignore[misc, assignment]
    body: list[str] = []
    last_title = ""
    for raw in statements:
        line = str(raw).strip()
        title = ""
        if line.startswith("[") and "]" in line:
            title, line = line[1:].split("]", 1)
            title = title.strip()
            line = line.strip()
        if not line:
            continue
        if title and title != last_title:
            body.append(f"// 网络：{title}")
            last_title = title
        if not line.endswith(";"):
            line = f"{line};"
        meaning = explain_scl_statement(line)
        if meaning:
            body.append(f"// {meaning}")
        body.append(line)
        if len(body) >= 28:
            break
    if not body:
        return []
    return ["主要逻辑（摘录，含中文说明）：", "```scl", *body, "```"]


def _program_body_unavailable_reason(block: dict[str, Any] | None) -> str:
    b = block or {}
    if b.get("interface_only"):
        return "程序体不可用（接口开放 / interface_only）"
    if b.get("protected"):
        return "程序体不可用（Know-how / 保护）"
    if b.get("body_available") is False:
        return "程序体不可用（未导出）"
    if b.get("is_safety"):
        return "程序体不可用（Safety / F 块不展开）"
    return "程序体不可用（无已导出 SCL / 无折叠语句）"


def _folded_scl_dump(job: dict[str, Any], block_name: str) -> str:
    """Whatever folded / TODO SCL we already have — not new Siemens semantics."""
    lines: list[str] = []
    folded = job.get("folded_logic") or {}
    nets = folded.get(block_name) if isinstance(folded, dict) else None
    if isinstance(nets, list):
        for net in nets:
            if not isinstance(net, dict):
                continue
            title = str(net.get("title") or net.get("network_id") or "").strip()
            if title:
                lines.append(f"// NETWORK: {title}")
            for stmt in net.get("statements") or []:
                if isinstance(stmt, dict):
                    target = str(stmt.get("target") or stmt.get("target_scl") or "").strip()
                    kind = str(stmt.get("kind") or "coil")
                    expr = _expr_dict_to_scl(stmt.get("value"))
                    if kind == "call":
                        piece = target.rstrip(";")
                    elif kind == "move":
                        en = stmt.get("enable")
                        if en:
                            piece = f"IF {_expr_dict_to_scl(en)} THEN {target} := {expr}; END_IF"
                        else:
                            piece = f"{target} := {expr}"
                    else:
                        piece = f"{target} := {expr}" if target else expr
                else:
                    piece = str(stmt).strip()
                if piece:
                    if not piece.endswith(";"):
                        piece = f"{piece};"
                    lines.append(piece)
            for todo in net.get("unresolved_parts") or []:
                text = str(todo).strip()
                if text:
                    lines.append(f"(* TODO: {text} *)")
    if lines:
        return "\n".join(lines)
    stmts = _folded_logic_lines(job, block_name)
    out: list[str] = []
    for raw in stmts:
        line = str(raw).strip()
        if line.startswith("[") and "]" in line:
            title, line = line[1:].split("]", 1)
            title = title.strip()
            line = line.strip()
            if title:
                out.append(f"// NETWORK: {title}")
        if line:
            if not line.endswith(";"):
                line = f"{line};"
            out.append(line)
    return "\n".join(out)


def _scl_from_ir_translator(job: dict[str, Any], block_name: str) -> str:
    """Reuse existing LAD/FBD→SCL translator when ingest skipped scl_sources."""
    try:
        from agents.plc.tia.flgnet_fold import attach_folded
        from agents.plc.tia.ir import PlcProject
        from agents.plc.tia.scl import translate_block_to_scl
        from agents.plc.tia.scl_rewrite import _load_ir_blocks, refuse_body_write_reason
    except Exception:  # noqa: BLE001
        return ""
    try:
        ir_blocks = _load_ir_blocks(job)
    except Exception:  # noqa: BLE001
        return ""
    block = ir_blocks.get(block_name)
    if block is None:
        return ""
    if refuse_body_write_reason(block):
        # Still try translate when networks exist — chat dump, not writeback.
        if not getattr(block, "networks", None) and not str(getattr(block, "source_text", "") or "").strip():
            return ""
    try:
        project = PlcProject(name=str(job.get("project_name") or "job"))
        project.add_block(block)
        attach_folded(project)
        block = project.blocks.get(block_name) or block
    except Exception:  # noqa: BLE001
        pass
    try:
        return str(translate_block_to_scl(block) or "").strip()
    except Exception:  # noqa: BLE001
        logger.warning("IR SCL translate failed for %s", block_name, exc_info=True)
        return ""


def _scl_from_export_package(job: dict[str, Any], block_name: str) -> str:
    export_dir = str(job.get("export_dir") or "").strip()
    if not export_dir:
        return ""
    try:
        from agents.plc.tia.package import _safe_filename
    except Exception:  # noqa: BLE001
        def _safe_filename(name: str) -> str:  # type: ignore[misc]
            return re.sub(r'[\\/:*?"<>|]', "_", name)

    path = Path(export_dir) / "converted_scl" / f"{_safe_filename(block_name)}.scl"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def _resolve_block_scl_text(job: dict[str, Any], block_name: str) -> tuple[str, str | None]:
    """SCL unit for chat: scl_sources → IR translator → package → folded dump.

    Second value is a one-line 程序体不可用 reason when the body is missing/TODO-only.
    """
    from agents.plc.tia.scl_rewrite import scl_is_untranslated

    stored = str((job.get("scl_sources") or {}).get(block_name) or "").strip()
    if stored:
        reason = "程序体不可用（仅 TODO / 占位）" if scl_is_untranslated(stored) else None
        return stored, reason

    ir_scl = _scl_from_ir_translator(job, block_name)
    if ir_scl:
        reason = "程序体不可用（仅 TODO / 占位）" if scl_is_untranslated(ir_scl) else None
        return ir_scl, reason

    pkg = _scl_from_export_package(job, block_name)
    if pkg:
        reason = "程序体不可用（仅 TODO / 占位）" if scl_is_untranslated(pkg) else None
        return pkg, reason

    folded = _folded_scl_dump(job, block_name).strip()
    meta = _block_meta(job, block_name)
    if folded:
        # Body excerpt exists even though ingest did not store a compilation unit.
        return folded, None
    return "(* 无已导出程序体 / 无折叠语句 *)", _program_body_unavailable_reason(meta)


def _format_block_scl_markdown(job: dict[str, Any], block_name: str) -> list[str]:
    """Full SCL fence — never an empty card after the title."""
    scl, reason = _resolve_block_scl_text(job, block_name)
    title = f"完整 SCL：{reason}" if reason else "完整 SCL："
    body = (scl or "(* 无已导出程序体 / 无折叠语句 *)").splitlines() or ["(* 无已导出程序体 / 无折叠语句 *)"]
    return [title, "```scl", *body, "```"]
