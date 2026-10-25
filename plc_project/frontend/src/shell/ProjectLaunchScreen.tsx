/**
 * ProjectLaunchScreen —— 工作台启动态三入口(docs/22-workbench-p0-contract.md §4,F1 自建)。
 *
 * 出现条件(App.tsx 控制):无活跃会话(activeSessionId 为空且 canvas.blocks 为空)
 * 且历史会话为空 —— 全新工作台的第一屏。三个入口:
 *   1. 继续最近项目:最近 3 个会话卡片(历史为空时整块隐藏);
 *   2. 导入工程:与顶栏「导入项目」按钮同一逻辑(打开 ImportDialog);
 *   3. 从工艺需求开始:打开需求卡抽屉草稿态(需求先行,契约 §1 铁律:确认不产生修改)。
 * 有历史会话时 App 不挂载本组件,保持既有「空白画布+引导」。
 * 样式走现有设计令牌,低显著度、居中卡片式。
 */
import React from "react";
import type { ChatSession } from "../state/sessions";

export interface ProjectLaunchScreenProps {
  /** 全部历史会话(取 updatedAt 最新的前 3 张卡片;空则隐藏「继续最近项目」) */
  sessions: ChatSession[];
  /** 触发既有导入对话框(与顶栏「导入项目」同款逻辑) */
  onImport: () => void;
  /** 打开需求卡抽屉草稿态(requestDraft 空提示词) */
  onStartFromRequirement: () => void;
  /** 点历史卡片 = 选中该会话(进画布) */
  onSelectSession: (id: string) => void;
}

const SESSION_CARD_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 6,
  width: 320,
  padding: "14px 16px",
  background: "var(--surface)",
  border: "1px solid var(--line)",
  cursor: "pointer",
  textAlign: "left",
  font: "inherit",
  color: "inherit",
};

const ENTRY_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 8,
  flex: 1,
  minWidth: 240,
  padding: "20px 20px",
  background: "var(--surface)",
  border: "1px solid var(--line)",
  cursor: "pointer",
  textAlign: "left",
  font: "inherit",
  color: "inherit",
};

const hoverCss = `
.launch-entry:hover, .launch-session:hover { border-color: var(--line-2); background: var(--surface-2); }
`;

/** ms epoch → "MM-DD HH:mm"(与会话列表口径一致) */
function sessionTimeLabel(ts: number | undefined): string {
  if (!ts) return "";
  const d = new Date(ts);
  const p2 = (n: number) => String(n).padStart(2, "0");
  return `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

export const ProjectLaunchScreen: React.FC<ProjectLaunchScreenProps> = ({
  sessions,
  onImport,
  onStartFromRequirement,
  onSelectSession,
}) => {
  // 防御性排序:即使上游未按 updatedAt 降序,这里也取最新的前 3 个
  const recent = [...sessions]
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
    .slice(0, 3);

  return (
    <div
      className="launch"
      data-ui="project-launch-screen"
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 28,
        padding: 24,
        background: "var(--surface)",
        overflowY: "auto",
      }}
    >
      <style>{hoverCss}</style>

      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 20, color: "var(--ink)", fontWeight: 600 }}>
          开始你的 PLC 工程
        </div>
        <div style={{ marginTop: 6, fontSize: 13, color: "var(--ink-2)" }}>
          导入既有博图工程,或先把工艺需求讲清楚 —— 需求先行,确认不产生任何修改
        </div>
      </div>

      {/* 入口 1:继续最近项目(历史为空时隐藏) */}
      {recent.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "min(720px, 100%)" }}>
          <div style={{ fontSize: 13, color: "var(--ink-2)" }}>继续最近项目</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {recent.map((s) => (
              <button
                key={s.id}
                type="button"
                className="launch-session"
                style={SESSION_CARD_STYLE}
                onClick={() => onSelectSession(s.id)}
                title={`打开会话:${s.title}`}
              >
                <span style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
                  {s.title || "未命名会话"}
                </span>
                <span className="tagchip">{s.messages.length} 条消息</span>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>
                  更新于 {sessionTimeLabel(s.updatedAt)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div
        style={{
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
          justifyContent: "center",
          width: "min(860px, 100%)",
        }}
      >
        {/* 入口 2:导入工程(与顶栏「导入项目」同款逻辑) */}
        <button type="button" className="launch-entry" style={ENTRY_STYLE} onClick={onImport}>
          <span style={{ fontSize: 15, color: "var(--ink)", fontWeight: 500 }}>导入工程</span>
          <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
            导入博图 Openness 导出的 XML / 服务器路径 / .zap19 归档,全部对象标记为已同步
          </span>
        </button>

        {/* 入口 3:从工艺需求开始(需求卡抽屉草稿态) */}
        <button
          type="button"
          className="launch-entry"
          style={ENTRY_STYLE}
          onClick={onStartFromRequirement}
        >
          <span style={{ fontSize: 15, color: "var(--ink)", fontWeight: 500 }}>
            从工艺需求开始
          </span>
          <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
            先描述工艺意图,生成需求卡(前置/序列/异常/约束/验收),确认后再进入逻辑编辑
          </span>
        </button>
      </div>
    </div>
  );
};
