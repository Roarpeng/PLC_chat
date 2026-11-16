import React, { useState } from "react";
import {
  actionNode, entityId, NODE_LABEL, OUTCOME_LABEL, outcomes,
  type Device, type DeviceProfile, type Edge, type Flow, type Hardware, type LogicOperator, type Node, type Permission, type SignalWire, type Station,
} from "./stationDesign";
import { formatFeedback } from "./StationSteps";
import { DATA_ONLY, nodePorts } from "./stationPorts";
import { StationPortEditor } from "./StationPortEditor";

export function CanvasInspector({ node, edge, flow, station, stations, hardware, catalog, preview, update, openStation,
  removeEdge, removeNode, retarget, editDevice, renameStation, wire, removeWire, unitPortUsed }: {
  node?: Node; edge?: Edge; flow: Flow; station?: Station; stations: Station[]; hardware: Hardware; catalog: DeviceProfile[];
  preview: boolean; update: (value: Flow) => void; openStation: (id: string) => void;
  removeEdge: (id: string) => void; removeNode: (id: string) => void; retarget: (line: Edge, target: string) => void;
  editDevice: (value: Device) => void; renameStation: (value: Station) => void;
  wire?: SignalWire; removeWire: (id: string) => void; unitPortUsed: (port: string) => boolean;
}) {
  const [permissionPort, setPermissionPort] = useState("");
  const [permissionValue, setPermissionValue] = useState(true);
  const [completionPort, setCompletionPort] = useState("");
  const [completionValue, setCompletionValue] = useState(true);
  const attached = station?.devices.find((item) => item.id === (node?.actions?.[0]?.device_id ?? node?.device_id));
  const attachedProfile = catalog.find((item) => item.id === attached?.driver);
  const called = node?.kind === "station" ? stations.find((item) => item.id === node.station_ids[0]) : undefined;
  const currentPorts = node ? nodePorts(node, station, stations, catalog) : [];
  const connected = (id: string) => Boolean(node && flow.wires?.some((item) =>
    (item.from_id === node.id && item.from_port === id) || (item.to_id === node.id && item.to_port === id)));
  const feedback = (station?.devices ?? []).flatMap((item) => {
    const profile = catalog.find((entry) => entry.id === item.driver);
    return Object.keys(profile?.ports ?? {}).filter((port) => profile?.ports[port] === "input").map((port) => ({
      key: item.id + "/" + port, device_id: item.id, port, label: item.name + " · " + profile?.port_labels[port],
    }));
  });
  const selectedFeedback = feedback.find((item) => item.key === permissionPort);
  const actionFeedback = feedback.find((item) => item.key === completionPort);

  function change(fields: Partial<Node>) {
    if (!node) return;
    const after = { ...node, ...fields };
    update({ ...flow, nodes: flow.nodes.map((item) => item.id === node.id ? after : item),
      edges: flow.edges.filter((item) => item.from_id !== node.id || outcomes(after).includes(item.outcome)) });
  }

  function editPermission(id: string, fields: Partial<Permission>) {
    change({ permissions: node?.permissions?.map((item) => item.id === id ? { ...item, ...fields } : item) });
  }

  return <aside className="af-canvas-inspector" aria-label="画布检查器">
    <div className="af-canvas-panel-title"><h2>{wire ? "信号连线" : edge ? "连线" : "节点检查器"}</h2></div>
    {!node && !edge && !wire && <p className="af-context">选择节点或连线查看设置。</p>}
    {wire && <fieldset disabled={preview} className="af-stack af-inspector-fields">
      <p>{flow.nodes.find((item) => item.id === wire.from_id)?.name} · {wire.from_port} → {flow.nodes.find((item) => item.id === wire.to_id)?.name} · {wire.to_port}</p>
      <button className="k-btn k-btn--sm" type="button" onClick={() => removeWire(wire.id)}>删除信号线</button>
    </fieldset>}
    {edge && <fieldset disabled={preview} className="af-stack af-inspector-fields">
      <p>{flow.nodes.find((item) => item.id === edge.from_id)?.name} · {OUTCOME_LABEL[edge.outcome]}</p>
      <label>连接到<select aria-label="连接到" value={edge.to_id} onChange={(event) => retarget(edge, event.target.value)}>
        {flow.nodes.filter((item) => item.id !== edge.from_id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <button className="k-btn k-btn--sm" type="button" onClick={() => removeEdge(edge.id)}>删除连线</button>
    </fieldset>}
    {node && <fieldset disabled={preview} className="af-stack af-inspector-fields">
      <p className="af-inspector-kind">{NODE_LABEL[node.kind]}</p>
      <label>{called ? "工位名称" : "节点名称"}<input aria-label={called ? "工位名称" : "节点名称"}
        value={called?.name ?? node.name} maxLength={100} onChange={(event) => {
          const name = event.target.value;
          if (called) renameStation({ ...called, name });
          else change({ name });
        }} /></label>
      {called && <button className="k-btn k-btn--sm" type="button" onClick={() => openStation(called.id)}>进入工位画布 ↗</button>}
      {node.kind === "handoff" && <label>目标工位<select aria-label="目标工位" value={node.station_ids[0] ?? ""}
        disabled={Boolean(flow.wires?.some((item) => item.from_id === node.id || item.to_id === node.id))}
        onChange={(event) => {
          const target = stations.find((item) => item.id === event.target.value);
          change({ station_ids: target ? [target.id] : [], name: target ? "交接至 " + target.name : "工位交接" });
        }}><option value="">选择目标工位</option>{stations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      {node.kind === "logic" && <>
        <label>逻辑运算<select aria-label="逻辑运算" value={node.operator ?? "and"}
          onChange={(event) => change({ operator: event.target.value as LogicOperator })}>
          <option value="and">与 AND</option><option value="or">或 OR</option><option value="not">非 NOT</option>
          <option value="eq">等于</option><option value="gt">大于</option><option value="lt">小于</option>
        </select></label>
        <StationPortEditor ports={node.ports ?? []} update={(ports) => change({ ports })} connected={connected} fixedDirection="input" />
      </>}
      {node.kind === "interface" && station && <>
        <p className="af-context">工位输入给内部节点提供信号，工位输出将内部信号发布到项目画布。</p>
        <StationPortEditor ports={station.public_ports ?? []}
          update={(public_ports) => renameStation({ ...station, public_ports })}
          connected={(id) => connected(id) || unitPortUsed(id)} />
      </>}
      {node.kind === "parallel" && <fieldset className="af-stations-check"><legend>并行工位</legend>
        {stations.map((item) => <label key={item.id}><input type="checkbox" checked={node.station_ids.includes(item.id)}
          onChange={(event) => change({ station_ids: event.target.checked ? [...node.station_ids, item.id] : node.station_ids.filter((id) => id !== item.id) })} />{item.name}</label>)}
      </fieldset>}
      {!station && node.kind === "decision" && <>
        <label>项目判断信号<select aria-label="项目判断信号" value={node.signal_id ?? ""} onChange={(event) => change({ signal_id: event.target.value || null })}>
          <option value="">选择输入信号</option>
          {hardware.signals.filter((item) => item.direction === "input").map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
        </select></label>
        <label>成立值<select aria-label="成立值" value={String(node.value)} onChange={(event) => change({ value: event.target.value === "true" })}>
          <option value="true">有效</option><option value="false">无效</option>
        </select></label>
      </>}
      {station && node.kind === "action" && node.actions?.length === 1 && attached && attachedProfile && <label>设备动作
        <select aria-label="设备动作" value={node.actions[0].action_id} onChange={(event) => {
          const preset = attachedProfile.actions.find((item) => item.id === event.target.value);
          if (preset) {
            const action = actionNode(attached, preset);
            change({ name: action.name, actions: action.actions, completion: action.completion, timeout_ms: action.timeout_ms });
          }
        }}>{attachedProfile.actions.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>}
      {station && node.kind === "action" && !node.actions?.length && <>
        <label>执行设备<select aria-label="执行设备" value={node.device_id ?? ""} onChange={(event) => change({ device_id: event.target.value || null, port: null })}>
          <option value="">选择执行设备</option>
          {station.devices.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
        </select></label>
        <label>输出端口<select aria-label="输出端口" value={node.port ?? ""} onChange={(event) => change({ port: event.target.value || null })}>
          <option value="">选择输出端口</option>
          {Object.entries(attachedProfile?.ports ?? {}).filter(([, direction]) => direction === "output").map(([port]) =>
            <option value={port} key={port}>{attachedProfile?.port_labels[port]}</option>)}
        </select></label>
        <label>输出值<select aria-label="输出值" value={String(node.value)} onChange={(event) => change({ value: event.target.value === "true" })}>
          <option value="true">有效</option><option value="false">无效</option>
        </select></label>
      </>}
      {station && (node.kind === "wait" || node.kind === "decision") && <>
        <label>反馈信号<select aria-label="反馈信号" value={node.device_id && node.port ? node.device_id + "/" + node.port : ""}
          onChange={(event) => {
            const item = feedback.find((entry) => entry.key === event.target.value);
            change({ device_id: item?.device_id ?? null, port: item?.port ?? null, pending_feedback: false,
              timeout_ms: node.kind === "wait" && item ? node.timeout_ms || 2000 : 0, duration_ms: item ? 0 : node.duration_ms || 300 });
          }}>
          <option value="">{node.pending_feedback ? "反馈待关联" : node.kind === "wait" ? "定时等待" : "请选择反馈"}</option>
          {feedback.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}
        </select></label>
        {(node.device_id || node.kind === "decision") && <label>期望值<select aria-label="期望值" value={String(node.value)}
          onChange={(event) => change({ value: event.target.value === "true" })}>
          <option value="true">有效</option><option value="false">无效</option>
        </select></label>}
        {node.kind === "wait" && !node.device_id && !node.pending_feedback && <label>等待时间（ms）
          <input type="number" min="1" max="86400000" value={node.duration_ms} onChange={(event) => change({ duration_ms: Number(event.target.value) })} />
        </label>}
      </>}
      {outcomes(node).includes("timeout") && <label>{node.kind === "handoff" ? "交接确认超时（ms）" : "完成超时（ms）"}
        <input aria-label={node.kind === "handoff" ? "交接确认超时（ms）" : "完成超时（ms）"} type="number" min="1" max="86400000" value={node.timeout_ms}
          onChange={(event) => change({ timeout_ms: Number(event.target.value) })} /></label>}
      {attached && attachedProfile && <details className="af-canvas-details">
        <summary>设备 I/O 绑定</summary>
        <label>设备名称<input aria-label="设备名称" value={attached.name} maxLength={100} onChange={(event) => editDevice({ ...attached, name: event.target.value })} /></label>
        {Object.entries(attachedProfile.ports).map(([port, direction]) => <label key={port}>{attachedProfile.port_labels[port]}
          <select aria-label={attachedProfile.port_labels[port]} value={attached.bindings[port] ?? ""} onChange={(event) => {
            const bindings = { ...attached.bindings };
            if (event.target.value) bindings[port] = event.target.value;
            else delete bindings[port];
            editDevice({ ...attached, bindings });
          }}>
            <option value="">未绑定</option>
            {hardware.signals.filter((item) => item.direction === direction).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>)}
      </details>}
      {attached?.driver === "cylinder" && <details className="af-canvas-details">
        <summary>气缸驱动参数</summary>
        {(["extend_timeout_ms", "retract_timeout_ms"] as const).map((field, index) => {
          const title = index === 0 ? "伸出超时（ms）" : "缩回超时（ms）";
          return <label key={field}>{title}<input aria-label={title} type="number" min="1" max="86400000"
            disabled={node.kind === "device" && connected(field.replace("_ms", ""))}
            value={attached[field] ?? ""} placeholder={String(attached.timeout_ms || 2000)}
            onChange={(event) => editDevice({ ...attached, [field]: event.target.value ? Number(event.target.value) : null })} /></label>;
        })}
      </details>}
      {currentPorts.length > 0 && <details className="af-canvas-details">
        <summary>接口信号 · {currentPorts.length}</summary>
        {currentPorts.map((item) => <p key={item.id}><small>{item.direction === "input" ? "输入" : "输出"} · {item.name} · {item.type}</small></p>)}
      </details>}
      {station && Boolean(node.actions?.length) && <details className="af-canvas-details">
        <summary>完成反馈{node.completion?.length ? " · " + node.completion.length : ""}</summary>
        {(node.completion ?? []).map((item) => <div key={item.device_id + "/" + item.port} className="af-inspector-rule">
          <small>{formatFeedback(item, station, catalog)}</small>
          <button className="k-btn k-btn--sm" type="button"
            onClick={() => change({ completion: node.completion?.filter((current) => current !== item) })}>移除反馈</button>
        </div>)}
        <label>新增完成反馈<select aria-label="新增完成反馈" value={completionPort} onChange={(event) => setCompletionPort(event.target.value)}>
          <option value="">选择输入信号</option>{feedback.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select></label>
        <label>反馈期望值<select aria-label="反馈期望值" value={String(completionValue)} onChange={(event) => setCompletionValue(event.target.value === "true")}>
          <option value="true">有效</option><option value="false">无效</option>
        </select></label>
        <button className="k-btn k-btn--sm" type="button" disabled={!actionFeedback} onClick={() => {
          if (!actionFeedback) return;
          const { device_id, port } = actionFeedback;
          change({ completion: [...(node.completion ?? []).filter((item) => item.device_id !== device_id || item.port !== port),
            { device_id, port, value: completionValue }], timeout_ms: node.timeout_ms || 2000 });
          setCompletionPort("");
        }}>添加完成反馈</button>
      </details>}
      {station && node.kind === "action" && <details className="af-canvas-details">
        <summary>运行许可 / 互锁{node.permissions?.length ? " · " + node.permissions.length : ""}</summary>
        {node.permissions?.map((rule, i) => <div key={rule.id} className="af-inspector-rule">
          <strong>{formatFeedback(rule, station, catalog)}</strong>
          <label>检查时机<select aria-label={"检查时机 " + (i + 1)} value={rule.mode} onChange={(event) => editPermission(rule.id, { mode: event.target.value as Permission["mode"] })}>
            <option value="start">启动前检查</option><option value="continuous">运行中持续检查</option>
          </select></label>
          <label>启动条件未满足<select aria-label={"启动条件未满足 " + (i + 1)} value={rule.blocked} onChange={(event) => editPermission(rule.id, { blocked: event.target.value as Permission["blocked"] })}>
            <option value="wait">等待条件成立</option><option value="fault">走互锁失效出口</option>
          </select></label>
          <button className="k-btn k-btn--sm" type="button" onClick={() => change({ permissions: node.permissions?.filter((item) => item.id !== rule.id) })}>移除许可</button>
        </div>)}
        <label>许可反馈<select aria-label="许可反馈" value={permissionPort} onChange={(event) => setPermissionPort(event.target.value)}>
          <option value="">选择输入信号</option>{feedback.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select></label>
        <label>许可期望值<select aria-label="许可期望值" value={String(permissionValue)} onChange={(event) => setPermissionValue(event.target.value === "true")}>
          <option value="true">有效</option><option value="false">无效</option>
        </select></label>
        <button className="k-btn k-btn--sm" type="button" disabled={!selectedFeedback} onClick={() => {
          if (!selectedFeedback) return;
          const { device_id, port } = selectedFeedback;
          change({ permissions: [...(node.permissions ?? []), { id: entityId("permission"), device_id, port, value: permissionValue, mode: "start", blocked: "wait" }] });
          setPermissionPort("");
        }}>添加运行许可</button>
      </details>}
      {node.kind === "fork" && <p className="af-context">拉出两个或更多分支，再把完成出口接到同一个「全部汇合」。</p>}
      {node.kind === "join" && <p className="af-context">所属并行组的各分支完成后继续。</p>}
      <div className="af-inspector-actions">
        {!DATA_ONLY.has(node.kind) && <button className="k-btn k-btn--sm" disabled={flow.start === node.id} type="button" onClick={() => update({ ...flow, start: node.id })}>设为起点</button>}
        <button className="k-btn k-btn--sm" type="button" onClick={() => removeNode(node.id)}>删除节点</button>
      </div>
    </fieldset>}
  </aside>;
}
