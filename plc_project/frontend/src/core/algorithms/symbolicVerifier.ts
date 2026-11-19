import type {
  GhostGraphTransaction,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
  VerificationReport,
  VerifierViolation,
} from '../ir/afHyperGraph.types';
import { detectActuatorGuardCycles } from './autoHomingSynth';

function nowMs(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now();
  }
  return Date.now();
}

function mergeById<T extends { id: string }>(base: T[], added?: T[]): T[] {
  if (!added || added.length === 0) return [...base];
  const merged = [...base];
  const indexById = new Map<string, number>();
  merged.forEach((item, idx) => indexById.set(item.id, idx));

  for (const item of added) {
    const existingIdx = indexById.get(item.id);
    if (existingIdx !== undefined) {
      merged[existingIdx] = item;
    } else {
      indexById.set(item.id, merged.length);
      merged.push(item);
    }
  }
  return merged;
}

function allocateNextDiagCodeHex(existingCodes: Set<string>): string {
  let candidate = 0x0201;
  while (true) {
    const hex = `16#${candidate.toString(16).padStart(4, '0').toUpperCase()}`;
    if (!existingCodes.has(hex)) {
      existingCodes.add(hex);
      return hex;
    }
    candidate += 1;
  }
}

function allocateGuardId(
  srcId: string,
  targetId: string,
  existingIds: Set<string>
): string {
  const baseId = `G_FIX_${srcId}_TO_${targetId}`;
  if (!existingIds.has(baseId)) {
    existingIds.add(baseId);
    return baseId;
  }
  let suffix = 2;
  while (existingIds.has(`${baseId}_${suffix}`)) {
    suffix += 1;
  }
  const uniqueId = `${baseId}_${suffix}`;
  existingIds.add(uniqueId);
  return uniqueId;
}

function serializeState(
  sortedNodeIds: string[],
  state: Map<string, string>
): string {
  return sortedNodeIds.map((id) => state.get(id) ?? '').join('\u0001');
}

function cloneState(state: Map<string, string>): Map<string, string> {
  return new Map(state);
}

function checkStepContention(
  steps: TemporalStepHyperEdge[],
  violations: VerifierViolation[]
): void {
  for (const step of steps) {
    const targetStates = new Map<string, Set<string>>();
    for (const inv of step.invocations) {
      let states = targetStates.get(inv.targetNodeId);
      if (!states) {
        states = new Set<string>();
        targetStates.set(inv.targetNodeId, states);
      }
      states.add(inv.targetDiscreteState);
    }

    for (const [nodeId, states] of targetStates.entries()) {
      if (states.size > 1) {
        violations.push({
          kind: 'ACTUATOR_CONTENTION',
          stepNo: step.stepNo,
          nodeId,
          message: `并发资源竞争: 工步 S${step.stepNo} (${step.title}) 对同一实例 "${nodeId}" 同时下发了冲突目标状态 (${Array.from(states).join(' vs ')})。`,
        });
      }
    }
  }
}

function buildSuggestedGuardEdge(
  srcNode: SpatialInstanceNode,
  axisNode: SpatialInstanceNode,
  usedDiagCodes: Set<string>,
  usedGuardIds: Set<string>
): SafetyGuardEdge {
  const fromPort =
    srcNode.outPorts.find((p) => p.type === 'GUARD')?.id ?? 'OUT_AT_HOME';
  const toPort =
    axisNode.inPorts.find((p) => p.type === 'GUARD')?.id ?? 'IN_GUARD';
  const diagCodeHex = allocateNextDiagCodeHex(usedDiagCodes);

  return {
    id: allocateGuardId(srcNode.id, axisNode.id, usedGuardIds),
    fromNode: srcNode.id,
    fromPort,
    toNode: axisNode.id,
    toPort,
    requiredSourceState: srcNode.initialHomeState,
    diagCodeHex,
    humanDescription: `${srcNode.title}处于安全原位 (${srcNode.initialHomeState}) 才允许${axisNode.title}移动`,
    isHealthy: true,
  };
}

/**
 * 算法二：离散状态空间 BFS 碰撞、竞争与护栏静态验证器（纯同步，典型工站耗时 < 5ms）。
 * 支持合并神经符号 GhostGraphTransaction 进行事务前只读验证（不修改任何入参对象）。
 */
export function verifyStationHyperGraph(
  station: StationHyperGraph,
  ghostTx?: GhostGraphTransaction | null
): VerificationReport {
  const tStart = nowMs();

  const spatialNodes = mergeById(station.spatialNodes, ghostTx?.addedNodes);
  const guardEdges = mergeById(station.guardEdges, ghostTx?.addedGuardEdges);
  const temporalSteps = mergeById(station.temporalSteps, ghostTx?.addedTemporalSteps).sort(
    (a, b) => a.stepNo - b.stepNo
  );

  const violations: VerifierViolation[] = [];
  const warnings: string[] = [];

  // 1. 并发资源竞争检查 (ACTUATOR_CONTENTION)
  checkStepContention(temporalSteps, violations);

  // 2. 护栏死锁环检查 (GUARD_CYCLE_DEADLOCK)
  const cycleReport = detectActuatorGuardCycles(spatialNodes, guardEdges, true);
  for (const scc of cycleReport.sccs) {
    violations.push({
      kind: 'GUARD_CYCLE_DEADLOCK',
      nodeId: scc.nodeIds[0],
      interferingNodeId: scc.nodeIds[1] ?? scc.nodeIds[0],
      message: `护栏死锁环路: 护栏边 [${scc.edgeIds.join(', ')}] 在执行器 [${scc.nodeIds.join(' <-> ')}] 之间构成强连通死锁环。`,
    });
  }

  // 构建索引与初始离散状态向量 s_0 = { nodeId -> initialHomeState }
  const nodeById = new Map<string, SpatialInstanceNode>();
  const sortedNodeIds: string[] = [];
  const initialState = new Map<string, string>();
  const verticalActuators: SpatialInstanceNode[] = [];
  const boundaryInIds = new Set<string>();

  for (const node of spatialNodes) {
    nodeById.set(node.id, node);
    sortedNodeIds.push(node.id);
    initialState.set(node.id, node.initialHomeState);
    if (node.driverClass === 'FB_AF_Actuator2Pos') {
      verticalActuators.push(node);
    }
    if (node.role === 'BOUNDARY_IN') {
      boundaryInIds.add(node.id);
    }
  }
  sortedNodeIds.sort();

  for (const g of guardEdges) {
    if (!nodeById.has(g.fromNode) || !nodeById.has(g.toNode)) {
      warnings.push(
        `护栏边 ${g.id} 引用了不存在的空间节点 (${g.fromNode} -> ${g.toNode})。`
      );
    }
  }

  const usedDiagCodes = new Set(
    guardEdges.map((g) => g.diagCodeHex.trim().toUpperCase()).filter(Boolean)
  );
  const usedGuardIds = new Set(guardEdges.map((g) => g.id));

  const missingGuardPairs = new Set<string>();
  const collisionKeys = new Set<string>();
  const visitedStepIds = new Set<string>();
  const uniqueStateKeys = new Set<string>();
  uniqueStateKeys.add(serializeState(sortedNodeIds, initialState));

  // 3. 确定 BFS 入口步序
  let entrySteps: TemporalStepHyperEdge[] = [];
  if (temporalSteps.length > 0) {
    if (boundaryInIds.size > 0) {
      entrySteps = temporalSteps.filter((s) => boundaryInIds.has(s.fromNode));
    } else {
      const validFromSteps = temporalSteps.filter((s) => nodeById.has(s.fromNode));
      if (validFromSteps.length > 0) {
        const minStepNo = validFromSteps[0].stepNo;
        entrySteps = validFromSteps.filter((s) => s.stepNo === minStepNo);
      }
    }
  }

  // 4. 沿 temporalSteps 进行离散状态空间 BFS
  interface BfsItem {
    step: TemporalStepHyperEdge;
    state: Map<string, string>;
  }

  const queue: BfsItem[] = [];
  const visitedQueueKeys = new Set<string>();

  for (const entry of entrySteps) {
    const stateKey = serializeState(sortedNodeIds, initialState);
    const qKey = `${entry.id}::${stateKey}`;
    if (!visitedQueueKeys.has(qKey)) {
      visitedQueueKeys.add(qKey);
      queue.push({ step: entry, state: cloneState(initialState) });
    }
  }

  const MAX_BFS_ITERATIONS = 10000;
  let cursor = 0;

  while (cursor < queue.length && cursor < MAX_BFS_ITERATIONS) {
    const { step, state } = queue[cursor++];
    visitedStepIds.add(step.id);

    for (const inv of step.invocations) {
      const targetNode = nodeById.get(inv.targetNodeId);
      if (!targetNode) {
        warnings.push(
          `工步 S${step.stepNo} (${step.title}) 引用了不存在的目标节点 "${inv.targetNodeId}"。`
        );
        continue;
      }

      if (targetNode.driverClass === 'FB_AF_AxisMotion') {
        const currentAxisState = state.get(targetNode.id) ?? targetNode.initialHomeState;
        const movesToNonHomeOrCrossPos =
          inv.targetDiscreteState !== targetNode.initialHomeState ||
          (currentAxisState !== targetNode.initialHomeState &&
            inv.targetDiscreteState !== currentAxisState);

        if (movesToNonHomeOrCrossPos) {
          const constraintMap = new Map<string, SpatialInstanceNode>();
          for (const vAct of verticalActuators) {
            if (vAct.id !== targetNode.id) {
              constraintMap.set(vAct.id, vAct);
            }
          }
          for (const reqId of step.requiresGuardNodeIds ?? []) {
            const reqNode = nodeById.get(reqId);
            if (reqNode && reqNode.id !== targetNode.id) {
              constraintMap.set(reqNode.id, reqNode);
            }
          }

          for (const constraintNode of constraintMap.values()) {
            const constraintState =
              state.get(constraintNode.id) ?? constraintNode.initialHomeState;

            // (a) 可达状态碰撞检测
            if (constraintState !== constraintNode.initialHomeState) {
              const colKey = `${step.stepNo}::${targetNode.id}::${constraintNode.id}`;
              if (!collisionKeys.has(colKey)) {
                collisionKeys.add(colKey);
                violations.push({
                  kind: 'COLLISION_REACHABLE',
                  stepNo: step.stepNo,
                  nodeId: targetNode.id,
                  interferingNodeId: constraintNode.id,
                  message: `机械碰撞可达: 工步 S${step.stepNo} (${step.title}) 驱动 "${targetNode.title}" 移至 ${inv.targetDiscreteState} 时，约束机构 "${constraintNode.title}" 当前可达状态为 ${constraintState}（未处于安全原位 ${constraintNode.initialHomeState}）。`,
                });
              }
            }

            // (b) 漏接安全护栏边检测 + 一键修复建议
            const hasValidGuard = guardEdges.some(
              (g) =>
                g.fromNode === constraintNode.id &&
                g.toNode === targetNode.id &&
                g.requiredSourceState === constraintNode.initialHomeState &&
                (g.toPort === 'IN_GUARD' ||
                  targetNode.inPorts.some((p) => p.id === g.toPort && p.type === 'GUARD'))
            );

            if (!hasValidGuard) {
              const pairKey = `${constraintNode.id}->${targetNode.id}`;
              if (!missingGuardPairs.has(pairKey)) {
                missingGuardPairs.add(pairKey);
                const suggestedGuardEdge = buildSuggestedGuardEdge(
                  constraintNode,
                  targetNode,
                  usedDiagCodes,
                  usedGuardIds
                );
                violations.push({
                  kind: 'MISSING_GUARDRAIL',
                  stepNo: step.stepNo,
                  nodeId: targetNode.id,
                  interferingNodeId: constraintNode.id,
                  message: `缺少防撞安全护栏: 工步 S${step.stepNo} (${step.title}) 移动 "${targetNode.title}"，但缺少 "${constraintNode.title} (${constraintNode.initialHomeState}) -> ${targetNode.title}.IN_GUARD" 的永久护栏边。`,
                  suggestedGuardEdge,
                });
              }
            }
          }
        }
      }
    }

    // 计算执行当前工步后的下一离散状态向量 s'
    const nextState = cloneState(state);
    for (const inv of step.invocations) {
      if (nodeById.has(inv.targetNodeId)) {
        nextState.set(inv.targetNodeId, inv.targetDiscreteState);
      }
    }

    const nextStateKey = serializeState(sortedNodeIds, nextState);
    uniqueStateKeys.add(nextStateKey);

    const stepTargets = new Set(step.invocations.map((i) => i.targetNodeId));
    for (const candidateNext of temporalSteps) {
      if (
        candidateNext.id !== step.id &&
        candidateNext.stepNo > step.stepNo &&
        stepTargets.has(candidateNext.fromNode)
      ) {
        const qKey = `${candidateNext.id}::${nextStateKey}`;
        if (!visitedQueueKeys.has(qKey)) {
          visitedQueueKeys.add(qKey);
          queue.push({ step: candidateNext, state: cloneState(nextState) });
        }
      }
    }
  }

  // 5. 孤立 / 不可达工步警告
  for (const step of temporalSteps) {
    if (!visitedStepIds.has(step.id)) {
      warnings.push(
        `孤立/不可达工步 S${step.stepNo} (${step.title}, id=${step.id}): 无法从工站入口沿时序流到达，请检查其前序节点 "${step.fromNode}"。`
      );
    }
  }

  const elapsedMs = Math.max(0, Number((nowMs() - tStart).toFixed(3)));

  return {
    passed: violations.length === 0,
    elapsedMs,
    exploredStateCount: uniqueStateKeys.size,
    violations,
    warnings,
  };
}

interface PendingWorkerJob {
  station: StationHyperGraph;
  ghostTx?: GhostGraphTransaction | null;
  resolve: (report: VerificationReport) => void;
}

let cachedWorker: Worker | null = null;
let workerUnavailable = false;
const workerQueue: PendingWorkerJob[] = [];

function flushWorkerQueueWithFallback(): void {
  while (workerQueue.length > 0) {
    const job = workerQueue.shift()!;
    job.resolve(verifyStationHyperGraph(job.station, job.ghostTx));
  }
}

function getOrCreateVerifierWorker(): Worker | null {
  if (workerUnavailable || typeof Worker === 'undefined') {
    return null;
  }
  if (cachedWorker) {
    return cachedWorker;
  }

  try {
    const worker = new Worker(new URL('./symbolicVerifier.worker.ts', import.meta.url), {
      type: 'module',
    });

    worker.onmessage = (event: MessageEvent<VerificationReport>) => {
      const job = workerQueue.shift();
      if (job) {
        job.resolve(event.data);
      }
    };

    worker.onerror = () => {
      workerUnavailable = true;
      try {
        worker.terminate();
      } catch {
        // ignore termination error
      }
      cachedWorker = null;
      flushWorkerQueueWithFallback();
    };

    cachedWorker = worker;
    return worker;
  } catch {
    workerUnavailable = true;
    return null;
  }
}

/**
 * 异步执行符号模型检验：在支持模块 Web Worker 的浏览器环境中卸载至 Worker 执行，
 * 否则优雅回退为本地同步执行并返回 Promise。
 */
export function runSymbolicVerifierAsync(
  station: StationHyperGraph,
  ghostTx?: GhostGraphTransaction | null
): Promise<VerificationReport> {
  const worker = getOrCreateVerifierWorker();
  if (!worker) {
    return Promise.resolve(verifyStationHyperGraph(station, ghostTx));
  }

  return new Promise<VerificationReport>((resolve) => {
    workerQueue.push({ station, ghostTx, resolve });
    try {
      worker.postMessage({ station, ghostTx: ghostTx ?? null });
    } catch {
      workerUnavailable = true;
      cachedWorker = null;
      flushWorkerQueueWithFallback();
    }
  });
}

/** 符号学验证器别名，与后端端点命名契约对齐 */
export const verifyStationInterlocks = verifyStationHyperGraph;
