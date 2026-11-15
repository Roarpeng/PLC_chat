import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { diagApi, type CompileScopeResult, type DiagCandidate, type DiagMapping, type DiagUnmapped } from "./apiDiag";
import {
  DiagnosticsPanel,
  DiagMappingView,
  DiagUnmappedView,
  FOCUS_OBJECT_EVENT,
  FORBIDDEN_SEVEN,
  ProposalsView,
  ScopeView,
  parseDiagLines,
} from "./DiagnosticsPanel";
import type { DeliveryJob } from "./types";

/* Node-environment tests: presentational render via renderToString (effects
   skipped), apiDiag binding via stubbed fetch — same pattern as api.test.ts. */

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

/* ---------- 1. 诊断列表渲染（job 诊断自动带入） ---------- */

const job: DeliveryJob = {
  id: "JOB-1", status: "SUCCEEDED",
  events: [{ stage: "compile", ok: true, state: "OK" }],
  diagnostics: [{ stage: "compile", code: "C0132", message: "type mismatch at input" }],
  artifact: null,
};

describe("DiagnosticsPanel render", () => {
  it("renders the diagnostics list from the delivery job (块/行/消息 + 定位 button)", () => {
    const html = renderToString(<DiagnosticsPanel projectId="PRJ_CLAMP" job={job} />);
    expect(html).toContain("编译诊断 → 对象定位");
    expect(html).toContain("C0132: type mismatch at input"); // job 诊断如实带入（无块名不猜）
    expect(html).toContain("定位");
    expect(html).toContain("修复提案（候选 · 不自动应用）");
    expect(html).toContain("编译范围（交付前意向）");
    expect(html).toContain("全量（默认）");
    expect(html).toContain("建议增量");
  });

  it("keeps the honest full-compile copy visible (增量由 FastWriteback 承接)", () => {
    const html = renderToString(<DiagnosticsPanel projectId="PRJ_CLAMP" job={null} />);
    expect(html).toContain("当前交付链总是全量编译");
    expect(html).toContain("FastWriteback");
    expect(html).toContain("暂无诊断"); // 无 job：空态如实，不编造
  });
});

/* ---------- 2. 定位结果：命中 / UNKNOWN 徽章 ---------- */

const mapping: DiagMapping = {
  index: 0, block: "FB_CM_CLAMP_CYL_DRV", line: null, message: "m",
  semantic_object_id: "af_1", behavior_step_id: null, source_map_id: "src_1",
  display_name: "夹紧气缸（双作用）", scl_line_range: null, scl_location: "块级定位（无行号）",
  release_build_id: "build_219", block_kind: "FB", instance_db: "", ownership: "GENERATED",
  located: "block",
};

const unmapped: DiagUnmapped = {
  index: 1, block: "FB_NATIVE_HANDWRITTEN", line: 12, message: "name conflict",
  error_code: "UNMAPPED_NATIVE_CODE",
  reason: "块名不在 SourceMap（手写原生代码/未知块）：不可映射不猜（PLAN §11）",
};

describe("locate result rendering", () => {
  it("shows object name / step / source span and the jump entry", () => {
    const html = renderToString(<DiagMappingView m={{ ...mapping, behavior_step_id: "S_EXTEND", scl_location: "行 33–45" }} />);
    expect(html).toContain("夹紧气缸（双作用）");
    expect(html).toContain("S_EXTEND");
    expect(html).toContain("行 33–45");
    expect(html).toContain("跳转现场追溯");
    expect(html).toContain(FOCUS_OBJECT_EVENT); // 事件名明示：由宿主监听
  });

  it("renders UNKNOWN badge + UNMAPPED_NATIVE_CODE red mark for unmapped blocks", () => {
    const html = renderToString(<DiagUnmappedView u={unmapped} />);
    expect(html).toContain("UNKNOWN");
    expect(html).toContain("UNMAPPED_NATIVE_CODE");
    expect(html).toContain("不可映射不猜");
  });

  it("block-ambiguous mapping stays UNKNOWN with candidates, never guesses", () => {
    const cand: DiagCandidate = {
      source_map_id: "src_2", semantic_object_id: "behavior_1", behavior_step_id: "S_EXTEND",
      display_name: "伸出", scl_line_range: [33, 45], scl_location: "行 33–45",
    };
    const html = renderToString(<DiagMappingView m={{
      ...mapping, located: "block_ambiguous", semantic_object_id: null, display_name: "UNKNOWN",
      candidates: [cand],
    }} />);
    expect(html).toContain("UNKNOWN");
    expect(html).toContain("不猜归属");
    expect(html).toContain("伸出");
    expect(html).not.toContain("跳转现场追溯"); // 无唯一对象：不提供跳转
  });
});

/* ---------- 3. 修复提案：ALLOWED 绿 / FORBIDDEN 红 + 七类明示 ---------- */

describe("ProposalsView", () => {
  const proposals = {
    proposals: [{
      diagnostic: { message: "name conflict: FB_X" },
      fix: { category: "BLOCK_NAME_CONFLICT", action: "重命名冲突块/实例 DB 并更新全部引用（候选变更，需人工审查）" },
      allowed: true, must_return_to_review: true,
    }],
    forbidden_seen: [{
      diagnostic: { message: "delete interlock to keep line running" },
      category: null, reason: "诊断不在保守白名单内：无可确定的自动修复类别，只登记不提议（PLAN §5.2）",
    }],
    auto_applied: [], note: "",
  };

  it("renders ALLOWED green with review-back copy", () => {
    const html = renderToString(<ProposalsView proposals={proposals} />);
    expect(html).toContain("ALLOWED");
    expect(html).toContain("BLOCK_NAME_CONFLICT");
    expect(html).toContain("以候选变更回流审批（不自动应用）");
    expect(html).toContain("auto_applied 恒空");
  });

  it("renders FORBIDDEN red with the reason and all seven forbidden classes", () => {
    const html = renderToString(<ProposalsView proposals={proposals} />);
    expect(html).toContain("FORBIDDEN");
    expect(html).toContain("未归类");
    expect(html).toContain("只登记不提议");
    for (const f of FORBIDDEN_SEVEN) expect(html).toContain(f.label);
    expect(FORBIDDEN_SEVEN).toHaveLength(7);
  });

  it("states honestly when no proposals exist yet", () => {
    expect(renderToString(<ProposalsView proposals={null} />)).toContain("未生成候选修复");
  });
});

/* ---------- 4. compile-scope 调用与展示 ---------- */

const scope: CompileScopeResult = {
  project_id: "PRJ_CLAMP", mode: "incremental",
  affected_blocks: ["FB_EM_CLAMP_SEQ"],
  reason: "无 OB/接口/IO/不变量变更：建议仅增量编译受影响块（incremental_blocks）",
  note: "当前交付链为全量编译；增量范围由 FastWriteback 分级编译承接（见 C# 侧）",
  ops_analyzed: 1,
};

describe("ScopeView", () => {
  it("renders the suggested scope with affected blocks and honest note", () => {
    const html = renderToString(<ScopeView scope={scope} />);
    expect(html).toContain("建议增量 · incremental_blocks");
    expect(html).toContain("FB_EM_CLAMP_SEQ");
    expect(html).toContain("当前交付链为全量编译");
  });

  it("renders full mode with its reason", () => {
    const html = renderToString(<ScopeView scope={{ ...scope, mode: "full", affected_blocks: [] }} />);
    expect(html).toContain("全量 · full");
  });
});

describe("diagApi binding", () => {
  it("locate posts diagnostics with actor headers to the project route", async () => {
    const fn = mockFetch(200, { project_id: "P", mappings: [], unmapped: [], proposals: null });
    await diagApi.locate("PRJ_CLAMP", [{ block: "FB_X", line: 3, message: "m" }]);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/projects/PRJ_CLAMP/diagnostics/locate");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Actor-Id"]).toBe("demo_operator"); // actorHeaders() 附带
    expect(init.headers["X-Actor-Role"]).toBe("Viewer");
    expect(JSON.parse(init.body).diagnostics[0].block).toBe("FB_X");
  });

  it("compileScope posts ops and returns the suggested scope", async () => {
    const fn = mockFetch(200, scope);
    const r = await diagApi.compileScope("PRJ_CLAMP", [{ op: "set", path: "/x", value: 1 }]);
    expect(r.mode).toBe("incremental");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/projects/PRJ_CLAMP/compile-scope");
    expect(JSON.parse(fn.mock.calls[0][1].body).ops).toHaveLength(1);
  });

  it("surfaces ApiError on failure", async () => {
    mockFetch(404, { error: "unknown project P" });
    await expect(diagApi.locate("P", [])).rejects.toMatchObject({ status: 404 });
  });
});

/* ---------- 5. 粘贴解析 ---------- */

describe("parseDiagLines", () => {
  it("parses pipe / colon / plain formats without guessing blocks", () => {
    const rows = parseDiagLines([
      "FB_EM_CLAMP_SEQ | 40 | type mismatch at input",
      "FB_CM_CLAMP_CYL_DRV | compile error in driver",
      "FB_X:12: something odd",
      "free text without block",
      "",
    ].join("\n"));
    expect(rows).toEqual([
      { block: "FB_EM_CLAMP_SEQ", line: 40, message: "type mismatch at input" },
      { block: "FB_CM_CLAMP_CYL_DRV", line: null, message: "compile error in driver" },
      { block: "FB_X", line: 12, message: "something odd" },
      { block: "", line: null, message: "free text without block" },
    ]);
  });
});
