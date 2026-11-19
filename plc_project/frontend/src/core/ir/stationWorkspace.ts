import type { AfStudioWorkspaceData, StationHyperGraph } from './afHyperGraph.types';
import { defaultCmControl, type CmDeviceProfile } from './fieldIo';
import { refreshBoundaryPortLabel } from './stationBoundaryLabels';

const workspaceKey = 'plc-chat.af-studio-v5.workspace';
const legacyCmPortLabels = {
  IN_EXEC: ['▶ 动作触发槽', '▶ 伸出/缩回触发槽', '▶ 作业请求'],
  OUT_DONE: ['● 动作到位', '● 气缸动作到位 →', '● 在位状态', '● 作业应答'],
};

export function readStationWorkspace(): AfStudioWorkspaceData | undefined {
  try {
    const saved = window.localStorage.getItem(workspaceKey);
    if (!saved) return;
    const workspace = JSON.parse(saved) as AfStudioWorkspaceData;
    if (
      typeof workspace.projectName === 'string' &&
      Array.isArray(workspace.projectGraph?.stations) &&
      Array.isArray(workspace.projectGraph?.edges) &&
      workspace.projectGraph.stations.length > 0 &&
      workspace.projectGraph.stations.every(({ stationId }) => {
        const graph = workspace.stationGraphs?.[stationId];
        return graph?.stationId === stationId &&
          Array.isArray(graph.spatialNodes) &&
          Array.isArray(graph.guardEdges) &&
          Array.isArray(graph.temporalSteps);
      })
    ) {
      for (const graph of Object.values(workspace.stationGraphs)) {
        graph.spatialNodes = graph.spatialNodes.map((node) => {
          if (node.role !== 'ACTUATOR') {
            const inPorts = node.inPorts.map(refreshBoundaryPortLabel);
            const outPorts = node.outPorts.map(refreshBoundaryPortLabel);
            const updated = inPorts.some((port, i) => port !== node.inPorts[i]) ||
              outPorts.some((port, i) => port !== node.outPorts[i]);
            if (!updated) return node;
            return {
              ...node,
              inPorts,
              outPorts,
              instanceDb: node.role === 'BOUNDARY_OUT' && node.instanceDb === '映射至 L1 下游接口'
                ? '反馈至 L1 工位接口' : node.instanceDb,
            };
          }
          let cmProfile: CmDeviceProfile | undefined = node.cmProfile;
          if (node.driverClass === 'FB_AF_Actuator2Pos' && 'IN_FWD' in node.cohesiveIoMap) cmProfile = 'Cylinder2Pos@1';
          if (node.driverClass === 'FB_AF_VisionSensor' && Object.keys(node.cohesiveIoMap).join() === 'SENSOR_RET') cmProfile = 'DigitalInput@1';
          if (node.driverClass === 'FB_AF_AxisMotion' && /_Robot_/.test(node.instanceDb)) cmProfile = 'Robot6Axis@1';
          if (!cmProfile) return node;
          const isUsed = graph.temporalSteps.some((step) => step.fromNode === node.id ||
            step.invocations.some((invocation) => invocation.targetNodeId === node.id)) ||
            graph.guardEdges.some((edge) => edge.fromNode === node.id || edge.toNode === node.id);
          if (!node.cmProfile && isUsed && cmProfile !== 'Cylinder2Pos@1') return node;
          const control = defaultCmControl(cmProfile);
          const keepPort = ({ id, label }: typeof node.inPorts[number]) => {
            if (id === 'IN_EXEC' && legacyCmPortLabels.IN_EXEC.includes(label)) {
              return graph.temporalSteps.some((step) => step.invocations.some((invocation) =>
                invocation.targetNodeId === node.id && (invocation.targetPortId ?? 'IN_EXEC') === id)) ||
                graph.guardEdges.some((edge) => edge.toNode === node.id && edge.toPort === id);
            }
            if (id === 'OUT_DONE' && legacyCmPortLabels.OUT_DONE.includes(label)) {
              return graph.temporalSteps.some((step) => step.fromNode === node.id && step.fromPort === id) ||
                Object.values(workspace.stationGraphs).some((owner) => owner.guardEdges.some((edge) =>
                  (owner === graph && edge.fromNode === node.id && edge.fromPort === id) ||
                  (edge.crossStationRef?.upstreamStationId === graph.stationId &&
                    edge.crossStationRef.upstreamInstanceId === node.id &&
                    (edge.crossStationRef.upstreamPortId ?? id) === id)));
            }
            return true;
          };
          const mergePorts = (existing: typeof node.inPorts, defaults: typeof control.inPorts) => [
            ...defaults.map((port) => existing.find(({ id }) => id === port.id) ?? port),
            ...existing.filter((port) => !defaults.some(({ id }) => id === port.id) && keepPort(port)),
          ];
          return {
            ...node, cmProfile,
            driverClass: cmProfile === 'DigitalInput@1' ? 'FB_AF_DigitalInput'
              : cmProfile === 'Robot6Axis@1' ? 'FB_AF_Robot6Axis' : node.driverClass,
            initialHomeState: isUsed ? node.initialHomeState : control.initialHomeState,
            discreteStates: [...new Set([...control.discreteStates, ...node.discreteStates])],
            inPorts: mergePorts(node.inPorts, control.inPorts),
            outPorts: mergePorts(node.outPorts, control.outPorts),
          };
        });
      }
      return workspace;
    }
  } catch {
    // The workspace can still be edited when browser storage is unavailable.
  }
}

export function saveStationWorkspace(workspace: AfStudioWorkspaceData): boolean {
  try {
    window.localStorage.setItem(workspaceKey, JSON.stringify(workspace));
    return true;
  } catch {
    return false;
  }
}

export function cloneStationGraph(source: StationHyperGraph, stationId: string, title: string): StationHyperGraph {
  const copy = structuredClone(source);
  const nodeIds = new Map(source.spatialNodes.map((node, index) => [
    node.id, node.role === 'ACTUATOR' ? `INST_${stationId}_${index + 1}` : `BOUND_${node.role === 'BOUNDARY_IN' ? 'IN' : 'OUT'}_${stationId}`,
  ]));
  const instanceDbs = new Map<string, string>();
  const nodes = copy.spatialNodes.map((node) => {
    const id = nodeIds.get(node.id)!;
    const isDevice = node.role === 'ACTUATOR';
    const instanceDb = isDevice ? `DB_${id}` : node.instanceDb;
    if (isDevice && node.instanceDb) instanceDbs.set(node.instanceDb, instanceDb);
    return {
      ...node,
      id,
      instanceDb,
      title: !isDevice && node.title.startsWith(source.stationId)
        ? stationId + node.title.slice(source.stationId.length) : node.title,
      cohesiveIoMap: Object.fromEntries(Object.keys(node.cohesiveIoMap).map((key) => [key, ''])),
      fieldBindings: node.cmProfile ? {} : undefined,
      ioSummaryText: undefined,
      isPhysicalRootCause: undefined,
    };
  });
  const remapReferences = (expression: string) => expression
    .replace(/[A-Za-z_][A-Za-z_0-9]*/g, (token) => nodeIds.get(token) ?? instanceDbs.get(token) ?? token);
  const fieldAddress = /%[IQM](?:[BWD])?\d+(?:\.\d+)?|"?DB_LineBus"?\s*\.\s*"?[A-Z_][A-Z_0-9]*"?/gi;
  const resetBindings = (expression: string) => remapReferences(expression).replace(fieldAddress, '__REBIND_IO__');
  return {
    stationId,
    stationName: title,
    spatialNodes: nodes,
    guardEdges: copy.guardEdges.filter((edge) => !edge.crossStationRef && nodeIds.has(edge.fromNode) && nodeIds.has(edge.toNode))
      .map((edge, index) => ({
        ...edge,
        id: `G_${stationId}_${index + 1}`,
        fromNode: nodeIds.get(edge.fromNode)!,
        toNode: nodeIds.get(edge.toNode)!,
        isHealthy: undefined,
      })),
    temporalSteps: copy.temporalSteps.map((step, index) => ({
      ...step,
      id: `T_${stationId}_${index + 1}`,
      fromNode: nodeIds.get(step.fromNode) ?? step.fromNode,
      requiresGuardNodeIds: step.requiresGuardNodeIds?.map((id) => nodeIds.get(id) ?? id),
      invocations: step.invocations.map((invocation) => ({
        ...invocation,
        targetNodeId: nodeIds.get(invocation.targetNodeId) ?? invocation.targetNodeId,
        sclStatement: resetBindings(invocation.sclStatement),
        waitPredicateScl: resetBindings(invocation.waitPredicateScl),
      })),
    })),
    orchestration: copy.orchestration && {
      ...copy.orchestration,
      operations: copy.orchestration.operations.map((operation) => ({ ...operation, stationId: '' })),
      interrupt: copy.orchestration.interrupt && { ...copy.orchestration.interrupt, stationId: '' },
      jobDispatch: copy.orchestration.jobDispatch && { ...copy.orchestration.jobDispatch, stationId: '' },
    },
  };
}

export function stationHasUnboundSignals(station: StationHyperGraph): boolean {
  return station.spatialNodes.some((node) => node.role === 'ACTUATOR' && !node.cmProfile && Object.values(node.cohesiveIoMap).some((value) => !value.trim())) ||
    station.temporalSteps.some((step) => step.invocations.some(
      (invocation) => [invocation.sclStatement, invocation.waitPredicateScl].some((value) => value.includes('__REBIND_IO__')),
    ));
}
