import React from "react";
import { StationDeviceLibrary } from "./StationDeviceLibrary";
import {
  entityId, usesDevice, type CatalogAction, type Device, type DeviceProfile, type Hardware,
  type Interlock, type ModuleKind, type Station,
} from "./stationDesign";

export function StationHardware({ hardware, update }: { hardware: Hardware; update: (value: Hardware) => void }) {
  return (
    <section className="af-pane">
      <h2 className="k-title">硬件组态</h2>
      <div className="af-fields">
        <label>PLC CPU<input value={hardware.cpu} placeholder="输入型号或 V19 目录标识" onChange={(e) => update({ ...hardware, cpu: e.target.value })} /></label>
        <label>网络 / 通信<input value={hardware.network} placeholder="例如 PROFINET" onChange={(e) => update({ ...hardware, network: e.target.value })} /></label>
      </div>
      <div className="af-section-head">
        <h3>I/O 模块</h3>
        <button className="k-btn k-btn--sm" onClick={() => {
          const slot = hardware.modules.reduce((max, item) => Math.max(max, item.slot), 0) + 1;
          update({ ...hardware, modules: [...hardware.modules, { id: entityId("io"), name: "I/O 模块", slot, kind: "DI_DO" }] });
        }}>添加模块</button>
      </div>
      {!hardware.modules.length && <p className="k-hatch">添加模块后可以登记信号。</p>}
      {hardware.modules.map((item) => (
        <div className="af-record" id={item.id} key={item.id}>
          <label>模块名称<input value={item.name} onChange={(e) => update({ ...hardware, modules: hardware.modules.map((m) => m.id === item.id ? { ...m, name: e.target.value } : m) })} /></label>
          <label>插槽<input type="number" min="0" max="255" value={item.slot} onChange={(e) => update({ ...hardware, modules: hardware.modules.map((m) => m.id === item.id ? { ...m, slot: Number(e.target.value) } : m) })} /></label>
          <label>类型<select value={item.kind} onChange={(e) => update({ ...hardware, modules: hardware.modules.map((m) => m.id === item.id ? { ...m, kind: e.target.value as ModuleKind } : m) })}>
            <option value="DI_DO">DI / DO</option><option value="DI">DI</option><option value="DO">DO</option>
          </select></label>
          <button className="k-btn k-btn--sm" disabled={hardware.signals.some((s) => s.module_id === item.id)} onClick={() => update({ ...hardware, modules: hardware.modules.filter((m) => m.id !== item.id) })}>移除模块</button>
        </div>
      ))}
      <div className="af-section-head">
        <h3>信号资源</h3>
        <button className="k-btn k-btn--sm" disabled={!hardware.modules.length} onClick={() => {
          const module = hardware.modules[0];
          update({ ...hardware, signals: [...hardware.signals, {
            id: entityId("sig"), name: "数字信号", module_id: module.id,
            direction: module.kind === "DO" ? "output" : "input", address: "",
          }] });
        }}>添加信号</button>
      </div>
      {hardware.signals.map((item) => {
        const change = (fields: Partial<typeof item>) => update({
          ...hardware, signals: hardware.signals.map((signal) => signal.id === item.id ? { ...signal, ...fields } : signal),
        });
        return (
          <div className="af-record" id={item.id} key={item.id}>
            <label>信号名称<input value={item.name} onChange={(e) => change({ name: e.target.value })} /></label>
            <label>模块<select value={item.module_id} onChange={(e) => change({ module_id: e.target.value })}>
              {hardware.modules.map((module) => <option value={module.id} key={module.id}>{module.name} · {module.slot}</option>)}
            </select></label>
            <label>方向<select value={item.direction} onChange={(e) => change({ direction: e.target.value as typeof item.direction })}>
              <option value="input">输入</option><option value="output">输出</option>
            </select></label>
            <label>布尔地址<input className="wb-mono" value={item.address} onChange={(e) => change({ address: e.target.value.trim().toUpperCase() })} /></label>
            <button className="k-btn k-btn--sm" onClick={() => update({ ...hardware, signals: hardware.signals.filter((signal) => signal.id !== item.id) })}>移除信号</button>
          </div>
        );
      })}
    </section>
  );
}

export function StationDevices({
  station, hardware, catalog, update, onAction, onDescribe,
}: {
  station: Station; hardware: Hardware; catalog: DeviceProfile[]; update: (item: Station) => void;
  onAction: (device: Device, action: CatalogAction) => void; onDescribe: () => void;
}) {
  const profiles = new Map(catalog.map((item) => [item.id, item]));
  const change = (device: Device) => update({
    ...station, devices: station.devices.map((item) => item.id === device.id ? device : item),
  });
  const interlocks = station.interlocks ?? [];
  const changeInterlock = (id: string, fields: Partial<Interlock>) =>
    update({ ...station, interlocks: interlocks.map((item) => item.id === id ? { ...item, ...fields } : item) });
  return (
    <section className="af-pane">
      <div className="af-section-head">
        <h2 className="k-title">工位设备 <small className="wb-mono">{station.devices.length}</small></h2>
        <button type="button" className="k-btn" onClick={onDescribe} disabled={!station.devices.length}>描述工位流程</button>
      </div>
      {station.devices.map((item) => {
        const profile = profiles.get(item.driver);
        const ports = Object.entries(profile?.ports ?? {});
        const bound = ports.filter(([key]) => item.bindings[key]).length;
        const inUse = station.flow.nodes.some((node) => usesDevice(node, item.id)) ||
          interlocks.some((condition) => condition.device_id === item.id);
        return <article className="af-device af-device-card" id={item.id} key={item.id}>
          <div className="af-section-head">
            <div>
              <h3>{item.name}</h3>
              <span>{profile?.label ?? item.driver}{profile?.interface ? " · " + profile.interface : ""}</span>
            </div>
            <span className={profile?.supported && bound === ports.length ? "af-ready" : "af-pending"}>
              {profile?.supported ? `I/O ${bound}/${ports.length}` : "待配套驱动"}
            </span>
          </div>
          {Boolean(profile?.actions.length) && <div className="af-inline af-device-actions">
            {profile?.actions.map((preset) =>
              <button className="k-btn k-btn--sm" type="button" key={preset.id}
                aria-label={item.name + " · " + preset.label + " 加入步骤"} onClick={() => onAction(item, preset)}>{preset.label} ＋</button>)}
          </div>}
          {!profile?.actions.length && ports.some(([, direction]) => direction === "input") && <p className="af-context">
            可用反馈 · {ports.filter(([, direction]) => direction === "input").map(([port]) => profile?.port_labels[port] ?? port).join(" · ")}
          </p>}
          <details className="af-device-bindings">
            <summary>I/O 绑定与参数</summary>
            <div className="af-fields">
              <label>设备名称<input value={item.name} maxLength={100} onChange={(event) => change({ ...item, name: event.target.value })} /></label>
              <label>默认动作超时（ms）<input type="number" min="0" max="86400000" value={item.timeout_ms}
                onChange={(event) => change({ ...item, timeout_ms: Number(event.target.value) })} /></label>
            </div>
            <div className="af-fields">
              {ports.map(([port, direction]) => (
                <label key={port}>{profile?.port_labels[port] ?? port}
                  <select aria-label={port} value={item.bindings[port] ?? ""} onChange={(event) => {
                    const bindings = { ...item.bindings };
                    if (event.target.value) bindings[port] = event.target.value;
                    else delete bindings[port];
                    change({ ...item, bindings });
                  }}>
                    <option value="">未绑定</option>
                    {hardware.signals.filter((signal) => signal.direction === direction).map((signal) =>
                      <option value={signal.id} key={signal.id}>{signal.name}{signal.address ? " · " + signal.address : ""}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <button className="k-btn k-btn--sm" disabled={inUse} type="button"
              title={inUse ? "此设备仍被步骤或联锁引用" : undefined}
              onClick={() => update({ ...station, devices: station.devices.filter((device) => device.id !== item.id) })}>移除设备</button>
          </details>
        </article>;
      })}
      <StationDeviceLibrary catalog={catalog} onAdd={(entry) => {
        const item = { id: entityId("dev"), name: entry.label, driver: entry.id, bindings: {}, timeout_ms: 0 };
        update({ ...station, devices: [...station.devices, item] });
      }} />
      {station.devices.length > 0 && <details className="af-device-bindings">
        <summary>工位联锁{interlocks.length ? " · " + interlocks.length : ""}</summary>
        <button className="k-btn k-btn--sm" type="button" onClick={() => update({ ...station, interlocks: [
          ...interlocks, { id: entityId("guard"), name: "运行许可", device_id: null, port: null, value: true },
        ] })}>添加联锁</button>
        {interlocks.map((item) => {
          const device = station.devices.find((d) => d.id === item.device_id);
          const profile = device && profiles.get(device.driver);
          return <div className="af-record" id={item.id} key={item.id}>
            <label>联锁名称<input value={item.name} onChange={(event) => changeInterlock(item.id, { name: event.target.value })} /></label>
            <label>反馈设备<select value={item.device_id ?? ""} onChange={(event) => changeInterlock(item.id, { device_id: event.target.value || null, port: null })}>
              <option value="">选择设备</option>{station.devices.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}
            </select></label>
            <label>反馈端口<select value={item.port ?? ""} onChange={(event) => changeInterlock(item.id, { port: event.target.value || null })}>
              <option value="">选择端口</option>
              {Object.entries(profile?.ports ?? {}).filter(([, value]) => value === "input").map(([port]) =>
                <option value={port} key={port}>{profile?.port_labels[port] ?? port}</option>)}
            </select></label>
            <label>许可值<select value={String(item.value)} onChange={(event) => changeInterlock(item.id, { value: event.target.value === "true" })}>
              <option value="true">TRUE</option><option value="false">FALSE</option>
            </select></label>
            <button className="k-btn k-btn--sm" type="button" onClick={() => update({ ...station, interlocks: interlocks.filter((entry) => entry.id !== item.id) })}>移除联锁</button>
          </div>;
        })}
      </details>}
    </section>
  );
}
