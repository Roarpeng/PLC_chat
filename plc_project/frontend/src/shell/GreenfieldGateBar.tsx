/** 顶栏（阶段节点 + 梯级进度带）+ 底栏确认硬门禁（P1-H 升级）。
 *
 *  - 确认按钮文案「确认设备逻辑并锁定还原契约」；
 *  - 前置 = 拓扑定稿 ∧ open_questions 清零 ∧ 节点/连线校验 ∧ 等价性预检 ∧ 基线版本锁定；
 *    任一未满足时按钮 disabled 且给出**具体原因**（不笼统提示）；
 *  - 后端 `/confirm` 返回的 code / message 通过 `mapConfirmError` 映射为可读中文展示；
 *  - 差异清单未显式确认 / 反向保护阻止 / fidelity 未达标时，后续写入按钮锁定并给出原因；
 *  - `pending_real_machine` 常驻可见：不宣称 L2 / L4 通过，不宣称编译零错误。
 */
import React, { useState } from "react";
import {
  assertNoSideEffects,
  canConfirm,
  confirmBlockers,
  downloadPackageUrl,
  formatGfError,
  gateReason,
  mapConfirmError,
  pendingRealMachineLabel,
  shortHash,
  type GFActionKind,
  type GFActionResult,
  type GFBlocker,
  type GFStage,
  type GFState,
} from "../state/greenfield";

export interface GreenfieldGateBarProps {
  state: GFState;
  onShowSummary: () => Promise<Record<string, unknown>>;
  onConfirm: () => void;
  onBeginEdit: () => void;
  onExportMermaid: () => void;
  onExportDraft: () => void;
  onImportDraft: (payload: unknown) => void;
  onGenerateProject?: () => void;
  onDeliverTia?: (mode: "auto" | "package") => void;
  onLoadReference?: () => void;
  onBack: () => void;

  /* —— 本批次新增 —— */
  /** 后端 `/confirm` 返回的网关 code（如 GF_TOPOLOGY_NOT_FINALIZED）。 */
  confirmErrorCode?: string;
  /** 后端 `/confirm` 返回的原始 message（映射中文时作为补充说明）。 */
  confirmErrorMessage?: string;
  /** 后续写入的阻断原因（D11 差异未确认 / D10 反向保护 / fidelity 未达标）。 */
  writeBlockers?: GFBlocker[];
  pendingRealMachine?: boolean;
  diffConfirmed?: boolean;
  projectId?: string;
  /** F20 三动作结果（顶栏状态徽标；真机结论一律 pending_real_machine）。 */
  actionResults?: Partial<Record<GFActionKind, GFActionResult | null>>;
}

/** 阶段 → 梯级点亮数（0..8）：蓝图纸上一格一格亮上去。 */
const STAGE_RUNGS: Record<GFStage, number> = {
  DRAFT: 1,
  LINKABLE: 3,
  VALIDATING: 5,
  FROZEN: 8,
  LOCKED: 8,
};

export const GreenfieldGateBar: React.FC<GreenfieldGateBarProps> = ({
  state,
  onShowSummary,
  onConfirm,
  onBeginEdit,
  onExportMermaid,
  onExportDraft,
  onImportDraft,
  onGenerateProject,
  onDeliverTia,
  onLoadReference,
  onBack,
  confirmErrorCode,
  confirmErrorMessage,
  writeBlockers = [],
  pendingRealMachine = true,
  diffConfirmed,
  projectId,
  actionResults,
}) => {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const frozen = state.stage === "FROZEN";
  const latest = state.specs[state.specs.length - 1];
  const ready = canConfirm(state);
  const delivery = state.delivery_summary;
  const lit = STAGE_RUNGS[state.stage] ?? 1;

  const blockers = confirmBlockers(state);
  const backendReason =
    confirmErrorCode || confirmErrorMessage
      ? mapConfirmError(confirmErrorCode ?? "", confirmErrorMessage)
      : "";
  const writeReason = writeBlockers.map((b) => b.reason).join("；");
  const generateDisabled = !frozen || !onGenerateProject || writeBlockers.length > 0;

  const openSummary = async () => {
    setSummaryError("");
    setSummaryLoading(true);
    try {
      assertNoSideEffects(state);
      setSummary(await onShowSummary());
    } catch (error) {
      setSummaryError(formatGfError(error));
    } finally {
      setSummaryLoading(false);
    }
  };

  const importFromFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    void file.text().then((text) => {
      try {
        onImportDraft(JSON.parse(text) as unknown);
      } catch {
        setSummaryError("草稿文件不是合法 JSON");
      }
    });
    event.target.value = "";
  };

  return (
    <>
      <header className="gf-topbar" data-ui="greenfield-gate-top">
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onBack}>
          返回工作台
        </button>
        <div className="gf-topbar__title">新建工程 · 对话 / 资料 → 逻辑图 → 博途</div>
        {projectId && <span className="gf-project-tag">项目 {projectId}</span>}

        {/* 梯级进度带：阶段一格一格点亮 */}
        <div className="gf-rungs" aria-label={`阶段进度 ${state.stage_label}`} title={`阶段 ${state.stage_label}`}>
          {Array.from({ length: 8 }, (_, i) => (
            <i key={i} className={i < lit ? "is-done" : undefined} />
          ))}
        </div>

        {/* 阶段节点（母题：带桩步块） */}
        <span className={frozen ? "gf-stage-node gf-stage-node--frozen" : "gf-stage-node"}>
          {state.stage_label}
        </span>
        <span className="gf-muted">{latest ? `v${latest.spec_version} · ${shortHash(latest.spec_hash)}` : "草稿 · 未冻结"}</span>
        {state.framework_baseline_version && (
          <span className="gf-muted" title="框架基线版本锁定状态">基线 {state.framework_baseline_version}</span>
        )}
        {/* pending_real_machine 常驻可见：真机未跑时显示「待真机」，绝不显示「成功」 */}
        <span className="gf-pending-chip" title={pendingRealMachineLabel(pendingRealMachine)}>
          {pendingRealMachine ? "pending_real_machine" : "真机证据待收口核验"}
        </span>
        <span
          className="gf-chip"
          title="三动作状态（A 导出 / B 首次写入 / C 增量回写）；fidelity_ok 只表达还原度校验，不等于编译通过；真机结论一律 pending_real_machine"
        >
          A {actionResults?.A
            ? (actionResults.A.fidelity_ok === true ? "还原度校验达标" : "还原度校验未达标")
            : "未执行"}
          {" · "}B {actionResults?.B
            ? (actionResults.B.tia_written ? "已写入（待真机）" : "待真机")
            : "未执行"}
          {" · "}C {actionResults?.C
            ? (actionResults.C.tia_written ? "已回写（待真机）" : "待真机")
            : "未执行"}
        </span>

        {onLoadReference && (
          <button
            type="button"
            className="gf-btn gf-btn--accent-outline"
            onClick={onLoadReference}
            title="一键加载内置 PLC_IO.pdf (113点) + KUKA_DATA.pdf (DB720) + PC_DATA.pdf (DB1900) 及参考工艺步序"
          >
            载入参考实例
          </button>
        )}
      </header>

      <footer className="gf-gatebar" data-ui="greenfield-gate-bottom">
        <div className="gf-gatebar__actions">
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onExportMermaid}>
            导出结构图
          </button>
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onExportDraft}>
            导出草稿
          </button>
          <label className="gf-btn gf-btn--ghost">
            导入草稿
            <input type="file" accept="application/json,.json" hidden onChange={importFromFile} />
          </label>
          {frozen && (
            <button type="button" className="gf-btn" onClick={onBeginEdit}>
              继续调整 (v+1)
            </button>
          )}
          {delivery && (
            <div className="gf-delivery-badges">
              <span className="gf-chip">AF V1.2 · {delivery.block_count} 块</span>
              <span className="gf-chip">
                Linter {delivery.verification?.linter_error_count ?? 0} 错
              </span>
              <span className="gf-chip">
                %Q 单写 {delivery.verification?.single_writer_audit?.mapped_q_tags ?? 0}/
                {delivery.verification?.single_writer_audit?.total_q_tags ?? 0}
              </span>
            </div>
          )}
        </div>

        <div className="gf-gatebar__gate">
          {/* 破坏级（赭红）：改工程状态的两个门 */}
          <button
            type="button"
            className={frozen ? "gf-btn gf-btn--danger" : "gf-btn"}
            disabled={generateDisabled}
            title={
              writeBlockers.length > 0
                ? writeReason
                : frozen
                  ? "按 AF V1.2 架构生成标准博途 SCL 工程包"
                  : gateReason(state)
            }
            onClick={() => onGenerateProject?.()}
          >
            {delivery ? "重新生成标准工程" : "生成标准 AF 博途工程"}
          </button>
          {frozen && onDeliverTia && (
            <button
              type="button"
              className="gf-btn gf-btn--danger"
              disabled={writeBlockers.length > 0}
              title={
                writeBlockers.length > 0
                  ? writeReason
                  : "真机交付：XML 补充包 + 四层静态门禁 + PCEC 账本；TIA 不可用时诚实降级为人工导入指引"
              }
              onClick={() => onDeliverTia("auto")}
            >
              写入博途（真机）
            </button>
          )}
          <button
            type="button"
            className={frozen ? "gf-btn" : "gf-btn gf-btn--danger"}
            disabled={frozen || !ready || summaryLoading}
            title={summaryLoading ? "正在加载工程视角摘要…" : ready ? "打开工程视角摘要并确认" : gateReason(state)}
            onClick={() => void openSummary()}
          >
            确认设备逻辑并锁定还原契约
          </button>
          {frozen && delivery && (
            <a
              className="gf-btn gf-btn--primary"
              href={downloadPackageUrl(state.session_id)}
              download={delivery.zip_filename}
            >
              下载工程包
            </a>
          )}
        </div>

        {/* 具体原因区：任一前置未满足时逐条展示，绝不笼统提示「操作失败」 */}
        {!ready && !frozen && (
          <div className="gf-gate-reasons" role="status">
            <div className="gf-gate-reasons__head">确认硬门禁未满足（{blockers.length} 项）：</div>
            {blockers.map((blocker, index) => (
              <div className="gf-gate-reason" key={`${blocker.code}-${index}`}>
                <span className="gf-bad__code">{blocker.code}</span>
                <span>{blocker.reason}</span>
              </div>
            ))}
          </div>
        )}
        {backendReason && (
          <div className="gf-gate-reasons gf-gate-reasons--backend" role="alert">
            <div className="gf-gate-reasons__head">后端 `/confirm` 返回的确认原因：</div>
            <div className="gf-gate-reason">{backendReason}</div>
          </div>
        )}
        {writeBlockers.length > 0 && (
          <div className="gf-gate-reasons gf-gate-reasons--write" role="alert">
            <div className="gf-gate-reasons__head">后续写入已锁定：</div>
            {writeBlockers.map((blocker, index) => (
              <div className="gf-gate-reason" key={`${blocker.code}-${index}`}>
                <span className="gf-bad__code">{blocker.code}</span>
                <span>{blocker.reason}</span>
              </div>
            ))}
            <div className="gf-muted">
              差异清单确认状态：{diffConfirmed ? "已显式确认" : "未确认（D11：确认前零副作用计数器恒 0）"}
            </div>
          </div>
        )}
        {summaryLoading && (
          <div className="gf-muted" role="status">正在加载工程视角摘要…</div>
        )}
        {summaryError && <div className="gf-bad">{summaryError}</div>}

        {summary && (
          <div className="gf-modal" role="dialog" aria-label="确认设备逻辑并锁定还原契约">
            <div className="gf-modal__card">
              <div className="gf-modal__title">确认设备逻辑并锁定还原契约</div>
              <div className="gf-muted">
                下面是工程视角摘要。确认后仅冻结规格，不会生成工程、不会写回博途。
                硬门禁前置：拓扑定稿 ∧ 待确认问题清零 ∧ 节点/连线校验 ∧ 等价性预检 ∧ 基线版本锁定。
              </div>
              <div className="gf-gate-checks">
                {blockers.length === 0 ? (
                  <div className="gf-ok">五项前置全部满足，可以锁定还原契约</div>
                ) : (
                  blockers.map((blocker, index) => (
                    <div className="gf-gate-reason" key={`${blocker.code}-${index}`}>
                      <span className="gf-bad__code">{blocker.code}</span>
                      <span>{blocker.reason}</span>
                    </div>
                  ))
                )}
              </div>
              <pre className="gf-modal__json">{JSON.stringify(summary, null, 2)}</pre>
              <div className="gf-modal__actions">
                <button type="button" className="gf-btn gf-btn--ghost" onClick={() => setSummary(null)}>
                  返回修改
                </button>
                <button
                  type="button"
                  className="gf-btn gf-btn--danger"
                  disabled={blockers.length > 0}
                  title={blockers.length > 0 ? blockers[0].reason : "确认并冻结规格"}
                  onClick={() => {
                    setSummary(null);
                    onConfirm();
                  }}
                >
                  确认设备逻辑并锁定还原契约
                </button>
              </div>
            </div>
          </div>
        )}
      </footer>
    </>
  );
};
