import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, processosApi } from "./api";
import { buildContract, ensureContract, type Conversation, type Project } from "./store";
import type { Changeset, ComplianceReport, Contract, DeliveryGate, DeliveryJob, ScenarioResult } from "./types";
import { CodeView, DeviceView, Icon, Sfc, TraceView } from "./views";

const P = {
  hold: "/operations/OP_CLAMP/steps/S_HOLD/duration_ms",
  extend: "/operations/OP_CLAMP/steps/S_EXTEND/timeout_ms",
  retract: "/operations/OP_CLAMP/steps/S_RETRACT/timeout_ms",
  reset: "/operations/OP_CLAMP/steps/S_FAULT/reset_guard",
  start: "/operations/OP_CLAMP/steps/S_WAIT/guard",
};

function NumField({ label, unit, sec, onCommit, step = 0.1, min = 0, max = 60 }: {
  label: string; unit: string; sec: number; onCommit: (ms: number) => void; step?: number; min?: number; max?: number;
}) {
  const [draft, setDraft] = useState(String(sec));
  useEffect(() => { setDraft(String(sec)); }, [sec]);
  const commit = (v: number) => onCommit(Math.round(Math.min(max, Math.max(min, v)) * 1000));
  return (
    <div className="ctrl">
      <div className="cl"><span className="name">{label}</span><span className="unit">{unit}</span></div>
      <div className="numinput">
        <button className="stepbtn" onClick={() => commit((parseFloat(draft) || 0) - step)}>−</button>
        <input value={draft} inputMode="decimal" onChange={e => setDraft(e.target.value)}
          onBlur={() => commit(parseFloat(draft) || 0)}
          onKeyDown={e => { if (e.key === "Enter") { commit(parseFloat(draft) || 0); (e.target as HTMLInputElement).blur(); } }} />
        <button className="stepbtn" onClick={() => commit((parseFloat(draft) || 0) + step)}>+</button>
      </div>
    </div>
  );
}
function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return <div className="toggle"><span>{label}</span><button className={`sw ${on ? "on" : ""}`} onClick={() => onChange(!on)}><i /></button></div>;
}

export function Workspace({ project, conversation, onBack, onNewConversation, onSwitchConversation }: {
  project: Project; conversation: Conversation; onBack: () => void; onNewConversation: () => void; onSwitchConversation: (cid: string) => void;
}) {
  const [contract, setContract] = useState<Contract | null>(null);
  const [revision, setRevision] = useState(0);
  const [mode, setMode] = useState<"talk" | "edit">("talk");
  const [sel, setSel] = useState("S_EXTEND");
  const [view, setView] = useState<"sfc" | "device" | "scl" | "trace">("sfc");
  const [report, setReport] = useState<ComplianceReport | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioResult[]>([]);
  const [scl, setScl] = useState<Record<string, string>>({});
  const [sclFile, setSclFile] = useState("");
  const [showGuards, setShowGuards] = useState(true);
  const [showTimeout, setShowTimeout] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [turns, setTurns] = useState<{ you: string; note: string }[]>([]);
  const [prompt, setPrompt] = useState("");
  const [changeset, setChangeset] = useState<Changeset | null>(null);
  const [approved, setApproved] = useState(false);
  const [gate, setGate] = useState<DeliveryGate | null>(null);
  const [job, setJob] = useState<DeliveryJob | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [toast, setToast] = useState<{ msg: string; err?: boolean } | null>(null);
  const toastTimer = useRef<number>(0);
  const pid = contract?.id ?? "";

  const flash = useCallback((msg: string, err?: boolean) => {
    setToast({ msg, err }); window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2800);
  }, []);

  const refreshDerived = useCallback(async (id: string) => {
    try {
      const [r, g, s] = await Promise.all([processosApi.validate(id), processosApi.generate(id), processosApi.simulate(id)]);
      setReport(r); setScl(g.files); setScenarios(s.results);
      setSclFile(prev => prev && g.files[prev] ? prev : Object.keys(g.files)[0] || "");
    } catch { /* best effort */ }
  }, []);
  const refreshGate = useCallback(async (id: string) => { try { setGate(await processosApi.deliveryGate(id)); } catch { /* */ } }, []);

  useEffect(() => {
    let live = true;
    setContract(null); setTurns([]); setChangeset(null); setApproved(false); setJob(null);
    (async () => {
      try {
        const { contract: c, revision: r } = await ensureContract(conversation.contractId);
        if (!live) return;
        setContract(c); setRevision(r); setSel(c.operations[0]?.steps[1]?.id ?? "S_EXTEND");
        await Promise.all([refreshDerived(c.id), refreshGate(c.id)]);
      } catch (e) { if (live) flash(e instanceof ApiError ? e.message : "加载契约失败", true); }
    })();
    return () => { live = false; };
  }, [conversation.contractId, refreshDerived, refreshGate, flash]);

  const commitOps = useCallback(async (ops: unknown[], note: string) => {
    try {
      const r = await processosApi.patch(pid, revision, ops, "ui-" + Date.now());
      setContract(r.contract); setRevision(r.revision); setChangeset(null); setApproved(false);
      await Promise.all([refreshDerived(pid), refreshGate(pid)]);
      flash(note); return r.revision;
    } catch (e) { flash(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e), true); return revision; }
  }, [pid, revision, refreshDerived, refreshGate, flash]);

  const sendPrompt = async () => {
    const text = prompt.trim(); if (!text) return;
    const m = text.match(/保持(?:时间)?\s*(?:改为|到|=)?\s*(\d+(?:\.\d+)?)\s*秒/);
    const t = text.match(/(伸出|缩回)?超时\s*(?:改为|到|=)?\s*(\d+(?:\.\d+)?)\s*秒/);
    let ops: unknown[] = []; let note = "";
    if (m) { ops = [{ op: "set", path: P.hold, value: Math.round(parseFloat(m[1]) * 1000) }]; note = `保持时间 → ${m[1]}s`; }
    else if (t) { const ms = Math.round(parseFloat(t[2]) * 1000); const keys = t[1] === "伸出" ? [P.extend] : t[1] === "缩回" ? [P.retract] : [P.extend, P.retract]; ops = keys.map(p => ({ op: "set", path: p, value: ms })); note = `超时 → ${t[2]}s`; }
    else { flash("试试：把保持时间改为 4 秒 / 伸出超时改为 5 秒", true); return; }
    setPrompt("");
    const rev = await commitOps(ops, note);
    setTurns(prev => [...prev, { you: text, note: `${note} · 已提交 rev ${rev}，契约 / SCL / 场景同步重新派生` }]);
  };

  const resolveQuestions = async () => {
    if (!contract) return;
    try {
      for (const q of contract.open_questions.filter(q => q.severity === "blocking" && !q.resolution))
        await processosApi.resolveQuestion(pid, q.id, "许可撤销时保持原位，待人工处理", "演示工程师");
      const d = await processosApi.getProject(pid); setContract(d.contract); await refreshGate(pid); flash("阻断问题已人工裁决");
    } catch (e) { flash(e instanceof ApiError ? e.message : String(e), true); }
  };
  const freeze = async () => { try { setChangeset(await processosApi.freezeChangeset(pid)); flash("ChangeSet 已冻结"); } catch (e) { flash(e instanceof ApiError ? e.message : String(e), true); } };
  const approve = async () => { if (!changeset) return; try { await processosApi.approve(pid, changeset.id, "演示工程师"); setApproved(true); await refreshGate(pid); flash("已人工批准 · 绑定 spec_hash"); } catch (e) { flash(e instanceof ApiError ? e.message : String(e), true); } };
  const deliver = async () => { try { setJob(await processosApi.createDelivery(pid)); flash("交付 Job 已创建"); } catch (e) { flash(e instanceof ApiError ? e.message : String(e), true); } };
  const exportScl = () => {
    const blob = new Blob([Object.entries(scl).map(([n, c]) => `// ===== ${n} =====\n${c}`).join("\n\n")], { type: "text/plain" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "af_sources.scl"; a.click(); URL.revokeObjectURL(a.href); flash("已导出 SCL");
  };
  const randomize = () => { const h = (Math.round(Math.random() * 40) + 10) / 10, e = (Math.round(Math.random() * 50) + 20) / 10; commitOps([{ op: "set", path: P.hold, value: Math.round(h * 1000) }, { op: "set", path: P.extend, value: Math.round(e * 1000) }, { op: "set", path: P.retract, value: Math.round(e * 1000) }], `随机示例 · 保持 ${h}s · 超时 ${e}s`); };
  const resetParams = () => commitOps([{ op: "set", path: P.hold, value: 2000 }, { op: "set", path: P.extend, value: 3000 }, { op: "set", path: P.retract, value: 3000 }], "参数已重置为基准");

  const op = contract?.operations[0];
  const steps = op?.steps ?? [];
  const step = (id: string) => steps.find(s => s.id === id);
  const errCount = report?.errors.length ?? 0;
  const warnCount = report?.warnings.length ?? 0;
  const simPassed = scenarios.length > 0 && scenarios.every(s => s.passed);
  const openQs = contract?.open_questions ?? [];
  const blockingOpen = openQs.filter(q => q.severity === "blocking" && !q.resolution);

  return (
    <div className="ws">
      <aside className="ws-side">
        <div className="tb">
          <button className="back" style={{ background: "none", border: "none", color: "var(--muted)", fontSize: "var(--step-small)", display: "flex", gap: 6, alignItems: "center", padding: 0, marginBottom: 10 }} onClick={onBack}><Icon name="back" size={13} /> 项目图纸夹</button>
          <div className="nm">{project.name}</div>
          <div className="mt"><span className="b">{project.kind === "import" ? "导入" : "新建"}</span><span className="b">比例 {project.scale}</span><span className="b">rev {revision}</span></div>
        </div>
        <div className="conv-head">对话 <span className="sp" /><button onClick={onNewConversation}>+ 新对话</button></div>
        <div className="convs">
          {project.conversations.map(c => (
            <button key={c.id} className={`conv ${c.id === conversation.id ? "on" : ""}`} onClick={() => onSwitchConversation(c.id)} data-cid={c.id}>
              <span className="ct">{c.title}</span><span className="cm">{c.created} · {c.contractId}</span>
            </button>
          ))}
        </div>
        <div className="foot">一个项目 · 多段工艺对话 · 真值来自服务端 revision</div>
      </aside>

      <div className="ws-main">
        <div className="ws-bar">
          <div className="seg">
            <button className={mode === "talk" ? "on" : ""} onClick={() => setMode("talk")}>对话编译</button>
            <button className={mode === "edit" ? "on" : ""} onClick={() => setMode("edit")}>编辑器</button>
          </div>
          <div className="sp" />
          <span className="serif" style={{ fontSize: "var(--step-lead)", fontWeight: 600 }}>{conversation.title}</span>
          <div className="sp" />
          <span className={`evidence ${errCount === 0 && simPassed ? "ok" : ""}`}><span className="led" />{job?.status === "SUCCEEDED" ? job.evidence_level : "offline_verified"} · G0 待真机</span>
          <button className="btn stamp sm" onClick={() => { setDrawer(true); refreshGate(pid); }}>审核与交付</button>
        </div>

        {!contract ? <div className="thread"><div className="hint">正在加载契约…</div></div> : mode === "talk" ? (
          <>
            <div className="thread">
              <div className="msg you"><div className="who">工程师</div><div className="body">{contract.name}：气缸伸出到位后保持 {step("S_HOLD") ? (step("S_HOLD")!.duration_ms / 1000) : 2} 秒，再缩回；伸出/缩回超时报警，复位须在缩回到位后。</div></div>
              <div className="msg">
                <div className="who"><Icon name="doc" size={13} /> ProcessOS Agent</div>
                <div className="body">
                  <p className="lead">已将这段工艺编译为一份 AF 契约，绘于图纸。</p>
                  <div data-ui style={{ border: "1px solid var(--line)", background: "var(--sheet)", padding: 10, margin: "6px 0", height: 300, overflow: "auto" }}>
                    <Sfc steps={steps} sel={sel} onSelect={setSel} showGuards={showGuards} showTimeout={showTimeout} />
                  </div>
                  <div data-ui style={{ minHeight: 200 }}>
                    <details className="trace" open><summary><span className="st done">DONE</span><span className="nm">解析意图 · 映射 AF 角色</span><span className="ev">Unit / EM / CM</span></summary>
                      <div className="tbody">站级 → Unit {contract.unit}；任务 → EM {op?.em}；气缸 → CM {contract.resources[0]?.id}（LBC 签名待 G0）；动作 → {steps.length} 个 Sequence Step。</div></details>
                    <details className="trace"><summary><span className={`st ${errCount ? "fail" : "done"}`}>{errCount ? "FAIL" : "DONE"}</span><span className="nm">静态合规检查</span><span className="ev">{errCount} 错误 · {warnCount} 警告</span></summary>
                      <div className="tbody">{report?.checks.slice(0, 8).map((c, i) => <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>{c.level === "pass" ? <Icon name="check" size={12} /> : c.level === "warn" ? <Icon name="warn" size={12} /> : <Icon name="cross" size={12} />}<span>{c.msg}</span></div>)}</div></details>
                    <details className="trace"><summary><span className={`st ${simPassed ? "done" : "fail"}`}>{simPassed ? "DONE" : "RUN"}</span><span className="nm">行为场景仿真</span><span className="ev">{scenarios.filter(s => s.passed).length}/{scenarios.length} 通过</span></summary>
                      <div className="tbody">{scenarios.map(s => <div key={s.scenario_id} style={{ display: "flex", gap: 6, alignItems: "center" }}>{s.passed ? <Icon name="check" size={12} /> : <Icon name="cross" size={12} />}<span>{s.scenario_id}{s.fault_reason ? ` · ${s.fault_reason}` : ""}</span></div>)}</div></details>
                  </div>
                  {openQs.length > 0 && <>
                    <p style={{ marginTop: 16, fontWeight: 600 }}>需要您裁决的</p>
                    <table className="ctable" data-ui><thead><tr><th>项目</th><th>需要的信息</th><th>状态</th></tr></thead>
                      <tbody>{openQs.map(q => <tr key={q.id}><td>{q.id}</td><td className={q.resolution ? "" : "q"}>{q.question}</td><td>{q.resolution ? "已裁决" : "待裁决"}</td></tr>)}</tbody></table>
                    {blockingOpen.length > 0 && <button className="btn sm" onClick={resolveQuestions}>人工裁决阻断问题</button>}
                  </>}
                  <div className="approve" data-ui style={{ minHeight: 180 }}>
                    <h3>批准这份契约</h3>
                    <div className="gap"><span className="ic"><Icon name="warn" /></span><span>I/O 保持 unbound；G0 模板待真机验证。编译通过 ≠ 现场功能正确。</span></div>
                    {!changeset && <button className="btn sm" onClick={freeze}>冻结 ChangeSet</button>}
                    {changeset && <><div className="hash">{changeset.spec_hash}</div>
                      {!approved ? <button className="btn stamp sm" onClick={approve}>人工批准（绑定 spec_hash）</button> : <span style={{ color: "var(--ok)", fontSize: "var(--step-small)", display: "inline-flex", gap: 6, alignItems: "center" }}><Icon name="check" size={12} /> 已人工批准 · hash 绑定</span>}</>}
                  </div>
                  {job && <div className="approve"><h3>交付 · {job.status}</h3>
                    <div className="stagelist">{job.events.map((e, i) => <div key={i} className={`stageitem ${e.ok ? "done" : "fail"}`}><span className="ic">{e.ok ? <Icon name="check" size={12} /> : <Icon name="cross" size={12} />}</span><span className="mono">{e.stage}</span></div>)}</div>
                    {job.artifact && <div className="hash">归档 {job.artifact.archive_sha256}</div>}</div>}
                </div>
              </div>
              {turns.map((t, i) => (
                <div key={i} style={{ display: "contents" }}>
                  <div className="msg you"><div className="who">工程师</div><div className="body">{t.you}</div></div>
                  <div className="msg"><div className="who"><Icon name="doc" size={13} /> ProcessOS Agent</div><div className="body"><details className="trace" open><summary><span className="st done">DONE</span><span className="nm">结构化 Patch · 重新派生</span><span className="ev">offline_verified</span></summary><div className="tbody">{t.note}</div></details></div></div>
                </div>
              ))}
            </div>
            <div className="prompt">
              <textarea value={prompt} placeholder="继续描述工艺，如：把保持时间改为 4 秒" onChange={e => setPrompt(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendPrompt(); } }} />
              <button className="btn primary" onClick={sendPrompt}>编译 <Icon name="arrow" /></button>
            </div>
          </>
        ) : (
          <div className="editor">
            <div className="demo">
              <div className="viewtabs">
                {([["sfc", "步序 SFC"], ["device", "设备图"], ["scl", "SCL 代码"], ["trace", "场景 Trace"]] as const).map(([v, l]) => <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)}>{l}</button>)}
              </div>
              <div className="demobody">
                {view === "sfc" && <div className="canvas" style={showGrid ? {} : { backgroundImage: "none" }}><Sfc steps={steps} sel={sel} onSelect={setSel} showGuards={showGuards} showTimeout={showTimeout} showGrid={showGrid} /></div>}
                {view === "device" && <div className="canvas" style={{ backgroundImage: "none" }}><DeviceView contract={contract} /></div>}
                {view === "scl" && <CodeView files={scl} file={sclFile} onFile={setSclFile} />}
                {view === "trace" && <TraceView results={scenarios} />}
              </div>
            </div>
            <div className="controls">
              <div className="scroll">
                <div className="chead">参数 · 数字输入</div>
                <NumField label="保持时间" unit="秒" sec={(step("S_HOLD")?.duration_ms ?? 2000) / 1000} onCommit={ms => commitOps([{ op: "set", path: P.hold, value: ms }], `保持时间 → ${ms / 1000}s`)} />
                <NumField label="伸出超时" unit="秒" sec={(step("S_EXTEND")?.timeout_ms ?? 3000) / 1000} onCommit={ms => commitOps([{ op: "set", path: P.extend, value: ms }], `伸出超时 → ${ms / 1000}s`)} />
                <NumField label="缩回超时" unit="秒" sec={(step("S_RETRACT")?.timeout_ms ?? 3000) / 1000} onCommit={ms => commitOps([{ op: "set", path: P.retract, value: ms }], `缩回超时 → ${ms / 1000}s`)} />
                <div className="ctrl"><div className="cl"><span className="name">复位条件</span></div>
                  <select value={step("S_FAULT")?.reset_guard || ""} onChange={e => commitOps([{ op: "set", path: P.reset, value: e.target.value }], "复位条件已更新")}>
                    <option>Reset AND Retracted AND NOT Extended</option><option>Reset AND Retracted</option><option>Reset</option></select></div>
                <div className="ctrl"><div className="cl"><span className="name">启动许可</span></div>
                  <select value={step("S_WAIT")?.guard || ""} onChange={e => commitOps([{ op: "set", path: P.start, value: e.target.value }], "启动许可已更新")}>
                    <option>Start AND SafetyPermit</option><option>Start</option></select></div>
                <div className="chead2">视图</div>
                <Toggle label="显示 Guard 标注" on={showGuards} onChange={setShowGuards} />
                <Toggle label="显示超时 / 复位路径" on={showTimeout} onChange={setShowTimeout} />
                <Toggle label="显示网格" on={showGrid} onChange={setShowGrid} />
                <div className="ctrlrow"><button className="btn ghost sm" onClick={resetParams}>重置</button><button className="btn ghost sm" onClick={randomize}>随机</button><button className="btn sm" onClick={exportScl}>导出</button></div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className={`scrim ${drawer ? "open" : ""}`} onClick={() => setDrawer(false)} />
      <div className={`drawer ${drawer ? "open" : ""}`}>
        <header><h3>审核与交付</h3><button className="iconbtn" onClick={() => setDrawer(false)}><Icon name="cross" /></button></header>
        <div className="dbody">
          <div className="dsec"><h4>人工裁决</h4>
            {openQs.map(q => <div key={q.id} className={`gaterow ${q.resolution ? "pass" : "fail"}`}><span className="ic">{q.resolution ? <Icon name="check" size={11} /> : "?"}</span><span style={{ flex: 1 }}>{q.question}</span></div>)}
            <button className="btn sm" onClick={resolveQuestions}>裁决阻断问题</button></div>
          <div className="dsec"><h4>冻结与批准</h4>
            {!changeset && <button className="btn sm" onClick={freeze}>冻结 ChangeSet</button>}
            {changeset && <><div className="hash">{changeset.spec_hash}</div>{!approved ? <button className="btn stamp sm" onClick={approve}>人工批准</button> : <div className="gaterow pass"><span className="ic"><Icon name="check" size={11} /></span>已批准 · hash 绑定</div>}</>}</div>
          <div className="dsec"><h4>交付门禁</h4>
            {gate && Object.entries(gate.checks).map(([k, v]) => <div key={k} className={`gaterow ${v ? "pass" : "fail"}`}><span className="ic">{v ? <Icon name="check" size={11} /> : <Icon name="cross" size={11} />}</span>{k}</div>)}
            <div className="note warn" style={{ margin: "12px 0" }}>G0 未验证：原生构建为受限演示模式（mocked），完整逻辑含 OB_Main。真实 .zap19 需 Windows V19 Worker 回执。</div>
            <button className="btn stamp" disabled={!gate?.ready} onClick={deliver}>创建交付 Job</button>
            {job && <><div className="stagelist">{job.events.map((e, i) => <div key={i} className={`stageitem ${e.ok ? "done" : "fail"}`}><span className="ic">{e.ok ? <Icon name="check" size={12} /> : <Icon name="cross" size={12} />}</span><span className="mono">{e.stage}</span></div>)}</div>
              {job.artifact && <div className="hash" style={{ marginTop: 10 }}>归档 {job.artifact.archive_sha256}</div>}</>}</div>
        </div>
      </div>
      <div className={`toast ${toast ? "show" : ""} ${toast?.err ? "err" : ""}`}>{toast?.msg}</div>
    </div>
  );
}
