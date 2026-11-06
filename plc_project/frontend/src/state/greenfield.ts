/**
 * Greenfield 通道状态与网关访问层（Agent D · 前端批次）。
 *
 * 铁律：确认前**零 ops / 零写盘 / 零回写 / 零生成**。本模块只包含
 * `/api/v1/plc/canvas/greenfield/*` 端点，不引用任何存量重构 / 回写端点。
 * 用户可见文案零专业术语（业务化同义文案，工程视角可切换）。
 *
 * 本批次新增（契约 04-parallel-wp-contract.md §3 / §4）：
 *  - 自带 `gfRequest` 封装：Base URL 走环境变量、令牌可选、错误映射可读中文、
 *    4xx 不重试、5xx 最多重试 3 次、fetch 失败给出离线提示；
 *  - `project_id` 一等公民：新建向导第一步生成并贯穿会话 / 拓扑 / 资料 / 规格 / 产物；
 *  - 对话绑定 `project_id` 并注入「已定拓扑」约束，复用 `GFSpecMeta.open_questions`
 *    与 `GFInterlock.source == "inferred"` 现成机制，禁止另起炉灶；
 *  - `/patch`、`/diff`、`/confirm-diff`、`/specs/{v}` 四个新端点的前端封装；
 *  - 确认硬门禁五项前置、差异清单显式确认（D11）、反向保护（D10）、
 *    fidelity 与编译诊断的展示层状态。
 *
 * 注意：不修改 `lib/plcGateway.ts`（不属本批次所有权），本模块自建封装以承载
 * Greenfield 专有的重试 / 错误 / 离线语义；IR 语义一律不改，只做展示层改造。
 */
import { newProjectId as makeProjectId } from "./projects";

export const GF_API = "/api/v1/plc/canvas/greenfield";
export const GF_SESSION_KEY = "greenfield.session_id";
export const GF_PROJECT_KEY = "greenfield.project_id";
export const GF_LAUNCH_CONTEXT_KEY = "greenfield.launch_context";

/**
 * 网关基址：一律走环境变量 `VITE_GATEWAY_URL`；未配置时为空串＝同源相对路径
 * （Vite 代理 / nginx 同源 `/api`），**禁止**在代码里硬编码后端主机或端口。
 */
const rawGateway = import.meta.env.VITE_GATEWAY_URL as string | undefined;
export const GF_BASE = rawGateway === undefined ? "" : String(rawGateway).replace(/\/$/, "");

/** 可选访问令牌（环境变量注入，未配置时不发送 Authorization 头）。 */
const rawToken = import.meta.env.VITE_PLC_API_TOKEN as string | undefined;

/** 5xx 最多重试 3 次（即初次 + 3 次重试 = 最多 4 次请求）。 */
export const GF_MAX_RETRIES = 3;

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

/* --------------------------------------------------------------------------
 * 契约 §2 / §4 对应类型（只读展示层；IR 语义不变）
 * -------------------------------------------------------------------------- */

/** 后端 `GFSpecMeta` 的展示层投影：`open_questions` 是确认硬门禁的现成载体。 */
export interface GFSpecMeta {
  spec_version?: string;
  spec_hash?: string;
  prev_spec_hash?: string | null;
  stage?: string;
  frozen_at?: string | null;
  frozen_by?: string | null;
  contract_hashes?: string[];
  receipt_id?: string;
  open_questions: string[];
}

/**
 * 后端 `GFInterlock` 的展示层投影：`source === "inferred"` 自动进「待确认问题」，
 * 复用既有机制（greenfield_validator.py），不另起炉灶。
 */
export interface GFInterlock {
  id: string;
  target_id: string;
  expression: string;
  source: "user" | "contract" | "inferred" | string;
  applies_to?: string[];
}

/** 业务语言节点类别（工站 / 执行单元 / 执行件）。 */
export type GFNodeKind = "unit" | "em" | "cm";

/** 契约 §3 `POST /patch` 的节点 op 白名单。 */
export type GFCanvasPatchOp =
  | "add_unit"
  | "add_em"
  | "add_cm"
  | "remove_node"
  | "rename_node"
  | "relabel_node"
  | "reparent_node";

/** 一个 patch op；字段按契约 §3 的 JSON shape 传递，服务端为唯一裁定。 */
export interface GFCanvasOp {
  op: GFCanvasPatchOp | string;
  [key: string]: unknown;
}

/** 契约 §2.3 `SourceBlock`。 */
export interface GFSourceBlock {
  source_id: string;
  kind: string;
  payload: Record<string, unknown>;
}

/** 契约 §2.3 `SpecDiff`。 */
export interface GFSpecDiff {
  base_spec_version: number;
  target_spec_version: number;
  changed: GFSourceBlock[];
  added: GFSourceBlock[];
  removed: GFSourceBlock[];
  changed_source_ids: string[];
  diff_id?: string;
}

/** 契约 §2.4 `ReverseGuardVerdict`（D10 展示层）。 */
export interface GFReverseProtection {
  allowed: boolean;
  drift_count: number;
  tia_side_drift: number;
  blocked_source_ids: string[];
  reason: string;
}

/** 契约 §2.5 `FidelityReport`（N9：与编译通过是两个独立层）。 */
export interface GFFidelityStatus {
  fidelity_ok: boolean;
  coverage: number;
  orphan: number;
  drift: number;
  tia_side_drift: number;
  mode?: "full" | "incremental" | string;
  base_spec_version?: number;
  changed_source_ids?: string[];
  reverse_protection?: GFReverseProtection | null;
  ob_number_deviations?: Array<Record<string, unknown>> | number;
  pending_real_machine?: boolean;
}

/** 结构化编译诊断（P1-I 展示层；不改后端 compile_jobs.py / writeback_heal.py）。 */
export type GFCompilePhase =
  | "idle"
  | "generating"
  | "compiling"
  | "diagnosed"
  | "healing"
  | "recompiling"
  | "settled";

export interface GFCompileBlock {
  name: string;
  block_type?: string;
  number?: number;
  error_count?: number;
  warning_count?: number;
}

export interface GFCompileDiagnostics {
  phase: GFCompilePhase;
  error_count: number;
  /** warning 单列，绝不并入「成功」。 */
  warnings: string[];
  blocks: GFCompileBlock[];
  compile_ok?: boolean;
  tia_unavailable?: boolean;
  pending_real_machine?: boolean;
  note?: string;
}

/** 确认硬门禁五项前置的服务端判定（缺失时由 /confirm 返回具体原因兜底）。 */
export interface GFGateChecks {
  topology_finalized?: boolean;
  open_questions_cleared?: boolean;
  nodes_edges_valid?: boolean;
  equivalence_precheck?: boolean;
  baseline_locked?: boolean;
  [key: string]: boolean | undefined;
}

/** 对话注入的「已定拓扑」约束：对话结果不得与已定拓扑矛盾。 */
export interface GFTopologyConstraints {
  units: Array<{ id: string; business_label: string; name: string }>;
  ems: Array<{ id: string; unit_id: string; business_label: string }>;
  cms: Array<{ id: string; em_id: string; business_label: string }>;
  edges: Array<{ id: string; kind: string; src_id: string; dst_id: string }>;
  open_questions: string[];
  inferred_interlocks: Array<{ id: string; target_id: string; expression: string }>;
  note: string;
}

export interface GFChatOptions {
  projectId?: string;
  topologyConstraints?: GFTopologyConstraints;
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
  /** P1-I 展示层：结构化编译诊断（后端未提供时 UI 诚实降级）。 */
  compile_diagnostics?: GFCompileDiagnostics | null;
  /** F13 降级：只读 SCL 预览源（块名 → 纯文本），无任何写回入口。 */
  scl_sources?: Record<string, string> | null;
  fidelity?: GFFidelityStatus | null;
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

  /* —— 契约 §3 `GET /state` 新增字段（均为可选，后端并行实现，缺省诚实降级）—— */
  project_id?: string;
  framework_baseline_version?: string;
  fidelity?: GFFidelityStatus | null;
  gate_checks?: GFGateChecks | null;
  spec_diff?: GFSpecDiff | null;
  reverse_protection?: GFReverseProtection | null;
  compile_diagnostics?: GFCompileDiagnostics | null;
  diff_confirmed?: boolean;
  pending_real_machine?: boolean;
  side_effect_counters?: Record<string, number>;
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

/** 新建向导四步完成后落盘的启动上下文（project_id 贯穿全程的载体）。 */
export interface GFLaunchContext {
  project_id: string;
  project_name: string;
  prompt: string;
  has_uploads: boolean;
  /** 未上传资料时明确降级：不虚构地址 / OB 条目。 */
  no_upload_note?: string;
  /** 可选：用户真实填写的 DB 编号（留空即不登记，绝不虚构）。 */
  db_number?: string;
  /** 可选：用户真实选择的资料文件名（仅登记文件名，不虚构内容 / 地址）。 */
  uploaded_files?: string[];
  created_at: string;
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

// ------------------------------------------------------------ 会话 / 项目保持
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

/** 复用 `projects.ts` 现成的 `prj-<hex12>` 生成机制，不另起炉灶。 */
export function createProjectId(): string {
  return makeProjectId();
}

export function loadProjectId(): string | null {
  try {
    return window.localStorage.getItem(GF_PROJECT_KEY);
  } catch {
    return null;
  }
}

export function saveProjectId(id: string): void {
  try {
    window.localStorage.setItem(GF_PROJECT_KEY, id);
  } catch {
    /* 隐私模式下静默降级为内存态 */
  }
}

/** 通道启动时保证有 project_id：向导已生成则复用，否则新建并落盘。 */
export function ensureProjectId(): string {
  const existing = loadProjectId();
  if (existing) return existing;
  const created = createProjectId();
  saveProjectId(created);
  return created;
}

export function saveLaunchContext(context: GFLaunchContext): void {
  try {
    window.localStorage.setItem(GF_LAUNCH_CONTEXT_KEY, JSON.stringify(context));
  } catch {
    /* 隐私模式下静默降级为内存态 */
  }
}

export function loadLaunchContext(): GFLaunchContext | null {
  try {
    const raw = window.localStorage.getItem(GF_LAUNCH_CONTEXT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GFLaunchContext;
    return parsed && typeof parsed.project_id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ 错误层
/**
 * Greenfield 专有请求错误：携带 HTTP 状态、网关 code、是否离线、原始 body，
 * `message` 一律是**可读中文**（绝不出现笼统的「操作失败」）。
 */
export class GFRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly offline: boolean;
  readonly details: unknown;
  readonly body: unknown;

  constructor(
    message: string,
    options: { status: number; code?: string; offline?: boolean; details?: unknown; body?: unknown },
  ) {
    super(message);
    this.name = "GFRequestError";
    this.status = options.status;
    this.code = options.code ?? "";
    this.offline = options.offline ?? false;
    this.details = options.details ?? null;
    this.body = options.body ?? null;
  }
}

/** 网关 code → 具体可读中文（契约 §3 要求把 /confirm 原因映射成中文文案）。 */
export const GF_ERROR_TEXT: Record<string, string> = {
  GF_GATE_NOT_CONFIRMED: "确认动作必须由你显式点击，系统不会自动代为确认。",
  GF_GATE_LOCKED: "当前阶段不允许该操作；请先完成拓扑定稿与结构校验。",
  GF_GATE_SIDE_EFFECTS: "确认前检测到未授权的副作用，已阻止本次操作。",
  GF_TOPOLOGY_NOT_FINALIZED: "拓扑尚未定稿：请先确认工站 / 执行单元 / 执行件及设备交互连线。",
  GF_OPEN_QUESTIONS_PENDING: "仍存在待确认问题（open_questions 未清零），请逐条答复后再确认。",
  GF_NODE_EDGE_INVALID: "节点或连线校验未通过，请按校验清单修正后再确认。",
  GF_EQUIVALENCE_PRECHECK_FAILED: "等价性预检未通过，无法锁定还原契约。",
  GF_BASELINE_NOT_LOCKED: "框架基线版本尚未锁定，无法确认。",
  GF_DIFF_NOT_CONFIRMED: "差异清单尚未显式勾选确认，禁止任何后续写入（确认前零副作用）。",
  GF_REVERSE_PROTECTION_BLOCKED: "TIA 侧存在手工改动，已阻止覆盖。",
  GF_TIA_SIDE_DRIFT: "TIA 侧存在手工改动，已阻止覆盖。",
  GF_FIDELITY_FAILED: "还原一致性（fidelity）检查未通过，已阻止写入；这不代表编译通过。",
  GF_SPEC_IMMUTABLE: "规格已冻结且不可变，请走「继续调整（v+1）」开启新版本草稿。",
  GF_PATCH_ATOMIC_REJECTED: "节点变更中存在非法操作，整批已回滚，画布保持不变。",
  GF_EDGE_ILLEGAL: "连线类型不在允许白名单内，变更已回滚。",
  GF_TIA_UNAVAILABLE: "TIA 真机环境不可用，本次交付未执行（非编译通过）。",
  GF_SPEC_NOT_FOUND: "未找到该版本的冻结规格快照。",
  LLM_CALL_FAILED: "工艺解析服务暂时不可用，请稍后重试。",
};

function readErrorBody(body: unknown, status: number): { code: string; message: string; details: unknown } {
  const envelope = body as { error?: unknown; detail?: unknown } | null;
  const raw = envelope?.error ?? envelope?.detail ?? null;
  if (typeof raw === "string" && raw.trim()) {
    return { code: "", message: raw.trim(), details: null };
  }
  if (raw && typeof raw === "object") {
    const err = raw as { code?: unknown; message?: unknown; detail?: unknown; details?: unknown };
    const message =
      (typeof err.message === "string" && err.message.trim()) ||
      (typeof err.detail === "string" && err.detail.trim()) ||
      "";
    return {
      code: typeof err.code === "string" ? err.code : "",
      message,
      details: err.details ?? null,
    };
  }
  return { code: "", message: "", details: null };
}

/** 把 HTTP 状态 / 网关 code / 原始 message 统一映射为可读中文。 */
export function mapApiError(code: string, message: string, status: number): string {
  const mapped = code ? GF_ERROR_TEXT[code] : undefined;
  if (mapped) {
    return message && message !== mapped ? `${mapped}（后端说明：${message}）` : mapped;
  }
  if (code) {
    return `网关拒绝本次操作（${code}）：${message || "未提供具体原因"}。`;
  }
  if (status === 404) {
    return "该 Greenfield 能力暂未上线（HTTP 404）：新端点正在并行实现中，本次操作已安全降级，未产生任何写入。";
  }
  if (status === 409) {
    return `硬门禁或规格不可变约束阻止了本次操作（HTTP 409）：${message || "未提供具体原因"}。`;
  }
  if (status === 422) {
    return `校验未通过，变更已整批回滚（HTTP 422）：${message || "未提供具体原因"}。`;
  }
  if (status >= 500) {
    return `网关服务暂时不可用（HTTP ${status}），已重试 ${GF_MAX_RETRIES} 次仍未恢复：${message || "未提供具体原因"}。`;
  }
  if (status >= 400) {
    return `网关拒绝本次操作（HTTP ${status}）：${message || "未提供具体原因"}。`;
  }
  return message || "网关返回了未知错误，未提供具体原因。";
}

/** `/confirm` 返回原因 → 具体中文（供门禁 UI 直接展示，不笼统提示）。 */
export function mapConfirmError(code: string, fallback?: string): string {
  return (
    GF_ERROR_TEXT[code] ||
    (fallback && fallback.trim()) ||
    (code ? `确认被拒绝（${code}），后端未提供更具体的原因。` : "确认被拒绝，后端未提供具体原因。")
  );
}

/** 任意异常 → 可读中文（组件统一用它渲染 error 区）。 */
export function formatGfError(error: unknown): string {
  if (error instanceof GFRequestError) return error.message;
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return "发生了未说明原因的错误，已阻止后续操作（未产生任何写入）。";
}

// -------------------------------------------------------------- gfRequest
function unwrapEnvelope<T>(body: unknown): T {
  const envelope = body as { data?: T } | null;
  if (envelope && typeof envelope === "object" && "data" in envelope && envelope.data !== undefined) {
    return envelope.data;
  }
  return body as T;
}

/**
 * Greenfield 唯一请求入口：
 * - URL = 环境变量基址 + 独立前缀路径（未配置 env 时同源相对路径）；
 * - 可选 Bearer 令牌来自环境变量；
 * - 4xx 不重试；5xx 最多重试 3 次；fetch 抛错给出离线提示且不重试；
 * - 错误一律 `GFRequestError` + 可读中文，409/422 保留后端具体原因。
 */
export async function gfRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${GF_BASE}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(rawToken ? { Authorization: `Bearer ${rawToken}` } : {}),
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  let attempt = 0;
  let lastFailure: GFRequestError | null = null;

  while (attempt <= GF_MAX_RETRIES) {
    let res: Response;
    try {
      res = await fetch(url, { ...init, headers });
    } catch (cause) {
      // 网络层失败：离线提示（不重试，避免掩盖离线事实）。
      throw new GFRequestError(
        `离线：网络连接不可用，无法访问网关。请检查后端服务是否已启动，以及环境变量 VITE_GATEWAY_URL 是否正确（当前基址：${GF_BASE || "同源相对路径"}）。`,
        { status: 0, code: "GF_OFFLINE", offline: true, details: String(cause) },
      );
    }

    let text = "";
    try {
      text = await res.text();
    } catch {
      text = "";
    }
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text) as unknown;
      } catch {
        body = text;
      }
    }

    const isEnvelopeFailure =
      !!body && typeof body === "object" && (body as { ok?: boolean }).ok === false;
    if (!res.ok || isEnvelopeFailure) {
      const { code, message, details } = readErrorBody(body, res.status);
      const textMessage = typeof body === "string" && body.trim() ? body.trim() : message;
      const failure = new GFRequestError(mapApiError(code, textMessage, res.status), {
        status: res.status,
        code,
        details,
        body,
      });
      if (res.status >= 500 && attempt < GF_MAX_RETRIES) {
        attempt += 1;
        lastFailure = failure;
        continue;
      }
      throw failure; // 4xx 不重试；5xx 重试耗尽也抛出
    }

    return unwrapEnvelope<T>(body);
  }

  throw (
    lastFailure ??
    new GFRequestError("网关请求在重试后仍未成功，未提供具体原因。", {
      status: 0,
      code: "GF_RETRY_EXHAUSTED",
    })
  );
}

// ------------------------------------------------------------------ API 层
export async function fetchState(
  sessionId?: string | null,
  projectId?: string | null,
): Promise<GFState> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (projectId) params.set("project_id", projectId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return gfRequest<GFState>(`${GF_API}/state${suffix}`);
}

export async function fetchWhitelist(): Promise<GFWhitelist> {
  return gfRequest<GFWhitelist>(`${GF_API}/whitelist`);
}

export async function createDraft(
  sessionId: string,
  prompt: string,
  projectId?: string,
): Promise<GFState> {
  return gfRequest<GFState>(
    `${GF_API}/draft`,
    jsonBody({ session_id: sessionId, prompt, ...(projectId ? { project_id: projectId } : {}) }),
  );
}

export async function uploadFiles(
  sessionId: string,
  items: Array<{ filename: string; content_base64?: string; text?: string; kind?: string }>,
  projectId?: string,
): Promise<{ receipt: GFReceipt }> {
  return gfRequest<{ receipt: GFReceipt }>(
    `${GF_API}/upload`,
    jsonBody({ session_id: sessionId, items, ...(projectId ? { project_id: projectId } : {}) }),
  );
}

export async function confirmReceipt(sessionId: string): Promise<{ contract: Record<string, unknown> }> {
  return gfRequest<{ contract: Record<string, unknown> }>(
    `${GF_API}/receipt/confirm`,
    jsonBody({ session_id: sessionId }),
  );
}

export async function applyLinkPatch(sessionId: string, patch: Record<string, unknown>): Promise<GFState> {
  return gfRequest<GFState>(`${GF_API}/links`, jsonBody({ session_id: sessionId, ...patch }));
}

export async function revalidate(sessionId: string): Promise<GFState> {
  return gfRequest<GFState>(`${GF_API}/validate`, jsonBody({ session_id: sessionId }));
}

export async function fetchViews(sessionId: string): Promise<GFViews> {
  return gfRequest<GFViews>(`${GF_API}/views?session_id=${encodeURIComponent(sessionId)}`);
}

export async function fetchEngineeringSummary(sessionId: string): Promise<Record<string, unknown>> {
  return gfRequest<Record<string, unknown>>(
    `${GF_API}/engineering-summary`,
    jsonBody({ session_id: sessionId }),
  );
}

/**
 * 确认硬门禁 → 冻结规格。带上 `project_id`（若调用方持有），
 * 后端任一前置未满足会返回具体 code，前端用 `mapConfirmError` 映射中文。
 */
export async function confirmSpec(
  sessionId: string,
  explicit: boolean,
  projectId?: string,
): Promise<{ spec: Record<string, unknown>; path: string; markdown: string }> {
  return gfRequest<{ spec: Record<string, unknown>; path: string; markdown: string }>(
    `${GF_API}/confirm`,
    jsonBody({
      session_id: sessionId,
      explicit,
      ...(projectId ? { project_id: projectId } : {}),
    }),
  );
}

export async function beginEdit(sessionId: string): Promise<GFState> {
  return gfRequest<GFState>(`${GF_API}/begin-edit`, jsonBody({ session_id: sessionId }));
}

export async function exportMermaid(sessionId: string): Promise<{ markdown: string }> {
  return gfRequest<{ markdown: string }>(
    `${GF_API}/export/mermaid?session_id=${encodeURIComponent(sessionId)}`,
  );
}

export async function exportDraft(sessionId: string): Promise<{ payload: GFDraftPayload }> {
  return gfRequest<{ payload: GFDraftPayload }>(
    `${GF_API}/draft/export`,
    jsonBody({ session_id: sessionId }),
  );
}

export async function importDraft(sessionId: string, payload: GFDraftPayload): Promise<GFState> {
  return gfRequest<GFState>(`${GF_API}/draft/import`, jsonBody({ session_id: sessionId, payload }));
}

export async function updateHardware(
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<GFState> {
  return gfRequest<GFState>(`${GF_API}/hardware`, jsonBody({ session_id: sessionId, ...payload }));
}

/**
 * chat ↔ 画布 双向联动：问答 / LLM 增量修改 / 首版生成（服务端为唯一裁定）。
 * 带 `project_id` 与「已定拓扑」约束注入，确保对话结果不得与已定拓扑矛盾。
 */
export async function sendChat(
  sessionId: string,
  message: string,
  options: GFChatOptions = {},
): Promise<{ state: GFState; reply: string; message: GFChatMessage }> {
  return gfRequest<{ state: GFState; reply: string; message: GFChatMessage }>(
    `${GF_API}/chat`,
    jsonBody({
      session_id: sessionId,
      message,
      ...(options.projectId ? { project_id: options.projectId } : {}),
      ...(options.topologyConstraints ? { topology_constraints: options.topologyConstraints } : {}),
    }),
  );
}

export async function loadReferenceFixture(
  sessionId: string,
  prompt = "",
): Promise<GFState> {
  return gfRequest<GFState>(`${GF_API}/load-reference`, jsonBody({ session_id: sessionId, prompt }));
}

export async function generateProjectPackage(
  sessionId: string,
  projectId?: string,
): Promise<{ delivery: GFDeliverySummary & Record<string, unknown> }> {
  return gfRequest<{ delivery: GFDeliverySummary & Record<string, unknown> }>(
    `${GF_API}/generate`,
    jsonBody({ session_id: sessionId, ...(projectId ? { project_id: projectId } : {}) }),
  );
}

/** 博途真机交付：XML 补充包 + PCEC 事务 + Openness 自动导入编译（不可用则诚实降级）。 */
export async function deliverTia(
  sessionId: string,
  mode: "auto" | "package" = "auto",
  projectId?: string,
): Promise<{ delivery: Record<string, unknown> }> {
  return gfRequest<{ delivery: Record<string, unknown> }>(
    `${GF_API}/deliver-tia`,
    jsonBody({ session_id: sessionId, mode, ...(projectId ? { project_id: projectId } : {}) }),
  );
}

export function downloadPackageUrl(sessionId: string): string {
  return `${GF_BASE}${GF_API}/download-package?session_id=${encodeURIComponent(sessionId)}`;
}

/* ---- 契约 §3 四个新端点（Agent A 并行实现；暂时 404 时由 gfRequest 中文降级） ---- */

export interface GFCanvasPatchResult {
  ir: Record<string, unknown> | null;
  spec_hash: string;
  violations: GFViolation[];
  stage?: GFStage;
  /** 变更事件入账（用于 UI 反馈）。 */
  events?: Array<{ op: string; node_id?: string; message?: string }>;
}

/** `POST /patch`：节点增删改 / 重命名 / 重挂 / 改标签，原子拒绝时 422。 */
export async function applyCanvasPatch(
  projectId: string,
  ops: GFCanvasOp[],
  baseSpecVersion?: number,
): Promise<GFCanvasPatchResult> {
  return gfRequest<GFCanvasPatchResult>(
    `${GF_API}/patch`,
    jsonBody({
      project_id: projectId,
      ops,
      ...(baseSpecVersion !== undefined ? { base_spec_version: baseSpecVersion } : {}),
    }),
  );
}

/** `POST /diff`：vN → vN+1 的 SpecDiff（带 source_id）。 */
export async function fetchSpecDiff(
  projectId: string,
  fromVersion: number,
  toVersion: number,
): Promise<GFSpecDiff> {
  return gfRequest<GFSpecDiff>(
    `${GF_API}/diff`,
    jsonBody({ project_id: projectId, from_version: fromVersion, to_version: toVersion }),
  );
}

/** `POST /confirm-diff`：差异清单级显式确认（D11）；未确认时零副作用计数器恒 0。 */
export async function confirmDiff(
  projectId: string,
  diffId: string,
  confirmed: boolean,
): Promise<{ ok: boolean; counters?: Record<string, number>; [key: string]: unknown }> {
  return gfRequest<{ ok: boolean; counters?: Record<string, number>; [key: string]: unknown }>(
    `${GF_API}/confirm-diff`,
    jsonBody({ project_id: projectId, diff_id: diffId, confirmed }),
  );
}

/** `GET /specs/{v}?project_id=`：完整 FrozenSpec 快照（可重建画布）。 */
export async function fetchSpec(
  projectId: string,
  version: number,
): Promise<Record<string, unknown>> {
  return gfRequest<Record<string, unknown>>(
    `${GF_API}/specs/${encodeURIComponent(String(version))}?project_id=${encodeURIComponent(projectId)}`,
  );
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

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

/** 复用 `GFInterlock.source == "inferred"` 现成机制，生成待确认问题。 */
export function inferredInterlockQuestions(ir: Record<string, unknown> | null): string[] {
  const interlocks = ir ? asArray(ir.interlocks) : [];
  return interlocks
    .filter((item) => str(item.source) === "inferred")
    .map((item) => {
      const id = str(item.id) || "未命名联锁";
      const expr = str(item.expression) || "TRUE";
      return `设备交互联锁「${id}」（${expr}）来源为推断，需人工确认`;
    });
}

/** 汇总 open_questions：复用 GFSpecMeta.open_questions + 校验报告 + 推断联锁。 */
export function collectOpenQuestions(state: GFState): string[] {
  const specMeta = (state.ir?.spec_meta ?? {}) as { open_questions?: unknown };
  const fromSpecMeta = Array.isArray(specMeta.open_questions)
    ? specMeta.open_questions.map(str)
    : [];
  const fromReport = state.report?.open_questions ?? [];
  const fromInferred = inferredInterlockQuestions(state.ir);
  const all = [...fromSpecMeta, ...fromReport, ...fromInferred];
  return Array.from(new Set(all.filter((q) => q.trim().length > 0)));
}

/** 已定拓扑约束注入：对话结果不得与已定拓扑矛盾（P1-G）。 */
export function buildTopologyConstraints(ir: Record<string, unknown> | null): GFTopologyConstraints {
  const units = asArray(ir?.units).map((u) => ({
    id: str(u.id),
    business_label: str(u.business_label) || str(u.name),
    name: str(u.name),
  }));
  const ems = asArray(ir?.ems).map((e) => ({
    id: str(e.id),
    unit_id: str(e.unit_id),
    business_label: str(e.business_label) || str(e.name),
  }));
  const cms = asArray(ir?.cms).map((c) => ({
    id: str(c.id),
    em_id: str(c.em_id),
    business_label: str(c.business_label) || str(c.id),
  }));
  const edges = asArray(ir?.edges).map((e) => ({
    id: str(e.id),
    kind: str(e.kind),
    src_id: str(e.src_id),
    dst_id: str(e.dst_id),
  }));
  const interlocks = asArray(ir?.interlocks)
    .filter((item) => str(item.source) === "inferred")
    .map((item) => ({
      id: str(item.id),
      target_id: str(item.target_id),
      expression: str(item.expression),
    }));
  const specMeta = (ir?.spec_meta ?? {}) as { open_questions?: unknown };
  const openQuestions = Array.isArray(specMeta.open_questions)
    ? specMeta.open_questions.map(str).filter(Boolean)
    : [];
  return {
    units,
    ems,
    cms,
    edges,
    open_questions: openQuestions,
    inferred_interlocks: interlocks,
    note: "以下为已定拓扑与已定设备交互约束；本轮对话结果不得与已定拓扑矛盾，不得擅自增删工站 / 执行单元 / 执行件或改写既有连线。",
  };
}

/** 确认硬门禁未满足项（五项前置 + 既有阶段 / 回执 / 副作用守卫）。 */
export interface GFBlocker {
  code: string;
  reason: string;
}

export function confirmBlockers(state: GFState): GFBlocker[] {
  const blockers: GFBlocker[] = [];
  if (state.stage === "FROZEN") {
    return [{ code: "GF_GATE_LOCKED", reason: "规格已冻结；生成标准工程属于下一阶段" }];
  }
  if (state.stage === "LOCKED") {
    return [{ code: "GF_GATE_LOCKED", reason: "当前会话已锁定，无法确认" }];
  }
  if (state.stage !== "VALIDATING" && state.stage !== "LINKABLE") {
    blockers.push({ code: "GF_GATE_LOCKED", reason: "当前阶段不允许确认，请先推进到校验阶段" });
  }
  if (!state.has_ir) {
    blockers.push({
      code: "GF_TOPOLOGY_NOT_FINALIZED",
      reason: "请先描述工艺，生成首版结构图并完成拓扑定稿",
    });
  }
  if (!state.report?.ok) {
    blockers.push({
      code: "GF_NODE_EDGE_INVALID",
      reason: "节点 / 连线结构校验尚未全部通过，请先修正连线",
    });
  }
  if (state.receipt && !state.receipt.user_confirmed) {
    blockers.push({ code: "GF_GATE_NOT_CONFIRMED", reason: "请先确认上传解析回执" });
  }
  if (!state.engineering_summary_shown) {
    blockers.push({
      code: "GF_GATE_NOT_CONFIRMED",
      reason: "请先在确认弹窗查看工程视角摘要",
    });
  }
  if (hasSideEffects(state)) {
    blockers.push({ code: "GF_GATE_SIDE_EFFECTS", reason: "检测到未授权的副作用，已阻止确认" });
  }

  const questions = collectOpenQuestions(state);
  if (questions.length > 0) {
    blockers.push({
      code: "GF_OPEN_QUESTIONS_PENDING",
      reason: `仍有 ${questions.length} 条待确认问题（open_questions 未清零）：${questions[0]}`,
    });
  }

  // 服务端五项前置：仅在明确返回 false 时阻断并给出具体原因；
  // 字段缺失不臆造「通过」，由 /confirm 的真实返回兜底。
  const checks = state.gate_checks ?? null;
  if (checks) {
    if (checks.topology_finalized === false) {
      blockers.push({
        code: "GF_TOPOLOGY_NOT_FINALIZED",
        reason: "拓扑定稿预检未通过：请先锁定工站 / 执行单元 / 执行件与设备交互",
      });
    }
    if (checks.open_questions_cleared === false) {
      blockers.push({
        code: "GF_OPEN_QUESTIONS_PENDING",
        reason: "待确认问题清零预检未通过：请逐条答复开放问题与推断联锁",
      });
    }
    if (checks.nodes_edges_valid === false) {
      blockers.push({
        code: "GF_NODE_EDGE_INVALID",
        reason: "节点 / 连线校验预检未通过：请按右栏校验清单修正",
      });
    }
    if (checks.equivalence_precheck === false) {
      blockers.push({
        code: "GF_EQUIVALENCE_PRECHECK_FAILED",
        reason: "等价性预检未通过：产物与冻结规格不等价，无法锁定还原契约",
      });
    }
    if (checks.baseline_locked === false) {
      blockers.push({
        code: "GF_BASELINE_NOT_LOCKED",
        reason: "框架基线版本锁定预检未通过：请先锁定 framework_baseline_version",
      });
    }
  }
  return blockers;
}

export function canConfirm(state: GFState): boolean {
  return confirmBlockers(state).length === 0;
}

export function gateReason(state: GFState): string {
  const blockers = confirmBlockers(state);
  if (blockers.length === 0) return "可以确认设备逻辑并锁定还原契约";
  return blockers[0].reason;
}

/** D11：差异清单显式确认后才允许后续写入；D10：反向保护阻止覆盖。 */
export function diffWriteBlockers(
  state: GFState,
  diffConfirmed: boolean,
  reverse?: GFReverseProtection | null,
): GFBlocker[] {
  const blockers: GFBlocker[] = [];
  const diff = state.spec_diff ?? null;
  const hasDiff = !!diff && (
    (diff.changed?.length ?? 0) > 0 ||
    (diff.added?.length ?? 0) > 0 ||
    (diff.removed?.length ?? 0) > 0
  );
  if (hasDiff && !diffConfirmed) {
    blockers.push({
      code: "GF_DIFF_NOT_CONFIRMED",
      reason: "差异清单尚未显式勾选确认，禁止任何后续写入（确认前零副作用）",
    });
  }
  const protection = reverse ?? state.reverse_protection ?? state.fidelity?.reverse_protection ?? null;
  if (protection && (protection.allowed === false || (protection.tia_side_drift ?? 0) > 0)) {
    blockers.push({
      code: "GF_REVERSE_PROTECTION_BLOCKED",
      reason: "TIA 侧存在手工改动，已阻止覆盖",
    });
  }
  if (state.fidelity && state.fidelity.fidelity_ok === false) {
    blockers.push({
      code: "GF_FIDELITY_FAILED",
      reason: "还原一致性（fidelity）检查未通过，已阻止写入；这不代表编译通过",
    });
  }
  return blockers;
}

export function canWriteAfterDiff(
  state: GFState,
  diffConfirmed: boolean,
  reverse?: GFReverseProtection | null,
): boolean {
  return diffWriteBlockers(state, diffConfirmed, reverse).length === 0;
}

/** N9：fidelity_ok 只表达「还原一致性」，绝不显示成「编译通过」。 */
export function formatFidelityLabel(fidelity: GFFidelityStatus | null | undefined): {
  label: string;
  detail: string;
  ok: boolean;
} {
  if (!fidelity) {
    return { label: "还原一致性：暂无数据", detail: "后端尚未返回 fidelity 报告（不视为通过）", ok: false };
  }
  const coverage = typeof fidelity.coverage === "number" ? Math.round(fidelity.coverage * 100) : null;
  const detail = `覆盖度 ${coverage === null ? "—" : `${coverage}%`} · 孤立块 ${fidelity.orphan ?? 0} · 漂移 ${fidelity.drift ?? 0} · TIA 侧漂移 ${fidelity.tia_side_drift ?? 0} · 模式 ${fidelity.mode ?? "full"}`;
  return {
    label: fidelity.fidelity_ok ? "还原一致性：达标（fidelity_ok=true）" : "还原一致性：未达标（fidelity_ok=false）",
    detail,
    ok: fidelity.fidelity_ok === true,
  };
}

/** generate → compile → 诊断 → 修正 → 复编译 的展示层状态机步骤（不改后端）。 */
export const GF_COMPILE_STEPS: Array<{ key: GFCompilePhase; label: string }> = [
  { key: "generating", label: "生成" },
  { key: "compiling", label: "编译" },
  { key: "diagnosed", label: "诊断" },
  { key: "healing", label: "修正" },
  { key: "recompiling", label: "复编译" },
  { key: "settled", label: "归档" },
];

export function compileStepStatus(
  phase: GFCompilePhase | undefined,
  step: GFCompilePhase,
): "done" | "active" | "todo" {
  if (!phase || phase === "idle") return "todo";
  const order = GF_COMPILE_STEPS.map((s) => s.key);
  const current = order.indexOf(phase === "settled" ? "settled" : phase);
  const target = order.indexOf(step);
  if (current < 0) return "todo";
  if (target < current) return "done";
  if (target === current) return "active";
  return "todo";
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
