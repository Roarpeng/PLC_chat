import type { DeviceProfile, Direction, Node, PortDefinition, PortType, Station } from "./stationDesign";

const port = (id: string, name: string, direction: Direction, type: PortType): PortDefinition => ({ id, name, direction, type });
export const DATA_ONLY = new Set(["device", "logic", "interface"]);
export const PORT_DEFAULTS = { BOOL: false, DINT: 0, TIME: 0, STRING: "", MODE: 0, REQUEST: 0 };
export const STATION_PORTS = [
  port("permit", "运行许可", "input", "BOOL"), port("reset", "复位", "input", "BOOL"),
  ...[["ready", "就绪"], ["busy", "运行中"], ["done", "完成"], ["fault", "故障"]].map(([id, name]) => port(id, name, "output", "BOOL")),
  port("alarm_id", "报警 ID", "output", "DINT"),
];
const CYLINDER_IO = [
  port("mode", "手动 / 自动", "input", "MODE"), port("enable", "使能", "input", "BOOL"),
  port("manual_request", "手动动作请求", "input", "REQUEST"), port("reset", "复位", "input", "BOOL"),
  port("extend_timeout", "伸出超时", "input", "TIME"), port("retract_timeout", "缩回超时", "input", "TIME"),
];
const CYLINDER_STATE = [
  ...[["ready", "就绪"], ["busy", "忙碌"], ["done", "本次动作完成"], ["blocked", "请求受阻"]].map(([id, name]) => port(id, name, "output", "BOOL")),
  port("state", "当前状态", "output", "DINT"), port("alarm_id", "报警 ID", "output", "DINT"),
];

export function nodePorts(node: Node, station: Station | undefined, stations: Station[], catalog: DeviceProfile[]): PortDefinition[] {
  if ((node.kind === "station" || node.kind === "handoff") && node.station_ids[0]) {
    return [...STATION_PORTS, ...(stations.find((item) => item.id === node.station_ids[0])?.public_ports ?? [])];
  }
  if (node.kind === "interface") return (station?.public_ports ?? []).map((item) => ({
    ...item, direction: item.direction === "input" ? "output" : "input",
  }));
  if (node.kind === "logic") return [...(node.ports ?? []), port("result", "结果", "output", "BOOL")];
  if (node.kind === "decision") return [port("condition", "判断条件", "input", "BOOL")];
  if (node.kind === "device" || node.kind === "action") {
    const inputs = node.kind === "action" ? [port("permit", "启动许可", "input", "BOOL")] : [];
    const key = node.actions?.length === 1 ? node.actions[0].device_id : node.device_id;
    const device = station?.devices.find((item) => item.id === key);
    const template = catalog.find((item) => item.id === device?.driver);
    if (!template) return inputs;
    const outputs = [port("fault", "驱动故障", "output", "BOOL"),
      ...Object.entries(template.ports).filter(([, direction]) => direction === "input")
        .map(([key]) => port("fb_" + key, template.port_labels[key], "output", "BOOL"))];
    if (template.id === "cylinder") return [...inputs, ...(node.kind === "device" ? CYLINDER_IO : []), ...outputs, ...CYLINDER_STATE];
    return [...inputs, ...outputs];
  }
  return [];
}
