/**
 * 工艺需求卡（ProcessRequirement，docs/22-workbench-p0-contract.md §1/§2）——前端数据层。
 *
 * - 「需求先行」：工程师先把工艺意图讲清楚（items 七字段拆解 + open_questions），
 *   确认（confirmation_status=confirmed）**仅表示工艺意图已确认**，
 *   绝不触发任何 ops / 写回（前后端共同的铁律，契约 §1）。
 * - 五个 API 全走 lib/plcGateway.requestPlc（统一 base URL / GatewayError / data 解包）：
 *   GET    /api/v1/plc/canvas/requirements        → meta 列表（fetchRequirements）
 *   GET    /api/v1/plc/canvas/requirements/{id}   → 完整对象（fetchRequirement）
 *   PUT    /api/v1/plc/canvas/requirements/{id}   → 整对象 upsert（putRequirement）
 *   DELETE /api/v1/plc/canvas/requirements/{id}   → 删除（deleteRequirement）
 *   POST   /api/v1/plc/canvas/requirements/draft  → LLM 草稿（requestDraft）
 * - mock-first：404 / 网络错 / 响应形态不符时回退内置示例卡（id req-mockdemo001），
 *   标注 origin="mock"（UI 显示「示例」徽标），只打一条 console.debug，
 *   绝不向 UI 抛错（对齐 state/pcec.ts 的兼容原则——后端 B 线未上线时前端照常可用）。
 *   putRequirement 的回退是**回显提交对象**（标 mock）：离线编辑时不能把工程师
 *   刚改的内容替换成示例卡；requestDraft 的回退是携带 prompt/task_kind 的示例草稿。
 */
import { requestPlc } from "../lib/plcGateway";

/* ------------------------------------------------------------------ */
/* 类型（契约 §1 的前端镜像）                                          */
/* ------------------------------------------------------------------ */

/** items.kind 五类：前置 / 序列 / 异常 / 约束 / 验收 */
export type RequirementItemKind =
  | "precondition"
  | "sequence"
  | "exception"
  | "constraint"
  | "acceptance";

/** items.source 三态：工程证据（带 source_ref）/ 用户输入 / AI 推断 */
export type RequirementItemSource = "engineering" | "user" | "inferred";

/** 确认三态：proposed=待确认 / confirmed=已确认（仅工艺意图）/ rejected=已拒绝 */
export type RequirementStatus = "proposed" | "confirmed" | "rejected";

/** 任务四类（与 TaskQuickBar 的 TaskKind 同一联合类型） */
export type TaskKind = "understand" | "diagnose" | "improve" | "refactor";

export interface RequirementItem {
  id: string;
  kind: RequirementItemKind;
  text: string;
  source: RequirementItemSource;
  /** engineering 来源的证据定位（如 "FB5002 NW1"）；user/inferred 不带 */
  source_ref?: string;
}

export interface Requirement {
  requirement_id: string;
  project_name: string;
  /** epoch 秒 */
  created_at: number;
  updated_at: number;
  confirmation_status: RequirementStatus;
  /** 一句话工艺意图 */
  intent_summary: string;
  items: RequirementItem[];
  /** 待工程师确认的问题（超时参数等未知值不填数值、进这里——契约 §2 draft 铁律） */
  open_questions: string[];
  linked_blocks: string[];
  linked_signals: string[];
  task_kind: TaskKind;
  /** 生成这张卡的用户原始输入 */
  origin_prompt: string;
}

/** GET /canvas/requirements 的 meta 条目（列表行） */
export interface RequirementMeta {
  requirement_id: string;
  summary: string;
  status: string;
  /** epoch 秒 */
  updated_at: number;
  task_kind: string;
}

export type RequirementOrigin = "gateway" | "mock";

export interface RequirementListResult {
  items: RequirementMeta[];
  origin: RequirementOrigin;
}

export interface RequirementResult {
  requirement: Requirement;
  origin: RequirementOrigin;
}

export interface RequirementDeleteResult {
  deleted: boolean;
  origin: RequirementOrigin;
}

/* ------------------------------------------------------------------ */
/* 展示常量（分组顺序 / 徽章文案）                                      */
/* ------------------------------------------------------------------ */

/** items 分组渲染顺序与中文组名（五类齐全，UI 与测试共用） */
export const REQUIREMENT_ITEM_KINDS: Array<{ kind: RequirementItemKind; label: string }> = [
  { kind: "precondition", label: "前置条件" },
  { kind: "sequence", label: "正常序列" },
  { kind: "exception", label: "异常分支" },
  { kind: "constraint", label: "约束" },
  { kind: "acceptance", label: "验收条件" },
];

/** 来源徽章文案：engineering=绿·工程证据 / user=蓝·用户输入 / inferred=琥珀·AI 推断 */
export const REQUIREMENT_SOURCE_LABELS: Record<RequirementItemSource, string> = {
  engineering: "工程证据",
  user: "用户输入",
  inferred: "AI 推断",
};

/** 确认状态文案（徽章用） */
export const REQUIREMENT_STATUS_TEXT: Record<RequirementStatus, string> = {
  proposed: "待确认",
  confirmed: "已确认",
  rejected: "已拒绝",
};

/** 任务四类文案（TaskQuickBar 按钮共用） */
export const TASK_KIND_LABELS: Record<TaskKind, string> = {
  understand: "理解工程",
  diagnose: "诊断问题",
  improve: "完善工艺逻辑",
  refactor: "重构程序",
};

/* ------------------------------------------------------------------ */
/* 归一（宽松可选字段 → 严格前端类型；坏行跳过，坏对象 null）            */
/* ------------------------------------------------------------------ */

const isItemKind = (v: unknown): v is RequirementItemKind =>
  v === "precondition" ||
  v === "sequence" ||
  v === "exception" ||
  v === "constraint" ||
  v === "acceptance";

const isSource = (v: unknown): v is RequirementItemSource =>
  v === "engineering" || v === "user" || v === "inferred";

const isTaskKind = (v: unknown): v is TaskKind =>
  v === "understand" || v === "diagnose" || v === "improve" || v === "refactor";

/** 来源归一：契约三态之外的值一律按「AI 推断」展示（不确定 ≠ 工程证据） */
export function itemSourceOf(value: unknown): RequirementItemSource {
  return isSource(value) ? value : "inferred";
}

/** 确认状态归一：未知一律「待确认」（绝不因脏数据默认成已确认） */
export function requirementStatusOf(value: unknown): RequirementStatus {
  return value === "confirmed" || value === "rejected" ? value : "proposed";
}

/** 任务归一：未知一律「理解工程」（最保守的只读任务） */
export function taskKindOf(value: unknown): TaskKind {
  return isTaskKind(value) ? value : "understand";
}

function toEpochSeconds(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => String(v ?? "").trim()).filter((s) => s.length > 0);
}

/**
 * 把网关对象归一为 Requirement。
 * requirement_id 缺失或 items 不是数组 → null（形状不符，调用方走 mock 回退）；
 * item 行内脏数据（无文本 / kind 不明）跳过，id 缺失时按序号补 "it-<n>"。
 */
export function normalizeRequirement(raw: unknown): Requirement | null {
  const r = asRecord(raw);
  if (!r) return null;
  const id = String(r.requirement_id ?? r.id ?? "").trim();
  if (!id) return null;
  if (!Array.isArray(r.items)) return null;

  const items: RequirementItem[] = [];
  for (const rawItem of r.items) {
    const it = asRecord(rawItem);
    if (!it) continue;
    const text = String(it.text ?? "").trim();
    if (!text || !isItemKind(it.kind)) continue;
    const sourceRef = String(it.source_ref ?? "").trim();
    items.push({
      id: String(it.id ?? "").trim() || `it-${items.length + 1}`,
      kind: it.kind,
      text,
      source: itemSourceOf(it.source),
      ...(sourceRef ? { source_ref: sourceRef } : {}),
    });
  }

  return {
    requirement_id: id,
    project_name: String(r.project_name ?? ""),
    created_at: toEpochSeconds(r.created_at),
    updated_at: toEpochSeconds(r.updated_at ?? r.created_at),
    confirmation_status: requirementStatusOf(r.confirmation_status),
    intent_summary: String(r.intent_summary ?? r.summary ?? ""),
    items,
    open_questions: toStringArray(r.open_questions),
    linked_blocks: toStringArray(r.linked_blocks),
    linked_signals: toStringArray(r.linked_signals),
    task_kind: taskKindOf(r.task_kind),
    origin_prompt: String(r.origin_prompt ?? r.prompt ?? ""),
  };
}

/** 把列表 meta 条目归一为 RequirementRow；requirement_id 缺失返回 null（跳过坏行） */
export function normalizeRequirementMeta(raw: unknown): RequirementMeta | null {
  const r = asRecord(raw);
  if (!r) return null;
  const id = String(r.requirement_id ?? r.id ?? "").trim();
  if (!id) return null;
  return {
    requirement_id: id,
    summary: String(r.summary ?? r.intent_summary ?? ""),
    status: requirementStatusOf(r.confirmation_status ?? r.status),
    updated_at: toEpochSeconds(r.updated_at ?? r.created_at),
    task_kind: taskKindOf(r.task_kind),
  };
}

/** req-<hex12> → 短码（去前缀取前 8 位）；不合规退末 8 字符，空 → — */
export function shortRequirementId(requirementId: unknown): string {
  const id = String(requirementId ?? "").trim();
  if (!id) return "—";
  const m = /^req-([0-9a-z]{6,})$/i.exec(id);
  if (m) return m[1].slice(0, 8).toLowerCase();
  return id.length > 12 ? id.slice(id.length - 8) : id;
}

/* ------------------------------------------------------------------ */
/* 内置 mock：一张示例需求卡（后端需求端点未就绪时的开发回退）           */
/* ------------------------------------------------------------------ */

/** mock 示例需求卡 id（仅用于回退展示与测试断言） */
export const MOCK_REQUIREMENT_ID = "req-mockdemo001";

const MOCK_REQUIREMENT: Requirement = {
  requirement_id: MOCK_REQUIREMENT_ID,
  project_name: "HR001_PLC_20260509",
  created_at: 1_790_000_000.0,
  updated_at: 1_790_000_042.0,
  confirmation_status: "proposed",
  intent_summary: "安全门联锁前提下完成工件夹紧与钻孔轴进给（示例）",
  items: [
    {
      id: "it-1",
      kind: "precondition",
      text: "工件到位、自动模式有效",
      source: "engineering",
      source_ref: "FB5002 NW1",
    },
    {
      id: "it-2",
      kind: "precondition",
      text: "安全门必须处于关闭且锁定状态",
      source: "engineering",
      source_ref: "FB5002_SafetyDoorV1 NW2",
    },
    {
      id: "it-3",
      kind: "sequence",
      text: "夹紧缸压紧 → 钻孔轴快进 → 工进到位 → 快退回原位",
      source: "user",
    },
    {
      id: "it-4",
      kind: "sequence",
      text: "钻孔完成后松夹、排气退回，等待取件",
      source: "inferred",
    },
    {
      id: "it-5",
      kind: "exception",
      text: "安全门开启时立即停止进给，夹紧保持",
      source: "engineering",
      source_ref: "FB5002 NW5",
    },
    {
      id: "it-6",
      kind: "constraint",
      text: "夹紧压力未到位禁止进给轴启动",
      source: "engineering",
      source_ref: "FB5001_ClampV1 NW3",
    },
    {
      id: "it-7",
      kind: "acceptance",
      text: "单循环节拍满足产线要求（具体数值需工程师确认）",
      source: "inferred",
    },
  ],
  open_questions: [
    "夹紧超时时间取多少秒？（必须工程师确认）",
    "安全门开启时夹紧是否保持？（必须工程师确认）",
  ],
  linked_blocks: ["FB5002_SafetyDoorV1", "FB5001_ClampV1"],
  linked_signals: ["i_bPartPresent", "i_bAutoMode"],
  task_kind: "improve",
  origin_prompt: "帮我完善安全门联锁与夹紧的工艺逻辑",
};

/** 取内置示例卡（深拷贝，不触网，不抛错） */
export function mockRequirement(): Requirement {
  return JSON.parse(JSON.stringify(MOCK_REQUIREMENT)) as Requirement;
}

/** 取内置示例卡的列表行（走同一归一管道，保证 meta/详情口径一致） */
export function mockRequirementMeta(): RequirementMeta {
  return normalizeRequirementMeta(MOCK_REQUIREMENT) as RequirementMeta;
}

/* ------------------------------------------------------------------ */
/* 取数（mock-first，全部不抛错）                                       */
/* ------------------------------------------------------------------ */

const errText = (err: unknown): string =>
  err instanceof Error ? err.message : String(err);

/**
 * 拉取需求卡列表（GET /api/v1/plc/canvas/requirements）。
 * 网关正常但列表为空 → items=[] 且 origin="gateway"（空列表是真实答案，不回退）；
 * 404（端点未上线）/ 网关不可达 / 响应形态不符 → 一条内置示例卡（origin="mock"）。
 */
export async function fetchRequirements(
  opts?: { signal?: AbortSignal },
): Promise<RequirementListResult> {
  try {
    const res = await requestPlc<unknown>(`/api/v1/plc/canvas/requirements`, {
      signal: opts?.signal ?? AbortSignal.timeout?.(8000),
    });
    if (!Array.isArray(res)) {
      throw new Error("requirements 响应不是数组");
    }
    const items = res
      .map(normalizeRequirementMeta)
      .filter((x): x is RequirementMeta => x !== null);
    return { items, origin: "gateway" };
  } catch (err) {
    // 404 / 超时 / 网关不可达：一条 debug 日志 + 示例回退，不打扰用户
    console.debug(`[requirements] 需求列表拉取失败（${errText(err)}），回退内置示例卡`);
    return { items: [mockRequirementMeta()], origin: "mock" };
  }
}

/**
 * 拉取一张完整需求卡（GET /api/v1/plc/canvas/requirements/{id}）。
 * 示例 id 不触网直接回 mock；真实 id 拉取失败 / 形状不符同样回退示例（UI 标「示例」）。
 * 空 id 返回 null（防御）。
 */
export async function fetchRequirement(
  requirementId: string,
  opts?: { signal?: AbortSignal },
): Promise<RequirementResult | null> {
  const id = String(requirementId ?? "").trim();
  if (!id) return null;
  if (id === MOCK_REQUIREMENT_ID) {
    return { requirement: mockRequirement(), origin: "mock" };
  }
  try {
    const res = await requestPlc<unknown>(
      `/api/v1/plc/canvas/requirements/${encodeURIComponent(id)}`,
      { signal: opts?.signal ?? AbortSignal.timeout?.(8000) },
    );
    const requirement = normalizeRequirement(res);
    if (!requirement) throw new Error("需求卡响应形状不符");
    return { requirement, origin: "gateway" };
  } catch (err) {
    console.debug(`[requirements] 需求卡 ${id} 拉取失败（${errText(err)}），回退内置示例卡`);
    return { requirement: mockRequirement(), origin: "mock" };
  }
}

/**
 * 整对象 upsert（PUT /api/v1/plc/canvas/requirements/{id}）。
 * 网关成功 → 回传服务端归一对象；失败（404 / 网络错 / 形状不符）→ **回显提交对象**
 * 并标 origin="mock"（离线可继续编辑，绝不把工程师刚改的内容替换成示例卡）。
 * 仅确认工艺意图或改文案——本函数永远不触发任何 ops / 写回（契约 §1 铁律）。
 */
export async function putRequirement(
  requirement: Requirement,
  opts?: { signal?: AbortSignal },
): Promise<RequirementResult> {
  const id = String(requirement?.requirement_id ?? "").trim();
  const local = normalizeRequirement(requirement);
  if (!local || !id) {
    console.debug("[requirements] upsert 对象缺 id / 形状不符，按本地编辑回显（mock）");
    return {
      requirement: local ?? mockRequirement(),
      origin: "mock",
    };
  }
  try {
    const res = await requestPlc<unknown>(
      `/api/v1/plc/canvas/requirements/${encodeURIComponent(id)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requirement),
        signal: opts?.signal ?? AbortSignal.timeout?.(8000),
      },
    );
    const saved = normalizeRequirement(res);
    if (!saved) throw new Error("upsert 响应形状不符");
    return { requirement: saved, origin: "gateway" };
  } catch (err) {
    console.debug(`[requirements] 需求卡 ${id} 保存失败（${errText(err)}），按本地编辑回显（mock）`);
    return { requirement: local, origin: "mock" };
  }
}

/**
 * 删除需求卡（DELETE /api/v1/plc/canvas/requirements/{id}）。
 * 网关成功 → deleted=true；失败 → deleted=false 且 origin="mock"（一条 debug，不抛错）。
 */
export async function deleteRequirement(
  requirementId: string,
  opts?: { signal?: AbortSignal },
): Promise<RequirementDeleteResult> {
  const id = String(requirementId ?? "").trim();
  if (!id) return { deleted: false, origin: "mock" };
  try {
    await requestPlc<unknown>(
      `/api/v1/plc/canvas/requirements/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        signal: opts?.signal ?? AbortSignal.timeout?.(8000),
      },
    );
    return { deleted: true, origin: "gateway" };
  } catch (err) {
    console.debug(`[requirements] 需求卡 ${id} 删除失败（${errText(err)}），未删除（mock）`);
    return { deleted: false, origin: "mock" };
  }
}

/**
 * 生成需求卡草稿（POST /api/v1/plc/canvas/requirements/draft）。
 * body { prompt, canvas, task_kind }；LLM 未配置（400 LLM_NOT_CONFIGURED）/
 * 端点未上线 / 网络错 → 携带 prompt 与 task_kind 的内置示例草稿
 * （confirmation_status=proposed，origin="mock"，一条 debug，不抛错）。
 */
export async function requestDraft(
  prompt: string,
  canvas?: unknown,
  taskKind?: TaskKind,
  opts?: { signal?: AbortSignal },
): Promise<RequirementResult> {
  const body = {
    prompt: String(prompt ?? ""),
    canvas: canvas ?? null,
    task_kind: taskKind ?? null,
  };
  try {
    const res = await requestPlc<unknown>(`/api/v1/plc/canvas/requirements/draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      // LLM 草稿生成实测 15-40s(大画布上下文),20s 会必然超时回退 mock
      signal: opts?.signal ?? AbortSignal.timeout?.(90_000),
    });
    const requirement = normalizeRequirement(res);
    if (!requirement) throw new Error("draft 响应形状不符");
    return { requirement, origin: "gateway" };
  } catch (err) {
    console.debug(`[requirements] 草稿生成失败（${errText(err)}），回退内置示例草稿`);
    const draft = mockRequirement();
    draft.origin_prompt = body.prompt;
    if (taskKind) draft.task_kind = taskKind;
    draft.confirmation_status = "proposed";
    return { requirement: draft, origin: "mock" };
  }
}
