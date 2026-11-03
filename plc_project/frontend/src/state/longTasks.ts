/**
 * LongTaskCenter —— 统一长任务模型(纯函数层,契约由 App/LongTaskChips/ChatDock 共同消费)。
 *
 * 长任务 = 重构流水线 / 编译回写 / AI 分析回答等耗时数十秒~数十分钟、且**期间对话
 * 必须继续可用**的后台作业。每个任务:
 *   - 跟随自己的 sessionId 跑完(切会话不中止),结果写回所属会话;
 *   - 顶栏芯片(任何布局可见)与对话坞任务卡(聊天面细节)渲染同一份数据;
 *   - messageId = 结果落点消息 id,点击芯片跳回会话并滚动到该消息。
 *
 * 编辑类指令(要改画布的 chat-ops)不进本中心——保持串行,防画布写竞态(决策点 2)。
 */
import type { PipelineStageView } from "./refactorPipeline";

export type LongTaskKind = "refactor_pipeline" | "compile" | "llm_answer";
export type LongTaskStatus = "running" | "done" | "error";

export interface LongTask {
  /** 唯一 id(惯例与锚定消息 phId / 编译 jobId 一致) */
  id: string;
  /** 所属会话 id(结果写回目标;切会话不中止) */
  sessionId: string;
  kind: LongTaskKind;
  /** 展示标题:重构流水线 / 编译回写 / AI 分析 */
  title: string;
  /** epoch ms */
  startedAt: number;
  updatedAt: number;
  status: LongTaskStatus;
  /** 阶段型进度(流水线五段/编译阶段);llm_answer 无 */
  stages?: PipelineStageView[];
  /** 文本型进度:当前阶段说明 / 已输出字数等 */
  detail?: string;
  /** 结果落点消息 id(点击芯片滚动定位) */
  messageId?: string;
  /** error 态的错误摘要 */
  errorText?: string;
}

/** 进行中任务,按启动时间升序(先启动在前) */
export function activeTasks(tasks: LongTask[]): LongTask[] {
  return tasks.filter((t) => t.status === "running").sort((a, b) => a.startedAt - b.startedAt);
}

/** 某会话的进行中任务 */
export function tasksBySession(tasks: LongTask[], sessionId: string): LongTask[] {
  return activeTasks(tasks).filter((t) => t.sessionId === sessionId);
}

/** 非当前会话的进行中任务(顶栏芯片标注「其他会话」) */
export function tasksForOtherSessions(tasks: LongTask[], sessionId: string): LongTask[] {
  return activeTasks(tasks).filter((t) => t.sessionId !== sessionId);
}

/** 按 id 替换或前插(upsert);完成态保留(组件据此显示 2s 绿色收尾) */
export function upsertTask(tasks: LongTask[], task: LongTask): LongTask[] {
  const idx = tasks.findIndex((t) => t.id === task.id);
  if (idx === -1) return [task, ...tasks];
  const next = tasks.slice();
  next[idx] = task;
  return next;
}

/** 局部补丁(进度刷新);目标不存在时忽略 */
export function patchTask(
  tasks: LongTask[],
  id: string,
  patch: Partial<Omit<LongTask, "id">>,
): LongTask[] {
  const idx = tasks.findIndex((t) => t.id === id);
  if (idx === -1) return tasks;
  const next = tasks.slice();
  next[idx] = { ...next[idx], ...patch, updatedAt: Date.now() };
  return next;
}

/** 收终态;目标不存在时忽略 */
export function finishTask(
  tasks: LongTask[],
  id: string,
  status: LongTaskStatus,
  errorText?: string,
): LongTask[] {
  return patchTask(tasks, id, { status, errorText });
}

/** 已结束且超过 keepMs 的任务可清除(收尾展示窗口) */
export function sweepFinished(tasks: LongTask[], keepMs = 2500, now = Date.now()): LongTask[] {
  return tasks.filter(
    (t) => t.status === "running" || now - t.updatedAt < keepMs,
  );
}

/** 顶栏芯片集合:当前会话优先,跨会话在后;最多 max 个,溢出计数由组件渲染 */
export function topbarChips(tasks: LongTask[], sessionId: string, max = 3): LongTask[] {
  const mine = tasksBySession(tasks, sessionId);
  const others = tasksForOtherSessions(tasks, sessionId);
  return [...mine, ...others].slice(0, max);
}

/** 顶栏溢出数(展示 max 之后还有几个) */
export function overflowCount(tasks: LongTask[], sessionId: string, max = 3): number {
  return Math.max(0, activeTasks(tasks).length - max);
}

/** 秒表文案 "m:ss" / 超 1h "h:mm:ss";负值防御为 0:00 */
export function formatElapsed(startedAt: number, now: number): string {
  const secs = Math.max(0, Math.floor((now - startedAt) / 1000));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

/** kind → 图标语义色钩子(组件用;此处只给文字标签,样式在 CSS) */
export const LONG_TASK_LABELS: Record<LongTaskKind, string> = {
  refactor_pipeline: "重构流水线",
  compile: "编译回写",
  llm_answer: "AI 分析",
};
