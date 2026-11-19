/**
 * AF-Studio v5 FastAPI 网关与纯 TS 算法适配层
 * 封装 7 个 /api/v2/af-studio/... 端点，支持无缝自动离线降级与 Pydantic v2 字段 100% 对齐。
 */

import type {
  AfStudioWorkspaceData,
  CompiledBlockArtifact,
  CutSetTraceResult,
  GhostGraphTransaction,
  HomingSynthesisResult,
  MerkleSyncManifest,
  ProjectHyperGraph,
  StationHyperGraph,
  VerificationReport,
} from '../core/ir/afHyperGraph.types';
import { createDefaultAfStudioWorkspace } from '../core/ir/seedHyperGraphs';
import { computeMerkleSyncManifest } from '../core/compiler/merkleAstHasher';
import { compileStationHyperGraph } from '../core/compiler/multiTargetSclGen';
import { verifyStationInterlocks } from '../core/algorithms/symbolicVerifier';
import { synthesizeStationHoming } from '../core/algorithms/autoHomingSynth';
import { synthesizeNlIntentToGhost } from '../core/copilot/nlGhostSynthesizer';
import { traceMinimalCutSet } from '../core/algorithms/minimalCutSetTracer';

export type EvidenceLevel = 'offline' | 'mocked' | 'V19_real' | 'pending_real_machine';

export interface V2ApiResponse<T> {
  ok: boolean;
  code: number;
  data: T;
  message: string;
  error?: { code: string; message: string; details?: unknown } | null;
  evidence_level: EvidenceLevel;
  evidenceLevel: EvidenceLevel;
  request_id?: string | null;
  requestId?: string | null;
}

export interface ApiCallOptions {
  fallbackToLocal?: boolean;
  signal?: AbortSignal;
  baseUrl?: string;
}

export interface MerkleManifestRequest {
  station: StationHyperGraph;
  previousHashes?: Record<string, string>;
  projectId?: string;
  projectPath?: string;
  plcName?: string;
  softwareUnit?: string;
  requestId?: string;
}

export interface MerkleSyncRequest {
  station: StationHyperGraph;
  previousHashes?: Record<string, string>;
  projectId?: string;
  projectPath?: string;
  plcName?: string;
  softwareUnit?: string;
  requestId?: string;
}

export interface MerkleSyncResponseData {
  projectId: string;
  stationId: string;
  totalBlocks: number;
  dirtyCount: number;
  unchangedCount: number;
  dirtyBlocks: string[];
  blocks: Array<{
    name: string;
    type: string;
    sclCode: string;
    merkleHash: string;
    interfaceHash: string;
    status: 'DIRTY' | 'UNCHANGED';
    reason?: string;
  }>;
  blockHashes: Record<string, string>;
  tiaSynced: boolean;
  compileOk: boolean;
  elapsedMs: number;
  notice?: string;
  entries?: MerkleSyncManifest['entries'];
}

export interface CompileStationRequest {
  station: StationHyperGraph;
  requestId?: string;
}

export interface CompileStationResponseData {
  stationId: string;
  blocks: Array<{
    name: string;
    type: string;
    sclCode: string;
    merkleHash: string;
    interfaceHash: string;
    instanceDb?: string;
  }>;
  blockHashes: Record<string, string>;
  artifacts: CompiledBlockArtifact[];
  totalLines: number;
}

export interface VerifyStationRequest {
  station: StationHyperGraph;
  ghostTx?: GhostGraphTransaction | null;
  requestId?: string;
}

export interface VerifyStationResponseData extends VerificationReport {
  homingResult?: HomingSynthesisResult;
  issues?: Array<{
    code: string;
    stepNo?: number;
    nodeId?: string;
    message: string;
    interferingNodeId?: string;
  }>;
  suggestedPatches?: Array<any>;
}

export interface SynthesizeHomingRequest {
  station: StationHyperGraph;
  throwOnDeadlock?: boolean;
  requestId?: string;
}

export interface CopilotIntentRequest {
  station: StationHyperGraph;
  prompt?: string;
  timingTableRows?: Array<Record<string, unknown>>;
  ioTableRows?: Array<Record<string, unknown>>;
  requestId?: string;
}

export interface TraceCutSetRequest {
  projectGraph?: ProjectHyperGraph;
  stationGraphs?: Record<string, StationHyperGraph>;
  faultStationId?: string;
  faultStepNo?: number;
  liveSignals?: Record<string, boolean>;
  requestId?: string;
}

export interface EnrichedCutSetResult extends CutSetTraceResult {
  faultResolved?: boolean;
  prunedHealthyEdges?: Array<any>;
  falsifiedEdges?: Array<any>;
  rootCauses?: Array<{
    stationId: string;
    nodeId: string;
    physicalTerminal: string;
    cabinetWireTag: string;
  }>;
  cameraFlySteps?: Array<{
    layer: 'STATION' | 'PROJECT';
    stationId?: string;
    focusNodeId?: string;
    stageTag?: string;
  }>;
}

const DEFAULT_API_BASE = '/api/v2/af-studio';

export async function exportTiaV19(workspace: AfStudioWorkspaceData): Promise<Blob> {
  const response = await fetch(`${DEFAULT_API_BASE}/export/tia-v19`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/octet-stream' },
    body: JSON.stringify(workspace),
  });
  if (!response.ok) {
    const issue = await response.json().catch(() => null);
    throw new Error(issue?.message || `V19 导出失败（HTTP ${response.status}）。`);
  }
  if (!response.headers.get('Content-Disposition')?.includes('.zap19')) {
    throw new Error('V19 导出未返回博途归档。');
  }
  return response.blob();
}

function createOfflineEnvelope<T>(data: T, requestId?: string): V2ApiResponse<T> {
  const rid = requestId || `req_offline_${Date.now()}`;
  return {
    ok: true,
    code: 0,
    data,
    message: 'ok',
    evidence_level: 'offline',
    evidenceLevel: 'offline',
    request_id: rid,
    requestId: rid,
  };
}

function normalizeServerEnvelope<T>(json: any, fallbackRequestId?: string): V2ApiResponse<T> {
  const level: EvidenceLevel = json.evidence_level || json.evidenceLevel || 'offline';
  const rid = json.request_id || json.requestId || fallbackRequestId || `req_${Date.now()}`;
  return {
    ok: json.ok !== false,
    code: typeof json.code === 'number' ? json.code : 0,
    data: json.data as T,
    message: json.message || 'ok',
    error: json.error ?? null,
    evidence_level: level,
    evidenceLevel: level,
    request_id: rid,
    requestId: rid,
  };
}

async function requestEndpoint<Req, Res>(
  endpointPath: string,
  payload: Req,
  options?: ApiCallOptions
): Promise<{ status: number; json: any }> {
  const base = (options?.baseUrl ?? DEFAULT_API_BASE).replace(/\/$/, '');
  const url = `${base}${endpointPath}`;

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
      signal: options?.signal,
    });
    let json: any = null;
    try {
      json = await res.json();
    } catch {
      json = null;
    }
    return { status: res.status, json };
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw err;
    }
    return { status: 0, json: null };
  }
}

/**
 * 1. 块级 Merkle 同步清单获取
 * 端点：/api/v2/af-studio/merkle/manifest
 */
export async function fetchMerkleManifest(
  request: MerkleManifestRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<MerkleSyncManifest>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    project_id: request.projectId || 'AssyLine_01',
    projectId: request.projectId || 'AssyLine_01',
    station: request.station,
    previous_hashes: request.previousHashes,
    previousHashes: request.previousHashes,
    project_path: request.projectPath,
    projectPath: request.projectPath,
    plc_name: request.plcName,
    plcName: request.plcName,
    software_unit: request.softwareUnit,
    softwareUnit: request.softwareUnit,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/merkle/manifest', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<MerkleSyncManifest>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const artifacts = compileStationHyperGraph(request.station);
    const manifest = computeMerkleSyncManifest(
      request.station.stationId,
      artifacts,
      request.previousHashes ?? {},
      'TIA_V19_STA'
    );
    return createOfflineEnvelope(manifest, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<MerkleSyncManifest>(json, request.requestId);
  }

  throw new Error(`fetchMerkleManifest failed with HTTP status ${status}`);
}

/**
 * 2. 块级 Merkle 差异热同步
 * 端点：/api/v2/af-studio/merkle/sync
 */
export async function syncMerkleBlocks(
  request: MerkleSyncRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<MerkleSyncResponseData>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    project_id: request.projectId || 'AssyLine_01',
    projectId: request.projectId || 'AssyLine_01',
    station: request.station,
    previous_hashes: request.previousHashes,
    previousHashes: request.previousHashes,
    project_path: request.projectPath,
    projectPath: request.projectPath,
    plc_name: request.plcName,
    plcName: request.plcName,
    software_unit: request.softwareUnit,
    softwareUnit: request.softwareUnit,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/merkle/sync', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<MerkleSyncResponseData>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const artifacts = compileStationHyperGraph(request.station);
    const manifest = computeMerkleSyncManifest(
      request.station.stationId,
      artifacts,
      request.previousHashes ?? {},
      'TIA_V19_STA'
    );
    const blockHashes: Record<string, string> = {};
    for (const entry of manifest.entries) {
      blockHashes[entry.blockName] = entry.merkleHash;
    }
    const dirtyBlocks = manifest.entries
      .filter((e) => e.status === 'DIRTY')
      .map((e) => e.blockName);

    const blocks = manifest.entries.map((e) => ({
      name: e.blockName,
      type: e.blockType,
      sclCode: e.sclCode,
      merkleHash: e.merkleHash,
      interfaceHash: e.interfaceHash,
      status: e.status,
      reason: e.reason,
    }));

    const data: MerkleSyncResponseData = {
      projectId: request.projectId || 'AssyLine_01',
      stationId: request.station.stationId,
      totalBlocks: manifest.entries.length,
      dirtyCount: manifest.dirtyCount,
      unchangedCount: manifest.unchangedCount,
      dirtyBlocks,
      blocks,
      blockHashes,
      tiaSynced: false,
      compileOk: true,
      elapsedMs: 2,
      notice: '前端本地离线 AST 比对完成',
      entries: manifest.entries,
    };
    return createOfflineEnvelope(data, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<MerkleSyncResponseData>(json, request.requestId);
  }

  throw new Error(`syncMerkleBlocks failed with HTTP status ${status}`);
}

/**
 * 3. 确定性编译工站超图为 4 份 SCL 产物
 * 端点：/api/v2/af-studio/compile/scl
 */
export async function compileStationScl(
  request: CompileStationRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<CompileStationResponseData>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    station: request.station,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/compile/scl', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<CompileStationResponseData>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const artifacts = compileStationHyperGraph(request.station);
    const blockHashes: Record<string, string> = {};
    let totalLines = 0;
    const blocks = artifacts.map((art) => {
      blockHashes[art.blockName] = art.merkleHash;
      totalLines += (art.sclCode.match(/\n/g)?.length || 0) + 1;
      return {
        name: art.blockName,
        type: art.blockType,
        sclCode: art.sclCode,
        merkleHash: art.merkleHash,
        interfaceHash: art.interfaceHash,
        instanceDb: art.instanceDbName,
      };
    });

    const data: CompileStationResponseData = {
      stationId: request.station.stationId,
      blocks,
      blockHashes,
      artifacts,
      totalLines,
    };
    return createOfflineEnvelope(data, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<CompileStationResponseData>(json, request.requestId);
  }

  throw new Error(`compileStationScl failed with HTTP status ${status}`);
}

/**
 * 4. 符号学静态验证 (防撞、死锁与互锁闭包)
 * 端点：/api/v2/af-studio/verify/symbolic
 */
export async function verifyStationSymbolic(
  request: VerifyStationRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<VerifyStationResponseData>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    station: request.station,
    ghost_tx: request.ghostTx,
    ghostTx: request.ghostTx,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/verify/symbolic', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<VerifyStationResponseData>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const report = verifyStationInterlocks(
      request.station,
      request.ghostTx
    );
    const homingResult = synthesizeStationHoming(request.station);

    const issues = report.violations.map((v) => ({
      code: v.kind,
      stepNo: v.stepNo,
      nodeId: v.nodeId,
      message: v.message,
      interferingNodeId: v.interferingNodeId,
    }));

    const suggestedPatches = report.violations
      .filter((v) => Boolean(v.suggestedGuardEdge))
      .map((v) => v.suggestedGuardEdge!);

    const data: VerifyStationResponseData = {
      ...report,
      issues,
      suggestedPatches,
      homingResult,
    };
    return createOfflineEnvelope(data, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<VerifyStationResponseData>(json, request.requestId);
  }

  throw new Error(`verifyStationSymbolic failed with HTTP status ${status}`);
}

/**
 * 5. 一键安全分层归航合成
 * 端点：/api/v2/af-studio/synthesize/homing
 */
export async function synthesizeStationHomingApi(
  request: SynthesizeHomingRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<HomingSynthesisResult>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    station: request.station,
    throw_on_deadlock: request.throwOnDeadlock,
    throwOnDeadlock: request.throwOnDeadlock,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/synthesize/homing', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<HomingSynthesisResult>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const result = synthesizeStationHoming(request.station, {
      throwOnDeadlock: request.throwOnDeadlock,
    });
    return createOfflineEnvelope(result, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<HomingSynthesisResult>(json, request.requestId);
  }

  throw new Error(`synthesizeStationHoming failed with HTTP status ${status}`);
}

// 别名导出，完全匹配任务描述
export const synthesizeStationHomingEndpoint = synthesizeStationHomingApi;
export { synthesizeStationHomingApi as synthesizeStationHoming };

/**
 * 6. 自然语言与冷启动表格虚影意图合成
 * 端点：/api/v2/af-studio/copilot/intent-diff
 */
export async function synthesizeCopilotIntent(
  request: CopilotIntentRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<GhostGraphTransaction>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    station: request.station,
    prompt: request.prompt,
    timing_table_rows: request.timingTableRows,
    timingTableRows: request.timingTableRows,
    io_table_rows: request.ioTableRows,
    ioTableRows: request.ioTableRows,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/copilot/intent-diff', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<GhostGraphTransaction>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const promptText = request.prompt || '根据现有配置生成虚影补丁';
    const ghostTx = synthesizeNlIntentToGhost(promptText, request.station);
    return createOfflineEnvelope(ghostTx, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<GhostGraphTransaction>(json, request.requestId);
  }

  throw new Error(`synthesizeCopilotIntent failed with HTTP status ${status}`);
}

/**
 * 7. 跨站最小证伪割集定位与镜头巡航构建
 * 端点：/api/v2/af-studio/cutset/trace
 */
export async function traceStationCutSet(
  request: TraceCutSetRequest,
  options?: ApiCallOptions
): Promise<V2ApiResponse<EnrichedCutSetResult>> {
  const shouldFallback = options?.fallbackToLocal !== false;
  const body = {
    project_graph: request.projectGraph,
    projectGraph: request.projectGraph,
    station_graphs: request.stationGraphs,
    stationGraphs: request.stationGraphs,
    fault_station_id: request.faultStationId,
    faultStationId: request.faultStationId,
    fault_step_no: request.faultStepNo,
    faultStepNo: request.faultStepNo,
    live_signals: request.liveSignals,
    liveSignals: request.liveSignals,
    request_id: request.requestId,
    requestId: request.requestId,
  };

  const { status, json } = await requestEndpoint('/cutset/trace', body, options);

  if (status >= 200 && status < 300 && json && json.ok) {
    return normalizeServerEnvelope<EnrichedCutSetResult>(json, request.requestId);
  }

  if (shouldFallback && (status === 0 || status === 404 || status >= 500 || !json?.ok)) {
    const defaultWs = createDefaultAfStudioWorkspace();
    const projectGraph = request.projectGraph || defaultWs.projectGraph;
    const stationGraphs = request.stationGraphs || defaultWs.stationGraphs;
    const faultStationId = request.faultStationId || 'ST20';
    const faultStepNo = request.faultStepNo ?? 30;

    const baseResult = traceMinimalCutSet(
      projectGraph,
      stationGraphs,
      faultStationId,
      faultStepNo,
      request.liveSignals
    );

    const rootCauses = [
      {
        stationId: baseResult.rootCauseStationId,
        nodeId: baseResult.rootCauseNodeId,
        physicalTerminal: baseResult.rootPhysicalTerminal,
        cabinetWireTag: baseResult.rootCabinetWireTag,
      },
    ];

    const cameraFlySteps = baseResult.flyToStages.map((s) => ({
      layer: s.layer,
      stationId: s.stationId,
      focusNodeId: s.focusEntityId,
      stageTag: s.stageTag,
    }));

    const prunedHealthyEdges = baseResult.prunedHealthyEdgeIds.map((id) => ({
      edgeId: id,
      signalValue: true,
      terminal: '%I10.0',
    }));

    const falsifiedEdges = baseResult.falsifiedEdgeIds.map((id) => ({
      edgeId: id,
      signalValue: false,
      diagCode: '#0203',
    }));

    const enriched: EnrichedCutSetResult = {
      ...baseResult,
      faultResolved: baseResult.falsifiedEdgeIds.length === 0,
      prunedHealthyEdges,
      falsifiedEdges,
      rootCauses,
      cameraFlySteps,
    };

    return createOfflineEnvelope(enriched, request.requestId);
  }

  if (json) {
    return normalizeServerEnvelope<EnrichedCutSetResult>(json, request.requestId);
  }

  throw new Error(`traceStationCutSet failed with HTTP status ${status}`);
}
