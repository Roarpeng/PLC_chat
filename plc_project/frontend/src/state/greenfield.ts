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

export interface GFStepNode {
  id: string;
  em_id: string;
  step_id: number;
  name: string;
  actions: string[];
  transition_condition: string;
  next_step_id: number;
  error_step_id: number;
  timeout_ms: number;
  is_initial?: boolean;
  is_error?: boolean;
}

export interface GFStepEdge {
  id: string;
  src_id: string;
  dst_id: string;
  src_step_id?: number;
  dst_step_id?: number;
  kind: string;
  label: string;
}

export interface GFStepFlowView {
  mermaid: string;
  nodes: GFStepNode[];
  edges: GFStepEdge[];
  em_tabs: Array<{ id: string; name: string; business_label?: string; unit_id?: string; em_idx?: number }>;
}

export interface GFViews {
  flow: string;
  seq: string;
  state: string;
  step_flow?: GFStepFlowView;
  node_ids: Record<string, string[]>;
  edge_ids: Record<string, string[]>;
}

export interface GFHwNode {
  id: string;
  kind: string;
  label: string;
  slot: string;
  protocol: string;
  address_range: string;
  tag_count: number;
  mounted_cm_ids: string[];
  tags_preview?: Array<Record<string, unknown>>;
}

export interface GFNetLink {
  id: string;
  src_hw_id: string;
  dst_hw_id: string;
  protocol: string;
  label: string;
}

export interface GFVariableCatalog {
  external_io: Array<{
    key: string;
    name: string;
    logical_address: string;
    direction: string;
    data_type: string;
    comment: string;
    hw_node_id: string;
    locked: boolean;
    bound_targets: string[];
  }>;
  external_db: Array<{
    key: string;
    db_name: string;
    name: string;
    full_symbol: string;
    data_type: string;
    offset: number;
    initial_value: string;
    comment: string;
    hw_node_id: string;
    locked: boolean;
    bound_targets: string[];
  }>;
  internal_vars: Array<{
    key: string;
    group: string;
    owner_id: string;
    em_id: string;
    name: string;
    data_type: string;
    role: string;
    locked: boolean;
  }>;
  counts: {
    external_io: number;
    external_db: number;
    internal_vars: number;
  };
}

export interface GFHardwareTopology {
  nodes: GFHwNode[];
  links: GFNetLink[];
  variable_catalog: GFVariableCatalog;
  custom_var_bindings?: Array<{ var_key: string; target_id: string; role: string }>;
  /** 用户手工指定的挂载（cm_id → hw_node_id；可卸载回自动推导）。 */
  custom_cm_mounts?: Record<string, string>;
  /** 用户手工新增的硬件节点 id（可移除；其余为自动推导）。 */
  custom_node_ids?: string[];
}

export interface GFDeliverySummary {
  ok: boolean;
  project_name: string;
  spec_version: string;
  spec_hash: string;
  block_count: number;
  blocks_manifest: Array<{
    name: string;
    block_type: string;
    number: number;
    af_role: string;
    folder: string;
    path: string;
    sha256: string;
  }>;
  verification: {
    ok: boolean;
    linter_error_count: number;
    linter_warning_count: number;
    single_writer_audit: {
      ok: boolean;
      violations?: string[];
      total_q_tags: number;
      mapped_q_tags: number;
    };
    compat_integrity?: {
      ok: boolean;
    };
  };
  zip_filename: string;
  zip_sha256?: string;
  zip_size_bytes?: number;
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

/** 对话流消息（真值在后端会话，前端只渲染 state.messages）。 */
export interface GFChatMessage {
  id: string;
  role: "user" | "assistant" | "event";
  kind: string; // text | receipt | contract | views | validation | freeze | delivery | edit
  text: string;
  payload: Record<string, unknown>;
  ts: string;
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
  messages?: GFChatMessage[];
  hardware?: GFHardwareTopology | null;
  delivery_summary?: GFDeliverySummary | null;
  summary: { units: number; ems: number; cms: number; steps?: number; edges: number };
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

export async function updateHardware(
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/hardware`, jsonBody({ session_id: sessionId, ...payload }));
}

/** chat ↔ 画布 双向联动：问答 / LLM 增量修改 / 首版生成（服务端为唯一裁定）。 */
export async function sendChat(
  sessionId: string,
  message: string,
): Promise<{ state: GFState; reply: string; message: GFChatMessage }> {
  return requestPlc<{ state: GFState; reply: string; message: GFChatMessage }>(
    `${GF_API}/chat`,
    jsonBody({ session_id: sessionId, message }),
  );
}

export async function loadReferenceFixture(
  sessionId: string,
  prompt = "",
): Promise<GFState> {
  return requestPlc<GFState>(`${GF_API}/load-reference`, jsonBody({ session_id: sessionId, prompt }));
}

export async function generateProjectPackage(
  sessionId: string,
): Promise<{ delivery: GFDeliverySummary & Record<string, unknown> }> {
  return requestPlc<{ delivery: GFDeliverySummary & Record<string, unknown> }>(
    `${GF_API}/generate`,
    jsonBody({ session_id: sessionId }),
  );
}

/** 博途真机交付：XML 补充包 + PCEC 事务 + Openness 自动导入编译（不可用则诚实降级）。 */
export async function deliverTia(
  sessionId: string,
  mode: "auto" | "package" = "auto",
): Promise<{ delivery: Record<string, unknown> }> {
  return requestPlc<{ delivery: Record<string, unknown> }>(
    `${GF_API}/deliver-tia`,
    jsonBody({ session_id: sessionId, mode }),
  );
}

export function downloadPackageUrl(sessionId: string): string {
  return `${GF_API}/download-package?session_id=${encodeURIComponent(sessionId)}`;
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
  const kind = lower.endsWith(".pdf")
    ? "pdf"
    : lower.endsWith(".xlsx") || lower.endsWith(".xlsm") || lower.endsWith(".csv")
      ? "io"
      : "db";
  return { filename: file.name, content_base64: bytesToBase64(bytes), kind };
}

/** 前端出口断言：所有 Greenfield 端点均落在独立前缀，且不触碰存量端点。 */
export function isSafeGreenfieldPath(path: string): boolean {
  if (!path.startsWith(GF_API)) return false;
  return !FORBIDDEN_ENDPOINTS.some((forbidden) => path.includes(forbidden));
}
