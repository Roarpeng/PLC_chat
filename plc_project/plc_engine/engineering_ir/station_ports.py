"""Typed signal interfaces for the AF canvas. Execution edges stay in Flow.edges."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PortId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,23}$")]
EndpointId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,29}$")]
PortType = Literal["BOOL", "DINT", "TIME", "STRING", "MODE", "REQUEST"]
Value = bool | int | str
SCL_TYPES = {"BOOL": "Bool", "DINT": "DInt", "TIME": "Time", "STRING": "String[40]", "MODE": "USInt", "REQUEST": "USInt"}
DEFAULTS: dict[str, Value] = {"BOOL": False, "DINT": 0, "TIME": 0, "STRING": "", "MODE": 0, "REQUEST": 0}


def valid_value(type_: PortType, value: Value) -> bool:
    if type_ == "BOOL":
        return type(value) is bool
    if type_ == "STRING":
        return isinstance(value, str) and len(value) <= 40 and all(char.isprintable() for char in value)
    lo, hi = {"DINT": (-2**31, 2**31 - 1), "TIME": (0, 86_400_000), "MODE": (0, 1), "REQUEST": (0, 2)}[type_]
    return type(value) is int and lo <= value <= hi


def scl_value(type_: PortType, value: Value) -> str:
    if type_ == "BOOL":
        return "TRUE" if value else "FALSE"
    if type_ == "TIME":
        return f"T#{value}ms"
    if type_ == "STRING":
        return "'" + str(value).replace("$", "$$").replace("'", "$'") + "'"
    return str(value)


class PortDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: PortId
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    direction: Literal["input", "output"]
    type: PortType
    default: Value | None = None

    @model_validator(mode="after")
    def check_default(self):
        if self.default is not None and not valid_value(self.type, self.default):
            raise ValueError("端口默认值与信号类型不匹配。")
        return self


class SignalWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: EndpointId
    from_id: EndpointId
    from_port: PortId
    to_id: EndpointId
    to_port: PortId


@dataclass(frozen=True)
class Port:
    label: str
    direction: Literal["input", "output"]
    type: PortType
    default: Value | None = None


STATION_PORTS = {
    "permit": Port("运行许可", "input", "BOOL", True),
    "reset": Port("复位", "input", "BOOL"),
    "ready": Port("就绪", "output", "BOOL"),
    "busy": Port("运行中", "output", "BOOL"),
    "done": Port("完成", "output", "BOOL"),
    "fault": Port("故障", "output", "BOOL"),
    "alarm_id": Port("报警 ID", "output", "DINT"),
}
STATION_OUTPUTS = {"ready": "Ready", "busy": "Busy", "done": "Done", "fault": "Fault", "alarm_id": "AlarmId"}
CYLINDER_INPUTS = {
    "mode": Port("手动 / 自动", "input", "MODE"),
    "enable": Port("使能", "input", "BOOL", True),
    "manual_request": Port("手动动作请求", "input", "REQUEST"),
    "reset": Port("复位", "input", "BOOL"),
    "extend_timeout": Port("伸出超时", "input", "TIME", 2000),
    "retract_timeout": Port("缩回超时", "input", "TIME", 2000),
}
CYLINDER_OUTPUTS = {
    "ready": ("Ready", Port("就绪", "output", "BOOL")),
    "busy": ("Busy", Port("忙碌", "output", "BOOL")),
    "done": ("Done", Port("本次动作完成", "output", "BOOL")),
    "state": ("State", Port("当前状态", "output", "DINT")),
    "alarm_id": ("AlarmId", Port("报警 ID", "output", "DINT")),
    "blocked": ("Blocked", Port("请求受阻", "output", "BOOL")),
}
NON_EXECUTABLE = {"logic", "interface", "device"}


def declared_ports(definitions, *, reverse=False) -> dict[str, Port]:
    return {item.id: Port(item.name, ("output" if item.direction == "input" else "input") if reverse else item.direction,
                          item.type, item.default) for item in definitions}


def station_node_ports(node, station, stations, profiles) -> dict[str, Port]:
    if node.kind in ("station", "handoff") and node.station_ids:
        called = stations.get(node.station_ids[0])
        return {**STATION_PORTS, **(declared_ports(called.public_ports) if called else {})}
    if node.kind == "interface" and station:
        return declared_ports(station.public_ports, reverse=True)
    if node.kind == "logic":
        return {**declared_ports(node.ports), "result": Port("结果", "output", "BOOL")}
    if node.kind == "decision":
        return {"condition": Port("判断条件", "input", "BOOL")}
    if node.kind in ("action", "device") and station:
        key = node.actions[0].device_id if len(node.actions) == 1 else node.device_id
        device = next((item for item in station.devices if item.id == key), None)
        ports = {"permit": Port("运行许可", "input", "BOOL", True)} if node.kind == "action" else {}
        if not device:
            return ports
        profile = profiles[device.driver]
        ports["fault"] = Port("驱动故障", "output", "BOOL")
        ports.update({f"fb_{port}": Port(profile["port_labels"][port], "output", "BOOL")
                      for port, direction in profile["ports"].items() if direction == "input"})
        if device.driver == "cylinder":
            ports.update({id_: port for id_, (_, port) in CYLINDER_OUTPUTS.items()})
            if node.kind == "device":
                ports.update(CYLINDER_INPUTS)
        return ports
    return {}
