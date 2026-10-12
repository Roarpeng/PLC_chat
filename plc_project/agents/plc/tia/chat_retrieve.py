"""Query-driven PLC chat: understand question → retrieve KG → answer (optional LLM)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

logger = logging.getLogger("researchos.plc.chat_retrieve")

# Lightweight bilingual cues for retrieval (not fixed answer templates)
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "水平": ("hor", "horizontal", "hordrill", "水平钻", "水平打"),
    "垂直": ("vertical", "down", "up", "垂直"),
    "向下": ("down", "downdrill", "向下", "下钻"),
    "向上": ("up", "updrill", "向上", "上钻"),
    "冷却": ("cooling", "fan", "cool", "风扇"),
    "机器人": ("robot", "kuka", "机器人"),
    "视觉": ("visual", "chisel", "vision", "camera", "凿削", "ros"),
    "阀": ("valve", "阀"),
    "模式": ("sysmode", "mode", "模式"),
    "自动": ("autostep", "auto", "自动"),
    "架构": ("ob1", "main", "调用", "扫描", "architecture"),
    "整体": ("ob1", "project", "工程", "项目"),
    "通信": ("modbus", "communication", "pc", "通信"),
    "安全": ("safety", "door", "安全门", "failsafe", "f-fb", "f-fc"),
    "线圈": ("coil", "write", "writes", "写入", "置位", "复位"),
    "写入": ("writes", "coil", "writer", "写"),
    "调用": ("calls", "call", "fb", "fc"),
    "互锁": ("interlock", "interlocked", "互锁", "stop", "estop"),
}


def _tokens(text: str) -> list[str]:
    raw = (text or "").strip().lower()
    if not raw:
        return []
    parts = re.findall(r"[a-z][a-z0-9_]*|[0-9]+|[\u4e00-\u9fff]{1,8}", raw)
    out: list[str] = []
    for p in parts:
        if len(p) == 1 and "\u4e00" <= p <= "\u9fff":
            continue
        out.append(p)
        for key, syns in _SYNONYMS.items():
            if key in p or p in key or p in syns:
                out.extend(syns)
                out.append(key)
    # de-dupe keep order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _block_meta(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }


def _network_titles(job: dict[str, Any], name: str) -> list[str]:
    titles: list[str] = []
    folded = job.get("folded_logic") or {}
    nets = folded.get(name) if isinstance(folded, dict) else None
    if isinstance(nets, list):
        for net in nets:
            if isinstance(net, dict):
                t = str(net.get("title") or "").strip().strip('"')
                if t:
                    titles.append(t)
    scl = str((job.get("scl_sources") or {}).get(name) or "")
    for line in scl.splitlines():
        s = line.strip()
        if s.upper().startswith("// NETWORK") and ":" in s:
            titles.append(s.split(":", 1)[1].strip())
    return titles


def _calls_map(job: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for e in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(e, dict) or e.get("type") != "CALLS":
            continue
        s = str(e.get("source") or "").split("::")[-1]
        t = str(e.get("target") or "").split("::")[-1]
        if s and t:
            out[s].append(t)
    # prefer logic_graph order when present
    for e in (job.get("logic_graph") or {}).get("edges") or []:
        if not isinstance(e, dict) or e.get("type") != "CALLS":
            continue
        s = str(e.get("source") or "").split("::")[-1]
        t = str(e.get("target") or "").split("::")[-1]
        if s and t and t not in out[s]:
            out[s].append(t)
    return out


def retrieve_kg_for_query(
    job: dict[str, Any],
    query: str,
    *,
    focus_block: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Score blocks/networks against the user question and expand 1-hop CALLS."""
    tokens = _tokens(query)
    blocks = _block_meta(job)
    scores: dict[str, float] = defaultdict(float)
    title_hits: dict[str, list[str]] = defaultdict(list)

    if focus_block and focus_block in blocks:
        scores[focus_block] += 100.0

    for name, meta in blocks.items():
        blob = " ".join(
            [
                name,
                str(meta.get("comment") or ""),
                str(meta.get("type") or ""),
                " ".join(_network_titles(job, name)[:30]),
            ]
        ).lower()
        for tok in tokens:
            tl = tok.lower()
            if not tl:
                continue
            if tl in name.lower():
                scores[name] += 12.0
            elif tl in blob:
                scores[name] += 4.0
            # title-specific
            for title in _network_titles(job, name):
                if tl in title.lower():
                    scores[name] += 6.0
                    if title not in title_hits[name]:
                        title_hits[name].append(title)

    # Tag READS/WRITES — "who writes this coil" must hit KG edges, never invent CALLs
    qlow = (query or "").lower()
    for edge in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        et = str(edge.get("type") or "")
        if et not in {"READS", "WRITES", "CALLS", "USES"}:
            continue
        src = str(edge.get("source") or "").split("::")[-1]
        tgt = str(edge.get("target") or "").split("::")[-1]
        blob = f"{src} {tgt} {et}".lower()
        for tok in tokens:
            tl = tok.lower()
            if tl and tl in blob:
                if src:
                    scores[src] += 10.0 if et in {"WRITES", "CALLS"} else 6.0
                    label = f"{et} {tgt}"
                    if label not in title_hits[src]:
                        title_hits[src].append(label)
                if et == "CALLS" and tgt and tgt in blocks:
                    scores[tgt] += 4.0
        if any(k in qlow for k in ("write", "coil", "写入", "线圈", "who writes")) and et == "WRITES":
            if tokens and any(t.lower() in tgt.lower() for t in tokens if len(t) > 1):
                scores[src] += 8.0

    # Always seed OB1/Main lightly for structural questions
    if any(k in (query or "") for k in ("整体", "架构", "工程", "项目", "图谱")) or "architect" in qlow:
        for name, meta in blocks.items():
            if str(meta.get("type") or "").upper() == "OB":
                scores[name] += 8.0

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [n for n, sc in ranked if sc > 0][:limit]
    if not top and focus_block:
        top = [focus_block]

    calls = _calls_map(job)
    callers: dict[str, list[str]] = defaultdict(list)
    for src, dsts in calls.items():
        for d in dsts:
            callers[d].append(src)

    hits: list[dict[str, Any]] = []
    for name in top:
        meta = blocks.get(name) or {"name": name}
        kids = list(dict.fromkeys(calls.get(name) or []))[:10]
        parents = list(dict.fromkeys(callers.get(name) or []))[:8]
        titles = title_hits.get(name) or _network_titles(job, name)[:12]
        # keep titles that touch query tokens first
        if tokens:
            titles = sorted(
                titles,
                key=lambda t: -sum(1 for tok in tokens if tok.lower() in t.lower()),
            )
        hits.append(
            {
                "name": name,
                "type": str(meta.get("type") or ""),
                "number": meta.get("number"),
                "networks": meta.get("networks"),
                "comment": str(meta.get("comment") or "").strip()[:160],
                "score": scores.get(name, 0),
                "titles": titles[:12],
                "calls": kids,
                "called_by": parents,
                "is_safety": bool(meta.get("is_safety") or meta.get("safety")),
            }
        )

    retrieval = {
        "query": query,
        "tokens": tokens[:24],
        "hits": hits,
        "project": job.get("project_name") or "",
        "summary": job.get("summary") or {},
    }
    retrieval["citations"] = citations_for_retrieval(job, retrieval)
    return retrieval


def _edge_network(edge: dict[str, Any]) -> str:
    props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    raw = str(props.get("network") or edge.get("network") or "")
    return raw.split("::")[-1] if raw else ""


def _scl_snippet(job: dict[str, Any], block_name: str, *, needle: str = "") -> str:
    scl = str((job.get("scl_sources") or {}).get(block_name) or "")
    lines = [ln.strip() for ln in scl.splitlines() if ln.strip() and not ln.strip().startswith("//")]
    if needle:
        nlow = needle.lower()
        for ln in lines:
            if nlow in ln.lower() and not ln.startswith("(*"):
                return ln[:180]
    for ln in lines:
        if ":=" in ln or "=>" in ln or "(" in ln:
            return ln[:180]
    return ""


def citations_for_retrieval(job: dict[str, Any], retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    """KG edge + network/SCL snippet citations. Never invent CALLs."""
    names = {str(h.get("name")) for h in (retrieval.get("hits") or []) if h.get("name")}
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        et = str(edge.get("type") or "")
        if et not in {"CALLS", "USES", "WRITES", "READS"}:
            continue
        src = str(edge.get("source") or "").split("::")[-1]
        tgt = str(edge.get("target") or "").split("::")[-1]
        if src not in names and tgt not in names:
            continue
        key = (et, src, tgt)
        if key in seen:
            continue
        seen.add(key)
        props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
        network = _edge_network(edge)
        snippet = _scl_snippet(job, src, needle=tgt)
        citations.append(
            {
                "block": src,
                "network": network,
                "locator": network,
                "evidence": str(props.get("evidence") or et),
                "edge_type": et,
                "target": tgt,
                "snippet": snippet,
                "source_status": "exported" if snippet or network else "indexed",
            }
        )
        if len(citations) >= 24:
            break
    if not citations:
        for h in retrieval.get("hits") or []:
            name = str(h.get("name") or "")
            snippet = _scl_snippet(job, name)
            if name:
                citations.append(
                    {
                        "block": name,
                        "network": (h.get("titles") or [""])[0] if h.get("titles") else "",
                        "locator": (h.get("titles") or [""])[0] if h.get("titles") else "",
                        "evidence": "retrieval_hit",
                        "edge_type": "",
                        "target": "",
                        "snippet": snippet,
                        "source_status": "exported" if snippet else "indexed",
                    }
                )
    return citations[:24]


def _format_evidence_pack(retrieval: dict[str, Any]) -> str:
    lines = [
        f"工程：{retrieval.get('project') or '未命名'}",
        f"用户问题：{retrieval.get('query') or ''}",
        f"检索词：{', '.join(retrieval.get('tokens') or [])}",
        "检索到的相关块（按相关度）：",
    ]
    for h in retrieval.get("hits") or []:
        lines.append(
            f"- `{h['name']}` ({h.get('type')}"
            + (f" #{h.get('number')}" if h.get("number") is not None else "")
            + f", score={h.get('score'):.1f})"
        )
        if h.get("comment"):
            lines.append(f"  注释：{h['comment']}")
        if h.get("called_by"):
            lines.append("  被调用：" + ", ".join(f"`{x}`" for x in h["called_by"][:6]))
        if h.get("calls"):
            lines.append("  调用：" + ", ".join(f"`{x}`" for x in h["calls"][:8]))
        if h.get("titles"):
            lines.append("  网络标题：" + " | ".join(h["titles"][:10]))
    return "\n".join(lines)


def _deterministic_answer(retrieval: dict[str, Any], query: str) -> str:
    """Grounded answer from retrieval hits — shaped by the question, not a fixed template."""
    hits = retrieval.get("hits") or []
    if not hits:
        return (
            f"**未导出/未索引**：针对问题「{query}」，知识图谱中未检索到足够相关的块/网络，"
            "不能编造逻辑。\n可换关键词，或 `@块名` 指定单块。"
        )

    lines = [f"**问题：** {query}", "**图谱检索结论：**"]
    # Present each high-score hit as its own mini-section (question-driven, not one template)
    for h in hits[:5]:
        lines.append(
            f"### `{h['name']}`"
            + (f"（{h.get('type')}）" if h.get("type") else "")
            + (f" — {h['comment']}" if h.get("comment") else "")
        )
        if h.get("called_by") or h.get("calls"):
            rel = []
            if h.get("called_by"):
                rel.append("上游 " + "、".join(f"`{x}`" for x in h["called_by"][:5]))
            if h.get("calls"):
                rel.append("下游 " + "、".join(f"`{x}`" for x in h["calls"][:6]))
            lines.append("- 关系：" + "；".join(rel))
        if h.get("titles"):
            lines.append("- 相关网络/步序：")
            for t in h["titles"][:8]:
                lines.append(f"  - {t}")

    lines.append(
        f"_检索命中 {len(hits)} 个块（块名/注释/网络标题/CALLS/READS/WRITES）。"
        "已配置 PLC 对话模型时将用 LLM 基于上述证据作答；未配置则直接展示检索证据。"
        "可用 `@块名` 继续下钻。_"
    )
    citations = retrieval.get("citations") or []
    if citations:
        lines.append("")
        lines.append("**证据：**")
        for c in citations[:8]:
            bits = [f"`{c.get('block')}`"]
            if c.get("network"):
                bits.append(str(c["network"]))
            if c.get("edge_type"):
                bits.append(str(c["edge_type"]))
            if c.get("target"):
                bits.append(f"→ `{c['target']}`")
            if c.get("snippet"):
                bits.append(f"`{c['snippet']}`")
            lines.append("- " + " · ".join(bits))
    return "\n".join(lines)


def _try_llm_answer(retrieval: dict[str, Any], query: str, history: list[dict[str, str]] | None) -> str | None:
    """Use PLC-bound chat slot when configured; evidence-gated prompt."""
    import os

    if os.getenv("RESEARCHOS_DISABLE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    try:
        from gateway.app.services import llm_settings as llm
    except Exception as exc:  # noqa: BLE001
        logger.debug("llm settings unavailable: %s", exc)
        return None

    bindings = llm.load_agent_bindings()
    slot_id = bindings.plc
    configs = llm._load_slot_configs()  # noqa: SLF001 — shared slot store
    keys = llm._migrate_legacy_keys(llm._load_json(llm._keys_path()))  # noqa: SLF001
    key = (keys.get(slot_id) or "").strip()
    cfg = configs.get(slot_id) or {}
    model = str(cfg.get("model") or "").strip()
    base = str(cfg.get("base_url") or "").strip()
    if not base:
        return None
    # Allow localhost without key; otherwise require key
    if not key and "localhost" not in base and "127.0.0.1" not in base:
        return None

    evidence = _format_evidence_pack(retrieval)
    try:
        from agents.plc.tia.understanding import format_facts_for_llm

        facts = format_facts_for_llm(retrieval.get("_job") or {})
        if facts:
            evidence = facts + "\n\n" + evidence
    except Exception:  # noqa: BLE001
        pass
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是 ResearchOS PLC 助手。只能依据提供的「知识图谱检索证据」和「工程师已确认」回答。"
                "工程师是权威：已确认的角色/不要动/必须保留嵌套不得推翻。"
                "未确认的图谱线索只能写成待确认问题，不要说「程序就是 X」或「我已经理解了」。"
                "不要编造未出现的 CALLS/网络。用中文、针对问题作答，不要套固定工程概览模板。"
                "若证据不足，明确说不足并指出还应向工程师确认哪些块。"
            ),
        }
    ]
    for turn in list(history or [])[-6:]:
        role = turn.get("role") or "user"
        content = str(turn.get("content") or "").strip()
        if content and role in {"user", "assistant"}:
            messages.append({"role": role, "content": content[:2000]})
    messages.append(
        {
            "role": "user",
            "content": f"{evidence}\n\n请直接回答用户问题：{query}",
        }
    )

    try:
        # Reuse connectivity probe HTTP path (IPv4/DNS hardened)
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1200}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        urls = llm._chat_completion_urls(base)  # noqa: SLF001
        res = None
        for url in urls:
            res = llm._request_with_dns_retry("POST", url, headers=headers, json_body=payload)  # noqa: SLF001
            if getattr(res, "status_code", 500) != 404:
                break
        if res is None or getattr(res, "status_code", 500) >= 400:
            return None
        import json as _json

        data = _json.loads(res.text)
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
        if not content:
            return None
        return content
    except Exception as exc:  # noqa: BLE001
        logger.warning("PLC LLM answer failed: %s", exc)
        return None


def answer_query_with_kg(
    job: dict[str, Any],
    query: str,
    *,
    focus_block: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    """Understand dialogue context → retrieve KG → answer (LLM if configured else grounded)."""
    return answer_query_pack(
        job, query, focus_block=focus_block, chat_history=chat_history
    )["content"]


def answer_query_pack(
    job: dict[str, Any],
    query: str,
    *,
    focus_block: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Same as ``answer_query_with_kg`` plus structured citations for the API/UI."""
    hist_bits = []
    for turn in list(chat_history or [])[-4:]:
        if (turn.get("role") or "") == "user":
            hist_bits.append(str(turn.get("content") or ""))
    retrieval_query = " ".join(hist_bits + [query or ""]).strip() or (query or "")

    retrieval = retrieve_kg_for_query(job, retrieval_query, focus_block=focus_block)
    retrieval["_job"] = job
    citations = list(retrieval.get("citations") or [])
    llm_ans = _try_llm_answer(retrieval, query or retrieval_query, chat_history)
    if llm_ans:
        names = [h["name"] for h in (retrieval.get("hits") or [])[:5]]
        content = llm_ans.rstrip()
        if names:
            content += "\n\n_依据块：`" + "`、`".join(names) + "`_"
        return {"content": content, "citations": citations, "retrieval": retrieval}
    return {
        "content": _deterministic_answer(retrieval, query or retrieval_query),
        "citations": citations,
        "retrieval": retrieval,
    }
