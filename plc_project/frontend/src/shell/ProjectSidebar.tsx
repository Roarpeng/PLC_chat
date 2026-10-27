/**
 * ProjectSidebar —— 左侧工程栏(docs/25 §3,S 线;Gemini 式窄条)。
 *
 * 工程是一等实体:工程名(点击=切换活跃工程)+ 当前工程展开的对话子列表
 * (点击=切对话)+ 「+ 新对话」;悬停工程行出现删除按钮,删除需经确认弹窗
 * (警告:所有对话和画布将删除)。可整体折叠成 ~48px 图标条(只显示工程
 * 首字,悬停出全名,当前工程高亮)。非活跃工程的对话列表折叠不显示。
 *
 * 样式走 ProjectSidebar.css(前缀 psb-):深色工业导轨,复用 HMI 屏幕域
 * 令牌(--scr-*);对话项时间戳复用 state/sessions 的 relativeTime。
 * 数据类型来自 state/projects(P 线);本组件不直接发请求。
 */
import React, { useEffect, useMemo, useState } from "react";
import { relativeTime } from "../state/sessions";
import type { ConversationMeta, ProjectMeta } from "../state/projects";
import "./ProjectSidebar.css";

export interface ProjectSidebarProps {
  /** 全部工程(顺序由上层控制,一般按 updatedAt 降序) */
  projects: ProjectMeta[];
  activeProjectId: string | null;
  /** 当前活跃工程的对话(仅活跃工程的) */
  conversations: ConversationMeta[];
  activeConversationId: string | null;
  /** 折叠成 ~48px 图标条 */
  collapsed: boolean;
  onSelectProject(pid: string): void;
  onSelectConversation(cid: string): void;
  onNewConversation(): void;
  onNewProject(): void;
  onDeleteProject(pid: string): void;
  onToggleCollapse(): void;
}

/* ---- 小图标(内联 SVG,风格与 HistorySidebar 一致:细线方角) ---- */

const BrandMark: React.FC = () => (
  <svg className="psb-brand-mark" width="18" height="18" viewBox="0 0 100 100" aria-hidden="true">
    <rect width="100" height="100" fill="#1E5F97" />
    <rect x="20" y="32" width="60" height="9" fill="#fff" />
    <rect x="20" y="47" width="40" height="9" fill="#fff" />
    <rect x="20" y="62" width="50" height="9" fill="#fff" />
  </svg>
);

const IconPlus: React.FC<{ size?: number }> = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
    <path
      d="M6 2v8M2 6h8"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
  </svg>
);

const IconChevronDown: React.FC = () => (
  <svg className="psb-chev" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
    <path
      d="M2 3.6 5 6.6l3-3"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const IconChevronsLeft: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
    <path
      d="M7.5 3 3.5 7l4 4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M11.5 3 7.5 7l4 4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const IconChevronsRight: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
    <path
      d="M6.5 3l4 4-4 4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M2.5 3l4 4-4 4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const IconTrash: React.FC = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
    <path
      d="M2 3.2h8M4.7 3.2V1.9h2.6v1.3M3.1 3.2l.5 7h4.8l.5-7M5 5.5v2.8M7 5.5v2.8"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const IconWarn: React.FC = () => (
  <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
    <path
      d="M10 2.8 18.3 17H1.7Z"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinejoin="round"
    />
    <path d="M10 8v4.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    <circle cx="10" cy="15.3" r="0.95" fill="currentColor" />
  </svg>
);

/** 工程首字图标(中文取首汉字;拉丁转大写;空名兜底 "?") */
function projectInitial(name: string): string {
  const ch = (name ?? "").trim().charAt(0);
  return ch ? ch.toUpperCase() : "?";
}

/**
 * 左侧工程栏。展开 ~240px:标题 / 新建工程主按钮 / 工程+对话树 / 底部折叠钮;
 * 折叠 ~48px:品牌标 + 新建工程 + 工程首字图标列 + 底部展开钮。
 * 删除工程经确认弹窗二次确认后才回调 onDeleteProject。
 */
export const ProjectSidebar: React.FC<ProjectSidebarProps> = ({
  projects,
  activeProjectId,
  conversations,
  activeConversationId,
  collapsed,
  onSelectProject,
  onSelectConversation,
  onNewConversation,
  onNewProject,
  onDeleteProject,
  onToggleCollapse,
}) => {
  /** 待确认删除的工程 id(非空 = 弹窗打开) */
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const pendingDelete = projects.find((p) => p.id === pendingDeleteId) ?? null;

  // Esc 关闭确认弹窗(与遮罩点击、取消按钮等价)
  useEffect(() => {
    if (!pendingDeleteId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPendingDeleteId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pendingDeleteId]);

  // 防御:只保留当前工程的对话,并按 updatedAt 降序(新对话在上)
  const activeConversations = useMemo(
    () =>
      conversations
        .filter((c) => !activeProjectId || c.projectId === activeProjectId)
        .slice()
        .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0)),
    [conversations, activeProjectId],
  );

  const confirmDialog = pendingDelete ? (
    <div
      className="psb-confirm-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) setPendingDeleteId(null);
      }}
    >
      <div className="psb-confirm" role="dialog" aria-modal="true" aria-labelledby="psb-confirm-title">
        <div className="psb-confirm-head">
          <span className="psb-confirm-mark" aria-hidden="true">
            <IconWarn />
          </span>
          <div className="psb-confirm-heading">
            <div className="psb-confirm-title" id="psb-confirm-title">
              删除工程「{pendingDelete.name}」?
            </div>
            <p className="psb-confirm-text">将删除该工程下的所有对话和画布,不可恢复。</p>
          </div>
        </div>
        <div className="psb-confirm-actions">
          <button type="button" className="btn btn--ghost" onClick={() => setPendingDeleteId(null)}>
            取消
          </button>
          <button
            type="button"
            className="btn btn--danger"
            onClick={() => {
              const id = pendingDelete.id;
              setPendingDeleteId(null);
              onDeleteProject(id);
            }}
          >
            删除工程
          </button>
        </div>
      </div>
    </div>
  ) : null;

  /* ---- 折叠态:~48px 图标条 ---- */

  if (collapsed) {
    return (
      <aside className="psb psb--rail" aria-label="工程栏(已折叠)">
        <div className="psb-rail-head">
          <BrandMark />
        </div>
        <button
          type="button"
          className="psb-rail-new"
          aria-label="新建工程"
          title="新建工程"
          onClick={onNewProject}
        >
          <IconPlus size={13} />
        </button>
        <nav className="psb-rail-list" aria-label="工程列表">
          {projects.length === 0 && <div className="psb-rail-empty" title="还没有工程">–</div>}
          {projects.map((p) => {
            const active = p.id === activeProjectId;
            return (
              <button
                key={p.id}
                type="button"
                className={"psb-rail-item" + (active ? " psb-rail-item--active" : "")}
                title={p.name}
                aria-label={`切换到工程 ${p.name}`}
                aria-current={active ? "true" : undefined}
                onClick={() => onSelectProject(p.id)}
              >
                {projectInitial(p.name)}
              </button>
            );
          })}
        </nav>
        <div className="psb-rail-foot">
          <button
            type="button"
            className="psb-rail-expand"
            aria-label="展开工程栏"
            title="展开工程栏"
            onClick={onToggleCollapse}
          >
            <IconChevronsRight />
          </button>
        </div>
      </aside>
    );
  }

  /* ---- 展开态:~240px ---- */

  return (
    <aside className="psb" aria-label="工程栏">
      <div className="psb-top">
        <div className="psb-brand">
          <BrandMark />
          <span className="psb-brand-name">PLC Co-Pilot</span>
        </div>
        <button
          type="button"
          className="psb-iconbtn"
          aria-label="折叠工程栏"
          title="折叠工程栏"
          onClick={onToggleCollapse}
        >
          <IconChevronsLeft />
        </button>
      </div>

      <button type="button" className="psb-new" onClick={onNewProject}>
        <IconPlus size={13} />
        <span>新建工程</span>
      </button>

      <nav className="psb-list" aria-label="工程与对话列表">
        {projects.length === 0 && (
          <div className="psb-empty">
            还没有工程
            <br />
            点击上方「新建工程」开始
          </div>
        )}
        {projects.map((p) => {
          const isActive = p.id === activeProjectId;
          return (
            <section
              key={p.id}
              className={"psb-project" + (isActive ? " psb-project--active" : "")}
              aria-label={`工程 ${p.name}`}
            >
              <button
                type="button"
                className="psb-project-main"
                title={p.name}
                aria-current={isActive ? "true" : undefined}
                aria-expanded={isActive ? "true" : "false"}
                onClick={() => onSelectProject(p.id)}
              >
                <IconChevronDown />
                <span className="psb-project-name">{p.name}</span>
              </button>
              <button
                type="button"
                className="psb-project-del"
                aria-label={`删除工程 ${p.name}`}
                title="删除工程"
                onClick={() => setPendingDeleteId(p.id)}
              >
                <IconTrash />
              </button>

              {isActive && (
                <div className="psb-convlist">
                  {activeConversations.map((c) => {
                    const convActive = c.id === activeConversationId;
                    return (
                      <div className={"psb-conv" + (convActive ? " psb-conv--active" : "")} key={c.id}>
                        <button
                          type="button"
                          className="psb-conv-main"
                          title={c.title}
                          aria-current={convActive ? "true" : undefined}
                          onClick={() => onSelectConversation(c.id)}
                        >
                          <span className="psb-conv-dot" aria-hidden="true" />
                          <span className="psb-conv-title">{c.title || "未命名对话"}</span>
                          <span className="psb-conv-time">{relativeTime(c.updatedAt)}</span>
                        </button>
                      </div>
                    );
                  })}
                  <button type="button" className="psb-newconv" onClick={onNewConversation}>
                    <IconPlus size={11} />
                    <span>新对话</span>
                  </button>
                </div>
              )}
            </section>
          );
        })}
      </nav>

      <div className="psb-foot">
        <button type="button" className="psb-foot-btn" onClick={onToggleCollapse}>
          <IconChevronsLeft />
          <span>折叠工程栏</span>
        </button>
      </div>

      {confirmDialog}
    </aside>
  );
};
