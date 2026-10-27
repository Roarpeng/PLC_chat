"""SCL DATA_BLOCK text -> Canvas DB block import (contract docs/24 B 线).

``parse_db_scl`` reads the TIA-exported SCL dialect of a global DB::

    DATA_BLOCK "DB1900_Communication_PC"
    { S7_Optimized_Access := 'FALSE' }
    VERSION : 0.1
       STRUCT
          Send : Struct          // nested -> dotted path Send.Heart
             Heart : Bool;   // 心跳
             Spare : Array[0..21] of Byte;
          END_STRUCT;
       END_STRUCT;

    BEGIN
       Send.Heart := TRUE;
    END_DATA_BLOCK

Nested ``Struct`` members flatten to dotted paths (``Send.Heart``),
``Array[a..b] of X`` keeps its textual type, ``//`` (and ``(* *)``) line
comments become variable comments, and ``BEGIN`` assignments land both in
``initial_assignments`` and on the matching interface entry's
``initial_value``. The original unit text is preserved as ``scl_body`` so
``db_to_canvas_block`` can carry it verbatim onto the canvas block.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from plc_engine.canvas_model import CanvasBlock, CanvasState, CanvasVariable

# Name : Rest — Rest may be Struct / Array[..] of X / simple type [:= initial].
_MEMBER_RE = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(.+)$")
_HEADER_RE = re.compile(r'(?i)^DATA_BLOCK\s+(?:"([^"]+)"|([A-Za-z_]\w*))')
_ASSIGN_RE = re.compile(r"^([A-Za-z_][\w.\[\]]*)\s*:=\s*(.+?);?\s*$")


class DBImportRejected(ValueError):
    """Import rejected before any canvas mutation; the router maps it to HTTP 400."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _comment_slash_index(code: str) -> int:
    """Index of a ``//`` comment start that is not inside a string literal."""
    in_str = False
    i = 0
    while i < len(code) - 1:
        ch = code[i]
        if ch == '"':
            in_str = not in_str
        elif not in_str and ch == "/" and code[i + 1] == "/":
            return i
        i += 1
    return -1


def _split_line_comment(line: str) -> tuple[str, str]:
    """Split one SCL line into (code, comment); strips // and (* *) comments."""
    code = line
    comment = ""
    block = re.search(r"\(\*(.*?)\*\)", code)
    if block:
        comment = block.group(1).strip()
        code = code[: block.start()] + code[block.end() :]
    idx = _comment_slash_index(code)
    if idx >= 0:
        inline = code[idx + 2 :].strip()
        comment = inline or comment
        code = code[:idx]
    return code, comment.strip()


def _norm_type(raw: str) -> str:
    """Normalize a type spelling: ``Array [ 0 .. 21 ] of Byte`` -> ``Array[0..21] of Byte``."""
    t = re.sub(r"\s+", " ", raw.strip())
    t = re.sub(r"\s*\[\s*", "[", t)
    t = re.sub(r"\s*\]", "]", t)
    t = re.sub(r"\s*\.\.\s*", "..", t)
    t = re.sub(r"(?i)\]\s*of\b", "] of", t)
    t = re.sub(r"(?i)^array\b", "Array", t)
    t = re.sub(r"(?i)\bof\b", "of", t)
    return t.strip()


def _parse_struct_members(
    lines: list[str], idx: int, prefix: str, interface: list[dict[str, Any]]
) -> int:
    """Parse STRUCT members from ``lines[idx:]`` until the matching END_STRUCT.

    ``lines[idx]`` is the first member line (the STRUCT keyword itself was
    consumed by the caller). Returns the index just past the END_STRUCT line.
    Nested Structs recurse and emit dotted-path leaf variables.
    """
    i = idx
    while i < len(lines):
        code, comment = _split_line_comment(lines[i])
        stripped = code.strip()
        if not stripped:
            i += 1
            continue
        if stripped.upper().rstrip(";").strip() == "END_STRUCT":
            return i + 1
        match = _MEMBER_RE.match(stripped)
        if match:
            var, rest = match.group(1), match.group(2).strip()
            initial = ""
            if ":=" in rest:
                rest, initial = (part.strip() for part in rest.split(":=", 1))
                initial = initial.rstrip(";").strip()
            rest = rest.rstrip(";").strip()
            full = f"{prefix}.{var}" if prefix else var
            if rest.upper() == "STRUCT":
                i = _parse_struct_members(lines, i + 1, full, interface)
                continue
            interface.append(
                {
                    "name": full,
                    "data_type": _norm_type(rest),
                    "comment": comment,
                    "initial_value": initial,
                    "section": "VAR",
                }
            )
        i += 1
    return i  # unterminated STRUCT — tolerate and stop at unit end


def _parse_one_db(lines: list[str]) -> dict[str, Any]:
    """Parse one DATA_BLOCK unit; ``lines[0]`` is the DATA_BLOCK header line."""
    code, _ = _split_line_comment(lines[0])
    header = _HEADER_RE.match(code.strip())
    if header is None:
        raise DBImportRejected(
            "DB_PARSE_FAILED", f"DATA_BLOCK 头无法解析：{code.strip()!r}"
        )
    name = header.group(1) or header.group(2) or ""

    interface: list[dict[str, Any]] = []
    struct_seen = False
    i = 1
    while i < len(lines):
        line_code, _ = _split_line_comment(lines[i])
        stripped = line_code.strip().rstrip(";").strip()
        if stripped.upper() == "STRUCT":
            struct_seen = True
            i = _parse_struct_members(lines, i + 1, "", interface)
            break
        if stripped.upper() == "BEGIN":
            break
        i += 1

    initial_assignments: dict[str, str] = {}
    var_by_path = {v["name"]: v for v in interface}
    in_begin = False
    for line in lines[i:]:
        line_code, _ = _split_line_comment(line)
        stripped = line_code.strip()
        if not stripped:
            continue
        keyword = stripped.upper().rstrip(";").strip()
        if keyword == "BEGIN":
            in_begin = True
            continue
        if keyword.startswith("END_DATA_BLOCK"):
            in_begin = False
            continue
        if not in_begin:
            continue
        assign = _ASSIGN_RE.match(stripped)
        if assign:
            path, value = assign.group(1), assign.group(2).strip()
            initial_assignments[path] = value
            target = var_by_path.get(path)
            if target is not None and not target["initial_value"]:
                target["initial_value"] = value

    if not interface and not struct_seen:
        raise DBImportRejected(
            "DB_PARSE_FAILED", f"DB {name!r} 未解析到 STRUCT 成员（无变量）"
        )

    return {
        "name": name,
        "interface": interface,
        "initial_assignments": initial_assignments,
        "scl_body": "\n".join(lines).strip(),
    }


def _split_db_units(text: str) -> list[list[str]]:
    """Split text into DATA_BLOCK units; each starts at its header line."""
    units: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        code, _ = _split_line_comment(line)
        if re.match(r"(?i)^\s*DATA_BLOCK\b", code):
            if current:
                units.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        units.append(current)
    return units


def parse_db_scl_all(text: str) -> list[dict[str, Any]]:
    """Parse every DATA_BLOCK unit in ``text`` (external-source files may hold several)."""
    units = _split_db_units(text)
    if not units:
        raise DBImportRejected(
            "DB_PARSE_FAILED", "文本中未找到 DATA_BLOCK 声明（SCL DB 导入需要 DATA_BLOCK 单元）"
        )
    return [_parse_one_db(unit) for unit in units]


def parse_db_scl(text: str) -> dict[str, Any]:
    """Parse SCL DATA_BLOCK text -> ``{name, interface, initial_assignments, scl_body}``.

    interface entries: ``{name: 点路径(Send.Heart), data_type, comment,
    initial_value, section: "VAR"}``; ``initial_assignments`` maps raw BEGIN
    paths (incl. array elements like ``Send.Spare[0]``) to raw value text.
    """
    return parse_db_scl_all(text)[0]


def _db_number(name: str) -> int:
    """Best-effort block number from the DB name (``DB1900_...`` -> 1900)."""
    digits = re.search(r"(\d+)", name)
    return int(digits.group(1)) if digits else 0


def _next_block_number(existing: dict[str, CanvasBlock]) -> int:
    numbers = [b.number for b in existing.values() if b.block_type.upper() == "DB"]
    return max(numbers) + 1 if numbers else 1


def db_to_canvas_block(
    parsed: dict[str, Any], existing: dict[str, CanvasBlock] | None = None
) -> CanvasBlock:
    """parsed DB -> canvas DB block (block_type="DB", language="DB", status="draft")."""
    existing = existing if existing is not None else {}
    name = str(parsed.get("name") or "").strip()
    number = _db_number(name) or _next_block_number(existing)
    interface = [
        CanvasVariable(
            name=v["name"],
            data_type=v.get("data_type", ""),
            comment=v.get("comment", ""),
            initial_value=v.get("initial_value", ""),
            section=v.get("section", "VAR"),
        )
        for v in parsed.get("interface", [])
    ]
    return CanvasBlock(
        name=name,
        block_type="DB",
        number=number,
        language="DB",
        interface=interface,
        scl_body=str(parsed.get("scl_body") or "").strip(),
        status="draft",
    )


def read_db_text(path: str | Path) -> str:
    """Read an exported .scl/.txt DB file; TIA exports may be UTF-8 (BOM) or ANSI/GBK."""
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def import_db_text(
    db_text: str,
    project_name: str = "",
    canvas: CanvasState | None = None,
) -> dict[str, Any]:
    """Import one-or-more DATA_BLOCK units onto a canvas.

    A fresh canvas is created unless ``canvas`` is passed (multi-DB merge:
    feed the previous response's canvas back in). Returns
    ``{"blocks_created": int, "canvas": CanvasState.to_dict()}``.
    """
    units = parse_db_scl_all(db_text)
    state = canvas if canvas is not None else CanvasState(
        project_name=(project_name or "").strip() or units[0]["name"]
    )
    for unit in units:
        block = db_to_canvas_block(unit, state.blocks)
        state.blocks[block.name] = block
    return {"blocks_created": len(units), "canvas": state.to_dict()}


def import_db_path(
    path: str | Path,
    project_name: str = "",
    canvas: CanvasState | None = None,
) -> dict[str, Any]:
    """Import DB SCL text from a file path (encoding-tolerant read)."""
    return import_db_text(read_db_text(path), project_name, canvas)
