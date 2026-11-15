import { useState } from "react";
import { ApiError, processosApi } from "./api";
import { roleDeniedText } from "./actor";
import { Badge, riskTone } from "./fieldui";
import type { ImpactReport } from "./types";
import { Icon } from "./views";

/* PLAN §3.3 / FC-05 — every change yields an impact report. Unknown items are
   shown as explicit UNKNOWN badges and block high-risk delivery. */
function AffectedCell({ label, list }: { label: string; list: { object_id: string }[] | undefined | null }) {
  const value = list ? list.length : null;
  return (
    <div className="ip-stat" title={list?.map(o => o.object_id).join(", ")}>
      <span className="ip-num">{value === null || value === undefined ? <Badge tone="unknown">UNKNOWN</Badge> : value}</span>
      <span className="ip-k">{label}</span>
    </div>
  );
}

export function ImpactReportView({ report }: { report: ImpactReport }) {
  return (
    <div className="ip-report" data-testid="impact-report">
      {report.blocked_high_risk_delivery && (
        <div className="fc-banner err" role="alert">高风险交付被阻断 — 存在 UNKNOWN 项或高风险保留数据，须补全证据并复核后方可继续。</div>
      )}
      <div className="ip-stats">
        <AffectedCell label="Unit" list={report.affected?.units} />
        <AffectedCell label="EM" list={report.affected?.ems} />
        <AffectedCell label="CM" list={report.affected?.cms} />
        <AffectedCell label="Step" list={report.affected?.steps} />
      </div>
      <div className="beh-row"><span className="beh-k">分析对象</span>
        <span className="mono">{report.subject?.object_id || "UNKNOWN"}</span>
        {report.subject?.display_name && <span className="hint"> · {report.subject.display_name}</span>}
      </div>
      <div className="beh-row"><span className="beh-k">状态保持风险</span>
        <Badge tone={riskTone(report.state_retention_risk)}>{report.state_retention_risk || "UNKNOWN"}</Badge>
        <span className="beh-k" style={{ marginLeft: 12 }}>在线加载影响</span>
        <Badge tone={report.online_load_impact === "NONE" ? "ok" : report.online_load_impact === "UNKNOWN" ? "unknown" : "warn"}>
          {report.online_load_impact || "UNKNOWN"}
        </Badge>
      </div>
      <div className="beh-row"><span className="beh-k">报警定义</span>
        {report.alarm_definitions?.length
          ? <span className="hyp">{report.alarm_definitions.map(a => <Badge key={a.definition_id} tone="warn" title={a.description}>{a.code || a.definition_id}</Badge>)}</span>
          : <span className="hint">无关联报警定义</span>}
      </div>
      {report.regression_tests?.length > 0 && (
        <div className="beh-row"><span className="beh-k">回归测试</span>
          <span className="hyp">{report.regression_tests.map((t, i) => (
            <Badge key={i} tone={t.status === "PLANNED" ? "info" : "unknown"}>{t.name}: {t.status}</Badge>
          ))}</span>
        </div>
      )}
      <div className="beh-row"><span className="beh-k">未知项</span>
        {report.unknown_fields?.length
          ? <span className="hyp">{report.unknown_fields.map(f => <Badge key={f} tone="unknown" title={f}>UNKNOWN</Badge>)}</span>
          : <span className="hint">无 — 影响面已全部映射</span>}
      </div>
      {report.deployment_notes?.length > 0 && (
        <div className="chain-meta">{report.deployment_notes.map((n, i) => <div key={i}>{n}</div>)}</div>
      )}
    </div>
  );
}

export function ImpactPanel({ projectId, objectId, onBuilt }: {
  projectId?: string; objectId?: string; onBuilt?: (r: ImpactReport) => void;
}) {
  const [oid, setOid] = useState(objectId ?? "");
  const [report, setReport] = useState<ImpactReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const build = async () => {
    const q = oid.trim();
    if (!q) return;
    setBusy(true); setErr("");
    try {
      const r = await processosApi.buildImpact(projectId ?? "", { object_id: q });
      setReport(r); onBuilt?.(r);
    } catch (e) {
      const denied = roleDeniedText(e);
      setErr(denied ?? (e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)));
    } finally { setBusy(false); }
  };

  return (
    <div className="ip-panel">
      <div className="obj-search">
        <input value={oid} placeholder="object_id，如 cm_clamp_a_001" onChange={e => setOid(e.target.value)}
          onKeyDown={e => e.key === "Enter" && build()} />
        <button className="btn sm" onClick={build} disabled={busy}>{busy ? "分析中…" : "生成影响报告"}</button>
      </div>
      {err && <div className="note" style={{ color: "var(--err)" }}>{err}</div>}
      {report && <>
        <div className="chain-meta mono">{report.report_id} · {report.subject?.object_id || "UNKNOWN"}</div>
        <ImpactReportView report={report} />
      </>}
      {!report && !err && <div className="hint">生成受影响 Unit / EM / CM / Step、报警定义、状态保持风险；未知项以 UNKNOWN 显式标出并阻断高风险交付。</div>}
      <div className="hint"><Icon name="warn" size={12} /> 影响报告是候选分析，不构成上线许可。</div>
    </div>
  );
}
