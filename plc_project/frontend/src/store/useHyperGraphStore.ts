/**
 * AF-Studio v5 正交超图全局响应式状态管理仓库
 * 基于 React 19 useSyncExternalStore 实现，零外部状态库依赖。
 */

import { useCallback, useRef, useSyncExternalStore } from 'react';
import type {
  AfStudioWorkspaceData,
  CutSetTraceResult,
  DriverMotherClass,
  GhostGraphTransaction,
  HomingSynthesisResult,
  MerkleSyncManifest,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
  TemporalStepInvocation,
  VerificationReport,
} from '../core/ir/afHyperGraph.types';
import { createDefaultAfStudioWorkspace } from '../core/ir/seedHyperGraphs';
import {
  MOTHER_CLASS_REGISTRY,
  getRadialMethodsForClass,
} from '../core/ir/motherClassRegistry';
import {
  compileStationScl,
  syncMerkleBlocks,
  synthesizeStationHoming,
  traceStationCutSet,
  verifyStationSymbolic,
} from '../lib/afStudioV5Api';

export type AfGuardEdge = SafetyGuardEdge;
export type AutoHomingPlan = HomingSynthesisResult;
export type MotherClassId =
  | DriverMotherClass
  | 'SERVO'
  | 'CYLINDER'
  | 'GRIPPER'
  | 'VISION';

export interface HyperGraphStudioState {
  workspace: AfStudioWorkspaceData;
  currentLayer: 'LINE' | 'STATION';
  currentStationId: string;
  viewportTransform: { x: number; y: number; scale: number };
  selectedNodeId: string | null;
  focusedStepNo: number | null;
  activeGhost: GhostGraphTransaction | null;
  verificationReport: VerificationReport | null;
  cutSetResult: CutSetTraceResult | null;
  faultCruiseStep: number; // 0=idle, 1=decelerate, 2=seekSafe, 3=brakeCut
  homingPlan: AutoHomingPlan | null;
  merkleManifest: MerkleSyncManifest | null;
  isSyncingMerkle: boolean;
  isCompiling: boolean;
  isVerifying: boolean;
  isSynthesizingHoming: boolean;
  isTracingCutSet: boolean;
  radialMenuState: { nodeId: string; x: number; y: number } | null;
  activeModal: 'homing' | 'merkle' | 'cutset' | 'coldstart' | 'verification' | null;
  inspectorOpen: boolean;
}

type Listener = () => void;

function createInitialState(): HyperGraphStudioState {
  return {
    workspace: createDefaultAfStudioWorkspace(),
    currentLayer: 'STATION',
    currentStationId: 'ST20',
    viewportTransform: { x: 0, y: 0, scale: 1.0 },
    selectedNodeId: null,
    focusedStepNo: null,
    activeGhost: null,
    verificationReport: null,
    cutSetResult: null,
    faultCruiseStep: 0,
    homingPlan: null,
    merkleManifest: null,
    isSyncingMerkle: false,
    isCompiling: false,
    isVerifying: false,
    isSynthesizingHoming: false,
    isTracingCutSet: false,
    radialMenuState: null,
    activeModal: null,
    inspectorOpen: false,
  };
}

let currentState: HyperGraphStudioState = createInitialState();
const listeners = new Set<Listener>();

function emitChange(): void {
  for (const listener of listeners) {
    listener();
  }
}

function updateState(
  updater: (prev: HyperGraphStudioState) => HyperGraphStudioState
): HyperGraphStudioState {
  currentState = updater(currentState);
  emitChange();
  return currentState;
}

function cloneStation(st: StationHyperGraph): StationHyperGraph {
  return {
    stationId: st.stationId,
    stationName: st.stationName,
    spatialNodes: st.spatialNodes.map((n) => ({
      ...n,
      position: { ...n.position },
      discreteStates: [...n.discreteStates],
      cohesiveIoMap: { ...n.cohesiveIoMap },
      inPorts: n.inPorts.map((p) => ({ ...p })),
      outPorts: n.outPorts.map((p) => ({ ...p })),
    })),
    guardEdges: st.guardEdges.map((g) => ({
      ...g,
      crossStationRef: g.crossStationRef ? { ...g.crossStationRef } : undefined,
    })),
    temporalSteps: st.temporalSteps.map((s) => ({
      ...s,
      invocations: s.invocations.map((inv) => ({ ...inv })),
      requiresGuardNodeIds: s.requiresGuardNodeIds
        ? [...s.requiresGuardNodeIds]
        : undefined,
    })),
  };
}

function cloneWorkspace(ws: AfStudioWorkspaceData): AfStudioWorkspaceData {
  const stationGraphs: Record<string, StationHyperGraph> = {};
  for (const [id, st] of Object.entries(ws.stationGraphs)) {
    stationGraphs[id] = cloneStation(st);
  }
  return {
    projectName: ws.projectName,
    projectGraph: {
      stations: ws.projectGraph.stations.map((s) => ({
        ...s,
        position: { ...s.position },
        instanceSummaries: [...s.instanceSummaries],
        inPorts: s.inPorts.map((p) => ({ ...p })),
        outPorts: s.outPorts.map((p) => ({ ...p })),
      })),
      edges: ws.projectGraph.edges.map((e) => ({ ...e })),
    },
    stationGraphs,
  };
}

export const hyperGraphStore = {
  getState(): HyperGraphStudioState {
    return currentState;
  },

  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },

  setLayer(layer: 'LINE' | 'STATION'): void {
    updateState((prev) => ({ ...prev, currentLayer: layer }));
  },

  setStation(stationId: string): void {
    updateState((prev) => ({
      ...prev,
      currentStationId: stationId,
      selectedNodeId: null,
      focusedStepNo: null,
      radialMenuState: null,
    }));
  },

  setViewportTransform(t: { x: number; y: number; scale: number }): void {
    updateState((prev) => ({ ...prev, viewportTransform: { ...t } }));
  },

  selectNode(nodeId: string | null): void {
    updateState((prev) => ({
      ...prev,
      selectedNodeId: nodeId,
      inspectorOpen: nodeId ? true : prev.inspectorOpen,
    }));
  },

  setFocusedStep(stepNo: number | null): void {
    updateState((prev) => ({ ...prev, focusedStepNo: stepNo }));
  },

  openRadialMenu(nodeId: string, x: number, y: number): void {
    updateState((prev) => ({
      ...prev,
      radialMenuState: { nodeId, x, y },
      selectedNodeId: nodeId,
    }));
  },

  closeRadialMenu(): void {
    updateState((prev) => ({ ...prev, radialMenuState: null }));
  },

  addCraftStepFromRadial(
    nodeId: string,
    methodId: string,
    targetState: string
  ): void {
    updateState((prev) => {
      const ws = cloneWorkspace(prev.workspace);
      const station = ws.stationGraphs[prev.currentStationId];
      if (!station) return prev;

      const node = station.spatialNodes.find((n) => n.id === nodeId);
      if (!node) return prev;

      const methods = getRadialMethodsForClass(node.driverClass);
      const methodSpec = methods.find((m) => m.methodId === methodId);

      const maxStep = station.temporalSteps.reduce(
        (m, s) => Math.max(m, s.stepNo),
        0
      );
      const nextStepNo = maxStep > 0 ? maxStep + 10 : 10;
      const prevStep = station.temporalSteps.find((s) => s.stepNo === maxStep);
      const fromNode =
        prevStep?.invocations[0]?.targetNodeId ||
        station.spatialNodes.find((n) => n.role === 'BOUNDARY_IN')?.id ||
        station.spatialNodes[0]?.id ||
        nodeId;
      const fromPort = prevStep?.fromPort || 'OUT_DONE';

      const targetPortId =
        node.inPorts.find((p) => p.type === 'SEQ')?.id ||
        node.inPorts[0]?.id ||
        'IN_EXEC';
      const label = methodSpec?.label || methodId;
      const sclStatement = methodSpec?.sclCommand
        ? `#${node.instanceDb}.${methodSpec.sclCommand};`
        : `#${node.instanceDb}.${methodId}();`;

      const invocation: TemporalStepInvocation = {
        targetNodeId: nodeId,
        targetPortId,
        methodId,
        actionLabel: label,
        targetDiscreteState:
          targetState || methodSpec?.targetDiscreteState || 'AtHome',
        sclStatement,
        waitPredicateScl: `"${node.instanceDb}".o_bDone`,
        waitDescription: methodSpec?.waitDescription || `${node.title} ${label}`,
      };

      const newStep: TemporalStepHyperEdge = {
        id: `STEP_${station.stationId}_S${nextStepNo}`,
        stepNo: nextStepNo,
        title: `${node.title}·${label}`,
        fromNode,
        fromPort,
        invocations: [invocation],
        branchPredicate: 'ALWAYS',
      };

      station.temporalSteps.push(newStep);
      station.temporalSteps.sort((a, b) => a.stepNo - b.stepNo);

      return {
        ...prev,
        workspace: ws,
        radialMenuState: null,
        focusedStepNo: nextStepNo,
      };
    });
  },

  addNodeFromMotherClass(
    className: MotherClassId,
    instanceName?: string,
    pos?: { x: number; y: number }
  ): SpatialInstanceNode | null {
    let createdNode: SpatialInstanceNode | null = null;
    updateState((prev) => {
      const ws = cloneWorkspace(prev.workspace);
      const station = ws.stationGraphs[prev.currentStationId];
      if (!station) return prev;

      let driverClass: DriverMotherClass = 'FB_AF_AxisMotion';
      if (className === 'SERVO') driverClass = 'FB_AF_AxisMotion';
      else if (className === 'CYLINDER') driverClass = 'FB_AF_Actuator2Pos';
      else if (className === 'GRIPPER') driverClass = 'FB_AF_Gripper';
      else if (className === 'VISION') driverClass = 'FB_AF_VisionSensor';
      else driverClass = className as DriverMotherClass;

      const spec =
        MOTHER_CLASS_REGISTRY[driverClass] ||
        MOTHER_CLASS_REGISTRY['FB_AF_AxisMotion'];
      const count =
        station.spatialNodes.filter((n) => n.driverClass === driverClass).length + 1;
      const title = instanceName || `${spec.displayName}_${count}`;
      const safeSuffix = title.replace(/[^A-Za-z0-9_]/g, '_').toUpperCase();
      const nodeId = `INST_${station.stationId}_${safeSuffix}_${count}`;
      const instanceDb = `DB_${station.stationId}_${safeSuffix}`;

      const position = pos ?? {
        x: 220 + (station.spatialNodes.length % 4) * 200,
        y: 180 + Math.floor(station.spatialNodes.length / 4) * 150,
      };

      const newNode: SpatialInstanceNode = {
        id: nodeId,
        role: spec.role,
        title,
        driverClass,
        instanceDb,
        position,
        isPinned: false,
        hasPartPresentSensor: spec.supportsPartPresentSensor,
        discreteStates: [...spec.defaultDiscreteStates],
        initialHomeState: spec.initialHomeState,
        cohesiveIoMap: {
          ...Object.fromEntries(spec.defaultCohesiveIoKeys.map((k) => [k, ''])),
          cabinetTerminal: `XT_${station.stationId}_${count}`,
        },
        ioSummaryText: spec.defaultIoSummaryText,
        theme: spec.theme,
        inPorts: spec.defaultInPorts.map((p) => ({ ...p })),
        outPorts: spec.defaultOutPorts.map((p) => ({ ...p })),
      };

      station.spatialNodes.push(newNode);
      createdNode = newNode;

      return {
        ...prev,
        workspace: ws,
        selectedNodeId: nodeId,
        inspectorOpen: true,
      };
    });
    return createdNode;
  },

  removeNode(nodeId: string): void {
    updateState((prev) => {
      const ws = cloneWorkspace(prev.workspace);
      const station = ws.stationGraphs[prev.currentStationId];
      if (!station) return prev;

      station.spatialNodes = station.spatialNodes.filter((n) => n.id !== nodeId);
      station.guardEdges = station.guardEdges.filter(
        (g) => g.fromNode !== nodeId && g.toNode !== nodeId
      );

      station.temporalSteps = station.temporalSteps
        .map((s) => ({
          ...s,
          invocations: s.invocations.filter((inv) => inv.targetNodeId !== nodeId),
        }))
        .filter((s) => s.invocations.length > 0 || s.fromNode !== nodeId);

      return {
        ...prev,
        workspace: ws,
        selectedNodeId: prev.selectedNodeId === nodeId ? null : prev.selectedNodeId,
        radialMenuState:
          prev.radialMenuState?.nodeId === nodeId ? null : prev.radialMenuState,
      };
    });
  },

  addGuardEdge(edge: Omit<AfGuardEdge, 'id'>): AfGuardEdge {
    let createdEdge: AfGuardEdge | null = null;
    updateState((prev) => {
      const ws = cloneWorkspace(prev.workspace);
      const station = ws.stationGraphs[prev.currentStationId];
      if (!station) return prev;

      const edgeId = `G_${station.stationId}_${edge.fromNode}_TO_${edge.toNode}_${Date.now()}`;
      const newGuard: SafetyGuardEdge = {
        ...edge,
        id: edgeId,
        diagCodeHex: edge.diagCodeHex || '16#02FF',
        humanDescription:
          edge.humanDescription || `${edge.fromNode} -> ${edge.toNode} 互锁护栏`,
      };

      station.guardEdges.push(newGuard);
      createdEdge = newGuard;

      return {
        ...prev,
        workspace: ws,
      };
    });
    return createdEdge!;
  },

  setGhostTransaction(ghost: GhostGraphTransaction | null): void {
    updateState((prev) => ({ ...prev, activeGhost: ghost }));
  },

  applyActiveGhost(): void {
    updateState((prev) => {
      const ghost = prev.activeGhost;
      if (!ghost) return prev;

      const ws = cloneWorkspace(prev.workspace);
      const targetStationId = ghost.stationId || prev.currentStationId;
      const station = ws.stationGraphs[targetStationId];
      if (!station) return prev;

      // 合并 addedNodes
      for (const node of ghost.addedNodes || []) {
        const existingIdx = station.spatialNodes.findIndex((n) => n.id === node.id);
        if (existingIdx >= 0) {
          station.spatialNodes[existingIdx] = { ...node };
        } else {
          station.spatialNodes.push({ ...node });
        }
      }

      // 合并 addedGuardEdges
      for (const edge of ghost.addedGuardEdges || []) {
        if (!station.guardEdges.some((g) => g.id === edge.id)) {
          station.guardEdges.push({ ...edge });
        }
      }

      // 合并 addedTemporalSteps
      for (const step of ghost.addedTemporalSteps || []) {
        const existingIdx = station.temporalSteps.findIndex(
          (s) => s.id === step.id || s.stepNo === step.stepNo
        );
        if (existingIdx >= 0) {
          station.temporalSteps[existingIdx] = { ...step };
        } else {
          station.temporalSteps.push({ ...step });
        }
      }
      station.temporalSteps.sort((a, b) => a.stepNo - b.stepNo);

      // 处理 diff 字段
      const diff = (ghost as any).diff;
      if (diff) {
        if (Array.isArray(diff.removedNodeIds)) {
          const rmNodeSet = new Set(diff.removedNodeIds);
          station.spatialNodes = station.spatialNodes.filter(
            (n) => !rmNodeSet.has(n.id)
          );
          station.guardEdges = station.guardEdges.filter(
            (g) => !rmNodeSet.has(g.fromNode) && !rmNodeSet.has(g.toNode)
          );
        }
        if (Array.isArray(diff.removedEdgeIds)) {
          const rmEdgeSet = new Set(diff.removedEdgeIds);
          station.guardEdges = station.guardEdges.filter(
            (g) => !rmEdgeSet.has(g.id)
          );
        }
        if (Array.isArray(diff.modifiedNodes)) {
          for (const mod of diff.modifiedNodes) {
            const idx = station.spatialNodes.findIndex((n) => n.id === mod.id);
            if (idx >= 0) {
              station.spatialNodes[idx] = { ...station.spatialNodes[idx], ...mod };
            }
          }
        }
      }

      return {
        ...prev,
        workspace: ws,
        activeGhost: null,
      };
    });
  },

  discardActiveGhost(): void {
    updateState((prev) => ({ ...prev, activeGhost: null }));
  },

  async runVerification(): Promise<VerificationReport | null> {
    const s = hyperGraphStore.getState();
    const station = s.workspace.stationGraphs[s.currentStationId];
    if (!station) return null;

    updateState((prev) => ({ ...prev, isVerifying: true }));
    try {
      const res = await verifyStationSymbolic({
        station,
        ghostTx: s.activeGhost,
      });
      updateState((prev) => ({
        ...prev,
        verificationReport: res.data,
        isVerifying: false,
      }));
      return res.data;
    } catch {
      updateState((prev) => ({ ...prev, isVerifying: false }));
      return null;
    }
  },

  applyAutoFix(suggestionId?: string): void {
    const s = hyperGraphStore.getState();
    const report = s.verificationReport;
    if (!report) return;

    let patchToAdd: SafetyGuardEdge | undefined;

    // 1. 从 violations 中寻找建议护栏
    for (const v of report.violations) {
      if (v.suggestedGuardEdge) {
        if (
          !suggestionId ||
          v.suggestedGuardEdge.id === suggestionId ||
          v.kind === suggestionId ||
          v.suggestedGuardEdge.diagCodeHex === suggestionId
        ) {
          patchToAdd = v.suggestedGuardEdge;
          break;
        }
      }
    }

    // 2. 从 suggestedPatches 数组中寻找
    if (!patchToAdd && (report as any).suggestedPatches?.length) {
      const patches = (report as any).suggestedPatches as SafetyGuardEdge[];
      patchToAdd =
        patches.find(
          (p) =>
            p.id === suggestionId ||
            p.fromNode === suggestionId ||
            p.diagCodeHex === suggestionId
        ) || patches[0];
    }

    if (patchToAdd) {
      updateState((prev) => {
        const ws = cloneWorkspace(prev.workspace);
        const station = ws.stationGraphs[prev.currentStationId];
        if (!station) return prev;

        if (!station.guardEdges.some((g) => g.id === patchToAdd!.id)) {
          station.guardEdges.push({ ...patchToAdd! });
        }
        return {
          ...prev,
          workspace: ws,
        };
      });

      // 自动重新触发符号学验证以刷新报告
      hyperGraphStore.runVerification();
    }
  },

  async runHomingSynthesis(): Promise<AutoHomingPlan | null> {
    const s = hyperGraphStore.getState();
    const station = s.workspace.stationGraphs[s.currentStationId];
    if (!station) return null;

    updateState((prev) => ({ ...prev, isSynthesizingHoming: true }));
    try {
      const res = await synthesizeStationHoming({ station });
      updateState((prev) => ({
        ...prev,
        homingPlan: res.data,
        isSynthesizingHoming: false,
        activeModal: 'homing',
      }));
      return res.data;
    } catch {
      updateState((prev) => ({ ...prev, isSynthesizingHoming: false }));
      return null;
    }
  },

  applyHomingPlan(): void {
    updateState((prev) => {
      const plan = prev.homingPlan;
      if (!plan) return { ...prev, activeModal: null };

      const ws = cloneWorkspace(prev.workspace);
      const station = ws.stationGraphs[prev.currentStationId];
      if (station && plan.generatedHomeScl) {
        // 将归航 SCL 固化至工站元数据
        (station as any).homingScl = plan.generatedHomeScl;
        (station as any).homingLayers = plan.concurrentLayers.length;
      }

      return {
        ...prev,
        workspace: ws,
        activeModal: null,
      };
    });
  },

  async runCutSetTrace(failedNodeId?: string): Promise<CutSetTraceResult | null> {
    const s = hyperGraphStore.getState();
    updateState((prev) => ({ ...prev, isTracingCutSet: true }));
    try {
      const res = await traceStationCutSet({
        projectGraph: s.workspace.projectGraph,
        stationGraphs: s.workspace.stationGraphs,
        faultStationId: s.currentStationId,
        faultStepNo: s.focusedStepNo ?? 30,
      });

      const cutSetResult = res.data;
      updateState((prev) => ({
        ...prev,
        cutSetResult,
        isTracingCutSet: false,
        faultCruiseStep: 1,
        selectedNodeId: failedNodeId || cutSetResult.blockedNodeId || prev.selectedNodeId,
      }));
      return cutSetResult;
    } catch {
      updateState((prev) => ({ ...prev, isTracingCutSet: false }));
      return null;
    }
  },

  stepFaultCruise(step: number): void {
    const clampedStep = Math.max(0, Math.min(3, step));
    updateState((prev) => {
      const cutSet = prev.cutSetResult;
      let nextLayer = prev.currentLayer;
      let nextStationId = prev.currentStationId;
      let nextSelectedNode = prev.selectedNodeId;
      let nextScale = prev.viewportTransform.scale;

      if (cutSet?.flyToStages && clampedStep >= 1 && clampedStep <= cutSet.flyToStages.length) {
        const stage = cutSet.flyToStages[clampedStep - 1];
        if (stage.layer === 'PROJECT') {
          nextLayer = 'LINE';
        } else {
          nextLayer = 'STATION';
          if (stage.stationId && prev.workspace.stationGraphs[stage.stationId]) {
            nextStationId = stage.stationId;
          }
        }
        if (stage.focusEntityId) {
          nextSelectedNode = stage.focusEntityId;
        }
        nextScale = stage.zoomScale;
      }

      return {
        ...prev,
        faultCruiseStep: clampedStep,
        currentLayer: nextLayer,
        currentStationId: nextStationId,
        selectedNodeId: nextSelectedNode,
        viewportTransform: {
          ...prev.viewportTransform,
          scale: nextScale,
        },
      };
    });
  },

  async compileAndSyncMerkle(
    target: 'TIA_V19_STA' | 'V19_EXPORT' = 'TIA_V19_STA'
  ): Promise<MerkleSyncManifest | null> {
    const s = hyperGraphStore.getState();
    const station = s.workspace.stationGraphs[s.currentStationId];
    if (!station) return null;

    updateState((prev) => ({ ...prev, isCompiling: true, isSyncingMerkle: true }));
    try {
      await compileStationScl({ station });
      const syncRes = await syncMerkleBlocks({
        station,
        projectId: s.workspace.projectName,
        plcName: target,
      });

      const manifest: MerkleSyncManifest = {
        stationId: station.stationId,
        tiaTarget: target,
        dirtyCount: syncRes.data.dirtyCount,
        unchangedCount: syncRes.data.unchangedCount,
        estimatedSyncSeconds: 1,
        entries: syncRes.data.entries || [],
      };

      updateState((prev) => ({
        ...prev,
        merkleManifest: manifest,
        isCompiling: false,
        isSyncingMerkle: false,
      }));
      return manifest;
    } catch {
      updateState((prev) => ({
        ...prev,
        isCompiling: false,
        isSyncingMerkle: false,
      }));
      return null;
    }
  },

  importColdStartGraph(ws: AfStudioWorkspaceData): void {
    const firstStationId = Object.keys(ws.stationGraphs)[0] || 'ST20';
    updateState((prev) => ({
      ...prev,
      workspace: cloneWorkspace(ws),
      currentStationId: ws.stationGraphs[prev.currentStationId]
        ? prev.currentStationId
        : firstStationId,
      currentLayer: 'STATION',
      selectedNodeId: null,
      focusedStepNo: null,
      activeGhost: null,
      verificationReport: null,
      cutSetResult: null,
      faultCruiseStep: 0,
      homingPlan: null,
      merkleManifest: null,
      radialMenuState: null,
      activeModal: null,
    }));
  },

  resetToDefaultWorkspace(): void {
    updateState(() => createInitialState());
  },

  openModal(modal: HyperGraphStudioState['activeModal']): void {
    updateState((prev) => ({ ...prev, activeModal: modal }));
  },

  closeModal(): void {
    updateState((prev) => ({ ...prev, activeModal: null }));
  },

  toggleInspector(open?: boolean): void {
    updateState((prev) => ({
      ...prev,
      inspectorOpen: open !== undefined ? open : !prev.inspectorOpen,
    }));
  },
};

function shallowEqual(a: any, b: any): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || a === null || typeof b !== 'object' || b === null) {
    return false;
  }
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (const k of keysA) {
    if (!Object.prototype.hasOwnProperty.call(b, k) || !Object.is(a[k], b[k])) {
      return false;
    }
  }
  return true;
}

/**
 * React 19 外部响应式 Hook (useSyncExternalStore)
 */
export function useHyperGraphStore<T = HyperGraphStudioState>(
  selector?: (state: HyperGraphStudioState) => T
): T {
  if (!selector) {
    return useSyncExternalStore(
      hyperGraphStore.subscribe,
      hyperGraphStore.getState,
      hyperGraphStore.getState
    ) as unknown as T;
  }

  const lastStateRef = useRef<HyperGraphStudioState | null>(null);
  const lastSelectedRef = useRef<T | null>(null);
  const selectorRef = useRef(selector);
  selectorRef.current = selector;

  const getSelection = useCallback(() => {
    const nextState = hyperGraphStore.getState();
    if (lastStateRef.current === nextState && lastSelectedRef.current !== null) {
      return lastSelectedRef.current;
    }
    const nextSelected = selectorRef.current(nextState);
    if (
      lastSelectedRef.current !== null &&
      shallowEqual(lastSelectedRef.current, nextSelected)
    ) {
      lastStateRef.current = nextState;
      return lastSelectedRef.current;
    }
    lastStateRef.current = nextState;
    lastSelectedRef.current = nextSelected;
    return nextSelected;
  }, []);

  return useSyncExternalStore(
    hyperGraphStore.subscribe,
    getSelection,
    getSelection
  );
}

// 属性选择器快捷 Hook
useHyperGraphStore.getState = hyperGraphStore.getState;
useHyperGraphStore.subscribe = hyperGraphStore.subscribe;
useHyperGraphStore.useWorkspace = () => useHyperGraphStore((s) => s.workspace);
useHyperGraphStore.useCurrentStation = () =>
  useHyperGraphStore((s) => s.workspace.stationGraphs[s.currentStationId]);
useHyperGraphStore.useSelectedNodeId = () =>
  useHyperGraphStore((s) => s.selectedNodeId);
useHyperGraphStore.useCurrentLayer = () =>
  useHyperGraphStore((s) => s.currentLayer);
useHyperGraphStore.useVerificationReport = () =>
  useHyperGraphStore((s) => s.verificationReport);
useHyperGraphStore.useActiveGhost = () =>
  useHyperGraphStore((s) => s.activeGhost);
useHyperGraphStore.useCutSetResult = () =>
  useHyperGraphStore((s) => s.cutSetResult);
useHyperGraphStore.useHomingPlan = () =>
  useHyperGraphStore((s) => s.homingPlan);
useHyperGraphStore.useFaultCruiseStep = () =>
  useHyperGraphStore((s) => s.faultCruiseStep);
useHyperGraphStore.useMerkleManifest = () =>
  useHyperGraphStore((s) => s.merkleManifest);
