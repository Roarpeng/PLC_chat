/** 服务端会话同步的合并/差量推送逻辑(网络与浏览器全局均 mock,node 环境)。 */
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSession } from "./sessions";

vi.mock("../lib/plcGateway", () => ({
  requestPlc: vi.fn(),
}));

import { requestPlc } from "../lib/plcGateway";
import { bootstrapRemoteMerge, persistAndSync } from "./sessionSync";

const mockedRequest = vi.mocked(requestPlc);

function sess(id: string, updatedAt: number, msgs = 1): ChatSession {
  return {
    id,
    title: `t-${id}`,
    createdAt: updatedAt - 10,
    updatedAt,
    messages: Array.from({ length: msgs }, (_, i) => ({
      id: `${id}-m${i}`,
      role: "user" as const,
      text: "x",
      ts: updatedAt,
    })),
    canvas: { project_name: "P", blocks: {}, hmi_widgets: {}, tags: {} },
  };
}

beforeAll(() => {
  const store = new Map<string, string>();
  (globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
  // 动态委托:vitest useFakeTimers 后 globalThis.setTimeout 即为假定时器
  (globalThis as Record<string, unknown>).window = {
    setTimeout: (...a: Parameters<typeof setTimeout>) => globalThis.setTimeout(...a),
    clearTimeout: (id: ReturnType<typeof setTimeout>) => globalThis.clearTimeout(id),
  };
});

describe("bootstrapRemoteMerge", () => {
  beforeEach(() => {
    localStorage.clear();
    mockedRequest.mockReset();
  });

  it("服务端独有的会话以占位进入列表(pendingRemote)", async () => {
    mockedRequest.mockResolvedValueOnce([
      { id: "remote1", title: "远程会话", createdAt: 5, updatedAt: 6, msgCount: 2 },
    ] as never);
    const merged = await bootstrapRemoteMerge([sess("local1", 100)]);
    expect(merged.map((s) => s.id).sort()).toEqual(["local1", "remote1"]);
    const ph = merged.find((s) => s.id === "remote1")!;
    expect(ph.pendingRemote).toBe(true);
    expect(ph.messages).toEqual([]);
  });

  it("本地更新则保留本地;网关不可达原样返回", async () => {
    mockedRequest.mockResolvedValueOnce([
      { id: "a", title: "a", createdAt: 1, updatedAt: 2, msgCount: 0 },
    ] as never);
    const merged = await bootstrapRemoteMerge([sess("a", 50)]);
    expect(merged[0].updatedAt).toBe(50);
    expect(merged[0].pendingRemote).toBeUndefined();
    mockedRequest.mockRejectedValueOnce(new Error("down") as never);
    const local = [sess("b", 9)];
    expect(await bootstrapRemoteMerge(local)).toEqual(local);
  });
});

describe("persistAndSync 差量推送", () => {
  beforeEach(() => {
    localStorage.clear();
    mockedRequest.mockReset();
    vi.useFakeTimers();
  });

  it("updatedAt 变化的会话防抖推送,未变的不重复推", async () => {
    mockedRequest.mockResolvedValue([] as never);
    const a = sess("a", 100);
    const b = sess("b", 100);
    persistAndSync([a, b]);
    persistAndSync([{ ...a, updatedAt: 100 }, b]); // a 未变:差量拦截
    vi.advanceTimersByTime(2000);
    await Promise.resolve();
    const putCalls = mockedRequest.mock.calls.filter(
      (c) =>
        String(c[0]).includes("/canvas/sessions/") &&
        (c[1] as RequestInit | undefined)?.method === "PUT",
    );
    expect(putCalls.length).toBe(2); // a、b 各一次;a 第二次被拦
    expect(localStorage.getItem("plc-copilot.sessions.v1") ?? "").toContain('"a"');
  });
});
