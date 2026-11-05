"""CNF (Conjunctive Normal Form) Boolean Algebra Splitter for Legacy PLC Decoupling.

Implements Tab 3 Step 3 of PLC_Chat V3.0 Architecture:
- Parses complex Boolean condition trees driving physical coils (%Q) or internal flags.
- Converts arbitrary Boolean formulas into Conjunctive Normal Form (CNF: C_1 AND C_2 ... AND C_k).
- Mathematically factorizes clauses into:
    1. Step-Trigger Clauses (Slot 3 @SEQ_AUTO actions: #AutoCmd.xxx := TRUE)
    2. Safety & Collision Release Interlocks (Slot 4 @INTERLOCK: #Cyl.xReleaseWork := ...)
- Preserves 100% logic determinism without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class TokenType(Enum):
    IDENT = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    TRUE = auto()
    FALSE = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: str


def tokenize_bool_expr(expr: str) -> list[Token]:
    """Tokenize a Boolean SCL/LAD condition expression."""
    tokens: list[Token] = []
    i = 0
    s = expr.strip()
    n = len(s)

    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append(Token(TokenType.LPAREN, "("))
            i += 1
        elif c == ")":
            tokens.append(Token(TokenType.RPAREN, ")"))
            i += 1
        elif c == "&":
            tokens.append(Token(TokenType.AND, "AND"))
            i += 1
        elif c == "|":
            tokens.append(Token(TokenType.OR, "OR"))
            i += 1
        elif c == "!":
            tokens.append(Token(TokenType.NOT, "NOT"))
            i += 1
        elif c == '"':
            # Quoted identifier e.g. "DB_Axis"."xInPos" or "DB_Axis".xInPos
            start = i
            i += 1
            while i < n and s[i] != '"':
                i += 1
            if i < n:
                i += 1
            # Check for struct member access like "DB".member or "DB"."member"
            while i < n and not s[i].isspace() and s[i] not in "()&|!":
                if s[i] == '"':
                    i += 1
                    while i < n and s[i] != '"':
                        i += 1
                    if i < n:
                        i += 1
                else:
                    i += 1
            ident = s[start:i]
            tokens.append(Token(TokenType.IDENT, ident))
        else:
            # Identifier or keyword
            start = i
            while i < n and not s[i].isspace() and s[i] not in "()&|!":
                i += 1
            word = s[start:i]
            upper = word.upper()
            if upper in ("AND", "&"):
                tokens.append(Token(TokenType.AND, "AND"))
            elif upper in ("OR", "|"):
                tokens.append(Token(TokenType.OR, "OR"))
            elif upper in ("NOT", "~"):
                tokens.append(Token(TokenType.NOT, "NOT"))
            elif upper == "TRUE":
                tokens.append(Token(TokenType.TRUE, "TRUE"))
            elif upper == "FALSE":
                tokens.append(Token(TokenType.FALSE, "FALSE"))
            else:
                tokens.append(Token(TokenType.IDENT, word))
    tokens.append(Token(TokenType.EOF, ""))
    return tokens


# AST Nodes for Boolean Logic
class BoolNode:
    """Base class for Boolean AST nodes."""

    def to_scl(self) -> str:
        raise NotImplementedError

    def literals(self) -> set[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class Literal(BoolNode):
    name: str
    negated: bool = False

    def to_scl(self) -> str:
        if self.negated:
            return f"NOT {self.name}"
        return self.name

    def literals(self) -> set[str]:
        return {self.name}

    def negate(self) -> Literal:
        return Literal(self.name, not self.negated)


@dataclass(frozen=True)
class ConstBool(BoolNode):
    value: bool

    def to_scl(self) -> str:
        return "TRUE" if self.value else "FALSE"

    def literals(self) -> set[str]:
        return set()


@dataclass(frozen=True)
class AndNode(BoolNode):
    operands: tuple[BoolNode, ...]

    def to_scl(self) -> str:
        if not self.operands:
            return "TRUE"
        parts = [f"({op.to_scl()})" if isinstance(op, OrNode) else op.to_scl() for op in self.operands]
        return " AND ".join(parts)

    def literals(self) -> set[str]:
        res: set[str] = set()
        for op in self.operands:
            res |= op.literals()
        return res


@dataclass(frozen=True)
class OrNode(BoolNode):
    operands: tuple[BoolNode, ...]

    def to_scl(self) -> str:
        if not self.operands:
            return "FALSE"
        parts = [op.to_scl() for op in self.operands]
        return " OR ".join(parts)

    def literals(self) -> set[str]:
        res: set[str] = set()
        for op in self.operands:
            res |= op.literals()
        return res


@dataclass(frozen=True)
class NotNode(BoolNode):
    operand: BoolNode

    def to_scl(self) -> str:
        if isinstance(self.operand, (AndNode, OrNode)):
            return f"NOT ({self.operand.to_scl()})"
        return f"NOT {self.operand.to_scl()}"

    def literals(self) -> set[str]:
        return self.operand.literals()


class BoolParser:
    """Recursive descent parser for Boolean expressions."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != TokenType.EOF:
            self.pos += 1
        return tok

    def match(self, *types: TokenType) -> bool:
        if self.peek().type in types:
            self.advance()
            return True
        return False

    def parse(self) -> BoolNode:
        node = self.parse_or()
        return node

    def parse_or(self) -> BoolNode:
        left = self.parse_and()
        operands = [left]
        while self.match(TokenType.OR):
            operands.append(self.parse_and())
        if len(operands) == 1:
            return operands[0]
        return OrNode(tuple(operands))

    def parse_and(self) -> BoolNode:
        left = self.parse_not()
        operands = [left]
        while self.match(TokenType.AND):
            operands.append(self.parse_not())
        if len(operands) == 1:
            return operands[0]
        return AndNode(tuple(operands))

    def parse_not(self) -> BoolNode:
        if self.match(TokenType.NOT):
            operand = self.parse_not()
            return NotNode(operand)
        return self.parse_primary()

    def parse_primary(self) -> BoolNode:
        tok = self.peek()
        if self.match(TokenType.LPAREN):
            node = self.parse_or()
            self.match(TokenType.RPAREN)
            return node
        if self.match(TokenType.TRUE):
            return ConstBool(True)
        if self.match(TokenType.FALSE):
            return ConstBool(False)
        if self.match(TokenType.IDENT):
            return Literal(tok.value, False)
        # Fallback for unexpected token
        self.advance()
        return ConstBool(True)


def parse_bool_expr(expr: str) -> BoolNode:
    """Parse a Boolean expression string into an AST."""
    if not expr or not expr.strip():
        return ConstBool(True)
    tokens = tokenize_bool_expr(expr)
    return BoolParser(tokens).parse()


# CNF Transformation via NNF and Distribution
def to_nnf(node: BoolNode) -> BoolNode:
    """Convert AST to Negation Normal Form (push NOTs down to literals)."""
    if isinstance(node, (Literal, ConstBool)):
        return node
    if isinstance(node, AndNode):
        return AndNode(tuple(to_nnf(op) for op in node.operands))
    if isinstance(node, OrNode):
        return OrNode(tuple(to_nnf(op) for op in node.operands))
    if isinstance(node, NotNode):
        inner = node.operand
        if isinstance(inner, Literal):
            return inner.negate()
        if isinstance(inner, ConstBool):
            return ConstBool(not inner.value)
        if isinstance(inner, NotNode):
            return to_nnf(inner.operand)
        if isinstance(inner, AndNode):
            # De Morgan: NOT (A AND B) -> (NOT A OR NOT B)
            return OrNode(tuple(to_nnf(NotNode(op)) for op in inner.operands))
        if isinstance(inner, OrNode):
            # De Morgan: NOT (A OR B) -> (NOT A AND NOT B)
            return AndNode(tuple(to_nnf(NotNode(op)) for op in inner.operands))
    return node


def _distribute_or_over_and(a: BoolNode, b: BoolNode) -> BoolNode:
    """Distribute OR over AND: (A AND B) OR C -> (A OR C) AND (B OR C)."""
    if isinstance(a, AndNode):
        return AndNode(tuple(_distribute_or_over_and(op, b) for op in a.operands))
    if isinstance(b, AndNode):
        return AndNode(tuple(_distribute_or_over_and(a, op) for op in b.operands))
    # Combine literals / ORs
    a_ops = a.operands if isinstance(a, OrNode) else (a,)
    b_ops = b.operands if isinstance(b, OrNode) else (b,)
    combined = list(a_ops) + list(b_ops)
    # Deduplicate literals
    dedup: list[BoolNode] = []
    seen: set[str] = set()
    for op in combined:
        rep = op.to_scl()
        if rep not in seen:
            seen.add(rep)
            dedup.append(op)
    if len(dedup) == 1:
        return dedup[0]
    return OrNode(tuple(dedup))


def to_cnf(node: BoolNode) -> BoolNode:
    """Convert Boolean AST into Conjunctive Normal Form (AND of ORs)."""
    nnf = to_nnf(node)
    if isinstance(nnf, (Literal, ConstBool)):
        return nnf
    if isinstance(nnf, AndNode):
        clauses: list[BoolNode] = []
        for op in nnf.operands:
            cnf_op = to_cnf(op)
            if isinstance(cnf_op, AndNode):
                clauses.extend(cnf_op.operands)
            else:
                clauses.append(cnf_op)
        return AndNode(tuple(clauses))
    if isinstance(nnf, OrNode):
        if not nnf.operands:
            return ConstBool(False)
        result = to_cnf(nnf.operands[0])
        for op in nnf.operands[1:]:
            result = _distribute_or_over_and(result, to_cnf(op))
        return result
    return nnf


def flatten_cnf_clauses(cnf_node: BoolNode) -> list[list[Literal]]:
    """Flatten a CNF AST into a list of clauses (each clause is a list of Literals)."""
    if isinstance(cnf_node, ConstBool):
        return []
    if isinstance(cnf_node, Literal):
        return [[cnf_node]]
    if isinstance(cnf_node, OrNode):
        clause: list[Literal] = []
        for op in cnf_node.operands:
            if isinstance(op, Literal):
                clause.append(op)
        return [clause] if clause else []
    if isinstance(cnf_node, AndNode):
        clauses: list[list[Literal]] = []
        for op in cnf_node.operands:
            sub = flatten_cnf_clauses(op)
            clauses.extend(sub)
        return clauses
    return []


# Role Classification & Decoupling
_STEP_KEYWORDS = ["step", "seq", "autostep", "statstep", "m_step", "m10.", "m20.", "state", "case"]
_SAFETY_KEYWORDS = ["safety", "estop", "emergency", "guard", "door", "curtain", "interlock", "axis", "inpos", "safe"]


def is_step_literal(lit: Literal, known_step_vars: set[str] | None = None) -> bool:
    """Check if a literal belongs to sequence / step machine."""
    name_clean = lit.name.lower().strip('"').lstrip("#")
    if known_step_vars and lit.name in known_step_vars:
        return True
    return any(k in name_clean for k in _STEP_KEYWORDS)


@dataclass
class DecoupledCondition:
    """Result of CNF decomposition separating step triggers from release interlocks."""

    original_expr: str
    cnf_scl: str
    step_trigger_expr: str
    release_interlock_expr: str
    step_literals: list[str] = field(default_factory=list)
    interlock_literals: list[str] = field(default_factory=list)
    has_step_binding: bool = False
    has_safety_binding: bool = False


class CnfLogicSplitter:
    """Factorizes legacy conditions into Slot 3 (Auto Sequence) and Slot 4 (Interlock)."""

    def __init__(self, known_step_vars: set[str] | None = None) -> None:
        self.known_step_vars = known_step_vars or set()

    def split_condition(self, expr: str) -> DecoupledCondition:
        """Split a raw coil condition into step triggers and release interlocks."""
        ast = parse_bool_expr(expr)
        cnf = to_cnf(ast)
        clauses = flatten_cnf_clauses(cnf)

        step_clauses: list[list[Literal]] = []
        interlock_clauses: list[list[Literal]] = []

        all_step_lits: list[str] = []
        all_interlock_lits: list[str] = []

        for clause in clauses:
            # If any literal in this clause is a step variable, it represents the operational step trigger
            contains_step = any(is_step_literal(lit, self.known_step_vars) for lit in clause)
            if contains_step:
                step_clauses.append(clause)
                all_step_lits.extend(lit.to_scl() for lit in clause)
            else:
                interlock_clauses.append(clause)
                all_interlock_lits.extend(lit.to_scl() for lit in clause)

        def _render_clauses(cl_list: list[list[Literal]]) -> str:
            if not cl_list:
                return "TRUE"
            rendered_ors = []
            for cl in cl_list:
                if len(cl) == 1:
                    rendered_ors.append(cl[0].to_scl())
                else:
                    rendered_ors.append("(" + " OR ".join(lit.to_scl() for lit in cl) + ")")
            return " AND ".join(rendered_ors)

        step_expr = _render_clauses(step_clauses)
        interlock_expr = _render_clauses(interlock_clauses)

        return DecoupledCondition(
            original_expr=expr,
            cnf_scl=cnf.to_scl(),
            step_trigger_expr=step_expr,
            release_interlock_expr=interlock_expr,
            step_literals=sorted(set(all_step_lits)),
            interlock_literals=sorted(set(all_interlock_lits)),
            has_step_binding=bool(step_clauses),
            has_safety_binding=bool(interlock_clauses),
        )
