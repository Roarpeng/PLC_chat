/**
 * PCEC 变更事务（docs/19-pcec-contract.md §1/§5）——前端数据层。
 *
 * - 「每次写回都是一个可审计事务」：本模块只做取数与展示归一，
 *   不做任何状态机迁移（那是后端 plc_engine/pcec.py 的职责）。
 * - GET /api/v1/plc/canvas/changes        → meta 列表（fetchChanges）
 *   GET /api/v1/plc/canvas/changes/{id}   → 完整事务（fetchChange）
 *   两者均走 lib/plcGateway.requestPlc（统一 base URL / GatewayError / data 解包）。
 * - mock-first：404 / 网关不可达 / 响应形态不符时回退一条内置示例事务，
 *   标注 origin="mock"（UI 显示「示例」徽标），只打一条 console.debug，
 *   绝不向 UI 抛错——PCEC 是"记账员"，不做"新故障点"（契约 §4 兼容原则）。
 * - V 等级四态文案（契约 §5）：pass=已通过 / fail=未通过 / pending=待执行 /
 *   skipped|未设=未运行——未知 ≠ 通过。
 */
import { requestPlc } from "../lib/plcGateway";

/* ------------------------------------------------------------------ */
/* V 等级与状态文案                                                     */
/* ------------------------------------------------------------------ */

export type PcecVStatus = "pass" | "fail" | "pending" | "skipped";

export type PcecVLevelKey = "v0_parsed" | "v1_static" | "v2_tia_compile" | "v3_behavior";

/** 四级验证等级：列表徽章用短标签，确认弹窗用全称 */
export const V_LEVELS: Array<{ key: PcecVLevelKey; label: string; full: string }> = [
  { key: "v0_parsed", label: "V0 结构", full: "V0 结构解析" },
  { key: "v1_static", label: "V1 静态", full: "V1 静态预检" },
  { key: "v2_tia_compile", label: "V2 编译", full: "V2 TIA 编译" },
  { key: "v3_behavior", label: "V3 行为", full: "V3 行为验证" },
];

const V_STATUS_TEXT: Record<PcecVStatus, string> = {
  pass: "已通过",
  fail: "未通过",
  pending: "待执行",
  skipped: "未运行",
};

export function isPcecVStatus(value: unknown): value is PcecVStatus {
  return (
    value === "pass" || value === "fail" || value === "pending" || value === "skipped"
  );
}

/** 归一：契约四态之外的值（未设 / 脏数据）一律按「未运行」展示——未知≠通过 */
export function vStatusOf(value: unknown): PcecVStatus {
  return isPcecVStatus(value) ? value : "skipped";
}

/** 四态文案：pass=已通过 / fail=未通过 / pending=待执行 / skipped|未设=未运行 */
export function vStatusText(value: unknown): string {
  return V_STATUS_TEXT[vStatusOf(value)];
}

/** 徽章前置符号：✓ 已通过 / ✗ 未通过 / · 待执行与未运行 */
export function vStatusMark(value: unknown): string {
  const st = vStatusOf(value);
  return st === "pass" ? "✓" : st === "fail" ? "✗" : "·";
}

/** 事务状态机九态文案（契约 §2）；未登记的值原样透出（后端新增状态不丢信息） */
const CHANGE_STATUS_TEXT: Record<string, string> = {
  proposed: "已提议",
  analyzed: "已分析",
  validated: "已验证",
  approved: "已批准",
  applied: "已应用",
  failed: "失败",
  expired: "已过期",
  rejected: "已拒绝",
  rolled_back: "已回滚",
};

export function changeStatusText(status: unknown): string {
  const key = String(status ?? "").trim();
  if (!key) return "未知";
  return CHANGE_STATUS_TEXT[key] ?? key;
}

/** 状态徽章分组：ok=终态成功 / bad=终态失败族 / hold=流转中 */
export type ChangeStatusGroup = "ok" | "bad" | "hold";

export function changeStatusGroup(status: unknown): ChangeStatusGroup {
  const key = String(status ?? "").trim();
  if (key === "applied") return "ok";
  if (key === "failed" || key === "expired" || key === "rejected" || key === "rolled_back") {
    return "bad";
  }
  return "hold";
}

/**
 * 确认弹窗时刻的 V 等级快照（契约 §5）：
 * V0 结构解析 ✓ / V1 静态预检 ✓（画布导入即解析、确认门禁前已完成静态检查），
 * V2 TIA 编译 ·待执行 / V3 行为验证 ·未运行。
 */
export const CONFIRM_V_SNAPSHOT: Record<PcecVLevelKey, PcecVStatus> = {
  v0_parsed: "pass",
  v1_static: "pass",
  v2_tia_compile: "pending",
  v3_behavior: "skipped",
};

/* ------------------------------------------------------------------ */
/* 事务对象（契约 §1 的前端镜像，字段宽松可选）                          */
/* ------------------------------------------------------------------ */

/** GET /canvas/changes 的 meta 条目（后端 list_changes 只回 meta；此处防御性归一） */
export interface PcecChangeMeta {
  change_id: string;
  /** intent.kind（writeback|nl_edit|fix|import） */
  kind: string;
  /** 一句话意图摘要 */
  summary: string;
  status: string;
  /** epoch 秒 */
  updated_at: number;
  /** 影响块数 */
  touched_count: number;
  /** meta 若携带 verification 摘要则列表徽章直接点亮，否则展开详情后点亮 */
  verification?: Partial<Record<PcecVLevelKey, string>> | null;
}

/** 完整变更事务（纯 dict，JSON 可序列化；保留后端新增字段的通道） */
export interface PcecChange {
  change_id: string;
  created_at?: number;
  updated_at?: number;
  project_baseline?: {
    project_hash?: string;
    tia_version?: string;
    parser_version?: string;
  } | null;
  intent?: { kind?: string; request?: string; summary?: string } | null;
  ops?: unknown[];
  touched_blocks?: string[];
  preconditions?: Array<{ name?: string; ok?: boolean }>;
  impact?: { blocks?: string[]; signals?: string[]; hmi_widgets?: string[] } | null;
  verification?: Record<string, unknown> | null;
  approval?: { reviewer?: string; approved_at?: number; scope?: string } | null;
  rollback?: {
    backup_path?: string;
    backup_hash?: string;
    restore_verified?: boolean;
  } | null;
  status?: string;
  events?: Array<{ ts?: number; event?: string }>;
  [key: string]: unknown;
}

/* ------------------------------------------------------------------ */
/* 归一与展示工具                                                       */
/* ------------------------------------------------------------------ */

function toEpochSeconds(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

/**
 * 把网关 meta 条目（或完整事务）归一为列表行。
 * change_id 缺失的坏行返回 null（跳过，对齐后端 list_changes 的容错语义）。
 */
export function normalizeChangeMeta(raw: unknown): PcecChangeMeta | null {
  const r = asRecord(raw);
  if (!r) return null;
  const id = String(r.change_id ?? r.id ?? "").trim();
  if (!id) return null;

  const intent = asRecord(r.intent);
  const touchedNumber = r.touched_count ?? r.touched;
  const touchedBlocks = Array.isArray(r.touched_blocks) ? r.touched_blocks : null;
  const impactBlocks = Array.isArray(asRecord(r.impact)?.blocks)
    ? (asRecord(r.impact)?.blocks as unknown[])
    : null;
  const touchedCount =
    typeof touchedNumber === "number" && Number.isFinite(touchedNumber)
      ? touchedNumber
      : touchedBlocks
        ? touchedBlocks.length
        : impactBlocks
          ? impactBlocks.length
          : 0;

  const verif = asRecord(r.verification);
  return {
    change_id: id,
    kind: String(r.kind ?? intent?.kind ?? ""),
    summary: String(r.summary ?? intent?.summary ?? intent?.request ?? ""),
    status: String(r.status ?? ""),
    updated_at: toEpochSeconds(r.updated_at ?? r.created_at),
    touched_count: touchedCount,
    verification: verif
      ? {
          v0_parsed: verif.v0_parsed as string | undefined,
          v1_static: verif.v1_static as string | undefined,
          v2_tia_compile: verif.v2_tia_compile as string | undefined,
          v3_behavior: verif.v3_behavior as string | undefined,
        }
      : null,
  };
}

/** chg-<hex12> → 短码（12 位 hex 取前 8 位）；不合规 id 退最后 8 字符，空 → — */
export function shortChangeId(changeId: unknown): string {
  const id = String(changeId ?? "").trim();
  if (!id) return "—";
  const m = /^chg-([0-9a-f]{12})$/i.exec(id);
  if (m) return m[1].slice(0, 8).toLowerCase();
  return id.length > 8 ? id.slice(id.length - 8) : id;
}

/** 基线指纹：project_hash 去掉 sha256: 前缀后取前 12 位；缺失 → — */
export function baselineFingerprint(source?: { project_hash?: string | null } | null): string {
  const raw = String(source?.project_hash ?? "").trim();
  if (!raw) return "—";
  const hex = raw.replace(/^sha256:/i, "");
  return hex.slice(0, 12).toLowerCase() || "—";
}

/** epoch 秒 → 本地时间 "MM-DD HH:mm"（账本列表用；非法值 → —） */
export function formatChangeTime(epochSeconds: unknown): string {
  const n = Number(epochSeconds);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const d = new Date(n * 1000);
  const p2 = (v: number) => String(v).padStart(2, "0");
  return `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/** 展开条目用的 JSON 摘要（ops 快照可达 MB 级，超长截断防撑爆 <pre>） */
export function changeJsonPreview(change: unknown, maxChars = 24_000): string {
  let text: string;
  try {
    text = JSON.stringify(change, null, 2);
  } catch {
    return String(change);
  }
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n…（展示已截断，完整事务共 ${text.length} 字符）`;
}

/* ------------------------------------------------------------------ */
/* 内置 mock：一条示例事务（网关 PCEC 端点未就绪时的开发回退）           */
/* ------------------------------------------------------------------ */

/** mock 示例事务 id（合法契约格式 chg-<hex12>，仅用于回退展示与测试断言） */
export const MOCK_CHANGE_ID = "chg-0a1b2c3d4e5f";

const MOCK_CHANGE: PcecChange = {
  change_id: MOCK_CHANGE_ID,
  created_at: 1_790_000_000.0,
  updated_at: 1_790_000_042.0,
  project_baseline: {
    project_hash: "sha256:e3b0c44298fc1c14afae4c3c7b7c5f2b8a5e1d0f",
    tia_version: "V19",
    parser_version: "0.1",
  },
  intent: {
    kind: "writeback",
    request: "回写 FB_Motor 启保停逻辑与速度给定",
    summary: "回写 2 个块到博图并触发编译校验（示例）",
  },
  ops: [
    { op: "upsert_block", name: "FB_Motor", language: "SCL" },
    { op: "upsert_block", name: "DB_MotorData", language: "SCL" },
  ],
  touched_blocks: ["FB_Motor", "DB_MotorData"],
  preconditions: [
    { name: "目标块存在", ok: true },
    { name: "基线未变化", ok: true },
  ],
  impact: { blocks: ["FB_Motor", "DB_MotorData"], signals: [], hmi_widgets: [] },
  verification: {
    v0_parsed: "pass",
    v1_static: "pass",
    v2_tia_compile: "pass",
    v3_behavior: "skipped",
    detail: { compile_job_id: "job-example-01", error_count: 0, diagnostics: [] },
  },
  approval: {
    reviewer: "engineer",
    approved_at: 1_790_000_001.0,
    scope: "FB_Motor, DB_MotorData",
  },
  rollback: {
    backup_path: "C:/PLC/backups/FB_Motor_20261024.bak",
    backup_hash: "sha256:0123456789abcdef0123456789abcdef",
    restore_verified: false,
  },
  status: "applied",
  events: [
    { ts: 1_790_000_000.0, event: "created" },
    { ts: 1_790_000_005.0, event: "analyzed" },
    { ts: 1_790_000_001.0, event: "approved" },
    { ts: 1_790_000_010.0, event: "write_started" },
    { ts: 1_790_000_040.0, event: "compile_ok" },
    { ts: 1_790_000_042.0, event: "applied" },
  ],
};

/** 取内置示例事务（深拷贝，不触网，不抛错） */
export function mockChange(): PcecChange {
  return JSON.parse(JSON.stringify(MOCK_CHANGE)) as PcecChange;
}

/** 取内置示例事务的列表行（走同一归一管道，保证 meta/事务口径一致） */
export function mockChangeMeta(): PcecChangeMeta {
  return normalizeChangeMeta(MOCK_CHANGE) as PcecChangeMeta;
}

/* ------------------------------------------------------------------ */
/* 取数（mock-first）                                                   */
/* ------------------------------------------------------------------ */

export type PcecOrigin = "gateway" | "mock";

export interface PcecChangesResult {
  items: PcecChangeMeta[];
  origin: PcecOrigin;
}

export interface PcecChangeResult {
  change: PcecChange;
  origin: PcecOrigin;
}

const errText = (err: unknown): string =>
  err instanceof Error ? err.message : String(err);

/**
 * 拉取变更账本列表（GET /api/v1/plc/canvas/changes）。
 * 网关正常但账本为空 → items=[] 且 origin="gateway"（空账本是真实答案，不回退）；
 * 404 / 网关不可达 / 响应形态不符 → 一条内置示例事务（origin="mock"，UI 标「示例」）。
 */
export async function fetchChanges(opts?: { signal?: AbortSignal }): Promise<PcecChangesResult> {
  try {
    const res = await requestPlc<unknown>(`/api/v1/plc/canvas/changes`, {
      signal: opts?.signal ?? AbortSignal.timeout?.(8000),
    });
    if (!Array.isArray(res)) {
      throw new Error("changes 响应不是数组");
    }
    const items = res
      .map(normalizeChangeMeta)
      .filter((x): x is PcecChangeMeta => x !== null);
    return { items, origin: "gateway" };
  } catch (err) {
    // 404（端点未上线）/ 超时 / 网关不可达：一条 debug 日志 + 示例回退，不打扰用户
    console.debug(`[pcec] 变更账本拉取失败（${errText(err)}），回退内置示例事务`);
    return { items: [mockChangeMeta()], origin: "mock" };
  }
}

/**
 * 拉取一条完整事务（GET /api/v1/plc/canvas/changes/{id}）。
 * 示例 id 不触网直接回 mock；真实 id 拉取失败同样回退示例（UI 标「示例」），
 * 不向调用方抛错。空 id 返回 null（防御：列表坏行不会进入展开态）。
 */
export async function fetchChange(
  changeId: string,
  opts?: { signal?: AbortSignal },
): Promise<PcecChangeResult | null> {
  const id = String(changeId ?? "").trim();
  if (!id) return null;
  if (id === MOCK_CHANGE_ID) {
    return { change: mockChange(), origin: "mock" };
  }
  try {
    const res = await requestPlc<unknown>(
      `/api/v1/plc/canvas/changes/${encodeURIComponent(id)}`,
      { signal: opts?.signal ?? AbortSignal.timeout?.(8000) },
    );
    const r = asRecord(res);
    if (!r) throw new Error("空事务响应");
    const change = {
      ...r,
      change_id: String(r.change_id ?? r.id ?? id),
    } as PcecChange;
    return { change, origin: "gateway" };
  } catch (err) {
    console.debug(`[pcec] 事务 ${id} 拉取失败（${errText(err)}），回退内置示例事务`);
    return { change: mockChange(), origin: "mock" };
  }
}
