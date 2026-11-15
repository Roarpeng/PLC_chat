import type {
  Changeset, ComplianceReport, Contract, DeliveryGate, DeliveryJob, DeviceCatalog, FrameworkProfile, HardwareConfig, ScenarioResult,
} from "./types";

export const PROCESSOS_BASE = "/api/processos";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${PROCESSOS_BASE}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new ApiError(res.status, data.error || res.statusText);
  return data as T;
}

export const processosApi = {
  frameworks: () => req<{ profiles: FrameworkProfile[] }>("GET", "/frameworks"),
  demo: () => req<{ project_id: string; revision: number; profile_id: string; contract: Contract }>("POST", "/demo"),
  deviceCatalog: () => req<DeviceCatalog>("GET", "/device-catalog"),
  fromHardware: (config: HardwareConfig) =>
    req<{ project_id: string; revision: number; profile_id: string; contract: Contract }>("POST", "/projects/from-hardware", config),
  createProject: (contract: Contract, profileId?: string) =>
    req<{ project_id: string; revision: number; profile_id: string }>("POST", "/projects", {
      contract, profile_id: profileId ?? "",
    }),
  getProject: (pid: string) =>
    req<{ contract: Contract; revision: number; profile_id: string }>("GET", `/projects/${pid}`),
  patch: (pid: string, baseRevision: number, ops: unknown[], requestId = "") =>
    req<{ revision: number; contract: Contract }>("POST", `/projects/${pid}/patches`, {
      base_revision: baseRevision, request_id: requestId, ops,
    }),
  validate: (pid: string) => req<ComplianceReport>("POST", `/projects/${pid}/validate`),
  simulate: (pid: string) =>
    req<{ results: ScenarioResult[]; all_passed: boolean }>("POST", `/projects/${pid}/simulate`),
  generate: (pid: string) =>
    req<{ files: Record<string, string>; coverage_assertions_passed: boolean; manifest_hash: string }>(
      "POST", `/projects/${pid}/generate`),
  resolveQuestion: (pid: string, qid: string, resolution: string, by: string) =>
    req("POST", `/projects/${pid}/questions/${qid}/resolve`, { resolution, by }),
  freezeChangeset: (pid: string) => req<Changeset>("POST", `/projects/${pid}/changesets`),
  approve: (pid: string, csid: string, by: string) =>
    req("POST", `/projects/${pid}/changesets/${csid}/approve`, { by }),
  deliveryGate: (pid: string) => req<DeliveryGate>("GET", `/projects/${pid}/delivery-gate`),
  createDelivery: (pid: string) => req<DeliveryJob>("POST", `/projects/${pid}/deliveries`),
  passport: (pid: string) =>
    req<{ revision_hash: string; entries: unknown[] }>("GET", `/projects/${pid}/passport`),
};
