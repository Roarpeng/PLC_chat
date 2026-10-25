export type NodeStatus = "synced" | "draft" | "error";

export interface CanvasVariableData {
  name: string;
  data_type: string;
  section: string;
  comment?: string;
  initial_value?: string;
}

export interface CanvasNetworkData {
  id: number;
  title: string;
  language: string;
  scl_text: string;
  status: NodeStatus;
  errors?: string[];
}

export interface CanvasBlockData {
  name: string;
  block_type: "FB" | "FC" | "DB" | "OB" | "UDT";
  number: number;
  language: string;
  comment?: string;
  interface: CanvasVariableData[];
  networks: CanvasNetworkData[];
  scl_body?: string;
  status: NodeStatus;
  errors?: string[];
}

export type HmiWidgetType =
  | "button"
  | "indicator"
  | "io_field"
  | "text"
  | "bar"
  | "gauge"
  | "slider"
  | "rect"
  | "alarm_banner"
  | "placeholder";

export interface CanvasHmiWidgetData {
  id: string;
  widget_type: HmiWidgetType | string;
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
  plc_tag: string;
  hmi_tag?: string;
  data_type: string;
  current_value: any;
  properties?: Record<string, any>;
  device?: string;
  screen?: string;
  source_name?: string;
  source_type?: string;
  text?: string;
  supported?: boolean;
  status: NodeStatus;
  errors?: string[];
}

export interface CanvasHmiScreenData {
  name: string;
  start_screen?: boolean;
  width?: number;
  height?: number;
}

export interface CanvasHmiDeviceData {
  name: string;
  kind: "classic" | "unified" | string;
  width: number;
  height: number;
  screens: CanvasHmiScreenData[];
}

export interface CanvasTagData {
  name: string;
  data_type: string;
  logical_address: string;
  comment?: string;
}

export interface CanvasSourceData {
  project_id: string;
  project_path: string;
  plc_name?: string;
  hmi_device_names?: string[];
  export_mode?: string;
  /** PCEC 工程基线指纹（sha256:…，网关 confirm-writeback / changes 端点写入；缺失时 UI 显示 —） */
  project_hash?: string;
}

export interface CanvasRevisionData {
  id: number;
  source: string;
  ops: Record<string, any>[];
  message?: string;
  ts?: number;
}

export interface CanvasStateData {
  project_name: string;
  blocks: Record<string, CanvasBlockData>;
  hmi_widgets: Record<string, CanvasHmiWidgetData>;
  hmi_devices?: CanvasHmiDeviceData[];
  tags: Record<string, CanvasTagData>;
  source?: CanvasSourceData | null;
  revisions?: CanvasRevisionData[];
  last_compile_result?: Record<string, any> | null;
}

export interface CompilerAttribution {
  target_type: "block" | "hmi_widget" | "network";
  target_id: string;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface CompileJobStage {
  name: string;
  status: "pending" | "running" | "ok" | "error" | "skipped";
  message?: string;
  started_at?: number;
  finished_at?: number;
  log?: string[];
}

export interface CompileJobData {
  id: string;
  status: "queued" | "running" | "ok" | "error" | "cancelled";
  stages: CompileJobStage[];
  attributions?: CompilerAttribution[];
  result?: Record<string, any> | null;
  canvas?: CanvasStateData | null;
  error?: string | null;
  created_at?: number;
  updated_at?: number;
}
