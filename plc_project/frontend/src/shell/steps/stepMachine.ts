/**
 * 4 步主链 · 纯函数状态机 / 中文业务文案 / 连线预校验。
 *
 * 设计约束（02-architecture.md §3.1 / §7）：
 * - 本模块不触碰 DOM、不发起任何请求、不 import 任何请求函数；
 * - `step / completed / engineeringOpen / engineeringGroups / data` 的唯一真值在
 *   GreenfieldChannel 的 useReducer；TOGGLE_* 是纯前端视图位，绝不触发后端调用；
 * - 主链 4 页可见文案一律业务中文，绝不出现内部契约术语；
 * - 折叠态不替代、不跳过任何写入门禁；`fetchEngineeringSummary` 属于步 3 主链动作。
 */
import type { Connection } from "@xyflow/react";
import {
  GF_LAUNCH_CONTEXT_KEY,
  GF_PROJECT_KEY,
  GF_SESSION_KEY,
  type GFDeliverySummary,
  type GFFidelityStatus,
  type GFWhitelist,
} from "../../state/greenfield";

export type WizardStep = 1 | 2 | 3 | 4;
export type EngGroupKey = "contract" | "fidelity" | "actions" | "diff" | "scl" | "machine";

/** 4 个阶段页的通用基座（展示层，零后端知识）。 */
export interface StepBaseProps {
  step: WizardStep;
  busy: boolean;
  error: string;
  completed: boolean;
  onBackStep?: () => void;
  onNext?: () => void;
  onOpenEngineering: () => void;
  onClearError?: () => void;
}

/** 每步的数据；全部为主链可见的业务语言字段，零内部契约术语。 */
export interface WizardData {
  /** 步 1 唯一输入框的值（全流程唯一「工艺描述」输入）。 */
  prompt: string;
  /** 已成功生成草图的描述原文（步 3「你要做的事」）。 */
  submittedPrompt: string;
  /** 步 2 当前连线类型，取自 whitelist.edge_kinds[0]。 */
  selectedEdgeKind: string;
  /** 步 2 非法连线的中文提示。 */
  linkError: string;
  /** 步 3 门禁未满足时的中文「还差什么 / 去哪补」。 */
  confirmNote: string;
  /** /generate 成功且 /state 返回 delivery_summary 后置 true。 */
  deliveryReady: boolean;
}

export interface WizardState {
  step: WizardStep;
  data: WizardData;
  completed: Record<WizardStep, boolean>;
  engineeringOpen: boolean;
  engineeringGroups: Record<EngGroupKey, boolean>;
  busy: boolean;
  error: string;
}

export type WizardAction =
  | { type: "SET_PROMPT"; value: string }
  | { type: "SET_SUBMITTED_PROMPT"; value: string }
  | { type: "SET_EDGE_KIND"; value: string }
  | { type: "SET_LINK_ERROR"; value: string }
  | { type: "SET_CONFIRM_NOTE"; value: string }
  | { type: "SET_DELIVERY_READY"; value: boolean }
  | { type: "SET_BUSY"; value: boolean }
  | { type: "SET_ERROR"; value: string }
  | { type: "MARK_COMPLETE"; step: WizardStep }
  | { type: "GO"; step: WizardStep }
  | { type: "NEXT" }
  | { type: "BACK" }
  | { type: "TOGGLE_ENGINEERING"; value?: boolean }
  | { type: "TOGGLE_GROUP"; key: EngGroupKey }
  | { type: "REENTER_EDIT" }
  | { type: "RESET" };

const INITIAL_DATA: WizardData = {
  prompt: "",
  submittedPrompt: "",
  selectedEdgeKind: "",
  linkError: "",
  confirmNote: "",
  deliveryReady: false,
};

const INITIAL_COMPLETED: Record<WizardStep, boolean> = {
  1: false,
  2: false,
  3: false,
  4: false,
};

const INITIAL_GROUPS: Record<EngGroupKey, boolean> = {
  contract: false,
  fidelity: false,
  actions: false,
  diff: false,
  scl: false,
  machine: false,
};

function freshInitial(): WizardState {
  return {
    step: 1,
    data: { ...INITIAL_DATA },
    completed: { ...INITIAL_COMPLETED },
    engineeringOpen: false,
    engineeringGroups: { ...INITIAL_GROUPS },
    busy: false,
    error: "",
  };
}

export const INITIAL_WIZARD_STATE: WizardState = freshInitial();

/** 4 步主链唯一状态迁移；GO / BACK / NEXT 均为纯前端，不重放任何请求。 */
export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "SET_PROMPT":
      return { ...state, data: { ...state.data, prompt: action.value } };
    case "SET_SUBMITTED_PROMPT":
      return { ...state, data: { ...state.data, submittedPrompt: action.value } };
    case "SET_EDGE_KIND":
      return { ...state, data: { ...state.data, selectedEdgeKind: action.value } };
    case "SET_LINK_ERROR":
      return { ...state, data: { ...state.data, linkError: action.value } };
    case "SET_CONFIRM_NOTE":
      return { ...state, data: { ...state.data, confirmNote: action.value } };
    case "SET_DELIVERY_READY":
      return { ...state, data: { ...state.data, deliveryReady: action.value } };
    case "SET_BUSY":
      return { ...state, busy: action.value };
    case "SET_ERROR":
      return { ...state, error: action.value };
    case "MARK_COMPLETE":
      return {
        ...state,
        completed: { ...state.completed, [action.step]: true },
      };
    case "GO":
      return { ...state, step: action.step };
    case "NEXT": {
      const next = Math.min(4, state.step + 1) as WizardStep;
      return { ...state, step: next };
    }
    case "BACK": {
      const previous = Math.max(1, state.step - 1) as WizardStep;
      return { ...state, step: previous };
    }
    case "TOGGLE_ENGINEERING":
      return {
        ...state,
        engineeringOpen: action.value === undefined ? !state.engineeringOpen : action.value,
      };
    case "TOGGLE_GROUP":
      return {
        ...state,
        engineeringGroups: {
          ...state.engineeringGroups,
          [action.key]: !state.engineeringGroups[action.key],
        },
      };
    case "REENTER_EDIT":
      return {
        ...state,
        step: 2,
        completed: { ...state.completed, 2: false, 3: false, 4: false },
        data: {
          ...state.data,
          confirmNote: "",
          linkError: "",
          deliveryReady: false,
        },
      };
    case "RESET":
      return freshInitial();
    default:
      return state;
  }
}

export const STEP_META: ReadonlyArray<{
  step: WizardStep;
  title: string;
  kicker: string;
  primaryLabel: string;
  ground: string;
}> = [
  {
    step: 1,
    title: "描述你要做的事",
    kicker: "工位 01 · 工艺描述",
    primaryLabel: "生成草图",
    ground: "#c3cbe5",
  },
  {
    step: 2,
    title: "把设备连起来",
    kicker: "工位 02 · 手动连线",
    primaryLabel: "下一步：确认",
    ground: "#cfd3cb",
  },
  {
    step: 3,
    title: "确认并生成",
    kicker: "工位 03 · 确认",
    primaryLabel: "确认并生成工程包",
    ground: "#e6dccd",
  },
  {
    step: 4,
    title: "工程包已就绪",
    kicker: "工位 04 · 交付",
    primaryLabel: "下载工程包",
    ground: "#bcc7e0",
  },
];

/** 步 3 主链必须遵守的合法调用顺序（禁止跳过 /confirm 直调 /generate）。 */
export const CONFIRM_CHAIN: readonly string[] = [
  "fetchEngineeringSummary",
  "confirmSpec",
  "generateProjectPackage",
  "refresh",
  "GO:4",
];

export interface AdvanceContext {
  hasIr: boolean;
  edges: number;
  reportOk: boolean;
  canConfirm: boolean;
  stage: string;
  hasDelivery: boolean;
}

/** 前进合法性（纯函数，ctx 由 Channel 从 /state 派生，不自行请求）。 */
export function canAdvance(
  step: WizardStep,
  ctx: AdvanceContext,
): { ok: boolean; reason: string } {
  if (step === 1) {
    return ctx.hasIr
      ? { ok: true, reason: "" }
      : { ok: false, reason: "请先描述工艺并生成首版结构图，再进入连线。" };
  }
  if (step === 2) {
    return ctx.edges > 0 && ctx.reportOk
      ? { ok: true, reason: "" }
      : { ok: false, reason: "请先在画布上连出至少一条设备关系，并完成结构校验。" };
  }
  if (step === 3) {
    const stageReady = ctx.stage === "LINKABLE" || ctx.stage === "VALIDATING";
    return ctx.canConfirm && stageReady
      ? { ok: true, reason: "" }
      : {
          ok: false,
          reason: "确认所需的前置尚未齐备，请查看工程视角补齐后再继续。",
        };
  }
  return {
    ok: false,
    reason: ctx.hasDelivery
      ? "本轮工程包已交付，可下载；如需修改请点「重新调整」。"
      : "本轮工程包尚未就绪，请先完成确认与生成。",
  };
}

/** 中文业务措辞，主链零术语（绝不出现内部契约字段名）。 */
export type FidelityView =
  | (Partial<GFFidelityStatus> & {
      status?: string;
      note?: string;
      fidelity_ok?: boolean | null;
    })
  | null
  | undefined;

export function formatFidelityBusiness(f: FidelityView): {
  title: string;
  detail: string;
  ok: boolean | null;
} {
  const verdict = f?.fidelity_ok;
  if (verdict === true) {
    return {
      title: "还原一致性校验：达标",
      detail: "本轮工程包与冻结规格的还原一致性校验已通过，可直接下载。",
      ok: true,
    };
  }
  if (verdict === false) {
    return {
      title: "还原一致性校验：尚未达标（不影响本轮工程包导出）",
      detail: "本轮工程包仍可下载；核对明细可在「工程视角」逐项查看。",
      ok: false,
    };
  }
  return {
    title: "还原一致性校验：待真机核验，本轮不判定（不影响本轮工程包导出）",
    detail: "本轮不给出达标或未达标结论；工程包已可下载，真机核验结论另行记录。",
    ok: null,
  };
}

export function formatDeliveryBusiness(d: GFDeliverySummary | null): {
  title: string;
  detail: string;
  ok: boolean;
} {
  if (!d) {
    return {
      title: "工程包尚未生成",
      detail: "确认后将生成工程包与还原度报告。",
      ok: false,
    };
  }
  const blocks = Number(d.block_count ?? 0);
  const errors = Number(d.verification?.linter_error_count ?? 0);
  return {
    title: `工程包已生成 · ${blocks} 个程序块 · 自检 ${errors} 项错误`,
    detail:
      d.ok === false
        ? "服务端标记本次生成未完全通过，可下载后按工程视角逐项核对。"
        : "工程包与还原度报告已随本轮交付生成，可直接下载。",
    ok: d.ok !== false && errors === 0,
  };
}

function nodeTag(ir: Record<string, unknown> | null, id: string): string {
  if (!ir) return "";
  const groups: Array<[string, string]> = [
    ["UN", "units"],
    ["EM", "ems"],
    ["CM", "cms"],
    ["CN", "control_nodes"],
    ["ST", "steps"],
    ["SF", "safety"],
  ];
  for (const [tag, key] of groups) {
    const items = Array.isArray(ir[key]) ? (ir[key] as Array<Record<string, unknown>>) : [];
    if (items.some((item) => String(item?.id ?? "") === id)) return tag;
  }
  return "";
}

/**
 * 纯前端连线预校验（后端仍是唯一裁定；仅用于即时中文反馈）。
 * `kind` 为步 2 当前选择的连线类型；缺省时取白名单第一项。
 */
export function validateConnection(
  c: Connection,
  whitelist: GFWhitelist | null,
  ir: Record<string, unknown> | null,
  kind: string = "",
): { ok: boolean; reason: string } {
  const src = String(c.source ?? "").trim();
  const dst = String(c.target ?? "").trim();
  if (!src || !dst) {
    return { ok: false, reason: "请从设备节点右侧的连接桩拖到另一个节点，再松开。" };
  }
  if (src === dst) {
    return { ok: false, reason: "同一个设备节点不能连到自己，请选择另一个节点。" };
  }
  const kinds = whitelist?.edge_kinds ?? [];
  const chosen = kind || kinds[0] || "";
  if (kinds.length > 0 && chosen && !kinds.includes(chosen)) {
    return { ok: false, reason: "连线类型不在允许白名单内，变更已回滚。" };
  }
  const legal = (whitelist?.legal_edges ?? []).filter((entry) => entry.kind === chosen);
  if (chosen && legal.length > 0 && ir) {
    const srcTag = nodeTag(ir, src);
    const dstTag = nodeTag(ir, dst);
    const matched = legal.some(
      (entry) =>
        ((entry.src_kinds?.length ?? 0) === 0 ||
          !srcTag ||
          entry.src_kinds.includes(srcTag)) &&
        ((entry.dst_kinds?.length ?? 0) === 0 ||
          !dstTag ||
          entry.dst_kinds.includes(dstTag)),
    );
    if (!matched) {
      return {
        ok: false,
        reason: "起点与终点的设备类型不符合该连线类型的要求，变更已回滚。",
      };
    }
  }
  return { ok: true, reason: "" };
}

/** 「开始新工程」：清本地会话键（随后由 Channel 调 fetchState 取真实新会话）。 */
export function resetWizardLocalState(): void {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.removeItem(GF_SESSION_KEY);
    window.localStorage.removeItem(GF_PROJECT_KEY);
    window.localStorage.removeItem(GF_LAUNCH_CONTEXT_KEY);
  } catch {
    /* 隐私模式下静默降级：仍由后端 /state 返回新会话，不伪造任何数据。 */
  }
}
