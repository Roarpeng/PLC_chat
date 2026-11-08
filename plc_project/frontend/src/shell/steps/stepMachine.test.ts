/** 4 步状态机 / 中文业务文案 / 连线预校验 · 纯函数测试（不 render、不用 jsdom）。 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Connection } from "@xyflow/react";
import type { GFDeliverySummary, GFWhitelist } from "../../state/greenfield";
import {
  CONFIRM_CHAIN,
  INITIAL_WIZARD_STATE,
  STEP_META,
  canAdvance,
  formatDeliveryBusiness,
  formatFidelityBusiness,
  resetWizardLocalState,
  validateConnection,
  wizardReducer,
  type AdvanceContext,
  type WizardState,
  type WizardStep,
} from "./stepMachine";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stateAfter(actions: Parameters<typeof wizardReducer>[1][]): WizardState {
  return actions.reduce<WizardState>(
    (current, action) => wizardReducer(current, action),
    INITIAL_WIZARD_STATE,
  );
}

function context(overrides: Partial<AdvanceContext> = {}): AdvanceContext {
  return {
    hasIr: false,
    edges: 0,
    reportOk: false,
    canConfirm: false,
    stage: "DRAFT",
    hasDelivery: false,
    ...overrides,
  };
}

function whitelist(): GFWhitelist {
  return {
    edge_kinds: ["E_MSG_STEP", "E_SAFETY"],
    legal_edges: [
      {
        kind: "E_MSG_STEP",
        src_kinds: ["UN", "EM"],
        dst_kinds: ["CM", "EM"],
        views: ["flow"],
        note: "",
      },
    ],
    illegal_edges: [],
    packml_states: [],
    plcopen_signals: [],
    limits: {},
    upload_error_codes: [],
    forbidden_pregate_actions: [],
    locked_hint: "",
  };
}

function conn(source: string, target: string): Connection {
  return { source, target, sourceHandle: null, targetHandle: null };
}

function ir(): Record<string, unknown> {
  return {
    units: [{ id: "UN1", business_label: "上料工站" }],
    ems: [{ id: "EM1", business_label: "机器人单元" }],
    cms: [{ id: "CM1", business_label: "真空吸盘" }],
    edges: [],
  };
}

describe("wizardReducer · 纯前端 4 步状态机", () => {
  it("初始态：步 1 / 工程视角折叠 / 6 组全折叠 / 全部未完成", () => {
    expect(INITIAL_WIZARD_STATE.step).toBe(1);
    expect(INITIAL_WIZARD_STATE.engineeringOpen).toBe(false);
    expect(Object.values(INITIAL_WIZARD_STATE.engineeringGroups).every((v) => v === false)).toBe(true);
    expect(Object.values(INITIAL_WIZARD_STATE.completed).every((v) => v === false)).toBe(true);
    expect(INITIAL_WIZARD_STATE.data.prompt).toBe("");
  });

  it("SET_PROMPT 只改 prompt，其他字段保持", () => {
    const next = wizardReducer(INITIAL_WIZARD_STATE, { type: "SET_PROMPT", value: "一条工艺描述" });
    expect(next.data.prompt).toBe("一条工艺描述");
    expect(next.step).toBe(1);
    expect(next.data.submittedPrompt).toBe("");
    expect(INITIAL_WIZARD_STATE.data.prompt).toBe("");
  });

  it("NEXT / BACK / GO 保留描述与连线数据，不丢已填内容", () => {
    const s = stateAfter([
      { type: "SET_PROMPT", value: "先夹紧再打磨" },
      { type: "SET_SUBMITTED_PROMPT", value: "先夹紧再打磨" },
      { type: "MARK_COMPLETE", step: 1 },
      { type: "NEXT" },
      { type: "SET_EDGE_KIND", value: "E_MSG_STEP" },
    ]);
    expect(s.step).toBe(2);
    const back = wizardReducer(s, { type: "BACK" });
    expect(back.step).toBe(1);
    expect(back.data.prompt).toBe("先夹紧再打磨");
    expect(back.data.selectedEdgeKind).toBe("E_MSG_STEP");
    expect(back.completed[1]).toBe(true);
    const jumped = wizardReducer(back, { type: "GO", step: 3 });
    expect(jumped.step).toBe(3);
    expect(jumped.data.submittedPrompt).toBe("先夹紧再打磨");
  });

  it("折叠 / 展开是纯视图位：不改 step、不改 data、不改 completed", () => {
    const s = stateAfter([
      { type: "SET_PROMPT", value: "描述" },
      { type: "TOGGLE_ENGINEERING", value: true },
      { type: "TOGGLE_GROUP", key: "contract" },
    ]);
    expect(s.engineeringOpen).toBe(true);
    expect(s.engineeringGroups.contract).toBe(true);
    expect(s.step).toBe(1);
    expect(s.data.prompt).toBe("描述");
    expect(s.completed[1]).toBe(false);
  });

  it("REENTER_EDIT 回到步 2，保留描述，清掉后续完成态与门禁提示", () => {
    const s = stateAfter([
      { type: "SET_PROMPT", value: "描述" },
      { type: "MARK_COMPLETE", step: 1 },
      { type: "MARK_COMPLETE", step: 2 },
      { type: "MARK_COMPLETE", step: 3 },
      { type: "SET_CONFIRM_NOTE", value: "还差一项" },
      { type: "GO", step: 4 },
      { type: "REENTER_EDIT" },
    ]);
    expect(s.step).toBe(2);
    expect(s.data.prompt).toBe("描述");
    expect(s.data.confirmNote).toBe("");
    expect(s.completed[1]).toBe(true);
    expect(s.completed[2]).toBe(false);
    expect(s.completed[3]).toBe(false);
    expect(s.completed[4]).toBe(false);
  });

  it("RESET 返回全新初态且不与初态共享引用", () => {
    const s = stateAfter([{ type: "SET_PROMPT", value: "旧描述" }, { type: "RESET" }]);
    expect(s.data.prompt).toBe("");
    expect(s.step).toBe(1);
    s.data.prompt = "写到本地对象";
    expect(INITIAL_WIZARD_STATE.data.prompt).toBe("");
  });

  it("STEP_META 的 4 张纸底按蓝图纸 → 鼠尾草 → 砂 → 冰蓝推进", () => {
    expect(STEP_META.map((m) => m.step)).toEqual([1, 2, 3, 4]);
    expect(STEP_META.map((m) => m.ground)).toEqual([
      "#c3cbe5",
      "#cfd3cb",
      "#e6dccd",
      "#bcc7e0",
    ]);
  });

  it("合法主链顺序：先取工程摘要，再确认、再生成、再回读、最后进步 4", () => {
    expect(CONFIRM_CHAIN).toEqual([
      "fetchEngineeringSummary",
      "confirmSpec",
      "generateProjectPackage",
      "refresh",
      "GO:4",
    ]);
    expect(CONFIRM_CHAIN.indexOf("confirmSpec")).toBeLessThan(
      CONFIRM_CHAIN.indexOf("generateProjectPackage"),
    );
  });
});

describe("canAdvance · 前进合法性", () => {
  it("步 1 必须有草图", () => {
    expect(canAdvance(1, context()).ok).toBe(false);
    expect(canAdvance(1, context({ hasIr: true })).ok).toBe(true);
  });

  it("步 2 必须有连线且结构校验通过", () => {
    expect(canAdvance(2, context({ hasIr: true, edges: 1 })).ok).toBe(false);
    expect(canAdvance(2, context({ hasIr: true, edges: 1, reportOk: true })).ok).toBe(true);
  });

  it("步 3 必须同口径可确认且阶段允许", () => {
    expect(canAdvance(3, context({ hasIr: true, canConfirm: true, stage: "VALIDATING" })).ok).toBe(true);
    expect(canAdvance(3, context({ hasIr: true, canConfirm: true, stage: "FROZEN" })).ok).toBe(false);
    expect(canAdvance(3, context({ hasIr: true, stage: "VALIDATING" })).reason).toContain("工程视角");
  });

  it("步 4 是终态，不允许 NEXT", () => {
    expect(canAdvance(4, context({ hasDelivery: true })).ok).toBe(false);
  });
});

describe("中文业务文案映射 · 主链零术语", () => {
  it("还原一致性：达标 / 未达标 / 本轮不判定三种如实措辞", () => {
    const ok = formatFidelityBusiness({ fidelity_ok: true });
    const bad = formatFidelityBusiness({ fidelity_ok: false });
    const pending = formatFidelityBusiness({ fidelity_ok: null, status: "pending_real_machine" });
    expect(ok.ok).toBe(true);
    expect(ok.title).toContain("达标");
    expect(bad.ok).toBe(false);
    expect(bad.title).toContain("尚未达标");
    expect(bad.title).toContain("不影响本轮工程包导出");
    expect(pending.ok).toBeNull();
    expect(pending.title).toContain("待真机核验，本轮不判定");
    expect(pending.title).toContain("不影响本轮工程包导出");
    expect(`${ok.title}${bad.title}${pending.title}`).not.toContain("fidelity_ok");
  });

  it("undefined / null 一律如实显示本轮不判定", () => {
    expect(formatFidelityBusiness(null).ok).toBeNull();
    expect(formatFidelityBusiness(undefined).ok).toBeNull();
  });

  it("交付摘要取真实块数与自检错误数，空值时诚实降级", () => {
    expect(formatDeliveryBusiness(null).ok).toBe(false);
    const sample = {
      ok: true,
      block_count: 24,
      verification: { linter_error_count: 0 },
    } as unknown as GFDeliverySummary;
    const view = formatDeliveryBusiness(sample);
    expect(view.title).toContain("24 个程序块");
    expect(view.title).toContain("自检 0 项错误");
    expect(view.ok).toBe(true);
  });
});

describe("validateConnection · 纯前端预校验（后端仍是唯一裁定）", () => {
  it("缺端点 / 自环给中文提示", () => {
    expect(validateConnection(conn("", "CM1"), whitelist(), ir()).ok).toBe(false);
    const self = validateConnection(conn("UN1", "UN1"), whitelist(), ir());
    expect(self.ok).toBe(false);
    expect(self.reason).toContain("同一个设备节点");
  });

  it("连线类型不在白名单内给中文提示", () => {
    const bad = validateConnection(
      conn("UN1", "CM1"),
      whitelist(),
      ir(),
      "E_UNKNOWN",
    );
    expect(bad.ok).toBe(false);
    expect(bad.reason).toContain("白名单");
  });

  it("合法连线通过；源/目标类型不匹配给中文提示", () => {
    expect(
      validateConnection(conn("UN1", "CM1"), whitelist(), ir(), "E_MSG_STEP").ok,
    ).toBe(true);
    const mismatch = validateConnection(
      conn("CM1", "UN1"),
      {
        ...whitelist(),
        legal_edges: [
          { kind: "E_MSG_STEP", src_kinds: ["UN"], dst_kinds: ["CM"], views: [], note: "" },
        ],
      },
      ir(),
      "E_MSG_STEP",
    );
    expect(mismatch.ok).toBe(false);
    expect(mismatch.reason).toContain("设备类型");
  });
});

describe("resetWizardLocalState", () => {
  it("只清三个本地会话键，不触碰其他键", () => {
    const removed: string[] = [];
    const fake = {
      removeItem: (key: string) => removed.push(key),
    };
    vi.stubGlobal("window", { localStorage: fake });
    resetWizardLocalState();
    expect(removed).toEqual([
      "greenfield.session_id",
      "greenfield.project_id",
      "greenfield.launch_context",
    ]);
  });

  it("无 window 时安全降级为 no-op", () => {
    vi.stubGlobal("window", undefined);
    expect(() => resetWizardLocalState()).not.toThrow();
  });
});

/* ======================================================================
 * QA 独立复核（V9）：以下用例由 QA 依据 PRD/架构自行设计，非实现者自带用例，
 * 专门覆盖状态机边界钳制、门禁拒绝矩阵、非法连线中文反馈与清理范围。
 * ==================================================================== */
describe("QA V9 · 状态机边界钳制与字段隔离", () => {
  it("BACK 在步 1 钳制、NEXT 在步 4 钳制，跨步 GO 不丢描述/连线类型", () => {
    expect(wizardReducer(INITIAL_WIZARD_STATE, { type: "BACK" }).step).toBe(1);
    const atLast = wizardReducer(
      wizardReducer(INITIAL_WIZARD_STATE, { type: "GO", step: 4 }),
      { type: "NEXT" },
    );
    expect(atLast.step).toBe(4);

    const loaded = stateAfter([
      { type: "SET_PROMPT", value: "描述A" },
      { type: "SET_SUBMITTED_PROMPT", value: "描述A" },
      { type: "SET_EDGE_KIND", value: "E_MSG_STEP" },
      { type: "GO", step: 2 },
      { type: "BACK" },
      { type: "GO", step: 3 },
      { type: "GO", step: 1 },
    ]);
    expect(loaded.step).toBe(1);
    expect(loaded.data.prompt).toBe("描述A");
    expect(loaded.data.submittedPrompt).toBe("描述A");
    expect(loaded.data.selectedEdgeKind).toBe("E_MSG_STEP");
  });

  it("各 SET_* 只改自身字段；TOGGLE 无值取反且只翻转目标组", () => {
    let s = INITIAL_WIZARD_STATE;
    s = wizardReducer(s, { type: "SET_LINK_ERROR", value: "连线被拒绝" });
    s = wizardReducer(s, { type: "SET_CONFIRM_NOTE", value: "还差一项" });
    s = wizardReducer(s, { type: "SET_DELIVERY_READY", value: true });
    s = wizardReducer(s, { type: "SET_BUSY", value: true });
    s = wizardReducer(s, { type: "SET_ERROR", value: "处理失败" });
    expect(s.data.linkError).toBe("连线被拒绝");
    expect(s.data.confirmNote).toBe("还差一项");
    expect(s.data.deliveryReady).toBe(true);
    expect(s.busy).toBe(true);
    expect(s.error).toBe("处理失败");
    expect(s.data.prompt).toBe("");
    expect(s.step).toBe(1);

    const opened = wizardReducer(s, { type: "TOGGLE_ENGINEERING" });
    expect(opened.engineeringOpen).toBe(true);
    expect(wizardReducer(opened, { type: "TOGGLE_ENGINEERING" }).engineeringOpen).toBe(false);
    const toggled = wizardReducer(opened, { type: "TOGGLE_GROUP", key: "fidelity" });
    expect(toggled.engineeringGroups.fidelity).toBe(true);
    expect(toggled.engineeringGroups.contract).toBe(false);
    expect(toggled.step).toBe(1);
  });

  it("REENTER_EDIT 保留描述与连线类型、清后续完成态；RESET 连折叠/错误态一起清空", () => {
    const dirty = stateAfter([
      { type: "SET_PROMPT", value: "描述B" },
      { type: "SET_SUBMITTED_PROMPT", value: "描述B" },
      { type: "SET_EDGE_KIND", value: "E_SAFETY" },
      { type: "TOGGLE_ENGINEERING", value: true },
      { type: "TOGGLE_GROUP", key: "actions" },
      { type: "SET_ERROR", value: "旧错误" },
      { type: "MARK_COMPLETE", step: 1 },
      { type: "GO", step: 4 },
      { type: "SET_DELIVERY_READY", value: true },
    ]);
    const reentered = wizardReducer(dirty, { type: "REENTER_EDIT" });
    expect(reentered.step).toBe(2);
    expect(reentered.data.prompt).toBe("描述B");
    expect(reentered.data.submittedPrompt).toBe("描述B");
    expect(reentered.data.selectedEdgeKind).toBe("E_SAFETY");
    expect(reentered.data.deliveryReady).toBe(false);
    expect(reentered.data.confirmNote).toBe("");
    expect(reentered.data.linkError).toBe("");

    const reset = wizardReducer(dirty, { type: "RESET" });
    expect(reset.step).toBe(1);
    expect(reset.engineeringOpen).toBe(false);
    expect(Object.values(reset.engineeringGroups).every((v) => v === false)).toBe(true);
    expect(reset.error).toBe("");
    expect(reset.busy).toBe(false);
    expect(reset.completed[1]).toBe(false);
    expect(reset.data.deliveryReady).toBe(false);
  });
});

describe("QA V9 · canAdvance 门禁拒绝矩阵", () => {
  it("未满足时全部拒绝，reason 为中文且不含英文错误码", () => {
    const cases: Array<[WizardStep, AdvanceContext, string]> = [
      [1, context(), "描述"],
      [2, context({ hasIr: true, edges: 1, reportOk: false }), "结构校验"],
      [2, context({ hasIr: true, edges: 0, reportOk: true }), "至少一条"],
      [3, context({ hasIr: true, canConfirm: true, stage: "DRAFT" }), "工程视角"],
      [3, context({ hasIr: true, canConfirm: true, stage: "FROZEN" }), "工程视角"],
      [3, context({ hasIr: true, canConfirm: false, stage: "VALIDATING" }), "工程视角"],
      [4, context({ hasDelivery: false }), "尚未就绪"],
      [4, context({ hasDelivery: true }), "重新调整"],
    ];
    for (const [step, ctx, keyword] of cases) {
      const verdict = canAdvance(step, ctx);
      expect(verdict.ok, `step ${step} 应被拒绝`).toBe(false);
      expect(verdict.reason).toContain(keyword);
      expect(verdict.reason).not.toMatch(/[A-Za-z]{3,}/);
      expect(verdict.reason).not.toMatch(/GF_|blocker|code/i);
    }
  });

  it("满足时放行且 reason 为空（含 LINKABLE / VALIDATING 两种合法阶段）", () => {
    expect(canAdvance(1, context({ hasIr: true })).reason).toBe("");
    expect(canAdvance(2, context({ edges: 1, reportOk: true })).ok).toBe(true);
    expect(canAdvance(3, context({ canConfirm: true, stage: "LINKABLE" })).ok).toBe(true);
    expect(canAdvance(3, context({ canConfirm: true, stage: "VALIDATING" })).ok).toBe(true);
  });
});

describe("QA V9 · validateConnection 错误路径中文反馈", () => {
  it("缺源 / 缺目标 / 空白端点 / 自环 / 非法 kind 全部中文拒绝", () => {
    const wl = whitelist();
    const verdicts = [
      validateConnection(conn("", "CM1"), wl, ir(), "E_MSG_STEP"),
      validateConnection(conn("UN1", ""), wl, ir(), "E_MSG_STEP"),
      validateConnection(conn("   ", "CM1"), wl, ir(), "E_MSG_STEP"),
      validateConnection(conn("UN1", "UN1"), wl, ir(), "E_MSG_STEP"),
      validateConnection(conn("UN1", "CM1"), wl, ir(), "E_NOT_ALLOWED"),
    ];
    for (const v of verdicts) {
      expect(v.ok).toBe(false);
      expect(v.reason.length).toBeGreaterThan(0);
      expect(v.reason).not.toMatch(/[A-Za-z]{3,}/);
      expect(v.reason).not.toMatch(/GF_|error/i);
    }
  });

  it("kind 缺省回落白名单首项；白名单未加载时不越权裁定（后端唯一裁定）", () => {
    expect(validateConnection(conn("UN1", "CM1"), whitelist(), ir()).ok).toBe(true);
    const noWhitelist = validateConnection(conn("UN1", "CM1"), null, null, "E_ANY");
    expect(noWhitelist.ok).toBe(true);
    expect(noWhitelist.reason).toBe("");
  });
});

describe("QA V9 · 文案三态与清理范围", () => {
  it("只有 status 无结论时按待核验处理；三态文案零内部契约术语", () => {
    const pending = formatFidelityBusiness({
      status: "pending_real_machine",
      fidelity_ok: null,
    });
    expect(pending.ok).toBeNull();
    const views = [
      formatFidelityBusiness({ fidelity_ok: true }),
      formatFidelityBusiness({ fidelity_ok: false }),
      pending,
      formatFidelityBusiness(null),
      formatFidelityBusiness(undefined),
    ];
    for (const v of views) {
      const text = `${v.title}${v.detail}`;
      expect(text.length).toBeGreaterThan(0);
      expect(text).not.toMatch(/fidelity_ok|spec_hash|pending_real_machine|blocker|GF_/);
      expect(text).not.toMatch(/[A-Za-z]{3,}/);
    }
  });

  it("交付摘要：服务端标记未通过或自检有错时如实不判定成功", () => {
    const failed = formatDeliveryBusiness({
      ok: false,
      block_count: 12,
      verification: { linter_error_count: 3 },
    } as unknown as GFDeliverySummary);
    expect(failed.ok).toBe(false);
    expect(failed.title).toContain("12 个程序块");
    expect(failed.title).toContain("自检 3 项错误");
    expect(failed.detail).toContain("未完全通过");

    const linter = formatDeliveryBusiness({
      ok: true,
      block_count: 5,
      verification: { linter_error_count: 2 },
    } as unknown as GFDeliverySummary);
    expect(linter.ok).toBe(false);
  });

  it("resetWizardLocalState 只删 3 个会话键，其他键值原样保留", () => {
    const store = new Map<string, string>([
      ["greenfield.session_id", "sid"],
      ["greenfield.project_id", "pid"],
      ["greenfield.launch_context", "ctx"],
      ["unrelated.key", "keep"],
    ]);
    const fake = {
      removeItem: (key: string) => void store.delete(key),
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    };
    vi.stubGlobal("window", { localStorage: fake });
    resetWizardLocalState();
    expect([...store.keys()]).toEqual(["unrelated.key"]);
    expect(store.get("unrelated.key")).toBe("keep");
  });

  it("localStorage 抛异常时静默降级，不抛错、不伪造任何会话", () => {
    vi.stubGlobal("window", {
      localStorage: {
        removeItem: () => {
          throw new Error("SecurityError");
        },
      },
    });
    expect(() => resetWizardLocalState()).not.toThrow();
  });
});
