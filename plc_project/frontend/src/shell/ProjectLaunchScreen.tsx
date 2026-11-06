/**
 * ProjectLaunchScreen —— 工作台启动态入口(F10 / P1-F,本批次合并双入口)。
 *
 * 出现条件(App.tsx 控制):无活跃会话且历史会话为空 —— 全新工作台的第一屏。
 * 原有「新建工程」与「从零生成标准工程」两个入口**合并为一个四步向导入口**:
 *   1. 继续最近项目:最近 3 个会话卡片(历史为空时整块隐藏);
 *   2. 导入工程:与顶栏「导入项目」按钮同一逻辑(打开 ImportDialog);
 *   3. 新建工程 · 四步向导:打开 NewProjectWizard,第一步生成 project_id 并
 *      贯穿全程,DB 编号 / IO 表上传为可选(D7),完成后才进入 Greenfield 通道。
 * 回调签名保持与 App.tsx 兼容(`onEnterGreenfield` 的 context 参数可选,不新增必需 props)。
 * 有历史会话时 App 不挂载本组件,保持既有「空白画布+引导」。
 */
import React, { useState } from "react";
import type { GFLaunchContext } from "../state/greenfield";
import type { ChatSession } from "../state/sessions";
import { NewProjectWizard } from "./NewProjectWizard";

export interface ProjectLaunchScreenProps {
  /** 全部历史会话(取 updatedAt 最新的前 3 张卡片;空则隐藏「继续最近项目」) */
  sessions: ChatSession[];
  /** 触发既有导入对话框(与顶栏「导入项目」同款逻辑) */
  onImport: () => void;
  /** 新建工程:打开需求卡草稿流(工艺先行);输入框为空时由 App 引导输入 */
  onNewProject: () => void;
  /** 点历史卡片 = 选中该会话(进画布) */
  onSelectSession: (id: string) => void;
  /** 从零生成标准工程:进入独立的规格工作台(确认前不产生任何修改)。
   * 收口接线(J9):把向导的工艺描述直接透出,供 App 作为 initialPrompt 传入通道,
   * 不再只依赖 loadLaunchContext() 兜底。参数可选,兼容 `() => void` 调用方。 */
  onEnterGreenfield?: (context?: GFLaunchContext) => void;
}

const SESSION_CARD_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 6,
  width: 320,
  padding: "14px 16px",
  background: "var(--surface)",
  borderLeft: "3px solid var(--line-2)",
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
  borderTop: "3px solid var(--line-2)",
  cursor: "pointer",
  textAlign: "left",
  font: "inherit",
  color: "inherit",
};

const hoverCss = `
.launch-entry:hover, .launch-session:hover { border-color: var(--accent); background: var(--surface-2); }
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
  onNewProject,
  onSelectSession,
  onEnterGreenfield,
}) => {
  const [wizardOpen, setWizardOpen] = useState(false);

  // 防御性排序:即使上游未按 updatedAt 降序,这里也取最新的前 3 个
  const recent = [...sessions]
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
    .slice(0, 3);

  return (
    <>
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
        <div style={{ fontSize: 22, color: "var(--ink)", fontWeight: 700, letterSpacing: "-0.01em" }}>
          开始你的 PLC 工程
        </div>
        <div style={{ marginTop: 6, fontSize: 13.5, color: "var(--ink-2)" }}>
          导入既有博图工程,或用四步向导从零开始 —— project_id 贯穿全程,确认前不产生任何修改
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

        {/* 入口 3(合并原「新建工程」+「从零生成标准工程」双入口):四步向导 */}
        <button
          type="button"
          className="launch-entry"
          style={{ ...ENTRY_STYLE, borderTopColor: "var(--accent, #1f2de6)" }}
          onClick={() => setWizardOpen(true)}
        >
          <span style={{ fontSize: 15, color: "var(--accent, #1f2de6)", fontWeight: 600 }}>
            新建工程 · 四步向导
          </span>
          <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
            合并后的单一入口：第一步生成 project_id 并贯穿全程 → 工艺描述 →
            可选资料（DB 编号 / IO 表可跳过，D7）→ 确认进入。无上传资料也能完成拓扑与逻辑确认，
            UI 不虚构地址 / OB 条目；确认设备逻辑前不产生任何修改
          </span>
        </button>
      </div>
    </div>
    {wizardOpen && (
      <NewProjectWizard
        onCancel={() => setWizardOpen(false)}
        onComplete={(context) => {
          setWizardOpen(false);
          // 两个既有回调在 App.tsx 中都是切到 greenfield 通道；优先用独立通道入口，
          // 并把向导 context（含工艺描述）直接透传给 App 的 initialPrompt。
          if (onEnterGreenfield) onEnterGreenfield(context);
          else onNewProject();
        }}
      />
    )}
    </>
  );
};
