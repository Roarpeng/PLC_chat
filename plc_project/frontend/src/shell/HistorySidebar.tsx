import React from "react";
import { groupSessions, relativeTime, type ChatSession } from "../state/sessions";
import "./sidebar.css";

export interface HistorySidebarProps {
  /** 已按 updatedAt 降序 */
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelect(id: string): void;
  onNewSession(): void;
  onDelete(id: string): void;
  /** 隐藏本栏 */
  onHide(): void;
}

export const HistorySidebar: React.FC<HistorySidebarProps> = ({
  sessions,
  activeSessionId,
  onSelect,
  onNewSession,
  onDelete,
  onHide,
}) => {
  const groups = groupSessions(sessions);

  return (
    <aside className="sb" aria-label="历史对话">
      <div className="sb-top">
        <div className="sb-brand">
          <svg
            className="sb-brand-mark"
            width="18"
            height="18"
            viewBox="0 0 100 100"
            aria-hidden="true"
          >
            <rect width="100" height="100" rx="18" fill="#1E5F97" />
            <rect x="20" y="32" width="60" height="9" fill="#fff" />
            <rect x="20" y="47" width="40" height="9" fill="#fff" />
            <rect x="20" y="62" width="50" height="9" fill="#fff" />
          </svg>
          <span className="sb-brand-name">PLC Co-Pilot</span>
        </div>
        <button
          type="button"
          className="sb-iconbtn"
          aria-label="隐藏历史对话"
          title="隐藏历史对话"
          onClick={onHide}
        >
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
        </button>
      </div>

      <button type="button" className="sb-new" onClick={onNewSession}>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path
            d="M6 2v8M2 6h8"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
        <span>新对话</span>
      </button>

      <nav className="sb-list" aria-label="历史对话列表">
        {sessions.length === 0 ? (
          <div className="sb-empty">还没有历史对话</div>
        ) : (
          groups.map((group) => (
            <section className="sb-group" key={group.label}>
              <div className="sb-group-label">{group.label}</div>
              {group.items.map((session) => {
                const active = session.id === activeSessionId;
                return (
                  <div
                    key={session.id}
                    className={"sb-item" + (active ? " sb-item--active" : "")}
                  >
                    <button
                      type="button"
                      className="sb-item-main"
                      title={session.title}
                      aria-current={active ? "true" : undefined}
                      onClick={() => onSelect(session.id)}
                    >
                      <span className="sb-item-title">{session.title}</span>
                      <span className="sb-item-time">
                        {relativeTime(session.updatedAt)}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="sb-item-del"
                      aria-label="删除对话"
                      title="删除对话"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(session.id);
                      }}
                    >
                      <svg width="11" height="11" viewBox="0 0 10 10" aria-hidden="true">
                        <path
                          d="M2 2l6 6M8 2 2 8"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                        />
                      </svg>
                    </button>
                  </div>
                );
              })}
            </section>
          ))
        )}
      </nav>
    </aside>
  );
};
