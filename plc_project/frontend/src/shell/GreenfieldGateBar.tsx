/**
 * 契约与门禁操作区（仅在「工程视角」抽屉内按需挂载，主链不再常驻）。
 *
 * 保留全部既有接线：canConfirm / confirmBlockers / gateReason / mapConfirmError /
 * downloadPackageUrl / pendingRealMachineLabel / shortHash，以及确认、生成、
 * 真机交付、继续调整、导出 / 导入草稿、载入参考实例等能力。
 *
 * 变更：删除原始报文弹窗，改为中文结构化摘要列表；
 * 顶栏徽标、三动作状态条、8 格梯级带只在抽屉内出现。
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
  confirmErrorCode?: string;
  confirmErrorMessage?: string;
  writeBlockers?: GFBlocker[];
  pendingRealMachine?: boolean;
  diffConfirmed?: boolean;
  projectId?: string;
  actionResults?: Partial<Record<GFActionKind, GFActionResult | null>>;
}

/** 阶段 → 梯级点亮数（0..8）：蓝图纸上一格一格亮上去（仅工程视角可见）。 */
const STAGE_RUNGS: Record<GFStage, number> = {
  DRAFT: 1,
  LINKABLE: 3,
  VALIDATING: 5,
  FROZEN: 8,
  LOCKED: 8,
};

function scalar(value: unknown): string {
  if (value === null || value === undefined) return "—（未提供）";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number" || typeof value === "string") return String(value);
  if (Array.isArray(value)) return `${value.length} 项`;
  if (typeof value === "object") return `结构化明细（${Object.keys(value as object).length} 个字段）`;
  return String(value);
}

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
        setSummaryError("草稿文件不是合法格式，已拒绝导入。");
      }
    });
    event.target.value = "";
  };

  return (
    <div className="gf-eng-gatebar" data-ui="greenfield-gate-bar">
      <div className="gf-topbar" data-ui="greenfield-gate-top">
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onBack}>
          返回工作台
        </button>
        <div className="gf-topbar__title">工程视角 · 契约与门禁</div>
        {projectId && <span className="gf-project-tag">项目 {projectId}</span>}

        <div className="gf-rungs" aria-label={`阶段进度 ${state.stage_label}`} title={`阶段 ${state.stage_label}`}>
          {Array.from({ length: 8 }, (_, i) => (
            <i key={i} className={i < lit ? "is-done" : undefined} />
          ))}
        </div>

        <span className={frozen ? "gf-stage-node gf-stage-node--frozen" : "gf-stage-node"}>
          {state.stage_label}
        </span>
        <span className="gf-muted">
          {latest ? `v${latest.spec_version} · ${shortHash(latest.spec_hash)}` : "草稿 · 未冻结"}
        </span>
        {state.framework_baseline_version && (
          <span className="gf-muted" title="框架基线版本锁定状态">基线 {state.framework_baseline_version}</span>
        )}
        {/* 真机口径只在工程视角出现：不宣称 L2 / L4 通过，不宣称编译零错误 */}
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
            title="一键加载内置参考资料与参考工艺步序"
          >
            载入参考实例
          </button>
        )}
      </div>

      <div className="gf-gatebar" data-ui="greenfield-gate-bottom">
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

        {/* 具体原因区：逐条展示，绝不笼统提示「操作失败」 */}
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
            <div className="gf-gate-reasons__head">后端返回的确认原因：</div>
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

        {/* 中文结构化摘要：不展示原始报文、不展示 JSON、不展示锁定清单原文 */}
        {summary && (
          <div className="gf-modal" role="dialog" aria-label="确认设备逻辑并锁定还原契约">
            <div className="gf-modal__card">
              <div className="gf-modal__title">确认设备逻辑并锁定还原契约</div>
              <div className="gf-muted">
                下面是工程视角摘要的中文结构化清单。确认后仅冻结规格，不会生成工程、不会写回博途。
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
              <ul className="gf-eng__list" data-ui="engineering-summary-structured">
                {Object.entries(summary).map(([key, value]) => (
                  <li key={key}>
                    <span className="gf-eng__code">{key}</span> · {scalar(value)}
                  </li>
                ))}
              </ul>
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
      </div>
    </div>
  );
};
