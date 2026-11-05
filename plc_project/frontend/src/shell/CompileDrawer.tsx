import React from "react";
import type { CompileJobData, CompilerAttribution } from "../canvas/types";
import {
  buildWritebackSubStages,
  getStageStatusText,
  type WritebackStageView,
} from "../state/refactorPipeline";

export interface CompileDrawerProps {
  job: CompileJobData | null;
  attributions: CompilerAttribution[];
  healingRound?: number;
  maxHealingRounds?: number;
  circuitBroken?: boolean;
  circuitBreakerAlert?: string;
  healing?: boolean;
  onJump?(attr: CompilerAttribution): void;
  onCancel?(): void;
  onClose?(): void;
  onSmartHeal?(): void;
}

export const CompileDrawer: React.FC<CompileDrawerProps> = ({
  job,
  attributions,
  healingRound,
  maxHealingRounds,
  circuitBroken,
  circuitBreakerAlert,
  healing,
  onJump,
  onCancel,
  onClose,
  onSmartHeal,
}) => {
  if (!job && attributions.length === 0 && !circuitBroken) return null;

  const plcAttrs = attributions.filter((a) => a.target_type === "block" || a.target_type === "network");
  const hmiAttrs = attributions.filter((a) => a.target_type === "hmi_widget");

  const subStages: WritebackStageView[] = buildWritebackSubStages(job?.stages, {
    healingRound,
    maxHealingRounds,
    circuitBroken,
    circuitBreakerAlert,
  });

  const done = subStages.filter((s) => s.status === "ok" || s.status === "skipped").length;
  const pct = Math.round((done / subStages.length) * 100);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "ok":
        return { text: "完成", bg: "#14532d", color: "#86efac", icon: "✓" };
      case "running":
        return { text: "进行中", bg: "#1e3a8a", color: "#93c5fd", icon: "⏳" };
      case "healing":
        return { text: "自愈中", bg: "#78350f", color: "#fcd34d", icon: "⚡" };
      case "intercepted":
      case "blocked":
        return { text: "已拦截", bg: "#7f1d1d", color: "#fca5a5", icon: "🛡️" };
      case "error":
        return { text: "出错", bg: "#7f1d1d", color: "#fca5a5", icon: "✕" };
      case "skipped":
        return { text: "已跳过", bg: "#334155", color: "#94a3b8", icon: "—" };
      default:
        return { text: "待开始", bg: "#1e293b", color: "#64748b", icon: "○" };
    }
  };

  return (
    <div
      className="compile-drawer"
      data-ui="compile-drawer"
      style={{
        position: "absolute",
        right: 12,
        bottom: 12,
        width: 380,
        maxHeight: "65%",
        overflow: "auto",
        background: "var(--panel-bg, #0f172a)",
        border: "1px solid #334155",
        borderRadius: 8,
        padding: 14,
        zIndex: 40,
        fontSize: 12,
        color: "#e2e8f0",
        boxShadow: "0 8px 24px rgba(0,0,0,.45)",
      }}
    >
      {/* 头部标题与操作 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <strong style={{ fontSize: 13, color: "#f8fafc" }}>
            回写与自愈闭环 {job ? `· ${job.status}` : ""}
          </strong>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {job && (job.status === "running" || job.status === "queued") && onCancel && (
            <button
              type="button"
              onClick={onCancel}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                background: "#334155",
                color: "#f1f5f9",
                border: "none",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              取消
            </button>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                border: "none",
                color: "#94a3b8",
                fontSize: 16,
                cursor: "pointer",
                padding: "0 4px",
              }}
              title="关闭抽屉"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* 熔断告警横幅 */}
      {circuitBroken && (
        <div
          style={{
            background: "rgba(185, 28, 28, 0.2)",
            border: "1px solid #ef4444",
            borderRadius: 6,
            padding: 8,
            marginBottom: 10,
            color: "#fca5a5",
          }}
        >
          <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}>
            <span>⚠️</span> 熔断保护跳闸 (CircuitBreaker)
          </div>
          <div style={{ fontSize: 11, marginTop: 4, opacity: 0.9 }}>
            {circuitBreakerAlert || "同一块的同类错误连续出现达到阈值，已熔断停止自动尝试，防止LLM空转编造字段。"}
          </div>
        </div>
      )}

      {/* 5 子阶段总体进度条 */}
      <div style={{ height: 6, background: "#1e293b", borderRadius: 3, marginBottom: 10 }}>
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: job?.status === "error" || circuitBroken ? "#ef4444" : "#22c55e",
            borderRadius: 3,
            transition: "width 0.3s ease",
          }}
        />
      </div>

      {/* 5 阶段卡片视图 */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 11, color: "#94a3b8", marginBottom: 6 }}>
          阶段进度 (5 Sub-Stages)
        </div>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {subStages.map((s, idx) => {
            const badge = getStatusBadge(s.status);
            return (
              <li
                key={s.key}
                style={{
                  padding: "6px 8px",
                  background: s.status === "running" || s.status === "healing" ? "rgba(30, 58, 138, 0.25)" : "rgba(30, 41, 59, 0.4)",
                  border: s.status === "running" || s.status === "healing" ? "1px solid #3b82f6" : "1px solid #1e293b",
                  borderRadius: 6,
                  marginBottom: 4,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: 500, color: "#f1f5f9" }}>
                    {idx + 1}. {s.label}
                  </span>
                  <span
                    style={{
                      background: badge.bg,
                      color: badge.color,
                      fontSize: 10,
                      padding: "1px 6px",
                      borderRadius: 10,
                      fontWeight: 600,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 3,
                    }}
                  >
                    <span>{badge.icon}</span>
                    <span>{badge.text}</span>
                  </span>
                </div>
                {s.detail && (
                  <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 3, wordBreak: "break-all" }}>
                    {s.detail}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {/* 一键智能自愈按钮（当有编译报错时高亮展示） */}
      {attributions.length > 0 && onSmartHeal && (
        <div
          style={{
            background: "rgba(59, 130, 246, 0.1)",
            border: "1px solid #3b82f6",
            borderRadius: 6,
            padding: 8,
            marginBottom: 10,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ fontWeight: 600, color: "#93c5fd" }}>发现 {attributions.length} 处编译报错</div>
            <div style={{ fontSize: 11, color: "#94a3b8" }}>
              {healing ? "自愈闭环推进中…" : "受控槽位修复 + 白名单注入"}
            </div>
          </div>
          <button
            type="button"
            disabled={healing}
            onClick={onSmartHeal}
            style={{
              padding: "5px 12px",
              background: healing ? "#475569" : "#2563eb",
              color: "#ffffff",
              border: "none",
              borderRadius: 4,
              cursor: healing ? "not-allowed" : "pointer",
              fontWeight: 600,
              fontSize: 11,
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            <span>⚡</span>
            <span>{healing ? "自愈中…" : "一键智能自愈"}</span>
          </button>
        </div>
      )}

      {/* 归因错误列表 */}
      {plcAttrs.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, color: "#f87171", marginBottom: 4 }}>PLC 错误精准归因</div>
          {plcAttrs.map((a, i) => (
            <button
              key={`p-${i}`}
              type="button"
              onClick={() => onJump?.(a)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "rgba(127, 29, 29, 0.15)",
                border: "1px solid #7f1d1d",
                borderRadius: 4,
                color: a.severity === "error" ? "#fca5a5" : "#fde68a",
                cursor: "pointer",
                padding: "4px 6px",
                marginBottom: 4,
                fontSize: 11,
                lineHeight: 1.4,
              }}
              title="点击在画布上定位对应块与网络"
            >
              <div style={{ fontWeight: 600 }}>[{a.target_id}]</div>
              <div>{a.message}</div>
            </button>
          ))}
        </div>
      )}

      {hmiAttrs.length > 0 && (
        <div>
          <div style={{ fontWeight: 600, color: "#f87171", marginBottom: 4 }}>HMI 报错归因</div>
          {hmiAttrs.map((a, i) => (
            <button
              key={`h-${i}`}
              type="button"
              onClick={() => onJump?.(a)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "rgba(127, 29, 29, 0.15)",
                border: "1px solid #7f1d1d",
                borderRadius: 4,
                color: a.severity === "error" ? "#fca5a5" : "#fde68a",
                cursor: "pointer",
                padding: "4px 6px",
                marginBottom: 4,
                fontSize: 11,
              }}
              title="点击在画布上定位对应控件"
            >
              [{a.target_id}] {a.message}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
