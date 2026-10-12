"""Block lookup, KG relations, and focus resolution."""

from __future__ import annotations

from typing import Any

from gateway.app.services.plc.chat_intents import _strip_at_hint

from .shared import _network_titles_from_scl

__all__ = [
    "_block_assoc_lines",
    "_block_meta",
    "_block_io_lists",
    "_match_block_query",
    "_resolve_block_focus",
    "_tag_io_for_block",
    "_block_network_titles",
    "_call_relation_names",
]


def _block_assoc_lines(job: dict[str, Any], block_name: str) -> list[str]:
    """CALLS / USES associations for engineer-facing graph summary."""
    kg = job.get("knowledge_graph") or {}
    blocks = {
        b["name"]: b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }
    node_type = {
        (n.get("props") or {}).get("name") or n["id"].split("::")[-1]: (n.get("props") or {}).get(
            "block_type"
        )
        for n in (kg.get("nodes") or [])
        if n.get("type") == "Block" and isinstance(n, dict) and n.get("id")
    }

    def _label(name: str) -> str:
        bt = node_type.get(name) or (blocks.get(name) or {}).get("type") or ""
        return f"{name}（{bt}）" if bt else name

    callers: list[str] = []
    callees: list[str] = []
    uses: list[str] = []
    used_by: list[str] = []
    bid = f"Block::{block_name}"
    for e in kg.get("edges") or []:
        et = e.get("type")
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if et == "CALLS" and tgt == bid and src.startswith("Block::"):
            callers.append(_label(src.split("::", 1)[-1]))
        elif et == "CALLS" and src == bid and tgt.startswith("Block::"):
            callees.append(_label(tgt.split("::", 1)[-1]))
        elif et == "USES" and src == bid and tgt.startswith("Block::"):
            uses.append(_label(tgt.split("::", 1)[-1]))
        elif et == "USES" and tgt == bid and src.startswith("Block::"):
            used_by.append(_label(src.split("::", 1)[-1]))

    lines: list[str] = []
    if callers:
        lines.append(f"被调用：{', '.join(sorted(set(callers)))}")
    if callees:
        lines.append(f"调用：{', '.join(sorted(set(callees)))}")
    if uses:
        lines.append(f"使用：{', '.join(sorted(set(uses)))}")
    if used_by:
        lines.append(f"被使用：{', '.join(sorted(set(used_by)))}")
    return lines


def _block_io_lists(
    job: dict[str, Any], block_name: str, block: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    """Merge interface pins + Tag READS/WRITES (iface first)."""
    iface_in = [str(x) for x in (block.get("inputs") or []) if x]
    iface_out = [str(x) for x in (block.get("outputs") or []) if x]
    iface_inout = [str(x) for x in (block.get("inouts") or []) if x]
    reads, writes = _tag_io_for_block(job, block_name)
    if iface_in or iface_out or iface_inout:
        reads = (
            iface_in
            + iface_inout
            + [
                r
                for r in reads
                if r not in iface_in and r not in iface_inout and not r.startswith("#")
            ]
        )
        writes = (
            iface_out
            + iface_inout
            + [
                w
                for w in writes
                if w not in iface_out and w not in iface_inout and not w.startswith("#")
            ]
        )
    return reads, writes, iface_inout


def _block_meta(job: dict[str, Any], block_name: str) -> dict[str, Any]:
    for b in job.get("blocks") or []:
        if isinstance(b, dict) and str(b.get("name") or "") == block_name:
            return b
    return {}


def _match_block_query(job: dict[str, Any], blocks: dict[str, Any], query: str) -> str:
    """Resolve a free-text query to a block name (exact / prefix / comment / network title)."""
    q = (query or "").strip().strip("@").strip()
    if not q or not blocks:
        return ""
    if q in blocks:
        return q
    ql = q.lower()
    for name in blocks:
        if name.lower() == ql:
            return name
    # Longest name contained in query, or query contained in name
    contained = [n for n in blocks if n.lower() in ql or ql in n.lower()]
    if len(contained) == 1:
        return contained[0]
    if contained:
        return max(contained, key=len)
    # Block comment / title
    for name, b in blocks.items():
        comment = str(b.get("comment") or "")
        if comment and (ql in comment.lower() or comment.lower() in ql):
            return name
    # SCL / folded network titles (often human-readable like "A Station CoolingFan")
    scl_sources = job.get("scl_sources") or {}
    for name, scl in scl_sources.items():
        if name not in blocks:
            continue
        for title in _network_titles_from_scl(str(scl or "")):
            tl = title.lower()
            if ql in tl or tl in ql:
                return name
    folded = job.get("folded_logic") or {}
    if isinstance(folded, dict):
        for name, nets in folded.items():
            if name not in blocks or not isinstance(nets, list):
                continue
            for net in nets:
                if not isinstance(net, dict):
                    continue
                title = str(net.get("title") or "").strip()
                if not title:
                    continue
                tl = title.lower()
                if ql in tl or tl in ql:
                    return name
    return ""


def _resolve_block_focus(
    job: dict[str, Any],
    message: str,
    block_name: str | None,
) -> str:
    """Resolve which PLC block the user is asking about."""
    import re

    blocks = {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }
    if not blocks:
        return ""

    if block_name:
        hit = _match_block_query(job, blocks, block_name)
        if hit:
            return hit

    msg = message or ""
    remainder = _strip_at_hint(msg)
    if remainder:
        # Prefer longest known block name as prefix of the mention
        for name in sorted(blocks.keys(), key=len, reverse=True):
            if remainder.lower().startswith(name.lower()):
                tail = remainder[len(name) :]
                if not tail or not tail[0].isalnum():
                    return name
        hit = _match_block_query(job, blocks, remainder)
        if hit:
            return hit

    # Bare name / comment / title inside the message (longer names first)
    for name in sorted(blocks.keys(), key=len, reverse=True):
        if len(name) <= 2:
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", msg, flags=re.IGNORECASE):
                return name
        elif name.lower() in msg.lower():
            return name

    # Last resort: match comment/title against whole message
    hit = _match_block_query(job, blocks, msg)
    if hit:
        return hit
    return ""


def _tag_io_for_block(job: dict[str, Any], block_name: str) -> tuple[list[str], list[str]]:
    reads: list[str] = []
    writes: list[str] = []
    bid = f"Block::{block_name}"
    for e in (job.get("knowledge_graph") or {}).get("edges") or []:
        if e.get("source") != bid:
            continue
        tag = str(e.get("target") or "")
        if not tag.startswith("Tag::"):
            continue
        name = tag.split("::", 1)[-1]
        if e.get("type") == "READS":
            reads.append(name)
        elif e.get("type") == "WRITES":
            writes.append(name)
    return sorted(set(reads)), sorted(set(writes))


def _block_network_titles(job: dict[str, Any], block_name: str) -> list[str]:
    """Human-readable network / step titles from folded_logic then SCL comments."""
    titles: list[str] = []
    seen: set[str] = set()
    folded = job.get("folded_logic") or {}
    nets = folded.get(block_name) if isinstance(folded, dict) else None
    if isinstance(nets, list):
        for net in nets:
            if not isinstance(net, dict):
                continue
            t = str(net.get("title") or "").strip().strip('"')
            if t and t not in seen:
                seen.add(t)
                titles.append(t)
    for t in _network_titles_from_scl(str((job.get("scl_sources") or {}).get(block_name) or "")):
        if t and t not in seen:
            seen.add(t)
            titles.append(t)
    return titles[:16]


def _call_relation_names(job: dict[str, Any], block_name: str) -> tuple[list[str], list[str]]:
    """Return (callers, callees) block names from KG CALLS edges."""
    callers: list[str] = []
    callees: list[str] = []
    bid = f"Block::{block_name}"
    for e in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(e, dict) or e.get("type") != "CALLS":
            continue
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if tgt == bid and src.startswith("Block::"):
            callers.append(src.split("::", 1)[-1])
        elif src == bid and tgt.startswith("Block::"):
            callees.append(tgt.split("::", 1)[-1])
    return sorted(set(callers)), sorted(set(callees))
