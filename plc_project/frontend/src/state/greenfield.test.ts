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
