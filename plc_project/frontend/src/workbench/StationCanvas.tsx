import React, { useMemo, useRef, useState } from "react";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow, useUpdateNodeInternals,
  type Connection, type Edge as GraphEdge, type Node as GraphNode, type NodeProps, type ReactFlowInstance, type XYPosition,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  actionNode, emptyFlow, entityId, newNode, NODE_LABEL, OUTCOME_LABEL, outcomes,
  type Device, type DeviceProfile, type Edge, type Flow, type Hardware, type Node, type NodeKind, type Outcome, type PortDefinition, type Station,
} from "./stationDesign";
import { formatFeedback, stepDetails } from "./StationSteps";
import { CanvasInspector } from "./StationCanvasInspector";
import { DATA_ONLY, nodePorts } from "./stationPorts";
import "./station-canvas.css";

type Entry = {
  id: string; label: string; detail?: string; category: string;
  make: () => { node: Node; device?: Device; station?: Station };
};
type Port = { source: string; exit: Outcome };
type Tile = GraphNode<{
  label: string; detail: string; kind: string; ports: Outcome[]; occupied: Outcome[];
  start?: boolean; change?: string; guarded?: boolean; problem?: boolean; open?: () => void; add?: (exit: Outcome) => void;
  signals?: PortDefinition[]; hiddenSignals?: number; toggleSignals?: () => void;
}>;
const MIME = "application/x-plc-canvas-entry";
const FLOW_TOOLS: NodeKind[] = ["start", "decision", "logic", "fork", "join", "done", "fault"];

function exitLabel(kind: string, exit: Outcome): string {
  if (kind === "action" && exit === "next") return "完成";
  return OUTCOME_LABEL[exit];
}

function CanvasTile({ id, data, selected }: NodeProps<Tile>) {
  const updateInternals = useUpdateNodeInternals();
  const ports = data.ports.join(",");
  const signalPorts = data.signals?.map((item) => item.id).join(",");
  React.useEffect(() => updateInternals(id), [id, ports, signalPorts, data.guarded, updateInternals]);
  return <article id={id} className="af-tile" data-kind={data.kind} data-change={data.change} data-problem={data.problem || undefined} data-selected={selected || undefined}
    onDoubleClick={(event) => { if (data.open) { event.stopPropagation(); data.open(); } }}>
    {data.kind !== "feedback" && !DATA_ONLY.has(data.kind) && <Handle id="in" type="target" position={Position.Left} aria-label="运行入口" />}
    {data.guarded && <Handle id="permission" type="target" position={Position.Bottom} isConnectable={false} />}
    <div className="af-tile-head">
      <span>{data.start ? "起点 · " : ""}{data.kind === "feedback" ? "互锁输入" : NODE_LABEL[data.kind as NodeKind]}</span>
      {(data.change || data.problem) && <span>{data.change ?? "需检查"}</span>}
    </div>
    <strong>{data.label}</strong>
    {data.detail && <small>{data.detail}</small>}
    {data.open && <button className="af-tile-open nodrag" type="button" onClick={data.open}>打开工位 ↗</button>}
    {data.ports.map((exit) => <div key={exit} className="af-tile-port" data-exit={exit}>
      <span>{exitLabel(data.kind, exit)}</span>
      {data.add && (exit === "branch" || !data.occupied.includes(exit)) &&
        <button className="af-port-add nodrag" type="button" aria-label={data.label + " · " + exitLabel(data.kind, exit) + "后添加节点"}
          onClick={() => data.add?.(exit)}>＋</button>}
      <Handle id={exit} type="source" position={Position.Right} style={{ top: "50%" }}
        aria-label={exitLabel(data.kind, exit) + "出口"} />
    </div>)}
    {data.toggleSignals && <button type="button" className="af-tile-open nodrag" onClick={data.toggleSignals}>
      {data.hiddenSignals ? "展开接口 · " + data.hiddenSignals : "收起接口"}
    </button>}
    {data.signals?.map((item) => <div className="af-tile-signal" data-direction={item.direction} key={item.id}>
      <span>{item.name}</span><code>{item.type}</code>
      <Handle id={"data-" + item.id} type={item.direction === "input" ? "target" : "source"}
        position={item.direction === "input" ? Position.Left : Position.Right}
        aria-label={item.name + (item.direction === "input" ? "信号输入" : "信号输出")} />
    </div>)}
    {data.kind === "feedback" && <Handle id="feedback" type="source" position={Position.Right} isConnectable={false} />}
  </article>;
}
const nodeTypes = { canvasTile: CanvasTile };

function makeCatalog(station: Station | undefined, stations: Station[], catalog: DeviceProfile[]): Entry[] {
  const flowEntry = (kind: NodeKind, detail?: string): Entry => ({
    id: kind, label: NODE_LABEL[kind], detail, category: "流程控制",
    make: () => ({ node: { ...newNode(kind), ...(kind === "wait" ? { duration_ms: 300 } : {}),
      ...(kind === "handoff" ? { timeout_ms: 3000 } : {}),
      ...(kind === "logic" ? { operator: "and" as const, ports: [
        { id: "a", name: "条件 A", direction: "input" as const, type: "BOOL" as const, default: false },
        { id: "b", name: "条件 B", direction: "input" as const, type: "BOOL" as const, default: false },
      ] } : {}) } }),
  });
  if (!station) {
    return [
      { id: "new-station", label: "新建工位", detail: "创建工位并放到项目中", category: "工位", make: () => {
        const item: Station = { id: entityId("st"), name: "工位 " + (stations.length + 1), devices: [], flow: emptyFlow() };
        return { station: item, node: { ...newNode("station"), name: item.name, station_ids: [item.id] } };
      } },
      ...stations.map((item): Entry => ({
        id: item.id, label: item.name, detail: item.devices.length + " 个设备", category: "工位",
        make: () => ({ node: { ...newNode("station"), name: item.name, station_ids: [item.id] } }),
      })),
      ...FLOW_TOOLS.map((kind) => flowEntry(kind)),
      flowEntry("handoff", "就绪 → 启动请求 → 接收确认"),
    ];
  }
  const templates = catalog.map((item): Entry => ({
    id: item.id, label: item.label, detail: item.actions.map((action) => action.label).join(" · ") || item.interface,
    category: item.category, make: () => {
      const amount = station.devices.filter((device) => device.driver === item.id).length;
      const device: Device = { id: entityId("dev"), name: item.label + (amount ? " " + (amount + 1) : ""), driver: item.id, bindings: {}, timeout_ms: 0 };
      const first = item.actions[0];
      const input = Object.keys(item.ports).find((key) => item.ports[key] === "input");
      const node = first ? actionNode(device, first) : { ...newNode("wait"), name: "等待 " + device.name,
        device_id: input ? device.id : null, port: input ?? null, pending_feedback: !input, timeout_ms: 2000 };
      return { node, device };
    },
  }));
  const existing = station.devices.flatMap((device): Entry[] => {
    const spec = catalog.find((item) => item.id === device.driver);
    if (!spec) return [];
    return [
      ...(!station.flow.nodes.some((item) => item.kind === "device" && item.device_id === device.id) ? [{
        id: device.id + "/interface", label: device.name + " · 驱动接口", detail: "控制与状态信号", category: "已有设备",
        make: () => ({ node: { ...newNode("device"), name: device.name + " · 驱动接口", device_id: device.id } }),
      }] : []),
      ...spec.actions.map((action): Entry => ({
        id: device.id + "/" + action.id, label: device.name + " · " + action.label, category: "已有设备",
        make: () => ({ node: actionNode(device, action) }),
      })),
      ...Object.entries(spec.ports).filter(([, kind]) => kind === "input").map(([port]): Entry => ({
        id: device.id + "/input/" + port, label: device.name + " · " + spec.port_labels[port], category: "已有设备",
        make: () => ({ node: { ...newNode("wait"), name: "等待 " + device.name + " · " + spec.port_labels[port], device_id: device.id, port, timeout_ms: 2000 } }),
      })),
    ];
  });
  return [...existing, ...FLOW_TOOLS.map((kind) => flowEntry(kind)), flowEntry("wait", "等待反馈或定时"),
    ...(!station.flow.nodes.some((item) => item.kind === "interface") ? [flowEntry("interface", "编辑工位公开端口")] : []), ...templates];
}

function defaultPositions(flow: Flow): Record<string, XYPosition> {
  const positions: Record<string, XYPosition> = Object.create(null);
  for (const node of flow.nodes) if (node.position) positions[node.id] = node.position;
  let slot = 0;
  for (const node of flow.nodes) {
    if (positions[node.id]) continue;
    let candidate: XYPosition;
    do {
      candidate = { x: 48 + (slot % 3) * 260, y: 54 + Math.floor(slot / 3) * 218 };
      slot++;
    } while (Object.values(positions).some((point) => Math.abs(point.x - candidate.x) < 208 && Math.abs(point.y - candidate.y) < 184));
    positions[node.id] = candidate;
  }
  return positions;
}

function comparableNode(node: Node): string {
  const value = { ...node, actions: node.actions ?? [], completion: node.completion ?? [], pending_feedback: node.pending_feedback ?? false,
    signal_id: node.signal_id ?? null, permissions: node.permissions ?? [], position: node.position ?? null,
    operator: node.operator ?? null, ports: node.ports ?? [] };
  return JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
}

export function StationCanvas({ flow, station, stations, hardware, catalog, selected, select, update, openStation, preview, previewStation, problemIds, projectFlow }: {
  flow: Flow; station?: Station; stations: Station[]; hardware: Hardware; catalog: DeviceProfile[];
  selected: string; select: (id: string) => void;
  update: (flow: Flow, additions?: { device?: Device; station?: Station }) => void;
  openStation: (id: string) => void; preview?: Flow; previewStation?: Station; problemIds: Set<string>;
  projectFlow?: Flow;
}) {
  const viewport = useRef<ReactFlowInstance<Tile, GraphEdge> | null>(null);
  const fitOnEntry = useRef(flow.nodes.length > 0);
  const surface = useRef<HTMLDivElement | null>(null);
  const search = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [edgeId, setEdgeId] = useState("");
  const [from, setFrom] = useState<Port | null>(null);
  const [drag, setDrag] = useState<{ id: string; position: XYPosition } | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [connectionError, setConnectionError] = useState("");
  const entries = useMemo(() => makeCatalog(station, stations, catalog), [station, stations, catalog]);
  const categories = [...new Set(entries.map((item) => item.category))];
  const visible = entries.filter((item) => (!category || category === item.category) &&
    (item.label + " " + (item.detail ?? "")).toLowerCase().includes(query.trim().toLowerCase()));
  const active = preview ?? flow;
  const position = defaultPositions(active);
  const node = active.nodes.find((item) => item.id === selected);
  const edge = active.edges.find((item) => item.id === edgeId);
  const wire = active.wires?.find((item) => item.id === edgeId);

  React.useEffect(() => {
    if (!preview) return;
    const task = window.setTimeout(() => void viewport.current?.fitView({ maxZoom: 1, padding: .16 }), 100);
    return () => window.clearTimeout(task);
  }, [preview]);

  React.useEffect(() => {
    if (!expanded.size) return;
    const task = window.setTimeout(() => {
      const view = surface.current?.getBoundingClientRect();
      if (!view) return;
      const clipped = [...expanded].some((id) => {
        const box = document.getElementById(id)?.getBoundingClientRect();
        return box && (box.bottom > view.bottom || box.top < view.top || box.left < view.left || box.right > view.right);
      });
      if (clipped) void viewport.current?.fitView({ maxZoom: 1, padding: .16 });
    }, 90);
    return () => window.clearTimeout(task);
  }, [expanded]);

  function setNode(id: string) {
    setEdgeId("");
    select(id);
  }

  function connection(source: string, exit: Outcome, target: string, replace?: string): Edge[] | undefined {
    const origin = flow.nodes.find((item) => item.id === source);
    if (!origin || source === target || !outcomes(origin).includes(exit)) return;
    const remaining = flow.edges.filter((item) => item.id !== replace);
    if (remaining.some((item) => item.from_id === source && item.outcome === exit && (exit !== "branch" || item.to_id === target))) return;
    return [...remaining, { id: replace || entityId("edge"), from_id: source, to_id: target, outcome: exit }];
  }

  function connect(value: Connection, replace?: string) {
    if (preview || !value.source || !value.target) return;
    setConnectionError("");
    if (value.sourceHandle?.startsWith("data-") || value.targetHandle?.startsWith("data-")) {
      const origin = flow.nodes.find((item) => item.id === value.source);
      const end = flow.nodes.find((item) => item.id === value.target);
      const source = origin && nodePorts(origin, station, stations, catalog).find((item) => "data-" + item.id === value.sourceHandle && item.direction === "output");
      const target = end && nodePorts(end, station, stations, catalog).find((item) => "data-" + item.id === value.targetHandle && item.direction === "input");
      if (!source || !target || source.type !== target.type || value.source === value.target) {
        setConnectionError("请连接类型一致的信号输出与输入。");
        return;
      }
      const existing = (flow.wires ?? []).filter((item) => item.id !== replace);
      if (existing.some((item) => item.to_id === value.target && item.to_port === target.id)) {
        setConnectionError("该输入已连接，请先解除原信号线。");
        return;
      }
      const pending = [value.source];
      const seen = new Set<string>();
      while (pending.length) {
        const key = pending.pop()!;
        if (key === value.target) { setConnectionError("这条连线会形成信号循环。"); return; }
        if (seen.has(key)) continue;
        seen.add(key);
        pending.push(...existing.filter((item) => item.to_id === key).map((item) => item.from_id));
      }
      update({ ...flow, wires: [...existing, { id: replace || entityId("wire"), from_id: value.source, from_port: source.id, to_id: value.target, to_port: target.id }] });
      return;
    }
    if (value.targetHandle !== "in") return;
    const next = connection(value.source, value.sourceHandle as Outcome, value.target, replace);
    if (next) update({ ...flow, edges: next });
  }

  function add(entry: Entry, point?: XYPosition, wire = from) {
    if (preview) return;
    const created = entry.make();
    if (wire && DATA_ONLY.has(created.node.kind)) {
      setConnectionError("此节点使用信号端口，可以直接拖入画布。");
      return;
    }
    setConnectionError("");
    const box = surface.current?.getBoundingClientRect();
    const after = wire && position[wire.source];
    const center = box && viewport.current?.screenToFlowPosition({ x: box.left + box.width / 2 - 85, y: box.top + 95 });
    const coord = { ...(point ?? (after ? { x: after.x + 270, y: after.y } : center) ?? { x: 64, y: 64 }) };
    if (!point) {
      const occupied = Object.values(position);
      while (occupied.some((item) => Math.abs(item.x - coord.x) < 204 && Math.abs(item.y - coord.y) < 184)) coord.y += 190;
    }
    created.node.position = { x: Math.round(coord.x), y: Math.round(coord.y) };
    const edges = wire ? connection(wire.source, wire.exit, created.node.id) : flow.edges;
    if (!edges) return;
    update({ ...flow, start: flow.start ?? (DATA_ONLY.has(created.node.kind) ? null : created.node.id), nodes: [...flow.nodes, created.node], edges }, created);
    setNode(created.node.id);
    setFrom(null);
  }

  function chooseNext(source: string, exit: Outcome) {
    setFrom({ source, exit });
    setQuery("");
    setCategory("");
    search.current?.focus();
  }

  const graphNodes: Tile[] = [];
  const graphEdges: GraphEdge[] = [];
  const oldNodes = new Map(flow.nodes.map((item) => [item.id, item]));
  const shown = preview ? [...active.nodes, ...flow.nodes.filter((item) => !active.nodes.some((next) => next.id === item.id))] : active.nodes;
  const oldPositions = preview ? defaultPositions(flow) : position;
  const shownWires = [...(active.wires ?? []), ...(preview ? (flow.wires ?? []).filter((wire) =>
    !active.wires?.some((item) => item.id === wire.id)) : [])];
  for (const item of shown) {
    const stationId = !station && item.kind === "station" ? item.station_ids[0] : "";
    const target = stations.find((entry) => entry.id === stationId);
    const at = drag?.id === item.id ? drag.position : position[item.id] ?? oldPositions[item.id];
    const original = oldNodes.get(item.id);
    const removed = !position[item.id];
    const change = preview ? removed ? "移除" : !original ? "新增" :
      comparableNode(original) === comparableNode(item) ? undefined : "修改" : undefined;
    const deviceScope = previewStation ?? station;
    const typed = nodePorts(item, deviceScope, stations, catalog);
    const wired = new Set(shownWires.flatMap((entry) =>
      entry.from_id === item.id ? [entry.from_port] : entry.to_id === item.id ? [entry.to_port] : []));
    const showPorts = item.kind === "logic" || item.kind === "interface" || expanded.has(item.id);
    const visibleSignals = showPorts ? typed : typed.filter((port) => wired.has(port.id));
    const details = deviceScope ? stepDetails(item, deviceScope, catalog) : "";
    graphNodes.push({
      id: item.id, type: "canvasTile", position: at, selected: selected === item.id,
      data: {
        label: target?.name ?? item.name, kind: item.kind, change, start: active.start === item.id, problem: problemIds.has(item.id),
        detail: details || (target ? target.devices.length + " 个设备" : ""),
        ports: outcomes(item), occupied: active.edges.filter((line) => line.from_id === item.id).map((line) => line.outcome),
        guarded: Boolean(item.permissions?.length), open: !preview && target ? () => openStation(target.id) : undefined,
        add: !preview ? (exit) => chooseNext(item.id, exit) : undefined,
        signals: visibleSignals, hiddenSignals: typed.length - visibleSignals.length,
        toggleSignals: typed.length && item.kind !== "logic" && item.kind !== "interface" ? () => setExpanded((previous) => {
          const next = new Set(previous);
          if (next.has(item.id)) next.delete(item.id);
          else next.add(item.id);
          return next;
        }) : undefined,
      },
    });
    item.permissions?.forEach((rule, i) => {
      if (!deviceScope) return;
      const id = "permission-" + rule.id;
      graphNodes.push({ id, type: "canvasTile", position: { x: at.x - 221, y: at.y + 149 + i * 85 }, draggable: false, selectable: false,
        data: { kind: "feedback", label: formatFeedback(rule, deviceScope, catalog), detail: rule.mode === "start" ? "启动前检查" : "持续检查", ports: [], occupied: [] } });
      graphEdges.push({ id, source: id, sourceHandle: "feedback", target: item.id, targetHandle: "permission",
        type: "smoothstep", className: "af-permission-edge", selectable: false, reconnectable: false });
    });
  }
  for (const item of shownWires) {
    const previous = flow.wires?.find((entry) => item.id === entry.id);
    const style = preview ? !active.wires?.some((entry) => entry.id === item.id) ? "removed"
      : !previous || JSON.stringify(previous) !== JSON.stringify(item) ? "changed" : "" : "";
    graphEdges.push({ id: item.id, source: item.from_id, sourceHandle: "data-" + item.from_port,
      target: item.to_id, targetHandle: "data-" + item.to_port, type: "smoothstep", selected: edgeId === item.id,
      className: "af-signal-edge " + style, markerEnd: { type: MarkerType.ArrowClosed, color: "var(--accent-sage-ink)" } });
  }
  const compare = new Map(active.edges.map((item) => [item.id, item]));
  const previousEdges = new Map(flow.edges.map((item) => [item.id, item]));
  for (const line of [...active.edges, ...(preview ? flow.edges.filter((item) => !compare.has(item.id)) : [])]) {
    const fault = ["fault", "timeout", "blocked", "false"].includes(line.outcome);
    const old = previousEdges.get(line.id);
    const style = preview ? !compare.has(line.id) ? "removed" : !old || JSON.stringify(line) !== JSON.stringify(old) ? "changed" : "" : "";
    graphEdges.push({
      id: line.id, source: line.from_id, sourceHandle: line.outcome, target: line.to_id, targetHandle: "in",
      type: "smoothstep", selected: edgeId === line.id, className: "af-route " + (fault ? "af-route-alert " : "") + style,
      markerEnd: { type: MarkerType.ArrowClosed, color: fault ? "var(--accent-clay-ink)" : "var(--ink-secondary)" },
    });
  }

  return <section className="af-canvas-workspace" aria-label={station ? "工位画布" : "项目主画布"}>
    <aside className="af-node-library" aria-label="节点库">
      <div className="af-canvas-panel-title"><h2>节点库</h2><span>{visible.length}</span></div>
      <label className="af-canvas-search"><span className="af-visually-hidden">搜索节点</span><input ref={search} type="search" placeholder="搜索工位、设备、动作" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <label className="af-canvas-search"><span className="af-visually-hidden">节点类别</span><select aria-label="节点类别" value={category} onChange={(event) => setCategory(event.target.value)}>
        <option value="">所有类别</option>
        {categories.map((name) => <option key={name}>{name}</option>)}
      </select></label>
      {from && <div className="af-insert-port">连接「{flow.nodes.find((item) => item.id === from.source)?.name}」的{OUTCOME_LABEL[from.exit]}出口
        <button className="k-btn k-btn--sm" type="button" onClick={() => setFrom(null)}>取消</button>
      </div>}
      <div className="af-node-library-items">
        {visible.map((item) => <button key={item.id} type="button" className="af-palette-item" draggable={!preview} disabled={Boolean(preview)}
          title={item.detail} onClick={() => add(item)} onDragStart={(event) => {
            event.dataTransfer.setData(MIME, item.id);
            event.dataTransfer.effectAllowed = "copy";
          }}>
          <span><strong>{item.label}</strong>{item.detail && <small>{item.detail}</small>}</span><span aria-hidden="true">＋</span>
        </button>)}
        {!visible.length && <p className="af-context">没有匹配节点</p>}
      </div>
    </aside>
    <div className="af-canvas-sheet">
      <div className="af-canvas-sheet-bar"><strong>{preview ? "提案预览" : station ? station.name : "项目编排"}</strong>
        <span>{active.nodes.length} 节点 · {active.edges.length} 连线</span>
      </div>
      <div ref={surface} className="af-graph af-canvas-surface" onDragOver={(event) => {
        if (!preview && event.dataTransfer.types.includes(MIME)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }
      }} onDrop={(event) => {
        const entry = entries.find((item) => item.id === event.dataTransfer.getData(MIME));
        if (!entry) return;
        event.preventDefault();
        add(entry, viewport.current?.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
      }}>
        <ReactFlow<Tile, GraphEdge> nodes={graphNodes} edges={graphEdges} nodeTypes={nodeTypes} onInit={(api) => { viewport.current = api; }}
          onConnect={connect} onReconnect={(line, value) => {
            const typedEdge = Boolean(line.sourceHandle?.startsWith("data-"));
            if (typedEdge === Boolean(value.sourceHandle?.startsWith("data-"))) connect(value, line.id);
          }}
          onNodeClick={(_, item) => setNode(item.id)}
          onEdgeClick={(_, item) => { setEdgeId(item.id); select(""); }}
          onPaneClick={() => { setEdgeId(""); select(""); }}
          onNodeDrag={(_, item) => setDrag({ id: item.id, position: item.position })}
          onNodeDragStop={(_, item) => {
            setDrag(null);
            if (preview) return;
            const { x, y } = item.position;
            update({ ...flow, nodes: flow.nodes.map((current) => current.id === item.id ?
              { ...current, position: { x: Math.round(x), y: Math.round(y) } } : current) });
          }}
          nodesConnectable={!preview} nodesDraggable={!preview} edgesReconnectable={!preview}
          selectionOnDrag={false} zoomOnDoubleClick={false} deleteKeyCode={null} fitView={fitOnEntry.current} fitViewOptions={{ maxZoom: 1, padding: 0.16 }}
          minZoom={0.25} maxZoom={1.75} proOptions={{ hideAttribution: true }}>
          <Background color="var(--ink-faint)" gap={22} />
          <Controls showInteractive={false} />
        </ReactFlow>
        {!shown.length && <div className="af-canvas-empty"><h2>{station ? "从设备动作开始" : "从第一个工位开始"}</h2>
          <p>把节点从左侧拖到这里。连接对应端口来编排流程。</p></div>}
      </div>
      <div className="af-canvas-sheet-bar af-canvas-legend"><span>实线 · 执行顺序</span><span>绿线 · 类型信号</span>{station && <span>虚线 · 互锁许可</span>}
        {connectionError && <span role="alert" className="af-pending">{connectionError}</span>}</div>
    </div>
    <CanvasInspector node={node} edge={edge} flow={active} station={previewStation ?? station} stations={stations} hardware={hardware}
      catalog={catalog} preview={Boolean(preview)} update={(value) => update(value)} openStation={openStation} wire={wire}
      removeWire={(id) => { update({ ...flow, wires: flow.wires?.filter((item) => item.id !== id) }); setEdgeId(""); }}
      unitPortUsed={(port) => Boolean(station && projectFlow?.wires?.some((line) =>
        projectFlow.nodes.some((call) => call.station_ids.includes(station.id) &&
          ((line.from_id === call.id && line.from_port === port) || (line.to_id === call.id && line.to_port === port)))))}
      editDevice={(device) => {
        const oldName = station?.devices.find((item) => item.id === device.id)?.name ?? "";
        const nodes = flow.nodes.map((item) => {
          if (item.actions?.[0]?.device_id === device.id && item.name.startsWith(oldName + " · ")) {
            return { ...item, name: (device.name + item.name.slice(oldName.length)).slice(0, 100) };
          }
          if (item.device_id === device.id && item.name.startsWith("等待 " + oldName)) {
            return { ...item, name: ("等待 " + device.name + item.name.slice(3 + oldName.length)).slice(0, 100) };
          }
          return item;
        });
        update({ ...flow, nodes }, { device });
      }}
      renameStation={(value) => update({ ...flow, nodes: flow.nodes.map((item) =>
        item.kind === "station" && item.station_ids[0] === value.id ? { ...item, name: value.name } : item) }, { station: value })}
      removeEdge={(id) => { update({ ...flow, edges: flow.edges.filter((item) => item.id !== id) }); setEdgeId(""); }}
      retarget={(line, target) => { const edges = connection(line.from_id, line.outcome, target, line.id); if (edges) update({ ...flow, edges }); }}
      removeNode={(id) => {
        update({ ...flow, start: flow.start === id ? null : flow.start,
          nodes: flow.nodes.filter((item) => item.id !== id), edges: flow.edges.filter((item) => item.from_id !== id && item.to_id !== id),
          wires: flow.wires?.filter((item) => item.from_id !== id && item.to_id !== id) });
        if (from?.source === id) setFrom(null);
        setNode("");
      }} />
  </section>;
}
