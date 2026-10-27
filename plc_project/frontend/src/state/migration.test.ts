/** 旧 sessions → Project/Conversation 本地迁移逻辑(localStorage 与网关均 mock,node 环境)。 */
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSession } from "./sessions";

vi.mock("../lib/plcGateway", () => ({
  requestPlc: vi.fn(),
}));

import { requestPlc } from "../lib/plcGateway";
import {
  MIGRATED_KEY,
  OLD_SESSIONS_KEY,
  PROJECTS_KEY,
  isMigrated,
  migrateLocalSessions,
  projectNameFromSession,
} from "./migration";
import { loadProjectRecords } from "./migration";

const mockedRequest = vi.mocked(requestPlc);

function sess(
  id: string,
  title: string,
  canvasName: string,
  msgs: number,
  updatedAt = 100,
): ChatSession {
  return {
    id,
    title,
    createdAt: updatedAt - 10,
    updatedAt,
    messages: Array.from({ length: msgs }, (_, i) => ({
      id: `${id}-m${i}`,
      role: "user" as const,
      text: "问",
      ts: updatedAt,
    })),
    canvas: { project_name: canvasName, blocks: {}, hmi_widgets: {}, tags: {} },
  };
}

function seedOld(sessions: ChatSession[]): void {
  localStorage.setItem(OLD_SESSIONS_KEY, JSON.stringify(sessions));
}

beforeAll(() => {
  const store = new Map<string, string>();
  (globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => store.delete(k),
    clear: () => store.clear(),
  };
});

beforeEach(() => {
  localStorage.clear();
  mockedRequest.mockReset();
});

describe("projectNameFromSession", () => {
  it("优先 canvas.project_name,其次标题「·」后段,最后标题/兜底", () => {
    expect(projectNameFromSession(sess("s1", "任意标题", "HR001", 0))).toBe("HR001");
    expect(projectNameFromSession(sess("s2", "导入 · 夹紧工站", "", 0))).toBe("夹紧工站");
    expect(projectNameFromSession(sess("s3", "标准工程 · XY", "  ", 0))).toBe("XY");
    const s = sess("s4", "会话标题", "", 0);
    expect(projectNameFromSession(s)).toBe("会话标题");
  });
});

describe("migrateLocalSessions", () => {
  it("按 project_name 分组建 Project + Conversations,上传并写新 key/标记,旧 key 不删", async () => {
    mockedRequest.mockResolvedValue({ id: "x", updated_at: 1 } as never);
    seedOld([
      sess("s-hr1", "会话一", "HR001", 2, 200),
      sess("s-hr2", "会话二", "HR001", 1, 300),
      sess("s-cl", "导入 · 夹紧工站", "", 1, 100),
    ]);

    const stats = await migrateLocalSessions();
    expect(stats).toEqual({
      projects_migrated: 2,
      conversations_migrated: 3,
      uploaded: true,
      skipped: false,
    });

    // 上传:每个工程 1 次 PUT project + N 次 PUT conversation(按记录交错)
    const puts = mockedRequest.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "PUT",
    );
    expect(puts.length).toBe(5); // 2 projects + 3 conversations
    const projPuts = puts.filter((c) => String(c[0]).includes("/canvas/projects/"));
    const convPuts = puts.filter((c) => String(c[0]).includes("/canvas/conversations/"));
    expect(projPuts.length).toBe(2);
    expect(convPuts.length).toBe(3);
    const projPut = JSON.parse((projPuts[0][1] as RequestInit).body as string);
    expect(projPut.project_name).toBe("HR001");
    expect(projPut.id).toMatch(/^prj-[0-9a-f]{12}$/);

    // 新 key:2 条记录,HR001 归并 2 对话,工程 updated 取组内最新
    const records = loadProjectRecords();
    expect(records.length).toBe(2);
    const hr = records.find((r) => r.project.name === "HR001")!;
    expect(hr.conversations.length).toBe(2);
    expect(hr.project.updatedAt).toBe(300);
    // 会话消息按会话归位(1 条与 2 条各一),画布不进对话
    expect(hr.conversations.map((c) => c.messages.length).sort()).toEqual([1, 2]);
    expect(hr.conversations.every((c) => c.projectId === hr.project.id)).toBe(true);
    // 标记 + 旧 key 保留
    expect(isMigrated()).toBe(true);
    expect(localStorage.getItem(MIGRATED_KEY)).toBe("done");
    expect(localStorage.getItem(OLD_SESSIONS_KEY)).toContain("s-hr1");
  });

  it("已迁移(skipped)且无旧数据时:零请求、零统计", async () => {
    localStorage.setItem(MIGRATED_KEY, "done");
    const stats = await migrateLocalSessions();
    expect(stats).toEqual({
      projects_migrated: 0,
      conversations_migrated: 0,
      uploaded: false,
      skipped: true,
    });
    expect(mockedRequest.mock.calls.length).toBe(0);

    // 无旧 key 的首次迁移:写空数组新 key 并打标记
    localStorage.clear();
    mockedRequest.mockReset();
    const empty = await migrateLocalSessions();
    expect(empty.projects_migrated).toBe(0);
    expect(empty.uploaded).toBe(true);
    expect(loadProjectRecords()).toEqual([]);
    expect(isMigrated()).toBe(true);
    expect(mockedRequest.mock.calls.length).toBe(0);
  });

  it("网关不可达:纯本地迁移(不上传剩余),新 key 照写、标记照打", async () => {
    mockedRequest.mockRejectedValue(new Error("gateway down") as never);
    seedOld([sess("s-a", "会话A", "HR001", 1), sess("s-b", "会话B", "XY02", 1)]);

    const stats = await migrateLocalSessions();
    expect(stats.uploaded).toBe(false);
    expect(stats.skipped).toBe(false);
    expect(stats.projects_migrated).toBe(2);
    // 失败即停:只有第一个 PUT 尝试
    const puts = mockedRequest.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "PUT",
    );
    expect(puts.length).toBe(1);
    // 本地结构完整(含消息),后续可在网关恢复后由服务端迁移补齐
    const records = loadProjectRecords();
    expect(records.length).toBe(2);
    expect(records[0].conversations[0].messages.length).toBe(1);
    expect(localStorage.getItem(PROJECTS_KEY)).toContain("HR001");
    expect(isMigrated()).toBe(true);
  });
});
