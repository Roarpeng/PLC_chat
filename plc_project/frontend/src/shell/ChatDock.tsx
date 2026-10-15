import React, { useEffect, useRef } from "react";
import type { ChatMessage } from "../state/sessions";
import "./chatdock.css";

export interface ChatDockProps {
  /** 当前会话消息流 */
  messages: ChatMessage[];
  inputValue: string;
  onInputChange(v: string): void;
  onSend(): void;
  collapsed: boolean;
  onToggleCollapse(): void;
}

export const ChatDock: React.FC<ChatDockProps> = ({
  messages,
  inputValue,
  onInputChange,
  onSend,
  collapsed,
  onToggleCollapse,
}) => {
  const listRef = useRef<HTMLDivElement | null>(null);

  // 新消息追加后自动滚到底部（展开瞬间也校正到底部）
  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length, collapsed]);

  return (
    <section
      className={"dock" + (collapsed ? " dock--collapsed" : "")}
      aria-label="当前对话"
    >
      <header className="dock-head">
        <div className="dock-headinfo">
          <span className="dock-title">当前对话</span>
          <span className="dock-count">{messages.length} 条消息</span>
        </div>
        <button
          type="button"
          className="dock-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "展开当前对话" : "折叠当前对话"}
          title={collapsed ? "展开当前对话" : "折叠当前对话"}
          onClick={onToggleCollapse}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path
              d={collapsed ? "M3 5.5 7 9.5l4-4" : "M3 8.5 7 4.5l4 4"}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </header>

      {!collapsed && (
        <div className="dock-body">
          <div className="dock-messages" ref={listRef}>
            {messages.length === 0 ? (
              <p className="dock-empty">输入指令，画布会实时更新，可随时在历史中找回。</p>
            ) : (
              messages.map((m) =>
                m.role === "user" ? (
                  <div className="dock-msg dock-msg--user" key={m.id}>
                    <div className="dock-bubble">{m.text}</div>
                  </div>
                ) : (
                  <div className="dock-msg dock-msg--system" key={m.id}>
                    <div className="dock-sysline">{m.text}</div>
                  </div>
                )
              )
            )}
          </div>
          <form
            className="dock-inputrow"
            onSubmit={(e) => {
              e.preventDefault();
              onSend();
            }}
          >
            <input
              className="dock-input"
              type="text"
              value={inputValue}
              placeholder="自然语言指令，例如：增加急停信号并添加红色急停按钮"
              aria-label="自然语言指令输入框"
              onChange={(e) => onInputChange(e.target.value)}
            />
            <span className="dock-key" aria-hidden="true">
              Enter
            </span>
            <button type="submit" className="dock-send">
              发送指令
            </button>
          </form>
        </div>
      )}
    </section>
  );
};
