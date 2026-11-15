export interface Action { target: string; command: string; value: unknown }
export interface Step {
  id: string; name: string; entry: Action[]; cyclic: Action[]; exit: Action[];
  guard: string; duration_ms: number; timeout_ms: number; next: string;
  failure_target: string; is_fault: boolean; reset_guard: string;
}
export interface Resource {
  id: string; name: string; kind: string; commands: string[]; feedback: string[];
  status: string[]; exclusive: boolean; io_bindings: Record<string, string>;
}
export interface Operation {
  id: string; name: string; unit: string; em: string; resource_ids: string[];
  preconditions: string[]; steps: Step[]; acceptance: string[];
}
export interface OpenQuestion {
  id: string; question: string; affects: string[]; severity: string;
  resolution: string | null; resolved_by: string | null;
}
export interface Scenario { id: string; name: string; kind: string; description: string }
export interface Contract {
  id: string; name: string; target_framework: string; unit: string; schema: string;
  resources: Resource[]; operations: Operation[]; open_questions: OpenQuestion[];
  scenarios: Scenario[];
}
export interface Issue { code: string; message: string; node: string; severity: string }
export interface ComplianceReport {
  errors: Issue[]; warnings: Issue[]; checks: { code: string; level: string; msg: string; node: string }[];
  coverage: Record<string, number>; evidence_level: string; profile_id: string; ir_hash: string;
}
export interface TraceEvent { t_ms: number; step: string; event: string; fault: boolean }
export interface Counterexample { property_id: string; cycle: number; description: string; trace: TraceEvent[] }
export interface ScenarioResult {
  scenario_id: string; passed: boolean; reached: string[]; fault_reason: string;
  properties: Record<string, string>; counterexamples: Counterexample[]; evidence_level: string;
}
export interface Changeset { id: string; spec_hash: string; profile_id: string; rev: number }
export interface DeliveryJob {
  id: string; status: string; chain_state?: string; evidence_level?: string;
  ob_main_included?: boolean; events: { stage: string; ok: boolean; state: string; message?: string }[];
  diagnostics: { stage: string; code: string; message: string }[];
  artifact?: { archive_sha256: string; archive_path: string } | null;
}
export interface DeliveryGate { ready: boolean; checks: Record<string, boolean>; spec_hash: string; note: string }
export interface FrameworkProfile {
  profile_id: string; framework: string; tia_version: string; template_sha256: string; verified: boolean;
}

export interface DeviceParam { key: string; label: string; default: number; unit: string }
export interface DeviceType {
  label: string; commands: string[]; feedback: string[];
  params: DeviceParam[]; io: { DI: number; DQ: number; AI: number; AQ: number };
  conflict: string[] | null; bus?: string;
}
export interface CpuEntry { series: string; order_no: string; firmware: string; label: string }
export interface IoModule { type: string; points: number; order_no: string; label: string }
export interface DeviceCatalog { device_types: Record<string, DeviceType>; cpus: CpuEntry[]; io_modules: IoModule[] }

export interface FieldDevice { type: string; name: string; id: string; params: Record<string, number>; em?: string }
export interface HardwareConfig {
  id?: string; name: string; unit?: string;
  cpu: CpuEntry | null; device_name?: string;
  io_modules: (IoModule & { slot: number })[];
  expansion: { name: string; modules: IoModule[] }[];
  devices: FieldDevice[];
  network: { ip: string; subnet: string; device_name: string };
}

export interface ObjectRef { object_id: string; kind: string; graph: string; display_name: string; aliases: string[]; status: string }
/* GET /trace/graphs rows — object registry members of the four graphs (no
   relationship rows: memberships are resolved via object contexts / shared
   attribute keys, never guessed). */
export interface TraceObject {
  object_id: string; kind: string; graph: string; display_name: string;
  aliases: string[]; attributes: Record<string, unknown>; status: string;
  created_at: number; history: unknown[];
}
export interface TraceGraphs {
  PhysicalGraph: TraceObject[]; AfGraph: TraceObject[];
  BehaviorGraph: TraceObject[]; EvidenceGraph: TraceObject[];
}
export interface SourceMapRef {
  source_map_id: string; semantic_object_id: string; behavior_step_id: string; release_build_id: string;
  block_name: string; block_kind: string; instance_db: string; scl_line_range: [number, number] | null; ownership: string;
}
export interface ObjectContext {
  object_id: string; found: boolean; kind: string; graph: string; display_name: string; aliases: string[];
  status: string; physical_path: string; af: Record<string, string>;
  behavior: { object_id: string; display_name: string; attributes: Record<string, unknown> }[];
  source_map: SourceMapRef[]; alarm_definitions: { definition_id: string; code: string; description: string }[];
  history: unknown[]; build_id: string;
}
export interface Incident {
  incident_id: string; object_id: string; asset_id: string; physical_path_at_event: string;
  af_refs: Record<string, string>; alarm: Record<string, unknown>; behavior: Record<string, unknown>;
  software: Record<string, unknown>; references: Record<string, unknown>;
  triage: { fact: string; hypotheses: string[]; root_cause: string | null; root_cause_verified?: boolean };
  handover: { owner: string; status: string; next_action: string };
}
export interface HandoverContext {
  incident: Incident; resolved_at_build: string; object_context: ObjectContext;
  recent_changes: unknown[]; triage_note: string; handover: { owner: string; status: string; next_action: string };
}

/* ===== field change / handover (PLAN §3–§8) — shapes locked to the backend ===== */
export interface ProjectSummary { project_id: string; name: string; revision: number; profile_id: string; steps: number }
export type BaselineKind = "B1" | "B2" | "B3";
export type BaselineStatus = "FROZEN" | "VERIFIED" | "UNVERIFIED_ONLINE";
export interface Baseline {
  baseline_id: string; kind: BaselineKind; project_id: string; status: BaselineStatus;
  created_at: string; seq: number;
  /* B1 */ spec_hash?: string; revision?: number; profile_id?: string;
  /* B2 */ build_id?: string; archive_sha256?: string; block_manifest?: Record<string, string>;
  /* B3 */ deployed_build_id?: string; verification?: string; plc_checksum?: string | null;
  device_id?: string | null; operator?: string | null; commissioned_at?: string | null;
}
export interface BaselineDifference { kind: string; detail: string }
export interface BaselineCompare {
  project_id: string;
  verdict: "OK_TO_PROCEED" | "FROZEN_DRIFT" | "UNVERIFIED_ONLINE";
  b2_vs_b3: string;
  differences: BaselineDifference[];
  latest_b1: Baseline | null; latest_b2: Baseline | null; latest_b3: Baseline | null;
}
/** gate_change: {ok, verdict, compare} on success; 409 {error, code, details} when blocked. */
export interface BaselineGate { ok: boolean; verdict: string; compare?: BaselineCompare }
export interface ImpactReport {
  report_id: string; project_id: string; generated_at: string;
  subject: { object_id: string; display_name: string; reason: string };
  affected: {
    units: { object_id: string; display_name: string; kind: string }[];
    ems: { object_id: string; display_name: string; kind: string }[];
    cms: { object_id: string; display_name: string; kind: string }[];
    steps: { object_id: string; display_name: string; kind: string }[];
  };
  callers: { object_id: string; display_name: string; relation: string }[];
  alarm_definitions: { definition_id: string; code: string; description: string }[];
  io_db_interfaces: string[];
  hmi_messages: string[];
  state_retention_risk: string;
  online_load_impact: string;
  regression_tests: { name: string; status: string }[];
  deployment_notes: string[];
  unknown_fields: string[];
  blocked_high_risk_delivery: boolean;
}
export interface DeploymentTestRow { name: string; passed: boolean; note?: string }
export type CommissioningResult = "COMMISSIONED" | "FAILED" | "ROLLED_BACK";
export interface DeploymentRecord {
  record_id: string; project_id: string; build_id: string; artifact_sha256: string;
  device_id: string; operator: string; plc_checksum: string; commissioned_at: string;
  tests: DeploymentTestRow[]; result: CommissioningResult; created_at?: string;
}
export interface GatewayPrecheck {
  precheck_id: string; project_id: string; build_id: string; device_id: string;
  window: string; authorized_window: boolean;
  satisfied: string[]; missing: string[]; blocked_by: string[];
  ready: boolean; one_click_online: boolean; note: string; created_at: string;
}
export interface GatewayExecuteResult {
  precheck_id: string; actor: string; backend: string;
  result: Record<string, unknown>; one_click_online: boolean;
  note: string; executed_at: string;
}
export interface TelemetryEvent {
  event_id: string; object_id: string; source: string; event_time: string;
  payload: Record<string, unknown>; quality: string; evidence_level: string;
  ingested_at: string;
}
export interface FieldmodChangedBlock {
  block_name: string; b2_sha256: string | null; field_sha256: string | null; reason: string;
}
export interface FieldmodOverride {
  override_id: string; project_id: string; block_name: string;
  ownership: string; protected_by: string; note: string; created_at: string;
}
export interface FieldmodReport {
  project_id: string; captured_at: string; source: string;
  b2_vs_b3: string; drift_detected: boolean | null;
  changed_blocks: FieldmodChangedBlock[];
  three_way: { native_changed: string[]; field_changed: string[]; design_changed: string[]; unknown: string[] };
  unmapped_native_code: string[];
  managed_native_overrides: FieldmodOverride[];
  frozen: boolean; error_code: string | null; note: string;
}
export interface RbacRoleMatrix {
  roles: string[];
  permissions: Record<string, string[]>;
}
export interface RbacAuditEntry {
  ts: string; seq: number; actor_id: string; role: string;
  action: string; target: string; result: string; extra?: Record<string, unknown>;
}
