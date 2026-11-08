/**
 * 4 步主链容器：左 220px 工位步序带 + 右阶段工作区 + 右上角单一「工程视角」入口。
 *
 * 只读展示层 + 纯前端导航：GO / BACK / NEXT 不发任何请求、不重放生成；
 * 唯一例外是「进入步 3」时由 Channel 调 fetchEngineeringSummary（隐藏硬门禁），
 * 该动作属于主链，不属于抽屉，也不属于导航本身。
 */
import React, { useCallback, useMemo, useState } from "react";
import type { Connection } from "@xyflow/react";
import type { GFState, GFWhitelist } from "../state/greenfield";
import {
  EngineeringDrawer,
  type EngineeringActions,
  type EngineeringViewData,
} from "./EngineeringDrawer";
import { StepConfirm, STEP_CONFIRM_WILL_GET } from "./steps/StepConfirm";
import { StepDeliver } from "./steps/StepDeliver";
import { StepDescribe, STEP_DESCRIBE_EXAMPLES } from "./steps/StepDescribe";
import { StepLink } from "./steps/StepLink";
import {
  STEP_META,
  canAdvance,
  type AdvanceContext,
  type FidelityView,
  type WizardAction,
  type WizardState,
  type WizardStep,
} from "./steps/stepMachine";
import type { SketchSummary } from "./steps/StepDescribe";

export interface GreenfieldWizardProps {
  wizard: WizardState;
  dispatch: React.Dispatch<WizardAction>;
  state: GFState;
  whitelist: GFWhitelist | null;
  busy: boolean;
  loading: boolean;
  error: string;
  warning: string;
  sessionId: string;
  projectId: string;
  canConfirm: boolean;
  engineeringData: EngineeringViewData;
  engineeringActions: EngineeringActions;
  onBack: () => void;
  onSubmitDescribe: () => void;
  onPromptChange?: (value: string) => void;
  onConnect: (kind: string, connection: Connection) => void;
  onRemoveEdge: (edgeId: string) => void;
  onEnterConfirm: () => void;
  onConfirmAndGenerate: () => void;
  onBeginEditAndGoLink: () => void;
  onRestart: () => void;
  onDownloadUrl: () => string;
  onClearError?: () => void;
  onToggleMoreInputs?: () => void;
  moreInputs?: React.ReactNode;
}

export const GreenfieldWizard: React.FC<GreenfieldWizardProps> = ({
  wizard,
  dispatch,
  state,
  whitelist,
  busy,
  loading,
  error,
  warning,
  engineeringData,
  engineeringActions,
  onBack,
  onSubmitDescribe,
  onPromptChange,
  onConnect,
  onRemoveEdge,
  onEnterConfirm,
  onConfirmAndGenerate,
  onBeginEditAndGoLink,
  onRestart,
  onDownloadUrl,
  onClearError,
  onToggleMoreInputs,
  moreInputs,
  canConfirm,
}) => {
  const [railHint, setRailHint] = useState<string>("");

  const summary = state.summary ?? null;
  const edgesCount = Number(summary?.edges ?? 0);
  const reportOk = state.report?.ok === true;
  const hasIr = state.has_ir === true;
  const nodesCount =
    Number(summary?.units ?? 0) + Number(summary?.ems ?? 0) + Number(summary?.cms ?? 0);

  const sketch: SketchSummary | null = summary
    ? {
        units: Number(summary.units ?? 0),
        ems: Number(summary.ems ?? 0),
        cms: Number(summary.cms ?? 0),
        steps: Number(summary.steps ?? 0),
        edges: edgesCount,
      }
    : null;

  const frozen = state.stage === "FROZEN";
  const delivery = frozen && state.delivery_summary ? state.delivery_summary : null;
  const fidelity = (state.fidelity ?? state.delivery_summary?.fidelity ?? null) as FidelityView;

  const advanceCtx: AdvanceContext = {
    hasIr,
    edges: edgesCount,
    reportOk,
    canConfirm,
    stage: state.stage,
    hasDelivery: !!state.delivery_summary,
  };

  const openEngineering = useCallback(() => {
    dispatch({ type: "TOGGLE_ENGINEERING", value: true });
  }, [dispatch]);

  const handleBack = useCallback(() => {
    setRailHint("");
    dispatch({ type: "BACK" });
  }, [dispatch]);

  const handleNext = useCallback(() => {
    setRailHint("");
    if (wizard.step === 1) {
      dispatch({ type: "MARK_COMPLETE", step: 1 });
      dispatch({ type: "GO", step: 2 });
      return;
    }
    if (wizard.step === 2) {
      if (canAdvance(2, advanceCtx).ok) {
        dispatch({ type: "MARK_COMPLETE", step: 2 });
      }
      dispatch({ type: "GO", step: 3 });
      // ★ 隐藏硬门禁：进入步 3 必须先展示一次工程视角摘要，否则后端的
      //   确认门禁会拒绝本次确认。此调用属于主链，不是抽屉动作。
      onEnterConfirm();
      return;
    }
    if (wizard.step === 3 && state.stage === "FROZEN" && state.delivery_summary) {
      // 刷新页面后回到已冻结会话时，允许从确认步直接查看现成的工程包（零请求）。
      dispatch({ type: "MARK_COMPLETE", step: 3 });
      dispatch({ type: "GO", step: 4 });
    }
  }, [dispatch, wizard.step, advanceCtx, onEnterConfirm, state.stage, state.delivery_summary]);

  const goToStep = useCallback(
    (target: WizardStep) => {
      if (target === wizard.step) return;
      if (target < wizard.step) {
        setRailHint("");
        dispatch({ type: "GO", step: target });
        return;
      }
      if (target === wizard.step + 1) {
        handleNext();
        return;
      }
      setRailHint("请按顺序完成当前工位，再进入后面的步骤。");
    },
    [dispatch, wizard.step, handleNext],
  );

  const isDone = useCallback(
    (step: WizardStep): boolean =>
      wizard.completed[step] || (step === 4 && !!state.delivery_summary),
    [wizard.completed, state.delivery_summary],
  );

  const stepProps = {
    busy,
    error,
    onBackStep: handleBack,
    onOpenEngineering: openEngineering,
    onClearError,
  };

  const renderStage = (): React.ReactNode => {
    switch (wizard.step) {
      case 1:
        return (
          <StepDescribe
            {...stepProps}
            step={1}
            completed={isDone(1)}
            prompt={wizard.data.prompt}
            onPromptChange={(value: string) => {
              dispatch({ type: "SET_PROMPT", value });
              onPromptChange?.(value);
            }}
            sketch={sketch}
            hasIr={hasIr}
            onSubmit={onSubmitDescribe}
            canNext={hasIr}
            examples={STEP_DESCRIBE_EXAMPLES}
          />
        );
      case 2:
        return (
          <StepLink
            {...stepProps}
            step={2}
            completed={isDone(2)}
            onNext={handleNext}
            ir={state.ir}
            views={state.views}
            whitelist={whitelist}
            edgeKind={wizard.data.selectedEdgeKind}
            onEdgeKindChange={(kind: string) => dispatch({ type: "SET_EDGE_KIND", value: kind })}
            onConnect={onConnect}
            onRemoveEdge={onRemoveEdge}
            linkError={wizard.data.linkError}
            edgesCount={edgesCount}
            reportOk={reportOk}
            moreInputs={moreInputs}
          />
        );
      case 3:
        return (
          <StepConfirm
            {...stepProps}
            step={3}
            completed={isDone(3)}
            submittedPrompt={wizard.data.submittedPrompt || wizard.data.prompt}
            nodesCount={nodesCount}
            edgesCount={edgesCount}
            canConfirm={canConfirm}
            confirmNote={wizard.data.confirmNote}
            onConfirmAndGenerate={onConfirmAndGenerate}
            willGet={STEP_CONFIRM_WILL_GET}
          />
        );
      case 4:
        return (
          <StepDeliver
            {...stepProps}
            step={4}
            completed={isDone(4)}
            delivery={delivery}
            fidelity={fidelity}
            onDownloadUrl={onDownloadUrl}
            onReAdjust={onBeginEditAndGoLink}
            onRestart={onRestart}
          />
        );
      default:
        return null;
    }
  };

  const currentMeta = useMemo(
    () => STEP_META.find((meta) => meta.step === wizard.step) ?? STEP_META[0],
    [wizard.step],
  );

  return (
    <>
      <header className="gf-wiz__topbar" data-ui="wizard-topbar">
        <span className="gf-wiz__brand">
          新建工程
          <span className="gf-wiz__brand-sub">工业图纸 · {currentMeta.kicker}</span>
        </span>
        <span className="gf-wiz__topbar-spacer" />
        {onToggleMoreInputs && (
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onToggleMoreInputs}>
            辅助输入
          </button>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--ghost gf-eng__entry"
          onClick={() =>
            dispatch({ type: "TOGGLE_ENGINEERING", value: !wizard.engineeringOpen })
          }
          aria-expanded={wizard.engineeringOpen}
        >
          工程视角
        </button>
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onBack}>
          返回工作台
        </button>
      </header>

      <div className="gf-wiz__grid">
        <nav className="gf-wiz__rail" aria-label="4 个工位">
          {STEP_META.map((meta) => {
            const active = meta.step === wizard.step;
            const done = isDone(meta.step);
            const cls = [
              "gf-block",
              "gf-wiz__node",
              active ? "gf-wiz__node--active" : "",
              done && !active ? "gf-wiz__node--done" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <button
                key={meta.step}
                type="button"
                className={cls}
                aria-current={active ? "step" : undefined}
                onClick={() => goToStep(meta.step)}
              >
                <span className="gf-wiz__node-index">
                  {String(meta.step).padStart(2, "0")}
                </span>
                <span className="gf-wiz__node-title">{meta.title}</span>
                <span className="gf-wiz__node-kicker">{meta.kicker}</span>
                {done && <span className="gf-wiz__node-flag">本步已完成</span>}
              </button>
            );
          })}
          <div className="gf-wiz__rail-note">
            图纸既是导航，也是工作内容。整张纸会随四个工位依次换底。
          </div>
        </nav>

        <main className="gf-wiz__stage" data-ui="wizard-stage">
          <div className="gf-wiz__watermark" aria-hidden="true">
            {String(wizard.step).padStart(2, "0")}
          </div>
          <div className="gf-wiz__stage-inner">{renderStage()}</div>
          {railHint && <div className="gf-wiz__note" role="status">{railHint}</div>}
        </main>
      </div>

      <EngineeringDrawer
        open={wizard.engineeringOpen}
        groups={wizard.engineeringGroups}
        onToggle={() => dispatch({ type: "TOGGLE_ENGINEERING" })}
        onToggleGroup={(key) => dispatch({ type: "TOGGLE_GROUP", key })}
        data={engineeringData}
        actions={engineeringActions}
      />

      {warning && <div className="gf-wiz__warning" role="status">{warning}</div>}
      {error && <div className="gf-error" role="alert">{error}</div>}
      {loading && <div className="gf-busy">正在加载通道…</div>}
      {busy && <div className="gf-busy">处理中…</div>}
    </>
  );
};
