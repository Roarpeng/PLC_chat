"""Unified metadata-filter matching shared by vector / bm25 / graph channels.

Filter keys (union of legacy and documented metadata filters):

- ``source_id``       exact match against payload ``source_id``/``doc_id``/``chunk_id``
- ``tags``            any-overlap against payload ``tags`` or ``metadata.tags``
- ``created_after``   timestamp >= value (ISO-8601 string, datetime, or epoch)
- ``created_before``  timestamp <= value
- ``doc_type``        match payload ``doc_type``, falling back to ``section_type``
- ``models``          (legacy) any model appears in ``model`` list / text / source_file
- ``workspace_id``    (legacy) exact
- ``knowledge_space_ids`` (legacy) workspace_id in list
- ``source_files``    (legacy) source_file in list
- ``section_types``   (legacy) section_type in list
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_timestamp(value: Any) -> datetime | None:
    """Normalize a timestamp-ish value to an aware UTC datetime (or None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        try:
            if abs(value) > 1e12:  # milliseconds
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def _payload_tags(payload: dict[str, Any]) -> list[str]:
    tags = payload.get("tags")
    if tags is None and isinstance(payload.get("metadata"), dict):
        tags = payload["metadata"].get("tags")
    return _as_list(tags)


def _payload_timestamp(payload: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "created_at", "created"):
        if key in payload and payload[key] is not None:
            return parse_timestamp(payload[key])
    return None


def _models_match(payload: dict[str, Any], models: list[str]) -> bool:
    payload_models = payload.get("model")
    if isinstance(payload_models, str):
        payload_models = [payload_models]
    elif not payload_models:
        payload_models = []
    blob = " ".join(
        [
            str(payload.get("text") or ""),
            str(payload.get("source_file") or ""),
            " ".join(str(m) for m in payload_models),
        ]
    )
    return any(m in payload_models for m in models) or any(str(m) in blob for m in models)


def payload_matches_filters(payload: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True

    # --- documented metadata filters ---
    sid = filters.get("source_id")
    if sid is not None:
        if (
            str(payload.get("source_id") or "") != str(sid)
            and str(payload.get("doc_id") or "") != str(sid)
            and str(payload.get("chunk_id") or "") != str(sid)
        ):
            return False

    tags = filters.get("tags")
    if tags:
        ptags = {t.lower() for t in _payload_tags(payload)}
        wanted = {t.lower() for t in _as_list(tags)}
        if not (ptags & wanted):
            return False

    ts = _payload_timestamp(payload)
    created_after = filters.get("created_after")
    created_before = filters.get("created_before")
    if (created_after is not None or created_before is not None) and ts is None:
        return False
    if created_after is not None:
        after = parse_timestamp(created_after)
        if after is not None and ts is not None and ts < after:
            return False
    if created_before is not None:
        before = parse_timestamp(created_before)
        if before is not None and ts is not None and ts > before:
            return False

    doc_type = filters.get("doc_type")
    if doc_type is not None:
        pdt = str(payload.get("doc_type") or payload.get("section_type") or "")
        if pdt != str(doc_type):
            return False

    # --- legacy / back-compat filters ---
    models = filters.get("models")
    if models and not _models_match(payload, _as_list(models)):
        return False

    workspace_id = filters.get("workspace_id")
    if workspace_id is not None and str(payload.get("workspace_id") or "") != str(workspace_id):
        return False

    knowledge_space_ids = filters.get("knowledge_space_ids")
    if knowledge_space_ids:
        ws = str(payload.get("workspace_id") or "")
        if ws not in {str(x) for x in knowledge_space_ids}:
            return False

    source_files = filters.get("source_files")
    if source_files and payload.get("source_file") not in source_files:
        return False

    section_types = filters.get("section_types")
    if section_types and payload.get("section_type") not in section_types:
        return False

    return True


def within_recency_window(
    payload: dict[str, Any],
    *,
    now: datetime,
    window_days: int,
) -> bool:
    """True when the payload timestamp is inside ``now - window_days``.

    Chunks without a timestamp are considered in-window (kept), matching the
    documented behavior that only timestamped chunks are subject to the window.
    """
    ts = _payload_timestamp(payload)
    if ts is None:
        return True
    from datetime import timedelta

    cutoff = now - timedelta(days=window_days)
    return ts >= cutoff
