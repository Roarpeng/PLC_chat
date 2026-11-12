"""Strong-typed Guard AST for SequenceIR (WP-03 / G3).

Hard rules:
  * only BOOL / TIME / INT value types;
  * only the closed node-type whitelist below;
  * **no eval(), no exec(), no free-text boolean expression**;
  * unknown node / unknown signal / type mismatch => fail-closed (False + issue).

The AST is a pure standard-library data structure. Both the offline scan
simulator and the SCL lowering consume the very same ``evaluate`` semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any


class GuardNodeType(str, Enum):
    CONST = "CONST"
    SIGNAL = "SIGNAL"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"
    ELAPSED_GE = "ELAPSED_GE"


class GuardValueType(str, Enum):
    BOOL = "BOOL"
    TIME = "TIME"
    INT = "INT"


BINARY_COMPARISONS: frozenset[GuardNodeType] = frozenset(
    {GuardNodeType.EQ, GuardNodeType.NE, GuardNodeType.LT, GuardNodeType.LE, GuardNodeType.GT, GuardNodeType.GE}
)
LOGICAL_NODES: frozenset[GuardNodeType] = frozenset({GuardNodeType.AND, GuardNodeType.OR, GuardNodeType.NOT})
NUMERIC_TYPES: frozenset[GuardValueType] = frozenset({GuardValueType.TIME, GuardValueType.INT})
FREE_TEXT_KEYS: frozenset[str] = frozenset({"expression", "expr", "text", "code", "eval", "formula"})

#: Strict schema: only these keys are accepted in a GuardAST node.
ALLOWED_GUARD_KEYS: frozenset[str] = frozenset({
    "node_type", "value_type", "signal", "value", "children", "source_id",
})

#: A signal name must be a plain (optionally dotted) identifier. This blocks
#: SCL injection such as ``X : BOOL; (* payload *)`` from ever reaching codegen.
GUARD_SIGNAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def is_valid_guard_signal(signal: str) -> bool:
    """Return True only for a safe, injection-free signal identifier."""
    return bool(isinstance(signal, str) and GUARD_SIGNAL_RE.match(signal))


class GuardValidationError(ValueError):
    """Raised when a guard payload contains free text or an unknown construct."""


def _parse_node_type(value: Any) -> GuardNodeType | str:
    try:
        return GuardNodeType(str(value))
    except (ValueError, TypeError):
        return str(value)


def _parse_value_type(value: Any) -> GuardValueType | str:
    try:
        return GuardValueType(str(value))
    except (ValueError, TypeError):
        return str(value)


@dataclass
class GuardAST:
    """A typed boolean expression tree.

    ``node_type`` selects the operator, ``value_type`` declares the static type
    of this node's result, ``signal`` names the snapshot key for SIGNAL nodes,
    ``value`` holds a CONST literal, and ``children`` holds sub-expressions.
    """

    node_type: GuardNodeType = GuardNodeType.CONST
    value_type: GuardValueType = GuardValueType.BOOL
    signal: str = ""
    value: Any = None
    children: list[GuardAST] = field(default_factory=list)
    source_id: str = ""

    # ------------------------------------------------------------------ IO --
    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type.value if isinstance(self.node_type, GuardNodeType) else str(self.node_type),
            "value_type": self.value_type.value if isinstance(self.value_type, GuardValueType) else str(self.value_type),
            "signal": self.signal,
            "value": self.value,
            "children": [child.to_dict() for child in self.children],
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GuardAST:
        """Strict builder: rejects free-text expressions and unknown fields."""
        if not isinstance(data, dict):
            raise GuardValidationError("guard must be a structured object, not free text")
        for key in data:
            lowered = str(key).lower()
            if lowered in FREE_TEXT_KEYS:
                raise GuardValidationError(f"free-text guard expression is forbidden: {key}")
            if str(key) not in ALLOWED_GUARD_KEYS:
                raise GuardValidationError(f"unknown guard field {key!r} (strict schema)")
        node_type = _parse_node_type(data.get("node_type"))
        if not isinstance(node_type, GuardNodeType):
            raise GuardValidationError(f"unknown guard node type: {node_type!r}")
        value_type = _parse_value_type(data.get("value_type") or "BOOL")
        children_raw = data.get("children") or []
        if not isinstance(children_raw, list):
            raise GuardValidationError("guard.children must be a list")
        children = [child if isinstance(child, GuardAST) else cls.from_dict(child) for child in children_raw]
        return cls(
            node_type=node_type,
            value_type=value_type if isinstance(value_type, GuardValueType) else GuardValueType.BOOL,
            signal=str(data.get("signal") or ""),
            value=data.get("value"),
            children=children,
            source_id=str(data.get("source_id") or ""),
        )

    # ----------------------------------------------------------- validation --
    def validate_types(self) -> list[str]:
        """Return a deterministic list of static type/unknown-reference issues."""
        issues: list[str] = []
        node = self.node_type
        vtype = self.value_type
        if not isinstance(node, GuardNodeType):
            issues.append(f"unknown guard node type: {node!r}")
            return issues
        if not isinstance(vtype, GuardValueType):
            issues.append(f"unknown guard value type: {vtype!r}")
            return issues

        if node is GuardNodeType.CONST:
            if vtype is GuardValueType.BOOL and not isinstance(self.value, bool):
                issues.append("CONST BOOL requires a bool value")
            if vtype in NUMERIC_TYPES and (not isinstance(self.value, int) or isinstance(self.value, bool)):
                issues.append(f"CONST {vtype.value} requires an int value (TIME = milliseconds)")
            if vtype not in {GuardValueType.BOOL, *NUMERIC_TYPES}:
                issues.append(f"unsupported CONST value type {vtype.value}")

        elif node is GuardNodeType.SIGNAL:
            if not self.signal:
                issues.append("SIGNAL guard requires a non-empty signal name")
            elif not is_valid_guard_signal(self.signal):
                issues.append(
                    f"SIGNAL guard has an invalid identifier {self.signal!r} "
                    "(fail-closed: free text / SCL injection is forbidden)"
                )
            if self.value is not None:
                issues.append("SIGNAL guard must not carry a literal value")

        elif node in LOGICAL_NODES:
            if vtype is not GuardValueType.BOOL:
                issues.append(f"{node.value} node must produce BOOL")
            if node is GuardNodeType.NOT and len(self.children) != 1:
                issues.append("NOT requires exactly one child")
            if node in (GuardNodeType.AND, GuardNodeType.OR) and len(self.children) < 1:
                issues.append(f"{node.value} requires at least one child")
            for child in self.children:
                if child.value_type is not GuardValueType.BOOL:
                    issues.append(f"{node.value} child must be BOOL, got {child.value_type}")
                issues.extend(child.validate_types())

        elif node in BINARY_COMPARISONS:
            if vtype is not GuardValueType.BOOL:
                issues.append(f"{node.value} comparison must produce BOOL")
            if len(self.children) != 2:
                issues.append(f"{node.value} requires exactly two children")
            else:
                left, right = self.children
                if left.value_type is not right.value_type:
                    issues.append(f"{node.value} operands must share a type: {left.value_type} vs {right.value_type}")
                if left.value_type not in NUMERIC_TYPES:
                    issues.append(f"{node.value} operands must be TIME or INT, got {left.value_type}")
                for child in self.children:
                    issues.extend(child.validate_types())

        elif node is GuardNodeType.ELAPSED_GE:
            if vtype is not GuardValueType.BOOL:
                issues.append("ELAPSED_GE must produce BOOL")
            if len(self.children) != 2:
                issues.append("ELAPSED_GE requires (elapsed signal, threshold const)")
            else:
                left, right = self.children
                if left.node_type is not GuardNodeType.SIGNAL:
                    issues.append("ELAPSED_GE first child must be a SIGNAL")
                if right.node_type is not GuardNodeType.CONST or right.value_type not in NUMERIC_TYPES:
                    issues.append("ELAPSED_GE second child must be a numeric CONST threshold")
                for child in self.children:
                    issues.extend(child.validate_types())
        return issues

    def is_valid(self) -> bool:
        """True when this guard subtree passes static type validation."""
        return not self.validate_types()

    # ------------------------------------------------------------ evaluation --
    def evaluate(self, snapshot: dict[str, Any]) -> bool:
        """Fail-closed evaluation. Unknown/mistyped input evaluates to False."""
        result, _ = self.evaluate_detailed(snapshot)
        return result

    def evaluate_detailed(self, snapshot: dict[str, Any]) -> tuple[bool, list[str]]:
        """Evaluate and return ``(result, issues)`` for Trace diagnostics."""
        issues = self.validate_types()
        if issues:
            return False, issues
        return self._eval(snapshot, issues)

    def _eval(self, snapshot: dict[str, Any], issues: list[str]) -> tuple[bool, list[str]]:
        node = self.node_type
        if node is GuardNodeType.CONST:
            if self.value_type is GuardValueType.BOOL:
                return bool(self.value), issues
            return True, issues

        if node is GuardNodeType.SIGNAL:
            if self.signal not in snapshot:
                issues.append(f"unknown signal {self.signal!r} (fail-closed)")
                return False, issues
            raw = snapshot[self.signal]
            if self.value_type is GuardValueType.BOOL:
                if not isinstance(raw, bool):
                    issues.append(f"signal {self.signal!r} expected BOOL, got {type(raw).__name__}")
                    return False, issues
                return raw, issues
            if not isinstance(raw, int) or isinstance(raw, bool):
                issues.append(f"signal {self.signal!r} expected INT/TIME, got {type(raw).__name__}")
                return False, issues
            return True, issues

        if node is GuardNodeType.AND:
            for child in self.children:
                ok, _ = child._eval(snapshot, issues)
                if not ok:
                    return False, issues
            return True, issues

        if node is GuardNodeType.OR:
            for child in self.children:
                ok, _ = child._eval(snapshot, issues)
                if ok:
                    return True, issues
            return False, issues

        if node is GuardNodeType.NOT:
            ok, _ = self.children[0]._eval(snapshot, issues)
            return (not ok), issues

        if node in BINARY_COMPARISONS or node is GuardNodeType.ELAPSED_GE:
            left, right = self.children[0], self.children[1]
            left_value = _numeric_operand(left, snapshot, issues)
            right_value = _numeric_operand(right, snapshot, issues)
            if left_value is None or right_value is None:
                return False, issues
            return _compare(node, left_value, right_value), issues

        issues.append(f"unknown guard node type at evaluation: {node!r}")
        return False, issues

    def referenced_signals(self) -> list[str]:
        """All signal names referenced by this guard, deterministically sorted."""
        found: set[str] = set()
        if self.node_type is GuardNodeType.SIGNAL and self.signal:
            found.add(self.signal)
        for child in self.children:
            found.update(child.referenced_signals())
        return sorted(found)


def _numeric_operand(node: GuardAST, snapshot: dict[str, Any], issues: list[str]) -> int | None:
    """Resolve a numeric operand without ever using eval()."""
    if node.node_type is GuardNodeType.CONST:
        return int(node.value) if isinstance(node.value, int) and not isinstance(node.value, bool) else None
    if node.node_type is GuardNodeType.SIGNAL:
        raw = snapshot.get(node.signal)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        issues.append(f"numeric signal {node.signal!r} missing or mistyped (fail-closed)")
        return None
    issues.append(f"numeric operand must be CONST or SIGNAL, got {node.node_type}")
    return None


def _compare(node: GuardNodeType, left: int, right: int) -> bool:
    if node is GuardNodeType.EQ:
        return left == right
    if node is GuardNodeType.NE:
        return left != right
    if node is GuardNodeType.LT:
        return left < right
    if node is GuardNodeType.LE:
        return left <= right
    if node is GuardNodeType.GT:
        return left > right
    if node is GuardNodeType.GE or node is GuardNodeType.ELAPSED_GE:
        return left >= right
    return False


# --------------------------------------------------------------- constructors --


def guard_const(value: bool | int, value_type: GuardValueType = GuardValueType.BOOL) -> GuardAST:
    """Build a typed CONST guard node."""
    return GuardAST(node_type=GuardNodeType.CONST, value_type=value_type, value=value)


def guard_signal(signal: str, value_type: GuardValueType = GuardValueType.BOOL) -> GuardAST:
    """Build a typed SIGNAL guard node."""
    return GuardAST(node_type=GuardNodeType.SIGNAL, value_type=value_type, signal=signal)


def guard_and(*children: GuardAST) -> GuardAST:
    """Build a BOOL AND node."""
    return GuardAST(node_type=GuardNodeType.AND, value_type=GuardValueType.BOOL, children=list(children))


def guard_or(*children: GuardAST) -> GuardAST:
    """Build a BOOL OR node."""
    return GuardAST(node_type=GuardNodeType.OR, value_type=GuardValueType.BOOL, children=list(children))


def guard_not(child: GuardAST) -> GuardAST:
    """Build a BOOL NOT node."""
    return GuardAST(node_type=GuardNodeType.NOT, value_type=GuardValueType.BOOL, children=[child])


def guard_compare(node_type: GuardNodeType, left: GuardAST, right: GuardAST) -> GuardAST:
    """Build a BOOL comparison node over two TIME/INT operands."""
    return GuardAST(node_type=node_type, value_type=GuardValueType.BOOL, children=[left, right])


def guard_true() -> GuardAST:
    """Convenience: an unconditionally true typed guard."""
    return guard_const(True, GuardValueType.BOOL)


def parse_guard(data: dict[str, Any] | GuardAST | None) -> GuardAST | None:
    """Parse a guard from a dict; ``None`` returns ``None`` (used by validators)."""
    if data is None:
        return None
    if isinstance(data, GuardAST):
        return data
    return GuardAST.from_dict(data)
