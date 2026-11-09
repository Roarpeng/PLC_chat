"""Dependency-free canonical helpers for the whole V2 kernel.

This module lives at the ``plc_engine`` top level (NOT inside engineering_ir,
components or process) so that any package can import it without triggering a
package ``__init__`` cycle. It is the single implementation of stable-ID rules,
canonical JSON, SHA256 helpers and semantic-hash noise exclusion.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

#: Stable ID grammar: immutable identifier, separated from display name.
STABLE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")

#: Fields that must never enter the semantic hash (G1 / US-3).
SEMANTIC_HASH_EXCLUDED_TOP_LEVEL: tuple[str, ...] = (
    "ir_sha256", "revision", "receipt", "created_at", "updated_at", "frozen_at", "probed_at",
)
SEMANTIC_HASH_EXCLUDED_NESTED: tuple[tuple[str, ...], ...] = (
    ("views", "layout"),
    ("spec_meta", "spec_hash"),
    ("spec_meta", "frozen_at"),
    ("spec_meta", "frozen_by"),
    ("spec_meta", "created_at"),
)
SEMANTIC_HASH_EXCLUDED_LIST_ITEM_KEYS: tuple[str, ...] = ("created_at",)


def is_valid_stable_id(value: str) -> bool:
    """Return True when ``value`` satisfies the immutable ID grammar."""
    return bool(isinstance(value, str) and STABLE_ID_RE.match(value))


def assert_stable_id(value: str, entity: str = "entity") -> None:
    """Raise ValueError when an ID is not a stable identifier."""
    if not is_valid_stable_id(value):
        raise ValueError(f"{entity} id is not a stable ID: {value!r}")


def to_plain(value: Any) -> Any:
    """Recursively convert dataclasses / enums / containers to plain JSON data."""
    if is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "to_dict"):
            return to_plain(value.to_dict())
        return {f.name: to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_dumps(obj: Any) -> str:
    """Global canonical JSON: sorted keys, compact separators, UTF-8 friendly."""
    return json.dumps(to_plain(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(payload: str | bytes) -> str:
    """Return bare lowercase 64-hex SHA256."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(raw).hexdigest()


def sha256_prefixed(payload: str | bytes) -> str:
    """Return the unified ``sha256:<64hex>`` format."""
    return f"sha256:{sha256_hex(payload)}"


def compute_file_sha256(path: str | Path) -> str:
    """Stream a file and return its ``sha256:<hex>`` content hash."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _strip_semantic_noise(value: Any, path: tuple[str, ...]) -> Any:
    """Recursively remove layout / timestamp / freeze metadata from a payload."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            child_path = path + (key_str,)
            if not path and key_str in SEMANTIC_HASH_EXCLUDED_TOP_LEVEL:
                continue
            if child_path in SEMANTIC_HASH_EXCLUDED_NESTED:
                continue
            if path and key_str in SEMANTIC_HASH_EXCLUDED_LIST_ITEM_KEYS:
                if path[-1] in ("edges", "steps", "transitions", "events", "job_events"):
                    continue
            if key_str == "layout" and path and path[-1] == "views":
                continue
            result[key_str] = _strip_semantic_noise(item, child_path)
        return result
    if isinstance(value, (list, tuple)):
        return [_strip_semantic_noise(item, path) for item in value]
    return value


def semantic_payload(ir_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied, noise-free payload used for the semantic hash."""
    if not isinstance(ir_dict, dict):
        raise TypeError("ir_dict must be a dict")
    return _strip_semantic_noise(copy.deepcopy(to_plain(ir_dict)), ())


def semantic_hash(ir_dict: dict[str, Any]) -> str:
    """Compute ``sha256:<hex>`` over the canonical semantic payload."""
    return sha256_prefixed(canonical_dumps(semantic_payload(ir_dict)))


def ir_sha256(ir_dict: dict[str, Any]) -> str:
    """Alias of :func:`semantic_hash` kept for design-document parity."""
    return semantic_hash(ir_dict)


def spec_hash(ir_dict: dict[str, Any], profile_id: str, template_sha256: str) -> str:
    """Freeze hash = semantic hash bound to pinned AF profile and template."""
    payload = {
        "ir": semantic_payload(ir_dict),
        "af_profile": profile_id,
        "template_sha256": template_sha256,
    }
    return sha256_prefixed(canonical_dumps(payload))


def manifest_semantic_hash(
    *,
    files: Iterable[dict[str, Any]],
    import_order: Iterable[str],
    dependencies: dict[str, Any],
) -> str:
    """Deterministic hash of generated semantic files (timestamps excluded)."""
    payload = {
        "files": [
            {
                "path": str(item.get("path") or ""),
                "sha256": str(item.get("sha256") or ""),
                "role": str(item.get("role") or ""),
                "source_ids": sorted(str(x) for x in (item.get("source_ids") or [])),
            }
            for item in files
        ],
        "import_order": list(import_order),
        "dependencies": to_plain(dependencies),
    }
    return sha256_prefixed(canonical_dumps(payload))


def stable_id_report(ids: Iterable[str]) -> dict[str, Any]:
    """Validate stable IDs; return duplicates plus malformed identifiers."""
    seen: set[str] = set()
    duplicates: list[str] = []
    malformed: list[str] = []
    for raw in ids:
        ident = str(raw)
        if ident in seen:
            duplicates.append(ident)
        seen.add(ident)
        if not STABLE_ID_RE.match(ident):
            malformed.append(ident)
    return {
        "ok": not duplicates and not malformed,
        "duplicate_ids": sorted(set(duplicates)),
        "malformed_ids": sorted(set(malformed)),
        "count": len(seen),
    }
