import type { CanvasStateData } from "../canvas/types";

/**
 * 导入成功后的工程简报(纯函数,vitest 覆盖):
 * 统计画布结构 + 动态生成 4 条建议问题,由 App.tsx 在导入成功后
 * 以 system 消息形式追加进当前会话。
 */
export interface ProjectBriefing {
  projectName: string;
  blockCount: number;
  /** status != synced 或 language != DB 的块数(可转换/待翻译候选) */
  convertibleCount: number;
  /** errors 含「待人工确认」的块数(AF 转换 HITL) */
  pendingCount: number;
  /** interface 变量为空且 block_type 非 DB 的块数(仅接口占位) */
  interfaceOnlyCount: number;
  /** canvas.tags 数 */
  tagCount: number;
  /** 所有块 networks 数之和 */
  networkCount: number;
  /** 恰好 4 条建议问题 */
  suggestions: string[];
}

/** AF 导入网关写入 errors 的 HITL 标记前缀(af_import.py PENDING_NOTE_PREFIX) */
const PENDING_MARKER = "待人工确认";

/* —— 建议问题文案 —— */
const SUGGEST_UNDERSTAND = "请帮我梳理这个工程的整体结构和各逻辑块的职责分工。";
const SUGGEST_SAFETY = "工程里有哪些安全联锁与急停逻辑?请逐条梳理。";
const SUGGEST_TIMING = "请为关键工艺流程画一张时序图,说明信号先后关系。";
const SUGGEST_REFACTOR = "哪些逻辑块的结构最混乱?请给出重构优先级与方案。";
const SUGGEST_SIMULATE = "请结合 HMI 画面与 PLC 变量,仿真一次典型操作流程。";

/**
 * 动态组合恰好 4 条建议:
 * - 理解工程 / 安全联锁恒定保留;
 * - 有 draft 块 → 重构 优先插入;有 HMI → 仿真 插入;
 * - 无 draft 无 HMI 时回落默认四条(理解/安全/时序/重构)。
 */
function buildSuggestions(hasDraft: boolean, hasHmi: boolean): string[] {
  const pool: string[] = [SUGGEST_UNDERSTAND, SUGGEST_SAFETY];
  if (hasDraft) pool.push(SUGGEST_REFACTOR);
  if (hasHmi) pool.push(SUGGEST_SIMULATE);
  pool.push(SUGGEST_TIMING);
  if (!hasDraft) pool.push(SUGGEST_REFACTOR);
  return pool.slice(0, 4);
}

export function buildBriefing(canvas: CanvasStateData): ProjectBriefing {
  const blocks = Object.values(canvas?.blocks ?? {});
  const hasDraft = blocks.some((b) => b.status === "draft");
  const hasHmi = Object.keys(canvas?.hmi_widgets ?? {}).length > 0;
  return {
    projectName: canvas?.project_name ?? "",
    blockCount: blocks.length,
    convertibleCount: blocks.filter(
      (b) => b.status !== "synced" || b.language !== "DB",
    ).length,
    pendingCount: blocks.filter((b) =>
      (b.errors ?? []).some((e) => typeof e === "string" && e.includes(PENDING_MARKER)),
    ).length,
    interfaceOnlyCount: blocks.filter(
      (b) => b.block_type !== "DB" && (b.interface ?? []).length === 0,
    ).length,
    tagCount: Object.keys(canvas?.tags ?? {}).length,
    networkCount: blocks.reduce((sum, b) => sum + (b.networks?.length ?? 0), 0),
    suggestions: buildSuggestions(hasDraft, hasHmi),
  };
}

/** 简报 → Markdown system 消息:粗体表头 + 统计 + 编号建议 */
export function briefingToMessage(b: ProjectBriefing): string {
  const lines: string[] = [
    `**工程简报 · ${b.projectName || "未命名工程"}**`,
    "",
    `- 逻辑块:${b.blockCount} 个(可转换 ${b.convertibleCount} · 待人工确认 ${b.pendingCount} · 仅接口 ${b.interfaceOnlyCount})`,
    `- 网络:${b.networkCount} 段 · 物理标签:${b.tagCount} 个`,
    "",
    "**建议从这里开始问:**",
  ];
  b.suggestions.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
  return lines.join("\n");
}
