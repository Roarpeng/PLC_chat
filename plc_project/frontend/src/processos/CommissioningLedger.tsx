import { useCallback, useEffect, useState } from "react";
import { ApiError, processosApi } from "./api";
import { roleDeniedText } from "./actor";
import { Badge, FieldTop, useFlash, verdictTone, type FieldView } from "./fieldui";
import type { DeploymentRecord, DeploymentTestRow, ProjectSummary } from "./types";
import { Icon } from "./views";

/* FC-14 — engineers register what ACTUALLY happened on the device after a
   manual TIA download/debug. The ledger records field facts; it never
   triggers a download. */
const EMPTY_FORM = {
  project_id: "", build_id: "", artifact_sha256: "", device_id: "",
  operator: "", plc_checksum: "", commissioned_at: "", result: "COMMISSIONED" as DeploymentRecord["result"],
};
const EMPTY_ROW: DeploymentTestRow = { name: "", passed: true, note: "" };

export function CommissioningLedger({ onBack, onNav }: { onBack: () => void; onNav: (v: FieldView) => void }) {
  const { flash, toastEl } = useFlash();
  const [records, setRecords] = useState<DeploymentRecord[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [tests, setTests] = useState<DeploymentTestRow[]>([{ ...EMPTY_ROW }]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try { setRecords((await processosApi.listDeploymentRecords()).records); }
    catch (e) { const d = roleDeniedText(e); if (d) flash(d, true); }
  }, [flash]);

  useEffect(() => {
    refresh();
    processosApi.projects().then(r => {
      setProjects(r.projects);
      setForm(f => f.project_id ? f : { ...f, project_id: r.projects[0]?.project_id ?? "" });
    }).catch(() => setProjects([]));
  }, [refresh]);

  const set = (k: keyof typeof EMPTY_FORM, v: string) => setForm({ ...form, [k]: v });

  const submit = async () => {
    if (!form.project_id || !form.build_id || !form.device_id) { flash("project_id / build_id / device_id 必填", true); return; }
    setBusy(true);
    try {
      await processosApi.createDeploymentRecord({
        ...form,
        commissioned_at: form.commissioned_at || new Date().toISOString(),
        tests: tests.filter(t => t.name.trim()),
      });
      flash("调试记录已登记");
      setForm({ ...EMPTY_FORM, project_id: form.project_id });
      setTests([{ ...EMPTY_ROW }]);
      await refresh();
    } catch (e) {
      const denied = roleDeniedText(e);
      flash(denied ?? (e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)), true);
    } finally { setBusy(false); }
  };

  return (
    <div className="flow">
      <FieldTop view="commissioning" onNav={onNav} onBack={onBack} title="调试台账"
        hint="COMMISSIONED 只能由现场复测证据支撑" />
      <div className="flow-body fc-body">
        <div className="fc-banner warn">
          <Icon name="warn" size={14} /> 下载 TIA 工程 ≠ 将程序下载到现场 PLC。本台账只登记现场事实（设备、校验和、测试与结果），不触发任何下载或写 PLC 操作。
        </div>

        <section className="panel">
          <div className="panel-h">登记表单<span className="sp" /><span className="hint">仅 CommissioningEngineer 及以上角色可登记</span></div>
          <div className="panel-b">
            <div className="form-grid">
              <div className="field"><label>项目</label>
                <select value={form.project_id} onChange={e => set("project_id", e.target.value)}>
                  <option value="">（选择项目）</option>
                  {projects.map(p => <option key={p.project_id} value={p.project_id}>{p.project_id} · {p.name}</option>)}
                </select></div>
              <div className="field"><label>build_id（交付的构建）</label>
                <input value={form.build_id} onChange={e => set("build_id", e.target.value)} placeholder="build_219" /></div>
              <div className="field"><label>artifact_sha256（工程归档哈希）</label>
                <input className="mono" value={form.artifact_sha256} onChange={e => set("artifact_sha256", e.target.value)} placeholder="sha256:…" /></div>
              <div className="field"><label>device_id（现场设备）</label>
                <input value={form.device_id} onChange={e => set("device_id", e.target.value)} placeholder="plc_station_01" /></div>
              <div className="field"><label>operator（操作工程师）</label>
                <input value={form.operator} onChange={e => set("operator", e.target.value)} /></div>
              <div className="field"><label>plc_checksum（在线比较校验和）</label>
                <input className="mono" value={form.plc_checksum} onChange={e => set("plc_checksum", e.target.value)} /></div>
              <div className="field"><label>commissioned_at（部署时间）</label>
                <input type="datetime-local" value={form.commissioned_at} onChange={e => set("commissioned_at", e.target.value)} /></div>
              <div className="field"><label>result（验收结果）</label>
                <select value={form.result} onChange={e => set("result", e.target.value)}>
                  <option value="COMMISSIONED">COMMISSIONED · 已验收</option>
                  <option value="FAILED">FAILED · 验收失败</option>
                  <option value="ROLLED_BACK">ROLLED_BACK · 已回退</option>
                </select></div>
            </div>

            <div className="sidehead">现场测试（动态行）</div>
            <div className="tl-tests">
              {tests.map((t, i) => (
                <div className="tl-testrow" key={i}>
                  <input placeholder="测试名称，如 extend_timeout 复测" value={t.name}
                    onChange={e => setTests(tests.map((r, j) => j === i ? { ...r, name: e.target.value } : r))} />
                  <select value={t.passed ? "1" : "0"} onChange={e => setTests(tests.map((r, j) => j === i ? { ...r, passed: e.target.value === "1" } : r))}>
                    <option value="1">通过</option><option value="0">未通过</option>
                  </select>
                  <input placeholder="备注" value={t.note}
                    onChange={e => setTests(tests.map((r, j) => j === i ? { ...r, note: e.target.value } : r))} />
                  <button className="btn ghost sm" onClick={() => setTests(tests.length > 1 ? tests.filter((_, j) => j !== i) : tests)}
                    title="删除该行"><Icon name="cross" size={12} /></button>
                </div>
              ))}
              <button className="btn ghost sm" onClick={() => setTests([...tests, { ...EMPTY_ROW }])}><Icon name="plus" size={12} /> 添加测试行</button>
            </div>

            <div className="ctrlrow">
              <button className="btn stamp" onClick={submit} disabled={busy}>{busy ? "登记中…" : "登记调试记录"}</button>
              <span className="hint">登记的是人工复测结果；FAILED / ROLLED_BACK 同样必须登记。</span>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-h">已登记记录<span className="sp" /><span className="hint">{records.length} 条</span></div>
          <div className="panel-b">
            {records.length === 0 && <div className="hint">暂无调试记录。</div>}
            {records.length > 0 && (
              <table className="ctable">
                <thead><tr><th>记录</th><th>构建</th><th>设备 / 操作员</th><th>校验和</th><th>测试</th><th>结果</th></tr></thead>
                <tbody>{records.map(r => (
                  <tr key={r.record_id}>
                    <td className="mono">{r.record_id}<div className="hint">{r.commissioned_at}</div></td>
                    <td className="mono">{r.build_id}<div className="hint mono">{String(r.artifact_sha256 || "").slice(0, 22)}</div></td>
                    <td>{r.device_id}<div className="hint">{r.operator}</div></td>
                    <td className="mono">{String(r.plc_checksum || "-")}</td>
                    <td>{r.tests?.filter(t => t.passed).length ?? 0}/{r.tests?.length ?? 0} 通过
                      {r.tests?.some(t => !t.passed) && <div className="hint">{r.tests.filter(t => !t.passed).map(t => t.name).join("、")} 未通过</div>}</td>
                    <td><Badge tone={verdictTone(r.result)}>{r.result}</Badge></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        </section>
      </div>
      {toastEl}
    </div>
  );
}
