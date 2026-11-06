/** 顶栏（阶段节点 + 梯级进度带）+ 底栏确认硬门禁（三级门禁色：读灰 / 写青 / 破坏赭红）。 */
import React, { useState } from "react";
import {
  assertNoSideEffects,
  canConfirm,
  downloadPackageUrl,
  gateReason,
  shortHash,
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
}) => {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const frozen = state.stage === "FROZEN";
  const latest = state.specs[state.specs.length - 1];
  const ready = canConfirm(state);
  const delivery = state.delivery_summary;
  const lit = STAGE_RUNGS[state.stage] ?? 1;

  const openSummary = async () => {
    setSummaryError("");
    try {
      assertNoSideEffects(state);
      setSummary(await onShowSummary());
    } catch (error) {
      setSummaryError(String(error));
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
            disabled={!frozen || !onGenerateProject}
            title={frozen ? "按 AF V1.2 架构生成标准博途 SCL 工程包" : gateReason(state)}
            onClick={() => onGenerateProject?.()}
          >
            {delivery ? "重新生成标准工程" : "生成标准 AF 博途工程"}
          </button>
          {frozen && onDeliverTia && (
            <button
              type="button"
              className="gf-btn gf-btn--danger"
              title="真机交付：XML 补充包 + 四层静态门禁 + PCEC 账本，经本机 TIA Openness 自动建项目、导入并编译（首次耗时分钟级；TIA 不可用时诚实降级为人工导入指引）"
              onClick={() => onDeliverTia("auto")}
            >
              写入博途（真机）
            </button>
          )}
          <button
            type="button"
            className={frozen ? "gf-btn" : "gf-btn gf-btn--danger"}
            disabled={frozen || !ready}
            title={gateReason(state)}
            onClick={() => void openSummary()}
          >
            确认图中架构与功能
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

        {summaryError && <div className="gf-bad">{summaryError}</div>}

        {summary && (
          <div className="gf-modal" role="dialog" aria-label="确认图中架构与功能">
            <div className="gf-modal__card">
              <div className="gf-modal__title">请确认图中架构与功能</div>
              <div className="gf-muted">
                下面是工程视角摘要。确认后仅冻结规格，不会生成工程、不会写回博途。
              </div>
              <pre className="gf-modal__json">{JSON.stringify(summary, null, 2)}</pre>
              <div className="gf-modal__actions">
                <button type="button" className="gf-btn gf-btn--ghost" onClick={() => setSummary(null)}>
                  返回修改
                </button>
                <button
                  type="button"
                  className="gf-btn gf-btn--danger"
                  onClick={() => {
                    setSummary(null);
                    onConfirm();
                  }}
                >
                  我已确认，冻结规格
                </button>
              </div>
            </div>
          </div>
        )}
      </footer>
    </>
  );
};
