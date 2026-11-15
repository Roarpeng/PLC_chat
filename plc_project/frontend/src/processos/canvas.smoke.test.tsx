import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { OpenCanvasButton } from "./FieldConsole";
import { ALL_MACHINES, loadMachineData, MachineCanvasView, StationCard } from "./MachineCanvas";
import { CmCard, loadStationData, StationCanvasView, StepChip } from "./StationCanvas";
import type { Incident, ObjectContext, TraceGraphs, TraceObject } from "./types";

/* Node-environment canvas tests (no jsdom), pattern of views.smoke.test.tsx:
   (1) fetch is mocked per endpoint and the REAL loaders (loadMachineData /
   loadStationData, the same code path the useEffect runs) aggregate the data;
   (2) the presentational views render that data to markup;
   (3) hook-free leaf cards are invoked as plain functions so their wired
   onClick handlers fire without a DOM. */

const BASE = "/api/processos";

function tobj(object_id: string, kind: string, display_name: string, attributes: Record<string, unknown>,
  status = "DESIGNED"): TraceObject {
  const graph = kind.startsWith("af_") ? "AfGraph" : kind.startsWith("behavior_") ? "BehaviorGraph" : "PhysicalGraph";
  return { object_id, kind, graph, display_name, aliases: [], attributes, status, created_at: 1, history: [] };
}

const graphs: TraceGraphs = {
  PhysicalGraph: [
    tobj("station_1", "station", "电池更换站", { name: "电池更换站" }),
    tobj("component_1", "component", "夹紧气缸（双作用）", { cm: "CM_CLAMP_CYL" }),
    tobj("station_2", "station", "检测站", { name: "检测站" }),
    tobj("component_2", "component", "检测探头", { cm: "CM_PROBE" }),
    tobj("component_3", "component", "未归属支架", {}),
  ],
  AfGraph: [
    tobj("af_unit_1", "af_unit", "U_ASSEMBLY", { name: "U_ASSEMBLY" }),
    tobj("af_em_1", "af_em", "夹紧循环", { em: "EM_CLAMP", unit: "U_ASSEMBLY" }),
    tobj("cm_1", "af_cm", "夹紧气缸（双作用）", {
      cm: "CM_CLAMP_CYL", kind: "cylinder", commands: ["Extend", "Retract"],
      feedback: ["Extended", "Retracted"], driver_contract: "cylinder",
    }),
    tobj("cm_2", "af_cm", "检测探头", { cm: "CM_PROBE", kind: "sensor", commands: ["Measure"], feedback: ["Done"], driver_contract: "sensor" }),
  ],
  BehaviorGraph: [
    tobj("step_wait", "behavior_step", "等待启动", { step: "S_WAIT", guard: "Start AND SafetyPermit", em: "EM_CLAMP", timeout_ms: 0, is_fault: false }),
    tobj("step_extend", "behavior_step", "伸出夹紧", { step: "S_EXTEND", guard: "Extended", em: "EM_CLAMP", timeout_ms: 3000, is_fault: false }),
    tobj("step_fault", "behavior_step", "故障保持", { step: "S_FAULT", guard: "", em: "EM_CLAMP", timeout_ms: 0, is_fault: true }),
  ],
  EvidenceGraph: [],
};

const handover = { owner: "engineer_on_duty", status: "INVESTIGATING", next_action: "" };
const inc1: Incident = {
  incident_id: "INC-2026-0042", object_id: "cm_1", asset_id: "machine_001",
  physical_path_at_event: "设备1/电池更换站/夹紧机构/气缸A", af_refs: {},
  alarm: { definition_id: "alarm_clamp_timeout", code: "CM_MOTION_TIMEOUT" },
  behavior: { step_id: "S_EXTEND", expected: "extended=true within 3000ms", observed: "extended=false at 3000ms" },
  software: {}, references: {},
  triage: { fact: "伸出反馈未按时出现", hypotheses: ["气压不足"], root_cause: null },
  handover,
};
const inc2: Incident = {
  ...inc1, incident_id: "INC-2", object_id: "cm_2", physical_path_at_event: "设备1/检测站/探头",
  handover: { ...handover, status: "RESOLVED" },
};

function compCtx(id: string, name: string, path: string): ObjectContext {
  return {
    object_id: id, found: true, kind: "component", graph: "PhysicalGraph", display_name: name,
    aliases: [], status: "DESIGNED", physical_path: path, af: { cm: name },
    behavior: [], source_map: [], alarm_definitions: [], history: [], build_id: "build_219",
  };
}
const extendStep = { object_id: "step_extend", display_name: "伸出夹紧", attributes: { step: "S_EXTEND", guard: "Extended", em: "EM_CLAMP", timeout_ms: 3000, is_fault: false } };
const cmCtx1: ObjectContext = {
  object_id: "cm_1", found: true, kind: "af_cm", graph: "AfGraph", display_name: "夹紧气缸（双作用）",
  aliases: [], status: "DESIGNED", physical_path: "电池更换站/夹紧气缸（双作用）",
  af: { em: "夹紧循环", unit: "U_ASSEMBLY", cm: "夹紧气缸（双作用）" },
  behavior: [extendStep, extendStep], /* backend emits one edge per entry/exit action — must dedupe */
  source_map: [{
    source_map_id: "src_1", semantic_object_id: "cm_1", behavior_step_id: "S_EXTEND",
    release_build_id: "build_219", block_name: "FB_CM_CLAMP_CYL_DRV", block_kind: "FB",
    instance_db: "", scl_line_range: null, ownership: "AF_GENERATED",
  }],
  alarm_definitions: [{ definition_id: "alarm_clamp_timeout", code: "CM_MOTION_TIMEOUT", description: "伸出到位信号未在规定时间内出现" }],
  history: [], build_id: "build_219",
};
const cmCtx2: ObjectContext = {
  ...cmCtx1, object_id: "cm_2", display_name: "检测探头", physical_path: "检测站/检测探头",
  af: {}, behavior: [], source_map: [], alarm_definitions: [],
};

const projectsPayload = {
  projects: [{ project_id: "PRJ_CLAMP", name: "夹紧工站 · HR001", revision: 1, profile_id: "hr001-af-v19", steps: 6 }],
};

function routesFor(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    [`${BASE}/trace/graphs`]: graphs,
    [`${BASE}/incidents`]: { incidents: [inc1, inc2] },
    [`${BASE}/projects`]: projectsPayload,
    [`${BASE}/objects/component_1/context`]: compCtx("component_1", "夹紧气缸（双作用）", "电池更换站/夹紧气缸（双作用）"),
    [`${BASE}/objects/component_2/context`]: compCtx("component_2", "检测探头", "检测站/检测探头"),
    [`${BASE}/objects/cm_1/context`]: cmCtx1,
    [`${BASE}/objects/cm_2/context`]: cmCtx2,
    [`${BASE}/projects/PRJ_CLAMP/sourcemap`]: {
      project_id: "PRJ_CLAMP", builds: ["build_219"],
      source_map: [{
        source_map_id: "src_1", semantic_object_id: "cm_1", behavior_step_id: "S_EXTEND",
        release_build_id: "build_219", block_name: "FB_CM_CLAMP_CYL_DRV", block_kind: "FB",
        instance_db: "", scl_line_range: null, ownership: "AF_GENERATED",
      }],
    },
    ...overrides,
  };
}

function mockRoutes(routes: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = routes[url];
    const ok = body !== undefined;
    return {
      ok, status: ok ? 200 : 404, statusText: ok ? "OK" : "Not Found",
      text: async () => JSON.stringify(ok ? body : { error: `not found: ${url}` }),
    };
  }));
}

function buttonLabels(html: string): string[] {
  const out: string[] = [];
  for (const m of html.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)) {
    out.push(m[1].replace(/<[^>]*>/g, ""));
  }
  return out;
}

/** renderToString 在文本与插值之间插入 `<!-- -->`，断言前归一化。 */
const denoise = (html: string) => html.replace(/<!-- -->/g, "");

afterEach(() => vi.unstubAllGlobals());
const noop = () => { };

describe("MachineCanvas (整机画布 · read-only station grid)", () => {
  it("loadMachineData aggregates stations, component counts and OPEN incident counts", async () => {
    mockRoutes(routesFor());
    const d = await loadMachineData();
    expect(d.summaries).toHaveLength(2);
    const s1 = d.summaries.find(x => x.station.object_id === "station_1")!;
    expect(s1.components).toHaveLength(1);
    expect(s1.openIncidents).toBe(1);          // INVESTIGATING counts
    const s2 = d.summaries.find(x => x.station.object_id === "station_2")!;
    expect(s2.openIncidents).toBe(0);          // RESOLVED does not count
    expect(d.unassigned.map(m => m.component.object_id)).toEqual(["component_3"]); // no context → UNKNOWN, not merged
    const html = denoise(renderToString(
      <MachineCanvasView data={d} project={ALL_MACHINES} onSelectProject={noop} onOpenStation={noop} />));
    expect(html).toContain("电池更换站");
    expect(html).toContain("未关闭 1");
    expect(html).toContain("无未关闭问题");
    expect(html).toContain("全部机器（未按项目过滤）");
    expect(html).toContain("PRJ_CLAMP");
    expect(html).toContain("组件归属 UNKNOWN");
    expect(html).toContain("只读汇总");       // §3.1: no physical actuation here
  });

  it("station card click hands the station object_id (and effective project) to the parent", () => {
    const spy = vi.fn();
    const summary = {
      station: graphs.PhysicalGraph[0], components: [graphs.PhysicalGraph[1]], cms: [graphs.AfGraph[2]],
      incidents: [inc1], openIncidents: 1, status: "DESIGNED",
    };
    const card = StationCard({ summary, onOpen: spy }) as unknown as { props: { onClick: () => void } };
    card.props.onClick();
    expect(spy).toHaveBeenCalledWith("station_1");
    const html = renderToString(<StationCard summary={summary} onOpen={noop} />);
    expect(html).toContain('data-testid="pos-mc-station"');
    expect(html).toContain("进入工位画布");
  });

  it("project (machine) filter keeps only stations whose CMs appear in the project sourcemap", async () => {
    mockRoutes(routesFor());
    const d = await loadMachineData("PRJ_CLAMP");
    expect(d.filteredBy).toBe("PRJ_CLAMP");
    expect(d.summaries.map(s => s.station.object_id)).toEqual(["station_1"]); // cm_1 ∈ sourcemap
    expect(d.excludedByProject).toBe(1);                                     // 检测站 excluded, honestly counted
    const html = denoise(renderToString(
      <MachineCanvasView data={d} project="PRJ_CLAMP" onSelectProject={noop} onOpenStation={noop} />));
    expect(html).toContain("1 个工位无法归属该项目（UNKNOWN），未显示");
  });
});

describe("StationCanvas (工位画布 · three deterministic layers)", () => {
  it("renders CM layer (driver contract), EM step chain (timeout/guard) and resource summary", async () => {
    mockRoutes(routesFor());
    const d = await loadStationData("station_1");
    expect(d.station?.object_id).toBe("station_1");
    expect(d.cmCards).toHaveLength(1);
    expect(d.cmCards[0].commands).toEqual(["Extend", "Retract"]);
    expect(d.cmCards[0].feedback).toEqual(["Extended", "Retracted"]);
    expect(d.cmCards[0].driverContract).toBe("cylinder");
    expect(d.cmCards[0].openIncidents).toBe(1);
    expect(d.emResolved).toBe(true);
    expect(d.steps.map(s => s.step.object_id)).toEqual(["step_wait", "step_extend", "step_fault"]); // deduped, graph order
    const ext = d.steps.find(s => s.step.object_id === "step_extend")!;
    expect(ext.timeoutMs).toBe(3000);
    expect(ext.expected).toBe("extended=true within 3000ms");   // from the incident behavior record
    expect(ext.observed).toBe("extended=false at 3000ms");
    const html = denoise(renderToString(
      <StationCanvasView data={d} onBackToMachine={noop} onOpenObject={noop} />));
    expect(html).toContain("层 1 · 组件 / CM");
    expect(html).toContain("层 2 · EM / 步骤序列");
    expect(html).toContain("层 3 · 资源 / 依赖摘要");
    expect(html).toContain("驱动契约");
    expect(html).toContain("CM_MOTION_TIMEOUT");
    expect(html).toContain("timeout 3000ms");
    expect(html).toContain("故障步");
    expect(html).toContain("整机画布");           // breadcrumb back
    expect(html).toContain("不能在此连线或生成任何控制流"); // §3.1 禁止连线生成控制流
  });

  it("shows explicit UNKNOWN badges when the CM/EM/steps cannot be resolved", async () => {
    const broken: TraceGraphs = {
      ...graphs,
      PhysicalGraph: [
        tobj("station_1", "station", "电池更换站", { name: "电池更换站" }),
        tobj("component_1", "component", "夹紧气缸（双作用）", { cm: "" }), // no af_cm match
      ],
    };
    mockRoutes(routesFor({ [`${BASE}/trace/graphs`]: broken }));
    const d = await loadStationData("station_1");
    expect(d.cmCards[0].cm).toBeNull();
    expect(d.emResolved).toBe(false);
    expect(d.steps).toHaveLength(0);
    const html = renderToString(
      <StationCanvasView data={d} onBackToMachine={noop} onOpenObject={noop} />);
    expect(html).toContain("驱动契约 UNKNOWN");
    expect(html).toContain("EM UNKNOWN");
    expect(html).toContain("步骤 UNKNOWN");
    expect(html).toContain("无映射（UNKNOWN）");
  });

  it("exposes NO write / force / output action buttons (§3.1 整机·工位画布禁止行为)", async () => {
    mockRoutes(routesFor());
    const d = await loadStationData("station_1");
    const stationHtml = renderToString(
      <StationCanvasView data={d} projectId="PRJ_CLAMP" onBackToMachine={noop} onOpenObject={noop} />);
    for (const label of buttonLabels(stationHtml)) {
      expect(label).not.toMatch(/写|强制|输出/);
    }
    const m = await loadMachineData();
    const machineHtml = renderToString(
      <MachineCanvasView data={m} project={ALL_MACHINES} onSelectProject={noop} onOpenStation={noop} />);
    for (const label of buttonLabels(machineHtml)) {
      expect(label).not.toMatch(/写|强制|输出/);
    }
  });

  it("CM card click focuses traceability on the CM object; step chip toggles expansion", () => {
    const openSpy = vi.fn();
    const card = CmCard({
      card: {
        component: graphs.PhysicalGraph[1], cm: graphs.AfGraph[2], commands: ["Extend"], feedback: ["Extended"],
        driverContract: "cylinder", status: "DESIGNED",
        alarms: [{ definition_id: "alarm_clamp_timeout", code: "CM_MOTION_TIMEOUT", description: "" }],
        openIncidents: 1,
      },
      onOpen: openSpy,
    }) as unknown as { props: { onClick: () => void } };
    card.props.onClick();
    expect(openSpy).toHaveBeenCalledWith("cm_1");

    const toggleSpy = vi.fn();
    const model = {
      step: graphs.BehaviorGraph[1], timeoutMs: 3000, guard: "Extended", isFault: false,
      expected: "extended=true within 3000ms", observed: "extended=false at 3000ms",
    };
    const chip = StepChip({ model, open: false, onToggle: toggleSpy }) as unknown as {
      props: { children: { props: { onClick: () => void } }[] };
    };
    const btn = chip.props.children.find(c => c?.props?.onClick)!;
    btn.props.onClick();
    expect(toggleSpy).toHaveBeenCalledWith("step_extend");
    const expanded = renderToString(<StepChip model={model} open onToggle={noop} />);
    expect(expanded).toContain("期望");
    expect(expanded).toContain("extended=true within 3000ms");
  });
});

describe("FieldConsole station-canvas entry", () => {
  it("hands the physical path (first segment = station) to the workbench resolver", () => {
    const spy = vi.fn();
    const btn = OpenCanvasButton({ path: "电池更换站/夹紧气缸（双作用）", onOpen: spy }) as unknown as {
      props: { onClick: () => void };
    };
    btn.props.onClick();
    expect(spy).toHaveBeenCalledWith("电池更换站/夹紧气缸（双作用）");
    const html = renderToString(<OpenCanvasButton path="x" onOpen={noop} />);
    expect(html).toContain("查看工位画布");
    expect(html).toContain('data-testid="fc-open-canvas"');
  });
});
