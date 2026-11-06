/**
 * 新建工程通道容器（GreenfieldChannel · chat 驱动 + one-motif 设计系统）：
 * - 左栏：对话流（唯一入口）——资料上传 / 工艺描述 / 修改指令都在对话完成
 * - 中区：硬件拓扑（逻辑级占位，可收起/可撤销）+ 三视图画布（React Flow 拖拽 + Mermaid 投影 + 源码抽屉）
 * - 右栏：变量绑定工作台（可折叠；外部锁定 IO/DB + 内部生成变量 + 绑定步序/设备）
 * 消息真值 = 后端会话 state.messages；画布手动编辑以系统事件回流对话（chat ↔ 画布双向联动）。
 * 根节点 gf-root[data-stage] 驱动整站纸色随阶段换底（慢速交叉淡变）。
 */
import React, { useCallback, useEffect, useState } from "react";
import "@fontsource/albert-sans/400.css";
import "@fontsource/albert-sans/500.css";
import "@fontsource/albert-sans/600.css";
import type { Connection } from "@xyflow/react";
import {
  applyLinkPatch,
  beginEdit,
  confirmReceipt,
  confirmSpec,
  createDraft,
  deliverTia,
  exportDraft,
  exportMermaid,
  fetchEngineeringSummary,
  fetchState,
  fetchWhitelist,
  fileToUploadItem,
  generateProjectPackage,
  importDraft,
  loadReferenceFixture,
  loadSessionId,
  revalidate,
  saveSessionId,
  sendChat,
  updateHardware,
  uploadFiles,
  type GFDraftPayload,
  type GFState,
  type GFWhitelist,
} from "../state/greenfield";
import { GreenfieldChatFeed } from "./GreenfieldChatFeed";
import { GreenfieldGateBar } from "./GreenfieldGateBar";
import { GreenfieldLinkPanel } from "./GreenfieldLinkPanel";
import { GreenfieldPanel, toGfEdge } from "./GreenfieldPanel";
import "./greenfield.css";

export interface GreenfieldChannelProps {
  onBack: () => void;
  initialPrompt?: string;
}

function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export const GreenfieldChannel: React.FC<GreenfieldChannelProps> = ({
  onBack,
  initialPrompt = "",
}) => {
  const [state, setState] = useState<GFState | null>(null);
  const [whitelist, setWhitelist] = useState<GFWhitelist | null>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [prompt, setPrompt] = useState(initialPrompt);
  const [selectedHwNodeId, setSelectedHwNodeId] = useState<string | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState<string>("");
  const [railOpen, setRailOpen] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
        let initial = await fetchState(existing);
        // chat 驱动：不再静默自动建稿；带 initialPrompt 的入口（引导页输入）走一次对话，
        // 让首版生成也出现在消息流里。
        if (!initial.has_ir && initialPrompt.trim()) {
          initial = (await sendChat(initial.session_id, initialPrompt)).state;
        }
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
  }, [initialPrompt]);

  const onFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const items = await Promise.all(files.slice(0, 5).map(fileToUploadItem));
    await run(async (sid) => {
      await uploadFiles(sid, items);
    });
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
      <div
        className="gf-root gf-channel gf-channel--loading"
        data-ui="greenfield-channel"
      >
        {error ? `通道不可用：${error}` : "正在准备新建工程对话工作台…"}
      </div>
    );
  }

  return (
    <div className="gf-root gf-channel" data-stage={state.stage} data-ui="greenfield-channel">
      <GreenfieldGateBar
        state={state}
        onBack={onBack}
        onLoadReference={() => {
          void run(async (sid) => {
            await loadReferenceFixture(sid, prompt);
          });
        }}
        onShowSummary={() => fetchEngineeringSummary(sessionId)}
        onConfirm={() => {
          void run(async (sid) => {
            const result = await confirmSpec(sid, true);
            downloadText(`spec-${result.spec.spec_version ?? 1}.md`, result.markdown);
          });
        }}
        onGenerateProject={() => {
          void run(async (sid) => {
            await generateProjectPackage(sid);
          });
        }}
        onDeliverTia={(mode) => {
          void run(async (sid) => {
            await deliverTia(sid, mode);
          });
        }}
        onBeginEdit={() =>
          void run(async (sid) => {
            await beginEdit(sid);
          })
        }
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

      <div
        className={
          railOpen ? "gf-body gf-body--chat" : "gf-body gf-body--chat gf-body--chat--railoff"
        }
      >
        <GreenfieldChatFeed
          state={state}
          busy={busy}
          onSend={(text) =>
            void run(async (sid) => {
              await sendChat(sid, text);
            })
          }
          onSendFiles={(files) => void onFiles(files)}
          onSendPastedScl={(sclText) =>
            void run(async (sid) => {
              await uploadFiles(sid, [{ filename: "pasted.scl", text: sclText, kind: "db" }]);
            })
          }
          onConfirmReceipt={() =>
            void run(async (sid) => {
              await confirmReceipt(sid);
            })
          }
        />

        <div className="gf-center-wrap">
          <button
            type="button"
            className="gf-rail-toggle"
            onClick={() => setRailOpen((v) => !v)}
            title={railOpen ? "收起右侧变量工作台" : "展开右侧变量工作台"}
          >
            {railOpen ? "收起变量台" : "变量台"}
          </button>
          <GreenfieldPanel
            views={state.views}
            ir={state.ir}
            hardware={state.hardware ?? null}
            legalKinds={whitelist?.edge_kinds ?? []}
            prompt={prompt}
            busy={busy}
            selectedHwNodeId={selectedHwNodeId}
            selectedTargetId={selectedTargetId}
            onSelectHwNode={setSelectedHwNodeId}
            onSelectTarget={setSelectedTargetId}
            onPromptChange={setPrompt}
            onGenerateDraft={() =>
              void run(async (sid) => {
                await createDraft(sid, prompt);
              })
            }
            onMountCm={(cmId, hwNodeId) =>
              void run(async (sid) => {
                await updateHardware(sid, { op: "mount_cm", cm_id: cmId, hw_node_id: hwNodeId });
              })
            }
            onUnmountCm={(cmId) =>
              void run(async (sid) => {
                await updateHardware(sid, { op: "unmount_cm", cm_id: cmId });
              })
            }
            onRemoveHwNode={(hwNodeId) =>
              void run(async (sid) => {
                await updateHardware(sid, { op: "remove_hw_node", hw_node_id: hwNodeId });
              })
            }
            onResetTopology={() =>
              void run(async (sid) => {
                await updateHardware(sid, { op: "reset_topology" });
              })
            }
            onEditStepField={(_stepId, fieldPath, value) =>
              void run(async (sid) => {
                await applyLinkPatch(sid, {
                  op: "set_ir_only_field",
                  field_path: fieldPath,
                  value,
                });
              })
            }
            onConnect={onConnect}
            onRemoveEdge={onRemoveEdge}
          />
        </div>

        {railOpen && (
          <GreenfieldLinkPanel
            whitelist={whitelist}
            report={state.report}
            state={state}
            busy={busy}
            selectedHwNodeId={selectedHwNodeId}
            selectedTargetId={selectedTargetId}
            onSelectTarget={setSelectedTargetId}
            onUploadFiles={(files) => void onFiles(Array.from(files))}
            onUploadPastedScl={(sclText) =>
              void run(async (sid) => {
                await uploadFiles(sid, [{ filename: "pasted.scl", text: sclText, kind: "db" }]);
              })
            }
            onConfirmReceipt={() =>
              void run(async (sid) => {
                await confirmReceipt(sid);
              })
            }
            onBindVar={(varKey, targetId, role) =>
              void run(async (sid) => {
                await updateHardware(sid, {
                  op: "bind_var",
                  var_key: varKey,
                  target_id: targetId,
                  role,
                });
              })
            }
            onUnbindVar={(varKey, targetId) =>
              void run(async (sid) => {
                await updateHardware(sid, {
                  op: "unbind_var",
                  var_key: varKey,
                  target_id: targetId || "",
                });
              })
            }
            onValidate={() =>
              void run(async (sid) => {
                await revalidate(sid);
              })
            }
          />
        )}
      </div>

      {error && (
        <div className="gf-error" role="alert">
          {error}
        </div>
      )}
      {busy && <div className="gf-busy">处理中…</div>}
    </div>
  );
};
