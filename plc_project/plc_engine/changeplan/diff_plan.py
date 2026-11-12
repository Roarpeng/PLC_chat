"""Minimal DiffPlan data structure (Q-04: interface + Schema only).

``executable`` is ALWAYS false in this batch. There is no real execution body,
no Openness write and no V19 real evidence. ADD/MODIFY/DELETE are declarations
used by the review UI and negative-case guards only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiffOp:
    """One declared (never executed) diff operation."""

    op: str = "KEEP"
    source_id: str = ""
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "source_id": self.source_id, "target": self.target,
                "payload": dict(self.payload), "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiffOp":
        return cls(op=str(data.get("op") or "KEEP"), source_id=str(data.get("source_id") or ""),
                   target=str(data.get("target") or ""), payload=dict(data.get("payload") or {}),
                   reason=str(data.get("reason") or ""))


@dataclass
class DiffPlan:
    """Frozen, non-executable change declaration."""

    plan_id: str = ""
    project_id: str = ""
    ops: list[DiffOp] = field(default_factory=list)
    impact_closure: list[str] = field(default_factory=list)
    baseline_hash: str = ""
    hardware_hash: str = ""
    safety_block_hash: str = ""
    executable: bool = False
    evidence_level: str = "mocked"
    review_approved: bool = False
    notice: str = "interface + schema only; no real TIA ADD/MODIFY/DELETE in this batch"

    def __post_init__(self) -> None:
        # Q-04 / design 3.1: executable MUST stay false this batch.
        self.executable = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id, "project_id": self.project_id,
            "ops": [op.to_dict() for op in self.ops],
            "impact_closure": list(self.impact_closure),
            "baseline_hash": self.baseline_hash,
            "hardware_hash": self.hardware_hash,
            "safety_block_hash": self.safety_block_hash,
            "executable": False,
            "evidence_level": self.evidence_level,
            "review_approved": self.review_approved,
            "notice": self.notice,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiffPlan":
        return cls(
            plan_id=str(data.get("plan_id") or ""),
            project_id=str(data.get("project_id") or ""),
            ops=[DiffOp.from_dict(x) if isinstance(x, dict) else x for x in (data.get("ops") or [])],
            impact_closure=[str(x) for x in (data.get("impact_closure") or [])],
            baseline_hash=str(data.get("baseline_hash") or ""),
            hardware_hash=str(data.get("hardware_hash") or ""),
            safety_block_hash=str(data.get("safety_block_hash") or ""),
            executable=False,
            evidence_level=str(data.get("evidence_level") or "mocked"),
            review_approved=bool(data.get("review_approved", False)),
            notice=str(data.get("notice") or ""),
        )
