"""Validate and resolve typed signal paths separately from execution edges."""
from __future__ import annotations

from collections import Counter

from plc_engine.engineering_ir.station_ports import DEFAULTS, NON_EXECUTABLE, STATION_PORTS, station_node_ports


class SignalGraph:
    def __init__(self, flow, station, stations, profiles):
        self.flow = flow
        self.station = station
        self.nodes = {item.id: item for item in flow.nodes}
        self.ports = {key: station_node_ports(item, station, stations, profiles) for key, item in self.nodes.items()}
        self.writers = {(item.to_id, item.to_port): item for item in flow.wires}

    def wired(self, node_id, port):
        return (node_id, port) in self.writers

    def input(self, node_id, key, external, logic, literal):
        wire = self.writers.get((node_id, key))
        if wire:
            return self.output(wire.from_id, wire.from_port, external, logic, literal)
        port = self.ports[node_id][key]
        return literal(port.type, DEFAULTS[port.type] if port.default is None else port.default)

    def output(self, node_id, key, external, logic, literal):
        node = self.nodes[node_id]
        port = self.ports[node_id][key]
        if node.kind == "logic":
            values = [self.input(node.id, item.id, external, logic, literal) for item in node.ports]
            return logic(node.operator, values)
        return external(node, key, port)


def signal_issues(graph: SignalGraph, *, release: bool = False):
    nodes, station, issues = graph.nodes, graph.station, []

    def report(key, reason):
        issues.append({"node_id": key, "source_id": key, "reason": reason, "field": "ports"})

    def check_definitions(owner, definitions, reserved):
        keys = [item.id.casefold() for item in definitions]
        if len(set(keys)) != len(keys) or set(keys).intersection(reserved):
            report(owner, "端口标识重复或与系统端口重名。")

    if station:
        check_definitions(station.id, station.public_ports, STATION_PORTS.keys())
    interfaces = [item for item in nodes.values() if item.kind == "interface"]
    if len(interfaces) > 1:
        report(interfaces[1].id, "每个工位使用一个工位接口节点。")
    devices = Counter(item.device_id for item in nodes.values() if item.kind == "device")
    for node in nodes.values():
        if node.ports and node.kind != "logic":
            report(node.id, "可变信号输入用于逻辑节点。")
        if node.kind == "device" and devices[node.device_id] > 1:
            report(node.id, "每个设备使用一个完整驱动接口节点。")
        if node.kind == "logic":
            check_definitions(node.id, node.ports, {"result"})
            types = [item.type for item in node.ports]
            if any(item.direction != "input" for item in node.ports):
                report(node.id, "逻辑节点的自定义项需要定义为输入。")
            if release:
                valid = ((node.operator in ("and", "or") and len(types) >= 2 and set(types) == {"BOOL"})
                         or (node.operator == "not" and types == ["BOOL"])
                         or (node.operator == "eq" and len(types) == 2 and len(set(types)) == 1)
                         or (node.operator in ("gt", "lt") and len(types) == 2 and len(set(types)) == 1
                             and types[0] in ("DINT", "TIME")))
                if not valid:
                    report(node.id, "请按逻辑运算选择匹配的输入类型和数量。")

    targets, dependencies = set(), {key: set() for key in nodes}
    for wire in graph.flow.wires:
        source = graph.ports.get(wire.from_id, {}).get(wire.from_port)
        target = graph.ports.get(wire.to_id, {}).get(wire.to_port)
        if not source or not target or source.direction != "output" or target.direction != "input":
            report(wire.id, "信号线需要从有效输出连接到同一画布的有效输入。")
            continue
        if source.type != target.type:
            report(wire.id, f"信号类型不匹配（{source.type} → {target.type}）。")
        endpoint = (wire.to_id, wire.to_port)
        if endpoint in targets:
            report(wire.id, "每个信号输入只接受一个来源。")
        targets.add(endpoint)
        dependencies[wire.to_id].add(wire.from_id)
    if release and station:
        interface = interfaces[0] if interfaces else None
        for port in station.public_ports:
            if port.direction == "output" and port.default is None and (not interface or not graph.wired(interface.id, port.id)):
                report(interface.id if interface else station.id, f"请连接工位输出「{port.name}」，或设定默认值。")
    states = {}

    def visit(key):
        if states.get(key) == 1:
            report(key, "信号线形成循环，请显式使用已确认的状态或拆开反馈路径。")
            return
        if states.get(key) == 2:
            return
        states[key] = 1
        for parent in sorted(dependencies[key]):
            visit(parent)
        states[key] = 2

    for key in nodes:
        visit(key)
    return issues
