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
