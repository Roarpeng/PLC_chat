/**
 * 交付结果区（从原 GreenfieldPanel.tsx:480-880 原样迁出，行为不变）。
 *
 * 新增可选 `visibleSections`：默认全部显示；工程视角 6 组可只挂载对应分组，
 * 便于「信息不删、按需展开」。所有字段仍来自 /state 与真实响应，不虚构结论。
 *
 * 覆盖：差异清单（D11）逐项勾选 / 反向保护（D10）/ fidelity（N9）/
 * 编译诊断（P1-I）/ F13 只读 SCL 预览 / 三动作 A·B·C / 八步 step_order。
 */
import React from "react";
import { highlightSclLines } from "../../canvas/sclHighlight";
import {
  GF_ACTION_B_STEPS,
  GF_ACTION_C_STEPS,
  GF_COMPILE_STEPS,
  actionStepStatus,
  compileStepStatus,
  diffItemKey,
  formatCompileVerdict,
  formatFidelityLabel,
  pendingRealMachineLabel,
  type GFActionAvailability,
  type GFActionCompileDiagnostics,
  type GFActionKind,
  type GFActionResult,
  type GFCompileDiagnostics,
  type GFFidelityStatus,
  type GFReverseProtection,
  type GFSpecDiff,
  type GFSourceBlock,
} from "../../state/greenfield";

export type DeliverySection =
  | "pending"
  | "triad"
  | "steps"
  | "compile"
  | "fidelity"
  | "diff"
  | "scl";

const ALL_SECTIONS: ReadonlyArray<DeliverySection> = [
  "pending",
  "triad",
  "steps",
  "compile",
  "fidelity",
  "diff",
  "scl",
];

export interface DeliveryReviewProps {
  diff?: GFSpecDiff | null;
  fidelity?: GFFidelityStatus | null;
  reverseProtection?: GFReverseProtection | null;
  compileDiagnostics?: GFCompileDiagnostics | null;
  diffConfirmed?: boolean;
  onConfirmDiff?: (confirmed: boolean) => void;
  onRefreshDiff?: () => void;
  busy?: boolean;
  pendingRealMachine?: boolean;
  sclSources?: Record<string, string> | null;
  /* —— F20 三动作 —— */
  actionAvailability?: Record<GFActionKind, GFActionAvailability>;
  actionResults?: Partial<Record<GFActionKind, GFActionResult | null>>;
  actionLoading?: GFActionKind | null;
  actionError?: string;
  actionErrorCode?: string;
  onRunActionA?: () => void;
  onRunActionB?: () => void;
  onRunActionC?: () => void;
  actionCompileDiagnostics?: GFActionCompileDiagnostics | null;
  diffChecked?: Record<string, boolean>;
  onToggleDiffItem?: (key: string, checked: boolean) => void;
  checklistComplete?: boolean;
  explicitConfirmed?: boolean;
  /** 工程视角 6 组按需挂载；缺省 = 全部显示（行为与原组件一致）。 */
  visibleSections?: ReadonlyArray<DeliverySection>;
}

export function sourceBlockLabel(block: GFSourceBlock): string {
  const payloadKeys = Object.keys(block.payload ?? {}).slice(0, 3);
  return `${block.source_id} · ${block.kind}${payloadKeys.length ? ` · ${payloadKeys.join("/")}` : ""}`;
}

export const DeliveryReview: React.FC<DeliveryReviewProps> = ({
  diff,
  fidelity,
  reverseProtection,
  compileDiagnostics,
  diffConfirmed,
  onConfirmDiff,
  onRefreshDiff,
  busy,
  pendingRealMachine,
  sclSources,
  actionAvailability,
  actionResults,
  actionLoading,
  actionError,
  actionErrorCode,
  onRunActionA,
  onRunActionB,
  onRunActionC,
  actionCompileDiagnostics,
  diffChecked,
  onToggleDiffItem,
  checklistComplete,
  explicitConfirmed,
  visibleSections = ALL_SECTIONS,
}) => {
  const show = (section: DeliverySection): boolean => visibleSections.includes(section);
  const fidelityLabel = formatFidelityLabel(fidelity);
  const protection = reverseProtection ?? fidelity?.reverse_protection ?? null;
  const blocked = !!protection && (protection.allowed === false || (protection.tia_side_drift ?? 0) > 0);
  const diagnostics = compileDiagnostics ?? null;
  const phase = diagnostics?.phase ?? "idle";
  const sclEntries = Object.entries(sclSources ?? {});
  const diffGroups: Array<{ key: "changed" | "added" | "removed"; title: string; blocks: GFSourceBlock[] }> = [
    { key: "changed", title: "变更", blocks: diff?.changed ?? [] },
    { key: "added", title: "新增", blocks: diff?.added ?? [] },
    { key: "removed", title: "移除", blocks: diff?.removed ?? [] },
  ];
  const hasDiff = diffGroups.some((g) => g.blocks.length > 0);
  const compileVerdict = formatCompileVerdict(
    actionCompileDiagnostics ?? diagnostics,
    pendingRealMachine,
  );
  const triad: Array<{ kind: GFActionKind; label: string; title: string; run?: () => void }> = [
    { kind: "A", label: "Action A · 导出工程包", title: "离线可校验、不写 TIA；产出 fidelity 报告与 EvidenceBundle", run: onRunActionA },
    { kind: "B", label: "Action B · 首次写入博途编译", title: "前置：Action A 的 fidelity_ok=true + 差异清单显式确认（D11）", run: onRunActionB },
    { kind: "C", label: "Action C · 调试期增量回写", title: "§13.5 八步；前置：差异清单显式确认（D11）+ 反向保护通过", run: onRunActionC },
  ];
  const cSteps = actionResults?.C?.steps ?? [];
  const bSteps = actionResults?.B?.steps ?? [];
  const shownSteps = cSteps.length > 0 ? cSteps : bSteps;

  return (
    <div className="gf-delivery" data-ui="greenfield-delivery-review">
      {show("pending") && (
        <div className="gf-delivery__pending">
          涉真机验收项：<strong>pending_real_machine</strong>
          {pendingRealMachine !== false ? "（本批次无真机，不宣称 L2 / L4 通过，不宣称编译零错误）" : ""}
          <div className="gf-muted">{pendingRealMachineLabel(pendingRealMachine)}</div>
        </div>
      )}

      {/* —— F20 三动作（§3.2）：A 导出 / B 首次写入 / C 增量回写 —— */}
      {show("triad") && (
        <section className="gf-review-section" data-ui="greenfield-action-triad">
          <div className="gf-review-section__head">
            <strong>三动作 · 交付结果区操作入口</strong>
            <span className="gf-muted">B 须在 A 的 fidelity_ok=true 后可用；C 须在差异清单显式确认后可用（D11）</span>
          </div>
          <div className="gf-action-triad">
            {triad.map((item) => {
              const avail = actionAvailability?.[item.kind] ?? {
                enabled: false,
                reason: "尚未获取三动作状态（未连接网关或状态未返回）",
              };
              const loading = actionLoading === item.kind;
              const disabled = !avail.enabled || !!busy || loading;
              return (
                <div className="gf-action-card" key={item.kind}>
                  <button
                    type="button"
                    className="gf-btn gf-btn--primary"
                    disabled={disabled}
                    title={avail.enabled ? item.title : avail.reason}
                    onClick={() => item.run?.()}
                  >
                    {loading ? "处理中…" : item.label}
                  </button>
                  <div className={avail.enabled ? "gf-muted" : "gf-bad-text"}>
                    {avail.enabled ? avail.reason : `已锁定：${avail.reason}`}
                  </div>
                  {actionResults?.[item.kind] && (
                    <div className="gf-muted">
                      上次结果：{actionResults[item.kind]?.ok ? "完成" : "被阻止 / 未通过"}
                      {actionResults[item.kind]?.fidelity_ok !== undefined && (
                        <> · 还原度校验 fidelity_ok={String(actionResults[item.kind]?.fidelity_ok)}</>
                      )}
                      {actionResults[item.kind]?.compile_ok !== undefined && (
                        <> · 本次编排 compile_ok={String(actionResults[item.kind]?.compile_ok)}</>
                      )}
                      {actionResults[item.kind]?.tia_written === false && <> · 未写 TIA（待真机）</>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {actionError && (
            <div className="gf-bad" role="alert">
              <strong>动作被拒绝（{actionErrorCode || "网关拒绝"}）：</strong>
              <div>{actionError}</div>
              <div className="gf-muted">服务端 fail-closed，未产生任何越权写入（D11 / D10）。</div>
            </div>
          )}
        </section>
      )}

      {/* —— §13.5 八步进度（step_order）与每步结果 —— */}
      {show("steps") && (
        <section className="gf-review-section" data-ui="greenfield-action-steps">
          <div className="gf-review-section__head">
            <strong>step_order（§13.5 八步）进度与每步结果</strong>
            <span className="gf-muted">顺序由服务端真实响应给出，未执行的步骤显示「待执行」，禁止臆造</span>
          </div>
          <div className="gf-compile-steps">
            {GF_ACTION_C_STEPS.map((step) => {
              const st = actionStepStatus(cSteps.length > 0 ? cSteps : undefined, step.key);
              const cls = st === "done" ? "done" : st === "failed" ? "active" : "todo";
              const suffix = st === "done" ? " · 完成" : st === "failed" ? " · 失败" : "";
              return (
                <span key={step.key} className={`gf-compile-step gf-compile-step--${cls}`} title={step.key}>
                  {step.label}{suffix}
                </span>
              );
            })}
          </div>
          <div className="gf-muted">
            {shownSteps.length > 0
              ? `步骤明细：${shownSteps
                  .map((s) => `${s.step}=${s.ok ? "ok" : "blocked"}${s.detail ? `(${s.detail})` : ""}`)
                  .join("；")}`
              : "尚未执行 B / C，八步进度均为待执行；step_order / 每步结果只展示服务端真实返回"}
          </div>
          {bSteps.length > 0 && (
            <div className="gf-muted">
              Action B 四步：{GF_ACTION_B_STEPS.map((s) => `${s.label}:${actionStepStatus(bSteps, s.key)}`).join(" · ")}
            </div>
          )}
        </section>
      )}

      {/* —— 编译诊断（P1-I 展示层，不改后端 compile_jobs.py / writeback_heal.py）—— */}
      {show("compile") && (
        <section className="gf-review-section">
          <div className="gf-review-section__head">
            <strong>结构化编译诊断与状态反馈</strong>
            <span className="gf-muted">generate → compile → 诊断 → 修正 → 复编译（仅展示与状态机）</span>
          </div>
          {/* N9：compile_ok 用 error_count / warnings 单列展示；真机未跑显示「待真机」而非「成功」 */}
          <div className={compileVerdict.ok ? "gf-fidelity gf-fidelity--ok" : "gf-fidelity"}>
            <strong>{compileVerdict.label}</strong>
            <span className="gf-muted">{compileVerdict.detail}</span>
          </div>
          <div className="gf-compile-steps">
            {GF_COMPILE_STEPS.map((step) => (
              <span
                key={step.key}
                className={`gf-compile-step gf-compile-step--${compileStepStatus(phase, step.key)}`}
              >
                {step.label}
              </span>
            ))}
          </div>
          {diagnostics ? (
            <div className="gf-compile-report">
              <div className="gf-compile-metric">
                <span className="gf-muted">error_count</span>
                <strong className={diagnostics.error_count > 0 ? "gf-bad-text" : "gf-ok-text"}>
                  {diagnostics.error_count}
                </strong>
                <span className="gf-muted">（warning 单列，绝不并入成功）</span>
              </div>
              <div className="gf-compile-cols">
                <div>
                  <div className="gf-side-title">warnings（单列，{diagnostics.warnings.length} 条）</div>
                  {diagnostics.warnings.length === 0 ? (
                    <div className="gf-muted">无 warning 条目</div>
                  ) : (
                    diagnostics.warnings.map((w, i) => (
                      <div className="gf-warning" key={`${w}-${i}`}>· {w}</div>
                    ))
                  )}
                </div>
                <div>
                  <div className="gf-side-title">块清单（{diagnostics.blocks.length} 块）</div>
                  {diagnostics.blocks.length === 0 ? (
                    <div className="gf-muted">后端未提供块清单</div>
                  ) : (
                    diagnostics.blocks.slice(0, 20).map((b, i) => (
                      <div className="gf-muted" key={`${b.name}-${i}`}>
                        {b.name} · {b.block_type ?? "—"} · 错误 {b.error_count ?? 0} / 警告 {b.warning_count ?? 0}
                      </div>
                    ))
                  )}
                </div>
              </div>
              {diagnostics.tia_unavailable && (
                <div className="gf-bad">TIA 真机环境不可用，本次编译判定未执行（非编译通过）。</div>
              )}
              {diagnostics.note && <div className="gf-muted">{diagnostics.note}</div>}
            </div>
          ) : actionCompileDiagnostics ? (
            <div className="gf-compile-report">
              <div className="gf-compile-metric">
                <span className="gf-muted">error_count</span>
                <strong className={actionCompileDiagnostics.error_count > 0 ? "gf-bad-text" : "gf-ok-text"}>
                  {actionCompileDiagnostics.error_count}
                </strong>
                <span className="gf-muted">（warning 单列，绝不并入成功）</span>
              </div>
              <div className="gf-compile-cols">
                <div>
                  <div className="gf-side-title">warnings（单列，{(actionCompileDiagnostics.warnings ?? []).length} 条）</div>
                  {(actionCompileDiagnostics.warnings ?? []).length === 0 ? (
                    <div className="gf-muted">无 warning 条目</div>
                  ) : (
                    (actionCompileDiagnostics.warnings ?? []).map((w, i) => (
                      <div className="gf-warning" key={`${w}-${i}`}>· {String(w)}</div>
                    ))
                  )}
                </div>
                <div>
                  <div className="gf-side-title">状态 / 诊断（真实响应）</div>
                  <div className="gf-muted">status：{actionCompileDiagnostics.status ?? "—"}</div>
                  <div className="gf-muted">l2_status：{actionCompileDiagnostics.l2_status ?? "—"}</div>
                  <div className="gf-muted">static_gate_passed：{String(actionCompileDiagnostics.static_gate_passed ?? "—")}</div>
                  {actionCompileDiagnostics.reason && (
                    <div className="gf-muted">reason：{actionCompileDiagnostics.reason}</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="gf-muted">
              后端尚未返回结构化编译诊断（诚实降级：不虚构 error_count，也不宣称编译零错误）。
            </div>
          )}
        </section>
      )}

      {/* —— fidelity（N9）—— */}
      {show("fidelity") && (
        <section className="gf-review-section">
          <div className="gf-review-section__head">
            <strong>还原度校验（fidelity）</strong>
            <span className="gf-muted">只表达 L1 逻辑等价；与「编译通过」是两个独立验收层，禁止互相替代（N9）</span>
          </div>
          <div className={fidelityLabel.ok ? "gf-fidelity gf-fidelity--ok" : "gf-fidelity"}>
            <strong>{fidelityLabel.label}</strong>
            <span className="gf-muted">{fidelityLabel.detail}</span>
          </div>
          {!!fidelity?.ob_number_deviations && (
            <div className="gf-muted">OB 编号偏差已留痕（不纳入 1:1 域，禁止静默）</div>
          )}
        </section>
      )}

      {/* —— 差异清单（F20 / D11 / D10）—— */}
      {show("diff") && (
        <section className="gf-review-section">
          <div className="gf-review-section__head">
            <strong>差异清单（SpecDiff）</strong>
            {onRefreshDiff && (
              <button
                type="button"
                className="gf-btn gf-btn--xs gf-btn--ghost"
                disabled={busy}
                onClick={onRefreshDiff}
              >
                重新计算差异
              </button>
            )}
          </div>

          {blocked && (
            <div className="gf-blocked" role="alert">
              <strong>TIA 侧存在手工改动，已阻止覆盖</strong>
              <div className="gf-muted">
                被阻止的 source_id：{(protection?.blocked_source_ids ?? []).join("、") || "—"}
                {protection?.reason ? ` · ${protection.reason}` : ""}
              </div>
              <div className="gf-muted">按 D10 fail-closed：不覆盖、不「先覆盖再提示」。</div>
            </div>
          )}

          {hasDiff ? (
            <div className="gf-diff-groups">
              {diffGroups.map((group) => (
                <div className="gf-diff-group" key={group.key}>
                  <div className="gf-side-title">
                    {group.title}（{group.blocks.length}）
                  </div>
                  {group.blocks.length === 0 ? (
                    <div className="gf-muted">无</div>
                  ) : (
                    group.blocks.map((block, index) => {
                      const key = diffItemKey(group.key, block, index);
                      return (
                        <label className="gf-diff-item" key={key}>
                          <input
                            type="checkbox"
                            checked={!!diffChecked?.[key]}
                            disabled={busy}
                            onChange={(e) => onToggleDiffItem?.(key, e.target.checked)}
                          />
                          <code>{sourceBlockLabel(block)}</code>
                          <span className="gf-muted">（{group.title} · source_id：{block.source_id}）</span>
                        </label>
                      );
                    })
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="gf-muted">
              暂无差异清单（后端未返回 SpecDiff 或版本未发生变化）。未确认前不会产生任何写入。
            </div>
          )}

          {/* D11：逐项勾选齐全后才能显式确认；显式确认前所有写入按钮 disabled 且说明原因 */}
          <label className="gf-diff-confirm">
            <input
              type="checkbox"
              checked={!!diffConfirmed}
              disabled={busy || !checklistComplete}
              onChange={(e) => onConfirmDiff?.(e.target.checked)}
            />
            <span>
              我已逐条核对上述差异清单并<strong>逐项勾选</strong>，现<strong>显式确认</strong>后才允许后续写入（D11：确认前零副作用计数器恒 0）
            </span>
          </label>
          <div className="gf-muted">
            逐项勾选：{checklistComplete ? "已齐全" : "未齐全（请先勾选全部变更 / 新增 / 移除项）"}；
            当前状态：{explicitConfirmed ? "已显式确认（D11 后续写入解锁）" : "未显式确认（A 之外的所有写入按钮已锁定）"}
          </div>
        </section>
      )}

      {/* —— F13 降级：纯文本 SCL 只读预览 + 关键字高亮 —— */}
      {show("scl") && (
        <section className="gf-review-section">
          <div className="gf-review-section__head">
            <strong>SCL 只读预览（F13 降级）</strong>
            <span className="gf-muted">纯文本 + 关键字高亮 · 未引入 Monaco · 无任何写回 TIA 的编辑入口</span>
          </div>
          {sclEntries.length === 0 ? (
            <div className="gf-muted">
              暂无只读预览内容：尚未生成产物或后端未提供 SCL 源，不会虚构任何代码或地址条目。
            </div>
          ) : (
            <div className="gf-scl-preview">
              {sclEntries.map(([name, code]) => (
                <div className="gf-scl-block" key={name}>
                  <div className="gf-scl-block__head">
                    <code>{name}</code>
                    <span className="gf-muted">只读</span>
                  </div>
                  <pre className="gf-scl-block__code">
                    {code.split("\n").map((line, i) => (
                      <div className="gf-scl-line" key={i}>
                        <span className="gf-scl-line__no">{i + 1}</span>
                        <span className="gf-scl-line__text">{highlightSclLines(line)}</span>
                      </div>
                    ))}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
};
