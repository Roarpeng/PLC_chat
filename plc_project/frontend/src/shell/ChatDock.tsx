import React, { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../state/sessions";
import {
  pipelineActiveStage,
  pipelineSettled,
  type PipelineStageView,
} from "../state/refactorPipeline";
import MarkdownBody from "../MarkdownBody";
import { linkifyBlockNames } from "./blockRefs";
import "./chatdock.css";

export interface ChatDockProps {
  /** 当前会话消息流 */
  messages: ChatMessage[];
  inputValue: string;
  onInputChange(v: string): void;
  onSend(): void;
  collapsed: boolean;
  onToggleCollapse(): void;
  /** 点击建议问题直接发送(工程简报的建议条目) */
  onSuggestion?(text: string): void;
  /** 已知块名清单(canvas.blocks 键):消息里的块名渲染为可点击块引用 */
  blockNames?: string[];
  /** 点击块引用 → 画布打开对应功能块 */
  onOpenBlock?(name: string): void;
  /** 重构流水线进度卡(App 侧轮询驱动;null=无在飞/终态已清) */
  pipeline?: {
    jobId: string;
    startedAt: number;
    stages: PipelineStageView[];
  } | null;
}

/** 重构流水线进度卡:阶段芯片(完成/进行/待开始/跳过/出错) + 作业号 + 实时时耗 */
const PipelineCard: React.FC<{ pipeline: NonNullable<ChatDockProps["pipeline"]> }> = ({
  pipeline,
}) => {
  const [now, setNow] = useState(() => Date.now());
  const settled = pipelineSettled(pipeline.stages);
  useEffect(() => {
    if (settled) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [settled]);
  const active = pipelineActiveStage(pipeline.stages);
  const secs = Math.max(0, Math.floor((now - pipeline.startedAt) / 1000));
  const elapsed = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  return (
    <div className="dock-pipeline" role="status" aria-label="重构流水线进度">
      <div className="dock-pipeline__head">
        <span className="dock-pipeline__title">
          重构流水线{settled ? " · 已结束" : ""}
        </span>
        <span className="dock-pipeline__elapsed">{elapsed}</span>
        <span className="dock-pipeline__job">作业 {pipeline.jobId.slice(0, 10)}</span>
      </div>
      <ol className="dock-pipeline__stages">
        {pipeline.stages.map((st) => (
          <li
            key={st.key}
            className={`dock-pipeline__stage is-${st.status}`}
            title={st.detail || st.label}
          >
            <i className="dock-pipeline__dot" aria-hidden="true" />
            {st.label}
          </li>
        ))}
      </ol>
      {active?.detail && <p className="dock-pipeline__detail">{active.detail}</p>}
    </div>
  );
};

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
    <div className="dock-mermaid" data-ui="mermaid-output">
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

/** 从系统消息中提取建议问题(编号列表行),渲染为可点击按钮 */
const SuggestionList: React.FC<{ text: string; onSuggestion?: (t: string) => void }> = ({
  text,
  onSuggestion,
}) => {
  const lines = text.split("\n");
  const suggIdx = lines.findIndex((l) => l.includes("建议从这里开始问"));
  if (suggIdx < 0 || !onSuggestion) return null;
  const suggs = lines
    .slice(suggIdx + 1)
    .map((l) => l.replace(/^\d+\.\s*/, "").trim())
    .filter(Boolean);
  if (!suggs.length) return null;
  return (
    <div className="dock-suggestions" role="group" aria-label="建议问题">
      {suggs.map((s, i) => (
        <button
          key={`sugg-${i}`}
          type="button"
          className="dock-suggestion-btn"
          title="点击发送此问题"
          onClick={() => onSuggestion(s)}
        >
          {s}
        </button>
      ))}
    </div>
  );
};

/** 系统消息正文:文本段照旧 Markdown 渲染,mermaid 围栏段替换为 MermaidBlock。
    传入块名清单时,文本段先做块名 linkify,块名在 MarkdownBody 里渲染为可点击块引用。 */
const SystemMessageBody: React.FC<{
  text: string;
  blockNames?: string[];
  onOpenBlock?: (name: string) => void;
}> = ({ text, blockNames, onOpenBlock }) => {
  const nameSet = useMemo(
    () => (blockNames?.length ? new Set(blockNames) : undefined),
    [blockNames],
  );
  const segments = splitMermaidSegments(text);
  return (
    <div className="dock-md">
      {segments.map((seg, i) =>
        seg.kind === "mermaid" ? (
          <MermaidBlock key={`mmd-${i}`} code={seg.body} />
        ) : seg.body.trim() ? (
          <MarkdownBody
            key={`txt-${i}`}
            content={nameSet ? linkifyBlockNames(seg.body, nameSet) : seg.body}
            blockNames={nameSet}
            onOpenBlock={onOpenBlock}
          />
        ) : null,
      )}
    </div>
  );
};

/** 单条消息:时间标签 + 正文(系统消息渲染 Markdown) + 悬停复制按钮 */
const DockMessage: React.FC<{
  m: ChatMessage;
  onSuggestion?: (t: string) => void;
  blockNames?: string[];
  onOpenBlock?: (name: string) => void;
}> = ({ m, onSuggestion, blockNames, onOpenBlock }) => {
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
      <SystemMessageBody text={m.text} blockNames={blockNames} onOpenBlock={onOpenBlock} />
      <SuggestionList text={m.text} onSuggestion={onSuggestion} />
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
  onSuggestion,
  blockNames,
  onOpenBlock,
  pipeline = null,
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
      <header className="dock-head" data-ui="dock-header">
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
              <div className="dock-welcome" aria-label="开始对话">
                <h3 className="dock-welcome__title">
                  把工艺说清楚，
                  <br />
                  逻辑交给我。
                </h3>
                <p className="dock-welcome__sub">
                  一句话工艺意图，Co-Pilot
                  生成可编译的 SCL 逻辑并回写博图：新增信号与安全联锁、重构功能块、生成 HMI
                  画面。输入指令后画布实时更新，全部变更带证据入账，可随时在历史中找回。
                </p>
                <div className="dock-welcome__sketch" aria-label="急停回路工程草稿线稿">
                  <svg
                    className="dock-welcome__sketch-svg"
                    viewBox="0 0 640 120"
                    role="img"
                    aria-label="工程草稿：急停按钮经接触器切断电机控制回路"
                  >
                    {/* 梯级母线（左） */}
                    <g className="sk-ink">
                      <line x1="24" y1="18" x2="24" y2="102" />
                    </g>
                    {/* 急停按钮：蘑菇头 + 断开触点 */}
                    <g className="sk-ink" transform="rotate(-0.6 70 44)">
                      <line x1="24" y1="44" x2="56" y2="44" />
                      <circle cx="70" cy="44" r="12" />
                      <circle cx="70" cy="44" r="5" />
                      <line x1="58" y1="30" x2="82" y2="58" strokeDasharray="3 4" />
                      <line x1="84" y1="44" x2="120" y2="44" />
                    </g>
                    <text className="sk-label" x="50" y="24">%I0.0 急停</text>
                    {/* 接触器触点 */}
                    <g className="sk-ink" transform="rotate(0.5 160 44)">
                      <line x1="120" y1="44" x2="146" y2="44" />
                      <line x1="146" y1="44" x2="162" y2="34" />
                      <line x1="176" y1="44" x2="212" y2="44" />
                    </g>
                    <text className="sk-label" x="128" y="24">K1</text>
                    {/* 线圈/输出（钴蓝，虚线直连电机） */}
                    <g className="sk-accent">
                      <line x1="212" y1="44" x2="236" y2="44" />
                      <path d="M236 32 q14 12 0 24 q-14 -12 0 -24" />
                      <line x1="252" y1="44" x2="520" y2="44" strokeDasharray="7 6" />
                      <path d="M512 36 l8 8 -8 8" />
                    </g>
                    <text className="sk-label sk-label--accent" x="226" y="24">%Q0.1 运行</text>
                    {/* 电机 M（右） */}
                    <g className="sk-ink" transform="rotate(-0.4 560 60)">
                      <circle cx="560" cy="60" r="30" />
                      <text className="sk-m" x="551" y="70">M</text>
                      <line x1="590" y1="60" x2="616" y2="60" />
                    </g>
                    <text className="sk-label" x="536" y="16">M1 电机</text>
                    {/* 底部标注：草稿尺寸线 */}
                    <g className="sk-construct">
                      <line x1="24" y1="108" x2="300" y2="108" />
                      <line x1="24" y1="103" x2="24" y2="113" />
                      <line x1="300" y1="103" x2="300" y2="113" />
                    </g>
                    <text className="sk-label" x="120" y="118">急停回路 · 草稿</text>
                  </svg>
                </div>
              </div>
            ) : (
              messages.map((m) => (
                <DockMessage key={m.id} m={m} onSuggestion={onSuggestion} blockNames={blockNames} onOpenBlock={onOpenBlock} />
              ))
            )}
          </div>
          {pipeline && pipeline.stages.length > 0 && <PipelineCard pipeline={pipeline} />}
          {pipeline && pipeline.stages.length === 0 && (
            <div className="dock-pipeline dock-pipeline--starting" role="status">
              <div className="dock-pipeline__head">
                <span className="dock-pipeline__title">重构流水线 · 启动中</span>
              </div>
            </div>
          )}
          <form
            className="dock-inputrow"
            data-ui="dock-input"
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
