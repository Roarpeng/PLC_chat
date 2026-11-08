/**
 * 主链 API 序列与拖线增删负载 · 纯逻辑 + ?raw 静态断言（不 render、不用 jsdom）。
 *
 * 重点覆盖：
 *  - add_edge / remove_edge 的 body 形状与 toGfEdge 输出；
 *  - 步 3 进入时 fetchEngineeringSummary → confirmSpec → generateProjectPackage → refresh；
 *  - Channel 源码中 /confirm 严格先于 /generate，且 GO(4) 只在成功分支。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Connection } from "@xyflow/react";
import {
  applyLinkPatch,
  confirmSpec,
  fetchEngineeringSummary,
  fetchState,
  formatGfError,
  generateProjectPackage,
  mapConfirmError,
  GF_API,
} from "../../state/greenfield";
import { toGfEdge } from "./canvasUtils";
import channelSource from "../GreenfieldChannel.tsx?raw";
import wizardSource from "../GreenfieldWizard.tsx?raw";

afterEach(() => {
  vi.unstubAllGlobals();
});

function conn(source: string, target: string): Connection {
  return { source, target, sourceHandle: null, targetHandle: null };
}

interface RecordedCall {
  url: string;
  init: RequestInit;
}

function stubFetch(): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ok: true, data: {} }),
      };
    }),
  );
  return calls;
}

function bodyOf(source: string, name: string): string {
  const start = source.indexOf(`const ${name} =`);
  if (start < 0) return "";
  const end = source.indexOf("\n  }, [", start);
  return end > start ? source.slice(start, end) : source.slice(start);
}

describe("步 2 · 拖线增删的调用负载", () => {
  it("toGfEdge 产出后端认识的手动连线结构", () => {
    const edge = toGfEdge("E_MSG_STEP", conn("UN1", "CM1"));
    expect(edge).toEqual({
      id: "E_MANUAL_E_MSG_STEP_UN1_CM1",
      kind: "E_MSG_STEP",
      src_id: "UN1",
      dst_id: "CM1",
      view_mask: ["flow"],
      origin: "manual",
    });
  });

  it("新增连线走 add_edge，删除连线走 remove_edge，URL 均为 /links", async () => {
    const calls = stubFetch();
    await applyLinkPatch("sid-1", {
      op: "add_edge",
      edge: toGfEdge("E_MSG_STEP", conn("UN1", "CM1")),
    });
    await applyLinkPatch("sid-1", { op: "remove_edge", edge_id: "E_MANUAL_E_MSG_STEP_UN1_CM1" });

    expect(calls).toHaveLength(2);
    expect(calls[0].url).toContain(`${GF_API}/links`);
    expect(calls[1].url).toContain(`${GF_API}/links`);
    const added = JSON.parse(String(calls[0].init.body)) as Record<string, unknown>;
    const removed = JSON.parse(String(calls[1].init.body)) as Record<string, unknown>;
    expect(added.session_id).toBe("sid-1");
    expect(added.op).toBe("add_edge");
    expect((added.edge as Record<string, unknown>).origin).toBe("manual");
    expect(removed.session_id).toBe("sid-1");
    expect(removed.op).toBe("remove_edge");
    expect(removed.edge_id).toBe("E_MANUAL_E_MSG_STEP_UN1_CM1");
    expect(removed.edge).toBeUndefined();
  });
});

describe("步 3 · 合法 API 序列（隐藏硬门禁）", () => {
  it("真实封装按 工程摘要 → 确认 → 生成 → 回读 顺序发出请求", async () => {
    const calls = stubFetch();
    await fetchEngineeringSummary("sid-2");
    await confirmSpec("sid-2", true, "prj-2");
    await generateProjectPackage("sid-2", "prj-2");
    await fetchState("sid-2", "prj-2");

    expect(calls.map((c) => c.url)).toEqual([
      expect.stringContaining("/engineering-summary"),
      expect.stringContaining("/confirm"),
      expect.stringContaining("/generate"),
      expect.stringContaining("/state"),
    ]);
    const confirmBody = JSON.parse(String(calls[1].init.body)) as Record<string, unknown>;
    expect(confirmBody.explicit).toBe(true);
    expect(confirmBody.project_id).toBe("prj-2");
  });

  it("Channel 源码：进入步 3 先 fetchEngineeringSummary，且 /confirm 严格先于 /generate", () => {
    const enter = bodyOf(channelSource, "onEnterConfirm");
    const confirmAndGenerate = bodyOf(channelSource, "onConfirmAndGenerate");

    expect(enter).toContain("fetchEngineeringSummary(sessionId)");
    expect(enter).toContain("await refresh(sessionId)");

    const iConfirm = confirmAndGenerate.indexOf("await confirmSpec(sessionId, true");
    const iGenerate = confirmAndGenerate.indexOf("await generateProjectPackage(sessionId");
    const iRefresh = confirmAndGenerate.indexOf("await refresh(sessionId)");
    const iGo = confirmAndGenerate.indexOf('type: "GO", step: 4');
    expect(iConfirm).toBeGreaterThan(-1);
    expect(iGenerate).toBeGreaterThan(iConfirm);
    expect(iRefresh).toBeGreaterThan(iGenerate);
    expect(iGo).toBeGreaterThan(iRefresh);
    // 失败分支不得 GO(4)、不得重试、不得绕过。
    expect(confirmAndGenerate).toContain("mapConfirmError(code, message)");
    expect(confirmAndGenerate).not.toContain("setTimeout");
  });

  it("Channel 源码：连线增删只走 applyLinkPatch，不做本地乐观增删", () => {
    expect(channelSource).toContain('{ op: "add_edge", edge: toGfEdge(kind, connection) }');
    expect(channelSource).toContain('{ op: "remove_edge", edge_id: edgeId }');
    expect(channelSource).toContain("await refresh(sessionId)");
    expect(channelSource).not.toContain("setEdges(");
  });

  it("Channel 源码：步 4 重新调整先 beginEdit，新工程取真实新会话", () => {
    const reenter = bodyOf(channelSource, "onBeginEditAndGoLink");
    const restart = bodyOf(channelSource, "onRestart");
    expect(reenter).toContain("await beginEdit(sessionId)");
    expect(reenter).toContain('type: "REENTER_EDIT"');
    expect(restart).toContain("resetWizardLocalState()");
    expect(restart).toContain("await fetchState(null, pid)");
    expect(restart).toContain('type: "RESET"');
  });
});

/* ======================================================================
 * QA 独立复核（V9）：网络错误四态 + 门禁中文提示 + 步 3 编排接线。
 * 这些不是实现者自带用例；用真实 gfRequest 走 stub 过的 fetch，验证
 * 4xx / 5xx / 离线 / 404 四态都转中文且不含原始英文错误码。
 * ==================================================================== */
interface FailureCalls {
  calls: Array<{ url: string }>;
}

function stubFailure(status: number, code: string, message: string): FailureCalls {
  const calls: Array<{ url: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push({ url });
      return {
        ok: false,
        status,
        text: async () => JSON.stringify({ ok: false, error: { code, message } }),
      };
    }),
  );
  return { calls };
}

function stubOffline(): FailureCalls {
  const calls: Array<{ url: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push({ url });
      throw new Error("connect ECONNREFUSED");
    }),
  );
  return { calls };
}

async function caught(call: () => Promise<unknown>): Promise<{ code: string; message: string }> {
  try {
    await call();
    return { code: "", message: "" };
  } catch (err) {
    return {
      code: (err as { code?: string })?.code ?? "",
      message: formatGfError(err),
    };
  }
}

describe("QA V9 · 网络错误四态与门禁中文提示", () => {
  it("① 非法连线 422：GF_EDGE_ILLEGAL 经 formatGfError 转中文，无原始错误码", async () => {
    stubFailure(422, "GF_EDGE_ILLEGAL", "");
    const e = await caught(() =>
      applyLinkPatch("sid-err", {
        op: "add_edge",
        edge: toGfEdge("E_MSG_STEP", conn("UN1", "CM1")),
      }),
    );
    expect(e.code).toBe("GF_EDGE_ILLEGAL");
    expect(e.message).toContain("白名单");
    expect(e.message).not.toMatch(/GF_|[A-Za-z]{3,}/);
  });

  it("② 跳过工程摘要直调 /confirm：GF_GATE_NOT_CONFIRMED 经 mapConfirmError 转中文", async () => {
    stubFailure(409, "GF_GATE_NOT_CONFIRMED", "确认弹窗须先展示一次工程视角摘要（Q9）");
    const e = await caught(() => confirmSpec("sid-err", true));
    expect(e.code).toBe("GF_GATE_NOT_CONFIRMED");
    const note = mapConfirmError(e.code, e.message);
    expect(note).toBe("确认动作必须由你显式点击，系统不会自动代为确认。");
    expect(note).not.toMatch(/GF_|[A-Za-z]{3,}/);
    expect(e.message).toContain("确认动作必须由你显式点击");
  });

  it("③ 5xx：最多重试 3 次（共 4 次请求）后中文降级，不无限重试", async () => {
    const { calls } = stubFailure(500, "", "");
    const e = await caught(() => fetchState("sid-err", "prj-err"));
    expect(calls).toHaveLength(4);
    expect(e.message).toContain("网关服务暂时不可用");
    expect(e.message).toContain("已重试 3 次仍未恢复");
    expect(e.message).not.toContain("GF_");
  });

  it("④ 网络离线：fetch 抛错立即给中文离线提示且不重试", async () => {
    const { calls } = stubOffline();
    const e = await caught(() => fetchState("sid-err", "prj-err"));
    expect(calls).toHaveLength(1);
    expect(e.code).toBe("GF_OFFLINE");
    expect(e.message).toContain("离线：网络连接不可用");
    expect(e.message).not.toContain("ECONNREFUSED");
  });

  it("⑤ 404：中文安全降级，不产生写入、不外露英文错误", async () => {
    stubFailure(404, "", "");
    const e = await caught(() => fetchState("sid-err", "prj-err"));
    expect(e.message).toContain("暂未上线");
    expect(e.message).toContain("未产生任何写入");
    expect(e.message).not.toContain("404 Not Found");
  });

  it("⑥ Wizard 进入步 3 必调 onEnterConfirm；/confirm 失败分支停步 3、不重试、不 GO(4)", () => {
    const iGo3 = wizardSource.indexOf('dispatch({ type: "GO", step: 3 })');
    const iEnter = wizardSource.indexOf("onEnterConfirm()");
    expect(iGo3).toBeGreaterThan(-1);
    expect(iEnter).toBeGreaterThan(iGo3);
    expect(wizardSource).toContain("onConfirmAndGenerate={onConfirmAndGenerate}");

    const start = channelSource.indexOf("const onConfirmAndGenerate");
    const end = channelSource.indexOf("const onBeginEditAndGoLink", start);
    const block = channelSource.slice(start, end);
    const catchBlock = block.slice(block.indexOf("} catch (caught) {"));
    expect(catchBlock).toContain("SET_CONFIRM_NOTE");
    expect(catchBlock).toContain("mapConfirmError(code, message)");
    expect(catchBlock).not.toContain('type: "GO"');
    expect(catchBlock).not.toContain("setTimeout");
    expect(catchBlock).not.toContain("generateProjectPackage");
  });
});
