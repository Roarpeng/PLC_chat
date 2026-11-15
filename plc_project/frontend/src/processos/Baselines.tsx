import { useCallback, useEffect, useState } from "react";
import { ApiError, processosApi } from "./api";
import { roleDeniedText } from "./actor";
import { Badge, FieldTop, useFlash, verdictTone, type FieldView } from "./fieldui";
import type { Baseline, BaselineCompare, FieldmodReport, ProjectSummary } from "./types";
import { Icon } from "./views";

/* FC-03 / PLAN §4 — three baselines, two comparisons. B3 may not be
   self-reported from a build id alone; without a PLC connection it must stay
   UNVERIFIED_ONLINE (yellow). */
const EMPTY_B3 = {
  deployed_build_id: "", device_id: "", plc_checksum: "", operator: "",
  commissioned_at: "", verification: "FIELD_VERIFIED" as "FIELD_VERIFIED" | "SELF_REPORTED",
};
const EMPTY_B2 = { build_id: "", archive_sha256: "", manifest_json: "{}" };
const EMPTY_BLOCK = { block_name: "", content_sha256: "" };

export function Baselines({ onBack, onNav }: { onBack: () => void; onNav: (v: FieldView) => void }) {
  const { flash, toastEl } = useFlash();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [pid, setPid] = useState("");
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [cmp, setCmp] = useState<BaselineCompare | null>(null);
  const [b2, setB2] = useState({ ...EMPTY_B2 });
  const [b3, setB3] = useState({ ...EMPTY_B3 });
  const [blocks, setBlocks] = useState<{ block_name: string; content_sha256: string }[]>([{ ...EMPTY_BLOCK }]);
  const [fieldmod, setFieldmod] = useState<FieldmodReport | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    processosApi.projects().then(r => {
      setProjects(r.projects);
      setPid(p => p || r.projects[0]?.project_id || "");
    }).catch(() => setProjects([]));
  }, []);

  const refresh = useCallback(async (id: string) => {
    if (!id) return;
    try { setBaselines((await processosApi.listBaselines(id)).baselines); }
    catch (e) { const d = roleDeniedText(e); if (d) flash(d, true); else setBaselines([]); }
  }, [flash]);

  useEffect(() => { refresh(pid); setCmp(null); }, [pid, refresh]);

  const guard = async (fn: () => Promise<void>, okMsg?: string) => {
    setBusy(true);
    try { await fn(); if (okMsg) flash(okMsg); await refresh(pid); }
    catch (e) {
      const denied = roleDeniedText(e);
      flash(denied ?? (e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)), true);
    } finally { setBusy(false); }
  };

  const recordB1 = () => guard(async () => {
    // spec_hash/revision/profile come from the server's own view of the contract
    const p = await processosApi.getProject(pid);
    await processosApi.recordB1(pid, { spec_hash: p.spec_hash, revision: p.revision, profile_id: p.profile_id });
  }, "B1 已记录（FROZEN）");

  const recordB2 = () => {
    if (!b2.build_id.trim() || !b2.archive_sha256.trim()) { flash("B2 需要 build_id 与 archive_sha256（真实归档哈希）", true); return; }
    let manifest: Record<string, string>;
    try { manifest = JSON.parse(b2.manifest_json || "{}") as Record<string, string>; }
    catch { flash("block_manifest 不是合法 JSON", true); return; }
    guard(async () => {
      await processosApi.recordB2(pid, {
        build_id: b2.build_id.trim(), archive_sha256: b2.archive_sha256.trim(), block_manifest: manifest,
      });
      setB2({ ...EMPTY_B2 });
    }, "B2 已记录");
  };

  const recordB3 = () => {
    if (!b3.deployed_build_id || !b3.device_id || !b3.plc_checksum) {
      flash("B3 需要 deployed_build_id / device_id / plc_checksum", true); return;
    }
    guard(async () => {
      await processosApi.recordB3(pid, { ...b3, plc_checksum: b3.plc_checksum.trim() });
      setB3({ ...EMPTY_B3 });
    }, "B3 已记录");
  };

  const compare = () => guard(async () => { setCmp(await processosApi.compareBaselines(pid)); });

  const gate = () => guard(async () => {
    try {
      const g = await processosApi.gateChange(pid);
      flash(g.ok ? `变更门禁：允许（${g.verdict}）` : `变更门禁阻断：${g.verdict}`, !g.ok);
    } catch (e) {
      // 409 SafetyError: {error, code=UNKNOWN_PLC_STATE|DRIFT_DETECTED, details}
      if (e instanceof ApiError && e.code) flash(`变更门禁阻断（${e.code}）：${e.message}`, true);
      else throw e;
    }
  });

  const prefillBlocks = () => guard(async () => {
    const sm = await processosApi.projectSourcemap(pid);
    const names = Array.from(new Set(sm.source_map.map(e => e.block_name).filter(Boolean)));
    if (!names.length) { flash("该项目尚无 SourceMap 块清单（先登记构建）", true); return; }
    // 块名预填；sha256 须由现场工程师从设备/归档如实抄录，不由前端编造
    setBlocks(names.map(n => ({ block_name: n, content_sha256: "" })));
  }, "已按 SourceMap 预填块名（sha256 请如实抄录）");

  const reportFieldmod = () => {
    const rows = blocks.filter(b => b.block_name.trim() && b.content_sha256.trim());
    if (!rows.length) { flash("至少一行完整的 block_name + content_sha256", true); return; }
    guard(async () => {
      setFieldmod(await processosApi.reportFieldModification(pid, {
        field_state: { blocks: rows.map(r => ({ block_name: r.block_name.trim(), content_sha256: r.content_sha256.trim() })) },
        source: "MANUAL_UPLOAD",
      }));
    });
  };

  return (
    <div className="flow">
      <FieldTop view="baselines" onNav={onNav} onBack={onBack} title="基线比对"
        hint="B1 设计 / B2 原生 / B3 现场 · 开工前先比 B2↔B3" />
      <div className="flow-body fc-body">
        <div className="fc-banner warn">
          <Icon name="warn" size={14} /> B3 不能仅凭 Build ID 自报：无法在线验证时保持 UNVERIFIED_ONLINE，且漂移时冻结变更（DRIFT_DETECTED → fail-closed）。
        </div>

        <div className="field" style={{ maxWidth: 420 }}>
          <label>项目</label>
          <select value={pid} onChange={e => setPid(e.target.value)}>
            <option value="">（选择项目）</option>
            {projects.map(p => <option key={p.project_id} value={p.project_id}>{p.project_id} · {p.name}</option>)}
          </select>
        </div>

        <section className="panel">
          <div className="panel-h">基线记录<span className="sp" />
            <button className="btn ghost sm" onClick={recordB1} disabled={busy || !pid}>记录 B1（冻结当前设计）</button>
          </div>
          <div className="panel-b">
            {baselines.length === 0 && <div className="hint">暂无基线记录。</div>}
            {baselines.length > 0 && (
              <table className="ctable">
                <thead><tr><th>基线</th><th>状态</th><th>标识 / 哈希</th><th>设备</th><th>验证方式</th><th>时间</th></tr></thead>
                <tbody>{baselines.map(b => (
                  <tr key={b.baseline_id}>
                    <td><Badge tone="ink">{b.kind}</Badge> <span className="mono hint">{b.baseline_id}</span></td>
                    <td><Badge tone={b.status === "UNVERIFIED_ONLINE" ? "warn" : b.status === "FROZEN" ? "ink" : "ok"}>{b.status}</Badge></td>
                    <td className="mono">{b.build_id || b.deployed_build_id || `rev ${b.revision ?? "-"}`}
                      <div className="hint mono">{String(b.archive_sha256 || b.spec_hash || b.plc_checksum || "").slice(0, 26)}</div></td>
                    <td>{b.device_id || "-"}</td>
                    <td>{b.verification ? <Badge tone={b.verification === "FIELD_VERIFIED" ? "ok" : "warn"}>{b.verification}</Badge> : "-"}</td>
                    <td className="hint">{b.created_at}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        </section>

        <div className="fc-grid">
          <section className="panel fc-card">
            <div className="panel-h">记录 B2（原生归档基线）</div>
            <div className="panel-b">
              <div className="field"><label>build_id（归档构建）</label>
                <input value={b2.build_id} onChange={e => setB2({ ...b2, build_id: e.target.value })} placeholder="build_219" /></div>
              <div className="field"><label>archive_sha256（归档文件真实哈希）</label>
                <input className="mono" value={b2.archive_sha256} onChange={e => setB2({ ...b2, archive_sha256: e.target.value })} placeholder="64 位十六进制" /></div>
              <div className="field"><label>block_manifest JSON（可选 {`{块名: sha256}`}）</label>
                <textarea className="tl-json mono" rows={3} value={b2.manifest_json}
                  onChange={e => setB2({ ...b2, manifest_json: e.target.value })} /></div>
              <div className="ctrlrow"><button className="btn stamp sm" onClick={recordB2} disabled={busy || !pid}>记录 B2</button></div>
            </div>
          </section>

          <section className="panel fc-card">
            <div className="panel-h">记录 B3（现场部署基线）</div>
            <div className="panel-b">
              <div className="field"><label>deployed_build_id</label>
                <input value={b3.deployed_build_id} onChange={e => setB3({ ...b3, deployed_build_id: e.target.value })} placeholder="build_219" /></div>
              <div className="field"><label>device_id</label>
                <input value={b3.device_id} onChange={e => setB3({ ...b3, device_id: e.target.value })} /></div>
              <div className="field"><label>plc_checksum（在线比较校验和，须与 B2 archive_sha256 一致）</label>
                <input className="mono" value={b3.plc_checksum} onChange={e => setB3({ ...b3, plc_checksum: e.target.value })} /></div>
              <div className="field"><label>operator（现场操作工程师）</label>
                <input value={b3.operator} onChange={e => setB3({ ...b3, operator: e.target.value })} /></div>
              <div className="field"><label>commissioned_at（验收时间）</label>
                <input type="datetime-local" value={b3.commissioned_at} onChange={e => setB3({ ...b3, commissioned_at: e.target.value })} /></div>
              <div className="field"><label>verification（验证方式）</label>
                <select value={b3.verification} onChange={e => setB3({ ...b3, verification: e.target.value as typeof b3.verification })}>
                  <option value="FIELD_VERIFIED">FIELD_VERIFIED · 现场验证</option>
                  <option value="SELF_REPORTED">SELF_REPORTED · 自报（将标记 UNVERIFIED_ONLINE）</option>
                </select></div>
              <div className="ctrlrow">
                <button className="btn stamp" onClick={recordB3} disabled={busy || !pid}>记录 B3</button>
                <button className="btn sm" onClick={compare} disabled={busy || !pid}>运行 B2 ↔ B3 比对</button>
                <button className="btn ghost sm" onClick={gate} disabled={busy || !pid}>变更门禁检查</button>
              </div>
            </div>
          </section>
        </div>

        <section className="panel">
          <div className="panel-h">比对结果</div>
          <div className="panel-b">
            {!cmp && <div className="hint">运行比对后显示 verdict 与差异；FROZEN_DRIFT 表示现场与工程漂移，须冻结变更并从现场只读采集。</div>}
            {cmp && <>
              <div className="ip-verdict">
                <Badge tone={verdictTone(cmp.verdict)}>{cmp.verdict}</Badge>
                <span className="mono hint">b2_vs_b3: {cmp.b2_vs_b3}</span>
                <span className="hint">{cmp.verdict === "OK_TO_PROCEED" ? "基线一致，可继续变更流程" : cmp.verdict === "FROZEN_DRIFT" ? "现场漂移：停止修改，走只读采集与三方差异" : "现场未在线验证：不得自动宣称可安全下载"}</span>
              </div>
              <div className="chain-meta mono">
                B1 {cmp.latest_b1?.baseline_id || "UNKNOWN"} · B2 {cmp.latest_b2?.baseline_id || "UNKNOWN"} · B3 {cmp.latest_b3?.baseline_id || "UNKNOWN"}
              </div>
              <div className="sidehead">差异（{cmp.differences.length}）</div>
              {cmp.differences.length === 0 && <div className="hint">无差异。</div>}
              {cmp.differences.map((d, i) => (
                <div className="fc-diff" key={i}>
                  <Badge tone={cmp.verdict === "FROZEN_DRIFT" ? "err" : "warn"}>{d.kind}</Badge>
                  <span>{d.detail}</span>
                </div>
              ))}
            </>}
          </div>
        </section>

        <section className="panel">
          <div className="panel-h">上报现场 TIA 修改（FC-17 · 只读回收）<span className="sp" />
            <button className="btn ghost sm" onClick={prefillBlocks} disabled={busy || !pid}>按 SourceMap 预填块名</button>
          </div>
          <div className="panel-b">
            <div className="tl-tests">
              {blocks.map((b, i) => (
                <div className="tl-testrow" key={i}>
                  <input placeholder="block_name，如 FB_ClampSequence" value={b.block_name}
                    onChange={e => setBlocks(blocks.map((r, j) => j === i ? { ...r, block_name: e.target.value } : r))} />
                  <input className="mono" placeholder="content_sha256（64 位十六进制）" value={b.content_sha256}
                    onChange={e => setBlocks(blocks.map((r, j) => j === i ? { ...r, content_sha256: e.target.value } : r))} />
                  <button className="btn ghost sm" onClick={() => setBlocks(blocks.length > 1 ? blocks.filter((_, j) => j !== i) : blocks)}
                    title="删除该行"><Icon name="cross" size={12} /></button>
                </div>
              ))}
              <button className="btn ghost sm" onClick={() => setBlocks([...blocks, { ...EMPTY_BLOCK }])}><Icon name="plus" size={12} /> 添加块行</button>
            </div>
            <div className="ctrlrow">
              <button className="btn sm" onClick={reportFieldmod} disabled={busy || !pid}>上报并比对</button>
              <span className="hint">sha256 由现场工程师从设备/归档如实抄录；前端不编造任何哈希。</span>
            </div>
            {fieldmod && (
              <div className="ip-report">
                <div className="beh-row"><span className="beh-k">漂移检测</span>
                  <Badge tone={fieldmod.drift_detected ? "err" : "ok"}>{fieldmod.b2_vs_b3}</Badge>
                  {fieldmod.frozen && <Badge tone="err">变更已冻结</Badge>}
                  {fieldmod.error_code && <Badge tone="err">{fieldmod.error_code}</Badge>}
                </div>
                <div className="beh-row"><span className="beh-k">变更块</span>
                  {fieldmod.changed_blocks.length
                    ? fieldmod.changed_blocks.map((c, i) => (
                      <Badge key={i} tone="warn" title={`b2=${String(c.b2_sha256 ?? "-").slice(0, 16)} field=${String(c.field_sha256 ?? "-").slice(0, 16)}`}>
                        {c.block_name} · {c.reason}
                      </Badge>))
                    : <span className="hint">无</span>}</div>
                <div className="beh-row"><span className="beh-k">不可映射原生代码</span>
                  {fieldmod.unmapped_native_code.length
                    ? <span className="hyp">{fieldmod.unmapped_native_code.map(b => <Badge key={b} tone="unknown" title="UNMAPPED_NATIVE_CODE：作为受控黑盒保留">{b}</Badge>)}</span>
                    : <span className="hint">无</span>}</div>
                <div className="beh-row"><span className="beh-k">受控黑盒覆盖</span>
                  {fieldmod.managed_native_overrides.length
                    ? <span className="hyp">{fieldmod.managed_native_overrides.map(o => <Badge key={o.override_id} tone="info" title={o.note}>{o.block_name}</Badge>)}</span>
                    : <span className="hint">无</span>}</div>
                <div className="hint">{fieldmod.note || "现场修改不会被默默覆盖：不可映射代码按 MANAGED_NATIVE_OVERRIDE 隔离，等待人工合并。"}</div>
              </div>
            )}
          </div>
        </section>
      </div>
      {toastEl}
    </div>
  );
}
