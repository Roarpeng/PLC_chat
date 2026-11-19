import { useId } from 'react';
import type { ProjectCompoundEdge, ProjectCompoundStation, ProjectHyperGraph, SelectedHyperEntity } from '../../core/ir/afHyperGraph.types';

export function groupProjectRelations(graph: ProjectHyperGraph) {
  const stations = new Map(graph.stations.map((station) => [station.id, station]));
  const pairs = new Map<string, { a: ProjectCompoundStation; b: ProjectCompoundStation; edges: ProjectCompoundEdge[] }>();
  for (const edge of graph.edges) {
    const [aId, bId] = [edge.fromNode, edge.toNode].sort();
    const a = stations.get(aId);
    const b = stations.get(bId);
    if (!a || !b) continue;
    const key = JSON.stringify([aId, bId]);
    const pair = pairs.get(key) ?? { a, b, edges: [] };
    pair.edges.push(edge);
    pairs.set(key, pair);
  }
  return [...pairs.values()];
}

export function visibleProjectRelations(graph: ProjectHyperGraph, selected: SelectedHyperEntity, all: boolean) {
  if (all) return graph.edges;
  if (selected?.kind === 'STATION') {
    return graph.edges.filter(({ fromNode, toNode }) => fromNode === selected.id || toNode === selected.id);
  }
  if (selected?.kind === 'L1_EDGE') {
    const edge = graph.edges.find(({ id }) => id === selected.id);
    return edge ? graph.edges.filter(({ fromNode, toNode }) =>
      (fromNode === edge.fromNode && toNode === edge.toNode) || (fromNode === edge.toNode && toNode === edge.fromNode)) : [];
  }
  return [];
}

interface StationBox { x: number; y: number; width: number; height: number }

function relationCurve(source: StationBox, target: StationBox, lane: number, self: boolean) {
  const x = source.x + source.width / 2;
  const y = source.y + source.height / 2;
  const tx = target.x + target.width / 2;
  const ty = target.y + target.height / 2;
  if (self) {
    const right = source.x + source.width;
    const reach = 48 + Math.abs(lane);
    return { d: `M ${right + 3} ${y - 12} C ${right + reach} ${y - 50}, ${right + reach} ${y + 50}, ${right + 3} ${y + 12}`, x: right + reach, y };
  }
  const horizontalGap = Math.abs(tx - x) - (source.width + target.width) / 2;
  const verticalGap = Math.abs(ty - y) - (source.height + target.height) / 2;
  const horizontal = horizontalGap >= verticalGap;
  const direction = Math.sign(horizontal ? tx - x : ty - y) || 1;
  const gap = Math.min(76, Math.max(10, (horizontal ? horizontalGap : verticalGap) * 0.4));
  const shift = Math.max(-45, Math.min(45, lane));
  if (horizontal) {
    const start = x + direction * (source.width / 2 + 3);
    const end = tx - direction * (target.width / 2 + 4);
    return { d: `M ${start} ${y + shift} C ${start + direction * gap} ${y + shift}, ${end - direction * gap} ${ty + shift}, ${end} ${ty + shift}`, x: (start + end) / 2, y: (y + ty) / 2 + shift };
  }
  const start = y + direction * (source.height / 2 + 3);
  const end = ty - direction * (target.height / 2 + 4);
  return { d: `M ${x + shift} ${start} C ${x + shift} ${start + direction * gap}, ${tx + shift} ${end - direction * gap}, ${tx + shift} ${end}`, x: (x + tx) / 2 + shift, y: (start + end) / 2 };
}

export function ProjectRelationsLayer({ graph, heights, edges, expanded }: {
  graph: ProjectHyperGraph;
  heights: ReadonlyMap<string, number>;
  edges: ProjectCompoundEdge[];
  expanded: boolean;
}) {
  const marker = `af5-project-arrow-${useId().replace(/[^a-z0-9_-]/gi, '')}`;
  const visible = new Set(edges.map(({ id }) => id));
  const box = (station: ProjectCompoundStation): StationBox =>
    ({ ...station.position, width: 264, height: heights.get(station.id) ?? 138 });
  return (
    <svg className="af5-svg-layer af5-project-relations" aria-hidden="true">
      <defs>
        <marker id={marker} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 Z" />
        </marker>
      </defs>
      {groupProjectRelations(graph).map(({ a, b, edges: pairEdges }) => {
        const active = pairEdges.filter(({ id }) => visible.has(id));
        const overviewCurve = relationCurve(box(a), box(b), 0, a.id === b.id);
        const jobExchange = !expanded && a.kind === 'LOGIC' && b.kind === 'LOGIC' &&
          pairEdges.some(({ label }) => label.includes('作业信息'));
        const bidirectional = pairEdges.some(({ fromNode }) => fromNode === a.id) &&
          pairEdges.some(({ fromNode }) => fromNode === b.id) && a.id !== b.id;
        if (active.length) return (
          <g key={JSON.stringify([a.id, b.id])}>
            {active.map((edge, index) => {
              const forward = edge.fromNode === a.id;
              const path = relationCurve(box(forward ? a : b), box(forward ? b : a),
                (index - (active.length - 1) / 2) * 18, a.id === b.id);
              return <path key={edge.id} data-project-edge={edge.id} d={path.d}
                className={`af5-relation-curve is-expanded ${edge.kind === 'GUARD' ? 'is-guard' : ''}`}
                markerEnd={`url(#${marker})`} />;
            })}
          </g>
        );
        return (
          <g key={JSON.stringify([a.id, b.id])} data-project-relation="summary">
            <path d={overviewCurve.d} className={`af5-relation-curve ${expanded ? 'is-context' : ''} ${jobExchange ? 'is-job-exchange' : ''}`}
              markerStart={jobExchange && bidirectional ? `url(#${marker})` : undefined}
              markerEnd={jobExchange ? `url(#${marker})` : undefined} />
            {jobExchange && <g transform={`translate(${overviewCurve.x} ${overviewCurve.y})`} className="af5-relation-summary-label">
              <rect x={-34} y={-10} width={68} height={20} rx={2} />
              <text textAnchor="middle" dominantBaseline="central">作业信息</text>
            </g>}
          </g>
        );
      })}
    </svg>
  );
}

export function ProjectRelationDetails({ graph, edges, selected, all, onSelect }: {
  graph: ProjectHyperGraph;
  edges: ProjectCompoundEdge[];
  selected: SelectedHyperEntity;
  all: boolean;
  onSelect: (entity: SelectedHyperEntity) => void;
}) {
  const names = new Map(graph.stations.map(({ id, title }) => [id, title]));
  const title = all ? '全部关系' : selected?.kind === 'STATION' ? `${names.get(selected.id)} · 相关关系` : '所选关系';
  return <section className="af5-relation-details" aria-label={title}>
    <header><strong>{title}</strong><span>{edges.length} 条</span></header>
    {edges.length ? <ul>{edges.map((edge) => {
      const content = <><span className="af5-relation-endpoints">{names.get(edge.fromNode)} <span aria-hidden="true">→</span> {names.get(edge.toNode)}</span><span className="af5-relation-name">{edge.label}</span></>;
      return <li key={edge.id}>
        {edge.managedByOrchestration ? <span className="af5-relation-row">{content}</span> :
          <button type="button" className="af5-relation-row" aria-pressed={selected?.kind === 'L1_EDGE' && selected.id === edge.id}
            onClick={() => onSelect({ kind: 'L1_EDGE', id: edge.id })}>{content}</button>}
      </li>;
    })}</ul> : <p>该工位暂无跨工位关系。</p>}
  </section>;
}
