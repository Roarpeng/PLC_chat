"""Local SCL / canvas prechecks before sending work to TIA compiler."""

from __future__ import annotations

import re
from typing import Any

from plc_engine.canvas_model import CanvasState

_PAIR_KEYWORDS = [
    ("FUNCTION_BLOCK", "END_FUNCTION_BLOCK"),
    ("FUNCTION", "END_FUNCTION"),
    ("ORGANIZATION_BLOCK", "END_ORGANIZATION_BLOCK"),
    ("DATA_BLOCK", "END_DATA_BLOCK"),
    ("TYPE", "END_TYPE"),
    ("IF", "END_IF"),
    ("CASE", "END_CASE"),
    ("FOR", "END_FOR"),
    ("WHILE", "END_WHILE"),
    ("REPEAT", "END_REPEAT"),
    ("REGION", "END_REGION"),
]

_IDENT_RE = re.compile(r"\b#?([A-Za-z_][A-Za-z0-9_]*)\b")
_KEYWORD_SKIP = {
    "IF",
    "THEN",
    "ELSE",
    "ELSIF",
    "END_IF",
    "CASE",
    "OF",
    "END_CASE",
    "FOR",
    "TO",
    "BY",
    "DO",
    "END_FOR",
    "WHILE",
    "END_WHILE",
    "REPEAT",
    "UNTIL",
    "END_REPEAT",
    "TRUE",
    "FALSE",
    "AND",
    "OR",
    "XOR",
    "NOT",
    "MOD",
    "RETURN",
    "EXIT",
    "CONTINUE",
    "BEGIN",
    "VAR",
    "VAR_INPUT",
    "VAR_OUTPUT",
    "VAR_IN_OUT",
    "VAR_TEMP",
    "VAR_STAT",
    "END_VAR",
    "STRUCT",
    "END_STRUCT",
    "FUNCTION_BLOCK",
    "END_FUNCTION_BLOCK",
    "FUNCTION",
    "END_FUNCTION",
    "DATA_BLOCK",
    "END_DATA_BLOCK",
    "ORGANIZATION_BLOCK",
    "END_ORGANIZATION_BLOCK",
    "TYPE",
    "END_TYPE",
    "CONST",
    "END_CONST",
    "INT",
    "DINT",
    "REAL",
    "LREAL",
    "BOOL",
    "BYTE",
    "WORD",
    "DWORD",
    "STRING",
    "TIME",
    "DATE",
    "VOID",
}


def _count_keyword(text: str, kw: str) -> int:
    return len(re.findall(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE))


def check_end_pairs(scl: str) -> list[str]:
    issues: list[str] = []
    # Strip line comments for counting
    lines = []
    for line in scl.splitlines():
        if "//" in line:
            line = line[: line.index("//")]
        lines.append(line)
    body = "\n".join(lines)
    for start, end in _PAIR_KEYWORDS:
        # FUNCTION vs FUNCTION_BLOCK: avoid double-counting FUNCTION inside FUNCTION_BLOCK
        if start == "FUNCTION":
            starts = _count_keyword(body, "FUNCTION") - _count_keyword(body, "FUNCTION_BLOCK")
            ends = _count_keyword(body, "END_FUNCTION") - _count_keyword(body, "END_FUNCTION_BLOCK")
        else:
            starts = _count_keyword(body, start)
            ends = _count_keyword(body, end)
        if starts != ends:
            issues.append(f"关键字未配对：{start}×{starts} vs {end}×{ends}")
    return issues


def check_declaration_comments(scl: str) -> list[str]:
    """External-source dialect: no // inside VAR…END_VAR sections."""
    issues: list[str] = []
    in_var = False
    for i, line in enumerate(scl.splitlines(), start=1):
        stripped = line.strip().upper()
        if stripped.startswith("VAR") and not stripped.startswith("VARIANT"):
            in_var = True
        if in_var and "//" in line:
            issues.append(f"L{i}: 声明区内禁止 // 注释（外部源约束）")
        if stripped == "END_VAR":
            in_var = False
    return issues


def precheck_block(name: str, scl: str, declared: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for msg in check_end_pairs(scl):
        findings.append({"target_type": "block", "target_id": name, "severity": "error", "message": msg})
    for msg in check_declaration_comments(scl):
        findings.append({"target_type": "block", "target_id": name, "severity": "error", "message": msg})
    # Empty body
    if not scl.strip():
        findings.append(
            {
                "target_type": "block",
                "target_id": name,
                "severity": "warning",
                "message": "SCL 正文为空",
            }
        )
    if "TODO" in scl.upper() or "(* EMPTY NETWORK *)" in scl.upper():
        findings.append(
            {
                "target_type": "block",
                "target_id": name,
                "severity": "error",
                "message": "SCL 含 TODO / 空网络占位，禁止送编译器",
            }
        )
    return findings


def precheck_canvas(canvas: CanvasState) -> dict[str, Any]:
    """Return {ok, errors, warnings, findings[]}."""
    findings: list[dict[str, Any]] = []
    for name, block in canvas.blocks.items():
        declared = {v.name for v in block.interface}
        scl = block.get_full_scl()
        findings.extend(precheck_block(name, scl, declared))

    for w_id, widget in canvas.hmi_widgets.items():
        if not widget.plc_tag:
            continue
        if "." in widget.plc_tag:
            blk_ref, var_ref = widget.plc_tag.split(".", 1)
            if blk_ref in canvas.blocks:
                names = {v.name for v in canvas.blocks[blk_ref].interface}
                if var_ref not in names:
                    findings.append(
                        {
                            "target_type": "hmi_widget",
                            "target_id": w_id,
                            "severity": "error",
                            "message": f"HMI 绑定 {widget.plc_tag}：块 {blk_ref} 无变量 {var_ref}",
                        }
                    )
            elif blk_ref not in canvas.tags and widget.plc_tag not in canvas.tags:
                findings.append(
                    {
                        "target_type": "hmi_widget",
                        "target_id": w_id,
                        "severity": "warning",
                        "message": f"HMI 绑定 {widget.plc_tag} 未在画布块/标签中找到",
                    }
                )

    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
    }
