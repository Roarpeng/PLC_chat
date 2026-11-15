import { useEffect, useRef, useState } from "react";
import { ApiError, processosApi } from "./api";
import {
  importerApi, readBlockFiles, sha256Hex, verdictLabel, verdictTone,
  type BaselineCheckResult, type ClaimKind, type ClaimMapping, type ClaimResult,
  type Fidelity, type ParsedBlock, type ParseResult,
} from "./apiImporter";
import { buildContract } from "./store";
import type { ProjectSummary } from "./types";
import { Icon } from "./views";

/* Import Agent (L) — 真解析流程（替换演示壳）：
   第 0 屏 开工前基线/比对说明（PLAN §4）→ 第 1 屏 上传 TIA「块导出」XML →
   第 2 屏 按保真度分组的结构树 → 第 3 屏 工位/执行器认领映射 → 进入工作台。
   进度 = 真实请求态；PROTECTED 安全块只读禁改；OPAQUE 落 MANAGED_NATIVE_OVERRIDE。
   完成时 contract 仍为 buildContract 占位 —— UI 明示「结构已登记，工艺重建待后续」。 */

export const FIDELITY_ORDER: Fidelity[] = ["EXACT", "PARTIAL", "OPAQUE", "PROTECTED"];

export const FIDELITY_LABELS: Record<Fidelity, string> = {
  EXACT: "精确 · 模式/接口可重建",
  PARTIAL: "部分 · 语义重建不完全",
  OPAQUE: "黑盒 · 仅元数据（MANAGED_NATIVE_OVERRIDE）",
  PROTECTED: "保护 · F/Safety 只读零修改",
};

export const CLAIM_KIND_OPTIONS: { value: ClaimKind; label: string }[] = [
  { value: "em", label: "EM 工艺单元" },
  { value: "cm", label: "执行器 CM" },
  { value: "component", label: "组件 component" },
  { value: "station", label: "工位 station" },
  { value: "ob", label: "OB 主循环" },
  { value: "other", label: "其它（黑盒保留）" },
];

export interface ClaimDraft {
  target_kind: ClaimKind | "";
  station_name: string;
  display_name: string;
  driver_hint: string;
}

/** 按保真度分组（保持 EXACT→PARTIAL→OPAQUE→PROTECTED 展示顺序）。 */
export function groupByFidelity(nodes: ParsedBlock[]): [Fidelity, ParsedBlock[]][] {
  return FIDELITY_ORDER
    .map(f => [f, nodes.filter(n => n.fidelity === f)] as [Fidelity, ParsedBlock[]])
    .filter(([, group]) => group.length > 0);
}

/** 认领草稿预填：AF 命名模式给保守默认（用户可改），其余留空。 */
export function draftFor(node: ParsedBlock): ClaimDraft {
  const name = node.block_name.toUpperCase();
  let target: ClaimKind | "" = "";
  if (name.startsWith("FB_EM_")) target = "em";
  else if (name.startsWith("FB_CM_")) target = "cm";
  else if (node.block_name === "Main" || name.startsWith("OB_MAIN")) target = "ob";
  return { target_kind: target, station_name: "", display_name: node.block_name, driver_hint: "" };
}

/** 组装 claim payload：只提交已选择 target_kind 的行。 */
export function buildClaimPayload(
  parse: ParseResult,
  drafts: Record<string, ClaimDraft>,
  projectId: string,
): { parse_id: string; project_id?: string; mappings: ClaimMapping[] } {
  const mappings: ClaimMapping[] = [];
  for (const node of parse.nodes) {
    if (node.fidelity === "PROTECTED") continue; // 安全块不参与认领
    const d = drafts[node.block_name];
    if (!d || !d.target_kind) continue;
    mappings.push({
      block_name: node.block_name,
      target_kind: d.target_kind,
      station_name: d.station_name.trim() || undefined,
      display_name: d.display_name.trim() || undefined,
      driver_hint: d.driver_hint.trim() || undefined,
    });
  }
  const body: { parse_id: string; project_id?: string; mappings: ClaimMapping[] } = {
    parse_id: parse.parse_id, mappings,
  };
  if (projectId) body.project_id = projectId;
  return body;
}

export function BaselineBanner({ check }: { check: BaselineCheckResult | null }) {
  if (!check) return null;
  const tone = verdictTone(check.verdict);
  return (
    <div className={`pos-imp-banner ${tone}`} data-testid="pos-imp-banner">
      <span className={`fid ${tone === "ok" ? "EXACT" : tone === "err" ? "PROTECTED" : "PARTIAL"}`}>
        {check.verdict}
      </span>
      <div className="pos-imp-banner-body">
        <strong>{verdictLabel(check.verdict)}</strong>
        {check.note && <span>{check.note}</span>}
        {check.block_diff && (check.block_diff.changed.length > 0 || check.block_diff.added_in_upload.length > 0) && (
          <span className="pos-imp-diff">
            块级差异：变更 {check.block_diff.changed.join("、") || "无"} · 新增
            {" "}{check.block_diff.added_in_upload.join("、") || "无"}
          </span>
        )}
      </div>
    </div>
  );
}

export function ImportTreeView({ parse }: { parse: ParseResult }) {
  const groups = groupByFidelity(parse.nodes);
  return (
    <div className="pos-imp-tree">
      {groups.map(([fidelity, group]) => (
        <div className={`pos-imp-group ${fidelity}`} key={fidelity}>
          <div className="pos-imp-group-h">
            <span className={`fid ${fidelity}`}>{fidelity}</span>
            <span className="pos-imp-group-t">{FIDELITY_LABELS[fidelity]}</span>
            <span className="sp" />
            <span className="hint">{group.length} 块</span>
          </div>
          {group.map(n => (
            <details className={`pos-imp-blk ${fidelity}`} key={n.node_id}>
              <summary>
                <span className="mono pos-imp-blk-name">{n.block_name}</span>
                <span className="pos-imp-blk-meta">
                  {n.block_type} · {n.language} · #{n.number || "?"}
                </span>
                {fidelity === "PROTECTED" && <span className="pos-imp-ro">只读</span>}
              </summary>
              <div className="pos-imp-blk-body">
                <div className="hint">{n.note}</div>
                {n.signals === "UNKNOWN" ? (
                  <div className="pos-imp-sig-unknown">信号清单 UNKNOWN · 不猜测结构</div>
                ) : (
                  <div className="pos-imp-sigs">
                    {n.signals.map(s => (
                      <span className="pos-imp-sig" key={s.section + "." + s.name}>
                        <em>{s.section}</em> {s.name}<i>{s.datatype}</i>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      ))}
    </div>
  );
}

function ClaimCell({ node, draft, onChange }: {
  node: ParsedBlock;
  draft: ClaimDraft;
  onChange: (patch: Partial<ClaimDraft>) => void;
}) {
  if (node.fidelity === "PROTECTED")
    return (
      <div className="pos-imp-claim-row protected">
        <span className="mono pos-imp-blk-name">{node.block_name}</span>
        <span className="pos-imp-ro">安全块 · 只读，不可认领</span>
        <select disabled aria-label={`认领 ${node.block_name}`}>
          <option value="">禁止映射</option>
        </select>
      </div>
    );
  return (
    <div className={`pos-imp-claim-row ${node.fidelity === "OPAQUE" ? "opaque" : ""}`}>
      <span className="mono pos-imp-blk-name">{node.block_name}</span>
      <span className={`fid ${node.fidelity}`}>{node.fidelity}</span>
      <select value={draft.target_kind} aria-label={`认领 ${node.block_name}`}
        onChange={e => onChange({ target_kind: e.target.value as ClaimKind | "" })}>
        <option value="">未认领</option>
        {CLAIM_KIND_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <input placeholder="工位名（如 装配站）" value={draft.station_name}
        onChange={e => onChange({ station_name: e.target.value })} aria-label={`${node.block_name} 工位名`} />
      <input placeholder="显示名" value={draft.display_name}
        onChange={e => onChange({ display_name: e.target.value })} aria-label={`${node.block_name} 显示名`} />
      <input placeholder="驱动提示（CM 可选）" value={draft.driver_hint}
        onChange={e => onChange({ driver_hint: e.target.value })} aria-label={`${node.block_name} 驱动提示`} />
      {node.fidelity === "OPAQUE" && <span className="hint">认领后落 MANAGED_NATIVE_OVERRIDE 黑盒</span>}
    </div>
  );
}

export function ClaimTable({ parse, drafts, onDraft }: {
  parse: ParseResult;
  drafts: Record<string, ClaimDraft>;
  onDraft: (blockName: string, patch: Partial<ClaimDraft>) => void;
}) {
  return (
    <div className="pos-imp-claim">
      {parse.nodes.map(n => (
        <ClaimCell key={n.node_id} node={n} draft={drafts[n.block_name] ?? draftFor(n)}
          onChange={patch => onDraft(n.block_name, patch)} />
      ))}
    </div>
  );
}

const STEPS = ["基线比对", "上传解析", "结构树", "认领映射"];

export function ImportView({ onCancel, onDone }: { onCancel: () => void; onDone: (name: string, contractId: string) => void }) {
  const [step, setStep] = useState(0);
  const [projectName, setProjectName] = useState("导入项目");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [check, setCheck] = useState<BaselineCheckResult | null>(null);
  const [checkBusy, setCheckBusy] = useState(false);
  const [blocks, setBlocks] = useState<{ name: string; xml_text: string }[]>([]);
  const [parse, setParse] = useState<ParseResult | null>(null);
  const [parseBusy, setParseBusy] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, ClaimDraft>>({});
  const [claim, setClaim] = useState<ClaimResult | null>(null);
  const [claimBusy, setClaimBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    processosApi.projects().then(r => setProjects(r.projects)).catch(() => setProjects([]));
  }, []);

  const runBaselineCheck = async (pid: string, hashes?: { block_name: string; sha256: string }[]) => {
    if (!pid) { setCheck(null); return; }
    setCheckBusy(true);
    try {
      setCheck(await importerApi.baselineCheck(hashes ? { project_id: pid, block_hashes: hashes } : { project_id: pid }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setCheckBusy(false); }
  };

  const selectProject = (pid: string) => {
    setProjectId(pid); setErr("");
    void runBaselineCheck(pid);
  };

  const upload = async (files: File[]) => {
    setErr(""); setParseBusy(true); setParse(null); setClaim(null);
    try {
      const { projectName: manifestName, blocks: parsed } = await readBlockFiles(files);
      const name = manifestName || projectName;
      if (manifestName) setProjectName(manifestName);
      setBlocks(parsed);
      const result = await importerApi.parse({ project_name: name, blocks: parsed });
      setParse(result);
      setDrafts(Object.fromEntries(result.nodes.map(n => [n.block_name, draftFor(n)])));
      if (projectId) {  // 已选项目：带逐块真实哈希刷新开工前比对（块级三方差异）
        const hashes = await Promise.all(parsed.map(async b => ({
          block_name: b.name, sha256: await sha256Hex(b.xml_text) })));
        void runBaselineCheck(projectId, hashes);
      }
      setStep(2);
    } catch (e) {
      setErr(e instanceof ApiError ? `[${e.code ?? e.status}] ${e.message}` : e instanceof Error ? e.message : String(e));
    } finally { setParseBusy(false); }
  };

  const submitClaim = async () => {
    if (!parse) return;
    setClaimBusy(true); setErr("");
    try {
      const body = buildClaimPayload(parse, drafts, projectId);
      setClaim(await importerApi.claim(body));
    } catch (e) {
      setErr(e instanceof ApiError ? `[${e.code ?? e.status}] ${e.message}` : e instanceof Error ? e.message : String(e));
    } finally { setClaimBusy(false); }
  };

  const finish = async () => {
    setBusy(true); setErr("");
    try {
      const contractId = "PRJ_IMP_" + Math.random().toString(36).slice(2, 7).toUpperCase();
      await processosApi.createProject(buildContract(contractId, projectName));
      onDone(projectName || (parse?.project_name ?? "导入项目"), contractId);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };

  const reset = () => {
    setBlocks([]); setParse(null); setClaim(null); setDrafts({}); setErr(""); setStep(1);
  };

  return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onCancel}><Icon name="back" /> 返回</button>
        <h2>导入旧项目</h2>
        <div className="sp" />
        <div className="steps-rail">
          {STEPS.map((s, i) => (
            <div key={s} className={`sr ${i === step ? "on" : i < step ? "done" : ""}`}>
              <span className="n">{i < step ? <Icon name="check" size={12} /> : i + 1}</span>{s}
            </div>
          ))}
        </div>
      </div>

      <div className="flow-body">
        {/* 第 0 屏：开工前基线/比对说明（PLAN §4 第一次比对 B2↔B3） */}
        {step === 0 && (
          <>
            <div className="panel">
              <div className="panel-h">开工前比对 · 三份基线两次比对（§4）</div>
              <div className="panel-b">
                <div className="field">
                  <label>导入工程名称</label>
                  <input value={projectName} onChange={e => setProjectName(e.target.value)} aria-label="导入工程名称" />
                </div>
                <div className="field">
                  <label>关联已有项目（可选 — 用于基线比对）</label>
                  <select value={projectId} onChange={e => selectProject(e.target.value)} aria-label="关联已有项目">
                    <option value="">全新导入（不关联）</option>
                    {projects.map(p => <option key={p.project_id} value={p.project_id}>{p.name} · {p.project_id}</option>)}
                  </select>
                </div>
                {checkBusy && <div className="hint">比对中…</div>}
                {projectId
                  ? <BaselineBanner check={check} />
                  : (
                    <div className="pos-imp-banner warn" data-testid="pos-imp-fresh">
                      <span className="fid PARTIAL">无基线</span>
                      <div className="pos-imp-banner-body">
                        <strong>全新导入 · 无历史基线</strong>
                        <span>将登记首份 B2（原生基线）后再可比对；导入解析本身只读，不改任何原件。</span>
                      </div>
                    </div>
                  )}
                <div className="note" style={{ marginTop: 12 }}>
                  导入前先回答「现场 PLC 与工程副本是否一致」：选择已有项目立即执行 B2↔B3 比对；
                  漂移（FROZEN_DRIFT）时冻结变更，只读采集。B3 不能仅凭 Build ID 自报。
                </div>
                {err && <div className="note" style={{ marginTop: 12, color: "var(--err)" }}>{err}</div>}
              </div>
            </div>
            <div className="flow-foot">
              <button className="btn ghost" onClick={onCancel}>取消</button>
              <button className="btn stamp" onClick={() => setStep(1)}>下一步 · 上传块导出 <Icon name="arrow" /></button>
            </div>
          </>
        )}

        {/* 第 1 屏：上传 TIA 块导出（多文件 .xml + 可选 manifest.json），真实请求态 */}
        {step === 1 && (
          <>
            <div className={`dropzone ${over ? "over" : ""}`} onClick={() => inputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={e => { e.preventDefault(); setOver(false); const fs = Array.from(e.dataTransfer.files); if (fs.length) void upload(fs); }}>
              <div className="dz-ic">⌗</div>
              <h3>拖入 TIA「块导出」文件</h3>
              <p>多选 plc/&lt;PLC&gt;/blocks/*.xml · 可选 manifest.json（读取工程名）· 或点击选择</p>
              <input ref={inputRef} type="file" accept=".xml,.json" multiple style={{ display: "none" }}
                onChange={e => { const fs = Array.from(e.target.files ?? []); if (fs.length) void upload(fs); }} />
            </div>
            {parseBusy && (
              <div className="panel">
                <div className="panel-h">解析中 · {blocks.length || "?"} 个块</div>
                <div className="panel-b">
                  <div className="hint">只读提取块元数据 / 接口 / 调用信号并标注保真等级 —— 原件 SHA256 不变，真实请求进行中。</div>
                </div>
              </div>
            )}
            {err && <div className="note" style={{ color: "var(--err)" }}>{err}</div>}
            <div className="flow-foot">
              <button className="btn ghost" onClick={() => setStep(0)}>上一步</button>
            </div>
          </>
        )}

        {/* 第 2 屏：按保真度分组的结构树 */}
        {step === 2 && parse && (
          <>
            <div className="panel">
              <div className="panel-h">
                解析结果 · {parse.project_name || projectName}
                <span className="sp" />
                <span className="hint">
                  {parse.nodes.length} 块 · EXACT {parse.stats.EXACT ?? 0} / PARTIAL {parse.stats.PARTIAL ?? 0} / OPAQUE {parse.stats.OPAQUE ?? 0} / PROTECTED {parse.stats.PROTECTED ?? 0} · 原件只读
                </span>
              </div>
              <div className="panel-b">
                {projectId && <div style={{ marginBottom: 14 }}><BaselineBanner check={check} /></div>}
                <ImportTreeView parse={parse} />
                <div className="note warn" style={{ marginTop: 12 }}>
                  PARTIAL/OPAQUE 不声称行为等价；OPAQUE 认领后以 MANAGED_NATIVE_OVERRIDE 黑盒隔离；PROTECTED 零修改。
                </div>
              </div>
            </div>
            <div className="flow-foot">
              <button className="btn ghost" onClick={reset}>重新选择</button>
              <button className="btn ghost" onClick={() => setStep(0)}>上一步</button>
              <button className="btn stamp" onClick={() => setStep(3)}>下一步 · 认领映射 <Icon name="arrow" /></button>
            </div>
          </>
        )}

        {/* 第 3 屏：认领映射（PROTECTED 行禁用） */}
        {step === 3 && parse && (
          <>
            <div className="panel">
              <div className="panel-h">认领映射 · 工位 / 执行器(CM) / EM / OB</div>
              <div className="panel-b">
                <ClaimTable parse={parse} drafts={drafts}
                  onDraft={(name, patch) => setDrafts(prev => ({
                    ...prev,
                    [name]: { ...(prev[name] ?? draftFor(parse.nodes.find(n => n.block_name === name)!)), ...patch },
                  }))} />
                <div className="hint" style={{ marginTop: 12 }}>
                  同批同工位名的 CM 会挂到同工位的 EM 下；组件挂到工位；工位 maps_to EM（一个工位可映射多个 EM）。
                </div>
                {err && <div className="note" style={{ marginTop: 12, color: "var(--err)" }}>{err}</div>}
              </div>
            </div>
            <div className="flow-foot">
              <button className="btn ghost" onClick={() => setStep(2)}>上一步</button>
              <button className="btn primary" onClick={submitClaim} disabled={claimBusy || !!claim}>
                {claimBusy ? "登记中…" : "提交认领（登记到对象注册表）"}
              </button>
            </div>

            {claim && (
              <div className="panel">
                <div className="panel-h">认领结果 · {claim.claim_id}</div>
                <div className="panel-b">
                  <table className="ctable" data-ui>
                    <thead><tr><th>来源块</th><th>登记为</th><th>object_id</th></tr></thead>
                    <tbody>
                      {claim.objects.map(o => (
                        <tr key={o.object_id}><td className="mono">{o.block_name}</td><td>{o.kind}</td><td className="mono">{o.object_id}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  {claim.unmapped.length > 0 && (
                    <div className="hint" style={{ marginTop: 10 }}>
                      未认领：{claim.unmapped.map(u => u.block_name).join("、")}（保持只读参考，不落可编辑结构）
                    </div>
                  )}
                  <div className="note warn" style={{ marginTop: 12 }}>
                    结构已登记，工艺重建待后续 —— 进入工作台的契约仍是占位（buildContract），
                    工位/执行器映射已写入对象注册表，语义重建在后续迭代完成。
                  </div>
                </div>
                <div className="flow-foot">
                  <button className="btn stamp" onClick={finish} disabled={busy}>
                    {busy ? "建立中…" : "建立项目并进入对话"} <Icon name="arrow" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
