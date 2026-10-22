"""SCL translator — PLC-IR blocks -> SCL source text.

Rule-based conversion with an LLM-ready fallback: LAD/FBD networks are
translated by walking the SimaticML wire graph (coils <- contacts <-
power rail); anything unresolvable is emitted as a structured TODO
comment so an LLM agent (or engineer) can finish it with full context.
"""

from __future__ import annotations

import re

from agents.plc.tia.flgnet_fold import stmt_to_scl
from agents.plc.tia.graph_scl import (
    graph_network_to_scl,
    graph_state_var_name,
    has_graph_sequence,
)
from agents.plc.tia.ir import (
    Access,
    AccessScope,
    Block,
    BlockType,
    InterfaceSection,
    Network,
    Part,
    PlcProject,
    Variable,
)
from agents.plc.tia.parts import (
    BOX_PARTS,
    BRANCH_PARTS,
    CALL_PARTS,
    COIL_PARTS,
    COMPARE_OPS,
    CONVERT_PARTS,
    JUMP_PARTS,
    MOVE_PARTS,
    MUX_PARTS,
    canon_part,
    format_todo,
)

#: Parts whose "out" pin produces a boolean RLO that can drive a wire.
RLO_OUTPUT_PARTS = {"Contact", "NegContact", "NotContact", "ContactNeg"} | set(COMPARE_OPS)


def _paren(expr: str) -> str:
    """Parenthesize a term when it would bind ambiguously in a join."""
    return f"({expr})" if (" OR " in expr or " AND " in expr) else expr

_SECTION_ORDER = [
    InterfaceSection.INPUT,
    InterfaceSection.OUTPUT,
    InterfaceSection.IN_OUT,
    InterfaceSection.STATIC,
    InterfaceSection.TEMP,
    InterfaceSection.CONSTANT,
]


class NetworkTranslator:
    """Translate one network's Parts+Wires into SCL statements."""

    def __init__(self, block: Block, network: Network) -> None:
        self.block = block
        self.network = network
        self.statements: list[str] = []
        self.notes: list[str] = []
        self._extra_decls: list[str] = []
        self._visited: set[str] = set()

    # -- wire helpers -------------------------------------------------------
    def _find_wire_to_pin(self, uuid: str, pin: str):
        for wire in self.network.wires:
            for ep in wire.targets:
                if ep.kind == "namecon" and ep.uuid == uuid and ep.pin == pin:
                    return wire
        return None

    def _wires_to_pin(self, uuid: str, pin: str) -> list:
        return [
            wire
            for wire in self.network.wires
            for ep in wire.targets
            if ep.kind == "namecon" and ep.uuid == uuid and ep.pin == pin
        ]

    def _operand_access(self, part: Part) -> Access | None:
        wire = self._find_wire_to_pin(part.uuid, "operand")
        if wire and wire.source and wire.source.kind == "identcon":
            return self.network.access_parts.get(wire.source.uuid)
        return part.accesses.get("operand")

    def _pin_name_aliases(self, pin: str) -> tuple[str, ...]:
        if pin == "out":
            return ("out", "out1", "OUT", "OUT1")
        return (pin,)

    def _access_bound_to_pin(self, part: Part, pin: str) -> Access | None:
        for wire in self.network.wires:
            for endpoint in wire.endpoints:
                if endpoint.kind != "namecon" or endpoint.uuid != part.uuid or endpoint.pin != pin:
                    continue
                for other in wire.endpoints:
                    if other.kind == "identcon":
                        return self.network.access_parts.get(other.uuid)
        return part.accesses.get(pin)

    def _pin_access(self, part: Part, pin: str) -> Access | None:
        for name in self._pin_name_aliases(pin):
            access = self._access_bound_to_pin(part, name)
            if access is not None:
                return access
        return None

    # -- expression synthesis -------------------------------------------------
    def _wire_driver_exprs(self, wire, sink: tuple[str, str] | None = None) -> list[str]:
        """Boolean expressions driven onto a wire by its source-side endpoints.

        A wire is a net: powerrail drives TRUE, IdentCon drives its Access
        value, and the `out` pin of RLO-producing parts drives their value.
        """
        exprs: list[str] = []
        for ep in wire.endpoints:
            if sink and ep.kind == "namecon" and ep.uuid == sink[0] and ep.pin == sink[1]:
                continue
            if ep.kind == "powerrail":
                exprs.append("TRUE")
            elif ep.kind == "identcon":
                acc = self.network.access_parts.get(ep.uuid)
                if acc is not None:
                    exprs.append(acc.as_scl())
            elif ep.kind == "namecon" and ep.pin == "out":
                part = self.network.parts.get(ep.uuid)
                if part is not None and part.name in RLO_OUTPUT_PARTS:
                    exprs.append(self._part_out_expr(part))
        return exprs

    def _value_at_pin(self, uuid: str, pin: str) -> str:
        """Boolean value arriving at a part pin (multiple drivers -> OR)."""
        key = f"{uuid}.{pin}"
        if key in self._visited:
            return "(* loop guard *)"
        self._visited.add(key)
        exprs: list[str] = []
        for wire in self._wires_to_pin(uuid, pin):
            exprs.extend(self._wire_driver_exprs(wire, sink=(uuid, pin)))
        exprs = [e for e in exprs if e]
        if not exprs:
            return "TRUE"
        if len(exprs) == 1:
            return exprs[0]
        return " OR ".join(_paren(e) for e in exprs)

    def _part_out_expr(self, part: Part) -> str:
        name = canon_part(part.name) or part.name
        if name in {"Contact", "NegContact", "NotContact", "ContactNeg"}:
            # contact out = (in value) AND operand ; negated variants invert
            in_expr = self._value_at_pin(part.uuid, "in")
            operand = self._operand_access(part)
            op_expr = operand.as_scl() if operand else "(* operand *)"
            if name in {"NegContact", "NotContact", "ContactNeg"} or part.negated:
                op_expr = f"NOT ({op_expr})"
            if in_expr == "TRUE":
                return op_expr
            return f"{_paren(in_expr)} AND {_paren(op_expr)}"
        if name in COMPARE_OPS:
            in1 = self._pin_access(part, "in1")
            in2 = self._pin_access(part, "in2")
            op = COMPARE_OPS[name]
            lhs = in1.as_scl() if in1 else "(* in1 *)"
            rhs = in2.as_scl() if in2 else "(* in2 *)"
            return f"({lhs} {op} {rhs})"
        return f"(* out of {name or 'part'} not expressible *)"

    # -- statement emission ----------------------------------------------------
    def _emit_move(self, part: Part) -> None:
        src = self._pin_access(part, "in")
        dst = self._pin_access(part, "out")
        if dst is None:
            dst = self._operand_access(part)
        src_txt = src.as_scl() if src else "(* in *)"
        dst_txt = dst.as_scl() if dst else "(* out *)"
        en = self._value_at_pin(part.uuid, "en")
        en_wires = self._wires_to_pin(part.uuid, "en")
        if not en_wires or en == "TRUE":
            # powerrail-only or missing EN → unconditional
            drivers = []
            for wire in en_wires:
                drivers.extend(self._wire_driver_exprs(wire, sink=(part.uuid, "en")))
            if not drivers or drivers == ["TRUE"]:
                self.statements.append(f"{dst_txt} := {src_txt};")
                return
        self.statements.append(f"IF {en} THEN {dst_txt} := {src_txt}; END_IF;")

    def _emit_coil(self, part: Part) -> None:
        operand = self._operand_access(part)
        target = operand.as_scl() if operand else "(* coil target unknown *)"
        cond = self._value_at_pin(part.uuid, "in")
        if part.name == "NegCoil":
            self.statements.append(f"{target} := NOT ({cond});")
        elif canon_part(part.name) == "Set":
            if cond == "TRUE":
                self.statements.append(f"{target} := TRUE;")
            else:
                self.statements.append(f"IF {cond} THEN {target} := TRUE; END_IF;")
        elif canon_part(part.name) == "Reset":
            if cond == "TRUE":
                self.statements.append(f"{target} := FALSE;")
            else:
                self.statements.append(f"IF {cond} THEN {target} := FALSE; END_IF;")
        elif " AND " not in cond and " OR " not in cond and cond not in {"TRUE", "FALSE"}:
            self.statements.append(
                f"IF {cond} THEN {target} := TRUE; ELSE {target} := FALSE; END_IF;"
            )
        else:
            self.statements.append(f"{target} := {cond};")

    def _emit_call(self, part: Part) -> None:
        called = part.template_values.get("Call") or part.template_values.get("calledBlock") or ""
        called = called.strip().strip('"') or part.name
        instance = (
            part.accesses.get("instance")
            or part.accesses.get("Instance")
            or self._pin_access(part, "db")
        )
        params: list[str] = []
        seen: set[str] = set()
        skip = {"in", "operand", "db", "instance", "en", "EN", "Instance"}
        out_pins = {"Q", "QU", "QD", "OUT", "OUT1", "CV", "ET", "ENO", "RET_VAL"}

        for pin, acc in part.accesses.items():
            if pin in skip:
                continue
            sec = str(part.template_values.get(f"__sec__{pin}") or "")
            op = "=>" if sec in {"Output", "Return"} or pin.upper() in out_pins else ":="
            params.append(f"{pin} {op} {acc.as_scl()}")
            seen.add(pin)

        for wire in self.network.wires:
            for ep in wire.endpoints:
                if ep.kind != "namecon" or ep.uuid != part.uuid:
                    continue
                pin = ep.pin or ""
                if not pin or pin in skip or pin in seen:
                    continue
                acc = None
                for other in wire.endpoints:
                    if other.kind == "identcon":
                        acc = self.network.access_parts.get(other.uuid)
                        if acc is not None:
                            break
                if acc is None:
                    continue
                sec = str(part.template_values.get(f"__sec__{pin}") or "")
                op = "=>" if sec in {"Output", "Return"} or pin.upper() in out_pins else ":="
                params.append(f"{pin} {op} {acc.as_scl()}")
                seen.add(pin)

        call = called or "UNKNOWN_BLOCK"
        if instance and instance.root:
            prefix = f"#{instance.root}" if instance.scope == AccessScope.LOCAL else f'"{instance.root}"'
            self.statements.append(f"{prefix}({', '.join(params)});")
        else:
            self.statements.append(f"{call}({', '.join(params)});")

    def _emit_box_call(self, part: Part) -> None:
        instance = (
            part.accesses.get("instance")
            or part.accesses.get("Instance")
        )
        inst = instance.as_scl() if instance is not None else (
            f'"{part.template_values["InstanceDB"]}"'
            if part.template_values.get("InstanceDB")
            else part.name
        )
        params: list[str] = []
        for pin in ("CU", "CD", "R", "R1", "S", "S1", "LD", "IN", "CLK"):
            if part.accesses.get(pin) is not None and not self._wires_to_pin(part.uuid, pin):
                params.append(f"{pin} := {part.accesses[pin].as_scl()}")
                continue
            wires = self._wires_to_pin(part.uuid, pin)
            if not wires:
                continue
            has_real = False
            for wire in wires:
                for ep in wire.endpoints:
                    if ep.kind == "namecon" and ep.uuid == part.uuid and ep.pin == pin:
                        continue
                    if ep.kind == "opencon":
                        continue
                    has_real = True
            if not has_real:
                continue
            params.append(f"{pin} := {self._value_at_pin(part.uuid, pin)}")
        for pin in ("PV", "PT"):
            access = self._pin_access(part, pin) or part.accesses.get(pin)
            if access is not None:
                params.append(f"{pin} := {access.as_scl()}")
        for pin in ("CV", "Q", "QU", "QD", "ET"):
            access = self._pin_access(part, pin) or part.accesses.get(pin)
            if access is not None:
                params.append(f"{pin} => {access.as_scl()}")
        self.statements.append(f"{inst}({', '.join(params)});")

    def translate(self) -> list[str]:
        """Return SCL statements for this network."""
        if self.network.source_text:
            return [line for line in self.network.source_text.splitlines() if line.strip()]

        folded_statements = iter(self.network.folded.statements) if self.network.folded else iter(())
        for part in self.network.parts.values():
            self._visited.clear()
            name = canon_part(part.name)
            if name in COIL_PARTS:
                folded = next(folded_statements, None)
                if folded is not None:
                    self.statements.append(stmt_to_scl(folded))
                else:
                    self._emit_coil(part)
            elif name in MOVE_PARTS or (part.name or "").startswith("Move"):
                folded = next(folded_statements, None)
                if folded is not None and getattr(folded, "kind", "") == "move":
                    self.statements.append(stmt_to_scl(folded))
                else:
                    self._emit_move(part)
            elif name in BOX_PARTS | CONVERT_PARTS | MUX_PARTS | JUMP_PARTS:
                folded = next(folded_statements, None)
                if folded is not None and getattr(folded, "kind", "") == "call":
                    self.statements.append(stmt_to_scl(folded))
                elif name in BOX_PARTS:
                    self._emit_box_call(part)
                else:
                    self.statements.append(stmt_to_scl(folded) if folded is not None else format_todo(part))
            elif name in CALL_PARTS or "Call" in (part.template_values or {}) or "calledBlock" in (
                part.template_values or {}
            ):
                folded = next(folded_statements, None)
                if folded is not None and getattr(folded, "kind", "") == "call":
                    self.statements.append(stmt_to_scl(folded))
                else:
                    self._emit_call(part)
            elif name in BRANCH_PARTS:
                continue  # consumed by downstream coils / moves
            else:
                self.statements.append(format_todo(part))
        if not self.statements:
            self.statements.append("(* empty network *)")
        return self.statements


# ---------------------------------------------------------------------------
# Block / project level — Siemens SCL / IEC 61131-3 Structured Text style
# Ref: Siemens SCL manual — VAR_INPUT…END_VAR, VAR_OUTPUT…END_VAR, …
# ---------------------------------------------------------------------------

#: Interface section → SCL declaration keyword (closed by END_VAR).
_SECTION_KEYWORDS: dict[InterfaceSection, str] = {
    InterfaceSection.INPUT: "VAR_INPUT",
    InterfaceSection.OUTPUT: "VAR_OUTPUT",
    InterfaceSection.IN_OUT: "VAR_IN_OUT",
    InterfaceSection.STATIC: "VAR",
    InterfaceSection.TEMP: "VAR_TEMP",
    InterfaceSection.CONSTANT: "VAR CONSTANT",
}

#: Block type → (open keyword, close keyword)
_BLOCK_KEYWORDS: dict[BlockType, tuple[str, str]] = {
    BlockType.FB: ("FUNCTION_BLOCK", "END_FUNCTION_BLOCK"),
    BlockType.FC: ("FUNCTION", "END_FUNCTION"),
    BlockType.OB: ("ORGANIZATION_BLOCK", "END_ORGANIZATION_BLOCK"),
}


def explain_scl_statement(stmt: str) -> str:
    """Chinese meaning comment for one SCL statement (engineer-facing)."""
    s = stmt.strip().rstrip(";")
    if not s or s.startswith("(*") or s.startswith("//"):
        return ""
    upper = s.upper()
    if "EMPTY NETWORK" in upper:
        return "空网络，无执行逻辑"
    # IF cond THEN tgt := TRUE; ELSE tgt := FALSE; END_IF
    m = re.fullmatch(
        r"IF\s+(.+?)\s+THEN\s+(.+?)\s*:=\s*TRUE\s*;\s*ELSE\s+\2\s*:=\s*FALSE\s*;\s*END_IF",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return f"当 {m.group(1)} 为 TRUE 时置位 {m.group(2)}，否则复位（触点→线圈）"
    # IF en THEN dst := src; END_IF  (move / conditional assign)
    m = re.fullmatch(
        r"IF\s+(.+?)\s+THEN\s+(.+?)\s*:=\s*(.+?)\s*;\s*END_IF",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return f"条件 {m.group(1)} 成立时，将 {m.group(3)} 传送到 {m.group(2)}"
    # IF cond THEN tgt := TRUE|FALSE; END_IF
    m = re.fullmatch(
        r"IF\s+(.+?)\s+THEN\s+(.+?)\s*:=\s*(TRUE|FALSE)\s*;\s*END_IF",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        act = "置位" if m.group(3).upper() == "TRUE" else "复位"
        return f"条件 {m.group(1)} 成立时{act} {m.group(2)}"
    # Instance / FC call: name(params)
    m = re.fullmatch(r"(.+?)\((.*)\)", s)
    if m and ":=" not in m.group(1):
        callee = m.group(1).strip()
        params = m.group(2).strip()
        if "CU" in params.upper() or "CV" in params.upper() or "PV" in params.upper():
            return f"调用计数器实例 {callee}（上升沿计数，当前值写入 CV）"
        if "R_TRIG" in callee.upper() or "CLK" in params.upper():
            return f"上升沿检测 {callee}（CLK 上升时 Q 为 TRUE）"
        if "F_TRIG" in callee.upper():
            return f"下降沿检测 {callee}"
        if "PT" in params.upper() or "ET" in params.upper() or re.search(r"\bIN\s*:=", params, re.IGNORECASE):
            return f"调用定时器实例 {callee}"
        return f"调用块/实例 {callee}" + (f"，参数：{params}" if params else "")
    if ":=" in s:
        left, right = s.split(":=", 1)
        return f"将 {right.strip()} 赋给 {left.strip()}"
    return "执行该语句"

def _comment_lines(indent: str, label: str, text: str) -> list[str]:
    """把可能多行的注释拆成每行都带 // 前缀的注释行。"""
    parts = str(text or "").splitlines() or [""]
    out = [f"{indent}// {label}{parts[0].strip()}" if parts[0].strip() else f"{indent}// {label}".rstrip()]
    for extra in parts[1:]:
        out.append(f"{indent}// {extra.strip()}" if extra.strip() else f"{indent}//")
    return out


def _header(block: Block) -> str:
    bt = block.block_type
    if bt == BlockType.UDT:
        return f"TYPE \"{block.name}\""
    open_kw, _ = _BLOCK_KEYWORDS.get(bt, (bt.value, f"END_{bt.value}"))
    ret = ""
    if bt == BlockType.FC:
        returns = block.interface_section(InterfaceSection.RETURN)
        ret_type = "Void"
        if returns:
            ret_type = returns[0].data_type or "Void"
            if ret_type.lower() == "void" or returns[0].name in {"Ret_Val", "RET_VAL"}:
                # Keep Void when no useful RET_VAL type
                if (returns[0].data_type or "Void").lower() == "void":
                    ret_type = "Void"
        ret = f" : {ret_type}"
    header = f'{open_kw} "{block.name}"{ret}'
    sub: list[str] = []
    if block.number:
        sub.append(f"// 编号：{bt.value}{block.number}")
    if block.programming_language:
        sub.append(f"// 原始语言：{block.programming_language}（规则翻译为 SCL）")
    if block.header_comment:
        # 块注释可能是多行（真实工程里有整段 ASCII 横幅）。必须逐行加 //
        # 前缀，否则只有首行被注释、其余裸文本会被当成代码，导致
        # 「设定值"VAR_OUTPUT"无效」这类错位报错（HR001 的 FB1081 就是这样崩的）。
        head_lines = str(block.header_comment).splitlines() or [""]
        sub.append(f"// 含义：{head_lines[0].strip()}")
        for extra in head_lines[1:]:
            sub.append(f"// {extra.strip()}" if extra.strip() else "//")
    else:
        sub.append("// 含义：由 LAD/FBD 网络折叠生成的等效 SCL，导入前请人工复核")
    return header + ("\n" + "\n".join(sub) if sub else "")


def _var_comment(var, *, constant: bool = False) -> str:
    dtype = var.data_type or "Bool"
    comment_bits: list[str] = []
    if var.comment:
        comment_bits.append(var.comment)
    if var.section == InterfaceSection.INPUT and not var.comment:
        comment_bits.append("输入参数")
    elif var.section == InterfaceSection.OUTPUT and not var.comment:
        comment_bits.append("输出参数")
    elif var.section == InterfaceSection.IN_OUT and not var.comment:
        comment_bits.append("输入输出参数")
    elif var.section == InterfaceSection.TEMP and not var.comment:
        comment_bits.append("临时变量")
    elif var.section == InterfaceSection.STATIC and not var.comment:
        comment_bits.append("静态变量")
    _ = dtype
    return f"  // {'；'.join(comment_bits)}" if comment_bits else ""


def _is_struct_type(dtype: str) -> bool:
    d = (dtype or "").strip().lower()
    return d == "struct" or d.endswith(" of struct") or d.endswith(" of \"struct\"")


#: SCL 保留字/内部类型名：这些不能直接当标识符用，否则 TIA 报「设定值无效」
#: 或「数据类型 Undef 未知」（真实工程 HR001 的 UDT_TypePara 用了 ``String : String[5]``）。
_SCL_RESERVED = {
    "IF", "THEN", "ELSE", "ELSIF", "END_IF", "CASE", "OF", "END_CASE", "FOR",
    "TO", "BY", "DO", "END_FOR", "WHILE", "END_WHILE", "REPEAT", "UNTIL",
    "END_REPEAT", "RETURN", "CONTINUE", "EXIT", "GOTO", "AND", "OR", "XOR",
    "NOT", "MOD", "TRUE", "FALSE", "BEGIN", "END", "VAR", "END_VAR",
    "STRUCT", "END_STRUCT", "ARRAY", "TYPE", "END_TYPE", "CONSTANT",
    "BOOL", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT", "REAL", "LREAL", "TIME", "LTIME",
    "DATE", "CHAR", "WCHAR", "STRING", "WSTRING", "VOID", "ANY", "VARIANT",
    "POINTER", "AT", "REGION", "END_REGION", "TITLE", "VERSION",
    # S7 遗留/系统类型名：真实工程 HR001 的 UDT_TypePara 有成员叫 S5Time，
    # 不加引号时 TIA 报「设定值"S5Time"无效」（它被当成类型而不是变量名）。
    "S5TIME", "S5TIME_OR_DT", "TIME_OF_DAY", "TOD", "DATE_AND_TIME", "DT",
    "IEC_TIMER", "IEC_COUNTER", "IEC_LTIMER", "IEC_LCOUNTER",
    "TON_TIME", "TOF_TIME", "TP_TIME", "TONR_TIME",
    "R_TRIG", "F_TRIG", "SFB", "SFC", "BLOCK_FB", "BLOCK_FC", "BLOCK_DB",
}


def _sc_ident(name: str) -> str:
    """把变量名转成 SCL 里合法的标识符。

    TIA 允许 ``"带空格的名称"`` 这种引号标识符；真实工程里 DB2100 就有
    ``Reserved Word 18`` 这类成员，直接裸写会被判「设定值无效」。
    """
    n = (name or "").strip()
    if not n:
        return n
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n) and n.upper() not in _SCL_RESERVED:
        return n
    if n.startswith('"') and n.endswith('"'):
        return n
    return '"%s"' % n.replace('"', "")


def _render_var(var, indent: str = "    ", *, constant: bool = False) -> list[str]:
    """渲染单条变量声明，返回若干行。

    STRUCT 必须展开成 ``X : Struct <成员...> END_STRUCT;``。若只输出
    ``X : Struct;``，TIA 会报「STRUCT 关键字后有不正确的 ';'」——真实工程
    HR001 里 46 个块踩了这个坑，所以这里不做猜测式降级。
    """
    dtype = var.data_type or "Bool"
    comment = _var_comment(var, constant=constant)
    ident = _sc_ident(var.name)

    if _is_struct_type(dtype):
        members = list(getattr(var, "members", None) or [])
        if not members:
            # 无成员信息：生成空的 Struct 一定编译失败，直接不声明并留痕，
            # 让错误退化为"变量未定义"（可定位），而不是晦涩的 STRUCT 语法错误。
            return [f"{indent}// [未能展开] {ident} : {dtype}（导出中无成员定义）"]
        head = f"{indent}{ident} : {dtype}"
        if var.start_value and not constant:
            head += f" := {var.start_value}"
        lines = [head + comment]
        seen_members: set[str] = set()
        for member in members:
            mkey = (member.name or "").strip().upper()
            if not mkey or mkey in seen_members:
                continue
            seen_members.add(mkey)
            lines.extend(_render_var(member, indent + "    "))
        lines.append(f"{indent}END_STRUCT;")
        return lines

    if constant:
        val = var.start_value or "0"
        return [f"{indent}{ident} : {dtype} := {val};{comment}"]
    value = f" := {var.start_value}" if var.start_value else ""
    return [f"{indent}{ident} : {dtype}{value};{comment}"]


def _var_line(var, *, constant: bool = False) -> str:
    return "\n".join(_render_var(var, constant=constant))


def _interface_text(block: Block, extra_static: list[Variable] | None = None) -> str:
    if block.block_type in {BlockType.DB, BlockType.UDT}:
        # Prefer sectioned layout for InstanceDB / GlobalDB readability
        by_section: dict[InterfaceSection, list] = {s: [] for s in _SECTION_ORDER}
        orphan: list = []
        for var in block.interface:
            if var.section in by_section:
                by_section[var.section].append(var)
            else:
                orphan.append(var)
        lines: list[str] = []
        seen_db: set[str] = set()
        for section in _SECTION_ORDER:
            members = by_section.get(section) or []
            if not members:
                continue
            unique = []
            for var in members:
                key = (var.name or "").strip().upper()
                if not key or key in seen_db:
                    continue
                seen_db.add(key)
                unique.append(var)
            if not unique:
                continue
            lines.append(f"    // ---- {section.value} ----")
            for var in unique:
                lines.append(_var_line(var))
        for var in orphan:
            key = (var.name or "").strip().upper()
            if key and key in seen_db:
                continue
            seen_db.add(key)
            lines.append(_var_line(var))
        return "\n".join(lines)

    lines: list[str] = []
    seen_names: set[str] = set()
    for section in _SECTION_ORDER:
        members = block.interface_section(section)
        if section is InterfaceSection.STATIC and extra_static:
            members = list(members) + list(extra_static)
        # Skip Void Ret_Val noise on FC
        if section == InterfaceSection.RETURN:
            continue
        if not members:
            continue
        keyword = _SECTION_KEYWORDS.get(section)
        if not keyword:
            continue
        # 同名变量只能声明一次（TIA 判重名错误）。多个 TON 实例被推断成同名的
        # PT/ET/IN/Q 时保留第一份；interface 里的真实声明排在 extra_static 之前。
        unique: list = []
        for var in members:
            key = (var.name or "").strip().upper()
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            unique.append(var)
        if not unique:
            continue
        lines.append(keyword)
        for var in unique:
            if section == InterfaceSection.CONSTANT:
                lines.append(_var_line(var, constant=True))
            else:
                lines.append(_var_line(var))
        lines.append("END_VAR")
    return "\n".join(lines)


def translate_block_to_scl(block: Block) -> str:
    """Convert one block to a full Siemens-standard SCL compilation unit."""
    if block.block_type == BlockType.DB:
        body = _interface_text(block)
        lines = [f'DATA_BLOCK "{block.name}"']
        if block.number:
            lines.append(f"// 编号：DB{block.number}")
        inst_of = (
            (block.attributes or {}).get("InstanceOfName")
            or (block.attributes or {}).get("OfType")
            or (block.attributes or {}).get("OfBlock")
            or ""
        )
        if inst_of:
            lines.append(f'// 实例数据块 · 类型 FB "{inst_of}"')
            lines.append("// 含义：成员声明含 FB 接口镜像与多实例推断")
        else:
            lines.append("// 含义：数据块成员声明（由导出接口生成）")
        if not any(v.is_retain for v in block.interface):
            lines.append("NON_RETAIN")
        lines.append("STRUCT")
        lines.append(body if body else "    // （无成员）")
        lines.append("END_STRUCT;")
        lines.append("BEGIN")
        lines.append("END_DATA_BLOCK")
        return "\n".join(lines)
    if block.block_type == BlockType.UDT:
        return (
            f'TYPE "{block.name}"\nSTRUCT\n'
            + _interface_text(block)
            + "\nEND_STRUCT;\nEND_TYPE"
        )

    _, end_kw = _BLOCK_KEYWORDS.get(
        block.block_type, (block.block_type.value, f"END_{block.block_type.value}")
    )
    # S7-GRAPH networks rebuild as CASE state machines and need one Int state
    # variable each; inject them into STATIC (FB only — FC has no STATIC section)
    # so the unit is compile-gated as-is.
    graph_state_vars: dict[int, str] = {}
    extra_static: list[Variable] = []
    if block.block_type == BlockType.FB:
        graph_seen = 0
        for net_idx, network in enumerate(block.networks, start=1):
            if has_graph_sequence(network) and graph_network_to_scl(network, "GraphStep"):
                graph_seen += 1
                graph_state_vars[net_idx] = graph_state_var_name(graph_seen)
        for var_name in sorted(set(graph_state_vars.values())):
            extra_static.append(
                Variable(
                    name=var_name,
                    section=InterfaceSection.STATIC,
                    data_type="Int",
                    comment="GRAPH 步序状态（规则重建自动注入）",
                )
            )
    lines: list[str] = [_header(block)]
    interface = _interface_text(block, extra_static=extra_static or None)
    if interface:
        lines.append(interface)
    lines.append("BEGIN")

    lang_u = (block.programming_language or "").upper()
    if lang_u in {"SCL", "STL"} and (block.source_text or "").strip() and not block.networks:
        # Native textual body — pass through, do not re-translate.
        lines.append(block.source_text.strip())
        lines.append("")
        lines.append(end_kw)
        return "\n".join(lines)

    for idx, network in enumerate(block.networks, start=1):
        translator = NetworkTranslator(block, network)
        statements = translator.translate()
        title = (network.title or "").strip()
        lines.append("")
        lines.append(f"    // ---------- 网络 {idx} ----------")
        if title and not re.match(r"(?i)^network\s*\d*$", title):
            lines.extend(_comment_lines("    ", "标题：", title))
        if network.comment:
            lines.extend(_comment_lines("    ", "注释：", network.comment))
        # S7-GRAPH: rebuild executable CASE state machine from parsed steps
        state_var = graph_state_vars.get(idx)
        if state_var is not None:
            graph_lines = graph_network_to_scl(network, state_var)
            if graph_lines is not None:
                lines.extend(graph_lines)
                continue
        # Blank network: keep placeholder so middle gaps never look like "parse ended"
        if statements == ["(* empty network *)"] or (
            not statements and not network.parts and not network.source_text
        ):
            lines.append("    // （空白网络）")
            continue
        # StructuredText / StatementList source: emit reconstructed text as-is
        if network.source_text:
            lang = (network.programming_language or "").upper()
            if lang == "STL":
                lines.append(
                    "    // 含义：本网络为 StatementList/STL 导出重建（CALL / 布尔指令），等效 SCL"
                )
            elif lang == "GRAPH" or getattr(network, "graph_steps", None):
                lines.append("    // 含义：S7-GRAPH 步序/转换（注释序列，非可执行 GRAPH）")
            else:
                lines.append(
                    "    // 含义：本网络为 StructuredText（SCL）原文重建，非 LAD 折叠"
                )
            for stmt in statements:
                lines.append("    " + stmt)
            continue
        for stmt in statements:
            meaning = explain_scl_statement(stmt)
            if meaning:
                lines.append(f"    // 含义：{meaning}")
            lines.append("    " + stmt)

    lines.append("")
    lines.append(end_kw)
    return "\n".join(lines)


def _is_instance_db(block: Block) -> bool:
    """实例 DB（InstanceDB）由 TIA 随 FB 自动创建，不该由我们重新生成。

    真实工程 HR001 暴露：实例 DB 的 Static 里会镜像 FB 的多实例成员，形如
    ``CycleTime : "FB5008_CycleTime";``。TIA 对实例 DB 里的这种成员判
    「不允许使用数据类型 FBxxx」，必然编译失败。跳过它们既避免错误，
    也不会破坏工程原有的实例 DB 结构。
    """
    if block.block_type != BlockType.DB:
        return False
    attrs = block.attributes or {}
    return bool(attrs.get("InstanceOfName") or attrs.get("OfType") or attrs.get("OfBlock"))


def convert_project_to_scl(project: PlcProject) -> dict[str, str]:
    """Map block name -> SCL for every *writable non-safety* translatable block.

    Know-how / password protected, interface-only (no body), and Safety/F-blocks
    are skipped (kept as original only). Never write F-block bodies.
    Instance DBs are skipped too — TIA owns them.
    """
    out: dict[str, str] = {}
    items = [
        (name, block)
        for name, block in project.blocks.items()
        if not (
            block.is_protected()
            or block.is_interface_only()
            or getattr(block, "is_safety", False)
            or _is_instance_db(block)
        )
    ]

    def _one(item: tuple[str, Block]) -> tuple[str, str]:
        name, block = item
        return name, translate_block_to_scl(block)

    from agents.plc.tia.parallel import map_parallel

    for name, scl in map_parallel(_one, items, min_items=8):
        out[name] = scl
    return out


def llm_prompt_for_network(block: Block, network: Network) -> str:
    """Context prompt for an LLM to translate a network the rules missed."""
    parts_txt = "\n".join(
        f"Part UId={p.uuid} Name={p.name} templates={p.template_values}"
        for p in network.parts.values()
    )
    wires_txt = "\n".join(
        f"Wire UId={w.uid}: {[(e.kind, e.uuid, e.pin) for e in w.endpoints]}"
        for w in network.wires
    )
    accesses_txt = "\n".join(
        f"Access UId={uid}: {acc.scope.value} {acc.root}.{'.'.join(acc.path)} ({acc.data_type})"
        for uid, acc in network.access_parts.items()
    )
    return (
        f"Translate the following TIA Portal network (block {block.name}, "
        f"language {network.programming_language or 'LAD'}) to equivalent SCL.\n"
        f"Network title: {network.title}\n\n"
        f"Parts:\n{parts_txt}\n\nAccesses:\n{accesses_txt}\n\nWires:\n{wires_txt}\n\n"
        "Return only SCL statements, preserving semantics (edges, timers, calls)."
    )
