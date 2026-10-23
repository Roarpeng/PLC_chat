import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MOCK_BLOCK_NAME,
  SOURCE_KINDS,
  fetchSourceArtifact,
  isSourceKind,
  mockArtifact,
  pickActiveJobId,
} from "./sourceCompare";
import type { PlcJobSummary } from "../lib/plcGateway";

/* ---- 测试夹具 ---- */

const job = (id: string, over: Partial<PlcJobSummary> = {}): PlcJobSummary =>
  ({
    id,
    status: "ready",
    source_type: "openness",
    coverage: {},
    ...over,
  }) as PlcJobSummary;

const GATEWAY_BODY = {
  job_id: "job-1",
  block_name: "FB_Motor",
  kind: "flgnet_xml",
  content: "<Document><FlgNet>…</FlgNet></Document>",
};

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/* ---- pickActiveJobId ---- */

describe("pickActiveJobId", () => {
  it("project_name 命中的 ready 作业优先", () => {
    const jobs = [
      job("other", { project_name: "别的工作", status: "failed" }),
      job("first-ready", { project_name: "别的工作" }),
      job("matched", { project_name: "产线A" }),
    ];
    expect(pickActiveJobId(jobs, "产线A")).toBe("matched");
  });

  it("无同名时退回第一个 ready；无 ready 返回 null", () => {
    expect(pickActiveJobId([job("a", { project_name: "X" })], "Y")).toBe("a");
    expect(
      pickActiveJobId([job("a", { status: "failed" }), job("b", { status: "running" })], "Y"),
    ).toBeNull();
    expect(pickActiveJobId([], "Y")).toBeNull();
  });
});

/* ---- isSourceKind / mock ---- */

describe("mock 与 kind 工具", () => {
  it("三种 kind 均有非空且互不相同的内置示例", () => {
    expect(SOURCE_KINDS.map((k) => k.kind)).toEqual(["flgnet_xml", "literal_scl", "ast_trace"]);
    const contents = SOURCE_KINDS.map((k) => mockArtifact(MOCK_BLOCK_NAME, k.kind).content);
    contents.forEach((c) => expect(c.trim().length).toBeGreaterThan(0));
    expect(new Set(contents).size).toBe(3);
  });

  it("isSourceKind 只放行契约三种 kind", () => {
    expect(isSourceKind("flgnet_xml")).toBe(true);
    expect(isSourceKind("literal_scl")).toBe(true);
    expect(isSourceKind("ast_trace")).toBe(true);
    expect(isSourceKind("semantic")).toBe(false);
    expect(isSourceKind(undefined)).toBe(false);
  });

  it("mockArtifact 标记 origin=mock 且不携带 job", () => {
    const m = mockArtifact("FB_X", "ast_trace");
    expect(m.origin).toBe("mock");
    expect(m.job_id).toBeNull();
    expect(m.block_name).toBe("FB_X");
  });
});

/* ---- fetchSourceArtifact（mock-first 回退契约） ---- */

describe("fetchSourceArtifact", () => {
  const realFetch = globalThis.fetch;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("网关 200 时透传 content 并标记 origin=gateway", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(GATEWAY_BODY));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const art = await fetchSourceArtifact("FB_Motor", "flgnet_xml", { jobId: "job-1" });
    expect(art.origin).toBe("gateway");
    expect(art.content).toBe(GATEWAY_BODY.content);
    expect(art.job_id).toBe("job-1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("/api/v1/plc/jobs/job-1/blocks/FB_Motor/source?kind=flgnet_xml");
    // 网关成功路径不应有回退日志
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("404（块无工件）静默回退 mock：一条 debug、不抛错", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(jsonRes({ detail: "artifact not found" }, 404)) as unknown as typeof fetch;

    const art = await fetchSourceArtifact("FB_Motor", "literal_scl", { jobId: "job-1" });
    expect(art.origin).toBe("mock");
    expect(art.kind).toBe("literal_scl");
    expect(art.content).toContain("#q_bMotorFwd :=");
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it("网络错误 / 网关不可达同样回退 mock", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("fetch failed")) as unknown as typeof fetch;

    const art = await fetchSourceArtifact("FB_Motor", "ast_trace", { jobId: "job-1" });
    expect(art.origin).toBe("mock");
    expect(art.content).toContain("[block] FB_Motor");
    expect(art.content).toContain("step:");
  });

  it("无活跃 job（jobId=null 且不给 projectName）直接 mock，不触网", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const art = await fetchSourceArtifact("FB_Motor", "flgnet_xml", { jobId: null });
    expect(art.origin).toBe("mock");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it("未给 jobId 时用 jobs 列表现场解析活跃作业", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonRes([job("job-9", { project_name: "产线A" })]))
      .mockResolvedValueOnce(jsonRes(GATEWAY_BODY));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const art = await fetchSourceArtifact("FB_Motor", "flgnet_xml", { projectName: "产线A" });
    expect(art.origin).toBe("gateway");
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).toContain("/api/v1/plc/jobs?limit=10");
    expect(urls[1]).toContain("/api/v1/plc/jobs/job-9/blocks/FB_Motor/source");
  });
});
