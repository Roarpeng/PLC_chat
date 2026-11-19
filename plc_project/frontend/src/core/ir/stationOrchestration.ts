import type { ProjectCompoundStation, StationOrchestration } from './afHyperGraph.types';

type Phase = 'idle' | 'ready' | 'running' | 'pause' | 'change-ready' | 'changing' | 'return' | 'resume' | 'done' | 'fault';
export type OrchestrationEvent = 'start' | 'ready' | 'done' | 'request-on' | 'request-off' | 'paused' | 'returned' | 'resumed' | 'fault' | 'reset';

export interface OrchestrationRun {
  phase: Phase;
  operationIndex: number;
  tool: string;
  request: boolean;
}

export function initialOrchestrationRun(plan: StationOrchestration): OrchestrationRun {
  return { phase: 'idle', operationIndex: 0, tool: plan.initialTool, request: false };
}

export function isOrchestrationBound(plan: StationOrchestration, stations: ProjectCompoundStation[]): boolean {
  const physicalIds = new Set(stations.filter((station) => station.kind !== 'LOGIC').map(({ stationId }) => stationId));
  const isBound = (operation: { stationId: string; command: string }) =>
    physicalIds.has(operation.stationId) && Boolean(operation.command.trim());
  return plan.operations.length > 0 && plan.operations.every(isBound) &&
    plan.operations.every(({ mountedToolAfter }) => mountedToolAfter == null || Boolean(mountedToolAfter.trim())) &&
    (!plan.interrupt || isBound(plan.interrupt)) &&
    (!plan.operations.some((operation) => operation.allowInterrupt) || Boolean(plan.interrupt));
}

export function advanceOrchestration(
  plan: StationOrchestration,
  run: OrchestrationRun,
  event: OrchestrationEvent,
): OrchestrationRun {
  const operation = plan.operations[run.operationIndex];
  if (event === 'reset') return initialOrchestrationRun(plan);
  if (event === 'request-off') return { ...run, request: false };
  if (event === 'request-on') {
    if (run.request) return run;
    const canPause = run.phase === 'running' && operation?.allowInterrupt && plan.interrupt && run.tool;
    return { ...run, request: true, phase: canPause ? 'pause' : run.phase };
  }
  if (run.phase === 'idle') {
    return event === 'start' && operation ? { ...run, phase: 'ready' } : run;
  }
  if (run.phase === 'done' || run.phase === 'fault') return run;
  if (event === 'fault') return { ...run, phase: 'fault' };

  switch (run.phase) {
    case 'ready':
      return event === 'ready' ? { ...run, phase: 'running' } : run;
    case 'running': {
      if (event !== 'done' || !operation) return run;
      const operationIndex = run.operationIndex + 1;
      return {
        ...run, operationIndex,
        tool: operation.mountedToolAfter === undefined ? run.tool : operation.mountedToolAfter?.trim() ?? '',
        phase: operationIndex < plan.operations.length ? 'ready' : 'done',
      };
    }
    case 'pause':
      return event === 'paused' ? { ...run, phase: 'change-ready' } : run;
    case 'change-ready':
      return event === 'ready' ? { ...run, phase: 'changing' } : run;
    case 'changing':
      return event === 'done' ? { ...run, phase: 'return' } : run;
    case 'return':
      return event === 'returned' ? { ...run, phase: 'resume' } : run;
    case 'resume':
      return event === 'resumed' ? { ...run, phase: 'running' } : run;
  }
}

export const orchestrationPhaseLabels: Record<Phase, string> = {
  idle: '待机',
  ready: '等待工位就绪',
  running: '等待操作完成',
  pause: '等待安全暂停确认',
  'change-ready': '等待附件位就绪',
  changing: '等待附件更换完成',
  return: '等待返回原作业位置',
  resume: '等待原工步恢复',
  done: '流程完成',
  fault: '故障锁定',
};
