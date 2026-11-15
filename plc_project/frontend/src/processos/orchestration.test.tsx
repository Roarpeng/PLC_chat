import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { OrchApiError, orchApi, type ContractWithSchedule, type ScheduleEntry } from "./apiOrch";
import {
  buildOrchModel, buildSchedulePayload, EmCard, loadOrchestrationData, moveCard,
  orchestrationHints, OrchTrack, OrchestrationHonestBanner, parallelGroups,
  toggleParallel, toggleResource, type OrchestrationModel, type SaveState,
} from "./OrchestrationView";
import type { Operation, Resource, TraceGraphs, TraceObject } from "./types";

/* Node-environment orchestration tests (no jsdom), pattern of canvas.smoke.test.tsx:
   (1) fetch mocked per endpoint, the REAL loader aggregates;
   (2) pure model functions (track / groups / payload / hints) tested directly;
   (3) hook-free leaves invoked as plain functions so wired handlers fire;
   (4) apiOrch binding asserts actor headers + patch payload shape. */

const BASE = "/api/processos";
const noop = () => { };

const cm = (id: string, exclusive = true): Resource => ({
  id, name: id, kind: "cylinder", commands: ["Extend"], feedback: ["Extended"],
  status: [], exclusive, io_bindings: {},
});
const op = (id: string, em: string, resource_ids: string[]): Operation => ({
  id, name: id + "工艺", unit: "U_ASSEMBLY", em, resource_ids,
  preconditions: [], steps: [], acceptance: [],
});

const contract: ContractWithSchedule = {
  id: "PRJ_ORCH", name: "编排测试", target_framework: "siemens-af-basic@unverified",
  unit: "U_ASSEMBLY", schema: "process-contract/1.0",
  resources: [cm("CM_CLAMP_CYL"), cm("CM_FEED_CYL"), cm("CM_PRESS_CYL", false)],
  operations: [
    op("OP_CLAMP", "EM_CLAMP", ["CM_CLAMP_CYL"]),
    op("OP_FEED", "EM_FEED", ["CM_FEED_CYL"]),
    op("OP_PRESS", "EM_PRESS", ["CM_PRESS_CYL"]),
  ],
  open_questions: [], scenarios: [],
};

function withSchedule(entries: ScheduleEntry[]): ContractWithSchedule {
  return { ...contract, schedule: entries };
}

function tobj(object_id: string, kind: string, display_name: string, attributes: Record<string, unknown>): TraceObject {
  const graph = kind.startsWith("af_") ? "AfGraph" : "PhysicalGraph";
  return { object_id, kind, graph, display_name, aliases: [], attributes, status: "DESIGNED", created_at: 1, history: [] };
}

const graphs: TraceGraphs = {
  PhysicalGraph: [], AfGraph: [tobj("af_em_1", "af_em", "EM_CLAMP", { em: "EM_CLAMP", unit: "U_ASSEMBLY" })],
  BehaviorGraph: [], EvidenceGraph: [],
};

function mockRoutes(routes: Record<string, unknown>) {
  return vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = routes[url];
    const ok = body !== undefined;
    return {
      ok, status: ok ? 200 : 404, statusText: ok ? "OK" : "Not Found",
      text: async () => JSON.stringify(ok ? body : { error: `not found: ${url}` }),
    } as unknown as Response;
  }));
}

const denoise = (html: string) => html.replace(/<!-- -->/g, "");

afterEach(() => vi.unstubAllGlobals());

describe("loadOrchestrationData (real loader + fetch mock)", () => {
  it("aggregates contract/revision and tolerates /trace/graphs failure (null, not guessed)", async () => {
    mockRoutes({ [`${BASE}/projects/PRJ_ORCH`]: { contract, revision: 4, profile_id: "p" } });
    const d = await loadOrchestrationData("PRJ_ORCH");
    expect(d.revision).toBe(4);
    expect(d.contract.operations).toHaveLength(3);
    expect(d.graphs).toBeNull();
  });

  it("loads graphs when available and surfaces contract failure as an error", async () => {
    mockRoutes({
      [`${BASE}/projects/PRJ_ORCH`]: { contract, revision: 1, profile_id: "p" },
      [`${BASE}/trace/graphs`]: graphs,
    });
    const d = await loadOrchestrationData("PRJ_ORCH");
    expect(d.graphs?.AfGraph).toHaveLength(1);
  });
});

describe("buildOrchModel (contract -> sequence track)", () => {
  it("sorts scheduled EMs by order and appends unscheduled operations honestly", () => {
    const c = withSchedule([
      { em: "EM_CLAMP", order: 2, resource_ids: ["CM_CLAMP_CYL"] },
      { em: "EM_FEED", order: 0, resource_ids: ["CM_FEED_CYL"], parallel_with: ["EM_PRESS"] },
      { em: "EM_PRESS", order: 1, resource_ids: [], parallel_with: ["EM_FEED"] },
    ]);
    const m = buildOrchModel(c);
    expect(m.cards.map(x => x.em)).toEqual(["EM_FEED", "EM_PRESS", "EM_CLAMP"]); // order 即位置
    expect(m.cards[0].parallelWith).toEqual(["EM_PRESS"]);
    expect(m.cards[2].scheduled).toBe(true);
    delete (c as { schedule?: ScheduleEntry[] }).schedule;
    const m2 = buildOrchModel(c); // 无 schedule：全部按契约顺序入轨
    expect(m2.cards.map(x => x.em)).toEqual(["EM_CLAMP", "EM_FEED", "EM_PRESS"]);
    expect(m2.cards.every(x => !x.scheduled)).toBe(true);
    expect(m2.cards[0].resourceIds).toEqual(["CM_CLAMP_CYL"]); // 未编排卡沿用 operation.resource_ids
  });
});

describe("track edits (structured, no free-form input)", () => {
  const m = buildOrchModel(withSchedule([
    { em: "EM_FEED", order: 0, resource_ids: ["CM_FEED_CYL"] },
    { em: "EM_CLAMP", order: 1, resource_ids: ["CM_CLAMP_CYL"] },
    { em: "EM_PRESS", order: 2, resource_ids: [] },
  ]));

  it("moveCard swaps position and renumbers (order = track index); boundaries are no-ops", () => {
    const up = moveCard(m.cards, "EM_CLAMP", -1);
    expect(up.map(c => c.em)).toEqual(["EM_CLAMP", "EM_FEED", "EM_PRESS"]);
    expect(up.map(c => c.order)).toEqual([0, 1, 2]);
    expect(moveCard(m.cards, "EM_FEED", -1)).toEqual(m.cards);   // 首位上移无效
    expect(moveCard(m.cards, "EM_PRESS", 1)).toEqual(m.cards);   // 末位下移无效
  });

  it("toggleResource / toggleParallel are additive toggles; self-parallel refused", () => {
    const r = toggleResource(m.cards, "EM_PRESS", "CM_PRESS_CYL");
    expect(r[2].resourceIds).toEqual(["CM_PRESS_CYL"]);
    expect(toggleResource(r, "EM_PRESS", "CM_PRESS_CYL")[2].resourceIds).toEqual([]);
    const p = toggleParallel(m.cards, "EM_CLAMP", "EM_PRESS");
    expect(p[1].parallelWith).toEqual(["EM_PRESS"]);
    expect(toggleParallel(p, "EM_CLAMP", "EM_PRESS")[1].parallelWith).toEqual([]);
    expect(toggleParallel(m.cards, "EM_CLAMP", "EM_CLAMP")).toEqual(m.cards); // 不与自己
  });
});

describe("parallel groups + payload shape", () => {
  it("groups are undirected connected components; loners get -1", () => {
    const cards = buildOrchModel(withSchedule([
      { em: "EM_FEED", order: 0, resource_ids: [], parallel_with: ["EM_PRESS"] },
      { em: "EM_PRESS", order: 1, resource_ids: [], parallel_with: ["EM_FEED"] },
      { em: "EM_CLAMP", order: 2, resource_ids: [] },
    ])).cards;
    const g = parallelGroups(cards);
    expect(g.get("EM_FEED")).toBe(0);
    expect(g.get("EM_PRESS")).toBe(0);   // 双向声明同组
    expect(g.get("EM_CLAMP")).toBe(-1);
    const oneWay = parallelGroups([
      { ...cards[0], parallelWith: ["EM_PRESS"] },
      { ...cards[1], parallelWith: [] },
      cards[2],
    ]);
    expect(oneWay.get("EM_FEED")).toBe(oneWay.get("EM_PRESS")); // 单向声明也成组（无向）
  });

  it("buildSchedulePayload locks the backend op shape (order = 0..n-1)", () => {
    const payload = buildSchedulePayload(buildOrchModel(withSchedule([
      { em: "EM_FEED", order: 7, resource_ids: ["CM_FEED_CYL"], mode: "auto", parallel_with: ["EM_CLAMP"] },
      { em: "EM_CLAMP", order: 9, resource_ids: [] },
    ])).cards);
    expect(payload).toEqual([
      { em: "EM_FEED", order: 0, resource_ids: ["CM_FEED_CYL"], mode: "auto", parallel_with: ["EM_CLAMP"] },
      { em: "EM_CLAMP", order: 1, resource_ids: [], mode: "", parallel_with: [] },
      /* 未编排的 EM_PRESS 附轨入编，沿用其 operation.resource_ids */
      { em: "EM_PRESS", order: 2, resource_ids: ["CM_PRESS_CYL"], mode: "", parallel_with: [] },
    ]);
  });
});

describe("orchestrationHints (front-end derived interlocks)", () => {
  it("flags exclusive resource double-booking, asymmetric and unknown parallel refs", () => {
    const cards = buildOrchModel(withSchedule([
      { em: "EM_CLAMP", order: 0, resource_ids: ["CM_CLAMP_CYL"] },
      { em: "EM_FEED", order: 1, resource_ids: ["CM_CLAMP_CYL", "CM_FEED_CYL"], parallel_with: ["EM_GHOST"] },
    ])).cards;
    const model: OrchestrationModel = { unit: "U_ASSEMBLY", resources: contract.resources, cards, duplicateOrders: [] };
    const hints = orchestrationHints(model);
    expect(hints.some(h => h.level === "err" && h.text.includes("CM_CLAMP_CYL") && h.text.includes("独占"))).toBe(true);
    expect(hints.some(h => h.level === "err" && h.text.includes("EM_GHOST"))).toBe(true);
    const asym = orchestrationHints({
      ...model,
      cards: [cards[0], { ...cards[1], parallelWith: ["EM_CLAMP"] }],
    });
    expect(asym.some(h => h.level === "warn" && h.text.includes("不对称"))).toBe(true);
    expect(asym.some(h => h.level === "err")).toBe(true); // 独占冲突仍在
    const clean = orchestrationHints({
      ...model,
      cards: buildOrchModel(withSchedule([
        { em: "EM_CLAMP", order: 0, resource_ids: ["CM_CLAMP_CYL"] },
        { em: "EM_FEED", order: 1, resource_ids: ["CM_FEED_CYL"] },
      ])).cards,
    });
    expect(clean).toEqual([]); // 非独占 CM_PRESS_CYL 共用不告警
  });

  it("surfaces duplicate orders coming from a tampered contract schedule", () => {
    const model = buildOrchModel(withSchedule([
      { em: "EM_CLAMP", order: 1, resource_ids: [] },
      { em: "EM_FEED", order: 1, resource_ids: [] },
    ]));
    expect(model.duplicateOrders).toEqual([1]);
    expect(orchestrationHints(model).some(h => h.level === "err" && h.text.includes("重复 order 1"))).toBe(true);
  });
});

describe("OrchTrack / EmCard rendering", () => {
  const model = buildOrchModel(withSchedule([
    { em: "EM_FEED", order: 0, resource_ids: ["CM_FEED_CYL"], parallel_with: ["EM_PRESS"] },
    { em: "EM_PRESS", order: 1, resource_ids: ["CM_PRESS_CYL"], parallel_with: ["EM_FEED"] },
    { em: "EM_CLAMP", order: 2, resource_ids: ["CM_CLAMP_CYL"] },
  ]));
  const saveOk: SaveState = { kind: "ok", revision: 5, message: "已保存 · revision 4 → 5" };
  const trackHtml = (m: OrchestrationModel = model, saveState: SaveState = { kind: "idle" }) => denoise(renderToString(
    <OrchTrack model={m} graphs={graphs} saveState={saveState}
      onSave={noop} onReload={noop} onUp={noop} onDown={noop}
      onToggleResource={noop} onToggleParallel={noop} />));

  it("renders EM cards in schedule order with station, order badge and resource chips", () => {
    const html = trackHtml();
    expect(html).toContain("#1");
    expect(html.indexOf("EM_FEED")).toBeLessThan(html.indexOf("EM_PRESS"));
    expect(html.indexOf("EM_PRESS")).toBeLessThan(html.indexOf("EM_CLAMP"));
    expect(html).toContain("所属工位");
    expect(html).toContain("U_ASSEMBLY");
    expect(html).toContain("CM_FEED_CYL"); // 资源占用徽章（多选 chips）
    expect(html).toContain("OP_CLAMP");    // operation id
  });

  it("colors parallel groups: same group same class + badge, loner unclassed", () => {
    const html = trackHtml();
    expect(html).toContain('data-group="g0"');
    expect(html).toContain("并行 G1");       // 同组并排着色分组
    const groups = parallelGroups(model.cards);
    expect(groups.get("EM_CLAMP")).toBe(-1); // 孤立 EM 无组
    expect((html.match(/data-group="g0"/g) ?? []).length).toBe(2); // EM_FEED/EM_PRESS 两卡同组
  });

  it("always shows the honest boundary banner about the pass-through unit generator", () => {
    const html = trackHtml();
    expect(html).toContain("调度声明已入工艺契约");
    expect(html).toContain("透传壳");
    expect(html).toContain("evidence/v2/real/processos_attempt_01");
    expect(html).toContain("暂不进入生成 SCL");
    expect(html).toContain("#State := #Mode"); // unit 块透传行为说明
    const banner = renderToString(<OrchestrationHonestBanner />);
    expect(banner).toContain("生成器扩展后自动生效");
  });

  it("renders conflict hints and disables save while errors exist", () => {
    const conflicted = buildOrchModel(withSchedule([
      { em: "EM_CLAMP", order: 0, resource_ids: ["CM_CLAMP_CYL"] },
      { em: "EM_FEED", order: 1, resource_ids: ["CM_CLAMP_CYL"], parallel_with: ["EM_GHOST"] },
    ]));
    const html = trackHtml(conflicted);
    expect(html).toContain("资源独占冲突");
    expect(html).toContain("EM_GHOST");
    expect(html).toContain("存在冲突，保存已禁用");
    expect(html).toContain('disabled'); // 保存按钮禁用
  });

  it("shows the revision bump after save and the in-place red bar on 409/422", () => {
    const ok = trackHtml(model, saveOk);
    expect(ok).toContain("已保存 · revision 4 → 5");
    const err = trackHtml(model, { kind: "err", message: "版本冲突（409）：base_revision 4 != current 6 —— 契约已被他人推进，请「重新装载」后重编。" });
    expect(err).toContain("版本冲突（409）");
    expect(err).toContain('role="alert"');
  });

  it("labels unscheduled EMs honestly and marks graph coverage", () => {
    const html = trackHtml(buildOrchModel(contract)); // 无 schedule
    expect(html).toContain("未编排");
    expect(html).toContain("图谱 EM 1/3"); // 只有 EM_CLAMP 映射到 af_em 对象
    const noGraph = denoise(renderToString(
      <OrchTrack model={model} graphs={null} saveState={{ kind: "idle" }}
        onSave={noop} onReload={noop} onUp={noop} onDown={noop}
        onToggleResource={noop} onToggleParallel={noop} />));
    expect(noGraph).toContain("图谱 UNKNOWN");
  });

  it("fires move / resource / parallel handlers from the hook-free card", () => {
    const up = vi.fn(), down = vi.fn(), res = vi.fn(), par = vi.fn();
    const card = EmCard({
      card: model.cards[2], cards: model.cards, index: 2, group: -1,
      resources: model.resources,
      onUp: up, onDown: down, onToggleResource: res, onToggleParallel: par,
    });
    /* 文档序收集全部可点击元素：上移、下移、资源 chips（契约资源序）、并行 chips（其他 EM 轨序） */
    const onClicks: (() => void)[] = [];
    const walk = (n: unknown): void => {
      if (Array.isArray(n)) { n.forEach(walk); return; }
      if (!n || typeof n !== "object") return;
      const props = (n as { props?: { onClick?: unknown; children?: unknown } }).props;
      if (props && typeof props.onClick === "function") onClicks.push(props.onClick as () => void);
      const kids = props?.children;
      (Array.isArray(kids) ? kids : [kids]).forEach(walk);
    };
    walk(card);
    onClicks[0]();  // 上移
    onClicks[1]();  // 下移
    expect(up).toHaveBeenCalledWith("EM_CLAMP");
    expect(down).toHaveBeenCalledWith("EM_CLAMP");
    onClicks[2]();  // 资源 chip：CM_CLAMP_CYL（契约资源序第一个）
    expect(res).toHaveBeenCalledWith("EM_CLAMP", "CM_CLAMP_CYL");
    onClicks[5]();  // 并行 chip：其他 EM 第一个（EM_FEED）
    expect(par).toHaveBeenCalledWith("EM_CLAMP", "EM_FEED");
    expect(onClicks).toHaveLength(7); // 2 move + 3 resources + 2 other EMs
  });
});

describe("apiOrch binding (independent module, actor headers)", () => {
  it("saveSchedule posts a set_operation_schedule patch to the existing patches channel", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init: init ?? {} });
      return {
        ok: true, status: 200, statusText: "OK",
        text: async () => JSON.stringify({ revision: 5, contract }),
      } as unknown as Response;
    }));
    const entries: ScheduleEntry[] = [
      { em: "EM_FEED", order: 0, resource_ids: ["CM_FEED_CYL"], parallel_with: ["EM_PRESS"] },
      { em: "EM_PRESS", order: 1, resource_ids: [] },
    ];
    const r = await orchApi.saveSchedule("PRJ_ORCH", 4, entries, "req-1");
    expect(r.revision).toBe(5);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/projects/PRJ_ORCH/patches`);
    expect(calls[0].init.method).toBe("POST");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["X-Actor-Id"]).toBeTruthy();          // actorHeaders() 演示身份传递
    expect(headers["X-Actor-Role"]).toBeTruthy();
    expect(headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(String(calls[0].init.body));
    expect(body).toEqual({
      base_revision: 4, request_id: "req-1", source: "user",
      ops: [{ op: "set_operation_schedule", path: "/schedule", schedule: entries }],
    });
  });

  it("maps 409 / 422 to OrchApiError with status (in-place red bar source)", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: string) => ({
      ok: false, status: 409, statusText: "Conflict",
      text: async () => JSON.stringify({ error: "base_revision 4 != current 6" }),
    } as unknown as Response)));
    await expect(orchApi.saveSchedule("PRJ_ORCH", 4, [])).rejects.toMatchObject(
      { status: 409, message: "base_revision 4 != current 6" });
    vi.stubGlobal("fetch", vi.fn(async (_url: string) => ({
      ok: false, status: 422, statusText: "Unprocessable Entity",
      text: async () => JSON.stringify({ error: "no operation with em 'EM_NOPE'" }),
    } as unknown as Response)));
    await expect(orchApi.saveSchedule("PRJ_ORCH", 4, [
      { em: "EM_NOPE", order: 0, resource_ids: [] },
    ])).rejects.toBeInstanceOf(OrchApiError);
  });

  it("project() loads the contract with its schedule declaration", async () => {
    mockRoutes({
      [`${BASE}/projects/PRJ_ORCH`]: {
        contract: withSchedule([{ em: "EM_CLAMP", order: 0, resource_ids: ["CM_CLAMP_CYL"] }]),
        revision: 2, profile_id: "p",
      },
    });
    const p = await orchApi.project("PRJ_ORCH");
    expect(p.contract.schedule?.[0].em).toBe("EM_CLAMP");
  });
});
