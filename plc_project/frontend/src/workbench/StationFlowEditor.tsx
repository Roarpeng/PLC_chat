import React, { useState } from "react";
import { Background, Controls, MarkerType, ReactFlow, type Connection, type XYPosition } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  NODE_LABEL, OUTCOME_LABEL, entityId, newNode, outcomes, primarySteps,
  type DeviceProfile, type Flow, type Node, type NodeKind, type Outcome, type Station,
} from "./stationDesign";
import { stepDetails } from "./StationSteps";

const STATION_TOOLS: NodeKind[] = ["action", "wait", "decision", "done", "fault"];
const PROJECT_TOOLS: NodeKind[] = ["station", "parallel", "done", "fault"];

export function StationFlowEditor({
  flow, station, stations, selected, setSelected, update, timeline, openStation, catalog, openSteps,
}: {
  flow: Flow; station?: Station; stations: Station[]; selected: string; setSelected: (key: string) => void;
  update: (flow: Flow) => void; timeline: boolean; openStation: (id: string) => void;
  catalog: DeviceProfile[]; openSteps: () => void;
}) {
  const [positions, setPositions] = useState<Record<string, XYPosition>>({});
  const [kind, setKind] = useState<NodeKind>(station ? "action" : "station");
  const [target, setTarget] = useState("");
  const [exit, setExit] = useState<Outcome>("next");
  const node = flow.nodes.find((item) => item.id === selected);

  function connect({ source, target: end }: Connection) {
    if (!source || !end) return;
    const start = flow.nodes.find((item) => item.id === source);
    const available = start && outcomes(start).find((value) =>
      !flow.edges.some((edge) => edge.from_id === source && edge.outcome === value));
    if (available) update({ ...flow, edges: [...flow.edges, { id: entityId("edge"), from_id: source, to_id: end, outcome: available }] });
  }

  function change(fields: Partial<Node>) {
    if (node) update({ ...flow, nodes: flow.nodes.map((item) => item.id === node.id ? { ...item, ...fields } : item) });
  }

  const device = station?.devices.find((item) => item.id === node?.device_id);
  const profile = device && catalog.find((item) => item.id === device.driver);
  const nodePortType = node?.kind === "action" ? "output" : "input";
  const choices = node ? outcomes(node) : [];
  const chosenExit = choices.includes(exit) ? exit : choices[0];

  return (
    <div className="af-flow-layout">
      <section className="af-pane">
        <div className="af-section-head">
          <h2 className="k-title">{timeline ? "时序参数" : station ? "工位逻辑图" : "项目逻辑图"}</h2>
          {!timeline && <>
            <label>节点类型<select aria-label="节点类型" value={kind} onChange={(event) => setKind(event.target.value as NodeKind)}>
              {(station ? STATION_TOOLS : PROJECT_TOOLS).map((key) => <option key={key} value={key}>{NODE_LABEL[key]}</option>)}
            </select></label>
            <button className="k-btn k-btn--sm" onClick={() => {
              const added = newNode(kind);
              update({ ...flow, start: flow.start || added.id, nodes: [...flow.nodes, added] });
              setSelected(added.id);
            }}>添加节点</button>
          </>}
        </div>
        {!flow.nodes.length ? <p className="k-hatch">添加节点以建立流程。</p> : timeline ? (
          <div className="af-timeline">
            {(station ? primarySteps(flow) : flow.nodes).map((item) => (
              <div className="af-record" key={item.id}>
                <button className="k-btn k-btn--sm" onClick={() => setSelected(item.id)} aria-pressed={item.id === selected}>{item.name}</button>
                <span>{NODE_LABEL[item.kind]}</span>
                {Boolean(item.kind === "wait" || item.completion?.length) && <label>{outcomes(item).includes("timeout") ? "超时（ms）" : "保持（ms）"}
                  <input type="number" min="0" value={outcomes(item).includes("timeout") ? item.timeout_ms : item.duration_ms} onChange={(event) => {
                    const key = outcomes(item).includes("timeout") ? "timeout_ms" : "duration_ms";
                    const time = Number(event.target.value);
                    const name = key === "duration_ms" && /^等待 \d+ ms$/.test(item.name) ? "等待 " + time + " ms" : item.name;
                    update({ ...flow, nodes: flow.nodes.map((node) => node.id === item.id ? { ...node, name, [key]: time } : node) });
                  }} />
                </label>}
                <span>{flow.edges.filter((edge) => edge.from_id === item.id).map((edge) =>
                  OUTCOME_LABEL[edge.outcome] + " → " + flow.nodes.find((next) => next.id === edge.to_id)?.name).join(" / ")}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="af-graph" aria-label="逻辑流程图">
            <ReactFlow
              nodes={flow.nodes.map((item, index) => ({
                id: item.id, position: positions[item.id] ?? { x: (index % 3) * 204, y: Math.floor(index / 3) * 118 },
                data: { label: (flow.start === item.id ? "起点 · " : "") + item.name },
                selected: item.id === selected, type: outcomes(item).length ? undefined : "output",
              }))}
              edges={flow.edges.map((edge) => ({
                id: edge.id, source: edge.from_id, target: edge.to_id, label: OUTCOME_LABEL[edge.outcome],
                markerEnd: { type: MarkerType.ArrowClosed, color: "var(--ink-secondary)" },
              }))}
              onConnect={connect}
              onNodeClick={(_, item) => setSelected(item.id)}
              onNodeDoubleClick={(_, item) => {
                const target = flow.nodes.find((entry) => entry.id === item.id);
                if (!station && target?.kind === "station" && target.station_ids[0]) openStation(target.station_ids[0]);
              }}
              onNodeDrag={(_, item) => setPositions((previous) => ({ ...previous, [item.id]: item.position }))}
              nodesConnectable={!timeline}
              deleteKeyCode={null}
              fitView
              minZoom={0.25}
              maxZoom={1.75}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="var(--border-line)" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        )}
        {flow.nodes.length > 0 && <label className="af-node-jump">选择节点<select aria-label="选择节点" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">选择…</option>
          {flow.nodes.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
        </select></label>}
      </section>
      <aside className="af-pane af-node-inspector">
        <h2 className="k-title">节点检查器</h2>
        {!node ? <p className="k-hatch">选择节点以编辑参数和连线。</p> : (
          <div className="af-stack">
            <label>节点名称<input value={node.name} onChange={(event) => change({ name: event.target.value })} /></label>
            <code>{node.id}</code>
            {station && Boolean(node.actions?.length || node.pending_feedback) && <>
              <p>{stepDetails(node, station, catalog)}</p>
              <button type="button" className="k-btn k-btn--sm" onClick={openSteps}>编辑设备动作和反馈</button>
            </>}
            {station && !node.actions?.length && !node.pending_feedback && (node.kind === "action" || node.kind === "decision" || node.kind === "wait") && <>
              <label>设备<select aria-label="设备" value={node.device_id ?? ""} onChange={(event) => change({
                device_id: event.target.value || null, port: null, pending_feedback: false,
                timeout_ms: event.target.value ? node.timeout_ms : 0,
              })}>
                <option value="">{node.kind === "wait" ? "定时等待" : "请选择设备"}</option>
                {station.devices.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
              </select></label>
              {device && <>
                <label>端口<select aria-label="端口" value={node.port ?? ""} onChange={(event) => change({ port: event.target.value || null })}>
                  <option value="">请选择端口</option>
                  {Object.entries(profile?.ports ?? {}).filter(([, type]) => type === nodePortType).map(([port]) =>
                    <option value={port} key={port}>{profile?.port_labels[port] ?? port}</option>)}
                </select></label>
                <label>布尔值<select value={String(node.value)} onChange={(event) => change({ value: event.target.value === "true" })}>
                  <option value="true">TRUE</option><option value="false">FALSE</option>
                </select></label>
              </>}
              {node.kind === "wait" && <label>{device ? "等待超时（ms）" : "保持时间（ms）"}
                <input type="number" min="0" max="86400000" value={device ? node.timeout_ms : node.duration_ms}
                  onChange={(event) => change({ [device ? "timeout_ms" : "duration_ms"]: Number(event.target.value) })} />
              </label>}
            </>}
            {node.kind === "station" && <label>运行工位<select aria-label="运行工位" value={node.station_ids[0] ?? ""}
              onChange={(event) => change({ station_ids: event.target.value ? [event.target.value] : [] })}>
              <option value="">选择工位</option>
              {stations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>}
            {node.kind === "parallel" && <fieldset className="af-stations-check">
              <legend>并行工位</legend>
              {stations.map((item) => <label key={item.id}>
                <input type="checkbox" checked={node.station_ids.includes(item.id)}
                  onChange={(event) => change({ station_ids: event.target.checked ? [...node.station_ids, item.id] : node.station_ids.filter((id) => id !== item.id) })} />
                {item.name}
              </label>)}
            </fieldset>}
            {choices.length > 0 && <>
              <label>出口<select aria-label="出口" value={chosenExit} onChange={(event) => setExit(event.target.value as Outcome)}>
                {choices.map((value) => <option value={value} key={value}>{OUTCOME_LABEL[value]}</option>)}
              </select></label>
              <label>目标节点<select aria-label="目标节点" value={target} onChange={(event) => setTarget(event.target.value)}>
                <option value="">选择目标</option>
                {flow.nodes.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
              </select></label>
              <button className="k-btn k-btn--sm" disabled={!target || !flow.nodes.some((item) => item.id === target)} onClick={() => update({
                ...flow, edges: [...flow.edges.filter((edge) => edge.from_id !== node.id || edge.outcome !== chosenExit),
                  { id: entityId("edge"), from_id: node.id, to_id: target, outcome: chosenExit }],
              })}>应用连线</button>
            </>}
            {flow.edges.filter((edge) => edge.from_id === node.id).map((edge) => (
              <div className="af-edge" key={edge.id}>
                {OUTCOME_LABEL[edge.outcome]} → {flow.nodes.find((item) => item.id === edge.to_id)?.name}
                <button className="k-btn k-btn--sm" onClick={() => update({ ...flow, edges: flow.edges.filter((item) => item.id !== edge.id) })}>移除连线</button>
              </div>
            ))}
            <button className="k-btn k-btn--sm" disabled={flow.start === node.id} onClick={() => update({ ...flow, start: node.id })}>设为起点</button>
            <button className="k-btn k-btn--sm" onClick={() => {
              update({ ...flow, start: flow.start === node.id ? null : flow.start,
                nodes: flow.nodes.filter((item) => item.id !== node.id),
                edges: flow.edges.filter((edge) => edge.from_id !== node.id && edge.to_id !== node.id) });
              setSelected("");
            }}>移除节点和连线</button>
          </div>
        )}
      </aside>
    </div>
  );
}
