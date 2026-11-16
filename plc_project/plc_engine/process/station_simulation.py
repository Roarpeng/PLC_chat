"""Offline flow traces with deterministic simulated feedback."""
from __future__ import annotations

from plc_engine.engineering_ir.station_design import Flow, Node, StationDesign
from plc_engine.engineering_ir.station_parallel import parallel_regions
from plc_engine.engineering_ir.station_catalog import PROFILES
from plc_engine.engineering_ir.station_ports import DEFAULTS
from plc_engine.engineering_ir.station_signals import SignalGraph
from plc_engine.process.station_cylinder import ALARM_EXTEND_TIMEOUT, ALARM_RETRACT_TIMEOUT

SCENARIOS = ("normal_cycle", "feedback_timeout", "negative_feedback", "interlock_blocked", "interlock_lost", "handoff_timeout")


def _evaluate(operator, values):
    if operator == "and":
        return all(values)
    if operator == "or":
        return any(values)
    if operator == "not":
        return not values[0]
    a, b = values
    return a == b if operator == "eq" else a > b if operator == "gt" else a < b


def simulate_design(design: StationDesign, scenario: str, *, station_id: str = "") -> list[dict]:
    if scenario not in SCENARIOS:
        raise KeyError(scenario)
    stations = {item.id: item for item in design.stations}
    remaining = 3000
    project_graph = SignalGraph(design.flow, None, stations, PROFILES)
    local = {item.id: SignalGraph(item.flow, item, stations, PROFILES) for item in design.stations}
    published, assigned, device_state = {}, {}, {}

    def frame(time, scope, node, event, name=None):
        return {"time_ms": time, "node_id": node.id, "station_id": scope,
                "event": event, "name": node.name if name is None else name}

    def values(scope, node, port, descriptor):
        if node.kind == "interface":
            return assigned[scope].get(port, DEFAULTS[descriptor.type] if descriptor.default is None else descriptor.default)
        if node.kind in ("station", "handoff"):
            return published.get(node.station_ids[0], {}).get(port, port == "ready" if descriptor.type == "BOOL" else DEFAULTS[descriptor.type])
        key = node.actions[0].device_id if node.actions else node.device_id
        state = device_state.get((scope, key), {})
        if port.startswith("fb_"):
            return state.get(port, scenario not in ("negative_feedback", "feedback_timeout"))
        return state.get(port, port == "ready" if descriptor.type == "BOOL" else DEFAULTS[descriptor.type])

    def read(graph, scope, node, port):
        return graph.input(node, port, lambda source, key, descriptor: values(scope, source, key, descriptor),
                           _evaluate, lambda _, value: value)

    def run_station(id_, time, call=None):
        station = stations[id_]
        graph = local[id_]
        assigned[id_] = {item.id: read(project_graph, "project", call.id, item.id) if call else
                         DEFAULTS[item.type] if item.default is None else item.default
                         for item in station.public_ports if item.direction == "input"}
        for device in station.devices:
            device_state.pop((id_, device.id), None)
        wrong_mode = next((node for node in station.flow.nodes if node.kind == "device" and graph.wired(node.id, "mode")
                           and read(graph, id_, node.id, "mode") != 0), None)
        if call and read(project_graph, "project", call.id, "reset"):
            result = time, "waiting", [frame(time, id_, station, "reset", station.name + " · 复位中")]
        elif (call and not read(project_graph, "project", call.id, "permit")) or wrong_mode:
            result = time, "fault", [frame(time, id_, wrong_mode or station, "interlock", station.name + " · 自动运行许可未满足")]
        elif scenario == "interlock_lost" and station.interlocks:
            condition = station.interlocks[0]
            result = time, "fault", [frame(time, id_, condition, "interlock")]
        else:
            result = run(station.flow, time, id_)
        interface = next((item for item in station.flow.nodes if item.kind == "interface"), None)
        end, state, trace = result
        alarms = [item.get("alarm_id", 0) for item in trace if item["event"] == "alarm"]
        published[id_] = {"ready": state in ("done",), "busy": state == "waiting", "done": state == "done",
                          "fault": state == "fault", "alarm_id": next(iter(alarms), 9000 if state == "fault" else 0)}
        for item in station.public_ports:
            if item.direction == "output":
                published[id_][item.id] = read(graph, id_, interface.id, item.id) if interface else (
                    DEFAULTS[item.type] if item.default is None else item.default)
        return end, state, trace

    def station_action(node: Node, time: int, scope: str):
        station = stations[scope]
        graph = local[scope]
        if graph.wired(node.id, "permit") and not read(graph, scope, node.id, "permit"):
            return time, "waiting", [frame(time, scope, node, "interlock", node.name + " · 信号许可未满足")]
        rule = next((rule for rule in node.permissions if scenario == "interlock_blocked" or
                     (scenario == "interlock_lost" and rule.mode == "continuous")), None)
        if rule:
            device = next(item for item in station.devices if item.id == rule.device_id)
            loss = scenario == "interlock_lost"
            end = time + (10 if loss else 0)
            event = "blocked" if loss or rule.blocked == "fault" else "waiting"
            label = f"{node.name} · 互锁 · {device.name} / {rule.port}"
            return end, event, [frame(end, scope, node, "interlock", label)]
        if node.kind == "decision":
            if graph.wired(node.id, "condition"):
                decision = read(graph, scope, node.id, "condition") == node.value
            else:
                decision = scenario != "negative_feedback"
            return time + 10, "true" if decision else "false", []
        if node.device_id and node.kind == "wait" or node.completion:
            for request in node.actions:
                command = next((item for item in station.flow.nodes if item.kind == "device" and item.device_id == request.device_id), None)
                if command and graph.wired(command.id, "enable") and not read(graph, scope, command.id, "enable"):
                    end = time + 10 + node.timeout_ms
                    return end, "timeout", [frame(time, scope, node, "interlock", node.name + " · 设备未使能")]
            if scenario == "feedback_timeout":
                deadline, alarms = node.timeout_ms, []
                lookup = {item.id: item for item in station.devices}
                for request in node.actions:
                    device = lookup[request.device_id]
                    if device.driver != "cylinder":
                        continue
                    extending = request.action_id == "extend"
                    device_ms = (device.extend_timeout_ms if extending else device.retract_timeout_ms) or max(
                        (candidate.timeout_ms for candidate in station.flow.nodes for item in candidate.actions
                         if item.device_id == device.id and item.action_id == request.action_id), default=device.timeout_ms)
                    selected = next((item for item in station.flow.nodes if item.kind == "device" and item.device_id == device.id), None)
                    port = "extend_timeout" if extending else "retract_timeout"
                    if selected and graph.wired(selected.id, port):
                        device_ms = read(graph, scope, selected.id, port)
                    if 0 < device_ms <= deadline:
                        deadline = device_ms
                        alarms = [(device, ALARM_EXTEND_TIMEOUT if extending else ALARM_RETRACT_TIMEOUT)]
                end = time + 10 + deadline
                events = []
                for device, alarm_id in alarms:
                    device_state[scope, device.id] = {"fault": True, "alarm_id": alarm_id, "state": 5, "ready": False}
                    events.append({**frame(end, scope, node, "alarm", f"{device.name} · 报警 {alarm_id}"), "alarm_id": alarm_id})
                return end, "timeout", events
        for item in node.completion:
            state = device_state.setdefault((scope, item.device_id), {})
            state["fb_" + item.port] = item.value
            state.update({"done": True, "busy": False})
        return time + 10 + node.duration_ms, "next", []

    def merge_runs(runs, failures, scope, now, frames):
        first_failure = min((item[0] for item in failures), default=None)
        for end, result, trace in runs:
            frames.extend(item for item in trace if first_failure is None or item["time_ms"] <= first_failure)
        return first_failure if first_failure is not None else max((item[0] for item in runs), default=now)

    def run(flow: Flow, start_ms: int, scope: str, project: bool = False):
        nonlocal remaining
        nodes = {node.id: node for node in flow.nodes}
        links = {(edge.from_id, edge.outcome): edge.to_id for edge in flow.edges}
        regions, _ = parallel_regions(flow, project=project)
        key, time = flow.start, start_ms
        frames = []
        for _ in range(600):
            if remaining <= 0:
                break
            remaining -= 1
            node = nodes.get(key)
            if node is None:
                return time, "fault", frames
            frames.append(frame(time, scope, node, node.kind))
            if node.kind in ("done", "fault"):
                return time, node.kind, frames
            if node.kind == "fork":
                region = regions[node.id]
                branch_start = time + 10
                runs = []
                for arm in region.branches:
                    initial = frame(branch_start, scope, arm, arm.kind)
                    if project:
                        end, result, events = run_station(arm.station_ids[0], branch_start, arm)
                    else:
                        end, result, events = station_action(arm, branch_start, scope)
                    runs.append((end, result, [initial, *events, frame(end, scope, arm, result)]))
                failures = [(end, index, result) for index, (end, result, _) in enumerate(runs)
                            if result not in ("done", "next", "waiting")]
                time = merge_runs(runs, failures, scope, time, frames)
                if failures:
                    _, index, outcome = min(failures)
                    key = links.get((region.branches[index].id, outcome))
                elif any(result == "waiting" for _, result, _ in runs):
                    return time, "waiting", frames
                else:
                    key = region.join_id
                continue
            if project and node.kind == "handoff":
                if scenario == "handoff_timeout" or not read(project_graph, scope, node.id, "permit"):
                    time += node.timeout_ms
                    outcome = "timeout"
                else:
                    frames.append(frame(time + 10, scope, node, "accepted", node.name + " · 接收确认"))
                    time, outcome, branch_frames = run_station(node.station_ids[0], time + 10, node)
                    frames.extend(branch_frames)
            elif project and node.kind in ("station", "parallel"):
                runs = [run_station(id_, time + 10, node if node.kind == "station" else None) for id_ in node.station_ids]
                failures = [(end, result) for end, result, _ in runs if result == "fault"]
                time = merge_runs(runs, failures, scope, time, frames)
                outcome = "fault" if failures else "waiting" if any(result == "waiting" for _, result, _ in runs) else "done"
            elif project:
                time += 10
                if node.kind == "decision":
                    decision = read(project_graph, scope, node.id, "condition") == node.value if project_graph.wired(node.id, "condition") else scenario != "negative_feedback"
                    outcome = "true" if decision else "false"
                else:
                    outcome = "next"
            else:
                time, outcome, events = station_action(node, time, scope)
                frames.extend(events)
            frames.append(frame(time, scope, node, outcome))
            if outcome == "waiting":
                return time, outcome, frames
            key = links.get((key, outcome))
        frames.append({"time_ms": time, "node_id": key, "station_id": scope,
                       "event": "limit", "name": "达到仿真步数上限"})
        return time, "fault", frames

    _, _, trace = run_station(station_id, 0) if station_id else run(design.flow, 0, "project", True)
    return sorted(trace, key=lambda item: item["time_ms"])
