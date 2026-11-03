import React, { useEffect, useMemo, useState } from "react";
import {
  formatElapsed,
  topbarChips,
  overflowCount,
  LONG_TASK_LABELS,
  type LongTask,
} from "../state/longTasks";

/* ==========================================================================
   LongTaskChips — 顶栏长任务芯片（契约：state/longTasks.ts）
   页面级常驻"正在干活"指示：重构流水线 / 编译回写 / AI 分析等后台作业
   在跑时，于 46px 细顶栏以 ~24px 方角小条并列展示（任何布局可见）。
   本会话任务在前，跨会话任务殿后并标「其他会话」；超出 3 枚折叠为 "+N"。
   running 圆点 1.1s 呼吸（IEC 信号灯语义，reduced-motion 下压平）；
   done 整枚转 --run 绿、error 圆点转 --fault 红——终态收尾展示 2.5s 后
   由父层 sweepFinished 清扫，组件不设定时器，只要 done 也照常渲染。
   纯展示：不拉数据、不持业务状态；空（无 running 且无收尾）时返回 null。
   点击/Enter/Space → onJump(task)：App 跳回该会话并滚动到 messageId。
   ========================================================================== */

export interface LongTaskChipsProps {
  /** 全量任务（App 传 longTasks；含 running 与收尾窗口内的 done/error） */
  tasks: LongTask[];
  /** 当前会话（本会话任务排前，其余标「其他会话」） */
  currentSessionId: string | null;
  /** 点击芯片：跳回该会话并滚动到 messageId */
  onJump: (task: LongTask) => void;
}

/** 顶栏最多并列芯片数，超出折叠为 "+N" */
const MAX_CHIPS = 3;

export const LongTaskChips: React.FC<LongTaskChipsProps> = ({
  tasks,
  currentSessionId,
  onJump,
}) => {
  const hasRunning = tasks.some((t) => t.status === "running");

  // 1s ticker：仅当存在 running 任务时走表，全停即清；now 只驱动 running 计时。
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!hasRunning) return;
    setNow(Date.now()); // 首个 running 出现立即校表，避免陈旧 now 显示 0:00
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [hasRunning]);

  // 芯片集合 = topbarChips（running，当前会话优先 ≤MAX）∪ 尚未被父层清扫的
  // done/error（收尾闪现）。合并后按 topbarChips 同序排列（本会话在前、各按
  // 启动时间升序），任务转终态时不挪位、只换色。
  const chips = useMemo(() => {
    const merged: LongTask[] = [
      ...topbarChips(tasks, currentSessionId, MAX_CHIPS),
      ...tasks.filter((t) => t.status !== "running"),
    ];
    const seen = new Set<string>();
    return merged
      .filter((t) => (seen.has(t.id) ? false : (seen.add(t.id), true)))
      .sort(
        (a, b) =>
          Number(a.sessionId !== currentSessionId) -
            Number(b.sessionId !== currentSessionId) || a.startedAt - b.startedAt,
      );
  }, [tasks, currentSessionId]);

  const overflow = overflowCount(tasks, currentSessionId, MAX_CHIPS);

  if (chips.length === 0) return null;

  return (
    <div className="ltc">
      {chips.map((task) => {
        const done = task.status === "done";
        const error = task.status === "error";
        const label = task.title || LONG_TASK_LABELS[task.kind];
        // 终态计时冻结在 updatedAt；running 随 ticker 走
        const elapsed = formatElapsed(
          task.startedAt,
          done || error ? task.updatedAt : now,
        );
        const tip = task.detail || task.errorText || "进行中";
        const other = task.sessionId !== currentSessionId;
        const stateText = done ? "已完成" : error ? "出错" : "进行中";
        return (
          <button
            key={task.id}
            type="button"
            className={
              "ltc-chip" + (done ? " ltc-chip--done" : "") + (error ? " ltc-chip--error" : "")
            }
            title={tip}
            aria-label={`${label}，${stateText}，${elapsed}${other ? "（其他会话）" : ""}`}
            onClick={() => onJump(task)}
          >
            <span className="ltc-chip__dot" aria-hidden="true" />
            <span className="ltc-chip__title">{label}</span>
            <span className="ltc-chip__elapsed">{elapsed}</span>
            {other && <span className="ltc-chip__other">其他会话</span>}
          </button>
        );
      })}
      {overflow > 0 && (
        <span className="ltc-chip ltc-overflow" title={`还有 ${overflow} 个后台任务`}>
          +{overflow}
        </span>
      )}
    </div>
  );
};
