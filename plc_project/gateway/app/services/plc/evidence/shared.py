"""Shared helpers used by PLC chat evidence renderers."""

from __future__ import annotations

import logging

logger = logging.getLogger("researchos.gateway.plc")

__all__ = [
    "_network_titles_from_scl",
    "_join_capped",
]


def _network_titles_from_scl(scl: str) -> list[str]:
    titles: list[str] = []
    for line in (scl or "").splitlines():
        s = line.strip()
        if s.upper().startswith("// NETWORK"):
            # "// NETWORK 1: title"
            part = s.split(":", 1)
            title = part[1].strip() if len(part) > 1 else s
            if title:
                titles.append(title)
    return titles[:12]


def _join_capped(items: list[str], *, limit: int = 6) -> str:
    if not items:
        return "—"
    shown = items[:limit]
    more = f" 等{len(items)}个" if len(items) > limit else ""
    return ", ".join(shown) + more
