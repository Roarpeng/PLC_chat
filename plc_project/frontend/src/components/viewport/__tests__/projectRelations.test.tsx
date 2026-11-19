import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ProjectCompoundEdge, ProjectCompoundStation, ProjectHyperGraph } from '../../../core/ir/afHyperGraph.types';
import { groupProjectRelations, ProjectRelationsLayer, visibleProjectRelations } from '../ProjectRelations';

const station = (id: string, x: number, kind: ProjectCompoundStation['kind']): ProjectCompoundStation => ({
  id, stationId: id, title: id, kind, position: { x, y: 90 },
  isPinned: false, instanceSummaries: [], inPorts: [], outPorts: [],
});
const edge = (id: string, fromNode: string, toNode: string, label: string): ProjectCompoundEdge => ({
  id, fromNode, toNode, label, fromPort: 'out', toPort: 'in', kind: 'SEQ',
});
const graph: ProjectHyperGraph = {
  stations: [station('host', 20, 'LOGIC'), station('robot', 400, 'LOGIC'), station('attach', 800, 'PHYSICAL')],
  edges: [
    edge('job', 'host', 'robot', '下发作业信息'),
    edge('request', 'robot', 'host', '读取下一项'),
    edge('change', 'robot', 'attach', '请求更换附件'),
    edge('done', 'attach', 'robot', '更换完成'),
  ],
};

describe('project relation overview and focus', () => {
  it('summarizes reciprocal signals without changing their identity', () => {
    expect(groupProjectRelations(graph).map(({ edges }) => edges.length)).toEqual([2, 2]);
    const markup = renderToStaticMarkup(<ProjectRelationsLayer graph={graph} heights={new Map()} edges={[]} expanded={false} />);
    expect(markup.match(/data-project-relation="summary"/g)).toHaveLength(2);
    expect(markup).toContain('作业信息');
    expect(markup).not.toContain('请求更换附件');
    expect(markup).toContain('marker-start');
  });

  it('expands only the chosen station or pair and exposes all directions on demand', () => {
    const focus = visibleProjectRelations(graph, { kind: 'STATION', id: 'attach' }, false);
    expect(focus.map(({ id }) => id)).toEqual(['change', 'done']);
    const markup = renderToStaticMarkup(<ProjectRelationsLayer graph={graph} heights={new Map()} edges={focus} expanded />);
    expect(markup.match(/data-project-edge=/g)).toHaveLength(2);
    expect(visibleProjectRelations(graph, { kind: 'L1_EDGE', id: 'done' }, false)).toEqual(focus);
    expect(visibleProjectRelations(graph, null, true)).toEqual(graph.edges);
  });
});
