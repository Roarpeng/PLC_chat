/* ==========================================================================
   smartRoute —— 智能标签路由（契约 25 §2「智能标签路由规则」，L 线）
   纯函数：最新一条 AI 回答文本 + 轻量上下文 → 画布标签切换建议。
   调用方（App）在 AI 回答 settle 后调用；命中即切标签，canvas 未打开
   （chat 态）时按 autoOpen 自动滑入 split。无命中返回 null（绝不乱切）。
   vitest 覆盖见 smartRoute.test.ts。
   ========================================================================== */

/** 画布面板的七个标签（WorkspacePanel 竖向图标栏同一集合） */
export type CanvasTab = "graph" | "scl" | "hmi" | "vars" | "mermaid" | "req" | "review";

export interface SmartRouteContext {
  /** 当前画布选中块（无下划线的块名如 ConveyorCtrl 也能借此命中 SCL 路由） */
  selectedBlock?: string;
  /** 最新回答里是否已检出 ```mermaid 围栏（App 用 extractMermaidSource 预判） */
  hasMermaid?: boolean;
  /** 画布当前草稿块数（>0 时「生成/创建/新增」才路由到全局图） */
  draftCount?: number;
}

export interface SmartRouteResult {
  tab: CanvasTab;
  /** canvas 未打开（chat 态）时为 true → 自动滑入；画布已开时调用方可忽略 */
  autoOpen: boolean;
  /** scl 路由命中时：回答里第一个被引用的块名（App 用于 setSelectedBlock） */
  focusBlock?: string;
}

/** 块名模式：大写字母开头、含下划线的标识符（FB_Motor / OB_MAIN / EM_CLAMP_1 / U1_HR001） */
const BLOCK_NAME_RE = /\b[A-Z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/g;

/** 长得像块名、但只是 SCL 关键字/分区名的词：不触发路由（denylist） */
const NON_BLOCK_KEYWORDS = new Set([
  "VAR_INPUT",
  "VAR_OUTPUT",
  "VAR_IN_OUT",
  "VAR_STAT",
  "VAR_TEMP",
  "VAR_GLOBAL",
  "END_VAR",
  "BEGIN_END",
]);

/** 正则元字符转义（selectedBlock 精确词匹配用） */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 回答里第一个块名引用；无 → null（导出供测试与潜在复用） */
export function findBlockReference(text: string): string | null {
  for (const match of text.matchAll(BLOCK_NAME_RE)) {
    const name = match[0];
    if (!NON_BLOCK_KEYWORDS.has(name)) return name;
  }
  return null;
}

/** 当前选中块是否被原词提及（词边界精确匹配，大小写敏感——块名本就区分大小写） */
function mentionsSelected(text: string, selectedBlock: string | undefined): string | null {
  const name = selectedBlock?.trim();
  if (!name) return null;
  return new RegExp(`\\b${escapeRegExp(name)}\\b`).test(text) ? name : null;
}

/**
 * 智能标签路由（规则表见契约 §2；命中即返回，顺序即优先级）：
 * 1. 回答含块名引用（当前选中块原词，或大写开头含下划线的标识符）→ scl + focusBlock
 * 2. hasMermaid → mermaid（渲染最新时序图）
 * 3. draftCount>0 且回答含「生成|创建|新增」→ graph（高亮 draft 块）
 * 4. 回答含「变量|交叉引用」→ vars
 * 5. 回答含「HMI|触摸屏|仿真」→ hmi
 * 6. 回答含「回写|编译」→ review（打开最新变更事务）
 * 7. 无命中 → null（不切）
 * autoOpen 恒为 true：路由命中意味着画布值得看，画布未打开时就滑入。
 */
export function smartRoute(
  lastMessage: string,
  context: SmartRouteContext = {},
): { tab: CanvasTab; autoOpen: boolean; focusBlock?: string } | null {
  const text = typeof lastMessage === "string" ? lastMessage : "";
  if (!text.trim()) return null;

  /* ① 块名引用 → SCL（选中块原词优先：它就是这次对话的主角） */
  const bySelection = mentionsSelected(text, context.selectedBlock);
  const focusBlock = bySelection ?? findBlockReference(text);
  if (focusBlock) return { tab: "scl", autoOpen: true, focusBlock };

  /* ② Mermaid 生成完成 → 时序图 */
  if (context.hasMermaid) return { tab: "mermaid", autoOpen: true };

  /* ③ 逻辑块生成/修改 → 全局图（只有真有草稿时才值得看图） */
  if ((context.draftCount ?? 0) > 0 && /生成|创建|新增/.test(text)) {
    return { tab: "graph", autoOpen: true };
  }

  /* ④ 变量 / 交叉引用 */
  if (/变量|交叉引用/.test(text)) return { tab: "vars", autoOpen: true };

  /* ⑤ HMI / 触摸屏 / 仿真 */
  if (/HMI|触摸屏|仿真/.test(text)) return { tab: "hmi", autoOpen: true };

  /* ⑥ 回写 / 编译 → 变更审查 */
  if (/回写|编译/.test(text)) return { tab: "review", autoOpen: true };

  /* ⑦ 无命中 */
  return null;
}

/** ```mermaid 围栏（与 ChatDock 同一宽容口径：开栏行可带尾缀，闭栏前容忍空白） */
const MERMAID_FENCE_RE = /```mermaid[^\n]*\n([\s\S]*?)```/g;

/**
 * 提取文本里最后一份 Mermaid 源码（对话生成的图自动流入画布时序图标签）。
 * 无围栏 → null。导出供 App 在回答 settle 时更新 latestMermaid。
 */
export function extractMermaidSource(text: string): string | null {
  if (typeof text !== "string") return null;
  let last: string | null = null;
  for (const match of text.matchAll(MERMAID_FENCE_RE)) {
    const body = match[1].trim();
    if (body) last = body;
  }
  return last;
}
