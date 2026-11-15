"""OpenQuestion ledger — the contract-negotiation gate (blueprint §3 / §1).

A contract with unresolved *blocking* questions must never reach a deliverable
state. The AI proposes questions; only a human resolution closes them. This is
the mechanised form of "未闭合契约不得生成可交付控制工程".
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import OpenQuestion, ProcessContract


@dataclass(frozen=True)
class QuestionGate:
    """Result of evaluating the open-question ledger for delivery readiness."""

    blocking_open: tuple[str, ...]
    advisory_open: tuple[str, ...]
    resolved: tuple[str, ...]

    @property
    def deliverable(self) -> bool:
        return not self.blocking_open

    def reason(self) -> str:
        if self.deliverable:
            return "all blocking questions resolved"
        return "blocking open questions: " + ", ".join(self.blocking_open)


def evaluate_questions(contract: ProcessContract) -> QuestionGate:
    blocking = tuple(q.id for q in contract.open_questions if q.severity == "blocking" and not q.resolved)
    advisory = tuple(q.id for q in contract.open_questions if q.severity == "advisory" and not q.resolved)
    resolved = tuple(q.id for q in contract.open_questions if q.resolved)
    return QuestionGate(blocking_open=blocking, advisory_open=advisory, resolved=resolved)


def resolve_question(
    contract: ProcessContract, question_id: str, resolution: str, resolved_by: str
) -> OpenQuestion:
    """Record a human resolution. Raises if the question is unknown."""
    for q in contract.open_questions:
        if q.id == question_id:
            if not resolution.strip():
                raise ValueError("resolution must be a non-empty human decision")
            if not resolved_by.strip():
                raise ValueError("resolved_by must identify the human decision maker")
            q.resolution = resolution
            q.resolved_by = resolved_by
            return q
    raise KeyError(f"unknown open question: {question_id}")