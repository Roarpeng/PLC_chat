import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, processosApi } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_url: string, _init: any) => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: "x",
    text: async () => JSON.stringify(body),
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("processosApi", () => {
  it("createProject posts contract and returns revision", async () => {
    const fn = mockFetch(200, { project_id: "PRJ_CLAMP", revision: 1, profile_id: "p" });
    const r = await processosApi.createProject({ id: "PRJ_CLAMP" } as never);
    expect(r.revision).toBe(1);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/projects");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).contract.id).toBe("PRJ_CLAMP");
  });

  it("patch sends base_revision and ops", async () => {
    const fn = mockFetch(200, { revision: 2, contract: {} });
    await processosApi.patch("PRJ_CLAMP", 1, [{ op: "set", path: "/name", value: "x" }], "r1");
    const body = JSON.parse(fn.mock.calls[0][1].body);
    expect(body.base_revision).toBe(1);
    expect(body.ops[0].op).toBe("set");
    expect(body.request_id).toBe("r1");
  });

  it("throws ApiError with status on 409", async () => {
    mockFetch(409, { error: "revision conflict" });
    await expect(processosApi.patch("P", 1, [])).rejects.toBeInstanceOf(ApiError);
    mockFetch(409, { error: "revision conflict" });
    await expect(processosApi.patch("P", 1, [])).rejects.toMatchObject({ status: 409 });
  });

  it("validate hits the validate endpoint", async () => {
    const fn = mockFetch(200, { errors: [], warnings: [], checks: [], coverage: {}, evidence_level: "offline_verified", profile_id: "", ir_hash: "" });
    const r = await processosApi.validate("PRJ_CLAMP");
    expect(r.evidence_level).toBe("offline_verified");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/projects/PRJ_CLAMP/validate");
  });

  it("deliveryGate returns readiness", async () => {
    mockFetch(200, { ready: false, checks: { approved_and_hash_match: false }, spec_hash: "sha256:x", note: "" });
    const g = await processosApi.deliveryGate("P");
    expect(g.ready).toBe(false);
  });
});
