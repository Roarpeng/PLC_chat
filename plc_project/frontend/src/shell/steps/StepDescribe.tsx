/**
 * 工位 01 · 描述：全流程唯一的「工艺描述」输入框。
 *
 * 展示层：零后端知识、零请求函数、零内部契约术语。
 * 示例文案只填入输入框，点击「生成草图」后仍由 GreenfieldChannel 走真实
 * 后端解析，不提供任何离线假结果。
 */
import React from "react";
import type { StepBaseProps, WizardStep } from "./stepMachine";

export interface SketchSummary {
  units: number;
  ems: number;
  cms: number;
  steps: number;
  edges: number;
}

export interface StepDescribeProps extends StepBaseProps {
  step: WizardStep;
  prompt: string;
  onPromptChange: (value: string) => void;
  sketch: SketchSummary | null;
  hasIr: boolean;
  onSubmit: () => void;
  canNext: boolean;
  examples?: readonly string[];
}

export const STEP_DESCRIBE_EXAMPLES: readonly string[] = [
  "视觉引导的机器人上下料工位：上位机下发配方后，机器人依次完成取料、定位夹紧、涂胶与下料，光幕触发时立即安全中止并回到待机。",
  "气缸夹紧与真空吸盘配合的打磨产线：夹紧到位后启动打磨执行件，压力不足或急停触发时释放吸盘并停机，完成后由输送单元送出工件。",
  "双工位轮换灌装线：A 工位灌装时 B 工位上下料，称重达标后切换，任一阀门超时未响应则报警并保持当前步序等待人工处理。",
];

const SKETCH_CELLS: ReadonlyArray<{ key: keyof SketchSummary; label: string }> = [
  { key: "units", label: "工站" },
  { key: "ems", label: "执行单元" },
  { key: "cms", label: "执行件" },
  { key: "steps", label: "步序" },
  { key: "edges", label: "设备关系" },
];

export const StepDescribe: React.FC<StepDescribeProps> = ({
  step,
  busy,
  error,
  completed,
  onNext,
  onOpenEngineering,
  onClearError,
  prompt,
  onPromptChange,
  sketch,
  hasIr,
  onSubmit,
  canNext,
  examples = STEP_DESCRIBE_EXAMPLES,
}) => {
  const trimmed = prompt.trim();

  return (
    <div className="gf-step-desc" data-step={step} data-ui="wizard-step-describe">
      <div className="gf-wiz__kicker">工位 01 · 工艺描述</div>
      <h2 className="gf-wiz__title">描述你要做的事</h2>
      <p className="gf-wiz__lead">
        用一句话讲清产线要完成的工作、设备之间的先后顺序，以及出错时该怎么处理。
        我们会把它解析成一张可编辑的设备草图。
      </p>

      {completed && <div className="gf-wiz__done">本步已完成 · 草图已生成</div>}

      <div className="gf-step-desc__field">
        <label className="gf-step-desc__label" htmlFor="gf-wiz-prompt">
          工艺描述
        </label>
        <textarea
          id="gf-wiz-prompt"
          className="gf-step-desc__input"
          data-ui="wizard-prompt-input"
          value={prompt}
          disabled={busy}
          onChange={(event) => onPromptChange(event.target.value)}
          placeholder="例如：视觉引导的机器人上下料工位，气缸夹紧与真空吸盘配合，光幕或急停触发安全中止…"
        />
      </div>

      <div className="gf-step-desc__examples" aria-label="示例描述">
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            className="gf-step-desc__example"
            disabled={busy}
            onClick={() => onPromptChange(example)}
            title="仅填入输入框，仍由真实后端解析"
          >
            {example}
          </button>
        ))}
      </div>

      <div className="gf-step-desc__sketch">
        <div className="gf-step-desc__sketch-head">
          {hasIr ? "设备与步序草图" : "设备与步序草图（尚未生成）"}
        </div>
        {hasIr && sketch ? (
          <div className="gf-step-desc__sketch-grid">
            {SKETCH_CELLS.map((cell) => (
              <div className="gf-step-desc__sketch-cell" key={cell.key}>
                <span className="gf-step-desc__sketch-num">
                  {Number(sketch[cell.key] ?? 0)}
                </span>
                <span className="gf-step-desc__sketch-label">{cell.label}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="gf-muted">
            还没有草图。填写上方描述并点击主按钮，草图会由后端解析结果生成，不会预置任何内容。
          </div>
        )}
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
        {hasIr ? (
          <button
            type="button"
            className="gf-btn gf-btn--primary gf-wiz__primary"
            disabled={busy || !canNext}
            onClick={onNext}
          >
            下一步：连线
          </button>
        ) : (
          <button
            type="button"
            className="gf-btn gf-btn--primary gf-wiz__primary"
            disabled={busy || trimmed.length === 0}
            onClick={onSubmit}
          >
            {busy ? "处理中…" : "生成草图"}
          </button>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--ghost"
          onClick={onOpenEngineering}
        >
          工程视角
        </button>
      </div>
    </div>
  );
};
