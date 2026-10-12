"""Extract / merge conversation knowledge nodes for the canvas."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any
from uuid import uuid4

_SENT_SPLIT = re.compile(r"[。！？.!?\n]+")
_WORDY = re.compile(r"[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\-_/]{1,40}")


def _nid(prefix: str, key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _place(index: int, total: int = 8) -> tuple[float, float]:
    """Spacious grid fallback (star layout is applied on the frontend)."""
    cols = 5
    row, col = divmod(max(0, index), cols)
    return 120.0 + col * 200.0, 100.0 + row * 130.0


def _place_star(index: int, total: int, *, ring: int = 1) -> tuple[float, float]:
    """Rough star seed so first paint is not a grid before frontend reflow."""
    cx, cy = 520.0, 420.0
    n = max(total, 1)
    radius = 160.0 + ring * 140.0 + max(0, n - 12) * 4.0
    angle = -math.pi / 2 + (2 * math.pi * index) / n
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def nodes_from_text(
    *,
    text: str,
    role: str,
    turn_id: str,
    task_id: str,
    source_type: str = "dialogue",
    start_index: int = 0,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Refine a turn into a few knowledge points (labels + source quote)."""
    chunks = [c.strip() for c in _SENT_SPLIT.split(text or "") if c.strip()]
    nodes: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks[:limit]):
        label_match = _WORDY.findall(chunk)
        label = "".join(label_match[:4]) if label_match else chunk[:18]
        label = label[:24] or f"要点{i + 1}"
        x, y = _place(start_index + i)
        nodes.append(
            {
                "id": _nid("kn", f"{turn_id}:{i}:{label}"),
                "label": label,
                "summary": chunk[:280],
                "kind": "insight" if role == "assistant" else "question",
                "x": x,
                "y": y,
                "source": {
                    "type": source_type,
                    "role": role,
                    "quote": chunk[:400],
                    "task_id": task_id,
                    "turn_id": turn_id,
                },
            }
        )
    return nodes


def empty_canvas() -> dict[str, Any]:
    return {"nodes": [], "edges": []}


def strip_job_plc_nodes(canvas: dict[str, Any] | None, *, job_id: str | None = None) -> dict[str, Any]:
    """Remove prior PLC-derived nodes/edges so a fresh job graph can replace them."""
    canvas = canvas or empty_canvas()
    keep_nodes: list[dict[str, Any]] = []
    removed: set[str] = set()
    for n in canvas.get("nodes") or []:
        kind = str(n.get("kind") or "")
        src = n.get("source") or {}
        is_plc = kind.startswith("plc_") or src.get("type") == "plc"
        other_job = bool(job_id and src.get("plc_job_id") and src.get("plc_job_id") != job_id)
        if is_plc and not other_job:
            removed.add(str(n["id"]))
            continue
        keep_nodes.append(n)
    keep_ids = {str(n["id"]) for n in keep_nodes}
    edges = [
        e
        for e in (canvas.get("edges") or [])
        if e.get("source") in keep_ids
        and e.get("target") in keep_ids
        and e.get("source") not in removed
        and e.get("target") not in removed
    ]
    return {"nodes": keep_nodes, "edges": edges}


def strip_dialogue_nodes(canvas: dict[str, Any] | None) -> dict[str, Any]:
    """Drop chat insight/question nodes — PLC galaxy stays block/dependency only."""
    canvas = canvas or empty_canvas()
    keep_nodes: list[dict[str, Any]] = []
    removed: set[str] = set()
    for n in canvas.get("nodes") or []:
        kind = str(n.get("kind") or "")
        src = n.get("source") or {}
        is_dialogue = kind in {"insight", "question"} or src.get("type") == "dialogue"
        if is_dialogue:
            removed.add(str(n["id"]))
            continue
        keep_nodes.append(n)
    keep_ids = {str(n["id"]) for n in keep_nodes}
    edges = [
        e
        for e in (canvas.get("edges") or [])
        if e.get("source") in keep_ids and e.get("target") in keep_ids
    ]
    return {"nodes": keep_nodes, "edges": edges}


def nodes_from_plc_job(job: dict[str, Any], *, task_id: str, turn_id: str) -> list[dict[str, Any]]:
    """Build canvas nodes from PLC job blocks + project (knowledge / logic seeds)."""
    nodes: list[dict[str, Any]] = []
    job_id = job.get("id")
    project = str(job.get("project_name") or job_id or "PLC")
    blocks = list(job.get("blocks") or [])
    cx, cy = 520.0, 420.0
    nodes.append(
        {
            "id": _nid("plc", f"{job_id}:project"),
            "label": project[:28],
            "summary": f"PLC 工程 · 块数 {len(blocks)}",
            "kind": "plc_project",
            "x": cx,
            "y": cy,
            "source": {
                "type": "plc",
                "quote": project,
                "project": project,
                "path": job.get("source_path") or job.get("project_path"),
                "task_id": task_id,
                "turn_id": turn_id,
                "plc_job_id": job_id,
            },
        }
    )

    def _ring_for(btype: str) -> int:
        t = (btype or "").upper()
        if t == "OB":
            return 0
        if t == "DB":
            return 2
        return 1

    def _kind_for(btype: str, instance_of: str = "") -> str:
        t = (btype or "").upper()
        if t == "OB":
            return "plc_ob"
        if t == "UDT":
            return "plc_udt"
        if t == "DB":
            return "plc_instance" if instance_of else "plc_db"
        return "plc_block"

    by_ring: dict[int, list[dict[str, Any]]] = {0: [], 1: [], 2: []}
    for block in blocks[:120]:
        by_ring[_ring_for(str(block.get("type") or ""))].append(block)

    for ring, ring_blocks in by_ring.items():
        total = len(ring_blocks)
        for i, block in enumerate(ring_blocks):
            name = str(block.get("name") or f"Block{i}")
            btype = str(block.get("type") or "Block")
            comment = str(block.get("comment") or "")
            inst = str(block.get("instance_of") or "").strip()
            nets = block.get("networks")
            lang = str(block.get("language") or "")
            statics = block.get("statics") or []
            bits = [btype]
            if lang:
                bits.append(lang)
            if nets is not None:
                bits.append(f"{nets} 网络")
            if inst:
                bits.append(f"实例←{inst}")
            if statics:
                bits.append(f"静态 {len(statics)}")
            summary = comment or " · ".join(bits)
            x, y = _place_star(i, total, ring=ring)
            nodes.append(
                {
                    "id": _nid("plc", f"{job_id}:{name}"),
                    "label": name,
                    "summary": summary[:280],
                    "kind": _kind_for(btype, inst),
                    "x": x,
                    "y": y,
                    "source": {
                        "type": "plc",
                        "quote": comment or name,
                        "block_name": name,
                        "block_type": btype,
                        "instance_of": inst or None,
                        "entity_kind": "instance" if inst else "block",
                        "project": project,
                        "path": job.get("source_path") or job.get("project_path"),
                        "task_id": task_id,
                        "turn_id": turn_id,
                        "plc_job_id": job_id,
                    },
                }
            )

    # Tag tables from logic/knowledge graph if present
    tag_nodes = [
        n
        for n in (job.get("logic_graph") or {}).get("nodes") or []
        if n.get("type") == "TagTable"
    ]
    if not tag_nodes:
        tag_nodes = [
            n
            for n in (job.get("knowledge_graph") or {}).get("nodes") or []
            if n.get("type") == "TagTable"
        ]
    tag_counts: dict[str, int] = {}
    for e in (job.get("knowledge_graph") or {}).get("edges") or []:
        if str(e.get("type") or "") != "CONTAINS":
            continue
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if src.startswith("TagTable::") and tgt.startswith("Tag::"):
            tname = src.split("::", 1)[-1]
            tag_counts[tname] = tag_counts.get(tname, 0) + 1
    for i, n in enumerate(tag_nodes[:16]):
        props = n.get("props") or {}
        name = str(props.get("name") or n.get("label") or n.get("id") or "Tags")
        x, y = _place_star(i, max(len(tag_nodes), 1), ring=3)
        count = tag_counts.get(name, 0)
        nodes.append(
            {
                "id": _nid("plc", f"{job_id}:tag:{name}"),
                "label": name,
                "summary": (
                    f"标签表 · {count} 个 Tag（点程序块查看 IO 子图）"
                    if count
                    else "标签表（点程序块查看 IO 子图）"
                ),
                "kind": "plc_tag",
                "x": x,
                "y": y,
                "source": {
                    "type": "plc",
                    "quote": name,
                    "project": project,
                    "task_id": task_id,
                    "turn_id": turn_id,
                    "plc_job_id": job_id,
                },
            }
        )

    # KG-only blocks (multi-instance / external DBs referenced by USES but not listed)
    known_names = {str(b.get("name") or "") for b in blocks}
    known_names |= {str(n.get("label") or "") for n in nodes}
    extra_blocks = [
        n
        for n in (job.get("knowledge_graph") or {}).get("nodes") or []
        if n.get("type") == "Block"
    ]
    extra_i = 0
    for n in extra_blocks:
        props = n.get("props") or {}
        name = str(props.get("name") or n.get("id", "").split("::")[-1] or "")
        if not name or name in known_names:
            continue
        btype = str(props.get("block_type") or "DB")
        external = bool(props.get("external"))
        x, y = _place_star(extra_i, max(len(extra_blocks), 1), ring=2)
        extra_i += 1
        known_names.add(name)
        nodes.append(
            {
                "id": _nid("plc", f"{job_id}:{name}"),
                "label": name,
                "summary": (
                    f"{btype} · 多实例/外部引用（图谱）"
                    if external
                    else f"{btype} · 由依赖引用补全"
                ),
                "kind": "plc_instance" if external else _kind_for(btype),
                "x": x,
                "y": y,
                "source": {
                    "type": "plc",
                    "quote": name,
                    "block_name": name,
                    "block_type": btype,
                    "entity_kind": "instance" if external else "block",
                    "instance_of": (
                        str(props.get("instance_of") or props.get("InstanceOfName") or "").strip()
                        or None
                    ),
                    "project": project,
                    "task_id": task_id,
                    "turn_id": turn_id,
                    "plc_job_id": job_id,
                },
            }
        )
    return nodes


def _plc_id_map(plc_nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Map logic-graph ids / labels → canvas node ids."""
    m: dict[str, str] = {}
    for n in plc_nodes:
        nid = str(n["id"])
        label = str(n.get("label") or "")
        m[nid] = nid
        if label:
            m[label] = nid
            m[f"Block::{label}"] = nid
            m[f"TagTable::{label}"] = nid
            m[f"Project::{label}"] = nid
        src = n.get("source") or {}
        bname = src.get("block_name")
        if bname:
            m[str(bname)] = nid
            m[f"Block::{bname}"] = nid
        if n.get("kind") == "plc_project":
            m["__project__"] = nid
    return m


def edges_from_plc_logic(job: dict[str, Any], plc_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canvas edges for **知识图谱**: implementation & inter-block dependencies.

    Includes CALLS / USES / INSTANCE_OF / DEPENDS_ON from the full knowledge_graph.
    Scan-cycle-only edges stay on ``logic_graph`` for the left pane.
    """
    from agents.plc.tia.graph_query import derive_depends_on_edges

    id_map = _plc_id_map(plc_nodes)
    kg = job.get("knowledge_graph") or {}
    if not isinstance(kg, dict):
        kg = {}

    wanted = {"CALLS", "USES", "INSTANCE_OF", "DEPENDS_ON"}
    raw: list[dict[str, Any]] = []
    for e in kg.get("edges") or []:
        et = str(e.get("type") or "")
        if et not in wanted:
            continue
        raw.append(e)

    strong_pairs = {
        (str(e.get("source")), str(e.get("target")))
        for e in raw
        if str(e.get("type") or "") in {"CALLS", "USES", "INSTANCE_OF"}
    }
    for edge in derive_depends_on_edges(kg, max_edges=160):
        pair = (str(edge.get("source")), str(edge.get("target")))
        if pair in strong_pairs:
            continue
        raw.append(edge)

    # Prefer structural edges first, then deps by weight
    rank = {"CALLS": 0, "USES": 1, "INSTANCE_OF": 2, "DEPENDS_ON": 3}
    raw.sort(
        key=lambda e: (
            rank.get(str(e.get("type") or ""), 9),
            -int(e.get("weight") or 1),
        )
    )

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for e in raw:
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        et = str(e.get("type") or "DEPENDS_ON")
        sid = id_map.get(src) or id_map.get(src.split("::")[-1] if "::" in src else src)
        tid = id_map.get(tgt) or id_map.get(tgt.split("::")[-1] if "::" in tgt else tgt)
        if not sid or not tid or sid == tid or (sid, tid, et) in seen:
            continue
        seen.add((sid, tid, et))
        edges.append(
            {
                "id": f"e_{uuid4().hex[:8]}",
                "source": sid,
                "target": tid,
                "label": et,
                "user_created": False,
            }
        )
        if len(edges) >= 180:
            break
    return edges


def merge_canvas(
    existing: dict[str, Any] | None,
    *,
    new_nodes: list[dict[str, Any]],
    new_edges: list[dict[str, Any]] | None = None,
    user_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    canvas = existing or empty_canvas()
    by_id = {n["id"]: n for n in canvas.get("nodes") or []}
    for n in new_nodes:
        prev = by_id.get(n["id"])
        if prev:
            # keep user position if already dragged
            n = {**n, "x": prev.get("x", n["x"]), "y": prev.get("y", n["y"])}
        by_id[n["id"]] = n
    edge_list = list(canvas.get("edges") or [])
    seen = {(e.get("source"), e.get("target"), e.get("label")) for e in edge_list}
    for e in (new_edges or []) + (user_edges or []):
        key = (e.get("source"), e.get("target"), e.get("label"))
        if key in seen:
            continue
        seen.add(key)
        edge_list.append(e)
    return {"nodes": list(by_id.values()), "edges": edge_list}


def find_node(canvas: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not canvas:
        return None
    for n in canvas.get("nodes") or []:
        if n.get("id") == node_id:
            return n
    return None


def find_node_by_block_name(canvas: dict[str, Any] | None, block_name: str) -> dict[str, Any] | None:
    """Locate a plc_block node when frontend/server canvas ids diverge."""
    if not canvas or not block_name:
        return None
    want = block_name.strip().lower()
    fallback: dict[str, Any] | None = None
    for n in canvas.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        src = n.get("source") if isinstance(n.get("source"), dict) else {}
        names = [str(src.get("block_name") or ""), str(n.get("label") or "")]
        if not any(c.lower() == want for c in names if c):
            continue
        if n.get("kind") == "plc_block" or src.get("block_name"):
            return n
        fallback = fallback or n
    return fallback


def apply_node_positions(canvas: dict[str, Any] | None, positions: list[dict[str, Any]] | None) -> dict[str, Any]:
    canvas = canvas or empty_canvas()
    if not positions:
        return canvas
    by_id = {n["id"]: dict(n) for n in canvas.get("nodes") or []}
    for p in positions:
        nid = str(p.get("id") or "")
        if nid in by_id and "x" in p and "y" in p:
            by_id[nid]["x"] = float(p["x"])
            by_id[nid]["y"] = float(p["y"])
    return {"nodes": list(by_id.values()), "edges": list(canvas.get("edges") or [])}
