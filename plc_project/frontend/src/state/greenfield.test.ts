import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FORBIDDEN_ENDPOINTS,
  GF_API,
  GF_BASE,
  GF_MAX_RETRIES,
  assertNoSideEffects,
  applyCanvasPatch,
  beginEdit,
  buildTopologyConstraints,
  bytesToBase64,
  canConfirm,
  canWriteAfterDiff,
  collectOpenQuestions,
  compileStepStatus,
  confirmBlockers,
  confirmDiff,
  confirmSpec,
  createDraft,
  createProjectId,
  diffWriteBlockers,
  downloadPackageUrl,
  ensureProjectId,
  exportMermaid,
  fetchSpec,
  fetchSpecDiff,
  fileToUploadItem,
  formatFidelityLabel,
  formatGfError,
  gateReason,
  generateProjectPackage,
  gfRequest,
  hasSideEffects,
  inferredInterlockQuestions,
  isSafeGreenfieldPath,
  loadLaunchContext,
  loadProjectId,
  loadReferenceFixture,
  mapApiError,
  mapConfirmError,
  saveLaunchContext,
  saveProjectId,
  sendChat,
  shortHash,
  updateHardware,
  uploadFiles,
  GFRequestError,
  /* F20 三动作 / D11 / N9 新增导出 */
  GF_ACTION_C_STEPS,
  GF_ERROR_TEXT,
  GF_NO_RETRY_CODES,
  actionAvailability,
  actionStepStatus,
  diffChecklistComplete,
  diffChecklistKeys,
  diffExplicitlyConfirmed,
  formatCompileVerdict,
  isDeterministicTiaFailure,
  pendingRealMachineLabel,
  runActionA,
  runActionB,
  runActionC,
  type GFActionMachine,
  type GFSpecDiff,
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

function mockFetchOnce(handler: (url: string, init?: RequestInit) => unknown) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function okResponse(data: unknown = {}): unknown {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ ok: true, data }),
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
    const fetchMock = mockFetchOnce((url) => {
      urls.push(String(url));
      return okResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    await createDraft("s1", "装配工位");
    await uploadFiles("s1", [{ filename: "PLCTags.csv", text: "Name,Logical Address" }]);
    await updateHardware("s1", { op: "mount_cm", cm_id: "CM_1", hw_node_id: "HW_DO_0" });
    await loadReferenceFixture("s1", "机器人上下料");
    await confirmSpec("s1", true);
    await generateProjectPackage("s1");
    await exportMermaid("s1");
    await beginEdit("s1");

    expect(downloadPackageUrl("s1")).toBe(`${GF_BASE}${GF_API}/download-package?session_id=s1`);
    const pdfFile = new File([new Uint8Array([37, 80, 68, 70])], "PLC_IO.pdf", {
      type: "application/pdf",
    });
    const pdfItem = await fileToUploadItem(pdfFile);
    expect(pdfItem.kind).toBe("pdf");

    expect(urls.length).toBeGreaterThanOrEqual(8);
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

describe("chat 对话入口（chat ↔ 画布双向联动）", () => {
  it("sendChat 走 greenfield 独立 /chat 端点并携带消息体", async () => {
    const urls: string[] = [];
    const bodies: string[] = [];
    const fetchMock = mockFetchOnce((url, init) => {
      urls.push(String(url));
      if (init?.body) bodies.push(String(init.body));
      return okResponse({ state: fakeState(), reply: "已应用", message: { id: "m1" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendChat("s1", "把首步超时改为 5000ms");
    expect(result.reply).toBe("已应用");
    expect(urls[0]).toBe(`${GF_BASE}${GF_API}/chat`);
    expect(JSON.parse(bodies[0])).toEqual({ session_id: "s1", message: "把首步超时改为 5000ms" });
    for (const forbidden of FORBIDDEN_ENDPOINTS) {
      expect(urls[0]).not.toContain(forbidden);
    }
  });

  it("对话绑定 project_id 并注入已定拓扑约束（结果不得与已定拓扑矛盾）", async () => {
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.body) bodies.push(String(init.body));
        return okResponse({ state: fakeState(), reply: "已应用", message: { id: "m1" } });
      }),
    );
    const ir = {
      units: [{ id: "U1", name: "AssemblyCell", business_label: "装配工位" }],
      ems: [{ id: "U1EM1", unit_id: "U1", business_label: "上料工序" }],
      cms: [{ id: "U1EM1_CM1", em_id: "U1EM1", business_label: "上料输送带" }],
      edges: [{ id: "E1", kind: "E_MSG_STEP", src_id: "U1", dst_id: "U1EM1" }],
      interlocks: [{ id: "IL_1", source: "inferred", expression: "TRUE", target_id: "U1EM1" }],
      spec_meta: { open_questions: ["急停后是否复位？"] },
    };
    const constraints = buildTopologyConstraints(ir);
    await sendChat("s1", "新增一个执行件", {
      projectId: "prj-abc123",
      topologyConstraints: constraints,
    });
    const body = JSON.parse(bodies[0]);
    expect(body.project_id).toBe("prj-abc123");
    expect(body.topology_constraints.units[0].business_label).toBe("装配工位");
    expect(body.topology_constraints.cms[0].id).toBe("U1EM1_CM1");
    expect(body.topology_constraints.open_questions).toContain("急停后是否复位？");
    expect(body.topology_constraints.inferred_interlocks).toHaveLength(1);
    expect(body.topology_constraints.note).toContain("不得与已定拓扑矛盾");
  });

  it("拓扑撤销操作仍走 /hardware 且在安全前缀内", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        urls.push(String(url));
        return okResponse(fakeState());
      }),
    );
    await updateHardware("s1", { op: "reset_topology" });
    await updateHardware("s1", { op: "unmount_cm", cm_id: "CM_1" });
    expect(urls).toHaveLength(2);
    for (const url of urls) {
      expect(url.startsWith(GF_API)).toBe(true);
      expect(url).toContain("/hardware");
    }
  });
});

describe("gfRequest 封装（env 基址 / 中文错误 / 重试 / 离线）", () => {
  it("Base URL 不硬编码后端主机，下载链接走环境变量基址", () => {
    expect(typeof GF_BASE).toBe("string");
    expect(GF_BASE).not.toContain("localhost");
    expect(downloadPackageUrl("s1")).toContain(`${GF_API}/download-package`);
    expect(GF_MAX_RETRIES).toBe(3);
  });

  it("4xx 不重试，错误映射为可读中文并保留网关 code", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      text: async () =>
        JSON.stringify({
          ok: false,
          error: { code: "GF_TOPOLOGY_NOT_FINALIZED", message: "拓扑未定稿" },
        }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(gfRequest(`${GF_API}/confirm`)).rejects.toMatchObject({
      name: "GFRequestError",
      code: "GF_TOPOLOGY_NOT_FINALIZED",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    try {
      await gfRequest(`${GF_API}/confirm`);
    } catch (err) {
      expect((err as GFRequestError).message).toContain("拓扑");
      expect((err as GFRequestError).status).toBe(409);
    }
  });

  it("5xx 最多重试 3 次（初次 + 3 次），耗尽后给出中文原因", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ ok: false, error: { message: "上游维护中" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(gfRequest(`${GF_API}/state`)).rejects.toMatchObject({ name: "GFRequestError" });
    expect(fetchMock).toHaveBeenCalledTimes(GF_MAX_RETRIES + 1);
    try {
      await gfRequest(`${GF_API}/state`);
    } catch (err) {
      expect((err as GFRequestError).message).toContain("网关服务暂时不可用");
    }
  });

  it("5xx 重试期间恢复成功则返回数据", async () => {
    let n = 0;
    const fetchMock = vi.fn(async () => {
      n += 1;
      if (n <= 2) {
        return { ok: false, status: 500, text: async () => "{}" };
      }
      return okResponse({ recovered: true });
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await gfRequest<{ recovered: boolean }>(`${GF_API}/state`);
    expect(result.recovered).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("fetch 抛错（网络不可达）显示离线中文提示且不重试", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(gfRequest(`${GF_API}/state`)).rejects.toMatchObject({
      name: "GFRequestError",
      offline: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    try {
      await gfRequest(`${GF_API}/state`);
    } catch (err) {
      expect((err as GFRequestError).message).toContain("离线");
      expect((err as GFRequestError).message).toContain("VITE_GATEWAY_URL");
    }
  });

  it("404 新端点暂未上线时安全降级，不宣称成功、不产生写入", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 404,
        text: async () => JSON.stringify({ detail: "Not Found" }),
      })),
    );
    try {
      await gfRequest(`${GF_API}/diff`);
      throw new Error("不应成功");
    } catch (err) {
      expect((err as GFRequestError).message).toContain("暂未上线");
      expect((err as GFRequestError).message).toContain("未产生任何写入");
    }
  });

  it("ok:false 信封错误按 code 映射中文，formatGfError 保留中文", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        text: async () =>
          JSON.stringify({
            ok: false,
            error: { code: "GF_DIFF_NOT_CONFIRMED", message: "diff not confirmed" },
          }),
      })),
    );
    try {
      await gfRequest(`${GF_API}/confirm-diff`);
    } catch (err) {
      expect(formatGfError(err)).toContain("差异清单");
      expect(mapApiError("GF_DIFF_NOT_CONFIRMED", "", 409)).toContain("差异清单");
    }
    expect(mapConfirmError("GF_BASELINE_NOT_LOCKED")).toContain("基线");
    expect(mapConfirmError("", "后端具体原因")).toBe("后端具体原因");
    expect(mapConfirmError("UNKNOWN_CODE")).toContain("UNKNOWN_CODE");
  });
});

describe("契约 §3 四个新端点的封装", () => {
  it("/patch /diff /confirm-diff /specs 都落在独立前缀且带 project_id", async () => {
    const urls: string[] = [];
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        urls.push(String(url));
        if (init?.body) bodies.push(String(init.body));
        return okResponse({});
      }),
    );
    await applyCanvasPatch("prj-1", [{ op: "add_cm", em_id: "U1EM1", business_label: "夹爪" }], 1);
    await fetchSpecDiff("prj-1", 1, 2);
    await confirmDiff("prj-1", "diff-1", true);
    await fetchSpec("prj-1", 2);

    for (const url of urls) {
      expect(url.startsWith(GF_API)).toBe(true);
      for (const forbidden of FORBIDDEN_ENDPOINTS) {
        expect(url).not.toContain(forbidden);
      }
    }
    expect(urls[0]).toContain("/patch");
    expect(urls[1]).toContain("/diff");
    expect(urls[2]).toContain("/confirm-diff");
    expect(urls[3]).toContain("/specs/2");
    expect(urls[3]).toContain("project_id=prj-1");
    const patchBody = JSON.parse(bodies[0]);
    expect(patchBody.project_id).toBe("prj-1");
    expect(patchBody.base_spec_version).toBe(1);
    expect(patchBody.ops[0].op).toBe("add_cm");
    expect(JSON.parse(bodies[1])).toMatchObject({ project_id: "prj-1", from_version: 1, to_version: 2 });
    expect(JSON.parse(bodies[2])).toMatchObject({ project_id: "prj-1", diff_id: "diff-1", confirmed: true });
  });
});

describe("project_id 贯穿与启动上下文", () => {
  it("生成 / 存取 / ensure 复用现成 prj- 机制", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    });
    const id = createProjectId();
    expect(id).toMatch(/^prj-[0-9a-f]{12}$/);
    saveProjectId(id);
    expect(loadProjectId()).toBe(id);
    expect(ensureProjectId()).toBe(id);
  });

  it("向导完成后启动上下文带 project_id、prompt 与资料可选标记", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    });
    saveLaunchContext({
      project_id: "prj-abc",
      project_name: "装配工位",
      prompt: "机器人上下料",
      has_uploads: false,
      no_upload_note: "未上传资料，不虚构地址 / OB 条目",
      created_at: "2026-11-06T00:00:00Z",
    });
    const ctx = loadLaunchContext();
    expect(ctx?.project_id).toBe("prj-abc");
    expect(ctx?.has_uploads).toBe(false);
    expect(ctx?.no_upload_note).toContain("不虚构");
    expect(loadLaunchContext()?.project_id).toBe(ctx?.project_id);
  });
});

describe("确认硬门禁五项前置（P1-H）与现成机制复用", () => {
  const checks: Array<[string, Record<string, boolean>, string]> = [
    ["拓扑定稿", { topology_finalized: false }, "拓扑"],
    ["open_questions 清零", { open_questions_cleared: false }, "待确认问题"],
    ["节点/连线校验", { nodes_edges_valid: false }, "节点"],
    ["等价性预检", { equivalence_precheck: false }, "等价性"],
    ["基线版本锁定", { baseline_locked: false }, "基线"],
  ];
  for (const [name, gate_checks, keyword] of checks) {
    it(`${name} 未满足时按钮不可用且给出具体原因`, () => {
      const state = fakeState({ gate_checks });
      expect(canConfirm(state)).toBe(false);
      expect(gateReason(state)).toContain(keyword);
      expect(confirmBlockers(state).some((b) => b.reason.includes(keyword))).toBe(true);
    });
  }

  it("复用 GFSpecMeta.open_questions：未清零即阻断", () => {
    const state = fakeState({ ir: { spec_meta: { open_questions: ["急停后复位策略？"] } } });
    expect(collectOpenQuestions(state)).toContain("急停后复位策略？");
    expect(canConfirm(state)).toBe(false);
    expect(gateReason(state)).toContain("待确认问题");
  });

  it("复用 GFInterlock.source == inferred：推断联锁自动进待确认问题", () => {
    const ir = {
      interlocks: [
        { id: "IL_1", source: "inferred", expression: "NOT #Estop", target_id: "U1EM1" },
        { id: "IL_2", source: "user", expression: "TRUE", target_id: "U1EM1" },
      ],
    };
    expect(inferredInterlockQuestions(ir)).toHaveLength(1);
    expect(inferredInterlockQuestions(ir)[0]).toContain("推断");
    const state = fakeState({ ir });
    expect(collectOpenQuestions(state)).toHaveLength(1);
    expect(canConfirm(state)).toBe(false);
  });
});

describe("差异清单显式确认（D11）/ 反向保护（D10）/ fidelity（N9）", () => {
  const diff = {
    base_spec_version: 1,
    target_spec_version: 2,
    changed: [{ source_id: "SRC-1", kind: "scl", payload: {} }],
    added: [{ source_id: "SRC-2", kind: "db", payload: {} }],
    removed: [],
    changed_source_ids: ["SRC-1"],
  };

  it("差异未显式勾选确认时禁止后续写入；确认后放行", () => {
    const state = fakeState({ spec_diff: diff });
    expect(diffWriteBlockers(state, false).some((b) => b.reason.includes("差异清单"))).toBe(true);
    expect(canWriteAfterDiff(state, false)).toBe(false);
    expect(canWriteAfterDiff(state, true)).toBe(true);
  });

  it("TIA 侧手工改动被阻止覆盖（D10），文案明确", () => {
    const state = fakeState({
      reverse_protection: {
        allowed: false,
        drift_count: 1,
        tia_side_drift: 1,
        blocked_source_ids: ["SRC-1"],
        reason: "hash mismatch",
      },
    });
    const blockers = diffWriteBlockers(state, true);
    expect(blockers.some((b) => b.reason === "TIA 侧存在手工改动，已阻止覆盖")).toBe(true);
    expect(canWriteAfterDiff(state, true)).toBe(false);
  });

  it("fidelity_ok 不显示成「编译通过」（N9）", () => {
    const label = formatFidelityLabel({
      fidelity_ok: true,
      coverage: 1,
      orphan: 0,
      drift: 0,
      tia_side_drift: 0,
      mode: "incremental",
    });
    expect(label.ok).toBe(true);
    expect(label.label).toContain("还原一致性");
    expect(label.label).not.toContain("编译通过");
    expect(label.detail).toContain("覆盖度");
    expect(formatFidelityLabel(null).label).toContain("暂无数据");
    const blocked = fakeState({
      fidelity: { fidelity_ok: false, coverage: 0.8, orphan: 1, drift: 0, tia_side_drift: 0 },
    });
    expect(diffWriteBlockers(blocked, true).some((b) => b.code === "GF_FIDELITY_FAILED")).toBe(true);
  });
});

describe("编译诊断状态机（P1-I 展示层）", () => {
  it("generate → compile → 诊断 → 修正 → 复编译 的步骤推进", () => {
    expect(compileStepStatus("idle", "generating")).toBe("todo");
    expect(compileStepStatus("diagnosed", "generating")).toBe("done");
    expect(compileStepStatus("diagnosed", "compiling")).toBe("done");
    expect(compileStepStatus("diagnosed", "diagnosed")).toBe("active");
    expect(compileStepStatus("diagnosed", "healing")).toBe("todo");
    expect(compileStepStatus("settled", "recompiling")).toBe("done");
  });
});

/* ==========================================================================
 * F20 三动作 UI 接线 + 批次 1 遗留补齐（新增）
 * ========================================================================== */

describe("F20 三动作 API 封装（按 H 的真实请求字段接线）", () => {
  it("runActionA/B/C 落在独立前缀且请求体使用真实字段", async () => {
    const urls: string[] = [];
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        urls.push(String(url));
        if (init?.body) bodies.push(String(init.body));
        return okResponse({ ok: true, action: "A", mode: "full", fidelity_ok: true });
      }),
    );
    await runActionA({ session_id: "s1", include_zip_base64: false });
    await runActionB({
      session_id: "s1",
      confirmed: true,
      fidelity_report: { fidelity_ok: true },
    });
    await runActionC({ session_id: "s1", confirmed: true, diff: null });

    expect(urls[0]).toContain("/action-a");
    expect(urls[1]).toContain("/action-b");
    expect(urls[2]).toContain("/action-c");
    for (const url of urls) {
      expect(url.startsWith(GF_API)).toBe(true);
      expect(isSafeGreenfieldPath(url)).toBe(true);
      for (const forbidden of FORBIDDEN_ENDPOINTS) {
        expect(url).not.toContain(forbidden);
      }
    }
    expect(JSON.parse(bodies[0])).toMatchObject({
      session_id: "s1",
      include_zip_base64: false,
    });
    expect(JSON.parse(bodies[1])).toMatchObject({
      session_id: "s1",
      confirmed: true,
      fidelity_report: { fidelity_ok: true },
    });
    expect(JSON.parse(bodies[2])).toMatchObject({
      session_id: "s1",
      confirmed: true,
    });
  });
});

describe("F20 三动作状态机（§3.2 / D11 / D10 / UC-17）", () => {
  const base: GFActionMachine = {
    stage: "FROZEN",
    actionARun: true,
    actionAFidelityOk: true,
    actionBDone: true,
    diffConfirmed: true,
    diffChecklistComplete: true,
    reverseBlocked: false,
  };

  it("全部前置满足时 A / B / C 均可用，且不笼统提示", () => {
    const a = actionAvailability(base);
    expect(a.A.enabled).toBe(true);
    expect(a.B.enabled).toBe(true);
    expect(a.C.enabled).toBe(true);
    expect(a.B.reason).not.toContain("操作失败");
    expect(a.C.reason).not.toContain("操作失败");
  });

  it("A 导出工程包需已 FROZEN（不写 TIA，不需差异确认）", () => {
    const a = actionAvailability({ ...base, stage: "LINKABLE" });
    expect(a.A.enabled).toBe(false);
    expect(a.A.reason).toContain("FROZEN");
  });

  it("B 必须在 A 的 fidelity_ok=true 后才可用（UC-17）", () => {
    const noA = actionAvailability({ ...base, actionARun: false, actionAFidelityOk: null });
    expect(noA.B.enabled).toBe(false);
    expect(noA.B.reason).toContain("fidelity_ok");
    const badFidelity = actionAvailability({ ...base, actionAFidelityOk: false });
    expect(badFidelity.B.enabled).toBe(false);
    expect(badFidelity.B.reason).toContain("还原度校验");
  });

  it("C 必须在差异清单显式确认后才可用（D11），且以已完成 B 为前提", () => {
    const notConfirmed = actionAvailability({
      ...base,
      diffConfirmed: false,
      diffChecklistComplete: false,
    });
    expect(notConfirmed.C.enabled).toBe(false);
    expect(notConfirmed.C.reason).toContain("D11");
    expect(notConfirmed.C.reason).toContain("逐项勾选");
    const noB = actionAvailability({ ...base, actionBDone: false });
    expect(noB.C.enabled).toBe(false);
    expect(noB.C.reason).toContain("Action B");
  });

  it("未确认前 B / C 均 disabled 且说明 D11 原因；D10 反向保护也锁定写入", () => {
    const notConfirmed = actionAvailability({
      ...base,
      diffConfirmed: false,
      diffChecklistComplete: true,
    });
    expect(notConfirmed.B.enabled).toBe(false);
    expect(notConfirmed.C.enabled).toBe(false);
    expect(notConfirmed.B.reason).toContain("D11");
    const drift = actionAvailability({ ...base, reverseBlocked: true });
    expect(drift.B.enabled).toBe(false);
    expect(drift.C.enabled).toBe(false);
    expect(drift.C.reason).toContain("D10");
  });
});

describe("D11 差异清单逐项勾选（changed / added / removed 带 source_id）", () => {
  const diff: GFSpecDiff = {
    base_spec_version: 1,
    target_spec_version: 2,
    changed: [{ source_id: "SRC-C", kind: "em", payload: {} }],
    added: [{ source_id: "SRC-A", kind: "cm", payload: {} }],
    removed: [{ source_id: "SRC-R", kind: "db", payload: {} }],
    changed_source_ids: ["SRC-C"],
  };

  it("三清单逐项生成可勾选 key，且带 source_id", () => {
    const keys = diffChecklistKeys(diff);
    expect(keys).toHaveLength(3);
    expect(keys).toContain("changed:SRC-C");
    expect(keys).toContain("added:SRC-A");
    expect(keys).toContain("removed:SRC-R");
  });

  it("未勾齐时不允许显式确认；勾齐 + 显式确认标志才放行", () => {
    expect(diffChecklistComplete(diff, {})).toBe(false);
    expect(diffExplicitlyConfirmed(diff, {}, true)).toBe(false);
    const partial = { "changed:SRC-C": true, "added:SRC-A": true };
    expect(diffChecklistComplete(diff, partial)).toBe(false);
    const all = {
      "changed:SRC-C": true,
      "added:SRC-A": true,
      "removed:SRC-R": true,
    };
    expect(diffChecklistComplete(diff, all)).toBe(true);
    expect(diffExplicitlyConfirmed(diff, all, false)).toBe(false);
    expect(diffExplicitlyConfirmed(diff, all, true)).toBe(true);
  });

  it("无差异项时视为已勾齐（无可勾选项），但仍需显式确认标志", () => {
    expect(diffChecklistComplete(null, {})).toBe(true);
    expect(diffExplicitlyConfirmed(null, {}, false)).toBe(false);
    expect(diffExplicitlyConfirmed(null, {}, true)).toBe(true);
  });
});

describe("F20 三动作错误码中文映射（禁止笼统「操作失败」）", () => {
  const cases: Array<[string, string]> = [
    ["GF_ACTION_CONFIRM_REQUIRED", "D11"],
    ["GF_ACTION_B_FIDELITY_FAILED", "还原度校验"],
    ["GF_ACTION_B_COMPILE_FAILED", "编译"],
    ["GF_ACTION_C_FIDELITY_PREREQUISITE", "前置"],
    ["GF_ACTION_C_SESSION_OWNERSHIP_CONFLICT", "会话归属冲突"],
    ["GF_ACTION_C_REVERSE_GUARD_BLOCKED", "阻止覆盖"],
    ["GF_ACTION_C_REVERSE_GUARD_UNAVAILABLE", "fail-closed"],
    ["GF_ACTION_C_ROLLBACK", "回滚"],
    ["GF_TIA_EXEC_ERROR", "TIA"],
    ["GF_TIA_UNAVAILABLE", "TIA"],
  ];
  for (const [code, keyword] of cases) {
    it(`${code} 映射为具体中文（含「${keyword}」）`, () => {
      const text = mapApiError(code, "", 409);
      expect(text).toContain(keyword);
      expect(text).not.toContain("操作失败");
      expect(GF_ERROR_TEXT[code]).toBeTruthy();
      expect(mapConfirmError(code)).toContain(keyword);
    });
  }

  it("D10 反向保护文案明确「已阻止覆盖」且说明未执行块级覆盖", () => {
    const text = GF_ERROR_TEXT.GF_ACTION_C_REVERSE_GUARD_BLOCKED;
    expect(text).toContain("D10");
    expect(text).toContain("已阻止覆盖");
    expect(text).toContain("未执行任何块级覆盖");
  });

  it("GF_ACTION_B_FIDELITY_FAILED 明确「这不代表编译通过」（N9）", () => {
    expect(GF_ERROR_TEXT.GF_ACTION_B_FIDELITY_FAILED).toContain("不代表编译通过");
  });
});

describe("gfRequest 503 确定性 TIA 错误重试豁免", () => {
  it("GF_TIA_UNAVAILABLE / GF_TIA_EXEC_ERROR（503）只请求 1 次，不重试", async () => {
    expect(GF_NO_RETRY_CODES).toContain("GF_TIA_UNAVAILABLE");
    expect(GF_NO_RETRY_CODES).toContain("GF_TIA_EXEC_ERROR");
    for (const code of GF_NO_RETRY_CODES) {
      const fetchMock = vi.fn(async () => ({
        ok: false,
        status: 503,
        text: async () =>
          JSON.stringify({ ok: false, error: { code, message: "tia down" } }),
      }));
      vi.stubGlobal("fetch", fetchMock);
      try {
        await gfRequest(`${GF_API}/action-b`);
      } catch (err) {
        expect((err as GFRequestError).message).toContain("TIA");
        expect((err as GFRequestError).message).not.toContain("已重试 3 次");
      }
      expect(isDeterministicTiaFailure(code)).toBe(true);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  });

  it("其他 5xx 仍最多重试 3 次；4xx 不重试；fetch 失败仍显示离线提示", async () => {
    const fetch5xx = vi.fn(async () => ({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ ok: false, error: { message: "上游维护中" } }),
    }));
    vi.stubGlobal("fetch", fetch5xx);
    await expect(gfRequest(`${GF_API}/state`)).rejects.toMatchObject({
      name: "GFRequestError",
    });
    expect(fetch5xx).toHaveBeenCalledTimes(GF_MAX_RETRIES + 1);

    const fetch4xx = vi.fn(async () => ({
      ok: false,
      status: 409,
      text: async () =>
        JSON.stringify({
          ok: false,
          error: { code: "GF_ACTION_CONFIRM_REQUIRED", message: "x" },
        }),
    }));
    vi.stubGlobal("fetch", fetch4xx);
    await expect(gfRequest(`${GF_API}/action-c`)).rejects.toMatchObject({
      name: "GFRequestError",
    });
    expect(fetch4xx).toHaveBeenCalledTimes(1);

    const fetchOffline = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    vi.stubGlobal("fetch", fetchOffline);
    await expect(gfRequest(`${GF_API}/state`)).rejects.toMatchObject({
      offline: true,
    });
    expect(fetchOffline).toHaveBeenCalledTimes(1);
  });
});

describe("N9 诚实口径文案（还原度校验 / 待真机 / warnings 单列）", () => {
  it("fidelity_ok 显示为「还原度校验」，绝不显示「编译通过」", () => {
    const label = formatFidelityLabel({
      fidelity_ok: true,
      coverage: 1,
      orphan: 0,
      drift: 0,
      tia_side_drift: 0,
    });
    expect(label.label).toContain("还原度校验");
    expect(label.label).toContain("还原一致性");
    expect(label.label).not.toContain("编译通过");
    expect(label.ok).toBe(true);
    const failed = formatFidelityLabel({
      fidelity_ok: false,
      coverage: 0.5,
      orphan: 1,
      drift: 0,
      tia_side_drift: 0,
    });
    expect(failed.ok).toBe(false);
    expect(failed.label).not.toContain("编译通过");
  });

  it("真机未跑时 formatCompileVerdict 显示「待真机」而非「成功」", () => {
    const verdict = formatCompileVerdict({
      status: "pending_real_machine",
      error_count: 0,
      warnings: [],
      l2_status: "pending_real_machine",
      pending_real_machine: true,
      compile_ok: false,
    });
    expect(verdict.label).toContain("待真机");
    expect(verdict.label).not.toContain("成功");
    expect(verdict.ok).toBe(false);
    expect(verdict.pending).toBe(true);
    expect(verdict.detail).toContain("error_count 0");
    expect(verdict.detail).toContain("warnings 0 条");
  });

  it("compile_ok 用 error_count / warnings 单列展示，warnings 不并入成功", () => {
    const verdict = formatCompileVerdict({
      status: "compiled",
      error_count: 0,
      warnings: ["W1: unused", "W2: implicit cast"],
      compile_ok: true,
      pending_real_machine: false,
    });
    expect(verdict.label).toContain("通过");
    expect(verdict.detail).toContain("error_count 0");
    expect(verdict.detail).toContain("warnings 2 条");
    expect(verdict.detail).toContain("W1");
    expect(verdict.detail).toContain("绝不并入成功");
    const err = formatCompileVerdict({
      status: "compiled",
      error_count: 2,
      warnings: [],
      compile_ok: false,
    });
    expect(err.label).toContain("未通过");
    expect(err.ok).toBe(false);
  });

  it("无编译诊断时诚实降级为待真机，不虚构 error_count", () => {
    const verdict = formatCompileVerdict(null);
    expect(verdict.label).toContain("待真机");
    expect(verdict.pending).toBe(true);
    expect(verdict.detail).toContain("不虚构");
  });

  it("pendingRealMachineLabel 常驻可见：真机未跑显示待真机", () => {
    expect(pendingRealMachineLabel(true)).toContain("待真机");
    expect(pendingRealMachineLabel(undefined)).toContain("pending_real_machine");
    expect(pendingRealMachineLabel(true)).toContain("不宣称 L2 / L4 通过");
  });
});

describe("§13.5 八步 step_order 与每步结果", () => {
  it("八步顺序与服务端 ACTION_C_STEPS 一致", () => {
    expect(GF_ACTION_C_STEPS.map((s) => s.key)).toEqual([
      "session_reuse",
      "spec_diff",
      "reverse_guard",
      "diff_confirm",
      "pre_write_backup",
      "block_overwrite",
      "compile_save",
      "incremental_fidelity_pcec",
    ]);
  });

  it("actionStepStatus 按服务端 steps 判定 done / failed / todo", () => {
    const steps = [
      { step: "session_reuse", ok: true },
      { step: "spec_diff", ok: true },
      { step: "reverse_guard", ok: false, detail: "tia_side_drift=1" },
    ];
    expect(actionStepStatus(steps, "session_reuse")).toBe("done");
    expect(actionStepStatus(steps, "reverse_guard")).toBe("failed");
    expect(actionStepStatus(steps, "compile_save")).toBe("todo");
    expect(actionStepStatus(undefined, "session_reuse")).toBe("todo");
  });
});
