/**
 * PLC gateway client — the only module in this repo that talks to
 * `gateway.app.main:app` (`/api/v1/plc/*`).
 *
 * It exists for three cross-cutting capabilities that hand-written `fetch`
 * (App.tsx / ImportDialog.tsx) keeps getting wrong or silently drops:
 *   1. one base URL (env-driven, same-origin in dev via the Vite proxy);
 *   2. one error path — `GatewayError` carrying HTTP status + gateway code,
 *      with a graceful fallback when the body is not JSON;
 *   3. one abortable poller (`pollUntil` / `waitForPlcJob`) with timeout.
 *
 * `requestPlc` is exported on purpose: the canvas endpoints
 * (`/api/v1/plc/canvas/*`) are still hand-rolled in App.tsx and can be
 * migrated one call site at a time without inventing a new wrapper each time.
 */

const rawGateway = import.meta.env.VITE_GATEWAY_URL as string | undefined;

/**
 * Gateway base URL.
 * - Dev / Docker nginx: empty → same-origin `/api` (Vite or nginx proxy).
 * - Explicit VITE_GATEWAY_URL (including "") wins; only fall back to localhost
 *   when the env var is truly unset at build time.
 */
export const GATEWAY_BASE =
  rawGateway === undefined
    ? import.meta.env.DEV
      ? ""
      : "http://localhost:8000"
    : String(rawGateway).replace(/\/$/, "");

/**
 * 统一网关基址入口：交付/打包等分支一律用它拼真实端点，
 * 禁止再在 UI 里 `window.location... + ":8000"` 硬拼端口绕过 Vite 代理。
 */
export function gatewayBase(): string {
  return GATEWAY_BASE;
}

/** Any non-2xx / `ok:false` gateway answer, with the gateway code preserved. */
export class GatewayError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly body: unknown;

  constructor(
    message: string,
    options: { status: number; code?: string | null; body?: unknown },
  ) {
    super(message);
    this.name = "GatewayError";
    this.status = options.status;
    this.code = options.code ?? null;
    this.body = options.body;
  }
}

type GatewayErrorBody = {
  code?: string;
  message?: string;
  detail?: string;
};

/**
 * Gateway answers carry the error either as FastAPI's `detail`
 * (HTTPException) or as the `ApiResponse.error` envelope. Extract both.
 */
function failureFromBody(body: unknown, status: number): { code: string | null; message: string } {
  const raw =
    (body as { detail?: unknown } | null | undefined)?.detail ??
    (body as { error?: unknown } | null | undefined)?.error ??
    null;

  if (typeof raw === "string" && raw.trim()) {
    return { code: null, message: raw.trim() };
  }
  if (raw && typeof raw === "object") {
    const detail = raw as GatewayErrorBody;
    // Nested detail: { code, message } | { message } | { detail }
    const message =
      (typeof detail.message === "string" && detail.message.trim()) ||
      (typeof detail.detail === "string" && detail.detail.trim()) ||
      "";
    if (message) {
      return { code: detail.code ?? null, message };
    }
  }
  return { code: null, message: `网关请求失败（HTTP ${status}）` };
}

/**
 * Single fetch entrypoint: JSON in, `{ ok, data }` unwrapped, `GatewayError`
 * out. Falls back to the raw body text when the response is not JSON at all
 * (proxy HTML error pages, nginx 502, empty body).
 */
export async function requestPlc<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${GATEWAY_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text; // non-JSON body: keep it for the error message
    }
  }

  if (!res.ok) {
    const parsed = typeof body === "object" ? body : null;
    const { code, message } = failureFromBody(parsed, res.status);
    throw new GatewayError(
      typeof body === "string" && body.trim() ? body.trim() : message,
      { status: res.status, code, body },
    );
  }

  if (body && typeof body === "object" && (body as { ok?: boolean }).ok === false) {
    const { code, message } = failureFromBody(body, res.status);
    throw new GatewayError(message, { status: res.status, code, body });
  }

  const envelope = body as { data?: T } | null;
  return (envelope && "data" in envelope && envelope.data !== undefined
    ? envelope.data
    : body) as T;
}

/* ---- polling ---- */

export type PollOptions<T> = {
  intervalMs?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
  onProgress?: (value: T) => void;
};

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Poll until `isDone` (or timeout / abort). Every probe is awaited, so a slow
 * request never overlaps the next one — unlike `setInterval` polling.
 */
export async function pollUntil<T>(
  probe: () => Promise<T>,
  isDone: (value: T) => boolean,
  options: PollOptions<T> = {},
): Promise<T> {
  const intervalMs = options.intervalMs ?? 1500;
  const timeoutMs = options.timeoutMs ?? 600_000;
  const start = Date.now();
  for (;;) {
    if (options.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    const value = await probe();
    options.onProgress?.(value);
    if (isDone(value)) return value;
    if (Date.now() - start > timeoutMs) {
      throw new Error(`轮询超时（${Math.round(timeoutMs / 1000)}s）`);
    }
    await sleep(intervalMs, options.signal);
  }
}

/* ---- types ---- */

export type StructureStatus = "exported" | "failed" | "skipped" | "pending";

export type PlcStructureUnit = {
  name: string;
  kind?: string;
  type?: string;
  category?: string;
  status: StructureStatus | string;
  reason?: string;
  detail?: string;
  retryable?: boolean;
  protected?: boolean;
  interface_only?: boolean;
  body_available?: boolean;
  instance_of?: string | null;
};

export type PlcStructure = {
  units?: PlcStructureUnit[];
  counts?: {
    exported?: number;
    failed?: number;
    skipped?: number;
    pending?: number;
    total?: number;
  };
  layers?: {
    device_tree?: PlcStructureUnit[];
    program_blocks?: PlcStructureUnit[];
    interface_dbs?: PlcStructureUnit[];
    tags?: PlcStructureUnit[];
    call_graph?: {
      edges?: Array<{ source?: string; target?: string; type?: string }>;
      missing_callees?: PlcStructureUnit[];
    };
  };
  complete?: boolean;
  incomplete_count?: number;
};

export type PlcCoverage = {
  todo_rate?: number;
  todo_count?: number;
  instruction_count?: number;
  converted?: number;
  parsed?: number;
  protected?: number;
  interface_only?: number;
  unknown?: number;
  total_blocks?: number;
  safety_block_count?: number;
  language_histogram?: Record<string, number>;
  part_histogram?: Record<string, number>;
  todo_histogram?: Record<string, number>;
  top_untranslated_parts?: Array<{ name?: string; count?: number }>;
  safety_blocks?: string[];
  categories?: Record<
    string,
    {
      exported?: number;
      parsed?: number;
      skipped?: number;
      skipped_reasons?: Array<{ name?: string; reason?: string; detail?: string }>;
    }
  >;
  structure?: {
    total?: number;
    exported?: number;
    failed?: number;
    skipped?: number;
    pending?: number;
    complete?: boolean;
    incomplete_count?: number;
  };
};

export type PlcCitation = {
  block?: string;
  network?: string;
  /** M3 locator, e.g. `Network 10 / line 3`. */
  locator?: string;
  line?: number | null;
  evidence?: string;
  nodeId?: string;
  edge_type?: string;
  target?: string;
  snippet?: string;
  source_status?: string;
};

/**
 * Chat message as the UI stores and renders it (`state/sessions.ChatMessage`).
 * The gateway speaks `{ role: "user" | "assistant", content }` — `chatPlcJob`
 * normalizes it into this shape so no `{ role, content }` leaks into the UI.
 */
export type PlcChatMessage = {
  role: "user" | "system";
  text: string;
  ts: number;
  block_name?: string | null;
  citations?: PlcCitation[];
};

export type PlcJobSummary = {
  id: string;
  status: string;
  source_type: string;
  source_path?: string | null;
  project_path?: string | null;
  project_name?: string;
  summary?: Record<string, unknown>;
  error?: string | null;
  export_ready?: boolean;
  coverage?: PlcCoverage | null;
  structure?: PlcStructure | null;
  brief_ready?: boolean;
  ingest_phase?: string | null;
};

export type PlcJobDetail = PlcJobSummary & {
  extraction_notes?: string[];
  progress?: Array<{
    step?: string;
    title?: string;
    detail?: string;
    status?: string;
    duration_ms?: number;
  }>;
  logic_graph?: {
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<{
      source?: string;
      target?: string;
      type?: string;
      weight?: number;
      seq?: number;
      inferred?: boolean;
    }>;
  };
  knowledge_graph?: { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> };
  blocks?: Array<{
    name: string;
    type?: string;
    number?: number | null;
    language?: string | null;
    networks?: number;
    comment?: string;
    instance_of?: string | null;
    nest_depth?: number | null;
    statics?: string[];
    members?: string[];
    inputs?: string[];
    outputs?: string[];
    inouts?: string[];
    protected?: boolean;
    interface_only?: boolean;
    body_available?: boolean;
    is_safety?: boolean;
    status?: StructureStatus | string;
    status_reason?: string;
    status_detail?: string;
    retryable?: boolean;
  }>;
  structure?: PlcStructure;
  chat?: PlcChatMessage[];
  coverage?: PlcCoverage;
  report?: string;
  changeset?: Record<string, unknown> | null;
  writeback?: Record<string, unknown> | null;
  optimize_plan?: string;
  scl_files?: Record<string, string>;
  scl_diffs?: Array<{
    block?: string;
    before?: string;
    after?: string;
    diff?: string;
    new_block?: boolean;
  }>;
  scl_skipped?: Array<{ block?: string; reason?: string; detail?: string }>;
  project_path?: string | null;
  export_ready?: boolean;
  export_dir?: string | null;
  hardware?: Array<Record<string, unknown>>;
  body_pull_queue?: Array<{ block?: string; reason?: string }>;
  block_stubs?: Array<Record<string, unknown>>;
};

export type PlcEngineerPrompt = {
  id: string;
  label: string;
  prompt: string;
};

export type PlcProjectBrief = {
  job_id?: string | null;
  project_name?: string;
  phase?: string;
  brief_ready?: boolean;
  purpose?: string;
  main_ob?: string | null;
  main_entry?: string | null;
  block_counts_by_status?: Record<string, number>;
  top_level_calls?: Array<{ callee?: string; network?: string; evidence?: string }>;
  device_sensor_summary?: {
    available?: boolean;
    source?: string;
    note?: string;
    devices?: Array<{ name: string; device_type?: string; address?: string; comment?: string }>;
    sensors?: Array<{ name: string; address?: string; comment?: string }>;
  };
  run_logic_entry?: string;
  export_gaps?: Array<{ block: string; status?: string; reason?: string }>;
  block_stubs?: Array<Record<string, unknown>>;
  engineer_prompts?: PlcEngineerPrompt[];
  timing?: Record<string, unknown>;
};

export type DeviceCardMeaningStatus = "cited" | "annotated" | "meaning_unconfirmed";

export type DeviceSensorCard = {
  schema?: string;
  id: string;
  kind: "tag" | "device" | string;
  symbol_name: string;
  address?: string;
  comment?: string;
  io_type?: string;
  data_type?: string;
  tag_table?: string;
  meaning_status: DeviceCardMeaningStatus | string;
  meaning_text?: string;
  meaning_source?: string;
  hmi_texts?: Array<{ device?: string; screen?: string; text?: string }>;
  used_by?: Array<{
    block?: string;
    access?: string;
    network_id?: string;
    network_title?: string;
    part?: string;
  }>;
  hardware?: {
    name?: string;
    type?: string;
    address?: string;
    rack?: string;
    slot?: string;
    failsafe?: boolean;
  } | null;
  annotation?: { text?: string; author?: string; updated_at?: string } | null;
  citations?: Array<{ kind?: string; locator?: string; quote?: string }>;
};

export type DeviceCardList = {
  schema?: string;
  job_id?: string;
  project_name?: string;
  counts?: {
    total?: number;
    returned?: number;
    cited?: number;
    annotated?: number;
    meaning_unconfirmed?: number;
  };
  cards: DeviceSensorCard[];
};

/* ---- PLC jobs ---- */

export async function listPlcJobs(limit = 20): Promise<PlcJobSummary[]> {
  const res = await requestPlc<PlcJobSummary[] | null>(
    `/api/v1/plc/jobs?limit=${encodeURIComponent(String(limit))}`,
  );
  return Array.isArray(res) ? res : [];
}

export async function fetchPlcJob(jobId: string): Promise<PlcJobDetail> {
  return requestPlc<PlcJobDetail>(
    `/api/v1/plc/jobs/${encodeURIComponent(jobId)}`,
  );
}

/** Poll a PLC job until it reaches `ready` / `failed`. */
export async function waitForPlcJob(
  jobId: string,
  options?: PollOptions<PlcJobDetail>,
): Promise<PlcJobDetail> {
  return pollUntil(
    () => fetchPlcJob(jobId),
    (detail) => detail.status === "ready" || detail.status === "failed",
    { intervalMs: 1500, timeoutMs: 600_000, ...options },
  );
}

/** Block-focused Q&A (read-only). Gateway `assistant` → UI `system`. */
export async function chatPlcJob(
  jobId: string,
  message: string,
  blockName?: string,
): Promise<PlcChatMessage> {
  const turn = await requestPlc<{
    role?: string;
    content?: string;
    block_name?: string | null;
    created_at?: string | null;
    citations?: PlcCitation[];
  }>(`/api/v1/plc/jobs/${encodeURIComponent(jobId)}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, block_name: blockName || null }),
  });
  const ts = turn?.created_at ? Date.parse(turn.created_at) : NaN;
  return {
    role: turn?.role === "user" ? "user" : "system",
    text: String(turn?.content ?? ""),
    ts: Number.isFinite(ts) ? ts : Date.now(),
    block_name: turn?.block_name ?? null,
    citations: turn?.citations ?? [],
  };
}

/* ---- device / sensor cards ---- */

export async function listPlcDeviceCards(
  jobId: string,
  opts?: { q?: string; io_type?: string; meaning_status?: string; kind?: string },
): Promise<DeviceCardList> {
  const qs = new URLSearchParams();
  if (opts?.q) qs.set("q", opts.q);
  if (opts?.io_type) qs.set("io_type", opts.io_type);
  if (opts?.meaning_status) qs.set("meaning_status", opts.meaning_status);
  if (opts?.kind) qs.set("kind", opts.kind);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return requestPlc<DeviceCardList>(
    `/api/v1/plc/jobs/${encodeURIComponent(jobId)}/device-cards${suffix}`,
  );
}

export async function fetchPlcDeviceCard(
  jobId: string,
  kind: string,
  name: string,
): Promise<DeviceSensorCard> {
  return requestPlc<DeviceSensorCard>(
    `/api/v1/plc/jobs/${encodeURIComponent(jobId)}/device-cards/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`,
  );
}

export async function annotatePlcDeviceCard(
  jobId: string,
  kind: string,
  name: string,
  text: string,
  author = "",
): Promise<DeviceSensorCard> {
  return requestPlc<DeviceSensorCard>(
    `/api/v1/plc/jobs/${encodeURIComponent(jobId)}/device-cards/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/annotation`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, author }),
    },
  );
}

/* ---- 交付包 / 简报 / 块级问答（真实端点，见 routers/plc.py） ---- */

/** 解析作业导出端点 URL（统一走 gatewayBase，不硬拼端口）。 */
export function plcJobExportUrl(jobId: string): string {
  return `${gatewayBase()}/api/v1/plc/jobs/${encodeURIComponent(jobId)}/export`;
}

/** 博途原生归档端点 URL（是否真有产物须以请求结果为准，绝不写死"已就绪"）。 */
export function plcJobZapUrl(jobId: string): string {
  return `${gatewayBase()}/api/v1/plc/jobs/${encodeURIComponent(jobId)}/zap`;
}

/** GET /jobs/{id}/brief → 分层工程简报（requestPlc 拆 { ok, data } 信封）。 */
export async function fetchPlcJobBrief(jobId: string): Promise<PlcProjectBrief> {
  return requestPlc<PlcProjectBrief>(
    `/api/v1/plc/jobs/${encodeURIComponent(jobId)}/brief`,
  );
}

/** 从 Content-Disposition 抽真实文件名：`attachment; filename="x.zip"`。 */
export function parseContentDispositionFilename(value: string | null): string | null {
  if (!value) return null;
  const match = /filename\*?="?([^";]+)"?/i.exec(value);
  const name = match?.[1]?.trim();
  return name || null;
}

/** 一次真实 GET /jobs/{id}/export 探测结果。 */
export type PlcExportProbe = {
  exists: boolean;
  status: number;
  filename: string | null;
  contentType: string | null;
  /** 不存在时的真实原因（HTTP 状态 / 网关 code+message / 网络错误）；存在时为 null。 */
  reason: string | null;
};

/**
 * 真实请求导出端点，只确认资源是否存在并读响应头，不把整包读进内存。
 * - 2xx：存在，文件名来自 Content-Disposition；
 * - 404/409 等：不存在，原因来自网关 JSON 错误体；
 * - 网络错误：不存在，原因来自异常信息。
 * 下载本身交给 `plcJobExportUrl` 链接，不在此消费 body。
 */
export async function probePlcJobExport(
  jobId: string,
  signal?: AbortSignal,
): Promise<PlcExportProbe> {
  let res: Response;
  try {
    res = await fetch(plcJobExportUrl(jobId), {
      method: "GET",
      headers: { Accept: "application/zip" },
      signal,
    });
  } catch (err) {
    return {
      exists: false,
      status: 0,
      filename: null,
      contentType: null,
      reason: `网关不可达或请求失败（${err instanceof Error ? err.message : String(err)}）`,
    };
  }
  const contentType = res.headers.get("content-type");
  const filename = parseContentDispositionFilename(res.headers.get("content-disposition"));
  if (!res.ok) {
    let reason = `导出端点返回 HTTP ${res.status}`;
    try {
      const body = JSON.parse(await res.text()) as {
        detail?: string | { code?: string; message?: string };
        error?: string | { code?: string; message?: string };
      };
      const detail = body?.detail ?? body?.error ?? null;
      const message = typeof detail === "string" ? detail : detail?.message;
      const code = typeof detail === "object" ? detail?.code : undefined;
      if (message) reason = `${message}${code ? `（${code}）` : ""}`;
    } catch {
      /* 非 JSON 错误体：保留 HTTP 状态即可 */
    }
    return { exists: false, status: res.status, filename, contentType, reason };
  }
  // 资源真实存在：取消响应体（只做存在性探测，避免把整个 zip 读进内存）
  try {
    await res.body?.cancel();
  } catch {
    /* 忽略取消失败 */
  }
  return { exists: true, status: res.status, filename, contentType, reason: null };
}

/**
 * 把块级只读问答返回的真实 citations 渲染成 Markdown 引用清单，
 * 追加进对话消息文本（ChatDock 的 MarkdownBody 会渲染，无需改 ChatDock）。
 */
export function formatPlcCitations(citations: PlcCitation[] | null | undefined): string {
  const list = Array.isArray(citations) ? citations : [];
  if (!list.length) return "";
  const lines = list.map((c, i) => {
    const block = c.block || c.target || c.nodeId || "—";
    const loc =
      c.locator ||
      (c.network ? `Network ${c.network}` : "") ||
      (typeof c.line === "number" ? `line ${c.line}` : "");
    const snip = c.snippet || c.evidence || "";
    const status = c.source_status ? ` · ${c.source_status}` : "";
    const head = `- [${i + 1}] \`${block}\`${loc ? ` · ${loc}` : ""}${status}`;
    return snip ? `${head}\n  - ${snip}` : head;
  });
  return `\n\n#### 引用源（网关真实 citations）\n${lines.join("\n")}`;
}
