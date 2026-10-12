"""Siemens multi-instance nesting: Variable.data_type → existing FB/FC/UDT/DB.

Not CALLS and not instance-DB ``INSTANCE_OF``. A Static/Input/InOut member whose
type names another block in the IR is a multi-instance embed. Chains of those
embeds (FB_A → FB_B → FB_C) are queryable without an LLM.

Never invent types that are not already Block nodes in the KG / IR.
"""

from __future__ import annotations

import re
from typing import Any

NEST_SECTIONS = {"Input", "Output", "InOut", "Static"}
TYPED_AS = "TYPED_AS"

_ARRAY_OF_RE = re.compile(
    r"^(?:array\s*(?:\[[^\]]*\])?\s+of\s+)(.+)$",
    re.IGNORECASE,
)
_PRIMITIVE_TYPES = {
    "bool",
    "byte",
    "word",
    "dword",
    "lword",
    "int",
    "dint",
    "lint",
    "uint",
    "udint",
    "ulint",
    "sint",
    "usint",
    "real",
    "lreal",
    "time",
    "ltime",
    "date",
    "tod",
    "dt",
    "dtl",
    "char",
    "wchar",
    "string",
    "wstring",
    "void",
    "any",
    "variant",
    "pointer",
    "ref_to",
    "hw_any",
    "hw_io",
    "hw_device",
    "hw_interface",
    "hw_iosystem",
    "hw_submodule",
    "hw_module",
    "hw_dpslave",
    "hw_dpmaster",
    "hw_ios",
    "hw_ieport",
    "hw_hsc",
    "hw_pwm",
    "hw_pto",
    "conn_any",
    "conn_ogn",
    "conn_prg",
    "conn_r_id",
    "conn_oui",
    "port",
    "rtm",
    "aom_ident",
    "event_any",
    "event_att",
    "event_hwint",
    "db_any",
    "db_dyn",
    "db_www",
    "fb_any",
    "ob_any",
    "ob_att",
    "ob_cyc",
    "ob_delay",
    "ob_diag",
    "ob_hwint",
    "ob_pcycle",
    "ob_start",
    "ob_timeerror",
    "ob_tod",
    "ob_watchdog",
}


def strip_type_name(data_type: str) -> str:
    """Strip Siemens quotes and ``Array[…] of`` wrappers. Empty if none."""
    raw = (data_type or "").strip()
    if not raw:
        return ""
    raw = raw.strip('"').strip("'").strip()
    match = _ARRAY_OF_RE.match(raw)
    if match:
        raw = match.group(1).strip().strip('"').strip("'").strip()
    # STRING[80] / WSTRING[254] stay as-is (not a block name)
    return raw


def is_primitive_type(type_name: str) -> bool:
    token = (type_name or "").strip().strip('"').strip("'")
    if not token:
        return True
    base = token.split("[", 1)[0].strip()
    return base.lower() in _PRIMITIVE_TYPES


def is_nest_section(section: str) -> bool:
    return (section or "").strip() in NEST_SECTIONS


def _block_name(node_id: object) -> str:
    return str(node_id).split("::", 1)[-1]


def known_block_names(kg: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for node in kg.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "Block":
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        name = str(props.get("name") or _block_name(node.get("id") or "")).strip()
        if name:
            names.add(name)
    return names


def resolve_named_type(data_type: str, known: set[str]) -> str | None:
    """Return a project block name if ``data_type`` names one; else None."""
    type_name = strip_type_name(data_type)
    if not type_name or is_primitive_type(type_name):
        return None
    if type_name in known:
        return type_name
    # Case-insensitive fallback (Siemens export quoting varies)
    lower = {n.lower(): n for n in known}
    return lower.get(type_name.lower())


def _parse_variable_id(node_id: str) -> tuple[str, str, str] | None:
    """Variable::{block}::{section}::{member} → (block, section, member)."""
    parts = str(node_id or "").split("::")
    if len(parts) < 4 or parts[0] != "Variable":
        return None
    return parts[1], parts[2], "::".join(parts[3:])


def _member_from_typed_edge(edge: dict[str, Any], source: str) -> tuple[str, str]:
    props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    member = str(props.get("member") or "")
    section = str(props.get("section") or "")
    parsed = _parse_variable_id(source)
    if parsed:
        _block, sec, name = parsed
        if not section:
            section = sec
        if not member:
            member = name
    return member, section


def typed_as_members(kg: dict[str, Any], block_name: str) -> list[dict[str, Any]]:
    """In-block members typed as another IR block (multi-instance embeds).

    Prefers ``TYPED_AS`` edges. Falls back to Variable.data_type so jobs parsed
    before this edge existed still surface the chain (no invented types).
    """
    if not block_name:
        return []
    known = known_block_names(kg)
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []

    def add(
        *,
        member: str,
        section: str,
        type_block: str,
        source: str,
        evidence: str,
    ) -> None:
        if not type_block or type_block == block_name:
            return
        if type_block not in known:
            return
        if section and not is_nest_section(section) and section != "_":
            return
        key = (member or source, section, type_block)
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "member": member,
                "section": section,
                "type_block": type_block,
                "source": source,
                "evidence": evidence,
            }
        )

    for edge in kg.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("type") != TYPED_AS:
            continue
        src = str(edge.get("source") or "")
        tgt = str(edge.get("target") or "")
        if not tgt.startswith("Block::"):
            continue
        type_block = _block_name(tgt)
        parsed = _parse_variable_id(src)
        if parsed and parsed[0] == block_name:
            member, section = _member_from_typed_edge(edge, src)
            add(
                member=member or parsed[2],
                section=section or parsed[1],
                type_block=type_block,
                source=src,
                evidence="typed_as",
            )

    if out:
        out.sort(key=lambda m: (m.get("section") or "", m.get("member") or "", m.get("type_block") or ""))
        return out

    # Block → Block TYPED_AS (canvas / chain); split merged member names
    for edge in kg.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("type") != TYPED_AS:
            continue
        src = str(edge.get("source") or "")
        tgt = str(edge.get("target") or "")
        if src != f"Block::{block_name}" or not tgt.startswith("Block::"):
            continue
        type_block = _block_name(tgt)
        member, section = _member_from_typed_edge(edge, src)
        for part in (p.strip() for p in (member or "").split(",")):
            add(
                member=part,
                section=section,
                type_block=type_block,
                source=src,
                evidence="typed_as",
            )

    if out:
        out.sort(key=lambda m: (m.get("section") or "", m.get("member") or "", m.get("type_block") or ""))
        return out

    # Fallback: Variable nodes whose data_type names an existing Block
    prefix = f"Variable::{block_name}::"
    for node in kg.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "Variable":
            continue
        nid = str(node.get("id") or "")
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        parsed = _parse_variable_id(nid)
        if parsed and parsed[0] == block_name:
            member, section = parsed[2], parsed[1]
        elif nid.startswith(prefix):
            rest = nid[len(prefix) :]
            section, _, member = rest.partition("::")
        else:
            parent = str(props.get("parent") or props.get("block") or "")
            if parent != block_name:
                continue
            member = str(props.get("name") or "")
            section = str(props.get("section") or "")
        type_block = resolve_named_type(str(props.get("data_type") or ""), known)
        if not type_block:
            continue
        add(
            member=member or str(props.get("name") or ""),
            section=section or str(props.get("section") or ""),
            type_block=type_block,
            source=nid or f"Variable::{block_name}",
            evidence="interface_data_type",
        )
    out.sort(key=lambda m: (m.get("section") or "", m.get("member") or "", m.get("type_block") or ""))
    return out


def typed_as_children(kg: dict[str, Any], block_name: str) -> list[str]:
    names: list[str] = []
    for item in typed_as_members(kg, block_name):
        child = str(item.get("type_block") or "")
        if child and child not in names:
            names.append(child)
    return names


def nest_depth_of(
    kg: dict[str, Any],
    block_name: str,
    *,
    _memo: dict[str, int] | None = None,
    _stack: set[str] | None = None,
) -> int:
    """Longest TYPED_AS hop count from this block (0 = no in-block FB types)."""
    memo = _memo if _memo is not None else {}
    if block_name in memo:
        return memo[block_name]
    stack = _stack if _stack is not None else set()
    if block_name in stack:
        return 0
    children = typed_as_children(kg, block_name)
    if not children:
        memo[block_name] = 0
        return 0
    stack.add(block_name)
    depth = 1 + max(nest_depth_of(kg, child, _memo=memo, _stack=stack) for child in children)
    stack.remove(block_name)
    memo[block_name] = depth
    return depth


def typed_as_chains(
    kg: dict[str, Any],
    block_name: str,
    *,
    max_hops: int = 8,
    max_chains: int = 12,
) -> list[list[str]]:
    """TYPED_AS paths starting at ``block_name`` with length ≥ 2 (includes start)."""
    chains: list[list[str]] = []

    def walk(path: list[str]) -> None:
        if len(chains) >= max_chains:
            return
        if len(path) - 1 >= max_hops:
            if len(path) >= 2:
                chains.append(list(path))
            return
        children = typed_as_children(kg, path[-1])
        progressed = False
        for child in children:
            if child in path:
                continue
            progressed = True
            walk(path + [child])
            if len(chains) >= max_chains:
                return
        if not progressed and len(path) >= 2:
            chains.append(list(path))

    walk([block_name])
    chains.sort(key=lambda c: (-len(c), c))
    return chains[:max_chains]


def format_chain(chain: list[str]) -> str:
    return " → ".join(f"`{name}`" for name in chain if name)


def format_chain_plain(chain: list[str]) -> str:
    return " → ".join(chain)


def one_level_embed_bits(kg: dict[str, Any], block_name: str, *, limit: int = 6) -> list[str]:
    """`member : Type` plus one more level of who those types themselves embed."""
    bits: list[str] = []
    for item in typed_as_members(kg, block_name)[:limit]:
        member = str(item.get("member") or "?")
        child = str(item.get("type_block") or "")
        if not child:
            continue
        piece = f"`{member} : {child}`"
        grandchildren = typed_as_members(kg, child)[:4]
        if grandchildren:
            inner = "、".join(
                f"`{g.get('member') or '?'} : {g.get('type_block')}`"
                for g in grandchildren
                if g.get("type_block")
            )
            if inner:
                piece += " → " + inner
        bits.append(piece)
    return bits
