"""Boolean guard/invariant expression parser + evaluator (shared grammar).

Grammar (see processos/contract/interfaces.py):
  expr := and_expr ("OR" and_expr)*
  and_expr := unary ("AND" unary)*
  unary := "NOT" unary | "(" expr ")" | TOKEN
Tokens are identifiers; resolution order (input > command > feedback) is the
caller's job when building the evaluation environment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"\s*(?:(AND|OR|NOT)(?![A-Za-z0-9_])|([A-Za-z_][A-Za-z0-9_.]*)|(\()|(\)))")


class GuardError(ValueError):
    """Invalid guard syntax or unresolvable token."""


@dataclass(frozen=True)
class _Node:
    kind: str  # token | not | and | or
    value: str = ""
    children: tuple = ()


def _tokenize(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        if expr[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise GuardError(f"invalid guard character at {pos}: {expr[pos:]!r}")
        kw, ident, lp, rp = m.groups()
        tokens.append(kw or ident or lp or rp)
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise GuardError("unexpected end of guard expression")
        self.i += 1
        return tok

    def parse(self) -> _Node:
        node = self.or_expr()
        if self.peek() is not None:
            raise GuardError(f"unexpected token {self.peek()!r}")
        return node

    def or_expr(self) -> _Node:
        children = [self.and_expr()]
        while self.peek() == "OR":
            self.take()
            children.append(self.and_expr())
        return children[0] if len(children) == 1 else _Node("or", children=tuple(children))

    def and_expr(self) -> _Node:
        children = [self.unary()]
        while self.peek() == "AND":
            self.take()
            children.append(self.unary())
        return children[0] if len(children) == 1 else _Node("and", children=tuple(children))

    def unary(self) -> _Node:
        tok = self.peek()
        if tok == "NOT":
            self.take()
            return _Node("not", children=(self.unary(),))
        if tok == "(":
            self.take()
            node = self.or_expr()
            if self.take() != ")":
                raise GuardError("expected ')'")
            return node
        if tok is None:
            raise GuardError("unexpected end of guard expression")
        if tok in ("AND", "OR", ")"):
            raise GuardError(f"unexpected token {tok!r}")
        self.take()
        return _Node("token", value=tok)


def _eval(node: _Node, env: dict[str, bool]) -> bool:
    if node.kind == "true":
        return True
    if node.kind == "token":
        if node.value not in env:
            raise GuardError(f"unresolved guard token {node.value!r}")
        return bool(env[node.value])
    if node.kind == "not":
        return not _eval(node.children[0], env)
    if node.kind == "and":
        return all(_eval(c, env) for c in node.children)
    if node.kind == "or":
        return any(_eval(c, env) for c in node.children)
    raise GuardError(f"unknown node kind {node.kind!r}")


def _collect(node: _Node, out: set[str]) -> None:
    if node.kind == "token":
        out.add(node.value)
    for c in node.children:
        _collect(c, out)


@dataclass(frozen=True)
class Guard:
    expr: str
    _ast: _Node
    tokens: frozenset[str]

    def evaluate(self, env: dict[str, bool]) -> bool:
        return _eval(self._ast, env)


def parse_guard(expr: str) -> Guard:
    expr = (expr or "").strip()
    if not expr:
        return Guard(expr="", _ast=_Node("true"), tokens=frozenset())
    ast = _Parser(_tokenize(expr)).parse()
    tokens: set[str] = set()
    _collect(ast, tokens)
    return Guard(expr=expr, _ast=ast, tokens=frozenset(tokens))


def always_true() -> Guard:
    return parse_guard("")


def eval_guard(expr: str, env: dict[str, bool]) -> bool:
    g = parse_guard(expr)
    if not g.expr:
        return True
    return g.evaluate(env)