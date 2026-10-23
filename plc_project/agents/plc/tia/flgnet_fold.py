"""Fold SimaticML FlgNet wire graphs into reusable PLC expression IR."""

from __future__ import annotations

from dataclasses import dataclass, replace

from agents.plc.tia.ir import (
    Access,
    AccessScope,
    And,
    Arith,
    AssignStmt,
    Block,
    Compare,
    Expr,
    FoldedNetwork,
    Func,
    Lit,
    Network,
    Not,
    Or,
    Part,
    PlcProject,
    Raw,
    Ref,
)
from agents.plc.tia.parts import (
    BOX_PARTS,
    BRANCH_PARTS,
    CALC_PARTS,
    CALL_PARTS,
    COIL_PARTS,
    COIL_TIMER_KINDS,
    COMPARE_OPS,
    CONVERT_PARTS,
    EDGE_CONTACT_PARTS,
    GATE_AND_PARTS,
    GATE_OR_PARTS,
    JUMP_PARTS,
    LATCH_PARTS,
    MATH_BINARY_OPS,
    MATH_UNARY_FUNCS,
    MOVE_PARTS,
    MUX_PARTS,
    RLO_NOT_PARTS,
    SYS_TIME_PARTS,
    TIME_CONV_PARTS,
    canon_part,
)

RLO_OUTPUT_PARTS = {"Contact", "NegContact", "NotContact", "ContactNeg"} | set(COMPARE_OPS)
COUNTER_PARTS = {"CTU", "CTD", "CTUD"}
TIMER_PARTS = {"TON", "TOF", "TP", "TONR"}
EDGE_TRIG_PARTS = {"R_TRIG", "F_TRIG", "P_TRIG"}
_SKIP_CALL_PINS = {"in", "operand", "db", "instance", "en", "EN"}
_OUTPUT_SECTIONS = {"Output", "Return"}
_OUTPUT_PINS = {"Q", "QU", "QD", "OUT", "OUT1", "CV", "ET", "ENO", "RET_VAL"}
# LAD coils relay the incoming RLO unchanged on their `out` pin.
_COIL_PASSTHROUGH_KINDS = {"Coil", "NegCoil", "Set", "Reset"}
# Box output pins usable as downstream RLO/value drivers (Q/ET/CV…).
_BOX_OUT_PINS = {"Q", "QU", "QD", "CV", "ET"}
# IEC box call parameter order (canonical uppercase pin names).
# S before R/R1 matches the SR signature (S, R1); RS keeps (R, S1).
_BOX_RLO_PINS = ("CU", "CD", "S", "R", "R1", "S1", "LD", "IN", "CLK")
_BOX_VALUE_PINS = ("PV", "PT")
_BOX_OUT_PIN_ORDER = ("CV", "Q", "QU", "QD", "ET")


@dataclass(frozen=True)
class FoldStmt(AssignStmt):
    """AssignStmt extended with the originating FlgNet part (additive contract).

    Field semantics of AssignStmt are unchanged; ``part_uuid`` / ``part_name``
    let downstream consumers (SCL translation, KG) attribute a statement to its
    exact part instead of relying on iteration order.
    """

    part_uuid: str = ""
    part_name: str = ""


def _same_pin(a: str, b: str) -> bool:
    """FlgNet pin names are case-insensitive (SR boxes use s/r1/q, code S/R1/Q)."""
    return (a or "").lower() == (b or "").lower()


def _wrap_en(core: str, en: Expr | None) -> str:
    """Condition a one-statement body on its EN: ``IF en THEN core END_IF;``."""
    if en is None:
        return core
    return f"IF {expr_to_scl(en)} THEN {core} END_IF;"


def _pin_assign_op(part: Part, pin: str) -> str:
    sec = str(part.template_values.get(f"__sec__{pin}") or "")
    if sec in _OUTPUT_SECTIONS or pin.upper() in _OUTPUT_PINS:
        return "=>"
    return ":="


def _paren(expr: str) -> str:
    """Parenthesize a term when it would bind ambiguously in a join."""
    return f"({expr})" if (" OR " in expr or " AND " in expr) else expr


def _cardinality(part: Part) -> int:
    """Siemens Card template value (gate/math input count); default 2."""
    raw = str(part.template_values.get("Card") or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def expr_to_scl(expr: Expr) -> str:
    """Render an expression with the same boolean parenthesis rules as SCL."""
    if isinstance(expr, Lit):
        if expr.value is True:
            return "TRUE"
        if expr.value is False:
            return "FALSE"
        return expr.value
    if isinstance(expr, Ref):
        return expr.access.as_scl()
    if isinstance(expr, Not):
        return f"NOT ({expr_to_scl(expr.operand)})"
    if isinstance(expr, And):
        return " AND ".join(_paren(expr_to_scl(item)) for item in expr.operands)
    if isinstance(expr, Or):
        return " OR ".join(_paren(expr_to_scl(item)) for item in expr.operands)
    if isinstance(expr, Compare):
        return f"({expr_to_scl(expr.lhs)} {expr.op} {expr_to_scl(expr.rhs)})"
    if isinstance(expr, Arith):
        joiner = f" {expr.op} "
        body = joiner.join(_paren_value(expr_to_scl(item)) for item in expr.operands)
        return f"({body})" if expr.op in {"+", "-", "*", "/", "**"} else body
    if isinstance(expr, Func):
        return f"{expr.name}({', '.join(expr_to_scl(arg) for arg in expr.args)})"
    if isinstance(expr, Raw):
        return expr.text
    raise TypeError(f"Unsupported expression: {type(expr).__name__}")


def _paren_value(text: str) -> str:
    """Parenthesize a nested arithmetic term so precedence stays explicit."""
    stripped = text.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return text
    return f"({text})" if " " in stripped else text


def stmt_to_scl(stmt: AssignStmt) -> str:
    """Render a folded coil/move/call statement as SCL (prefer IF forms when clear)."""
    if stmt.kind == "call":
        return stmt.target_scl or "(* call *)"
    target = stmt.target.as_scl() if stmt.target is not None else stmt.target_scl or "(* coil target unknown *)"
    condition = expr_to_scl(stmt.value)
    if stmt.kind == "move":
        src = condition
        en = stmt.enable
        en_txt = expr_to_scl(en) if en is not None else "TRUE"
        if en is None or en_txt == "TRUE":
            return f"{target} := {src};"
        return f"IF {en_txt} THEN {target} := {src}; END_IF;"
    if stmt.kind == "neg_coil":
        return f"{target} := NOT ({condition});"
    if stmt.kind == "set":
        return f"{target} := TRUE;" if condition == "TRUE" else f"IF {condition} THEN {target} := TRUE; END_IF;"
    if stmt.kind == "reset":
        return f"{target} := FALSE;" if condition == "TRUE" else f"IF {condition} THEN {target} := FALSE; END_IF;"
    # Coil: simple boolean → IF/ELSE TRUE/FALSE (matches engineer mental model)
    if " AND " not in condition and " OR " not in condition and condition not in {"TRUE", "FALSE"}:
        return f"IF {condition} THEN {target} := TRUE; ELSE {target} := FALSE; END_IF;"
    return f"{target} := {condition};"


def _trace_stmt_line(statement: AssignStmt) -> str:
    """One-line ast_trace conclusion for a folded statement (contract docs/15 §4)."""
    if statement.target is None:
        text = (statement.target_scl or "(* call *)").strip()
        return f"{statement.kind} {text}"
    return f"{statement.kind} {statement.target.as_scl()} := {expr_to_scl(statement.value)}"


class _NetworkFolder:
    def __init__(self, network: Network, trace: list[str] | None = None) -> None:
        self.network = network
        # FlgNet flow graphs are acyclic DAGs: the same contact chain fanning
        # out into several gate inputs is a *shared subgraph*, not a loop.
        # ``_stack`` holds the active recursion path (true back-edge guard);
        # ``_pin_memo`` / ``_part_memo`` reuse completed subgraph expressions so
        # shared branches fold into the same expression (no loop-guard noise).
        self._stack: set[tuple[str, str]] = set()
        self._pin_memo: dict[tuple[str, str], Expr] = {}
        self._part_memo: dict[str, Expr] = {}
        # Optional ast_trace collection (contract docs/15 §4); None = no tracing.
        self._trace = trace
        self._steps: list[str] = []

    def _find_wire_to_pin(self, uuid: str, pin: str):
        for wire in self.network.wires:
            for endpoint in wire.targets:
                if (
                    endpoint.kind == "namecon"
                    and endpoint.uuid == uuid
                    and _same_pin(endpoint.pin, pin)
                ):
                    return wire
        return None

    def _wires_to_pin(self, uuid: str, pin: str) -> list:
        return [
            wire
            for wire in self.network.wires
            for endpoint in wire.targets
            if endpoint.kind == "namecon"
            and endpoint.uuid == uuid
            and _same_pin(endpoint.pin, pin)
        ]

    def _operand_access(self, part: Part) -> Access | None:
        wire = self._find_wire_to_pin(part.uuid, "operand")
        if wire and wire.source and wire.source.kind == "identcon":
            return self.network.access_parts.get(wire.source.uuid)
        return part.accesses.get("operand")

    def _pin_name_aliases(self, pin: str) -> tuple[str, ...]:
        """Siemens Move cardinality uses out1/out2… instead of out."""
        if pin == "out":
            return ("out", "out1", "OUT", "OUT1")
        if pin == "in":
            return ("in", "IN")
        return (pin,)

    def _access_bound_to_pin(self, part: Part, pin: str) -> Access | None:
        """Resolve Access on a part pin regardless of wire direction.

        Inputs: IdentCon → NameCon(pin)
        Outputs (Move CV etc.): NameCon(pin) → IdentCon
        """
        for wire in self.network.wires:
            for endpoint in wire.endpoints:
                if (
                    endpoint.kind != "namecon"
                    or endpoint.uuid != part.uuid
                    or not _same_pin(endpoint.pin, pin)
                ):
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

    def _wire_driver_exprs(self, wire, sink: tuple[str, str] | None = None) -> list[Expr]:
        expressions: list[Expr] = []
        for endpoint in wire.endpoints:
            if sink and endpoint.kind == "namecon" and (
                endpoint.uuid == sink[0] and _same_pin(endpoint.pin, sink[1])
            ):
                continue
            if endpoint.kind == "powerrail":
                expressions.append(Lit(True))
            elif endpoint.kind == "identcon":
                access = self.network.access_parts.get(endpoint.uuid)
                if access is not None:
                    expressions.append(Ref(access))
            elif endpoint.kind == "namecon":
                expr = self._namecon_driver_expr(endpoint)
                if expr is not None:
                    expressions.append(expr)
        return expressions

    def _namecon_driver_expr(self, endpoint) -> Expr | None:
        """Expression driven onto a wire by one part output pin.

        Covers RLO contacts/gates, coil `out` RLO passthrough, and timer /
        counter / latch box outputs (Q, ET, CV… referenced via their instance).
        """
        part = self.network.parts.get(endpoint.uuid)
        if part is None:
            return None
        pin_up = (endpoint.pin or "").upper()
        if pin_up == "OUT" and (
            part.name in RLO_OUTPUT_PARTS
            or part.name in GATE_AND_PARTS
            or part.name in GATE_OR_PARTS
            or part.name in RLO_NOT_PARTS
            or part.name in EDGE_CONTACT_PARTS
        ):
            return self._part_out_expr(part)
        cname = canon_part(part.name)
        if pin_up == "OUT" and cname in _COIL_PASSTHROUGH_KINDS:
            # Coils relay the incoming RLO: SCoil.out → Move.en chains etc.
            incoming = self._value_at_pin(part.uuid, "in")
            return Not(incoming) if cname == "NegCoil" else incoming
        if pin_up == "OUT" and part.name in COIL_TIMER_KINDS:
            return self._box_pin_ref(part, "Q")
        if (
            pin_up in _BOX_OUT_PINS
            and (
                cname in TIMER_PARTS
                or cname in COUNTER_PARTS
                or cname in EDGE_TRIG_PARTS
                or cname in LATCH_PARTS
            )
        ):
            return self._box_pin_ref(part, pin_up)
        return None

    def _box_instance_access(self, part: Part) -> Access | None:
        """Instance of an IEC box: operand/instance pin wire, then InstanceDB."""
        inst = (
            self._access_bound_to_pin(part, "operand")
            or part.accesses.get("operand")
            or self._access_bound_to_pin(part, "instance")
            or part.accesses.get("instance")
            or part.accesses.get("Instance")
        )
        if inst is None:
            db = str(part.template_values.get("InstanceDB") or "").strip().strip('"')
            if db:
                inst = Access(scope=AccessScope.GLOBAL, root=db)
        return inst

    def _box_pin_ref(self, part: Part, member: str) -> Expr | None:
        """Reference to a box output member, e.g. ``#Timer.Q`` / ``"CTU_DB".CV``."""
        inst = self._box_instance_access(part)
        if inst is None or not inst.root:
            return None
        return Ref(replace(inst, path=tuple(inst.path) + (member,), negated=False))

    def _value_at_pin(self, uuid: str, pin: str) -> Expr:
        key = (uuid, pin.lower())
        if key in self._stack:  # true back-edge (cannot happen in valid FlgNet)
            if self._trace is not None:
                self._steps.append(f"UId={uuid}.{pin} 真环回边 -> 按 FALSE 截断")
            return Lit(False)
        cached = self._pin_memo.get(key)
        if cached is not None:
            if self._trace is not None:
                self._steps.append(f"UId={uuid}.{pin} 复用已折叠共享支路")
            return cached
        self._stack.add(key)
        try:
            expressions = [
                expression
                for wire in self._wires_to_pin(uuid, pin)
                for expression in self._wire_driver_exprs(wire, sink=(uuid, pin))
            ]
        finally:
            self._stack.discard(key)
        if not expressions:
            result: Expr = Lit(True)
        elif len(expressions) == 1:
            result = expressions[0]
        else:
            if self._trace is not None:
                self._steps.append(
                    f"UId={uuid}.{pin} 汇入 {len(expressions)} 条 Wire -> 并联 OR 归约"
                )
            result = Or(tuple(expressions))
        self._pin_memo[key] = result
        return result

    def _part_out_expr(self, part: Part) -> Expr:
        cached = self._part_memo.get(part.uuid)
        if cached is not None:
            if self._trace is not None:
                self._steps.append(
                    f"{part.name or 'Part'} UId={part.uuid}.out 复用已折叠共享支路"
                )
            return cached
        guard = (part.uuid, "(* out *)")
        if guard in self._stack:  # value-path back-edge (invalid FlgNet)
            return Lit(False)
        self._stack.add(guard)
        try:
            result = self._compute_part_out_expr(part)
        finally:
            self._stack.discard(guard)
        self._part_memo[part.uuid] = result
        return result

    def _compute_part_out_expr(self, part: Part) -> Expr:
        if part.name in {"Contact", "NegContact", "NotContact", "ContactNeg"}:
            incoming = self._value_at_pin(part.uuid, "in")
            operand = self._operand_access(part)
            operand_expr: Expr = Ref(operand) if operand is not None else Lit("(* operand *)")
            if part.name in {"NegContact", "NotContact", "ContactNeg"} or part.negated:
                operand_expr = Not(operand_expr)
            return operand_expr if incoming == Lit(True) else And((incoming, operand_expr))
        cname = canon_part(part.name)
        if cname in COMPARE_OPS:
            lhs = self._value_expr(part, "in1")
            rhs = self._value_expr(part, "in2")
            compare = Compare(
                COMPARE_OPS[cname],
                lhs if lhs is not None else Lit("(* in1 *)"),
                rhs if rhs is not None else Lit("(* in2 *)"),
            )
            # `.pre` carries the upstream RLO into the comparison:
            # ---|ClearHoleNoReq|---( Eq )  →  pre AND (a = b)
            # A powerrail-driven .pre is unconditional (TRUE AND x ≡ x).
            pre = self._value_at_pin(part.uuid, "pre") if self._wires_to_pin(part.uuid, "pre") else None
            if pre is not None and pre != Lit(True):
                return And((pre, compare))
            return compare
        if part.name in GATE_AND_PARTS or part.name in GATE_OR_PARTS:
            inputs = self._gate_input_exprs(part)
            if not inputs:
                return Lit(f"(* empty {part.name} gate *)")
            return And(tuple(inputs)) if part.name in GATE_AND_PARTS else Or(tuple(inputs))
        if part.name in RLO_NOT_PARTS:
            return Not(self._value_at_pin(part.uuid, "in"))
        if part.name in EDGE_CONTACT_PARTS:
            # ---|P|--- / ---|N|--- : RLO passthrough; operand is the edge memory bit.
            return self._value_at_pin(part.uuid, "in")
        rhs = self._math_rhs_expr(part)
        if rhs is not None:
            return rhs
        return Lit(f"(* out of {part.name or 'part'} not expressible *)")

    def _gate_input_exprs(self, part: Part) -> list[Expr]:
        card = _cardinality(part)
        inputs: list[Expr] = []
        for i in range(1, card + 1):
            expr = self._value_at_pin(part.uuid, f"in{i}")
            inputs.append(expr)
        if self._trace is not None and card > 1:
            joiner = "串联 AND" if part.name in GATE_AND_PARTS else "并联 OR"
            self._steps.append(
                f"{part.name or 'Gate'} UId={part.uuid} Card={card} -> {joiner} 归约"
            )
        return inputs

    def _value_expr(self, part: Part, pin: str) -> Expr | None:
        """Value bound to an input pin: Access first, then a driver part's output."""
        access = self._pin_access(part, pin) or part.accesses.get(pin)
        if access is not None:
            return Ref(access)
        for wire in self._wires_to_pin(part.uuid, pin):
            for endpoint in wire.endpoints:
                if endpoint.kind != "namecon" or (
                    endpoint.uuid == part.uuid and _same_pin(endpoint.pin, pin)
                ):
                    continue
                pin_up = (endpoint.pin or "").upper()
                driver = self.network.parts.get(endpoint.uuid)
                if driver is None:
                    continue
                if pin_up in {"OUT", "OUT1"}:
                    expr = self._part_out_expr(driver)
                    if isinstance(expr, Lit) and isinstance(expr.value, str) and expr.value.startswith("(*"):
                        continue
                    return expr
                if pin_up in _BOX_OUT_PINS:
                    # Timer/counter/latch outputs drive value inputs by member ref.
                    expr = self._namecon_driver_expr(endpoint)
                    if expr is not None:
                        return expr
        return None

    def _math_rhs_expr(self, part: Part) -> Expr | None:
        """Right-hand value produced by a math box (Add/Mul/Sin/Calc/Swap…)."""
        name = part.name or ""
        if name in MATH_BINARY_OPS:
            op = MATH_BINARY_OPS[name]
            card = _cardinality(part)
            operands: list[Expr] = []
            for i in range(1, card + 1):
                expr = self._value_expr(part, f"in{i}")
                operands.append(expr if expr is not None else Lit(f"(* in{i} *)"))
            if len(operands) < 2:
                operands.append(Lit("(* operand *)"))
            return Arith(op=op, operands=tuple(operands))
        if name in MATH_UNARY_FUNCS:
            func = MATH_UNARY_FUNCS[name]
            arg = self._value_expr(part, "in")
            return Func(name=func, args=(arg if arg is not None else Lit("(* in *)"),))
        if name in CALC_PARTS:
            equation = (part.template_values.get("Equation") or "").strip()
            card = _cardinality(part)
            subs = {
                f"IN{i}": expr_to_scl(
                    self._value_expr(part, f"IN{i}") or Lit(f"(* IN{i} *)")
                )
                for i in range(1, card + 1)
            }
            if equation:
                text = equation
                for key in sorted(subs, key=len, reverse=True):
                    text = text.replace(key, subs[key])
                return Raw(text=text)
            operands = [Lit(subs[f"IN{i}"]) for i in range(1, card + 1) if f"IN{i}" in subs]
            if operands:
                return Arith(op="+", operands=tuple(operands))
        return None

    def fold(self) -> FoldedNetwork:
        folded = FoldedNetwork(network_id=self.network.id, title=self.network.title)

        def _emit(statement: AssignStmt, part: Part | None = None) -> None:
            if part is not None and not isinstance(statement, FoldStmt):
                statement = FoldStmt(
                    target=statement.target,
                    value=statement.value,
                    kind=statement.kind,
                    target_scl=statement.target_scl,
                    enable=statement.enable,
                    part_uuid=part.uuid or "",
                    part_name=part.name or "",
                )
            folded.statements.append(statement)
            if self._trace is None:
                return
            self._trace.append(f"[net {self.network.id}] {_trace_stmt_line(statement)}")
            self._trace.extend(f"  step: {step}" for step in self._steps)
            self._steps.clear()

        if self.network.source_text:
            # SCL / StructuredText network: keep statements for folded_logic /
            # chat. Lines are passed through verbatim — appending ';' would
            # corrupt multi-line constructs (IF #Confirm; / THEN;).
            for line in self.network.source_text.splitlines():
                text = line.strip()
                if not text:
                    continue
                _emit(AssignStmt(None, Lit(True), kind="call", target_scl=text))
            if self._trace is not None:
                self._trace.append(
                    f"[net {self.network.id}] SCL/ST 文本网络（source_text）"
                )
            return folded
        for part in self.network.parts.values():
            self._steps.clear()
            name = canon_part(part.name)
            if name in COIL_PARTS:
                target = self._operand_access(part)
                kind = {
                    "NegCoil": "neg_coil",
                    "Set": "set",
                    "Reset": "reset",
                }.get(name, "coil")
                _emit(
                    AssignStmt(target, self._value_at_pin(part.uuid, "in"), kind), part
                )
            elif name in MOVE_PARTS or (part.name or "").startswith("Move"):
                src = self._pin_access(part, "in")
                dst = self._pin_access(part, "out")
                if dst is None:
                    dst = self._operand_access(part)
                src_expr: Expr = Ref(src) if src is not None else Lit("(* in *)")
                en_wires = self._wires_to_pin(part.uuid, "en")
                en_expr: Expr | None = None
                if en_wires:
                    drivers = [
                        e
                        for w in en_wires
                        for e in self._wire_driver_exprs(w, sink=(part.uuid, "en"))
                    ]
                    # Ignore pure powerrail enable (unconditional Move)
                    if drivers and drivers != [Lit(True)]:
                        en_expr = drivers[0] if len(drivers) == 1 else Or(tuple(drivers))
                _emit(
                    AssignStmt(dst, src_expr, kind="move", enable=en_expr), part
                )
            elif name in CONVERT_PARTS:
                _emit(self._fold_convert(part, name), part)
            elif name in MUX_PARTS:
                _emit(self._fold_mux(part, name), part)
            elif name in JUMP_PARTS:
                _emit(self._fold_jump(part, name), part)
            elif name in COIL_TIMER_KINDS:
                _emit(self._fold_coil_timer(part), part)
            elif name in SYS_TIME_PARTS:
                _emit(self._fold_named_func_call(part), part)
            elif name in TIME_CONV_PARTS:
                _emit(self._fold_time_conv(part), part)
            elif (
                name in MATH_BINARY_OPS or name in MATH_UNARY_FUNCS or name in CALC_PARTS
            ):
                _emit(self._fold_math_assign(part), part)
            elif (
                name in GATE_AND_PARTS
                or name in GATE_OR_PARTS
                or name in RLO_NOT_PARTS
                or name in EDGE_CONTACT_PARTS
            ):
                # RLO join / negation / edge elements fold into downstream expressions.
                continue
            elif name in BOX_PARTS:
                _emit(self._fold_box_call(part), part)
            elif (
                name in CALL_PARTS
                or part.template_values.get("Call")
                or part.template_values.get("calledBlock")
            ):
                _emit(self._fold_block_call(part), part)
            elif name in BRANCH_PARTS or name in COMPARE_OPS:
                continue
            else:
                folded.unresolved_parts.append(part.name or part.uuid or "unknown")
        return folded

    def _en_expr(self, part: Part) -> Expr | None:
        """Enable-pin condition; None when unconditional (pure powerrail)."""
        en_wires = self._wires_to_pin(part.uuid, "en")
        if not en_wires:
            return None
        drivers = [
            e for w in en_wires for e in self._wire_driver_exprs(w, sink=(part.uuid, "en"))
        ]
        if drivers and drivers != [Lit(True)]:
            return drivers[0] if len(drivers) == 1 else Or(tuple(drivers))
        return None

    def _fold_coil_timer(self, part: Part) -> AssignStmt:
        """LAD coil-form timer (CoilTON/CoilTOF/CoilTP) → instance call."""
        kind = COIL_TIMER_KINDS.get(part.name or "", "TON")
        inst = (
            self._access_bound_to_pin(part, "operand")
            or self._access_bound_to_pin(part, "instance")
            or part.accesses.get("operand")
            or part.accesses.get("instance")
        )
        inst_txt = inst.as_scl() if inst is not None else '"IEC_Timer_DB"'
        in_expr = self._value_at_pin(part.uuid, "in")
        pt_access = self._pin_access(part, "value") or self._pin_access(part, "PT")
        pt_txt = (
            pt_access.as_scl()
            if pt_access is not None
            else expr_to_scl(self._value_expr(part, "PT") or Lit("(* PT *)"))
        )
        call = f"{inst_txt}.{kind}(IN := {expr_to_scl(in_expr)}, PT := {pt_txt});"
        return AssignStmt(None, Lit(True), kind="call", target_scl=call)

    def _fold_named_func_call(self, part: Part) -> AssignStmt:
        """Fold fixed-function boxes (RD_SYS_T / WR_LOC_T…) into SCL calls."""
        fname = part.name or "FUNC"
        params: list[str] = []
        seen: set[str] = {"operand", "db", "instance", "Instance"}
        en = self._en_expr(part)
        if en is not None:
            params.append(f"EN := {expr_to_scl(en)}")
        for pin, acc in part.accesses.items():
            if pin in seen or pin.lower() in {"en"}:
                continue
            params.append(f"{pin} {_pin_assign_op(part, pin)} {acc.as_scl()}")
            seen.add(pin)
        for wire in self.network.wires:
            for ep in wire.endpoints:
                if ep.kind != "namecon" or ep.uuid != part.uuid:
                    continue
                pin = ep.pin or ""
                if not pin or pin in seen or pin.lower() in {"en", "eno"}:
                    continue
                acc = None
                for other in wire.endpoints:
                    if other.kind == "identcon":
                        acc = self.network.access_parts.get(other.uuid)
                        if acc is not None:
                            break
                if acc is None:
                    continue
                params.append(f"{pin} {_pin_assign_op(part, pin)} {acc.as_scl()}")
                seen.add(pin)
        call = f"{fname}({', '.join(params)});"
        return AssignStmt(None, Lit(True), kind="call", target_scl=call)

    def _fold_time_conv(self, part: Part) -> AssignStmt:
        """T_CONV box → typed conversion assignment with provenance comment."""
        src = self._pin_access(part, "in") or part.accesses.get("IN")
        dst = self._pin_access(part, "out") or part.accesses.get("OUT")
        src_txt = src.as_scl() if src is not None else "(* in *)"
        dst_txt = dst.as_scl() if dst is not None else "(* out *)"
        src_t = (part.template_values.get("src_type") or "").strip()
        dest_t = (part.template_values.get("dest_type") or "").strip()
        comment = "T_CONV" + (f" {src_t} → {dest_t}" if src_t or dest_t else "")
        line = f"{dst_txt} := {src_txt}; (* {comment} *)"
        return AssignStmt(None, Lit(True), kind="call", target_scl=line)

    def _fold_math_assign(self, part: Part) -> AssignStmt:
        """Math box (Add/Mul/Sin/Calc/Swap…) → value assignment on its out pin."""
        rhs = self._math_rhs_expr(part)
        if rhs is None:
            return AssignStmt(
                None,
                Lit(True),
                kind="call",
                target_scl=f"(* TODO[{part.name or 'math'}] *)",
            )
        dst = self._pin_access(part, "out")
        return AssignStmt(dst, rhs, kind="move", enable=self._en_expr(part))

    def _pin_has_real_driver(self, part: Part, pin: str) -> bool:
        """True when pin wire has a non-OpenCon driver (skip dangling R/LD etc.)."""
        for wire in self._wires_to_pin(part.uuid, pin):
            for endpoint in wire.endpoints:
                if (
                    endpoint.kind == "namecon"
                    and endpoint.uuid == part.uuid
                    and _same_pin(endpoint.pin, pin)
                ):
                    continue
                if endpoint.kind == "opencon":
                    continue
                return True
        return False

    def _fold_block_call(self, part: Part) -> AssignStmt:
        """Fold FC/FB Call parts into SCL call statements (wires + CallInfo params)."""
        called = (
            part.template_values.get("Call")
            or part.template_values.get("calledBlock")
            or ""
        ).strip().strip('"') or "UNKNOWN_BLOCK"
        instance = (
            part.accesses.get("instance")
            or part.accesses.get("Instance")
            or self._pin_access(part, "db")
        )
        params: list[str] = []
        seen_pins: set[str] = set()

        # 1) Explicit Access on CallInfo Parameter
        for pin, acc in part.accesses.items():
            if pin in _SKIP_CALL_PINS or pin in {"instance", "Instance"}:
                continue
            op = _pin_assign_op(part, pin)
            params.append(f"{pin} {op} {acc.as_scl()}")
            seen_pins.add(pin)

        # 2) FlgNet wires onto call pins
        for wire in self.network.wires:
            for ep in wire.endpoints:
                if ep.kind != "namecon" or ep.uuid != part.uuid:
                    continue
                pin = ep.pin or ""
                if not pin or pin in _SKIP_CALL_PINS or pin in seen_pins:
                    continue
                acc = None
                for other in wire.endpoints:
                    if other.kind == "identcon":
                        acc = self.network.access_parts.get(other.uuid)
                        if acc is not None:
                            break
                if acc is None:
                    continue
                op = _pin_assign_op(part, pin)
                params.append(f"{pin} {op} {acc.as_scl()}")
                seen_pins.add(pin)

        if instance is not None and instance.root:
            callee = (
                f"#{instance.root}"
                if instance.scope == AccessScope.LOCAL
                else f'"{instance.root}"'
            )
            # Siemens: multi-instance / InstanceDB → call the instance, not Type.method
            call = f"{callee}({', '.join(params)});"
        else:
            call = f"{called}({', '.join(params)});"
        return AssignStmt(None, Lit(True), kind="call", target_scl=call)

    def _fold_box_call(self, part: Part) -> AssignStmt:
        """Fold IEC counter/timer/edge/latch boxes into a call-like SCL statement.

        Siemens exports mix cases on box pins (SR uses s/r1/q, timers IN/PT/Q),
        so pins are matched case-insensitively and emitted canonically. The
        instance comes from the operand/instance pin or the InstanceDB
        template. Timers and SR/RS latches call their typed member:
        ``#Timer.TON(IN := …)`` / ``#Latch.SR(S := …)`` — downstream RLO reads
        the instance output (``#Timer.Q``) instead.
        """
        name = canon_part(part.name)
        inst = self._box_instance_access(part)
        inst_txt = (
            inst.as_scl()
            if inst is not None and inst.root
            else (
                f'"{part.template_values["InstanceDB"]}"'
                if part.template_values.get("InstanceDB")
                else (part.name or "Box")
            )
        )
        wired_pins: dict[str, str] = {}  # canonical pin -> actual label on wires
        for wire in self.network.wires:
            for endpoint in wire.endpoints:
                if endpoint.kind == "namecon" and endpoint.uuid == part.uuid and endpoint.pin:
                    wired_pins.setdefault((endpoint.pin or "").upper(), endpoint.pin)
        access_pins = {key.upper(): key for key in part.accesses}

        params: list[str] = []
        # Boolean / RLO inputs may be driven by contacts, not IdentCon Access.
        for pin in _BOX_RLO_PINS:
            actual = wired_pins.get(pin) or access_pins.get(pin)
            if actual is None:
                continue
            access = part.accesses.get(actual) or part.accesses.get(pin)
            if wired_pins.get(pin) and self._pin_has_real_driver(part, actual):
                params.append(f"{pin} := {expr_to_scl(self._value_at_pin(part.uuid, actual))}")
            elif access is not None:
                params.append(f"{pin} := {access.as_scl()}")
        for pin in _BOX_VALUE_PINS:
            actual = wired_pins.get(pin) or access_pins.get(pin)
            if actual is None:
                continue
            access = (
                self._pin_access(part, actual)
                or part.accesses.get(actual)
                or part.accesses.get(pin)
            )
            if access is not None:
                params.append(f"{pin} := {access.as_scl()}")
        for pin in _BOX_OUT_PIN_ORDER:
            actual = wired_pins.get(pin) or access_pins.get(pin)
            if actual is None:
                continue
            access = (
                self._pin_access(part, actual)
                or part.accesses.get(actual)
                or part.accesses.get(pin)
            )
            if access is not None:
                params.append(f"{pin} => {access.as_scl()}")
        callee = f"{inst_txt}.{name}" if name in TIMER_PARTS or name in LATCH_PARTS else inst_txt
        call = f"{callee}({', '.join(params)});"
        return AssignStmt(None, Lit(True), kind="call", target_scl=call)

    def _fold_convert(self, part: Part, name: str) -> AssignStmt:
        src = self._pin_access(part, "in") or part.accesses.get("in")
        dst = self._pin_access(part, "out") or part.accesses.get("out")
        src_txt = src.as_scl() if src is not None else "(* in *)"
        dst_txt = dst.as_scl() if dst is not None else "(* out *)"
        # EN input conditions the conversion (FB5009: IF Cmd.Read1 THEN …).
        en = self._en_expr(part)
        if name == "Round":
            line = _wrap_en(f"{dst_txt} := ROUND({src_txt});", en)
        else:
            to_type = (
                part.template_values.get("DestType")
                or part.template_values.get("Type")
                or part.template_values.get("OutType")
                or ""
            ).strip()
            comment = f" (* Convert → {to_type} *)" if to_type else " (* Convert *)"
            line = _wrap_en(f"{dst_txt} := {src_txt};", en) + comment
        return AssignStmt(None, Lit(True), kind="call", target_scl=line)

    def _fold_mux(self, part: Part, name: str) -> AssignStmt:
        k = self._pin_access(part, "k") or part.accesses.get("k") or part.accesses.get("K")
        out = self._pin_access(part, "out") or part.accesses.get("out")
        k_txt = k.as_scl() if k is not None else "#K"
        out_txt = out.as_scl() if out is not None else "(* out *)"
        en = self._en_expr(part)
        if name == "Demux":
            ins = self._pin_access(part, "in") or part.accesses.get("in")
            in_txt = ins.as_scl() if ins is not None else "(* in *)"
            line = _wrap_en(f"(* Demux *) CASE {k_txt} OF (* {in_txt} → {out_txt} *); END_CASE;", en)
        else:
            ins = []
            for pin in ("in0", "in1", "in2", "in3", "IN0", "IN1"):
                acc = self._pin_access(part, pin) or part.accesses.get(pin)
                if acc is not None:
                    ins.append(acc.as_scl())
            args = ", ".join([k_txt, *ins]) if ins else k_txt
            line = _wrap_en(f"{out_txt} := (* Mux *) {args};", en)
        return AssignStmt(None, Lit(True), kind="call", target_scl=line)

    def _fold_jump(self, part: Part, name: str) -> AssignStmt:
        label = (
            part.template_values.get("Label")
            or part.template_values.get("Name")
            or (self._operand_access(part).raw if self._operand_access(part) else "")
            or part.name
        )
        if name == "Label":
            line = f"{label}:"
        elif name == "Return":
            cond = expr_to_scl(self._value_at_pin(part.uuid, "in"))
            line = "RETURN;" if cond == "TRUE" else f"IF {cond} THEN RETURN; END_IF;"
        else:
            cond = expr_to_scl(self._value_at_pin(part.uuid, "in"))
            line = f"JMP {label};" if cond == "TRUE" else f"IF {cond} THEN JMP {label}; END_IF;"
        return AssignStmt(None, Lit(True), kind="call", target_scl=line)


def fold_network(network: Network, trace: list[str] | None = None) -> FoldedNetwork:
    """Fold one LAD/FBD network's FlgNet wires into expression statements.

    ``trace`` (optional) collects ast_trace lines for this network; None = off.
    """
    return _NetworkFolder(network, trace=trace).fold()


def fold_block(block: Block, trace: list[str] | None = None) -> list[FoldedNetwork]:
    """Fold every network in a block."""
    return [fold_network(network, trace=trace) for network in block.networks]


def _expr_to_dict(expr: Expr) -> dict:
    if isinstance(expr, Lit):
        return {"type": "literal", "value": expr.value}
    if isinstance(expr, Ref):
        return {"type": "ref", "access": expr.access.as_scl()}
    if isinstance(expr, Not):
        return {"type": "not", "operand": _expr_to_dict(expr.operand)}
    if isinstance(expr, And):
        return {"type": "and", "operands": [_expr_to_dict(item) for item in expr.operands]}
    if isinstance(expr, Or):
        return {"type": "or", "operands": [_expr_to_dict(item) for item in expr.operands]}
    if isinstance(expr, Compare):
        return {
            "type": "compare",
            "op": expr.op,
            "lhs": _expr_to_dict(expr.lhs),
            "rhs": _expr_to_dict(expr.rhs),
        }
    if isinstance(expr, Arith):
        return {
            "type": "arith",
            "op": expr.op,
            "operands": [_expr_to_dict(item) for item in expr.operands],
        }
    if isinstance(expr, Func):
        return {
            "type": "func",
            "name": expr.name,
            "args": [_expr_to_dict(arg) for arg in expr.args],
        }
    if isinstance(expr, Raw):
        return {"type": "raw", "text": expr.text}
    raise TypeError(f"Unsupported expression: {type(expr).__name__}")


def folded_to_dict(folded: FoldedNetwork) -> dict:
    """Return a JSON-serializable representation of folded logic."""
    return {
        "network_id": folded.network_id,
        "title": folded.title,
        "statements": [
            {
                "target": statement.target.as_scl() if statement.target is not None else statement.target_scl,
                "kind": statement.kind,
                "value": _expr_to_dict(statement.value),
                # Additive provenance (FoldStmt): exact originating FlgNet part.
                "part_uuid": getattr(statement, "part_uuid", ""),
                "part_name": getattr(statement, "part_name", ""),
                **(
                    {"enable": _expr_to_dict(statement.enable)}
                    if statement.enable is not None
                    else {}
                ),
            }
            for statement in folded.statements
        ],
        "unresolved_parts": folded.unresolved_parts,
        "evidence": folded.evidence,
    }


def attach_folded(
    project: PlcProject,
    trace_out: dict[str, list[str]] | None = None,
) -> PlcProject:
    """Attach folded expressions to every project network and return the project.

    ``trace_out`` (optional) receives ``{block_name: [ast_trace lines]}`` for the
    fold (contract docs/15 §4); None keeps the default no-trace behavior.
    """
    jobs: list[tuple[str, int]] = [
        (block.name, idx)
        for block in project.blocks.values()
        for idx, _network in enumerate(block.networks)
    ]

    def _fold_job(item: tuple[str, int]):
        name, idx = item
        block_trace: list[str] | None = None if trace_out is None else []
        return name, idx, fold_network(project.blocks[name].networks[idx], trace=block_trace), block_trace

    from agents.plc.tia.parallel import map_parallel

    for name, idx, folded, block_trace in map_parallel(_fold_job, jobs, min_items=8):
        project.blocks[name].networks[idx].folded = folded
        if trace_out is not None and block_trace:
            trace_out.setdefault(name, []).extend(block_trace)
    return project


def fold_project(
    project: PlcProject,
    trace_out: dict[str, list[str]] | None = None,
) -> dict[str, list[dict]]:
    """Return JSON-ready folded logic keyed by block name."""
    result: dict[str, list[dict]] = {}
    for block in project.blocks.values():
        block_trace = trace_out.get(block.name) if trace_out is not None else None
        networks: list[dict] = []
        for network in block.networks:
            if network.folded is None:
                network.folded = fold_network(network, trace=block_trace)
            networks.append(folded_to_dict(network.folded))
        result[block.name] = networks
    return result
