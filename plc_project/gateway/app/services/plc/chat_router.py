"""PLC block chat routing across evidence, understanding, and HITL flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gateway.app.services.plc.evidence.blocks import _resolve_block_focus
from gateway.app.services.plc.evidence.cards import (
    _describe_block_function,
    _focused_optimize_advice,
    _format_block_runtime_explain,
)
from gateway.app.services.plc.evidence.scl import _expr_dict_to_scl
from gateway.app.services.plc.evidence.instances import (
    _describe_instance_from_kg,
    _lookup_instance_entity,
)
from gateway.app.services.plc.evidence.nested import _format_typed_as_nest_lines
from gateway.app.services.plc.evidence.signal import _format_signal_trace
from gateway.app.services.plc.chat_intents import (
    _strip_at_hint,
    _wants_block_explain,
    _wants_confirm_writeback,
    _wants_full_scl,
    _wants_nest_chains,
    _wants_node_analyze,
    _wants_optimize_hints,
    _wants_optimize_logic,
    _wants_optimize_scl,
    _wants_project_interview,
    _wants_signal_trace,
    _wants_understand_logic,
)
from gateway.app.services.plc.chat_evidence import _folded_logic_lines
from gateway.app.services.plc.handover import (
    format_hitl_adjust_answer,
    wants_handover_hardware,
    wants_handover_hitl,
    wants_handover_run_logic,
)
from gateway.app.services.plc.writeback_views import (
    _format_confirm_writeback_chat,
    _format_optimize_scl_chat,
)

def answer_block_chat(
    job: dict[str, Any],
    message: str,
    block_name: str | None,
    *,
    confirm_writeback: Callable[..., dict[str, Any]],
    propose_optimize: Callable[..., dict[str, Any]],
) -> str:
    """Understand the user question, retrieve from KG, then answer (LLM if configured)."""
    import re

    from agents.plc.tia.understanding import (
        format_confirmation_ack,
        format_interview_block,
        format_optimize_advice,
        format_understand_logic,
        ingest_engineer_reply,
        looks_like_confirmation_reply,
        maybe_append_interview,
    )

    blocks = {b["name"]: b for b in job.get("blocks") or [] if isinstance(b, dict) and b.get("name")}
    focus = _resolve_block_focus(job, message, block_name)
    msg = message or ""
    hint = (block_name or "").strip() or _strip_at_hint(msg)
    at = re.search(r"@(.+)", msg)

    stored = ingest_engineer_reply(job, msg, block_name=focus or block_name)
    if (
        stored
        and not _wants_optimize_hints(msg)
        and not _wants_optimize_scl(msg)
        and not _wants_confirm_writeback(msg)
        and not _wants_optimize_logic(msg)
        and not _wants_understand_logic(msg)
        and not _wants_full_scl(msg)
        and not _wants_signal_trace(msg)
        and not _wants_nest_chains(msg)
        and not _wants_node_analyze(msg)
        and (
            looks_like_confirmation_reply(msg)
            or any(str(item.get("kind") or "") == "process_narrative" for item in stored)
        )
    ):
        return format_confirmation_ack(job, stored)

    through_member: str | None = None
    nest_origin: str | None = None
    # Explicit canvas/@ name that is NOT an IR block → multi-instance / external KG entity
    inst = None
    for candidate in (block_name, hint):
        cand = (candidate or "").strip()
        if not cand or cand in blocks:
            continue
        inst = _lookup_instance_entity(job, cand)
        if inst is not None:
            break
    if inst is not None and not (focus and focus in blocks):
        parents = [str(p) for p in (inst.get("parents") or []) if p]
        type_name = str(inst.get("type_block") or "")
        member_name = str(inst.get("name") or "")
        parent = next((p for p in parents if p in blocks), "")
        remap_chips = (
            _wants_full_scl(msg)
            or _wants_nest_chains(msg)
            or _wants_node_analyze(msg)
            or _wants_understand_logic(msg)
            or _wants_optimize_logic(msg)
            or _wants_optimize_scl(msg)
            or _wants_confirm_writeback(msg)
            or _wants_optimize_hints(msg)
        )
        if remap_chips and _wants_nest_chains(msg):
            origin = parent or (type_name if type_name in blocks else "")
            if origin:
                title = f"**`{member_name or origin}`**"
                body = _format_typed_as_nest_lines(
                    job,
                    origin,
                    through_member=member_name or None,
                    compact=False,
                    always=True,
                )
                return "\n".join([title, *body])
        if remap_chips and (type_name in blocks or parent in blocks):
            focus = type_name if type_name in blocks else parent
            through_member = member_name or None
            nest_origin = parent or focus
        else:
            return _describe_instance_from_kg(job, inst)

    if (at or block_name) and not focus:
        show = (hint or block_name or "")[:80]
        lines = [
            f"未找到与 `@{show}` 匹配的**独立程序块**（Blocks 列表中的 OB/FB/FC/DB 名 / 注释 / 网络标题）。"
        ]
        near: list[str] = []
        ql = show.lower()
        for n in (job.get("knowledge_graph") or {}).get("nodes") or []:
            if n.get("type") not in {"Variable", "Block"}:
                continue
            props = n.get("props") if isinstance(n.get("props"), dict) else {}
            nm = str(props.get("name") or "")
            if nm and ql and (ql in nm.lower() or nm.lower() in ql) and nm not in near:
                near.append(nm)
            if len(near) >= 8:
                break
        if near:
            lines.append("图谱中有近似节点（可能是多实例成员）：" + ", ".join(f"`{n}`" for n in near))
        names = [b["name"] for b in (job.get("blocks") or [])[:12]]
        if names:
            lines.append(f"可试独立块：{', '.join(f'`{n}`' for n in names)}")
        lines.append("也可点击知识图谱节点；多实例成员会按图谱边（USES / INSTANCE_OF / 接口变量）作答。")
        return "\n".join(lines)

    if wants_handover_hitl(msg) and not _wants_confirm_writeback(msg) and not _wants_optimize_scl(msg):
        from gateway.app.services.plc.brief import build_project_brief
        from gateway.app.services.plc.citations import citations_for_block

        _ = build_project_brief(job)
        job["_last_citations"] = citations_for_block(job, focus) if focus else []
        return format_hitl_adjust_answer(job, focus=focus or None)
    if wants_handover_hardware(msg) and not focus:
        from gateway.app.services.plc.brief import format_hardware_brief_answer
        from gateway.app.services.plc.citations import citations_for_block, gap_citation

        text = format_hardware_brief_answer(job)
        cites = []
        for d in (job.get("hardware") or [])[:6]:
            if isinstance(d, dict) and d.get("name"):
                cites.append(
                    {
                        "block": str(d["name"]),
                        "locator": str(d.get("address") or "hardware"),
                        "snippet": str(d.get("comment") or d.get("device_type") or ""),
                        "source_status": "indexed",
                        "evidence": "hardware",
                    }
                )
        if not cites:
            cites = [gap_citation("hardware")]
        job["_last_citations"] = cites
        return text
    if wants_handover_run_logic(msg) and not focus:
        from gateway.app.services.plc.brief import format_run_logic_brief_answer
        from gateway.app.services.plc.citations import citations_for_block

        main = None
        for b in job.get("blocks") or []:
            if isinstance(b, dict) and str(b.get("type") or "").upper() == "OB":
                name = str(b.get("name") or "")
                if name.startswith("OB1") or name.lower() in {"main", "ob1"} or b.get("number") == 1:
                    main = name
                    break
                if main is None:
                    main = name
        job["_last_citations"] = citations_for_block(job, focus or main or "")
        return format_run_logic_brief_answer(job)
    if focus and focus in blocks:
        job["_last_citations"] = _focused_citations(job, focus)

    if _wants_confirm_writeback(msg):
        return _format_confirm_writeback_chat(
            job,
            focus or None,
            message=msg,
            confirm_writeback=confirm_writeback,
        )
    if _wants_optimize_scl(msg):
        return _format_optimize_scl_chat(
            job,
            focus or None,
            message=msg,
            propose_optimize=propose_optimize,
        )
    if _wants_understand_logic(msg):
        return format_understand_logic(job, focus or None)
    if _wants_optimize_logic(msg):
        if focus and focus in blocks:
            return _focused_optimize_advice(job, focus, blocks[focus])
        return format_optimize_advice(job, focus or None)

    # Project-level interview: do not dump architecture as if already understood
    if (
        _wants_project_interview(msg)
        and not _wants_optimize_hints(msg)
        and not _wants_full_scl(msg)
        and not _wants_nest_chains(msg)
        and not _wants_node_analyze(msg)
        and not _wants_understand_logic(msg)
    ):
        interview = format_interview_block(job, focus_block=focus or None, limit=3)
        return interview or format_optimize_advice(job, focus)

    # Single-block card for explicit @/canvas focus (not multi-topic questions)
    explicit_one = bool(block_name) or bool(at)
    multi_topic = any(
        k in msg for k in ("水平", "垂直", "向上", "向下", "整体", "架构", "比较", "作业", "哪些")
    )
    if focus and focus in blocks and explicit_one and not multi_topic:
        b = blocks[focus]
        include_scl = _wants_full_scl(msg)
        if _wants_signal_trace(msg) and not include_scl:
            return "\n".join(_format_signal_trace(job, focus))
        if _wants_confirm_writeback(msg):
            return _format_confirm_writeback_chat(
                job,
                focus,
                message=msg,
                confirm_writeback=confirm_writeback,
            )
        if _wants_optimize_scl(msg):
            return _format_optimize_scl_chat(
                job,
                focus,
                message=msg,
                propose_optimize=propose_optimize,
            )
        if _wants_understand_logic(msg):
            return format_understand_logic(job, focus)
        if (_wants_optimize_logic(msg) or _wants_optimize_hints(msg)) and not include_scl:
            return _focused_optimize_advice(job, focus, b)
            return format_optimize_advice(job, focus)
        if _wants_nest_chains(msg) and not include_scl:
            title = f"**`{focus}`**"
            body = _format_typed_as_nest_lines(
                job,
                focus,
                through_member=through_member,
                compact=False,
                always=True,
            )
            return "\n".join([title, *body])
        meta = " · ".join(
            p
            for p in [
                str(b.get("type") or ""),
                f"编号 {b.get('number')}" if b.get("number") is not None else "",
                str(b.get("language") or ""),
                f"{b.get('networks')} 网络" if b.get("networks") is not None else "",
            ]
            if p
        )
        fact_lines = [f"**`{focus}`**（{meta}）" if meta else f"**`{focus}`**"]
        if _wants_block_explain(msg) and not include_scl:
            fact_lines.extend(
                _format_block_runtime_explain(
                    job,
                    focus,
                    b,
                    through_member=through_member,
                    nest_block=nest_origin or focus,
                )
            )
            return maybe_append_interview(job, "\n".join(fact_lines), focus_block=focus)
        fact_lines.extend(
            _describe_block_function(job, focus, b, include_full_scl=include_scl)
        )
        # Concise by default: no LLM essay + evidence appendix on canvas click
        card = "\n".join(fact_lines)
        if include_scl:
            if through_member and nest_origin:
                extra = _format_typed_as_nest_lines(
                    job,
                    nest_origin,
                    through_member=through_member,
                    compact=False,
                    always=False,
                )
                if extra:
                    card = card.rstrip() + "\n" + "\n".join(extra)
            return card
        return maybe_append_interview(job, card, focus_block=focus)

    # Project-level optimize without @block
    if (_wants_optimize_logic(msg) or _wants_optimize_hints(msg)) and not at:
        return format_optimize_advice(job, None)

    from agents.plc.tia.chat_retrieve import answer_query_pack

    history = []
    chat_turns = list(job.get("chat") or [])
    for turn in chat_turns[-8:]:
        if isinstance(turn, dict) and turn.get("content"):
            history.append(
                {"role": str(turn.get("role") or "user"), "content": str(turn.get("content"))}
            )
    pack = answer_query_pack(
        job,
        msg,
        focus_block=focus or None,
        chat_history=history,
    )
    job["_last_citations"] = list(pack.get("citations") or [])
    content = pack["content"]
    if focus:
        return maybe_append_interview(job, content, focus_block=focus)
    return content


def _focused_citations(job: dict[str, Any], focus: str) -> list[dict[str, Any]]:
    """Deterministic citations for a canvas/@block card, even without LLM retrieval."""
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _folded_rows(block_name: str) -> list[tuple[str, dict[str, Any], str]]:
        rows: list[tuple[str, dict[str, Any], str]] = []
        source = job.get("folded_logic")
        block_nets = source.get(block_name) if isinstance(source, dict) else None
        if not isinstance(block_nets, list):
            return rows
        for net in block_nets:
            if not isinstance(net, dict):
                continue
            title = str(net.get("title") or net.get("network_id") or "")
            for stmt in net.get("statements") or []:
                if isinstance(stmt, dict):
                    rows.append((title, stmt, ""))
        return rows

    def _statement_text(stmt: dict[str, Any]) -> str:
        target = str(stmt.get("target") or "?")
        kind = str(stmt.get("kind") or "coil")
        value = _expr_dict_to_scl(stmt.get("value"))
        if kind == "call":
            return target.rstrip(";")
        enable = stmt.get("enable")
        if enable is not None:
            return f"IF {_expr_dict_to_scl(enable)} THEN {target} := {value}; END_IF"
        return f"{target} := {value}"

    def _normalize(text: str) -> str:
        return text.lower().replace('"', "").replace("#", "").replace("\\", "/")

    def snippet_for(block_name: str, target: str) -> tuple[str, str]:
        wanted = _normalize(target)
        for title, stmt, _evidence in _folded_rows(block_name):
            text = _statement_text(stmt)
            normalized = _normalize(text)
            if wanted and (wanted in normalized or _normalize(str(stmt.get("target"))) in wanted):
                return text[:240], title
        return "", ""

    for edge in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source") or "").split("::")[-1]
        tgt = str(edge.get("target") or "").split("::")[-1]
        et = str(edge.get("type") or "")
        if focus not in {src, tgt} or et not in {"CALLS", "READS", "WRITES", "USES", "TYPED_AS"}:
            continue
        key = (et, src, tgt)
        if key in seen:
            continue
        seen.add(key)
        props = edge.get("props") if isinstance(edge.get("props"), dict) else {}
        raw_network = str(props.get("network") or "")
        snippet, network_title = snippet_for(src, tgt)
        citations.append(
            {
                "block": src,
                "target": tgt,
                "edge_type": et,
                "network": (raw_network.split("::")[-1] if raw_network else network_title),
                "evidence": str(props.get("evidence") or et),
                "snippet": snippet,
            }
        )
        if len(citations) >= 12:
            break

    if not citations:
        lines = _folded_logic_lines(job, focus)
        if lines:
            citations.append(
                {
                    "block": focus,
                    "target": "",
                    "edge_type": "",
                    "network": "",
                    "evidence": "flgnet_fold",
                    "snippet": lines[0][:240],
                }
            )
    return citations[:12]
