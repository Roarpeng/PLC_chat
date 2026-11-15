import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, processosApi } from "./api";
import { DEFAULT_ACTOR, loadActor, roleDeniedText, saveActor } from "./actor";

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

afterEach(() => { vi.unstubAllGlobals(); saveActor(DEFAULT_ACTOR); });

describe("actor identity headers", () => {
  it("injects X-Actor-Id / X-Actor-Role on every call", async () => {
    saveActor({ id: "op9", role: "ReleaseApprover" });
    const fn = mockFetch(200, { projects: [] });
    await processosApi.projects();
    const init = fn.mock.calls[0][1];
    expect(init.headers["X-Actor-Id"]).toBe("op9");
    expect(init.headers["X-Actor-Role"]).toBe("ReleaseApprover");
  });

  it("falls back to the default Viewer identity when nothing is stored", () => {
    saveActor(DEFAULT_ACTOR);
    expect(loadActor()).toEqual({ id: "demo_operator", role: "Viewer" });
  });
});

/* Contract-locked shapes: every binding mirrors the backend route signature. */
describe("processosApi field bindings (contract-locked shapes)", () => {
  it("listBaselines GETs the project baselines", async () => {
    const fn = mockFetch(200, { baselines: [{ baseline_id: "b3_1", kind: "B3", project_id: "P1", status: "UNVERIFIED_ONLINE", created_at: "t", seq: 1 }] });
    const r = await processosApi.listBaselines("P1");
    expect(r.baselines[0].kind).toBe("B3");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/projects/P1/baselines");
    expect(fn.mock.calls[0][1].method).toBe("GET");
  });

  it("recordB1 posts spec_hash/revision/profile_id from the server's own view", async () => {
    const fn = mockFetch(200, { baseline_id: "b1_1", kind: "B1", project_id: "P1", status: "FROZEN", created_at: "t", seq: 1 });
    await processosApi.recordB1("P1", { spec_hash: "abc", revision: 2, profile_id: "hr001" });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/projects/P1/baselines/b1");
    expect(JSON.parse(init.body)).toMatchObject({ spec_hash: "abc", revision: 2, profile_id: "hr001" });
  });

  it("recordB3 posts deployed_build_id/verification with optional field evidence", async () => {
    const fn = mockFetch(200, { baseline_id: "b3_2", kind: "B3", project_id: "P1", status: "VERIFIED", created_at: "t", seq: 2 });
    const r = await processosApi.recordB3("P1", {
      deployed_build_id: "build_219", device_id: "plc_01", plc_checksum: "cd".repeat(32),
      operator: "comm_chen", commissioned_at: "2026-11-15T14:00:00+08:00",
      verification: "FIELD_VERIFIED",
    });
    expect(r.status).toBe("VERIFIED");
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/projects/P1/baselines/b3");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ deployed_build_id: "build_219", device_id: "plc_01", verification: "FIELD_VERIFIED" });
    expect(body.build_id).toBeUndefined(); // legacy field name must be gone
  });

  it("compareBaselines returns verdict, b2_vs_b3 and summary objects", async () => {
    mockFetch(200, {
      project_id: "P1", verdict: "FROZEN_DRIFT", b2_vs_b3: "DRIFT",
      differences: [{ kind: "ARCHIVE_SHA256_MISMATCH", detail: "FB_Clamp" }],
      latest_b1: { baseline_id: "b1_1" }, latest_b2: { baseline_id: "b2_1" }, latest_b3: { baseline_id: "b3_1" },
    });
    const r = await processosApi.compareBaselines("P1");
    expect(r.verdict).toBe("FROZEN_DRIFT");
    expect(r.b2_vs_b3).toBe("DRIFT");
    expect(r.differences[0].kind).toBe("ARCHIVE_SHA256_MISMATCH");
    expect(r.latest_b3?.baseline_id).toBe("b3_1");
  });

  it("buildImpact posts object_id/patch_ops/reason and getImpact GETs by report id", async () => {
    const fn = mockFetch(200, {
      report_id: "imp_1", project_id: "P1", generated_at: "t",
      subject: { object_id: "cm_x", display_name: "夹紧气缸", reason: "r" },
      affected: { units: [], ems: [], cms: [], steps: [] }, callers: [],
      alarm_definitions: [], io_db_interfaces: ["UNKNOWN"], hmi_messages: [],
      state_retention_risk: "HIGH", online_load_impact: "UNKNOWN", regression_tests: [],
      deployment_notes: [], unknown_fields: ["io_db_interfaces"], blocked_high_risk_delivery: true,
    });
    const r = await processosApi.buildImpact("P1", {
      object_id: "cm_x", patch_ops: [{ op: "set", path: "/x", value: 1 }], reason: "超时 3s→5s",
    });
    expect(r.blocked_high_risk_delivery).toBe(true);
    expect(JSON.parse(fn.mock.calls[0][1].body)).toMatchObject({ object_id: "cm_x", reason: "超时 3s→5s" });
    expect(fn.mock.calls[0][0]).toBe("/api/processos/projects/P1/impact");
    const fn2 = mockFetch(200, { report_id: "imp_1" });
    await processosApi.getImpact("imp_1");
    expect(fn2.mock.calls[0][0]).toBe("/api/processos/impact/imp_1");
  });

  it("deployment records: list with optional pid filter, create with tests rows", async () => {
    const fn = mockFetch(200, { records: [{ record_id: "dep_1", project_id: "P1", build_id: "b", artifact_sha256: "s", device_id: "d", operator: "o", plc_checksum: "c", commissioned_at: "t", tests: [{ name: "retest", passed: true, note: "" }], result: "COMMISSIONED" }] });
    const r = await processosApi.listDeploymentRecords("P1");
    expect(r.records[0].result).toBe("COMMISSIONED");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/deployments/records?project_id=P1");
    const fn2 = mockFetch(200, {});
    await processosApi.listDeploymentRecords();
    expect(fn2.mock.calls[0][0]).toBe("/api/processos/deployments/records");
    const fn3 = mockFetch(200, { record_id: "dep_2" });
    await processosApi.createDeploymentRecord({
      project_id: "P1", build_id: "b", artifact_sha256: "s", device_id: "d", operator: "o",
      plc_checksum: "c", tests: [{ name: "t1", passed: false, note: "n" }], result: "ROLLED_BACK",
    });
    expect(JSON.parse(fn3.mock.calls[0][1].body).result).toBe("ROLLED_BACK");
  });

  it("gateway precheck posts window string + object-or-null gate evidence", async () => {
    const fn = mockFetch(200, {
      precheck_id: "pre_1", project_id: "P1", build_id: "b", device_id: "d",
      window: "w", authorized_window: false, satisfied: ["ONLINE_COMPARE"],
      missing: ["AUTHORIZED_WINDOW"], blocked_by: [], ready: false,
      one_click_online: false, note: "n", created_at: "t",
    });
    const r = await processosApi.gatewayPrecheck({
      project_id: "P1", build_id: "b", device_id: "d",
      window: "2026-11-15T08:00 ~ 2026-11-15T10:00",
      online_compare: { attested: true }, retain_assessment: null,
      second_person: "lead", rollback_plan: { attested: true }, authorized_window: false,
    });
    expect(r.ready).toBe(false);
    expect(r.missing).toContain("AUTHORIZED_WINDOW");
    const body = JSON.parse(fn.mock.calls[0][1].body);
    expect(body.window).toBe("2026-11-15T08:00 ~ 2026-11-15T10:00");
    expect(body.online_compare).toEqual({ attested: true });
    expect(body.retain_assessment).toBeNull();
  });

  it("gateway execute posts {precheck_id, confirm: true, actor}", async () => {
    const fn = mockFetch(200, {
      precheck_id: "pre_1", actor: "lead", backend: "MockBackend",
      result: { ok: true }, one_click_online: false, note: "n", executed_at: "t",
    });
    const r = await processosApi.gatewayExecute({ precheck_id: "pre_1", confirm: true, actor: "lead" });
    expect(r.precheck_id).toBe("pre_1");
    expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ precheck_id: "pre_1", confirm: true, actor: "lead" });
  });

  it("gateway execute blocked with SAFETY_SCOPE_BLOCKED surfaces the machine code", async () => {
    mockFetch(501, { error: "safety scope", code: "SAFETY_SCOPE_BLOCKED" });
    await expect(processosApi.gatewayExecute({ precheck_id: "pre_1", confirm: true, actor: "x" }))
      .rejects.toMatchObject({ status: 501, code: "SAFETY_SCOPE_BLOCKED" });
  });

  it("403 ROLE_FORBIDDEN yields a uniform role hint from the required list", async () => {
    mockFetch(403, { error: "forbidden", code: "ROLE_FORBIDDEN", required: ["CommissioningEngineer", "Admin"], action: "deployment.gateway.execute" });
    const p = processosApi.gatewayExecute({ precheck_id: "p", confirm: true, actor: "x" });
    await expect(p).rejects.toBeInstanceOf(ApiError);
    await p.catch(e => {
      const txt = roleDeniedText(e);
      expect(txt).toContain("CommissioningEngineer");
      expect(txt).toContain("ROLE_FORBIDDEN");
    });
  });

  it("ingestEvent posts source/payload/quality only; objectTelemetry GETs /objects/{id}/telemetry", async () => {
    const fn = mockFetch(200, { event_id: "e1", object_id: "cm x", source: "MANUAL_UPLOAD", event_time: "t", payload: {}, quality: "REPORTED", evidence_level: "MANUAL", ingested_at: "t2" });
    await processosApi.ingestEvent({ object_id: "cm x", source: "MANUAL_UPLOAD", event_time: "t", payload: { a: 1 }, quality: "REPORTED" });
    const body = JSON.parse(fn.mock.calls[0][1].body);
    expect(body.source).toBe("MANUAL_UPLOAD");
    expect(body.evidence_level).toBeUndefined(); // derived server-side, never claimed by the client
    expect(fn.mock.calls[0][0]).toBe("/api/processos/telemetry/events");
    const fn2 = mockFetch(200, { object_id: "cm x", events: [] });
    await processosApi.objectTelemetry("cm x");
    expect(fn2.mock.calls[0][0]).toBe("/api/processos/objects/cm%20x/telemetry");
  });

  it("reportFieldModification posts field_state.blocks and parses the drift report", async () => {
    const fn = mockFetch(200, {
      project_id: "P1", captured_at: "t", source: "MANUAL_UPLOAD", b2_vs_b3: "DRIFT",
      drift_detected: true,
      changed_blocks: [{ block_name: "FB_Clamp", b2_sha256: "aa", field_sha256: "bb", reason: "content_differs" }],
      three_way: { native_changed: ["FB_Clamp"], field_changed: ["FB_Clamp"], design_changed: [], unknown: ["design_baseline_b1"] },
      unmapped_native_code: ["OB_Safety"], managed_native_overrides: [],
      frozen: true, error_code: "DRIFT_DETECTED", note: "n",
    });
    const r = await processosApi.reportFieldModification("P1", {
      field_state: { blocks: [{ block_name: "FB_Clamp", content_sha256: "bb" }] },
    });
    expect(r.drift_detected).toBe(true);
    expect(r.error_code).toBe("DRIFT_DETECTED");
    expect(r.changed_blocks[0].reason).toBe("content_differs");
    const body = JSON.parse(fn.mock.calls[0][1].body);
    expect(body.field_state.blocks[0]).toEqual({ block_name: "FB_Clamp", content_sha256: "bb" });
    expect(fn.mock.calls[0][0]).toBe("/api/processos/projects/P1/field-modifications");
  });

  it("projectSourcemap GETs the block inventory for fieldmod prefill", async () => {
    const fn = mockFetch(200, { project_id: "P1", builds: ["build_219"], source_map: [] });
    await processosApi.projectSourcemap("P1");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/projects/P1/sourcemap");
  });

  it("rbac roles returns the role matrix with permissions; audit hits query params", async () => {
    const fn = mockFetch(200, { roles: ["Viewer", "Admin"], permissions: { "rbac.audit.read": ["Admin"] } });
    const r = await processosApi.rbacRoles();
    expect(r.roles[0]).toBe("Viewer");
    expect(r.permissions["rbac.audit.read"]).toEqual(["Admin"]);
    const fn2 = mockFetch(200, { entries: [{ ts: "t", seq: 1, actor_id: "op", role: "Admin", action: "deployment.record", target: "/x", result: "FORBIDDEN", extra: {} }] });
    const a = await processosApi.rbacAudit({ limit: 20, action: "deploy" });
    expect(a.entries[0].action).toBe("deployment.record");
    expect(a.entries[0].result).toBe("FORBIDDEN");
    expect(fn2.mock.calls[0][0]).toBe("/api/processos/rbac/audit?limit=20&action=deploy");
  });

  it("traceGraphs GETs the four-graph object dump (canvases data source)", async () => {
    const obj = (kind: string) => ({
      object_id: `${kind}_1`, kind, graph: "PhysicalGraph", display_name: "x",
      aliases: [], attributes: {}, status: "DESIGNED", created_at: 1, history: [],
    });
    const fn = mockFetch(200, {
      PhysicalGraph: [obj("station"), obj("component")], AfGraph: [obj("af_cm")],
      BehaviorGraph: [obj("behavior_step")], EvidenceGraph: [obj("build")],
    });
    const r = await processosApi.traceGraphs();
    expect(r.PhysicalGraph.map(o => o.kind)).toEqual(["station", "component"]);
    expect(r.AfGraph[0].object_id).toBe("af_cm_1");
    expect(r.BehaviorGraph).toHaveLength(1);
    expect(r.EvidenceGraph[0].kind).toBe("build");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/trace/graphs");
    expect(fn.mock.calls[0][1].method).toBe("GET");
  });
});
