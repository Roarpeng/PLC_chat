import { useEffect, useState } from "react";
import {
  diagApi,
  type CompileScopeResult,
  type DiagInput,
  type DiagMapping,
  type DiagUnmapped,
  type LocateResponse,
} from "./apiDiag";
import type { DeliveryJob } from "./types";
import { Icon } from "./views";

/* §1 L-loop 修错闭环面板：编译诊断 → SourceMap → 对象定位；§5.2 修复提案；
   §5/FastWriteback 编译范围意向。三个区块都只呈现事实：映射不出 = UNKNOWN
   （不猜），修复只作为候选（不自动应用），范围只是建议（当前链全量）。 */

/** 跳转现场追溯的轻量事件：宿主工作台（Workbench/Traceability）可监听并聚焦
 *  对象；本面板不依赖宿主接线——完整映射信息始终就地渲染，跳转仅为增强。 */
export const FOCUS_OBJECT_EVENT = "processos:focus-object";

/** PLAN §5.2 七类禁改——面板恒展示，明示不存在自动修复路径。 */
export const FORBIDDEN_SEVEN: { code: string; label: string }[] = [
  { code: "DELETE_INTERLOCK", label: "删除互锁" },
  { code: "BYPASS_SAFETY_PERMIT", label: "绕过安全许可" },
  { code: "INCREASE_TIMEOUT_TO_CLEAR_FAULT", label: "加大超时消除故障" },
  { code: "CHANGE_ACTION_PRIORITY", label: "改变动作优先级" },
  { code: "IGNORE_FAULT_BITS", label: "忽略/屏蔽故障位" },
  { code: "SILENT_DB_RESET", label: "静默重置 DB" },
  { code: "MODIFY_F_SAFETY", label: "修改 F-Safety 逻辑" },
];

function toLine(s: string): number | null {
  return /^\d+$/.test(s) ? parseInt(s, 10) : null;
}

/** 粘贴诊断解析：`块 | 行 | 消息`、`块 | 消息`、`块:行: 消息`；
 *  其余整行当消息（无块名 → locate 如实回 UNKNOWN，不猜）。 */
export function parseDiagLines(text: string): DiagInput[] {
  const out: DiagInput[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (line.includes("|")) {
      const parts = line.split("|").map(p => p.trim());
      if (parts.length >= 3) {
        out.push({ block: parts[0], line: toLine(parts[1]), message: parts.slice(2).join(" | ") });
        continue;
      }
      if (parts.length === 2 && parts[0]) {
        out.push({ block: parts[0], line: null, message: parts[1] });
        continue;
      }
    }
    const m = line.match(/^(\S+?):(\d+):\s*(.+)$/);
    if (m) { out.push({ block: m[1], line: parseInt(m[2], 10), message: m[3] }); continue; }
    out.push({ block: "", line: null, message: line });
  }
  return out;
}

function rowsFromJob(job: DeliveryJob | null): DiagInput[] {
  if (!job || !Array.isArray(job.diagnostics)) return [];
  /* job 诊断若带 block/line（原生链未来形态）直接采用；否则块名为空 →
     locate 如实回 UNKNOWN（不可映射不猜），绝不从消息文本里猜块名。 */
  return job.diagnostics.map(d => {
    const ext = d as { block?: string; line?: number };
    return {
      block: String(ext.block ?? ""),
      line: ext.line ?? null,
      message: `${d.code || d.stage}: ${d.message}`,
    };
  });
}

export function jumpToObject(objectId: string): void {
  try {
    window.dispatchEvent(new CustomEvent(FOCUS_OBJECT_EVENT, { detail: { objectId } }));
  } catch { /* no window (tests): mapping is already rendered inline */ }
}

/* ---------- 命中：对象名 / 步骤 / 源码区间（+跳转为增强） ---------- */

export function DiagMappingView({ m }: { m: DiagMapping }) {
  const ambiguous = m.located === "block_ambiguous";
  return (
    <div className={`pos-diag-map ${ambiguous ? "amb" : ""}`}>
      <div className="pos-diag-map-main">
        {ambiguous && <span className="pos-diag-badge unknown">UNKNOWN</span>}
        <span className="pos-diag-obj">{m.display_name}</span>
        {m.behavior_step_id && <span className="pos-diag-step mono">{m.behavior_step_id}</span>}
        <span className="pos-diag-loc mono">{m.scl_location}</span>
        {!ambiguous && m.semantic_object_id && (
          <button className="pos-diag-jump" onClick={() => jumpToObject(m.semantic_object_id as string)}
            title={`通过 window 事件 ${FOCUS_OBJECT_EVENT} 通知宿主聚焦；完整映射已在上方展示`}>
            跳转现场追溯<Icon name="arrow" size={11} />
          </button>
        )}
      </div>
      <div className="pos-diag-map-meta">
        build {m.release_build_id} · {m.block_kind}
        {m.instance_db ? ` · DB ${m.instance_db}` : ""} · {m.ownership}
        {m.source_map_id ? ` · ${m.source_map_id}` : ""}
      </div>
      {m.candidates && m.candidates.length > 0 && (
        <div className="pos-diag-cands">
          <div className="pos-diag-cands-note">块级歧义：该块承载多个语义对象且未给可命中的行号——不猜归属，候选如下（补行号可精确定位）：</div>
          {m.candidates.map(c => (
            <div key={c.source_map_id} className="pos-diag-cand">
              <span className="pos-diag-obj">{c.display_name}</span>
              {c.behavior_step_id && <span className="mono">{c.behavior_step_id}</span>}
              <span className="mono">{c.scl_location}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- 未命中：UNKNOWN 徽章 + UNMAPPED_NATIVE_CODE 红标 ---------- */

export function DiagUnmappedView({ u }: { u: DiagUnmapped }) {
  return (
    <div className="pos-diag-unmapped">
      <span className="pos-diag-badge unknown">UNKNOWN</span>
      <span className="pos-diag-code err mono">{u.error_code}</span>
      <span className="pos-diag-reason">{u.reason}</span>
    </div>
  );
}

/* ---------- 修复提案：ALLOWED 绿 / FORBIDDEN 红 + 七类明示 ---------- */

export function ProposalsView({ proposals }: { proposals: LocateResponse["proposals"] }) {
  if (!proposals) return <div className="hint">未生成候选修复（还没有定位过诊断）。</div>;
  const allowed: typeof proposals.proposals = proposals.proposals;
  const forbidden: typeof proposals.forbidden_seen = proposals.forbidden_seen;
  return (
    <div className="pos-diag-props" data-testid="pos-diag-props">
      {allowed.length === 0 && forbidden.length === 0 &&
        <div className="hint">无候选修复：诊断均不在保守白名单内（只登记不提议）。</div>}
      {allowed.map((p, i) => (
        <div key={"a" + i} className="pos-diag-prop ok">
          <span className="pos-diag-badge ok">ALLOWED · {p.fix.category}</span>
          <span className="pos-diag-action">{p.fix.action}</span>
          <span className="pos-diag-review">must_return_to_review · 以候选变更回流审批（不自动应用）</span>
        </div>
      ))}
      {forbidden.map((f, i) => (
        <div key={"f" + i} className="pos-diag-prop err">
          <span className="pos-diag-badge err">FORBIDDEN{f.category ? " · " + f.category : " · 未归类"}</span>
          <span className="pos-diag-reason">{f.reason}</span>
        </div>
      ))}
      <div className="pos-diag-note">auto_applied 恒空：一切修复以候选变更回到人工审查/验证链路（PLAN §5.2）。</div>
      <div className="pos-diag-forbidden7">
        <div className="pos-diag-f7-title">七类禁改（永不自动修复）</div>
        {FORBIDDEN_SEVEN.map(f => <span key={f.code} className="pos-diag-f7">{f.label}</span>)}
      </div>
    </div>
  );
}

/* ---------- 编译范围：建议范围 + 诚实注脚 ---------- */

export function ScopeView({ scope }: { scope: CompileScopeResult }) {
  return (
    <div className="pos-diag-scope" data-mode={scope.mode} data-testid="pos-diag-scope">
      <div className="pos-diag-scope-head">
        <span className={`pos-diag-badge ${scope.mode === "incremental" ? "ok" : "err"}`}>
          {scope.mode === "incremental" ? "建议增量 · incremental_blocks" : "全量 · full"}
        </span>
        <span className="pos-diag-reason">{scope.reason}</span>
      </div>
      {scope.affected_blocks.length > 0 && (
        <div className="pos-diag-blocks">
          {scope.affected_blocks.map(b => <span key={b} className="pos-diag-block mono">{b}</span>)}
        </div>
      )}
      <div className="pos-diag-note warn">{scope.note}</div>
    </div>
  );
}

/* ---------- 主面板 ---------- */

export function DiagnosticsPanel({ projectId, job, pendingOps }: {
  projectId: string; job: DeliveryJob | null; pendingOps?: unknown[];
}) {
  const [rows, setRows] = useState<DiagInput[]>(() => rowsFromJob(job));
  const [paste, setPaste] = useState("");
  const [results, setResults] = useState<Record<number, DiagMapping | DiagUnmapped>>({});
  const [proposals, setProposals] = useState<LocateResponse["proposals"]>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [scopeMode, setScopeMode] = useState<"full" | "incremental">("full");
  const [scope, setScope] = useState<CompileScopeResult | null>(null);

  useEffect(() => { setRows(rowsFromJob(job)); setResults({}); }, [job?.id]);

  const applyLocate = (r: LocateResponse) => {
    const next: Record<number, DiagMapping | DiagUnmapped> = {};
    for (const m of r.mappings) next[m.index] = m;
    for (const u of r.unmapped) next[u.index] = u;
    setResults(prev => ({ ...prev, ...next }));
    setProposals(r.proposals);
  };

  const locateAll = async () => {
    if (!projectId || rows.length === 0 || busy) return;
    setBusy(true); setErr("");
    try { applyLocate(await diagApi.locate(projectId, rows)); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const locateOne = async (i: number) => {
    if (!projectId || busy) return;
    setBusy(true); setErr("");
    try { applyLocate(await diagApi.locate(projectId, [rows[i]])); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const appendPasted = () => {
    const parsed = parseDiagLines(paste);
    if (parsed.length === 0) return;
    setRows(prev => [...prev, ...parsed]);
    setPaste("");
  };
  const runScope = async () => {
    if (!projectId || busy) return;
    setBusy(true); setErr("");
    try { setScope(await diagApi.compileScope(projectId, pendingOps ?? [])); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="pos-diag" data-testid="pos-diag">
      {err && <div className="note" style={{ color: "var(--err)", marginBottom: 8 }}>{err}</div>}

      <div className="pos-diag-sec">
        <div className="pos-diag-sec-h">编译诊断 → 对象定位（L 环）</div>
        <div className="pos-diag-hint">每行一条：<span className="mono">块 | 行 | 消息</span> 或 <span className="mono">块:行: 消息</span>。无块名/未知块将如实标 UNKNOWN（UNMAPPED_NATIVE_CODE，不可映射不猜）。</div>
        {rows.length === 0 && <div className="hint">暂无诊断：交付 Job 产生诊断后自动带入，或在下方粘贴。</div>}
        <div className="pos-diag-rows">
          {rows.map((d, i) => (
            <div key={i} className="pos-diag-rowwrap">
              <div className="pos-diag-row">
                <span className="pos-diag-rb mono">{d.block || "—"}</span>
                <span className="pos-diag-rl mono">{d.line ?? "—"}</span>
                <span className="pos-diag-rm">{d.message}</span>
                <button className="btn sm ghost" disabled={busy || !projectId} onClick={() => locateOne(i)}>定位</button>
              </div>
              {results[i] && ("error_code" in results[i]
                ? <DiagUnmappedView u={results[i] as DiagUnmapped} />
                : <DiagMappingView m={results[i] as DiagMapping} />)}
            </div>
          ))}
        </div>
        <div className="pos-diag-paste">
          <textarea className="pos-diag-ta" value={paste} placeholder={"粘贴原生编译诊断，例如\nFB_EM_CLAMP_SEQ | 40 | type mismatch at input\nFB_NATIVE_HANDWRITTEN | 12 | name conflict"}
            onChange={e => setPaste(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); appendPasted(); } }} />
          <div className="ctrlrow">
            <button className="btn sm ghost" disabled={!paste.trim()} onClick={appendPasted}>解析追加</button>
            <button className="btn sm" disabled={busy || rows.length === 0 || !projectId} onClick={locateAll}>定位全部</button>
            {rows.length > 0 && <button className="btn sm ghost" disabled={busy} onClick={() => { setRows([]); setResults({}); }}>清空</button>}
          </div>
        </div>
      </div>

      <div className="pos-diag-sec">
        <div className="pos-diag-sec-h">修复提案（候选 · 不自动应用）</div>
        <ProposalsView proposals={proposals} />
      </div>

      <div className="pos-diag-sec">
        <div className="pos-diag-sec-h">编译范围（交付前意向）</div>
        <div className="pos-diag-scopepick">
          <label className={scopeMode === "full" ? "on" : ""}>
            <input type="radio" name="pos-diag-scope" checked={scopeMode === "full"} onChange={() => setScopeMode("full")} />
            全量（默认）
          </label>
          <label className={scopeMode === "incremental" ? "on" : ""}>
            <input type="radio" name="pos-diag-scope" checked={scopeMode === "incremental"} onChange={() => setScopeMode("incremental")} />
            建议增量
          </label>
          <button className="btn sm ghost" disabled={busy || !projectId} onClick={runScope}>查询受影响块</button>
        </div>
        <div className="pos-diag-hint">选择仅作范围意向记录：当前交付链总是全量编译，增量范围由 Worker 侧 FastWriteback 分级编译承接（触及接口/IO/不变量时增量本身就不安全）。</div>
        {scope && <ScopeView scope={scope} />}
      </div>
    </div>
  );
}
