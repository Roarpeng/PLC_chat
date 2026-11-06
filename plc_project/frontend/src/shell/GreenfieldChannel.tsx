/**
 * 新建工程通道容器（Agent D · 前端批次）：
 * - `project_id` 一等公民：向导第一步生成并落盘，启动时 `ensureProjectId()` 贯穿
 *   会话 / 拓扑 / 资料 / 规格 / 产物；所有相关请求带 `project_id`；
 * - 项目内对话注入「已定拓扑」约束（结果不得与已定拓扑矛盾），复用
 *   `GFSpecMeta.open_questions` 与 `GFInterlock.source == "inferred"` 现成机制；
 * - 初始 loading / 操作 busy / 统一 error（可读中文）/ 变更事件反馈四态齐全；
 * - 差异清单显式确认（D11）、反向保护（D10）、fidelity（N9）、编译诊断（P1-I）
 *   与 F13 只读预览全部接线到 GateBar / Panel。
 *
 * 消息真值 = 后端会话 state.messages；画布手动编辑以系统事件回流对话。
 * 根节点 gf-root[data-stage] 驱动整站纸色随阶段换底。
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import "@fontsource/albert-sans/400.css";
import "@fontsource/albert-sans/500.css";
import "@fontsource/albert-sans/600.css";
import type { Connection } from "@xyflow/react";
import {
  GFRequestError,
  applyCanvasPatch,
  applyLinkPatch,
  beginEdit,
  buildTopologyConstraints,
  confirmDiff,
  confirmReceipt,
  confirmSpec,
  createDraft,
  deliverTia,
  diffWriteBlockers,
  ensureProjectId,
  exportDraft,
  exportMermaid,
  fetchEngineeringSummary,
  fetchSpecDiff,
  fetchState,
  fetchWhitelist,
  fileToUploadItem,
  formatGfError,
  generateProjectPackage,
  importDraft,
  loadLaunchContext,
  loadReferenceFixture,
  loadSessionId,
  revalidate,
  saveSessionId,
  sendChat,
  updateHardware,
  uploadFiles,
  type GFBlocker,
  type GFCanvasOp,
  type GFDraftPayload,
  type GFSpecDiff,
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
  const [projectId, setProjectId] = useState<string>("");
  const [prompt, setPrompt] = useState(initialPrompt);
  const [selectedHwNodeId, setSelectedHwNodeId] = useState<string | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState<string>("");
  const [railOpen, setRailOpen] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionFeedback, setActionFeedback] = useState("");
  const [diff, setDiff] = useState<GFSpecDiff | null>(null);
  const [diffError, setDiffError] = useState("");
  const [diffConfirmed, setDiffConfirmed] = useState(false);
  const [confirmErrorCode, setConfirmErrorCode] = useState("");
  const [confirmErrorMessage, setConfirmErrorMessage] = useState("");

  /** run 内部始终读最新 state，避免闭包捕获旧快照。 */
  const stateRef = useRef<GFState | null>(null);
  stateRef.current = state;

  const refresh = useCallback(
    async (sid: string) => {
      setState(await fetchState(sid, projectId || undefined));
    },
    [projectId],
  );

  /** 统一异步边界：loading / busy / error（中文）/ 变更反馈。 */
  const run = useCallback(
    async (action: (sid: string) => Promise<void>, onCaught?: (err: unknown) => void) => {
      if (!sessionId || busy) return;
      setBusy(true);
      setError("");
      setConfirmErrorCode("");
      setConfirmErrorMessage("");
      try {
        await action(sessionId);
        await refresh(sessionId);
      } catch (caught) {
        setError(formatGfError(caught));
        onCaught?.(caught);
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh, sessionId],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        // project_id：向导第一步已生成并落盘；直接进入（如顶栏按钮）时也保证存在。
        const pid = ensureProjectId();
        setProjectId(pid);
        const ctx = loadLaunchContext();
        const existing = loadSessionId();
        let initial = await fetchState(existing, pid);
        // chat 驱动：不再静默自动建稿；带 initialPrompt 或向导工艺描述的入口走一次对话，
        // 让首版生成也出现在消息流里，并注入已定拓扑约束。
        const seedPrompt = initialPrompt.trim() || ctx?.prompt?.trim() || "";
        if (!initial.has_ir && seedPrompt) {
          initial = (
            await sendChat(initial.session_id, seedPrompt, {
              projectId: pid,
              topologyConstraints: buildTopologyConstraints(initial.ir),
            })
          ).state;
        }
        if (cancelled) return;
        setState(initial);
        setSessionId(initial.session_id);
        saveSessionId(initial.session_id);
        setWhitelist(await fetchWhitelist());
      } catch (caught) {
        if (!cancelled) setError(formatGfError(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialPrompt]);

  /** 拉取带 source_id 的 SpecDiff；404 / 网络错时安全降级，不产生任何写入。 */
  const loadDiff = useCallback(async (pid: string, current: GFState | null) => {
    if (!current) return null;
    const versions = (current.specs ?? []).map((s) => s.spec_version);
    const toVersion = versions.length ? versions[versions.length - 1] : 1;
    const fromVersion =
      versions.length > 1 ? versions[versions.length - 2] : Math.max(0, toVersion - 1);
    try {
      const result = await fetchSpecDiff(pid, fromVersion, toVersion);
      setDiff(result);
      setDiffError("");
      return result;
    } catch (caught) {
      setDiffError(
        `差异清单暂不可用：${formatGfError(caught)}（已安全降级，未产生任何写入）`,
      );
      return null;
    }
  }, []);

  // 冻结后自动计算一次差异（新端点由 Agent A 并行实现，暂时 404 时降级）。
  useEffect(() => {
    if (!projectId || state?.stage !== "FROZEN") return;
    let cancelled = false;
    void loadDiff(projectId, state).then((result) => {
      if (!cancelled && result) setDiff(result);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, state?.stage, state?.specs?.length, loadDiff]);

  const constraints = state ? buildTopologyConstraints(state.ir) : null;
  const constraintNote = constraints
    ? `${constraints.units.length} 工站 / ${constraints.ems.length} 执行单元 / ${constraints.cms.length} 执行件 / ${constraints.edges.length} 设备交互连线 · ${constraints.open_questions.length + constraints.inferred_interlocks.length} 条待确认；对话结果不得与已定拓扑矛盾`
    : "";

  // 本地拉取的 diff 也要参与 D11 门禁（后端 /state 可能暂未返回 spec_diff）。
  const effectiveState = state
    ? { ...state, spec_diff: state.spec_diff ?? diff }
    : null;
  const effectiveDiffConfirmed = diffConfirmed || state?.diff_confirmed === true;
  const writeBlockers: GFBlocker[] = effectiveState
    ? diffWriteBlockers(effectiveState, effectiveDiffConfirmed, state?.reverse_protection ?? null)
    : [];

  const onFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const items = await Promise.all(files.slice(0, 5).map(fileToUploadItem));
    await run(async (sid) => {
      await uploadFiles(sid, items, projectId);
      setActionFeedback("资料上传已提交（DB 编号 / IO 表为可选步骤；未上传也能完成拓扑与逻辑确认，不会虚构地址或 OB 条目）");
    });
  };

  const onConnect = (kind: string, connection: Connection) => {
    void run(async (sid) => {
      await applyLinkPatch(sid, { op: "add_edge", edge: toGfEdge(kind, connection) });
      setActionFeedback("设备交互连线已提交，四视图已同步刷新");
    });
  };

  const onRemoveEdge = (edgeId: string) => {
    void run(async (sid) => {
      await applyLinkPatch(sid, { op: "remove_edge", edge_id: edgeId });
      setActionFeedback("设备交互连线已删除，四视图已同步刷新");
    });
  };

  const onPatchNodes = (ops: GFCanvasOp[]) => {
    if (!projectId) return;
    void run(
      async () => {
        const snapshot = stateRef.current;
        const versions = (snapshot?.specs ?? []).map((s) => s.spec_version);
        const baseSpecVersion = versions.length ? versions[versions.length - 1] : undefined;
        const result = await applyCanvasPatch(projectId, ops, baseSpecVersion);
        if (result.violations?.length) {
          throw new Error(`节点变更校验未通过：${result.violations.map((v) => v.message).join("；")}`);
        }
        setActionFeedback(
          `已提交 ${ops.length} 个节点变更 op（${ops.map((o) => String(o.op)).join("、")}）；原子校验通过，变更事件已入账，四视图已刷新`,
        );
      },
      (err) => setActionFeedback(`节点变更未生效：${formatGfError(err)}（整批回滚，画布不变）`),
    );
  };

  const onRefreshDiff = () => {
    if (!projectId) return;
    void run(async () => {
      const result = await loadDiff(projectId, stateRef.current);
      setActionFeedback(
        result
          ? "差异清单已刷新（带 source_id），请逐条核对后显式勾选确认"
          : "差异清单刷新失败，已安全降级，未产生任何写入",
      );
    });
  };

  const onConfirmDiff = (confirmed: boolean) => {
    if (!projectId) return;
    void run(
      async () => {
        const versions = (stateRef.current?.specs ?? []).map((s) => s.spec_version);
        const toVersion = versions.length ? versions[versions.length - 1] : 1;
        const fromVersion =
          versions.length > 1 ? versions[versions.length - 2] : Math.max(0, toVersion - 1);
        const diffId = diff?.diff_id ?? `diff-${fromVersion}-${toVersion}`;
        await confirmDiff(projectId, diffId, confirmed);
        setDiffConfirmed(confirmed);
        setActionFeedback(
          confirmed
            ? "差异清单已显式确认（D11）：后续写入解锁；确认前零副作用计数器恒 0"
            : "已撤销差异清单确认：后续写入重新锁定",
        );
      },
      (err) => setActionFeedback(`差异确认失败：${formatGfError(err)}`),
    );
  };

  if (!state) {
    return (
      <div
        className="gf-root gf-channel gf-channel--loading"
        data-ui="greenfield-channel"
      >
        {error
          ? `通道不可用：${error}`
          : loading
            ? "正在准备新建工程对话工作台…（正在连接网关，请稍候）"
            : "正在准备新建工程对话工作台…"}
      </div>
    );
  }

  const compileDiagnostics =
    state.compile_diagnostics ?? state.delivery_summary?.compile_diagnostics ?? null;
  const fidelity = state.fidelity ?? state.delivery_summary?.fidelity ?? null;
  const reverseProtection = state.reverse_protection ?? null;
  const sclSources = state.delivery_summary?.scl_sources ?? null;
  const pendingRealMachine = state.pending_real_machine !== false;

  return (
    <div className="gf-root gf-channel" data-stage={state.stage} data-ui="greenfield-channel">
      <GreenfieldGateBar
        state={state}
        onBack={onBack}
        projectId={projectId}
        confirmErrorCode={confirmErrorCode}
        confirmErrorMessage={confirmErrorMessage}
        writeBlockers={writeBlockers}
        pendingRealMachine={pendingRealMachine}
        diffConfirmed={effectiveDiffConfirmed}
        onLoadReference={() => {
          void run(async (sid) => {
            await loadReferenceFixture(sid, prompt);
          });
        }}
        onShowSummary={() => fetchEngineeringSummary(sessionId)}
        onConfirm={() => {
          void run(
            async (sid) => {
              const result = await confirmSpec(sid, true, projectId);
              downloadText(`spec-${result.spec.spec_version ?? 1}.md`, result.markdown);
              setActionFeedback("设备逻辑已确认，还原契约已锁定（规格冻结）");
            },
            (err) => {
              const gfErr = err instanceof GFRequestError ? err : null;
              setConfirmErrorCode(gfErr?.code ?? "");
              setConfirmErrorMessage(gfErr?.message ?? "");
            },
          );
        }}
        onGenerateProject={() => {
          void run(async (sid) => {
            if (writeBlockers.length > 0) {
              throw new Error(writeBlockers.map((b) => b.reason).join("；"));
            }
            await generateProjectPackage(sid, projectId);
            setActionFeedback("已生成工程包；交付结果区展示结构化编译诊断（这不代表编译零错误）");
          });
        }}
        onDeliverTia={(mode) => {
          void run(async (sid) => {
            if (writeBlockers.length > 0) {
              throw new Error(writeBlockers.map((b) => b.reason).join("；"));
            }
            await deliverTia(sid, mode, projectId);
            setActionFeedback("真机交付已发起；TIA 不可用时会诚实降级为人工导入指引");
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
          projectId={projectId}
          constraintNote={constraintNote}
          onSend={(text) =>
            void run(async (sid) => {
              await sendChat(sid, text, {
                projectId,
                topologyConstraints: buildTopologyConstraints(stateRef.current?.ir ?? null),
              });
            })
          }
          onSendFiles={(files) => void onFiles(files)}
          onSendPastedScl={(sclText) =>
            void run(async (sid) => {
              await uploadFiles(sid, [{ filename: "pasted.scl", text: sclText, kind: "db" }], projectId);
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
            projectId={projectId}
            selectedHwNodeId={selectedHwNodeId}
            selectedTargetId={selectedTargetId}
            diff={state.spec_diff ?? diff}
            fidelity={fidelity}
            reverseProtection={reverseProtection}
            compileDiagnostics={compileDiagnostics}
            diffConfirmed={effectiveDiffConfirmed}
            onConfirmDiff={onConfirmDiff}
            onRefreshDiff={onRefreshDiff}
            onPatchNodes={onPatchNodes}
            actionFeedback={actionFeedback}
            pendingRealMachine={pendingRealMachine}
            sclSources={sclSources}
            onSelectHwNode={setSelectedHwNodeId}
            onSelectTarget={setSelectedTargetId}
            onPromptChange={setPrompt}
            onGenerateDraft={() =>
              void run(async (sid) => {
                await createDraft(sid, prompt, projectId);
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
            onPatchNodes={onPatchNodes}
            actionFeedback={actionFeedback}
            onUploadFiles={(files) => void onFiles(Array.from(files))}
            onUploadPastedScl={(sclText) =>
              void run(async (sid) => {
                await uploadFiles(sid, [{ filename: "pasted.scl", text: sclText, kind: "db" }], projectId);
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
      {diffError && (
        <div className="gf-warning" role="status">
          {diffError}
        </div>
      )}
      {loading && <div className="gf-busy">正在加载通道…</div>}
      {busy && <div className="gf-busy">处理中…</div>}
    </div>
  );
};
