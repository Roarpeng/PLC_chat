"""M3 citation contract for PLC node-chat / understand answers.

Every grounded answer must carry: block name + network/line locator + source snippet.
If the block/body is not exported or not indexed, say「未导出/未索引」and do not invent logic.
"""

from __future__ import annotations

from typing import Any

NOT_EXPORTED = "未导出/未索引"

EXPORT_STATUS_ENUM = (
    "converted",
    "parsed",
    "protected",
    "interface_only",
    "unknown",
    "not_exported",
    "not_indexed",
)

_GAP_STATUSES = frozenset(
    {"protected", "interface_only", "unknown", "not_exported", "not_indexed"}
)

_LOGIC_KEYS = (
    "逻辑",
    "运行",
    "做什么",
    "干什么",
    "干嘛",
    "作用",
    "理解",
    "解释",
    "分析",
    "调用",
    "怎么跑",
    "主循环",
    "scl",
    "网络",
    "步骤",
)


def resolve_export_status(block: dict[str, Any] | None, job: dict[str, Any] | None = None) -> str:
    """Consume M1 ``export_status`` when present; otherwise degrade from flags."""
    meta = block if isinstance(block, dict) else {}
    raw = str(meta.get("export_status") or meta.get("m1_export_status") or "").strip()
    if raw in EXPORT_STATUS_ENUM:
        return raw
    # Conversion-report style ``status`` (parsed/converted/...) — not job.status
    legacy = str(meta.get("status") or "").strip()
    if legacy in EXPORT_STATUS_ENUM:
        return legacy
    if meta.get("interface_only"):
        return "interface_only"
    if meta.get("protected") and meta.get("body_available") is False:
        return "protected"
    name = str(meta.get("name") or "")
    scl = ""
    if job and name:
        scl = str((job.get("scl_sources") or {}).get(name) or "")
    if meta.get("body_available") is False and not scl:
        return "not_exported"
    if scl and "TODO[" in scl:
        return "parsed"
    if scl:
        return "converted"
    if name and job and not _kg_has_block(job, name) and not (job.get("knowledge_graph") or {}).get("nodes"):
        return "unknown"
    if name and job and job.get("knowledge_graph") and not _kg_has_block(job, name):
        return "not_indexed"
    if int(meta.get("networks") or 0) == 0 and not scl:
        return "unknown"
    return "unknown"


def source_status_for_block(job: dict[str, Any], block_name: str) -> str:
    blocks = {
        str(b.get("name")): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }
    meta = blocks.get(block_name) or {}
    status = resolve_export_status(meta, job)
    if status in {"not_exported", "not_indexed", "protected", "interface_only", "unknown"}:
        if not _has_indexed_body(job, block_name):
            return NOT_EXPORTED
    if not block_name:
        return NOT_EXPORTED
    if block_name not in blocks and not _kg_has_block(job, block_name):
        return NOT_EXPORTED
    if not _has_indexed_body(job, block_name) and status in _GAP_STATUSES:
        return NOT_EXPORTED
    return "exported" if _has_indexed_body(job, block_name) else "indexed"


def _kg_has_block(job: dict[str, Any], name: str) -> bool:
    for node in (job.get("knowledge_graph") or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        nid = str(node.get("id") or "")
        if props.get("name") == name or nid.endswith(f"::{name}") or nid == name:
            return True
    return False


def _has_indexed_body(job: dict[str, Any], name: str) -> bool:
    if name and str((job.get("scl_sources") or {}).get(name) or "").strip():
        return True
    folded = job.get("folded_logic") or {}
    nets = folded.get(name) if isinstance(folded, dict) else None
    if isinstance(nets, list) and nets:
        return True
    blocks = {
        str(b.get("name")): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }
    meta = blocks.get(name) or {}
    if meta.get("body_available") is False or meta.get("interface_only"):
        return False
    return bool(int(meta.get("networks") or 0) > 0)


def is_not_exported_or_indexed(job: dict[str, Any], block_name: str | None) -> bool:
    if not block_name:
        return False
    return source_status_for_block(job, block_name) == NOT_EXPORTED


def asks_about_logic(message: str) -> bool:
    msg = (message or "").lower()
    return any(k in msg for k in _LOGIC_KEYS)


def normalize_citation(raw: dict[str, Any] | None) -> dict[str, Any]:
    c = raw if isinstance(raw, dict) else {}
    block = str(c.get("block") or "").strip()
    network = str(c.get("network") or "").strip()
    line = c.get("line")
    locator = str(c.get("locator") or "").strip()
    if not locator:
        if network and line is not None:
            locator = f"{network} / line {line}"
        elif network:
            locator = network
        elif line is not None:
            locator = f"line {line}"
    snippet = str(c.get("snippet") or "").strip()[:240]
    status = str(c.get("source_status") or "").strip() or (
        "exported" if snippet or locator else NOT_EXPORTED
    )
    return {
        "block": block,
        "network": network,
        "locator": locator,
        "line": line,
        "snippet": snippet,
        "source_status": status,
        "evidence": str(c.get("evidence") or ""),
        "edge_type": str(c.get("edge_type") or ""),
        "target": str(c.get("target") or ""),
        "nodeId": c.get("nodeId"),
    }


def normalize_citations(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        c = normalize_citation(raw)
        key = (c["block"], c["locator"], c["snippet"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= 24:
            break
    return out


def gap_citation(block_name: str, *, reason: str = "") -> dict[str, Any]:
    return normalize_citation(
        {
            "block": block_name,
            "locator": "",
            "snippet": "",
            "source_status": NOT_EXPORTED,
            "evidence": reason or NOT_EXPORTED,
        }
    )


def not_exported_reply(block_name: str, *, extra: str = "") -> str:
    head = f"**{NOT_EXPORTED}**：`{block_name or '（未指定块）'}` 没有可引用的程序体/索引，不能编造内部逻辑。"
    if extra:
        return f"{head}\n{extra}"
    return head


def _edge_locator(edge: dict[str, Any]) -> str:
    props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
    raw = str(props.get("network") or edge.get("network") or "")
    return raw.split("::")[-1] if raw else ""


def _scl_locator_and_snippet(
    job: dict[str, Any], block_name: str, *, needle: str = ""
) -> tuple[str, str, int | None]:
    scl = str((job.get("scl_sources") or {}).get(block_name) or "")
    if not scl:
        folded = job.get("folded_logic") or {}
        nets = folded.get(block_name) if isinstance(folded, dict) else None
        if isinstance(nets, list):
            for net in nets:
                if not isinstance(net, dict):
                    continue
                title = str(net.get("title") or "").strip().strip('"')
                stmts = net.get("statements") or []
                snippet = ""
                if isinstance(stmts, list) and stmts:
                    snippet = str(stmts[0])[:180]
                if title:
                    return title, snippet, None
        return "", "", None
    lines = scl.splitlines()
    nlow = needle.lower() if needle else ""
    for idx, raw in enumerate(lines, start=1):
        s = raw.strip()
        if not s or s.startswith("//") or s.startswith("(*"):
            continue
        if nlow and nlow in s.lower():
            return f"line {idx}", s[:180], idx
    for idx, raw in enumerate(lines, start=1):
        s = raw.strip()
        if ":=" in s or "=>" in s or "(" in s:
            return f"line {idx}", s[:180], idx
    return "", "", None


def citations_for_block(job: dict[str, Any], block_name: str) -> list[dict[str, Any]]:
    """Best-available citations for one block: KG edges then SCL/fold snippet."""
    if not block_name:
        return []
    status = source_status_for_block(job, block_name)
    cites: list[dict[str, Any]] = []
    for edge in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        et = str(edge.get("type") or "")
        if et not in {"CALLS", "USES", "WRITES", "READS"}:
            continue
        src = str(edge.get("source") or "").split("::")[-1]
        tgt = str(edge.get("target") or "").split("::")[-1]
        if src != block_name and tgt != block_name:
            continue
        locator = _edge_locator(edge)
        snippet_locator, snippet, line = _scl_locator_and_snippet(job, src, needle=tgt)
        cites.append(
            normalize_citation(
                {
                    "block": src,
                    "network": locator,
                    "locator": locator or snippet_locator,
                    "line": line,
                    "snippet": snippet,
                    "source_status": status if src == block_name else source_status_for_block(job, src),
                    "evidence": et,
                    "edge_type": et,
                    "target": tgt,
                }
            )
        )
        if len(cites) >= 12:
            break
    if not cites:
        locator, snippet, line = _scl_locator_and_snippet(job, block_name)
        if locator or snippet:
            cites.append(
                normalize_citation(
                    {
                        "block": block_name,
                        "locator": locator,
                        "line": line,
                        "snippet": snippet,
                        "source_status": status,
                        "evidence": "block_body",
                    }
                )
            )
        else:
            cites.append(gap_citation(block_name))
    return normalize_citations(cites)


def citations_for_answer(
    job: dict[str, Any],
    message: str,
    focus: str | None,
) -> list[dict[str, Any]]:
    existing = list(job.get("_last_citations") or [])
    if existing:
        return normalize_citations(existing)
    if focus:
        return citations_for_block(job, focus)
    try:
        from agents.plc.tia.chat_retrieve import retrieve_kg_for_query

        retrieval = retrieve_kg_for_query(job, message or "", focus_block=focus, limit=5)
        return normalize_citations(retrieval.get("citations") or [])
    except Exception:  # noqa: BLE001
        return []


def finalize_grounded_answer(
    job: dict[str, Any],
    message: str,
    block_name: str | None,
    content: str,
) -> str:
    """Attach citation contract after any PLC understand/node-chat path."""
    from gateway.app.services.plc.evidence.blocks import _resolve_block_focus

    focus = _resolve_block_focus(job, message, block_name) or (block_name or "").strip() or None
    cites = citations_for_answer(job, message, focus)
    text = content or ""

    if focus and is_not_exported_or_indexed(job, focus) and asks_about_logic(message):
        if NOT_EXPORTED not in text:
            extra = text.strip()
            # Keep interface/call facts, but label the body gap first.
            text = not_exported_reply(focus, extra=extra)
        gap = gap_citation(focus)
        if not cites:
            cites = [gap]
        else:
            for c in cites:
                if c.get("block") == focus and not c.get("snippet"):
                    c["source_status"] = NOT_EXPORTED
            if not any(
                c.get("block") == focus and c.get("source_status") == NOT_EXPORTED
                for c in cites
            ):
                cites = [gap, *cites]

    if asks_about_logic(message) and not cites:
        text = (
            f"**{NOT_EXPORTED}**：当前问题没有可引用的块名 / 网络或行 / 源片段，"
            "不能编造逻辑。可换关键词，或等程序体导出后再问。"
        )
        cites = [gap_citation(focus or "")]

    if cites and "**证据：**" not in text and not any(
        str(c.get("source_status")) == NOT_EXPORTED and not c.get("snippet") for c in cites[:1]
    ):
        # Keep card answers scannable; evidence chips carry structured cites.
        pass

    job["_last_citations"] = normalize_citations(cites)
    return text
