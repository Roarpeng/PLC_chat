"""EngineeringIR v2 frozen contract constants (WP-00 / G0).

This module is pure standard library. It is the single authoritative home for
schema version, AF profile identity, delivery states, error codes and hash
exclusion rules. Every other v2 module imports from here; no module redefines
these constants, which prevents contract drift between the kernel, the gateway
and the tests.
"""
from __future__ import annotations

from enum import Enum

# Stable-ID grammar and semantic-hash exclusion rules have ONE implementation
# in plc_engine/canonical.py; they are re-exported here for contract parity.
# ``__all__`` is explicit so linters never strip these public re-exports.
from plc_engine.canonical import (
    SEMANTIC_HASH_EXCLUDED_LIST_ITEM_KEYS,
    SEMANTIC_HASH_EXCLUDED_NESTED,
    SEMANTIC_HASH_EXCLUDED_TOP_LEVEL,
    STABLE_ID_RE,
    assert_stable_id,
    is_valid_stable_id,
)

__all__ = [
    "AF_FOLDER_TREE",
    "AF_LIBRARY_ID",
    "AF_LIBRARY_VERSION",
    "AF_NUMBER_POLICY",
    "AF_PROFILE_ID",
    "AF_TEMPLATE_SHA256",
    "ALLOWED_STATE_TRANSITIONS",
    "DELIVERY_STAGES",
    "PATCHABLE_COMPONENT_FIELDS",
    "PATCHABLE_STEP_FIELDS",
    "PATCH_OPS",
    "SCAN_CYCLE_MS",
    "SCAN_ORDER",
    "SCHEMA_VERSION",
    "SEMANTIC_HASH_EXCLUDED_LIST_ITEM_KEYS",
    "SEMANTIC_HASH_EXCLUDED_NESTED",
    "SEMANTIC_HASH_EXCLUDED_TOP_LEVEL",
    "STABLE_ID_RE",
    "TERMINAL_STATES",
    "TIA_ARCHIVE_EXTENSION",
    "TIA_PROJECT_EXTENSION",
    "TIA_VERSION",
    "DeliveryState",
    "ErrorCode",
    "assert_stable_id",
    "can_transition",
    "is_valid_stable_id",
]

#: Frozen schema identifier. Never replace with "latest".
SCHEMA_VERSION = "engineering-ir/2.0"

#: Frozen AF profile (user decision 11-p0d-decision.md: AF Basic folder edition).
AF_PROFILE_ID = "SIEMENS_AF_BASIC_FOLDER_V19"
AF_LIBRARY_ID = "SIEMENS_AF_BASIC_FOLDER"
AF_LIBRARY_VERSION = "V19-BASIC-FOLDER-2.2"
AF_TEMPLATE_SHA256 = "sha256:af_basic_folder_v19_template_unbound"
AF_NUMBER_POLICY = "AF_BASIC_FOLDER_DERIVED_OB_NUMBERS"
AF_FOLDER_TREE = "AF/Units/EquipmentModules/ControlModules"

TIA_VERSION = "V19"
TIA_ARCHIVE_EXTENSION = ".zap19"
TIA_PROJECT_EXTENSION = ".ap19"

#: Deterministic scan cycle order shared by the simulator and SCL lowering.
SCAN_ORDER: tuple[str, ...] = (
    "FREEZE_INPUT_SNAPSHOT",
    "EVALUATE_TYPED_GUARDS",
    "RESOLVE_PRIORITY_AND_EXCLUSIVITY",
    "ATOMIC_TRANSITION",
    "COMPOSE_ACTIONS",
    "ARBITRATE_SINGLE_WRITER",
    "TICK_DRIVER_FSMS",
    "EMIT_OUTPUTS_AND_ALARMS",
)
SCAN_CYCLE_MS = 10

#: Atomic Patch op whitelist. Unknown op == fail-closed => 422.
PATCH_OPS: frozenset[str] = frozenset(
    {
        "set_step_parameter",
        "set_component_parameter",
        "set_component_name",
        "add_component",
        "remove_component",
        "add_step",
        "add_transition",
        "remove_transition",
        "set_guard",
        "set_view_layout",
        "set_hardware_intent",
        "set_sequence_mode",
        "add_exception",
    }
)

#: Step fields that a patch may mutate (semantic fields only).
PATCHABLE_STEP_FIELDS: frozenset[str] = frozenset(
    {"name", "min_duration_ms", "max_duration_ms", "failure_target", "entry_actions", "cyclic_actions", "exit_actions"}
)
PATCHABLE_COMPONENT_FIELDS: frozenset[str] = frozenset(
    {"name", "component_type", "driver_template", "source", "parameters", "io_bindings"}
)


class DeliveryState(str, Enum):
    """Authoritative delivery state machine (PRD 4.2 / design 4.3)."""

    DRAFT = "DRAFT"
    SPEC_FROZEN = "SPEC_FROZEN"
    SOURCE_READY = "SOURCE_READY"
    TIA_IMPORTED = "TIA_IMPORTED"
    TIA_COMPILED = "TIA_COMPILED"
    NATIVE_ARCHIVED = "NATIVE_ARCHIVED"
    FAILED = "FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    QUEUED = "QUEUED"


#: Allowed transitions. NATIVE_ARCHIVED is terminal; FAILED keeps evidence.
ALLOWED_STATE_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("QUEUED", "DRAFT"),
        ("DRAFT", "SPEC_FROZEN"),
        ("DRAFT", "FAILED"),
        ("SPEC_FROZEN", "SOURCE_READY"),
        ("SPEC_FROZEN", "FAILED"),
        ("SOURCE_READY", "TIA_IMPORTED"),
        ("SOURCE_READY", "FAILED"),
        ("TIA_IMPORTED", "TIA_COMPILED"),
        ("TIA_IMPORTED", "FAILED"),
        ("TIA_IMPORTED", "RECOVERY_REQUIRED"),
        ("TIA_COMPILED", "NATIVE_ARCHIVED"),
        ("TIA_COMPILED", "FAILED"),
        ("TIA_COMPILED", "RECOVERY_REQUIRED"),
        ("RECOVERY_REQUIRED", "TIA_IMPORTED"),
        ("RECOVERY_REQUIRED", "FAILED"),
        ("FAILED", "DRAFT"),
    }
)

TERMINAL_STATES: frozenset[str] = frozenset({"NATIVE_ARCHIVED"})

#: Delivery chain stages. Ledger is append-only and written BEFORE each stage.
DELIVERY_STAGES: tuple[str, ...] = (
    "CREATE",
    "IMPORT",
    "COMPILE",
    "SAVE",
    "ARCHIVE",
    "HASH",
    "RETRIEVE_REOPEN",
)


class ErrorCode(str, Enum):
    """v2 API error codes (design 5.4)."""

    BASE_REVISION_CONFLICT = "BASE_REVISION_CONFLICT"
    BASELINE_HASH_MISMATCH = "BASELINE_HASH_MISMATCH"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    SEMANTIC_VALIDATION_FAILED = "SEMANTIC_VALIDATION_FAILED"
    UNSUPPORTED_PARALLEL_SEMANTICS = "UNSUPPORTED_PARALLEL_SEMANTICS"
    WRITEBACK_FORBIDDEN = "WRITEBACK_FORBIDDEN"
    ARTIFACT_JOB_MISMATCH = "ARTIFACT_JOB_MISMATCH"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    ARCHIVE_MISSING = "ARCHIVE_MISSING"
    TIA_UNAVAILABLE = "TIA_UNAVAILABLE"
    CPU_TEMPLATE_NOT_SELECTED = "CPU_TEMPLATE_NOT_SELECTED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CHANGESET_NOT_APPROVED = "CHANGESET_NOT_APPROVED"
    COMPILE_FAILED = "COMPILE_FAILED"
    REOPEN_FAILED = "REOPEN_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"


def can_transition(source: str, target: str) -> bool:
    """Return whether a delivery state transition is legal."""
    return (source, target) in ALLOWED_STATE_TRANSITIONS
