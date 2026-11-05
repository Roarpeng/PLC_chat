import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FORBIDDEN_ENDPOINTS,
  GF_API,
  assertNoSideEffects,
  beginEdit,
  bytesToBase64,
  canConfirm,
  confirmSpec,
  createDraft,
  exportMermaid,
  gateReason,
  hasSideEffects,
  isSafeGreenfieldPath,
  shortHash,
  uploadFiles,
  type GFState,
} from "./greenfield";

function fakeState(overrides: Partial<GFState> = {}): GFState {
  return {
    session_id: "s1",
    stage: "VALIDATING",
    stage_label: "校验中",
    locked_hint: "规格尚未确认，确认前禁止任何生成或写回",
    has_ir: true,
    has_contract: false,
    receipt: null,
    report: { ok: true, violations: [], open_questions: [] },
    specs: [],
    counters: { ops: 0, disk_writes: 0, writebacks: 0, generations: 0 },
    engineering_summary_shown: true,
    notes: [],
    ir: {},
    views: null,
    summary: { units: 1, ems: 2, cms: 3, edges: 12 },
    ir_only_fields: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("确认门禁纯函数", () => {
  it("校验通过且零副作用时允许确认", () => {
    expect(canConfirm(fakeState())).toBe(true);
    expect(hasSideEffects(fakeState())).toBe(false);
    expect(() => assertNoSideEffects(fakeState())).not.toThrow();
  });

  it("任何未授权副作用都阻止确认", () => {
    for (const key of ["ops", "disk_writes", "writebacks", "generations"]) {
      const state = fakeState({ counters: { ...fakeState().counters, [key]: 1 } });
      expect(hasSideEffects(state)).toBe(true);
      expect(canConfirm(state)).toBe(false);
      expect(() => assertNoSideEffects(state)).toThrow();
    }
  });

  it("已冻结版本的 spec 写盘不算新副作用（与后端同口径）", () => {
    const state = fakeState({
      stage: "LINKABLE",
      specs: [{ spec_version: 1, spec_hash: "sha256:aaa", frozen_at: "t" }],
      counters: { ops: 0, disk_writes: 1, writebacks: 0, generations: 0 },
    });
    expect(hasSideEffects(state)).toBe(false);
  });

  it("校验未过 / 回执未确认 / 摘要未看时给出解释性提示", () => {
    expect(gateReason(fakeState({ report: { ok: false, violations: [], open_questions: [] } }))).toContain("校验");
    expect(
      gateReason(
        fakeState({
          receipt: {
            receipt_id: "R1",
            status: "parsed",
            items_total: 1,
            items_accepted: 1,
            errors: [],
            user_confirmed: false,
          },
        }),
      ),
    ).toContain("回执");
    expect(gateReason(fakeState({ engineering_summary_shown: false }))).toContain("摘要");
  });

  it("短哈希与 base64 编码", () => {
    expect(shortHash("sha256:abcdef1234567890")).toBe("abcdef12");
    expect(shortHash(undefined)).toBe("—");
    expect(bytesToBase64(new Uint8Array([65, 66, 67]))).toBe("QUJD");
  });
});

describe("端点隔离（AC-4 / AC-6）", () => {
  it("所有 Greenfield 端点都在独立前缀且不含存量端点", () => {
    expect(isSafeGreenfieldPath(`${GF_API}/state`)).toBe(true);
    expect(isSafeGreenfieldPath(`${GF_API}/confirm`)).toBe(true);
    expect(isSafeGreenfieldPath("/api/v1/plc/canvas/state")).toBe(false);
    for (const forbidden of FORBIDDEN_ENDPOINTS) {
      expect(isSafeGreenfieldPath(`/api/v1/plc${forbidden}?from=greenfield`)).toBe(false);
    }
  });

  it("真实 API 调用只访问独立前缀，确认动作必须显式", async () => {
    const urls: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      urls.push(String(url));
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ok: true, data: {} }),
      } as unknown as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    await createDraft("s1", "装配工位");
    await uploadFiles("s1", [{ filename: "PLCTags.csv", text: "Name,Logical Address" }]);
    await confirmSpec("s1", true);
    await exportMermaid("s1");
    await beginEdit("s1");

    expect(urls.length).toBeGreaterThanOrEqual(5);
    for (const url of urls) {
      expect(url.startsWith(GF_API)).toBe(true);
      for (const forbidden of FORBIDDEN_ENDPOINTS) {
        expect(url).not.toContain(forbidden);
      }
    }
    const confirmCall = fetchMock.mock.calls.find((call) => String(call[0]).includes("/confirm"));
    expect(confirmCall).toBeTruthy();
    const init = confirmCall?.[1] as RequestInit | undefined;
    expect(JSON.parse(String(init?.body ?? "{}")).explicit).toBe(true);
  });
});
