import React, { useEffect, useRef, useState } from "react";
import type { CanvasHmiWidgetData } from "../canvas/types";

export interface HmiPaneProps {
  widgets: CanvasHmiWidgetData[];
  focusWidgetId: string | null;
  onWidgetClick(w: CanvasHmiWidgetData): void;
}

/** HMI 仿真栏：工作台上的实体触摸屏（全应用唯一深色发光体）。
 *  外壳按栏宽/栏高自动等比缩放（不小于 25%），保证任意栏宽下完整可见。 */
export const HmiPane: React.FC<HmiPaneProps> = ({ widgets, focusWidgetId, onWidgetClick }) => {
  const zoneRef = useRef<HTMLDivElement>(null);
  const encRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState<{ k: number; w: number; h: number } | null>(null);

  useEffect(() => {
    const zone = zoneRef.current;
    const enc = encRef.current;
    if (!zone || !enc) return;
    const W = enc.offsetWidth || 780;
    const H = enc.offsetHeight || 550;
    const update = () => {
      const k = Math.max(0.25, Math.min(1, (zone.clientWidth - 20) / W, (zone.clientHeight - 20) / H));
      setScale({ k, w: Math.round(W * k), h: Math.round(H * k) });
    };
    update();
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(update);
      ro.observe(zone);
      return () => ro.disconnect();
    }
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return (
    <div className="hmi-zone" ref={zoneRef}>
      <div
        className="hmi-scaleholder"
        style={scale ? { width: scale.w, height: scale.h } : undefined}
      >
        <div
          className="hmi-enclosure"
          ref={encRef}
          style={scale && scale.k < 1 ? { transform: `scale(${scale.k})`, transformOrigin: "top left" } : undefined}
        >
          <div className="hmi-frame">
            <div className="hmi-screen">
              <div className="hmi-topbar">
                <span>SIMATIC HMI — 工艺主控画面 · 触摸仿真</span>
                <span className="hmi-topbar__link">
                  <i />
                  PLC LINK ONLINE
                </span>
              </div>

              {widgets.length === 0 && (
                <div className="hmi-empty">
                  <div className="hmi-empty__title">尚无 HMI 控件</div>
                  <div className="hmi-empty__text">通过底部对话添加，例如“添加启动按钮和转速表”</div>
                </div>
              )}

              {widgets.map((widget) => {
                const isError = widget.status === "error";
                const isFocused = focusWidgetId === widget.id;
                const btnColor = widget.properties?.color || "green";
                return (
                  <div
                    key={widget.id}
                    className={`hw ${isError ? "hw--error" : ""} ${isFocused ? "hw--focus" : ""}`}
                    data-widget-id={widget.id}
                    onClick={() => onWidgetClick(widget)}
                    style={{
                      left: `${widget.x}px`,
                      top: `${widget.y}px`,
                      width: `${widget.width}px`,
                      height: `${widget.height}px`,
                    }}
                  >
                    {widget.widget_type === "button" && (
                      <button
                        className={`hw-btn ${btnColor === "red" ? "hw-btn--red" : ""} ${
                          widget.current_value ? "is-on" : ""
                        }`}
                      >
                        {widget.title}
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
                          <span className="hw-gauge__unit">RPM</span>
                        </div>
                        <div className="hw-gauge__bar">
                          <i
                            style={{
                              width: `${Math.min(
                                100,
                                Math.round(((Number(widget.current_value) || 0) / 1500) * 100)
                              )}%`,
                            }}
                          />
                        </div>
                      </div>
                    )}

                    <div className="hw-tag">{widget.plc_tag || "未绑定"}</div>
                  </div>
                );
              })}

              <div className="hmi-glass" />
            </div>
          </div>
          <div className="hmi-print">
            <span className="hmi-print__name">SIMATIC HMI · TP700 COMFORT</span>
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
