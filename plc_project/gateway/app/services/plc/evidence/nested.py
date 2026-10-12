"""Typed-as / nested FB chain rendering."""

from __future__ import annotations

from typing import Any

__all__ = [
    "_typed_as_nest_payload",
    "_format_typed_as_nest_lines",
    "_format_nested_fb_line",
]


def _typed_as_nest_payload(
    job: dict[str, Any],
    block_name: str,
    *,
    through_member: str | None = None,
) -> dict[str, Any]:
    """Full TYPED_AS chains + STAT member names for a block (or one member)."""
    from agents.plc.tia.typed_as import (
        format_chain,
        nest_depth_of,
        typed_as_chains,
        typed_as_members,
    )

    kg = job.get("knowledge_graph") or {}
    depth = nest_depth_of(kg, block_name)
    members = typed_as_members(kg, block_name)
    if through_member:
        want = through_member.strip().lstrip("#")
        want_l = want.lower()
        members = [
            m
            for m in members
            if str(m.get("member") or "").strip().lstrip("#").lower() == want_l
        ]
    member_bits: list[str] = []
    chain_lines: list[str] = []
    child_types = {str(item.get("type_block") or "") for item in members if item.get("type_block")}
    for item in members:
        member = str(item.get("member") or "?")
        child = str(item.get("type_block") or "")
        if not child:
            continue
        rest = typed_as_chains(kg, child)
        if rest:
            for path in rest:
                tail = " → ".join(f"`{n}`" for n in path[1:] if n)
                bit = f"`{block_name}.{member} : {child}`"
                member_bits.append(f"{bit} → {tail}" if tail else bit)
        else:
            member_bits.append(f"`{block_name}.{member} : {child}`")
    for path in typed_as_chains(kg, block_name):
        if through_member:
            if not child_types or len(path) < 2 or path[1] not in child_types:
                continue
        rendered = format_chain(path)
        if rendered:
            chain_lines.append(rendered)
    # De-dupe while preserving order
    member_bits = list(dict.fromkeys(member_bits))
    chain_lines = list(dict.fromkeys(chain_lines))
    return {
        "depth": depth,
        "members": member_bits,
        "chains": chain_lines,
        "has_nest": bool(member_bits or chain_lines or depth),
    }


def _format_typed_as_nest_lines(
    job: dict[str, Any],
    block_name: str,
    *,
    through_member: str | None = None,
    compact: bool = False,
    always: bool = False,
) -> list[str]:
    """Engineer-facing nest listing. ``always`` prints 无 FB-as-type when depth 0."""
    payload = _typed_as_nest_payload(job, block_name, through_member=through_member)
    depth = int(payload.get("depth") or 0)
    members = list(payload.get("members") or [])
    chains = list(payload.get("chains") or [])
    if not members and not chains:
        if always:
            who = f"`{block_name}`"
            if through_member:
                who = f"`{block_name}.{through_member}`"
            return [f"{who} 无 FB-as-type 嵌套（STAT 成员类型不是另一个 FB）"]
        return []
    if compact:
        bits = members or chains
        # Card keeps the existing ``Child : FB_B`` shape plus remaining types.
        short: list[str] = []
        for bit in bits:
            short.append(bit.replace(f"{block_name}.", "", 1) if bit.startswith(f"`{block_name}.") else bit)
        return [f"嵌套 FB 类型（深度 {depth}）：" + "；".join(short[:6])]
    lines = [f"**FB-as-type 嵌套链**（`{block_name}`，深度 {depth}）"]
    if through_member:
        lines[0] += f" · 经成员 `{through_member}`"
    if members:
        lines.append("成员：")
        for bit in members:
            lines.append(f"- {bit}")
    if chains:
        lines.append("链：")
        for chain in chains:
            lines.append(f"- {chain}")
    return lines


def _format_nested_fb_line(job: dict[str, Any], block_name: str) -> str | None:
    """Node-card line: full TYPED_AS path, not one embed level only."""
    lines = _format_typed_as_nest_lines(job, block_name, compact=True)
    return lines[0] if lines else None
