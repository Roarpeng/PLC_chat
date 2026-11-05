/**
 * Greenfield 通道状态与网关访问层（T04）。
 *
 * 铁律：确认前**零 ops / 零写盘 / 零回写 / 零生成**。本模块只包含
 * `/api/v1/plc/canvas/greenfield/*` 端点，不引用任何存量重构 / 回写端点。
 * 用户可见文案零专业术语（业务化同义文案，工程视角可切换）。
 */
import { requestPlc } from "../lib/plcGateway";

export const GF_API = "/api/v1/plc/canvas/greenfield";
export const GF_SESSION_KEY = "greenfield.session_id";

export type GFStage = "DRAFT" | "LINKABLE" | "VALIDATING" | "FROZEN" | "LOCKED";

export interface GFEdge {
  id: string;
  kind: string;
  src_id: string;
  dst_id: string;
  view_mask: string[];
  origin?: string;
  label?: string;
  immutable?: boolean;
}

export interface GFViews {
  flow: string;
  seq: string;
  state: string;
  node_ids: Record<string, string[]>;
  edge_ids: Record<string, string[]>;
}

export interface GFViolation {
  code: string;
  view: string;
  node_id: string;
  edge_id: string;
  message: string;
}

export interface GFReport {
  ok: boolean;
  violations: GFViolation[];
  open_questions: string[];
  checked_at?: string;
  ir_sha256?: string;
}

export interface GFReceipt {
  receipt_id: string;
  status: string;
  items_total: number;
  items_accepted: number;
  errors: Array<{ file: string; row: number; column: string; code: string; message: string }>;
  user_confirmed: boolean;
  contract_draft_hash?: string;
}

export interface GFState {
  session_id: string;
  stage: GFStage;
  stage_label: string;
  locked_hint: string;
  has_ir: boolean;
  has_contract: boolean;
  receipt: GFReceipt | null;
  report: GFReport | null;
  specs: Array<{ spec_version: number; spec_hash: string; frozen_at: string }>;
  counters: Record<string, number>;
  engineering_summary_shown: boolean;
  notes: string[];
  ir: Record<string, unknown> | null;
  views: GFViews | null;
  summary: { units: number; ems: number; cms: number; edges: number };
  ir_only_fields: Array<{ field?: string; path?: string; label?: string; [key: string]: unknown }>;
}

export interface GFWhitelist {
  legal_edges: Array<{ kind: string; src_kinds: string[]; dst_kinds: string[]; views: string[]; note: string }>;
  illegal_edges: Array<{ code: string; reason: string }>;
  edge_kinds: string[];
  packml_states: string[];
  plcopen_signals: string[];
  limits: Record<string, number>;
  upload_error_codes: string[];
  forbidden_pregate_actions: string[];
  locked_hint: string;
}

export interface GFDraftPayload {
  format: "greenfield-draft-v1";
  session_id: string;
  source_stage?: string;
  ir?: unknown;
  [key: string]: unknown;
}

export const FORBIDDEN_ENDPOINTS = [
  "/canvas/confirm-writeback",
  "/canvas/compile-jobs",
  "/canvas/generate-from-requirement",
  "/canvas/generate-from-mermaid",
  "/canvas/refactor",
  "/canvas/chat-ops",
] as const;

function jsonBody(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  };
}

// ---------------------------------------------------------------- 会话保持
export function loadSessionId(): string | null {
  try {
    return window.localStorage.getItem(GF_SESSION_KEY);
  } catch {
    return null;
  }
}

export function saveSessionId(id: string): void {
  try {
    window.localStorage.setItem(GF_SESSION_KEY, id);
  } catch {
    /* 隐私模式下静默降级为内存态 */
  }
}

// ------------------------------------------------------------------ API 层
export async function fetchState(sessionId?: string | null): Promise<GFState> {
  const suffix = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return requestPlc<GFState>(`${GF_API}/state${suffix}`);
}

export async function fetchWhitelist(): Promise<GFWhitelist> {
  return requestPlc<GFWhitelist>(`${GF_API}/whitelist`);
}

export async function createDraft(sessionId: string, prompt: string): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/draft`, jsonBody({ session_id: sessionId, prompt }));
}

export async function uploadFiles(
  sessionId: string,
  items: Array<{ filename: string; content_base64?: string; text?: string; kind?: string }>,
): Promise<{ receipt: GFReceipt }> {
  return requestPlc<{ receipt: GFReceipt }>(
    `${GF_API}/upload`,
    jsonBody({ session_id: sessionId, items }),
  );
}

export async function confirmReceipt(sessionId: string): Promise<{ contract: Record<string, unknown> }> {
  return requestPlc<{ contract: Record<string, unknown> }>(
    `${GF_API}/receipt/confirm`,
    jsonBody({ session_id: sessionId }),
  );
}

export async function applyLinkPatch(sessionId: string, patch: Record<string, unknown>): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/links`, jsonBody({ session_id: sessionId, ...patch }));
}

export async function revalidate(sessionId: string): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/validate`, jsonBody({ session_id: sessionId }));
}

export async function fetchViews(sessionId: string): Promise<GFViews> {
  return requestPlc<GFViews>(`${GF_API}/views?session_id=${encodeURIComponent(sessionId)}`);
}

export async function fetchEngineeringSummary(sessionId: string): Promise<Record<string, unknown>> {
  return requestPlc<Record<string, unknown>>(
    `${GF_API}/engineering-summary`,
    jsonBody({ session_id: sessionId }),
  );
}

export async function confirmSpec(
  sessionId: string,
  explicit: boolean,
): Promise<{ spec: Record<string, unknown>; path: string; markdown: string }> {
  return requestPlc<{ spec: Record<string, unknown>; path: string; markdown: string }>(
    `${GF_API}/confirm`,
    jsonBody({ session_id: sessionId, explicit }),
  );
}

export async function beginEdit(sessionId: string): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/begin-edit`, jsonBody({ session_id: sessionId }));
}

export async function exportMermaid(sessionId: string): Promise<{ markdown: string }> {
  return requestPlc<{ markdown: string }>(
    `${GF_API}/export/mermaid?session_id=${encodeURIComponent(sessionId)}`,
  );
}

export async function exportDraft(sessionId: string): Promise<{ payload: GFDraftPayload }> {
  return requestPlc<{ payload: GFDraftPayload }>(
    `${GF_API}/draft/export`,
    jsonBody({ session_id: sessionId }),
  );
}

export async function importDraft(sessionId: string, payload: GFDraftPayload): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/draft/import`, jsonBody({ session_id: sessionId, payload }));
}

// -------------------------------------------------------------- 纯函数守卫
type SideEffectView = {
  counters: Record<string, number>;
  specs?: Array<{ spec_version: number; spec_hash: string; frozen_at: string }>;
  stage?: GFStage;
};

/** 与后端同口径：每次确认恰好一次 spec 写盘，其余计数恒为 0。 */
export function hasSideEffects(state: SideEffectView): boolean {
  const baseline = state.stage === "FROZEN" ? 0 : (state.specs?.length ?? 0);
  return Object.entries(state.counters ?? {}).some(
    ([key, value]) => value > (key === "disk_writes" ? baseline : 0),
  );
}

export function assertNoSideEffects(state: SideEffectView): void {
  if (state.stage === "FROZEN") return;
  if (hasSideEffects(state)) {
    throw new Error("规格尚未确认，确认前禁止任何生成或写回");
  }
}

export function canConfirm(state: GFState): boolean {
  if (state.stage !== "VALIDATING" && state.stage !== "LINKABLE") return false;
  if (!state.report?.ok) return false;
  if (!state.has_ir) return false;
  if (state.receipt && !state.receipt.user_confirmed) return false;
  if (hasSideEffects(state)) return false;
  return true;
}

export function gateReason(state: GFState): string {
  if (state.stage === "FROZEN") return "规格已冻结；生成标准工程属于下一阶段";
  if (state.stage === "LOCKED") return "当前会话已锁定";
  if (!state.has_ir) return "请先描述工艺，生成首版结构图";
  if (!state.report?.ok) return "结构校验尚未全部通过，请先修正连线";
  if (state.receipt && !state.receipt.user_confirmed) return "请先确认上传解析回执";
  if (hasSideEffects(state)) return "检测到未授权的副作用，已阻止确认";
  if (!state.engineering_summary_shown) return "请先在确认弹窗查看工程视角摘要";
  return "规格尚未确认，确认前禁止任何生成或写回";
}

export function shortHash(hash: string | undefined): string {
  if (!hash) return "—";
  return hash.replace(/^sha256:/, "").slice(0, 8);
}

/** 上传文件 → base64（纯函数层，便于单测；浏览器 File 在组件层读取）。 */
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export async function fileToUploadItem(file: File): Promise<{
  filename: string;
  content_base64: string;
  kind: string;
}> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const lower = file.name.toLowerCase();
  const kind = lower.endsWith(".xlsx") || lower.endsWith(".xlsm") || lower.endsWith(".csv") ? "io" : "db";
  return { filename: file.name, content_base64: bytesToBase64(bytes), kind };
}

/** 前端出口断言：所有 Greenfield 端点均落在独立前缀，且不触碰存量端点。 */
export function isSafeGreenfieldPath(path: string): boolean {
  if (!path.startsWith(GF_API)) return false;
  return !FORBIDDEN_ENDPOINTS.some((forbidden) => path.includes(forbidden));
}
