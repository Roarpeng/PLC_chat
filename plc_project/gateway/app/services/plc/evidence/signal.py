"""Signal-trace evidence rendering."""

from __future__ import annotations

from typing import Any

from .blocks import _tag_io_for_block
from .shared import _join_capped

__all__ = [
    "_format_signal_trace",
]


def _format_signal_trace(job: dict[str, Any], block_name: str) -> list[str]:
    """Compact who-reads / who-writes for tags touched by this block."""
    reads, writes = _tag_io_for_block(job, block_name)
    tags = list(dict.fromkeys([*reads, *writes]))[:12]
    if not tags:
        return ["信号：该块暂无已验证 Tag READS/WRITES 边。"]
    lines = [f"**信号追踪（`{block_name}`）**"]
    kg = job.get("knowledge_graph") or {}
    for tag in tags:
        tid = f"Tag::{tag}"
        r_blocks: list[str] = []
        w_blocks: list[str] = []
        for e in kg.get("edges") or []:
            if str(e.get("target") or "") != tid:
                continue
            src = str(e.get("source") or "")
            if not src.startswith("Block::"):
                continue
            bname = src.split("::", 1)[-1]
            if e.get("type") == "READS":
                r_blocks.append(bname)
            elif e.get("type") == "WRITES":
                w_blocks.append(bname)
        lines.append(
            f"- `{tag}`：写={_join_capped(sorted(set(w_blocks)), limit=4)}；"
            f"读={_join_capped(sorted(set(r_blocks)), limit=4)}"
        )
    return lines
