import type {
  CameraFlyToStage,
  CutSetTraceResult,
  ProjectHyperGraph,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
} from '../ir/afHyperGraph.types';

const TERMINAL_ADDR_REGEX = /%[IQM]\d+\.\d+/i;

function extractTerminalFromText(text?: string): string {
  if (!text) return '';
  const match = text.match(TERMINAL_ADDR_REGEX);
  return match ? match[0].toUpperCase() : '';
}

function getGuardEdgesForNode(
  station: StationHyperGraph,
  nodeId: string
): SafetyGuardEdge[] {
  const node = station.spatialNodes.find((n) => n.id === nodeId);
  const guardPortIds = new Set(
    (node?.inPorts ?? []).filter((p) => p.type === 'GUARD').map((p) => p.id)
  );
  guardPortIds.add('IN_GUARD');

  return station.guardEdges.filter(
    (g) => g.toNode === nodeId && (!g.toPort || guardPortIds.has(g.toPort))
  );
}

function extractIoCandidatesForState(
  node: SpatialInstanceNode,
  requiredState: string,
  portId?: string
): string[] {
  const keys: string[] = [];
  const io = node.cohesiveIoMap ?? {};

  if (portId) {
    const outPort = node.outPorts.find((p) => p.id === portId);
    const portTerm = extractTerminalFromText(outPort?.label);
    if (portTerm) keys.push(portTerm);
  }

  const stateLower = requiredState.toLowerCase();
  const isHomeLike =
    requiredState === node.initialHomeState ||
    stateLower.includes('home') ||
    stateLower === 'idle';

  const preferredIoKeys: string[] = [];
  if (isHomeLike) {
    preferredIoKeys.push('diHome', 'retracted', 'o_bAtHome', 'o_bSafeAtHome');
  }
  if (stateLower.includes('open')) {
    preferredIoKeys.push('diOpened', 'opened');
  }
  if (stateLower.includes('close')) {
    preferredIoKeys.push('diClosed', 'closed');
  }
  if (stateLower.includes('work')) {
    preferredIoKeys.push('diWork', 'extended');
  }

  for (const k of preferredIoKeys) {
    if (io[k]) {
      keys.push(io[k], `${node.id}.${k}`);
    }
  }

  for (const [k, v] of Object.entries(io)) {
    if (/terminal/i.test(k)) continue;
    if (TERMINAL_ADDR_REGEX.test(v)) {
      keys.push(v, `${node.id}.${k}`);
    }
  }

  return keys;
}

function collectEdgeSignalKeys(
  edge: SafetyGuardEdge,
  station: StationHyperGraph,
  stationGraphs: Record<string, StationHyperGraph>
): string[] {
  const keys: string[] = [edge.id];

  if (edge.crossStationRef) {
    if (edge.crossStationRef.physicalTerminal) {
      keys.push(edge.crossStationRef.physicalTerminal);
    }
    const upStation = stationGraphs[edge.crossStationRef.upstreamStationId];
    const upNode = upStation?.spatialNodes.find(
      (n) => n.id === edge.crossStationRef!.upstreamInstanceId
    );
    if (upNode) {
      keys.push(
        ...extractIoCandidatesForState(
          upNode,
          edge.requiredSourceState,
          edge.crossStationRef.upstreamPortId
        )
      );
    }
  }

  const localSrc = station.spatialNodes.find((n) => n.id === edge.fromNode);
  if (localSrc) {
    keys.push(
      ...extractIoCandidatesForState(localSrc, edge.requiredSourceState, edge.fromPort)
    );
  }

  const descTerminal = extractTerminalFromText(edge.humanDescription);
  if (descTerminal) {
    keys.push(descTerminal);
  }

  return [...new Set(keys.filter(Boolean))];
}

function evaluateGuardEdgeHealth(
  edge: SafetyGuardEdge,
  station: StationHyperGraph,
  stationGraphs: Record<string, StationHyperGraph>,
  liveSignals?: Record<string, boolean>
): boolean {
  if (liveSignals) {
    const candidateKeys = collectEdgeSignalKeys(edge, station, stationGraphs);
    for (const key of candidateKeys) {
      if (Object.prototype.hasOwnProperty.call(liveSignals, key)) {
        const val = liveSignals[key];
        if (typeof val === 'boolean') return val;
      }
      const upperKey = key.toUpperCase();
      if (upperKey !== key && Object.prototype.hasOwnProperty.call(liveSignals, upperKey)) {
        const val = liveSignals[upperKey];
        if (typeof val === 'boolean') return val;
      }
    }
  }

  if (typeof edge.isHealthy === 'boolean') {
    return edge.isHealthy;
  }

  if (edge.crossStationRef) {
    const upStation = stationGraphs[edge.crossStationRef.upstreamStationId];
    const upNode = upStation?.spatialNodes.find(
      (n) => n.id === edge.crossStationRef!.upstreamInstanceId
    );
    if (upNode?.isPhysicalRootCause) {
      return false;
    }
  }

  return true;
}

function extractNodePhysicalTerminal(
  node: SpatialInstanceNode | undefined,
  portId?: string,
  fallbackEdge?: SafetyGuardEdge
): string {
  if (node) {
    if (portId) {
      const port = node.outPorts.find((p) => p.id === portId);
      const fromPort = extractTerminalFromText(port?.label);
      if (fromPort) return fromPort;
    }
    const io = node.cohesiveIoMap ?? {};
    const priorityKeys = ['diHome', 'retracted', 'diOpened', 'diClosed', 'diWork'];
    for (const k of priorityKeys) {
      if (io[k] && TERMINAL_ADDR_REGEX.test(io[k])) {
        return io[k];
      }
    }
    for (const val of Object.values(io)) {
      if (TERMINAL_ADDR_REGEX.test(val)) return val;
    }
  }
  return extractTerminalFromText(fallbackEdge?.humanDescription);
}

function findL1CutSetEdgeId(
  projectGraph: ProjectHyperGraph,
  upstreamStationId: string,
  downstreamStationId: string,
  diagCodeHex?: string
): string | undefined {
  const fromL1 = projectGraph.stations.find((s) => s.stationId === upstreamStationId);
  const toL1 = projectGraph.stations.find((s) => s.stationId === downstreamStationId);
  if (!fromL1 || !toL1) return undefined;

  const matchingGuards = projectGraph.edges.filter(
    (e) => e.fromNode === fromL1.id && e.toNode === toL1.id && e.kind === 'GUARD'
  );
  if (matchingGuards.length === 0) return undefined;
  if (diagCodeHex) {
    const exact = matchingGuards.find((e) => e.diagCodeHex === diagCodeHex);
    if (exact) return exact.id;
  }
  return matchingGuards[0].id;
}

/**
 * 算法三：跨站布尔 DAG 最小证伪割集穿透定位。
 * 在受阻执行器的 IN_GUARD 逻辑与门上剪枝全部 TRUE 健康边，
 * 并沿唯一 FALSE 割集穿透 L2 -> L1 -> 上游 L2 递归锁定物理端子与电柜线号，
 * 同时构建 3 段式 Camera Fly-To 自动巡航指令。
 */
export function traceMinimalFalsifyingCutSet(
  projectGraph: ProjectHyperGraph,
  stationGraphs: Record<string, StationHyperGraph>,
  faultStationId: string,
  faultStepNo: number,
  liveSignals?: Record<string, boolean>
): CutSetTraceResult {
  const faultStation = stationGraphs[faultStationId];
  const faultL1Node = projectGraph.stations.find((s) => s.stationId === faultStationId);

  if (!faultStation) {
    return {
      blockedStationId: faultStationId,
      blockedStepNo: faultStepNo,
      blockedNodeId: '',
      prunedHealthyEdgeIds: [],
      falsifiedEdgeIds: [],
      rootCauseStationId: faultStationId,
      rootCauseNodeId: '',
      rootPhysicalTerminal: '',
      rootCabinetWireTag: '',
      diagnosisSummary: `未在工站超图映射中找到受阻工站 "${faultStationId}"。`,
      flyToStages: [
        {
          stageIndex: 1,
          layer: 'PROJECT',
          zoomScale: 0.85,
          stageTag: '巡航 1/3 · 产线总览',
          description: `未找到工站 "${faultStationId}"`,
          focusEntityId: faultL1Node?.id ?? faultStationId,
        },
        {
          stageIndex: 2,
          layer: 'PROJECT',
          zoomScale: 0.85,
          stageTag: '巡航 2/3 · 割集未命中',
          description: `无法检索工步 S${faultStepNo}`,
          focusEntityId: faultL1Node?.id ?? faultStationId,
        },
        {
          stageIndex: 3,
          layer: 'PROJECT',
          zoomScale: 0.85,
          stageTag: '巡航 3/3 · 定位结束',
          description: `工站 "${faultStationId}" 不存在`,
          focusEntityId: faultL1Node?.id ?? faultStationId,
        },
      ],
    };
  }

  const faultStep = faultStation.temporalSteps.find((s) => s.stepNo === faultStepNo);
  const candidateTargets = faultStep?.invocations.map((inv) => inv.targetNodeId) ?? [];

  let blockedNodeId = candidateTargets[0] ?? '';
  let nodeGuardEdges: SafetyGuardEdge[] = blockedNodeId
    ? getGuardEdgesForNode(faultStation, blockedNodeId)
    : [];

  for (const targetId of candidateTargets) {
    const edges = getGuardEdgesForNode(faultStation, targetId);
    const hasFalsified = edges.some(
      (e) => !evaluateGuardEdgeHealth(e, faultStation, stationGraphs, liveSignals)
    );
    if (hasFalsified) {
      blockedNodeId = targetId;
      nodeGuardEdges = edges;
      break;
    }
    if (nodeGuardEdges.length === 0 && edges.length > 0) {
      blockedNodeId = targetId;
      nodeGuardEdges = edges;
    }
  }

  const prunedHealthyEdgeIds: string[] = [];
  const falsifiedEdgeIds: string[] = [];
  const falsifiedEdges: SafetyGuardEdge[] = [];

  for (const g of nodeGuardEdges) {
    if (evaluateGuardEdgeHealth(g, faultStation, stationGraphs, liveSignals)) {
      prunedHealthyEdgeIds.push(g.id);
    } else {
      falsifiedEdgeIds.push(g.id);
      falsifiedEdges.push(g);
    }
  }

  const blockedNode = faultStation.spatialNodes.find((n) => n.id === blockedNodeId);

  if (falsifiedEdges.length === 0) {
    const summary = `工站 ${faultStationId} Step ${faultStepNo} (${blockedNode?.title ?? blockedNodeId}) 的全部 ${prunedHealthyEdgeIds.length} 条护栏边当前均实测为 TRUE，已全部剪枝健康项，无阻塞割集。`;
    return {
      blockedStationId: faultStationId,
      blockedStepNo: faultStepNo,
      blockedNodeId,
      prunedHealthyEdgeIds,
      falsifiedEdgeIds: [],
      rootCauseStationId: faultStationId,
      rootCauseNodeId: blockedNodeId,
      rootPhysicalTerminal: '',
      rootCabinetWireTag: '',
      diagnosisSummary: summary,
      flyToStages: [
        {
          stageIndex: 1,
          layer: 'STATION',
          stationId: faultStationId,
          zoomScale: 1.5,
          stageTag: '巡航 1/3 · 受阻现场复核',
          description: summary,
          focusEntityId: blockedNodeId || faultStationId,
        },
        {
          stageIndex: 2,
          layer: 'PROJECT',
          zoomScale: 0.85,
          stageTag: '巡航 2/3 · L1 产线护栏核验',
          description: '跨站与本地安全护栏均为 TRUE，无需跨站穿透。',
          focusEntityId: faultL1Node?.id ?? faultStationId,
        },
        {
          stageIndex: 3,
          layer: 'STATION',
          stationId: faultStationId,
          zoomScale: 1.5,
          stageTag: '巡航 3/3 · 护栏健康就绪',
          description: `${faultStationId} 所有安全护栏已恢复导通。`,
          focusEntityId: blockedNodeId || faultStationId,
        },
      ],
    };
  }

  // 沿主证伪割集边向布尔 DAG 上游递归穿透
  const visitedEdgeIds = new Set<string>(falsifiedEdgeIds);
  let l1CutSetEdgeId: string | undefined;
  let rootCauseStationId = faultStationId;
  let rootCauseNodeId = blockedNodeId;
  let rootPhysicalTerminal = '';
  let rootCabinetWireTag = '';

  const walkUpstream = (
    currentStationId: string,
    edge: SafetyGuardEdge
  ): void => {
    if (edge.crossStationRef) {
      const ref = edge.crossStationRef;
      const resolvedL1 =
        ref.l1EdgeId ??
        findL1CutSetEdgeId(
          projectGraph,
          ref.upstreamStationId,
          currentStationId,
          edge.diagCodeHex
        );
      if (!l1CutSetEdgeId && resolvedL1) {
        l1CutSetEdgeId = resolvedL1;
      }

      const upStation = stationGraphs[ref.upstreamStationId];
      const upNode = upStation?.spatialNodes.find(
        (n) => n.id === ref.upstreamInstanceId
      );

      if (upStation && upNode) {
        const upIncomingFalsified = getGuardEdgesForNode(upStation, upNode.id).find(
          (g) =>
            !visitedEdgeIds.has(g.id) &&
            !evaluateGuardEdgeHealth(g, upStation, stationGraphs, liveSignals)
        );
        if (upIncomingFalsified) {
          visitedEdgeIds.add(upIncomingFalsified.id);
          falsifiedEdgeIds.push(upIncomingFalsified.id);
          walkUpstream(ref.upstreamStationId, upIncomingFalsified);
          return;
        }
      }

      rootCauseStationId = ref.upstreamStationId;
      rootCauseNodeId = ref.upstreamInstanceId;
      rootPhysicalTerminal =
        ref.physicalTerminal ||
        extractNodePhysicalTerminal(upNode, ref.upstreamPortId, edge);
      rootCabinetWireTag =
        ref.cabinetWireTag || upNode?.cohesiveIoMap.cabinetTerminal || '';
      return;
    }

    const curStation = stationGraphs[currentStationId];
    const srcNode = curStation?.spatialNodes.find((n) => n.id === edge.fromNode);
    if (curStation && srcNode) {
      const srcIncomingFalsified = getGuardEdgesForNode(curStation, srcNode.id).find(
        (g) =>
          !visitedEdgeIds.has(g.id) &&
          !evaluateGuardEdgeHealth(g, curStation, stationGraphs, liveSignals)
      );
      if (srcIncomingFalsified) {
        visitedEdgeIds.add(srcIncomingFalsified.id);
        falsifiedEdgeIds.push(srcIncomingFalsified.id);
        walkUpstream(currentStationId, srcIncomingFalsified);
        return;
      }
    }

    rootCauseStationId = currentStationId;
    rootCauseNodeId = edge.fromNode;
    rootPhysicalTerminal = extractNodePhysicalTerminal(srcNode, edge.fromPort, edge);
    rootCabinetWireTag = srcNode?.cohesiveIoMap.cabinetTerminal || '';
  };

  const primaryFalsifiedEdge = falsifiedEdges[0];
  walkUpstream(faultStationId, primaryFalsifiedEdge);

  const rootStation = stationGraphs[rootCauseStationId];
  const rootNode = rootStation?.spatialNodes.find((n) => n.id === rootCauseNodeId);
  const rootL1Node = projectGraph.stations.find(
    (s) => s.stationId === rootCauseStationId
  );

  const prunedSummary =
    prunedHealthyEdgeIds.length > 0
      ? `已剪枝 ${prunedHealthyEdgeIds.length} 条健康护栏 (${prunedHealthyEdgeIds.join(', ')})`
      : '无健康护栏可剪枝';

  const terminalInfo = [
    rootPhysicalTerminal ? `物理端子 ${rootPhysicalTerminal}` : '',
    rootCabinetWireTag ? `电柜线号 ${rootCabinetWireTag}` : '',
  ]
    .filter(Boolean)
    .join(' / ');

  const isCrossStation = rootCauseStationId !== faultStationId;
  const diagnosisSummary = isCrossStation
    ? `${prunedSummary}；沿唯一 FALSE 割集 ${primaryFalsifiedEdge.id} (${primaryFalsifiedEdge.diagCodeHex}) 穿透 L1 边 ${l1CutSetEdgeId ?? 'L1_GUARD'} 锁定上游根因：${rootCauseStationId}「${rootNode?.title ?? rootCauseNodeId}」(${terminalInfo || '信号异常'})。`
    : `${prunedSummary}；锁定本站 FALSE 割集 ${primaryFalsifiedEdge.id} (${primaryFalsifiedEdge.diagCodeHex}) 根因：${rootCauseStationId}「${rootNode?.title ?? rootCauseNodeId}」(${terminalInfo || '信号异常'})。`;

  const flyToStages: CameraFlyToStage[] = [
    {
      stageIndex: 1,
      layer: 'STATION',
      stationId: faultStationId,
      zoomScale: 1.5,
      stageTag: `巡航 1/3 · ${faultStationId} 受阻现场`,
      description: `${prunedSummary}，锁定受阻实例「${blockedNode?.title ?? blockedNodeId}」唯一 FALSE 护栏边 ${primaryFalsifiedEdge.id} (${primaryFalsifiedEdge.diagCodeHex})。`,
      focusEntityId: blockedNodeId || primaryFalsifiedEdge.id,
    },
    {
      stageIndex: 2,
      layer: 'PROJECT',
      zoomScale: 0.8,
      stageTag: '巡航 2/3 · L1 跨工站割集穿越',
      description: isCrossStation
        ? `沿 L1 产线安全割集边 ${l1CutSetEdgeId ?? ''} 从 ${faultStationId} 逆向穿越至上游工站 ${rootCauseStationId}。`
        : `在 L1 产线总图确认故障收敛于工站 ${faultStationId} 内部，切回本工站物理根因。`,
      focusEntityId: l1CutSetEdgeId ?? rootL1Node?.id ?? faultL1Node?.id ?? rootCauseStationId,
    },
    {
      stageIndex: 3,
      layer: 'STATION',
      stationId: rootCauseStationId,
      zoomScale: 1.65,
      stageTag: '巡航 3/3 · 真凶物理端子已锁定',
      description: `根因锁定：${rootCauseStationId}「${rootNode?.title ?? rootCauseNodeId}」${terminalInfo ? `（${terminalInfo} = FALSE）` : ''}。`,
      focusEntityId: rootCauseNodeId,
    },
  ];

  return {
    blockedStationId: faultStationId,
    blockedStepNo: faultStepNo,
    blockedNodeId,
    prunedHealthyEdgeIds,
    falsifiedEdgeIds,
    ...(l1CutSetEdgeId ? { l1CutSetEdgeId } : {}),
    rootCauseStationId,
    rootCauseNodeId,
    rootPhysicalTerminal,
    rootCabinetWireTag,
    diagnosisSummary,
    flyToStages,
  };
}

/** 跨站最小证伪割集追踪别名，与后端端点命名契约对齐 */
export const traceMinimalCutSet = traceMinimalFalsifyingCutSet;
