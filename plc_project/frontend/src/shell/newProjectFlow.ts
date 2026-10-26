/**
 * 新建工程流(docs/23-af-builtin-contract.md §1)——纯逻辑层,F1(App.tsx)接线用。
 *
 * 两个纯部件(无 React 依赖,vitest 直接覆盖):
 *   1. sanitizeProjectName —— 把需求卡 intent_summary 洗成合法 SCL 标识
 *      (字母开头,仅字母/数字/下划线),作为最小创建确认的项目名默认值;
 *   2. newProjectFlowReducer —— 新建工程流状态机:
 *      idle →(ENTRY_CLICK,空 prompt)guiding →(DRAFT_OPENED)requirement
 *      →(INTENT_CONFIRMED)confirm →(CREATE_SUBMIT)creating →(CREATE_SETTLED)idle。
 *      状态机只管阶段与载荷;抽屉/对话框渲染、创建链与 N 线端点调用都在 App.tsx。
 */
import type { Requirement } from "../state/requirements";

/* ------------------------------------------------------------------ */
/* intent_summary → 合法项目名                                          */
/* ------------------------------------------------------------------ */

/** 项目名默认值长度上限(TIA 标识符上限远大于此,取工程可读长度) */
export const PROJECT_NAME_MAX_LEN = 32;

/** 洗不出任何合法字符时的兜底名(保证默认值永远可直接确认) */
export const DEFAULT_PROJECT_NAME = "PLC_Project";

/**
 * 把任意文本(通常是需求卡 intent_summary)洗成合法 SCL 标识:
 * - 非 [A-Za-z0-9_] 字符段折叠为单个下划线(中文/标点/空格全部洗掉);
 * - 必须字母开头:砍掉开头的数字与下划线;
 * - 折叠连续下划线、去首尾下划线、截断到 PROJECT_NAME_MAX_LEN;
 * - 结果为空(如纯中文意图)回退 fallback。
 */
export function sanitizeProjectName(summary: unknown, fallback: string = DEFAULT_PROJECT_NAME): string {
  const raw = String(summary ?? "");
  let washed = raw.replace(/[^A-Za-z0-9_]+/g, "_");
  washed = washed.replace(/^[^A-Za-z]+/, "");
  washed = washed.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  washed = washed.slice(0, PROJECT_NAME_MAX_LEN).replace(/_+$/g, "");
  return washed || fallback;
}

/** 项目名合法性(与 CreateBlockDialog 的 SCL 标识规则同口径:字母或下划线开头) */
const PROJECT_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function isValidProjectName(name: unknown): boolean {
  const s = String(name ?? "").trim();
  return s.length > 0 && PROJECT_NAME_RE.test(s);
}

/* ------------------------------------------------------------------ */
/* 新建工程流状态机                                                     */
/* ------------------------------------------------------------------ */

/**
 * - idle:        未在流中(启动屏两入口之外的默认态);
 * - guiding:     点击「新建工程」但输入框为空 → 复用 improve 任务引导预填,
 *                等工程师补工艺描述后再进需求卡;
 * - requirement: 需求卡草稿抽屉流活跃(ENTRY_CLICK 带 prompt 或 DRAFT_OPENED);
 * - confirm:     工艺意图已确认 → 弹最小创建确认(项目名/目标目录);
 * - creating:    已提交创建(创建链 + N 线逻辑生成在途,按钮锁定)。
 */
export type NewProjectFlowPhase = "idle" | "guiding" | "requirement" | "confirm" | "creating";

export interface NewProjectFlowState {
  phase: NewProjectFlowPhase;
  /** 本流持有的需求卡;确认工艺意图后写入(confirmation_status=confirmed) */
  requirement: Requirement | null;
  /** 最小创建确认的项目名默认值(intent_summary 洗成合法标识) */
  defaultProjectName: string;
}

export const NEW_PROJECT_FLOW_IDLE: NewProjectFlowState = {
  phase: "idle",
  requirement: null,
  defaultProjectName: "",
};

export type NewProjectFlowEvent =
  /** 点击启动屏「新建工程」入口;promptText 为当前指令输入框文本 */
  | { type: "ENTRY_CLICK"; promptText?: unknown }
  /** 需求卡草稿抽屉已打开(仅在 guiding 态会把流带进 requirement) */
  | { type: "DRAFT_OPENED" }
  /** 需求卡「确认工艺意图」回调(仅在流内生效;流外确认不弹创建) */
  | { type: "INTENT_CONFIRMED"; requirement: Requirement }
  /** 取消最小创建确认 → 回 requirement(需求卡保留,可再次进入确认) */
  | { type: "CREATE_CANCEL" }
  /** 最小创建确认「确认创建」→ 创建链开跑 */
  | { type: "CREATE_SUBMIT" }
  /** 创建链结束(成功 settle / 失败兜底都归位) */
  | { type: "CREATE_SETTLED" }
  /** 强制归位(导入工程 / 切换会话等离开本流的动作) */
  | { type: "RESET" };

export function newProjectFlowReducer(
  state: NewProjectFlowState,
  event: NewProjectFlowEvent,
): NewProjectFlowState {
  switch (event.type) {
    case "ENTRY_CLICK": {
      if (state.phase === "creating") return state; // 创建在途,忽略重复点击
      // 本流内已确认过工艺意图:再次点击直达最小创建确认
      if (state.requirement?.confirmation_status === "confirmed") {
        return {
          phase: "confirm",
          requirement: state.requirement,
          defaultProjectName: sanitizeProjectName(state.requirement.intent_summary),
        };
      }
      const hasPrompt = String(event.promptText ?? "").trim().length > 0;
      return { ...state, phase: hasPrompt ? "requirement" : "guiding" };
    }
    case "DRAFT_OPENED": {
      // improve 任务(流外)打开草稿不得误入流;guiding 态打开即随流进入草稿
      return state.phase === "guiding" ? { ...state, phase: "requirement" } : state;
    }
    case "INTENT_CONFIRMED": {
      if (
        state.phase !== "requirement" &&
        state.phase !== "guiding" &&
        state.phase !== "confirm"
      ) {
        return state; // 流外确认(idle/creating):行为不变,不弹创建确认
      }
      return {
        phase: "confirm",
        requirement: event.requirement,
        defaultProjectName: sanitizeProjectName(event.requirement.intent_summary),
      };
    }
    case "CREATE_CANCEL":
      return state.phase === "confirm" ? { ...state, phase: "requirement" } : state;
    case "CREATE_SUBMIT":
      return state.phase === "confirm" ? { ...state, phase: "creating" } : state;
    case "CREATE_SETTLED":
    case "RESET":
      return NEW_PROJECT_FLOW_IDLE;
    default:
      return state;
  }
}
