/** 顶栏阶段徽章 + 底栏确认硬门禁（T04 / AC-4 / Q9）。 */
import React, { useState } from "react";
import {
  assertNoSideEffects,
  canConfirm,
  gateReason,
  shortHash,
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
  onBack: () => void;
}

export const GreenfieldGateBar: React.FC<GreenfieldGateBarProps> = ({
  state,
  onShowSummary,
  onConfirm,
  onBeginEdit,
  onExportMermaid,
  onExportDraft,
  onImportDraft,
  onBack,
}) => {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const frozen = state.stage === "FROZEN";
  const latest = state.specs[state.specs.length - 1];
  const ready = canConfirm(state);

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
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onBack}>返回工作台</button>
        <div className="gf-topbar__title">从零生成标准工程</div>
        <span className="gf-badge">{state.stage_label}</span>
        <span className="gf-muted">版本 {latest ? `v${latest.spec_version}` : "草稿"}</span>
        <span className="gf-muted">编号 {shortHash(latest?.spec_hash)}</span>
        {!frozen && <span className="gf-badge gf-badge--lock">未确认 · 已锁定生成</span>}
      </header>

      <footer className="gf-gatebar" data-ui="greenfield-gate-bottom">
        <div className="gf-gatebar__actions">
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onExportMermaid}>导出结构图</button>
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onExportDraft}>导出草稿</button>
          <label className="gf-btn gf-btn--ghost">
            导入草稿
            <input type="file" accept="application/json,.json" hidden onChange={importFromFile} />
          </label>
          {frozen && (
            <button type="button" className="gf-btn gf-btn--ghost" onClick={onBeginEdit}>继续调整</button>
          )}
        </div>

        <div className="gf-gatebar__gate">
          <button type="button" className="gf-btn" disabled title={gateReason(state)}>
            生成标准工程（下一阶段）
          </button>
          <button
            type="button"
            className="gf-btn gf-btn--primary"
            disabled={frozen || !ready}
            title={gateReason(state)}
            onClick={() => void openSummary()}
          >
            确认图中架构与功能
          </button>
          <div className="gf-muted">{gateReason(state)}</div>
        </div>

        {summaryError && <div className="gf-bad">{summaryError}</div>}

        {summary && (
          <div className="gf-modal" role="dialog" aria-label="确认图中架构与功能">
            <div className="gf-modal__card">
              <div className="gf-modal__title">请确认图中架构与功能</div>
              <div className="gf-muted">
                下面是工程视角摘要。确认后仅冻结规格，不会生成工程、不会写回博图。
              </div>
              <pre className="gf-modal__json">{JSON.stringify(summary, null, 2)}</pre>
              <div className="gf-modal__actions">
                <button type="button" className="gf-btn gf-btn--ghost" onClick={() => setSummary(null)}>
                  返回修改
                </button>
                <button
                  type="button"
                  className="gf-btn gf-btn--primary"
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
