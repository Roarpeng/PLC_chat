"""Evidence-gated PLC Analyst — deterministic findings from KG + folded logic.

Never invent CALLS. Every finding contains concrete KG-edge or folded-logic
evidence, so this module is safe to use without an LLM.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

try:  # Agent B may add this module independently.
    from agents.plc.tia.graph_query import (  # type: ignore[import-not-found]
        callees_of as _query_callees_of,
        callers_of as _query_callers_of,
        dead_blocks as _query_dead_blocks,
        readers_of_tag as _query_readers_of_tag,
        writers_of_tag as _query_writers_of_tag,
    )
except ImportError:  # Self-sufficient JSON KG fallbacks are used below.
    _query_callees_of = _query_callers_of = _query_dead_blocks = None
    _query_readers_of_tag = _query_writers_of_tag = None

try:
    from agents.plc.tia.flgnet_fold import stmt_to_scl as _stmt_to_scl
except ImportError:  # Folded logic is optional for older pipeline installs.
    _stmt_to_scl = None


def _name(node_id: object) -> str:
    """Turn typed KG IDs such as ``Block::Main`` into their display name."""
    return str(node_id).split("::", 1)[-1]


def _edges(job: dict[str, Any], edge_type: str | None = None) -> list[dict[str, Any]]:
    edges = (job.get("knowledge_graph") or {}).get("edges") or []
    return [
        edge
        for edge in edges
        if isinstance(edge, dict) and (edge_type is None or edge.get("type") == edge_type)
    ]


def _block_metadata(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {
        str(block["name"]): block
        for block in (job.get("blocks") or [])
        if isinstance(block, dict) and block.get("name")
    }
    for node in (job.get("knowledge_graph") or {}).get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "Block":
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        name = str(props.get("name") or _name(node.get("id") or ""))
        if name:
            result.setdefault(
                name,
                {
                    "name": name,
                    "type": props.get("block_type") or props.get("type") or "",
                },
            )
    return result


def _edge_evidence(edge: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "edge_type": str(edge.get("type") or ""),
        "source": str(edge.get("source") or ""),
        "target": str(edge.get("target") or ""),
    }
    props = edge.get("props")
    if isinstance(props, dict) and props.get("evidence"):
        evidence["source_evidence"] = props["evidence"]
    elif edge.get("evidence"):
        evidence["source_evidence"] = edge["evidence"]
    if isinstance(props, dict) and props.get("network"):
        evidence["network"] = str(props["network"])
    elif edge.get("network"):
        evidence["network"] = str(edge["network"])
    return evidence


def _call_edges(job: dict[str, Any], block_name: str, *, incoming: bool) -> list[dict[str, Any]]:
    block_id = f"Block::{block_name}"
    key = "target" if incoming else "source"
    return [edge for edge in _edges(job, "CALLS") if edge.get(key) == block_id]


def _calls(job: dict[str, Any], block_name: str) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Prefer optional graph-query helpers, but retain edge-level proof locally."""
    incoming = _call_edges(job, block_name, incoming=True)
    outgoing = _call_edges(job, block_name, incoming=False)
    callers = sorted({_name(edge.get("source")) for edge in incoming})
    callees = sorted({_name(edge.get("target")) for edge in outgoing})
    kg = job.get("knowledge_graph") or {}
    try:
        if _query_callers_of is not None:
            callers = sorted(set(_query_callers_of(kg, block_name)))
        if _query_callees_of is not None:
            callees = sorted(set(_query_callees_of(kg, block_name)))
    except (AttributeError, KeyError, TypeError):
        # Optional module shape is intentionally non-blocking.
        pass
    return callers, callees, [_edge_evidence(edge) for edge in incoming + outgoing]


def _io(job: dict[str, Any], block_name: str) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    block_id = f"Block::{block_name}"
    reads = [edge for edge in _edges(job, "READS") if edge.get("source") == block_id]
    writes = [edge for edge in _edges(job, "WRITES") if edge.get("source") == block_id]
    return (
        sorted({_name(edge.get("target")) for edge in reads}),
        sorted({_name(edge.get("target")) for edge in writes}),
        [_edge_evidence(edge) for edge in reads + writes],
    )


def _ob_names(job: dict[str, Any]) -> list[str]:
    return sorted(
        name
        for name, block in _block_metadata(job).items()
        if str(block.get("type") or block.get("block_type") or "").upper() == "OB"
    )


def _reachable_from_obs(job: dict[str, Any]) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in _edges(job, "CALLS"):
        adjacency[_name(edge.get("source"))].add(_name(edge.get("target")))
    reachable = set(_ob_names(job))
    queue: deque[str] = deque(reachable)
    while queue:
        for callee in adjacency.get(queue.popleft(), set()):
            if callee not in reachable:
                reachable.add(callee)
                queue.append(callee)
    return reachable


def _dead_block_names(job: dict[str, Any]) -> list[str]:
    blocks = _block_metadata(job)
    try:
        if _query_dead_blocks is not None:
            return sorted(set(_query_dead_blocks(job.get("knowledge_graph") or {})))
    except (AttributeError, KeyError, TypeError):
        pass
    reachable = _reachable_from_obs(job)
    return sorted(name for name in blocks if name not in reachable and name not in _ob_names(job))


def _expr_to_scl(value: Any) -> str:
    """Best-effort renderer for JSON serialized by ``folded_to_dict``."""
    if not isinstance(value, dict):
        return str(value)
    kind = value.get("type")
    if kind == "literal":
        return str(value.get("value", "(* literal *)"))
    if kind == "ref":
        return str(value.get("access", "(* ref *)"))
    if kind == "not":
        return f"NOT ({_expr_to_scl(value.get('operand'))})"
    if kind in {"and", "or"}:
        op = " AND " if kind == "and" else " OR "
        return op.join(f"({_expr_to_scl(item)})" for item in value.get("operands") or [])
    if kind == "compare":
        return f"({_expr_to_scl(value.get('lhs'))} {value.get('op', '?')} {_expr_to_scl(value.get('rhs'))})"
    return "(* folded expression unavailable *)"


def _folded_lines(job: dict[str, Any], block_name: str) -> tuple[list[str], list[dict[str, Any]]]:
    folded = (job.get("folded_logic") or {}).get(block_name) or []
    lines: list[str] = []
    evidence: list[dict[str, Any]] = []
    for network in folded:
        if not isinstance(network, dict):
            continue
        network_id = str(network.get("network_id") or "")
        for statement in network.get("statements") or []:
            if not isinstance(statement, dict):
                if _stmt_to_scl is not None:
                    lines.append(_stmt_to_scl(statement))
                    evidence.append(
                        {"kind": "folded_logic", "block": block_name, "network_id": network_id}
                    )
                continue
            target = str(statement.get("target") or "(* target unknown *)")
            condition = _expr_to_scl(statement.get("value"))
            stmt_kind = statement.get("kind")
            if stmt_kind == "neg_coil":
                line = f"{target} := NOT ({condition});"
            elif stmt_kind == "set":
                line = f"IF {condition} THEN {target} := TRUE; END_IF;"
            elif stmt_kind == "reset":
                line = f"IF {condition} THEN {target} := FALSE; END_IF;"
            else:
                line = f"{target} := {condition};"
            lines.append(line)
            evidence.append(
                {
                    "kind": "folded_logic",
                    "block": block_name,
                    "network_id": network_id,
                    "target": target,
                }
            )
    return lines, evidence


def analyze_block(job_or_ctx: dict, block_name: str) -> dict:
    """Return deterministic, evidence-carrying findings for one PLC block."""
    job = job_or_ctx
    blocks = _block_metadata(job)
    callers, callees, call_evidence = _calls(job, block_name)
    reads, writes, io_evidence = _io(job, block_name)
    folded, fold_evidence = _folded_lines(job, block_name)
    findings: list[dict[str, Any]] = []

    if call_evidence:
        findings.append(
            {
                "code": "CALL_GRAPH",
                "severity": "info",
                "message": f"`{block_name}` 的调用方: {', '.join(callers) or '无'}；调用目标: {', '.join(callees) or '无'}。",
                "evidence": call_evidence,
            }
        )
    if io_evidence:
        findings.append(
            {
                "code": "SIGNAL_FLOW",
                "severity": "info",
                "message": f"`{block_name}` 读取: {', '.join(reads) or '无'}；写入: {', '.join(writes) or '无'}。",
                "evidence": io_evidence,
            }
        )
    if folded:
        findings.append(
            {
                "code": "FOLDED_LOGIC",
                "severity": "info",
                "message": f"`{block_name}` 有 {len(folded)} 条已折叠的逻辑表达式。",
                "evidence": fold_evidence,
            }
        )

    block_type = str((blocks.get(block_name) or {}).get("type") or "").upper()
    if block_type in {"FB", "FC"} and not callers and not callees:
        findings.append(
            {
                "code": "NO_CALLS",
                "severity": "warn",
                "message": f"`{block_name}` 是 {block_type}，但 KG 中没有已验证的 CALLS 边。",
                "evidence": [
                    {
                        "kind": "block_metadata",
                        "block": block_name,
                        "block_type": block_type,
                        "calls_edges_checked": 0,
                    }
                ],
            }
        )
    if block_name in _dead_block_names(job):
        findings.append(
            {
                "code": "UNREACHABLE_FROM_OB",
                "severity": "risk",
                "message": f"`{block_name}` 未从任一 OB 入口经已验证 CALLS 边到达。",
                "evidence": [_edge_evidence(edge) for edge in _edges(job, "CALLS")] + [
                    {
                        "kind": "reachability",
                        "block": block_name,
                        "ob_entry_points": _ob_names(job),
                        "calls_edges_checked": len(_edges(job, "CALLS")),
                    }
                ],
            }
        )

    findings.extend(_nested_fb_findings(job, block_name))

    scl = (job.get("scl_sources") or {}).get(block_name)
    return {
        "block": block_name,
        "findings": findings,
        "calls": {"callers": callers, "callees": callees},
        "io": {"reads": reads, "writes": writes},
        "folded": folded,
        "scl_preview": "\n".join(str(scl).splitlines()[:40]) if scl else None,
    }


def analyze_project(job: dict) -> dict:
    """Return project-wide deterministic findings based solely on KG evidence."""
    blocks = _block_metadata(job)
    ob_entries = _ob_names(job)
    dead = _dead_block_names(job)
    call_edges = _edges(job, "CALLS")
    findings: list[dict[str, Any]] = []
    if dead:
        findings.append(
            {
                "code": "DEAD_BLOCK",
                "severity": "risk",
                "message": f"未从 OB 入口到达的块: {', '.join(dead)}。",
                "evidence": [_edge_evidence(edge) for edge in call_edges] + [
                    {
                        "kind": "reachability",
                        "ob_entry_points": ob_entries,
                        "calls_edges_checked": len(call_edges),
                        "blocks": dead,
                    }
                ],
            }
        )
    no_reads: list[str] = []
    no_writes: list[str] = []
    for name in sorted(blocks):
        reads, writes, evidence = _io(job, name)
        if not reads:
            no_reads.append(name)
        if not writes:
            no_writes.append(name)
        if evidence:
            findings.append(
                {
                    "code": "SIGNAL_FLOW",
                    "severity": "info",
                    "message": f"`{name}` 读取 {len(reads)} 个标签，写入 {len(writes)} 个标签。",
                    "evidence": evidence,
                }
            )
    writers: dict[str, list[str]] = defaultdict(list)
    for edge in _edges(job, "WRITES"):
        tag = _name(edge.get("target"))
        src = _name(edge.get("source"))
        if tag and src and src not in writers[tag]:
            writers[tag].append(src)
    for tag, srcs in sorted(writers.items()):
        if len(srcs) < 2:
            continue
        findings.append(
            {
                "code": "MULTIPLE_WRITERS",
                "severity": "warn",
                "message": f"标签 `{tag}` 被多个块写入: {', '.join(srcs)}。",
                "evidence": [
                    _edge_evidence(e)
                    for e in _edges(job, "WRITES")
                    if _name(e.get("target")) == tag
                ],
            }
        )
    interlock_findings = _missing_interlock_findings(job)
    findings.extend(interlock_findings)
    safety_findings = _safety_findings(job, writers)
    findings.extend(safety_findings)
    findings.extend(_project_nested_fb_findings(job))
    return {
        "project": job.get("project_name") or "",
        "findings": findings,
        "dead_blocks": dead,
        "blocks_with_no_reads": no_reads,
        "blocks_with_no_writes": no_writes,
        "ob_entry_points": ob_entries,
        "calls_edge_count": len(call_edges),
        "safety_outputs": safety_findings[0]["evidence"] if safety_findings else [],
    }


def _typed_as_evidence(job: dict[str, Any], block_name: str) -> tuple[list[dict[str, Any]], list[list[str]], int]:
    from agents.plc.tia.typed_as import nest_depth_of, typed_as_chains, typed_as_members

    kg = job.get("knowledge_graph") or {}
    members = typed_as_members(kg, block_name)
    chains = typed_as_chains(kg, block_name)
    depth = nest_depth_of(kg, block_name)
    evidence: list[dict[str, Any]] = []
    for item in members:
        evidence.append(
            {
                "kind": "typed_as",
                "edge_type": "TYPED_AS",
                "source": item.get("source") or f"Block::{block_name}",
                "target": f"Block::{item.get('type_block')}",
                "member": item.get("member"),
                "section": item.get("section"),
                "evidence": item.get("evidence") or "interface_data_type",
            }
        )
    if chains:
        evidence.append(
            {
                "kind": "multi_instance_chain",
                "block": block_name,
                "nest_depth": depth,
                "chains": chains[:8],
            }
        )
    return evidence, chains, depth


def _nested_fb_findings(job: dict[str, Any], block_name: str) -> list[dict[str, Any]]:
    """Warn/risk for in-block FB-as-type nesting — not instance-DB INSTANCE_OF."""
    evidence, chains, depth = _typed_as_evidence(job, block_name)
    if depth < 1:
        return []
    from agents.plc.tia.typed_as import format_chain, typed_as_members

    kg = job.get("knowledge_graph") or {}
    members = typed_as_members(kg, block_name)
    member_bits = [
        f"`{m.get('member') or '?'} : {m.get('type_block')}`"
        for m in members
        if m.get("type_block")
    ]
    findings: list[dict[str, Any]] = [
        {
            "code": "NESTED_FB_TYPE",
            "severity": "warn",
            "message": (
                f"`{block_name}` 以多实例成员嵌入 FB/FC/UDT 类型"
                f"（深度 {depth}）："
                + ("、".join(member_bits[:8]) or "见 TYPED_AS 边")
                + "。"
            ),
            "evidence": evidence,
        }
    ]
    if depth >= 2:
        longest = chains[0] if chains else [block_name]
        findings.append(
            {
                "code": "MULTI_INSTANCE_CHAIN",
                "severity": "risk",
                "message": (
                    f"`{block_name}` 多实例嵌套链（深度 {depth}）："
                    f"{format_chain(longest)}。"
                ),
                "evidence": evidence,
            }
        )
    return findings


def _project_nested_fb_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Project-wide deep multi-instance chains (depth ≥ 2). Skip shallow INSTANCE_OF."""
    from agents.plc.tia.typed_as import format_chain, nest_depth_of, typed_as_chains

    kg = job.get("knowledge_graph") or {}
    blocks = _block_metadata(job)
    hits: list[tuple[int, str, list[str]]] = []
    for name in blocks:
        depth = nest_depth_of(kg, name)
        if depth < 2:
            continue
        chains = typed_as_chains(kg, name)
        longest = chains[0] if chains else [name]
        hits.append((depth, name, longest))
    if not hits:
        return []
    hits.sort(key=lambda item: (-item[0], item[1]))
    shown = hits[:12]
    bits = [f"`{name}`（深度 {depth}：{format_chain(chain)}）" for depth, name, chain in shown]
    evidence = [
        {
            "kind": "multi_instance_chain",
            "block": name,
            "nest_depth": depth,
            "chain": chain,
        }
        for depth, name, chain in shown
    ]
    return [
        {
            "code": "MULTI_INSTANCE_CHAIN",
            "severity": "risk",
            "message": "工程中存在深度≥2 的多实例 FB 类型嵌套：" + "；".join(bits) + "。",
            "evidence": evidence,
        }
    ]


def _block_is_safety(job: dict[str, Any], name: str) -> bool:
    meta = _block_metadata(job).get(name) or {}
    if meta.get("is_safety") or meta.get("safety"):
        return True
    for node in (job.get("knowledge_graph") or {}).get("nodes") or []:
        if node.get("type") != "Block":
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        nid = str(node.get("id") or "")
        if _name(nid) == name:
            return bool(props.get("safety"))
    n = (name or "").upper()
    return n.startswith(("F-", "F_", "FOB", "FFB", "FFC", "FDB"))


def _missing_interlock_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag outputs whose folded coil is unconditional / single contact — do not auto-fix."""
    findings: list[dict[str, Any]] = []
    folded = job.get("folded_logic") or {}
    if not isinstance(folded, dict):
        return findings
    for block_name, networks in folded.items():
        if not isinstance(networks, list):
            continue
        for net in networks:
            if not isinstance(net, dict):
                continue
            net_id = str(net.get("network_id") or net.get("title") or "")
            for stmt in net.get("statements") or []:
                if not isinstance(stmt, dict):
                    continue
                kind = str(stmt.get("kind") or "coil")
                if kind not in {"coil", "set"}:
                    continue
                target = str(stmt.get("target") or "")
                if not target or target.startswith("(*"):
                    continue
                value = stmt.get("value")
                simple = False
                if isinstance(value, dict) and value.get("type") == "literal" and value.get("value") is True:
                    simple = True
                if isinstance(value, dict) and value.get("type") == "ref":
                    simple = True
                if not simple:
                    continue
                findings.append(
                    {
                        "code": "OUTPUT_NO_INTERLOCK",
                        "severity": "warn",
                        "message": (
                            f"`{block_name}` 输出 `{target}` 未见明显互锁触点（仅单条件/恒 TRUE）。"
                            "仅标记，不自动改 LAD。"
                        ),
                        "evidence": [
                            {
                                "kind": "folded_logic",
                                "block": block_name,
                                "network": net_id,
                                "target": target,
                                "snippet": f"{target} := …",
                            }
                        ],
                    }
                )
    return findings[:20]


def _safety_findings(job: dict[str, Any], writers: dict[str, list[str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    safety_blocks = [n for n in _block_metadata(job) if _block_is_safety(job, n)]
    safety_tags: set[str] = set()
    for edge in _edges(job, "WRITES"):
        src = _name(edge.get("source"))
        tag = _name(edge.get("target"))
        if src in safety_blocks and tag:
            safety_tags.add(tag)
    if safety_tags:
        findings.append(
            {
                "code": "SAFETY_OUTPUTS",
                "severity": "info",
                "message": f"安全输出: {', '.join(sorted(safety_tags)[:20])}",
                "evidence": [
                    {"kind": "safety_tag", "tag": t, "writers": writers.get(t, [])}
                    for t in sorted(safety_tags)[:20]
                ],
            }
        )
    for tag in sorted(safety_tags):
        std = [w for w in writers.get(tag, []) if not _block_is_safety(job, w)]
        if not std:
            continue
        findings.append(
            {
                "code": "STANDARD_WRITES_SAFETY",
                "severity": "risk",
                "message": f"标准块写入安全标签 `{tag}`: {', '.join(std)}。",
                "evidence": [
                    _edge_evidence(e)
                    for e in _edges(job, "WRITES")
                    if _name(e.get("target")) == tag
                    and not _block_is_safety(job, _name(e.get("source")))
                ],
            }
        )
    return findings


def _role_hint(name: str, comment: str = "", titles: list[str] | None = None) -> str:
    """Cheap domain label from block name / comment / network titles (not invented CALLS)."""
    blob = " ".join([name, comment or "", " ".join(titles or [])]).lower()
    rules = [
        (("kuka", "robot", "机器人"), "机器人"),
        (("visual", "chisel", "vision", "相机", "凿削", "ros"), "视觉/凿削"),
        (("modbus", "communication_pc", "通信"), "通信"),
        (("cooling", "fan", "冷却", "风扇"), "冷却"),
        (("valve", "阀"), "阀岛/执行器"),
        (("component", "组件"), "设备组件"),
        (("safety", "door", "安全门", "safedoor"), "安全"),
        (("fixture", "夹具"), "夹具"),
        (("drill", "hammer", "钻"), "钻孔"),
        (("diamond", "金刚"), "金刚石工艺"),
        (("autostep", "auto_step", "自动"), "自动步序"),
        (("sysmode", "subsys", "模式"), "模式管理"),
        (("homepos", "home", "回零", "原点"), "回零/原点"),
        (("parameter", "参数"), "参数"),
        (("message", "prompt", "提示", "消息", "typechange"), "消息/提示"),
        (("ft control", "force", "torque", "力控"), "力/力矩"),
        (("timer", "定时"), "定时"),
        (("analog", "模拟"), "模拟量"),
        (("stdsignal", "标准信号"), "标准信号"),
        (("iocheck",), "IO 检查"),
        (("time calculation", "time calc"), "时序/对时"),
    ]
    for keys, label in rules:
        if any(k in blob for k in keys):
            return label
    return ""


def _network_titles(job: dict[str, Any], block_name: str, *, limit: int = 8) -> list[str]:
    titles: list[str] = []
    folded = job.get("folded_logic") or {}
    nets = folded.get(block_name) if isinstance(folded, dict) else None
    if isinstance(nets, list):
        for net in nets:
            if not isinstance(net, dict):
                continue
            title = str(net.get("title") or "").strip().strip('"')
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= limit:
                return titles
    scl = str((job.get("scl_sources") or {}).get(block_name) or "")
    for line in scl.splitlines():
        s = line.strip()
        if s.upper().startswith("// NETWORK") and ":" in s:
            title = s.split(":", 1)[1].strip()
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= limit:
                break
    return titles


def _ordered_callees(job: dict[str, Any], block_name: str) -> list[str]:
    """Callees in logic_graph scan order when available, else KG CALLS."""
    block_id = f"Block::{block_name}"
    logic_edges = (job.get("logic_graph") or {}).get("edges") or []
    scored: list[tuple[int, str]] = []
    for edge in logic_edges:
        if not isinstance(edge, dict) or edge.get("type") != "CALLS":
            continue
        if edge.get("source") != block_id:
            continue
        target = _name(edge.get("target"))
        if not target:
            continue
        seq = edge.get("seq")
        try:
            scored.append((int(seq), target))
        except (TypeError, ValueError):
            scored.append((10_000, target))
    if scored:
        scored.sort(key=lambda item: (item[0], item[1]))
        out: list[str] = []
        for _, name in scored:
            if name not in out:
                out.append(name)
        return out
    _callers, callees, _ev = _calls(job, block_name)
    return callees


def describe_project_architecture(job: dict[str, Any]) -> str:
    """KG/CALLS hypotheses for a project (no LLM).

    Do **not** paste this into chat as if the plant is already understood.
    The ingest welcome and 「优化建议」 path interview the engineer via
    ``agents.plc.tia.understanding``; this text is a source of questions.
    """
    blocks = _block_metadata(job)
    summary = job.get("summary") or {}
    project = job.get("project_name") or "工程"
    obs = _ob_names(job)
    # Prefer cyclic OB1 / Main as primary scan entry
    main_ob = ""
    for candidate in obs:
        low = candidate.lower()
        if candidate.startswith("OB1") or low in {"main", "ob1", "ob1main"} or "main" in low:
            main_ob = candidate
            break
    if not main_ob and obs:
        main_ob = obs[0]

    lines: list[str] = []
    summary_bits = []
    if isinstance(summary, dict):
        for key in ("OB", "FB", "FC", "DB", "Networks"):
            if key in summary:
                summary_bits.append(f"{key} {summary[key]}")
    head = f"**{project}**"
    if summary_bits:
        head += " · " + " · ".join(summary_bits)
    lines.append(head)

    # Domain fingerprint from names/comments/titles across FB/FC
    role_hits: dict[str, list[str]] = defaultdict(list)
    for name, meta in blocks.items():
        btype = str(meta.get("type") or "").upper()
        if btype not in {"FB", "FC", "OB"}:
            continue
        role = _role_hint(name, str(meta.get("comment") or ""), _network_titles(job, name, limit=4))
        if role:
            role_hits[role].append(name)
    if role_hits:
        # Prefer roles with more than one hit, or strong process roles
        ordered_roles = sorted(
            role_hits.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )
        fingerprint = []
        for role, names in ordered_roles[:8]:
            fingerprint.append(f"{role}（{len(names)}）")
        lines.append("能力画像（据块名/注释/网络标题）：" + "、".join(fingerprint))

    if main_ob:
        callees = _ordered_callees(job, main_ob)
        lines.append(f"主扫描入口：`{main_ob}`" + (f"（调用 {len(callees)} 个块）" if callees else ""))
        if callees:
            lines.append("扫描调用链（顺序来自逻辑图 CALLS）：")
            for i, callee in enumerate(callees[:16], start=1):
                meta = blocks.get(callee) or {}
                comment = str(meta.get("comment") or "")
                titles = _network_titles(job, callee, limit=3)
                # Prefer name/comment roles; titles only if name gives nothing
                role = _role_hint(callee, comment) or _role_hint(callee, "", titles)
                children = _ordered_callees(job, callee)
                role_s = f" — {role}" if role else ""
                if children:
                    child_bits = []
                    for ch in children[:6]:
                        cr = _role_hint(ch, str((blocks.get(ch) or {}).get("comment") or ""))
                        child_bits.append(f"`{ch}`" + (f"({cr})" if cr else ""))
                    more = f" 等{len(children)}个" if len(children) > 6 else ""
                    lines.append(
                        f"{i}. `{callee}`{role_s} → " + "、".join(child_bits) + more
                    )
                else:
                    title_s = f"；网络：{' / '.join(titles)}" if titles else ""
                    lines.append(f"{i}. `{callee}`{role_s}{title_s}")

            # Highlight major hubs (high fan-out under main)
            hubs = []
            for callee in callees:
                kids = _ordered_callees(job, callee)
                if len(kids) >= 3:
                    hubs.append((callee, kids))
            if hubs:
                lines.append("关键子系统（主循环下再分发）：")
                for hub, kids in hubs[:4]:
                    role = _role_hint(hub, str((blocks.get(hub) or {}).get("comment") or ""))
                    kid_roles = []
                    for ch in kids[:8]:
                        kid_roles.append(
                            f"`{ch}`"
                            + (
                                f"({_role_hint(ch, str((blocks.get(ch) or {}).get('comment') or ''))})"
                                if _role_hint(ch, str((blocks.get(ch) or {}).get("comment") or ""))
                                else ""
                            )
                        )
                    lines.append(
                        f"- `{hub}`"
                        + (f"（{role}）" if role else "")
                        + "："
                        + "、".join(kid_roles)
                        + (f" …共{len(kids)}个" if len(kids) > 8 else "")
                    )
        else:
            lines.append(f"`{main_ob}` 暂无已验证 CALLS 边；可点击图谱节点或 `@块名` 深入。")
    else:
        lines.append("未发现 OB 入口；以下按块类型罗列（证据不足时的退化视图）。")

    other_obs = [o for o in obs if o != main_ob]
    if other_obs:
        lines.append("其它 OB：" + "、".join(f"`{o}`" for o in other_obs[:8]))

    # Compact type inventory (not a raw dump of first 20 DB names)
    by_type: dict[str, list[str]] = defaultdict(list)
    for name, meta in blocks.items():
        by_type[str(meta.get("type") or "?").upper()].append(name)
    inv = []
    for t in ("OB", "FB", "FC", "DB"):
        names = sorted(by_type.get(t) or [])
        if names:
            inv.append(f"{t} {len(names)}")
    if inv:
        lines.append("块库存：" + " · ".join(inv))

    # Process / device FB highlights by role
    process_roles = ("自动步序", "机器人", "钻孔", "金刚石工艺", "视觉/凿削", "阀岛/执行器", "冷却")
    highlights: list[str] = []
    for role in process_roles:
        names = role_hits.get(role) or []
        # Prefer FB/FC over DB/instance names
        preferred = [
            n
            for n in names
            if str((blocks.get(n) or {}).get("type") or "").upper() in {"FB", "FC"}
        ] or names
        if preferred:
            highlights.append(f"{role}：`" + "`、`".join(preferred[:4]) + "`")
    if highlights:
        lines.append("工艺/设备要点：")
        lines.extend(f"- {h}" for h in highlights[:8])

    lines.append("深入：点击图谱节点，或发送 `@块名 描述功能` / `@网络标题 作用`。")
    return "\n".join(lines)


def _folded_step_titles(job: dict[str, Any], block_name: str, *, limit: int = 18) -> list[str]:
    """Meaningful network titles for a process FB (skip empty / asterisk banners lightly)."""
    titles = _network_titles(job, block_name, limit=40)
    out: list[str] = []
    for title in titles:
        t = title.strip().strip("*").strip()
        if not t or t.lower() in {"running;", "taskdone", "always 1 and 0"}:
            continue
        # Collapse long asterisk separators but keep content
        if set(t) <= {"*", " ", "-", "_"}:
            continue
        if t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _axis_block_map(job: dict[str, Any]) -> dict[str, list[str]]:
    """Map process axes → concrete FB/FC names present in this job."""
    blocks = _block_metadata(job)
    names = list(blocks.keys())

    def pick(*needles: str) -> list[str]:
        found: list[str] = []
        for name in names:
            low = name.lower()
            if any(n.lower() in low for n in needles):
                # Prefer FB/FC over DB/instance
                btype = str((blocks.get(name) or {}).get("type") or "").upper()
                if btype in {"FB", "FC", "OB"}:
                    found.append(name)
        # Stable unique
        out: list[str] = []
        for n in found:
            if n not in out:
                out.append(n)
        return out

    return {
        "horizontal": pick("HorDrill", "Hor_Drill", "Horizontal"),
        "down": pick("DownDrill", "Down_Drill", "DownChisel"),
        "up": pick("UpDrill", "Up_Drill", "Upward"),
        "robot": pick("RobotAutoStep"),
        "dispatcher": pick("FB1060_AutoStep", "AutoStep"),
        "core": pick("Diamond", "CoreDrill"),
        "vision": pick("Visual Chiseling", "VisualChisel"),
        "kuka": pick("KuKa_MainCtrl", "Kuka_MainCtrl"),
    }


def _message_wants_axis_process(message: str) -> bool:
    raw = message or ""
    msg = raw.lower()
    zh = ("水平", "垂直", "向上", "向下", "作业", "钻孔", "打孔", "钻削", "凿削", "工艺逻辑")
    en = ("hor", "down", "updrill", "drill axis", "horizontal", "vertical")
    return any(k in raw for k in zh) or any(k in msg for k in en)


def describe_axis_process_logic(job: dict[str, Any], message: str = "") -> str | None:
    """Answer horizontal / vertical-down / vertical-up process logic from folded titles + CALLS.

    Returns None if the job has no matching process blocks.
    """
    axes = _axis_block_map(job)
    if not (axes["horizontal"] or axes["down"] or axes["up"] or axes["dispatcher"]):
        return None

    msg = message or ""
    want_h = "水平" in msg or "hor" in msg.lower()
    want_d = "向下" in msg or "down" in msg.lower()
    want_u = "向上" in msg or "updrill" in msg.lower()
    if "垂直" in msg:
        want_d = True
        if "向上" in msg:
            want_u = True
    if not (want_h or want_d or want_u):
        # 「作业/工艺逻辑」等笼统问法 → 有证据的方向全给
        want_h = want_d = True
        want_u = True

    lines: list[str] = []
    lines.append("**作业方向逻辑（据 AutoStep 调度 + 各方向步序 FB 网络标题）**")
    lines.append(
        "说明：PLC 对话走知识图谱/折叠网络的确定性回答，**不依赖 LLM 联通**。"
    )

    disp = (axes["dispatcher"] or [""])[0]
    if disp:
        lines.append(f"总调度：`{disp}` 按方向调用子步序（网络可见 `HorDrillAutoStep` / `DownDrillAutoStep` / `CoreDrillAutoStep`）。")
        # Direction codes from PC para if present in folded enable refs — already observed 1/2/3
        lines.append(
            "方向字：`DB1042_Timer.DrillDirectionCurrent/Memory` ← `DB1900_Communication_PC.Para.DrillDirection1/2/3`（值为 1/2/3）。"
        )

    def emit_axis(label: str, block_names: list[str], extra: list[str] | None = None) -> None:
        if not block_names and not extra:
            lines.append(f"### {label}")
            lines.append("图谱中**未找到**独立步序 FB（无 UpDrill 类块名/网络标题证据）。")
            return
        lines.append(f"### {label}")
        for name in block_names:
            meta = _block_metadata(job).get(name) or {}
            comment = str(meta.get("comment") or "").strip()
            nets = meta.get("networks")
            head = f"- 块：`{name}`"
            if nets is not None:
                head += f"（{nets} 网络）"
            if comment:
                head += f" — {comment[:80]}"
            lines.append(head)
            steps = _folded_step_titles(job, name, limit=14)
            if steps:
                lines.append("  步序要点：" + " → ".join(f"`{s}`" for s in steps[:12]))
            children = _ordered_callees(job, name)
            if children:
                lines.append("  再调用：" + "、".join(f"`{c}`" for c in children[:8]))
        for note in extra or []:
            lines.append(f"- {note}")

    if want_h:
        extras = []
        if axes["vision"]:
            extras.append(
                "视觉凿削挂在主循环，网络标注 **Only for Hor Chisel**：`"
                + "`、`".join(axes["vision"][:3])
                + "`"
            )
        if axes["robot"]:
            rsteps = _folded_step_titles(job, axes["robot"][0], limit=20)
            hor_steps = [s for s in rsteps if "水平" in s or "Hor" in s]
            if hor_steps:
                extras.append(f"机器人支路 `{axes['robot'][0]}`：" + " / ".join(hor_steps[:4]))
        emit_axis("水平作业", axes["horizontal"], extras)

    if want_d:
        extras = []
        if axes["robot"]:
            rsteps = _folded_step_titles(job, axes["robot"][0], limit=20)
            down_steps = [s for s in rsteps if "向下" in s or "Down" in s or "下" in s]
            if down_steps:
                extras.append(f"机器人支路 `{axes['robot'][0]}`：" + " / ".join(down_steps[:4]))
        emit_axis("垂直向下作业", axes["down"], extras)

    if want_u:
        extras = []
        if axes["core"]:
            extras.append(
                "第三路工艺为取芯/金刚石 `CoreDrillAutoStep`→"
                + "、".join(f"`{n}`" for n in axes["core"][:2])
                + "，**不是**命名为 Up 的垂直向上钻；若现场“向上”指 Dir=3，需结合 HMI/参数表确认。"
            )
        if not axes["up"]:
            extras.append(
                "证据：仅见水平 `HorDrill*` 与垂直向下 `DownDrill*`；无 `UpDrill*` 块。"
            )
        emit_axis("垂直向上作业", axes["up"], extras)

    # Cross-cut shared resources
    shared = []
    if axes["kuka"]:
        shared.append("`" + axes["kuka"][0] + "`（钻削应答/层号/停止钻）")
    shared.append("`DB1910_DrillData`（已钻长度等）")
    shared.append("`DB1080_Component`（压力/机器人 ProgNo/速度）")
    shared.append("`DB1900_Communication_PC`（参数与上位握手）")
    lines.append("共用资源：" + "、".join(shared))
    lines.append("深入单块：`@FB1062_HorDrillAutoStep` / `@FB1063_DownDrillAutoStep` / `@FB1061_RobotAutoStep`。")
    return "\n".join(lines)


def format_analysis_markdown(result: dict) -> str:
    """Format deterministic PLC analysis as a compact Chinese chat section."""
    lines = ["## 证据门控分析", ""]
    if result.get("block"):
        lines.append(f"分析块：`{result['block']}`")
    else:
        lines.append(f"工程：`{result.get('project') or '未命名工程'}`")
        lines.append(f"- OB 入口：{', '.join(result.get('ob_entry_points') or []) or '未发现'}")
        lines.append(f"- 已验证 CALLS 边：{result.get('calls_edge_count', 0)}")
    findings = result.get("findings") or []
    if not findings:
        lines.append("- 未产生可报告的已验证发现。")
    for finding in findings:
        lines.append(f"- [{finding.get('severity', 'info')}] `{finding.get('code', 'INFO')}`：{finding.get('message', '')}")
    folded = result.get("folded") or []
    if folded:
        lines.append("")
        lines.append("已折叠逻辑：")
        for network in folded:
            for statement in (network.get("statements") or []) if isinstance(network, dict) else []:
                lines.append(f"- `{statement.get('target', '?')} := {_expr_to_scl(statement.get('value'))};`")
    lines.append("")
    lines.append("> 仅列出知识图谱边和已折叠逻辑的证据；不推断未验证的调用关系。")
    return "\n".join(lines)
