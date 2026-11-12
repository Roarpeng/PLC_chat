/**
 * DeviceCanvas — component/typed-port projection of the server IR (WP-04).
 *
 * Pure CSS/HTML custom nodes (zero new UI dependency). Physical IO is ALWAYS
 * shown as `unbound` — no `%I`/`%Q` address is ever invented client-side.
 */
import React from "react";

interface PortView { name?: string; data_type?: string; role?: string; binding?: string | null; writer?: string }
interface ComponentView {
  id?: string; name?: string; component_type?: string; driver_template?: string;
  driver_spec_id?: string;
  io_bindings?: Record<string, unknown> | null; parameters?: Record<string, unknown>;
}
interface SpecView { typed_ports?: Record<string, PortView>; compile_mode?: string; move_timeout_ms?: number }

export interface DeviceCanvasProps {
  ir: Record<string, unknown>;
  onSelectNode: (nodeId: string, data: Record<string, unknown>) => void;
  selectedNodeId: string | null;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export const DeviceCanvas: React.FC<DeviceCanvasProps> = ({ ir, onSelectNode, selectedNodeId }) => {
  const components = Array.isArray(ir.components) ? (ir.components as ComponentView[]) : [];
  const specs = asRecord(ir.driver_specs);
  return (
    <div className="wb-device" data-ui="device-canvas">
      <div className="wb-canvas__head">
        <b>DEVICE LIBRARY / 元器件驱动</b>
        <span className="wb-canvas__notice">typed ports · io_bindings = unbound（禁止编造 %I/%Q）</span>
      </div>
      <div className="wb-device__grid">
        {components.length === 0 && <div className="wb-canvas__empty">服务端 IR 暂无组件；请从步序画布或 Copilot 生成候选 Patch。</div>}
        {components.map((component) => {
          const id = String(component.id ?? "?");
          const spec = asRecord(specs[String(component.driver_spec_id ?? "")]) as SpecView;
          const ports = Object.values(spec.typed_ports ?? {});
          return (
            <button
              type="button"
              key={id}
              className={`wb-device__node ${selectedNodeId === id ? "is-selected" : ""}`}
              onClick={() => onSelectNode(id, asRecord(component))}
              data-ui={`device-node-${id}`}
            >
              <div className="wb-device__node-head">
                <span className="wb-mono">{id}</span>
                <span className="wb-device__tag">{component.component_type ?? "custom_pending"}</span>
              </div>
              <div className="wb-device__name">{component.name ?? id}</div>
              <div className="wb-device__ports">
                {ports.slice(0, 8).map((port) => (
                  <span key={String(port.name)} className={`wb-port wb-port--${String(port.role ?? "").toLowerCase()}`}>
                    {port.name} <i>{port.data_type ?? "?"}</i>
                  </span>
                ))}
              </div>
              <div className="wb-device__foot">
                <span>mode: {spec.compile_mode ?? "—"}</span>
                <span>timeout: {spec.move_timeout_ms ?? "—"} ms</span>
                <span className="wb-device__unbound">io_bindings: unbound</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
