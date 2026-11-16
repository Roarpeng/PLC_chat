"""Resolve explicit fork and join edges into structured parallel regions."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plc_engine.engineering_ir.station_design import Flow, Node


@dataclass(frozen=True)
class ParallelRegion:
    branches: tuple[Node, ...]
    join_id: str


def parallel_regions(flow: Flow, *, project: bool) -> tuple[dict[str, ParallelRegion], list[tuple[str, str]]]:
    nodes = {node.id: node for node in flow.nodes}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge in flow.edges:
        incoming[edge.to_id].append(edge)
        outgoing[edge.from_id].append(edge)
    regions, issues, used_joins = {}, [], set()
    success = "done" if project else "next"
    for fork in (node for node in flow.nodes if node.kind == "fork"):
        edges = [edge for edge in outgoing[fork.id] if edge.outcome == "branch"]
        if len(edges) < 2:
            issues.append((fork.id, "并行分支至少需要连接两个节点。"))
            continue
        members = [nodes.get(edge.to_id) for edge in edges]
        expected_kind = "station" if project else "action"
        if any(not item or item.kind != expected_kind or (not project and not item.actions) for item in members):
            issues.append((fork.id, "项目并行分支请直接连接工位；工位并行分支请直接连接预设设备动作。"))
            continue
        join_edges = [edge for member in members for edge in outgoing[member.id] if edge.outcome == success]
        targets = {edge.to_id for edge in join_edges}
        join = nodes.get(next(iter(targets))) if len(targets) == 1 else None
        if not join or join.kind != "join" or len(join_edges) != len(members):
            issues.append((fork.id, "每条并行分支的完成出口都需要接到同一个汇合节点。"))
            continue
        if (join.id in used_joins or flow.start in {join.id, *(item.id for item in members)}
                or any(incoming[member.id] != [edge] for member, edge in zip(members, edges))
                or {item.id for item in incoming[join.id]} != {item.id for item in join_edges}):
            issues.append((fork.id, "并行分支或汇合有额外入口。请从并行起点进入完整的分支组。"))
            continue
        if any(edge.to_id == fork.id for member in members for edge in outgoing[member.id]):
            issues.append((fork.id, "并行分支重试前请先连接恢复节点。"))
        owners = {}
        for member in members:
            resources = member.station_ids if project else [action.device_id for action in member.actions]
            for resource in resources:
                if resource in owners:
                    previous = owners[resource]
                    reason = f"「{previous.name}」与「{member.name}」在同一并行组调用同一{'工位' if project else '设备'}。"
                    issues.extend([(previous.id, reason), (member.id, reason)])
                owners[resource] = member
        regions[fork.id] = ParallelRegion(tuple(members), join.id)
        used_joins.add(join.id)
    for node in flow.nodes:
        if node.kind == "join" and node.id not in used_joins:
            issues.append((node.id, "汇合节点需要对应一个完整的并行分支组。"))
    return regions, issues
