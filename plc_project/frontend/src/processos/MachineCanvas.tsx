import { useEffect, useState } from "react";
import { processosApi } from "./api";
import {
  assignComponents, buildStationSummaries, filterSummariesByProject, UNKNOWN,
  type StationMembership, type StationSummary,
} from "./canvasModel";
import { Badge, FieldTop, type FieldView } from "./fieldui";
import type { Incident, ObjectContext, ProjectSummary, TraceGraphs, TraceObject } from "./types";
import { Icon } from "./views";

/* PLAN §3.1 整机 Canvas：工位 / 依赖 / 资源 / 状态汇总 + 位置跳转。
 * 只读视图——这里不存在、也不允许出现任何对下层物理执行元件的操作；
 * 点击工位卡进入工位画布继续下钻。 */

export const ALL_MACHINES = "all";

export interface MachineData {
  graphs: TraceGraphs;
  incidents: Incident[];
  projects: ProjectSummary[];
  compContexts: Record<string, ObjectContext>;
  summaries: StationSummary[];
  unassigned: StationMembership[];
  /** 当前按哪个项目（机器）过滤；null = 未过滤。 */
  filteredBy: string | null;
  /** 因无法归属到所选项目而被隐藏的工位数（诚实 UNKNOWN 计数）。 */
  excludedByProject: number;
  /** 所选项目没有任何已登记构建 → 无法按 SourceMap 归属。 */
  attributionUnknown: boolean;
}

/** 机器画布数据装载（真实代码路径，测试用 fetch mock 驱动）。 */
export async function loadMachineData(projectId?: string): Promise<MachineData> {
  const [graphs, incR, projectsR] = await Promise.all([
    processosApi.traceGraphs(), processosApi.incidents(), processosApi.projects(),
  ]);
  const comps = graphs.PhysicalGraph.filter(o => o.kind === "component");
  const rs = await Promise.allSettled(comps.map(c => processosApi.objectContext(c.object_id)));
  const compContexts: Record<string, ObjectContext> = {};
  comps.forEach((c, i) => { if (rs[i].status === "fulfilled") compContexts[c.object_id] = rs[i].value; });
  const memberships = assignComponents(graphs, compContexts);
  const { summaries, unassigned } = buildStationSummaries(graphs, incR.incidents, memberships);
  let kept = summaries;
  let excludedByProject = 0;
  let attributionUnknown = false;
  if (projectId) {
    const sm = await processosApi.projectSourcemap(projectId).catch(() => null);
    const entries = sm?.source_map ?? [];
    const ids = new Set<string>(entries.map(e => String(e.semantic_object_id)));
    attributionUnknown = ids.size === 0;
    const f = filterSummariesByProject(summaries, ids);
    kept = f.kept;
    excludedByProject = f.excluded;
  }
  return {
    graphs, incidents: incR.incidents, projects: projectsR.projects, compContexts,
    summaries: kept, unassigned,
    filteredBy: projectId ?? null, excludedByProject, attributionUnknown,
  };
}

export function statusTone(status: string): "ink" | "unknown" {
  return !status || status === UNKNOWN ? "unknown" : "ink";
}
export function StatusBadge({ status }: { status: string }) {
  const known = !!status && status !== UNKNOWN;
  return <Badge tone={statusTone(status)}>{known ? status : "状态 UNKNOWN"}</Badge>;
}

/** 工位卡（无 hooks，可直接函数调用测试点击回调）。 */
export function StationCard({ summary, onOpen }: { summary: StationSummary; onOpen: (stationId: string) => void }) {
  const open = summary.openIncidents;
  return (
    <button className="pos-mc-card" data-testid="pos-mc-station" onClick={() => onOpen(summary.station.object_id)}>
      <span className="pos-mc-name">{summary.station.display_name || summary.station.object_id}</span>
      <span className="mono pos-mc-id">{summary.station.object_id}</span>
      <span className="pos-mc-meta">组件 {summary.components.length} · CM {summary.cms.length}
        {summary.components.length > summary.cms.length ? " · 部分 CM UNKNOWN" : ""}</span>
      <span className="pos-mc-badges">
        {open > 0 ? <Badge tone="err">未关闭 {open}</Badge> : <Badge tone="ok">无未关闭问题</Badge>}
        <StatusBadge status={summary.status} />
      </span>
      <span className="pos-mc-go">进入工位画布 <Icon name="arrow" size={12} /></span>
    </button>
  );
}

export function MachineCanvasView({ data, project, onSelectProject, onOpenStation }: {
  data: MachineData;
  project: string;
  onSelectProject: (pid: string) => void;
  /** 返回 (工位 object_id, 可确定的 project_id)；project_id 仅用于工位画布的影响分析预填。 */
  onOpenStation: (stationId: string, projectId?: string) => void;
}) {
  const effPid = project !== ALL_MACHINES
    ? project
    : data.projects.length === 1 ? data.projects[0].project_id : undefined;
  return (
    <>
      <div className="fc-banner info">整机画布是只读汇总：定位工位、组件与未关闭问题后下钻；不提供任何对下层物理执行元件的直接操作。</div>

      <div className="pos-canvas-toolbar">
        <label>机器（项目）
          <select value={project} aria-label="机器（项目）选择" onChange={e => onSelectProject(e.target.value)}>
            <option value={ALL_MACHINES}>全部机器（未按项目过滤）</option>
            {data.projects.map(p => (
              <option key={p.project_id} value={p.project_id}>{p.name} · {p.project_id}</option>
            ))}
          </select>
        </label>
        <span className="hint">
          {data.filteredBy ? `按 ${data.filteredBy} 过滤` : "未按项目过滤"} · 工位 {data.summaries.length}
        </span>
        {data.attributionUnknown && <Badge tone="unknown">项目归属 UNKNOWN · 该项目无已登记构建</Badge>}
        {data.filteredBy && data.excludedByProject > 0 &&
          <Badge tone="unknown">{data.excludedByProject} 个工位无法归属该项目（UNKNOWN），未显示</Badge>}
      </div>

      <div className="pos-canvas-grid">
        {data.summaries.map(s => (
          <StationCard key={s.station.object_id} summary={s} onOpen={id => onOpenStation(id, effPid)} />
        ))}
        {data.summaries.length === 0 &&
          <div className="hint">未登记任何工位（UNKNOWN）。注册工程或 POST /demo 后此处显示工位卡片。</div>}
      </div>

      {data.unassigned.length > 0 && (
        <section className="panel">
          <div className="panel-h">组件归属 UNKNOWN<span className="sp" /><span className="hint">无法从对象 context 解析所属工位，不并入任何工位卡</span></div>
          <div className="panel-b">
            <div className="pos-sc-unassigned">
              {data.unassigned.map(m => (
                <span key={m.component.object_id} className="pos-sc-io-chip" title={m.physicalPath ?? ""}>
                  {m.component.display_name || m.component.object_id}
                </span>
              ))}
            </div>
          </div>
        </section>
      )}
    </>
  );
}

export function MachineCanvas({ project = ALL_MACHINES, onSelectProject, onOpenStation, onBack, onNav }: {
  project?: string;
  onSelectProject: (pid: string) => void;
  onOpenStation: (stationId: string, projectId?: string) => void;
  onBack: () => void;
  onNav: (v: FieldView) => void;
}) {
  const [data, setData] = useState<MachineData | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setData(null); setErr("");
    loadMachineData(project === ALL_MACHINES ? undefined : project)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [project]);

  return (
    <div className="flow">
      <FieldTop view="machine" onNav={onNav} onBack={onBack} title="整机画布"
        hint="工位 · 依赖 · 资源 · 状态汇总（只读）" />
      <div className="flow-body pos-canvas">
        {err && <div className="fc-banner err">整机数据加载失败：{err}（对象与状态保持 UNKNOWN，不做猜测）</div>}
        {!data && !err && <div className="hint">正在装载四图对象与问题单…</div>}
        {data && (
          <MachineCanvasView data={data} project={project} onSelectProject={onSelectProject}
            onOpenStation={onOpenStation} />
        )}
      </div>
    </div>
  );
}
