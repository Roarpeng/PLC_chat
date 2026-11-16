import React from "react";
import { NODE_LABEL, OUTCOME_LABEL, outcomes, primarySteps, type Flow } from "./stationDesign";

export function StationTimeline({ flow, selected, select, update }: {
  flow: Flow; selected: string; select: (id: string) => void; update: (flow: Flow) => void;
}) {
  return <section className="af-pane">
    <h2 className="k-title">时序参数</h2>
    {!flow.nodes.length && <p className="k-hatch">请先在画布中编排节点。</p>}
    {primarySteps(flow).map((item) => {
      const signalWait = outcomes(item).includes("timeout");
      return <div className="af-record" key={item.id}>
        <button className="k-btn k-btn--sm" onClick={() => select(item.id)} aria-pressed={item.id === selected}>{item.name}</button>
        <span>{NODE_LABEL[item.kind]}</span>
        {Boolean(item.kind === "wait" || item.completion?.length) &&
          <label>{signalWait ? "超时（ms）" : "保持（ms）"}
            <input type="number" min="1" max="86400000" value={signalWait ? item.timeout_ms : item.duration_ms} onChange={(event) => {
              const time = Number(event.target.value);
              const name = !signalWait && /^等待 \d+ ms$/.test(item.name) ? "等待 " + time + " ms" : item.name;
              const key = signalWait ? "timeout_ms" : "duration_ms";
              update({ ...flow, nodes: flow.nodes.map((node) => node.id === item.id ? { ...node, name, [key]: time } : node) });
            }} />
          </label>}
        <span>{flow.edges.filter((edge) => edge.from_id === item.id).map((edge) =>
          OUTCOME_LABEL[edge.outcome] + " → " + flow.nodes.find((next) => next.id === edge.to_id)?.name).join(" / ")}</span>
      </div>;
    })}
  </section>;
}
