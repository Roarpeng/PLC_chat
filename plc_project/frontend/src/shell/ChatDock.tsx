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

/* ==========================================================================
   Mermaid 时序图（docs/24 C 线）：系统消息里的 ```mermaid 围栏 → SVG 内联渲染。
   渲染失败或未就绪时回退普通代码块；SVG 下方提供「复制 Mermaid 源码」。
   样式走现有令牌（--surface/--line/--accent…），随组件注入一份作用域样式。
   ========================================================================== */

/** ```mermaid 围栏：开栏行允许可选尾缀，闭栏前容忍空白 */
const MERMAID_FENCE_RE = /```mermaid[^\n]*\n([\s\S]*?)```/g;

type MessageSegment = { kind: "text" | "mermaid"; body: string };

/** 把系统消息正文切成 mermaid 围栏段与普通文本段（围栏段优先走 SVG 渲染）。 */
function splitMermaidSegments(text: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(MERMAID_FENCE_RE)) {
    const at = match.index ?? 0;
    if (at > cursor) {
      segments.push({ kind: "text", body: text.slice(cursor, at) });
    }
    segments.push({ kind: "mermaid", body: match[1].trim() });
    cursor = at + match[0].length;
  }
  if (cursor < text.length) {
    segments.push({ kind: "text", body: text.slice(cursor) });
  }
  return segments;
}

let mermaidModule: Promise<typeof import("mermaid")> | null = null;

/** 懒加载 mermaid（本地打包，无 CDN；体积大故异步 chunk，不进主包）。只初始化一次。 */
function loadMermaid(): Promise<typeof import("mermaid")> {
  if (!mermaidModule) {
    mermaidModule = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "neutral",
      });
      return mod;
    });
  }
  return mermaidModule;
}

let mermaidRenderSeq = 0;

/** 单个 Mermaid 块：mermaid.render → SVG 内联；失败回退源码块 + 复制按钮。 */
const MermaidBlock: React.FC<{ code: string }> = ({ code }) => {
  const [svg, setSvg] = useState("");
  const [ready, setReady] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const renderId = `dock-mmd-${++mermaidRenderSeq}`;
    loadMermaid()
      .then((mod) => mod.default.render(renderId, code))
      .then(({ svg: out }) => {
        if (!cancelled) {
          setSvg(out);
          setReady(true);
        }
      })
      .catch(() => {
        // 渲染失败：保持代码块回退；清掉 mermaid 可能遗留的临时节点
        const leftover = document.getElementById(renderId);
        if (leftover) leftover.remove();
        if (!cancelled) setReady(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  const onCopy = async () => {
    if (await copyText(code)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }
  };

  return (
    <div className="dock-mermaid">
      {ready && svg ? (
        <div className="dock-mermaid-svg" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <code className="md-code-block language-mermaid">{code}</code>
      )}
      <button
        type="button"
        className={"dock-mermaid-copy" + (copied ? " is-copied" : "")}
        aria-label={copied ? "已复制 Mermaid 源码" : "复制 Mermaid 源码"}
        title={copied ? "已复制" : "复制 Mermaid 源码"}
        onClick={() => void onCopy()}
      >
        {copied ? "已复制" : "复制 Mermaid 源码"}
      </button>
    </div>
  );
};

/** 系统消息正文：文本段照旧 Markdown 渲染，mermaid 围栏段替换为 MermaidBlock。 */
const SystemMessageBody: React.FC<{ text: string }> = ({ text }) => {
  const segments = splitMermaidSegments(text);
  return (
    <div className="dock-md">
      {segments.map((seg, i) =>
        seg.kind === "mermaid" ? (
          <MermaidBlock key={`mmd-${i}`} code={seg.body} />
        ) : seg.body.trim() ? (
          <MarkdownBody key={`txt-${i}`} content={seg.body} />
        ) : null,
      )}
    </div>
  );
};

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
      <SystemMessageBody text={m.text} />
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
      {/* Mermaid 内联渲染作用域样式（docs/24 C 线；样式走现有令牌） */}
      <style>{`
.dock-mermaid {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  margin: 6px 0;
  min-width: 0;
  max-width: 100%;
}
.dock-mermaid-svg {
  max-width: 100%;
  overflow-x: auto;
  padding: 8px;
  background: var(--surface, #ffffff);
  border: 1px solid var(--line, #e3e4de);
}
.dock-mermaid-svg svg {
  display: block;
  max-width: 100%;
  height: auto;
}
.dock-mermaid .md-code-block {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  font-family: var(--mono, monospace);
  font-size: 11.5px;
  line-height: 1.5;
  padding: 6px 8px;
  white-space: pre;
}
.dock-mermaid-copy {
  height: 22px;
  padding: 0 10px;
  border: 1px solid var(--line-2, #c3c7bc);
  border-radius: 0;
  background: var(--surface-2, #eff1ea);
  color: var(--ink-2, #454b46);
  font-family: var(--sans);
  font-size: 11px;
  line-height: 20px;
  cursor: pointer;
  transition: color 0.12s ease, border-color 0.12s ease, background 0.12s ease;
}
.dock-mermaid-copy:hover,
.dock-mermaid-copy.is-copied {
  color: var(--accent, #1d5a90);
  border-color: var(--accent, #1d5a90);
  background: var(--surface, #ffffff);
}
.dock-mermaid-copy.is-copied {
  font-weight: 600;
}
@media (prefers-reduced-motion: reduce) {
  .dock-mermaid-copy {
    transition-duration: 0.01ms !important;
  }
}
`}</style>
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
