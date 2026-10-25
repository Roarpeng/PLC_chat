/**
 * WorkbenchHeader —— 工程概览横条(docs/22-workbench-p0-contract.md §4,F1 自建)。
 *
 * 活跃项目(activeSessionId 存在且画布有块)时,顶栏下沿常驻一条紧凑横条:
 *   项目名 · PLC(canvas.source.plc_name 或 —) · 块数/变量数/标签数(canvas 即时统计,
 *   由 App 计算后传入) · 会话更新时间;右侧「审查最近变更」次级按钮
 *   (打开 ChangeReviewDrawer 审查最新一条 PCEC 事务,契约 §3)。
 * 基线指纹不在本条展示(契约 §4:复用确认弹窗逻辑不动)。
 * 样式走现有设计令牌(tagchip / --surface-2 / --line-2),低显著度。
 */
import React from "react";

export interface WorkbenchHeaderProps {
  projectName: string;
  /** canvas.source.plc_name;缺失显示 — */
  plcName: string | null;
  /** 三项即时统计(canvas 即时计算后传入) */
  blockCount: number;
  variableCount: number;
  tagCount: number;
  /** 活跃会话更新时间(ms epoch);无会话信息时为 null → 显示 — */
  sessionUpdatedAt: number | null;
  /** 打开最近一条变更的四层审查抽屉(fetchChanges 取最新 id) */
  onReviewLatestChange: () => void;
}

/** ms epoch → "MM-DD HH:mm"(与账本列表 formatChangeTime 同口径) */
function timeLabel(ms: number | null): string {
  if (!ms) return "—";
  const d = new Date(ms);
  const p2 = (n: number) => String(n).padStart(2, "0");
  return `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

const SEP: React.CSSProperties = { color: "var(--line-2)" };

export const WorkbenchHeader: React.FC<WorkbenchHeaderProps> = ({
  projectName,
  plcName,
  blockCount,
  variableCount,
  tagCount,
  sessionUpdatedAt,
  onReviewLatestChange,
}) => (
  <div
    className="workbench-header"
    data-ui="workbench-header"
    role="status"
    aria-label="工程概览"
    style={{
      flex: "none",
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "5px 14px",
      background: "var(--surface-2)",
      borderBottom: "1px solid var(--line-2)",
      fontSize: 12.5,
      color: "var(--ink-2)",
    }}
  >
    <span style={{ color: "var(--ink)", fontWeight: 500 }}>{projectName || "未命名项目"}</span>
    <span style={SEP}>·</span>
    <span title="canvas.source.plc_name(工程来源 CPU/PLC)">PLC {plcName || "—"}</span>
    <span style={SEP}>·</span>
    <span className="tagchip" title="逻辑块 / 接口变量 / 物理标签(canvas 即时统计)">
      块 {blockCount} · 变量 {variableCount} · 标签 {tagCount}
    </span>
    <span style={SEP}>·</span>
    <span title="活跃会话最后更新时间">更新 {timeLabel(sessionUpdatedAt)}</span>

    <span style={{ flex: 1 }} />

    {/* 次级入口:审查最近一条变更(四层审查抽屉;ChangeLogDrawer 条目入口归 F2/收口) */}
    <button
      type="button"
      className="btn btn--ghost"
      onClick={onReviewLatestChange}
      title="打开最近一条工程变更的四层审查(工艺/逻辑/源码/验证)"
      style={{ padding: "2px 10px", fontSize: 12 }}
    >
      审查最近变更
    </button>
  </div>
);
