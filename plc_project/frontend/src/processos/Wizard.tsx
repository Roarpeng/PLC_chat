import { useEffect, useRef, useState } from "react";
import { processosApi } from "./api";
import { createProjectFromSpec, signalTable, validateSpec } from "./apiWizard";
import type { ProjectSpec } from "./apiWizard";
import type { CpuEntry, DeviceCatalog, FieldDevice, IoModule } from "./types";
import { Icon } from "./views";

/* §b 结构化步序编辑：硬件组态 → … → 现场设备 → 网络 → 步序编排 → 预览与建立。
   步序编排不允许自由连线（§3.1）：下一步只能从既有步骤中选择。 */
const STEPS = ["CPU 与机架", "IO 模块与扩展", "现场设备", "网络", "步序编排", "预览与建立"];
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

/* ---------- 步序编排模型（纯函数，供组件与测试共用） ---------- */

export interface WizStep {
  id: string; name: string;
  guardSignal: string; guardValue: boolean;   // guard 下拉：无 / 反馈信号 == 真|假
  commands: string[];                          // 动作多选（来自该操作资源的命令集）
  timeoutMs: number;                           // 默认 3000
  failureTarget: string;                       // 故障出口：无 / 既有步骤
  nextMode: "auto" | "id"; nextId: string;     // 下一步：自动=时序后继 / 指定既有步骤
}
export interface WizOp { em: string; name: string; resourceIds: string[]; steps: WizStep[] }

export function newWizStep(n: number): WizStep {
  return { id: uid("S_"), name: `步骤 ${n}`, guardSignal: "", guardValue: true, commands: [], timeoutMs: 3000, failureTarget: "", nextMode: "auto", nextId: "" };
}

export function wizAddStep(ops: WizOp[], opIdx: number): WizOp[] {
  return ops.map((o, j) => j === opIdx ? { ...o, steps: [...o.steps, newWizStep(o.steps.length + 1)] } : o);
}
export function wizDelStep(ops: WizOp[], opIdx: number, stepId: string): WizOp[] {
  return ops.map((o, j) => j === opIdx ? { ...o, steps: o.steps.filter(s => s.id !== stepId) } : o);
}
export function wizMoveStep(ops: WizOp[], opIdx: number, stepId: string, dir: -1 | 1): WizOp[] {
  return ops.map((o, j) => {
    if (j !== opIdx) return o;
    const i = o.steps.findIndex(s => s.id === stepId);
    const t = i + dir;
    if (i < 0 || t < 0 || t >= o.steps.length) return o;
    const steps = [...o.steps];
    [steps[i], steps[t]] = [steps[t], steps[i]];
    return { ...o, steps };
  });
}
export function wizPatchStep(ops: WizOp[], opIdx: number, stepId: string, patch: Partial<WizStep>): WizOp[] {
  return ops.map((o, j) => j === opIdx
    ? { ...o, steps: o.steps.map(s => s.id === stepId ? { ...s, ...patch } : s) } : o);
}

/** 下一步的「指定」候选：仅限同一操作的既有步骤（不含自身 —— 禁止自由连线/自环）。 */
export function targetChoices(steps: readonly (string | { id: string })[], selfId: string): string[] {
  return steps.map(s => (typeof s === "string" ? s : s.id)).filter(id => id !== selfId);
}
/** 「自动」下一步 = 时序后继；末步为空（序列结束）。 */
export function resolveNext(step: WizStep, idx: number, steps: WizStep[]): string {
  return step.nextMode === "auto" ? (steps[idx + 1]?.id ?? "") : step.nextId;
}
/** guard 候选信号：全部设备反馈的并集。 */
export function feedbackUnion(devices: FieldDevice[], cat: DeviceCatalog | null): string[] {
  const set = new Set<string>();
  for (const d of devices) for (const fb of cat?.device_types[d.type]?.feedback ?? []) set.add(fb);
  return [...set];
}
/** 动作候选命令：该操作关联资源的命令并集。 */
export function commandOptions(devices: FieldDevice[], cat: DeviceCatalog | null, resourceIds: string[]): string[] {
  const set = new Set<string>();
  for (const rid of resourceIds) {
    const dev = devices.find(d => d.id === rid);
    for (const c of cat?.device_types[dev?.type ?? ""]?.commands ?? []) set.add(c);
  }
  return [...set];
}
/** 步骤卡就地红字（与后端校验同规则的子集，针对单卡可见的问题）。 */
export function stepCardErrors(step: WizStep, steps: WizStep[], cmds: string[], fbs: string[]): string[] {
  const errs: string[] = [];
  const sids = steps.map(s => s.id);
  for (const c of step.commands) if (!cmds.includes(c)) errs.push(`命令 ${c} 不属于该操作的资源（资源可能已变更）`);
  if (step.timeoutMs <= 0) errs.push("超时必须大于 0 ms");
  if (step.nextMode === "id" && !sids.includes(step.nextId)) errs.push("下一步指向的步骤已删除");
  if (step.failureTarget && !sids.includes(step.failureTarget)) errs.push("故障出口指向的步骤已删除");
  if (step.guardSignal && !fbs.includes(step.guardSignal)) errs.push(`guard 信号 ${step.guardSignal} 不在设备反馈集合内`);
  return errs;
}
function opErrors(op: WizOp, devices: FieldDevice[]): string[] {
  const errs: string[] = [];
  if (!op.em.trim()) errs.push("EM 名称不能为空");
  const ids = new Set(devices.map(d => d.id));
  for (const r of op.resourceIds) if (!ids.has(r)) errs.push(`资源 ${r} 已不存在（设备已删除）`);
  if (!op.resourceIds.length) errs.push("至少关联一个资源");
  if (!op.steps.length) errs.push("至少需要 1 个步骤");
  return errs;
}

/** 组装提交后端的显式规格（spec 形状与 processos/spec_builder.py 锁定一致）。 */
export function buildSpecPayload(args: {
  name: string; cpu: CpuEntry | null; deviceName: string;
  network: { ip: string; subnet: string; device_name: string };
  devices: FieldDevice[]; ops: WizOp[];
}): ProjectSpec {
  return {
    name: args.name,
    cpu: args.cpu ?? undefined,
    device_name: args.deviceName,
    network: args.network,
    devices: args.devices.map(d => ({ type: d.type, name: d.name, id: d.id, params: d.params })),
    operations: args.ops.map(op => ({
      em: op.em,
      name: op.name,
      resource_ids: op.resourceIds,
      steps: op.steps.map((s, i): SpecStepOf => ({
        id: s.id,
        name: s.name,
        ...(s.guardSignal ? { guard: { signal: s.guardSignal, op: "==" as const, value: s.guardValue } } : {}),
        actions: s.commands.map(c => ({ command: c })),
        ...(s.timeoutMs > 0 ? { timeout_ms: s.timeoutMs } : {}),
        failure_target: s.failureTarget,
        next: resolveNext(s, i, op.steps),
      })),
    })),
  };
}
type SpecStepOf = ProjectSpec["operations"][number]["steps"][number];

/* ---------- 步骤卡（展示组件，测试可用 renderToString 直接驱动） ---------- */

export function StepCardView({ step, index, stepIds, commandOpts, feedbackOpts, errors,
  onPatch, onDel, onMove, canUp, canDown }: {
  step: WizStep; index: number; stepIds: string[];
  commandOpts: string[]; feedbackOpts: string[]; errors: string[];
  onPatch: (patch: Partial<WizStep>) => void;
  onDel: () => void; onMove: (dir: -1 | 1) => void;
  canUp: boolean; canDown: boolean;
}) {
  const stale = step.commands.filter(c => !commandOpts.includes(c));
  return (
    <div className="pos-wiz-step">
      <div className="pos-wiz-step-h">
        <span className="pos-wiz-no">{index + 1}</span>
        <input className="pos-wiz-name" aria-label="步骤名称" value={step.name} placeholder="步骤名称"
          onChange={e => onPatch({ name: e.target.value })} />
        <div className="pos-wiz-move">
          <button title="上移" disabled={!canUp} onClick={() => onMove(-1)}>↑</button>
          <button title="下移" disabled={!canDown} onClick={() => onMove(1)}>↓</button>
          <button title="删除步骤" className="pos-wiz-del" onClick={onDel}><Icon name="cross" size={11} /></button>
        </div>
      </div>
      <div className="pos-wiz-fields">
        <div className="pos-wiz-field">
          <label>guard（反馈条件）</label>
          <div className="pos-wiz-guard">
            <select aria-label="guard 信号" value={step.guardSignal} onChange={e => onPatch({ guardSignal: e.target.value })}>
              <option value="">无</option>
              {feedbackOpts.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
            {step.guardSignal !== "" && (
              <select aria-label="guard 值" value={step.guardValue ? "true" : "false"}
                onChange={e => onPatch({ guardValue: e.target.value === "true" })}>
                <option value="true">== 真</option>
                <option value="false">== 假</option>
              </select>
            )}
          </div>
        </div>
        <div className="pos-wiz-field">
          <label>超时 ms</label>
          <input aria-label="超时毫秒" type="number" min={1} value={step.timeoutMs}
            onChange={e => onPatch({ timeoutMs: Number(e.target.value) || 0 })} />
        </div>
        <div className="pos-wiz-field pos-wiz-wide">
          <label>动作（命令，来自该操作的资源）</label>
          <div className="pos-wiz-cmds">
            {commandOpts.length === 0 && stale.length === 0 && <span className="hint">该操作未关联资源</span>}
            {commandOpts.map(c => (
              <label key={c} className={step.commands.includes(c) ? "on" : ""}>
                <input type="checkbox" checked={step.commands.includes(c)}
                  onChange={e => onPatch({ commands: e.target.checked ? [...step.commands, c] : step.commands.filter(x => x !== c) })} />
                {c}
              </label>
            ))}
            {stale.map(c => (
              <label key={c} className="stale"><input type="checkbox" checked readOnly />{c}</label>
            ))}
          </div>
        </div>
        <div className="pos-wiz-field">
          <label>故障出口</label>
          <select aria-label="故障出口" value={step.failureTarget} onChange={e => onPatch({ failureTarget: e.target.value })}>
            <option value="">无</option>
            {targetChoices(stepIds, step.id).map(id => <option key={id} value={id}>{id}</option>)}
          </select>
        </div>
        <div className="pos-wiz-field">
          <label>下一步（仅既有步骤，无自由连线）</label>
          <select aria-label="下一步" value={step.nextMode === "auto" ? "__auto" : step.nextId}
            onChange={e => e.target.value === "__auto"
              ? onPatch({ nextMode: "auto", nextId: "" })
              : onPatch({ nextMode: "id", nextId: e.target.value })}>
            <option value="__auto">自动 · 时序后继</option>
            {targetChoices(stepIds, step.id).map(id => <option key={id} value={id}>{id}</option>)}
          </select>
        </div>
      </div>
      {errors.length > 0 && (
        <div className="pos-wiz-errs">
          {errors.map(e => <div key={e} className="pos-wiz-err"><Icon name="warn" size={11} /> {e}</div>)}
        </div>
      )}
    </div>
  );
}

/* ---------- IO / 符号预览（只读，从类型契约推导；推导不出 → UNKNOWN） ---------- */

export function IoSignalTable({ devices, cat }: { devices: FieldDevice[]; cat: DeviceCatalog | null }) {
  const rows = signalTable(devices, cat);
  return (
    <div className="pos-wiz-io">
      <div className="pos-wiz-io-h">IO / 符号预览<span className="sp" /><span className="hint">由设备类型契约推导 · 只读</span></div>
      <table>
        <thead><tr><th>信号名</th><th>方向</th><th>所属执行器</th><th>建议符号名</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={`${r.deviceId}:${r.dir}:${r.signal}`}>
              <td>{r.signal}</td>
              <td>{r.kind === "UNKNOWN" ? "UNKNOWN" : r.dir === "I" ? "I（输入）" : "Q（输出）"}</td>
              <td>{r.deviceName} <span className="mono">{r.deviceId}</span></td>
              <td className="mono">{r.symbol}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={4} className="hint">尚未添加现场设备</td></tr>}
        </tbody>
      </table>
      <div className="pos-wiz-io-note">符号命名策略：symbolic_only — 契约只声明符号名（如 CM_CLAMP_CYL.ExtendedFb），不绑定物理 %I/%Q 地址；地址在编译硬件组态时分配。推导不出的信号显示 UNKNOWN。</div>
    </div>
  );
}

/* ---------- 主向导 ---------- */

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
  const [ops, setOps] = useState<WizOp[]>([]);
  const suggestedRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { processosApi.deviceCatalog().then(c => { setCat(c); setCpu(c.cpus[0]); }).catch(() => setErr("无法加载设备目录")); }, []);

  /* 进入步序编排时按 devices 自动建议一个操作（仅一次，之后由用户增删） */
  useEffect(() => {
    if (step === 4 && !suggestedRef.current && devices.length > 0) {
      suggestedRef.current = true;
      setOps(prev => prev.length ? prev : [{
        em: "EM_01", name: devices[0].name, resourceIds: [devices[0].id], steps: [newWizStep(1)],
      }]);
    }
  }, [step, devices]);

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

  const addOp = () => setOps(prev => [...prev, {
    em: `EM_${String(prev.length + 1).padStart(2, "0")}`, name: "",
    resourceIds: devices.map(d => d.id), steps: [newWizStep(1)],
  }]);
  const delOp = (i: number) => setOps(prev => prev.filter((_, j) => j !== i));
  const patchOp = (i: number, patch: Partial<WizOp>) => setOps(prev => prev.map((o, j) => j === i ? { ...o, ...patch } : o));
  const addStep = (i: number) => setOps(prev => wizAddStep(prev, i));
  const delStep = (i: number, sid: string) => setOps(prev => wizDelStep(prev, i, sid));
  const moveStep = (i: number, sid: string, dir: -1 | 1) => setOps(prev => wizMoveStep(prev, i, sid, dir));
  const patchStep = (i: number, sid: string, patch: Partial<WizStep>) => setOps(prev => wizPatchStep(prev, i, sid, patch));

  const effDevices: FieldDevice[] = devices.length ? devices
    : [{ type: "cylinder", name: "夹紧气缸", id: uid("CM_"), params: { timeout_ms: 3000, hold_ms: 2000 } }];
  const specProblems = step === 5
    ? validateSpec(buildSpecPayload({ name: projectName, cpu, deviceName, network, devices: effDevices, ops }), cat)
    : [];
  const invariantCount = devices.filter(d => cat?.device_types[d.type]?.conflict).length;

  const create = async () => {
    setBusy(true); setErr("");
    const payload = buildSpecPayload({ name: projectName, cpu, deviceName, network, devices: effDevices, ops });
    const problems = validateSpec(payload, cat);
    if (problems.length) { setErr("校验未通过：" + problems[0]); setBusy(false); return; }
    try {
      const r = await createProjectFromSpec(payload);
      onDone(projectName, r.project_id);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };

  if (!cat) return <div className="flow"><div className="flow-body"><div className="hint">{err || "加载设备目录…"}</div></div></div>;

  return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onCancel}><Icon name="back" /> 返回</button>
        <h2>新建项目 · 硬件组态与步序编排</h2>
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
            <div className="panel-h">步序编排（EM / 工位）<span className="sp" /><span className="hint">结构化步序编辑 · 不允许自由连线，下一步只能选择既有步骤</span></div>
            <div className="panel-b">
              <div className="pos-wiz-toolbar">
                <button className="btn sm" onClick={addOp}><Icon name="plus" /> 新增操作 (EM)</button>
                <span className="hint">{devices.length} 台设备 · 可选反馈信号 {feedbackUnion(devices, cat).length} 个</span>
              </div>
              <div className="pos-wiz-ops">
                {ops.map((op, i) => {
                  const cmds = commandOptions(devices, cat, op.resourceIds);
                  const fbs = feedbackUnion(devices, cat);
                  const errs = opErrors(op, devices);
                  return (
                    <div className="pos-wiz-op" key={i}>
                      <div className="pos-wiz-op-h">
                        <span className="pos-wiz-em">{op.em || "(未命名)"}</span>
                        <input className="pos-wiz-opname" aria-label="操作名" value={op.name} placeholder="操作名（如 夹紧与检测）"
                          onChange={e => patchOp(i, { name: e.target.value })} />
                        <button className="pos-wiz-del" title="删除操作" onClick={() => delOp(i)}><Icon name="cross" size={13} /></button>
                      </div>
                      <div className="pos-wiz-res">
                        <span className="pos-wiz-res-t">关联资源：</span>
                        {devices.map(d => (
                          <label key={d.id}>
                            <input type="checkbox" checked={op.resourceIds.includes(d.id)}
                              onChange={e => patchOp(i, { resourceIds: e.target.checked ? [...op.resourceIds, d.id] : op.resourceIds.filter(x => x !== d.id) })} />
                            {d.name}
                          </label>
                        ))}
                        {devices.length === 0 && <span className="hint">无设备</span>}
                      </div>
                      {errs.length > 0 && errs.map(e => <div key={e} className="pos-wiz-err"><Icon name="warn" size={11} /> {e}</div>)}
                      <div className="pos-wiz-timeline">
                        {op.steps.map((s, j) => (
                          <StepCardView key={s.id} step={s} index={j}
                            stepIds={op.steps.map(x => x.id)}
                            commandOpts={cmds} feedbackOpts={fbs}
                            errors={stepCardErrors(s, op.steps, cmds, fbs)}
                            onPatch={p => patchStep(i, s.id, p)}
                            onDel={() => delStep(i, s.id)}
                            onMove={d => moveStep(i, s.id, d)}
                            canUp={j > 0} canDown={j < op.steps.length - 1}
                          />
                        ))}
                        <button className="btn ghost sm pos-wiz-add" onClick={() => addStep(i)}><Icon name="plus" /> 添加步骤</button>
                      </div>
                    </div>
                  );
                })}
                {ops.length === 0 && (
                  <div className="hint pos-wiz-empty">尚无操作。点击「新增操作 (EM)」，或返回「现场设备」添加设备后自动建议。</div>
                )}
              </div>
              <IoSignalTable devices={devices} cat={cat} />
            </div>
          </div>
        )}

        {step === 5 && (
          <div className="panel">
            <div className="panel-h">确认并建立<span className="sp" /><span className="hint">显式步序规格 → 工艺契约（POST /projects/from-spec）</span></div>
            <div className="panel-b">
              <div className="pos-wiz-summary">
                <div className="pw-row"><span>项目</span><b>{projectName}</b></div>
                <div className="pw-row"><span>硬件</span><b>{cpu ? `${cpu.label} · ${cpu.order_no}` : "未选择 CPU"} · {network.ip}</b></div>
                <div className="pw-row"><span>现场设备</span><b>{effDevices.length} 台 — {effDevices.map(d => d.name).join("、")}</b></div>
                {ops.map(op => (
                  <div className="pw-row" key={op.em}><span>步序 {op.em}{op.name ? ` · ${op.name}` : ""}</span><b>{op.steps.length} 步 · 资源 {op.resourceIds.length} 个</b></div>
                ))}
                <div className="pw-row"><span>互锁</span><b>{invariantCount} 项（设备类型契约推导）</b></div>
              </div>
              <div className="preview-cms">
                {effDevices.map(d => {
                  const spec = cat.device_types[d.type];
                  return (
                    <div className="preview-cm" key={d.id}>
                      <span className="pc-tag">{spec ? spec.label : "UNKNOWN"}</span>
                      <div className="pc-body"><div className="pc-name">{d.name} <span className="mono" style={{ color: "var(--faint)", fontSize: 12 }}>{d.id}</span></div>
                        <div className="pc-meta">{spec ? `命令 ${spec.commands.join(", ") || "—"} · 反馈 ${spec.feedback.join(", ")}` : "UNKNOWN"} · 参数 {Object.entries(d.params).map(([k, v]) => `${k}=${v}`).join(", ") || "默认"}</div></div>
                    </div>
                  );
                })}
              </div>
              {specProblems.length > 0 && (
                <div className="note warn" style={{ marginTop: 14 }}>
                  校验未通过（共 {specProblems.length} 项，提交被阻止）：{specProblems.slice(0, 4).join("；")}{specProblems.length > 4 ? "…" : ""}
                </div>
              )}
              <div className="note warn" style={{ marginTop: 14 }}>步序为显式编排（不合成场景，scenarios 为空）；含 1 项阻断问题（安全停机方式）待裁决；I/O 保持 unbound（symbolic_only 符号命名）。</div>
              {err && <div className="note" style={{ marginTop: 12, color: "var(--err)" }}>{err}</div>}
            </div>
          </div>
        )}

        <div className="flow-foot">
          {step > 0 && <button className="btn ghost" onClick={() => setStep(s => s - 1)}>上一步</button>}
          {step < 5 && <button className="btn primary" onClick={() => setStep(s => s + 1)} disabled={(step === 2 && devices.length === 0) || (step === 4 && ops.length === 0)}>下一步 <Icon name="arrow" /></button>}
          {step === 5 && <button className="btn stamp" onClick={create} disabled={busy || specProblems.length > 0}>{busy ? "建立中…" : "建立项目并进入对话"} <Icon name="arrow" /></button>}
        </div>
      </div>
    </div>
  );
}
