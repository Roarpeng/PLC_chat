"""回写前毫秒级静态门禁：V3.0 蓝图 Tab5 的规则 1~5。

为什么要有这一层：调用 Openness 编译一次要 2~4 秒，而下面 5 条规则全是
正则 / 轻量词法级判断，毫秒级就能拦掉绝大多数低级错误，省掉 IPC 往返。

本模块不追求完整 AST，只追求"能拦住、不误伤"。与 scl_precheck.py 的分工：
scl_precheck 管 END 配对与声明区注释，本模块只管蓝图 Tab5 的五条规则，
两者互补、互不调用；也不修改 writeback_contract 的任何字段语义。

规则一览：
    R1 符号作用域定界符：局部变量必须 #，含中文/空格的全局符号必须 "..."。
    R2 单线圈唯一性：物理输出不得出现在 := 左侧，且全站只能被一个块写。
    R3 状态机内禁放有状态指令：CASE 区间内禁 TON/TOF/TP/R_TRIG/F_TRIG。
    R4 数据类型隐式转换：Int 与 DInt/Real 比较、Time 变量赋裸数字。
    R5 UTF-8 BOM：含中文的块必须由调用方声明以 UTF-8 BOM 写盘。
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from plc_engine.writeback_contract import BlockArtifact

__all__ = [
    "Finding",
    "LintError",
    "assert_clean",
    "lint_block",
    "lint_bundle",
]


@dataclass
class Finding:
    """一条静态门禁结论。line 为 1-based；定位不到给 None。"""

    rule: str  # "R1".."R5"
    severity: str  # "error" | "warning"
    block: str
    line: int | None
    message: str


class LintError(ValueError):
    """findings 含 error 时由 assert_clean 抛出。"""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        errors = [f for f in findings if f.severity == "error"]
        preview = "；".join(f"[{f.rule}] {f.block}:L{f.line} {f.message}" for f in errors[:5])
        more = f"（共 {len(errors)} 条 error）" if len(errors) > 5 else ""
        super().__init__(f"静态门禁未通过：{preview}{more}")


# --------------------------------------------------------------------------
# 词法预处理：把注释 / 字符串抹白，但保持字符偏移与换行完全不变，
# 这样所有规则的报错行号都能直接映射回原文。
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Views:
    """同一份 SCL 的三种视图（长度与原文严格相等）。"""

    raw: str  # 原文
    code: str  # 注释抹白（保留字符串与双引号标识符）
    nostr: str  # 注释 + 单引号字符串内容抹白（保留双引号标识符，供 R2/R3/R4 用）
    masked: str  # 注释 + 所有引号内容抹白（供 R1 找"裸写"标识符用）
    line_starts: list[int] = field(default_factory=list)
    paren_depth: list[int] = field(default_factory=list)  # 每个偏移处的圆括号深度

    def line_of(self, offset: int) -> int:
        """把字符偏移换成 1-based 行号。"""
        return bisect.bisect_right(self.line_starts, offset)


def _blank(buffers: Sequence[list[str]], start: int, stop: int) -> None:
    for buf in buffers:
        for k in range(start, min(stop, len(buf))):
            if buf[k] != "\n":
                buf[k] = " "


def _build_views(src: str) -> _Views:
    n = len(src)
    code = list(src)
    nostr = list(src)
    masked = list(src)
    i = 0
    while i < n:
        ch = src[i]
        # // 行注释
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            _blank((code, nostr, masked), i, j)
            i = j
            continue
        # (* 块注释 *)，支持嵌套
        if ch == "(" and i + 1 < n and src[i + 1] == "*":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if src.startswith("(*", j):
                    depth += 1
                    j += 2
                elif src.startswith("*)", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            _blank((code, nostr, masked), i, min(j, n))
            i = min(j, n)
            continue
        # 引号：单引号是字符串字面量，双引号是标识符（两者都要保护内容）
        if ch in "\"'":
            quote = ch
            j = i + 1
            while j < n and src[j] != quote and src[j] != "\n":
                j += 1
            stop = j if j < n and src[j] == quote else min(j, n)
            if quote == "'":
                _blank((nostr, masked), i + 1, stop)
            else:
                _blank((masked,), i + 1, stop)
            i = j + 1 if j < n and src[j] == quote else min(j, n)
            continue
        i += 1

    starts = [0]
    for idx, c in enumerate(src):
        if c == "\n":
            starts.append(idx + 1)
    masked_str = "".join(masked)
    depths = [0] * (len(src) + 1)
    depth = 0
    for idx, c in enumerate(masked_str):
        depths[idx] = depth
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
    depths[len(src)] = depth
    return _Views(
        raw=src,
        code="".join(code),
        nostr="".join(nostr),
        masked=masked_str,
        line_starts=starts,
        paren_depth=depths,
    )


# --------------------------------------------------------------------------
# 声明段解析：抽取 VAR..END_VAR 区间与"名字 -> 类型"表
# --------------------------------------------------------------------------

_VAR_HEADER_RE = re.compile(
    r"(?im)^[ \t\r]*(VAR(?:_[A-Z]+)?|VAR[ \t]+(?:CONSTANT|RETAIN|NON_RETAIN|PERSISTENT))[ \t\r]*$"
)
_END_VAR_RE = re.compile(r"(?im)^[ \t\r]*END_VAR\b")
_NAME_LIST_RE = re.compile(r"^([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)")
_TYPE_TOKEN_RE = re.compile(r'^"?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)')
_AT_ADDR_RE = re.compile(r"(?i)\s+AT\s+%[IQM][\w.]*\s*$")
_STRUCT_TAIL_RE = re.compile(r"(?i)^(?:ARRAY\s*\[[^\]]*\]\s+OF\s+)?STRUCT\b")


@dataclass(frozen=True)
class _Section:
    header: str  # 大写段名，如 VAR_INPUT
    start: int  # 段首偏移
    body_start: int
    body_end: int


def _var_sections(code: str) -> list[_Section]:
    """找出全部 VAR..END_VAR 声明区间（不配对则丢弃尾部孤立段）。"""
    out: list[_Section] = []
    pos = 0
    while True:
        m = _VAR_HEADER_RE.search(code, pos)
        if m is None:
            break
        end = _END_VAR_RE.search(code, m.end())
        if end is None:
            break
        out.append(_Section(header=m.group(1).upper(), start=m.start(), body_start=m.end(), body_end=end.start()))
        pos = end.end()
    return out


def _parse_declarations(code: str, sections: Sequence[_Section]) -> dict[str, str]:
    """返回 {大写变量名: 大写类型名}。STRUCT 内部成员不计入（它们是 .member）。"""
    types: dict[str, str] = {}
    for sec in sections:
        struct_depth = 0
        pending = ""
        for raw in code[sec.body_start : sec.body_end].splitlines():
            line = raw.strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("END_STRUCT"):
                struct_depth = max(0, struct_depth - 1)
                pending = ""
                continue
            if struct_depth:
                if "STRUCT" in upper:
                    struct_depth += 1
                continue
            if ":" not in line:
                # 多行名字列表：xStart,
                pending = f"{pending} {line}"
                continue
            stmt = f"{pending} {line}".strip()
            pending = ""
            head, _, tail = stmt.partition(":")
            tail = tail.strip()
            if tail.startswith("=") or not head:
                continue
            type_match = _TYPE_TOKEN_RE.match(tail)
            if type_match is None:
                continue
            type_name = type_match.group(1).upper()
            body = _AT_ADDR_RE.sub("", head)
            name_match = _NAME_LIST_RE.match(body.strip())
            if name_match is None:
                continue
            for name in name_match.group(1).split(","):
                name = name.strip()
                if name:
                    types[name.upper()] = type_name
            if _STRUCT_TAIL_RE.match(tail):
                struct_depth = 1
    return types


def _statement_start(code: str, sections: Sequence[_Section], kind: str) -> int | None:
    """语句区起点：最后一个声明段之后的 BEGIN。找不到 BEGIN 视为没有语句区。"""
    if kind not in ("FB", "FC", "OB"):
        return None
    base = max((s.body_end for s in sections), default=0)
    m = re.search(r"(?im)^[ \t\r]*BEGIN\b", code[base:])
    if m is not None:
        return base + m.start()
    # 没有 BEGIN 说明这不是可执行块（或源被截断），不做语句级检查，
    # 否则会把块头属性（TITLE = 中文标题）当成语句误报。
    return None


# --------------------------------------------------------------------------
# R1 符号作用域定界符
# --------------------------------------------------------------------------

_IDENT_TOKEN_RE = re.compile(r"(?<!\w)([A-Za-z_][A-Za-z0-9_]*)(?!\w)")
# 裸写的"含中文"标识符：以 ASCII 字母开头、后面跟中文
_CJK_IDENT_RE = re.compile(r"(?<![\w#.\"])([A-Za-z_]\w*[\u4e00-\u9fff]\w*)")

# 关键字 / 类型名 / 常用内置函数，不参与"裸用"判定
_NON_VARIABLE = {
    "IF", "THEN", "ELSE", "ELSIF", "END_IF", "CASE", "OF", "END_CASE",
    "FOR", "TO", "BY", "DO", "END_FOR", "WHILE", "END_WHILE", "REPEAT",
    "UNTIL", "END_REPEAT", "EXIT", "CONTINUE", "RETURN", "GOTO", "GOTO_END",
    "AND", "OR", "XOR", "NOT", "MOD", "TRUE", "FALSE",
    "BEGIN", "END", "VAR", "END_VAR", "CONSTANT", "STRUCT", "END_STRUCT",
    "REGION", "END_REGION", "TITLE", "AUTHOR", "NAME", "VERSION", "FAMILY",
    "COMMENT", "KNOW_HOW_PROTECT", "ATTRIBUTE", "AT",
    "FUNCTION_BLOCK", "END_FUNCTION_BLOCK", "FUNCTION", "END_FUNCTION",
    "ORGANIZATION_BLOCK", "END_ORGANIZATION_BLOCK", "DATA_BLOCK", "END_DATA_BLOCK",
    "TYPE", "END_TYPE", "VARIANT",
    "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR_STAT",
    "VAR_CONSTANT", "VAR_PERSISTENT",
    "BOOL", "BYTE", "WORD", "DWORD", "LWORD", "INT", "DINT", "SINT", "UINT",
    "UDINT", "USINT", "LINT", "REAL", "LREAL", "TIME", "LTIME", "DATE",
    "TIME_OF_DAY", "TOD", "DATE_AND_TIME", "DT", "S5TIME", "STRING", "WSTRING",
    "CHAR", "WCHAR", "VOID", "ANY", "ARRAY", "POINTER", "REFERENCE",
    "RETAIN", "NON_RETAIN", "PERSISTENT",
    "ABS", "MIN", "MAX", "LIMIT", "SEL", "MUX", "SHL", "SHR", "ROL", "ROR",
    "SQRT", "EXP", "LN", "LOG", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN",
    "TRUNC", "ROUND", "CEIL", "FLOOR", "MOVE", "MOVE_BLK", "FILL_BLK",
    "BLKMOV", "CONCAT", "LEN", "LEFT", "RIGHT", "MID", "INSERT", "DELETE",
    "REPLACE", "FIND", "EQ", "NE", "LT", "GT", "LE", "GE",
    "TON", "TOF", "TP", "R_TRIG", "F_TRIG", "CTU", "CTD", "CTUD", "SR", "RS",
}


def _has_prefix(text: str, start: int) -> bool:
    """判断 start 处的标识符是否已被正确定界（前置 # " . % $ 或更长标识符）。"""
    prev = start - 1
    if prev < 0:
        return False
    ch = text[prev]
    if ch.isalnum() or ch in '_#"%.$':
        return True
    if ch in " \t":
        # 允许 `"DB" . x` 这种带空格的成员访问，但不把 `IF x` 当成已定界
        q = prev
        while q >= 0 and text[q] in " \t":
            q -= 1
        return q >= 0 and text[q] in '."'
    return False


def _is_named_argument(views: _Views, start: int, end: int) -> bool:
    """判断标识符是否是 FB 调用的命名实参（形如 `#Cyl_Lift(i_xSen := ...)`）。

    命名实参用的是被调块的形式参数名，不需要 # 前缀，也不能算本块变量引用。
    判据：位于圆括号内 + 后面紧跟 `:=`（输入实参）或 `=>`（输出绑定）。
    """
    if views.paren_depth[start] <= 0:
        return False
    i = end
    while i < len(views.masked) and views.masked[i] in " \t":
        i += 1
    return views.masked.startswith((":=", "=>"), i)


def _rule1(block: BlockArtifact, views: _Views, sections: Sequence[_Section], types: dict[str, str]) -> list[Finding]:
    start = _statement_start(views.code, sections, block.kind)
    if start is None:
        # UDT / GLOBAL_DB / INSTANCE_DB 没有语句区：中文裸标识符检查在这里
        # 会全是误报（DB 字段在外部源里本来就裸写），故整条跳过。
        return []
    out: list[Finding] = []
    region_lines = {
        i
        for i, text in enumerate(views.code.splitlines(), 1)
        if text.strip().upper().startswith(("REGION", "END_REGION"))
    }

    # 1a. 声明过的局部变量必须带 #
    for m in _IDENT_TOKEN_RE.finditer(views.masked, start):
        name = m.group(1)
        upper = name.upper()
        if upper in _NON_VARIABLE or "_TO_" in upper or upper not in types:
            continue
        line = views.line_of(m.start())
        if line in region_lines:
            continue
        if _has_prefix(views.masked, m.start()):
            continue  # #x / "DB".x / a.b / %Qx 都属于已定界写法
        if _is_named_argument(views, m.start(), m.end()):
            continue  # #FB(iParam := ...) 里的 iParam 是被调块的形式参数名
        out.append(
            Finding(
                rule="R1",
                severity="error",
                block=block.name,
                line=line,
                message=f"局部变量 {name} 缺少 # 前缀：块内声明的变量必须写 #{name}",
            )
        )

    # 1b. 语句区里裸写的含中文标识符必须用英文双引号
    for m in _CJK_IDENT_RE.finditer(views.masked, start):
        name = m.group(1)
        line = views.line_of(m.start())
        if line in region_lines:
            continue
        out.append(
            Finding(
                rule="R1",
                severity="error",
                block=block.name,
                line=line,
                message=f'标识符 {name} 含中文：全局符号必须用英文双引号定界，写成 "{name}"',
            )
        )
    return out


# --------------------------------------------------------------------------
# R2 单线圈唯一性
# --------------------------------------------------------------------------

_PHYS_Q_SEG_RE = re.compile(r"(?i)^Q[\d_.]")


def _split_path(token: str) -> list[tuple[str, bool]]:
    """把 `"DB_IO".Q0_1` 拆成 [("DB_IO", True), ("Q0_1", False)]。"""
    parts: list[tuple[str, bool]] = []
    buf: list[str] = []
    quoted = False
    in_quote = False
    for ch in token:
        if in_quote:
            if ch == '"':
                in_quote = False
            else:
                buf.append(ch)
        elif ch == '"':
            in_quote = True
            quoted = True
        elif ch == ".":
            parts.append(("".join(buf), quoted))
            buf = []
            quoted = False
        else:
            buf.append(ch)
    parts.append(("".join(buf), quoted))
    return parts


def _is_physical_q(token: str) -> bool:
    """判断一个符号是不是物理输出（%Q0.0 / "Q0.0" / "DB_IO".Q0_1）。"""
    if not token:
        return False
    if token.startswith("%"):
        return token[:2].upper() == "%Q"
    parts = _split_path(token)
    if not parts or not parts[-1][0]:
        return False
    if len(parts) == 1:
        # 单段：必须本身以 Q+数字/下划线开头，避免把 "Qty" 当成输出
        return bool(_PHYS_Q_SEG_RE.match(parts[0][0]))
    # 多段：首段必须是引号包住的 DB，末段是 Q 成员；
    # 这样 #inst.q1 这类普通实例成员不会被误判成物理输出。
    return parts[0][1] and bool(_PHYS_Q_SEG_RE.match(parts[-1][0]))


def _canonical(token: str) -> str:
    return re.sub(r"\s+", "", token).upper()


def _assignment_targets(text: str) -> list[tuple[int, str]]:
    """扫描 `:=` 并往前取出赋值左值，返回 [(偏移, 归一化左值)]。"""
    out: list[tuple[int, str]] = []
    pos = 0
    while True:
        hit = text.find(":=", pos)
        if hit < 0:
            return out
        pos = hit + 2
        j = hit - 1
        while j >= 0 and text[j] in " \t":
            j -= 1
        end = j + 1
        k = j
        while k >= 0:
            ch = text[k]
            if ch in " \t":
                t = k
                while t >= 0 and text[t] in " \t":
                    t -= 1
                if t >= 0 and text[t] == ".":  # 允许 `"DB" . Q0` 这种带空格的写法
                    k = t
                    continue
                break
            if ch.isalnum() or ch in '_#%."$':
                k -= 1
                continue
            break
        token = re.sub(r"\s+", "", text[k + 1 : end])
        if token:
            out.append((hit, token))


def _rule2(block: BlockArtifact, views: _Views) -> tuple[list[Finding], dict[str, list[tuple[int, str]]]]:
    out: list[Finding] = []
    assigned: dict[str, list[tuple[int, str]]] = {}
    for offset, token in _assignment_targets(views.nostr):
        if not _is_physical_q(token):
            continue
        assigned.setdefault(_canonical(token), []).append((views.line_of(offset), token))

    for hits in assigned.values():
        line0, raw0 = hits[0]
        out.append(
            Finding(
                rule="R2",
                severity="error",
                block=block.name,
                line=line0,
                message=(
                    f'物理输出 {raw0} 出现在 := 左侧：物理输出必须经由元件 FB 调用的输出绑定赋值'
                    f'（形如 q_xOutHome => {raw0}），中间量请改用 #statXxx'
                ),
            )
        )
        if len(hits) > 1:
            where = "、".join(f"L{line}" for line, _ in hits)
            out.append(
                Finding(
                    rule="R2",
                    severity="error",
                    block=block.name,
                    line=hits[1][0],
                    message=(
                        f"同一块内物理输出 {raw0} 被赋值 {len(hits)} 次（{where}）："
                        f"单线圈唯一性铁律要求每个输出只允许一处线圈"
                    ),
                )
            )
    return out, assigned


# --------------------------------------------------------------------------
# R3 状态机内禁放有状态指令
# --------------------------------------------------------------------------

_CASE_TOK_RE = re.compile(r"(?i)\b(END_CASE|CASE)\b")
_STATEFUL_CALL_RE = re.compile(r"(?i)\b(TON|TOF|TP|R_TRIG|F_TRIG)\s*\(")
_INSTANCE_CALL_RE = re.compile(r"(?i)#([A-Za-z_]\w*)\s*\(")
_STATEFUL_TYPES = {"TON", "TOF", "TP", "R_TRIG", "F_TRIG"}


def _case_regions(text: str, views: _Views) -> list[tuple[int, int, int]]:
    """返回 [(CASE 起点, 结束偏移, CASE 所在行)]，内含嵌套，未闭合的延到文末。"""
    stack: list[tuple[int, int]] = []
    regions: list[tuple[int, int, int]] = []
    for m in _CASE_TOK_RE.finditer(text):
        if m.group(1).upper() == "END_CASE":
            if stack:
                start, line = stack.pop()
                regions.append((start, m.end(), line))
        else:
            stack.append((m.start(), views.line_of(m.start())))
    for start, line in stack:
        regions.append((start, len(text), line))
    return regions


def _innermost_case(regions: Sequence[tuple[int, int, int]], pos: int) -> tuple[int, int, int] | None:
    best: tuple[int, int, int] | None = None
    for region in regions:
        if region[0] <= pos < region[1] and (best is None or region[0] > best[0]):
            best = region
    return best


def _rule3(block: BlockArtifact, views: _Views, types: dict[str, str]) -> list[Finding]:
    regions = _case_regions(views.nostr, views)
    if not regions:
        return []
    out: list[Finding] = []
    seen: set[int] = set()

    for m in _STATEFUL_CALL_RE.finditer(views.nostr):
        call = _innermost_case(regions, m.start())
        if call is None:
            continue
        seen.add(m.start())
        out.append(_r3_finding(block, views, m.start(), call[2], m.group(1), "定时器/边沿指令"))

    for m in _INSTANCE_CALL_RE.finditer(views.nostr):
        if m.start() in seen:
            continue
        name = m.group(1)
        type_name = types.get(name.upper())
        if type_name not in _STATEFUL_TYPES:
            continue  # #Cyl_Lift(...) 这类元件 FB 调用允许留在 CASE 内
        call = _innermost_case(regions, m.start())
        if call is None:
            continue
        out.append(_r3_finding(block, views, m.start(), call[2], name, f"{type_name} 状态实例"))
    return out


def _r3_finding(block: BlockArtifact, views: _Views, offset: int, case_line: int, what: str, kind: str) -> Finding:
    return Finding(
        rule="R3",
        severity="error",
        block=block.name,
        line=views.line_of(offset),
        message=(
            f"CASE（第 {case_line} 行）内出现 {what}（{kind}）：跳步后定时器/边沿状态会残留，"
            f"请移到 CASE 外，或封装进元件 FB 内部"
        ),
    )


# --------------------------------------------------------------------------
# R4 数据类型隐式转换（启发式，宁可漏报）
# --------------------------------------------------------------------------

_COMPARE_RE = re.compile(
    r"(?<![\w.#])(#?[A-Za-z_]\w*)\s*(<=|>=|<>|=|<|>)\s*(#?[A-Za-z_]\w*)(?![\w(])"
)
_INT_TYPES = {"INT", "SINT", "UINT", "USINT"}
_DINT_TYPES = {"DINT", "UDINT"}
_REAL_TYPES = {"REAL", "LREAL"}
_BARE_NUMBER_RE = re.compile(r"(?<![\w#.])(#?[A-Za-z_]\w*)\s*:=\s*(\d+(?:\.\d+)?)\s*(?=[;,)\r\n]|$)")
_TIME_DECL_DEFAULT_RE = re.compile(
    r"(?im)^[ \t\r]*(#?[A-Za-z_]\w*)\s*(?:AT\s+%[IQM][\w.]*\s*)?:\s*(TIME|S5TIME)\s*:=\s*(\d+(?:\.\d+)?)"
)


def _rule4(block: BlockArtifact, views: _Views, sections: Sequence[_Section], types: dict[str, str]) -> list[Finding]:
    out: list[Finding] = []
    start = _statement_start(views.code, sections, block.kind)

    # 4a. Int 与 DInt/Real 直接比较
    if start is not None:
        for m in _COMPARE_RE.finditer(views.nostr, start):
            left, op, right = m.group(1), m.group(2), m.group(3)
            left_type = types.get(left.lstrip("#").upper())
            right_type = types.get(right.lstrip("#").upper())
            if left_type is None or right_type is None:
                continue  # 任一侧类型不明就不猜，避免误报
            if not _mixed_numeric(left_type, right_type):
                continue
            out.append(
                Finding(
                    rule="R4",
                    severity="warning",
                    block=block.name,
                    line=views.line_of(m.start()),
                    message=(
                        f"比较 {left}({left_type}) {op} {right}({right_type})："
                        f"Int 与 DInt/Real 直接比较会触发隐式转换，请显式转换（如 INT_TO_DINT / INT_TO_REAL）"
                    ),
                )
            )

    # 4b. Time 变量赋裸数字
    for m in _BARE_NUMBER_RE.finditer(views.nostr):
        var = m.group(1).lstrip("#").upper()
        if types.get(var) not in ("TIME", "S5TIME"):
            continue
        out.append(_r4_time_finding(block, views, m.start(), m.group(1), m.group(2)))
    for m in _TIME_DECL_DEFAULT_RE.finditer(views.nostr):
        out.append(_r4_time_finding(block, views, m.start(3), m.group(1), m.group(3)))
    return out


def _mixed_numeric(left_type: str, right_type: str) -> bool:
    def cls(t: str) -> str:
        if t in _INT_TYPES:
            return "int"
        if t in _DINT_TYPES:
            return "dint"
        if t in _REAL_TYPES:
            return "real"
        return ""

    a, b = cls(left_type), cls(right_type)
    return (a == "int" and b in ("dint", "real")) or (b == "int" and a in ("dint", "real"))


def _r4_time_finding(block: BlockArtifact, views: _Views, offset: int, var: str, value: str) -> Finding:
    return Finding(
        rule="R4",
        severity="warning",
        block=block.name,
        line=views.line_of(offset),
        message=(
            f"Time 变量 {var} 被赋裸数字 {value}：时间常量必须写 T#../TIME#../S5T#.. 形式"
            f"（如 T#{value}ms），否则博途会当成整数处理"
        ),
    )


# --------------------------------------------------------------------------
# 单块 / 整包入口
# --------------------------------------------------------------------------


@dataclass
class _BlockScan:
    findings: list[Finding] = field(default_factory=list)
    # 物理输出 -> [(行号, 原样符号)]，供 bundle 层做跨块重复检查
    q_assignments: dict[str, list[tuple[int, str]]] = field(default_factory=dict)


def _sort(findings: list[Finding]) -> list[Finding]:
    findings.sort(key=lambda f: (f.line is None, f.line or 0, f.rule))
    return findings


_IF_COND_RE = re.compile(r"\bIF\s+([\s\S]*?)\s+THEN\b", re.IGNORECASE)


def _rule6(block: BlockArtifact, views: _Views) -> list[Finding]:
    """R6 形式化死锁与恒假矛盾检测 (SMT Deadlock Guard)。"""
    out: list[Finding] = []
    for m in _IF_COND_RE.finditer(views.nostr):
        cond_text = m.group(1).strip()
        if not cond_text:
            continue
        m_contradiction = re.search(r'([#\w".]+)\s+AND\s+NOT\s+\1\b', cond_text, re.IGNORECASE)
        if m_contradiction:
            var_name = m_contradiction.group(1)
            out.append(
                Finding(
                    rule="R6",
                    severity="error",
                    block=block.name,
                    line=views.line_of(m.start()),
                    message=(
                        f"条件中存在形式化死锁（恒假矛盾项 {var_name} AND NOT {var_name}）："
                        f"该条件在数学上恒为 FALSE（UNSAT），会导致工步永远无法转移或动作死锁"
                    ),
                )
            )
    return out


def _scan_block(block: BlockArtifact) -> _BlockScan:
    views = _build_views(block.source)
    sections = _var_sections(views.code)
    types = _parse_declarations(views.code, sections)

    findings: list[Finding] = []
    findings.extend(_rule1(block, views, sections, types))
    r2_findings, q_assignments = _rule2(block, views)
    findings.extend(r2_findings)
    findings.extend(_rule3(block, views, types))
    findings.extend(_rule4(block, views, sections, types))
    findings.extend(_rule6(block, views))
    return _BlockScan(findings=_sort(findings), q_assignments=q_assignments)


def lint_block(block: BlockArtifact) -> list[Finding]:
    """单块静态门禁：R1~R4。跨块的双写由 lint_bundle 负责。"""
    return _scan_block(block).findings


_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def lint_bundle(blocks: Sequence[BlockArtifact], *, bom_enabled: bool = True) -> list[Finding]:
    """整包静态门禁：逐块 R1~R4 + 跨块 R2 + 包级 R5。

    bom_enabled=False 表示调用方没有声明"以 UTF-8 BOM 写盘"，
    此时含中文的块会被 R5 提醒。默认 True（正常回写链路都带 BOM）。
    """
    findings: list[Finding] = []
    owners: dict[str, list[tuple[str, int, str]]] = {}

    for block in blocks:
        scan = _scan_block(block)
        findings.extend(scan.findings)
        for canonical, hits in scan.q_assignments.items():
            for line, raw in hits:
                owners.setdefault(canonical, []).append((block.name, line, raw))

    # 跨块双写：同一个物理输出被两个及以上块写
    for hits in owners.values():
        names = {name for name, _, _ in hits}
        if len(names) < 2:
            continue
        ordered = sorted(names)
        detail = "、".join(f"{name}:L{line}" for name, line, _ in hits)
        findings.append(
            Finding(
                rule="R2",
                severity="error",
                block=" / ".join(ordered),
                line=hits[0][1],
                message=(
                    f"物理输出 {hits[0][2]} 被多个块同时赋值（{detail}）："
                    f"单线圈唯一性铁律要求全站只有一个块驱动该输出，请改为输出到 #statXxx 再统一汇总"
                ),
            )
        )

    # R5 含中文但未声明 BOM
    if not bom_enabled:
        for block in blocks:
            src = block.source
            if src.startswith("\ufeff"):
                continue  # 文本里已经带了 BOM 记号
            m = _NON_ASCII_RE.search(src)
            if m is None:
                continue
            line = src.count("\n", 0, m.start()) + 1
            findings.append(
                Finding(
                    rule="R5",
                    severity="warning",
                    block=block.name,
                    line=line,
                    message=(
                        "块内含中文/非 ASCII 字符，但未声明 UTF-8 BOM："
                        "必须以 UTF-8 BOM（0xEF 0xBB 0xBF）写盘，否则博途导入外部源会乱码"
                    ),
                )
            )
    return _sort(findings)


def assert_clean(blocks: Sequence[BlockArtifact], *, bom_enabled: bool = True) -> None:
    """门禁断言：有 error 就抛 LintError（warning 不阻断）。"""
    findings = lint_bundle(blocks, bom_enabled=bom_enabled)
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise LintError(findings)
