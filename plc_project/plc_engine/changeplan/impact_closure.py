"""Reverse-reference closure query (interface only, no TIA write)."""
from __future__ import annotations

from collections import deque
from typing import Iterable

from plc_engine.changeplan.source_binding import SourceBinding


def reverse_reference_closure(
    bindings: Iterable[SourceBinding],
    target_source_ids: Iterable[str],
) -> list[str]:
    """Return every source id that (transitively) references a target block.

    Pure function over the imported block index; it never opens a TIA project.
    The result is deterministically sorted for reproducible review UI.
    """
    records = list(bindings)
    by_id = {record.source_id: record for record in records}
    reverse: dict[str, set[str]] = {record.source_id: set() for record in records}
    for record in records:
        for referenced in record.referenced_by:
            # ``referenced_by`` lists callers of this block; build caller -> callee.
            if referenced in reverse:
                reverse[referenced].add(record.source_id)
    targets = [t for t in target_source_ids if t]
    seen: set[str] = set(targets)
    queue: deque[str] = deque(targets)
    while queue:
        current = queue.popleft()
        for caller in sorted(reverse.get(current, set())):
            if caller not in seen:
                seen.add(caller)
                queue.append(caller)
    return sorted(seen)


def referenced_by_kept_blocks(binding: SourceBinding, kept_ids: set[str]) -> list[str]:
    """Return kept blocks that still reference this binding (delete guard)."""
    return sorted({caller for caller in binding.referenced_by if caller in kept_ids})
