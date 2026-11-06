/**
 * Greenfield 对话流（chat 唯一入口 · one-motif：消息即步序块节点）：
 * - 用户消息 = 墨色节点（右桩），助手消息 = 纸色节点（左桩），系统事件 = 图例行
 * - 编辑类消息 diff-first：先列 patch 结构，再读叙述（agent 交互模式 #13）
 * - 动作卡长在事件消息下：回执【确认解析结果】、交付【下载工程包】
 * - 输入区：多行输入 + 附件（PDF/Excel/CSV/SCL）+ 整区拖拽 + SCL 粘贴识别 + Enter 发送
 * - 消息真值来自后端 state.messages，前端不自建
 */
import React, { useEffect, useRef, useState } from "react";
import MarkdownBody from "../MarkdownBody";
import {
  downloadPackageUrl,
  type GFChatMessage,
  type GFState,
} from "../state/greenfield";

export interface GreenfieldChatFeedProps {
  state: GFState;
  busy: boolean;
  onSend: (text: string) => void;
  onSendFiles: (files: File[]) => void;
  onSendPastedScl: (text: string) => void;
  onConfirmReceipt: () => void;
}

/** 事件类别 → 图例桩色（母题小方点） */
const EVENT_JOINT: Record<string, string> = {
  receipt: "var(--field-sand)",
  contract: "var(--ink)",
  views: "var(--field-sage)",
  validation: "var(--ok)",
  freeze: "var(--accent)",
  delivery: "var(--accent)",
  edit: "var(--ink-3)",
  text: "var(--ink-3)",
};

const ACCEPT_ATTR = ".pdf,.xlsx,.xlsm,.csv,.scl,.txt,.db";

const SUGGESTIONS: string[] = [
  "怎么开始？",
  "视觉引导与KUKA机器人上下料涂胶打磨工位：上位机PC下发配方，KUKA执行取料、涂胶、打磨与下料步序，气缸夹紧与真空吸盘配合，急停触发安全中止",
];

function timeLabel(ts: string): string {
  const m = ts.match(/(\d{2}:\d{2}):\d{2}/);
  return m ? m[1] : "";
}

/** patch → 单行结构摘要（diff-first 行） */
function patchRow(patch: Record<string, unknown>): { op: string; label: string } {
  const op = String(patch.op ?? "");
  if (op === "add_edge") {
    const edge = (patch.edge ?? {}) as Record<string, unknown>;
    return { op: "连线", label: `${edge.kind} ${edge.src_id} → ${edge.dst_id}` };
  }
  if (op === "remove_edge") return { op: "删线", label: String(patch.edge_id ?? "") };
  if (op === "redirect_edge")
    return { op: "改向", label: `${patch.edge_id} → ${patch.src_id} ⇒ ${patch.dst_id}` };
  return { op: "置值", label: `${patch.field_path} = ${JSON.stringify(patch.value)}` };
}

const MessageBody: React.FC<{ message: GFChatMessage }> = ({ message }) => {
  if (message.role === "assistant") {
    return <MarkdownBody className="gf-chat-md" content={message.text} />;
  }
  return <span className="gf-chat-bubble__text">{message.text}</span>;
};

export const GreenfieldChatFeed: React.FC<GreenfieldChatFeedProps> = ({
  state,
  busy,
  onSend,
  onSendFiles,
  onSendPastedScl,
  onConfirmReceipt,
}) => {
  const messages = state.messages ?? [];
  const [draft, setDraft] = useState("");
  const [dragging, setDragging] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, busy]);

  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const timer = window.setInterval(() => setElapsed((v) => v + 1), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const lastReceiptIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].kind === "receipt") return i;
    }
    return -1;
  })();
  const lastDeliveryIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].kind === "delivery") return i;
    }
    return -1;
  })();
  const receiptPending =
    !!state.receipt &&
    state.receipt.status === "parsed" &&
    !state.receipt.user_confirmed &&
    !state.has_contract;

  const submit = () => {
    const text = draft.trim();
    if (!text || busy) return;
    onSend(text);
    setDraft("");
  };

  const editPatches = (payload: Record<string, unknown>): Array<Record<string, unknown>> =>
    Array.isArray(payload.patches) ? (payload.patches as Array<Record<string, unknown>>) : [];

  return (
    <div
      className={dragging ? "gf-chat gf-chat--dragging" : "gf-chat"}
      data-ui="greenfield-chat-feed"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const files = Array.from(e.dataTransfer.files ?? []);
        if (files.length > 0 && !busy) onSendFiles(files.slice(0, 5));
      }}
    >
      <div className="gf-chat__head">
        <strong>对话</strong>
        <span className="gf-muted">资料上传 · 工艺描述 · 修改指令，都在这里</span>
      </div>

      <div className="gf-chat-feed" ref={feedRef}>
        {messages.length === 0 && (
          <div className="gf-chat-welcome gf-rise">
            <div className="gf-chat-welcome__title">说一句工艺，或丢一份资料，逻辑图从这里开始。</div>
            <div className="gf-chat-welcome__desc">
              上传旧项目的变量表 / DB 打印 PDF 冻结兼容边界；或直接描述工艺，
              生成首版逻辑图后在画布连线、对话修改。确认之前不会生成任何工程。
            </div>
            <div className="gf-chat-welcome__sugs">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={s}
                  type="button"
                  className={i === 0 ? "gf-chat-sug gf-rise-1" : "gf-chat-sug gf-rise-2"}
                  disabled={busy}
                  onClick={() => onSend(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, idx) => {
          if (message.role === "event") {
            const jointColor = EVENT_JOINT[message.kind] ?? "var(--ink-3)";
            return (
              <React.Fragment key={message.id}>
                <div className="gf-chat-event">
                  <span className="gf-joint" style={{ background: jointColor }} />
                  <span className="gf-chat-event__text">{message.text}</span>
                  <span className="gf-chat-event__ts">{timeLabel(message.ts)}</span>
                </div>

                {message.kind === "receipt" && idx === lastReceiptIdx && receiptPending && (
                  <div className="gf-chat-card gf-chat-card--standalone">
                    <button
                      type="button"
                      className="gf-btn gf-btn--primary gf-btn--xs"
                      disabled={busy}
                      onClick={onConfirmReceipt}
                    >
                      确认解析结果并冻结契约
                    </button>
                    <span className="gf-muted">
                      {state.receipt?.errors?.length
                        ? `${state.receipt.errors.length} 条失败明细见右栏`
                        : "全部条目解析通过"}
                    </span>
                  </div>
                )}
                {message.kind === "delivery" && idx === lastDeliveryIdx && state.delivery_summary && (
                  <div className="gf-chat-card gf-chat-card--standalone">
                    <a
                      className="gf-btn gf-btn--primary gf-btn--xs"
                      href={downloadPackageUrl(state.session_id)}
                      download
                    >
                      下载工程包（{state.delivery_summary.block_count} 块）
                    </a>
                  </div>
                )}
              </React.Fragment>
            );
          }

          const isUser = message.role === "user";
          const patches = isUser ? [] : editPatches(message.payload ?? {});
          return (
            <div
              key={message.id}
              className={isUser ? "gf-chat-row gf-chat-row--user" : "gf-chat-row"}
            >
              <div
                className={
                  message.kind === "edit" && !isUser
                    ? "gf-chat-bubble gf-chat-bubble--pending"
                    : isUser
                      ? "gf-chat-bubble gf-chat-bubble--user"
                      : "gf-chat-bubble"
                }
              >
                {/* diff-first：先读结构，再读叙述 */}
                {patches.length > 0 && (
                  <div className="gf-diff">
                    {patches.map((p, i) => {
                      const row = patchRow(p);
                      return (
                        <div className="gf-diff__row" key={i}>
                          <span className="gf-diff__op">{row.op}</span>
                          <code>{row.label}</code>
                        </div>
                      );
                    })}
                  </div>
                )}
                <MessageBody message={message} />
              </div>
            </div>
          );
        })}

        {busy && (
          <div className="gf-chat-row">
            <div className="gf-chat-bubble gf-chat-bubble--pending">
              <span className="gf-chat-typing">
                正在处理{elapsed > 0 ? `（${elapsed}s）` : ""}
                <span className="gf-chat-dots">
                  <i />
                  <i />
                  <i />
                </span>
              </span>
            </div>
          </div>
        )}
      </div>

      <div className="gf-chat-composer">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length > 0 && !busy) onSendFiles(files.slice(0, 5));
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="gf-btn"
          title="上传资料（PDF / Excel / CSV / SCL，可多选，也可直接拖进对话区）"
          disabled={busy}
          onClick={() => fileInputRef.current?.click()}
        >
          上传资料
        </button>
        <textarea
          className="gf-chat-input"
          rows={2}
          value={draft}
          disabled={busy}
          placeholder="描述工艺，或下达修改指令（如：把首步超时改为 5000ms）；粘贴 DB SCL 自动识别；文件可直接拖入"
          onChange={(e) => setDraft(e.target.value)}
          onPaste={(e) => {
            const text = e.clipboardData.getData("text") ?? "";
            if (text.includes("DATA_BLOCK") && text.length > 80 && !busy) {
              e.preventDefault();
              onSendPastedScl(text);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          type="button"
          className="gf-btn gf-btn--primary"
          disabled={busy || draft.trim().length === 0}
          onClick={submit}
        >
          发送
        </button>
      </div>
    </div>
  );
};
