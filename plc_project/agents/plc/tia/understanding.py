"""Engineer-confirmed plant understanding — interview loop, not a one-shot IR read.

Durable state lives on ``job["engineer_understanding"]``. Graph/SCL evidence is
treated as **hypotheses to verify**. Only the engineer confirms roles, nested
FB intent, and do-not-touch constraints. Optimization chat and HITL propose
must cite those facts (or ask), never claim "the program is X".
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("researchos.plc.understanding")

ROLE_LABELS: dict[str, str] = {
    "process_main": "工艺主控",
    "device_driver": "设备驱动",
    "vendor_lib": "厂商库",
    "extractable_helper": "可拆辅助",
    "do_not_touch": "不要动",
}
LABEL_TO_ROLE: dict[str, str] = {label: key for key, label in ROLE_LABELS.items()}

NESTED_LABELS: dict[str, str] = {
    "required_multi_instance": "必须的西门子多实例",
    "accidental_coupling": "意外耦合",
}

_ROLE_PATTERNS: list[tuple[str, str]] = [
    (r"工艺主控|过程主控|主控工艺", "process_main"),
    (r"设备驱动|驱动块", "device_driver"),
    (r"厂商库|厂家库|vendor\s*lib", "vendor_lib"),
    (r"可拆辅助|可提取|可解耦|辅助块|may_extract", "extractable_helper"),
    (r"不要动|不许动|别动|must\s*not\s*touch|do_not_touch", "do_not_touch"),
]

_NESTED_REQUIRED_RE = re.compile(
    r"必须的(西门子)?多实例|必须保留嵌套|是必须的多实例|required\s*multi.?instance|"
    r"不要拍平|不建议拍平|不能拍平|must_keep_nested",
    re.I,
)
_NESTED_ACCIDENTAL_RE = re.compile(
    r"意外耦合|可以拍平|可拍平|不是必须的(多实例)?|偶然耦合|accidental",
    re.I,
)

_QUESTION_RE = re.compile(
    r"[？?]|(什么|谁|怎么|如何|请描述|请简述|优化建议|优化逻辑|优化\s*SCL|改写\s*SCL|"
    r"理解逻辑|理解这块|确认逻辑|这块逻辑|展开\s*SCL|谁读写|"
    r"分析节点|分析逻辑|运行逻辑|嵌套链|这个块干什么|"
    r"确认反写|执行反写)"
)
_CONFIRM_ONLY_RE = re.compile(
    r"^(工艺主控|设备驱动|厂商库|可拆辅助|不要动|必须的多实例|必须的西门子多实例|意外耦合)$"
)

WRITE_OP_KINDS = frozenset(
    {"rewrite_scl", "stage_scl_source", "stage_xml_import", "set_block_comment"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_understanding() -> dict[str, Any]:
    return {
        "process_narrative": None,
        "roles": {},
        "nested": {},
        "constraints": {
            "must_keep_nested": [],
            "do_not_touch": [],
            "may_extract": [],
        },
        "open_questions": [],
        "facts": [],
        "pending_question_id": None,
    }


def ensure_understanding(job: dict[str, Any]) -> dict[str, Any]:
    """Return the job's understanding dict, creating and seeding it if needed."""
    raw = job.get("engineer_understanding")
    if not isinstance(raw, dict):
        raw = empty_understanding()
        job["engineer_understanding"] = raw
    else:
        raw.setdefault("process_narrative", None)
        raw.setdefault("roles", {})
        raw.setdefault("nested", {})
        raw.setdefault("constraints", {})
        cons = raw["constraints"]
        if not isinstance(cons, dict):
            cons = {}
            raw["constraints"] = cons
        for key in ("must_keep_nested", "do_not_touch", "may_extract"):
            cons.setdefault(key, [])
        raw.setdefault("open_questions", [])
        raw.setdefault("facts", [])
        raw.setdefault("pending_question_id", None)
        job["engineer_understanding"] = raw
    refresh_open_questions(job)
    return raw


def _block_meta(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(b["name"]): b
        for b in (job.get("blocks") or [])
        if isinstance(b, dict) and b.get("name")
    }


def _main_ob(job: dict[str, Any]) -> str:
    from agents.plc.tia.analyst import _ob_names

    obs = _ob_names(job)
    for candidate in obs:
        low = candidate.lower()
        if candidate.startswith("OB1") or low in {"main", "ob1", "ob1main"} or "main" in low:
            return candidate
    return obs[0] if obs else ""


def _evidence_blocks(*names: str) -> list[str]:
    out: list[str] = []
    for n in names:
        n = str(n or "").strip()
        if n and n not in out:
            out.append(n)
    return out


def _question(
    qid: str,
    kind: str,
    text: str,
    *,
    block: str | None = None,
    evidence: list[str] | None = None,
    priority: int = 50,
) -> dict[str, Any]:
    return {
        "id": qid,
        "kind": kind,
        "block": block,
        "question": text,
        "evidence": list(evidence or ([block] if block else [])),
        "priority": priority,
    }


def _nested_parent_names(job: dict[str, Any]) -> list[tuple[str, int, list[str]]]:
    from agents.plc.tia.typed_as import nest_depth_of, typed_as_chains

    kg = job.get("knowledge_graph") or {}
    hits: list[tuple[str, int, list[str]]] = []
    for name, meta in _block_meta(job).items():
        btype = str(meta.get("type") or "").upper()
        if btype not in {"FB", "FC"}:
            continue
        depth = int(nest_depth_of(kg, name) or 0)
        if depth < 1:
            continue
        chains = typed_as_chains(kg, name) or []
        longest = chains[0] if chains else [name]
        hits.append((name, depth, longest))
    hits.sort(key=lambda item: (-item[1], item[0]))
    return hits


def _dead_block_names(job: dict[str, Any]) -> list[str]:
    try:
        from agents.plc.tia.analyst import analyze_project

        return list(analyze_project(job).get("dead_blocks") or [])
    except Exception:  # noqa: BLE001
        return []


def refresh_open_questions(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild unanswered high-value questions from KG hypotheses + confirmed facts."""
    u = job.get("engineer_understanding")
    if not isinstance(u, dict):
        u = empty_understanding()
        job["engineer_understanding"] = u

    roles = u.get("roles") if isinstance(u.get("roles"), dict) else {}
    nested = u.get("nested") if isinstance(u.get("nested"), dict) else {}
    cons = u.get("constraints") if isinstance(u.get("constraints"), dict) else {}
    do_not_touch = {str(x) for x in (cons.get("do_not_touch") or [])}
    questions: list[dict[str, Any]] = []

    main = _main_ob(job)
    if not (u.get("process_narrative") or "").strip():
        callees: list[str] = []
        if main:
            try:
                from agents.plc.tia.analyst import _ordered_callees

                callees = _ordered_callees(job, main)[:8]
            except Exception:  # noqa: BLE001
                callees = []
        ev = _evidence_blocks(main, *callees)
        callee_s = "、".join(f"`{c}`" for c in callees[:6]) if callees else "（暂无已验证 CALLS）"
        questions.append(
            _question(
                "process_purpose",
                "process_purpose",
                (
                    "这条产线/工艺主要在干什么？"
                    + (
                        f"图谱显示主扫描入口是 `{main}`，调用 {callee_s}。"
                        if main
                        else "图谱里还没看到明确的 OB 入口。"
                    )
                    + "请用一两句话说明（不是让我猜）。"
                ),
                evidence=ev,
                priority=10,
            )
        )

    for name, depth, chain in _nested_parent_names(job)[:6]:
        if name in nested or name in do_not_touch:
            continue
        chain_s = " → ".join(f"`{c}`" for c in chain[:6])
        questions.append(
            _question(
                f"nested:{name}",
                "nested_fb",
                (
                    f"`{name}` 的 STAT 成员把另一 FB 当类型嵌套（深度 {depth}："
                    f"{chain_s}）。这是**必须的西门子多实例**，还是**意外耦合**？"
                    "请不要让我根据 IR 擅自拍平。"
                ),
                block=name,
                evidence=list(chain[:8]),
                priority=20 if depth >= 2 else 28,
            )
        )

    # Role of a few high-value FB/FC that are still unconfirmed
    from agents.plc.tia.analyst import _role_hint

    role_candidates: list[tuple[int, str, str]] = []
    for name, meta in _block_meta(job).items():
        btype = str(meta.get("type") or "").upper()
        if btype not in {"FB", "FC", "OB"}:
            continue
        if name in roles or name in do_not_touch:
            continue
        hint = _role_hint(name, str(meta.get("comment") or ""))
        score = 0
        if btype == "OB":
            score += 2
        if hint:
            score += 4
        if int(meta.get("nest_depth") or 0) >= 1:
            score += 3
        if name == main:
            score += 5
        role_candidates.append((score, name, hint))
    role_candidates.sort(key=lambda item: (-item[0], item[1]))
    for score, name, hint in role_candidates[:8]:
        if score < 2 and len(questions) >= 6:
            continue
        hint_s = f"图谱线索像「{hint}」，" if hint else ""
        questions.append(
            _question(
                f"role:{name}",
                "block_role",
                (
                    f"`{name}` {hint_s}在工艺里是什么角色？"
                    "请选：工艺主控 / 设备驱动 / 厂商库 / 可拆辅助 / 不要动。"
                ),
                block=name,
                evidence=_evidence_blocks(name),
                priority=32 if score >= 4 else 40,
            )
        )

    for dead in _dead_block_names(job)[:4]:
        if dead in roles or dead in do_not_touch:
            continue
        questions.append(
            _question(
                f"dead:{dead}",
                "dead_or_keep",
                (
                    f"图谱显示 `{dead}` 未从 OB 入口到达。"
                    "它是可注释的死块，还是实际在用 / 不要动？"
                ),
                block=dead,
                evidence=_evidence_blocks(dead, main),
                priority=45,
            )
        )

    questions.sort(key=lambda q: (int(q.get("priority") or 99), str(q.get("id") or "")))
    # de-dupe by id
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for q in questions:
        qid = str(q.get("id") or "")
        if not qid or qid in seen:
            continue
        seen.add(qid)
        uniq.append(q)
    u["open_questions"] = uniq
    return uniq


def open_questions(
    job: dict[str, Any],
    *,
    focus_block: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    ensure_understanding(job)
    qs = list((job.get("engineer_understanding") or {}).get("open_questions") or [])
    focus = (focus_block or "").strip()
    if focus:
        focused = [q for q in qs if str(q.get("block") or "") == focus]
        rest = [q for q in qs if str(q.get("block") or "") != focus]
        qs = focused + rest
    return qs[:limit]


def is_understanding_thin(job: dict[str, Any]) -> bool:
    u = ensure_understanding(job)
    if (u.get("process_narrative") or "").strip():
        return False
    if u.get("roles"):
        return False
    if u.get("nested"):
        return False
    cons = u.get("constraints") or {}
    if any(cons.get(k) for k in ("must_keep_nested", "do_not_touch", "may_extract")):
        return False
    return True


def is_block_understanding_thin(job: dict[str, Any], block_name: str | None) -> bool:
    """True when this focused block has no engineer-confirmed role/nest/fact."""
    name = (block_name or "").strip()
    if not name:
        return is_understanding_thin(job)
    if confirmed_role(job, name) or confirmed_nested(job, name):
        return False
    u = ensure_understanding(job)
    for fact in u.get("facts") or []:
        if isinstance(fact, dict) and str(fact.get("block") or "") == name:
            return False
    return True


def block_understanding_ready(job: dict[str, Any], block_name: str) -> bool:
    """Role confirmed; nested FB intent confirmed when this block hosts a chain."""
    name = (block_name or "").strip()
    if not name or not confirmed_role(job, name):
        return False
    nested_parents = {n for n, _, _ in _nested_parent_names(job)}
    if name in nested_parents:
        return bool(confirmed_nested(job, name))
    return True


def confirmed_role(job: dict[str, Any], block_name: str) -> dict[str, Any] | None:
    u = job.get("engineer_understanding") if isinstance(job.get("engineer_understanding"), dict) else {}
    roles = u.get("roles") if isinstance(u.get("roles"), dict) else {}
    hit = roles.get(block_name)
    return hit if isinstance(hit, dict) else None


def confirmed_nested(job: dict[str, Any], block_name: str) -> dict[str, Any] | None:
    u = job.get("engineer_understanding") if isinstance(job.get("engineer_understanding"), dict) else {}
    nested = u.get("nested") if isinstance(u.get("nested"), dict) else {}
    hit = nested.get(block_name)
    return hit if isinstance(hit, dict) else None


def _constraint_set(job: dict[str, Any], key: str) -> set[str]:
    u = job.get("engineer_understanding") if isinstance(job.get("engineer_understanding"), dict) else {}
    cons = u.get("constraints") if isinstance(u.get("constraints"), dict) else {}
    return {str(x) for x in (cons.get(key) or []) if str(x).strip()}


def must_not_touch(job: dict[str, Any], block_name: str) -> bool:
    if not block_name:
        return False
    if block_name in _constraint_set(job, "do_not_touch"):
        return True
    role = confirmed_role(job, block_name)
    return bool(role and role.get("role") == "do_not_touch")


def must_keep_nested(job: dict[str, Any], block_name: str) -> bool:
    if not block_name:
        return False
    if block_name in _constraint_set(job, "must_keep_nested"):
        return True
    nest = confirmed_nested(job, block_name)
    return bool(nest and nest.get("kind") == "required_multi_instance")


def may_extract_block(job: dict[str, Any], block_name: str) -> bool:
    if not block_name:
        return False
    if block_name in _constraint_set(job, "may_extract"):
        return True
    role = confirmed_role(job, block_name)
    if role and role.get("role") == "extractable_helper":
        return True
    nest = confirmed_nested(job, block_name)
    return bool(nest and nest.get("kind") == "accidental_coupling")


def skip_write_reason(job: dict[str, Any], block_name: str, *, kind: str = "") -> str | None:
    """Why a proposed write/extract should not land. None = allowed."""
    name = (block_name or "").strip()
    if not name:
        return None
    if must_not_touch(job, name):
        return "工程师确认不要动"
    if must_keep_nested(job, name) and kind in {
        "rewrite_scl",
        "stage_scl_source",
        "stage_xml_import",
        "decouple",
        "flatten",
    }:
        if may_extract_block(job, name):
            return None
        return "工程师确认必须保留多实例嵌套，不拍平"
    return None


def _append_unique(seq: list[Any], item: str) -> None:
    if item and item not in seq:
        seq.append(item)


def _add_fact(
    u: dict[str, Any],
    *,
    kind: str,
    text: str,
    block: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    fact = {
        "id": f"fact:{kind}:{block or 'project'}:{len(u.get('facts') or [])}",
        "kind": kind,
        "block": block,
        "text": text,
        "evidence": list(evidence or ([block] if block else [])),
        "source": "engineer",
        "confirmed_at": _now_iso(),
    }
    u.setdefault("facts", []).append(fact)
    return fact


def _set_role(
    job: dict[str, Any],
    block: str,
    role: str,
    *,
    note: str = "",
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    u = ensure_understanding(job)
    label = ROLE_LABELS.get(role, role)
    rec = {
        "role": role,
        "label": label,
        "note": (note or "").strip(),
        "evidence": list(evidence or [block]),
        "confirmed_at": _now_iso(),
        "source": "engineer",
    }
    u.setdefault("roles", {})[block] = rec
    cons = u.setdefault("constraints", {})
    if role == "do_not_touch":
        _append_unique(cons.setdefault("do_not_touch", []), block)
    elif role == "extractable_helper":
        _append_unique(cons.setdefault("may_extract", []), block)
    _add_fact(
        u,
        kind="block_role",
        text=f"`{block}` 是{label}" + (f"：{note}" if note else ""),
        block=block,
        evidence=rec["evidence"],
    )
    return rec


def _set_nested(
    job: dict[str, Any],
    block: str,
    kind: str,
    *,
    note: str = "",
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    u = ensure_understanding(job)
    label = NESTED_LABELS.get(kind, kind)
    rec = {
        "kind": kind,
        "label": label,
        "note": (note or "").strip(),
        "evidence": list(evidence or [block]),
        "confirmed_at": _now_iso(),
        "source": "engineer",
    }
    u.setdefault("nested", {})[block] = rec
    cons = u.setdefault("constraints", {})
    if kind == "required_multi_instance":
        _append_unique(cons.setdefault("must_keep_nested", []), block)
    elif kind == "accidental_coupling":
        _append_unique(cons.setdefault("may_extract", []), block)
    _add_fact(
        u,
        kind="nested_fb",
        text=f"`{block}` 嵌套 FB：{label}" + (f"：{note}" if note else ""),
        block=block,
        evidence=rec["evidence"],
    )
    return rec


def _strip_at(message: str) -> tuple[str | None, str]:
    msg = (message or "").strip()
    hit = re.match(r"^@(\S+)\s*(.*)$", msg, re.S)
    if not hit:
        return None, msg
    return hit.group(1).strip(), (hit.group(2) or "").strip()


def _mentioned_block(job: dict[str, Any], text: str, focus: str | None) -> str | None:
    if focus and focus in _block_meta(job):
        return focus
    names = sorted(_block_meta(job), key=len, reverse=True)
    blob = text or ""
    for name in names:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", blob):
            return name
    at, _ = _strip_at(blob)
    if at and at in _block_meta(job):
        return at
    return None


def _match_role(text: str) -> str | None:
    blob = (text or "").strip()
    if blob in LABEL_TO_ROLE:
        return LABEL_TO_ROLE[blob]
    for pat, role in _ROLE_PATTERNS:
        if re.search(pat, blob, re.I):
            return role
    return None


def looks_like_confirmation_reply(message: str) -> bool:
    _, body = _strip_at(message)
    body = (body or "").strip()
    if not body:
        return False
    if _CONFIRM_ONLY_RE.match(body):
        return True
    if _match_role(body) and len(body) <= 24:
        return True
    if _NESTED_REQUIRED_RE.search(body) and len(body) <= 40:
        return True
    if _NESTED_ACCIDENTAL_RE.search(body) and len(body) <= 40:
        return True
    return False


def ingest_engineer_reply(
    job: dict[str, Any],
    message: str,
    block_name: str | None = None,
) -> list[dict[str, Any]]:
    """Parse a node-scoped chat reply into confirmed facts. Mutates the job."""
    u = ensure_understanding(job)
    _, body = _strip_at(message)
    body = body or (message or "").strip()
    if not body:
        return []

    focus = _mentioned_block(job, message, block_name)
    pending_id = str(u.get("pending_question_id") or "")
    pending = None
    if pending_id:
        pending = next(
            (q for q in (u.get("open_questions") or []) if str(q.get("id")) == pending_id),
            None,
        )
    if not focus and isinstance(pending, dict) and pending.get("block"):
        focus = str(pending.get("block") or "") or None

    stored: list[dict[str, Any]] = []
    role = _match_role(body)
    if role and focus:
        stored.append(_set_role(job, focus, role, note=body, evidence=[focus]))

    if focus and _NESTED_REQUIRED_RE.search(body):
        stored.append(
            _set_nested(
                job,
                focus,
                "required_multi_instance",
                note=body,
                evidence=[focus],
            )
        )
    elif focus and _NESTED_ACCIDENTAL_RE.search(body):
        stored.append(
            _set_nested(job, focus, "accidental_coupling", note=body, evidence=[focus])
        )

    # Process narrative: answering the line/process question, or first descriptive reply
    narrative_cue = any(
        k in body for k in ("产线", "工艺", "这条线", "这个项目", "用来", "做的是", "车间")
    )
    pending_kind = str((pending or {}).get("kind") or "")
    looks_question = bool(_QUESTION_RE.search(body))
    if (
        not (u.get("process_narrative") or "").strip()
        and len(body) >= 8
        and not looks_like_confirmation_reply(message)
        and not looks_question
        and (pending_kind == "process_purpose" or narrative_cue)
        and not role
    ):
        u["process_narrative"] = body[:800]
        stored.append(
            _add_fact(
                u,
                kind="process_narrative",
                text=body[:800],
                evidence=_evidence_blocks(_main_ob(job)),
            )
        )

    if stored:
        u["pending_question_id"] = None
        refresh_open_questions(job)
    return stored


def format_question_line(q: dict[str, Any], *, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else "- "
    evidence = [str(e) for e in (q.get("evidence") or []) if e]
    chips = " ".join(f"`{e}`" for e in evidence[:6])
    extra = f"  〔线索：{chips}〕" if chips else ""
    return f"{prefix}{q.get('question') or ''}{extra}"


def format_interview_block(
    job: dict[str, Any],
    *,
    focus_block: str | None = None,
    limit: int = 3,
    heading: str | None = None,
) -> str:
    qs = open_questions(job, focus_block=focus_block, limit=limit)
    if not qs:
        return ""
    u = ensure_understanding(job)
    u["pending_question_id"] = qs[0].get("id")
    lines = [heading or "我还没懂，需要你确认几件事（图谱是线索，不是结论）："]
    for i, q in enumerate(qs, start=1):
        lines.append(format_question_line(q, index=i))
    return "\n".join(lines)


def format_welcome_interview(job: dict[str, Any]) -> str:
    """Post-ingest welcome: short interview, not an architecture essay."""
    ensure_understanding(job)
    name = job.get("project_name") or job.get("id")
    blocks = job.get("blocks") or []
    summary = job.get("summary") or {}
    summary_bits = []
    if isinstance(summary, dict):
        summary_bits = [f"{k} {v}" for k, v in summary.items() if v]
    head = (
        f"工程「{name}」· 程序块 {len(blocks)} 个"
        + (f"（{' · '.join(summary_bits[:8])}）" if summary_bits else "")
        + "\n画布已更新。我还没懂这条线，不会把 SCL/IR 当成已经理解的工艺。"
    )
    interview = format_interview_block(
        job,
        limit=3,
        heading="需要你确认几件事（点画布上的块，也可以用「工艺主控 / 设备驱动 / 厂商库 / 可拆辅助 / 不要动」直接答）：",
    )
    return f"{head}\n\n{interview}".rstrip()


def format_confirmation_ack(job: dict[str, Any], stored: list[dict[str, Any]]) -> str:
    bits: list[str] = []
    for rec in stored:
        text = str(rec.get("text") or rec.get("label") or "").strip()
        if text:
            bits.append(text)
    ack = "已记下：" + "；".join(bits[:4]) if bits else "已记下你的确认。"
    nxt = format_interview_block(
        job,
        limit=2,
        heading="下一个高价值问题：",
    )
    if nxt:
        return f"{ack}\n\n{nxt}"
    return (
        ack
        + "\n\n目前没有更高优先级的待确认项。可以点「优化逻辑」看改动计划，或「优化SCL」出 HITL diff。"
    )


def format_role_prompt(job: dict[str, Any], block_name: str) -> str:
    nest = ""
    parents = {n: (d, c) for n, d, c in _nested_parent_names(job)}
    if block_name in parents and not confirmed_nested(job, block_name):
        depth, chain = parents[block_name]
        chain_s = " → ".join(f"`{c}`" for c in chain[:6])
        nest = (
            f" 另：STAT 嵌套（深度 {depth}：{chain_s}）是必须的西门子多实例，还是意外耦合？"
        )
    return (
        f"角色未确认：`{block_name}` 是 工艺主控 / 设备驱动 / 厂商库 / 可拆辅助 / 不要动？"
        + nest
    )


def maybe_append_interview(
    job: dict[str, Any],
    answer: str,
    *,
    focus_block: str | None = None,
) -> str:
    """Pin a follow-up question onto an evidence card when that block's role is open."""
    focus = (focus_block or "").strip()
    if not focus:
        return answer
    if confirmed_role(job, focus) and (
        confirmed_nested(job, focus) or focus not in {n for n, _, _ in _nested_parent_names(job)}
    ):
        return answer
    prompt = format_role_prompt(job, focus)
    if prompt in (answer or ""):
        return answer
    u = ensure_understanding(job)
    qid = f"role:{focus}"
    if any(str(q.get("id")) == qid for q in (u.get("open_questions") or [])):
        u["pending_question_id"] = qid
    return f"{answer.rstrip()}\n{prompt}"


def _format_confirmed_facts(job: dict[str, Any], *, focus: str | None = None) -> list[str]:
    u = ensure_understanding(job)
    lines: list[str] = []
    narrative = str(u.get("process_narrative") or "").strip()
    if narrative:
        lines.append(f"- 工艺（你确认）：{narrative[:240]}")
    roles = u.get("roles") if isinstance(u.get("roles"), dict) else {}
    items = list(roles.items())
    if focus:
        items = [(n, r) for n, r in items if n == focus] + [
            (n, r) for n, r in items if n != focus
        ]
    for name, rec in items[:8]:
        if not isinstance(rec, dict):
            continue
        label = rec.get("label") or rec.get("role")
        lines.append(f"- `{name}`：{label}（工程师确认）")
    nested = u.get("nested") if isinstance(u.get("nested"), dict) else {}
    for name, rec in list(nested.items())[:6]:
        if not isinstance(rec, dict):
            continue
        lines.append(
            f"- `{name}` 嵌套：{rec.get('label') or rec.get('kind')}（工程师确认，不按 IR 擅自拍平）"
        )
    cons = u.get("constraints") if isinstance(u.get("constraints"), dict) else {}
    for key, label in (
        ("do_not_touch", "不要动"),
        ("must_keep_nested", "必须保留嵌套"),
        ("may_extract", "可拆"),
    ):
        names = [str(x) for x in (cons.get(key) or []) if x]
        if names:
            lines.append("- " + label + "：" + "、".join(f"`{n}`" for n in names[:8]))
    return lines


def _hypothesis_call_bits(job: dict[str, Any], block_name: str) -> str:
    callers: list[str] = []
    callees: list[str] = []
    bid = f"Block::{block_name}"
    for e in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(e, dict) or e.get("type") != "CALLS":
            continue
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if tgt == bid and src.startswith("Block::"):
            callers.append(src.split("::", 1)[-1])
        elif src == bid and tgt.startswith("Block::"):
            callees.append(tgt.split("::", 1)[-1])
    bits: list[str] = []
    if callers:
        bits.append("被调用 " + "、".join(f"`{c}`" for c in sorted(set(callers))[:4]))
    if callees:
        bits.append("调用 " + "、".join(f"`{c}`" for c in sorted(set(callees))[:4]))
    return "；".join(bits)


def format_understand_logic(job: dict[str, Any], block_name: str | None = None) -> str:
    """Chat 「理解逻辑」: interview about this node's runtime, never claim IR as truth."""
    ensure_understanding(job)
    focus = (block_name or "").strip() or None
    if not focus:
        interview = format_interview_block(
            job,
            limit=3,
            heading="请先在画布选中一个块（或 @块名）。图谱/IR 只是待确认假设，不是结论：",
        )
        return interview or (
            "请先在画布选中一个块，再点「理解逻辑」。"
            "我不会把 SCL/IR 当成已经理解的工艺。"
        )

    lines = [
        f"**理解逻辑（`{focus}`）**",
        "折叠网络 / IO / CALLS / 嵌套只是**待确认假设**，不是「程序就是 X」。请你拍板。",
    ]
    facts = _format_confirmed_facts(job, focus=focus)
    if facts:
        lines.append("已确认（工程师为准）：")
        lines.extend(facts[:8])

    hypo: list[str] = []
    titles: list[str] = []
    folded = job.get("folded_logic") or {}
    nets = folded.get(focus) if isinstance(folded, dict) else None
    if isinstance(nets, list):
        for net in nets:
            if not isinstance(net, dict):
                continue
            t = str(net.get("title") or "").strip().strip('"')
            if t:
                titles.append(t)
    if titles:
        chain = " → ".join(f"`{t}`" for t in titles[:6])
        hypo.append(f"- 网络标题线索：{chain}。这些网络在工艺里各自干什么？")

    try:
        from agents.plc.tia.typed_as import format_chain, nest_depth_of, typed_as_chains

        kg = job.get("knowledge_graph") or {}
        depth = int(nest_depth_of(kg, focus) or 0)
        if depth >= 1 and not confirmed_nested(job, focus):
            chains = typed_as_chains(kg, focus) or []
            chain_s = format_chain(chains[0]) if chains else f"`{focus}`"
            hypo.append(
                f"- 嵌套线索（深度 {depth}：{chain_s}）：是**必须的西门子多实例**，还是**意外耦合**？"
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("understand-logic nest hypothesis skipped: %s", exc)

    call_s = _hypothesis_call_bits(job, focus)
    if call_s and not confirmed_role(job, focus):
        hypo.append(f"- 调用关系线索：{call_s}。这块是工艺主控 / 设备驱动 / 厂商库 / 可拆辅助，还是不要动？")

    meta = (_block_meta(job).get(focus) or {}) if focus else {}
    reads = [str(x) for x in (meta.get("inputs") or []) if x]
    writes = [str(x) for x in (meta.get("outputs") or []) if x]
    if (reads or writes) and not confirmed_role(job, focus):
        io_s = []
        if reads:
            io_s.append("入 " + "、".join(f"`{x}`" for x in reads[:4]))
        if writes:
            io_s.append("出 " + "、".join(f"`{x}`" for x in writes[:4]))
        hypo.append("- IO 线索：" + "；".join(io_s) + "。这些针脚在现场对应什么？")

    if hypo:
        lines.append("待确认假设（请拍板，不当作结论）：")
        lines.extend(hypo[:4])

    if block_understanding_ready(job, focus):
        lines.append("")
        lines.append(
            f"`{focus}` 的关键事实已确认，够用来优化。"
            "下一步可点「优化逻辑」看改动计划，或「优化SCL」出该块 HITL diff（不自动反写）。"
        )
        return "\n".join(lines)

    interview = format_interview_block(
        job,
        focus_block=focus,
        limit=3,
        heading=(
            "请确认这 1–3 点（也可用芯片：工艺主控 / 设备驱动 / 厂商库 / 可拆辅助 / 不要动"
            " / 必须的多实例 / 意外耦合）："
        ),
    )
    lines.append("")
    lines.append(interview or format_role_prompt(job, focus))
    return "\n".join(lines)


def format_optimize_advice(job: dict[str, Any], block_name: str | None = None) -> str:
    """Chat 「优化逻辑」/「优化建议」: plan only. Ask if thin; cite facts if present."""
    ensure_understanding(job)
    focus = (block_name or "").strip() or None
    thin = is_block_understanding_thin(job, focus) if focus else is_understanding_thin(job)
    title = "**优化逻辑**" + (f"（`{focus}`）" if focus else "（工程）")
    lines = [
        title,
        "优化提示须引用你确认的事实；这是控制逻辑计划，不是 SCL 文件。未确认的只提问，不当作「程序就是 X」。",
    ]

    facts = _format_confirmed_facts(job, focus=focus)
    findings: list[dict[str, Any]] = []
    try:
        from agents.plc.tia.analyst import analyze_block, analyze_project

        result = analyze_block(job, focus) if focus else analyze_project(job)
        findings = list(result.get("findings") or [])
    except Exception:  # noqa: BLE001
        findings = []

    if thin:
        lines.append("确认还不够，先不编造改写。图谱线索需要你拍板：")
        interview = format_interview_block(job, focus_block=focus, limit=3, heading="")
        if interview:
            lines.append(interview.strip())
        else:
            lines.append("- 请先说明这条线干什么，并给几个块打上角色。")
        actionable = 0
        hint_lines: list[str] = []
        for f in findings:
            sev = str(f.get("severity") or "")
            if sev not in {"warn", "risk"}:
                continue
            msg = str(f.get("message") or "").strip()
            code = str(f.get("code") or "")
            if not msg:
                continue
            tip = {
                "DEAD_BLOCK": "是死块可注释，还是不要动？",
                "UNREACHABLE_FROM_OB": "调用链缺失，还是间接在用？",
                "NESTED_FB_TYPE": "必须的西门子多实例，还是意外耦合？这不是父 FB CALL 子 FB。",
                "MULTI_INSTANCE_CHAIN": "请确认是否必须保留嵌套；未确认前不拍平、不发明 I/O。",
            }.get(code, "请确认是否可动。")
            hint_lines.append(f"- [{sev}] {msg} → {tip}")
            actionable += 1
            if actionable >= 5:
                break
        if hint_lines:
            lines.append("**优化提示（待你确认，不是结论）**")
            lines.extend(hint_lines)
        lines.append("")
        lines.append("确认后再点「优化SCL」可出 HITL 预览（未确认不会被当成已批准改写）。")
        return "\n".join(lines)

    lines.append("已确认（工程师为准）：")
    lines.extend(facts or ["- （尚无结构化事实，但已有部分确认）"])
    lines.append("")
    lines.append("逻辑上拟改（还不是 SCL 文件；引用你的确认 + 图谱证据）：")
    lines.append("- 必须的西门子多实例保持嵌套，不拍平、不发明 I/O。")
    lines.append("- 你标「不要动」的块跳过写回。")
    lines.append("- 未从 OB 到达且未标不要动的死块可注释（HITL），不静默删除。")
    if focus and may_extract_block(job, focus):
        lines.append(
            f"- `{focus}` 你确认可拆/意外耦合：仅在 folded 网络已有 I/O 时提取 helper，仍禁止发明 CALLS。"
        )
    else:
        lines.append("- 提取 helper 仅当工程师确认可拆辅助或意外耦合。")

    suggested = 0
    for f in findings:
        sev = str(f.get("severity") or "")
        if sev not in {"warn", "risk"}:
            continue
        msg = str(f.get("message") or "").strip()
        code = str(f.get("code") or "")
        block = focus
        if not block:
            m = re.search(r"`([^`]+)`", msg)
            block = m.group(1) if m else None
        if block and must_not_touch(job, block):
            lines.append(
                f"- `{block}` 你确认**不要动**，跳过改写。证据仍在：{msg}"
            )
            suggested += 1
            continue
        if code in {"NESTED_FB_TYPE", "MULTI_INSTANCE_CHAIN"} and block:
            nest = confirmed_nested(job, block)
            role = confirmed_role(job, block)
            role_s = f"你确认 `{block}` 是{role.get('label')}" if role else ""
            if nest and nest.get("kind") == "required_multi_instance":
                lines.append(
                    f"- {role_s + '，' if role_s else ''}你确认 `{block}` 是**必须的"
                    f"{' KUKA ' if 'kuka' in (block or '').lower() or 'robot' in (block or '').lower() else ''}"
                    "多实例**，所以**不建议拍平**。"
                    f"证据：{msg}"
                )
            elif nest and nest.get("kind") == "accidental_coupling":
                lines.append(
                    f"- 你确认 `{block}` 是意外耦合，可在有既有 I/O 的前提下考虑提取 helper，"
                    f"仍禁止发明 I/O。证据：{msg}"
                )
            else:
                lines.append(
                    f"- `{block}` 嵌套尚未确认是必须多实例还是意外耦合；暂不拍平。证据：{msg}"
                )
            suggested += 1
            continue
        if code == "DEAD_BLOCK" and block:
            if must_not_touch(job, block):
                continue
            lines.append(
                f"- 死块 `{block}` 你未标为不要动，仍可注释/归档（HITL）。证据：{msg}"
            )
            suggested += 1
            continue
        if msg:
            lines.append(f"- [{sev}] {msg}")
            suggested += 1
        if suggested >= 6:
            break

    # Always mention remaining do-not-touch / keep-nested even if not in findings
    for name in sorted(_constraint_set(job, "must_keep_nested")):
        if focus and name != focus:
            continue
        if any(name in ln for ln in lines):
            continue
        lines.append(f"- `{name}` 你确认必须保留嵌套，优化提案不会拍平该多实例。")
        suggested += 1
    for name in sorted(_constraint_set(job, "do_not_touch")):
        if focus and name != focus:
            continue
        if any(name in ln for ln in lines):
            continue
        lines.append(f"- `{name}` 你确认不要动，提案将跳过其写回。")
        suggested += 1

    remaining = open_questions(job, focus_block=focus, limit=2)
    if remaining:
        lines.append("")
        lines.append("仍不清楚（先问，不当作结论）：")
        for q in remaining:
            lines.append(format_question_line(q))

    if not suggested:
        lines.append("- 未发现与已确认事实相符的 warn/risk；可点「优化SCL」做该块 HITL 预览。")
    lines.append("")
    if focus:
        lines.append("下一步可点「优化SCL」出该块 diff（不自动反写；仍须节点「确认反写」或画布「确认反写.zap」）。")
    else:
        lines.append("下一步可点「优化SCL」或画布「优化提案」出 HITL SCL diff（不自动反写）。")
    return "\n".join(lines)


def format_facts_for_llm(job: dict[str, Any]) -> str:
    """Short block injected into retrieve/LLM evidence: engineer is authority."""
    u = job.get("engineer_understanding")
    if not isinstance(u, dict):
        return ""
    lines = ["工程师已确认（不得与之矛盾；未确认的只可提问）："]
    facts = _format_confirmed_facts(job)
    if not facts:
        return ""
    lines.extend(facts)
    return "\n".join(lines)


def filter_optimize_ops(job: dict[str, Any], ops: list[Any]) -> tuple[list[Any], list[str]]:
    """Drop changeset ops that contradict must_keep_nested / do_not_touch."""
    kept: list[Any] = []
    skipped: list[str] = []
    for op in ops:
        kind = getattr(op, "kind", None) or (op.get("kind") if isinstance(op, dict) else "")
        payload = getattr(op, "payload", None) or (op.get("payload") if isinstance(op, dict) else {}) or {}
        name = str(payload.get("block_name") or "")
        reason = skip_write_reason(job, name, kind=str(kind or ""))
        if reason and str(kind) in WRITE_OP_KINDS | {"add_edge", "annotate"}:
            # Keep annotate on must_keep nested (documents coupling) unless do_not_touch
            if str(kind) == "annotate" and must_keep_nested(job, name) and not must_not_touch(job, name):
                kept.append(op)
                continue
            skipped.append(f"- `{name}`：{reason}，跳过 `{kind}`")
            continue
        kept.append(op)
    return kept, skipped
