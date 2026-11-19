import { describe, expect, it } from 'vitest';
import { compileStationHyperGraph } from '../compiler/multiTargetSclGen';
import { createDefaultAfStudioWorkspace } from './seedHyperGraphs';
import { advanceOrchestration, initialOrchestrationRun, type OrchestrationEvent } from './stationOrchestration';
import type { StationOrchestration } from './afHyperGraph.types';
import { cloneStationGraph, stationHasUnboundSignals } from './stationWorkspace';

describe('station copy', () => {
  it('clones local topology and step logic while requiring field signal rebinding', () => {
    const source = createDefaultAfStudioWorkspace().stationGraphs.ST20;
    const invocation = source.temporalSteps[0].invocations[0];
    invocation.waitPredicateScl = `%I10.4 AND #${invocation.targetNodeId}.o_bDone`;
    const copy = cloneStationGraph(source, 'ST60', '独立副本');
    const oldIds = new Set(source.spatialNodes.map((node) => node.id));
    const ids = new Set(copy.spatialNodes.map((node) => node.id));
    expect(copy.spatialNodes).toHaveLength(source.spatialNodes.length);
    expect(copy.spatialNodes.every((node) => !oldIds.has(node.id))).toBe(true);
    expect(copy.guardEdges).toHaveLength(source.guardEdges.filter((edge) => !edge.crossStationRef).length);
    expect(copy.guardEdges.every((edge) => ids.has(edge.fromNode) && ids.has(edge.toNode))).toBe(true);
    expect(copy.temporalSteps).toHaveLength(source.temporalSteps.length);
    const copiedInvocation = copy.temporalSteps[0].invocations[0];
    expect(copiedInvocation.waitPredicateScl).toBe(`__REBIND_IO__ AND #${copiedInvocation.targetNodeId}.o_bDone`);
    expect(stationHasUnboundSignals(copy)).toBe(true);
    expect(() => compileStationHyperGraph(copy)).toThrow('待绑定');
    expect(invocation.waitPredicateScl).toContain('%I10.4');
  });
});

describe('orchestration handshake', () => {
  const plan: StationOrchestration = {
    initialTool: 'A',
    operations: [{ stationId: 'WORK', command: '作业', allowInterrupt: true }],
    interrupt: { stationId: 'ATTACH', command: '更换附件' },
  };
  const run = (...events: OrchestrationEvent[]) => events.reduce(
    (state, event) => advanceOrchestration(plan, state, event),
    initialOrchestrationRun(plan),
  );

  it('resumes the same operation and tool only after all handshake acknowledgements', () => {
    const requests = ['start', 'ready', 'request-on', 'done'] as const;
    expect(run(...requests)).toMatchObject({ phase: 'pause', tool: 'A', operationIndex: 0 });
    const resumed = run(...requests, 'paused', 'ready', 'done', 'returned', 'resumed', 'request-on');
    expect(resumed).toMatchObject({ phase: 'running', tool: 'A', operationIndex: 0 });
    expect(advanceOrchestration(plan, resumed, 'done').phase).toBe('done');
  });

  it('locks the paused operation on fault', () => {
    expect(run('start', 'ready', 'request-on', 'paused', 'fault', 'ready', 'returned', 'resumed'))
      .toMatchObject({ phase: 'fault', tool: 'A', operationIndex: 0 });
  });
});
