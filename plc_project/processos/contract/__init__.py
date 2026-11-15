"""Process Contract IR — frozen spine for all ProcessOS workstreams."""
from __future__ import annotations

from .fixtures import clamp_contract, clamp_operation, clamp_resource, clamp_scenarios, clamp_steps
from .hashing import contract_semantic_hash, contract_spec_hash
from .interfaces import (
    EVIDENCE_LEVELS,
    AfBlock,
    AfProject,
    ComplianceReport,
    Counterexample,
    FrameworkBackend,
    FrameworkProfile,
    GeneratedSource,
    Issue,
    ScenarioResult,
    ScenarioRunner,
    SemanticValidator,
    SourceGenerator,
    TraceEvent,
)
from .model import (
    SCAN_ORDER,
    SCHEMA,
    Action,
    FailurePolicy,
    Invariant,
    OpenQuestion,
    Operation,
    ProcessContract,
    Provenance,
    Resource,
    Scenario,
    Step,
)
from .patch import PATCH_OPS, Patch, PatchError, PatchOp, RevisionConflict, apply_patch
from .questions import QuestionGate, evaluate_questions, resolve_question

__all__ = [
    "SCHEMA", "SCAN_ORDER", "PATCH_OPS", "EVIDENCE_LEVELS",
    "Action", "Step", "Resource", "Invariant", "FailurePolicy", "OpenQuestion",
    "Scenario", "Operation", "Provenance", "ProcessContract",
    "Patch", "PatchOp", "PatchError", "RevisionConflict", "apply_patch",
    "QuestionGate", "evaluate_questions", "resolve_question",
    "contract_semantic_hash", "contract_spec_hash",
    "clamp_contract", "clamp_operation", "clamp_resource", "clamp_scenarios", "clamp_steps",
    "Issue", "ComplianceReport", "TraceEvent", "Counterexample", "ScenarioResult",
    "FrameworkProfile", "AfBlock", "AfProject", "GeneratedSource",
    "SemanticValidator", "ScenarioRunner", "FrameworkBackend", "SourceGenerator",
]