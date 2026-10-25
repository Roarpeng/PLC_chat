import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CONFIRM_V_SNAPSHOT,
  MOCK_CHANGE_ID,
  V_LEVELS,
  baselineFingerprint,
  changeJsonPreview,
  changeStatusGroup,
  changeStatusText,
  fetchChange,
  fetchChanges,
  formatChangeTime,
  mockChange,
  mockChangeMeta,
  normalizeChangeMeta,
  shortChangeId,
  vStatusMark,
  vStatusOf,
  vStatusText,
} from "./pcec";

/* ---- 测试夹具 ---- */

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const GATEWAY_META = [
  {
    id: "chg-111111aaaaaa",
    kind: "writeback",
    summary: "回写 FB_Motor 与 DB_MotorData",
    status: "applied",
    updated_at: 1_790_000_042,
    touched_count: 2,
  },
  {
    change_id: "chg-222222bbbbbb",
    kind: "nl_edit",
    summary: "对话修改 FB_Conveyor 速度逻辑",
    status: "expired",
    updated_at: 1_790_000_100,
    touched: 1,
  },
];

const GATEWAY_CHANGE = {
  change_id: "chg-111111aaaaaa",
  status: "applied",
  intent: { kind: "writeback", request: "回写", summary: "回写 2 个块" },
  verification: { v0_parsed: "pass", v1_static: "pass", v2_tia_compile: "pass" },
  touched_blocks: ["FB_Motor", "DB_MotorData"],
};

/* ---- V 等级工具 ---- */

describe("V 等级四态文案", () => {
  it("四态映射：pass=已通过 / fail=未通过 / pending=待执行 / skipped=未运行", () => {
    expect(vStatusText("pass")).toBe("已通过");
    expect(vStatusText("fail")).toBe("未通过");
    expect(vStatusText("pending")).toBe("待执行");
    expect(vStatusText("skipped")).toBe("未运行");
  });

  it("未设与脏数据一律按「未运行」展示（未知≠通过）", () => {
    expect(vStatusText(undefined)).toBe("未运行");
    expect(vStatusText(null)).toBe("未运行");
    expect(vStatusText("")).toBe("未运行");
    expect(vStatusText("ok")).toBe("未运行");
    expect(vStatusOf("weird")).toBe("skipped");
  });

  it("前置符号：✓ 已通过 / ✗ 未通过 / · 待执行与未运行", () => {
    expect(vStatusMark("pass")).toBe("✓");
    expect(vStatusMark("fail")).toBe("✗");
    expect(vStatusMark("pending")).toBe("·");
    expect(vStatusMark("skipped")).toBe("·");
    expect(vStatusMark(undefined)).toBe("·");
  });

  it("V_LEVELS 四级齐全且键与契约一致", () => {
    expect(V_LEVELS.map((v) => v.key)).toEqual([
      "v0_parsed",
      "v1_static",
      "v2_tia_compile",
      "v3_behavior",
    ]);
    V_LEVELS.forEach((v) => {
      expect(v.label.trim().length).toBeGreaterThan(0);
      expect(v.full.startsWith(v.label.slice(0, 2))).toBe(true);
    });
  });

  it("确认弹窗快照：V0/V1 已通过、V2 待执行、V3 未运行", () => {
    expect(CONFIRM_V_SNAPSHOT).toEqual({
      v0_parsed: "pass",
      v1_static: "pass",
      v2_tia_compile: "pending",
      v3_behavior: "skipped",
    });
  });
});

/* ---- 短码 / 指纹 / 时间 / 状态文案 ---- */

describe("短码·基线指纹·时间·状态文案", () => {
  it("shortChangeId：契约 id 取 hex 前 8 位；不合规退末 8 字符；空 → —", () => {
    expect(shortChangeId("chg-0a1b2c3d4e5f")).toBe("0a1b2c3d");
    expect(shortChangeId("CHG-ABCDEF123456")).toBe("abcdef12");
    expect(shortChangeId("some-funny-long-id")).toBe("-long-id");
    expect(shortChangeId("")).toBe("—");
    expect(shortChangeId(undefined)).toBe("—");
  });

  it("baselineFingerprint：去 sha256: 前缀取前 12 位；缺失 → —", () => {
    expect(baselineFingerprint({ project_hash: "sha256:ABCDEF1234567890" })).toBe("abcdef123456");
    expect(baselineFingerprint({ project_hash: "1234567890abcd" })).toBe("1234567890ab");
    expect(baselineFingerprint({ project_hash: "" })).toBe("—");
    expect(baselineFingerprint({})).toBe("—");
    expect(baselineFingerprint(null)).toBe("—");
  });

  it("formatChangeTime：epoch 秒转 MM-DD HH:mm；非法 → —", () => {
    expect(formatChangeTime(1_790_000_000)).toMatch(/^\d{2}-\d{2} \d{2}:\d{2}$/);
    expect(formatChangeTime(0)).toBe("—");
    expect(formatChangeTime("abc")).toBe("—");
  });

  it("changeStatusText：九态文案 + 未登记值原样透出", () => {
    expect(changeStatusText("applied")).toBe("已应用");
    expect(changeStatusText("expired")).toBe("已过期");
    expect(changeStatusText("rolled_back")).toBe("已回滚");
    expect(changeStatusText("proposed")).toBe("已提议");
    expect(changeStatusText("future_state")).toBe("future_state");
    expect(changeStatusText("")).toBe("未知");
  });

  it("changeStatusGroup：applied=ok / 失败族=bad / 流转中与未知=hold", () => {
    expect(changeStatusGroup("applied")).toBe("ok");
    expect(changeStatusGroup("failed")).toBe("bad");
    expect(changeStatusGroup("expired")).toBe("bad");
    expect(changeStatusGroup("approved")).toBe("hold");
    expect(changeStatusGroup("")).toBe("hold");
  });
});

/* ---- 内置 mock ---- */

describe("内置示例事务", () => {
  it("id 符合契约 chg-<hex12>，四 V 齐全且均为合法四态", () => {
    const m = mockChange();
    expect(m.change_id).toMatch(/^chg-[0-9a-f]{12}$/);
    expect(m.change_id).toBe(MOCK_CHANGE_ID);
    V_LEVELS.forEach((v) => {
      const st = (m.verification ?? {})[v.key];
      expect(["pass", "fail", "pending", "skipped"]).toContain(st);
    });
    expect(m.status).toBe("applied");
  });

  it("mockChangeMeta 走同一归一管道：短码可截、影响块数来自 touched_blocks", () => {
    const meta = mockChangeMeta();
    expect(meta.change_id).toBe(MOCK_CHANGE_ID);
    expect(meta.touched_count).toBe(2);
    expect(meta.kind).toBe("writeback");
    expect(meta.verification?.v2_tia_compile).toBe("pass");
  });

  it("mockChange 返回深拷贝，调用方改动不污染内置样例", () => {
    const a = mockChange();
    a.status = "expired";
    (a.verification as Record<string, unknown>).v2_tia_compile = "fail";
    const b = mockChange();
    expect(b.status).toBe("applied");
    expect(b.verification?.v2_tia_compile).toBe("pass");
  });
});

/* ---- normalizeChangeMeta ---- */

describe("normalizeChangeMeta", () => {
  it("兼容 id / change_id 两种字段与 touched 数字 / touched_blocks 数组", () => {
    const a = normalizeChangeMeta(GATEWAY_META[0]);
    expect(a?.change_id).toBe("chg-111111aaaaaa");
    expect(a?.touched_count).toBe(2);
    const b = normalizeChangeMeta(GATEWAY_META[1]);
    expect(b?.change_id).toBe("chg-222222bbbbbb");
    expect(b?.touched_count).toBe(1);
  });

  it("完整事务也能归一（intent 摘要 + impact.blocks 兜底影响块数）", () => {
    const meta = normalizeChangeMeta({
      change_id: "chg-333333cccccc",
      intent: { kind: "fix", request: "修复编译错误", summary: "修正 FB_X 类型" },
      status: "failed",
      updated_at: 123,
      impact: { blocks: ["FB_X", "FB_Y", "FB_Z"] },
      verification: { v0_parsed: "pass", v1_static: "fail" },
    });
    expect(meta).toEqual({
      change_id: "chg-333333cccccc",
      kind: "fix",
      summary: "修正 FB_X 类型",
      status: "failed",
      updated_at: 123,
      touched_count: 3,
      verification: {
        v0_parsed: "pass",
        v1_static: "fail",
        v2_tia_compile: undefined,
        v3_behavior: undefined,
      },
    });
  });

  it("无 id 的坏行返回 null；非对象同样 null", () => {
    expect(normalizeChangeMeta({ summary: "no id" })).toBeNull();
    expect(normalizeChangeMeta(null)).toBeNull();
    expect(normalizeChangeMeta("chg-0a1b2c3d4e5f")).toBeNull();
  });
});

/* ---- changeJsonPreview ---- */

describe("changeJsonPreview", () => {
  it("小事务完整序列化（含 change_id）", () => {
    const text = changeJsonPreview(GATEWAY_CHANGE);
    expect(text).toContain("chg-111111aaaaaa");
    expect(text).not.toContain("已截断");
  });

  it("超长事务截断并注明总字符数", () => {
    const big = { change_id: "chg-0a1b2c3d4e5f", ops: [{ blob: "x".repeat(50_000) }] };
    const text = changeJsonPreview(big, 1000);
    expect(text.length).toBeLessThan(big.ops[0].blob.length);
    expect(text).toContain("已截断");
    expect(text).toContain(String(JSON.stringify(big, null, 2).length));
  });
});

/* ---- fetchChanges（mock-first 回退契约） ---- */

describe("fetchChanges", () => {
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

    const res = await fetchChanges();
    expect(res.origin).toBe("gateway");
    expect(res.items.map((m) => m.change_id)).toEqual([
      "chg-111111aaaaaa",
      "chg-222222bbbbbb",
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/v1/plc/canvas/changes");
    // 网关成功路径不应有回退日志
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("网关 200 空数组是真实答案：items 空且不回退 mock", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes([])) as unknown as typeof fetch;
    const res = await fetchChanges();
    expect(res.origin).toBe("gateway");
    expect(res.items).toEqual([]);
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("404（端点未上线）→ 一条内置示例事务：一条 debug、不抛错", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(jsonRes({ detail: "not found" }, 404)) as unknown as typeof fetch;

    const res = await fetchChanges();
    expect(res.origin).toBe("mock");
    expect(res.items).toHaveLength(1);
    expect(res.items[0]?.change_id).toBe(MOCK_CHANGE_ID);
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it("网络错误 / 网关不可达同样回退 mock", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("fetch failed")) as unknown as typeof fetch;
    const res = await fetchChanges();
    expect(res.origin).toBe("mock");
    expect(res.items[0]?.change_id).toBe(MOCK_CHANGE_ID);
  });

  it("响应形态不符（非数组）→ 回退 mock", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes({ hello: 1 })) as unknown as typeof fetch;
    const res = await fetchChanges();
    expect(res.origin).toBe("mock");
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });
});

/* ---- fetchChange（mock-first 回退契约） ---- */

describe("fetchChange", () => {
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

    const res = await fetchChange(MOCK_CHANGE_ID);
    expect(res?.origin).toBe("mock");
    expect(res?.change.change_id).toBe(MOCK_CHANGE_ID);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("空 id 返回 null（防御）", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    expect(await fetchChange("")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("网关 200 → 完整事务透传 origin=gateway", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(GATEWAY_CHANGE));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await fetchChange("chg-111111aaaaaa");
    expect(res?.origin).toBe("gateway");
    expect(res?.change.change_id).toBe("chg-111111aaaaaa");
    expect(res?.change.touched_blocks).toEqual(["FB_Motor", "DB_MotorData"]);
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("/api/v1/plc/canvas/changes/chg-111111aaaaaa");
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("404 / 网络错误 → 回退示例事务并打一条 debug", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonRes({ detail: "no such change" }, 404))
      .mockRejectedValueOnce(new TypeError("fetch failed")) as unknown as typeof fetch;

    const a = await fetchChange("chg-999999999999");
    expect(a?.origin).toBe("mock");
    expect(a?.change.change_id).toBe(MOCK_CHANGE_ID);
    const b = await fetchChange("chg-888888888888");
    expect(b?.origin).toBe("mock");
    expect(debugSpy).toHaveBeenCalledTimes(2);
  });
});
