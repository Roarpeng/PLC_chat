import React, { useState } from "react";
import {
  actionNode, entityId, insertBefore, newNode, NODE_LABEL, outcomes, primarySteps,
  type CatalogAction, type Device, type DeviceProfile, type Feedback, type Flow, type Node, type Station,
} from "./stationDesign";

function updateStep(flow: Flow, node: Node): Flow {
  const nodes = flow.nodes.map((item) => item.id === node.id ? node : item);
  const needsTimeout = outcomes(node).includes("timeout");
  const previousTimeout = flow.edges.find((edge) => edge.from_id === node.id && edge.outcome === "timeout")?.to_id;
  const edges = flow.edges.filter((edge) => edge.from_id !== node.id || edge.outcome !== "timeout" || needsTimeout);
  if (needsTimeout && !edges.some((edge) => edge.from_id === node.id && edge.outcome === "timeout")) {
    let fault = nodes.find((item) => item.kind === "fault" && item.name === "动作超时");
    if (!fault) {
      fault = { ...newNode("fault"), name: "动作超时" };
      nodes.push(fault);
    }
    edges.push({ id: entityId("edge"), from_id: node.id, to_id: fault.id, outcome: "timeout" });
  }
  return { ...flow, nodes: nodes.filter((item) => item.id !== previousTimeout || item.kind !== "fault" || item.name !== "动作超时" ||
    item.id === node.id || item.id === flow.start || edges.some((edge) => edge.to_id === item.id)), edges };
}

function reorder(flow: Flow, steps: Node[], index: number, offset: number): Flow {
  const order = [...steps];
  [order[index], order[index + offset]] = [order[index + offset], order[index]];
  const next = new Map(order.slice(0, -1).map((item, i) => [item.id, order[i + 1].id]));
  return { ...flow, start: order[0].id, edges: flow.edges.map((edge) =>
    edge.outcome === "next" && next.has(edge.from_id) ? { ...edge, to_id: next.get(edge.from_id)! } : edge) };
}

function removeFromFlow(flow: Flow, id: string): Flow {
  const next = flow.edges.find((item) => item.from_id === id && item.outcome === "next")?.to_id;
  const previousTimeout = flow.edges.find((item) => item.from_id === id && item.outcome === "timeout")?.to_id;
  const edges = flow.edges.filter((edge) => edge.from_id !== id && (edge.to_id !== id || next))
    .map((edge) => edge.to_id === id && next ? { ...edge, to_id: next } : edge);
  const nodes = flow.nodes.filter((item) => item.id !== id &&
    (item.id !== previousTimeout || item.kind !== "fault" || item.name !== "动作超时" || item.id === flow.start ||
      edges.some((edge) => edge.to_id === item.id)));
  return { start: flow.start === id ? next ?? null : flow.start, nodes, edges };
}

export function formatFeedback(condition: Feedback, station: Station, catalog: DeviceProfile[]): string {
  const device = station.devices.find((item) => item.id === condition.device_id);
  const profile = device && catalog.find((item) => item.id === device.driver);
  return (device?.name ?? condition.device_id) + " · " + (profile?.port_labels[condition.port] ?? condition.port) +
    (condition.value ? "" : " = FALSE");
}

export function stepDetails(node: Node, station: Station, catalog: DeviceProfile[]): string {
  if (node.pending_feedback) return "反馈待关联";
  if (node.completion?.length) return node.completion.map((item) => formatFeedback(item, station, catalog)).join(" 且 ");
  if (node.device_id && node.port && node.kind === "wait") {
    return formatFeedback({ device_id: node.device_id, port: node.port, value: node.value }, station, catalog);
  }
  if (node.kind === "wait" && node.duration_ms) return "保持 " + node.duration_ms + " ms";
  return "";
}

export function StationSteps({ station, catalog, selected, select, update, openGraph }: {
  station: Station; catalog: DeviceProfile[]; selected: string; select: (id: string) => void;
  update: (flow: Flow) => void; openGraph: () => void;
}) {
  const [deviceId, setDeviceId] = useState("");
  const [presetId, setPresetId] = useState("");
  const [delay, setDelay] = useState(300);
  const [error, setError] = useState("");
  const [feedbackChoice, setFeedbackChoice] = useState("");
  const [feedbackValue, setFeedbackValue] = useState(true);
  const flow = station.flow;
  const ordered = primarySteps(flow);
  const sequence = ordered.filter((item) => item.kind !== "fault");
  const node = flow.nodes.find((item) => item.id === selected);
  const devices = new Map(station.devices.map((item) => [item.id, item]));
  const profiles = new Map(catalog.map((item) => [item.id, item]));
  const operable = station.devices.filter((device) => profiles.get(device.driver)?.actions.length);
  const source = devices.get(deviceId);
  const presets = source ? profiles.get(source.driver)?.actions ?? [] : [];
  const preset = presets.find((item) => item.id === presetId);
  const feedback = station.devices.flatMap((item) => Object.entries(profiles.get(item.driver)?.ports ?? {})
    .filter(([, direction]) => direction === "input")
    .map(([port]) => ({
      device_id: item.id, port, value: feedbackValue,
      key: item.id + "/" + port, name: item.name + " · " + (profiles.get(item.driver)?.port_labels[port] ?? port),
    })));
  const chosen = feedback.find((item) => item.key === feedbackChoice);
  const canOrder = sequence.length > 1 && sequence[sequence.length - 1]?.kind === "done" &&
    sequence.slice(0, -1).every((item, i) =>
      (item.kind === "action" || item.kind === "wait") && flow.edges.some((edge) =>
        edge.from_id === item.id && edge.to_id === sequence[i + 1].id && edge.outcome === "next"));

  function modify(fields: Partial<Node>) {
    if (node) update(updateStep(flow, { ...node, ...fields }));
  }

  function insert(item: Node, anchor?: string) {
    setError("");
    try {
      update(insertBefore(flow, item, anchor));
      select(item.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法插入步骤。");
    }
  }

  function addAction(device: Device, action: CatalogAction, parallel: boolean) {
    const added = actionNode(device, action);
    if (!parallel || !node) { insert(added, node && !["done", "fault"].includes(node.kind) ? node.id : undefined); return; }
    modify({
      name: (node.name + " + " + added.name).slice(0, 100),
      actions: [...node.actions ?? [], ...added.actions ?? []],
      completion: [...node.completion ?? [], ...added.completion ?? []].filter((value, index, list) =>
        list.findIndex((item) => item.device_id === value.device_id && item.port === value.port && item.value === value.value) === index),
      timeout_ms: Math.max(node.timeout_ms, added.timeout_ms),
    });
  }

  function addFeedback() {
    if (!node || !chosen) return;
    const { device_id, port, value } = chosen;
    if (node.kind === "wait") {
      modify({ device_id, port, value, pending_feedback: false, timeout_ms: node.timeout_ms || 2000, duration_ms: 0 });
    } else {
      modify({
        completion: [...(node.completion ?? []).filter((item) => item.device_id !== device_id || item.port !== port), { device_id, port, value }],
        timeout_ms: node.timeout_ms || 2000,
      });
    }
    setFeedbackChoice("");
  }

  return <section className="af-pane af-step-editor">
    <div className="af-section-head">
      <h2 className="k-title">动作步骤</h2>
      <button type="button" className="k-btn k-btn--sm" onClick={openGraph}>查看逻辑图</button>
    </div>
    <div className="af-action-toolbar">
      <label>设备<select aria-label="步骤设备" value={deviceId} onChange={(event) => { setDeviceId(event.target.value); setPresetId(""); }}>
        <option value="">选择设备</option>
        {operable.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label>动作<select aria-label="步骤动作" value={presetId} onChange={(event) => setPresetId(event.target.value)}>
        <option value="">选择动作</option>
        {presets.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      <button type="button" className="k-btn k-btn--sm" disabled={!source || !preset} onClick={() => source && preset && addAction(source, preset, false)}>
        {node && node.kind !== "done" && node.kind !== "fault" ? "在所选步骤前插入" : "添加动作"}
      </button>
      <button type="button" className="k-btn k-btn--sm" disabled={!source || !preset || !node?.actions?.length || node.actions.some((item) => item.device_id === source?.id)}
        onClick={() => source && preset && addAction(source, preset, true)}>并入所选步骤</button>
    </div>
    <div className="af-action-toolbar af-step-delay">
      <label>定时等待（ms）<input type="number" min="1" max="86400000" value={delay} onChange={(event) => setDelay(Number(event.target.value))} /></label>
      <button type="button" className="k-btn k-btn--sm" disabled={delay <= 0 || delay > 86400000} onClick={() =>
        insert({ ...newNode("wait"), name: "等待 " + delay + " ms", duration_ms: delay },
          node?.kind !== "fault" ? node?.id : undefined)}>插入定时等待</button>
    </div>
    {error && <p className="wb-inline-error" role="alert">{error}</p>}
    {!ordered.length && <p className="k-hatch">描述工艺生成草稿，或从上方选择设备动作添加步骤。</p>}
    {ordered.length > 0 && <div className="af-steps-layout">
      <ol className="af-step-list">
        {ordered.map((item, index) => {
          const notes = stepDetails(item, station, catalog);
          const time = outcomes(item).includes("timeout") && item.timeout_ms ? "超时 " + item.timeout_ms + " ms" : "";
          return <li key={item.id}>
            <button type="button" className="af-step-row" aria-pressed={selected === item.id} onClick={() => { select(item.id); setFeedbackChoice(""); }}>
              <span className="wb-mono af-step-number">{String(index + 1).padStart(2, "0")}</span>
              <span><strong>{item.name}</strong>{notes && <small className={item.pending_feedback ? "af-pending" : ""}>{notes}</small>}</span>
              <span className="af-step-kind">{time || (item.actions && item.actions.length > 1 ? "并行" : NODE_LABEL[item.kind])}</span>
            </button>
          </li>;
        })}
      </ol>
      <aside className="af-step-properties">
        <h3>步骤设置</h3>
        {node && <div className="af-stack">
          <label>步骤名称<input value={node.name} maxLength={100} onChange={(event) => modify({ name: event.target.value })} /></label>
          {(node.actions ?? []).map((reference) => {
            const device = devices.get(reference.device_id);
            const action = device && profiles.get(device.driver)?.actions.find((entry) => entry.id === reference.action_id);
            return <p key={reference.device_id}>{device?.name} · {action?.label}
              {(node.actions?.length ?? 0) > 1 && <button type="button" className="k-btn k-btn--sm" onClick={() => modify({
                actions: node.actions?.filter((item) => item.device_id !== reference.device_id),
                completion: node.completion?.filter((item) => item.device_id !== reference.device_id),
              })}>移除此并行动作</button>}
            </p>;
          })}
          {node.kind === "wait" && !node.device_id && !node.pending_feedback && <label>保持时间（ms）
            <input type="number" min="1" max="86400000" value={node.duration_ms} onChange={(event) => {
              const duration_ms = Number(event.target.value);
              const name = /^等待 \d+ ms$/.test(node.name) ? "等待 " + duration_ms + " ms" : node.name;
              modify({ duration_ms, name });
            }} />
          </label>}
          {outcomes(node).includes("timeout") && <label>完成超时（ms）
            <input type="number" min="1" max="86400000" value={node.timeout_ms}
              onChange={(event) => modify({ timeout_ms: Number(event.target.value) })} />
          </label>}
          {Boolean(node.actions?.length || node.kind === "wait") && <>
            <div className="af-stack">
              {(node.completion ?? []).map((item) => <div className="af-edge" key={item.device_id + "/" + item.port}>
                <span>{formatFeedback(item, station, catalog)}</span>
                <button type="button" className="k-btn k-btn--sm"
                  onClick={() => modify({ completion: node.completion?.filter((condition) => condition !== item) })}>移除条件</button>
              </div>)}
            </div>
            <label>完成反馈<select aria-label="完成反馈" value={feedbackChoice} onChange={(event) => setFeedbackChoice(event.target.value)}>
              <option value="">选择工位内的设备信号</option>
              {feedback.map((item) => <option value={item.key} key={item.key}>{item.name}</option>)}
            </select></label>
            <label>期望值<select aria-label="期望值" value={String(feedbackValue)} onChange={(event) => setFeedbackValue(event.target.value === "true")}>
              <option value="true">有效</option><option value="false">无效</option>
            </select></label>
            <button type="button" className="k-btn k-btn--sm" disabled={!chosen} onClick={addFeedback}>
              {node.kind === "wait" ? "关联反馈" : "加入完成条件"}
            </button>
          </>}
          {outcomes(node).includes("timeout") && <label>超时去向<select aria-label="超时去向"
            value={flow.edges.find((edge) => edge.from_id === node.id && edge.outcome === "timeout")?.to_id ?? ""}
            onChange={(event) => update({ ...flow, edges: [
              ...flow.edges.filter((edge) => edge.from_id !== node.id || edge.outcome !== "timeout"),
              { id: entityId("edge"), from_id: node.id, to_id: event.target.value, outcome: "timeout" },
            ] })}>
            <option value="" disabled>选择目标</option>
            {flow.nodes.filter((item) => item.id !== node.id).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select></label>}
          <div className="af-inline">
            <button type="button" className="k-btn k-btn--sm" disabled={!canOrder || sequence.indexOf(node) < 1 || node.kind === "done"}
              onClick={() => update(reorder(flow, sequence, sequence.indexOf(node), -1))}>上移</button>
            <button type="button" className="k-btn k-btn--sm" disabled={!canOrder || sequence.indexOf(node) < 0 || sequence.indexOf(node) >= sequence.length - 2}
              onClick={() => update(reorder(flow, sequence, sequence.indexOf(node), 1))}>下移</button>
            <button type="button" className="k-btn k-btn--sm" disabled={!flow.edges.some((edge) => edge.from_id === node.id && edge.outcome === "next")}
              onClick={() => { update(removeFromFlow(flow, node.id)); select(""); }}>移除步骤</button>
          </div>
        </div>}
      </aside>
    </div>}
  </section>;
}
