"""Block dossiers — per-node evidence packs powering deep node conversations.

A dossier is the pre-computed answer sheet for one block: identity, call
relations, signal IO, instances, folded-logic summary, translation coverage,
review findings, and a list of preset engineer questions that can all be
answered deterministically from the KG / folded logic (zero hallucination —
every answer cites its evidence). Chat layers may render these as cards and
let the LLM only rephrase, never invent.
"""

from __future__ import annotations

from typing import Any

from agents.plc.tia.analyst import _folded_lines
from agents.plc.tia.graph_query import callees_of, callers_of

_MAX_BLOCKS = 500
_MAX_SAMPLE_LINES = 12
_MAX_REVIEW_PER_BLOCK = 5


def _io_tags(kg: dict[str, Any], block_name: str) -> tuple[list[str], list[str]]:
    block_id = f"Block::{block_name}"
    reads: set[str] = set()
    writes: set[str] = set()
    for edge in kg.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("source") != block_id:
            continue
        target = str(edge.get("target") or "")
        if not target.startswith("Tag::"):
            continue
        ref = target.removeprefix("Tag::")
        if edge.get("type") == "READS":
            reads.add(ref)
        elif edge.get("type") == "WRITES":
            writes.add(ref)
    return sorted(reads), sorted(writes)


def _instances(kg: dict[str, Any], block_name: str) -> list[str]:
    target = f"Block::{block_name}"
    names: set[str] = set()
    for edge in kg.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("type") != "INSTANCE_OF":
            continue
        if edge.get("target") != target:
            continue
        source = str(edge.get("source") or "")
        if "::" in source:
            names.add(source.split("::", 1)[1])
    return sorted(names)


def _logic_summary(job: dict[str, Any], block_name: str) -> dict[str, Any]:
    networks = (job.get("folded_logic") or {}).get(block_name) or []
    statements = 0
    todo_statements = 0
    for network in networks:
        if not isinstance(network, dict):
            continue
        for statement in network.get("statements") or []:
            statements += 1
            if "TODO" in str(statement.get("target_scl") or "") or "TODO" in str(
                statement.get("target") or ""
            ):
                todo_statements += 1
    scl_text = str((job.get("scl_sources") or {}).get(block_name) or "")
    return {
        "networks": len(networks),
        "statements": statements,
        "todo_statements": todo_statements,
        "scl_todo_comments": scl_text.count("(* TODO"),
        "scl_available": bool(scl_text.strip()),
    }


def _review_for_block(review: dict[str, Any] | None, block_name: str) -> list[dict[str, Any]]:
    findings = []
    for finding in (review or {}).get("findings") or []:
        if finding.get("block") == block_name:
            findings.append(
                {
                    "rule": finding.get("rule"),
                    "severity": finding.get("severity"),
                    "title": finding.get("title"),
                }
            )
        elif finding.get("rule") == "multi_block_write" and block_name in (
            finding.get("blocks") or []
        ):
            findings.append(
                {
                    "rule": finding.get("rule"),
                    "severity": finding.get("severity"),
                    "title": finding.get("title"),
                }
            )
        if len(findings) >= _MAX_REVIEW_PER_BLOCK:
            break
    return findings


def _preset_questions(
    identity: dict[str, Any],
    callers: list[str],
    callees: list[str],
    reads: list[str],
    writes: list[str],
    logic: dict[str, Any],
    instances: list[str],
    review: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    name = identity.get("name")
    questions: list[dict[str, Any]] = []

    questions.append(
        {
            "q": f"谁调用 {name}？",
            "a": (
                "、".join(callers)
                if callers
                else "KG 中没有 CALLS 入边：可能由 OB 直接调用、被系统隐式调用，或调用点在保护块内。"
            ),
            "evidence": {"kind": "kg_calls_in", "block": name, "callers": callers},
        }
    )
    questions.append(
        {
            "q": f"{name} 调用了哪些块？",
            "a": "、".join(callees) if callees else "没有解析到对外调用（CALLS 出边为空）。",
            "evidence": {"kind": "kg_calls_out", "block": name, "callees": callees},
        }
    )
    questions.append(
        {
            "q": f"{name} 读/写哪些信号？",
            "a": (
                f"读 {len(reads)} 个：{'、'.join(reads[:10]) or '无'}；"
                f"写 {len(writes)} 个：{'、'.join(writes[:10]) or '无'}。"
            ),
            "evidence": {"kind": "kg_tag_io", "reads": reads[:25], "writes": writes[:25]},
        }
    )
    questions.append(
        {
            "q": f"{name} 的逻辑能完整翻译成 SCL 吗？",
            "a": (
                f"共 {logic.get('networks', 0)} 个网络、{logic.get('statements', 0)} 条折叠语句；"
                f"SCL 中有 {logic.get('scl_todo_comments', 0)} 处 TODO 注释"
                + ("，需要人工/LLM 补全。" if logic.get("scl_todo_comments") else "，规则翻译完整。")
            ),
            "evidence": {"kind": "folded_coverage", **logic},
        }
    )
    if review:
        questions.append(
            {
                "q": f"{name} 有什么确定性告警？",
                "a": "；".join(str(item.get("title") or "") for item in review),
                "evidence": {"kind": "review_findings", "findings": review},
            }
        )
    if identity.get("type") == "FB":
        questions.append(
            {
                "q": f"{name} 的实例情况？",
                "a": (
                    f"有 {len(instances)} 个实例数据块：{'、'.join(instances[:10])}"
                    if instances
                    else "没有找到实例数据块（可能是仅被多重实例引用）。"
                ),
                "evidence": {"kind": "kg_instances", "instances": instances[:25]},
            }
        )
    return questions


def build_block_dossiers(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build one dossier per parsed block; deterministic, JSON-safe, capped."""
    kg = job.get("knowledge_graph") or {}
    review = job.get("review")
    dossiers: dict[str, dict[str, Any]] = {}
    blocks = [b for b in (job.get("blocks") or []) if isinstance(b, dict) and b.get("name")]
    blocks.sort(key=lambda b: str(b.get("name") or ""))
    truncated = len(blocks) > _MAX_BLOCKS
    for block in blocks[:_MAX_BLOCKS]:
        name = str(block.get("name") or "")
        identity = {
            key: block.get(key)
            for key in (
                "name",
                "type",
                "number",
                "language",
                "comment",
                "instance_of",
                "protected",
                "interface_only",
                "body_available",
                "is_safety",
                "nest_depth",
            )
        }
        callers = callers_of(kg, name)
        callees = callees_of(kg, name)
        reads, writes = _io_tags(kg, name)
        instances = _instances(kg, name) if str(block.get("type") or "") == "FB" else []
        logic = _logic_summary(job, name)
        review_hits = _review_for_block(review, name)
        sample_lines, sample_evidence = _folded_lines(job, name)
        dossier = {
            "identity": identity,
            "callers": callers,
            "callees": callees,
            "reads": reads,
            "writes": writes,
            "instances": instances,
            "logic": logic,
            "review": review_hits,
            "sample_scl": sample_lines[:_MAX_SAMPLE_LINES],
            "sample_evidence": sample_evidence[:_MAX_SAMPLE_LINES],
            "questions": _preset_questions(
                identity, callers, callees, reads, writes, logic, instances, review_hits
            ),
        }
        dossiers[name] = dossier
    result: dict[str, Any] = {"blocks": dossiers}
    if truncated:
        result["truncated"] = True
        result["note"] = f"块数超过 {_MAX_BLOCKS}，仅保留排序后的前 {_MAX_BLOCKS} 个档案"
    return result


def dossier_for(job: dict[str, Any], block_name: str) -> dict[str, Any] | None:
    """Return one block's dossier, building it on demand when missing."""
    stored = (job.get("dossiers") or {}).get("blocks") or {}
    if stored.get(block_name):
        return stored[block_name]
    if any(b.get("name") == block_name for b in (job.get("blocks") or [])):
        single = build_block_dossiers({**job, "blocks": [b for b in job.get("blocks") or [] if b.get("name") == block_name]})
        return single.get("blocks", {}).get(block_name)
    return None
