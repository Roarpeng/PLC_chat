import React from "react";
import type { CompileJobData, CompilerAttribution } from "../canvas/types";

export interface CompileDrawerProps {
  job: CompileJobData | null;
  attributions: CompilerAttribution[];
  onJump?(attr: CompilerAttribution): void;
  onCancel?(): void;
  onClose?(): void;
}

export const CompileDrawer: React.FC<CompileDrawerProps> = ({
  job,
  attributions,
  onJump,
  onCancel,
  onClose,
}) => {
  if (!job && attributions.length === 0) return null;

  const plcAttrs = attributions.filter((a) => a.target_type === "block" || a.target_type === "network");
  const hmiAttrs = attributions.filter((a) => a.target_type === "hmi_widget");
  const stages = job?.stages || [];
  const done = stages.filter((s) => s.status === "ok" || s.status === "skipped").length;
  const pct = stages.length ? Math.round((done / stages.length) * 100) : 0;

  return (
    <div
      className="compile-drawer"
      style={{
        position: "absolute",
        right: 12,
        bottom: 12,
        width: 360,
        maxHeight: "55%",
        overflow: "auto",
        background: "var(--panel-bg, #0f172a)",
        border: "1px solid #334155",
        borderRadius: 8,
        padding: 12,
        zIndex: 40,
        fontSize: 12,
        color: "#e2e8f0",
        boxShadow: "0 8px 24px rgba(0,0,0,.35)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <strong>编译作业 {job ? `· ${job.status}` : ""}</strong>
        <span>
          {job && (job.status === "running" || job.status === "queued") && onCancel && (
            <button type="button" onClick={onCancel} style={{ marginRight: 8 }}>
              取消
            </button>
          )}
          {onClose && (
            <button type="button" onClick={onClose}>
              ×
            </button>
          )}
        </span>
      </div>

      {job && (
        <>
          <div style={{ height: 6, background: "#1e293b", borderRadius: 3, marginBottom: 8 }}>
            <div
              style={{
                width: `${pct}%`,
                height: "100%",
                background: job.status === "error" ? "#ef4444" : "#22c55e",
                borderRadius: 3,
              }}
            />
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: "0 0 10px" }}>
            {stages.map((s) => (
              <li key={s.name} style={{ marginBottom: 4, opacity: s.status === "pending" ? 0.5 : 1 }}>
                <span style={{ width: 72, display: "inline-block" }}>{s.name}</span>
                <span> {s.status}</span>
                {s.message ? <span style={{ opacity: 0.7 }}> — {s.message}</span> : null}
              </li>
            ))}
          </ul>
          {job.error && <div style={{ color: "#fca5a5", marginBottom: 8 }}>{job.error}</div>}
        </>
      )}

      {plcAttrs.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>PLC</div>
          {plcAttrs.map((a, i) => (
            <button
              key={`p-${i}`}
              type="button"
              onClick={() => onJump?.(a)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "transparent",
                border: "none",
                color: a.severity === "error" ? "#fca5a5" : "#fde68a",
                cursor: "pointer",
                padding: "2px 0",
              }}
            >
              [{a.target_id}] {a.message}
            </button>
          ))}
        </div>
      )}

      {hmiAttrs.length > 0 && (
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>HMI</div>
          {hmiAttrs.map((a, i) => (
            <button
              key={`h-${i}`}
              type="button"
              onClick={() => onJump?.(a)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "transparent",
                border: "none",
                color: a.severity === "error" ? "#fca5a5" : "#fde68a",
                cursor: "pointer",
                padding: "2px 0",
              }}
            >
              [{a.target_id}] {a.message}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
