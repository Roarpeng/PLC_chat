/** Greenfield 通道容器：对话上传 / 三视图连线 / 校验 / 确认门禁（T04）。 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import type { Connection } from "@xyflow/react";
import {
  applyLinkPatch,
  beginEdit,
  confirmReceipt,
  confirmSpec,
  createDraft,
  exportDraft,
  exportMermaid,
  fetchEngineeringSummary,
  fetchState,
  fetchWhitelist,
  fileToUploadItem,
  importDraft,
  loadSessionId,
  revalidate,
  saveSessionId,
  uploadFiles,
  type GFDraftPayload,
  type GFState,
  type GFWhitelist,
} from "../state/greenfield";
import { GreenfieldGateBar } from "./GreenfieldGateBar";
import { GreenfieldLinkPanel } from "./GreenfieldLinkPanel";
import { GreenfieldPanel, toGfEdge } from "./GreenfieldPanel";
import "./greenfield.css";

export interface GreenfieldChannelProps {
  onBack: () => void;
}

function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export const GreenfieldChannel: React.FC<GreenfieldChannelProps> = ({ onBack }) => {
  const [state, setState] = useState<GFState | null>(null);
  const [whitelist, setWhitelist] = useState<GFWhitelist | null>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [pastedDb, setPastedDb] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async (sid: string) => {
    setState(await fetchState(sid));
  }, []);

  const run = useCallback(
    async (action: (sid: string) => Promise<void>) => {
      if (!sessionId || busy) return;
      setBusy(true);
      setError("");
      try {
        await action(sessionId);
        await refresh(sessionId);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh, sessionId],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const existing = loadSessionId();
        const initial = await fetchState(existing);
        if (cancelled) return;
        setState(initial);
        setSessionId(initial.session_id);
        saveSessionId(initial.session_id);
        setWhitelist(await fetchWhitelist());
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : String(caught));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const items = await Promise.all(Array.from(files).slice(0, 5).map(fileToUploadItem));
    await run(async (sid) => {
      await uploadFiles(sid, items);
    });
    if (fileRef.current) fileRef.current.value = "";
  };

  const onConnect = (kind: string, connection: Connection) => {
    void run(async (sid) => {
      await applyLinkPatch(sid, { op: "add_edge", edge: toGfEdge(kind, connection) });
    });
  };

  const onRemoveEdge = (edgeId: string) => {
    void run(async (sid) => {
      await applyLinkPatch(sid, { op: "remove_edge", edge_id: edgeId });
    });
  };

  if (!state) {
    return (
      <div className="gf-channel gf-channel--loading" data-ui="greenfield-channel">
        {error ? `通道不可用：${error}` : "正在准备规格工作台…"}
      </div>
    );
  }

  return (
    <div className="gf-channel" data-ui="greenfield-channel">
      <GreenfieldGateBar
        state={state}
        onBack={onBack}
        onShowSummary={() => fetchEngineeringSummary(sessionId)}
        onConfirm={() => {
          void run(async (sid) => {
            const result = await confirmSpec(sid, true);
            downloadText(`spec-${result.spec.spec_version ?? 1}.md`, result.markdown);
          });
        }}
        onBeginEdit={() => void run(async (sid) => { await beginEdit(sid); })}
        onExportMermaid={() => {
          void run(async (sid) => {
            const result = await exportMermaid(sid);
            downloadText("结构图.md", result.markdown);
          });
        }}
        onExportDraft={() => {
          void run(async (sid) => {
            const result = await exportDraft(sid);
            downloadText("草稿.json", JSON.stringify(result.payload, null, 2));
          });
        }}
        onImportDraft={(payload) => {
          void run(async (sid) => {
            await importDraft(sid, payload as GFDraftPayload);
          });
        }}
      />

      <div className="gf-body">
        <section className="gf-chat" data-ui="greenfield-chat">
          <div className="gf-side-title">描述工艺</div>
          <textarea
            className="gf-textarea"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="例如：一个装配工位，先上料再压装；压装超时或急停时中止"
          />
          <button
            type="button"
            className="gf-btn gf-btn--primary"
            disabled={busy}
            onClick={() => void run(async (sid) => { await createDraft(sid, prompt); })}
          >
            生成首版结构图
          </button>

          <div className="gf-side-title">上传兼容资料</div>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".xlsx,.xlsm,.csv,.scl,.txt,.db"
            onChange={(event) => void onFiles(event.target.files)}
          />
          <div className="gf-muted">IO 表（xlsx / csv）与 DB 源码（scl / txt）可一次选多个</div>

          <textarea
            className="gf-textarea gf-textarea--small"
            value={pastedDb}
            onChange={(event) => setPastedDb(event.target.value)}
            placeholder="也可直接粘贴 DB 的 SCL 文本"
          />
          <button
            type="button"
            className="gf-btn gf-btn--ghost"
            disabled={busy || !pastedDb.trim()}
            onClick={() => void run(async (sid) => {
              await uploadFiles(sid, [{ filename: "pasted.scl", text: pastedDb, kind: "db" }]);
              setPastedDb("");
            })}
          >
            解析粘贴内容
          </button>

          {state.receipt && (
            <div className="gf-receipt">
              <div className="gf-muted">
                回执 {state.receipt.receipt_id} · {state.receipt.status} ·
                接收 {state.receipt.items_accepted}/{state.receipt.items_total}
              </div>
              {!state.receipt.user_confirmed && (
                <button
                  type="button"
                  className="gf-btn gf-btn--ghost"
                  disabled={state.receipt.status !== "parsed" || busy}
                  onClick={() => void run(async (sid) => { await confirmReceipt(sid); })}
                >
                  确认解析结果并锁定资料
                </button>
              )}
            </div>
          )}

          <div className="gf-muted gf-chat__note">
            兼容资料只读：结构、偏移与绝对地址不可改动，程序只通过映射边界访问。
          </div>
        </section>

        <GreenfieldPanel
          views={state.views}
          ir={state.ir}
          legalKinds={whitelist?.edge_kinds ?? []}
          onConnect={onConnect}
          onRemoveEdge={onRemoveEdge}
        />

        <GreenfieldLinkPanel
          whitelist={whitelist}
          report={state.report}
          state={state}
          onValidate={() => void run(async (sid) => { await revalidate(sid); })}
        />
      </div>

      {error && <div className="gf-error" role="alert">{error}</div>}
      {busy && <div className="gf-busy">处理中…</div>}
    </div>
  );
};
