"""Brownfield interface + Schema ONLY (WP-05 / Q-04).

This package deliberately contains NO real TIA write path. It defines the
SourceBinding record, a minimal non-executable DiffPlan, reverse-reference
closure queries, negative-case guards and a mocked (explicitly labelled)
orchestration demo. AC-02 real-machine ADD/MODIFY/DELETE is OUT OF SCOPE.
"""
from __future__ import annotations

from plc_engine.changeplan.brownfield_guard import GuardIssue, evaluate_diff_plan
from plc_engine.changeplan.diff_plan import DiffOp, DiffPlan
from plc_engine.changeplan.impact_closure import reverse_reference_closure
from plc_engine.changeplan.mocked_orchestrator import mocked_orchestrate
from plc_engine.changeplan.source_binding import SourceBinding

__all__ = [
    "DiffOp",
    "DiffPlan",
    "GuardIssue",
    "SourceBinding",
    "evaluate_diff_plan",
    "mocked_orchestrate",
    "reverse_reference_closure",
]
