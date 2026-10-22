"""Deterministic queries and UI dependency derivation for PLC knowledge graphs."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from agents.plc.tia.typed_as import (
    TYPED_AS,
)
from agents.plc.tia.typed_as import (
    nest_depth_of as _nest_depth_of,
)
from agents.plc.tia.typed_as import (
    typed_as_chains as _typed_as_chains,
)
from agents.plc.tia.typed_as import (
    typed_as_children as _typed_as_children,
)
from agents.plc.tia.typed_as import (
    typed_as_members as _typed_as_members,
)


def normalize_kg(kg: dict[str, Any] | Any) -> dict[str, list[dict[str, Any]]]:
    """Return the JSON-compatible KG shape accepted by this module."""
    if hasattr(kg, "to_json") and callable(kg.to_json):
        kg = kg.to_json()
    if not isinstance(kg, dict):
        raise TypeError("kg must be a dict or an object with to_json()")
    return {
        "nodes": [n for n in kg.get("nodes") or [] if isinstance(n, dict)],
        "edges": [e for e in kg.get("edges") or [] if isinstance(e, dict)],
    }


def block_id(name: str) -> str:
    return f"Block::{name}"


def tag_id(name: str) -> str:
    return f"Tag::{name}"


def _block_name(node_id: str) -> str:
    return node_id.split("::", 1)[-1]


def _block_nodes(kg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node["id"]): node
        for node in kg["nodes"]
        if node.get("type") == "Block" and node.get("id")
    }


def _access_matches_tag(
    edge: dict[str, Any], tag: str, node_by_id: dict[str, dict[str, Any]]
) -> bool:
    target = str(edge.get("target") or "")
    if target == tag_id(tag):
        return True
    target_node = node_by_id.get(target, {})
    values = [target]
    values.extend(
        str((target_node.get("props") or {}).get(key) or "")
        for key in ("name", "ref", "tag", "reference")
    )
    props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    values.extend(str(props.get(key) or "") for key in ("tag", "ref", "access", "reference"))
    return any(value == tag or value == tag_id(tag) for value in values)


def _tag_from_edge(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> str | None:
    target = str(edge.get("target") or "")
    if target.startswith("Tag::"):
        return target.removeprefix("Tag::")
    node = node_by_id.get(target, {})
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    edge_props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    for value in (
        props.get("name"),
        props.get("ref"),
        props.get("tag"),
        edge_props.get("tag"),
        edge_props.get("ref"),
        edge_props.get("access"),
    ):
        if isinstance(value, str) and value:
            return value.removeprefix("Tag::")
    return None


def _access_edges(kg: dict[str, Any], access_type: str) -> list[dict[str, Any]]:
    blocks = _block_nodes(kg)
    return [
        edge
        for edge in kg["edges"]
        if edge.get("type") == access_type and str(edge.get("source") or "") in blocks
    ]


def callers_of(kg: dict[str, Any] | Any, block_name: str) -> list[str]:
    graph = normalize_kg(kg)
    target = block_id(block_name)
    return sorted(
        {
            _block_name(str(edge["source"]))
            for edge in graph["edges"]
            if edge.get("type") == "CALLS" and edge.get("target") == target
        }
    )


def callees_of(kg: dict[str, Any] | Any, block_name: str) -> list[str]:
    graph = normalize_kg(kg)
    source = block_id(block_name)
    return sorted(
        {
            _block_name(str(edge["target"]))
            for edge in graph["edges"]
            if edge.get("type") == "CALLS" and edge.get("source") == source
        }
    )


def _blocks_for_tag(kg: dict[str, Any] | Any, tag: str, access_type: str) -> list[str]:
    graph = normalize_kg(kg)
    node_by_id = {str(node.get("id")): node for node in graph["nodes"]}
    return sorted(
        {
            _block_name(str(edge["source"]))
            for edge in _access_edges(graph, access_type)
            if _access_matches_tag(edge, tag, node_by_id)
        }
    )


def writers_of_tag(kg: dict[str, Any] | Any, tag: str) -> list[str]:
    return _blocks_for_tag(kg, tag, "WRITES")


def readers_of_tag(kg: dict[str, Any] | Any, tag: str) -> list[str]:
    return _blocks_for_tag(kg, tag, "READS")


def _ob_block_ids(kg: dict[str, Any], blocks: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        node_id
        for node_id, node in blocks.items()
        if str((node.get("props") or {}).get("block_type") or "").upper() == "OB"
    )


def reachable_from(
    kg: dict[str, Any] | Any,
    roots: list[str] | None = None,
    edge_types: tuple[str, ...] = ("CALLS", "INSTANCE_OF"),
) -> set[str]:
    """Return reachable block names by traversing only the requested edge types."""
    graph = normalize_kg(kg)
    blocks = _block_nodes(graph)
    root_ids = [block_id(name) for name in roots] if roots is not None else _ob_block_ids(graph, blocks)
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if edge.get("type") in edge_types and source in blocks and target in blocks:
            adjacency[source].add(target)
    visited: set[str] = set()
    pending = deque(node_id for node_id in root_ids if node_id in blocks)
    while pending:
        current = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(sorted(adjacency[current] - visited))
    return {_block_name(node_id) for node_id in visited}


def dead_blocks(kg: dict[str, Any] | Any) -> list[str]:
    graph = normalize_kg(kg)
    blocks = _block_nodes(graph)
    ob_ids = set(_ob_block_ids(graph, blocks))
    reachable = {block_id(name) for name in reachable_from(graph, edge_types=("CALLS",))}
    return sorted(_block_name(node_id) for node_id in blocks if node_id not in ob_ids | reachable)


def typed_as_of(kg: dict[str, Any] | Any, block_name: str) -> list[dict[str, Any]]:
    """In-block members whose data_type is another IR block (multi-instance)."""
    return _typed_as_members(normalize_kg(kg), block_name)


def typed_as_callees(kg: dict[str, Any] | Any, block_name: str) -> list[str]:
    return _typed_as_children(normalize_kg(kg), block_name)


def nest_depth(kg: dict[str, Any] | Any, block_name: str) -> int:
    return _nest_depth_of(normalize_kg(kg), block_name)


def typed_as_chains(kg: dict[str, Any] | Any, block_name: str) -> list[list[str]]:
    return _typed_as_chains(normalize_kg(kg), block_name)


def _access_evidence(
    graph: dict[str, Any], tag: str, access_types: tuple[str, ...]
) -> list[dict[str, Any]]:
    node_by_id = {str(node.get("id")): node for node in graph["nodes"]}
    return [
        edge
        for edge in graph["edges"]
        if edge.get("type") in access_types and _access_matches_tag(edge, tag, node_by_id)
    ]


def depends_between(
    kg: dict[str, Any] | Any, src_block: str, tgt_block: str
) -> dict[str, Any]:
    graph = normalize_kg(kg)
    src, tgt = block_id(src_block), block_id(tgt_block)
    node_by_id = {str(node.get("id")): node for node in graph["nodes"]}
    target_name = _block_name(tgt)
    evidence: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        if edge.get("type") == "DEPENDS_ON" and edge.get("source") == src and edge.get("target") == tgt:
            evidence.append(edge)
    access_edges = [
        edge
        for edge in graph["edges"]
        if edge.get("type") in {"READS", "WRITES"} and str(edge.get("source") or "") in {src, tgt}
    ]
    source_tags = {
        _tag_from_edge(edge, node_by_id)
        for edge in access_edges
        if edge.get("source") == src
    }
    target_tags = {
        _tag_from_edge(edge, node_by_id)
        for edge in access_edges
        if edge.get("source") == tgt
    }
    for edge in access_edges:
        tag = _tag_from_edge(edge, node_by_id)
        if not tag:
            continue
        if (
            edge.get("source") == src
            and (tag == target_name or tag.startswith(f"{target_name}.") or tag.startswith(f"{target_name}["))
        ) or (
            edge.get("source") == src
            and edge.get("type") == "WRITES"
            and tag in target_tags
        ) or (
            edge.get("source") == tgt
            and edge.get("type") == "READS"
            and tag in source_tags
        ):
            evidence.append(edge)
    unique_evidence: list[dict[str, Any]] = []
    seen_evidence: set[tuple[str, str, str, str]] = set()
    for edge in evidence:
        key = (
            str(edge.get("source")),
            str(edge.get("target")),
            str(edge.get("type")),
            repr(edge.get("props")),
        )
        if key not in seen_evidence:
            seen_evidence.add(key)
            unique_evidence.append(edge)
    derived = any(
        edge["source"] == src and edge["target"] == tgt
        for edge in derive_depends_on_edges(graph, max_edges=10_000)
    )
    return {
        "source": src_block,
        "target": tgt_block,
        "depends": bool(unique_evidence) or derived,
        "evidence": unique_evidence,
    }


def derive_depends_on_edges(kg: dict[str, Any] | Any, *, max_edges: int = 160) -> list[dict[str, Any]]:
    """Derive evidence-backed functional dependencies between PLC blocks."""
    graph = normalize_kg(kg)
    blocks = _block_nodes(graph)
    node_by_id = {str(node.get("id")): node for node in graph["nodes"]}
    names_by_length = sorted(
        (
            (str((node.get("props") or {}).get("name") or _block_name(node_id)), node_id)
            for node_id, node in blocks.items()
        ),
        key=lambda item: (-len(item[0]), item[0]),
    )
    weights: dict[tuple[str, str], int] = defaultdict(int)
    evidence: dict[tuple[str, str], set[str]] = defaultdict(set)
    readers: dict[str, set[str]] = defaultdict(set)
    writers: dict[str, set[str]] = defaultdict(set)

    for edge in graph["edges"]:
        edge_type, source = str(edge.get("type") or ""), str(edge.get("source") or "")
        if edge_type not in {"READS", "WRITES"} or source not in blocks:
            continue
        tag = _tag_from_edge(edge, node_by_id)
        if not tag or tag.startswith("#"):
            continue
        for target_name, target_id in names_by_length:
            if source != target_id and (
                tag == target_name
                or tag.startswith(f"{target_name}.")
                or tag.startswith(f"{target_name}[")
            ):
                weights[(source, target_id)] += 1
                evidence[(source, target_id)].add("xml_var_access")
                break
        if edge_type == "READS":
            readers[tag].add(source)
        else:
            writers[tag].add(source)

    for tag in sorted(set(readers) | set(writers)):
        for source in sorted(writers[tag]):
            for target in sorted(readers[tag]):
                if source == target:
                    continue
                weights[(source, target)] += 1
                evidence[(source, target)].add(f"shared_tag:{tag}")

    derived = [
        {
            "source": source,
            "target": target,
            "type": "DEPENDS_ON",
            "weight": weight,
            "evidence": ";".join(sorted(evidence[(source, target)])),
        }
        for (source, target), weight in weights.items()
    ]
    derived.sort(key=lambda edge: (-edge["weight"], edge["source"], edge["target"]))
    return derived[:max(0, max_edges)]


def _node_label(node_id: str) -> str:
    return node_id.split("::", 1)[-1] if "::" in node_id else node_id


def resolve_kg_node(kg: dict[str, Any] | Any, ref: str) -> str | None:
    """Resolve a user-typed reference (tag or block name) to a KG node id.

    Exact ``Tag::x`` / ``Block::x`` ids win; otherwise a tag whose last path
    segment matches (``"Table".Motor`` matches ``Motor``).
    """
    ref = str(ref or "").strip().strip('"')
    if not ref:
        return None
    ids = {str(node.get("id") or "") for node in kg["nodes"]}
    for candidate in (tag_id(ref), block_id(ref)):
        if candidate in ids:
            return candidate
    tail = ref.rsplit(".", 1)[-1].strip('"')
    for node in kg["nodes"]:
        node_id = str(node.get("id") or "")
        if node_id.startswith("Tag::") and _node_label(node_id).rsplit(".", 1)[-1].strip('"') == tail:
            return node_id
    return None


def signal_paths(
    kg: dict[str, Any] | Any,
    source: str,
    target: str,
    *,
    max_hops: int = 8,
    max_paths: int = 3,
) -> dict[str, Any]:
    """Trace signal influence paths between two KG nodes (tag or block).

    Walks the Block/Tag sub-graph in both directions along READS / WRITES /
    CALLS / INSTANCE_OF edges — a path like
    ``Tag::Door_Closed <- Block::SafetyFB <- Block::Main -> Block::MotorCtrl -> Tag::Motor_Enable``
    answers "what chain connects this sensor to that actuator". Deterministic,
    bounded (hop + result caps), evidence-only.
    """
    graph = normalize_kg(kg)
    src = resolve_kg_node(graph, source)
    dst = resolve_kg_node(graph, target)
    missing = []
    if src is None:
        missing.append(source)
    if dst is None:
        missing.append(target)
    if missing:
        raise ValueError(f"KG node not found: {', '.join(str(m) for m in missing)}")
    assert src is not None and dst is not None
    if src == dst:
        raise ValueError("signal_path source and target are the same node")

    adjacency: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for edge in graph["edges"]:
        s, t = str(edge.get("source") or ""), str(edge.get("target") or "")
        if not s or not t or s == t:
            continue
        if not (s.startswith("Block::") or s.startswith("Tag::")):
            continue
        if not (t.startswith("Block::") or t.startswith("Tag::")):
            continue
        adjacency[s].append((t, edge))
        adjacency[t].append((s, edge))
    for entries in adjacency.values():
        entries.sort(key=lambda item: (item[0], str(item[1].get("type") or "")))

    steps_taken = {"budget": 20000}
    found: list[list[tuple[str, dict]]] = []

    def _record(chain: list[tuple[str, dict]]) -> None:
        found.append(list(chain))

    def _dfs(node: str, chain: list[tuple[str, dict]], visited: set[str]) -> None:
        if len(found) >= max_paths or steps_taken["budget"] <= 0:
            return
        steps_taken["budget"] -= 1
        if node == dst:
            _record(chain)
            return
        if len(chain) >= max_hops:
            return
        for nxt, edge in adjacency.get(node, []):
            if nxt in visited:
                continue
            _dfs(nxt, chain + [(nxt, edge)], visited | {nxt})

    _dfs(src, [], {src})
    found.sort(key=len)

    paths: list[dict[str, Any]] = []
    for chain in found[:max_paths]:
        paths.append(
            {
                "hops": len(chain),
                "nodes": [_node_label(node) for node, _edge in [(src, {})] + chain],
                "node_ids": [src] + [node for node, _edge in chain],
                "edges": [edge for _node, edge in chain],
                "sequence": " -> ".join(
                    [f"{src.split('::', 1)[0]}:{_node_label(src)}"]
                    + [
                        f"-[{edge.get('type')}]-> {node.split('::', 1)[0]}:{_node_label(node)}"
                        for node, edge in chain
                    ]
                ),
            }
        )
    return {
        "source": src,
        "target": dst,
        "paths": paths,
        "truncated": steps_taken["budget"] <= 0,
    }


def query(kg: dict[str, Any] | Any, op: str, **params: Any) -> dict[str, Any]:
    """Run a supported KG query and include only source-edge evidence."""
    graph = normalize_kg(kg)
    if op == "callers":
        block = str(params.get("block_name") or "")
        result = callers_of(graph, block)
        evidence = [e for e in graph["edges"] if e.get("type") == "CALLS" and e.get("target") == block_id(block)]
    elif op == "callees":
        block = str(params.get("block_name") or "")
        result = callees_of(graph, block)
        evidence = [e for e in graph["edges"] if e.get("type") == "CALLS" and e.get("source") == block_id(block)]
    elif op in {"writers", "readers"}:
        tag = str(params.get("tag") or "")
        access_type = "WRITES" if op == "writers" else "READS"
        result = _blocks_for_tag(graph, tag, access_type)
        evidence = _access_evidence(graph, tag, (access_type,))
    elif op == "reachable":
        roots = params.get("roots")
        result = sorted(reachable_from(graph, roots=roots))
        evidence = [e for e in graph["edges"] if e.get("type") in ("CALLS", "INSTANCE_OF")]
    elif op == "dead_blocks":
        result = dead_blocks(graph)
        evidence = [e for e in graph["edges"] if e.get("type") == "CALLS"]
    elif op == "depends":
        source = str(params.get("block_name") or "")
        target = str(params.get("target_block") or "")
        dependency = depends_between(graph, source, target)
        result = dependency
        evidence = dependency["evidence"]
    elif op == "neighbors":
        block = block_id(str(params.get("block_name") or ""))
        result = sorted(
            {
                _block_name(str(e["target"] if e.get("source") == block else e["source"]))
                for e in graph["edges"]
                if e.get("source") == block or e.get("target") == block
            }
        )
        evidence = [e for e in graph["edges"] if e.get("source") == block or e.get("target") == block]
    elif op in {"typed_as", "nested_fb"}:
        block = str(params.get("block_name") or "")
        result = {
            "members": typed_as_of(graph, block),
            "children": typed_as_callees(graph, block),
            "nest_depth": nest_depth(graph, block),
            "chains": typed_as_chains(graph, block),
        }
        bid = block_id(block)
        evidence = [
            e
            for e in graph["edges"]
            if e.get("type") == TYPED_AS
            and (
                e.get("source") == bid
                or str(e.get("source") or "").startswith(f"Variable::{block}::")
            )
        ]
    elif op == "signal_path":
        source = str(params.get("source") or params.get("from") or params.get("tag") or "")
        target = str(params.get("target") or params.get("to") or "")
        try:
            max_hops = min(12, max(1, int(params.get("max_hops") or 8)))
            max_paths = min(5, max(1, int(params.get("max_paths") or 3)))
        except (TypeError, ValueError):
            max_hops, max_paths = 8, 3
        result = signal_paths(graph, source, target, max_hops=max_hops, max_paths=max_paths)
        evidence = [edge for path in result["paths"] for edge in path["edges"]]
    else:
        raise ValueError(f"Unsupported graph query op: {op}")
    return {"op": op, "result": result, "evidence": evidence}
