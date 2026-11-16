"""Deterministic edits for the shared project and station graphs."""
from __future__ import annotations

import re
from uuid import uuid4

from plc_engine.engineering_ir.station_catalog import PROFILES
from plc_engine.engineering_ir.station_design import Edge, Flow, Node, Permission, Station, StationDesign, outcomes
from plc_engine.engineering_ir.station_ports import NON_EXECUTABLE, SignalWire
from plc_engine.engineering_ir.station_signals import SignalGraph

EXITS = {"继续": "next", "完成": "done", "成立": "true", "不成立": "false", "超时": "timeout",
         "故障": "fault", "互锁失效": "blocked", "分支": "branch"}


def _key(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _node(kind: str, name: str, **fields) -> Node:
    return Node(id=_key("node"), name=name, kind=kind, **fields)


def _wire(flow: Flow, source: Node, outcome: str, target: Node) -> None:
    if source.id == target.id or outcome not in outcomes(source):
        raise ValueError(f"「{source.name}」没有可用于这条连线的出口。")
    existing = next((edge for edge in flow.edges
                     if edge.from_id == source.id and edge.outcome == outcome
                     and (outcome != "branch" or edge.to_id == target.id)), None)
    if existing:
        existing.to_id = target.id
    else:
        flow.edges.append(Edge(id=_key("edge"), from_id=source.id, outcome=outcome, to_id=target.id))


def reconnect_flow(flow: Flow, message: str, selected: str) -> str | None:
    match = re.fullmatch(r"(?:把|将)?[「“]([^」”]+)[」”]的?(继续|完成|成立|不成立|超时|故障|互锁失效|分支)(?:出口)?(?:改)?(?:连到|接到|连接到)[「“]([^」”]+)[」”][。！!]?", message)
    if not match:
        return None
    source_choices = [item for item in flow.nodes if item.name == match[1]]
    source = next((item for item in source_choices if item.id == selected), None)
    target_choices = [item for item in flow.nodes if item.name == match[3]]
    if (source is None and len(source_choices) != 1) or len(target_choices) != 1:
        raise ValueError("请使用画布上唯一的节点名称，或先选中要改接的源节点。")
    source = source or source_choices[0]
    outcome = EXITS[match[2]]
    if outcome == "done" and source.kind == "action":
        outcome = "next"
    _wire(flow, source, outcome, target_choices[0])
    return f"把「{source.name}」的{match[2]}出口连接到「{target_choices[0].name}」。"


def connect_signal(design: StationDesign, station: Station | None, message: str) -> str | None:
    match = re.fullmatch(r"(?:把|将)[「“]([^」”]+)[」”]的[「“]([^」”]+)[」”](?:信号)?(?:改)?(?:连到|接到|连接到)[「“]([^」”]+)[」”]的[「“]([^」”]+)[」”][。！!]?", message)
    if not match:
        return None
    flow = station.flow if station else design.flow
    graph = SignalGraph(flow, station, {item.id: item for item in design.stations}, PROFILES)
    selected = []
    for name, label, direction in ((match[1], match[2], "output"), (match[3], match[4], "input")):
        options = [(item.id, key, port) for item in flow.nodes if item.name == name
                   for key, port in graph.ports[item.id].items() if port.direction == direction and label in (key, port.label)]
        if len(options) != 1:
            raise ValueError(f"请检查「{name}」的信号端口「{label}」。")
        selected.append(options[0])
    (source, out, left), (target, inlet, right) = selected
    if source == target or left.type != right.type:
        raise ValueError(f"信号需要连接不同节点且类型一致（{left.type} → {right.type}）。")
    previous = graph.writers.get((target, inlet))
    if previous:
        previous.from_id, previous.from_port = source, out
    else:
        flow.wires.append(SignalWire(id=_key("wire"), from_id=source, from_port=out, to_id=target, to_port=inlet))
    return f"连接「{match[1]} · {match[2]}」与「{match[3]} · {match[4]}」。"


def _stations_from_text(stations: list[Station], text: str) -> list[Station]:
    quotes = re.findall(r"[「“]([^」”]+)[」”]", text)
    if quotes:
        exact = [[item for item in stations if item.name == name] for name in quotes]
        if any(len(choices) != 1 for choices in exact):
            raise ValueError("请用引号标出已存在且名称唯一的工位。")
        return [choices[0] for choices in exact]
    matches = [(text.index(item.name), -len(item.name), item) for item in stations if item.name in text]
    chosen = []
    end = -1
    for start, length, item in sorted(matches, key=lambda match: match[:2]):
        if start >= end:
            chosen.append(item)
            end = start - length
    return chosen


def describe_project_flow(design: StationDesign, message: str) -> str | None:
    replace = bool(re.match(r"^(?:重新生成|重建|替换)项目(?:流程|画布)", message))
    if any(node.kind not in NON_EXECUTABLE for node in design.flow.nodes) and not replace:
        return None
    if not replace and not re.search(r"先|再|然后|依次|完成后|并行|同时", message):
        return None
    if re.search(r"如果|否则|除非|失败|超时", message):
        return None
    parts = re.split(r"汇合后|全部完成后|都完成后", message, maxsplit=1)
    first = _stations_from_text(design.stations, parts[0])
    following = _stations_from_text(design.stations, parts[1]) if len(parts) > 1 else []
    if len(first) + len(following) < 2:
        return None
    simultaneous = bool(re.search(r"并行|同时", parts[0]))
    if simultaneous and (len(first) < 2 or len({item.id for item in first}) != len(first)):
        raise ValueError("并行分支需要两个或更多不同的工位。")
    if simultaneous and len(parts) == 1 and re.search(r"然后|接着|随后|再(?:运行|执行|启动)", parts[0]):
        raise ValueError("请用「汇合后」明确哪些工位在并行组之后执行。")
    entry = _node("start", "项目开始")
    finish = _node("done", "项目完成")
    failed = _node("fault", "项目故障")
    existing = [item for item in design.flow.nodes if item.kind in NON_EXECUTABLE]
    ids = {item.id for item in existing}
    graph = Flow(start=entry.id, nodes=[entry], wires=[
        wire for wire in design.flow.wires if wire.from_id in ids and wire.to_id in ids
    ])
    cursor, exit_ = entry, "next"
    if simultaneous:
        fork = _node("fork", "并行分支")
        join = _node("join", "全部汇合")
        graph.nodes.append(fork)
        _wire(graph, entry, "next", fork)
        for station in first:
            arm = _node("station", station.name, station_ids=[station.id])
            graph.nodes.append(arm)
            _wire(graph, fork, "branch", arm)
            _wire(graph, arm, "done", join)
            _wire(graph, arm, "fault", failed)
        graph.nodes.append(join)
        cursor = join
    for station in following if simultaneous else [*first, *following]:
        call = _node("station", station.name, station_ids=[station.id])
        graph.nodes.append(call)
        _wire(graph, cursor, exit_, call)
        _wire(graph, call, "fault", failed)
        cursor, exit_ = call, "done"
    graph.nodes.extend([finish, failed, *existing])
    _wire(graph, cursor, exit_, finish)
    design.flow = graph
    return f"编排 {len(first) + len(following)} 个工位调用及故障分支。"


def describe_permission(station: Station, message: str) -> str | None:
    if "互锁" not in message and "运行许可" not in message:
        return None
    names = re.findall(r"[「“]([^」”]+)[」”]", message)
    if len(names) != 2:
        return None
    actions = [item for item in station.flow.nodes if item.kind == "action" and item.name == names[0]]
    feedback = [(device, port) for device in station.devices for port, direction in PROFILES[device.driver]["ports"].items()
                if direction == "input" and device.name + " · " + PROFILES[device.driver]["port_labels"][port] == names[1]]
    if len(actions) != 1 or len(feedback) != 1:
        raise ValueError("请写出画布中的动作节点名称和设备反馈全名。")
    node = actions[0]
    device, port = feedback[0]
    mode = "continuous" if "持续" in message or "运行中" in message else "start"
    blocked = "fault" if "立即故障" in message else "wait"
    rule = Permission(id=_key("permission"), device_id=device.id, port=port,
                      value=not bool(re.search("无效|为假", message)), mode=mode, blocked=blocked)
    node.permissions = [item for item in node.permissions if (item.device_id, item.port, item.mode) != (rule.device_id, rule.port, rule.mode)]
    node.permissions.append(rule)
    if "blocked" in outcomes(node) and not any(edge.from_id == node.id and edge.outcome == "blocked" for edge in station.flow.edges):
        fault = next((item for item in station.flow.nodes if item.kind == "fault" and item.name == "互锁失效"), None)
        if fault is None:
            fault = _node("fault", "互锁失效")
            station.flow.nodes.append(fault)
        _wire(station.flow, node, "blocked", fault)
    return f"为「{node.name}」设置运行许可。"
