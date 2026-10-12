"""Lightweight wall-clock timing helpers for PLC ingest instrumentation."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator


def now_ms() -> int:
    return int(time.monotonic() * 1000)


@contextmanager
def timed_step(bucket: dict[str, int], key: str) -> Iterator[None]:
    """Accumulate elapsed milliseconds into ``bucket[key]``."""
    start = time.monotonic()
    try:
        yield
    finally:
        bucket[key] = int((time.monotonic() - start) * 1000)


def merge_timings(*parts: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in parts:
        if not part:
            continue
        for key, value in part.items():
            try:
                ms = int(value)
            except (TypeError, ValueError):
                continue
            out[key] = out.get(key, 0) + ms
    return out


def timings_summary(timings: dict[str, int], *, total_key: str = "total_ms") -> str:
    """One-line human summary ordered by descending duration."""
    items = [(k, v) for k, v in timings.items() if k != total_key and isinstance(v, int)]
    items.sort(key=lambda kv: kv[1], reverse=True)
    total = timings.get(total_key)
    head = ", ".join(f"{k}={v}ms" for k, v in items[:12])
    if total is not None:
        return f"total={total}ms; {head}" if head else f"total={total}ms"
    return head or "(no timings)"
