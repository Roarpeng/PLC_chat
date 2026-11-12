/**
 * V2 Workbench API facade + view-state reducer (WP-04 / Q-03 / US-2/3/6/7).
 *
 * HARD RULE: the frontend owns ONLY view/selection state. The EngineeringIR
 * truth lives on the server and is addressed by `revision` + `ir_sha256`.
 * Every edit goes through an atomic SequencePatch with `base_revision`;
 * Undo/Redo re-issue a patch against the CURRENT server revision and never
 * mutate a local copy of the truth.
 *
 * Compatibility: `gfRequest` unwraps `{data}` and loses the envelope, while V2
 * needs the envelope-level `evidence_level`. We therefore reuse `GF_BASE`,
 * `GFRequestError` and the 4xx-no-retry / 5xx-retry semantics, but keep the
 * full envelope in `wbRequestEnvelope`. No `greenfield.ts` export is changed.
 */
import { GF_BASE, GF_MAX_RETRIES, GFRequestError } from "./greenfield";
import type { EvidenceLevel } from "../workbench/featureFlags";

export const V2_API = "/api/v2";

/** Unified V2 envelope (superset of the v1 ApiResponse). */
export interface V2Envelope<T> {
  ok: boolean;
  code: number;
  data: T | null;
  message: string;
  error: { code: string; message: string; details?: unknown } | null;
  evidence_level: EvidenceLevel;
  request_id: string | null;
}

export interface ValidationIssue {
  source_id?: string;
  node_id?: string;
  field?: string;
  reason?: string;
}

export interface PatchResultV2 {
  revision: number;
  ir_sha256: string;
  changed_ir_ids: string[];
  source_map_dirty: string[];
  warnings: string[];
  evidence_level: EvidenceLevel;
  request_id: string;
  idempotent_hit: boolean;
  derived?: { manifest_sha256: string; trace_frames: number; scl_files: string[]; source_map_entries: number };
}

export interface JobView {
  job_id: string;
  state: string;
  native_artifact: { artifact_id: string; kind: string; sha256: string; size_bytes: number; reopen_ok: boolean } | null;
  evidence_level: EvidenceLevel;
  evidence_id: string;
  compile: { state: string; error_count: number; warning_count: number; compile_ok: boolean } | null;
  notice: string;
}

export interface SequencePatchBody {
  project_id: string;
  base_revision: number;
  request_id: string;
  ops: Array<Record<string, unknown>>;
}

/** Read a full V2 envelope (evidence_level preserved), 4xx never retried. */
export async function wbRequestEnvelope<T>(path: string, init?: RequestInit): Promise<V2Envelope<T>> {
  const url = `${GF_BASE}${V2_API}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  let lastFailure: GFRequestError | null = null;
  for (let attempt = 0; attempt <= GF_MAX_RETRIES; attempt += 1) {
    let res: Response;
    try {
      res = await fetch(url, { ...init, headers });
    } catch {
      throw new GFRequestError("网关不可达，工作区保持离线视图（未写入任何数据）。", {
        status: 0, code: "OFFLINE", offline: true,
      });
    }
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (res.ok) return body as V2Envelope<T>;
    const envelope = (body ?? {}) as Partial<V2Envelope<T>>;
    const dataCode = (envelope?.data as { code?: string } | null | undefined)?.code ?? "";
    const code = String(envelope?.error?.code ?? dataCode);
    const message = envelope?.message ?? envelope?.error?.message ?? `请求失败（HTTP ${res.status}）`;
    const failure = new GFRequestError(String(message), {
      status: res.status, code, details: envelope?.data, body,
    });
    lastFailure = failure;
    if (res.status < 500 || res.status === 503) break; // deterministic / client error
  }
  throw lastFailure ?? new GFRequestError("请求失败", { status: 0, code: "OFFLINE", offline: true });
}

/** Convenience: data only, for callers that checked evidence separately. */
export async function wbRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const envelope = await wbRequestEnvelope<T>(path, init);
  if (!envelope.ok || envelope.data === null) {
    throw new GFRequestError(envelope.message || "网关未返回数据", {
      status: envelope.code, code: envelope.error?.code ?? "EMPTY_DATA", body: envelope,
    });
  }
  return envelope.data;
}

const jsonInit = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const v2Api = {
  getIr: (projectId: string) =>
    wbRequestEnvelope<{ ir: Record<string, unknown>; revision: number; ir_sha256: string; derived_dirty: boolean }>(
      `/projects/${encodeURIComponent(projectId)}/ir`),
  patch: (body: SequencePatchBody) =>
    wbRequestEnvelope<PatchResultV2>(`/projects/${encodeURIComponent(body.project_id)}/patches`, jsonInit(body)),
  preview: (projectId: string, baseRevision: number, requestId: string) =>
    wbRequestEnvelope<Record<string, unknown>>(
      `/projects/${encodeURIComponent(projectId)}/preview`,
      jsonInit({ project_id: projectId, base_revision: baseRevision, request_id: requestId, include_scl: true })),
  simulate: (projectId: string, baseRevision: number, requestId: string, scenario = "normal_cycle") =>
    wbRequestEnvelope<Record<string, unknown>>(
      `/projects/${encodeURIComponent(projectId)}/simulate`,
      jsonInit({ project_id: projectId, base_revision: baseRevision, request_id: requestId, scenario })),
  validate: (projectId: string, baseRevision: number, requestId: string) =>
    wbRequestEnvelope<Record<string, unknown>>(
      `/projects/${encodeURIComponent(projectId)}/validate`,
      jsonInit({ project_id: projectId, base_revision: baseRevision, request_id: requestId })),
  job: (jobId: string) => wbRequestEnvelope<JobView>(`/delivery-jobs/${encodeURIComponent(jobId)}`),
  capability: () => wbRequestEnvelope<Record<string, unknown>>(`/capability`),
};

/* ------------------------------------------------------------------ state -- */

export type WorkbenchView = "overview" | "device" | "sequence" | "trace" | "diff" | "delivery";
export const WORKBENCH_VIEWS: ReadonlyArray<{ id: WorkbenchView; label: string }> = [
  { id: "overview", label: "① 项目总览" },
  { id: "device", label: "② 元器件驱动" },
  { id: "sequence", label: "③ 工艺步序" },
  { id: "trace", label: "④ 时序预览" },
  { id: "diff", label: "⑤ 变更审核" },
  { id: "delivery", label: "⑥ TIA 交付" },
];

export interface Diagnostic {
  sourceId: string;
  message: string;
  level: "error" | "warning" | "info";
}

export interface PatchRecord {
  ops: Array<Record<string, unknown>>;
  reverseOps: Array<Record<string, unknown>>;
  baseRevision: number;
  requestId: string;
}

export interface WorkbenchViewState {
  projectId: string;
  activeView: WorkbenchView;
  selectedNodeId: string | null;
  baseRevision: number;
  irSha256: string;
  evidenceLevel: EvidenceLevel;
  afProfile: string;
  diagnostics: Diagnostic[];
  nodeErrors: Record<string, string[]>;
  conflict: { code: string; currentRevision: number } | null;
  inspector: Record<string, unknown> | null;
  diagnosticsOpen: boolean;
  busy: boolean;
  optimistic: Record<string, unknown> | null;
  undoStack: PatchRecord[];
  redoStack: PatchRecord[];
  lastSync: { ir: string; trace: number; scl: string[] } | null;
}

export const initialViewState = (projectId: string): WorkbenchViewState => ({
  projectId,
  activeView: "overview",
  selectedNodeId: null,
  baseRevision: 0,
  irSha256: "",
  evidenceLevel: "pending_real_machine",
  afProfile: "SIEMENS_AF_BASIC_FOLDER_V19",
  diagnostics: [],
  nodeErrors: {},
  conflict: null,
  inspector: null,
  diagnosticsOpen: false,
  busy: false,
  optimistic: null,
  undoStack: [],
  redoStack: [],
  lastSync: null,
});

export type WorkbenchEvent =
  | { type: "IR_LOADED"; revision: number; irSha256: string; evidenceLevel: EvidenceLevel; ir: Record<string, unknown> }
  | { type: "SELECT_VIEW"; view: WorkbenchView }
  | { type: "SELECT_NODE"; nodeId: string | null; inspector?: Record<string, unknown> | null }
  | { type: "PATCH_START"; record: PatchRecord; optimistic?: Record<string, unknown> }
  | { type: "PATCH_OK"; result: PatchResultV2 }
  | { type: "PATCH_CONFLICT"; currentRevision: number }
  | { type: "PATCH_REJECTED"; issues: ValidationIssue[]; unchangedIrHash: string }
  | { type: "PATCH_TRANSPORT_ERROR"; message: string }
  | { type: "DERIVED_LOADED"; manifestSha256: string; traceFrames: number; sclFiles: string[] }
  | { type: "TOGGLE_DIAGNOSTICS" }
  | { type: "UNDO_READY"; record: PatchRecord }
  | { type: "RESET_CONFLICT" };

/** Pure reducer: no IR mutation, no local truth, no mock success. */
export function reduceViewState(state: WorkbenchViewState, event: WorkbenchEvent): WorkbenchViewState {
  switch (event.type) {
    case "IR_LOADED":
      return {
        ...state,
        baseRevision: event.revision,
        irSha256: event.irSha256,
        evidenceLevel: event.evidenceLevel,
        inspector: event.ir,
        conflict: null,
        optimistic: null,
        diagnostics: [...state.diagnostics.filter((d) => d.level !== "info"),
          { sourceId: "workspace", level: "info", message: `已从服务端读取权威 IR · revision ${event.revision}` }],
      };
    case "SELECT_VIEW":
      return { ...state, activeView: event.view };
    case "SELECT_NODE":
      return { ...state, selectedNodeId: event.nodeId, inspector: event.inspector ?? state.inspector };
    case "PATCH_START":
      return { ...state, busy: true, conflict: null, optimistic: event.optimistic ?? null,
        undoStack: [...state.undoStack, event.record], redoStack: [] };
    case "PATCH_OK": {
      const derived = event.result.derived;
      return {
        ...state,
        busy: false,
        optimistic: null,
        conflict: null,
        nodeErrors: {},
        baseRevision: event.result.revision,
        irSha256: event.result.ir_sha256,
        evidenceLevel: event.result.evidence_level,
        lastSync: derived
          ? { ir: event.result.ir_sha256, trace: derived.trace_frames, scl: derived.scl_files }
          : state.lastSync,
        diagnostics: [
          { sourceId: "patch", level: "info", message: `已提交 revision ${event.result.revision} · ${event.result.changed_ir_ids.join(", ") || "UI 布局"}` },
          ...event.result.warnings.map((w) => ({ sourceId: "patch", level: "warning" as const, message: w })),
        ],
      };
    }
    case "PATCH_CONFLICT":
      return {
        ...state, busy: false, optimistic: null,
        conflict: { code: "BASE_REVISION_CONFLICT", currentRevision: event.currentRevision },
        undoStack: state.undoStack.slice(0, -1),
        diagnostics: [{ sourceId: "patch", level: "error",
          message: `409 BASE_REVISION_CONFLICT：服务端 current_revision=${event.currentRevision}，请重新拉取 IR 后合并` }],
      };
    case "PATCH_REJECTED": {
      const nodeErrors: Record<string, string[]> = {};
      for (const issue of event.issues) {
        const id = issue.node_id || issue.source_id || "unknown";
        nodeErrors[id] = [...(nodeErrors[id] ?? []), issue.reason ?? "语义校验失败"];
      }
      return {
        ...state, busy: false, optimistic: null, nodeErrors,
        undoStack: state.undoStack.slice(0, -1),
        irSha256: event.unchangedIrHash || state.irSha256,
        diagnostics: event.issues.map((i) => ({ sourceId: i.source_id ?? "unknown", level: "error" as const,
          message: `422 ${i.reason ?? "语义校验失败"}` })),
        diagnosticsOpen: true,
      };
    }
    case "PATCH_TRANSPORT_ERROR":
      return { ...state, busy: false, optimistic: null, undoStack: state.undoStack.slice(0, -1),
        diagnostics: [{ sourceId: "transport", level: "error", message: event.message }], diagnosticsOpen: true };
    case "DERIVED_LOADED":
      return { ...state, lastSync: { ir: state.irSha256, trace: event.traceFrames, scl: event.sclFiles } };
    case "TOGGLE_DIAGNOSTICS":
      return { ...state, diagnosticsOpen: !state.diagnosticsOpen };
    case "UNDO_READY":
      return { ...state, undoStack: state.undoStack.slice(0, -1), redoStack: [...state.redoStack, event.record] };
    case "RESET_CONFLICT":
      return { ...state, conflict: null };
    default:
      return state;
  }
}

/* --------------------------------------------------------------- helpers -- */

let requestSeq = 0;
export function newRequestId(): string {
  requestSeq += 1;
  return `req_wb_${Date.now().toString(36)}_${requestSeq}`;
}

/** Build an atomic SequencePatch for a step parameter edit (US-2). */
export function buildSequencePatch(
  projectId: string, baseRevision: number, stepId: string, field: string, value: unknown,
): SequencePatchBody {
  return {
    project_id: projectId,
    base_revision: baseRevision,
    request_id: newRequestId(),
    ops: [{ op: "set_step_parameter", step_id: stepId, field, value, source_id: stepId }],
  };
}

/** Undo/Redo must re-issue a patch against the CURRENT server revision. */
export function rebasePatch(record: PatchRecord, currentRevision: number): SequencePatchBody {
  return {
    project_id: "__rebased__",
    base_revision: currentRevision,
    request_id: newRequestId(),
    ops: record.reverseOps,
  };
}

/** US-3: IR / Trace / SCL are in sync only when all three changed together. */
export function deriveSyncCheck(before: WorkbenchViewState["lastSync"], after: WorkbenchViewState["lastSync"]): boolean {
  if (!before || !after) return false;
  return before.ir !== after.ir && before.trace !== after.trace && before.scl.join("|") === after.scl.join("|");
}

/** US-7: a native download button is allowed ONLY with a V19 real full chain. */
export function canShowNativeDownload(job: JobView | null): boolean {
  return Boolean(
    job && job.state === "NATIVE_ARCHIVED" && job.evidence_level === "V19_real"
      && job.native_artifact && job.native_artifact.artifact_id && job.native_artifact.reopen_ok,
  );
}

/** The source package is explicitly NOT a native TIA project. */
export const SOURCE_PACKAGE_NOTICE = "源码包就绪（非原生工程）";
export const PENDING_REAL_MACHINE_NOTICE = "编译结果 pending_real_machine · 归档 SHA256 未生成 · 无原生归档终态";

export function deliveryNotice(job: JobView | null): string {
  if (!job) return PENDING_REAL_MACHINE_NOTICE;
  if (canShowNativeDownload(job)) return "V19 real 全链回执：可下载真实 .zap19 与 evidence bundle";
  if (job.state === "FAILED" || job.state === "RECOVERY_REQUIRED") return "交付失败或需恢复：仅提供诊断报告，不提供原生归档";
  return PENDING_REAL_MACHINE_NOTICE;
}
