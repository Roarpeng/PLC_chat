export type Driver = string;
export type Direction = "input" | "output";
export type ModuleKind = "DI" | "DO" | "DI_DO";
export type NodeKind = "start" | "action" | "wait" | "decision" | "station" | "parallel" | "fork" | "join" | "done" | "fault" | "device" | "logic" | "interface" | "handoff";
export type Outcome = "next" | "true" | "false" | "timeout" | "done" | "fault" | "branch" | "blocked";

export interface Module { id: string; name: string; slot: number; kind: ModuleKind }
export interface Signal { id: string; name: string; module_id: string; direction: Direction; address: string }
export interface Hardware { cpu: string; network: string; modules: Module[]; signals: Signal[] }
export interface Device { id: string; name: string; driver: Driver; bindings: Record<string, string>; timeout_ms: number; extend_timeout_ms?: number | null; retract_timeout_ms?: number | null }
export interface CatalogAction {
  id: string; label: string; outputs: Record<string, boolean>; feedback: Record<string, boolean>; timeout_ms: number;
}
export interface DeviceProfile {
  id: Driver; label: string; category: string; interface: string; aliases: string[];
  ports: Record<string, Direction>; port_labels: Record<string, string>; actions: CatalogAction[]; supported: boolean;
}
export interface DeviceAction { device_id: string; action_id: string }
export interface Feedback { device_id: string; port: string; value: boolean }
export interface Permission extends Feedback { id: string; mode: "start" | "continuous"; blocked: "wait" | "fault" }
export type PortType = "BOOL" | "DINT" | "TIME" | "STRING" | "MODE" | "REQUEST";
export type PortValue = number | boolean | string;
export interface PortDefinition { id: string; name: string; direction: Direction; type: PortType; default?: PortValue | null }
export interface SignalWire { id: string; from_id: string; from_port: string; to_id: string; to_port: string }
export type LogicOperator = "and" | "or" | "not" | "eq" | "gt" | "lt";
export interface Node {
  id: string;
  name: string;
  kind: NodeKind;
  device_id: string | null;
  port: string | null;
  value: boolean;
  duration_ms: number;
  timeout_ms: number;
  station_ids: string[];
  actions?: DeviceAction[];
  completion?: Feedback[];
  pending_feedback?: boolean;
  signal_id?: string | null;
  permissions?: Permission[];
  position?: { x: number; y: number } | null;
  ports?: PortDefinition[];
  operator?: LogicOperator | null;
}
export interface Edge { id: string; from_id: string; to_id: string; outcome: Outcome }
export interface Flow { start: string | null; nodes: Node[]; edges: Edge[]; wires?: SignalWire[] }
export interface Interlock { id: string; name: string; device_id: string | null; port: string | null; value: boolean }
export interface Station { id: string; name: string; devices: Device[]; flow: Flow; interlocks?: Interlock[]; public_ports?: PortDefinition[] }
export interface StationDesign { version: 1; name: string; hardware: Hardware; stations: Station[]; flow: Flow }

export const NODE_LABEL: Record<NodeKind, string> = {
  start: "开始", action: "动作", wait: "等待", decision: "条件分支", station: "运行工位",
  parallel: "并行工位组", fork: "并行分支", join: "全部汇合", done: "完成", fault: "故障",
  device: "设备接口", logic: "信号逻辑", interface: "工位接口", handoff: "工位交接",
};
export const OUTCOME_LABEL: Record<Outcome, string> = {
  next: "继续", true: "成立", false: "不成立", timeout: "超时", done: "完成", fault: "故障",
  branch: "分支", blocked: "互锁失效",
};

export function outcomes(node: Node): Outcome[] {
  switch (node.kind) {
    case "action": return [
      "next", ...(node.actions?.length && node.completion?.length ? ["timeout" as const] : []),
      ...(node.permissions?.some((item) => item.mode === "continuous" || item.blocked === "fault") ? ["blocked" as const] : []),
    ];
    case "start":
    case "join": return ["next"];
    case "fork": return ["branch"];
    case "wait": return node.device_id || node.pending_feedback ? ["next", "timeout"] : ["next"];
    case "decision": return ["true", "false"];
    case "station":
    case "parallel": return ["done", "fault"];
    case "handoff": return ["done", "fault", "timeout"];
    default: return [];
  }
}

export function emptyFlow(): Flow {
  return { start: null, nodes: [], edges: [] };
}

export function entityId(prefix: string): string {
  return prefix + "_" + crypto.randomUUID().replaceAll("-", "").slice(0, 14);
}

export function newNode(kind: NodeKind): Node {
  return {
    id: entityId("node"), name: NODE_LABEL[kind], kind, device_id: null, port: null,
    value: true, duration_ms: 0, timeout_ms: 0, station_ids: [],
  };
}

export function actionNode(device: Device, preset: CatalogAction): Node {
  const completion = Object.entries(preset.feedback).map(([port, value]) => ({ device_id: device.id, port, value }));
  return {
    ...newNode("action"), name: (device.name + " · " + preset.label).slice(0, 100),
    actions: [{ device_id: device.id, action_id: preset.id }], completion,
    timeout_ms: completion.length ? device.timeout_ms || preset.timeout_ms : 0,
  };
}

export function usesDevice(node: Node, deviceId: string): boolean {
  return node.device_id === deviceId || Boolean(node.actions?.some((item) => item.device_id === deviceId)) ||
    Boolean(node.completion?.some((item) => item.device_id === deviceId)) ||
    Boolean(node.permissions?.some((item) => item.device_id === deviceId));
}

export function primarySteps(flow: Flow): Node[] {
  const nodes = new Map(flow.nodes.map((item) => [item.id, item]));
  const targets = new Map(flow.edges.filter((edge) => edge.outcome === "next" || edge.outcome === "true")
    .map((edge) => [edge.from_id, edge.to_id]));
  const visited = new Set<string>();
  const result: Node[] = [];
  let current = flow.start;
  while (current && !visited.has(current)) {
    const item = nodes.get(current);
    if (!item) break;
    visited.add(current);
    result.push(item);
    current = targets.get(current) ?? null;
  }
  return [...result, ...flow.nodes.filter((node) => !visited.has(node.id))];
}

export function insertBefore(flow: Flow, next: Node, anchor?: string): Flow {
  const createdDone = !flow.nodes.length ? { ...newNode("done"), name: "工位完成" } : undefined;
  const done = createdDone ?? flow.nodes.filter((node) => node.kind === "done")[0];
  const target = anchor ?? done?.id;
  if (!target || (!createdDone && !flow.nodes.some((node) => node.id === target))) {
    throw new Error("请在步骤或逻辑图上选择插入位置。");
  }
  const defaultFault = flow.nodes.find((node) => node.kind === "fault" && node.name === "动作超时");
  const createdFault = outcomes(next).includes("timeout") && !defaultFault
    ? { ...newNode("fault"), name: "动作超时" } : undefined;
  const fault = createdFault ?? defaultFault;
  const edges: Edge[] = flow.edges.map((edge) => edge.to_id === target && edge.outcome === "next" ? { ...edge, to_id: next.id } : edge);
  if (!createdDone && flow.start !== target && !edges.some((edge) => edge.to_id === next.id)) {
    throw new Error("该节点从分支进入。请在逻辑图里选择对应连线。");
  }
  edges.push({ id: entityId("edge"), from_id: next.id, to_id: target, outcome: "next" });
  if (fault && outcomes(next).includes("timeout")) {
    edges.push({ id: entityId("edge"), from_id: next.id, to_id: fault.id, outcome: "timeout" });
  }
  const nodes = [...flow.nodes];
  nodes.splice(createdDone ? 0 : nodes.findIndex((node) => node.id === target), 0, next);
  if (createdDone) nodes.push(createdDone);
  if (createdFault) nodes.push(createdFault);
  return { nodes, edges, start: !flow.start || flow.start === target ? next.id : flow.start };
}

function collect(design: StationDesign) {
  const records = new Map<string, { name: string; value: unknown }>();
  const add = (id: string, name: string, value: unknown) => { records.set(id, { name, value }); };
  const flow = (item: Flow, scope: string) => {
    add(scope, "流程起点", item.start);
    item.nodes.forEach((node) => add(node.id, node.name, node));
    item.edges.forEach((edge) => add(edge.id, "流程连线", edge));
    item.wires?.forEach((wire) => add(wire.id, "信号连线", wire));
  };
  add("project", design.name, design.name);
  add("hardware", "PLC 与通信", { cpu: design.hardware.cpu, network: design.hardware.network });
  design.hardware.modules.forEach((item) => add(item.id, item.name, item));
  design.hardware.signals.forEach((item) => add(item.id, item.name, item));
  design.stations.forEach((item) => {
    add(item.id, item.name, { name: item.name, ports: item.public_ports });
    item.devices.forEach((device) => add(device.id, device.name, device));
    item.interlocks?.forEach((condition) => add(condition.id, condition.name, condition));
    flow(item.flow, item.id + "_flow");
  });
  flow(design.flow, "flow");
  return records;
}

export function designDiff(before: StationDesign, after: StationDesign) {
  const old = collect(before);
  const next = collect(after);
  return [...new Set([...old.keys(), ...next.keys()])].flatMap((key) => {
    const a = old.get(key), b = next.get(key);
    if (JSON.stringify(a?.value) === JSON.stringify(b?.value)) return [];
    return [{ id: key, name: (b ?? a)?.name ?? key, kind: a ? b ? "修改" : "移除" : "新增", before: a?.value, after: b?.value }];
  });
}
