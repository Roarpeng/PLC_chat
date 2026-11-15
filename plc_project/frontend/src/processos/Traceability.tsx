import { useCallback, useEffect, useState } from "react";
import { processosApi } from "./api";
import { FieldTop, type FieldView } from "./fieldui";
import { ImpactPanel } from "./ImpactPanel";
import { TelemetryPanel } from "./TelemetryPanel";
import type { HandoverContext, Incident, ObjectContext } from "./types";
import { Icon } from "./views";

function ChainCard({ no, title, children }: { no: string; title: string; children: React.ReactNode }) {
  return (
    <div className="chain-card">
      <div className="chain-no">{no}</div>
      <div className="chain-body">
        <div className="chain-title">{title}</div>
        {children}
      </div>
    </div>
  );
}

export function Traceability({ onBack, onNav, focusIncidentId, focusObjectId }: {
  onBack: () => void; onNav?: (v: FieldView) => void; focusIncidentId?: string; focusObjectId?: string;
}) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [sel, setSel] = useState<string>("");
  const [ho, setHo] = useState<HandoverContext | null>(null);
  const [search, setSearch] = useState("");
  const [searchCtx, setSearchCtx] = useState<ObjectContext | null>(null);
  const [err, setErr] = useState("");

  const loadIncidents = useCallback(async () => {
    try {
      const r = await processosApi.incidents();
      setIncidents(r.incidents);
      if (r.incidents[0]) setSel(r.incidents[0].incident_id);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => { loadIncidents(); }, [loadIncidents]);

  /* entry ②/③ from FieldConsole: focus the requested incident once loaded */
  useEffect(() => {
    if (focusIncidentId && incidents.some(i => i.incident_id === focusIncidentId)) setSel(focusIncidentId);
  }, [focusIncidentId, incidents]);

  /* canvas CM card click: prefill + resolve the object context directly by id */
  useEffect(() => {
    if (!focusObjectId) return;
    processosApi.objectContext(focusObjectId)
      .then(c => { setSearchCtx(c); setSearch(c.display_name || focusObjectId); })
      .catch(() => setErr("未找到对象：" + focusObjectId));
  }, [focusObjectId]);

  useEffect(() => {
    if (!sel) return;
    processosApi.handover(sel).then(setHo).catch(e => setErr(e instanceof Error ? e.message : String(e)));
  }, [sel]);

  const doSearch = async () => {
    if (!search.trim()) return;
    try {
      const obj = await processosApi.findObject(search.trim());
      const ctx = await processosApi.objectContext(obj.object_id);
      setSearchCtx(ctx);
    } catch { setSearchCtx(null); setErr("未找到对象：" + search); }
  };

  const verifyRoot = async (verified: boolean) => {
    if (!ho || !ho.incident.triage.root_cause && !verified) return;
    const rc = ho.incident.triage.root_cause || "传感器故障";
    await processosApi.triage(sel, { root_cause: rc, root_cause_verified: verified });
    const h = await processosApi.handover(sel); setHo(h);
  };

  const inc = ho?.incident;
  const ctx = ho?.object_context;

  return (
    <div className="flow">
      <FieldTop view="trace" onNav={onNav ?? (() => { })} onBack={onBack} title="现场追溯"
        hint="从报警 → 工位 → AF → 行为 → 源码 → 证据 → 行动" />

      <div className="trace-layout">
        <aside className="trace-side">
          <div className="sidehead">问题单</div>
          <div className="inc-list">
            {incidents.map(i => (
              <button key={i.incident_id} className={`inc-item ${sel === i.incident_id ? "on" : ""}`} onClick={() => setSel(i.incident_id)}>
                <span className="inc-id">{i.incident_id}</span>
                <span className="inc-code">{String(i.alarm?.definition_id || "")}</span>
                <span className={`inc-status ${i.handover?.status === "RESOLVED" ? "ok" : ""}`}>{i.handover?.status}</span>
              </button>
            ))}
            {incidents.length === 0 && <div className="hint" style={{ padding: 12 }}>暂无问题单</div>}
          </div>
          <div className="sidehead">按对象查找</div>
          <div className="obj-search">
            <input value={search} placeholder="组件名 / 别名…" onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === "Enter" && doSearch()} />
            <button className="btn sm" onClick={doSearch}>定位</button>
          </div>
          {searchCtx && (
            <div className="obj-result">
              <div className="or-name">{searchCtx.display_name}</div>
              <div className="or-path">{searchCtx.physical_path}</div>
              <div className="or-af">{Object.entries(searchCtx.af).map(([k, v]) => `${k}:${v}`).join(" · ")}</div>
            </div>
          )}
        </aside>

        <main className="trace-main">
          {err && <div className="note" style={{ color: "var(--err)" }}>{err}</div>}
          {!ho && <div className="hint">选择一个问题单查看交接上下文。</div>}
          {ho && inc && ctx && (
            <>
              <div className="inc-header">
                <div>
                  <div className="ih-id">{inc.incident_id}</div>
                  <div className="ih-sub">{String(inc.alarm?.definition_id)} · {String(inc.alarm?.event_time)} · 部署版本 <b>{ho.resolved_at_build}</b></div>
                </div>
                <span className={`inc-status ${inc.handover?.status === "RESOLVED" ? "ok" : ""}`}>{inc.handover?.status}</span>
              </div>

              <div className="chain">
                <ChainCard no="位置" title="物理定位（发生时路径）">
                  <div className="chain-path">{inc.physical_path_at_event}</div>
                  <div className="chain-meta">当前解析：{ctx.physical_path} · 对象 <span className="mono">{inc.object_id}</span></div>
                </ChainCard>

                <ChainCard no="AF" title="AF 组织">
                  <div className="af-row">
                    <span className="af-chip unit">Unit · {ctx.af.unit || inc.af_refs?.unit_id}</span>
                    <span className="af-arr">→</span>
                    <span className="af-chip em">EM · {ctx.af.em || inc.af_refs?.em_id}</span>
                    <span className="af-arr">→</span>
                    <span className="af-chip cm">CM · {ctx.af.cm || inc.af_refs?.cm_id}</span>
                  </div>
                </ChainCard>

                <ChainCard no="行为" title="行为契约（期望 vs 观测）">
                  <div className="beh-row"><span className="beh-k">Step</span><span className="mono">{String(inc.behavior?.step_id)}</span></div>
                  <div className="beh-row"><span className="beh-k ok">期望</span><span>{String(inc.behavior?.expected)}</span></div>
                  <div className="beh-row"><span className="beh-k err">观测</span><span>{String(inc.behavior?.observed)}</span></div>
                </ChainCard>

                <ChainCard no="源码" title="原生源码映射（SourceMap）">
                  {ctx.source_map.length === 0 && <div className="chain-meta">无映射（UNKNOWN）</div>}
                  {ctx.source_map.map(s => (
                    <div className="sm-row" key={s.source_map_id}>
                      <span className="sm-block mono">{s.block_name}</span>
                      <span className="sm-kind">{s.block_kind}</span>
                      {s.instance_db && <span className="sm-db mono">{s.instance_db}</span>}
                      <span className="sm-line">{s.scl_line_range ? `行 ${s.scl_line_range[0]}–${s.scl_line_range[1]}` : "块级定位"}</span>
                      <span className="sm-own">{s.ownership}</span>
                    </div>
                  ))}
                </ChainCard>

                <ChainCard no="诊断" title="诊断与分诊（观测 ≠ 根因）">
                  <div className="beh-row"><span className="beh-k">事实</span><span>{inc.triage.fact}</span></div>
                  <div className="hyp">
                    {inc.triage.hypotheses.map((h, i) => <span className="hyp-chip" key={i}>{h}</span>)}
                  </div>
                  <div className="rootcause">
                    <span className="beh-k">根因</span>
                    {inc.triage.root_cause
                      ? <span className="rc-verified"><Icon name="check" size={12} /> {inc.triage.root_cause}（已验证）</span>
                      : <span className="rc-null">未确认（候选原因不等于根因）</span>}
                    <button className="btn sm ghost" onClick={() => verifyRoot(!inc.triage.root_cause_verified)}>
                      {inc.triage.root_cause_verified ? "撤销验证" : "人工/仪器确认根因"}
                    </button>
                  </div>
                </ChainCard>

                <ChainCard no="行动" title="交接与下一步">
                  <div className="beh-row"><span className="beh-k">负责人</span><span>{inc.handover?.owner}</span></div>
                  <div className="beh-row"><span className="beh-k">下一步</span><span>{inc.handover?.next_action}</span></div>
                  <div className="chain-meta">{ho.triage_note}</div>
                </ChainCard>
              </div>

              <details className="fc-fold">
                <summary><Icon name="warn" size={13} /> 影响分析（FC-05 · 该对象）</summary>
                <div className="fc-fold-body">
                  <ImpactPanel objectId={inc.object_id} />
                </div>
              </details>
              <details className="fc-fold">
                <summary><Icon name="doc" size={13} /> 对象事件时间线（FC-15 · 遥测与手工证据）</summary>
                <div className="fc-fold-body">
                  <TelemetryPanel objectId={inc.object_id} />
                </div>
              </details>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
