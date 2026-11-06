"""Greenfield 上传解析编排 + fail-closed 严格校验（§3.4.2 / §3.4.3）。

**wrapper 模式（§3.4.3 / D5）**：底层 ``io_import.py`` / ``db_import.py``
两文件**零 diff**，本模块只调用其公开函数（``parse_plctags_csv`` /
``parse_db_scl_all``）并复用其表头别名 / 行映射口径。底层会「丢弃空 Name 行 /
跳过无表头 sheet / 编码兜底 replace」——这些静默近似在 Greenfield 通道一律
升级为**整批原子拒绝 + 明细回执**。

**确认前零写盘（AC-4）**：上传内容是内存字节；xlsx 用 ``BytesIO`` +
openpyxl 解析，绝不写临时文件去调用需要路径的 ``parse_plctags_xlsx``。
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from gateway.app.services.plc import db_import as _db
from gateway.app.services.plc import io_import as _io
from gateway.app.services.plc import pdf_import as _pdf
from plc_engine.af.greenfield_contract import ParseReceipt, ReceiptError
from plc_engine.af.greenfield_ir import canonical_dumps, sha256_hex, sha256_prefixed

# ---------------------------------------------------------------------------
# 白名单与上限（R2 裁定 / §3.4.2）
# ---------------------------------------------------------------------------

IO_SUFFIXES: frozenset[str] = frozenset({".xlsx", ".xlsm", ".csv"})
DB_SUFFIXES: frozenset[str] = frozenset({".scl", ".txt", ".db"})
PDF_SUFFIXES: frozenset[str] = frozenset({".pdf"})
PDF_MAX_FILE_BYTES = 10 * 1024 * 1024

IO_MAX_FILE_BYTES = 5 * 1024 * 1024
IO_MAX_ROWS = 5000
DB_MAX_FILE_BYTES = 2 * 1024 * 1024
DB_MAX_UNITS = 50
DB_MAX_MEMBERS_PER_UNIT = 2000
DB_MAX_STRUCT_DEPTH = 8
MAX_FILES = 5
MAX_BATCH_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IO_ENTRIES = 5000
MAX_TOTAL_DB_MEMBERS = 20000

IO_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "gbk")
DB_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030")

NAME_RE = re.compile(r"^[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{0,63}$")
ADDRESS_RE = re.compile(r"^%[IQ][BWD]?\d+(\.\d+)?$")
ARRAY_RE = re.compile(r"(?i)^Array\[(\d+)\.\.(\d+)\]\s+of\s+\w+$")
LITERAL_RE = re.compile(
    r"^(?:TRUE|FALSE|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|(?:2|8|10|16)#[0-9A-Fa-f_]+|(?:T|TIME|LT|LTIME)#[0-9A-Za-z_.+-]+|'[^']*'|\"[^\"]*\")$",
    re.IGNORECASE,
)
OPTIMIZED_ACCESS_RE = re.compile(
    r"(?i)S7_Optimized_Access\s*:=\s*'([^']+)'"
)
DATA_BLOCK_HEADER_RE = re.compile(r"(?i)^\s*DATA_BLOCK\b")

#: 上限清单（供 A7 面板与单测逐项断言）。
LIMITS: dict[str, int] = {
    "io_max_file_bytes": IO_MAX_FILE_BYTES,
    "io_max_rows": IO_MAX_ROWS,
    "db_max_file_bytes": DB_MAX_FILE_BYTES,
    "db_max_units": DB_MAX_UNITS,
    "db_max_members_per_unit": DB_MAX_MEMBERS_PER_UNIT,
    "db_max_struct_depth": DB_MAX_STRUCT_DEPTH,
    "max_files": MAX_FILES,
    "max_batch_bytes": MAX_BATCH_BYTES,
    "max_total_io_entries": MAX_TOTAL_IO_ENTRIES,
    "max_total_db_members": MAX_TOTAL_DB_MEMBERS,
}

#: 全部 ``GF_UPLOAD_*`` 错误码（前端明细定位与测试用）。
UPLOAD_ERROR_CODES: frozenset[str] = frozenset(
    {
        "GF_UPLOAD_EXT_UNSUPPORTED",
        "GF_UPLOAD_FILE_TOO_LARGE",
        "GF_UPLOAD_BATCH_TOO_MANY_FILES",
        "GF_UPLOAD_BATCH_TOO_LARGE",
        "GF_UPLOAD_ENCODING_FALLBACK",
        "GF_UPLOAD_IO_HEADER_MISSING",
        "GF_UPLOAD_IO_ROW_DROPPED",
        "GF_UPLOAD_IO_NAME_INVALID",
        "GF_UPLOAD_IO_ADDR_INVALID",
        "GF_UPLOAD_IO_NAME_DUPLICATE",
        "GF_UPLOAD_IO_ADDR_DUPLICATE",
        "GF_UPLOAD_IO_ROW_LIMIT",
        "GF_UPLOAD_IO_PARSE_FAILED",
        "GF_UPLOAD_IO_SILENT_DROP",
        "GF_UPLOAD_IO_TOTAL_LIMIT",
        "GF_UPLOAD_DB_PARSE_FAILED",
        "GF_UPLOAD_DB_UNIT_LIMIT",
        "GF_UPLOAD_DB_NAME_DUPLICATE",
        "GF_UPLOAD_DB_MEMBER_LIMIT",
        "GF_UPLOAD_DB_MEMBER_DUPLICATE",
        "GF_UPLOAD_DB_ARRAY_BOUNDS",
        "GF_UPLOAD_DB_INITIAL_EXPRESSION",
        "GF_UPLOAD_DB_STRUCT_DEPTH",
        "GF_UPLOAD_DB_TOTAL_MEMBER_LIMIT",
        "GF_UPLOAD_DB_HEADER_MISSING",
        "GF_UPLOAD_PDF_PARSE_FAILED",
        "GF_UPLOAD_PDF_UNRECOGNIZED",
        "GF_UPLOAD_PDF_LAYOUT_MISMATCH",
        "GF_UPLOAD_EMPTY_BATCH",
    }
)


@dataclass
class UploadItem:
    """一个上传项：文件名 + 原始字节；``text`` 非空时表示对话粘贴文本。"""

    filename: str = ""
    data: bytes = b""
    text: str = ""
    kind: str = ""  # "io" | "db" | ""（自动按后缀判定）

    @property
    def is_paste(self) -> bool:
        """是否为对话粘贴文本（无文件字节）。"""
        return bool(self.text) and not self.data

    @property
    def display_name(self) -> str:
        """回执中展示的文件名。"""
        return self.filename or ("pasted.scl" if "DATA_BLOCK" in self.text[:512] else "pasted.csv")

    @property
    def suffix(self) -> str:
        """小写后缀（粘贴文本按内容近似判定）。"""
        if self.filename:
            idx = self.filename.rfind(".")
            return self.filename[idx:].lower() if idx >= 0 else ""
        if self.is_paste:
            return ".scl" if DATA_BLOCK_HEADER_RE.search(self.text) else ".csv"
        return ""


def _err(
    filename: str, row: int, column: str, code: str, message: str
) -> ReceiptError:
    """构造一条标准化失败明细 ``{file,row,column,code,message}``。"""
    return ReceiptError(file=filename, row=row, column=column, code=code, message=message)


def _decode_strict(
    data: bytes, encodings: tuple[str, ...], filename: str
) -> tuple[str, ReceiptError | None]:
    """按白名单编码链严格解码；需要兜底（latin-1 / replace）即判失败。"""
    for encoding in encodings:
        try:
            return data.decode(encoding), None
        except UnicodeDecodeError:
            continue
    chain = " → ".join(encodings)
    return "", _err(
        filename, 0, "encoding", "GF_UPLOAD_ENCODING_FALLBACK",
        f"编码回退到兜底视为失败，拒绝静默近似（严格链：{chain}）",
    )


def _csv_rows(text: str) -> list[list[str]]:
    """按 ``,`` / ``;`` / tab 嗅探分隔符拆分 CSV 行（与底层口径一致）。"""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _locate_header(rows: list[list[str]]) -> tuple[dict[int, str] | None, int]:
    """在前 5 行内定位表头，返回（列映射, 数据起始行下标）。"""
    for offset, row in enumerate(rows[:5]):
        mapping = _io._map_header_columns(list(row))
        if mapping is not None:
            return mapping, offset + 1
    return None, 0


def _blank_row(row: list[str]) -> bool:
    """是否整行空白（允许跳过，不算静默丢行）。"""
    return not any(str(cell or "").strip() for cell in row)


def _validate_io_rows(
    rows: list[list[str]],
    mapping: dict[int, str],
    data_start: int,
    filename: str,
    errors: list[ReceiptError],
) -> list[dict[str, str]]:
    """逐行严格校验 IO 数据行：空 Name / 非法名 / 非法地址 / 重复 → 明细拒绝。"""
    entries: list[dict[str, str]] = []
    seen_names: set[str] = set()
    seen_addresses: set[str] = set()
    data_rows = rows[data_start:]

    if len(data_rows) > IO_MAX_ROWS:
        errors.append(
            _err(filename, data_start + IO_MAX_ROWS + 1, "row", "GF_UPLOAD_IO_ROW_LIMIT",
                 f"IO 数据行 {len(data_rows)} 超过单文件上限 {IO_MAX_ROWS}")
        )

    for offset, row in enumerate(data_rows):
        row_no = data_start + offset + 1
        if _blank_row(row):
            continue
        entry = _io._row_to_entry(tuple(row), mapping)
        if entry is None:
            # 底层会静默丢弃「空 Name 行 / 重复表头行」——这里升级为整批拒绝。
            errors.append(
                _err(filename, row_no, "Name", "GF_UPLOAD_IO_ROW_DROPPED",
                     "该行会被解析器静默丢弃（Name 为空或重复表头），拒绝静默近似")
            )
            continue
        name = entry.get("name", "")
        address = entry.get("logical_address", "")

        if not NAME_RE.match(name):
            errors.append(
                _err(filename, row_no, "Name", "GF_UPLOAD_IO_NAME_INVALID",
                     f"符号名 {name!r} 不符合 ^[A-Za-z_一-鿿][A-Za-z0-9_一-鿿]{{0,63}}$")
            )
        if name in seen_names:
            errors.append(
                _err(filename, row_no, "Name", "GF_UPLOAD_IO_NAME_DUPLICATE",
                     f"符号名 {name!r} 在本文件内重复")
            )
        seen_names.add(name)

        if address:
            if not ADDRESS_RE.match(address):
                errors.append(
                    _err(filename, row_no, "Logical Address", "GF_UPLOAD_IO_ADDR_INVALID",
                         f"{address!r} 不符合 %I/%Q 绝对地址格式")
                )
            if address in seen_addresses:
                errors.append(
                    _err(filename, row_no, "Logical Address", "GF_UPLOAD_IO_ADDR_DUPLICATE",
                         f"绝对地址 {address!r} 被多个符号占用")
                )
            seen_addresses.add(address)

        entries.append(
            {
                "name": name,
                "path": entry.get("path", ""),
                "data_type": entry.get("data_type", ""),
                "logical_address": address,
                "comment": entry.get("comment", ""),
            }
        )
    return entries


def strict_validate_io(item: UploadItem) -> tuple[list[dict[str, str]], list[ReceiptError]]:
    """严格解析单个 IO 表（``.xlsx/.xlsm/.csv`` 或粘贴 CSV 文本）。

    Returns:
        ``(entries, errors)``；errors 非空时调用方必须整批拒绝。

    Notes:
        CSV 额外调用底层公开函数 ``parse_plctags_csv`` 做交叉一致性校验；
        xlsx 因上传为内存字节且确认前禁止落盘，用 ``openpyxl.BytesIO`` 复用
        底层 ``_HEADER_ALIASES`` / ``_map_header_columns`` / ``_row_to_entry``
        口径，**不修改、不绕过**底层两文件。
    """
    errors: list[ReceiptError] = []
    filename = item.display_name
    suffix = item.suffix

    if suffix in PDF_SUFFIXES:
        io_list, db_list, pdf_errors = strict_validate_pdf(item)
        if pdf_errors:
            return [], pdf_errors
        if db_list and not io_list:
            return [], [_err(filename, 0, "file", "GF_UPLOAD_IO_HEADER_MISSING", "该 PDF 为 DB 块打印表而非 IO 变量表")]
        return io_list, []

    if suffix not in IO_SUFFIXES:
        return [], [_err(filename, 0, "file", "GF_UPLOAD_EXT_UNSUPPORTED",
                         f"不支持的 IO 表格式 {suffix or '(无后缀)'}，仅支持 .xlsx/.xlsm/.csv/.pdf")]

    is_workbook = suffix in {".xlsx", ".xlsm"}
    raw_bytes = b""
    text = ""
    public_entries: list[dict[str, str]] = []

    if item.is_paste:
        text = item.text
        if not text.strip():
            return [], [_err(filename, 0, "file", "GF_UPLOAD_EMPTY_BATCH", "粘贴内容为空")]
        raw_bytes = text.encode("utf-8")
    else:
        if len(item.data) > IO_MAX_FILE_BYTES:
            return [], [_err(filename, 0, "file", "GF_UPLOAD_FILE_TOO_LARGE",
                             f"IO 文件 {len(item.data)}B 超过单文件上限 {IO_MAX_FILE_BYTES}B")]
        raw_bytes = item.data
        if not is_workbook:
            # xlsx/xlsm 是二进制工作簿，不适用文本编码链；只有 CSV 才严格解码。
            text, decode_error = _decode_strict(item.data, IO_ENCODINGS, filename)
            if decode_error is not None:
                return [], [decode_error]

    if is_workbook:
        rows, rows_error = _read_xlsx_rows(raw_bytes, filename)
        if rows_error is not None:
            return [], [rows_error]
    else:
        rows = _csv_rows(text)
        # 复用底层公开解析器做交叉一致性：它会静默丢行，数量差异即视为失败。
        try:
            public_entries = _io.parse_plctags_csv(text)
        except _io.IoImportRejected as exc:
            errors.append(
                _err(filename, 0, "table", "GF_UPLOAD_IO_PARSE_FAILED",
                     f"底层解析器拒绝：{exc.message}（{exc.code}）")
            )
            public_entries = []

    mapping, data_start = _locate_header(rows)
    if mapping is None:
        errors.append(
            _err(filename, 0, "Name", "GF_UPLOAD_IO_HEADER_MISSING",
                 "IO 表未找到必需表头（Name + Data Type/Logical Address）")
        )
        return [], errors

    entries = _validate_io_rows(rows, mapping, data_start, filename, errors)
    if suffix not in {".xlsx", ".xlsm"} and not errors and len(public_entries) > len(entries):
        errors.append(
            _err(filename, 0, "table", "GF_UPLOAD_IO_SILENT_DROP",
                 f"底层解析器接受了 {len(public_entries)} 行而严格校验只接受 {len(entries)} 行，"
                 "存在静默近似风险")
        )
    return entries, errors


def _read_xlsx_rows(data: bytes, filename: str) -> tuple[list[list[Any]], ReceiptError | None]:
    """用内存字节读取第一个命中表头的 sheet；无写盘、无临时文件。"""
    try:
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
        from zipfile import BadZipFile
    except ImportError as exc:  # pragma: no cover —— openpyxl 为既有依赖
        return [], _err(filename, 0, "file", "GF_UPLOAD_IO_PARSE_FAILED", f"openpyxl 不可用：{exc}")

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, OSError, KeyError, ValueError) as exc:
        return [], _err(filename, 0, "file", "GF_UPLOAD_IO_PARSE_FAILED", f"xlsx 无法读取：{exc}")

    try:
        for worksheet in workbook.worksheets:
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            mapping, _ = _locate_header(rows)
            if mapping is not None:
                return rows, None  # 白名单：仅取第一个命中表头的 sheet
    finally:
        workbook.close()
    return [], _err(filename, 0, "table", "GF_UPLOAD_IO_HEADER_MISSING",
                    "xlsx 中未找到带 PLCTags 表头的工作表")


NESTED_STRUCT_RE = re.compile(r"(?i)^[A-Za-z_]\w*\s*:\s*Struct\b")


def _struct_depth(scl_body: str) -> int:
    """统计 SCL 文本中 STRUCT 的最大嵌套深度。

    同时识别独立 ``STRUCT`` 行与 ``<成员> : Struct`` 内联声明；
    ``END_STRUCT`` 闭合一层。注释以 ``//`` 剥离。
    """
    depth = 0
    maximum = 0
    for line in scl_body.splitlines():
        code = line.split("//", 1)[0].strip().rstrip(";").strip()
        upper = code.upper()
        if upper == "STRUCT" or NESTED_STRUCT_RE.match(code):
            depth += 1
            maximum = max(maximum, depth)
        elif upper.startswith("END_STRUCT"):
            depth = max(0, depth - 1)
    return maximum


def strict_validate_db(item: UploadItem) -> tuple[list[dict[str, Any]], list[ReceiptError]]:
    """严格解析单个 DB 文件（``.scl/.txt/.db`` 或粘贴 SCL 文本）。

    Returns:
        ``(db_struct_dicts, errors)``；errors 非空时调用方必须整批拒绝。
    """
    errors: list[ReceiptError] = []
    filename = item.display_name
    suffix = item.suffix

    if suffix in PDF_SUFFIXES:
        io_list, db_list, pdf_errors = strict_validate_pdf(item)
        if pdf_errors:
            return [], pdf_errors
        if io_list and not db_list:
            return [], [_err(filename, 0, "DATA_BLOCK", "GF_UPLOAD_DB_HEADER_MISSING", "该 PDF 为 IO 变量表而非 DB 块打印表")]
        return db_list, []

    if suffix not in DB_SUFFIXES:
        return [], [_err(filename, 0, "file", "GF_UPLOAD_EXT_UNSUPPORTED",
                         f"不支持的 DB 格式 {suffix or '(无后缀)'}，仅支持 .scl/.txt/.db/.pdf 或粘贴文本")]

    if item.is_paste:
        text = item.text
        if not text.strip():
            return [], [_err(filename, 0, "file", "GF_UPLOAD_EMPTY_BATCH", "粘贴内容为空")]
        if len(text.encode("utf-8")) > DB_MAX_FILE_BYTES:
            return [], [_err(filename, 0, "file", "GF_UPLOAD_FILE_TOO_LARGE",
                             "DB 文本超过单文件上限 2MB")]
    else:
        if len(item.data) > DB_MAX_FILE_BYTES:
            return [], [_err(filename, 0, "file", "GF_UPLOAD_FILE_TOO_LARGE",
                             f"DB 文件 {len(item.data)}B 超过单文件上限 {DB_MAX_FILE_BYTES}B")]
        text, decode_error = _decode_strict(item.data, DB_ENCODINGS, filename)
        if decode_error is not None:
            return [], [decode_error]

    if not DATA_BLOCK_HEADER_RE.search(text):
        errors.append(
            _err(filename, 0, "DATA_BLOCK", "GF_UPLOAD_DB_HEADER_MISSING",
                 "DB 文本缺少 DATA_BLOCK 声明")
        )
        return [], errors

    try:
        units = _db.parse_db_scl_all(text)
    except _db.DBImportRejected as exc:
        errors.append(
            _err(filename, 0, "DATA_BLOCK", "GF_UPLOAD_DB_PARSE_FAILED",
                 f"底层 DB 解析器拒绝：{exc.message}（{exc.code}）")
        )
        return [], errors

    if len(units) > DB_MAX_UNITS:
        errors.append(
            _err(filename, 0, "DATA_BLOCK", "GF_UPLOAD_DB_UNIT_LIMIT",
                 f"单次上传 DATA_BLOCK 数 {len(units)} 超过上限 {DB_MAX_UNITS}")
        )

    structs: list[dict[str, Any]] = []
    seen_db_names: set[str] = set()
    for unit_index, unit in enumerate(units, start=1):
        name = str(unit.get("name") or "")
        interface = list(unit.get("interface") or [])
        scl_body = str(unit.get("scl_body") or "")
        initial_assignments = dict(unit.get("initial_assignments") or {})

        if name in seen_db_names:
            errors.append(
                _err(filename, unit_index, "name", "GF_UPLOAD_DB_NAME_DUPLICATE",
                     f"DB 名 {name!r} 在批次内重复，整批拒绝")
            )
        seen_db_names.add(name)

        if len(interface) > DB_MAX_MEMBERS_PER_UNIT:
            errors.append(
                _err(filename, unit_index, "members", "GF_UPLOAD_DB_MEMBER_LIMIT",
                     f"DB {name!r} 成员 {len(interface)} 超过单 DB 上限 {DB_MAX_MEMBERS_PER_UNIT}")
            )

        depth = _struct_depth(scl_body)
        if depth > DB_MAX_STRUCT_DEPTH:
            errors.append(
                _err(filename, unit_index, "STRUCT", "GF_UPLOAD_DB_STRUCT_DEPTH",
                     f"DB {name!r} STRUCT 嵌套 {depth} 层超过上限 {DB_MAX_STRUCT_DEPTH}")
            )

        seen_paths: set[str] = set()
        members: list[dict[str, Any]] = []
        for member_index, raw_member in enumerate(interface, start=1):
            member_name = str(raw_member.get("name") or "")
            data_type = str(raw_member.get("data_type") or "")
            initial_value = str(raw_member.get("initial_value") or "").strip().rstrip(";").strip()
            comment = str(raw_member.get("comment") or "")

            if member_name in seen_paths:
                errors.append(
                    _err(filename, member_index, "name", "GF_UPLOAD_DB_MEMBER_DUPLICATE",
                         f"成员点路径 {member_name!r} 在 DB {name!r} 内重复")
                )
            seen_paths.add(member_name)

            array_match = ARRAY_RE.match(data_type)
            if array_match:
                lower, upper = int(array_match.group(1)), int(array_match.group(2))
                if not (0 <= lower <= upper <= 65535):
                    errors.append(
                        _err(filename, member_index, "data_type", "GF_UPLOAD_DB_ARRAY_BOUNDS",
                             f"Array[{lower}..{upper}] 上下界须满足 0 ≤ a ≤ b ≤ 65535")
                    )
            elif "Array[" in data_type:
                errors.append(
                    _err(filename, member_index, "data_type", "GF_UPLOAD_DB_ARRAY_BOUNDS",
                         f"无法解析 Array 上下界：{data_type!r}")
                )

            if initial_value and not LITERAL_RE.match(initial_value):
                errors.append(
                    _err(filename, member_index, "initial_value", "GF_UPLOAD_DB_INITIAL_EXPRESSION",
                         f"BEGIN 初值 {initial_value!r} 非字面量，禁止表达式")
                )
            members.append(
                {
                    "name": member_name,
                    "data_type": data_type,
                    "initial_value": initial_value,
                    "comment": comment,
                    # 偏移按声明顺序确定性派生；无法证明与 TIA 实际字节偏移等价，
                    # 已在 compat_notes 显式标注，绝不静默近似。
                    "offset": member_index - 1,
                }
            )

        for path, value in initial_assignments.items():
            clean = str(value).strip().rstrip(";").strip()
            if clean and not LITERAL_RE.match(clean):
                errors.append(
                    _err(filename, 0, "BEGIN", "GF_UPLOAD_DB_INITIAL_EXPRESSION",
                         f"BEGIN 赋值 {path} := {clean!r} 非字面量，禁止表达式")
                )

        optimized = OPTIMIZED_ACCESS_RE.search(scl_body)
        structs.append(
            {
                "name": name,
                "optimized_access": str(optimized.group(1) if optimized else "FALSE"),
                "members": members,
                "initial_assignments": {
                    str(k): str(v).strip().rstrip(";").strip()
                    for k, v in initial_assignments.items()
                },
                "scl_body": scl_body,
            }
        )
    return structs, errors


def strict_validate_pdf(
    item: UploadItem,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[ReceiptError]]:
    """严格解析单个 TIA Portal PDF（自动识别 PLC 变量表或标准访问 DB 块）。"""
    filename = item.display_name
    if item.suffix not in PDF_SUFFIXES:
        return [], [], [
            _err(filename, 0, "file", "GF_UPLOAD_EXT_UNSUPPORTED", f"非 PDF 文件：{filename}")
        ]
    if len(item.data) > PDF_MAX_FILE_BYTES:
        return [], [], [
            _err(
                filename,
                0,
                "file",
                "GF_UPLOAD_FILE_TOO_LARGE",
                f"PDF 文件 {len(item.data)}B 超过上限 {PDF_MAX_FILE_BYTES}B",
            )
        ]
    raw_io, raw_dbs, errors = _pdf.parse_pdf_bytes(item.data, filename)
    if errors:
        return [], [], errors

    if raw_io:
        rows: list[list[str]] = [["Name", "Path", "Data Type", "Logical Address", "Comment"]]
        for entry in raw_io:
            rows.append(
                [
                    entry.get("name", ""),
                    entry.get("path", ""),
                    entry.get("data_type", ""),
                    entry.get("logical_address", ""),
                    entry.get("comment", ""),
                ]
            )
        mapping, data_start = _locate_header(rows)
        assert mapping is not None
        validated_io = _validate_io_rows(rows, mapping, data_start, filename, errors)
        return validated_io, [], errors

    if raw_dbs:
        validated_dbs: list[dict[str, Any]] = []
        for unit_idx, db in enumerate(raw_dbs, start=1):
            members = list(db.get("members") or [])
            if len(members) > DB_MAX_MEMBERS_PER_UNIT:
                errors.append(
                    _err(
                        filename,
                        unit_idx,
                        "members",
                        "GF_UPLOAD_DB_MEMBER_LIMIT",
                        f"DB {db.get('name')!r} 成员 {len(members)} 超过单 DB 上限 {DB_MAX_MEMBERS_PER_UNIT}",
                    )
                )
            seen_paths: set[str] = set()
            for m_idx, member in enumerate(members, start=1):
                m_name = str(member.get("name") or "")
                m_type = str(member.get("data_type") or "")
                m_init = str(member.get("initial_value") or "").strip()
                if m_name in seen_paths:
                    errors.append(
                        _err(
                            filename,
                            m_idx,
                            "name",
                            "GF_UPLOAD_DB_MEMBER_DUPLICATE",
                            f"成员点路径 {m_name!r} 在 DB {db.get('name')!r} 内重复",
                        )
                    )
                seen_paths.add(m_name)
                arr_match = ARRAY_RE.match(m_type)
                if arr_match:
                    lower, upper = int(arr_match.group(1)), int(arr_match.group(2))
                    if not (0 <= lower <= upper <= 65535):
                        errors.append(
                            _err(
                                filename,
                                m_idx,
                                "data_type",
                                "GF_UPLOAD_DB_ARRAY_BOUNDS",
                                f"Array[{lower}..{upper}] 上下界须满足 0 ≤ a ≤ b ≤ 65535",
                            )
                        )
                if m_init and not LITERAL_RE.match(m_init):
                    errors.append(
                        _err(
                            filename,
                            m_idx,
                            "initial_value",
                            "GF_UPLOAD_DB_INITIAL_EXPRESSION",
                            f"初值 {m_init!r} 非字面量，禁止表达式",
                        )
                    )
            validated_dbs.append(db)
        return [], validated_dbs, errors

    return [], [], [
        _err(filename, 0, "file", "GF_UPLOAD_PDF_UNRECOGNIZED", "PDF 未识别出有效 IO 表或 DB 块")
    ]


def _classify(item: UploadItem) -> str:
    """判定上传项类别：io / db / pdf / unknown。"""
    suffix = item.suffix
    if suffix in PDF_SUFFIXES and item.kind not in {"io", "db"}:
        return "pdf"
    if item.kind in {"io", "db", "pdf"}:
        return item.kind
    if suffix in IO_SUFFIXES:
        return "io"
    if suffix in DB_SUFFIXES:
        return "db"
    if suffix in PDF_SUFFIXES:
        return "pdf"
    return "unknown"


def parse_upload_batch(items: list[UploadItem]) -> ParseReceipt:
    """整批原子解析：任一明细失败 → ``status=rejected`` / ``items_accepted=0``。

    批次上限、跨文件符号名 / 绝对地址唯一性、DB 重名、成员总量均在此收口。
    回执默认 ``user_confirmed=False``；**确认前契约绝不冻结**（Q3）。
    """
    errors: list[ReceiptError] = []
    io_entries: list[dict[str, str]] = []
    db_structs: list[dict[str, Any]] = []
    files = [item.display_name for item in items]

    if not items:
        errors.append(_err("", 0, "batch", "GF_UPLOAD_EMPTY_BATCH", "上传批次为空"))
    if len(items) > MAX_FILES:
        errors.append(
            _err("", 0, "batch", "GF_UPLOAD_BATCH_TOO_MANY_FILES",
                 f"单批次 {len(items)} 个文件超过上限 {MAX_FILES}")
        )
    total_bytes = sum(len(item.data) + len(item.text.encode("utf-8")) for item in items)
    if total_bytes > MAX_BATCH_BYTES:
        errors.append(
            _err("", 0, "batch", "GF_UPLOAD_BATCH_TOO_LARGE",
                 f"批次总大小 {total_bytes}B 超过上限 {MAX_BATCH_BYTES}B")
        )

    for item in items:
        category = _classify(item)
        if category == "io":
            entries, item_errors = strict_validate_io(item)
            io_entries.extend(entries)
            errors.extend(item_errors)
        elif category == "db":
            structs, item_errors = strict_validate_db(item)
            db_structs.extend(structs)
            errors.extend(item_errors)
        elif category == "pdf":
            entries, structs, item_errors = strict_validate_pdf(item)
            io_entries.extend(entries)
            db_structs.extend(structs)
            errors.extend(item_errors)
        else:
            errors.append(
                _err(item.display_name, 0, "file", "GF_UPLOAD_EXT_UNSUPPORTED",
                     f"无法判定文件类别：{item.display_name}")
            )

    # 跨文件唯一性（fail-closed）
    name_owner: dict[str, str] = {}
    address_owner: dict[str, str] = {}
    for entry in io_entries:
        name = entry["name"]
        address = entry["logical_address"]
        if name in name_owner:
            errors.append(
                _err(name_owner[name], 0, "Name", "GF_UPLOAD_IO_NAME_DUPLICATE",
                     f"符号名 {name!r} 跨文件重复，整批拒绝")
            )
        name_owner[name] = entry.get("path") or name
        if address:
            if address in address_owner:
                errors.append(
                    _err(address_owner[address], 0, "Logical Address",
                         "GF_UPLOAD_IO_ADDR_DUPLICATE",
                         f"绝对地址 {address!r} 跨文件被多个符号占用，整批拒绝")
                )
            address_owner[address] = name

    if len(io_entries) > MAX_TOTAL_IO_ENTRIES:
        errors.append(
            _err("", 0, "batch", "GF_UPLOAD_IO_TOTAL_LIMIT",
                 f"IO 条目合计 {len(io_entries)} 超过上限 {MAX_TOTAL_IO_ENTRIES}")
        )
    total_members = sum(len(s["members"]) for s in db_structs)
    if total_members > MAX_TOTAL_DB_MEMBERS:
        errors.append(
            _err("", 0, "batch", "GF_UPLOAD_DB_TOTAL_MEMBER_LIMIT",
                 f"DB 成员合计 {total_members} 超过上限 {MAX_TOTAL_DB_MEMBERS}")
        )
    db_name_owner: dict[str, str] = {}
    for struct in db_structs:
        name = struct["name"]
        if name in db_name_owner:
            errors.append(
                _err("", 0, "DATA_BLOCK", "GF_UPLOAD_DB_NAME_DUPLICATE",
                     f"DB 名 {name!r} 跨文件重复，整批拒绝")
            )
        db_name_owner[name] = name

    symbols = [
        {"name": entry["name"], "raw": entry["logical_address"]}
        for entry in io_entries
    ]
    compat_notes = [
        "DB 成员偏移按 SCL 声明顺序确定性派生，非 TIA 实际字节偏移；"
        "无法证明等价，保留原样并标注，绝不静默近似",
        "上传格式（IO 表 / DB SCL 文本）不含 OB 编号与调用顺序、F/安全块来源，"
        "未虚构条目，ob_entries / safety_entries 留空",
    ]
    draft: dict[str, Any] = {
        "io_entries": io_entries,
        "db_structs": db_structs,
        "ob_entries": [],
        "safety_entries": [],
        "symbols": symbols,
        "compat_notes": compat_notes,
    }
    digest = sha256_hex(canonical_dumps({"files": files, "draft": draft, "errors": [e.to_dict() for e in errors]}))
    receipt_id = f"RCP_{digest[:12]}"

    if errors:
        return ParseReceipt(
            receipt_id=receipt_id,
            status="rejected",
            items_total=len(io_entries) + total_members,
            items_accepted=0,
            errors=errors,
            contract_draft_hash="",
            user_confirmed=False,
            files=files,
            draft={},
        )

    return ParseReceipt(
        receipt_id=receipt_id,
        status="parsed",
        items_total=len(io_entries) + total_members,
        items_accepted=len(io_entries) + total_members,
        errors=[],
        contract_draft_hash=sha256_prefixed(canonical_dumps(draft)),
        user_confirmed=False,
        files=files,
        draft=draft,
    )
