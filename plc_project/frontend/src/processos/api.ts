import { actorHeaders } from "./actor";
import type {
  Baseline, BaselineCompare, BaselineGate, Changeset, ComplianceReport, Contract, DeliveryGate, DeliveryJob,
  DeploymentRecord, DeviceCatalog, FieldmodReport, FrameworkProfile, GatewayExecuteResult, GatewayPrecheck,
  HardwareConfig, HandoverContext, ImpactReport, Incident, ObjectContext, ObjectRef, ProjectSummary,
  RbacAuditEntry, RbacRoleMatrix, ScenarioResult, SourceMapRef, TelemetryEvent, TraceGraphs,
} from "./types";

export const PROCESSOS_BASE = "/api/processos";

export class ApiError extends Error {
  status: number;
  /** machine error code from the backend body, e.g. SAFETY_SCOPE_BLOCKED / ROLE_FORBIDDEN */
  code?: string;
  /** role required for ROLE_FORBIDDEN responses */
  requiredRole?: string;
  constructor(status: number, message: string, code?: string, requiredRole?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.requiredRole = requiredRole;
  }
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
      Array.isArray(data.required) ? data.required.join(" / ")
        : data.required_role !== undefined ? String(data.required_role)
        : data.role_required !== undefined ? String(data.role_required) : undefined,
    );
  return data as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const processosApi = {
  frameworks: () => req<{ profiles: FrameworkProfile[] }>("GET", "/frameworks"),
  demo: () => req<{ project_id: string; revision: number; profile_id: string; contract: Contract }>("POST", "/demo"),
  deviceCatalog: () => req<DeviceCatalog>("GET", "/device-catalog"),
  projects: () => req<{ projects: ProjectSummary[] }>("GET", "/projects"),
  fromHardware: (config: HardwareConfig) =>
    req<{ project_id: string; revision: number; profile_id: string; contract: Contract }>("POST", "/projects/from-hardware", config),
  incidents: () => req<{ incidents: Incident[] }>("GET", "/incidents"),
  /* four-graph object registry dump (FC-00); objects only, no relation rows */
  traceGraphs: () => req<TraceGraphs>("GET", "/trace/graphs"),
  incident: (id: string) => req<Incident>("GET", `/incidents/${id}`),
  handover: (id: string) => req<HandoverContext>("GET", `/incidents/${id}/handover`),
  objectContext: (id: string, buildId?: string) =>
    req<ObjectContext>("GET", `/objects/${id}/context${buildId ? `?build_id=${buildId}` : ""}`),
  findObject: (name: string) => req<ObjectRef>("GET", `/objects?name=${encodeURIComponent(name)}`),
  triage: (id: string, body: { fact?: string; hypotheses?: string[]; root_cause?: string; root_cause_verified?: boolean }) =>
    req<Incident>("POST", `/incidents/${id}/triage`, body),
  createProject: (contract: Contract, profileId?: string) =>
    req<{ project_id: string; revision: number; profile_id: string }>("POST", "/projects", {
      contract, profile_id: profileId ?? "",
    }),
  getProject: (pid: string) =>
    req<{ contract: Contract; revision: number; profile_id: string; spec_hash: string }>("GET", `/projects/${pid}`),
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

  /* ===== FC-03 baselines / drift gate ===== */
  listBaselines: (pid: string) => req<{ baselines: Baseline[] }>("GET", `/projects/${pid}/baselines`),
  recordB1: (pid: string, body: { spec_hash: string; revision: number; profile_id?: string }) =>
    req<Baseline>("POST", `/projects/${pid}/baselines/b1`, body),
  recordB2: (pid: string, body: { build_id: string; archive_sha256: string; block_manifest?: Record<string, string> }) =>
    req<Baseline>("POST", `/projects/${pid}/baselines/b2`, body),
  recordB3: (pid: string, body: {
    deployed_build_id: string; verification: "FIELD_VERIFIED" | "SELF_REPORTED";
    plc_checksum?: string | null; device_id?: string | null;
    operator?: string | null; commissioned_at?: string | null;
  }) => req<Baseline>("POST", `/projects/${pid}/baselines/b3`, body),
  compareBaselines: (pid: string) => req<BaselineCompare>("POST", `/projects/${pid}/baselines/compare`),
  /** 409 {error, code, details} when the gate blocks (UNKNOWN_PLC_STATE / DRIFT_DETECTED). */
  gateChange: (pid: string) => req<BaselineGate>("POST", `/projects/${pid}/baselines/gate`),
  projectSourcemap: (pid: string) =>
    req<{ project_id: string; builds: string[]; source_map: SourceMapRef[] }>("GET", `/projects/${pid}/sourcemap`),

  /* ===== FC-05 impact ===== */
  buildImpact: (pid: string, body: { object_id?: string; patch_ops?: unknown[]; reason?: string }) =>
    req<ImpactReport>("POST", `/projects/${pid}/impact`, body),
  getImpact: (reportId: string) => req<ImpactReport>("GET", `/impact/${reportId}`),

  /* ===== FC-14 / FC-18 deployments ===== */
  listDeploymentRecords: (pid?: string) =>
    req<{ records: DeploymentRecord[] }>("GET", `/deployments/records${qs({ project_id: pid })}`),
  createDeploymentRecord: (body: {
    project_id: string; build_id: string; artifact_sha256: string; device_id: string;
    operator: string; plc_checksum?: string; commissioned_at?: string;
    tests?: { name: string; passed: boolean; note?: string }[];
    result?: "COMMISSIONED" | "FAILED" | "ROLLED_BACK";
  }) => req<DeploymentRecord>("POST", "/deployments/records", body),
  gatewayPrecheck: (body: {
    project_id: string; build_id: string; device_id: string;
    window?: string;
    online_compare?: Record<string, unknown> | null;
    retain_assessment?: Record<string, unknown> | null;
    second_person?: string;
    rollback_plan?: Record<string, unknown> | null;
    authorized_window?: boolean;
  }) => req<GatewayPrecheck>("POST", "/deployments/gateway/precheck", body),
  gatewayExecute: (body: { precheck_id: string; confirm: true; actor: string }) =>
    req<GatewayExecuteResult>("POST", "/deployments/gateway/execute", body),

  /* ===== FC-15 telemetry ===== */
  ingestEvent: (body: {
    object_id: string; source: "MANUAL_UPLOAD" | "OT_CHANNEL" | "SIMULATED"; event_time: string;
    payload?: Record<string, unknown>; quality?: string;
  }) => req<TelemetryEvent>("POST", "/telemetry/events", body),
  objectTelemetry: (objectId: string) =>
    req<{ object_id: string; events: TelemetryEvent[] }>("GET", `/objects/${encodeURIComponent(objectId)}/telemetry`),

  /* ===== FC-17 field modifications ===== */
  reportFieldModification: (pid: string, body: {
    field_state: { blocks: { block_name: string; content_sha256: string }[] };
    captured_at?: string; source?: string; b2_manifest?: Record<string, unknown>;
  }) => req<FieldmodReport>("POST", `/projects/${pid}/field-modifications`, body),

  /* ===== RBAC ===== */
  rbacRoles: () => req<RbacRoleMatrix>("GET", "/rbac/roles"),
  rbacAudit: (params: Record<string, string | number | undefined> = {}) =>
    req<{ entries: RbacAuditEntry[] }>("GET", `/rbac/audit${qs(params)}`),
};
