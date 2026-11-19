import { useCallback, useRef, useSyncExternalStore } from 'react';
import type {
  AfStudioWorkspaceData,
  CameraFlyToStage,
  CutSetTraceResult,
  GhostGraphTransaction,
  HomingSynthesisResult,
  ProjectCompoundEdge,
  ProjectCompoundStation,
  ProjectHyperGraph,
  SafetyGuardEdge,
  SelectedHyperEntity,
  SpatialInstanceNode,
  StationKind,
  StationOrchestration,
  StationHyperGraph,
  TemporalStepHyperEdge,
  VerificationReport,
  VerifierViolation,
} from '../core/ir/afHyperGraph.types';
import { createDefaultAfStudioWorkspace } from '../core/ir/seedHyperGraphs';
import { stationBoundaryLabels } from '../core/ir/stationBoundaryLabels';
import { cloneStationGraph, readStationWorkspace, saveStationWorkspace } from '../core/ir/stationWorkspace';
import { bindingError, fieldIoOwners, parseFieldAddress, pointError, type FieldIoPoint } from '../core/ir/fieldIo';
import { verifyStationHyperGraph } from '../core/algorithms/symbolicVerifier';
import { traceMinimalFalsifyingCutSet } from '../core/algorithms/minimalCutSetTracer';
import { synthesizeSafeHomingSequence } from '../core/algorithms/autoHomingSynth';

export type StudioModalType = 'homing' | 'verifier' | 'cutset' | 'coldstart' | 'newProject' | 'fieldIo' | null;

export interface NewProjectPayload {
  projectName: string;
  template: 'blank' | 'single_station' | 'three_station_line';
  firstStationId?: string;
  firstStationTitle?: string;
}

export interface AddStationPayload {
  stationId: string;
  title: string;
  kind?: StationKind;
  copyFromId?: string;
}

export interface HyperGraphStoreState {
  workspace: AfStudioWorkspaceData;
  currentLayer: 'PROJECT' | 'STATION';
  currentStationId: string;
  zoomScale: number;
  focusedStepNo: number | null;
  selectedEntity: SelectedHyperEntity;
  activeGhost: GhostGraphTransaction | null;
  verifierReport: VerificationReport | null;
  cutSetTrace: CutSetTraceResult | null;
  faultFlyActive: boolean;
  flyToStage: CameraFlyToStage | null;
  activeModal: StudioModalType;
  isMerkleDrawerOpen: boolean;
  isInspectorOpen: boolean;
  paletteCollapsed: boolean;
  st10SensorHealthy: boolean;
  workspaceSaved: boolean;
}

export interface HyperGraphStoreActions {
  setLayer: (layer: 'PROJECT' | 'STATION', stationId?: string) => void;
  setStation: (stationId: string) => void;
  setZoomScale: (scale: number) => void;
  setFocusedStepNo: (stepNo: number | null) => void;
  setSelectedEntity: (entity: SelectedHyperEntity) => void;
  setActiveGhost: (ghost: GhostGraphTransaction | null) => void;
  commitGhost: () => void;
  discardGhost: () => void;
  runVerification: () => VerificationReport;
  applyAutoFix: (violation: VerifierViolation) => void;
  runCutSetTrace: (stationId?: string, stepNo?: number) => CutSetTraceResult;
  stepFaultCruise: (stageIndex: 1 | 2 | 3) => void;
  stopFaultCruise: () => void;
  openModal: (modal: StudioModalType) => void;
  closeModal: () => void;
  toggleMerkleDrawer: (open?: boolean) => void;
  toggleInspector: (open?: boolean) => void;
  togglePaletteCollapse: () => void;
  setSt10SensorHealthy: (healthy: boolean) => void;
  addNode: (stationId: string, node: SpatialInstanceNode) => void;
  updateNode: (stationId: string, nodeId: string, patch: Partial<SpatialInstanceNode>) => void;
  deleteNode: (stationId: string, nodeId: string) => void;
  addGuardEdge: (stationId: string, edge: SafetyGuardEdge) => void;
  updateGuardEdge: (stationId: string, edgeId: string, patch: Partial<SafetyGuardEdge>) => void;
  deleteGuardEdge: (stationId: string, edgeId: string) => void;
  addTemporalStep: (stationId: string, step: TemporalStepHyperEdge) => void;
  updateTemporalStep: (stationId: string, stepId: string, patch: Partial<TemporalStepHyperEdge>) => void;
  deleteTemporalStep: (stationId: string, stepId: string) => void;
  updateProjectStation: (nodeId: string, patch: Partial<ProjectCompoundStation>) => void;
  arrangeProjectStations: () => void;
  deleteProjectStation: (nodeId: string) => void;
  addProjectEdge: (edge: ProjectCompoundEdge) => void;
  updateProjectEdge: (edgeId: string, patch: Partial<ProjectCompoundEdge>) => void;
  deleteProjectEdge: (edgeId: string) => void;
  createNewProject: (payload: NewProjectPayload) => void;
  addStationToProject: (payload: AddStationPayload) => void;
  updateOrchestration: (stationId: string, orchestration: StationOrchestration) => void;
  saveFieldPoint: (point: FieldIoPoint) => string | undefined;
  deleteFieldPoint: (pointId: string) => string | undefined;
  bindFieldPoint: (stationId: string, nodeId: string, portId: string, pointId: string) => string | undefined;
  applyHomingResult: (stationId: string, result: HomingSynthesisResult) => void;
  resetWorkspace: () => void;
}

function buildBlankStationGraph(stationId: string, stationName: string): StationHyperGraph {
  return {
    stationId,
    stationName,
    spatialNodes: [
      {
        id: `BOUND_IN_${stationId}`,
        role: 'BOUNDARY_IN',
        title: `${stationId} · 左输入边界`,
        driverClass: 'STATION_INPUT_PORT',
        instanceDb: '映射自 L1 产线接口',
        position: { x: 40, y: 150 },
        isPinned: true,
        discreteStates: ['WaitingPart', 'PartArrived'],
        initialHomeState: 'WaitingPart',
        cohesiveIoMap: {
          i_bPartArrived: `DB_LineBus.${stationId}_PartReady`,
        },
        theme: 'ink',
        inPorts: [],
        outPorts: [
          { id: 'OUT_PART_ARRIVED', label: stationBoundaryLabels.request, type: 'SEQ' },
          { id: 'OUT_SAFE_IN', label: stationBoundaryLabels.permit, type: 'GUARD' },
        ],
      },
      {
        id: `BOUND_OUT_${stationId}`,
        role: 'BOUNDARY_OUT',
        title: `${stationId} · 右输出边界`,
        driverClass: 'STATION_OUTPUT_PORT',
        instanceDb: '反馈至 L1 工位接口',
        position: { x: 760, y: 150 },
        isPinned: true,
        discreteStates: ['Idle', 'CycleDone'],
        initialHomeState: 'Idle',
        cohesiveIoMap: {
          o_bCycleDone: `DB_LineBus.${stationId}_Done`,
        },
        theme: 'ink',
        inPorts: [
          { id: 'IN_HANDOVER', label: stationBoundaryLabels.done, type: 'SEQ' },
          { id: 'IN_SAFE_OUT', label: stationBoundaryLabels.safe, type: 'GUARD' },
        ],
        outPorts: [],
      },
    ],
    guardEdges: [],
    temporalSteps: [],
  };
}

function projectStationPosition(index: number) {
  return { x: 20 + (index % 3) * 285, y: 78 + Math.floor(index / 3) * 158 };
}

function buildNewWorkspace(payload: NewProjectPayload): {
  workspace: AfStudioWorkspaceData;
  initialStationId: string;
} {
  const cleanName = payload.projectName.trim() || 'NewLine_01';
  if (payload.template === 'three_station_line') {
    const base = createDefaultAfStudioWorkspace();
    base.projectName = cleanName;
    return { workspace: base, initialStationId: 'ST20' };
  }

  const stId = (payload.firstStationId || 'ST10').trim().toUpperCase() || 'ST10';
  const stTitle = (payload.firstStationTitle || `${stId} · 主工作站`).trim();
  const baseStation = buildBlankStationGraph(stId, stTitle);

  if (payload.template === 'single_station') {
    const cylId = `INST_${stId}_CYL1`;
    const servoId = `INST_${stId}_AXIS1`;
    baseStation.spatialNodes.splice(
      1,
      0,
      {
        id: cylId,
        role: 'ACTUATOR',
        title: '1号夹紧定位气缸',
        driverClass: 'FB_AF_Actuator2Pos',
        instanceDb: `DB_${stId}_CylClamp`,
        position: { x: 280, y: 95 },
        isPinned: true,
        discreteStates: ['AtHome', 'AtWork'],
        initialHomeState: 'AtHome',
        cohesiveIoMap: { diHome: '%I0.0', diWork: '%I0.1', doWork: '%Q0.0' },
        ioSummaryText: '原位 %I0.0 · 动位 %I0.1 · 输出 %Q0.0',
        theme: 'emerald',
        inPorts: [
          { id: 'IN_EXEC', label: '▶ 动作触发槽', type: 'SEQ' },
          { id: 'IN_GUARD', label: '🛡️ 防撞护栏', type: 'GUARD' },
        ],
        outPorts: [{ id: 'OUT_DONE', label: '● 动作到位 →', type: 'SEQ' }],
      },
      {
        id: servoId,
        role: 'ACTUATOR',
        title: 'Z轴压装伺服',
        driverClass: 'FB_AF_AxisMotion',
        instanceDb: `DB_${stId}_AxisZ`,
        position: { x: 520, y: 235 },
        isPinned: true,
        discreteStates: ['Pos_Home_0', 'Pos_Press_120'],
        initialHomeState: 'Pos_Home_0',
        cohesiveIoMap: { drvTelegram: 'Telegram_111_Z', diHomeLim: '%I1.0' },
        ioSummaryText: '配方: 待机0 / 下压120mm',
        theme: 'klein',
        inPorts: [
          { id: 'IN_EXEC', label: '▶ 点位触发槽', type: 'SEQ' },
          { id: 'IN_GUARD', label: '🛡️ 防撞护栏', type: 'GUARD' },
        ],
        outPorts: [{ id: 'OUT_DONE', label: '● 定位完成 →', type: 'SEQ' }],
      }
    );
    baseStation.guardEdges.push({
      id: `G_${stId}_CYL_TO_Z`,
      fromNode: cylId,
      fromPort: 'OUT_DONE',
      toNode: servoId,
      toPort: 'IN_GUARD',
      requiredSourceState: 'AtWork',
      diagCodeHex: '16#0101',
      humanDescription: '夹紧气缸夹紧到位后才允许Z轴伺服下压',
      isHealthy: true,
    });
    baseStation.temporalSteps.push({
      id: `T_${stId}_S10`,
      stepNo: 10,
      title: '工件夹紧定位',
      fromNode: `BOUND_IN_${stId}`,
      fromPort: 'OUT_PART_ARRIVED',
      branchPredicate: 'ALWAYS',
      invocations: [
        {
          targetNodeId: cylId,
          targetPortId: 'IN_EXEC',
          methodId: 'Extend',
          actionLabel: '气缸伸出夹紧',
          targetDiscreteState: 'AtWork',
          sclStatement: `#${cylId}.i_bCmdWork := TRUE;`,
          waitPredicateScl: `#${cylId}.o_bAtWork`,
          waitDescription: '气缸伸出到位',
        },
      ],
    });
  }

  const compoundStation: ProjectCompoundStation = {
    id: `NODE_${stId}`,
    stationId: stId,
    title: stTitle,
    position: projectStationPosition(0),
    isPinned: true,
    instanceSummaries:
      payload.template === 'single_station'
        ? [`DB_${stId}_CylClamp (夹紧缸)`, `DB_${stId}_AxisZ (Z轴伺服)`]
        : ['待从左侧母版库拖入执行器实例'],
    inPorts: [
      { id: 'P_UP', label: payload.template === 'blank' ? '操作请求' : '📦 上游来料就绪', type: 'SEQ' },
      { id: 'P_GUARD_IN', label: '🛡️ 跨站安全护栏', type: 'GUARD' },
    ],
    outPorts: [
      { id: 'P_HANDOVER', label: payload.template === 'blank' ? '就绪 / 完成 / 故障' : '📦 节拍完成放行 →', type: 'SEQ' },
      { id: 'P_SAFE_HOME', label: '🛡️ 工站在安全原位', type: 'GUARD' },
    ],
  };

  return {
    workspace: {
      projectName: cleanName,
      projectGraph: {
        stations: [compoundStation],
        edges: [],
      },
      stationGraphs: {
        [stId]: baseStation,
      },
    },
    initialStationId: stId,
  };
}

export type HyperGraphStore = HyperGraphStoreState & HyperGraphStoreActions;

function createInitialState(saved?: AfStudioWorkspaceData): HyperGraphStoreState {
  const ws = saved ?? createDefaultAfStudioWorkspace();
  const initialStationId = saved?.projectGraph.stations[0]?.stationId ?? 'ST20';
  const initialStation = ws.stationGraphs[initialStationId];
  const initialVerifierReport = initialStation
    ? verifyStationHyperGraph(initialStation)
    : null;

  return {
    workspace: ws,
    currentLayer: saved ? 'PROJECT' : 'STATION',
    currentStationId: initialStationId,
    zoomScale: 1.0,
    focusedStepNo: null,
    selectedEntity: null,
    activeGhost: null,
    verifierReport: saved ? null : initialVerifierReport,
    cutSetTrace: null,
    faultFlyActive: false,
    flyToStage: null,
    activeModal: null,
    isMerkleDrawerOpen: false,
    isInspectorOpen: !saved,
    paletteCollapsed: false,
    st10SensorHealthy: false,
    workspaceSaved: Boolean(saved),
  };
}

class HyperGraphStoreManager {
  private state: HyperGraphStoreState;
  private cachedStore: HyperGraphStore;
  private listeners: Set<() => void> = new Set();

  constructor() {
    this.state = createInitialState(readStationWorkspace());
    this.cachedStore = { ...this.state, ...this.actions };
  }

  public getState = (): HyperGraphStoreState => {
    return this.state;
  };

  /** Return the cached combined store snapshot so useSyncExternalStore gets a stable reference. */
  public getStore = (): HyperGraphStore => {
    return this.cachedStore;
  };

  public subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private commitState = (nextState: HyperGraphStoreState) => {
    if (nextState.workspace !== this.state.workspace) {
      nextState = { ...nextState, workspaceSaved: saveStationWorkspace(nextState.workspace) };
    }
    this.state = nextState;
    this.cachedStore = { ...this.state, ...this.actions };
    this.listeners.forEach((l) => l());
  };

  private setState = (updater: Partial<HyperGraphStoreState> | ((prev: HyperGraphStoreState) => Partial<HyperGraphStoreState>)) => {
    const patch = typeof updater === 'function' ? updater(this.state) : updater;
    this.commitState({ ...this.state, ...patch });
  };

  public actions: HyperGraphStoreActions = {
    setLayer: (layer, stationId) => {
      this.setState((prev) => {
        const nextStationId = stationId ?? prev.currentStationId;
        const currentStation = prev.workspace.stationGraphs[nextStationId];
        const nextReport =
          layer === 'STATION' && currentStation && !currentStation.orchestration
            ? verifyStationHyperGraph(currentStation)
            : null;
        return {
          currentLayer: layer,
          currentStationId: nextStationId,
          verifierReport: nextReport,
          selectedEntity: null,
          focusedStepNo: null,
          activeGhost: null,
          isInspectorOpen: false,
        };
      });
    },

    setStation: (stationId) => {
      this.setState((prev) => {
        const station = prev.workspace.stationGraphs[stationId];
        return {
          currentStationId: stationId,
          verifierReport: station ? verifyStationHyperGraph(station) : null,
          selectedEntity: null,
          focusedStepNo: null,
        };
      });
    },

    setZoomScale: (zoomScale) => {
      this.setState({ zoomScale });
    },

    setFocusedStepNo: (focusedStepNo) => {
      this.setState({ focusedStepNo });
    },

    setSelectedEntity: (selectedEntity) => {
      this.setState({ selectedEntity });
    },

    setActiveGhost: (activeGhost) => {
      this.setState({ activeGhost });
    },

    commitGhost: () => {
      const ghost = this.state.activeGhost;
      if (!ghost) return;
      if (!ghost.addedNodes.length && !ghost.addedGuardEdges.length && !ghost.addedTemporalSteps.length) return;
      this.setState((prev) => {
        const stationId = ghost.stationId || prev.currentStationId;
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return { activeGhost: null };

        const updatedStation: StationHyperGraph = {
          ...st,
          spatialNodes: [...st.spatialNodes, ...ghost.addedNodes],
          guardEdges: [...st.guardEdges, ...ghost.addedGuardEdges],
          temporalSteps: [...st.temporalSteps, ...ghost.addedTemporalSteps],
        };

        const updatedWs: AfStudioWorkspaceData = {
          ...prev.workspace,
          stationGraphs: {
            ...prev.workspace.stationGraphs,
            [stationId]: updatedStation,
          },
        };

        const nextReport = verifyStationHyperGraph(updatedStation);
        return {
          workspace: updatedWs,
          activeGhost: null,
          verifierReport: nextReport,
        };
      });
    },

    discardGhost: () => {
      this.setState({ activeGhost: null });
    },

    runVerification: () => {
      const { currentLayer, currentStationId, workspace } = this.state;
      const station = workspace.stationGraphs[currentStationId];
      const report = station
        ? verifyStationHyperGraph(station)
        : {
            passed: true,
            elapsedMs: 0,
            exploredStateCount: 0,
            violations: [],
            warnings: [],
          };
      this.setState({ verifierReport: report });
      return report;
    },

    applyAutoFix: (violation) => {
      if (!violation.suggestedGuardEdge) return;
      const suggested = violation.suggestedGuardEdge;
      this.setState((prev) => {
        const stationId = prev.currentStationId;
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};

        const alreadyExists = st.guardEdges.some((g) => g.id === suggested.id);
        const updatedGuards = alreadyExists
          ? st.guardEdges
          : [...st.guardEdges, suggested];

        const updatedStation: StationHyperGraph = {
          ...st,
          guardEdges: updatedGuards,
        };

        const updatedWs: AfStudioWorkspaceData = {
          ...prev.workspace,
          stationGraphs: {
            ...prev.workspace.stationGraphs,
            [stationId]: updatedStation,
          },
        };

        const nextReport = verifyStationHyperGraph(updatedStation);
        return {
          workspace: updatedWs,
          verifierReport: nextReport,
        };
      });
    },

    runCutSetTrace: (stationId, stepNo) => {
      const targetStationId = stationId ?? this.state.currentStationId;
      const targetStepNo = stepNo ?? (targetStationId === 'ST20' ? 20 : 10);
      const liveSignals = {
        'DB_ST10_CylTransfer.diHome': this.state.st10SensorHealthy,
        '%I0.4': this.state.st10SensorHealthy,
      };

      const result = traceMinimalFalsifyingCutSet(
        this.state.workspace.projectGraph,
        this.state.workspace.stationGraphs,
        targetStationId,
        targetStepNo,
        liveSignals
      );

      const firstStage = result.flyToStages[0] ?? null;
      this.setState({
        cutSetTrace: result,
        faultFlyActive: true,
        flyToStage: firstStage,
      });
      return result;
    },

    stepFaultCruise: (stageIndex) => {
      const trace = this.state.cutSetTrace;
      if (!trace) return;
      const targetStage =
        trace.flyToStages.find((s) => s.stageIndex === stageIndex) ?? null;
      this.setState({
        faultFlyActive: true,
        flyToStage: targetStage,
      });
    },

    stopFaultCruise: () => {
      this.setState({
        faultFlyActive: false,
        flyToStage: null,
      });
    },

    openModal: (modal) => {
      this.setState({ activeModal: modal });
    },

    closeModal: () => {
      this.setState({ activeModal: null });
    },

    toggleMerkleDrawer: (open) => {
      this.setState((prev) => ({
        isMerkleDrawerOpen: typeof open === 'boolean' ? open : !prev.isMerkleDrawerOpen,
      }));
    },

    toggleInspector: (open) => {
      this.setState((prev) => ({
        isInspectorOpen: typeof open === 'boolean' ? open : !prev.isInspectorOpen,
      }));
    },

    togglePaletteCollapse: () => {
      this.setState((prev) => ({
        paletteCollapsed: !prev.paletteCollapsed,
      }));
    },

    setSt10SensorHealthy: (healthy) => {
      this.setState({ st10SensorHealthy: healthy });
    },

    addNode: (stationId, node) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedStation: StationHyperGraph = {
          ...st,
          spatialNodes: [...st.spatialNodes, node],
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          selectedEntity: { kind: 'NODE', id: node.id },
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    updateNode: (stationId, nodeId, patch) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedNodes = st.spatialNodes.map((n) =>
          n.id === nodeId ? { ...n, ...patch } : n
        );
        const updatedStation: StationHyperGraph = {
          ...st,
          spatialNodes: updatedNodes,
        };
        const layoutOnly = Object.keys(patch).every(
          (k) => k === 'position' || k === 'isPinned'
        );
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          verifierReport: layoutOnly
            ? prev.verifierReport
            : verifyStationHyperGraph(updatedStation),
        };
      });
    },

    deleteNode: (stationId, nodeId) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedNodes = st.spatialNodes.filter((n) => n.id !== nodeId);
        const updatedGuards = st.guardEdges.filter(
          (g) => g.fromNode !== nodeId && g.toNode !== nodeId
        );
        const updatedSteps = st.temporalSteps
          .filter((s) => s.fromNode !== nodeId)
          .map((s) => ({
            ...s,
            invocations: s.invocations.filter((inv) => inv.targetNodeId !== nodeId),
          }))
          .filter((s) => s.invocations.length > 0);
        const updatedStation: StationHyperGraph = {
          ...st,
          spatialNodes: updatedNodes,
          guardEdges: updatedGuards,
          temporalSteps: updatedSteps,
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          selectedEntity:
            prev.selectedEntity?.id === nodeId ? null : prev.selectedEntity,
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    addGuardEdge: (stationId, edge) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedStation: StationHyperGraph = {
          ...st,
          guardEdges: [...st.guardEdges, edge],
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    updateGuardEdge: (stationId, edgeId, patch) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedGuards = st.guardEdges.map((g) =>
          g.id === edgeId ? { ...g, ...patch } : g
        );
        const updatedStation: StationHyperGraph = {
          ...st,
          guardEdges: updatedGuards,
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    deleteGuardEdge: (stationId, edgeId) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedGuards = st.guardEdges.filter((g) => g.id !== edgeId);
        const updatedStation: StationHyperGraph = {
          ...st,
          guardEdges: updatedGuards,
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          selectedEntity:
            prev.selectedEntity?.id === edgeId ? null : prev.selectedEntity,
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    addTemporalStep: (stationId, step) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedSteps = [...st.temporalSteps, step].sort(
          (a, b) => a.stepNo - b.stepNo
        );
        const updatedStation: StationHyperGraph = {
          ...st,
          temporalSteps: updatedSteps,
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    updateTemporalStep: (stationId, stepId, patch) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const updatedSteps = st.temporalSteps
          .map((s) => (s.id === stepId ? { ...s, ...patch } : s))
          .sort((a, b) => a.stepNo - b.stepNo);
        const updatedStation: StationHyperGraph = {
          ...st,
          temporalSteps: updatedSteps,
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    deleteTemporalStep: (stationId, stepId) => {
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        const removed = st.temporalSteps.find((s) => s.id === stepId);
        const updatedSteps = st.temporalSteps.filter((s) => s.id !== stepId);
        const updatedStation: StationHyperGraph = {
          ...st,
          temporalSteps: updatedSteps,
        };
        return {
          workspace: {
            ...prev.workspace,
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [stationId]: updatedStation,
            },
          },
          selectedEntity:
            prev.selectedEntity?.id === stepId ? null : prev.selectedEntity,
          focusedStepNo:
            removed && prev.focusedStepNo === removed.stepNo
              ? null
              : prev.focusedStepNo,
          verifierReport: verifyStationHyperGraph(updatedStation),
        };
      });
    },

    updateProjectStation: (nodeId, patch) => {
      this.setState((prev) => {
        const target = prev.workspace.projectGraph.stations.find(
          (s) => s.id === nodeId
        );
        if (!target) return {};
        const updatedStations = prev.workspace.projectGraph.stations.map((s) =>
          s.id === nodeId ? { ...s, ...patch } : s
        );
        let updatedStationGraphs = prev.workspace.stationGraphs;
        if (patch.title && prev.workspace.stationGraphs[target.stationId]) {
          updatedStationGraphs = {
            ...prev.workspace.stationGraphs,
            [target.stationId]: {
              ...prev.workspace.stationGraphs[target.stationId],
              stationName: patch.title,
            },
          };
        }
        return {
          workspace: {
            ...prev.workspace,
            projectGraph: {
              ...prev.workspace.projectGraph,
              stations: updatedStations,
            },
            stationGraphs: updatedStationGraphs,
          },
        };
      });
    },

    arrangeProjectStations: () => {
      this.setState(({ workspace }) => ({
        workspace: {
          ...workspace,
          projectGraph: {
            ...workspace.projectGraph,
            stations: workspace.projectGraph.stations.map((station, index) => ({ ...station, position: projectStationPosition(index) })),
          },
        },
      }));
    },

    deleteProjectStation: (nodeId) => {
      this.setState((prev) => {
        const target = prev.workspace.projectGraph.stations.find(
          (s) => s.id === nodeId
        );
        if (!target) return {};
        if (prev.workspace.projectGraph.stations.length <= 1) {
            const resetSt = buildBlankStationGraph(target.stationId, target.title);
            if (target.kind === 'LOGIC') resetSt.orchestration = { initialTool: '', operations: [] };
          return {
            workspace: {
              ...prev.workspace,
              projectGraph: {
                ...prev.workspace.projectGraph,
                stations: prev.workspace.projectGraph.stations.map((s) =>
                  s.id === nodeId
                    ? { ...s, instanceSummaries: ['待从左侧母版库拖入执行器实例'] }
                    : s
                ),
                edges: [],
              },
              stationGraphs: {
                [target.stationId]: resetSt,
              },
            },
            selectedEntity: null,
            focusedStepNo: null,
            verifierReport: verifyStationHyperGraph(resetSt),
          };
        }

        const remainingStations = prev.workspace.projectGraph.stations.filter(
          (s) => s.id !== nodeId
        );
        const remainingEdges = prev.workspace.projectGraph.edges.filter(
          (e) => e.fromNode !== nodeId && e.toNode !== nodeId
        );
        const nextStationGraphs = { ...prev.workspace.stationGraphs };
        delete nextStationGraphs[target.stationId];

        const nextCurrentId =
          prev.currentStationId === target.stationId
            ? remainingStations[0]?.stationId ?? ''
            : prev.currentStationId;
        const activeStation = nextStationGraphs[nextCurrentId];

        return {
          workspace: {
            ...prev.workspace,
            projectGraph: {
              ...prev.workspace.projectGraph,
              stations: remainingStations,
              edges: remainingEdges,
            },
            stationGraphs: nextStationGraphs,
          },
          currentStationId: nextCurrentId,
          selectedEntity:
            prev.selectedEntity?.id === nodeId ? null : prev.selectedEntity,
          focusedStepNo:
            prev.currentStationId === target.stationId ? null : prev.focusedStepNo,
          verifierReport: activeStation
            ? verifyStationHyperGraph(activeStation)
            : null,
        };
      });
    },

    addProjectEdge: (edge) => {
      this.setState((prev) => ({
        workspace: {
          ...prev.workspace,
          projectGraph: {
            ...prev.workspace.projectGraph,
            edges: [...prev.workspace.projectGraph.edges, edge],
          },
        },
        selectedEntity: { kind: 'L1_EDGE', id: edge.id },
      }));
    },

    updateProjectEdge: (edgeId, patch) => {
      this.setState((prev) => ({
        workspace: {
          ...prev.workspace,
          projectGraph: {
            ...prev.workspace.projectGraph,
            edges: prev.workspace.projectGraph.edges.map((e) =>
              e.id === edgeId ? { ...e, ...patch } : e
            ),
          },
        },
      }));
    },

    deleteProjectEdge: (edgeId) => {
      this.setState((prev) => ({
        workspace: {
          ...prev.workspace,
          projectGraph: {
            ...prev.workspace.projectGraph,
            edges: prev.workspace.projectGraph.edges.filter((e) => e.id !== edgeId),
          },
        },
        selectedEntity:
          prev.selectedEntity?.id === edgeId ? null : prev.selectedEntity,
      }));
    },

    createNewProject: (payload) => {
      const { workspace, initialStationId } = buildNewWorkspace(payload);
      const station = workspace.stationGraphs[initialStationId];
      this.commitState({
        workspace,
        currentLayer: 'STATION',
        currentStationId: initialStationId,
        zoomScale: 1.0,
        focusedStepNo: null,
        selectedEntity: null,
        activeGhost: null,
        verifierReport: station ? verifyStationHyperGraph(station) : null,
        cutSetTrace: null,
        faultFlyActive: false,
        flyToStage: null,
        activeModal: null,
        isMerkleDrawerOpen: false,
        isInspectorOpen: false,
        paletteCollapsed: this.state.paletteCollapsed,
        st10SensorHealthy: false,
        workspaceSaved: false,
      });
    },

    addStationToProject: (payload) => {
      this.setState((prev) => {
        const cleanId = payload.stationId.trim().toUpperCase().replace(/\s+/g, '_');
        if (!/^[A-Z][A-Z0-9_]*$/.test(cleanId) || Object.hasOwn(prev.workspace.stationGraphs, cleanId)) {
          return {};
        }
        const title = payload.title.trim() || `${cleanId} · 新建工站`;
        const source = prev.workspace.projectGraph.stations.find((station) => station.id === payload.copyFromId);
        if (payload.copyFromId && !source) return {};
        const kind = source?.kind ?? payload.kind ?? 'PHYSICAL';
        let idx = 0;
        while (prev.workspace.projectGraph.stations.some(({ position }) =>
          Math.abs(position.x - projectStationPosition(idx).x) < 264 && Math.abs(position.y - projectStationPosition(idx).y) < 140)) idx += 1;
        const compoundStation: ProjectCompoundStation = {
          id: `NODE_${cleanId}`,
          kind,
          stationId: cleanId,
          title,
          position: projectStationPosition(idx),
          isPinned: true,
          instanceSummaries: ['待从左侧母版库拖入执行器实例'],
          inPorts: [
            { id: 'P_UP', label: kind === 'LOGIC' ? '工位应答' : '操作请求', type: 'SEQ' },
            { id: 'P_GUARD_IN', label: '🛡️ 跨站安全护栏', type: 'GUARD' },
          ],
          outPorts: [
            { id: 'P_HANDOVER', label: kind === 'LOGIC' ? '工位调用' : '就绪 / 完成 / 故障', type: 'SEQ' },
            { id: 'P_SAFE_HOME', label: '🛡️ 工站在安全原位', type: 'GUARD' },
          ],
        };
        const newStationGraph = source
          ? cloneStationGraph(prev.workspace.stationGraphs[source.stationId], cleanId, title)
          : buildBlankStationGraph(cleanId, title);
        if (source) {
          compoundStation.inPorts = structuredClone(source.inPorts);
          compoundStation.outPorts = structuredClone(source.outPorts);
        }
        if (kind === 'LOGIC' && !newStationGraph.orchestration) {
          newStationGraph.orchestration = { initialTool: '', operations: [] };
        }
        return {
          workspace: {
            ...prev.workspace,
            projectGraph: {
              ...prev.workspace.projectGraph,
              stations: [...prev.workspace.projectGraph.stations, compoundStation],
            },
            stationGraphs: {
              ...prev.workspace.stationGraphs,
              [cleanId]: newStationGraph,
            },
          },
          currentStationId: cleanId,
          currentLayer: source ? 'PROJECT' : 'STATION',
          selectedEntity: null,
          focusedStepNo: null,
          verifierReport: source || kind === 'LOGIC' ? null : verifyStationHyperGraph(newStationGraph),
          activeGhost: null,
          activeModal: null,
          isInspectorOpen: false,
        };
      });
    },

    updateOrchestration: (stationId, orchestration) => {
      this.setState(({ workspace }) => {
        const station = workspace.stationGraphs[stationId];
        if (!station?.orchestration) return {};
        return {
          workspace: {
            ...workspace,
            stationGraphs: {
              ...workspace.stationGraphs,
              [stationId]: { ...station, orchestration },
            },
          },
        };
      });
    },

    saveFieldPoint: (point) => {
      const { workspace } = this.state;
      const error = pointError(workspace, point);
      if (error) return error;
      const points = workspace.fieldIoPoints ?? [];
      const saved = { ...point, name: point.name.trim(), address: parseFieldAddress(point.address, point.type)!.address };
      const fieldIoPoints = points.some(({ id }) => id === point.id)
        ? points.map((candidate) => candidate.id === point.id ? saved : candidate) : [...points, saved];
      this.setState({ workspace: { ...workspace, fieldIoPoints } });
    },

    deleteFieldPoint: (pointId) => {
      const { workspace } = this.state;
      if (fieldIoOwners(workspace, pointId).length) return '请先解除设备绑定，再删除点位';
      this.setState({ workspace: { ...workspace, fieldIoPoints: workspace.fieldIoPoints?.filter(({ id }) => id !== pointId) } });
    },

    bindFieldPoint: (stationId, nodeId, portId, pointId) => {
      const { workspace } = this.state;
      const node = workspace.stationGraphs[stationId]?.spatialNodes.find(({ id }) => id === nodeId);
      if (!node) return '该设备实例不存在';
      const error = bindingError(workspace, stationId, node, portId, pointId);
      if (error) return error;
      const fieldBindings = { ...node.fieldBindings };
      if (pointId) fieldBindings[portId] = pointId;
      else delete fieldBindings[portId];
      this.actions.updateNode(stationId, nodeId, node.cmProfile === 'Gripper@1'
        ? { fieldBindings, hasPartPresentSensor: Boolean(fieldBindings.diPartPresent) }
        : { fieldBindings });
    },

    applyHomingResult: (stationId, result) => {
      // Homing synthesis can update station logic / homing SCL metadata
      this.setState((prev) => {
        const st = prev.workspace.stationGraphs[stationId];
        if (!st) return {};
        return {
          activeModal: null,
        };
      });
    },

    resetWorkspace: () => {
      this.commitState(createInitialState());
    },
  };
}

export const defaultHyperGraphStoreManager = new HyperGraphStoreManager();

const UNSET_SELECTION = Symbol('unset_selection');

function shallowEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || a === null || typeof b !== 'object' || b === null) {
    return false;
  }
  const objA = a as Record<string, unknown>;
  const objB = b as Record<string, unknown>;
  const keysA = Object.keys(objA);
  const keysB = Object.keys(objB);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    if (!Object.prototype.hasOwnProperty.call(objB, key) || !Object.is(objA[key], objB[key])) {
      return false;
    }
  }
  return true;
}

/**
 * React Hook for AF-Studio v5 HyperGraph State.
 * Zero external dependencies (uses native React useSyncExternalStore with cached snapshots).
 */
export function useHyperGraphStore<T = HyperGraphStore>(
  selector?: (store: HyperGraphStore) => T,
  manager: HyperGraphStoreManager = defaultHyperGraphStoreManager
): T {
  const lastStoreRef = useRef<HyperGraphStore | null>(null);
  const lastSelectedRef = useRef<unknown>(UNSET_SELECTION);
  const selectorRef = useRef(selector);
  selectorRef.current = selector;

  const getSnapshot = useCallback((): T => {
    const store = manager.getStore();
    const sel = selectorRef.current;
    if (!sel) {
      return store as unknown as T;
    }
    if (lastStoreRef.current === store && lastSelectedRef.current !== UNSET_SELECTION) {
      return lastSelectedRef.current as T;
    }
    const nextSelected = sel(store);
    if (
      lastSelectedRef.current !== UNSET_SELECTION &&
      shallowEqual(lastSelectedRef.current, nextSelected)
    ) {
      lastStoreRef.current = store;
      return lastSelectedRef.current as T;
    }
    lastStoreRef.current = store;
    lastSelectedRef.current = nextSelected;
    return nextSelected;
  }, [manager]);

  return useSyncExternalStore(manager.subscribe, getSnapshot, getSnapshot);
}
