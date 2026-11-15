import { actorHeaders } from "./actor";
import { ApiError } from "./api";

/* Import Agent (L) — standalone API module for /api/processos/import/*.
   Binding style mirrors api.ts (same {error, code, details} contract, same
   actorHeaders() demo identity pass-through) but stays a separate module so
   the import flow evolves without touching the frozen core client. */

export const IMPORT_BASE = "/api/processos/import";

export type Fidelity = "EXACT" | "PARTIAL" | "OPAQUE" | "PROTECTED";
export type ClaimKind = "station" | "component" | "em" | "cm" | "ob" | "other";

export interface ImportSignal { name: string; datatype: string; section: string }

export interface ParsedBlock {
  node_id: string;
  block_name: string;
  block_type: string;
  number: string;
  language: string;
  fidelity: Fidelity;
  signals: ImportSignal[] | "UNKNOWN";
  note: string;
  secondary_type?: string;
}

export interface ParseResult {
  parse_id: string;
  project_name: string;
  parsed_at: string;
  nodes: ParsedBlock[];
  stats: Record<string, number>;
}

export interface ClaimMapping {
  block_name: string;
  target_kind: ClaimKind;
  station_name?: string;
  display_name?: string;
  driver_hint?: string;
}

export interface ClaimedObject { object_id: string; block_name: string; kind: string }

export interface ClaimResult {
  claim_id: string;
  parse_id: string;
  project_id: string | null;
  objects: ClaimedObject[];
  unmapped: { block_name: string; reason?: string }[];
  created_at: string;
}

export interface BaselineBlockDiff {
  matched: string[];
  changed: string[];
  added_in_upload: string[];
  missing_from_upload: string[];
}

/** verdict 三色：OK_TO_PROCEED 绿 / FROZEN_DRIFT 红 / 其它（含 UNVERIFIED_ONLINE）黄 */
export type VerdictTone = "ok" | "warn" | "err";

export interface BaselineCheckResult {
  project_id: string;
  verdict: string;
  note: string;
  compare: Record<string, unknown> | null;
  block_diff: BaselineBlockDiff | null;
}

export function verdictTone(verdict: string): VerdictTone {
  if (verdict === "OK_TO_PROCEED") return "ok";
  if (verdict === "FROZEN_DRIFT") return "err";
  return "warn";
}

export function verdictLabel(verdict: string): string {
  if (verdict === "OK_TO_PROCEED") return "比对通过 · 可开工";
  if (verdict === "FROZEN_DRIFT") return "现场漂移 · 冻结变更";
  if (verdict === "UNVERIFIED_ONLINE") return "现场状态未知（UNVERIFIED_ONLINE）";
  return verdict || "UNKNOWN";
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${IMPORT_BASE}${path}`, {
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

export const importerApi = {
  /** 真解析：TIA「块导出」XML 文本提交后端，按块保真度分级返回结构树。 */
  parse: (body: { project_name: string; blocks: { name: string; xml_text: string; language?: string }[] }) =>
    req<ParseResult>("POST", "/parse", body),
  /** 认领映射：把解析出的块指派为 工位/组件/执行器(CM)/EM/OB 并落 ObjectRegistry。 */
  claim: (body: { parse_id: string; project_id?: string; mappings: ClaimMapping[] }) =>
    req<ClaimResult>("POST", "/claim", body),
  /** 开工前比对（PLAN §4）：无任何基线→UNVERIFIED_ONLINE；有 B2→compare 透传。 */
  baselineCheck: (body: { project_id: string; block_hashes?: { block_name: string; sha256: string }[] }) =>
    req<BaselineCheckResult>("POST", "/baseline-check", body),
  getParse: (parseId: string) => req<ParseResult>("GET", `/parses/${parseId}`),
};

/* ---------- upload helpers (browser File API; node 20+ covers tests) ---------- */

export interface ReadBlocks {
  projectName: string;
  blocks: { name: string; xml_text: string }[];
}

/** Read uploaded block .xml files (+ optional manifest.json for the project name). */
export async function readBlockFiles(files: File[]): Promise<ReadBlocks> {
  let projectName = "";
  const blocks: { name: string; xml_text: string }[] = [];
  for (const f of files) {
    const text = await f.text();
    if (f.name.toLowerCase() === "manifest.json") {
      try {
        const m = JSON.parse(text) as Record<string, unknown>;
        projectName = String(m.projectName || m.project_name || "");
      } catch { /* 非法 manifest：忽略，不阻断上传 */ }
      continue;
    }
    if (!f.name.toLowerCase().endsWith(".xml")) continue;
    blocks.push({ name: f.name.replace(/\.xml$/i, ""), xml_text: text });
  }
  return { projectName, blocks };
}

/** SHA-256 hex of a file's text — real hashes only, never fabricated (§12). */
export async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, "0")).join("");
}
