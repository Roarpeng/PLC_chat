"""SCL expressions for validated typed connections."""
from __future__ import annotations

from plc_engine.engineering_ir.station_catalog import PROFILES
from plc_engine.engineering_ir.station_ports import CYLINDER_OUTPUTS, STATION_OUTPUTS, scl_value
from plc_engine.engineering_ir.station_signals import SignalGraph


def _scl_logic(operator, values):
    if operator == "not":
        return f"(NOT ({values[0]}))"
    token = {"and": "AND", "or": "OR", "eq": "=", "gt": ">", "lt": "<"}[operator]
    return "(" + f" {token} ".join(f"({value})" for value in values) + ")"


class SignalLowering:
    def __init__(self, flow, station, stations, *, names=None):
        self.graph = SignalGraph(flow, station, stations, PROFILES)
        self.names = names or {}

    def source(self, node, port, _type):
        if node.kind == "interface":
            return f"#X_{port}"
        if node.kind in ("station", "handoff"):
            member = STATION_OUTPUTS.get(port, f"X_{port}")
            return f'"DB_{self.names[node.station_ids[0]]}".{member}'
        device_id = node.actions[0].device_id if node.actions else node.device_id
        field = CYLINDER_OUTPUTS[port][0] if port in CYLINDER_OUTPUTS else "Fault" if port == "fault" else f"State_{port[3:]}"
        return f"#D_{device_id}.{field}"

    def input(self, node_id, port, unbound=None):
        if unbound is not None and not self.graph.wired(node_id, port):
            return unbound
        return self.graph.input(node_id, port, self.source, _scl_logic, scl_value)
