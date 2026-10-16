import React, { useEffect, useMemo, useRef, useState } from "react";
import type { CanvasHmiDeviceData, CanvasHmiWidgetData } from "../canvas/types";

export interface HmiPaneProps {
  widgets: CanvasHmiWidgetData[];
  devices?: CanvasHmiDeviceData[];
  focusWidgetId: string | null;
  onWidgetClick(w: CanvasHmiWidgetData): void;
}

/** HMI 仿真：多设备/多画面、真实分辨率、核心控件 + placeholder。 */
export const HmiPane: React.FC<HmiPaneProps> = ({
  widgets,
  devices = [],
  focusWidgetId,
  onWidgetClick,
}) => {
  const zoneRef = useRef<HTMLDivElement>(null);
  const encRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState<{ k: number; w: number; h: number } | null>(null);

  const deviceNames = useMemo(() => {
    if (devices.length) return devices.map((d) => d.name);
    const set = new Set(widgets.map((w) => w.device || "HMI").filter(Boolean));
    return set.size ? Array.from(set) : ["HMI"];
  }, [devices, widgets]);

  const [deviceName, setDeviceName] = useState(deviceNames[0] || "HMI");
  useEffect(() => {
    if (!deviceNames.includes(deviceName)) setDeviceName(deviceNames[0] || "HMI");
  }, [deviceNames, deviceName]);

  const device = devices.find((d) => d.name === deviceName);
  const screens = useMemo(() => {
    if (device?.screens?.length) return device.screens.map((s) => s.name);
    const set = new Set(
      widgets.filter((w) => (w.device || "HMI") === deviceName).map((w) => w.screen || "Screen_1")
    );
    return set.size ? Array.from(set) : ["Screen_1"];
  }, [device, widgets, deviceName]);

  const [screenName, setScreenName] = useState(screens[0] || "Screen_1");
  useEffect(() => {
    if (!screens.includes(screenName)) setScreenName(screens[0] || "Screen_1");
  }, [screens, screenName]);

  const screenW = device?.width || device?.screens?.find((s) => s.name === screenName)?.width || 800;
  const screenH = device?.height || device?.screens?.find((s) => s.name === screenName)?.height || 480;

  const visible = widgets.filter(
    (w) =>
      (w.device || deviceName) === deviceName &&
      (w.screen || screenName) === screenName
  );

  useEffect(() => {
    const zone = zoneRef.current;
    const enc = encRef.current;
    if (!zone || !enc) return;
    const W = screenW + 40;
    const H = screenH + 90;
    const update = () => {
      const k = Math.max(0.2, Math.min(1, (zone.clientWidth - 20) / W, (zone.clientHeight - 20) / H));
      const next = { k, w: Math.round(W * k), h: Math.round(H * k) };
      setScale((prev) => (prev && prev.k === next.k && prev.w === next.w && prev.h === next.h ? prev : next));
    };
    update();
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(update);
      ro.observe(zone);
      return () => ro.disconnect();
    }
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [screenW, screenH]);

  return (
    <div className="hmi-zone" ref={zoneRef}>
      <div className="hmi-toolbar" style={{ display: "flex", gap: 8, padding: "4px 8px", fontSize: 12 }}>
        <label>
          设备{" "}
          <select value={deviceName} onChange={(e) => setDeviceName(e.target.value)}>
            {deviceNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label>
          画面{" "}
          <select value={screenName} onChange={(e) => setScreenName(e.target.value)}>
            {screens.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <span style={{ opacity: 0.7 }}>
          {screenW}×{screenH}
          {device?.kind ? ` · ${device.kind}` : ""}
        </span>
      </div>
      <div className="hmi-scaleholder" style={scale ? { width: scale.w, height: scale.h } : undefined}>
        <div
          className="hmi-enclosure"
          ref={encRef}
          style={scale && scale.k < 1 ? { transform: `scale(${scale.k})`, transformOrigin: "top left" } : undefined}
        >
          <div className="hmi-frame">
            <div className="hmi-screen" style={{ width: screenW, height: screenH, position: "relative" }}>
              <div className="hmi-topbar">
                <span>
                  {deviceName} — {screenName}
                </span>
                <span className="hmi-topbar__link">
                  <i />
                  PLC LINK
                </span>
              </div>

              {visible.length === 0 && (
                <div className="hmi-empty">
                  <div className="hmi-empty__title">当前画面无控件</div>
                  <div className="hmi-empty__text">通过对话添加，或从工程导入 HMI</div>
                </div>
              )}

              {visible.map((widget) => {
                const isError = widget.status === "error";
                const isFocused = focusWidgetId === widget.id;
                const btnColor = widget.properties?.color || "green";
                const supported = widget.supported !== false;
                return (
                  <div
                    key={widget.id}
                    className={`hw ${isError ? "hw--error" : ""} ${isFocused ? "hw--focus" : ""} ${
                      !supported ? "hw--placeholder" : ""
                    }`}
                    data-widget-id={widget.id}
                    onClick={() => onWidgetClick(widget)}
                    style={{
                      left: `${widget.x}px`,
                      top: `${widget.y}px`,
                      width: `${widget.width}px`,
                      height: `${widget.height}px`,
                      position: "absolute",
                      border: !supported ? "1px dashed #888" : undefined,
                      boxSizing: "border-box",
                    }}
                  >
                    {widget.widget_type === "button" && (
                      <button
                        className={`hw-btn ${btnColor === "red" || btnColor === "rose" ? "hw-btn--red" : ""} ${
                          widget.current_value ? "is-on" : ""
                        }`}
                      >
                        {widget.text || widget.title}
                      </button>
                    )}

                    {widget.widget_type === "indicator" && (
                      <div className="hw-panel">
                        <i className={`hw-lamp ${widget.current_value ? "is-on" : ""}`} />
                        <span className="hw-panel__label">{widget.title}</span>
                      </div>
                    )}

                    {widget.widget_type === "gauge" && (
                      <div className="hw-gauge">
                        <span className="hw-gauge__label">{widget.title}</span>
                        <div className="hw-gauge__read">
                          <span className="hw-gauge__val">{widget.current_value ?? 0}</span>
                          <span className="hw-gauge__unit">{widget.properties?.unit || ""}</span>
                        </div>
                        <div className="hw-gauge__bar">
                          <i
                            style={{
                              width: `${Math.min(
                                100,
                                Math.round(
                                  ((Number(widget.current_value) || 0) /
                                    (Number(widget.properties?.max) || 1500)) *
                                    100
                                )
                              )}%`,
                            }}
                          />
                        </div>
                      </div>
                    )}

                    {widget.widget_type === "io_field" && (
                      <div className="hw-io" style={{ padding: 4, background: "#1a1a1a", color: "#0f0", fontFamily: "monospace" }}>
                        <div style={{ fontSize: 10, opacity: 0.7 }}>{widget.title}</div>
                        <div>{String(widget.current_value ?? "—")}</div>
                      </div>
                    )}

                    {widget.widget_type === "text" && (
                      <div className="hw-text" style={{ padding: 4, fontSize: 13 }}>
                        {widget.text || widget.title}
                      </div>
                    )}

                    {widget.widget_type === "bar" && (
                      <div className="hw-bar" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                        <span style={{ fontSize: 10 }}>{widget.title}</span>
                        <div style={{ flex: 1, background: "#222", position: "relative" }}>
                          <div
                            style={{
                              position: "absolute",
                              bottom: 0,
                              left: 0,
                              right: 0,
                              height: `${Math.min(100, Number(widget.current_value) || 0)}%`,
                              background: "#3b82f6",
                            }}
                          />
                        </div>
                      </div>
                    )}

                    {widget.widget_type === "slider" && (
                      <div className="hw-slider" style={{ padding: 4 }}>
                        <div style={{ fontSize: 10 }}>{widget.title}</div>
                        <input type="range" min={0} max={100} value={Number(widget.current_value) || 0} readOnly />
                      </div>
                    )}

                    {widget.widget_type === "rect" && (
                      <div
                        style={{
                          width: "100%",
                          height: "100%",
                          background: widget.properties?.color || "#334155",
                          opacity: 0.5,
                        }}
                      />
                    )}

                    {widget.widget_type === "alarm_banner" && (
                      <div
                        style={{
                          width: "100%",
                          height: "100%",
                          background: widget.current_value ? "#7f1d1d" : "#1e293b",
                          color: "#fecaca",
                          fontSize: 12,
                          padding: 6,
                          display: "flex",
                          alignItems: "center",
                        }}
                      >
                        {widget.text || widget.title || "报警视图"}
                      </div>
                    )}

                    {(widget.widget_type === "placeholder" || !supported) &&
                      widget.widget_type !== "button" &&
                      widget.widget_type !== "indicator" &&
                      widget.widget_type !== "gauge" &&
                      widget.widget_type !== "io_field" &&
                      widget.widget_type !== "text" &&
                      widget.widget_type !== "bar" &&
                      widget.widget_type !== "slider" &&
                      widget.widget_type !== "rect" &&
                      widget.widget_type !== "alarm_banner" && (
                        <div
                          style={{
                            width: "100%",
                            height: "100%",
                            border: "1px dashed #94a3b8",
                            color: "#94a3b8",
                            fontSize: 10,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            textAlign: "center",
                            padding: 4,
                          }}
                        >
                          {widget.source_type || widget.widget_type}
                          <br />
                          {widget.title}
                        </div>
                      )}

                    <div className="hw-tag">{widget.plc_tag || widget.hmi_tag || "未绑定"}</div>
                  </div>
                );
              })}

              <div className="hmi-glass" />
            </div>
          </div>
          <div className="hmi-print">
            <span className="hmi-print__name">
              {deviceName} · {device?.kind || "classic"}
            </span>
            <span className="hmi-print__power">
              <i />
              POWER
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
