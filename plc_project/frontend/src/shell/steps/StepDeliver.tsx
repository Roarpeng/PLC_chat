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
      <h2 className="gf-step-deliver__headline">源码包就绪（非原生工程）</h2>

      {/* D-3 / Q-03 P0：SOURCE_READY ≠ NATIVE_ARCHIVED。
          旧文案把源码 ZIP 冒充 TIA 原生工程（伪成功终态），已删除。 */}
      <div className="gf-stamp" data-ui="wizard-stamp">
        源码包就绪（非原生工程）
      </div>

      {(completed || canDownload) && (
        <div className="gf-wiz__done">源码包已生成 · 可下载源码导入包（非 TIA 原生工程）</div>
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
            本轮只生成源码导入包（SOURCE_READY），不是 TIA 原生工程归档（NATIVE_ARCHIVED）。
            真实 .zap19 需经 V19 创建、导入、编译 error_count=0、Save、Archive、sha256 与
            Retrieve/reopen 全链通过后由后端 Job 提供；真机结果未取得前一律标注「待真机核验」，
            此处不显示原生交付终态、不提供原生归档下载。
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
            下载源码包
          </a>
        ) : (
          <button type="button" className="gf-btn gf-btn--primary" disabled>
            源码包尚未就绪
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
