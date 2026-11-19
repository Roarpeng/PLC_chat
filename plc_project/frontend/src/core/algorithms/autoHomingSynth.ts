import type {
  HomingNodeAction,
  HomingSynthesisResult,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
} from '../ir/afHyperGraph.types';

/**
 * 当空间安全护栏偏序图中存在强连通死锁环路时抛出的异常。
 */
export class DeadlockCycleError extends Error {
  public readonly cycleNodeIds: string[];
  public readonly cycleEdgeIds: string[];

  constructor(message: string, cycleNodeIds: string[], cycleEdgeIds: string[]) {
    super(message);
    this.name = 'DeadlockCycleError';
    this.cycleNodeIds = cycleNodeIds;
    this.cycleEdgeIds = cycleEdgeIds;
  }
}

export interface AutoHomingOptions {
  stationId?: string;
  throwOnDeadlock?: boolean;
}

export interface GuardCycleScc {
  nodeIds: string[];
  edgeIds: string[];
}

export interface GuardCycleDetectionResult {
  hasCycle: boolean;
  sccs: GuardCycleScc[];
  cycleNodeIds: string[];
  cycleEdgeIds: string[];
}

interface DirectedEdgeRef {
  to: string;
  edgeId: string;
}

function sanitizeBlockIdent(raw: string): string {
  const cleaned = raw.replace(/[^A-Za-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  return cleaned || 'Station';
}

function canHome(node: SpatialInstanceNode, includeVisionSensors = false): boolean {
  return node.role === 'ACTUATOR' && node.driverClass !== 'FB_AF_DigitalInput' &&
    node.driverClass !== 'FB_AF_Robot6Axis' && node.driverClass !== 'FB_AF_Vacuum' &&
    node.driverClass !== 'FB_AF_MotorStartStop' && node.cmProfile !== 'ServoAxis@1' &&
    (includeVisionSensors || node.driverClass !== 'FB_AF_VisionSensor');
}

/**
 * 使用 Tarjan 强连通分量 (SCC) 算法检测执行器护栏依赖图中的死锁环路（自环或长度 >= 2 的 SCC）。
 */
export function detectActuatorGuardCycles(
  nodes: SpatialInstanceNode[],
  guards: SafetyGuardEdge[],
  includeVisionSensors = false
): GuardCycleDetectionResult {
  const actuators = nodes.filter((node) => canHome(node, includeVisionSensors));
  const actuatorOrder = new Map<string, number>();
  const adj = new Map<string, DirectedEdgeRef[]>();

  actuators.forEach((node, idx) => {
    actuatorOrder.set(node.id, idx);
    adj.set(node.id, []);
  });

  const relevantGuards = guards.filter((g) => actuatorOrder.has(g.fromNode) && actuatorOrder.has(g.toNode));
  for (const g of relevantGuards) {
    adj.get(g.fromNode)!.push({ to: g.toNode, edgeId: g.id });
  }

  let currentIndex = 0;
  const indices = new Map<string, number>();
  const lowlink = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const rawSccs: string[][] = [];

  const strongConnect = (v: string) => {
    indices.set(v, currentIndex);
    lowlink.set(v, currentIndex);
    currentIndex += 1;
    stack.push(v);
    onStack.add(v);

    for (const edge of adj.get(v) ?? []) {
      const w = edge.to;
      if (!indices.has(w)) {
        strongConnect(w);
        lowlink.set(v, Math.min(lowlink.get(v)!, lowlink.get(w)!));
      } else if (onStack.has(w)) {
        lowlink.set(v, Math.min(lowlink.get(v)!, indices.get(w)!));
      }
    }

    if (lowlink.get(v) === indices.get(v)) {
      const component: string[] = [];
      while (stack.length > 0) {
        const w = stack.pop()!;
        onStack.delete(w);
        component.push(w);
        if (w === v) break;
      }
      rawSccs.push(component);
    }
  };

  for (const node of actuators) {
    if (!indices.has(node.id)) {
      strongConnect(node.id);
    }
  }

  const cyclicSccs: GuardCycleScc[] = [];
  const cycleNodeSet = new Set<string>();
  const cycleEdgeSet = new Set<string>();

  for (const component of rawSccs) {
    const isMultiNodeCycle = component.length >= 2;
    const isSelfLoop =
      component.length === 1 && (adj.get(component[0])?.some((e) => e.to === component[0]) ?? false);

    if (!isMultiNodeCycle && !isSelfLoop) continue;

    const compSet = new Set(component);
    const orderedNodes = [...component].sort(
      (a, b) => (actuatorOrder.get(a) ?? 0) - (actuatorOrder.get(b) ?? 0)
    );
    const edgeIds = relevantGuards
      .filter((g) => compSet.has(g.fromNode) && compSet.has(g.toNode))
      .map((g) => g.id);

    orderedNodes.forEach((id) => cycleNodeSet.add(id));
    edgeIds.forEach((id) => cycleEdgeSet.add(id));
    cyclicSccs.push({ nodeIds: orderedNodes, edgeIds });
  }

  const cycleNodeIds = actuators.filter((n) => cycleNodeSet.has(n.id)).map((n) => n.id);
  const cycleEdgeIds = relevantGuards.filter((g) => cycleEdgeSet.has(g.id)).map((g) => g.id);

  return {
    hasCycle: cyclicSccs.length > 0,
    sccs: cyclicSccs,
    cycleNodeIds,
    cycleEdgeIds,
  };
}

function buildHomingNodeAction(node: SpatialInstanceNode): HomingNodeAction {
  const db = node.instanceDb;
  const partPresentProtected = node.hasPartPresentSensor === true;

  if (partPresentProtected) {
    return {
      node,
      partPresentProtected: true,
      sclSnippet: `IF "${db}".i_bPartPresent THEN "${db}".MaintainGrip(); ELSE "${db}".OpenGrip(); END_IF;`,
      waitAtHomeExpr: `(("${db}".i_bPartPresent AND "${db}".o_bClosed) OR (NOT "${db}".i_bPartPresent AND "${db}".o_bOpened))`,
    };
  }

  if (node.driverClass === 'FB_AF_AxisMotion') {
    return {
      node,
      partPresentProtected: false,
      sclSnippet: `"${db}".MoveAbs(0.0);`,
      waitAtHomeExpr: `"${db}".o_bAtHome`,
    };
  }

  if (node.driverClass === 'FB_AF_Gripper') {
    return {
      node,
      partPresentProtected: false,
      sclSnippet: `"${db}".OpenGrip();`,
      waitAtHomeExpr: `"${db}".o_bOpened`,
    };
  }

  return {
    node,
    partPresentProtected: false,
    sclSnippet: `"${db}".RetractHome();`,
    waitAtHomeExpr: `"${db}".o_bAtHome`,
  };
}

function renderDeadlockHomeScl(
  stationIdent: string,
  cycleNodeIds: string[],
  cycleEdgeIds: string[]
): string {
  return [
    `// [DEADLOCK_CYCLE_BLOCKED] 算法一 (Auto-Homing) 检测到护栏强连通死锁环，已禁止生成并发归航步序`,
    `// 死锁环节点: ${cycleNodeIds.join(' <-> ')}`,
    `// 死锁环护栏边: ${cycleEdgeIds.join(', ')}`,
    `FUNCTION_BLOCK "FB_${stationIdent}_HomeSeq"`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VAR_INPUT`,
    `   i_bExecute : BOOL;`,
    `END_VAR`,
    `VAR_OUTPUT`,
    `   o_bDone : BOOL;`,
    `   o_bFault : BOOL;`,
    `END_VAR`,
    `VAR`,
    `   statHomeStep : INT := -1;`,
    `   statHomeFault : BOOL := TRUE;`,
    `   statHomeDone : BOOL := FALSE;`,
    `END_VAR`,
    `BEGIN`,
    `   // 安全阻断: 存在互锁环路死锁，禁止自动回原位`,
    `   #statHomeFault := TRUE;`,
    `   #statHomeDone := FALSE;`,
    `   CASE #statHomeStep OF`,
    `      ELSE`,
    `         #statHomeFault := TRUE;`,
    `   END_CASE;`,
    `   #o_bDone := #statHomeDone;`,
    `   #o_bFault := #statHomeFault;`,
    `END_FUNCTION_BLOCK`,
  ].join('\n');
}

function renderLayeredHomeScl(stationIdent: string, layerActions: HomingNodeAction[][]): string {
  const stepLines: string[] = [
    `      0: // 待机等待整站一键安全归航指令`,
    `         IF #i_bExecute THEN`,
    `            #statHomeFault := FALSE;`,
    `            #statHomeDone := FALSE;`,
    `            #statHomeStep := ${layerActions.length > 0 ? 10 : 900};`,
    `         END_IF;`,
  ];

  layerActions.forEach((actions, layerIdx) => {
    const stepNo = (layerIdx + 1) * 10;
    const nextStepNo = layerIdx + 1 < layerActions.length ? (layerIdx + 2) * 10 : 900;
    const actionStatements = actions
      .map((a) => `         ${a.sclSnippet} // ${a.node.title}`)
      .join('\n');
    const waitExpr = actions.map((a) => a.waitAtHomeExpr).join(' AND ') || 'TRUE';

    stepLines.push(
      ``,
      `      ${stepNo}: // Kahn 并发归航层 Layer ${layerIdx + 1} (${actions.map((a) => a.node.id).join(', ')})`,
      actionStatements,
      `         IF ${waitExpr} THEN`,
      `            #statHomeStep := ${nextStepNo};`,
      `         END_IF;`
    );
  });

  stepLines.push(
    ``,
    `      900: // 整站安全归航完成`,
    `         #statHomeDone := TRUE;`,
    `         IF NOT #i_bExecute THEN`,
    `            #statHomeStep := 0;`,
    `         END_IF;`
  );

  return [
    `// 算法一 (Auto-Homing): Kahn 分层拓扑排序 + Tarjan 环检测自动合成`,
    `FUNCTION_BLOCK "FB_${stationIdent}_HomeSeq"`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VAR_INPUT`,
    `   i_bExecute : BOOL;`,
    `END_VAR`,
    `VAR_OUTPUT`,
    `   o_bDone : BOOL;`,
    `   o_bFault : BOOL;`,
    `END_VAR`,
    `VAR`,
    `   statHomeStep : INT := 0;`,
    `   statHomeFault : BOOL := FALSE;`,
    `   statHomeDone : BOOL := FALSE;`,
    `END_VAR`,
    `BEGIN`,
    `   CASE #statHomeStep OF`,
    ...stepLines,
    `   END_CASE;`,
    `   #o_bDone := #statHomeDone;`,
    `   #o_bFault := #statHomeFault;`,
    `END_FUNCTION_BLOCK`,
  ].join('\n');
}

/**
 * 算法一：基于空间护栏偏序图的一键安全归航合成。
 * 使用 Tarjan 强连通分量检测护栏死锁环，并用 Kahn 分层拓扑排序推导无碰撞并发归航步序及 SCL 状态机。
 */
export function synthesizeSafeHomingSequence(
  station: StationHyperGraph,
  options?: AutoHomingOptions
): HomingSynthesisResult;
export function synthesizeSafeHomingSequence(
  nodes: SpatialInstanceNode[],
  guards: SafetyGuardEdge[],
  stationIdOrOptions?: string | AutoHomingOptions,
  options?: AutoHomingOptions
): HomingSynthesisResult;
export function synthesizeSafeHomingSequence(
  stationOrNodes: StationHyperGraph | SpatialInstanceNode[],
  guardsOrOptions?: SafetyGuardEdge[] | AutoHomingOptions,
  stationIdOrOptions?: string | AutoHomingOptions,
  maybeOptions?: AutoHomingOptions
): HomingSynthesisResult {
  let nodes: SpatialInstanceNode[];
  let guards: SafetyGuardEdge[];
  let resolvedOptions: AutoHomingOptions = {};

  if (Array.isArray(stationOrNodes)) {
    nodes = stationOrNodes;
    guards = Array.isArray(guardsOrOptions) ? guardsOrOptions : [];
    if (typeof stationIdOrOptions === 'string') {
      resolvedOptions = { ...(maybeOptions ?? {}), stationId: stationIdOrOptions };
    } else if (stationIdOrOptions && typeof stationIdOrOptions === 'object') {
      resolvedOptions = { ...stationIdOrOptions, ...(maybeOptions ?? {}) };
    } else {
      resolvedOptions = maybeOptions ?? {};
    }
  } else {
    nodes = stationOrNodes.spatialNodes;
    guards = stationOrNodes.guardEdges;
    const optArg = !Array.isArray(guardsOrOptions) ? guardsOrOptions : undefined;
    resolvedOptions = {
      stationId: stationOrNodes.stationId,
      ...(optArg ?? {}),
    };
  }

  const stationIdent = sanitizeBlockIdent(resolvedOptions.stationId ?? 'Station');
  const actuators = nodes.filter((node) => canHome(node));

  const cycleReport = detectActuatorGuardCycles(nodes, guards, false);
  if (cycleReport.hasCycle) {
    const generatedHomeScl = renderDeadlockHomeScl(
      stationIdent,
      cycleReport.cycleNodeIds,
      cycleReport.cycleEdgeIds
    );
    if (resolvedOptions.throwOnDeadlock) {
      throw new DeadlockCycleError(
        `护栏偏序图存在死锁环路 (${cycleReport.cycleNodeIds.join(' -> ')})`,
        cycleReport.cycleNodeIds,
        cycleReport.cycleEdgeIds
      );
    }
    return {
      hasCycleDeadlock: true,
      cycleNodeIds: cycleReport.cycleNodeIds,
      cycleEdgeIds: cycleReport.cycleEdgeIds,
      concurrentLayers: [],
      layerActions: [],
      generatedHomeScl,
    };
  }

  const actuatorOrder = new Map<string, number>();
  const actuatorById = new Map<string, SpatialInstanceNode>();
  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();

  actuators.forEach((node, idx) => {
    actuatorOrder.set(node.id, idx);
    actuatorById.set(node.id, node);
    inDegree.set(node.id, 0);
    adj.set(node.id, []);
  });

  for (const g of guards) {
    if (g.fromNode !== g.toNode && actuatorById.has(g.fromNode) && actuatorById.has(g.toNode)) {
      adj.get(g.fromNode)!.push(g.toNode);
      inDegree.set(g.toNode, (inDegree.get(g.toNode) ?? 0) + 1);
    }
  }

  const concurrentLayers: SpatialInstanceNode[][] = [];
  let zeroInQueue = actuators.filter((a) => (inDegree.get(a.id) ?? 0) === 0);

  while (zeroInQueue.length > 0) {
    concurrentLayers.push(zeroInQueue);
    const nextLayer: SpatialInstanceNode[] = [];

    for (const u of zeroInQueue) {
      for (const vId of adj.get(u.id) ?? []) {
        const nextDeg = (inDegree.get(vId) ?? 0) - 1;
        inDegree.set(vId, nextDeg);
        if (nextDeg === 0) {
          const vNode = actuatorById.get(vId);
          if (vNode) nextLayer.push(vNode);
        }
      }
    }

    nextLayer.sort((a, b) => (actuatorOrder.get(a.id) ?? 0) - (actuatorOrder.get(b.id) ?? 0));
    zeroInQueue = nextLayer;
  }

  const layerActions = concurrentLayers.map((layer) => layer.map(buildHomingNodeAction));
  const generatedHomeScl = renderLayeredHomeScl(stationIdent, layerActions);

  return {
    hasCycleDeadlock: false,
    cycleNodeIds: [],
    cycleEdgeIds: [],
    concurrentLayers,
    layerActions,
    generatedHomeScl,
  };
}

/** 一键安全归航合成别名，与后端端点命名契约对齐 */
export const synthesizeStationHoming = synthesizeSafeHomingSequence;
