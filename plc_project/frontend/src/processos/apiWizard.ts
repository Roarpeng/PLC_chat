/* Wizard-only API module (§b step orchestration): POSTs the explicit spec to
   /projects/from-spec. Deliberately separate from api.ts (owned by another
   stream): the binding style, the {error} body contract (-> ApiError) and
   actorHeaders() are shared, the endpoint binding is not. */
import { ApiError } from "./api";
import { actorHeaders } from "./actor";
import type { Contract, CpuEntry, DeviceCatalog, FieldDevice } from "./types";

export const WIZARD_BASE = "/api/processos";

/* Spec shape — LOCKED, mirrors processos/spec_builder.py:build_contract_from_spec. */
export interface SpecGuard { signal: string; op: "=="; value: boolean }
export interface SpecStep {
  id: string; name: string;
  guard?: SpecGuard;
  actions: { command: string }[];
  timeout_ms?: number;
  failure_target?: string;
  next?: string;
}
export interface SpecOperation { em: string; name?: string; resource_ids: string[]; steps: SpecStep[] }
export interface SpecInvariant { id: string; expr: string; scope: string; severity: "error" | "warning" }
export interface ProjectSpec {
  id?: string; name: string; profile_id?: string;
  cpu?: CpuEntry; device_name?: string;
  network?: { ip: string; subnet: string; device_name: string };
  devices: { type: string; name: string; id: string; params: Record<string, number> }[];
  operations: SpecOperation[];
  invariants?: SpecInvariant[];
}

export interface FromSpecResult { project_id: string; revision: number; profile_id: string; contract: Contract }

export async function createProjectFromSpec(spec: ProjectSpec): Promise<FromSpecResult> {
  const res = await fetch(`${WIZARD_BASE}/projects/from-spec`, {
    method: "POST",
    headers: { ...actorHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(spec),
  });
  const text = await res.text();
  let data: Record<string, unknown> = {};
  if (text) { try { data = JSON.parse(text) as Record<string, unknown>; } catch { data = {}; } }
  if (!res.ok)
    throw new ApiError(res.status, String(data.error || data.detail || res.statusText));
  return data as unknown as FromSpecResult;
}

/* Client-side pre-flight — same rules the backend enforces (fail-closed).
   Returns human-readable problems; empty list means the spec may be submitted. */
export function validateSpec(spec: ProjectSpec, catalog: DeviceCatalog | null): string[] {
  const problems: string[] = [];
  if (!catalog) return ["设备目录未加载"];
  if (!spec.devices.length) problems.push("至少需要 1 台现场设备");
  const byId = new Map(spec.devices.map(d => [d.id, d]));
  for (const d of spec.devices) {
    if (!catalog.device_types[d.type]) problems.push(`设备 ${d.name || d.id}：未知类型 ${d.type}`);
  }
  if (!spec.operations.length) problems.push("至少需要 1 个操作 (EM)");
  const opIds = new Set<string>();
  for (const op of spec.operations) {
    const opId = `OP_${op.em}`;
    if (!op.em) problems.push("存在未命名的操作（em 不能为空）");
    if (opIds.has(opId)) problems.push(`操作 ${op.em} 重复`);
    opIds.add(opId);
    if (!op.resource_ids.length) problems.push(`${opId}：至少关联一个资源`);
    for (const rid of op.resource_ids)
      if (!byId.has(rid)) problems.push(`${opId}：资源 ${rid} 不存在（设备可能已删除）`);
    if (!op.steps.length) problems.push(`${opId}：至少需要 1 个步骤`);
    const sids = new Set(op.steps.map(s => s.id));
    for (const s of op.steps) {
      const where = `${opId}.${s.id}`;
      for (const a of s.actions) {
        const owners = op.resource_ids.filter(rid => (catalog.device_types[byId.get(rid)?.type ?? ""]?.commands ?? []).includes(a.command));
        if (!owners.length) problems.push(`${where}：命令 ${a.command} 不属于该操作的任何资源`);
        else if (owners.length > 1) problems.push(`${where}：命令 ${a.command} 在多个资源间有歧义`);
      }
      if (s.timeout_ms !== undefined && s.timeout_ms <= 0) problems.push(`${where}：超时必须大于 0`);
      if (s.next && !sids.has(s.next)) problems.push(`${where}：下一步 ${s.next} 不存在（步骤可能已删除）`);
      if (s.failure_target && !sids.has(s.failure_target)) problems.push(`${where}：故障出口 ${s.failure_target} 不存在`);
      if (s.guard && (!s.guard.signal || s.guard.op !== "==" || typeof s.guard.value !== "boolean"))
        problems.push(`${where}：guard 形状不合法`);
    }
  }
  return problems;
}

/* IO/symbol preview rows derived from the type contracts (honest: rows we
   cannot derive render as UNKNOWN, never guessed). */
export interface SignalRow {
  deviceId: string; deviceName: string; signal: string;
  dir: "I" | "Q"; kind: "反馈" | "命令" | "UNKNOWN";
  symbol: string;
}

export function signalTable(devices: FieldDevice[], catalog: DeviceCatalog | null): SignalRow[] {
  const rows: SignalRow[] = [];
  for (const d of devices) {
    const spec = catalog?.device_types[d.type];
    if (!spec) {
      rows.push({ deviceId: d.id, deviceName: d.name, signal: "UNKNOWN", dir: "I", kind: "UNKNOWN", symbol: "UNKNOWN" });
      continue;
    }
    for (const fb of spec.feedback)
      rows.push({ deviceId: d.id, deviceName: d.name, signal: fb, dir: "I", kind: "反馈", symbol: `${d.id}.${fb}Fb` });
    for (const cmd of spec.commands)
      rows.push({ deviceId: d.id, deviceName: d.name, signal: cmd, dir: "Q", kind: "命令", symbol: `${d.id}.${cmd}Cmd` });
  }
  return rows;
}
