"""Shared thread-pool sizing for PLC ingest (XML parse / fold / SCL)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

_MAX_WORKERS = 8


def ingest_workers(n_items: int, *, min_items: int = 4) -> int:
    """How many threads to use for a batch of ``n_items`` independent jobs."""
    if n_items < min_items:
        return 1
    raw = os.getenv("RESEARCHOS_PLC_PARSE_WORKERS", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), n_items))
        except ValueError:
            pass
    cpus = os.cpu_count() or 4
    return max(1, min(_MAX_WORKERS, cpus, n_items))


def map_parallel(
    fn: Callable[[T], R],
    items: list[T],
    *,
    min_items: int = 4,
) -> list[R]:
    """Apply ``fn`` preserving order; serial when a thread pool would not help."""
    if not items:
        return []
    workers = ingest_workers(len(items), min_items=min_items)
    if workers <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))
