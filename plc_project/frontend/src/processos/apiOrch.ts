import { actorHeaders } from "./actor";
import type { Contract, TraceGraphs } from "./types";

/* 需求 c —— 工位编排（Unit 级 EM 运行步序）独立 API 模块。
   刻意不改 api.ts：本模块只做三件事——装载契约（operations/resources/schedule）、
   装载追溯四图（af_em 对象，仅用于显示映射）、把「保存调度」组装成
   set_operation_schedule patch 走既有 POST /projects/{pid}/patches 通道。
   绑定风格与 api.ts 一致：actorHeaders() 演示身份传递、错误统一带 status。 */

export const ORCH_BASE = "/api/processos";

/** 契约层调度声明条目（后端 ProcessContract.schedule，由 patch op 写入）。 */
export interface ScheduleEntry {
  em: string;
  order: number;
  resource_ids: string[];
  mode?: string;
  parallel_with?: string[];
}

/** ProcessContract 的前端形状 + 可选 schedule 承载字段（types.ts 禁改，本地扩展）。 */
export type ContractWithSchedule = Contract & { schedule?: ScheduleEntry[] };

export class OrchApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function orchReq<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${ORCH_BASE}${path}`, {
    method,
    headers: { ...actorHeaders(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: Record<string, unknown> = {};
  if (text) { try { data = JSON.parse(text) as Record<string, unknown>; } catch { data = {}; } }
  if (!res.ok)
    throw new OrchApiError(res.status, String(data.error || data.detail || res.statusText));
  return data as T;
}

export interface OrchProjectPayload { contract: ContractWithSchedule; revision: number; profile_id: string }
export interface PatchAcceptedPayload { revision: number; contract: ContractWithSchedule }

export const orchApi = {
  /** GET /projects/{pid} —— 契约（operations/resources/可选 schedule）+ 当前 revision。 */
  project: (pid: string) => orchReq<OrchProjectPayload>("GET", `/projects/${pid}`),
  /** GET /trace/graphs —— af_em 对象注册（EM 显示名/Unit 归属），仅显示用。 */
  traceGraphs: () => orchReq<TraceGraphs>("GET", "/trace/graphs"),
  /** POST /projects/{pid}/patches —— set_operation_schedule（走既有版本化原子 patch 通道）。 */
  saveSchedule: (pid: string, baseRevision: number, schedule: ScheduleEntry[], requestId = "") =>
    orchReq<PatchAcceptedPayload>("POST", `/projects/${pid}/patches`, {
      base_revision: baseRevision,
      request_id: requestId,
      source: "user",
      ops: [{ op: "set_operation_schedule", path: "/schedule", schedule }],
    }),
};
