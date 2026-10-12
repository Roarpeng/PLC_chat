import { useEffect, useRef, useState, type FormEvent } from "react";
import MarkdownBody from "../../MarkdownBody";
import type { PlcCitation, PlcJobDetail } from "../../api";
import type { KnowledgeNode, WritebackChipHint } from "../../KnowledgeCanvas";
import { writebackHintForBlock } from "../detail";
import type { ChatMsg } from "../../workbench/model";
import { userBubbleParts } from "../../workbench/model";
import { CitationSourceList } from "./CitationSourceList";
import { readHumanNote, writeHumanNote } from "./humanNotes";
import {
  collectNodeCitations,
  inspectNode,
  nodeScopedMessages,
  type InspectContext,
} from "./inspectModel";

export type NodeWorkbenchTab = "meaning" | "run" | "tune";

type Props = {
  node: KnowledgeNode;
  job?: PlcJobDetail | null;
  messages: ChatMsg[];
  busy?: boolean;
  tab: NodeWorkbenchTab;
  noteFocusKey?: number;
  switchCue?: string | null;
  inspectCtx?: InspectContext;
  writebackHint?: (blockName: string) => WritebackChipHint;
  getSclPreview?: (blockName: string) => Array<{ block?: string }>;
  onTabChange: (tab: NodeWorkbenchTab) => void;
  onClose: () => void;
  onAsk: (node: KnowledgeNode, question: string) => Promise<void> | void;
  onOptimizePropose?: () => Promise<void> | void;
  onConfirmWriteback?: (node: KnowledgeNode) => Promise<void> | void;
  onJumpCitation?: (ref: string) => void;
};

const TABS: Array<{ id: NodeWorkbenchTab; label: string }> = [
  { id: "meaning", label: "是什么" },
  { id: "run", label: "怎么跑" },
  { id: "tune", label: "怎么调" },
];

export function NodeWorkbench({
  node,
  job,
  messages,
  busy,
  tab,
  noteFocusKey,
  switchCue,
  inspectCtx,
  writebackHint,
  getSclPreview,
  onTabChange,
  onClose,
  onAsk,
  onOptimizePropose,
  onConfirmWriteback,
  onJumpCitation,
}: Props) {
  const view = inspectNode(node, inspectCtx);
  const noteRef = useRef<HTMLTextAreaElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [note, setNote] = useState(() => readHumanNote(view.noteKey));
  const [draft, setDraft] = useState("");
  const [sclOpen, setSclOpen] = useState(false);
  const scoped = nodeScopedMessages(messages, node);
  const citations: PlcCitation[] = collectNodeCitations(messages, job, node);
  const blockName = String(node.source?.block_name || node.label || "");
  const hint = writebackHint
    ? writebackHint(blockName)
    : writebackHintForBlock(job, blockName);
  const sclHits = getSclPreview?.(blockName) || [];

  useEffect(() => {
    setNote(readHumanNote(view.noteKey));
  }, [view.noteKey]);

  useEffect(() => {
    if (!noteFocusKey) return;
    window.requestAnimationFrame(() => noteRef.current?.focus());
  }, [noteFocusKey]);

  useEffect(() => {
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, [node.id]);

  function saveNote(next: string) {
    setNote(next);
    writeHumanNote(view.noteKey, next);
  }

  function submitAsk(event: FormEvent) {
    event.preventDefault();
    const q = draft.trim();
    if (!q || busy) return;
    setDraft("");
    void onAsk(node, q);
  }

  const runPrompts =
    node.kind === "plc_tag"
      ? ["这个信号干什么?", "谁读写它"]
      : ["这个块干什么?", "分析逻辑", "展开 SCL", "谁读写这些信号?"];
  const tunePrompts = ["优化逻辑", "优化建议"];

  return (
    <aside className="kg-workbench" aria-label="节点工作台">
      <div className="kg-wb-head">
        <div>
          <div className="kg-wb-kicker">当前节点</div>
          <strong>{view.name}</strong>
          <div className="kg-wb-sub">
            {view.typeLabel}
            <span className={`kg-export-dot tone-${view.exportTone}`}>{view.exportStatus}</span>
          </div>
        </div>
        <button type="button" className="ghost compact" onClick={onClose} aria-label="关闭工作台">
          关闭
        </button>
      </div>
      {switchCue ? (
        <div className="kg-wb-switch" role="status">
          {switchCue}
        </div>
      ) : null}
      <div className="kg-wb-tabs" role="tablist" aria-label="工程师三问">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? "on" : ""}
            onClick={() => onTabChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="kg-wb-body">
        {tab === "meaning" ? (
          <section className="kg-wb-section" aria-label="是什么">
            <h3>含义</h3>
            <p>{view.meaning}</p>
            <h3>状态</h3>
            <ul className="kg-wb-status">
              {view.statusLines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <label className="kg-wb-note">
              人注（本机，不自动反写）
              <textarea
                ref={noteRef}
                rows={4}
                value={note}
                onChange={(e) => saveNote(e.target.value)}
                placeholder="例如：这是工艺主控，不要动互锁。"
              />
            </label>
          </section>
        ) : null}
        {tab === "run" ? (
          <section className="kg-wb-section" aria-label="怎么跑">
            <h3>引用源</h3>
            <CitationSourceList
              citations={citations}
              onJump={onJumpCitation}
              emptyHint="尚无带引用的跑法说明。问一句运行逻辑后，将按 block · locator · snippet 展示。"
            />
            <h3>节点问答</h3>
            {scoped.length ? (
              <div className="kg-wb-thread">
                {scoped.map((m) => {
                  const parts = userBubbleParts(m);
                  return (
                    <article key={m.id} className={`kg-wb-msg ${m.role}`}>
                      {m.role === "assistant" ? (
                        <MarkdownBody content={m.content} />
                      ) : (
                        <p>{parts.body}</p>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="muted">还没有针对 {view.name} 的问答。下面可以直接问。</p>
            )}
            <div className="kg-wb-chips">
              {runPrompts.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="ghost compact"
                  disabled={busy}
                  onClick={() => void onAsk(node, p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </section>
        ) : null}
        {tab === "tune" ? (
          <section className="kg-wb-section" aria-label="怎么调">
            <h3>HITL 调整建议</h3>
            <p className="muted">只生成建议与预览，不会自动 SCL 反写。</p>
            <div className="kg-wb-chips">
              {tunePrompts.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="ghost compact"
                  disabled={busy}
                  onClick={() => void onAsk(node, p)}
                >
                  {p}
                </button>
              ))}
            </div>
            <details
              className="kg-wb-scl"
              open={sclOpen}
              onToggle={(e) => setSclOpen((e.target as HTMLDetailsElement).open)}
            >
              <summary>SCL 优化 / 反写（默认折叠）</summary>
              <p className="muted">优化提案与确认反写仍走现有 HITL 门闩，需人工确认。</p>
              {onOptimizePropose ? (
                <button
                  type="button"
                  className="ghost compact"
                  disabled={busy}
                  onClick={() => void onOptimizePropose()}
                >
                  优化提案
                </button>
              ) : null}
              <button
                type="button"
                className="ghost compact"
                disabled={busy}
                onClick={() => void onAsk(node, "优化SCL")}
              >
                优化SCL
              </button>
              <button
                type="button"
                className="ghost compact"
                disabled={busy || node.kind === "plc_tag" || !hint.canWrite}
                title={hint.reason}
                onClick={() => {
                  if (node.kind === "plc_tag" || !hint.canWrite) return;
                  if (onConfirmWriteback) {
                    void onConfirmWriteback(node);
                    return;
                  }
                  void onAsk(node, "确认反写");
                }}
              >
                确认反写
              </button>
              {sclHits.length ? (
                <p className="muted">对话栏已有该块 SCL 预览（Diff / 改写前 / 改写后）。</p>
              ) : (
                <p className="muted">{hint.reason}</p>
              )}
            </details>
          </section>
        ) : null}
      </div>
      <form className="kg-wb-composer" onSubmit={submitAsk}>
        <div className="kg-wb-context" aria-live="polite">
          上下文 · {view.name}
        </div>
        <textarea
          ref={inputRef}
          rows={2}
          value={draft}
          disabled={busy}
          placeholder={`问 ${view.name}…`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <button type="submit" className="btn-primary compact" disabled={busy || !draft.trim()}>
          发送
        </button>
      </form>
    </aside>
  );
}
