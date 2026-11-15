import { useEffect, useState } from "react";
import { ApiError, processosApi } from "./api";
import { loadActor, roleDeniedText } from "./actor";
import { Badge, FieldTop, useFlash, type FieldView } from "./fieldui";
import type { GatewayExecuteResult, GatewayPrecheck, ProjectSummary } from "./types";
import { Icon } from "./views";

/* FC-18 — a CONTROLLED gateway, never one-click go-live. Execute needs an
   explicit second confirmation dialog and remains subject to on-site human
   authorization; SAFETY_SCOPE_BLOCKED responses render as a hard stop. */
const EMPTY_FORM = {
  project_id: "", build_id: "", device_id: "", window_start: "", window_end: "",
  second_person: "", authorized_window: false,
  online_compare: true, retain_assessment: true, rollback_plan: true,
};
const CONFIRM_PHRASE = "确认执行受控下载";

function CheckRow({ tone, code, label }: { tone: "ok" | "err" | "warn"; code: string; label: string }) {
  return (
    <div className={`gaterow ${tone === "ok" ? "pass" : tone === "err" ? "fail" : ""}`}>
      <span className="ic">{tone === "ok" ? <Icon name="check" size={11} /> : tone === "err" ? <Icon name="cross" size={11} /> : "?"}</span>
      <Badge tone={tone}>{code}</Badge>
      <span style={{ flex: 1 }}>{label}</span>
    </div>
  );
}

export function DeploymentGateway({ onBack, onNav }: { onBack: () => void; onNav: (v: FieldView) => void }) {
  const { flash, toastEl } = useFlash();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [pre, setPre] = useState<GatewayPrecheck | null>(null);
  const [exec, setExec] = useState<GatewayExecuteResult | null>(null);
  const [blocked, setBlocked] = useState<{ code: string; message: string } | null>(null);
  const [modal, setModal] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    processosApi.projects().then(r => {
      setProjects(r.projects);
      setForm(f => f.project_id ? f : { ...f, project_id: r.projects[0]?.project_id ?? "" });
    }).catch(() => setProjects([]));
  }, []);

  const set = <K extends keyof typeof EMPTY_FORM>(k: K, v: (typeof EMPTY_FORM)[K]) => setForm({ ...form, [k]: v });

  const runPrecheck = async () => {
    if (!form.build_id || !form.device_id || !form.window_start || !form.window_end) {
      flash("build_id / device_id / 停机窗口必填", true); return;
    }
    setBusy(true); setPre(null); setExec(null); setBlocked(null);
    try {
      // 后端契约：window 为字符串；online_compare / retain_assessment / rollback_plan
      // 为对象（已提供）或 null（未提供）；authorized_window 独立声明。
      setPre(await processosApi.gatewayPrecheck({
        project_id: form.project_id, build_id: form.build_id, device_id: form.device_id,
        window: `${form.window_start} ~ ${form.window_end}`,
        online_compare: form.online_compare ? { attested: true } : null,
        retain_assessment: form.retain_assessment ? { attested: true } : null,
        rollback_plan: form.rollback_plan ? { attested: true } : null,
        second_person: form.second_person,
        authorized_window: form.authorized_window,
      }));
      flash("precheck 完成");
    } catch (e) {
      const denied = roleDeniedText(e);
      if (denied) flash(denied, true);
      else if (e instanceof ApiError) setBlocked({ code: e.code ?? `HTTP_${e.status}`, message: e.message });
      else flash(String(e), true);
    } finally { setBusy(false); }
  };

  const doExecute = async () => {
    if (!pre) return;
    setBusy(true);
    try {
      const r = await processosApi.gatewayExecute({
        precheck_id: pre.precheck_id,
        confirm: true, // UI 二次确认短语通过后才允许提交
        actor: form.second_person || loadActor().id,
      });
      setExec(r); flash("受控执行已受理");
    } catch (e) {
      const denied = roleDeniedText(e);
      if (denied) flash(denied, true);
      else if (e instanceof ApiError) setBlocked({ code: e.code ?? `HTTP_${e.status}`, message: e.message });
      else flash(String(e), true);
    } finally { setBusy(false); setModal(false); setPhrase(""); }
  };

  return (
    <div className="flow">
      <FieldTop view="gateway" onNav={onNav} onBack={onBack} title="部署网关"
        hint="独立站点部署网关（可选 FC-18）· 受控在线加载" />
      <div className="flow-body fc-body">
        <div className="fc-banner err">
          <Icon name="warn" size={14} /> 不存在一键上线：任何在线加载必须经过 precheck、停机窗口、双人复核与现场授权；本页面也不提供任何直接操作物理输出的入口。
        </div>

        <section className="panel">
          <div className="panel-h">部署前检查（precheck）</div>
          <div className="panel-b">
            <div className="form-grid">
              <div className="field"><label>项目</label>
                <select value={form.project_id} onChange={e => set("project_id", e.target.value)}>
                  <option value="">（选择项目）</option>
                  {projects.map(p => <option key={p.project_id} value={p.project_id}>{p.project_id} · {p.name}</option>)}
                </select></div>
              <div className="field"><label>build_id</label>
                <input value={form.build_id} onChange={e => set("build_id", e.target.value)} placeholder="build_219" /></div>
              <div className="field"><label>device_id（目标 PLC）</label>
                <input value={form.device_id} onChange={e => set("device_id", e.target.value)} /></div>
              <div className="field"><label>停机窗口开始</label>
                <input type="datetime-local" value={form.window_start} onChange={e => set("window_start", e.target.value)} /></div>
              <div className="field"><label>停机窗口结束</label>
                <input type="datetime-local" value={form.window_end} onChange={e => set("window_end", e.target.value)} /></div>
              <div className="field"><label>第二复核人（second person）</label>
                <input value={form.second_person} onChange={e => set("second_person", e.target.value)} placeholder="field_lead" /></div>
            </div>
            <div className="toggle"><span>现场授权窗口（authorized_window）</span>
              <button className={`sw ${form.authorized_window ? "on" : ""}`} onClick={() => set("authorized_window", !form.authorized_window)}><i /></button></div>
            <div className="toggle"><span>在线比较结果已提供（online_compare）</span>
              <button className={`sw ${form.online_compare ? "on" : ""}`} onClick={() => set("online_compare", !form.online_compare)}><i /></button></div>
            <div className="toggle"><span>数据保持评估已提供（retain_assessment）</span>
              <button className={`sw ${form.retain_assessment ? "on" : ""}`} onClick={() => set("retain_assessment", !form.retain_assessment)}><i /></button></div>
            <div className="toggle"><span>回退方案已归档（rollback_plan）</span>
              <button className={`sw ${form.rollback_plan ? "on" : ""}`} onClick={() => set("rollback_plan", !form.rollback_plan)}><i /></button></div>
            <div className="ctrlrow">
              <button className="btn" onClick={runPrecheck} disabled={busy}>{busy ? "检查中…" : "运行 precheck"}</button>
            </div>
          </div>
        </section>

        {pre && (
          <section className="panel" data-testid="precheck-result">
            <div className="panel-h">precheck 结果 <span className="mono hint">{pre.precheck_id}</span><span className="sp" />
              <Badge tone={pre.ready ? "ok" : pre.blocked_by.length ? "err" : "warn"}>{pre.ready ? "READY" : "NOT READY"}</Badge></div>
            <div className="panel-b">
              {pre.satisfied.length > 0 && <>
                <div className="sidehead">满足（satisfied）</div>
                {pre.satisfied.map(c => <CheckRow key={c} tone="ok" code={c} label="" />)}
              </>}
              {pre.missing.length > 0 && <>
                <div className="sidehead">缺失（missing）</div>
                {pre.missing.map(c => <CheckRow key={c} tone="warn" code={c} label="需补齐后方可执行" />)}
              </>}
              {pre.blocked_by.length > 0 && <>
                <div className="sidehead">阻断（blocked_by）</div>
                {pre.blocked_by.map(c => <CheckRow key={c} tone="err" code={c} label="安全边界阻断，见错误码" />)}
              </>}
              <div className="ctrlrow">
                <button className="btn stamp" disabled={!pre.ready || busy} onClick={() => setModal(true)}>发起受控执行…</button>
                <span className="hint">{pre.ready ? "执行前将再次人工确认" : "ready=false 时不可发起执行"}</span>
              </div>
            </div>
          </section>
        )}

        {blocked && (
          <div className="fc-banner err" role="alert" data-testid="gateway-blocked">
            <Badge tone="err">{blocked.code}</Badge> 部署被阻断：{blocked.message}
            {blocked.code === "SAFETY_SCOPE_BLOCKED" && " — F/Safety、保护块或安全相关范围需要独立流程，网关默认拒绝。"}
            {blocked.code === "UNKNOWN_PLC_STATE" && " — 现场状态未知，禁止自动宣称可安全下载。"}
            {blocked.code === "DRIFT_DETECTED" && " — 在线实际程序与批准工程不一致，变更已冻结。"}
          </div>
        )}

        {exec && (
          <div className="fc-banner info" data-testid="gateway-exec-result">
            执行结果：<Badge tone="ok">{exec.backend}</Badge>
            <span className="mono"> · {exec.precheck_id} · {exec.executed_at}</span>
            {exec.actor && <span> · 执行人 {exec.actor}</span>}
            <div className="hint mono">receipt: {JSON.stringify(exec.result)}</div>
            <div className="hint">{exec.note}受控执行后仍须现场功能复测，并在调试台账登记 COMMISSIONED/FAILED/ROLLED_BACK。</div>
          </div>
        )}
      </div>

      {modal && pre && (
        <div className="fmodal open" role="dialog" aria-modal="true">
          <div className="fm-box">
            <h3>二次确认 · 受控执行</h3>
            <table className="ctable">
              <tbody>
                <tr><td>precheck</td><td className="mono">{pre.precheck_id}</td></tr>
                <tr><td>构建 / 设备</td><td className="mono">{form.build_id} → {form.device_id}</td></tr>
                <tr><td>停机窗口</td><td className="mono">{form.window_start} ~ {form.window_end}</td></tr>
                <tr><td>第二复核人</td><td>{form.second_person || "（未填写）"}</td></tr>
              </tbody>
            </table>
            <div className="note warn">不存在一键上线：本次操作只构造受控加载任务，仍需现场工程师在允许窗口内人工执行、在线比较与复测确认。</div>
            <div className="field"><label>输入「{CONFIRM_PHRASE}」以确认</label>
              <input value={phrase} onChange={e => setPhrase(e.target.value)} placeholder={CONFIRM_PHRASE} /></div>
            <div className="ctrlrow" style={{ justifyContent: "flex-end" }}>
              <button className="btn ghost" onClick={() => { setModal(false); setPhrase(""); }}>取消</button>
              <button className="btn stamp" disabled={phrase !== CONFIRM_PHRASE || busy} onClick={doExecute}>{busy ? "执行中…" : "确认执行"}</button>
            </div>
          </div>
        </div>
      )}
      {toastEl}
    </div>
  );
}
