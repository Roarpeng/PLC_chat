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
from dataclasses import dataclass, field
from typing import Any

#: statement kinds that overwrite their target on every scan when unguarded
_UNCONDITIONAL_KINDS = {"coil", "neg_coil", "move"}
_GUARDED_KINDS = {"set", "reset"}

_MAX_PER_RULE = 50
_MAX_UNUSED_PER_BLOCK = 10


@dataclass
class _RuleResult:
    """Findings to report plus the true match count, so truncation stays visible."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0

    @property
    def truncated(self) -> bool:
        return self.total > len(self.findings)


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


def _double_write_findings(job: dict[str, Any]) -> _RuleResult:
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
    result = _RuleResult()
    for (block, target), sites in sorted(writes.items()):
        if len(sites) < 2:
            continue
        result.total += 1
        if len(result.findings) >= _MAX_PER_RULE:
            continue
        result.findings.append(
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
    return result


def _multi_block_write_findings(job: dict[str, Any]) -> _RuleResult:
    writers: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for block, network_id, stmt in _iter_statements(job):
        if stmt.get("kind") not in _UNCONDITIONAL_KINDS or stmt.get("enable") is not None:
            continue
        target = _norm_target(stmt.get("target"))
        if not target:
            continue
        writers[target][block].add(network_id)
    result = _RuleResult()
    for target, by_block in sorted(writers.items()):
        if len(by_block) < 2:
            continue
        result.total += 1
        if len(result.findings) >= _MAX_PER_RULE:
            continue
        result.findings.append(
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
    return result


def _set_reset_findings(job: dict[str, Any]) -> _RuleResult:
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
    result = _RuleResult()
    for target, kinds in sorted(kinds_by_target.items()):
        has_set, has_reset = "set" in kinds, "reset" in kinds
        if has_set and has_reset:
            continue
        result.total += 1
        if len(result.findings) >= _MAX_PER_RULE:
            continue
        missing = "RESET" if has_set else "SET"
        present = "SET" if has_set else "RESET"
        result.findings.append(
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
    return result


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


def _orphan_tag_findings(job: dict[str, Any]) -> _RuleResult:
    readers, writers = _tag_access_maps(job)
    result = _RuleResult()
    for ref in sorted(set(writers) - set(readers)):
        result.total += 1
        if len(result.findings) >= _MAX_PER_RULE:
            continue
        result.findings.append(
            {
                "rule": "tag_write_never_read",
                "severity": "info",
                "target": ref,
                "title": f"{ref} 只被写入，从未被读取",
                "detail": "可能是遗留输出、仅供 HMI/调试观察，或读取方在保护块内。",
                "evidence": [{"tag": ref, "writers": sorted(writers[ref])}],
            }
        )
    for ref in sorted(set(readers) - set(writers)):
        result.total += 1
        if len(result.findings) >= _MAX_PER_RULE:
            continue
        result.findings.append(
            {
                "rule": "tag_read_never_written",
                "severity": "info",
                "target": ref,
                "title": f"{ref} 只被读取，工程内无人写入",
                "detail": "可能来自 HMI / OPC UA / 通信写入，否则为常量或未接线信号。",
                "evidence": [{"tag": ref, "readers": sorted(readers[ref])}],
            }
        )
    return result


def _member_name(member: Any) -> str:
    raw = str(member or "").strip()
    if not raw:
        return ""
    return raw.split(":", 1)[0].strip()


def _unused_member_findings(job: dict[str, Any]) -> _RuleResult:
    result = _RuleResult()
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
        unused_total = 0
        for member in block.get("members") or []:
            member_name = _member_name(member)
            if not member_name:
                continue
            pattern = re.compile(
                r"(?<![A-Za-z0-9_])" + re.escape(member_name) + r"(?![A-Za-z0-9_])"
            )
            if pattern.search(body_blob):
                continue
            unused_total += 1
            if len(unused) < _MAX_UNUSED_PER_BLOCK:
                unused.append(member_name)
        if not unused_total:
            continue
        result.total += 1
        if len(result.findings) >= _MAX_PER_RULE:
            continue
        detail = "未使用的接口成员增加维护成本；也可能是解析覆盖不足导致的误报，请结合证据判断。"
        finding: dict[str, Any] = {
            "rule": "unused_member",
            "severity": "info",
            "block": name,
            "title": f"{name} 有 {unused_total} 个接口成员未在逻辑中出现",
            "detail": detail,
            "evidence": [{"block": name, "members": unused}],
        }
        if unused_total > len(unused):
            finding["truncated"] = True
            finding["total_count"] = unused_total
            finding["detail"] = (
                detail + f"此处仅列出前 {len(unused)} 个，实际共 {unused_total} 个。"
            )
        result.findings.append(finding)
    return result


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
    rules: dict[str, dict[str, Any]] = {}
    for rule, fn in _RULES.items():
        try:
            outcome = fn(job)
        except Exception:  # noqa: BLE001 — one broken rule must not sink the rest
            findings.append(
                {
                    "rule": rule,
                    "severity": "info",
                    "title": f"规则 {rule} 执行失败（已跳过）",
                    "evidence": [],
                }
            )
            rules[rule] = {"shown": 0, "total_count": 0, "truncated": False, "error": True}
            continue
        findings.extend(outcome.findings)
        shown = len(outcome.findings)
        rules[rule] = {
            "shown": shown,
            "total_count": int(outcome.total),
            "truncated": outcome.truncated,
        }
        if outcome.truncated:
            findings.append(
                {
                    "rule": rule,
                    "severity": "info",
                    "truncated": True,
                    "total_count": int(outcome.total),
                    "shown_count": shown,
                    "title": (
                        f"此规则实际命中 {outcome.total} 处，"
                        f"报告仅展示前 {shown} 处（已截断）"
                    ),
                    "detail": (
                        "为避免报告无限膨胀，每条规则最多展示固定条数；"
                        "请不要把这里的条数当作问题总数，真实命中数见 total_count。"
                    ),
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
    total_count = sum(int(row.get("total_count") or 0) for row in rules.values())
    return {
        "ok": True,
        "engine": "deterministic-review-rules",
        "findings": findings,
        "summary": {**summary, "by_rule": by_rule},
        "truncated": any(bool(row.get("truncated")) for row in rules.values()),
        "total_count": total_count,
        "rules": rules,
    }


def format_review_markdown(result: dict[str, Any]) -> str:
    """Render a review result as a compact markdown section."""
    lines = ["## 确定性审查", ""]
    summary = result.get("summary") or {}
    lines.append(
        f"- 发现 {summary.get('total', 0)} 项"
        f"（警告 {summary.get('warning', 0)} / 提示 {summary.get('info', 0)}）"
    )
    if result.get("truncated"):
        lines.append(
            f"- ⚠ 报告已截断：真实命中 {result.get('total_count', 0)} 处，"
            "各规则仅展示前若干条（见每条规则下方的截断提示）"
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
