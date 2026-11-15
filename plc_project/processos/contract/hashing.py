"""Semantic hashing for Process Contracts — reuses the verified kernel.

No new hash implementation: ``plc_engine.canonical`` is the single source of
canonical JSON, SHA256 and noise exclusion (R3 D-10 / blueprint evidence chain).
"""
from __future__ import annotations

from typing import Any

from plc_engine.canonical import (
    canonical_dumps,
    compute_file_sha256,
    semantic_hash,
    sha256_prefixed,
    spec_hash,
)

from .model import ProcessContract

__all__ = [
    "contract_semantic_hash",
    "contract_spec_hash",
    "compute_file_sha256",
    "canonical_dumps",
    "sha256_prefixed",
]


def contract_semantic_hash(contract: ProcessContract | dict[str, Any]) -> str:
    """``sha256:<hex>`` over the canonical, layout-free contract payload."""
    payload = contract.to_dict() if isinstance(contract, ProcessContract) else contract
    return semantic_hash(payload)


def contract_spec_hash(
    contract: ProcessContract | dict[str, Any],
    profile_id: str,
    template_sha256: str,
) -> str:
    """Freeze hash binding the contract to a pinned AF profile + real template."""
    payload = contract.to_dict() if isinstance(contract, ProcessContract) else contract
    return spec_hash(payload, profile_id, template_sha256)