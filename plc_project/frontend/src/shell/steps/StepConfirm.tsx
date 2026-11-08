/**
 * 工位 03 · 确认：三段业务摘要 + 唯一主按钮。
 *
 * 门禁未满足时只给一句中文「还差什么 / 去哪补」+「查看工程视角」入口；
 * 逐项清单、原始返回信息与审计明细全部收在默认折叠的工程视角里。
 */
import React from "react";
import type { StepBaseProps, WizardStep } from "./stepMachine";

export interface StepConfirmProps extends StepBaseProps {
  step: WizardStep;
  submittedPrompt: string;
  nodesCount: number;
  edgesCount: number;
  canConfirm: boolean;
  confirmNote: string;
  onConfirmAndGenerate: () => void;
  willGet: { title: string; detail: string };
}

export const STEP_CONFIRM_WILL_GET: { title: string; detail: string } = {
  title: "工程包 + 还原度报告",
  detail: "一份可直接下载的工程包，以及本轮还原一致性结论的中文说明。",
};

export const StepConfirm: React.FC<StepConfirmProps> = ({
  step,
  busy,
  error,
  completed,
  onBackStep,
  onOpenEngineering,
  onClearError,
  submittedPrompt,
  nodesCount,
  edgesCount,
  canConfirm,
  confirmNote,
  onConfirmAndGenerate,
  willGet,
}) => {
  const note = confirmNote || (canConfirm
    ? ""
    : "确认所需的前置还没有齐备：请回到前两步补齐描述与连线，或展开工程视角查看具体还差什么。");

  return (
    <div className="gf-step-confirm" data-step={step} data-ui="wizard-step-confirm">
      <div className="gf-wiz__kicker">工位 03 · 确认</div>
      <h2 className="gf-wiz__title">确认这一轮工作</h2>
      <p className="gf-wiz__lead">
        下面三张卡片就是本轮全部内容。确认后系统会冻结规格并生成可下载的工程包。
      </p>

      {completed && <div className="gf-wiz__done">本步已完成 · 工程包已生成</div>}

      <div className="gf-step-confirm__cards">
        <section className="gf-step-confirm__card">
          <div className="gf-step-confirm__card-no">01 / 你要做的事</div>
          <div className="gf-step-confirm__card-title">工艺描述</div>
          <div className="gf-step-confirm__card-body">
            {submittedPrompt || "尚未填写描述，请返回第一步补充。"}
          </div>
        </section>

        <section className="gf-step-confirm__card">
          <div className="gf-step-confirm__card-no">02 / 你连的关系</div>
          <div className="gf-step-confirm__card-title">结构概览</div>
          <div className="gf-step-confirm__card-body">
            <span className="gf-step-confirm__card-num">{nodesCount}</span> 个设备节点 ·{" "}
            <span className="gf-step-confirm__card-num">{edgesCount}</span> 条设备关系
          </div>
        </section>

        <section className="gf-step-confirm__card">
          <div className="gf-step-confirm__card-no">03 / 你将拿到</div>
          <div className="gf-step-confirm__card-title">{willGet.title}</div>
          <div className="gf-step-confirm__card-body">{willGet.detail}</div>
        </section>
      </div>

      {note && (
        <div className="gf-wiz__note" role="status">
          {note}
          <div style={{ marginTop: 10 }}>
            <button
              type="button"
              className="gf-btn gf-btn--xs gf-btn--ghost"
              onClick={onOpenEngineering}
            >
              查看工程视角
            </button>
          </div>
        </div>
      )}

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
        {onBackStep && (
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onBackStep}>
            返回上一步
          </button>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--primary gf-wiz__primary"
          disabled={busy || !canConfirm}
          onClick={onConfirmAndGenerate}
        >
          {busy ? "处理中…" : "确认并生成工程包"}
        </button>
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onOpenEngineering}>
          工程视角
        </button>
      </div>
    </div>
  );
};
