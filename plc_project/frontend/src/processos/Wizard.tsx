import { useEffect, useState } from "react";
import { processosApi } from "./api";
import type { CpuEntry, DeviceCatalog, FieldDevice, HardwareConfig, IoModule } from "./types";
import { Icon } from "./views";

const STEPS = ["CPU 与机架", "IO 模块与扩展", "现场设备", "网络", "预览与建立"];
const uid = (p: string) => p + Math.random().toString(36).slice(2, 7).toUpperCase();

function PNum({ value, onChange, unit }: { value: number; onChange: (v: number) => void; unit: string }) {
  return (
    <div className="numinput">
      <button className="stepbtn" onClick={() => onChange(value - 1)}>−</button>
      <input value={value} inputMode="numeric" onChange={e => onChange(Number(e.target.value) || 0)} />
      <button className="stepbtn" onClick={() => onChange(value + 1)}>+</button>
    </div>
  );
}

export function Wizard({ onCancel, onDone }: { onCancel: () => void; onDone: (name: string, contractId: string) => void }) {
  const [cat, setCat] = useState<DeviceCatalog | null>(null);
  const [step, setStep] = useState(0);
  const [projectName, setProjectName] = useState("新建装配工站");
  const [cpu, setCpu] = useState<CpuEntry | null>(null);
  const [deviceName, setDeviceName] = useState("PLC_1");
  const [ioModules, setIoModules] = useState<(IoModule & { slot: number })[]>([]);
  const [expansion, setExpansion] = useState<{ name: string; modules: IoModule[] }[]>([]);
  const [devices, setDevices] = useState<FieldDevice[]>([]);
  const [network, setNetwork] = useState({ ip: "192.168.0.1", subnet: "255.255.255.0", device_name: "plc_1" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { processosApi.deviceCatalog().then(c => { setCat(c); setCpu(c.cpus[0]); }).catch(() => setErr("无法加载设备目录")); }, []);

  const addIo = (m: IoModule) => setIoModules(prev => [...prev, { ...m, slot: prev.length + 2 }]);
  const delIo = (slot: number) => setIoModules(prev => prev.filter(x => x.slot !== slot).map((x, i) => ({ ...x, slot: i + 2 })));
  const addDevice = (type: string) => {
    if (!cat) return;
    const spec = cat.device_types[type];
    const params: Record<string, number> = {};
    spec.params.forEach(p => { params[p.key] = p.default; });
    setDevices(prev => [...prev, { type, name: spec.label + " " + (prev.length + 1), id: uid("CM_"), params }]);
  };
  const delDevice = (id: string) => setDevices(prev => prev.filter(d => d.id !== id));
  const setDev = (id: string, patch: Partial<FieldDevice>) => setDevices(prev => prev.map(d => d.id === id ? { ...d, ...patch } : d));

  const ioTotals = ioModules.reduce((a, m) => ({ ...a, [m.type]: (a[m.type] || 0) + m.points }), {} as Record<string, number>);

  const create = async () => {
    setBusy(true); setErr("");
    const config: HardwareConfig = {
      name: projectName, cpu, device_name: deviceName, io_modules: ioModules,
      expansion, devices: devices.length ? devices : [{ type: "cylinder", name: "夹紧气缸", id: uid("CM_"), params: { timeout_ms: 3000, hold_ms: 2000 } }],
      network,
    };
    try {
      const r = await processosApi.fromHardware(config);
      onDone(projectName, r.project_id);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };

  if (!cat) return <div className="flow"><div className="flow-body"><div className="hint">{err || "加载设备目录…"}</div></div></div>;

  return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onCancel}><Icon name="back" /> 返回</button>
        <h2>新建项目 · 硬件组态</h2>
        <div className="sp" />
        <div className="steps-rail">
          {STEPS.map((s, i) => <div key={s} className={`sr ${i === step ? "on" : i < step ? "done" : ""}`}><span className="n">{i < step ? <Icon name="check" size={12} /> : i + 1}</span>{s}</div>)}
        </div>
      </div>

      <div className="flow-body">
        {step === 0 && (
          <div className="panel">
            <div className="panel-h">选择控制器 CPU<span className="sp" /><span className="hint">机架随 CPU 自动生成，CPU 占 1 号槽</span></div>
            <div className="panel-b">
              <div className="hw-grid">
                <div className="rack">
                  <div className="rack-rail">
                    <div className="slot"><span className="sl-no">0</span><div className="sl-type">PS</div><div className="sl-label">电源（可选）</div></div>
                    <div className="slot cpu"><span className="sl-no">1</span><div className="sl-type">{cpu?.series}</div><div className="sl-label">{cpu?.label}<br />{cpu?.order_no}</div></div>
                    <div className="slot empty">2<br />IO</div>
                  </div>
                  <div className="rack-cap">设备名称：{deviceName} · 固件 {cpu?.firmware}</div>
                </div>
                <div className="hw-tools">
                  <div className="field"><label>CPU 型号（订货号）</label>
                    <select value={cpu?.order_no} onChange={e => setCpu(cat.cpus.find(c => c.order_no === e.target.value) || null)}>
                      {cat.cpus.map(c => <option key={c.order_no} value={c.order_no}>{c.series} · {c.label} · {c.order_no} · {c.firmware}</option>)}
                    </select></div>
                  <div className="field"><label>设备名称</label><input value={deviceName} onChange={e => setDeviceName(e.target.value)} /></div>
                  <div className="field"><label>项目名称</label><input value={projectName} onChange={e => setProjectName(e.target.value)} /></div>
                </div>
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="panel">
            <div className="panel-h">IO 模块与扩展<span className="sp" /><span className="hint">信号模块插 CPU 右侧槽位；分布式 IO 经 PROFINET 扩展</span></div>
            <div className="panel-b">
              <div className="hw-grid">
                <div className="rack">
                  <div className="rack-rail">
                    <div className="slot cpu"><span className="sl-no">1</span><div className="sl-type">{cpu?.series}</div><div className="sl-label">{cpu?.label}</div></div>
                    {ioModules.map(m => (
                      <div className="slot" key={m.slot}><span className="sl-no">{m.slot}</span><button className="sl-del" onClick={() => delIo(m.slot)}><Icon name="cross" size={11} /></button><div className="sl-type">{m.type}</div><div className="sl-label">{m.label}</div></div>
                    ))}
                    <div className="slot empty">{ioModules.length + 2}<br />空闲</div>
                  </div>
                  <div className="io-counts">
                    {["DI", "DQ", "AI", "AQ"].map(t => <span className="cc" key={t}>{t} <b>{ioTotals[t] || 0}</b></span>)}
                  </div>
                  {expansion.map((ex, i) => (
                    <div className="expansion" key={i}>
                      <div className="ex-head"><Icon name="topo" /><input value={ex.name} onChange={e => setExpansion(prev => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} /><button className="sl-del" onClick={() => setExpansion(prev => prev.filter((_, j) => j !== i))}><Icon name="cross" size={12} /></button></div>
                      <div className="io-counts">{ex.modules.map((m, j) => <span className="cc" key={j}>{m.label}</span>)}</div>
                    </div>
                  ))}
                </div>
                <div className="hw-tools">
                  <div className="hint">添加信号模块</div>
                  {cat.io_modules.map(m => <button className="btn" key={m.order_no} onClick={() => addIo(m)}><Icon name="plus" /> {m.label}</button>)}
                  <button className="btn ghost" onClick={() => setExpansion(prev => [...prev, { name: "ET200SP_" + (prev.length + 1), modules: [cat.io_modules[0], cat.io_modules[1]] }])}><Icon name="plus" /> 添加分布式 IO 站</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="panel">
            <div className="panel-h">现场设备（CM 类型目录）<span className="sp" /><span className="hint">选类型 → 设参数 → 绑 IO → 生成类型化 CM</span></div>
            <div className="panel-b">
              <div className="devcat">
                {Object.entries(cat.device_types).map(([k, spec]) => (
                  <button key={k} onClick={() => addDevice(k)}>
                    <div className="dc-label">{spec.label}</div>
                    <div className="dc-io">DI {spec.io.DI} · DQ {spec.io.DQ} · AI {spec.io.AI}{spec.bus ? " · " + spec.bus : ""}</div>
                  </button>
                ))}
              </div>
              <div className="devlist">
                {devices.length === 0 && <div className="hint">尚未添加现场设备。从上方目录选择执行器/传感器类型；气缸只是其中一种。</div>}
                {devices.map(d => {
                  const spec = cat.device_types[d.type];
                  return (
                    <div className="devcard" key={d.id}>
                      <div className="dv-head">
                        <span className="dv-type">{spec.label}</span>
                        <input className="dv-name" value={d.name} onChange={e => setDev(d.id, { name: e.target.value })} />
                        <button className="dv-del" onClick={() => delDevice(d.id)}><Icon name="cross" /></button>
                      </div>
                      <div className="dv-ports">命令 <span className="mono">{spec.commands.join(", ") || "—"}</span> · 反馈 <span className="mono">{spec.feedback.join(", ")}</span> · IO <span className="mono">DI{spec.io.DI}/DQ{spec.io.DQ}/AI{spec.io.AI}</span></div>
                      <div className="devparams">
                        {spec.params.map(p => (
                          <div className="dp" key={p.key}><label>{p.label}{p.unit ? ` (${p.unit})` : ""}</label>
                            <PNum value={d.params[p.key] ?? p.default} unit={p.unit} onChange={v => setDev(d.id, { params: { ...d.params, [p.key]: v } })} /></div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="panel">
            <div className="panel-h">网络组态 · PROFINET<span className="sp" /><span className="hint">分配 IP 与设备名，IO 设备经此挂到 CPU</span></div>
            <div className="panel-b">
              <div className="net-grid">
                <div className="field"><label>IP 地址</label><input value={network.ip} onChange={e => setNetwork(n => ({ ...n, ip: e.target.value }))} /></div>
                <div className="field"><label>子网掩码</label><input value={network.subnet} onChange={e => setNetwork(n => ({ ...n, subnet: e.target.value }))} /></div>
                <div className="field"><label>PROFINET 设备名</label><input value={network.device_name} onChange={e => setNetwork(n => ({ ...n, device_name: e.target.value }))} /></div>
              </div>
              <div className="note" style={{ marginTop: 16 }}>拓扑：{cpu?.label}（{network.ip}）→ {expansion.length} 个分布式 IO 站 → {devices.length} 个现场设备。编译硬件后地址自动分配（%I/%Q）。</div>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="panel">
            <div className="panel-h">预览生成的 CM 与工艺<span className="sp" /><span className="hint">建立后可在对话中继续演进</span></div>
            <div className="panel-b">
              <div className="preview-cms">
                {(devices.length ? devices : [{ type: "cylinder", name: "夹紧气缸", id: "CM_01", params: {} } as FieldDevice]).map(d => {
                  const spec = cat.device_types[d.type];
                  return (
                    <div className="preview-cm" key={d.id}>
                      <span className="pc-tag">{spec.label}</span>
                      <div className="pc-body"><div className="pc-name">{d.name} <span className="mono" style={{ color: "var(--faint)", fontSize: 12 }}>{d.id}</span></div>
                        <div className="pc-meta">命令 {spec.commands.join(", ") || "—"} · 反馈 {spec.feedback.join(", ")} · 参数 {Object.entries(d.params).map(([k, v]) => `${k}=${v}`).join(", ") || "默认"}</div></div>
                    </div>
                  );
                })}
              </div>
              <div className="note warn" style={{ marginTop: 14 }}>每个 CM 按类型生成驱动序列与场景；含 1 项阻断问题（安全停机方式）待裁决；I/O 保持 unbound；G0 模板待真机验证。</div>
              {err && <div className="note" style={{ marginTop: 12, color: "var(--err)" }}>{err}</div>}
            </div>
          </div>
        )}

        <div className="flow-foot">
          {step > 0 && <button className="btn ghost" onClick={() => setStep(s => s - 1)}>上一步</button>}
          {step < 4 && <button className="btn primary" onClick={() => setStep(s => s + 1)} disabled={step === 2 && devices.length === 0}>下一步 <Icon name="arrow" /></button>}
          {step === 4 && <button className="btn stamp" onClick={create} disabled={busy}>{busy ? "建立中…" : "建立项目并进入对话"} <Icon name="arrow" /></button>}
        </div>
      </div>
    </div>
  );
}
