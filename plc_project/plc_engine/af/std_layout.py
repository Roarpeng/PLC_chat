"""S7 标准访问（``S7_Optimized_Access := 'FALSE'``）DB 字节.位偏移计算与校验器。

工业铁律：
- ``Bool`` 按位连续打包（``byte.0 .. byte.7``），满 8 位进 1 字节。
- ``Byte`` / ``Char`` / ``SInt`` / ``USInt`` 占 1 字节，1 字节对齐（先冲刷未满字节的位偏移）。
- ``Word`` / ``Int`` / ``UInt``（2B）、``DWord`` / ``DInt`` / ``UDInt`` / ``Real`` / ``Time``（4B）、
  ``LReal``（8B）等标量按偶数字节（2B）对齐。
- ``IEC_TIMER``（S7-1500 标准访问下 16B，偶数字节对齐；TIA 打印展开子项固定为
  ``PT@+4.0``、``ET@+8.0``、``IN@+12.1``、``Q@+12.2``）。
- ``Struct`` 与 ``Array[lo..hi] of T`` 起始与结束均按偶数字节（2B）对齐。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SCALAR_SIZES: dict[str, tuple[int, int]] = {
    "Bool": (0, 1),
    "Byte": (1, 1),
    "Char": (1, 1),
    "SInt": (1, 1),
    "USInt": (1, 1),
    "Word": (2, 2),
    "Int": (2, 2),
    "UInt": (2, 2),
    "DWord": (4, 2),
    "DInt": (4, 2),
    "UDInt": (4, 2),
    "Real": (4, 2),
    "Time": (4, 2),
    "LReal": (8, 2),
    "IEC_TIMER": (16, 2),
}

ARRAY_TYPE_RE = re.compile(r"(?i)^Array\[(\d+)\.\.(\d+)\]\s+of\s+([A-Za-z0-9_]+)$")
ARRAY_ELEM_NAME_RE = re.compile(r"^([A-Za-z0-9_]+)\[(\d+)\]$")


@dataclass(frozen=True)
class PdfDbRow:
    """TIA Portal DB 打印表中的一行原始记录。"""

    level: int
    name: str
    data_type: str
    pdf_offset: str
    start_value: str = ""
    comment: str = ""
    retain: bool = False


@dataclass(frozen=True)
class LayoutMismatch:
    """单行偏移校验不一致明细。"""

    row_index: int
    dotted_name: str
    data_type: str
    expected_offset: str
    actual_offset: str

    def message(self) -> str:
        return (
            f"成员 {self.dotted_name} ({self.data_type}) 标准访问偏移不匹配："
            f"PDF 标注 {self.actual_offset}，S7 标准布局计算为 {self.expected_offset}"
        )


@dataclass
class VerifiedDbLayout:
    """DB 布局校验与折叠结果。"""

    db_name: str
    db_number: int
    optimized_access: str = "FALSE"
    mismatches: list[LayoutMismatch] = field(default_factory=list)
    scl_body: str = ""
    members: list[dict[str, Any]] = field(default_factory=list)
    initial_assignments: dict[str, str] = field(default_factory=dict)
    offset_map: dict[str, str] = field(default_factory=dict)
    total_bytes: int = 0
    pdf_row_count: int = 0


def _flush_bits(byte_off: int, bit_off: int) -> tuple[int, int]:
    if bit_off > 0:
        return byte_off + 1, 0
    return byte_off, 0


def _align_even(byte_off: int, bit_off: int) -> tuple[int, int]:
    byte_off, bit_off = _flush_bits(byte_off, bit_off)
    if byte_off % 2 == 1:
        byte_off += 1
    return byte_off, 0


def verify_and_build_std_db(
    db_name: str,
    db_number: int,
    rows: list[PdfDbRow],
) -> VerifiedDbLayout:
    """逐行校验 TIA DB 打印表的 Offset 列，并生成折叠后的标准访问 DATA_BLOCK SCL。"""
    byte_off = 0
    bit_off = 0
    mismatches: list[LayoutMismatch] = []
    offset_map: dict[str, str] = {}
    members: list[dict[str, Any]] = []
    initial_assignments: dict[str, str] = {}

    # 维护结构栈：(level, name, kind) 其中 kind in {"STRUCT", "ARRAY"}
    stack: list[tuple[int, str, str]] = []
    scl_lines: list[str] = [
        f'DATA_BLOCK "{db_name}"',
        "{ S7_Optimized_Access := 'FALSE' }",
        "VERSION : 0.1",
        "NON_RETAIN",
        "   STRUCT",
    ]

    def _close_until(target_level: int) -> None:
        nonlocal byte_off, bit_off
        while stack and stack[-1][0] >= target_level:
            _, _, kind = stack.pop()
            byte_off, bit_off = _align_even(byte_off, bit_off)
            if kind == "STRUCT":
                indent = "   " * (len(stack) + 2)
                scl_lines.append(f"{indent}END_STRUCT;")

    def _dotted(local_name: str) -> str:
        prefix = [ item[1] for item in stack if item[2] == "STRUCT" ]
        return ".".join([*prefix, local_name]) if prefix else local_name

    idx = 0
    total_rows = len(rows)
    while idx < total_rows:
        row = rows[idx]
        _close_until(row.level)

        dtype = row.data_type.strip()
        if dtype == "IEC_TIMER":
            byte_off, bit_off = _align_even(byte_off, bit_off)
            calc_off = f"{byte_off}.0"
            full_name = _dotted(row.name)
            offset_map[full_name] = calc_off
            if row.pdf_offset and calc_off != row.pdf_offset:
                mismatches.append(
                    LayoutMismatch(idx + 1, full_name, dtype, calc_off, row.pdf_offset)
                )
            timer_base = byte_off
            expected_children = {
                "PT": f"{timer_base + 4}.0",
                "ET": f"{timer_base + 8}.0",
                "IN": f"{timer_base + 12}.1",
                "Q": f"{timer_base + 12}.2",
            }
            j = idx + 1
            while j < total_rows and rows[j].level > row.level:
                child = rows[j]
                child_full = f"{full_name}.{child.name}"
                exp_off = expected_children.get(child.name, "")
                offset_map[child_full] = child.pdf_offset or exp_off
                if exp_off and child.pdf_offset and exp_off != child.pdf_offset:
                    mismatches.append(
                        LayoutMismatch(j + 1, child_full, child.data_type, exp_off, child.pdf_offset)
                    )
                if child.start_value and not _is_default_literal(child.start_value):
                    initial_assignments[child_full] = child.start_value
                j += 1

            indent = "   " * (len(stack) + 2)
            comment_sfx = f"   // {row.comment}" if row.comment else ""
            scl_lines.append(f"{indent}{row.name} : IEC_TIMER;{comment_sfx}")
            members.append(
                {
                    "name": full_name,
                    "data_type": "IEC_TIMER",
                    "initial_value": "",
                    "comment": row.comment,
                    "offset": timer_base,
                }
            )
            byte_off = timer_base + 16
            bit_off = 0
            idx = j
            continue

        if dtype == "Struct":
            byte_off, bit_off = _align_even(byte_off, bit_off)
            calc_off = f"{byte_off}.0"
            full_name = _dotted(row.name)
            offset_map[full_name] = calc_off
            if row.pdf_offset and calc_off != row.pdf_offset:
                mismatches.append(
                    LayoutMismatch(idx + 1, full_name, dtype, calc_off, row.pdf_offset)
                )
            indent = "   " * (len(stack) + 2)
            comment_sfx = f"   // {row.comment}" if row.comment else ""
            scl_lines.append(f"{indent}{row.name} : Struct{comment_sfx}")
            stack.append((row.level, row.name, "STRUCT"))
            idx += 1
            continue

        arr_match = ARRAY_TYPE_RE.match(dtype)
        if arr_match:
            byte_off, bit_off = _align_even(byte_off, bit_off)
            calc_off = f"{byte_off}.0"
            full_name = _dotted(row.name)
            norm_arr_type = f"Array[{arr_match.group(1)}..{arr_match.group(2)}] of {arr_match.group(3)}"
            offset_map[full_name] = calc_off
            if row.pdf_offset and calc_off != row.pdf_offset:
                mismatches.append(
                    LayoutMismatch(idx + 1, full_name, norm_arr_type, calc_off, row.pdf_offset)
                )
            arr_start_byte = byte_off
            indent = "   " * (len(stack) + 2)
            comment_sfx = f"   // {row.comment}" if row.comment else ""
            scl_lines.append(f"{indent}{row.name} : {norm_arr_type};{comment_sfx}")
            members.append(
                {
                    "name": full_name,
                    "data_type": norm_arr_type,
                    "initial_value": "",
                    "comment": row.comment,
                    "offset": arr_start_byte,
                }
            )
            has_children = idx + 1 < total_rows and rows[idx + 1].level > row.level
            if has_children:
                stack.append((row.level, row.name, "ARRAY"))
            else:
                lo, hi = int(arr_match.group(1)), int(arr_match.group(2))
                cnt = hi - lo + 1
                elem_t = arr_match.group(3)
                if elem_t == "Bool":
                    byte_off += (cnt + 7) // 8
                else:
                    sz, _ = SCALAR_SIZES.get(elem_t, (2, 2))
                    byte_off += cnt * sz
                byte_off, bit_off = _align_even(byte_off, bit_off)
            idx += 1
            continue

        # 标量成员（或 Array 展开子元素）
        in_array = any(item[2] == "ARRAY" for item in stack)
        full_name = _dotted(row.name)
        if dtype == "Bool":
            calc_off = f"{byte_off}.{bit_off}"
            elem_byte = byte_off
            if row.pdf_offset and calc_off != row.pdf_offset:
                mismatches.append(
                    LayoutMismatch(idx + 1, full_name, dtype, calc_off, row.pdf_offset)
                )
            offset_map[full_name] = calc_off
            bit_off += 1
            if bit_off == 8:
                byte_off += 1
                bit_off = 0
        else:
            byte_off, bit_off = _flush_bits(byte_off, bit_off)
            sz, align = SCALAR_SIZES.get(dtype, (2, 2))
            if align == 2 and byte_off % 2 == 1:
                byte_off += 1
            calc_off = f"{byte_off}.0"
            elem_byte = byte_off
            if row.pdf_offset and calc_off != row.pdf_offset:
                mismatches.append(
                    LayoutMismatch(idx + 1, full_name, dtype, calc_off, row.pdf_offset)
                )
            offset_map[full_name] = calc_off
            byte_off += sz

        sval = _normalize_start_value(dtype, row.start_value)
        if not in_array:
            indent = "   " * (len(stack) + 2)
            comment_sfx = f"   // {row.comment}" if row.comment else ""
            scl_lines.append(f"{indent}{row.name} : {dtype};{comment_sfx}")
            if sval and not _is_default_literal(sval):
                initial_assignments[full_name] = sval
            members.append(
                {
                    "name": full_name,
                    "data_type": dtype,
                    "initial_value": sval,
                    "comment": row.comment,
                    "offset": elem_byte,
                }
            )
        idx += 1

    _close_until(0)
    scl_lines.append("   END_STRUCT;")
    scl_lines.append("BEGIN")
    for path, val in initial_assignments.items():
        scl_lines.append(f"   {path} := {val};")
    scl_lines.append("END_DATA_BLOCK")

    return VerifiedDbLayout(
        db_name=db_name,
        db_number=db_number,
        optimized_access="FALSE",
        mismatches=mismatches,
        scl_body="\n".join(scl_lines),
        members=members,
        initial_assignments=initial_assignments,
        offset_map=offset_map,
        total_bytes=byte_off,
        pdf_row_count=total_rows,
    )


def _normalize_start_value(dtype: str, raw: str) -> str:
    val = (raw or "").strip()
    if not val:
        return ""
    if dtype == "Bool":
        if val in {"0", "false", "FALSE"}:
            return "FALSE"
        if val in {"1", "true", "TRUE"}:
            return "TRUE"
    return val


def _is_default_literal(val: str) -> bool:
    clean = val.strip().upper()
    return clean in {"", "FALSE", "0", "0.0", "16#0", "16#00", "T#0MS", "T#0S"}
