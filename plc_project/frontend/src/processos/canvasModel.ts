/* PLAN §3.1 整机/工位 Canvas · 纯聚合逻辑（无 React、无随机、无坐标）。
 *
 * /trace/graphs 只返回四图对象（不含关系边），因此：
 *  - 组件→工位归属：用组件对象 context 的 physical_path 首段（后端自己的
 *    part_of 链解析结果）匹配工位 display_name/别名；
 *  - 组件→CM：组件与 af_cm 共享 attributes.cm（契约资源 ID）；
 *  - 步骤→EM：behavior_step.attributes.em 与 af_em.attributes.em 对齐，
 *    EM 显示名来自 CM context 的 af 段。
 * 任何解析不出的字段保持 UNKNOWN，不做猜测；同数据同结果（顺序一律取自
 * 后端数组顺序，不排序、不随机）。 */
import type { Incident, ObjectContext, TraceGraphs, TraceObject } from "./types";

export const UNKNOWN = "UNKNOWN";
/** 与 Traceability 的口径一致：RESOLVED（及 CLOSED）之外都算未关闭。 */
export const CLOSED_INCIDENT_STATUSES: readonly string[] = ["RESOLVED", "CLOSED"];

export function isOpenIncident(i: Incident): boolean {
  return !CLOSED_INCIDENT_STATUSES.includes(String(i.handover?.status ?? ""));
}

/** 物理路径首段 = 工位名（后端 _physical_path 以工位为根）。 */
export function stationNameOfPath(path: string): string | null {
  const seg = String(path ?? "").split("/").map(s => s.trim()).filter(Boolean);
  return seg.length > 0 ? seg[0] : null;
}

export function attrStr(o: TraceObject, key: string): string {
  const v = (o.attributes ?? {})[key];
  return v === undefined || v === null ? "" : String(v);
}

export function attrNum(o: TraceObject, key: string): number | null {
  const v = (o.attributes ?? {})[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function strList(o: TraceObject, key: string): string[] | null {
  const v = (o.attributes ?? {})[key];
  return Array.isArray(v) ? v.map(String) : null;
}

export function isStation(o: TraceObject): boolean { return o.kind === "station"; }
export function isComponent(o: TraceObject): boolean { return o.kind === "component"; }

export interface StationMembership {
  component: TraceObject;
  /** physical_path 首段解析出的工位名；null → 归属 UNKNOWN。 */
  stationName: string | null;
  /** 经 attributes.cm 匹配到的 af_cm；null → 驱动契约 UNKNOWN。 */
  cm: TraceObject | null;
  physicalPath: string | null;
}

/** 组件归属解析：context 缺失/路径为空 → stationName null（诚实 UNKNOWN）。 */
export function assignComponents(graphs: TraceGraphs, compContexts: Record<string, ObjectContext>): StationMembership[] {
  const cmByCmKey = new Map<string, TraceObject>();
  for (const o of graphs.AfGraph) {
    if (o.kind !== "af_cm") continue;
    const k = attrStr(o, "cm");
    if (k && !cmByCmKey.has(k)) cmByCmKey.set(k, o); // 首个匹配，数组顺序确定
  }
  return graphs.PhysicalGraph.filter(isComponent).map(component => {
    const ctx = compContexts[component.object_id];
    const physicalPath = ctx?.physical_path ?? null;
    const key = attrStr(component, "cm");
    return {
      component,
      stationName: physicalPath ? stationNameOfPath(physicalPath) : null,
      cm: key ? cmByCmKey.get(key) ?? null : null,
      physicalPath,
    };
  });
}

export interface StationSummary {
  station: TraceObject;
  components: TraceObject[];
  cms: TraceObject[];
  /** 归属到该工位的未关闭问题单（对象链优先，物理路径段兜底）。 */
  incidents: Incident[];
  openIncidents: number;
  status: string;
}

export interface StationAggregation {
  summaries: StationSummary[];
  /** 工位归属无法解析的组件（显示为 UNKNOWN，不并入任何工位）。 */
  unassigned: StationMembership[];
}

export function buildStationSummaries(
  graphs: TraceGraphs, incidents: Incident[], memberships: StationMembership[],
): StationAggregation {
  const stations = graphs.PhysicalGraph.filter(isStation);
  const byStation = new Map<string, StationMembership[]>();
  const cmToStation = new Map<string, string>();
  const unassigned: StationMembership[] = [];
  for (const m of memberships) {
    const st = m.stationName
      ? stations.find(s => s.display_name === m.stationName || (s.aliases ?? []).includes(m.stationName!))
      : undefined;
    if (!st) { unassigned.push(m); continue; }
    const list = byStation.get(st.object_id) ?? [];
    list.push(m);
    byStation.set(st.object_id, list);
    if (m.cm) cmToStation.set(m.cm.object_id, st.object_id);
  }
  const open = incidents.filter(isOpenIncident);
  const summaries = stations.map(station => {
    const ms = byStation.get(station.object_id) ?? [];
    const hit = open.filter(i => {
      const via = cmToStation.get(i.object_id);
      if (via) return via === station.object_id; // 对象链能定位就不看路径，避免跨工位重复计
      const segs = String(i.physical_path_at_event ?? "").split("/").map(s => s.trim());
      return segs.includes(station.display_name) || (station.aliases ?? []).some(a => segs.includes(a));
    });
    return {
      station,
      components: ms.map(m => m.component),
      cms: ms.map(m => m.cm).filter((c): c is TraceObject => c !== null),
      incidents: hit,
      openIncidents: hit.length,
      status: station.status || UNKNOWN,
    };
  });
  return { summaries, unassigned };
}

/** 按项目（机器）过滤工位：项目已登记构建的 SourceMap semantic_object_id
 *  里包含该工位任一 CM → 归属该项目。无构建记录 → 全保留并由调用方标注
 *  归属 UNKNOWN（不能因此隐藏工位）。 */
export function filterSummariesByProject(summaries: StationSummary[], semanticIds: Set<string>):
  { kept: StationSummary[]; excluded: number } {
  if (semanticIds.size === 0) return { kept: summaries, excluded: 0 };
  const kept = summaries.filter(s => s.cms.some(c => semanticIds.has(c.object_id)));
  return { kept, excluded: summaries.length - kept.length };
}

export interface CmCardModel {
  component: TraceObject;
  cm: TraceObject | null;
  commands: string[] | null;
  feedback: string[] | null;
  driverContract: string | null;
  status: string;
  alarms: { definition_id: string; code: string; description: string }[];
  openIncidents: number;
}

export function buildCmCards(
  memberships: StationMembership[], cmContexts: Record<string, ObjectContext>, incidents: Incident[],
): CmCardModel[] {
  return memberships.map(m => {
    const cm = m.cm;
    const ctx = cm ? cmContexts[cm.object_id] : undefined;
    return {
      component: m.component,
      cm,
      commands: cm ? strList(cm, "commands") : null,
      feedback: cm ? strList(cm, "feedback") : null,
      driverContract: cm ? attrStr(cm, "driver_contract") || attrStr(cm, "kind") || null : null,
      status: cm?.status || m.component.status || UNKNOWN,
      alarms: (ctx?.alarm_definitions ?? []).map(a => ({
        definition_id: a.definition_id, code: a.code, description: a.description,
      })),
      openIncidents: cm ? incidents.filter(i => isOpenIncident(i) && i.object_id === cm.object_id).length : 0,
    };
  });
}

export interface StepChipModel {
  step: TraceObject;
  timeoutMs: number | null;
  guard: string;
  isFault: boolean;
  /** 关联问题单记录的期望/观测（按 attributes.step 匹配；无记录 → null）。 */
  expected: string | null;
  observed: string | null;
}

/** 层2 步骤链：EM 归属（attributes.em）命中的全部步骤 ∪ 各 CM context 的
 *  behavior 段步骤，按 BehaviorGraph 数组顺序输出并按 object_id 去重。 */
export function buildStepChains(
  graphs: TraceGraphs, cmContexts: Record<string, ObjectContext>, emAttrs: Set<string>, incidents: Incident[],
): StepChipModel[] {
  const ctxStepIds = new Set<string>();
  for (const c of Object.values(cmContexts)) {
    for (const b of c.behavior ?? []) if (b.object_id) ctxStepIds.add(b.object_id);
  }
  const seen = new Set<string>();
  const out: StepChipModel[] = [];
  for (const step of graphs.BehaviorGraph) {
    if (step.kind !== "behavior_step" || seen.has(step.object_id)) continue;
    const inEm = emAttrs.size > 0 && emAttrs.has(attrStr(step, "em"));
    if (!inEm && !ctxStepIds.has(step.object_id)) continue;
    seen.add(step.object_id);
    const sid = attrStr(step, "step");
    const inc = sid ? incidents.find(i => String((i.behavior ?? {}).step_id ?? "") === sid) : undefined;
    out.push({
      step,
      timeoutMs: attrNum(step, "timeout_ms"),
      guard: attrStr(step, "guard"),
      isFault: (step.attributes ?? {}).is_fault === true,
      expected: inc && String((inc.behavior ?? {}).expected ?? "") || null,
      observed: inc && String((inc.behavior ?? {}).observed ?? "") || null,
    });
  }
  return out;
}
