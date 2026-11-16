"""Typed hardware and two-level canvas stored in the authoritative V2 IR."""
from __future__ import annotations


from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from plc_engine.engineering_ir.station_catalog import ACTIONS, DRIVERS, PROFILES
from plc_engine.engineering_ir.station_parallel import parallel_regions
from plc_engine.engineering_ir.station_ports import NON_EXECUTABLE, PortDefinition, SignalWire
from plc_engine.engineering_ir.station_signals import SignalGraph, signal_issues

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,29}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Duration = Annotated[int, Field(ge=0, le=86_400_000)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Module(Record):
    id: Identifier
    name: Label
    slot: Annotated[int, Field(ge=0, le=255)]
    kind: Literal["DI", "DO", "DI_DO"]


class Signal(Record):
    id: Identifier
    name: Label
    module_id: Identifier
    direction: Literal["input", "output"]
    address: Annotated[str, StringConstraints(pattern=r"^(?:%[IQ](?:0|[1-9][0-9]{0,3})\.[0-7])?$")] = ""


class Hardware(Record):
    cpu: str = Field(default="", max_length=100)
    network: str = Field(default="", max_length=120)
    modules: list[Module] = Field(default_factory=list, max_length=64)
    signals: list[Signal] = Field(default_factory=list, max_length=512)


class Device(Record):
    id: Identifier
    name: Label
    driver: Identifier
    bindings: dict[Identifier, Identifier] = Field(default_factory=dict)
    timeout_ms: Duration = 0
    extend_timeout_ms: Annotated[int, Field(ge=1, le=86_400_000)] | None = None
    retract_timeout_ms: Annotated[int, Field(ge=1, le=86_400_000)] | None = None

    @field_validator("driver")
    @classmethod
    def known_driver(cls, value: str) -> str:
        if value not in PROFILES:
            raise ValueError("未知设备规格")
        return value


class DeviceAction(Record):
    device_id: Identifier
    action_id: Identifier


class Feedback(Record):
    device_id: Identifier
    port: Identifier
    value: bool = True


class Permission(Feedback):
    id: Identifier
    mode: Literal["start", "continuous"] = "start"
    blocked: Literal["wait", "fault"] = "wait"


class Position(Record):
    x: Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
    y: Annotated[float, Field(ge=-1_000_000, le=1_000_000)]


class Node(Record):
    id: Identifier
    name: Label
    kind: Literal["start", "action", "wait", "decision", "done", "fault", "station", "parallel", "fork", "join", "logic", "interface", "device", "handoff"]
    device_id: Identifier | None = None
    port: Identifier | None = None
    value: bool = True
    duration_ms: Duration = 0
    timeout_ms: Duration = 0
    station_ids: list[Identifier] = Field(default_factory=list, max_length=24)
    actions: list[DeviceAction] = Field(default_factory=list, max_length=16)
    completion: list[Feedback] = Field(default_factory=list, max_length=64)
    pending_feedback: bool = False
    signal_id: Identifier | None = None
    permissions: list[Permission] = Field(default_factory=list, max_length=16)
    position: Position | None = None
    operator: Literal["and", "or", "not", "eq", "gt", "lt"] | None = None
    ports: list[PortDefinition] = Field(default_factory=list, max_length=24)


class Edge(Record):
    id: Identifier
    from_id: Identifier
    to_id: Identifier
    outcome: Literal["next", "true", "false", "timeout", "done", "fault", "branch", "blocked"]


class Flow(Record):
    start: Identifier | None = None
    nodes: list[Node] = Field(default_factory=list, max_length=120)
    edges: list[Edge] = Field(default_factory=list, max_length=360)
    wires: list[SignalWire] = Field(default_factory=list, max_length=360)


class Interlock(Record):
    id: Identifier
    name: Label
    device_id: Identifier | None = None
    port: Identifier | None = None
    value: bool = True


class Station(Record):
    id: Identifier
    name: Label
    devices: list[Device] = Field(default_factory=list, max_length=64)
    flow: Flow = Field(default_factory=Flow)
    interlocks: list[Interlock] = Field(default_factory=list, max_length=32)
    public_ports: list[PortDefinition] = Field(default_factory=list, max_length=24)


class StationDesign(Record):
    version: Literal[1] = 1
    name: Label
    hardware: Hardware = Field(default_factory=Hardware)
    stations: list[Station] = Field(default_factory=list, max_length=24)
    flow: Flow = Field(default_factory=Flow)


def outcomes(node: Node) -> set[str]:
    if node.kind in NON_EXECUTABLE:
        return set()
    exits = {
        "start": {"next"},
        "fork": {"branch"},
        "join": {"next"},
        "action": {"next", "timeout"} if node.actions and node.completion else {"next"},
        "wait": {"next", "timeout"} if node.device_id or node.pending_feedback else {"next"},
        "decision": {"true", "false"},
        "station": {"done", "fault"},
        "handoff": {"done", "fault", "timeout"},
        "parallel": {"done", "fault"},
        "done": set(),
        "fault": set(),
    }[node.kind]
    if any(item.mode == "continuous" or item.blocked == "fault" for item in node.permissions):
        exits.add("blocked")
    return exits


def design_records(design: StationDesign) -> dict[str, dict]:
    """Index semantic records for impact and review summaries."""
    records = [*design.hardware.modules, *design.hardware.signals, *design.stations]
    for station in design.stations:
        records.extend(station.devices)
        records.extend(station.interlocks)
        records.extend(station.flow.nodes)
        records.extend(station.flow.edges)
        records.extend(station.flow.wires)
        records.extend(rule for node in station.flow.nodes for rule in node.permissions)
    records.extend(design.flow.nodes)
    records.extend(design.flow.edges)
    records.extend(design.flow.wires)
    return {item.id: item.model_dump() for item in records}


def design_issues(design: StationDesign, *, release: bool = False) -> list[dict]:
    issues: list[dict] = []

    def issue(id_: str, reason: str, field: str) -> None:
        issues.append({"node_id": id_, "source_id": id_, "reason": reason, "field": field})

    def require(condition: bool, id_: str, reason: str, field: str) -> None:
        if release and not condition:
            issue(id_, reason, field)

    hardware = design.hardware
    modules = {item.id: item for item in hardware.modules}
    signals = {item.id: item for item in hardware.signals}
    stations = {item.id: item for item in design.stations}
    all_ids = [item.id for item in [*hardware.modules, *hardware.signals, *design.stations]]
    require(bool(hardware.cpu.strip()), "hardware", "请选择 PLC CPU。", "cpu")
    require(bool(modules), "hardware", "请添加 I/O 模块。", "modules")
    require(bool(stations), "hardware", "请创建至少一个工位。", "stations")
    occupied_slots: set[int] = set()
    for module in hardware.modules:
        if module.slot in occupied_slots:
            issue(module.id, f"插槽 {module.slot} 已占用。", "slot")
        occupied_slots.add(module.slot)
    addresses: set[str] = set()
    for signal in hardware.signals:
        module = modules.get(signal.module_id)
        if not module:
            issue(signal.id, "信号引用了不存在的模块。", "module_id")
        elif module.kind not in ("DI_DO", "DI" if signal.direction == "input" else "DO"):
            issue(signal.id, "信号方向与模块类型不符。", "direction")
        if signal.address:
            if signal.address in addresses:
                issue(signal.id, f"I/O 地址 {signal.address} 已占用。", "address")
            addresses.add(signal.address)
            if not signal.address.startswith("%I" if signal.direction == "input" else "%Q"):
                issue(signal.id, "I/O 地址方向与信号方向不符。", "address")

    writers: dict[str, str] = {}
    for station in design.stations:
        all_ids.extend(d.id for d in station.devices)
        all_ids.extend(item.id for item in station.interlocks)
        devices = {item.id: item for item in station.devices}
        for condition in station.interlocks:
            device = devices.get(condition.device_id)
            if condition.device_id and (not device or (condition.port and DRIVERS[device.driver].get(condition.port) != "input")):
                issue(condition.id, "联锁引用了不存在或方向不符的反馈信号。", "port")
            require(bool(condition.device_id and condition.port), condition.id, "请配置联锁信号。", "port")
        for device in station.devices:
            ports = DRIVERS[device.driver]
            require(PROFILES[device.driver]["supported"], device.id, f"{device.name} 待配套驱动，无法生成 AF 代码。", "driver")
            for port, signal_id in device.bindings.items():
                signal = signals.get(signal_id)
                if port not in ports or not signal or signal.direction != ports[port]:
                    issue(device.id, f"{port} 的信号或方向不匹配。", "bindings")
                    continue
                if signal.direction == "output":
                    if signal_id in writers:
                        issue(device.id, f"{signal.name} 已由 {writers[signal_id]} 写入。", "bindings")
                    writers[signal_id] = device.id
                require(bool(signal.address), signal.id, f"请填写 {signal.name} 的 I/O 地址。", "address")
            for port in ports:
                require(port in device.bindings, device.id, f"请绑定 {device.name} 的 {port}。", "bindings")

    for station, flow in [(item, item.flow) for item in design.stations] + [(None, design.flow)]:
        scope = station.id if station else "flow"
        nodes = {node.id: node for node in flow.nodes}
        devices = {item.id: item for item in station.devices} if station else {}
        all_ids.extend(item.id for item in [*flow.nodes, *flow.edges, *flow.wires])
        graph = SignalGraph(flow, station, stations, PROFILES)
        issues.extend(signal_issues(graph, release=release))
        if flow.start and (flow.start not in nodes or nodes[flow.start].kind in NON_EXECUTABLE):
            issue(scope, "起点引用不存在的节点。", "start")
        require(bool(flow.start), scope, "请设置流程起点。", "start")
        branches: dict[str, dict[str, str]] = {}
        for edge in flow.edges:
            source = nodes.get(edge.from_id)
            if not source or edge.to_id not in nodes:
                issue(edge.id, "连线引用了本画布中不存在的节点。", "edge")
                continue
            if nodes[edge.to_id].kind in NON_EXECUTABLE:
                issue(edge.id, "执行线需要连接具有执行入口的节点。", "edge")
            routes = branches.setdefault(edge.from_id, {})
            exit_key = f"branch:{edge.to_id}" if edge.outcome == "branch" else edge.outcome
            if exit_key in routes or edge.outcome not in outcomes(source):
                issue(edge.id, "出口重复或与节点类型不符。", "outcome")
            if release and edge.from_id == edge.to_id:
                issue(edge.id, "循环需要经过独立的等待、判断或恢复节点。", "edge")
            routes[exit_key] = edge.to_id
        for node in flow.nodes:
            shared = {"start", "decision", "fork", "join", "done", "fault", "logic"}
            if node.kind not in shared | ({"action", "wait", "device", "interface"} if station else {"station", "parallel", "handoff"}):
                issue(node.id, "节点类型与画布层级不符。", "kind")
            if node.signal_id and (station or node.kind != "decision" or node.signal_id not in signals
                                   or signals[node.signal_id].direction != "input"):
                issue(node.id, "项目判断只能引用组态中的输入信号。", "signal_id")
            if node.signal_id in signals:
                require(bool(signals[node.signal_id].address), node.id, "请填写项目判断输入的 I/O 地址。", "signal_id")
            if node.device_id:
                device = devices.get(node.device_id)
                direction = "output" if node.kind == "action" else "input"
                if not device or (node.port and DRIVERS[device.driver].get(node.port) != direction):
                    issue(node.id, "请选择本工位内匹配的设备信号。", "port")
            if node.actions or node.completion:
                if node.kind != "action" or node.device_id or node.port or not node.actions:
                    issue(node.id, "设备动作与直接端口写入必须使用独立步骤。", "actions")
                action_devices: set[str] = set()
                needs_feedback = False
                for item in node.actions:
                    device = devices.get(item.device_id)
                    spec = ACTIONS[device.driver].get(item.action_id) if device else None
                    if not spec:
                        issue(node.id, "动作引用了本工位不存在的设备或动作。", "actions")
                    elif spec["feedback"]:
                        needs_feedback = True
                    if item.device_id in action_devices:
                        issue(node.id, "同一设备在一个并行步骤内只能执行一个动作。", "actions")
                    action_devices.add(item.device_id)
                signals_seen: set[tuple[str, str]] = set()
                for feedback in node.completion:
                    device = devices.get(feedback.device_id)
                    key = (feedback.device_id, feedback.port)
                    if not device or DRIVERS[device.driver].get(feedback.port) != "input":
                        issue(node.id, "完成条件需要引用本工位的反馈信号。", "completion")
                    if key in signals_seen:
                        issue(node.id, "完成条件重复引用同一反馈。", "completion")
                    signals_seen.add(key)
                require(not needs_feedback or bool(node.completion), node.id, "请设置该动作的完成反馈。", "completion")
                require(not node.completion or bool(node.timeout_ms), node.id, "请设置完成反馈的等待超时。", "timeout_ms")
            if node.kind == "decision" and not station:
                require(bool(node.signal_id) or graph.wired(node.id, "condition"), node.id, "请选择或连接项目判断信号。", "signal_id")
            if (station and node.kind == "decision" and not graph.wired(node.id, "condition")) or (node.kind == "action" and not node.actions):
                require(bool(node.device_id and node.port), node.id, "请配置节点的设备和端口。", "port")
            if node.kind == "device":
                require(node.device_id in devices, node.id, "请选择驱动实例。", "device_id")
            if node.permissions and (not station or node.kind != "action"):
                issue(node.id, "运行许可用于工位内的设备动作。", "permissions")
            for condition in node.permissions:
                all_ids.append(condition.id)
                device = devices.get(condition.device_id)
                if not device or DRIVERS[device.driver].get(condition.port) != "input":
                    issue(node.id, "运行许可需要引用本工位的输入反馈。", "permissions")
            if node.pending_feedback:
                if node.kind != "wait" or node.device_id is not None:
                    issue(node.id, "待关联反馈只用于未配置设备的等待节点。", "pending_feedback")
                require(False, node.id, f"请选择「{node.name}」对应的反馈信号。", "pending_feedback")
            if node.kind == "wait":
                if not node.device_id and not node.pending_feedback and node.timeout_ms:
                    issue(node.id, "只有信号等待节点可以配置超时。", "timeout_ms")
                require(bool(node.port and node.timeout_ms) if node.device_id or node.pending_feedback else bool(node.duration_ms),
                        node.id, "信号等待需要端口和超时，定时等待需要保持时间。", "timeout_ms")
            if node.kind in ("station", "parallel", "handoff"):
                if len(set(node.station_ids)) != len(node.station_ids) or any(key not in stations for key in node.station_ids):
                    issue(node.id, "工位引用重复或不存在。", "station_ids")
                if node.kind in ("station", "handoff") and len(node.station_ids) > 1:
                    issue(node.id, "单工位节点只接受一个工位。", "station_ids")
                require(len(node.station_ids) >= (2 if node.kind == "parallel" else 1),
                        node.id, "请选择参与执行的工位。", "station_ids")
                if node.kind == "handoff":
                    require(bool(node.timeout_ms), node.id, "请设置工位交接确认超时。", "timeout_ms")
            exits = {item.split(":", 1)[0] for item in branches.get(node.id, {})}
            require(outcomes(node) == exits, node.id, "请连接此节点的全部出口。", "outcome")
        if release:
            _, parallel_issues = parallel_regions(flow, project=station is None)
            for id_, reason in parallel_issues:
                issue(id_, reason, "parallel")
        if release and flow.start in nodes:
            seen: set[str] = set()
            pending = [flow.start]
            while pending:
                key = pending.pop()
                if key not in seen:
                    seen.add(key)
                    pending.extend(branches.get(key, {}).values())
            for node_id in nodes.keys() - seen:
                if nodes[node_id].kind not in NON_EXECUTABLE:
                    issue(node_id, "从起点无法到达此节点。", "start")
            if not any(nodes[key].kind == "done" for key in seen):
                issue(scope, "至少需要一个可到达的完成节点。", "flow")
    for key, count in Counter(key.casefold() for key in all_ids).items():
        if count > 1:
            issue(key, "工程标识重复（PLC 不区分大小写）。", "id")
    return issues
