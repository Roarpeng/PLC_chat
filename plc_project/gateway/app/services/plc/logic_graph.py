"""Scan-cycle logic-graph shaping for PLC jobs."""

from __future__ import annotations

import re
from typing import Any


def _is_ob_props(props: dict[str, Any], label: str = "") -> bool:
    bt = str(props.get("block_type") or props.get("type") or "").upper()
    name = label or str(props.get("name") or "")
    if bt == "OB":
        return True
    if re.match(r"^OB\d", name, re.I):
        return True
    if re.match(r"^(Startup|System|Pull|Rack|Main)\b", name, re.I):
        return True
    return False


def _logic_graph_from_kg(
    kg: dict[str, Any],
    *,
    max_dep_edges: int = 160,
) -> dict[str, Any]:
    """Build **逻辑图** (scan-cycle) from KG.

    Engineer view: which blocks Main/OB invokes each cycle — ordered CALLS + NEXT.
    Does **not** include internal implementation deps (nested CALLS, USES, INSTANCE_OF,
    DEPENDS_ON); those belong on the knowledge canvas via ``edges_from_plc_logic``.
    """
    del max_dep_edges  # kept for call-site compatibility; deps live on knowledge canvas
    blocks: list[dict[str, Any]] = []
    for n in kg.get("nodes") or []:
        if n.get("type") != "Block":
            continue
        props = n.get("props") or {}
        blocks.append(
            {
                "id": n["id"],
                "label": props.get("name") or n["id"].split("::")[-1],
                "type": "Block",
                "props": props,
            }
        )
    by_id = {b["id"]: b for b in blocks}
    ob_ids = {
        b["id"]
        for b in blocks
        if _is_ob_props(b.get("props") or {}, str(b.get("label") or ""))
    }

    # OB → callee CALLS only (top-level scan cycle)
    calls: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for e in kg.get("edges") or []:
        if str(e.get("type") or "") != "CALLS":
            continue
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if src not in ob_ids or tgt not in by_id or src == tgt:
            continue
        src_safe = bool((by_id.get(src) or {}).get("props", {}).get("safety"))
        tgt_safe = bool((by_id.get(tgt) or {}).get("props", {}).get("safety"))
        if src_safe != tgt_safe:
            # F-blocks are first-class and never mixed into standard scan logic
            continue
        key = (src, tgt, "CALLS")
        if key in seen:
            continue
        seen.add(key)
        props = e.get("props") if isinstance(e.get("props"), dict) else {}
        item: dict[str, Any] = {"source": src, "target": tgt, "type": "CALLS", "weight": 1}
        if "seq" in props:
            item["seq"] = props["seq"]
        elif "seq" in e:
            item["seq"] = e["seq"]
        if props.get("evidence"):
            item["evidence"] = props["evidence"]
        calls.append(item)

    # NEXT between successive OB callees (prefer KG NEXT; else synthesize by seq)
    callee_seq: dict[str, list[tuple[int, str]]] = {oid: [] for oid in ob_ids}
    for c in calls:
        seq = int(c.get("seq") or 999)
        callee_seq.setdefault(c["source"], []).append((seq, c["target"]))
    for oid, lst in callee_seq.items():
        lst.sort(key=lambda x: (x[0], x[1]))

    next_edges: list[dict[str, Any]] = []
    kg_next = {
        (str(e.get("source")), str(e.get("target")))
        for e in (kg.get("edges") or [])
        if str(e.get("type") or "") == "NEXT"
    }
    for oid, lst in callee_seq.items():
        uniq: list[str] = []
        for _, tid in lst:
            if tid not in uniq:
                uniq.append(tid)
        for i in range(len(uniq) - 1):
            a, b = uniq[i], uniq[i + 1]
            key = (a, b, "NEXT")
            if key in seen:
                continue
            seen.add(key)
            next_edges.append(
                {
                    "source": a,
                    "target": b,
                    "type": "NEXT",
                    "weight": 1,
                    "seq": i + 1,
                    "evidence": "kg_next" if (a, b) in kg_next else "scan_cycle_order",
                }
            )

    keep_ids = set(ob_ids)
    for c in calls:
        keep_ids.add(c["source"])
        keep_ids.add(c["target"])
    # Always keep OBs even with no calls (show Main alone)
    nodes = [b for b in blocks if b["id"] in keep_ids]
    return {"nodes": nodes, "edges": calls + next_edges}


def refresh_logic_graph(job: dict[str, Any]) -> dict[str, Any]:
    """Recompute logic_graph from knowledge_graph (XML-derived edges only)."""
    kg = job.get("knowledge_graph")
    if isinstance(kg, dict) and (kg.get("nodes") or kg.get("edges")):
        # Optional: re-scan source XMLs + LLM validate CallInfo evidence
        xmls = []
        for p in job.get("source_xmls") or []:
            if isinstance(p, str):
                xmls.append(p)
        export_dir = job.get("openness_export_dir") or ""
        if export_dir:
            from pathlib import Path as _P

            root = _P(str(export_dir))
            if root.is_dir():
                xmls.extend(str(p) for p in root.rglob("*.xml"))
        if xmls:
            known = {
                str(b.get("name"))
                for b in (job.get("blocks") or [])
                if isinstance(b, dict) and b.get("name")
            }
            # Deterministic CallInfo always; LLM only if LiteLLM configured
            import os

            use_llm = bool(os.getenv("LITELLM_BASE_URL"))
            from agents.plc.tia.xml_understand import enrich_kg_calls_from_xml_files

            kg = enrich_kg_calls_from_xml_files(
                kg,
                xml_paths=xmls[:200],
                known_blocks=known,
                use_llm=use_llm,
            )
            job["knowledge_graph"] = kg
        job["logic_graph"] = _logic_graph_from_kg(kg)
    return job
