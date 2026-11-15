/* §1 L-loop diagnostics API — independent module (api.ts stays untouched).
   Read-level endpoints; actor headers are attached exactly like api.ts. */
import { actorHeaders } from "./actor";
import { ApiError, PROCESSOS_BASE } from "./api";

/* ===== request shapes locked to processos/diagnostics/service.py ===== */

/** 原生编译诊断输入：{block, line?, message}；块名映射不回时后端标 UNMAPPED_NATIVE_CODE。 */
export interface DiagInput {
  block: string;
  line?: number | null;
  message: string;
  code?: string;
  category?: string;
}

/** 块级歧义时后端列全的最新 build 候选（不猜归属）。 */
export interface DiagCandidate {
  source_map_id: string;
  semantic_object_id: string | null;
  behavior_step_id: string | null;
  display_name: string;
  scl_line_range: [number, number] | null;
  scl_location: string;
}

/** locate 命中：诊断 → SourceMap → 语义对象（CM/EM/Step）。 */
export interface DiagMapping {
  index: number;
  block: string;
  line: number | null;
  message: string;
  semantic_object_id: string | null;
  behavior_step_id: string | null;
  source_map_id: string | null;
  display_name: string;
  scl_line_range: [number, number] | null;
  scl_location: string; /* "行 a–b" | "块级定位（无行号）" */
  release_build_id: string;
  block_kind: string;
  instance_db: string;
  ownership: string;
  located: "line" | "block" | "block_ambiguous";
  candidates?: DiagCandidate[];
}

/** locate 未命中：不可映射不猜（§11）。 */
export interface DiagUnmapped {
  index: number;
  block: string;
  line: number | null;
  message: string;
  error_code: string; /* UNMAPPED_NATIVE_CODE */
  reason: string;
}

export interface RepairFixProposal {
  diagnostic: Record<string, unknown>;
  fix: { category: string; action: string };
  allowed: boolean;
  must_return_to_review: boolean; /* 恒真：候选变更回流审批 */
}

export interface RepairForbiddenSeen {
  diagnostic: Record<string, unknown>;
  category: string | null;
  reason: string;
}

export interface LocateResponse {
  project_id: string;
  mappings: DiagMapping[];
  unmapped: DiagUnmapped[];
  proposals: {
    proposals: RepairFixProposal[];
    forbidden_seen: RepairForbiddenSeen[];
    auto_applied: unknown[]; /* 恒空：无自动应用路径 */
    note: string;
  } | null;
  created_at: string;
}

/** compile-scope：建议范围（当前交付链总是全量，note 恒诚实说明）。 */
export interface CompileScopeResult {
  project_id: string;
  mode: "incremental" | "full";
  affected_blocks: string[];
  reason: string;
  note: string;
  ops_analyzed: number;
  unresolved_targets?: string[];
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${PROCESSOS_BASE}${path}`, {
    method,
    headers: { ...actorHeaders(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: Record<string, unknown> = {};
  if (text) { try { data = JSON.parse(text) as Record<string, unknown>; } catch { data = {}; } }
  if (!res.ok)
    throw new ApiError(
      res.status,
      String(data.error || data.detail || res.statusText),
      data.error_code !== undefined ? String(data.error_code) : data.code !== undefined ? String(data.code) : undefined,
    );
  return data as T;
}

export const diagApi = {
  /** POST /projects/{pid}/diagnostics/locate — 诊断批量定位（读级，无门禁）。 */
  locate: (pid: string, diagnostics: DiagInput[]) =>
    req<LocateResponse>("POST", `/projects/${pid}/diagnostics/locate`, { diagnostics }),
  /** POST /projects/{pid}/compile-scope — 待交付 ops 的建议编译范围。 */
  compileScope: (pid: string, ops: unknown[]) =>
    req<CompileScopeResult>("POST", `/projects/${pid}/compile-scope`, { ops }),
};
