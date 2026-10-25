import type { FC } from "react";
import { TASK_KIND_LABELS, type TaskKind } from "../state/requirements";
import "./requirements.css";

/* ==========================================================================
   TaskQuickBar — 任务快捷条（契约 22 §3，正式版）
   四个任务入口（理解工程 / 诊断问题 / 完善工艺逻辑 / 重构程序），每个按钮带
   一句话说明 tooltip；低显著度贴顶栏下沿——学 index.css 的 .tabstrip/.tab
   风格：surface-2 托盘 + 透明按钮，选中态仅提亮底色 + 一根钢蓝内侧标线，
   不引入新的强调色。active 由 App 持有（F1 接线：onTask("improve") → 聚焦
   输入框预填任务前缀；需求卡草稿流由 F1 调 state/requirements.requestDraft）。
   本组件纯展示：不拉数据、不持有状态。TaskKind 从这里 re-export（契约 §3）。
   ========================================================================== */

// 契约 §3：TaskQuickBar 导出 TaskKind（App.tsx 从这里 import）
export type { TaskKind };

/** 四个入口的一句话说明（按钮 title，帮助工程师理解入口语义） */
const TASK_DESCRIPTIONS: Record<TaskKind, string> = {
  understand: "通读工程结构、块职责与信号流向，先弄清现有逻辑再动手",
  diagnose: "从故障或异常表现出发，带证据定位根因",
  improve: "在既有工艺上补全或改进逻辑，建议先生成需求卡确认意图",
  refactor: "在不改变工艺行为的前提下重构程序结构",
};

/** 展示顺序 = 契约顺序：理解 → 诊断 → 完善 → 重构 */
const TASK_ORDER: TaskKind[] = ["understand", "diagnose", "improve", "refactor"];

export interface TaskQuickBarProps {
  /** 当前激活的任务（null = 未选）；再次点击同一任务由父层决定是否取消 */
  active: TaskKind | null;
  /** 点击任务入口（App 决定聚焦输入框 / 预填前缀 / 打开需求卡草稿流） */
  onTask: (t: TaskKind) => void;
}

export const TaskQuickBar: FC<TaskQuickBarProps> = ({ active, onTask }) => (
  <nav className="tqb" aria-label="任务快捷入口">
    <span className="tqb__label">任务</span>
    <div className="tqb__group" role="group" aria-label="选择任务类型">
      {TASK_ORDER.map((t) => {
        const on = active === t;
        return (
          <button
            key={t}
            type="button"
            className={"tqb-btn" + (on ? " tqb-btn--on" : "")}
            aria-pressed={on}
            title={`${TASK_KIND_LABELS[t]} · ${TASK_DESCRIPTIONS[t]}`}
            onClick={() => onTask(t)}
          >
            {TASK_KIND_LABELS[t]}
          </button>
        );
      })}
    </div>
  </nav>
);
