import type { CmDeviceProfile, FieldIoPoint } from './fieldIo';

/**
 * AF-Studio v5 正交超图核心数据契约 (G_AF = <V_spatial, E_guard, T_seq>)
 *
 * 将「空间物理唯一实例」「空间永久安全护栏」与「时序控制步序超边」严格正交分离，
 * 供前端算法引擎、编译器、Zustand 仓库与画布视口零漂移共享。
 */

export type DriverMotherClass =
  | 'FB_AF_AxisMotion'
  | 'FB_AF_Actuator2Pos'
  | 'FB_AF_Gripper'
  | 'FB_AF_Vacuum'
  | 'FB_AF_MotorStartStop'
  | 'FB_AF_VisionSensor'
  | 'FB_AF_DigitalInput'
  | 'FB_AF_Robot6Axis'
  | 'STATION_INPUT_PORT'
  | 'STATION_OUTPUT_PORT';

export interface SpatialPort {
  id: string;
  label: string;
  type: 'SEQ' | 'GUARD';
  isFaultLeaf?: boolean;
}

export type SpatialNodeTheme = 'klein' | 'emerald' | 'amber' | 'vermilion' | 'ink';

/** 1. 空间唯一实例节点 V_spatial (每个物理执行器在工站画布上永远只有 1 个节点) */
export interface SpatialInstanceNode {
  id: string;
  role: 'BOUNDARY_IN' | 'BOUNDARY_OUT' | 'ACTUATOR';
  title: string;
  driverClass: DriverMotherClass;
  instanceDb: string;
  position: { x: number; y: number };
  isPinned: boolean;
  hasPartPresentSensor?: boolean;
  discreteStates: string[];
  initialHomeState: string;
  cohesiveIoMap: Record<string, string>;
  cmProfile?: CmDeviceProfile;
  fieldBindings?: Record<string, string>;
  ioSummaryText?: string;
  theme?: SpatialNodeTheme;
  isPhysicalRootCause?: boolean;
  inPorts: SpatialPort[];
  outPorts: SpatialPort[];
}

export interface CrossStationGuardRef {
  upstreamStationId: string;
  upstreamInstanceId: string;
  upstreamPortId?: string;
  physicalTerminal: string;
  cabinetWireTag: string;
  l1EdgeId?: string;
}

/** 2. 空间永久安全护栏有向边 E_guard (编译至 i_bInterlockOK 与阻断诊断字) */
export interface SafetyGuardEdge {
  id: string;
  fromNode: string;
  fromPort: string;
  toNode: string;
  toPort: string;
  requiredSourceState: string;
  diagCodeHex: string;
  humanDescription: string;
  isHealthy?: boolean;
  crossStationRef?: CrossStationGuardRef;
}

export interface TemporalStepInvocation {
  targetNodeId: string;
  targetPortId?: string;
  methodId: string;
  actionLabel: string;
  targetDiscreteState: string;
  sclStatement: string;
  waitPredicateScl: string;
  waitDescription?: string;
}

/** 3. 时序控制超边 T_seq (代表单拍工步，支持单拍并发触发多个空间实例) */
export interface TemporalStepHyperEdge {
  id: string;
  stepNo: number;
  title: string;
  fromNode: string;
  fromPort: string;
  invocations: TemporalStepInvocation[];
  branchPredicate?: 'OK' | 'NG' | 'ALWAYS';
  requiresGuardNodeIds?: string[];
}

/** 4. 神经符号 AI 虚影事务补丁 (Ghost Diff Patch) */
export interface GhostGraphTransaction {
  txId: string;
  stationId: string;
  summary: string;
  addedNodes: SpatialInstanceNode[];
  addedGuardEdges: SafetyGuardEdge[];
  addedTemporalSteps: TemporalStepHyperEdge[];
  verificationPassed: boolean;
  verifierWarnings: string[];
}

export type StationKind = 'PHYSICAL' | 'LOGIC';

export interface StationOperation {
  stationId: string;
  command: string;
  mountedToolAfter?: string | null;
  allowInterrupt?: boolean;
}

export interface StationOrchestration {
  initialTool: string;
  operations: StationOperation[];
  interrupt?: { stationId: string; command: string };
  jobDispatch?: { stationId: string; durationSeconds?: number };
}

/** L1 产线复合工站节点 */
export interface ProjectCompoundStation {
  kind?: StationKind;
  id: string;
  stationId: string;
  title: string;
  position: { x: number; y: number };
  isPinned: boolean;
  instanceSummaries: string[];
  inPorts: SpatialPort[];
  outPorts: SpatialPort[];
}

/** L1 产线级交接/跨站护栏连线 */
export interface ProjectCompoundEdge {
  id: string;
  fromNode: string;
  fromPort: string;
  toNode: string;
  toPort: string;
  kind: 'SEQ' | 'GUARD';
  label: string;
  diagCodeHex?: string;
  isFaultCutSet?: boolean;
  managedByOrchestration?: boolean;
}

/** L1 产线复合超图容器 */
export interface ProjectHyperGraph {
  stations: ProjectCompoundStation[];
  edges: ProjectCompoundEdge[];
}

/** L2 工站正交超图容器 */
export interface StationHyperGraph {
  stationId: string;
  stationName: string;
  spatialNodes: SpatialInstanceNode[];
  guardEdges: SafetyGuardEdge[];
  temporalSteps: TemporalStepHyperEdge[];
  orchestration?: StationOrchestration;
}

/** AF-Studio 全局工作区事实源 */
export interface AfStudioWorkspaceData {
  projectName: string;
  projectGraph: ProjectHyperGraph;
  stationGraphs: Record<string, StationHyperGraph>;
  fieldIoPoints?: FieldIoPoint[];
}

export type SelectedHyperEntity = {
  kind: 'NODE' | 'GUARD' | 'STEP' | 'STATION' | 'L1_EDGE';
  id: string;
} | null;

/** 径向菜单动作候选项 */
export interface RadialMethodOption {
  methodId: string;
  label: string;
  waitDescription: string;
  sclCommand: string;
  targetDiscreteState: string;
  targetPortId?: string;
  feedbackMember?: string;
  isGuard?: boolean;
}

/** 算法一 (Auto-Homing) 单执行器归航动作 */
export interface HomingNodeAction {
  node: SpatialInstanceNode;
  partPresentProtected: boolean;
  sclSnippet: string;
  waitAtHomeExpr: string;
}

/** 算法一 (Auto-Homing) 分层拓扑合成结果 */
export interface HomingSynthesisResult {
  hasCycleDeadlock: boolean;
  cycleNodeIds: string[];
  cycleEdgeIds: string[];
  concurrentLayers: SpatialInstanceNode[][];
  layerActions: HomingNodeAction[][];
  generatedHomeScl: string;
}

/** 算法二 (Symbolic Verifier) 违例记录 */
export interface VerifierViolation {
  kind:
    | 'COLLISION_REACHABLE'
    | 'MISSING_GUARDRAIL'
    | 'ACTUATOR_CONTENTION'
    | 'GUARD_CYCLE_DEADLOCK'
    | 'UNREACHABLE_STEP';
  stepNo?: number;
  nodeId?: string;
  interferingNodeId?: string;
  message: string;
  suggestedGuardEdge?: SafetyGuardEdge;
}

/** 算法二 (Symbolic Verifier) 校验报告 */
export interface VerificationReport {
  passed: boolean;
  elapsedMs: number;
  exploredStateCount: number;
  violations: VerifierViolation[];
  warnings: string[];
}

/** 算法三 (Minimal Cut-Set Tracer) 镜头自动巡航阶段 */
export interface CameraFlyToStage {
  stageIndex: 1 | 2 | 3;
  layer: 'STATION' | 'PROJECT';
  stationId?: string;
  zoomScale: number;
  stageTag: string;
  description: string;
  focusEntityId: string;
}

/** 算法三 (Minimal Cut-Set Tracer) 跨站最小证伪割集定位结果 */
export interface CutSetTraceResult {
  blockedStationId: string;
  blockedStepNo: number;
  blockedNodeId: string;
  prunedHealthyEdgeIds: string[];
  falsifiedEdgeIds: string[];
  l1CutSetEdgeId?: string;
  rootCauseStationId: string;
  rootCauseNodeId: string;
  rootPhysicalTerminal: string;
  rootCabinetWireTag: string;
  diagnosisSummary: string;
  flyToStages: CameraFlyToStage[];
}

/** 多目标编译器块级产物 */
export interface CompiledBlockArtifact {
  blockName: string;
  blockType: 'FB' | 'FC' | 'DB';
  stationId: string;
  sclCode: string;
  merkleHash: string;
  fullSha256: string;
  interfaceHash: string;
  instanceDbName?: string;
}

/** Merkle 增量比对条目 */
export interface MerkleBlockDiffEntry {
  blockName: string;
  blockType: 'FB' | 'FC' | 'DB';
  merkleHash: string;
  previousHash?: string;
  status: 'DIRTY' | 'UNCHANGED';
  reason?: string;
  sclCode: string;
  interfaceHash: string;
}

/** Merkle 块级热同步清单 */
export interface MerkleSyncManifest {
  stationId: string;
  tiaTarget: string;
  dirtyCount: number;
  unchangedCount: number;
  estimatedSyncSeconds: number;
  entries: MerkleBlockDiffEntry[];
}
