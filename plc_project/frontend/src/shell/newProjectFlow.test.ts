import { describe, expect, it } from "vitest";
import {
  DEFAULT_PROJECT_NAME,
  NEW_PROJECT_FLOW_IDLE,
  PROJECT_NAME_MAX_LEN,
  isValidProjectName,
  newProjectFlowReducer,
  sanitizeProjectName,
  type NewProjectFlowState,
} from "./newProjectFlow";
import type { Requirement } from "../state/requirements";

/* ---- 测试夹具:一张已确认需求卡(只填状态机关心的字段) ---- */

const confirmedReq = (intentSummary: string): Requirement => ({
  requirement_id: "req-test0001",
  project_name: "",
  created_at: 1_790_000_000,
  updated_at: 1_790_000_042,
  confirmation_status: "confirmed",
  intent_summary: intentSummary,
  items: [],
  open_questions: [],
  linked_blocks: [],
  linked_signals: [],
  task_kind: "improve",
  origin_prompt: "测试工艺需求",
});

const IDENT_RE = /^[A-Za-z][A-Za-z0-9_]*$/;

describe("sanitizeProjectName(intent_summary → 合法项目名)", () => {
  it("英文意图按词拼接为下划线标识", () => {
    expect(sanitizeProjectName("Conveyor station 3 control")).toBe("Conveyor_station_3_control");
  });

  it("中英混排:洗掉中文与标点,仅留 ASCII 词", () => {
    expect(sanitizeProjectName("HR001 产线改造 (v2)")).toBe("HR001_v2");
  });

  it("纯中文意图洗不出字符 → 回退默认名", () => {
    expect(sanitizeProjectName("安全门联锁前提下完成工件夹紧与钻孔轴进给")).toBe(DEFAULT_PROJECT_NAME);
  });

  it("开头数字/下划线被砍掉,保证字母开头", () => {
    expect(sanitizeProjectName("2号站 上料")).toBe(DEFAULT_PROJECT_NAME); // 砍掉 2 后为空
    expect(sanitizeProjectName("__ABC def")).toBe("ABC_def");
    expect(sanitizeProjectName("3rd station")).toBe("rd_station");
  });

  it("连续分隔折叠为单个下划线,且无首尾下划线", () => {
    expect(sanitizeProjectName("A  --  B == C")).toBe("A_B_C");
    expect(sanitizeProjectName(" station start ")).toBe("station_start");
  });

  it("超长意图截断到上限且不以下划线结尾", () => {
    const long = "A".repeat(PROJECT_NAME_MAX_LEN + 10);
    const out = sanitizeProjectName(long);
    expect(out.length).toBe(PROJECT_NAME_MAX_LEN);
    expect(out.endsWith("_")).toBe(false);
  });

  it("空值 / null / undefined / 非字符串 → 回退默认名", () => {
    expect(sanitizeProjectName("")).toBe(DEFAULT_PROJECT_NAME);
    expect(sanitizeProjectName(null)).toBe(DEFAULT_PROJECT_NAME);
    expect(sanitizeProjectName(undefined)).toBe(DEFAULT_PROJECT_NAME);
    expect(sanitizeProjectName(12345)).toBe(DEFAULT_PROJECT_NAME); // 数字开头被砍 → 空
  });

  it("所有输出都满足「字母开头 + 仅字母数字下划线」且可通过合法名校验", () => {
    const samples = [
      "Conveyor station 3 control",
      "HR001 产线改造 (v2)",
      "安全门联锁",
      "  mixed  中文 42 cases ",
      "___leading",
      "9lives",
    ];
    for (const s of samples) {
      const out = sanitizeProjectName(s);
      expect(out.length).toBeGreaterThan(0);
      if (out !== DEFAULT_PROJECT_NAME) expect(out).toMatch(IDENT_RE);
      expect(isValidProjectName(out)).toBe(true);
    }
  });
});

describe("isValidProjectName", () => {
  it("接受字母/下划线开头的合法标识", () => {
    expect(isValidProjectName("FB_Motor")).toBe(true);
    expect(isValidProjectName("_Internal")).toBe(true);
    expect(isValidProjectName("PLC_Project_2026")).toBe(true);
  });

  it("拒绝空串/中文/开头数字/非法字符", () => {
    expect(isValidProjectName("")).toBe(false);
    expect(isValidProjectName("   ")).toBe(false);
    expect(isValidProjectName("2ndStation")).toBe(false);
    expect(isValidProjectName("工程一号")).toBe(false);
    expect(isValidProjectName("My-Project")).toBe(false);
  });
});

describe("newProjectFlowReducer(新建工程流状态机)", () => {
  it("idle + ENTRY_CLICK 空 prompt → guiding(引导输入,不开草稿)", () => {
    const next = newProjectFlowReducer(NEW_PROJECT_FLOW_IDLE, { type: "ENTRY_CLICK", promptText: "" });
    expect(next.phase).toBe("guiding");
    expect(next.requirement).toBeNull();
  });

  it("idle + ENTRY_CLICK 带 prompt → requirement(直接进需求卡草稿流)", () => {
    const next = newProjectFlowReducer(NEW_PROJECT_FLOW_IDLE, {
      type: "ENTRY_CLICK",
      promptText: "工艺需求:上料机构按节拍供料",
    });
    expect(next.phase).toBe("requirement");
  });

  it("guiding + DRAFT_OPENED → requirement;idle + DRAFT_OPENED 不误入流", () => {
    const guiding = newProjectFlowReducer(NEW_PROJECT_FLOW_IDLE, { type: "ENTRY_CLICK", promptText: "  " });
    expect(newProjectFlowReducer(guiding, { type: "DRAFT_OPENED" }).phase).toBe("requirement");
    // 流外(improve 任务)打开草稿:不改变 idle
    expect(newProjectFlowReducer(NEW_PROJECT_FLOW_IDLE, { type: "DRAFT_OPENED" }).phase).toBe("idle");
  });

  it("requirement + INTENT_CONFIRMED → confirm,默认项目名取 intent_summary 洗名", () => {
    const req = confirmedReq("灌装线 Cap washer 改造 v3");
    const next = newProjectFlowReducer(
      { phase: "requirement", requirement: null, defaultProjectName: "" },
      { type: "INTENT_CONFIRMED", requirement: req },
    );
    expect(next.phase).toBe("confirm");
    expect(next.requirement).toBe(req);
    expect(next.defaultProjectName).toBe("Cap_washer_v3");
  });

  it("纯中文意图 → 默认项目名回退 PLC_Project", () => {
    const next = newProjectFlowReducer(
      { phase: "requirement", requirement: null, defaultProjectName: "" },
      { type: "INTENT_CONFIRMED", requirement: confirmedReq("夹紧与钻孔轴进给控制") },
    );
    expect(next.defaultProjectName).toBe("PLC_Project");
  });

  it("idle + INTENT_CONFIRMED(流外 improve 确认)不弹创建确认,状态不变", () => {
    const next = newProjectFlowReducer(NEW_PROJECT_FLOW_IDLE, {
      type: "INTENT_CONFIRMED",
      requirement: confirmedReq("anything"),
    });
    expect(next.phase).toBe("idle");
  });

  it("confirm + CREATE_CANCEL → requirement 且需求卡保留", () => {
    const req = confirmedReq("Conveyor control");
    const confirm: NewProjectFlowState = {
      phase: "confirm",
      requirement: req,
      defaultProjectName: "Conveyor_control",
    };
    const next = newProjectFlowReducer(confirm, { type: "CREATE_CANCEL" });
    expect(next.phase).toBe("requirement");
    expect(next.requirement).toBe(req);
  });

  it("已确认需求下再次 ENTRY_CLICK → 直达 confirm(取消后重入路径)", () => {
    const req = confirmedReq("Station 5 upgrade");
    const requirementPhase: NewProjectFlowState = {
      phase: "requirement",
      requirement: req,
      defaultProjectName: "old",
    };
    const next = newProjectFlowReducer(requirementPhase, { type: "ENTRY_CLICK", promptText: "" });
    expect(next.phase).toBe("confirm");
    expect(next.defaultProjectName).toBe("Station_5_upgrade");
  });

  it("confirm + CREATE_SUBMIT → creating;creating 忽略重复 ENTRY_CLICK", () => {
    const confirm: NewProjectFlowState = {
      phase: "confirm",
      requirement: confirmedReq("x"),
      defaultProjectName: "X",
    };
    const creating = newProjectFlowReducer(confirm, { type: "CREATE_SUBMIT" });
    expect(creating.phase).toBe("creating");
    const after = newProjectFlowReducer(creating, { type: "ENTRY_CLICK", promptText: "text" });
    expect(after.phase).toBe("creating");
  });

  it("creating + CREATE_SETTLED → idle(全字段归位)", () => {
    const creating: NewProjectFlowState = {
      phase: "creating",
      requirement: confirmedReq("done"),
      defaultProjectName: "Done",
    };
    const next = newProjectFlowReducer(creating, { type: "CREATE_SETTLED" });
    expect(next).toEqual(NEW_PROJECT_FLOW_IDLE);
  });

  it("RESET 从任意阶段强制归位 idle", () => {
    for (const phase of ["guiding", "requirement", "confirm", "creating"] as const) {
      const state: NewProjectFlowState = {
        phase,
        requirement: confirmedReq("r"),
        defaultProjectName: "R",
      };
      expect(newProjectFlowReducer(state, { type: "RESET" })).toEqual(NEW_PROJECT_FLOW_IDLE);
    }
  });

  it("非 confirm 态的 CREATE_SUBMIT / CREATE_CANCEL 不产生阶段变化", () => {
    const idle = NEW_PROJECT_FLOW_IDLE;
    expect(newProjectFlowReducer(idle, { type: "CREATE_SUBMIT" }).phase).toBe("idle");
    expect(newProjectFlowReducer(idle, { type: "CREATE_CANCEL" }).phase).toBe("idle");
  });
});
