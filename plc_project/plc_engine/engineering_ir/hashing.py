"""Deterministic hashing utilities for EngineeringIR v2 (G1 / G4).

Thin compatibility facade over :mod:`plc_engine.canonical`, which holds the
single dependency-free implementation. Keeping this module means existing
imports (``plc_engine.engineering_ir.hashing``) keep working while no code is
duplicated and no package ``__init__`` cycle can be formed.
"""
from __future__ import annotations

from plc_engine.canonical import (
    SEMANTIC_HASH_EXCLUDED_LIST_ITEM_KEYS,
    SEMANTIC_HASH_EXCLUDED_NESTED,
    SEMANTIC_HASH_EXCLUDED_TOP_LEVEL,
    STABLE_ID_RE,
    canonical_dumps,
    compute_file_sha256,
    ir_sha256,
    manifest_semantic_hash,
    semantic_hash,
    semantic_payload,
    sha256_hex,
    sha256_prefixed,
    spec_hash,
    stable_id_report,
    to_plain,
)

__all__ = [
    "SEMANTIC_HASH_EXCLUDED_LIST_ITEM_KEYS",
    "SEMANTIC_HASH_EXCLUDED_NESTED",
    "SEMANTIC_HASH_EXCLUDED_TOP_LEVEL",
    "STABLE_ID_RE",
    "canonical_dumps",
    "compute_file_sha256",
    "ir_sha256",
    "manifest_semantic_hash",
    "semantic_hash",
    "semantic_payload",
    "sha256_hex",
    "sha256_prefixed",
    "spec_hash",
    "stable_id_report",
    "to_plain",
]
