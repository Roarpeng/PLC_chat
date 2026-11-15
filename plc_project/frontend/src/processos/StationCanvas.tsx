import { useEffect, useState } from "react";
import { processosApi } from "./api";
import {
  assignComponents, attrStr, buildCmCards, buildStepChains, isOpenIncident, UNKNOWN,
  type CmCardModel, type StationMembership, type StepChipModel,
} from "./canvasModel";
import { Badge, FieldTop, type FieldView } from "./fieldui";
import { ImpactPanel } from "./ImpactPanel";
import type { Incident, ObjectContext, ProjectSummary, TraceGraphs, TraceObject } from "./types";
import { Icon } from "./views";
import { StatusBadge } from "./MachineCanvas";

/* PLAN §3.1 工位 Canvas：CM · 逻辑步骤 · 互锁 · 状态 · 报警 · 测试。
 * 自上而下三层确定性网格（无自由连线、无拖拽坐标持久化——画布不许生成
 * 不确定控制流）；层1 CM、层2 EM/步骤、层3 资源依赖摘要。只读下钻视图。 */

export interface StationData {
  stationId: string;
  station: TraceObject | null;
  graphs: TraceGraphs;
  incidents: Incident[];
  projects: ProjectSummary[];
  memberships: StationMembership[];
  cmContexts: Record<string, ObjectContext>;
  cmCards: CmCardModel[];
  steps: StepChipModel[];
  emDisplayNames: string[];
  emResolved: boolean;
  unitName: string | null;
  sourceMapCount: number;
  openIncidentCount: number;
}

function resolveStation(graphs: TraceGraphs, idOrName: string): TraceObject | null {
  const phys = graphs.PhysicalGraph;
  return phys.find(o => o.object_id === idOrName && o.kind === "station")
    ?? phys.find(o => o.kind === "station" && (o.display_name === idOrName || (o.aliases ?? []).includes(idOrName)))
    ?? null;
}

/** 工位画布数据装载（真实代码路径，测试用 fetch mock 驱动）。 */
export async function loadStationData(stationId: string): Promise<StationData> {
  const [graphs, incR, projectsR] = await Promise.all([
    processosApi.traceGraphs(), processosApi.incidents(), processosApi.projects(),
  ]);
  const station = resolveStation(graphs, stationId);
  const comps = graphs.PhysicalGraph.filter(o => o.kind === "component");
  const rs = await Promise.allSettled(comps.map(c => processosApi.objectContext(c.object_id)));
  const compContexts: Record<string, ObjectContext> = {};
  comps.forEach((c, i) => { if (rs[i].status === "fulfilled") compContexts[c.object_id] = rs[i].value; });
  const memberships = station
    ? assignComponents(graphs, compContexts).filter(m =>
        !!m.stationName && (station.display_name === m.stationName || (station.aliases ?? []).includes(m.stationName!)))
    : [];
  const cmIds = memberships.map(m => m.cm?.object_id).filter((x): x is string => !!x);
  const cmRs = await Promise.allSettled(cmIds.map(id => processosApi.objectContext(id)));
  const cmContexts: Record<string, ObjectContext> = {};
  cmIds.forEach((id, i) => { if (cmRs[i].status === "fulfilled") cmContexts[id] = cmRs[i].value; });
  const emDisplayNames = [...new Set(
    Object.values(cmContexts).map(c => String((c.af ?? {}).em ?? "")).filter(Boolean))];
  const ems = graphs.AfGraph.filter(o => o.kind === "af_em" && emDisplayNames.includes(o.display_name));
  const emAttrs = new Set(ems.map(e => attrStr(e, "em")).filter(Boolean));
  const unitName = ems.map(e => attrStr(e, "unit")).find(Boolean) || null;
  const segsOf = (i: Incident) => String(i.physical_path_at_event ?? "").split("/").map(s => s.trim());
  const openIncidentCount = station
    ? incR.incidents.filter(i => isOpenIncident(i) &&
        (cmIds.includes(i.object_id) || segsOf(i).includes(station.display_name))).length
    : 0;
  return {
    stationId, station, graphs, incidents: incR.incidents, projects: projectsR.projects,
    memberships, cmContexts,
    cmCards: buildCmCards(memberships, cmContexts, incR.incidents),
    steps: buildStepChains(graphs, cmContexts, emAttrs, incR.incidents),
    emDisplayNames, emResolved: emAttrs.size > 0, unitName,
    sourceMapCount: Object.values(cmContexts).reduce((n, c) => n + (c.source_map?.length ?? 0), 0),
    openIncidentCount,
  };
}

/** 层1 CM 卡（无 hooks，可直接函数调用测试点击回调）。 */
export function CmCard({ card, onOpen }: { card: CmCardModel; onOpen: (objectId: string) => void }) {
  const oid = card.cm?.object_id ?? card.component.object_id;
  return (
    <button className="pos-sc-cm" data-testid="pos-sc-cm" onClick={() => onOpen(oid)}
      title="跳转现场追溯并聚焦该对象">
      <span className="pos-sc-cm-head">
        <span className="pos-sc-cm-name">{card.component.display_name || card.component.object_id}</span>
        <StatusBadge status={card.status} />
      </span>
      <span className="mono pos-sc-cm-id">{oid}</span>
      {card.cm ? (
        <span className="pos-sc-cm-io">
          <span className="pos-sc-io-row">
            <span className="pos-sc-io-k">驱动契约</span>
            <span className="mono">{card.driverContract ?? UNKNOWN}</span>
          </span>
          <span className="pos-sc-io-row">
            <span className="pos-sc-io-k">命令</span>
            {card.commands?.map(c => <span className="pos-sc-io-chip cmd mono" key={c}>{c}</span>)
              ?? <Badge tone="unknown">命令 UNKNOWN</Badge>}
          </span>
          <span className="pos-sc-io-row">
            <span className="pos-sc-io-k">反馈</span>
            {card.feedback?.map(f => <span className="pos-sc-io-chip fb mono" key={f}>{f}</span>)
              ?? <Badge tone="unknown">反馈 UNKNOWN</Badge>}
          </span>
        </span>
      ) : (
        <Badge tone="unknown">驱动契约 UNKNOWN（无匹配 af_cm）</Badge>
      )}
      <span className="pos-sc-cm-badges">
        {card.alarms.map(a => <Badge key={a.definition_id} tone="warn" title={a.description}>{a.code}</Badge>)}
        {card.openIncidents > 0 ? <Badge tone="err">未关闭 {card.openIncidents}</Badge>
          : <Badge tone="ok">无未关闭</Badge>}
      </span>
      <span className="pos-sc-cm-go">追溯该对象 <Icon name="arrow" size={12} /></span>
    </button>
  );
}

/** 层2 步骤链节点（无 hooks；展开态由父组件控制）。 */
export function StepChip({ model, open, onToggle }: {
  model: StepChipModel; open: boolean; onToggle: (stepObjectId: string) => void;
}) {
  const m = model;
  return (
    <div className={`pos-sc-step${m.isFault ? " fault" : ""}${open ? " on" : ""}`} data-testid="pos-sc-step">
      <button className="pos-sc-step-btn" onClick={() => onToggle(m.step.object_id)}
        title={m.guard ? `转移/联锁条件：${m.guard}` : m.step.display_name}>
        <span className="pos-sc-step-name">{m.step.display_name || attrStr(m.step, "step") || m.step.object_id}</span>
        <span className="pos-sc-step-meta">
          {m.timeoutMs !== null && m.timeoutMs > 0 && <span className="pos-sc-step-to mono">timeout {m.timeoutMs}ms</span>}
          {m.guard && <span className="pos-sc-step-guard mono"><Icon name="warn" size={11} />{m.guard}</span>}
          {m.isFault && <Badge tone="err">故障步</Badge>}
        </span>
      </button>
      {open && (
        <div className="pos-sc-step-x">
          {m.expected || m.observed ? (
            <>
              <div className="beh-row"><span className="beh-k ok">期望</span><span>{m.expected ?? UNKNOWN}</span></div>
              <div className="beh-row"><span className="beh-k err">观测</span><span>{m.observed ?? UNKNOWN}</span></div>
            </>
          ) : <Badge tone="unknown">无期望/观测记录（UNKNOWN）</Badge>}
        </div>
      )}
    </div>
  );
}

function ResRow({ k, children }: { k: string; children: React.ReactNode }) {
  return <div className="pos-sc-res-row"><span className="pos-sc-res-k">{k}</span><span>{children}</span></div>;
}

export function StationCanvasView({ data, projectId, onBackToMachine, onOpenObject }: {
  data: StationData;
  projectId?: string;
  onBackToMachine: () => void;
  onOpenObject: (objectId: string) => void;
}) {
  const [openStep, setOpenStep] = useState<string | null>(null);
  const st = data.station;
  const firstCmId = data.cmCards.find(c => c.cm)?.cm?.object_id
    ?? data.cmCards[0]?.component.object_id ?? "";
  const driverKinds = [...new Set(data.cmCards.map(c => c.driverContract).filter((x): x is string => !!x))];
  const emText = data.emResolved ? data.emDisplayNames.join(" · ") : null;
  /* 影响分析项目：显式选中项目 → 单一项目自动补全；否则 UNKNOWN 交由后端 404 如实反馈。 */
  const impactPid = projectId ?? (data.projects.length === 1 ? data.projects[0].project_id : undefined);
  return (
    <>
      <nav className="pos-crumb" aria-label="画布导航">
        <button className="btn sm ghost" onClick={onBackToMachine}><Icon name="back" size={12} /> 整机画布</button>
        <span className="pos-crumb-sep">/</span>
        <span className="pos-crumb-cur">{st ? st.display_name || st.object_id : "未知工位"}</span>
        <span className="mono pos-crumb-id">{st?.object_id ?? UNKNOWN}</span>
      </nav>

      {!st && <div className="fc-banner warn">未找到所选工位对象（UNKNOWN）——请从整机画布或现场入口重新定位，不做猜测。</div>}

      {st && <>
        <div className="fc-banner info">工位画布为只读分层视图：CM 驱动契约、行为步骤与资源依赖；不能在此连线或生成任何控制流。</div>

        <section className="pos-sc-layer">
          <div className="pos-sc-layer-h"><b>层 1 · 组件 / CM</b>
            <span className="sp" />
            <span className="hint">点击卡片跳转现场追溯并聚焦该对象</span>
          </div>
          <div className="pos-sc-cmrow">
            {data.cmCards.map(c => <CmCard key={c.component.object_id} card={c} onOpen={onOpenObject} />)}
            {data.cmCards.length === 0 && <Badge tone="unknown">该工位无组件记录（UNKNOWN）</Badge>}
          </div>
        </section>

        <section className="pos-sc-layer">
          <div className="pos-sc-layer-h"><b>层 2 · EM / 步骤序列</b>
            <span className="sp" />
            {emText
              ? <span className="hint">EM：{emText}{data.unitName ? ` · Unit ${data.unitName}` : ""}</span>
              : <Badge tone="unknown">EM UNKNOWN（context 未解析出 EM 归属）</Badge>}
          </div>
          <div className="pos-sc-seq">
            {data.steps.map(m => (
              <StepChip key={m.step.object_id} model={m} open={openStep === m.step.object_id}
                onToggle={id => setOpenStep(openStep === id ? null : id)} />
            ))}
            {data.steps.length === 0 && <Badge tone="unknown">步骤 UNKNOWN（context 与 graphs 均未解析出步骤）</Badge>}
          </div>
        </section>

        <section className="pos-sc-layer">
          <div className="pos-sc-layer-h"><b>层 3 · 资源 / 依赖摘要</b>
            <span className="sp" />
            <span className="hint">工位内部资源与跨层依赖，均为只读汇总</span>
          </div>
          <div className="pos-sc-res">
            <ResRow k="组件 / CM">组件 {data.memberships.length} · CM {data.cmCards.filter(c => c.cm).length}
              {data.cmCards.some(c => !c.cm) ? " · 部分 CM UNKNOWN" : ""}</ResRow>
            <ResRow k="Unit / EM">
              {data.unitName ? <span className="mono">{data.unitName}</span> : <Badge tone="unknown">Unit UNKNOWN</Badge>}
              <span className="af-arr"> → </span>
              {emText ? <span className="mono">{emText}</span> : <Badge tone="unknown">EM UNKNOWN</Badge>}
            </ResRow>
            <ResRow k="驱动契约">{driverKinds.length > 0
              ? driverKinds.map(k => <span className="pos-sc-io-chip mono" key={k}>{k}</span>)
              : <Badge tone="unknown">驱动契约 UNKNOWN</Badge>}</ResRow>
            <ResRow k="源码映射">{data.sourceMapCount > 0 ? `${data.sourceMapCount} 条（按对象解析）`
              : <Badge tone="unknown">无映射（UNKNOWN）</Badge>}</ResRow>
            <ResRow k="未关闭问题">{data.openIncidentCount > 0
              ? <Badge tone="err">{data.openIncidentCount}</Badge> : <Badge tone="ok">0</Badge>}</ResRow>
          </div>
        </section>

        <details className="fc-fold">
          <summary><Icon name="doc" size={13} /> 影响分析（FC-05 · 预填该工位首个 CM）</summary>
          <div className="fc-fold-body">
            <ImpactPanel projectId={impactPid} objectId={firstCmId} />
          </div>
        </details>
      </>}
    </>
  );
}

export function StationCanvas({ stationId, projectId, onBack, onNav, onBackToMachine, onOpenObject }: {
  stationId: string;
  projectId?: string;
  onBack: () => void;
  onNav: (v: FieldView) => void;
  onBackToMachine: () => void;
  onOpenObject: (objectId: string) => void;
}) {
  const [data, setData] = useState<StationData | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!stationId) { setData(null); return; }
    let alive = true;
    setData(null); setErr("");
    loadStationData(stationId)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [stationId]);

  return (
    <div className="flow">
      <FieldTop view="station" onNav={onNav} onBack={onBack} title="工位画布"
        hint="CM · 逻辑步骤 · 互锁 · 状态 · 报警（只读分层）" />
      <div className="flow-body pos-canvas">
        {!stationId && <div className="fc-banner warn">未选择工位（UNKNOWN）——请从整机画布选择工位后进入。</div>}
        {err && <div className="fc-banner err">工位数据加载失败：{err}（对象与状态保持 UNKNOWN，不做猜测）</div>}
        {!data && stationId && !err && <div className="hint">正在装载工位对象、CM 契约与行为步骤…</div>}
        {data && (
          <StationCanvasView data={data} projectId={projectId}
            onBackToMachine={onBackToMachine} onOpenObject={onOpenObject} />
        )}
      </div>
    </div>
  );
}
