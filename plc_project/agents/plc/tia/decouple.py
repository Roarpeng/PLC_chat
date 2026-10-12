"""Evidence-gated FB/FC decoupling — extract helper FCs as SCL.

Distinct from parse / analyze / SCL rewrite / writeback. Finds mixed-concern
or tightly coupled blocks and proposes SCL extractions:

  - extract a helper FC from an oversized FB (god-block / disjoint networks)
  - move a reusable network/region into its own FC
  - update original CALL sites in the caller SCL
  - never invent I/O that is not in the IR / folded evidence

Does not decrypt Know-how, invent LAD, write Safety bodies, or guess CALLS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agents.plc.tia.scl_rewrite import refuse_body_write_reason
from agents.plc.tia.typed_as import (
    format_chain_plain,
    nest_depth_of,
    typed_as_chains,
    typed_as_members,
)

_IDENT_RE = re.compile(r'(?:#|"?)([A-Za-z_][\w.]*)"?')
_NETWORK_HEADER_RE = re.compile(
    r"^[ \t]*// ---------- 网络\s+(\d+) ----------[ \t]*$",
    re.MULTILINE,
)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")

GOD_WRITE_THRESHOLD = 6
GOD_NETWORK_THRESHOLD = 3
MAX_EXTRACTS = 4


@dataclass
class DecoupleExtract:
    caller: str
    helper_name: str
    network_id: str
    network_title: str
    helper_scl: str
    caller_scl: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller,
            "helper_name": self.helper_name,
            "network_id": self.network_id,
            "network_title": self.network_title,
            "helper_scl": self.helper_scl,
            "caller_scl": self.caller_scl,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


def _name(node_id: object) -> str:
    return str(node_id).split("::", 1)[-1]


def _block_map(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }


def _edges(job: dict[str, Any], edge_type: str | None = None) -> list[dict[str, Any]]:
    edges = (job.get("knowledge_graph") or {}).get("edges") or []
    return [
        e
        for e in edges
        if isinstance(e, dict) and (edge_type is None or e.get("type") == edge_type)
    ]


def _interface_names(meta: dict[str, Any]) -> dict[str, str]:
    """Map stripped var name → section hint (input/output/inout/static)."""
    out: dict[str, str] = {}
    for key, section in (
        ("inputs", "input"),
        ("outputs", "output"),
        ("inouts", "inout"),
        ("statics", "static"),
    ):
        for raw in meta.get(key) or []:
            token = str(raw).split(":", 1)[0].strip().lstrip("#").strip('"')
            if token:
                out[token] = section
    for raw in meta.get("members") or []:
        token = str(raw).split(":", 1)[0].strip().lstrip("#").strip('"')
        if token and token not in out:
            out[token] = "static"
    return out


def _member_type(meta: dict[str, Any], name: str) -> str:
    needle = name.lower()
    for raw in meta.get("members") or []:
        text = str(raw)
        left = text.split(":", 1)[0].strip().lstrip("#").strip('"')
        if left.lower() == needle and ":" in text:
            return text.split(":", 1)[1].strip() or "Bool"
    return "Bool"


def _collect_refs(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    kind = value.get("type")
    if kind == "ref":
        acc = str(value.get("access") or "").strip()
        return [acc] if acc else []
    if kind == "not":
        return _collect_refs(value.get("operand"))
    if kind in {"and", "or"}:
        out: list[str] = []
        for item in value.get("operands") or []:
            out.extend(_collect_refs(item))
        return out
    if kind == "compare":
        return _collect_refs(value.get("lhs")) + _collect_refs(value.get("rhs"))
    return []


def _strip_operand(token: str) -> str:
    t = (token or "").strip()
    t = t.lstrip("#").strip('"')
    if t.startswith("NOT (") and t.endswith(")"):
        t = t[5:-1].strip().lstrip("#").strip('"')
    return t


def _network_tags(net: dict[str, Any]) -> tuple[set[str], set[str]]:
    reads: set[str] = set()
    writes: set[str] = set()
    for stmt in net.get("statements") or []:
        if not isinstance(stmt, dict):
            continue
        target = _strip_operand(str(stmt.get("target") or ""))
        if target and not target.startswith("(*"):
            writes.add(target)
        for ref in _collect_refs(stmt.get("value")):
            name = _strip_operand(ref)
            if name and not name.startswith("(*"):
                reads.add(name)
    return reads, writes


def _render_folded_stmt(stmt: dict[str, Any]) -> str:
    from agents.plc.tia.analyst import _expr_to_scl

    target = str(stmt.get("target") or "(* target unknown *)")
    condition = _expr_to_scl(stmt.get("value"))
    kind = stmt.get("kind")
    if kind == "call" and target and ":=" not in target and not target.endswith(";"):
        return target if target.endswith(";") else f"{target};"
    if kind == "neg_coil":
        return f"{target} := NOT ({condition});"
    if kind == "set":
        return f"IF {condition} THEN {target} := TRUE; END_IF;"
    if kind == "reset":
        return f"IF {condition} THEN {target} := FALSE; END_IF;"
    if kind == "move":
        return f"{target} := {condition};"
    return f"{target} := {condition};"


def _sanitize_fc_name(caller: str, title: str, network_id: str, used: set[str]) -> str:
    base = title.strip() or f"N{network_id}"
    base = _SAFE_NAME_RE.sub("_", base).strip("_") or f"N{network_id}"
    if base[0].isdigit():
        base = "N" + base
    name = f"FC_{caller}_{base}"[:80]
    if name not in used:
        return name
    suffix = _SAFE_NAME_RE.sub("_", str(network_id)) or "x"
    candidate = f"FC_{caller}_{base}_{suffix}"[:80]
    n = 2
    while candidate in used:
        candidate = f"FC_{caller}_{base}_{n}"[:80]
        n += 1
    return candidate


def _bidirectional_pairs(job: dict[str, Any]) -> set[tuple[str, str]]:
    calls: dict[str, set[str]] = {}
    for edge in _edges(job, "CALLS"):
        src, tgt = _name(edge.get("source")), _name(edge.get("target"))
        if src and tgt:
            calls.setdefault(src, set()).add(tgt)
    pairs: set[tuple[str, str]] = set()
    for a, tgts in calls.items():
        for b in tgts:
            if a in calls.get(b, set()):
                pairs.add(tuple(sorted((a, b))))
    return pairs


def _shared_instance_dbs(job: dict[str, Any]) -> dict[str, list[str]]:
    """Instance DB name → caller blocks that USE it (tight coupling when >1)."""
    owners: dict[str, list[str]] = {}
    for edge in _edges(job, "USES"):
        src, tgt = _name(edge.get("source")), _name(edge.get("target"))
        if src and tgt:
            owners.setdefault(tgt, []).append(src)
    return {db: sorted(set(cs)) for db, cs in owners.items() if len(set(cs)) > 1}


def _nested_fb_reason(job: dict[str, Any], name: str) -> str | None:
    """Deep in-block multi-instance nesting (depth ≥ 2). Not instance-DB INSTANCE_OF."""
    kg = job.get("knowledge_graph") or {}
    depth = nest_depth_of(kg, name)
    if depth < 2:
        return None
    chains = typed_as_chains(kg, name)
    chain = format_chain_plain(chains[0] if chains else [name])
    return f"multi-instance nest depth {depth}: {chain}"


def nested_fb_coupling_notes(job: dict[str, Any], *, focus: str | None = None) -> list[dict[str, Any]]:
    """HITL notes for optimize_plan: chains + skip reasons even when no SCL can land."""
    kg = job.get("knowledge_graph") or {}
    blocks = _block_map(job)
    names: list[str]
    if focus and focus in blocks:
        names = [focus]
    else:
        names = sorted(blocks)
    notes: list[dict[str, Any]] = []
    for name in names:
        btype = str((blocks.get(name) or {}).get("type") or "").upper()
        if btype not in {"FB", "FC", "DB", "UDT"}:
            continue
        depth = nest_depth_of(kg, name)
        min_depth = 1 if (focus and name == focus) else 2
        if depth < min_depth:
            continue
        members = typed_as_members(kg, name)
        chains = typed_as_chains(kg, name)
        skip: list[dict[str, str]] = []
        nested_names = {str(m.get("type_block") or "") for m in members}
        for chain in chains:
            nested_names.update(chain[1:])
        for nested in sorted(n for n in nested_names if n):
            reason = refuse_body_write_reason(blocks.get(nested))
            if reason:
                skip.append({"block": nested, "reason": reason})
        parent_skip = refuse_body_write_reason(blocks.get(name))
        notes.append(
            {
                "block": name,
                "depth": depth,
                "members": members,
                "chains": chains,
                "skip": skip,
                "parent_skip": parent_skip,
                "writable_parent": parent_skip is None,
            }
        )
    notes.sort(key=lambda n: (-int(n.get("depth") or 0), str(n.get("block") or "")))
    return notes[:16]


def _god_or_mixed(
    job: dict[str, Any],
    name: str,
    meta: dict[str, Any],
    networks: list[dict[str, Any]],
) -> str | None:
    writes = {
        _name(e.get("target"))
        for e in _edges(job, "WRITES")
        if _name(e.get("source")) == name and _name(e.get("target"))
    }
    n_nets = len(networks) or int(meta.get("networks") or 0)
    if n_nets >= GOD_NETWORK_THRESHOLD and len(writes) >= GOD_WRITE_THRESHOLD:
        return (
            f"god-block: {n_nets} networks, {len(writes)} WRITES "
            f"({', '.join(sorted(writes)[:8])})"
        )
    if n_nets >= 2:
        tag_sets = []
        for net in networks:
            reads, wr = _network_tags(net)
            tag_sets.append(reads | wr)
        for i, a in enumerate(tag_sets):
            for b in tag_sets[i + 1 :]:
                if a and b and a.isdisjoint(b):
                    return (
                        f"mixed concerns: networks with disjoint tags "
                        f"{sorted(a)[:6]} vs {sorted(b)[:6]}"
                    )
    return None


def _pick_extract_network(
    networks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Prefer a non-first network that has statements (reusable region)."""
    scored: list[tuple[int, dict[str, Any]]] = []
    for idx, net in enumerate(networks):
        stmts = [s for s in (net.get("statements") or []) if isinstance(s, dict)]
        if not stmts:
            continue
        # Skip first network unless it is the only candidate later
        scored.append((len(stmts) + (2 if idx > 0 else 0), net))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    # Prefer not the first network when multiple exist
    for _score, net in scored:
        if str(net.get("network_id") or "") not in {"", "1", networks[0].get("network_id")}:
            return net
        if net is not networks[0]:
            return net
    return scored[0][1] if len(networks) >= 2 else None


def _split_io(
    reads: set[str],
    writes: set[str],
    iface: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Only names that exist on the parent interface — never invent I/O."""
    inputs: list[str] = []
    outputs: list[str] = []
    for name in sorted(reads | writes):
        if name not in iface:
            continue
        if name in writes:
            outputs.append(name)
        else:
            inputs.append(name)
    return inputs, outputs


def _helper_scl(
    helper_name: str,
    caller: str,
    net: dict[str, Any],
    meta: dict[str, Any],
    inputs: list[str],
    outputs: list[str],
    statements: list[str],
) -> str:
    lines = [
        f'FUNCTION "{helper_name}" : Void',
        f"// 从 `{caller}` 网络 {net.get('network_id') or '?'} 提取（证据门控，未发明 I/O）",
    ]
    title = str(net.get("title") or "").strip()
    if title:
        lines.append(f"// 标题：{title}")
    if inputs:
        lines.append("VAR_INPUT")
        for name in inputs:
            lines.append(f"    {name} : {_member_type(meta, name)};")
        lines.append("END_VAR")
    if outputs:
        lines.append("VAR_OUTPUT")
        for name in outputs:
            lines.append(f"    {name} : {_member_type(meta, name)};")
        lines.append("END_VAR")
    lines.append("BEGIN")
    lines.append(f"    // ---------- 网络 1 ----------")
    if title:
        lines.append(f"    // 标题：{title}")
    for stmt in statements:
        # Rewrite local operands to #name when they are helper I/O
        rendered = stmt
        for var in inputs + outputs:
            rendered = re.sub(
                rf'(?<![\w#])#?{re.escape(var)}(?![\w.])',
                f"#{var}",
                rendered,
            )
        lines.append(f"    {rendered}")
    lines.append("")
    lines.append("END_FUNCTION")
    return "\n".join(lines)


def _call_line(helper_name: str, inputs: list[str], outputs: list[str]) -> str:
    params: list[str] = [f"{n} := #{n}" for n in inputs]
    params.extend(f"{n} => #{n}" for n in outputs)
    return f'"{helper_name}"({", ".join(params)});'


def _replace_network_in_scl(
    scl: str,
    network_id: str,
    call_line: str,
    helper_name: str,
    title: str,
) -> str:
    """Replace one `// ---------- 网络 N ----------` body with a CALL."""
    text = scl or ""
    matches = list(_NETWORK_HEADER_RE.finditer(text))
    target_idx = None
    for i, m in enumerate(matches):
        if m.group(1) == str(network_id):
            target_idx = i
            break
    if target_idx is None and matches:
        # Fall back to last network (typical extract target)
        target_idx = len(matches) - 1
    if target_idx is None:
        # No markers — insert CALL before END_*
        end = re.search(
            r"\nEND_(?:FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK)\s*$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        insert = (
            f"\n    // 解耦：提取为 {helper_name}\n    {call_line}\n"
        )
        if end:
            return text[: end.start()] + insert + text[end.start() :]
        return text.rstrip() + insert

    start = matches[target_idx].start()
    end = matches[target_idx + 1].start() if target_idx + 1 < len(matches) else None
    if end is None:
        close = re.search(
            r"\nEND_(?:FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK)\s*$",
            text[start:],
            re.IGNORECASE | re.MULTILINE,
        )
        end = start + close.start() if close else len(text)
    header = matches[target_idx].group(0)
    replacement = (
        f"{header}\n"
        f"    // 解耦：原网络提取为 {helper_name}"
        + (f"（{title}）" if title else "")
        + "\n"
        f"    {call_line}\n"
    )
    return text[:start] + replacement + text[end:]


def propose_decouple(
    job: dict[str, Any],
    *,
    max_extracts: int = MAX_EXTRACTS,
) -> list[DecoupleExtract]:
    """Propose SCL extractions from KG + folded_logic evidence."""
    blocks = _block_map(job)
    folded = job.get("folded_logic") or {}
    scl_sources = dict(job.get("scl_sources") or {})
    used_names = set(blocks) | set(scl_sources)
    extracts: list[DecoupleExtract] = []
    bidir = _bidirectional_pairs(job)
    shared_db = _shared_instance_dbs(job)

    candidates: list[tuple[str, str, list[dict[str, Any]]]] = []
    for name, meta in blocks.items():
        btype = str(meta.get("type") or "").upper()
        if btype not in {"FB", "FC"}:
            continue
        if refuse_body_write_reason(meta):
            continue
        nets = folded.get(name) if isinstance(folded, dict) else None
        networks = [n for n in (nets or []) if isinstance(n, dict)]
        reason = _god_or_mixed(job, name, meta, networks)
        if not reason:
            for a, b in bidir:
                if name in {a, b}:
                    reason = f"bidirectional CALLS between `{a}` and `{b}`"
                    break
        if not reason:
            for db, callers in shared_db.items():
                if name in callers:
                    reason = f"shared instance DB `{db}` used by {', '.join(callers)}"
                    break
        if not reason:
            reason = _nested_fb_reason(job, name)
        if reason:
            candidates.append((name, reason, networks))

    for name, reason, networks in candidates:
        if len(extracts) >= max_extracts:
            break
        net = _pick_extract_network(networks)
        if net is None:
            continue
        reads, writes = _network_tags(net)
        iface = _interface_names(blocks[name])
        inputs, outputs = _split_io(reads, writes, iface)
        if not inputs and not outputs:
            # Would require inventing I/O — refuse
            continue
        stmts = [
            _render_folded_stmt(s)
            for s in (net.get("statements") or [])
            if isinstance(s, dict)
        ]
        if not stmts:
            continue
        helper = _sanitize_fc_name(
            name,
            str(net.get("title") or ""),
            str(net.get("network_id") or len(extracts) + 1),
            used_names,
        )
        used_names.add(helper)
        helper_scl = _helper_scl(
            helper, name, net, blocks[name], inputs, outputs, stmts
        )
        call = _call_line(helper, inputs, outputs)
        caller_before = scl_sources.get(name) or ""
        caller_after = _replace_network_in_scl(
            caller_before,
            str(net.get("network_id") or ""),
            call,
            helper,
            str(net.get("title") or ""),
        )
        if caller_after == caller_before and caller_before:
            # Still attach CALL before END if replace was a no-op on identical text
            pass
        evidence = [
            {
                "kind": "decouple",
                "block": name,
                "network": str(net.get("network_id") or ""),
                "title": str(net.get("title") or ""),
                "tags": sorted(reads | writes),
                "helper": helper,
                "reason": reason,
            }
        ]
        extracts.append(
            DecoupleExtract(
                caller=name,
                helper_name=helper,
                network_id=str(net.get("network_id") or ""),
                network_title=str(net.get("title") or ""),
                helper_scl=helper_scl,
                caller_scl=caller_after,
                inputs=inputs,
                outputs=outputs,
                evidence=evidence,
                reason=reason,
            )
        )
        scl_sources[name] = caller_after
        scl_sources[helper] = helper_scl
    return extracts
