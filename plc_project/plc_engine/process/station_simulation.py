"""Offline flow traces with deterministic simulated feedback."""
from __future__ import annotations

from plc_engine.engineering_ir.station_design import Flow, StationDesign

SCENARIOS = ("normal_cycle", "feedback_timeout", "negative_feedback", "interlock_lost")


def simulate_design(design: StationDesign, scenario: str, *, station_id: str = "") -> list[dict]:
    if scenario not in SCENARIOS:
        raise KeyError(scenario)

    remaining = 3000

    def run(flow: Flow, start_ms: int, scope: str, project: bool = False):
        nonlocal remaining
        nodes = {node.id: node for node in flow.nodes}
        links = {(edge.from_id, edge.outcome): edge.to_id for edge in flow.edges}
        key, time = flow.start, start_ms
        frames = []
        for _ in range(600):
            if remaining <= 0:
                break
            remaining -= 1
            node = nodes.get(key)
            if node is None:
                return time, "fault", frames
            frames.append({"time_ms": time, "node_id": key, "station_id": scope,
                           "event": node.kind, "name": node.name})
            if node.kind in ("done", "fault"):
                return time, node.kind, frames
            time += 10
            outcome = "next"
            if project:
                batch = [run_station(id_, time) for id_ in node.station_ids]
                first_fault = min((end for end, result, _ in batch if result == "fault"), default=None)
                for _, _, branch in batch:
                    frames.extend(frame for frame in branch if first_fault is None or frame["time_ms"] <= first_fault)
                time = first_fault if first_fault is not None else max(end for end, _, _ in batch)
                outcome = "fault" if first_fault is not None else "done"
            elif node.kind == "wait" or (node.kind == "action" and node.completion):
                if node.device_id or node.completion:
                    if scenario == "feedback_timeout":
                        time += node.timeout_ms
                        outcome = "timeout"
                else:
                    time += node.duration_ms
            elif node.kind == "decision":
                outcome = "false" if scenario == "negative_feedback" else "true"
            frames.append({"time_ms": time, "node_id": key, "station_id": scope,
                           "event": outcome, "name": node.name})
            key = links.get((key, outcome))
        frames.append({"time_ms": time, "node_id": key, "station_id": scope,
                       "event": "limit", "name": "达到仿真步数上限"})
        return time, "fault", frames

    def run_station(id_: str, time: int):
        station = stations[id_]
        if scenario == "interlock_lost" and station.interlocks:
            condition = station.interlocks[0]
            return time, "fault", [{"time_ms": time, "node_id": condition.id, "station_id": id_,
                                     "event": "interlock", "name": condition.name}]
        return run(station.flow, time, id_)

    stations = {station.id: station for station in design.stations}
    _, _, trace = run_station(station_id, 0) if station_id else run(design.flow, 0, "project", True)
    return sorted(trace, key=lambda item: item["time_ms"])
