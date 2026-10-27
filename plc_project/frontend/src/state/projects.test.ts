/** Project/Conversation 前端 API 层(契约 docs/25 §1 · P 线):映射 + mock-first 降级。 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/plcGateway", () => ({
  requestPlc: vi.fn(),
}));

import { requestPlc } from "../lib/plcGateway";
import {
  createConversation,
  createProject,
  deleteConversation,
  deleteProject,
  fetchConversation,
  fetchConversations,
  fetchProject,
  fetchProjects,
  newConversationId,
  newProjectId,
  putConversation,
  putProject,
} from "./projects";

const mockedRequest = vi.mocked(requestPlc);

function proj() {
  return {
    id: "prj-aaa111bbb222",
    name: "HR001",
    createdAt: 1000,
    updatedAt: 2000,
    canvas: { project_name: "HR001", blocks: {}, hmi_widgets: {}, tags: {} },
  };
}

function conv(pid = "prj-aaa111bbb222") {
  return {
    id: "cv-111111111111",
    projectId: pid,
    title: "工艺讨论",
    createdAt: 1200,
    updatedAt: 1800,
    messages: [{ id: "m1", role: "user" as const, text: "hi", ts: 1500 }],
  };
}

beforeEach(() => {
  mockedRequest.mockReset();
});

describe("读接口:wire snake_case → 前端 camelCase", () => {
  it("fetchProjects 映射 meta 列表", async () => {
    mockedRequest.mockResolvedValueOnce([
      { id: "prj-1", name: "HR001", updated_at: 200, conversation_count: 3 },
    ] as never);
    const metas = await fetchProjects();
    expect(mockedRequest.mock.calls[0][0]).toBe("/api/v1/plc/canvas/projects");
    expect(metas).toEqual([
      { id: "prj-1", name: "HR001", createdAt: 0, updatedAt: 200, conversationCount: 3 },
    ]);
  });

  it("fetchProject / fetchConversation 映射完整对象", async () => {
    mockedRequest.mockResolvedValueOnce({
      id: "prj-1",
      project_name: "HR001",
      canvas: { project_name: "HR001", blocks: {}, hmi_widgets: {}, tags: {} },
      created_at: 100,
      updated_at: 200,
      conversation_count: 1,
    } as never);
    const p = await fetchProject("prj-1");
    expect(p).not.toBeNull();
    expect(p!.name).toBe("HR001");
    expect(p!.canvas.project_name).toBe("HR001");
    expect(p!.conversationCount).toBe(1);

    mockedRequest.mockResolvedValueOnce({
      id: "cv-1",
      project_id: "prj-1",
      title: "t",
      created_at: 1,
      updated_at: 2,
      messages: [{ id: "m1", role: "user", text: "x", ts: 1 }],
    } as never);
    const c = await fetchConversation("cv-1");
    expect(c).not.toBeNull();
    expect(c!.projectId).toBe("prj-1");
    expect(c!.messages.length).toBe(1);

    mockedRequest.mockResolvedValueOnce([
      { id: "cv-1", project_id: "prj-1", title: "t", updated_at: 9 },
    ] as never);
    const metas = await fetchConversations("prj-1");
    expect(metas).toEqual([
      { id: "cv-1", projectId: "prj-1", title: "t", createdAt: 0, updatedAt: 9 },
    ]);
  });
});

describe("mock-first:404 / 网络错静默降级,不抛错", () => {
  it("读 → 空数组 / null;写/删 → false / null", async () => {
    mockedRequest.mockRejectedValue(new Error("gateway down") as never);
    await expect(fetchProjects()).resolves.toEqual([]);
    await expect(fetchConversations("prj-1")).resolves.toEqual([]);
    await expect(fetchProject("prj-1")).resolves.toBeNull();
    await expect(fetchConversation("cv-1")).resolves.toBeNull();
    await expect(deleteProject("prj-1")).resolves.toBe(false);
    await expect(deleteConversation("cv-1")).resolves.toBe(false);
    await expect(createProject("X")).resolves.toBeNull();
    await expect(createConversation("prj-1", "t")).resolves.toBeNull();
    await expect(putProject(proj())).resolves.toBeNull();
    await expect(putConversation(conv())).resolves.toBeNull();
  });
});

describe("写接口:调用契约与 camel → snake body", () => {
  it("putProject → PUT /canvas/projects/{id},body 为 snake_case 完整对象", async () => {
    mockedRequest.mockResolvedValueOnce({
      id: "prj-aaa111bbb222",
      name: "HR001",
      updated_at: 2000,
      conversation_count: 0,
    } as never);
    const meta = await putProject(proj());
    const [url, init] = mockedRequest.mock.calls[0];
    expect(url).toBe("/api/v1/plc/canvas/projects/prj-aaa111bbb222");
    expect((init as RequestInit).method).toBe("PUT");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      id: "prj-aaa111bbb222",
      project_name: "HR001",
      canvas: { project_name: "HR001", blocks: {}, hmi_widgets: {}, tags: {} },
      created_at: 1000,
      updated_at: 2000,
    });
    expect(meta).toEqual({
      id: "prj-aaa111bbb222",
      name: "HR001",
      createdAt: 0,
      updatedAt: 2000,
      conversationCount: 0,
    });
  });

  it("putConversation → PUT /canvas/conversations/{cid},只带消息不带画布", async () => {
    mockedRequest.mockResolvedValueOnce({
      id: "cv-111111111111",
      project_id: "prj-aaa111bbb222",
      title: "工艺讨论",
      updated_at: 1800,
    } as never);
    const meta = await putConversation(conv());
    const [url, init] = mockedRequest.mock.calls[0];
    expect(url).toBe("/api/v1/plc/canvas/conversations/cv-111111111111");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      id: "cv-111111111111",
      project_id: "prj-aaa111bbb222",
      title: "工艺讨论",
      messages: [{ id: "m1", role: "user", text: "hi", ts: 1500 }],
      created_at: 1200,
      updated_at: 1800,
    });
    expect("canvas" in body).toBe(false);
    expect(meta!.projectId).toBe("prj-aaa111bbb222");
  });

  it("createProject → POST {project_name, canvas?}", async () => {
    mockedRequest.mockResolvedValueOnce({
      id: "prj-new",
      project_name: "夹紧工站",
      canvas: { project_name: "夹紧工站", blocks: {}, hmi_widgets: {}, tags: {} },
      created_at: 1,
      updated_at: 1,
    } as never);
    const p = await createProject("夹紧工站");
    const [url, init] = mockedRequest.mock.calls[0];
    expect(url).toBe("/api/v1/plc/canvas/projects");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      project_name: "夹紧工站",
    });
    expect(p!.name).toBe("夹紧工站");
  });

  it("createConversation → POST /canvas/projects/{pid}/conversations {title}", async () => {
    mockedRequest.mockResolvedValueOnce({
      id: "cv-new",
      project_id: "prj-1",
      title: "新对话",
      created_at: 1,
      updated_at: 1,
      messages: [],
    } as never);
    const c = await createConversation("prj-1", "新对话");
    const [url, init] = mockedRequest.mock.calls[0];
    expect(url).toBe("/api/v1/plc/canvas/projects/prj-1/conversations");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ title: "新对话" });
    expect(c!.messages).toEqual([]);
  });

  it("deleteProject / deleteConversation → DELETE 正确 URL", async () => {
    mockedRequest.mockResolvedValue({ removed: "x" } as never);
    expect(await deleteProject("prj-1")).toBe(true);
    expect(await deleteConversation("cv-1")).toBe(true);
    expect(mockedRequest.mock.calls[0][0]).toBe("/api/v1/plc/canvas/projects/prj-1");
    expect((mockedRequest.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
    expect(mockedRequest.mock.calls[1][0]).toBe("/api/v1/plc/canvas/conversations/cv-1");
  });
});

describe("id 生成", () => {
  it("prj-/cv- 前缀 + 12 位 hex", () => {
    expect(newProjectId()).toMatch(/^prj-[0-9a-f]{12}$/);
    expect(newConversationId()).toMatch(/^cv-[0-9a-f]{12}$/);
    expect(newProjectId()).not.toBe(newProjectId());
  });
});
