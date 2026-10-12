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

export interface CanvasHmiWidgetData {
  id: string;
  widget_type: "button" | "indicator" | "io_field" | "slider" | "gauge" | "alarm_banner";
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
  plc_tag: string;
  data_type: string;
  current_value: any;
  properties?: Record<string, any>;
  status: NodeStatus;
  errors?: string[];
}

export interface CanvasTagData {
  name: string;
  data_type: string;
  logical_address: string;
  comment?: string;
}

export interface CanvasStateData {
  project_name: string;
  blocks: Record<string, CanvasBlockData>;
  hmi_widgets: Record<string, CanvasHmiWidgetData>;
  tags: Record<string, CanvasTagData>;
  last_compile_result?: Record<string, any> | null;
}

export interface CompilerAttribution {
  target_type: "block" | "hmi_widget" | "network";
  target_id: string;
  severity: "error" | "warning" | "info";
  message: string;
}
