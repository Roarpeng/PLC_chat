import { Fragment, useEffect, useState } from "react";
import { orchApi, OrchApiError, type ContractWithSchedule, type ScheduleEntry } from "./apiOrch";
import { Badge } from "./fieldui";
import type { Resource, TraceGraphs } from "./types";
import { Icon } from "./views";

/* 需求 c —— 工位编排视图（Unit 级 EM 运行步序与逻辑）。
 *
 * 结构化编排，禁止自由连线（同画布纪律）：
 *  - 顺序轨：EM 卡片横轨，上移/下移即 order（位置即步序，保存时重编号 0..n-1）；
 *  - 并行组：parallel_with 声明（无向连通分量），同组同色并排；
 *  - 资源占用：resources 多选徽章，保存时落到 operations[].resource_ids；
 *  - 冲突提示：独占资源被多 EM 占用 / 并行声明不对称 / 引用未知 EM —— 前端推导，后端仍 fail-closed。
 * 诚实边界（固定横幅）：调度只是契约层声明，当前 Unit 生成器为透传壳。 */

export interface EmCardModel {
  em: string;
  opId: string;
  opName: string;
  unit: string;
  order: number;            /* 声明序（未编排 = -1，轨位由数组位置决定） */
  resourceIds: string[];
  parallelWith: string[];
  mode: string;
  scheduled: boolean;       /* 是否来自契约 schedule 声明 */
}

export interface OrchestrationModel {
  unit: string;
  resources: Resource[];
  cards: EmCardModel[];     /* 顺序轨：schedule 按 order，未编排 EM 按契约顺序附尾 */
  duplicateOrders: number[]; /* 契约 schedule 自带的重复 order（数据异常，如实提示） */
}

export interface OrchHint { level: "err" | "warn"; text: string }

export interface OrchestrationData {
  projectId: string;
  contract: ContractWithSchedule;
  revision: number;
  graphs: TraceGraphs | null;   /* /trace/graphs 失败不阻塞编排，置 null 如实标注 */
}

/** 契约 → 顺序轨模型（纯函数）。schedule 缺失时所有 EM 按契约顺序入轨（未编排）。 */
export function buildOrchModel(contract: ContractWithSchedule): OrchestrationModel {
  const entries = contract.schedule ?? [];
  const byEm = new Map(entries.map(e => [e.em, e]));
  const duplicateOrders = entries.map(e => e.order).filter(o => entries.filter(x => x.order === o).length > 1);
  const scheduledCards: EmCardModel[] = [...entries]
    .sort((a, b) => a.order - b.order)
    .map(e => {
      const op = contract.operations.find(o => o.em === e.em);
      return {
        em: e.em, opId: op?.id ?? "", opName: op?.name ?? "", unit: op?.unit ?? contract.unit,
        order: e.order, resourceIds: [...e.resource_ids],
        parallelWith: [...(e.parallel_with ?? [])], mode: e.mode ?? "", scheduled: true,
      };
    });
  const unscheduled: EmCardModel[] = contract.operations
    .filter(o => o.em && !byEm.has(o.em))
    .map(op => ({
      em: op.em, opId: op.id, opName: op.name, unit: op.unit || contract.unit,
      order: -1, resourceIds: [...op.resource_ids], parallelWith: [], mode: "", scheduled: false,
    }));
  return {
    unit: contract.unit,
    resources: contract.resources,
    cards: [...scheduledCards, ...unscheduled],
    duplicateOrders: [...new Set(duplicateOrders)],
  };
}

/** 上移/下移（-1/+1）：交换轨位并全轨重编号（order 即位置）。越界原样返回。 */
export function moveCard(cards: EmCardModel[], em: string, dir: -1 | 1): EmCardModel[] {
  const i = cards.findIndex(c => c.em === em);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= cards.length) return cards;
  const next = [...cards];
  [next[i], next[j]] = [next[j], next[i]];
  return renumber(next);
}

function renumber(cards: EmCardModel[]): EmCardModel[] {
  return cards.map((c, i) => ({ ...c, order: i }));
}

/** 资源占用多选开关（只允许契约内资源；UI 选项即全集，无自由输入）。 */
export function toggleResource(cards: EmCardModel[], em: string, rid: string): EmCardModel[] {
  return cards.map(c => c.em !== em ? c : {
    ...c,
    resourceIds: c.resourceIds.includes(rid)
      ? c.resourceIds.filter(x => x !== rid)
      : [...c.resourceIds, rid],
  });
}

/** 「声明并行」多选开关（不与自己；对称与否由提示如实标注，不代填）。 */
export function toggleParallel(cards: EmCardModel[], em: string, other: string): EmCardModel[] {
  if (em === other) return cards;
  return cards.map(c => c.em !== em ? c : {
    ...c,
    parallelWith: c.parallelWith.includes(other)
      ? c.parallelWith.filter(x => x !== other)
      : [...c.parallelWith, other],
  });
}

/** 并行组 = parallel_with 无向连通分量；组号按组内首成员轨位排序，无组 = -1。 */
export function parallelGroups(cards: EmCardModel[]): Map<string, number> {
  const adj = new Map<string, Set<string>>();
  const ensure = (em: string) => { if (!adj.has(em)) adj.set(em, new Set()); };
  for (const c of cards) {
    ensure(c.em);
    for (const p of c.parallelWith) {
      if (!cards.some(x => x.em === p)) continue; // 未知引用交由提示，不进入着色
      ensure(p);
      adj.get(c.em)!.add(p);
      adj.get(p)!.add(c.em);
    }
  }
  const groupOf = new Map<string, number>();
  let groupId = 0;
  for (const c of cards) {
    if (groupOf.has(c.em) || (adj.get(c.em)?.size ?? 0) === 0) continue;
    const stack = [c.em];
    groupOf.set(c.em, groupId);
    while (stack.length) {
      const cur = stack.pop()!;
      for (const n of adj.get(cur) ?? []) {
        if (!groupOf.has(n)) { groupOf.set(n, groupId); stack.push(n); }
      }
    }
    groupId += 1;
  }
  for (const c of cards) if (!groupOf.has(c.em)) groupOf.set(c.em, -1);
  return groupOf;
}

/** 保存 payload：order 即轨位（0..n-1），字段形状锁定后端 SCHEDULE_ENTRY_FIELDS。 */
export function buildSchedulePayload(cards: EmCardModel[]): ScheduleEntry[] {
  return cards.map((c, i) => ({
    em: c.em,
    order: i,
    resource_ids: [...c.resourceIds],
    mode: c.mode,
    parallel_with: [...c.parallelWith],
  }));
}

/** 前端即时推导的互锁/资源冲突提示（后端构造+执行双重校验仍 fail-closed）。 */
export function orchestrationHints(model: OrchestrationModel): OrchHint[] {
  const hints: OrchHint[] = [];
  const { cards, resources } = model;
  for (const o of model.duplicateOrders)
    hints.push({ level: "err", text: `契约 schedule 存在重复 order ${o}——保存后将按轨位重编号修正。` });
  const known = new Set(cards.map(c => c.em));
  for (const c of cards) {
    for (const p of c.parallelWith) {
      if (!known.has(p))
        hints.push({ level: "err", text: `并行声明引用了未知 EM：${c.em} → ${p}（保存会被 422 拒绝）。` });
      else if (!cards.find(x => x.em === p)!.parallelWith.includes(c.em))
        hints.push({ level: "warn", text: `并行声明不对称：${c.em} → ${p} 未回指（组着色按无向处理）。` });
    }
  }
  for (const res of resources) {
    if (!res.exclusive) continue;
    const occupiers = cards.filter(c => c.resourceIds.includes(res.id));
    if (occupiers.length > 1)
      hints.push({
        level: "err",
        text: `资源独占冲突：${res.id}（exclusive）被 ${occupiers.map(c => c.em).join("、")} 同时占用。`,
      });
  }
  return hints;
}

/** 装载编排数据：契约必需；/trace/graphs 失败不阻塞（置 null 如实标注）。 */
export async function loadOrchestrationData(projectId: string): Promise<OrchestrationData> {
  const [proj, graphs] = await Promise.allSettled([
    orchApi.project(projectId), orchApi.traceGraphs(),
  ]);
  if (proj.status !== "fulfilled")
    throw proj.reason instanceof Error ? proj.reason : new Error(String(proj.reason));
  return {
    projectId,
    contract: proj.value.contract,
    revision: proj.value.revision,
    graphs: graphs.status === "fulfilled" ? graphs.value : null,
  };
}

/* ---------- 无 hooks 展示组件（可直接函数调用测试点击回调） ---------- */

function Chip({ on, onClick, children, title }: {
  on: boolean; onClick: () => void; children: React.ReactNode; title?: string;
}) {
  return (
    <button type="button" className={`pos-orch-chip mono${on ? " on" : ""}`} onClick={onClick} title={title}
      aria-pressed={on}>{children}</button>
  );
}

export function EmCard({ card, cards, index, group, resources, onUp, onDown, onToggleResource, onToggleParallel }: {
  card: EmCardModel;
  cards: EmCardModel[];
  index: number;
  group: number;
  resources: Resource[];
  onUp: (em: string) => void;
  onDown: (em: string) => void;
  onToggleResource: (em: string, rid: string) => void;
  onToggleParallel: (em: string, other: string) => void;
}) {
  const total = cards.length;
  return (
    <div className={`pos-orch-card${group >= 0 ? ` pos-orch-g${group % 4}` : ""}`} data-testid="pos-orch-card"
      data-group={group >= 0 ? `g${group}` : undefined}>
      <div className="pos-orch-card-head">
        <span className="mono pos-orch-order">#{index + 1}</span>
        <span className="pos-orch-em mono">{card.em}</span>
        {group >= 0 && <Badge tone="info" title={`并行组 G${group + 1}（parallel_with 声明）`}>并行 G{group + 1}</Badge>}
        {!card.scheduled && <Badge tone="unknown">未编排</Badge>}
        <span className="sp" />
        <button type="button" className="btn sm ghost pos-orch-move" disabled={index === 0}
          onClick={() => onUp(card.em)} title="上移（order 即位置）">上移</button>
        <button type="button" className="btn sm ghost pos-orch-move" disabled={index === total - 1}
          onClick={() => onDown(card.em)} title="下移（order 即位置）">下移</button>
      </div>
      <div className="pos-orch-card-name">{card.opName || card.em}</div>
      <div className="pos-orch-card-unit">所属工位 <span className="mono">{card.unit}</span>
        {card.opId && <span className="mono pos-orch-opid">{card.opId}</span>}</div>
      <div className="pos-orch-card-row">
        <span className="pos-orch-k">资源占用</span>
        {resources.length === 0 && <Badge tone="unknown">契约无资源（UNKNOWN）</Badge>}
        {resources.map(r => (
          <Chip key={r.id} on={card.resourceIds.includes(r.id)}
            onClick={() => onToggleResource(card.em, r.id)}
            title={`${r.id} · ${r.name}${r.exclusive ? "（exclusive 独占）" : ""}`}>{r.id}</Chip>
        ))}
      </div>
      <div className="pos-orch-card-row">
        <span className="pos-orch-k">声明并行</span>
        {total <= 1 && <Badge tone="unknown">无其他 EM</Badge>}
        {cards.filter(c => c.em !== card.em).map(c => (
          <Chip key={c.em} on={card.parallelWith.includes(c.em)}
            onClick={() => onToggleParallel(card.em, c.em)}
            title={`与 ${c.em} 并行（同组并排）`}>{c.em}</Chip>
        ))}
      </div>
    </div>
  );
}

export interface SaveState { kind: "idle" | "saving" | "ok" | "err"; revision?: number; message?: string }

/** 固定诚实边界横幅：调度只是契约层声明，Unit 生成器当前为透传壳。 */
export function OrchestrationHonestBanner() {
  return (
    <div className="fc-banner warn pos-orch-honest" role="note" data-testid="pos-orch-honest">
      调度声明已入工艺契约；当前 Unit 生成器为透传壳（真机凭证 evidence/v2/real/processos_attempt_01），跨工位调度语义暂不进入生成 SCL，生成器扩展后自动生效。
      <span className="hint">Unit FB 仅透传 Mode/State（#State := #Mode；FaultSummary := FALSE），EM 时序由 FB_EM_* 承担——本视图的 order / parallel_with / 资源占用是契约层声明与前端推导，不构成下装控制逻辑。</span>
    </div>
  );
}

export function OrchTrack({ model, graphs, saveState, onSave, onReload, onUp, onDown, onToggleResource, onToggleParallel }: {
  model: OrchestrationModel;
  graphs: TraceGraphs | null;
  saveState: SaveState;
  onSave: () => void;
  onReload: () => void;
  onUp: (em: string) => void;
  onDown: (em: string) => void;
  onToggleResource: (em: string, rid: string) => void;
  onToggleParallel: (em: string, other: string) => void;
}) {
  const hints = orchestrationHints(model);
  const groups = parallelGroups(model.cards);
  const hasErr = hints.some(h => h.level === "err");
  const afEms = graphs?.AfGraph.filter(o => o.kind === "af_em") ?? [];
  const mapped = model.cards.filter(c =>
    afEms.some(e => e.display_name === c.em || e.attributes?.em === c.em));
  return (
    <>
      <OrchestrationHonestBanner />

      <section className="pos-orch-layer">
        <div className="pos-orch-layer-h">
          <b>顺序轨 · EM 运行步序</b>
          <span className="mono pos-orch-unit">Unit {model.unit}</span>
          <span className="sp" />
          <span className="hint">上移/下移即 order（位置即步序）；并行组同色并排（无向连通分量）</span>
          {graphs
            ? <Badge tone={afEms.length > 0 ? "info" : "unknown"} title="/trace/graphs af_em 对象映射">
                图谱 EM {mapped.length}/{model.cards.length}
              </Badge>
            : <Badge tone="unknown" title="/trace/graphs 加载失败">图谱 UNKNOWN</Badge>}
        </div>
        {model.cards.length === 0 && <div className="pos-orch-empty">
          <Badge tone="unknown">契约无 operations（UNKNOWN）——先用向导/导入建立工艺契约。</Badge>
        </div>}
        <div className="pos-orch-track">
          {model.cards.map((c, i) => {
            const g = groups.get(c.em) ?? -1;
            const prev = i > 0 ? (groups.get(model.cards[i - 1].em) ?? -1) : -2;
            return (
              <Fragment key={c.em}>
                {i > 0 && <span className="pos-orch-arrow" aria-hidden title={
                  g !== -1 && g === prev ? "同并行组（并排）" : "串行步序"}>{g !== -1 && g === prev ? "∥" : "→"}</span>}
                <div className="pos-orch-cardwrap">
                  <EmCard card={c} cards={model.cards} index={i} group={g}
                    resources={model.resources}
                    onUp={onUp} onDown={onDown} onToggleResource={onToggleResource} onToggleParallel={onToggleParallel} />
                </div>
              </Fragment>
            );
          })}
        </div>
      </section>

      <section className="pos-orch-layer">
        <div className="pos-orch-layer-h"><b>互锁 / 资源冲突提示（前端推导）</b>
          <span className="sp" /><span className="hint">后端 patch 构造+执行双重校验仍 fail-closed</span></div>
        <div className="pos-orch-hints">
          {hints.length === 0 && <Badge tone="ok">无冲突提示</Badge>}
          {hints.map((h, i) => (
            <div key={i} className={`pos-orch-hint ${h.level}`}>
              {h.level === "err" ? <Icon name="warn" size={12} /> : null}{h.text}
            </div>
          ))}
        </div>
      </section>

      <section className="pos-orch-layer">
        <div className="pos-orch-layer-h"><b>保存调度</b>
          <span className="sp" />
          <span className="hint">组装 set_operation_schedule patch → 既有 POST /projects/{ "{pid}" }/patches</span>
        </div>
        <div className="pos-orch-save">
          <button type="button" className="btn sm" onClick={onSave} disabled={saveState.kind === "saving" || hasErr}>
            {saveState.kind === "saving" ? "保存中…" : "保存调度"}
          </button>
          <button type="button" className="btn sm ghost" onClick={onReload}>重新装载</button>
          {hasErr && <Badge tone="err">存在冲突，保存已禁用（修正后自动恢复）</Badge>}
          {saveState.kind === "ok" && <Badge tone="ok">{saveState.message}</Badge>}
          {saveState.kind === "err" && <div className="pos-orch-save-err" role="alert">{saveState.message}</div>}
        </div>
      </section>
    </>
  );
}

/* ---------- 视图（hooks 装载 + 保存流） ---------- */

export function OrchestrationView({ projectId, onBack }: { projectId: string; onBack: () => void }) {
  const [data, setData] = useState<OrchestrationData | null>(null);
  const [cards, setCards] = useState<EmCardModel[] | null>(null);
  const [err, setErr] = useState("");
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });

  useEffect(() => {
    let alive = true;
    setData(null); setErr(""); setSaveState({ kind: "idle" });
    loadOrchestrationData(projectId)
      .then(d => { if (alive) { setData(d); setCards(buildOrchModel(d.contract).cards); } })
      .catch(e => { if (alive) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [projectId]);

  if (err) return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onBack}><Icon name="back" /> 工艺对话</button>
        <h2>工位编排</h2>
      </div>
      <div className="flow-body">
        <div className="fc-banner err">契约装载失败：{err}（状态保持 UNKNOWN，不做猜测）。</div>
      </div>
    </div>
  );

  if (!data || !cards) return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onBack}><Icon name="back" /> 工艺对话</button>
        <h2>工位编排</h2>
      </div>
      <div className="flow-body"><div className="hint">正在装载工艺契约与调度声明…</div></div>
    </div>
  );

  const model: OrchestrationModel = {
    unit: data.contract.unit,
    resources: data.contract.resources,
    cards,
    duplicateOrders: buildOrchModel(data.contract).duplicateOrders,
  };
  const hints = orchestrationHints(model);

  const save = async () => {
    if (hints.some(h => h.level === "err")) return;
    const base = data.revision;
    setSaveState({ kind: "saving" });
    try {
      const r = await orchApi.saveSchedule(projectId, base, buildSchedulePayload(cards));
      setData({ ...data, revision: r.revision, contract: r.contract });
      setCards(buildOrchModel(r.contract).cards);
      setSaveState({ kind: "ok", revision: r.revision, message: `已保存 · revision ${base} → ${r.revision}` });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const status = e instanceof OrchApiError ? e.status : 0;
      setSaveState({
        kind: "err",
        message: status === 409
          ? `版本冲突（409）：${msg} —— 契约已被他人推进，请「重新装载」后重编。`
          : `保存被拒绝（${status || "网络错误"}）：${msg}`,
      });
    }
  };

  const reload = () => {
    setData(null); setErr(""); setSaveState({ kind: "idle" });
    loadOrchestrationData(projectId)
      .then(d => { setData(d); setCards(buildOrchModel(d.contract).cards); })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)));
  };

  return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onBack}><Icon name="back" /> 工艺对话</button>
        <h2>工位编排</h2>
        <span className="mono hint">revision {data.revision}</span>
        <span className="sp" />
        <span className="hint fieldhint">EM 运行步序 · 资源占用 · 并行组（契约层声明）</span>
      </div>
      <div className="flow-body pos-orch">
        <OrchTrack model={model} graphs={data.graphs} saveState={saveState}
          onSave={save} onReload={reload}
          onUp={em => setCards(moveCard(cards, em, -1))}
          onDown={em => setCards(moveCard(cards, em, 1))}
          onToggleResource={(em, rid) => setCards(toggleResource(cards, em, rid))}
          onToggleParallel={(em, other) => setCards(toggleParallel(cards, em, other))} />
      </div>
    </div>
  );
}
