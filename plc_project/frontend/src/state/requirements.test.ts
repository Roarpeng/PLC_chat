import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MOCK_REQUIREMENT_ID,
  REQUIREMENT_ITEM_KINDS,
  REQUIREMENT_SOURCE_LABELS,
  REQUIREMENT_STATUS_TEXT,
  deleteRequirement,
  fetchRequirement,
  fetchRequirements,
  itemSourceOf,
  mockRequirement,
  mockRequirementMeta,
  normalizeRequirement,
  normalizeRequirementMeta,
  putRequirement,
  requestDraft,
  requirementStatusOf,
  shortRequirementId,
  taskKindOf,
  type Requirement,
} from "./requirements";

/* ---- 测试夹具 ---- */

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const GATEWAY_META = [
  {
    requirement_id: "req-111111aaaaaa",
    summary: "安全门联锁 + 夹紧钻孔流程",
    confirmation_status: "confirmed",
    updated_at: 1_790_000_042,
    task_kind: "improve",
  },
  {
    id: "req-222222bbbbbb",
    intent_summary: "清理 FB_Legacy 冗余网络",
    status: "proposed",
    updated_at: 1_790_000_100,
    task_kind: "refactor",
  },
];

const GATEWAY_REQUIREMENT = {
  requirement_id: "req-111111aaaaaa",
  project_name: "HR001_PLC_20260509",
  created_at: 1_790_000_000,
  updated_at: 1_790_000_042,
  confirmation_status: "confirmed",
  intent_summary: "安全门联锁前提下完成夹紧与进给",
  items: [
    { id: "it-1", kind: "precondition", text: "工件到位", source: "engineering", source_ref: "FB5002 NW1" },
    { id: "it-2", kind: "sequence", text: "夹紧→进给→退回", source: "user" },
  ],
  open_questions: ["夹紧超时取多少秒？"],
  linked_blocks: ["FB5002"],
  linked_signals: [],
  task_kind: "improve",
  origin_prompt: "完善夹紧逻辑",
};

/* ---- 枚举归一 ---- */

describe("枚举归一（未知值的安全默认）", () => {
  it("itemSourceOf：三态放行，未知一律「AI 推断」（不确定 ≠ 工程证据）", () => {
    expect(itemSourceOf("engineering")).toBe("engineering");
    expect(itemSourceOf("user")).toBe("user");
    expect(itemSourceOf("inferred")).toBe("inferred");
    expect(itemSourceOf("guess")).toBe("inferred");
    expect(itemSourceOf(undefined)).toBe("inferred");
  });

  it("requirementStatusOf：未知一律「待确认」（脏数据绝不默认成已确认）", () => {
    expect(requirementStatusOf("confirmed")).toBe("confirmed");
    expect(requirementStatusOf("rejected")).toBe("rejected");
    expect(requirementStatusOf("proposed")).toBe("proposed");
    expect(requirementStatusOf("done")).toBe("proposed");
    expect(requirementStatusOf(null)).toBe("proposed");
  });

  it("taskKindOf：四态放行，未知退「理解工程」", () => {
    (["understand", "diagnose", "improve", "refactor"] as const).forEach((k) =>
      expect(taskKindOf(k)).toBe(k),
    );
    expect(taskKindOf("optimize")).toBe("understand");
  });

  it("shortRequirementId：req-<hex12> 取后段前 8 位；不合规退末 8 字符；空 → —", () => {
    expect(shortRequirementId("req-0a1b2c3d4e5f")).toBe("0a1b2c3d");
    expect(shortRequirementId(MOCK_REQUIREMENT_ID)).toBe("mockdemo");
    expect(shortRequirementId("very-long-requirement-name")).toBe("ent-name");
    expect(shortRequirementId("")).toBe("—");
    expect(shortRequirementId(undefined)).toBe("—");
  });

  it("展示常量：五类分组、三态来源、三态确认文案齐全", () => {
    expect(REQUIREMENT_ITEM_KINDS.map((k) => k.kind)).toEqual([
      "precondition",
      "sequence",
      "exception",
      "constraint",
      "acceptance",
    ]);
    expect(REQUIREMENT_ITEM_KINDS.every((k) => k.label.trim().length > 0)).toBe(true);
    expect(REQUIREMENT_SOURCE_LABELS).toEqual({
      engineering: "工程证据",
      user: "用户输入",
      inferred: "AI 推断",
    });
    expect(REQUIREMENT_STATUS_TEXT).toEqual({
      proposed: "待确认",
      confirmed: "已确认",
      rejected: "已拒绝",
    });
  });
});

/* ---- normalizeRequirement / normalizeRequirementMeta ---- */

describe("normalizeRequirement", () => {
  it("合法对象透传：字段齐全时七字段原样归一", () => {
    const r = normalizeRequirement(GATEWAY_REQUIREMENT);
    expect(r).not.toBeNull();
    expect(r?.requirement_id).toBe("req-111111aaaaaa");
    expect(r?.confirmation_status).toBe("confirmed");
    expect(r?.items).toHaveLength(2);
    expect(r?.items[0]).toEqual({
      id: "it-1",
      kind: "precondition",
      text: "工件到位",
      source: "engineering",
      source_ref: "FB5002 NW1",
    });
    expect(r?.open_questions).toEqual(["夹紧超时取多少秒？"]);
    expect(r?.task_kind).toBe("improve");
  });

  it("宽松字段：缺省可选项补默认，item 缺 id 按序号补，脏 item 行跳过", () => {
    const r = normalizeRequirement({
      requirement_id: "req-abc123def456",
      items: [
        { kind: "sequence", text: "正常序列一条" },
        { kind: "weird-kind", text: "脏 kind 丢弃" },
        { kind: "constraint", text: "   " },
        { kind: "acceptance", text: "验收一条", source: "mystery" },
      ],
    });
    expect(r?.items).toEqual([
      { id: "it-1", kind: "sequence", text: "正常序列一条", source: "inferred" },
      { id: "it-2", kind: "acceptance", text: "验收一条", source: "inferred" },
    ]);
    expect(r?.confirmation_status).toBe("proposed");
    expect(r?.task_kind).toBe("understand");
    expect(r?.created_at).toBe(0);
    expect(r?.updated_at).toBe(0);
    expect(r?.open_questions).toEqual([]);
    expect(r?.origin_prompt).toBe("");
    expect(r?.items[1]).not.toHaveProperty("source_ref");
  });

  it("形状不符返回 null：缺 id / items 非数组 / 非对象", () => {
    expect(normalizeRequirement({ items: [] })).toBeNull();
    expect(normalizeRequirement({ requirement_id: "req-1", items: "no" })).toBeNull();
    expect(normalizeRequirement(null)).toBeNull();
    expect(normalizeRequirement("req-1")).toBeNull();
  });
});

describe("normalizeRequirementMeta", () => {
  it("兼容 requirement_id / id 与 summary / intent_summary、status / confirmation_status", () => {
    const a = normalizeRequirementMeta(GATEWAY_META[0]);
    expect(a).toEqual({
      requirement_id: "req-111111aaaaaa",
      summary: "安全门联锁 + 夹紧钻孔流程",
      status: "confirmed",
      updated_at: 1_790_000_042,
      task_kind: "improve",
    });
    const b = normalizeRequirementMeta(GATEWAY_META[1]);
    expect(b?.requirement_id).toBe("req-222222bbbbbb");
    expect(b?.summary).toBe("清理 FB_Legacy 冗余网络");
    expect(b?.status).toBe("proposed");
  });

  it("无 id 的坏行返回 null；非对象同样 null", () => {
    expect(normalizeRequirementMeta({ summary: "no id" })).toBeNull();
    expect(normalizeRequirementMeta(null)).toBeNull();
    expect(normalizeRequirementMeta(42)).toBeNull();
  });
});

/* ---- 内置 mock ---- */

describe("内置示例需求卡", () => {
  it("契约形态：五类 items 各≥1、三态来源各≥1、2 条 open_questions、status=proposed", () => {
    const m = mockRequirement();
    expect(m.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    expect(m.confirmation_status).toBe("proposed");
    expect(m.open_questions).toHaveLength(2);
    for (const { kind } of REQUIREMENT_ITEM_KINDS) {
      expect(m.items.filter((it) => it.kind === kind).length).toBeGreaterThanOrEqual(1);
    }
    (["engineering", "user", "inferred"] as const).forEach((src) => {
      expect(m.items.filter((it) => it.source === src).length).toBeGreaterThanOrEqual(1);
    });
    // engineering 来源必带 source_ref（证据定位）
    m.items
      .filter((it) => it.source === "engineering")
      .forEach((it) => expect(it.source_ref?.trim().length).toBeGreaterThan(0));
  });

  it("mockRequirementMeta 走同一归一管道：id / 状态 / 任务口径一致", () => {
    const meta = mockRequirementMeta();
    expect(meta.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    expect(meta.status).toBe("proposed");
    expect(meta.task_kind).toBe(mockRequirement().task_kind);
  });

  it("mockRequirement 返回深拷贝，调用方改动不污染内置样例", () => {
    const a = mockRequirement();
    a.intent_summary = "被改掉了";
    a.items[0].text = "被改掉了";
    a.open_questions.push("多余问题");
    const b = mockRequirement();
    expect(b.intent_summary).not.toBe("被改掉了");
    expect(b.items[0].text).not.toBe("被改掉了");
    expect(b.open_questions).toHaveLength(2);
  });
});

/* ---- fetchRequirements（mock-first 回退契约） ---- */

describe("fetchRequirements", () => {
  const realFetch = globalThis.fetch;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("网关 200 数组 → origin=gateway，meta 归一透传", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(GATEWAY_META));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await fetchRequirements();
    expect(res.origin).toBe("gateway");
    expect(res.items.map((m) => m.requirement_id)).toEqual([
      "req-111111aaaaaa",
      "req-222222bbbbbb",
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/v1/plc/canvas/requirements");
    // 网关成功路径不应有回退日志
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("网关 200 空数组是真实答案：items 空且不回退 mock", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes([])) as unknown as typeof fetch;
    const res = await fetchRequirements();
    expect(res.origin).toBe("gateway");
    expect(res.items).toEqual([]);
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("404（端点未上线）→ 一条内置示例卡：一条 debug、不抛错", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(jsonRes({ detail: "not found" }, 404)) as unknown as typeof fetch;

    const res = await fetchRequirements();
    expect(res.origin).toBe("mock");
    expect(res.items).toHaveLength(1);
    expect(res.items[0]?.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it("网络错误 / 响应形态不符（非数组）同样回退 mock", async () => {
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(jsonRes({ hello: 1 })) as unknown as typeof fetch;

    const a = await fetchRequirements();
    expect(a.origin).toBe("mock");
    const b = await fetchRequirements();
    expect(b.origin).toBe("mock");
    expect(b.items[0]?.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    expect(debugSpy).toHaveBeenCalledTimes(2);
  });
});

/* ---- fetchRequirement（mock-first 回退契约） ---- */

describe("fetchRequirement", () => {
  const realFetch = globalThis.fetch;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("示例 id 不触网直接回 mock", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await fetchRequirement(MOCK_REQUIREMENT_ID);
    expect(res?.origin).toBe("mock");
    expect(res?.requirement.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("空 id 返回 null（防御）", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    expect(await fetchRequirement("")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("网关 200 → 完整对象归一透传 origin=gateway", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(GATEWAY_REQUIREMENT));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await fetchRequirement("req-111111aaaaaa");
    expect(res?.origin).toBe("gateway");
    expect(res?.requirement.requirement_id).toBe("req-111111aaaaaa");
    expect(res?.requirement.items).toHaveLength(2);
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("/api/v1/plc/canvas/requirements/req-111111aaaaaa");
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("404 / 网络错误 / 形状不符 → 回退示例卡并各打一条 debug", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonRes({ code: "PLC_REQUIREMENT_NOT_FOUND" }, 404))
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(jsonRes({ nope: true })) as unknown as typeof fetch;

    const a = await fetchRequirement("req-999999999999");
    expect(a?.origin).toBe("mock");
    expect(a?.requirement.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    const b = await fetchRequirement("req-888888888888");
    expect(b?.origin).toBe("mock");
    const c = await fetchRequirement("req-777777777777");
    expect(c?.origin).toBe("mock");
    expect(debugSpy).toHaveBeenCalledTimes(3);
  });
});

/* ---- putRequirement（保存失败回显编辑，不替换成示例卡） ---- */

describe("putRequirement", () => {
  const realFetch = globalThis.fetch;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("网关 200 → PUT 透传整对象，回传服务端归一结果 origin=gateway", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(GATEWAY_REQUIREMENT));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await putRequirement(GATEWAY_REQUIREMENT as Requirement);
    expect(res.origin).toBe("gateway");
    expect(res.requirement.requirement_id).toBe("req-111111aaaaaa");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/api/v1/plc/canvas/requirements/req-111111aaaaaa");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual(GATEWAY_REQUIREMENT);
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("404 / 网络错误 → 回显提交对象（不是示例卡）并标 mock：一条 debug、不抛错", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonRes({ detail: "no" }, 404))
      .mockRejectedValueOnce(new TypeError("fetch failed")) as unknown as typeof fetch;

    const edited: Requirement = {
      ...(GATEWAY_REQUIREMENT as Requirement),
      intent_summary: "工程师改过的意图",
    };
    const a = await putRequirement(edited);
    expect(a.origin).toBe("mock");
    expect(a.requirement.intent_summary).toBe("工程师改过的意图");
    expect(a.requirement.requirement_id).toBe("req-111111aaaaaa");
    const b = await putRequirement(edited);
    expect(b.origin).toBe("mock");
    expect(b.requirement.intent_summary).toBe("工程师改过的意图");
    expect(debugSpy).toHaveBeenCalledTimes(2);
  });

  it("缺 id / 形状不符的提交对象：不触网，本地回显标 mock", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const a = await putRequirement({} as Requirement);
    expect(a.origin).toBe("mock");
    expect(a.requirement.requirement_id).toBe(MOCK_REQUIREMENT_ID);
    const b = await putRequirement({ requirement_id: "req-x", items: "bad" } as unknown as Requirement);
    expect(b.origin).toBe("mock");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(debugSpy).toHaveBeenCalledTimes(2);
  });
});

/* ---- deleteRequirement ---- */

describe("deleteRequirement", () => {
  const realFetch = globalThis.fetch;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("网关 200 → deleted=true origin=gateway，方法与 URL 透传", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await deleteRequirement("req-111111aaaaaa");
    expect(res).toEqual({ deleted: true, origin: "gateway" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/api/v1/plc/canvas/requirements/req-111111aaaaaa");
    expect(init.method).toBe("DELETE");
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("空 id 不触网；404 / 网络错误 → deleted=false 标 mock：一条 debug、不抛错", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes({ detail: "no" }, 404))
      .mockRejectedValueOnce(new TypeError("fetch failed"));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    expect(await deleteRequirement("")).toEqual({ deleted: false, origin: "mock" });
    const a = await deleteRequirement("req-999999999999");
    expect(a).toEqual({ deleted: false, origin: "mock" });
    const b = await deleteRequirement("req-888888888888");
    expect(b).toEqual({ deleted: false, origin: "mock" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(debugSpy).toHaveBeenCalledTimes(2);
  });
});

/* ---- requestDraft（LLM 草稿端点） ---- */

describe("requestDraft", () => {
  const realFetch = globalThis.fetch;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("网关 200 → POST /draft 透传 body（prompt/canvas/task_kind）并归一草稿", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(GATEWAY_REQUIREMENT));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const canvas = { blocks: [{ name: "FB5002" }], signals: [] };
    const res = await requestDraft("完善夹紧逻辑", canvas, "improve");
    expect(res.origin).toBe("gateway");
    expect(res.requirement.requirement_id).toBe("req-111111aaaaaa");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/api/v1/plc/canvas/requirements/draft");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      prompt: "完善夹紧逻辑",
      canvas,
      task_kind: "improve",
    });
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("400 LLM_NOT_CONFIGURED → 携带 prompt/task_kind 的示例草稿：proposed、标 mock、一条 debug", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(jsonRes({ code: "LLM_NOT_CONFIGURED" }, 400)) as unknown as typeof fetch;

    const res = await requestDraft("帮我重构安全门逻辑", null, "refactor");
    expect(res.origin).toBe("mock");
    expect(res.requirement.origin_prompt).toBe("帮我重构安全门逻辑");
    expect(res.requirement.task_kind).toBe("refactor");
    expect(res.requirement.confirmation_status).toBe("proposed");
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it("网络错误 / 形状不符 → 同样回退示例草稿，不抛错；未传 task_kind 保底卡片默认", async () => {
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(jsonRes({ nope: 1 })) as unknown as typeof fetch;

    const a = await requestDraft("诊断一下");
    expect(a.origin).toBe("mock");
    expect(a.requirement.task_kind).toBe(mockRequirement().task_kind);
    const b = await requestDraft("诊断一下");
    expect(b.origin).toBe("mock");
    expect(debugSpy).toHaveBeenCalledTimes(2);
  });
});
