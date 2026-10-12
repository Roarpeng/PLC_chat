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

export const WS_BASE = GATEWAY_BASE
  ? GATEWAY_BASE.replace(/^http/, "ws")
  : "ws://localhost:8000";

export type TaskCreateResponse = {
  ok?: boolean;
  data?: {
    id?: string;
    query?: string;
    status?: string;
    plan?: unknown;
    evidence?: unknown[];
    result?: string | null;
    citations?: unknown[];
    events?: unknown[];
    interrupts?: unknown[];
    updated_at?: string;
    created_at?: string;
  };
  id?: string;
  query?: string;
  status?: string;
  plan?: unknown;
  evidence?: unknown[];
  result?: string | null;
  citations?: unknown[];
  events?: unknown[];
  interrupts?: unknown[];
  detail?: string;
};

export async function createResearchTask(
  query: string,
  mode: string,
  options?: { tiaExportDir?: string },
) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/research/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      query,
      mode,
      ...(options?.tiaExportDir?.trim()
        ? { tia_export_dir: options.tiaExportDir.trim() }
        : {}),
      options: {
        language: "zh-CN",
        enable_web: true,
        citation_required: true,
        report_format: ["markdown"],
        model_profile: "default",
      },
    }),
  });
  const text = await res.text();
  let body: TaskCreateResponse = {};
  try {
    body = text ? (JSON.parse(text) as TaskCreateResponse) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    throw new Error(body.detail || `Gateway ${res.status}`);
  }
  return body;
}

export async function listResearchTasks(limit = 40) {
  const res = await fetch(
    `${GATEWAY_BASE}/api/v1/research/tasks?limit=${limit}`,
    { headers: { Accept: "application/json" } },
  );
  return parseJsonArray(res);
}

export async function deleteResearchTask(taskId: string) {
  const headers = { Accept: "application/json" };
  // Prefer DELETE; fall back to POST alias if proxy/gateway returns 405.
  let res = await fetch(`${GATEWAY_BASE}/api/v1/research/tasks/${taskId}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 405) {
    res = await fetch(`${GATEWAY_BASE}/api/v1/research/tasks/${taskId}/delete`, {
      method: "POST",
      headers,
    });
  }
  const text = await res.text();
  let body: { detail?: string | { message?: string }; ok?: boolean; data?: unknown } = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    const detail = body.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in detail
          ? String((detail as { message?: string }).message || res.statusText)
          : `Gateway ${res.status}`;
    throw new Error(msg);
  }
  return body;
}

async function parseJsonArray(res: Response): Promise<TaskCreateResponse["data"][]> {
  const text = await res.text();
  let body: { detail?: string; data?: unknown; ok?: boolean } = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Gateway ${res.status}`,
    );
  }
  const data = body.data ?? body;
  return Array.isArray(data) ? (data as TaskCreateResponse["data"][]) : [];
}

export async function fetchTask(taskId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/research/tasks/${taskId}`, {
    headers: { Accept: "application/json" },
  });
  const text = await res.text();
  let body: TaskCreateResponse = {};
  try {
    body = text ? (JSON.parse(text) as TaskCreateResponse) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    throw new Error(body.detail || `Gateway ${res.status}`);
  }
  return body;
}

export async function resumeTask(
  taskId: string,
  resolution: string = "approve",
  interruptId?: string,
) {
  const res = await fetch(
    `${GATEWAY_BASE}/api/v1/research/tasks/${taskId}/resume`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ resolution, interrupt_id: interruptId }),
    },
  );
  const text = await res.text();
  let body: TaskCreateResponse = {};
  try {
    body = text ? (JSON.parse(text) as TaskCreateResponse) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    throw new Error(body.detail || `Gateway ${res.status}`);
  }
  return body;
}

export async function cancelTask(taskId: string) {
  const res = await fetch(
    `${GATEWAY_BASE}/api/v1/research/tasks/${taskId}/cancel`,
    {
      method: "POST",
      headers: { Accept: "application/json" },
    },
  );
  const text = await res.text();
  let body: TaskCreateResponse = {};
  try {
    body = text ? (JSON.parse(text) as TaskCreateResponse) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    throw new Error(body.detail || `Gateway ${res.status}`);
  }
  return body;
}

export function unwrapTask(body: TaskCreateResponse) {
  const data = (body.data ?? body) as Record<string, unknown>;
  return {
    id: (data.id ?? body.id) as string | undefined,
    query: data.query as string | undefined,
    status: (data.status ?? body.status) as string | undefined,
    route: data.route as string | undefined,
    plc_job_id: data.plc_job_id as string | undefined,
    plan: data.plan ?? body.plan,
    evidence: data.evidence ?? body.evidence,
    result: data.result ?? body.result,
    citations: data.citations ?? body.citations,
    events: data.events ?? body.events,
    interrupts: data.interrupts ?? body.interrupts,
  };
}

export type KnowledgeCanvasPayload = {
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
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

export type ChatTurnResult = {
  task: ReturnType<typeof unwrapTask> & { id?: string };
  assistant_message: string;
  route: string;
  plc_job_id?: string | null;
  knowledge_canvas?: KnowledgeCanvasPayload;
  citations?: PlcCitation[];
};

export async function postChatTurn(options: {
  message: string;
  taskId?: string | null;
  file?: File | null;
  focusNodeId?: string | null;
  blockName?: string | null;
  canvasEdges?: unknown;
  canvasPositions?: unknown;
}) {
  const form = new FormData();
  form.append("message", options.message);
  if (options.taskId) form.append("task_id", options.taskId);
  if (options.file) form.append("file", options.file);
  if (options.focusNodeId) form.append("focus_node_id", options.focusNodeId);
  if (options.blockName) form.append("block_name", options.blockName);
  if (options.canvasEdges) {
    form.append("canvas_edges", JSON.stringify(options.canvasEdges));
  }
  if (options.canvasPositions) {
    form.append("canvas_positions", JSON.stringify(options.canvasPositions));
  }
  const res = await fetch(`${GATEWAY_BASE}/api/v1/chat/turns`, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
  });
  const text = await res.text();
  let body: { detail?: unknown; data?: ChatTurnResult; ok?: boolean } = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    const detail = body.detail;
    let msg = `Gateway ${res.status}`;
    if (typeof detail === "string") {
      msg = detail;
    } else if (detail && typeof detail === "object" && detail !== null) {
      const d = detail as { message?: string; code?: string; detail?: string };
      if (typeof d.message === "string" && d.message.trim()) {
        msg = d.message;
      } else if (typeof d.detail === "string") {
        msg = d.detail;
      }
    }
    throw new Error(msg);
  }
  const data = (body.data ?? body) as ChatTurnResult;
  const taskRaw = data.task as unknown as TaskCreateResponse["data"];
  return {
    assistant_message: data.assistant_message,
    route: data.route,
    plc_job_id: data.plc_job_id,
    knowledge_canvas: data.knowledge_canvas,
    citations: data.citations || [],
    task: unwrapTask({ data: taskRaw, ok: true }),
  };
}

/** Create a WebSocket connection to the research stream. */
export function connectResearchStream(
  taskId: string,
  onEvent: (event: Record<string, unknown>) => void,
  onError?: (err: Event) => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/api/v1/ws/research/${taskId}`);
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "auth", token: "dev", last_seq: 0 }));
  };
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data as string);
      onEvent(data);
    } catch {
      // ignore parse errors
    }
  };
  ws.onerror = (err) => {
    onError?.(err);
  };
  return ws;
}

/* ---- PLC Intelligence feature ---- */

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
  chat?: Array<{
    role: string;
    content: string;
    block_name?: string | null;
    citations?: PlcCitation[];
  }>;
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

export async function fetchPlcBrief(jobId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/brief`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<PlcProjectBrief>(res);
}

async function parseJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: { detail?: string; data?: T; ok?: boolean } = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text || res.statusText };
  }
  if (!res.ok) {
    const detail = body.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in (detail as object)
          ? String((detail as { message?: string }).message)
          : `Gateway ${res.status}`;
    throw new Error(msg);
  }
  return (body.data ?? body) as T;
}

export async function createPlcJobFromPath(path: string, projectName = "") {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      path,
      project_name: projectName,
      publish_graph: true,
    }),
  });
  return parseJson<PlcJobSummary>(res);
}

export async function createPlcJobFromUpload(file: File, projectName = "") {
  const form = new FormData();
  form.append("file", file);
  form.append("project_name", projectName);
  form.append("publish_graph", "true");
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/upload`, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
  });
  return parseJson<PlcJobSummary>(res);
}

export async function retryPlcStructure(jobId: string, names: string[] = []) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/structure/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ names }),
  });
  return parseJson<PlcJobDetail>(res);
}

export async function fetchPlcJob(jobId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<PlcJobDetail>(res);
}

/** Poll PLC job until ready/failed. Default interval 1.5s. */
export async function waitForPlcJob(
  jobId: string,
  options?: {
    intervalMs?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
    onProgress?: (detail: PlcJobDetail) => void;
  },
): Promise<PlcJobDetail> {
  const intervalMs = options?.intervalMs ?? 1500;
  const timeoutMs = options?.timeoutMs ?? 600_000;
  const start = Date.now();
  for (;;) {
    if (options?.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    const detail = await fetchPlcJob(jobId);
    options?.onProgress?.(detail);
    if (detail.status === "ready" || detail.status === "failed") {
      return detail;
    }
    if (Date.now() - start > timeoutMs) {
      throw new Error(`PLC 解析超时（${jobId}）`);
    }
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => resolve(), intervalMs);
      options?.signal?.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
}

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

export type ProjectBrief = {
  schema?: string;
  job_id?: string;
  project_name?: string;
  status?: string;
  sections?: {
    device_sensor_summary?: {
      schema?: string;
      owned_by?: string;
      total_cards?: number;
      cited?: number;
      annotated?: number;
      meaning_unconfirmed?: number;
      io_type_counts?: Record<string, number>;
      cards?: Array<Record<string, unknown>>;
      unconfirmed_ids?: string[];
      gaps?: string[];
    };
  };
  notes?: string[];
  card_count?: number;
};

export async function listPlcDeviceCards(
  jobId: string,
  opts?: { q?: string; io_type?: string; meaning_status?: string; kind?: string },
) {
  const qs = new URLSearchParams();
  if (opts?.q) qs.set("q", opts.q);
  if (opts?.io_type) qs.set("io_type", opts.io_type);
  if (opts?.meaning_status) qs.set("meaning_status", opts.meaning_status);
  if (opts?.kind) qs.set("kind", opts.kind);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/device-cards${suffix}`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<DeviceCardList>(res);
}

export async function fetchPlcDeviceCard(jobId: string, kind: string, name: string) {
  const res = await fetch(
    `${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/device-cards/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`,
    { headers: { Accept: "application/json" } },
  );
  return parseJson<DeviceSensorCard>(res);
}

export async function annotatePlcDeviceCard(
  jobId: string,
  kind: string,
  name: string,
  text: string,
  author = "",
) {
  const res = await fetch(
    `${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/device-cards/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/annotation`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ text, author }),
    },
  );
  return parseJson<DeviceSensorCard>(res);
}

export async function fetchPlcProjectBrief(jobId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/brief`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<ProjectBrief>(res);
}

export async function listPlcJobs() {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<PlcJobSummary[]>(res);
}

export async function chatPlcJob(
  jobId: string,
  message: string,
  blockName?: string,
) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      message,
      block_name: blockName || null,
    }),
  });
  return parseJson<{
    role: string;
    content: string;
    block_name?: string | null;
    citations?: PlcCitation[];
  }>(res);
}

export async function analyzePlcJob(jobId: string, blockName?: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ block_name: blockName || null }),
  });
  return parseJson<Record<string, unknown>>(res);
}

export type PlcGraphQueryBody = {
  op: "callers" | "callees" | "writers" | "readers" | "reachable" | "dead_blocks" | "depends" | "neighbors";
  block_name?: string | null;
  tag?: string | null;
  target_block?: string | null;
  roots?: string[] | null;
};

export type PlcGraphQueryResult = {
  op: string;
  result: unknown;
  evidence: Array<Record<string, unknown>>;
};

export async function queryPlcJob(jobId: string, body: PlcGraphQueryBody) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson<PlcGraphQueryResult>(res);
}

export async function proposePlcChanges(
  jobId: string,
  message: string,
  blockName?: string,
) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/changes`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      message,
      block_name: blockName || null,
    }),
  });
  return parseJson<Record<string, unknown>>(res);
}

export async function optimizePlcJob(
  jobId: string,
  options?: { blockName?: string; message?: string },
) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      block_name: options?.blockName || null,
      message: options?.message || "优化工程逻辑并准备反写",
    }),
  });
  return parseJson<{
    changeset?: Record<string, unknown>;
    optimize_plan?: string;
    ops?: number;
    scl_files?: Record<string, string>;
    scl_diffs?: Array<{
      block?: string;
      before?: string;
      after?: string;
      diff?: string;
      new_block?: boolean;
    }>;
    skipped?: Array<{ block?: string; reason?: string; detail?: string }>;
  }>(res);
}

export async function writebackPlcJob(
  jobId: string,
  projectPath?: string | null,
  options?: {
    plcName?: string;
    executeOpennessImport?: boolean;
    archiveZap?: boolean;
    xmlPaths?: string[];
    blockName?: string | null;
  },
) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/writeback`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      project_path: projectPath || null,
      plc_name: options?.plcName || "",
      accept_changeset: true,
      execute_openness_import: options?.executeOpennessImport ?? true,
      archive_zap: options?.archiveZap ?? true,
      xml_paths: options?.xmlPaths || [],
      block_name: options?.blockName || null,
    }),
  });
  return parseJson<Record<string, unknown>>(res);
}

export function plcExportUrl(jobId: string) {
  return `${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/export`;
}

export function plcZapUrl(jobId: string) {
  return `${GATEWAY_BASE}/api/v1/plc/jobs/${jobId}/zap`;
}

/* ---- LLM / Agent model settings ---- */

export type LlmModelInfo = {
  id: string;
  label: string;
  provider: string;
  kind?: string;
  requires_key?: string | null;
};

export type LlmSlotStatus = {
  id: string;
  label: string;
  kind?: string;
  configured: boolean;
  hint?: string | null;
  model?: string;
  base_url?: string;
  default_model?: string;
  default_base_url?: string;
  primary?: boolean;
  removable?: boolean;
  env_var?: string;
};

/** @deprecated use LlmSlotStatus */
export type LlmProviderStatus = LlmSlotStatus;

export type LlmAgentBinding = {
  research: string;
  planner: string;
  researcher: string;
  writer: string;
  plc: string;
  embed: string;
  rerank?: string;
};

export type LlmSettings = {
  catalog: LlmModelInfo[];
  agents: LlmAgentBinding;
  slots?: LlmSlotStatus[];
  providers: LlmSlotStatus[];
  litellm_base_url?: string | null;
  default_model?: string;
  notes?: string[];
};

export async function fetchLlmSettings() {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/llm`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<LlmSettings>(res);
}

export async function updateLlmSettings(body: {
  agents?: LlmAgentBinding;
  slots?: Record<string, { api_key?: string; model?: string; base_url?: string }>;
  providers?: Record<string, { api_key?: string; model?: string; base_url?: string }>;
  provider_keys?: Record<string, string>;
  add_slot?: "chat" | "embed" | "rerank";
  remove_slot?: string;
}) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/llm`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson<LlmSettings>(res);
}

export type LlmSlotTestResult = {
  ok: boolean;
  slot_id: string;
  kind: string;
  model?: string;
  base_url?: string;
  latency_ms?: number;
  message: string;
  detail?: string | null;
};

export async function testLlmSlot(body: {
  slot_id: string;
  api_key?: string;
  model?: string;
  base_url?: string;
}) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/llm/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson<LlmSlotTestResult>(res);
}

export type KnowledgeDocument = {
  id: string;
  title?: string | null;
  filename?: string | null;
  status?: string;
  chunk_count?: number;
  created_at?: string | null;
};

export type KnowledgeSpace = {
  id: string;
  name: string;
  description?: string | null;
  status?: string;
  document_count: number;
  workspace_id?: string | null;
  created_at?: string;
  documents?: KnowledgeDocument[];
};

export async function listKnowledgeSpaces() {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/spaces`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<KnowledgeSpace[]>(res);
}

export async function createKnowledgeSpace(name: string, description?: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/spaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ name, description }),
  });
  return parseJson<KnowledgeSpace>(res);
}

export async function uploadKnowledgeDocument(spaceId: string, file: File, title?: string) {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/spaces/${spaceId}/documents`, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
  });
  return parseJson<{
    id: string;
    knowledge_space_id: string;
    title?: string | null;
    status: string;
    chunk_count: number;
    entity_count?: number;
    message?: string;
  }>(res);
}

export type AgentToolItem = {
  id?: string | null;
  name: string;
  description?: string;
  enabled?: boolean;
  command?: string;
};

export type McpServerItem = {
  id?: string | null;
  name: string;
  description?: string;
  enabled?: boolean;
  transport?: string;
  command?: string;
  url?: string;
  args?: string;
};

export type SkillItem = {
  id?: string | null;
  name: string;
  description?: string;
  enabled?: boolean;
  path?: string;
  source?: string;
};

export type AgentWorkspaceSettings = {
  tools: AgentToolItem[];
  mcp_servers: McpServerItem[];
  skills: SkillItem[];
};

export async function fetchAgentWorkspace() {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/agent-workspace`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<AgentWorkspaceSettings>(res);
}

export async function updateAgentWorkspace(body: Partial<AgentWorkspaceSettings>) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/agent-workspace`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson<AgentWorkspaceSettings>(res);
}

export type KnowledgeStats = {
  space_id?: string | null;
  document_count: number;
  chunk_count: number;
  entity_count: number;
  relation_count: number;
  documents?: Array<{
    id: string;
    title?: string | null;
    filename?: string | null;
    status?: string;
    chunk_count?: number;
  }>;
  channels?: Record<string, boolean>;
};

export async function fetchKnowledgeStats(spaceId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/spaces/${spaceId}/stats`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<KnowledgeStats>(res);
}

export async function fetchKnowledgeGraph(spaceId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/spaces/${spaceId}/graph`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<{ nodes?: unknown[]; edges?: unknown[] }>(res);
}

export async function rebuildKnowledgeSpace(spaceId: string) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/spaces/${spaceId}/rebuild`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return parseJson<{ ok: boolean; chunk_count: number; warnings?: string[] }>(res);
}

export async function fetchKnowledgeChunks(spaceId: string, docId?: string, limit = 80) {
  const q = new URLSearchParams();
  if (docId) q.set("doc_id", docId);
  q.set("limit", String(limit));
  const res = await fetch(
    `${GATEWAY_BASE}/api/v1/knowledge/spaces/${spaceId}/chunks?${q.toString()}`,
    { headers: { Accept: "application/json" } },
  );
  return parseJson<{
    space_id?: string;
    doc_id?: string | null;
    count: number;
    chunks: KnowledgeChunk[];
  }>(res);
}

export type KnowledgeChunk = {
  chunk_id: string;
  doc_id?: string;
  source_file?: string;
  section_type?: string;
  text: string;
  chars?: number;
  has_vector?: boolean;
  dim?: number;
  vector_preview?: number[];
};

export async function searchKnowledge(
  query: string,
  spaceIds?: string[],
  topK = 6,
  mode: "hybrid" | "vector" = "hybrid",
) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/knowledge/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      query,
      knowledge_space_ids: spaceIds || [],
      top_k: topK,
      mode,
    }),
  });
  return parseJson<{
    query: string;
    hits: Array<{
      citation_id: string;
      score: number;
      text: string;
      source_id: string;
      metadata?: { channels?: string[]; chunk_id?: string };
    }>;
    diagnostics?: { channel_hits?: Record<string, number> };
    message?: string;
  }>(res);
}

export type HubMcpItem = {
  name: string;
  title?: string;
  description?: string;
  transport?: string;
  command?: string;
  args?: string;
  url?: string;
  hub?: string;
  source?: string;
};

export type HubSkillItem = {
  id: string;
  name: string;
  description?: string;
  owner?: string;
  repo?: string;
  path?: string;
  hub?: string;
  source_url?: string;
};

export async function searchMcpHub(query: string, limit = 20) {
  const q = new URLSearchParams({ query, limit: String(limit) });
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/hub/mcp?${q}`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<{ items: HubMcpItem[]; offline?: boolean; warning?: string; hub?: string }>(res);
}

export async function searchSkillsHub(query: string, limit = 20) {
  const q = new URLSearchParams({ query, limit: String(limit) });
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/hub/skills?${q}`, {
    headers: { Accept: "application/json" },
  });
  return parseJson<{ items: HubSkillItem[]; offline?: boolean; warning?: string; hub?: string }>(res);
}

export async function installMcpFromHub(item: HubMcpItem) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/hub/mcp/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ item }),
  });
  return parseJson<AgentWorkspaceSettings>(res);
}

export async function installSkillFromHub(item: HubSkillItem) {
  const res = await fetch(`${GATEWAY_BASE}/api/v1/settings/hub/skills/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ item }),
  });
  return parseJson<AgentWorkspaceSettings>(res);
}
