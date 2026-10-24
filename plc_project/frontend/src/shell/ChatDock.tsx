import React, { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../state/sessions";
import MarkdownBody from "../MarkdownBody";
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

/** HH:MM 时间标签（无时间戳的旧消息显示 "—"） */
function timeLabel(ts: number | undefined): string {
  if (!ts) return "";
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // http/权限受限时的兜底（与 SclPane 复制同款）
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    document.body.removeChild(ta);
    return ok;
  }
}

/** 单条消息：时间标签 + 正文（系统消息渲染 Markdown）+ 悬停复制按钮 */
const DockMessage: React.FC<{ m: ChatMessage }> = ({ m }) => {
  const [copied, setCopied] = useState(false);
  const label = timeLabel(m.ts);
  const onCopy = async () => {
    if (await copyText(m.text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }
  };
  if (m.role === "user") {
    return (
      <div className="dock-msg dock-msg--user">
        <div className="dock-bubble">
          {m.text}
          {label && <span className="dock-time dock-time--user">{label}</span>}
        </div>
        <button
          type="button"
          className={"dock-copy" + (copied ? " is-copied" : "")}
          aria-label={copied ? "已复制" : "复制这条消息"}
          title={copied ? "已复制" : "复制"}
          onClick={() => void onCopy()}
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
    );
  }
  return (
    <div className="dock-msg dock-msg--system">
      <div className="dock-msgmeta">
        {label && <span className="dock-time">{label}</span>}
        <button
          type="button"
          className={"dock-copy" + (copied ? " is-copied" : "")}
          aria-label={copied ? "已复制" : "复制这条回答"}
          title={copied ? "已复制" : "复制"}
          onClick={() => void onCopy()}
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <MarkdownBody className="dock-md" content={m.text} />
    </div>
  );
};

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
              messages.map((m) => <DockMessage key={m.id} m={m} />)
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
