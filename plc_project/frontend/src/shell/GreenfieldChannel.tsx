/**
 * 新建工程通道容器 · 唯一后端编排者。
 *
 * 保留全部既有 state 字段与 run / runAction / refresh / loadDiff / onConnect /
 * onRemoveEdge / onPatchNodes / onConfirmDiff / onToggleDiffItem 等回调；
 * render tree 换成 4 步主链 <GreenfieldWizard/>，契约信息移入默认折叠的工程视角。
 *
 * ★ 合法主链 API 序列（严禁变形）：
 *   fetchState → fetchWhitelist
 *   → [步 1 用户点主按钮] sendChat
 *   → [步 2] applyLinkPatch(add_edge / remove_edge)
 *   → [步 3 进入时] fetchEngineeringSummary（★隐藏硬门禁，置 engineering_summary_shown）
 *   → [步 3 主按钮] confirmSpec(explicit=true) → generateProjectPackage → refresh → GO(4)
 *   → [步 4] downloadPackageUrl
 * 严禁跳过 /confirm 直调 /generate；严禁伪造 frozen / delivery / 任何 mock 数据。
 */
import React, { useCallback, useEffect, useReducer, useRef, useState } from "react";
import "@fontsource/albert-sans/400.css";
import "@fontsource/albert-sans/500.css";
import "@fontsource/albert-sans/600.css";
import type { Connection } from "@xyflow/react";
import {
  GFRequestError,
  actionAvailability,
  applyCanvasPatch,
  applyLinkPatch,
  beginEdit,
  buildTopologyConstraints,
  canConfirm,
  confirmBlockers,
  confirmDiff,
  confirmReceipt,
  confirmSpec,
  createDraft,
  deliverTia,
  diffChecklistComplete,
  diffExplicitlyConfirmed,
  diffWriteBlockers,
  downloadPackageUrl,
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
  mapConfirmError,
  pendingRealMachineLabel,
  revalidate,
  runActionA,
  runActionB,
  runActionC,
  saveSessionId,
  sendChat,
  updateHardware,
  uploadFiles,
  type GFActionCompileDiagnostics,
  type GFActionKind,
  type GFActionMachine,
  type GFActionResult,
  type GFBlocker,
  type GFCanvasOp,
  type GFCompileDiagnostics,
  type GFDraftPayload,
  type GFFidelityStatus,
  type GFReverseProtection,
  type GFSpecDiff,
  type GFState,
  type GFWhitelist,
} from "../state/greenfield";
import { GreenfieldLinkPanel } from "./GreenfieldLinkPanel";
import { GreenfieldWizard } from "./GreenfieldWizard";
import { toGfEdge } from "./GreenfieldPanel";
import type { EngineeringActions, EngineeringViewData } from "./EngineeringDrawer";
import {
  INITIAL_WIZARD_STATE,
  resetWizardLocalState,
  wizardReducer,
} from "./steps/stepMachine";
import "./greenfield.css";
import "./steps/steps.css";

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
  const [engineeringSummary, setEngineeringSummary] = useState<Record<string, unknown> | null>(null);

  /* —— F20 三动作状态（A 导出 / B 首次写入 / C 增量回写）—— */
  const [actionResults, setActionResults] = useState<
    Partial<Record<GFActionKind, GFActionResult | null>>
  >({});
  const [actionLoading, setActionLoading] = useState<GFActionKind | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionErrorCode, setActionErrorCode] = useState("");
  /** 差异清单逐项勾选（D11：显式确认前必须逐项勾齐）。 */
  const [diffChecked, setDiffChecked] = useState<Record<string, boolean>>({});
  const [actionARun, setActionARun] = useState(false);
  const [actionAFidelityOk, setActionAFidelityOk] = useState<boolean | null>(null);
  const [actionBDone, setActionBDone] = useState(false);
  /** Action A 的真实 fidelity 报告，透传给 B/C（不虚构）。 */
  const [actionFidelityReport, setActionFidelityReport] = useState<Record<string, unknown> | null>(null);

  /** 4 步主链状态机：唯一存放位置，不写 localStorage。 */
  const [wizard, dispatch] = useReducer(wizardReducer, INITIAL_WIZARD_STATE);

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

  /** 三动作统一异步边界：loading / error（可读中文）/ 结果 / 反馈四态齐全。 */
  const runAction = useCallback(
    async (kind: GFActionKind, call: (sid: string) => Promise<GFActionResult>) => {
      if (!sessionId || busy) return;
      setActionLoading(kind);
      setActionError("");
      setActionErrorCode("");
      setError("");
      try {
        const result = await call(sessionId);
        setActionResults((prev) => ({ ...prev, [kind]: result }));
        if (kind === "A") {
          setActionARun(true);
          setActionAFidelityOk(result.fidelity_ok === true);
          setActionFidelityReport(
            result.fidelity_report
              ? (result.fidelity_report as unknown as Record<string, unknown>)
              : null,
          );
        }
        if (kind === "B" && result.ok && !result.blocked) setActionBDone(true);
        setActionFeedback(
          kind === "A"
            ? `Action A 已导出工程包：还原度校验 fidelity_ok=${String(result.fidelity_ok)}（不写 TIA，不等于编译通过）`
            : kind === "B"
              ? `Action B 首次写入编排返回：compile_ok=${String(result.compile_ok)}（真机 L2 仍为 pending_real_machine）`
              : `Action C 增量回写返回：mode=${result.mode}；真机结论 pending_real_machine`,
        );
        await refresh(sessionId);
      } catch (caught) {
        const gfErr = caught instanceof GFRequestError ? caught : null;
        setActionError(formatGfError(caught));
        setActionErrorCode(gfErr?.code ?? "");
        setActionFeedback(
          `Action ${kind} 被拒绝：${formatGfError(caught)}（服务端 fail-closed，未产生越权写入）`,
        );
      } finally {
        setActionLoading(null);
      }
    },
    [busy, refresh, sessionId],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const pid = ensureProjectId();
        setProjectId(pid);
        const ctx = loadLaunchContext();
        const existing = loadSessionId();
        const initial = await fetchState(existing, pid);
        if (cancelled) return;
        // 只预填步 1 唯一输入框，等用户显式点主按钮才发 /chat（不再静默生成）。
        const seedPrompt = initialPrompt.trim() || ctx?.prompt?.trim() || "";
        setPrompt(seedPrompt);
        dispatch({ type: "SET_PROMPT", value: seedPrompt });
        setState(initial);
        setSessionId(initial.session_id);
        saveSessionId(initial.session_id);
        const wl = await fetchWhitelist();
        if (cancelled) return;
        setWhitelist(wl);
        if (wl.edge_kinds.length > 0) {
          dispatch({ type: "SET_EDGE_KIND", value: wl.edge_kinds[0] });
        }
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

  // 冻结后自动计算一次差异（新端点 404 时降级）。
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
  const effectiveDiff: GFSpecDiff | null = state?.spec_diff ?? diff ?? null;
  const effectiveDiffConfirmed = diffConfirmed || state?.diff_confirmed === true;
  /** D11：逐项勾选齐全 ∧ 显式确认标志，才算显式确认（确认前零副作用）。 */
  const checklistComplete = diffChecklistComplete(effectiveDiff, diffChecked);
  const explicitConfirmed = diffExplicitlyConfirmed(
    effectiveDiff,
    diffChecked,
    effectiveDiffConfirmed,
  );
  const writeBlockers: GFBlocker[] = effectiveState
    ? diffWriteBlockers(effectiveState, explicitConfirmed, state?.reverse_protection ?? null)
    : [];

  /* —— 三动作状态机（对齐服务端 §3.2 / D11 / D10 / UC-17）—— */
  const latestActionReverse =
    actionResults.C?.reverse_protection ?? actionResults.B?.reverse_protection ?? null;
  const effectiveReverse = state?.reverse_protection ?? latestActionReverse ?? null;
  const reverseBlocked =
    !!effectiveReverse &&
    (effectiveReverse.allowed === false || (effectiveReverse.tia_side_drift ?? 0) > 0);
  const machine: GFActionMachine = {
    stage: state?.stage ?? "DRAFT",
    actionARun,
    actionAFidelityOk,
    actionBDone,
    diffConfirmed: explicitConfirmed,
    diffChecklistComplete: checklistComplete,
    reverseBlocked,
  };
  const availability = actionAvailability(machine);
  const actionCompileDiagnostics: GFActionCompileDiagnostics | null =
    actionResults.B?.compile_diagnostics ?? actionResults.C?.compile_diagnostics ?? null;

  const onFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const items = await Promise.all(files.slice(0, 5).map(fileToUploadItem));
    await run(async (sid) => {
      await uploadFiles(sid, items, projectId);
      setActionFeedback("资料上传已提交（DB 编号 / IO 表为可选步骤；未上传也能完成拓扑与逻辑确认，不会虚构地址或 OB 条目）");
    });
  };

  /** 步 2 新增连线：白名单由后端裁定；失败给中文提示且画布保持 /state 原样。 */
  const onConnect = (kind: string, connection: Connection) => {
    dispatch({ type: "SET_LINK_ERROR", value: "" });
    void run(
      async (sid) => {
        await applyLinkPatch(sid, { op: "add_edge", edge: toGfEdge(kind, connection) });
        setActionFeedback("设备交互连线已提交，四视图已同步刷新");
      },
      (err) => dispatch({ type: "SET_LINK_ERROR", value: formatGfError(err) }),
    );
  };

  /** 步 2 删除连线：禁止本地乐观增删，永远以 refresh() 回读为准。 */
  const onRemoveEdge = (edgeId: string) => {
    dispatch({ type: "SET_LINK_ERROR", value: "" });
    void run(
      async (sid) => {
        await applyLinkPatch(sid, { op: "remove_edge", edge_id: edgeId });
        setActionFeedback("设备交互连线已删除，四视图已同步刷新");
      },
      (err) => dispatch({ type: "SET_LINK_ERROR", value: formatGfError(err) }),
    );
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
      // 差异清单变了，逐项勾选与显式确认一律重置（D11 fail-closed，需重新核对）。
      setDiffChecked({});
      setDiffConfirmed(false);
      setActionFeedback(
        result
          ? "差异清单已刷新（带 source_id），请逐条勾选后显式确认（D11）"
          : "差异清单刷新失败，已安全降级，未产生任何写入",
      );
    });
  };

  /** D11：任一勾选变化都撤销显式确认，要求重新核对并再次显式确认。 */
  const onToggleDiffItem = (key: string, checked: boolean) => {
    setDiffChecked((prev) => ({ ...prev, [key]: checked }));
    setDiffConfirmed(false);
  };

  const onConfirmDiff = (confirmed: boolean) => {
    if (!projectId) return;
    if (confirmed && !checklistComplete) {
      setActionFeedback("请先逐项勾选全部变更 / 新增 / 移除项后再显式确认（D11：确认前零副作用）");
      return;
    }
    void run(
      async () => {
        const versions = (stateRef.current?.specs ?? []).map((s) => s.spec_version);
        const toVersion = versions.length ? versions[versions.length - 1] : 1;
        const fromVersion =
          versions.length > 1 ? versions[versions.length - 2] : Math.max(0, toVersion - 1);
        const diffId = diff?.diff_id ?? `diff-${fromVersion}-${toVersion}`;
        await confirmDiff(projectId, diffId, confirmed && checklistComplete);
        setDiffConfirmed(confirmed && checklistComplete);
        setActionFeedback(
          confirmed
            ? "差异清单已逐项核对并显式确认（D11）：后续写入解锁；确认前零副作用计数器恒 0"
            : "已撤销差异清单确认：后续写入重新锁定",
        );
      },
      (err) => setActionFeedback(`差异确认失败：${formatGfError(err)}`),
    );
  };

  /* ======================================================================
   * 4 步主链编排（§4.2 唯一合法序列）
   * ==================================================================== */

  /** 步 1 主按钮：显式 sendChat → refresh；不自动前进，留下草图与「下一步：连线」。 */
  const onSubmitDescribe = useCallback(() => {
    const text = wizard.data.prompt.trim();
    if (!text || !sessionId || busy) return;
    if (stateRef.current?.has_ir) return; // 已有草图时按钮已切换为纯导航
    void (async () => {
      setBusy(true);
      setError("");
      try {
        await sendChat(sessionId, text, {
          projectId: projectId || undefined,
          topologyConstraints: buildTopologyConstraints(null),
        });
        await refresh(sessionId);
        setPrompt(text);
        dispatch({ type: "SET_SUBMITTED_PROMPT", value: text });
        dispatch({ type: "MARK_COMPLETE", step: 1 });
        setActionFeedback("工艺描述已解析，设备与步序草图已生成");
      } catch (caught) {
        setError(formatGfError(caught));
      } finally {
        setBusy(false);
      }
    })();
  }, [busy, projectId, refresh, sessionId, wizard.data.prompt]);

  /**
   * 步 3 进入时：★必须先 fetchEngineeringSummary 置工程摘要已展示标志，
   * 否则后端确认门禁会拒绝本次确认。
   */
  const onEnterConfirm = useCallback(() => {
    if (!sessionId) return;
    void (async () => {
      setBusy(true);
      setError("");
      try {
        const summary = await fetchEngineeringSummary(sessionId);
        setEngineeringSummary(summary);
        await refresh(sessionId);
      } catch (caught) {
        const note = formatGfError(caught);
        setError(note);
        dispatch({ type: "SET_CONFIRM_NOTE", value: note });
      } finally {
        setBusy(false);
      }
    })();
  }, [refresh, sessionId]);

  /** 步 3 主按钮：严格 confirmSpec → generateProjectPackage → refresh → GO(4)。 */
  const onConfirmAndGenerate = useCallback(() => {
    if (!sessionId || busy) return;
    void (async () => {
      setBusy(true);
      setError("");
      setConfirmErrorCode("");
      setConfirmErrorMessage("");
      dispatch({ type: "SET_CONFIRM_NOTE", value: "" });
      try {
        await confirmSpec(sessionId, true, projectId || undefined);
        await generateProjectPackage(sessionId, projectId || undefined);
        await refresh(sessionId);
        dispatch({ type: "MARK_COMPLETE", step: 3 });
        dispatch({ type: "SET_DELIVERY_READY", value: true });
        dispatch({ type: "GO", step: 4 });
        setActionFeedback("工程包已生成，可直接下载");
      } catch (caught) {
        // 停在步 3：不重试、不绕过、不 GO(4)、不伪造成功态。
        const gfErr = caught instanceof GFRequestError ? caught : null;
        const code = gfErr?.code ?? "";
        const message = gfErr?.message ?? formatGfError(caught);
        setConfirmErrorCode(code);
        setConfirmErrorMessage(message);
        const note = mapConfirmError(code, message);
        setError(note);
        dispatch({ type: "SET_CONFIRM_NOTE", value: note });
      } finally {
        setBusy(false);
      }
    })();
  }, [busy, projectId, refresh, sessionId]);

  /** 步 4「重新调整」：FROZEN 不允许 link，必须先 beginEdit。 */
  const onBeginEditAndGoLink = useCallback(() => {
    if (!sessionId) return;
    void (async () => {
      setBusy(true);
      setError("");
      try {
        await beginEdit(sessionId);
        await refresh(sessionId);
        dispatch({ type: "REENTER_EDIT" });
      } catch (caught) {
        setError(formatGfError(caught));
      } finally {
        setBusy(false);
      }
    })();
  }, [refresh, sessionId]);

  /** 步 4「开始新工程」：清本地键 → fetchState 取真实新会话 → RESET。 */
  const onRestart = useCallback(() => {
    void (async () => {
      setBusy(true);
      setError("");
      try {
        resetWizardLocalState();
        const pid = ensureProjectId();
        setProjectId(pid);
        const fresh = await fetchState(null, pid);
        setState(fresh);
        setSessionId(fresh.session_id);
        saveSessionId(fresh.session_id);
        setWhitelist(await fetchWhitelist());
        setPrompt("");
        setSelectedHwNodeId(null);
        setSelectedTargetId("");
        setDiff(null);
        setDiffError("");
        setDiffConfirmed(false);
        setDiffChecked({});
        setActionResults({});
        setActionError("");
        setActionErrorCode("");
        setActionFeedback("");
        setActionLoading(null);
        setConfirmErrorCode("");
        setConfirmErrorMessage("");
        setEngineeringSummary(null);
        setActionARun(false);
        setActionAFidelityOk(null);
        setActionBDone(false);
        setActionFidelityReport(null);
        dispatch({ type: "RESET" });
      } catch (caught) {
        setError(formatGfError(caught));
      } finally {
        setBusy(false);
      }
    })();
  }, []);

  const onDownloadUrl = useCallback(() => downloadPackageUrl(sessionId), [sessionId]);

  /* ======================================================================
   * 工程视角抽屉（并行只读 + 局部可写；open/close 零请求）
   * ==================================================================== */

  const onShowSummary = useCallback(async (): Promise<Record<string, unknown>> => {
    const summary = await fetchEngineeringSummary(sessionId);
    setEngineeringSummary(summary);
    return summary;
  }, [sessionId]);

  const onGenerateProject = useCallback(() => {
    void run(async (sid) => {
      if (writeBlockers.length > 0) {
        throw new Error(writeBlockers.map((b) => b.reason).join("；"));
      }
      await generateProjectPackage(sid, projectId);
      setActionFeedback("已生成工程包；交付结果区展示结构化编译诊断（这不代表编译零错误）");
    });
  }, [projectId, run, writeBlockers]);

  const onDeliverTia = useCallback(
    (mode: "auto" | "package") => {
      void run(async (sid) => {
        if (writeBlockers.length > 0) {
          throw new Error(writeBlockers.map((b) => b.reason).join("；"));
        }
        await deliverTia(sid, mode, projectId);
        setActionFeedback("真机交付已发起；TIA 不可用时会诚实降级为人工导入指引");
      });
    },
    [projectId, run, writeBlockers],
  );

  const onRunActionA = useCallback(
    () => void runAction("A", (sid) => runActionA({ session_id: sid })),
    [runAction],
  );
  const onRunActionB = useCallback(
    () =>
      void runAction("B", (sid) =>
        runActionB({
          session_id: sid,
          confirmed: explicitConfirmed,
          fidelity_report: actionFidelityReport,
        }),
      ),
    [actionFidelityReport, explicitConfirmed, runAction],
  );
  const onRunActionC = useCallback(
    () =>
      void runAction("C", (sid) =>
        runActionC({
          session_id: sid,
          confirmed: explicitConfirmed,
          diff: effectiveDiff,
          fidelity_report: actionFidelityReport,
        }),
      ),
    [actionFidelityReport, effectiveDiff, explicitConfirmed, runAction],
  );

  const onSendChat = useCallback(
    (text: string) =>
      void run(async (sid) => {
        await sendChat(sid, text, {
          projectId,
          topologyConstraints: buildTopologyConstraints(stateRef.current?.ir ?? null),
        });
      }),
    [projectId, run],
  );

  const onSendPastedScl = useCallback(
    (sclText: string) =>
      void run(async (sid) => {
        await uploadFiles(sid, [{ filename: "pasted.scl", text: sclText, kind: "db" }], projectId);
      }),
    [projectId, run],
  );

  const onConfirmReceiptAction = useCallback(
    () => void run(async (sid) => { await confirmReceipt(sid); }),
    [run],
  );

  const onValidate = useCallback(
    () => void run(async (sid) => { await revalidate(sid); }),
    [run],
  );

  const onGenerateDraft = useCallback(
    () =>
      void run(async (sid) => {
        await createDraft(sid, wizard.data.prompt || prompt, projectId);
      }),
    [projectId, prompt, run, wizard.data.prompt],
  );

  /** 非 memo：onFiles 依赖 run / projectId，每次 render 都要拿到最新闭包。 */
  const onUploadFilesAction = (files: FileList | null): void => {
    void onFiles(Array.from(files ?? []));
  };

  const onBindVar = useCallback(
    (varKey: string, targetId: string, role: string) =>
      void run(async (sid) => {
        await updateHardware(sid, { op: "bind_var", var_key: varKey, target_id: targetId, role });
      }),
    [run],
  );

  const onUnbindVar = useCallback(
    (varKey: string, targetId?: string) =>
      void run(async (sid) => {
        await updateHardware(sid, { op: "unbind_var", var_key: varKey, target_id: targetId || "" });
      }),
    [run],
  );

  const engineeringActions: EngineeringActions = {
    onBack,
    onShowSummary,
    onConfirm: () => {
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
    },
    onBeginEdit: () => void run(async (sid) => { await beginEdit(sid); }),
    onExportMermaid: () => {
      void run(async (sid) => {
        const result = await exportMermaid(sid);
        downloadText("结构图.md", result.markdown);
      });
    },
    onExportDraft: () => {
      void run(async (sid) => {
        const result = await exportDraft(sid);
        downloadText("草稿.json", JSON.stringify(result.payload, null, 2));
      });
    },
    onImportDraft: (payload: unknown) => {
      void run(async (sid) => {
        await importDraft(sid, payload as GFDraftPayload);
      });
    },
    onGenerateProject,
    onDeliverTia,
    onLoadReference: () => {
      void run(async (sid) => {
        await loadReferenceFixture(sid, wizard.data.prompt || prompt);
      });
    },
    onGenerateDraft,
    onValidate,
    onRunActionA,
    onRunActionB,
    onRunActionC,
    onToggleDiffItem,
    onConfirmDiff,
    onRefreshDiff,
    onSendChat,
    onSendFiles: (files: File[]) => void onFiles(files),
    onSendPastedScl,
    onConfirmReceipt: onConfirmReceiptAction,
    onUploadFiles: onUploadFilesAction,
    onBindVar,
    onUnbindVar,
    onPatchNodes,
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

  const compileDiagnostics: GFCompileDiagnostics | null =
    state.compile_diagnostics ?? state.delivery_summary?.compile_diagnostics ?? null;
  const fidelity: GFFidelityStatus | null =
    state.fidelity ?? state.delivery_summary?.fidelity ?? null;
  const reverseProtection: GFReverseProtection | null = state.reverse_protection ?? null;
  const sclSources = state.delivery_summary?.scl_sources ?? null;
  const pendingRealMachine = state.pending_real_machine !== false;

  const engineeringData: EngineeringViewData = {
    state,
    whitelist,
    diff: effectiveDiff,
    fidelity,
    compileDiagnostics,
    reverseProtection,
    sclSources,
    pendingRealMachine,
    pendingLabel: pendingRealMachineLabel(pendingRealMachine),
    actionResults,
    actionLoading,
    actionError,
    actionErrorCode,
    actionAvailability: availability,
    actionCompileDiagnostics,
    diffChecked,
    checklistComplete,
    explicitConfirmed,
    writeBlockers,
    blockers: confirmBlockers(state),
    summary: engineeringSummary,
    confirmErrorCode,
    confirmErrorMessage,
    backendConfirmReason:
      confirmErrorCode || confirmErrorMessage
        ? mapConfirmError(confirmErrorCode, confirmErrorMessage)
        : "",
    actionFeedback,
    diffError,
    projectId,
    constraintNote,
    busy,
  };

  const moreInputs: React.ReactNode = railOpen ? (
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
      onUploadFiles={onUploadFilesAction}
      onUploadPastedScl={onSendPastedScl}
      onConfirmReceipt={onConfirmReceiptAction}
      onBindVar={onBindVar}
      onUnbindVar={onUnbindVar}
      onValidate={onValidate}
    />
  ) : null;

  return (
    <div
      className="gf-root gf-channel gf-wiz"
      data-stage={state.stage}
      data-step={wizard.step}
      data-ui="greenfield-channel"
    >
      <GreenfieldWizard
        wizard={wizard}
        dispatch={dispatch}
        state={state}
        whitelist={whitelist}
        busy={busy}
        loading={loading}
        error={error}
        warning={diffError}
        sessionId={sessionId}
        projectId={projectId}
        canConfirm={canConfirm(state)}
        engineeringData={engineeringData}
        engineeringActions={engineeringActions}
        onBack={onBack}
        onPromptChange={(value: string) => {
          setPrompt(value);
          dispatch({ type: "SET_PROMPT", value });
        }}
        onSubmitDescribe={onSubmitDescribe}
        onConnect={onConnect}
        onRemoveEdge={onRemoveEdge}
        onEnterConfirm={onEnterConfirm}
        onConfirmAndGenerate={onConfirmAndGenerate}
        onBeginEditAndGoLink={onBeginEditAndGoLink}
        onRestart={onRestart}
        onDownloadUrl={onDownloadUrl}
        onClearError={() => setError("")}
        onToggleMoreInputs={() => setRailOpen((v) => !v)}
        moreInputs={moreInputs}
      />
    </div>
  );
};
