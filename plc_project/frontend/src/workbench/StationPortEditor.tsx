import React from "react";
import { entityId, type PortDefinition, type PortType } from "./stationDesign";
import { PORT_DEFAULTS } from "./stationPorts";

const TYPES = Object.keys(PORT_DEFAULTS) as PortType[];

export function StationPortEditor({ ports, update, fixedDirection, connected }: {
  ports: PortDefinition[]; update: (ports: PortDefinition[]) => void;
  fixedDirection?: "input"; connected: (id: string) => boolean;
}) {
  function change(id: string, fields: Partial<PortDefinition>) {
    update(ports.map((item) => item.id === id ? { ...item, ...fields } : item));
  }
  return <div className="af-stack">
    {ports.map((item, index) => {
      const locked = connected(item.id);
      const value = item.default ?? PORT_DEFAULTS[item.type];
      const options = item.type === "MODE" ? [[0, "自动"], [1, "手动"]]
        : item.type === "REQUEST" ? [[0, "空闲"], [1, "伸出"], [2, "缩回"]] : [];
      return <div className="af-inspector-rule" key={item.id}>
        <label>端口名称<input aria-label={"端口名称 " + (index + 1)} value={item.name} maxLength={60}
          onChange={(event) => change(item.id, { name: event.target.value })} /></label>
        <small className="wb-mono">{item.id}</small>
        {!fixedDirection && <label>方向<select aria-label={"端口方向 " + (index + 1)} disabled={locked} value={item.direction}
          onChange={(event) => change(item.id, { direction: event.target.value as PortDefinition["direction"] })}>
          <option value="input">工位输入</option><option value="output">工位输出</option>
        </select></label>}
        <label>信号类型<select aria-label={"端口类型 " + (index + 1)} disabled={locked} value={item.type} onChange={(event) => {
          const type = event.target.value as PortType;
          change(item.id, { type, default: item.direction === "input" ? PORT_DEFAULTS[type] : null });
        }}>{TYPES.map((type) => <option key={type}>{type}</option>)}</select></label>
        {item.direction === "output" && <label><input type="checkbox" checked={item.default != null}
          onChange={(event) => change(item.id, { default: event.target.checked ? PORT_DEFAULTS[item.type] : null })} />设置输出默认值</label>}
        {(item.direction === "input" || item.default != null) && <label>{item.type === "TIME" ? "默认值（ms）" : "默认值"}
          {item.type === "BOOL" ? <select value={String(value)} onChange={(event) => change(item.id, { default: event.target.value === "true" })}>
            <option value="false">FALSE</option><option value="true">TRUE</option>
          </select> : options.length ? <select value={Number(value)} onChange={(event) => change(item.id, { default: Number(event.target.value) })}>
            {options.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select> : <input type={item.type === "STRING" ? "text" : "number"} value={String(value)}
            maxLength={40} min={item.type === "TIME" ? 0 : -2147483648} max={item.type === "TIME" ? 86400000 : 2147483647}
            onChange={(event) => change(item.id, { default: item.type === "STRING" ? event.target.value : Number(event.target.value) })} />}
        </label>}
        <button className="k-btn k-btn--sm" type="button" disabled={locked}
          title={locked ? "先解除关联信号线" : undefined}
          onClick={() => update(ports.filter((entry) => entry.id !== item.id))}>删除端口</button>
      </div>;
    })}
    <button type="button" className="k-btn k-btn--sm" disabled={ports.length >= 24} onClick={() =>
      update([...ports, { id: entityId("io"), name: "信号 " + (ports.length + 1), type: "BOOL", direction: "input", default: false }])
    }>添加端口</button>
  </div>;
}
