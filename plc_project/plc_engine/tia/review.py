"""Deterministic PLC review rules — folded logic + KG edges in, findings out.

Complements ``analyst`` (which already covers dead blocks, missing interlocks,
safety mixing and nested-FB findings). This module encodes the classic
LAD/SCL defect patterns that only folded statements can prove:

- ``double_write``      one block assigns the same target unconditionally in
                        ≥2 places (classic double-coil; last scan wins);
- ``multi_block_write`` ≥2 blocks write the same tag unconditionally;
- ``set_reset_unpaired`` a target is SET but never RESET (or vice versa);
- ``tag_write_never_read`` / ``tag_read_never_written`` — orphan signals;
- ``unused_member``     interface member never referenced in block logic.

Evidence-gated like the rest of the pipeline: every finding carries the
statements / KG edges that triggered it, no LLM involved, no CALLS invented.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

#: statement kinds that overwrite their target on every scan when unguarded
_UNCONDITIONAL_KINDS = {"coil", "neg_coil", "move"}
_GUARDED_KINDS = {"set", "reset"}

_MAX_PER_RULE = 50
_MAX_UNUSED_PER_BLOCK = 10


def _norm_target(raw: Any) -> str:
    target = str(raw or "").strip()
    if not target or "TODO" in target or target.startswith("(*"):
        return ""
    return target


def _block_networks(job: dict[str, Any], block_name: str) -> list[dict[str, Any]]:
    return (job.get("folded_logic") or {}).get(block_name) or []


def _iter_statements(job: dict[str, Any]):
    """Yield (block, network_id, statement) for every folded statement."""
    for block_name, networks in (job.get("folded_logic") or {}).items():
        if not isinstance(networks, list):
            continue
        for network in networks:
            if not isinstance(network, dict):
                continue
            network_id = str(network.get("network_id") or "")
            for statement in network.get("statements") or []:
                if isinstance(statement, dict):
                    yield block_name, network_id, statement


def _double_write_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    writes: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for block, network_id, stmt in _iter_statements(job):
        if stmt.get("kind") not in _UNCONDITIONAL_KINDS or stmt.get("enable") is not None:
            continue
        target = _norm_target(stmt.get("target"))
        if not target:
            continue
        writes[(block, target)].append(
            {
                "block": block,
                "network_id": network_id,
                "kind": str(stmt.get("kind") or ""),
                "target": target,
            }
        )
    findings: list[dict[str, Any]] = []
    for (block, target), sites in sorted(writes.items()):
        if len(sites) < 2:
            continue
        findings.append(
            {
                "rule": "double_write",
                "severity": "warning",
                "block": block,
                "target": target,
                "title": f"{block} 无条件写入 {target} 共 {len(sites)} 处（双线圈/覆盖写）",
                "detail": (
                    "同一目标在不止一处被无条件赋值，扫描周期内后写的会覆盖先写的，"
                    "是 LAD 双线圈 / SCL 顺序覆盖的典型缺陷。"
                ),
                "evidence": sites,
            }
        )
        if len(findings) >= _MAX_PER_RULE:
            break
    return findings


def _multi_block_write_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    writers: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for block, network_id, stmt in _iter_statements(job):
        if stmt.get("kind") not in _UNCONDITIONAL_KINDS or stmt.get("enable") is not None:
            continue
        target = _norm_target(stmt.get("target"))
        if not target:
            continue
        writers[target][block].add(network_id)
    findings: list[dict[str, Any]] = []
    for target, by_block in sorted(writers.items()):
        if len(by_block) < 2:
            continue
        findings.append(
            {
                "rule": "multi_block_write",
                "severity": "warning",
                "target": target,
                "blocks": sorted(by_block),
                "title": f"{target} 被 {len(by_block)} 个块无条件写入",
                "detail": "跨块覆盖写容易形成隐性耦合，应收敛为单一写入者或显式协调。",
                "evidence": [
                    {"block": block, "network_ids": sorted(nets)}
                    for block, nets in sorted(by_block.items())
                ],
            }
        )
        if len(findings) >= _MAX_PER_RULE:
            break
    return findings


def _set_reset_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    kinds_by_target: dict[str, set[str]] = defaultdict(set)
    sites: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for block, network_id, stmt in _iter_statements(job):
        if stmt.get("kind") not in _GUARDED_KINDS:
            continue
        target = _norm_target(stmt.get("target"))
        if not target:
            continue
        kinds_by_target[target].add(str(stmt.get("kind")))
        sites[target][str(stmt.get("kind"))].append(
            {"block": block, "network_id": network_id}
        )
    findings: list[dict[str, Any]] = []
    for target, kinds in sorted(kinds_by_target.items()):
        has_set, has_reset = "set" in kinds, "reset" in kinds
        if has_set and has_reset:
            continue
        missing = "RESET" if has_set else "SET"
        present = "SET" if has_set else "RESET"
        findings.append(
            {
                "rule": "set_reset_unpaired",
                "severity": "info",
                "target": target,
                "title": f"{target} 只有 {present}，没有配对的 {missing}",
                "detail": (
                    "置位/复位不成对时，目标一旦进入该状态可能无法回到初始值，"
                    "请确认是否有意为之（如锁存到断电）。"
                ),
                "evidence": [
                    site
                    for kind in ("set", "reset")
                    for site in sites[target].get(kind, [])
                ],
            }
        )
        if len(findings) >= _MAX_PER_RULE:
            break
    return findings


def _tag_access_maps(job: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    readers: dict[str, set[str]] = defaultdict(set)
    writers: dict[str, set[str]] = defaultdict(set)
    for edge in (job.get("knowledge_graph") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target") or "")
        if not target.startswith("Tag::"):
            continue
        ref = target.removeprefix("Tag::")
        block = str(edge.get("source") or "").split("::", 1)[-1]
        if edge.get("type") == "READS":
            readers[ref].add(block)
        elif edge.get("type") == "WRITES":
            writers[ref].add(block)
    return readers, writers


def _orphan_tag_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    readers, writers = _tag_access_maps(job)
    findings: list[dict[str, Any]] = []
    for ref in sorted(set(writers) - set(readers)):
        findings.append(
            {
                "rule": "tag_write_never_read",
                "severity": "info",
                "target": ref,
                "title": f"{ref} 只被写入，从未被读取",
                "detail": "可能是遗留输出、仅供 HMI/调试观察，或读取方在保护块内。",
                "evidence": [{"tag": ref, "writers": sorted(writers[ref])}],
            }
        )
        if len(findings) >= _MAX_PER_RULE:
            break
    for ref in sorted(set(readers) - set(writers)):
        findings.append(
            {
                "rule": "tag_read_never_written",
                "severity": "info",
                "target": ref,
                "title": f"{ref} 只被读取，工程内无人写入",
                "detail": "可能来自 HMI / OPC UA / 通信写入，否则为常量或未接线信号。",
                "evidence": [{"tag": ref, "readers": sorted(readers[ref])}],
            }
        )
        if len(findings) >= _MAX_PER_RULE:
            break
    return findings


def _member_name(member: Any) -> str:
    raw = str(member or "").strip()
    if not raw:
        return ""
    return raw.split(":", 1)[0].strip()


def _unused_member_findings(job: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    scl_sources = job.get("scl_sources") or {}
    for block in job.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        name = str(block.get("name") or "")
        block_type = str(block.get("type") or "")
        if not name or block_type in {"DB", "UDT", "OB"}:
            continue
        if block.get("interface_only") or block.get("protected") or not block.get("body_available"):
            continue
        body_blob = json.dumps(_block_networks(job, name), ensure_ascii=False, default=str)
        body_blob += "\n" + str(scl_sources.get(name) or "")
        unused: list[str] = []
        for member in block.get("members") or []:
            member_name = _member_name(member)
            if not member_name:
                continue
            pattern = re.compile(
                r"(?<![A-Za-z0-9_])" + re.escape(member_name) + r"(?![A-Za-z0-9_])"
            )
            if not pattern.search(body_blob):
                unused.append(member_name)
            if len(unused) >= _MAX_UNUSED_PER_BLOCK:
                break
        if unused:
            findings.append(
                {
                    "rule": "unused_member",
                    "severity": "info",
                    "block": name,
                    "title": f"{name} 有 {len(unused)} 个接口成员未在逻辑中出现",
                    "detail": "未使用的接口成员增加维护成本；也可能是解析覆盖不足导致的误报，请结合证据判断。",
                    "evidence": [{"block": name, "members": unused}],
                }
            )
        if len(findings) >= _MAX_PER_RULE:
            break
    return findings


_RULES = {
    "double_write": _double_write_findings,
    "multi_block_write": _multi_block_write_findings,
    "set_reset_unpaired": _set_reset_findings,
    "tag_write_never_read": _orphan_tag_findings,  # also emits tag_read_never_written
    "unused_member": _unused_member_findings,
}


def run_review(job: dict[str, Any]) -> dict[str, Any]:
    """Run every deterministic rule against a parsed PLC job record."""
    findings: list[dict[str, Any]] = []
    for rule, fn in _RULES.items():
        try:
            findings.extend(fn(job))
        except Exception:  # noqa: BLE001 — one broken rule must not sink the rest
            findings.append(
                {
                    "rule": rule,
                    "severity": "info",
                    "title": f"规则 {rule} 执行失败（已跳过）",
                    "evidence": [],
                }
            )
    summary: dict[str, int] = {"total": len(findings), "warning": 0, "info": 0}
    by_rule: dict[str, int] = {}
    for finding in findings:
        rule = str(finding.get("rule") or "unknown")
        by_rule[rule] = by_rule.get(rule, 0) + 1
        severity = str(finding.get("severity") or "info")
        if severity in summary:
            summary[severity] += 1
    return {
        "ok": True,
        "engine": "deterministic-review-rules",
        "findings": findings,
        "summary": {**summary, "by_rule": by_rule},
    }


def format_review_markdown(result: dict[str, Any]) -> str:
    """Render a review result as a compact markdown section."""
    lines = ["## 确定性审查", ""]
    summary = result.get("summary") or {}
    lines.append(
        f"- 发现 {summary.get('total', 0)} 项"
        f"（警告 {summary.get('warning', 0)} / 提示 {summary.get('info', 0)}）"
    )
    lines.append("")
    for finding in result.get("findings") or []:
        severity = "⚠️" if finding.get("severity") == "warning" else "ℹ️"
        where = finding.get("block") or finding.get("target") or ""
        lines.append(f"- {severity} **[{finding.get('rule')}]** {finding.get('title')}")
        if where:
            lines.append(f"  - 位置: `{where}`")
        if finding.get("detail"):
            lines.append(f"  - {finding.get('detail')}")
    return "\n".join(lines)
