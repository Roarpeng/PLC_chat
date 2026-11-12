/**
 * WP-04 V2 Workbench contract tests (offline, no DOM rendering).
 *
 * Covers: feature-flag routing, atomic patch reducer (409/422/optimistic
 * rollback), Undo not bypassing server revision, evidence-level preservation,
 * no-native-download rule, and the D-3 P0 wording correction.
 */
// @ts-ignore vitest 运行在 Node 环境；本仓库未安装 @types/node（与既有 steps.contract.test.ts 一致）
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  channelFromHash, hashForChannel, initialChannel, LEGACY_WIZARD_ROUTE, V2_ROUTE, V2_WORKBENCH_DEFAULT,
} from "./featureFlags";
import {
  SOURCE_PACKAGE_NOTICE,
  buildSequencePatch,
  canShowNativeDownload,
  deriveSyncCheck,
  initialViewState,
  reduceViewState,
  rebasePatch,
  wbRequestEnvelope,
  type JobView,
  type PatchResultV2,
} from "../state/workbench_v2";

/* Vitest runs as ESM: resolve sources relative to import.meta.url (no __dirname). */
const read = (relative: string) => readFileSync(new URL(`../${relative}`, import.meta.url), "utf-8");

const patchResult = (revision: number, hash: string): PatchResultV2 => ({
  revision,
  ir_sha256: hash,
  changed_ir_ids: ["S2"],
  source_map_dirty: ["FB_Sequence"],
  warnings: [],
  evidence_level: "offline",
  request_id: "req_1",
  idempotent_hit: false,
  derived: { manifest_sha256: "sha256:new", trace_frames: 250, scl_files: ["scl/FB_Sequence.scl"], source_map_entries: 44 },
});

afterEach(() => vi.unstubAllGlobals());

describe("feature flag / independent legacy route (Q-03)", () => {
  it("defaults to the V2 workbench", () => {
    expect(V2_WORKBENCH_DEFAULT).toBe(true);
    expect(initialChannel("")).toBe("v2");
    expect(initialChannel()).toBe("v2");
  });
  it("keeps the legacy wizard reachable by its own hash route", () => {
    expect(channelFromHash(LEGACY_WIZARD_ROUTE)).toBe("greenfield");
    expect(channelFromHash("#/classic")).toBe("workbench");
    expect(channelFromHash("#/unknown")).toBe("v2");
  });
  it("round-trips channel <-> hash so a refresh does not lose the workspace", () => {
    for (const c of ["v2", "greenfield", "workbench"] as const) {
      expect(channelFromHash(hashForChannel(c))).toBe(c);
    }
    expect(hashForChannel("v2")).toBe(V2_ROUTE);
  });
});

describe("atomic patch reducer (US-2 / US-6)", () => {
  it("IR_LOADED sets revision and hash from the SERVER, never a local truth", () => {
    const s = reduceViewState(initialViewState("prj_1"), {
      type: "IR_LOADED", revision: 7, irSha256: "sha256:server", evidenceLevel: "offline", ir: { process: {} },
    });
    expect(s.baseRevision).toBe(7);
    expect(s.irSha256).toBe("sha256:server");
    expect(s.inspector).toEqual({ process: {} });
  });

  it("PATCH_OK advances revision and records the three-way derived sync", () => {
    let s = reduceViewState(initialViewState("prj_1"), {
      type: "PATCH_START", record: { ops: [], reverseOps: [], baseRevision: 0, requestId: "r" },
    });
    s = reduceViewState(s, { type: "PATCH_OK", result: patchResult(1, "sha256:after") });
    expect(s.baseRevision).toBe(1);
    expect(s.busy).toBe(false);
    expect(s.optimistic).toBeNull();
    expect(s.lastSync?.ir).toBe("sha256:after");
    expect(s.lastSync?.scl).toContain("scl/FB_Sequence.scl");
  });

  it("409 conflict rolls back optimistic state and reports current_revision", () => {
    let s = reduceViewState(initialViewState("prj_1"), {
      type: "PATCH_START",
      record: { ops: [], reverseOps: [], baseRevision: 3, requestId: "r" },
      optimistic: { S2: 2000 },
    });
    s = reduceViewState(s, { type: "PATCH_CONFLICT", currentRevision: 9 });
    expect(s.conflict).toEqual({ code: "BASE_REVISION_CONFLICT", currentRevision: 9 });
    expect(s.optimistic).toBeNull();
    expect(s.baseRevision).toBe(0); // unchanged until the IR is re-read
    expect(s.diagnostics[0].message).toContain("409");
  });

  it("422 rejection annotates the offending node and keeps the IR hash", () => {
    let s = reduceViewState(initialViewState("prj_1"), {
      type: "IR_LOADED", revision: 2, irSha256: "sha256:unchanged", evidenceLevel: "offline", ir: {},
    });
    s = reduceViewState(s, {
      type: "PATCH_REJECTED",
      issues: [{ source_id: "S2", node_id: "S2", field: "guard", reason: "非法 Guard 类型" }],
      unchangedIrHash: "sha256:unchanged",
    });
    expect(s.nodeErrors.S2).toContain("非法 Guard 类型");
    expect(s.irSha256).toBe("sha256:unchanged");
    expect(s.diagnosticsOpen).toBe(true);
  });

  it("Undo/Redo re-issue a patch against the CURRENT server revision", () => {
    const record = { ops: [{ op: "set_step_parameter" }], reverseOps: [{ op: "set_step_parameter", value: 1000 }], baseRevision: 1, requestId: "r1" };
    const rebased = rebasePatch(record, 8);
    expect(rebased.base_revision).toBe(8);
    expect(rebased.ops).toEqual(record.reverseOps);
    expect(rebased.request_id).not.toBe(record.requestId);
  });

  it("buildSequencePatch always carries project_id / base_revision / request_id", () => {
    const p = buildSequencePatch("prj_1", 5, "S2", "min_duration_ms", 2000);
    expect(p.project_id).toBe("prj_1");
    expect(p.base_revision).toBe(5);
    expect(p.request_id).toBeTruthy();
    expect(p.ops[0]).toMatchObject({ op: "set_step_parameter", step_id: "S2", value: 2000 });
  });

  it("US-3 three-way sync check requires IR + Trace to change together", () => {
    const before = { ir: "sha256:a", trace: 250, scl: ["scl/FB_Sequence.scl"] };
    expect(deriveSyncCheck(before, { ir: "sha256:b", trace: 260, scl: ["scl/FB_Sequence.scl"] })).toBe(true);
    expect(deriveSyncCheck(before, { ir: "sha256:a", trace: 250, scl: ["scl/FB_Sequence.scl"] })).toBe(false);
    expect(deriveSyncCheck(null, before)).toBe(false);
  });
});

describe("evidence envelope + no fake success (US-7)", () => {
  it("preserves envelope-level evidence_level instead of unwrapping only data", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, code: 0, data: { revision: 3 }, message: "ok", error: null, evidence_level: "offline", request_id: "r1" }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const envelope = await wbRequestEnvelope<{ revision: number }>("/projects/p/ir");
    expect(envelope.evidence_level).toBe("offline");
    expect(envelope.data?.revision).toBe(3);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("409 is never retried and carries the backend code", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ ok: false, code: 409, data: { code: "BASE_REVISION_CONFLICT", current_revision: 9 }, message: "conflict", error: { code: "BASE_REVISION_CONFLICT", message: "conflict" }, evidence_level: "offline" }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(wbRequestEnvelope("/projects/p/patches")).rejects.toMatchObject({ status: 409, code: "BASE_REVISION_CONFLICT" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("native download button is allowed ONLY for a V19 real full chain", () => {
    const base: JobView = {
      job_id: "j1", state: "QUEUED", native_artifact: null, evidence_level: "pending_real_machine",
      evidence_id: "", compile: null, notice: "",
    };
    expect(canShowNativeDownload(base)).toBe(false);
    expect(canShowNativeDownload({ ...base, state: "NATIVE_ARCHIVED", evidence_level: "mocked" })).toBe(false);
    expect(canShowNativeDownload({ ...base, state: "NATIVE_ARCHIVED", evidence_level: "V19_real" })).toBe(false);
    expect(canShowNativeDownload({
      ...base, state: "NATIVE_ARCHIVED", evidence_level: "V19_real",
      native_artifact: { artifact_id: "a_1", kind: "zap19", sha256: "sha256:x", size_bytes: 1, reopen_ok: false },
    })).toBe(false);
    expect(canShowNativeDownload({
      ...base, state: "NATIVE_ARCHIVED", evidence_level: "V19_real",
      native_artifact: { artifact_id: "a_1", kind: "zap19", sha256: "sha256:x", size_bytes: 1, reopen_ok: true },
    })).toBe(true);
  });
});

describe("D-3 P0 wording correction (SOURCE_READY != NATIVE_ARCHIVED)", () => {
  it("uses the source-package wording and removes 'delivery complete'", () => {
    expect(SOURCE_PACKAGE_NOTICE).toBe("源码包就绪（非原生工程）");
    const deliver = read("shell/steps/StepDeliver.tsx");
    const machine = read("shell/steps/stepMachine.ts");
    const confirm = read("shell/steps/StepConfirm.tsx");
    expect(deliver).toContain("源码包就绪（非原生工程）");
    expect(machine).toContain("源码包就绪（非原生工程）");
    expect(deliver).not.toContain("本轮交付完成");
    expect(deliver).not.toContain("工程包已就绪");
    expect(machine).not.toContain("工程包已就绪");
    expect(confirm).not.toContain("工程包已生成");
    expect(`${deliver}${machine}${confirm}`).not.toContain("交付完成");
    expect(deliver).toContain("NATIVE_ARCHIVED");
    expect(deliver).toContain("待真机核验");
    /* 内部契约术语不得出现在旧向导首屏（既有 AC-1 静态契约）。 */
    expect(deliver).not.toContain("pending_real_machine");
  });
});
