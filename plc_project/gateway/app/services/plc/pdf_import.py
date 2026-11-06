"""TIA Portal 打印版 PDF 解析器（PLC 变量表 PDF + 标准访问 DB 块 PDF）。

遵循 Greenfield fail-closed 与零写盘铁律：
- 仅在内存字节流（``stream=data``）解析，确认前零落盘。
- PLC Tag 表 PDF：提取全部 ``%I / %Q`` 变量并与表头声明总数（如 ``PLC_IO [113]``）交叉核对。
- DB 打印表 PDF：提取全部成员行与 ``Offset`` 列（``byte.bit``），调用
  ``plc_engine.af.std_layout.verify_and_build_std_db`` 做 100% 字节.位偏移校验，
  任何偏移不一致即以 ``GF_UPLOAD_PDF_LAYOUT_MISMATCH`` 整批拒绝。
"""
from __future__ import annotations

import io
import re
from typing import Any

from gateway.app.services.plc import db_import as _db
from plc_engine.af.greenfield_contract import ReceiptError
from plc_engine.af.std_layout import PdfDbRow, VerifiedDbLayout, verify_and_build_std_db

IO_ADDR_RE = re.compile(r"^%[IQ][BWD]?\d+(?:\.\d+)?$")
DB_OFFSET_RE = re.compile(r"^\d+\.\d$")
DB_HEADER_RE = re.compile(r"([A-Za-z0-9_]+)\s*\[DB(\d+)\]")
IO_HEADER_COUNT_RE = re.compile(r"([A-Za-z0-9_]+)\s*\[(\d+)\]")
TEXT_TYPES_RE = re.compile(
    r"^(Bool|Byte|Word|DWord|Int|DInt|UInt|USInt|SInt|UDInt|Real|LReal|Time|Char|"
    r"IEC_TIMER|String(?:\[\d+\])?|Struct|Array\[.*\]\s+of\s+[A-Za-z0-9_]+)$"
)


def _err(filename: str, row: int, column: str, code: str, message: str) -> ReceiptError:
    return ReceiptError(file=filename, row=row, column=column, code=code, message=message)


def _join_identifier(words: list[Any]) -> str:
    """拼接可能被 TIA PDF 打印机断字换行（带 ``\\u2010``/``\\u00ad`` 连字符）的标识符。"""
    parts = [str(w[4]).rstrip("\u2010\u00ad-") for w in words]
    return "".join(parts)


def parse_pdf_bytes(
    data: bytes,
    filename: str = "upload.pdf",
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[ReceiptError]]:
    """解析单个 TIA Portal PDF（自动识别 PLC Tags 表或 DB 打印表）。

    Returns:
        ``(io_entries, db_structs, errors)``
    """
    if not data or not data.startswith(b"%PDF"):
        return [], [], [
            _err(filename, 0, "file", "GF_UPLOAD_PDF_PARSE_FAILED", "非合法 PDF 字节流（缺少 %PDF 头）")
        ]

    try:
        import pymupdf
    except ImportError:
        pymupdf = None  # type: ignore[assignment]

    if pymupdf is not None:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            return [], [], [
                _err(filename, 0, "file", "GF_UPLOAD_PDF_PARSE_FAILED", f"PDF 无法打开：{exc}")
            ]
        try:
            if len(doc) == 0:
                return [], [], [
                    _err(filename, 0, "file", "GF_UPLOAD_PDF_PARSE_FAILED", "PDF 页数为 0")
                ]
            first_text = doc[0].get_text("text")
            if DB_HEADER_RE.search(first_text) or ("Offset" in first_text and "Static" in first_text):
                structs, errs = _parse_db_pdf_pymupdf(doc, filename, first_text)
                return [], structs, errs
            if "PLC tags" in first_text or "Address" in first_text:
                entries, errs = _parse_io_pdf_pymupdf(doc, filename, first_text)
                return entries, [], errs
        finally:
            doc.close()

    # 文本流回退（适用于 pypdf 或合成单测 PDF）
    return _parse_pdf_text_fallback(data, filename)


def _parse_io_pdf_pymupdf(
    doc: Any,
    filename: str,
    first_text: str,
) -> tuple[list[dict[str, str]], list[ReceiptError]]:
    errors: list[ReceiptError] = []
    entries: list[dict[str, str]] = []
    hdr_match = IO_HEADER_COUNT_RE.search(first_text)
    table_name = hdr_match.group(1) if hdr_match else "PLC_IO"
    expected_count = int(hdr_match.group(2)) if hdr_match else None

    for page in doc:
        words = page.get_text("words")
        addr_words = [
            w for w in words if 315.0 <= w[0] < 398.0 and IO_ADDR_RE.match(w[4])
        ]
        addr_words.sort(key=lambda w: w[1])
        for idx, aw in enumerate(addr_words):
            y_top = aw[1] - 4.0
            y_bot = (
                addr_words[idx + 1][1] - 4.0
                if idx + 1 < len(addr_words)
                else page.rect.height - 30.0
            )
            row_words = [
                w
                for w in words
                if y_top <= w[1] < y_bot and w[1] < page.rect.height - 40.0
            ]
            name_words = [w for w in row_words if 75.0 <= w[0] < 230.0]
            dtype_words = [w for w in row_words if 230.0 <= w[0] < 315.0]
            comm_words = [w for w in row_words if w[0] >= 645.0]
            if not name_words or not dtype_words:
                errors.append(
                    _err(
                        filename,
                        len(entries) + 1,
                        "Name",
                        "GF_UPLOAD_IO_ROW_DROPPED",
                        f"地址 {aw[4]} 所在行缺少符号名或数据类型",
                    )
                )
                continue
            entries.append(
                {
                    "name": _join_identifier(name_words),
                    "path": table_name,
                    "data_type": " ".join(w[4] for w in dtype_words),
                    "logical_address": aw[4],
                    "comment": " ".join(w[4] for w in comm_words),
                }
            )

    if not entries:
        errors.append(
            _err(filename, 0, "table", "GF_UPLOAD_PDF_UNRECOGNIZED", "PDF 中未提取到任何 %I/%Q 变量行")
        )
    elif expected_count is not None and len(entries) != expected_count:
        errors.append(
            _err(
                filename,
                0,
                "table",
                "GF_UPLOAD_IO_SILENT_DROP",
                f"PDF 表头声明 {expected_count} 条变量，实际提取 {len(entries)} 条，拒绝静默丢行",
            )
        )
    return entries, errors


def _parse_db_pdf_pymupdf(
    doc: Any,
    filename: str,
    first_text: str,
) -> tuple[list[dict[str, Any]], list[ReceiptError]]:
    errors: list[ReceiptError] = []
    hdr_match = DB_HEADER_RE.search(first_text)
    db_name = hdr_match.group(1) if hdr_match else "DB_Imported"
    db_number = int(hdr_match.group(2)) if hdr_match else 1

    rows: list[PdfDbRow] = []
    for page in doc:
        words = page.get_text("words")
        offset_words = [
            w for w in words if 260.0 <= w[0] < 312.0 and DB_OFFSET_RE.match(w[4])
        ]
        offset_words.sort(key=lambda w: w[1])
        for idx, ow in enumerate(offset_words):
            y_top = ow[1] - 4.0
            y_bot = (
                offset_words[idx + 1][1] - 4.0
                if idx + 1 < len(offset_words)
                else page.rect.height - 30.0
            )
            row_words = [
                w
                for w in words
                if y_top <= w[1] < y_bot and w[1] < page.rect.height - 40.0
            ]
            name_words = [w for w in row_words if 80.0 <= w[0] < 205.0]
            dtype_words = [w for w in row_words if 205.0 <= w[0] < 260.0]
            sval_words = [w for w in row_words if 312.0 <= w[0] < 420.0]
            ret_words = [w for w in row_words if 420.0 <= w[0] < 465.0]
            comm_words = [w for w in row_words if w[0] >= 655.0]
            if not name_words or not dtype_words:
                continue
            name_x = name_words[0][0]
            level = max(0, round((name_x - 89.2) / 11.4))
            rows.append(
                PdfDbRow(
                    level=level,
                    name=_join_identifier(name_words),
                    data_type=" ".join(w[4] for w in dtype_words),
                    pdf_offset=ow[4],
                    start_value=" ".join(w[4] for w in sval_words),
                    comment=" ".join(w[4] for w in comm_words),
                    retain=any(w[4].lower() == "true" for w in ret_words),
                )
            )

    if not rows:
        return [], [
            _err(filename, 0, "DATA_BLOCK", "GF_UPLOAD_PDF_UNRECOGNIZED", "DB PDF 中未提取到任何有效成员行")
        ]

    return _finalize_db_layout(db_name, db_number, rows, filename, errors)


def _finalize_db_layout(
    db_name: str,
    db_number: int,
    rows: list[PdfDbRow],
    filename: str,
    errors: list[ReceiptError],
) -> tuple[list[dict[str, Any]], list[ReceiptError]]:
    layout: VerifiedDbLayout = verify_and_build_std_db(db_name, db_number, rows)
    if layout.mismatches:
        for mm in layout.mismatches:
            errors.append(
                _err(
                    filename,
                    mm.row_index,
                    "Offset",
                    "GF_UPLOAD_PDF_LAYOUT_MISMATCH",
                    mm.message(),
                )
            )
        return [], errors

    # 交叉校验生成出的标准访问 SCL 是否能被底层 db_import 完整解析
    try:
        parsed_units = _db.parse_db_scl_all(layout.scl_body)
    except _db.DBImportRejected as exc:
        errors.append(
            _err(
                filename,
                0,
                "DATA_BLOCK",
                "GF_UPLOAD_DB_PARSE_FAILED",
                f"PDF 重建 DATA_BLOCK 未通过底层解析器：{exc.message}（{exc.code}）",
            )
        )
        return [], errors

    if not parsed_units or len(parsed_units[0].get("interface") or []) != len(layout.members):
        errors.append(
            _err(
                filename,
                0,
                "DATA_BLOCK",
                "GF_UPLOAD_DB_PARSE_FAILED",
                "PDF 重建 DATA_BLOCK 成员数与布局校验器不一致",
            )
        )
        return [], errors

    struct_dict: dict[str, Any] = {
        "name": db_name,
        "optimized_access": "FALSE",
        "members": layout.members,
        "initial_assignments": layout.initial_assignments,
        "scl_body": layout.scl_body,
    }
    return [struct_dict], errors


def _parse_pdf_text_fallback(
    data: bytes,
    filename: str,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[ReceiptError]]:
    """当 PyMuPDF 坐标流未命中时，使用文本行回退解析。"""
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        return [], [], [
            _err(filename, 0, "file", "GF_UPLOAD_PDF_PARSE_FAILED", f"PDF 文本提取失败：{exc}")
        ]

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], [], [
            _err(filename, 0, "file", "GF_UPLOAD_PDF_UNRECOGNIZED", "PDF 不含可提取文本")
        ]

    joined = "\n".join(lines[:30])
    if DB_HEADER_RE.search(joined):
        hdr = DB_HEADER_RE.search(joined)
        assert hdr is not None
        db_name, db_num = hdr.group(1), int(hdr.group(2))
        rows: list[PdfDbRow] = []
        current_struct_level = 0
        for i in range(len(lines) - 2):
            if TEXT_TYPES_RE.match(lines[i + 1]) and DB_OFFSET_RE.match(lines[i + 2]):
                name, dtype, off = lines[i], lines[i + 1], lines[i + 2]
                if dtype == "Struct":
                    rows.append(PdfDbRow(level=0, name=name, data_type=dtype, pdf_offset=off))
                    current_struct_level = 1
                else:
                    lvl = current_struct_level + (1 if "[" in name else 0)
                    rows.append(PdfDbRow(level=lvl, name=name, data_type=dtype, pdf_offset=off))
        if rows:
            structs, errs = _finalize_db_layout(db_name, db_num, rows, filename, [])
            return [], structs, errs

    io_entries: list[dict[str, str]] = []
    for i in range(len(lines) - 2):
        if TEXT_TYPES_RE.match(lines[i + 1]) and IO_ADDR_RE.match(lines[i + 2]):
            io_entries.append(
                {
                    "name": lines[i],
                    "path": "PLC_IO",
                    "data_type": lines[i + 1],
                    "logical_address": lines[i + 2],
                    "comment": "",
                }
            )
    if io_entries:
        return io_entries, [], []

    return [], [], [
        _err(filename, 0, "file", "GF_UPLOAD_PDF_UNRECOGNIZED", "无法从 PDF 识别 TIA 变量表或 DB 块结构")
    ]
