/**
 * 工位 04 · 完成：用户可见终点。
 *
 * 严谨口径：不依赖真机环境、不依赖三动作、不依赖差异清单勾选；
 * 还原一致性结论由 formatFidelityBusiness 中文如实转述，达标与否都不阻断完成。
 * 「重新调整」由 Channel 先调 beginEdit 解锁连线；「开始新工程」清本地键后取真实新会话。
 */
import React from "react";
import type { GFDeliverySummary } from "../../state/greenfield";
import {
  formatDeliveryBusiness,
  formatFidelityBusiness,
  type FidelityView,
  type StepBaseProps,
  type WizardStep,
} from "./stepMachine";

export interface StepDeliverProps extends StepBaseProps {
  step: WizardStep;
  delivery: GFDeliverySummary | null;
  fidelity: FidelityView;
  onDownloadUrl: () => string;
  onReAdjust: () => void;
  onRestart: () => void;
}

export const StepDeliver: React.FC<StepDeliverProps> = ({
  step,
  busy,
  error,
  completed,
  onOpenEngineering,
  onClearError,
  delivery,
  fidelity,
  onDownloadUrl,
  onReAdjust,
  onRestart,
}) => {
  const fidelityView = formatFidelityBusiness(fidelity);
  const packageView = formatDeliveryBusiness(delivery);
  const canDownload = !!delivery;

  return (
    <div className="gf-step-deliver" data-step={step} data-ui="wizard-step-deliver">
      <div className="gf-wiz__kicker">工位 04 · 交付</div>
      <h2 className="gf-step-deliver__headline">工程包已就绪</h2>

      <div className="gf-stamp" data-ui="wizard-stamp">
        本轮交付完成
      </div>

      {(completed || canDownload) && (
        <div className="gf-wiz__done">本步已完成 · 可下载工程包</div>
      )}

      <div className="gf-step-deliver__report">
        <div className="gf-step-deliver__report-row">
          <div className="gf-step-deliver__report-title">{packageView.title}</div>
          <div className="gf-step-deliver__report-detail">{packageView.detail}</div>
        </div>
        <div className="gf-step-deliver__report-row">
          <div className="gf-step-deliver__report-title">{fidelityView.title}</div>
          <div className="gf-step-deliver__report-detail">{fidelityView.detail}</div>
        </div>
        <div className="gf-step-deliver__report-row">
          <div className="gf-step-deliver__report-title">交付说明</div>
          <div className="gf-step-deliver__report-detail">
            本轮工作在工程包生成后即告完成；真机核验与审计明细可在工程视角中按需查看，不影响本轮下载。
          </div>
        </div>
      </div>

      {error && (
        <div className="gf-wiz__error" role="alert">
          {error}
          {onClearError && (
            <button
              type="button"
              className="gf-btn gf-btn--xs gf-btn--ghost"
              onClick={onClearError}
            >
              知道了
            </button>
          )}
        </div>
      )}

      <div className="gf-wiz__actions">
        {canDownload ? (
          <a
            className="gf-btn gf-btn--primary gf-step-deliver__download"
            href={onDownloadUrl()}
            download={delivery?.zip_filename || undefined}
          >
            下载工程包
          </a>
        ) : (
          <button type="button" className="gf-btn gf-btn--primary" disabled>
            工程包尚未就绪
          </button>
        )}
      </div>

      <div className="gf-wiz__actions gf-step-deliver__secondary">
        <button
          type="button"
          className="gf-btn gf-btn--ghost"
          disabled={busy}
          onClick={onReAdjust}
        >
          重新调整
        </button>
        <button
          type="button"
          className="gf-btn gf-btn--ghost"
          disabled={busy}
          onClick={onRestart}
        >
          开始新工程
        </button>
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onOpenEngineering}>
          工程视角
        </button>
      </div>
    </div>
  );
};
