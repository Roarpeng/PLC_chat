"""行为等价性核对报告（文本级/地址级）——纯函数服务。

背景：交付包里的 ``io_retention`` 是重构构造时的「记账」，不是独立「验证」。
本模块在交付前对 before/after 两份画布做**独立的文本级核对**，把关键保全
主张变成可断言、可落盘的字段：

- ``io_addresses``  绝对地址（%I/%Q/%IW/%QW…）在新旧两侧的出现矩阵；
- ``io_verdict``    preserved / dropped（逐地址）/ added 判定与计数；
- ``statement_counts``  ``:=`` 赋值 + 独立调用语句的行级计数（口径见 method）；
- ``structure``     引擎报告摘要（ems 数 / AF 块数 / pending 数）；
- ``caveats``       诚实口径——这是文本级/地址级核对，**不是行为等价性证明**。

纯文本分析：不碰 TIA、不碰网络、不改画布。入参是画布 dict（兼容
CanvasState 序列化形态，字段用 dict/属性双通道读取）与引擎 report dict。
"""

from __future__ import annotations

import re
import time
from typing import Any

#: AF draft 块角色（新画布侧统计范围；键含 "::" 亦视为 AF draft）
_AF_DRAFT_ROLES = frozenset(
    {
        "Sequence",
        "CallEquipment",
        "CallUnit",
        "ControlNodes",
        "EmNodes",
        "OB",
        "StepToString",
        "CallEquipment_DB",
        "CallUnit_DB",
    }
)

#: 旧画布侧的显式 legacy 角色（重构后画布中被取代/待人工确认的块）
_LEGACY_ROLES = frozenset({"legacy_superseded", "af_pending_manual"})

#: 绝对地址：兼容 %I0.0 / %Q4.1 / %IW64 / %QW80 / %ID16 / %MD12，以及
#: %Idb… 变体与 %DB5.DBX0.0 形态；大小写归一后聚合
_ABS_ADDR_RE = re.compile(
    r"%(?:[IQM](?:DB)?[XBWD]?\d+(?:\.\d+)?|DB\d+(?:\.DB[XBWD]?\d+(?:\.\d+)?)?)",
    re.IGNORECASE,
)

#: 符号 IO 兜底：``:=`` 语句行上的带引号 tag 名（仅当块内无任何绝对地址）
_QUOTED_TAG_RE = re.compile(r'"([^"\r\n]{1,128})"')

#: 注释剔除：SCL 行注释 ``//`` 与块注释 ``(* *)``（不嵌套）
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"\(\*.*?\*\)", re.DOTALL)

#: 声明区剔除（仅语句计数用；地址提取**保留**声明区以覆盖 ``AT %Ix.x``）
_VAR_SECTION_RE = re.compile(r"\bVAR[A-Z_]*\b.*?\bEND_VAR\b", re.DOTALL | re.IGNORECASE)

#: 独立调用语句行：行首为 #局部名/标识符/带引号 tag，紧跟 ``(``（实参 ``:=`` 不重复计数）
_CALL_LINE_RE = re.compile(r'^(?:#\s*)?(?:"[^"\r\n]+"|[A-Za-z_][\w.$:]*)\s*\(')

#: 形似调用但不是调用的 SCL 关键字（防 ``IF (…) THEN`` 被误计为调用行）
_NON_CALL_KEYWORDS = frozenset(
    {
        "IF", "ELSIF", "ELSE", "THEN", "FOR", "TO", "BY", "DO", "WHILE",
        "REPEAT", "UNTIL", "CASE", "OF", "RETURN", "EXIT", "CONTINUE",
        "GOTO", "REGION", "BEGIN", "END", "VAR", "CONST", "STRUCT", "TYPE",
        "SUPER", "THIS",
    }
)

_IO_METHOD_TEXT = (
    "绝对地址按正则 %I/%Q/%M/%DB… 提取（含 X/B/W/D 宽度与 %Idb… 变体，"
    "大小写归一，声明区 AT 地址计入）；块内无任何绝对地址时，以 := 左/右值的"
    "带引号 tag 生成 sym: 前缀符号 IO 兜底。旧侧=重构前画布非 AF 块"
    "（含 legacy_superseded/af_pending_manual），交付侧=重构后画布的 AF draft 块"
    "加上以 legacy 角色保留的 pending/superseded 旧块（它们原样留在交付画布与"
    "TIA 工程中——dropped 只表示地址从交付物里真正消失）。"
)

_STATEMENT_METHOD_TEXT = (
    "剔除 // 与 (* *) 注释及 VAR…END_VAR 声明区后按行统计：每行 := 出现次数"
    "计为赋值语句；行首为 标识符/带引号tag( 的独立调用语句行计 1 次（实参中的 "
    ":= 不重复计数，IF/WHILE 等关键字行不误计）；跨行语句不做归并；CONST 初始值"
    "不剔除。total_legacy 为 0 时不计算 delta_pct（记 null）。"
)

_CAVEAT_TEXTS = [
    (
        "本报告是文本级/地址级保全核对，不是行为等价性证明：未做时序、扫描周期、"
        "语义或故障路径验证。"
    ),
    (
        "地址口径见 io_verdict.method；符号 IO（sym: 前缀）仅为无绝对地址块的兜底"
        "统计，不与绝对地址做同一性比对。"
    ),
    "statement 口径见 statement_counts.method；行级计数不等于逻辑复杂度等价。",
    (
        "dropped/added 是地址出现性差异，不等于语义丢失或新增（可能来自归并、重命名"
        "或结构重组），需人工核对。"
    ),
    (
        "交付侧包含以 legacy 角色保留的旧块（pending/superseded 原样交付）；被 AF "
        "取代的 superseded 旧块地址虽仍在交付物中，但其在 AF 结构中的对应驱动才是"
        "有效路径——本口径只证明地址未消失，不证明驱动路径等价。"
    ),
]


# ---------------------------------------------------------------- 字段读取 --


def _field(obj: Any, name: str, default: Any = "") -> Any:
    """dict 键 / 对象属性 双通道读取（兼容 dict 画布与 CanvasState 实例）。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _iter_blocks(canvas: Any) -> list[tuple[str, Any]]:
    """画布 → [(键, 块)] 列表；blocks 为 dict（常规）或 list（容错）。"""
    blocks = _field(canvas, "blocks", None)
    out: list[tuple[str, Any]] = []
    if isinstance(blocks, dict):
        out.extend((str(k), b) for k, b in blocks.items())
    elif isinstance(blocks, (list, tuple)):
        for b in blocks:
            out.append((str(_field(b, "name", "")), b))
    return out


def _block_name(key: str, block: Any) -> str:
    """展示名：优先块自带 name，缺省回落到画布键。"""
    return str(_field(block, "name", "") or "").strip() or key


def _block_scl_text(block: Any) -> str:
    """块的完整 SCL 文本：scl_body + networks[].scl_text 拼接。"""
    parts = [str(_field(block, "scl_body", "") or "")]
    nets = _field(block, "networks", None)
    if isinstance(nets, (list, tuple)):
        for net in nets:
            parts.append(str(_field(net, "scl_text", "") or ""))
    return "\n".join(p for p in parts if p)


def _af_role(block: Any) -> str:
    return str(_field(block, "af_role", "") or "").strip()


def _is_af_draft_block(key: str, block: Any) -> bool:
    """AF draft 判定：af_role ∈ AF 角色集，或键/名含 "::"（AF 生成键形态）。"""
    if _af_role(block) in _AF_DRAFT_ROLES:
        return True
    name = str(_field(block, "name", "") or "")
    return "::" in key or "::" in name


def _is_legacy_block(key: str, block: Any) -> bool:
    """legacy 判定：显式 legacy 角色，或（重构前画布的）非 AF 块。"""
    if _af_role(block) in _LEGACY_ROLES:
        return True
    return not _is_af_draft_block(key, block)


# ---------------------------------------------------------------- 文本处理 --


def _strip_comments(text: str) -> str:
    code = _BLOCK_COMMENT_RE.sub(" ", text)
    return _LINE_COMMENT_RE.sub("", code)


def _strip_declarations(text: str) -> str:
    return _VAR_SECTION_RE.sub(" ", text)


def extract_io_keys(text: str) -> tuple[set[str], bool]:
    """从一段 SCL 文本提取 IO 键集合。

    返回 ``(键集合, 是否符号兜底)``：有绝对地址时直接返回地址（大写归一）；
    一个都没有时，才把 ``:=`` 语句行上的带引号 tag 记为 ``sym:<tag>`` 兜底。
    """
    code = _strip_comments(text)
    addrs = {a.upper() for a in _ABS_ADDR_RE.findall(code)}
    if addrs:
        return addrs, False
    syms: set[str] = set()
    for line in code.splitlines():
        if ":=" not in line:
            continue
        for tag in _QUOTED_TAG_RE.findall(line):
            name = tag.strip()
            if name:
                syms.add(f"sym:{name}")
    return syms, bool(syms)


def count_scl_statements(text: str) -> int:
    """语句行级计数：``:=`` 赋值次数 + 独立调用语句行数（口径见 _STATEMENT_METHOD_TEXT）。"""
    code = _strip_declarations(_strip_comments(text))
    assignments = 0
    calls = 0
    for raw_line in code.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _CALL_LINE_RE.match(line):
            word = re.match(r'#?\s*"?([A-Za-z_][A-Za-z_0-9]*)', line)
            if not word or word.group(1).upper() not in _NON_CALL_KEYWORDS:
                calls += 1
                continue  # 调用实参里的 := 不重复计数
        assignments += line.count(":=")
    return assignments + calls


def _collect_io(
    blocks: list[tuple[str, Any]],
) -> tuple[dict[str, set[str]], set[str]]:
    """[(键, 块)] → (IO 键 → 出现块名集合, 使用符号兜底的块名集合)。"""
    io_map: dict[str, set[str]] = {}
    fallback_blocks: set[str] = set()
    for key, block in blocks:
        name = _block_name(key, block)
        keys, fallback = extract_io_keys(_block_scl_text(block))
        if fallback:
            fallback_blocks.add(name)
        for io_key in keys:
            io_map.setdefault(io_key, set()).add(name)
    return io_map, fallback_blocks


# ---------------------------------------------------------------- 报告摘要 --


def _count_ems(af_report: dict[str, Any]) -> int:
    """ems 数：兼容 report.ems（清单/计数）与 report.units[].ems（逐 Unit 求和）。"""
    ems = af_report.get("ems")
    if isinstance(ems, list):
        return len(ems)
    if isinstance(ems, (int, float)):
        return int(ems)
    total = 0
    units = af_report.get("units")
    if isinstance(units, list):
        for unit in units:
            if isinstance(unit, dict) and isinstance(unit.get("ems"), list):
                total += len(unit["ems"])
    return total


def _count_af_blocks(af_report: dict[str, Any]) -> int:
    """AF 块数：优先显式 af_blocks_count，回落 af_blocks_created 清单长度。"""
    value = af_report.get("af_blocks_count")
    if isinstance(value, (int, float)):
        return int(value)
    created = af_report.get("af_blocks_created")
    return len(created) if isinstance(created, list) else 0


def _count_pending(af_report: dict[str, Any]) -> int:
    """pending 数：兼容 int（计数）与 list（清单）。"""
    value = af_report.get("pending_blocks")
    if isinstance(value, list):
        return len(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


# ---------------------------------------------------------------- 主入口 --


def build_equivalence_report(
    before_canvas: dict,
    after_canvas: dict,
    af_report: dict,
) -> dict:
    """构建行为等价性核对报告（纯函数，文本级/地址级）。

    - ``before_canvas``：重构前画布（或重构后画布——此时按 af_role 取 legacy 块）；
    - ``after_canvas``：重构后画布——交付侧 = AF draft 块 + 以 legacy 角色保留的
      pending/superseded 旧块（它们原样留在交付画布与 TIA 工程中，地址未消失，
      dropped 只表示"地址从交付物里真正消失"）；
    - ``af_report``：引擎 report dict（ems/af_blocks_created/pending_blocks 等）。
    """
    legacy_pairs = [(k, b) for k, b in _iter_blocks(before_canvas) if _is_legacy_block(k, b)]
    af_pairs = [
        (k, b)
        for k, b in _iter_blocks(after_canvas)
        if _is_af_draft_block(k, b) or _af_role(b) in _LEGACY_ROLES
    ]

    legacy_io, legacy_fallback = _collect_io(legacy_pairs)
    af_io, _af_fallback = _collect_io(af_pairs)

    # 1) IO 出现矩阵（并集，键排序保证确定性）
    io_addresses: dict[str, dict[str, list[str]]] = {
        key: {
            "legacy_in": sorted(legacy_io.get(key, ())),
            "af_in": sorted(af_io.get(key, ())),
        }
        for key in sorted(legacy_io.keys() | af_io.keys())
    }

    # 2) 判定：preserved / dropped（逐地址）/ added
    legacy_keys = set(legacy_io)
    af_keys = set(af_io)
    preserved = sorted(legacy_keys & af_keys)
    dropped = sorted(legacy_keys - af_keys)
    added = sorted(af_keys - legacy_keys)
    io_verdict = {
        "preserved": preserved,
        "dropped": dropped,
        "added": added,
        "preserved_count": len(preserved),
        "dropped_count": len(dropped),
        "added_count": len(added),
        "io_preserved": not dropped,
        "symbolic_fallback_blocks": sorted(legacy_fallback),
        "method": _IO_METHOD_TEXT,
    }

    # 3) 语句计数（每旧块 / 每 AF draft 块 / 合计与变化率）
    legacy_stmts = {_block_name(k, b): count_scl_statements(_block_scl_text(b)) for k, b in legacy_pairs}
    af_stmts = {_block_name(k, b): count_scl_statements(_block_scl_text(b)) for k, b in af_pairs}
    total_legacy = sum(legacy_stmts.values())
    total_af = sum(af_stmts.values())
    delta_pct = (
        round((total_af - total_legacy) / total_legacy * 100.0, 2) if total_legacy else None
    )
    statement_counts = {
        "method": _STATEMENT_METHOD_TEXT,
        "legacy_blocks": dict(sorted(legacy_stmts.items())),
        "af_blocks": dict(sorted(af_stmts.items())),
        "total_legacy": total_legacy,
        "total_af": total_af,
        "delta_pct": delta_pct,
    }

    # 4) 引擎报告摘要
    pending_value = af_report.get("pending_blocks")
    pending_names = list(pending_value) if isinstance(pending_value, list) else []
    structure = {
        "ems_count": _count_ems(af_report),
        "af_blocks_count": _count_af_blocks(af_report),
        "pending_blocks_count": _count_pending(af_report),
        "pending_blocks": pending_names,
    }

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inputs": {
            "before_project_name": str(_field(before_canvas, "project_name", "") or ""),
            "after_project_name": str(_field(after_canvas, "project_name", "") or ""),
            "legacy_blocks_scanned": len(legacy_pairs),
            "af_blocks_scanned": len(af_pairs),
        },
        "io_addresses": io_addresses,
        "io_verdict": io_verdict,
        "statement_counts": statement_counts,
        "structure": structure,
        "caveats": list(_CAVEAT_TEXTS),
    }


__all__ = [
    "build_equivalence_report",
    "count_scl_statements",
    "extract_io_keys",
]
