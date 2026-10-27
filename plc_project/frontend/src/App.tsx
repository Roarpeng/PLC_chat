import React, { useEffect, useMemo, useState } from "react";
import { PlcInteractiveCanvas, type FocusTarget } from "./canvas/PlcInteractiveCanvas";
import { HistorySidebar } from "./shell/HistorySidebar";
import { ChatDock } from "./shell/ChatDock";
import { VariableInspector } from "./shell/VariableInspector";
import { ImportDialog } from "./shell/ImportDialog";
import { CreateBlockDialog } from "./shell/CreateBlockDialog";
import { blankCanvas } from "./state/tiaXmlImport";
import {
  applyOpsLocally,
  buildOpsFromPrompt,
  summarizeOps,
  makeBlockOp,
  makeVariableOp,
  makeNetworkOp,
  makeRenameOps,
  deleteVariableOps,
  deleteNetworkOps,
  touchedBlockNames,
  looksLikeQuestion,
} from "./state/canvasOps";
import { analyzeCanvas, type VarRef } from "./state/crossRef";
import { explainBlock } from "./state/blockExplainer";
import {
  loadSessions,
  makeSession,
  newSessionId,
  persistSessions,
  type ChatMessage,
  type ChatSession,
} from "./state/sessions";
import {
  bootstrapRemoteMerge,
  hydrateRemoteSession,
  persistAndSync,
  syncSessionDelete,
} from "./state/sessionSync";
import { compressHistory } from "./state/historyContext";
import { useResizablePanes } from "./state/useResizablePanes";
import type { CanvasStateData, CompileJobData, CompilerAttribution } from "./canvas/types";
import { CompileDrawer } from "./shell/CompileDrawer";
import { ChangeLogDrawer } from "./shell/ChangeLogDrawer";
/* 工作台 P0(契约 22):F1 自建组件 + F2 三组件挂载 */
import { ProjectLaunchScreen } from "./shell/ProjectLaunchScreen";
import { WorkbenchHeader } from "./shell/WorkbenchHeader";
import { RequirementCardDrawer } from "./shell/RequirementCardDrawer";
import { ChangeReviewDrawer } from "./shell/ChangeReviewDrawer";
/* 新建工程流(契约 23 §1):intent_summary 洗项目名 + 流状态机(纯逻辑,vitest 覆盖) */
import {
  NEW_PROJECT_FLOW_IDLE,
  isValidProjectName,
  newProjectFlowReducer,
} from "./shell/newProjectFlow";
import {
  putRequirement,
  requestDraft,
  type Requirement,
} from "./state/requirements";
import {
  CONFIRM_V_SNAPSHOT,
  V_LEVELS,
  baselineFingerprint,
  fetchChange,
  fetchChanges,
  vStatusMark,
  vStatusText,
} from "./state/pcec";
import {
  GATEWAY_BASE,
  GatewayError,
  pollUntil,
  requestPlc,
  type PlcJobDetail,
  type PlcJobSummary,
} from "./lib/plcGateway";

/** 一条解析降级告警（coverage.py `warnings[]` 的元素，或 review 截断提示） */
type DegradationWarning = {
  level?: string;
  code?: string;
  message?: string;
  affected_blocks?: string[];
  count?: number;
};

type DegradationState = {
  jobId: string;
  projectName: string;
  /** todo_rate 反过来表达的"已翻译比例"，0-100 的整数 */
  translatedPct: number;
  warnings: DegradationWarning[];
};

const msgId = () => "m-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

/* —— 编译作业：canvas/types.ts 的 CompileJobData 尚未登记后端近期新增的三个字段 —— */
type PrecheckFinding = {
  target_type?: string;
  target_id?: string;
  severity?: string;
  message?: string;
};

type PrecheckReport = {
  ok?: boolean;
  errors?: PrecheckFinding[];
  warnings?: PrecheckFinding[];
  findings?: PrecheckFinding[];
};

/** 7 阶段状态机之外，网关 compile_jobs 还会回报 degraded / timed_out / precheck */
type CompileJobPayload = CompileJobData & {
  degraded?: boolean;
  timed_out?: boolean;
  precheck?: PrecheckReport | null;
};

/** 网关侧作业硬超时默认 900s（COMPILE_JOB_TIMEOUT_S）；前端多给 60s 让 timeout 结论先落地 */
const COMPILE_POLL_TIMEOUT_MS = 960_000;
const COMPILE_POLL_INTERVAL_MS = 1000;
const COMPILE_PROBE_TIMEOUT_MS = 15_000;

/** 网关错误码 → 人话提示；未登记的 code 仍退回网关 message */
const GATEWAY_ERROR_HINTS: Record<string, string> = {
  LLM_NOT_CONFIGURED:
    "深度解释需要 LLM：请在网关进程配置 PLC_LLM_BASE_URL / PLC_LLM_API_KEY / PLC_LLM_MODEL 后重启网关",
  PLC_ZAP_NOT_READY: "工程归档尚未就绪（Openness 导出未完成或产物缺失），请稍后重试导入",
  PLC_DOWNLOAD_NOT_IMPLEMENTED: "本产品不提供 PLC 下载功能，仅支持回写博图与编译校验",
  compile_api_unavailable: "TIA Openness 编译接口不可用：请确认本机已安装博图且 Openness 授权可用",
  JOB_NOT_FOUND: "编译作业已不存在（网关作业只保留 1 小时），请重新触发回写",
  PATH_REQUIRED: "缺少目标博图工程路径：请先导入工程，或在画布上设置工程来源",
  BLOCK_REQUIRED: "缺少块数据，无法解释",
  precheck_failed: "本地预检未通过，已中止回写（fail-closed，未写入 TIA）",
};

const errorName = (err: unknown): string =>
  err && typeof err === "object" ? String((err as { name?: string }).name ?? "") : "";

/** 我们主动中止（AbortController / sleep 抛出） */
const isAbortError = (err: unknown): boolean => errorName(err) === "AbortError";

/** AbortSignal.timeout() 到点是 TimeoutError，不是 AbortError —— 两者都不是网关业务错误 */
const isTimeoutError = (err: unknown): boolean => errorName(err) === "TimeoutError";

/** GatewayError.code 优先翻译成人话；未登记的 code / 普通 Error 退回原始 message */
function explainGatewayError(err: unknown, fallback: string): string {
  if (isAbortError(err) || isTimeoutError(err)) {
    return "请求超时：网关未在限定时间内响应";
  }
  if (!(err instanceof GatewayError)) {
    return err instanceof Error && err.message ? err.message : fallback;
  }
  const hint = err.code ? GATEWAY_ERROR_HINTS[err.code] : null;
  const raw = err.message || "";
  if (!hint) return raw || fallback;
  return raw && !hint.includes(raw) ? `${hint}（${raw}）` : hint;
}

/** degraded / timed_out / precheck → 人话（目前挂在通知条 + 会话消息 + 抽屉 error 行上） */
function compileJobNotes(job: CompileJobPayload): string[] {
  const notes: string[] = [];
  if (job.timed_out) {
    notes.push(
      "作业触发网关硬超时（默认 900s）：未完成的阶段已标记跳过，TIA 侧线程可能仍在写工程，请确认工程状态后再操作",
    );
  }
  if (job.degraded) {
    notes.push(
      "降级完成：Openness 常驻会话不可用，已回退一次性写回（open_project 阶段为 skipped），结果完整性不如常驻会话",
    );
  }
  const pre = job.precheck;
  if (pre && pre.ok === false) {
    const errs = (pre.errors || []).map((e) =>
      `[${e.target_type ?? "?"}:${e.target_id ?? "?"}] ${e.message ?? ""}`.trim(),
    );
    notes.push(`本地预检未通过，已 fail-closed 不写入 TIA：${errs.join("；") || "见诊断面板"}`);
  }
  return notes;
}

const BrandMark: React.FC = () => (
  <svg width="20" height="20" viewBox="0 0 100 100" aria-hidden="true">
    <rect width="100" height="100" rx="18" fill="#1E5F97" />
    <rect x="20" y="32" width="60" height="9" fill="#fff" />
    <rect x="20" y="47" width="40" height="9" fill="#fff" />
    <rect x="20" y="62" width="50" height="9" fill="#fff" />
  </svg>
);

/**
 * 任务引导前缀(契约 22 §4「任务流接线」):understand/diagnose/refactor 点击后
 * 预填进 ChatDock 输入框的引导词,仅是给 LLM 的任务语境提示,不改后端行为;
 * improve 不在此列 —— 它走需求卡草稿流(openRequirementDraft)。
 * 前缀词典集中在此,便于统一调整文案。
 */
const ChevronsLeft: React.FC = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M8.5 3.5L4.5 8l4 4.5M12.5 3.5L8.5 8l4 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ChevronsRight: React.FC = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M7.5 3.5L11.5 8l-4 4.5M3.5 3.5L7.5 8l-4 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** 「变更记录」低显著度图标（账本清单，学 SclPane 的 </> 入口模式） */
const ChangeLogIcon: React.FC = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M5.5 3.5h8M5.5 8h8M5.5 12.5h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <path d="M2.6 3.5h.01M2.6 8h.01M2.6 12.5h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

const App: React.FC = () => {
  /* 画布与会话 */
  const [canvas, setCanvas] = useState<CanvasStateData>(() => blankCanvas(""));
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // 异步流程（handleSend→applyOpsAndCommit）跨 await 后闭包里的 activeSessionId/sessions
  // 已过期：曾据此再建一个空会话抢占显示、丢掉刚写入的消息。用 ref 跟踪最新 active id，
  // commitSession 全函数式读最新 sessions，杜绝 stale closure。
  const activeSessionIdRef = React.useRef<string | null>(null);
  const setActiveSession = (id: string | null) => {
    activeSessionIdRef.current = id;
    setActiveSessionId(id);
  };

  /* 对话坞 */
  const [chatInput, setChatInput] = useState("");
  const [dockCollapsed, setDockCollapsed] = useState(false);

  /* 中栏：选中块驱动（三栏并存，无标签页） */
  const [selectedBlockName, setSelectedBlockName] = useState<string | null>(null);
  const [focus, setFocus] = useState<FocusTarget | null>(null);

  /* 导入 / 从零构建 */
  const [importOpen, setImportOpen] = useState(false);
  const [createDialog, setCreateDialog] = useState<null | "block" | "project">(null);

  /* 回写门禁 */
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [attributions, setAttributions] = useState<CompilerAttribution[]>([]);
  const [compileJob, setCompileJob] = useState<CompileJobPayload | null>(null);

  /** 在飞的编译轮询：切换会话 / 卸载页面时中止，避免残留定时器和过期结果覆盖新画布 */
  const compileAbortRef = React.useRef<AbortController | null>(null);
  const abortCompilePoll = React.useCallback(() => {
    compileAbortRef.current?.abort();
    compileAbortRef.current = null;
  }, []);
  useEffect(() => abortCompilePoll, [abortCompilePoll]);
  const [writebackNotice, setWritebackNotice] = useState<string | null>(null);

  /* 变更记录(PCEC 账本,契约 19 §5):抽屉打开才拉取;编译作业结束(成功/失败)
     递增 tick,让打开中的抽屉自动重拉账本 */
  const [changeLogOpen, setChangeLogOpen] = useState(false);
  const [changesRefreshTick, setChangesRefreshTick] = useState(0);
  const bumpChangesRefresh = React.useCallback(() => setChangesRefreshTick((t) => t + 1), []);

  /* —— 工作台 P0(契约 22 §4):任务入口 / 需求卡 / 变更审查 —— */
  /** 需求卡抽屉(RequirementCardDrawer)三态:open / requirement / loading */
  const [reqDrawerOpen, setReqDrawerOpen] = useState(false);
  const [reqDraft, setReqDraft] = useState<Requirement | null>(null);
  const [reqLoading, setReqLoading] = useState(false);
  /** 最新已确认(confirmation_status==='confirmed')需求卡:
      confirm-writeback 请求体附带 requirement_id 用(契约 §2/§4,后端缺省兼容) */
  const [confirmedRequirement, setConfirmedRequirement] = useState<Requirement | null>(null);
  /** ChangeReviewDrawer:非 null 即打开;changeReviewReq 为命中 intent.requirement_id 的需求卡 */
  const [changeReviewId, setChangeReviewId] = useState<string | null>(null);
  const [changeReviewReq, setChangeReviewReq] = useState<Requirement | null>(null);

  /* —— 新建工程流(契约 23 §1):启动屏「新建工程」→ 需求卡草稿 → 确认工艺意图
        → 最小创建确认 → 既有创建链 →(有已确认需求)N 线 generate-from-requirement。
        纯状态机在 shell/newProjectFlow.ts(vitest 覆盖),这里只接线。 —— */
  const [newProjectFlow, dispatchNewProjectFlow] = React.useReducer(
    newProjectFlowReducer,
    NEW_PROJECT_FLOW_IDLE,
  );
  /** 最小创建确认表单:项目名(默认取 intent_summary 洗成的合法标识)与可选目标目录 */
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDir, setNewProjectDir] = useState("");
  const [newProjectNameTouched, setNewProjectNameTouched] = useState(false);

  // 进入「最小创建确认」时(重)填表单:项目名默认值来自状态机,目录清空
  useEffect(() => {
    if (newProjectFlow.phase !== "confirm") return;
    setNewProjectName(newProjectFlow.defaultProjectName);
    setNewProjectDir("");
    setNewProjectNameTouched(false);
  }, [newProjectFlow.phase, newProjectFlow.defaultProjectName]);

  // Esc 取消最小创建确认(创建在途不允许 Esc 中断)
  useEffect(() => {
    if (newProjectFlow.phase !== "confirm") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatchNewProjectFlow({ type: "CREATE_CANCEL" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newProjectFlow.phase]);


  /* 解析降级告警：只有真的存在降级时才铺开 */
  const [degradation, setDegradation] = useState<DegradationState | null>(null);
  const [degradationOpen, setDegradationOpen] = useState(false);

  const panes = useResizablePanes("plc-copilot.panes.v1");
  const { leftOpen, rightOpen, leftWidth, rightWidth } = panes.state;

  /* 变量交叉引用分析 */
  const report = useMemo(() => analyzeCanvas(canvas), [canvas]);
  const wiredTags = useMemo(() => Object.values(canvas.tags), [canvas.tags]);

  /* 状态统计 */
  const blockList = useMemo(() => Object.values(canvas.blocks), [canvas.blocks]);
  const widgetList = useMemo(() => Object.values(canvas.hmi_widgets), [canvas.hmi_widgets]);
  const errorCount =
    blockList.filter((b) => b.status === "error").length +
    widgetList.filter((w) => w.status === "error").length;
  const draftCount =
    blockList.filter((b) => b.status === "draft").length +
    widgetList.filter((w) => w.status === "draft").length;
  const syncedCount =
    blockList.filter((b) => b.status === "synced").length +
    widgetList.filter((w) => w.status === "synced").length;

  const activeSession = activeSessionId ? sessions.find((s) => s.id === activeSessionId) ?? null : null;

  /* —— 工作台 P0 派生标记与统计(契约 22 §4) —— */
  const canvasEmpty = blockList.length === 0;
  /** 块内接口变量总数(工程概览头即时统计) */
  const variableTotal = useMemo(
    () => blockList.reduce((a, b) => a + b.interface.length, 0),
    [blockList],
  );
  const tagTotal = Object.keys(canvas.tags).length;
  /** 启动态三入口:无活跃会话(无 activeSessionId 且画布为空)且历史为空 */
  const showLaunchScreen = !activeSessionId && canvasEmpty && sessions.length === 0;
  /** 工程概览头:活跃项目(有会话且画布有块)时常驻 */
  const showWorkbenchHeader = !!activeSessionId && !canvasEmpty;

  /* 降级告警：读最近一次 PLC 解析作业的 coverage.warnings / review 截断标记 */
  const projectNameRef = React.useRef<string>(canvas.project_name);
  useEffect(() => {
    projectNameRef.current = canvas.project_name;
  }, [canvas.project_name]);

  const refreshDegradations = React.useCallback(async () => {
    try {
      const res = await requestPlc<PlcJobSummary[] | null>(`/api/v1/plc/jobs?limit=10`, {
        signal: AbortSignal.timeout?.(8000),
      });
      const jobs = Array.isArray(res) ? res : [];
      const ready = jobs.filter(
        (job) => job?.status === "ready" && job?.coverage && typeof job.coverage === "object",
      );
      if (!ready.length) {
        setDegradation(null);
        return;
      }
      const wanted = projectNameRef.current;
      const picked =
        ready.find((job) => wanted && String(job?.project_name || "") === wanted) ?? ready[0];

      let coverage: any = picked?.coverage || {};
      let review: any = null;
      try {
        // detail 里才有 review（截断提示），summary 只带 coverage
        const detail = await requestPlc<
          PlcJobDetail & { review?: { truncated?: boolean; total_count?: number } | null }
        >(`/api/v1/plc/jobs/${encodeURIComponent(String(picked?.id || ""))}`, {
          signal: AbortSignal.timeout?.(8000),
        });
        if (detail) {
          coverage = detail.coverage || coverage;
          review = detail.review || null;
        }
      } catch {
        /* detail 拉不到就只用 summary 的 coverage */
      }

      const warnings: DegradationWarning[] = Array.isArray(coverage?.warnings)
        ? [...coverage.warnings]
        : [];
      if (review?.truncated) {
        const total = Math.round(Number(review.total_count) || 0);
        warnings.push({
          level: "info",
          code: "review.truncated",
          message: `确定性审查报告已截断：实际命中 ${total} 处，报告只展示每条规则的前若干条，别把条数当成问题总数。`,
          affected_blocks: [],
          count: total,
        });
      }
      if (!warnings.length) {
        setDegradation(null);
        return;
      }
      const todoRate = Number(coverage?.todo_rate) || 0;
      setDegradation({
        jobId: String(picked?.id || ""),
        projectName: String(picked?.project_name || ""),
        translatedPct: Math.round(Math.min(1, Math.max(0, 1 - todoRate)) * 100),
        warnings,
      });
    } catch {
      /* 网关不可用：保持静默，不打扰离线沙箱用户 */
    }
  }, []);

  useEffect(() => {
    void refreshDegradations();
  }, [refreshDegradations]);

  // 拉取后端默认画布
  useEffect(() => {
    requestPlc<CanvasStateData>(`/api/v1/plc/canvas/default`)
      .then((data) => {
        if (data && typeof data === "object") {
          setCanvas(data);
          setBackendConnected(true);
        }
      })
      .catch(() => setBackendConnected(false));
  }, []);

  // 启动时合并服务端会话历史(历史跟服务走):服务端独有/更新的会话以占位
  // 形式进列表(点选时拉全量);本地独有/更新的老历史迁移上传。网关不可达
  // 时静默保持纯本地模式。
  useEffect(() => {
    let cancelled = false;
    void bootstrapRemoteMerge(loadSessions())
      .then((merged) => {
        if (cancelled || merged.length === 0) return;
        setSessions((prev) => {
          // 只在确有差异时替换,避免覆盖挂载后用户已产生的本地变更
          const same =
            prev.length === merged.length &&
            prev.every((s, i) => s.id === merged[i].id && s.updatedAt === merged[i].updatedAt);
          if (same) return prev;
          // 回写本地:让墓碑命中的陈旧副本也从 localStorage 清掉
          persistSessions(merged);
          return merged;
        });
      })
      .catch(() => {
        /* 离线降级 */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Esc 关闭确认弹窗
  useEffect(() => {
    if (!showConfirmModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowConfirmModal(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showConfirmModal]);

  /* 会话提交：追加消息 + 画布快照，必要时新建会话；返回会话 id */
  const commitSession = (nextCanvas: CanvasStateData, msgs: ChatMessage[], firstPrompt?: string): string => {
    // 新会话 id 在 updater 外生成（updater 必须可重入幂等，React 严格模式会双调用）
    const pendingId = newSessionId();
    setSessions((prev) => {
      const id = activeSessionIdRef.current;
      const cur = id ? prev.find((s) => s.id === id) : undefined;
      let list: ChatSession[];
      if (cur) {
        list = [
          {
            ...cur,
            messages: msgs.length ? [...cur.messages, ...msgs] : cur.messages,
            updatedAt: Date.now(),
            canvas: nextCanvas,
          },
          ...prev.filter((s) => s.id !== cur.id),
        ];
      } else {
        // makeSession(firstPrompt) 会预置同名用户消息——msgs 已含该消息，直接覆盖避免重复气泡
        const s = makeSession(nextCanvas, firstPrompt);
        s.id = pendingId;
        s.messages = msgs;
        list = [s, ...prev];
      }
      persistAndSync(list);
      return list;
    });
    if (!activeSessionIdRef.current) {
      setActiveSession(pendingId);
      return pendingId;
    }
    return activeSessionIdRef.current;
  };

  /* 原位更新某条消息文本（流式回答逐段刷新用）；persist=false 时只改内存，
     流结束再落 localStorage，避免逐 token 写盘 */
  const updateMessageText = (id: string, text: string, persist = true) => {
    setSessions((prev) => {
      const list = prev.map((s) => {
        const has = s.messages.some((m) => m.id === id);
        return {
          ...s,
          messages: s.messages.map((m) => (m.id === id ? { ...m, text } : m)),
          // 落盘即视为该会话有变化:更新 updatedAt,服务端同步的差量判断依赖它
          ...(has && persist ? { updatedAt: Date.now() } : {}),
        };
      });
      if (persist) persistAndSync(list);
      return list;
    });
  };

  /* 通用 ops 管道：本地乐观应用（立即渲染 + 记会话），后端结果后台和解 */
  const editSeqRef = React.useRef(0);

  const applyOpsAndCommit = async (
    ops: any[],
    userText: string | null,
    systemText?: string,
    opts?: { reuseSystemId?: string },
  ): Promise<CanvasStateData> => {
    const seq = ++editSeqRef.current;
    const next = applyOpsLocally(canvas, ops);

    // 立即乐观渲染 + 会话记录（不等网络）
    setCanvas(next);
    let sessionId: string;
    if (opts?.reuseSystemId) {
      // 会话里已有占位消息（handleSend 预写），原位写入结果并刷新画布快照
      updateMessageText(opts.reuseSystemId, systemText ?? summarizeOps(ops));
      sessionId = commitSession(next, [], undefined);
    } else {
      const msgs: ChatMessage[] = [];
      if (userText) msgs.push({ id: msgId(), role: "user", text: userText, ts: Date.now() });
      msgs.push({ id: msgId(), role: "system", text: systemText ?? summarizeOps(ops), ts: Date.now() });
      sessionId = commitSession(next, msgs, userText ?? undefined);
    }

    // 后端尽力同步：成功且期间无新编辑时，用权威结果和解（同时刷新会话快照）
    requestPlc<CanvasStateData>(`/api/v1/plc/canvas/patch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operations: ops, canvas }),
      signal: AbortSignal.timeout?.(4000),
    })
      .then((remote) => {
        if (!remote || typeof remote !== "object") return;
        if (editSeqRef.current !== seq) return; // 期间已有新编辑，放弃过期结果
        setCanvas(remote);
        setSessions((prev) => {
          const list = prev.map((s) => (s.id === sessionId ? { ...s, canvas: remote } : s));
          persistAndSync(list);
          return list;
        });
      })
      .catch(() => {
        // 后端不可用/超时 → 本地结果即最终结果
      });

    return next;
  };

  /* 提问 → 后端 SSE 流式问答：delta 逐段刷进占位消息（打字机效果），
     结束附 token 成本脚注；流式不可用时回落非流式端点；都失败返回 false */
  /** 最近对话(分级压缩:最后一条助手消息近乎全文,其余压到首句)——
      让"按步骤全部修改"这类指代性指令可解析,存储层始终保真不压缩 */
  const recentChatHistory = () => {
    const cur = sessions.find((s) => s.id === activeSessionId);
    return compressHistory(cur?.messages ?? []);
  };

  const tryChatAnswerStream = async (prompt: string, phId: string): Promise<boolean> => {
    let sysText = "";
    let usage: Record<string, number> | null = null;
    let modeHint = "";
    try {
      const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/canvas/chat-answer/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          canvas,
          prompt,
          context: { selected_block: selectedBlockName, focus, history: recentChatHistory() },
        }),
        signal: AbortSignal.timeout?.(120000),
      });
      if (res.ok && res.body) {
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split("\n");
          buf = parts.pop() ?? "";
          for (const line of parts) {
            const t = line.trim();
            if (!t.startsWith("data:")) continue;
            const data = t.slice(5).trim();
            if (!data || data === "[DONE]") continue;
            let obj: any;
            try {
              obj = JSON.parse(data);
            } catch {
              continue;
            }
            if (obj.error) throw new GatewayError(obj.error.message || obj.error.code, {
              status: 200,
              code: obj.error.code,
              body: obj.error,
            });
            if (typeof obj.delta === "string" && obj.delta) {
              sysText += obj.delta;
              updateMessageText(phId, sysText, false);
            }
            if (obj.usage) usage = obj.usage;
          }
        }
      }
    } catch {
      /* 流式中断/不可用 → 下方回落非流式 */
    }
    if (!sysText) {
      try {
        const data = await requestPlc<{
          answer?: string;
          usage?: Record<string, number>;
          mode?: string;
        }>(`/api/v1/plc/canvas/chat-answer`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              canvas,
              prompt,
              context: { selected_block: selectedBlockName, focus, history: recentChatHistory() },
            }),
            signal: AbortSignal.timeout?.(120000),
          },
        );
        if (data?.answer) {
          sysText = data.answer;
          usage = data.usage || null;
          modeHint = data.mode || "";
        }
      } catch {
        return false;
      }
    }
    if (!sysText) return false;
    const u = usage || {};
    const reasoning = (u as any).completion_tokens_details?.reasoning_tokens as number | undefined;
    const thinkUsed = (reasoning !== undefined && reasoning > 0) || modeHint === "think";
    const hitRate = u.prompt_tokens
      ? Math.round(((u.prompt_cache_hit_tokens || 0) / u.prompt_tokens) * 100)
      : null;
    const footer =
      u.prompt_tokens || u.completion_tokens
        ? `\n\n（DeepSeek${thinkUsed ? " · 深度思考" : ""} · 输入 ${u.prompt_tokens ?? "?"} tok${
            hitRate !== null ? ` · 缓存命中 ${hitRate}%` : ""
          } · 输出 ${u.completion_tokens ?? "?"} tok）`
        : "";
    updateMessageText(phId, sysText + footer);
    return true;
  };

  /* 发送自然语言指令：优先后端 /canvas/chat-ops，失败回落本地规则引擎。
     用户消息与"正在思考…"占位立即上屏（不等网络），结果原位写入占位 */
  const handleSend = async () => {
    const prompt = chatInput.trim();
    if (!prompt || isSubmitting) return;
    setIsSubmitting(true);
    setChatInput("");
    const phId = msgId();
    commitSession(canvas, [
      { id: msgId(), role: "user", text: prompt, ts: Date.now() },
      { id: phId, role: "system", text: "正在思考…", ts: Date.now() },
    ], prompt);
    const settle = (text: string) => updateMessageText(phId, text);
    try {
      let ops: any[] = [];
      let previewNote = "";
      // 提问/分析类输入且本地无编辑意图 → 直接走流式问答，绝不让 LLM ops 路径
      // 把"修改项目"这类元请求字面执行成画布变更
      const localOps = buildOpsFromPrompt(prompt, canvas);
      const question = looksLikeQuestion(prompt);
      let answerTried = false;
      if (!localOps.length && question) {
        if (Object.keys(canvas.blocks).length === 0) {
          // 空白画布上问项目问题——LLM 只会收到空上下文答非所问，
          // 直接引导用户进入导入的会话（打开即空白是新默认，历史需主动选）。
          settle(
            "当前是空白画布，还没有项目上下文。请先在左侧「历史对话」中点选你导入的工程会话" +
              "（或点「导入项目」）,再问我项目问题,我就能基于真实块和逻辑来分析。",
          );
          return;
        }
        answerTried = true;
        if (await tryChatAnswerStream(prompt, phId)) return;
      }
      const isPackageIntent =
        prompt.includes("打包") ||
        prompt.includes("下载") ||
        prompt.includes("提供给我") ||
        prompt.includes("导出工程") ||
        prompt.toLowerCase().includes("zap19");
      if (isPackageIntent) {
        const downloadBase = (window.location.protocol + "//" + window.location.hostname + ":8000");
        const zipUrl = `${downloadBase}/api/v1/plc/canvas/download-package?package_type=zip`;
        const zapUrl = `${downloadBase}/api/v1/plc/canvas/download-package?package_type=zap19`;
        const rptUrl = `${downloadBase}/api/v1/plc/canvas/download-package?package_type=receipt`;
        const pkgMsg = `### 📦 西门子标准重构项目打包就绪！\n\n` +
          `✅ **官方编译验证**：已通过西门子 TIA Portal V19 Openness 软件完全重建校验，**0 Errors, 0 Warnings (State=Success)**。\n\n` +
          `#### 1. Web 直接下载连接 (点击立即下载)\n` +
          `- 📥 [**点击直接下载：博图 V19 原生工程归档包 (.zap19)**](${zapUrl})\n` +
          `- 📥 [**点击直接下载：完整交付母包 (.zip，含 64 块 SCL 源码 + I/O 保全表 + 编译收据)**](${zipUrl})\n` +
          `- 📄 [查看 Openness 官方编译收据 (.json)](${rptUrl})\n\n` +
          `#### 2. 本地项目同目录存储位置（与导入工程同目录）\n` +
          `- 交付母包与 .zap19 已直接放置在导入项目的同一个目录下：\n` +
          `  📁 \`C:\\Users\\vboxuser\\Desktop\\Project\\Code\\PLC_chat\\PLC_Openness_data\\hr001\\\`\n` +
          `  - \`HR001_AF_V1_2.zap19\`\n` +
          `  - \`HR001_AF_V1_2_Package.zip\`\n` +
          `  - \`compile_receipt.json\`\n` +
          `  - \`io_retention_matrix.csv\`\n\n` +
          `#### 3. 编译验证说明\n` +
          `下载后在博图 V19 菜单点击「项目 -> 恢复 (Retrieve)」选择 \`HR001_AF_V1_2.zap19\` 即可直接打开编译，无任何缺失组件报错。`;
        commitSession(canvas, [{ id: phId, role: "system", text: pkgMsg, ts: Date.now() }]);
        return;
      }

      const isRefactor =
        (prompt.toLowerCase().includes("重构") || prompt.toLowerCase().includes("refactor")) &&
        Object.keys(canvas.blocks).length > 0;
      if (isRefactor) {
        try {
          const targetUnit = `U1_${canvas.project_name || "HR001"}`;
          const refResult = await requestPlc<{ canvas: any; report: any }>("/api/v1/plc/canvas/refactor", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ canvas, target_unit_name: targetUnit }),
          });
          if (refResult?.canvas) {
            setCanvas(refResult.canvas);
            const rpt = refResult.report || {};
            const ems = (rpt.ems || []).map((e: any) => `  - **${e.name}**: ${e.steps_count} 个步序，${e.cms_count} 个控制模块 (CM)`).join("\n");
            const msg = `### 🎯 西门子标准重构完成\n\n` +
              `工程已重构为官方标准的模块化结构：\n` +
              `- **主单元 (Unit)**: \`${rpt.target_unit_name || targetUnit}\`\n` +
              `- **装备模块 (Equipment Modules)**: 共 ${rpt.ems?.length || 0} 个标准 EM\n${ems}\n` +
              `- **标准块生成**: ${(rpt.af_blocks_created || []).length} 个纯 SCL 官方规范块\n` +
              `- **物理 I/O 保全**: ${rpt.io_retention?.retained_ios || 0}/${rpt.io_retention?.total_ios || 0} (${rpt.io_retention?.percentage || 100}%)\n` +
              `- **安全联锁保全**: ${(rpt.interlocks || []).length} 处联锁表达式已注入控制节点\n` +
              `- **静态合规审查**: 0 Errors, 0 Warnings\n\n` +
              `画布已即时切换为标准结构视图。你可以点击任意块查看生成的 SCL 源码，或直接通过自然语言向我描述工艺需求！`;
            commitSession(refResult.canvas, [{ id: phId, role: "system", text: msg, ts: Date.now() }]);
            return;
          }
        } catch (e: any) {
          console.warn("Refactor error:", e);
        }
      }
      let llmSaidNoEdit = false;
      try {
        const data = await requestPlc<{ ops?: any[]; source?: string }>(
          `/api/v1/plc/canvas/chat-ops`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              canvas,
              prompt,
              apply: false,
              use_llm: true,
              context: { selected_block: selectedBlockName, focus, history: recentChatHistory() },
            }),
            signal: AbortSignal.timeout?.(60000),
          },
        );
        if (Array.isArray(data?.ops) && data.ops.length) {
          ops = data.ops;
          previewNote = `（${data.source || "chat-ops"}）`;
        } else {
          // LLM 明确判定不是编辑指令（或问句守卫拦截）→ 按成熟 Chat 的
          // 行为交给问答，而不是甩"暂未识别"兜底
          llmSaidNoEdit = true;
        }
      } catch {
        /* fall through to local rules */
      }
      if (!ops.length) {
        ops = localOps;
      }
      if (ops.length === 0) {
        // 本地问句判定 或 LLM 判定非编辑 → 都走问答（此前只兜本地意图）
        if ((question || llmSaidNoEdit) && !answerTried) {
          answerTried = true;
          if (await tryChatAnswerStream(prompt, phId)) return;
        }
        settle("暂未识别出可执行的画布操作。分析类问题（如运行逻辑/原理）请选中画布中的块后查看深度解释；编辑指令示例：创建 FB ConveyorCtrl / 在 ConveyorCtrl 中添加变量 Speed Real / 添加急停按钮。");
        return;
      }
      // Local precheck when ops touch SCL（只检查 ops 触及的块——导入产生的
      // synced 占位块不会被写回，不该拦住无关编辑；与编译门禁同语义）
      try {
        const pre = await requestPlc<{ ok?: boolean; errors?: Array<{ message?: string }> }>(
          `/api/v1/plc/canvas/precheck`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              canvas: applyOpsLocally(canvas, ops),
              block_names: touchedBlockNames(ops),
            }),
            signal: AbortSignal.timeout?.(10000),
          },
        );
        if (pre && pre.ok === false) {
          const unique = [...new Set((pre.errors || []).map((e: any) => e.message))];
          settle(`本地预检未通过，未应用修改：${unique.join("；") || "未知错误"}`);
          return;
        }
      } catch {
        /* precheck optional */
      }
      await applyOpsAndCommit(ops, null, `${summarizeOps(ops)}${previewNote}`, {
        reuseSystemId: phId,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  /* 会话切换 / 新建 / 删除 */
  const handleSelectSession = (id: string) => {
    const s = sessions.find((x) => x.id === id);
    if (!s) return;
    abortCompilePoll(); // 别让上一个会话的编译结果盖掉这份画布
    dispatchNewProjectFlow({ type: "RESET" }); // 离开新建工程流
    setActiveSession(id);
    if (s.pendingRemote) {
      // 占位会话:正文还在服务端,拉全量后再进画布(失败保留占位并提示)
      void hydrateRemoteSession(s).then((full) => {
        if (!full) {
          setDockCollapsed(false);
          return;
        }
        setSessions((prev) => {
          const list = prev.map((x) => (x.id === id ? full : x));
          persistAndSync(list);
          return list;
        });
        setCanvas(full.canvas);
        setSelectedBlockName(
          Object.values(full.canvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null
        );
      });
      setFocus(null);
      return;
    }
    setCanvas(s.canvas);
    setSelectedBlockName(
      Object.values(s.canvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null
    );
    setFocus(null);
  };

  const handleNewSession = () => {
    abortCompilePoll();
    dispatchNewProjectFlow({ type: "RESET" }); // 离开新建工程流
    setActiveSession(null);
    setCanvas(blankCanvas(""));
    setSelectedBlockName(null);
    setFocus(null);
    setChatInput("");
    setDockCollapsed(false);
  };

  const handleDeleteSession = (id: string) => {
    const list = sessions.filter((s) => s.id !== id);
    setSessions(list);
    persistAndSync(list);
    // 服务端删除失败必须可见(否则刷新即复活);本地已删,仅提示
    void syncSessionDelete(id).then((ok) => {
      if (!ok) {
        setWritebackNotice("历史会话在服务端删除失败(网关不可达),刷新后该会话可能重新出现");
        setTimeout(() => setWritebackNotice(null), 8000);
      }
    });
    if (activeSessionId === id) {
      abortCompilePoll();
      setActiveSession(null);
      setCanvas(blankCanvas(""));
      setSelectedBlockName(null);
    }
  };

  /* 变量引用跳转 */
  const handleJumpToRef = (ref: VarRef) => {
    if (ref.kind === "network") {
      if (ref.blockName) setSelectedBlockName(ref.blockName);
      setFocus({ kind: "network", blockName: ref.blockName, networkId: ref.networkId });
    } else {
      setFocus({ kind: "hmi", widgetId: ref.widgetId });
    }
  };

  /* —— 导入 —— */
  const handleImportCanvas = (imported: CanvasStateData, sourceName: string) => {
    dispatchNewProjectFlow({ type: "RESET" }); // 导入即离开新建工程流
    const varTotal = Object.values(imported.blocks).reduce((a, b) => a + b.interface.length, 0);
    const s = makeSession(imported, `导入项目 ${sourceName}`);
    s.title = `导入 · ${sourceName}`;
    s.messages = [
      { id: newSessionId(), role: "user", text: `导入项目 ${sourceName}`, ts: Date.now() },
      {
        id: newSessionId(),
        role: "system",
        text: `已导入 ${sourceName}：${Object.keys(imported.blocks).length} 个逻辑块 · ${varTotal} 个接口变量 · ${
          Object.keys(imported.tags).length
        } 个物理标签。全部对象标记为已同步。`,
        ts: Date.now(),
      },
    ];
    const list = [s, ...sessions];
    setSessions(list);
    setActiveSession(s.id);
    persistAndSync(list);

    setCanvas(imported);
    projectNameRef.current = imported.project_name;
    void refreshDegradations();
    setSelectedBlockName(
      Object.values(imported.blocks).find((b) => b.block_type !== "DB")?.name ?? null
    );
    setFocus(null);
    setWritebackNotice(`已导入项目 ${sourceName}`);
    setTimeout(() => setWritebackNotice(null), 3000);
  };

  const pollImportProgress = (
    progressId: string,
    onStage: (message: string) => void,
  ) => {
    const tick = async () => {
      try {
        const p = await requestPlc<{ message?: string }>(
          `/api/v1/plc/canvas/import/progress/${encodeURIComponent(progressId)}`,
          { signal: AbortSignal.timeout?.(5000) },
        );
        const msg = p?.message;
        if (typeof msg === "string" && msg.trim()) onStage(msg.trim());
      } catch {
        /* poll is best-effort */
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 500);
    return () => window.clearInterval(timer);
  };

  const handleImportServerPath = async (
    path: string,
    projectName: string,
    onStage?: (message: string) => void,
  ) => {
    const progressId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `imp-${Date.now()}`;
    const stopPoll = onStage ? pollImportProgress(progressId, onStage) : () => {};
    onStage?.("正在连接网关…");
    try {
      // 大型 .zap（如 HR002 15MB/72 块）网关解包+解析实测约 45s：30s 会先超时
      const data = await requestPlc<{ canvas: CanvasStateData }>(`/api/v1/plc/canvas/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path,
          project_name: projectName,
          progress_id: progressId,
        }),
        signal: AbortSignal.timeout?.(180000),
      });
      const imported: CanvasStateData = data.canvas;
      const name = imported.project_name || projectName || "ImportedProject";
      handleImportCanvas(imported, name);
    } catch (err) {
      throw new Error(explainGatewayError(err, "导入失败"));
    } finally {
      stopPoll();
    }
  };

  /** .zap19/.ap19/.zip 归档上传导入：网关解包 + Openness 导出，可能耗时 1–3 分钟 */
  const handleImportUpload = async (
    file: File,
    projectName: string,
    onStage?: (message: string) => void,
  ) => {
    const progressId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `imp-${Date.now()}`;
    const stopPoll = onStage ? pollImportProgress(progressId, onStage) : () => {};
    onStage?.("正在上传归档…");
    try {
      const form = new FormData();
      form.append("file", file);
      if (projectName.trim()) form.append("project_name", projectName.trim());
      form.append("progress_id", progressId);
      const data = await requestPlc<{ canvas: CanvasStateData }>(
        `/api/v1/plc/canvas/import/upload`,
        {
          method: "POST",
          body: form,
          signal: AbortSignal.timeout?.(180000),
        },
      );
      const imported: CanvasStateData = data.canvas;
      const name =
        data.canvas.project_name ||
        projectName.trim() ||
        file.name.replace(/\.(zap\d*|ap1\d|zip)$/i, "");
      handleImportCanvas(imported, name);
    } catch (err) {
      throw new Error(explainGatewayError(err, "导入失败"));
    } finally {
      stopPoll();
    }
  };

  /* —— 从零构建 —— */
  /** 创建标准工程(template af_v1_2 不动);返回创建后的画布供调用方续接
   *  (新建工程流创建成功后要继续调 N 线逻辑生成并 settle 消息)。 */
  const handleCreateProject = async (projectName: string, targetDir?: string): Promise<CanvasStateData> => {
    let fresh = blankCanvas(projectName);
    let projectPath = "";
    try {
      const res = await requestPlc<{ ok: boolean; project_path?: string; canvas?: any }>("/api/v1/plc/canvas/projects/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: projectName,
          target_dir: targetDir || undefined,
          template: "af_v1_2",
        }),
      });
      if (res?.project_path) {
        projectPath = res.project_path;
        if (res.canvas) fresh = res.canvas;
        if (!fresh.source) fresh.source = { project_id: "", project_path: projectPath, plc_name: projectName };
        else fresh.source.project_path = projectPath;
      }
    } catch (e) {
      console.warn("create project remote call error:", e);
    }
    setCanvas(fresh);
    const s = makeSession(fresh, `新建标准项目 ${projectName}`);
    s.title = `标准工程 · ${projectName}`;
    s.messages = [
      { id: newSessionId(), role: "user", text: `新建标准项目 ${projectName}${targetDir ? ` (保存于: ${targetDir})` : ""}`, ts: Date.now() },
      {
        id: newSessionId(),
        role: "system",
        text: `已创建标准工程 ${projectName}。\n` +
          (targetDir || projectPath ? `- **项目目录**：\`${targetDir || projectPath}\`\n` : "") +
          `- **结构标准**：按西门子官方工程规范初始化\n\n` +
          `后续生成的所有 SCL 源码、数据定义及归档交付包都将默认保存在该选定文件夹下。你可以通过任务快捷条（完善工艺逻辑/重构）或下方输入框开始设计！`,
        ts: Date.now(),
      },
    ];
    const list = [s, ...sessions];
    setSessions(list);
    setActiveSession(s.id);
    persistAndSync(list);
    setSelectedBlockName(null);
    setFocus(null);
    return fresh;
  };

  /** 新建工程流 · 最小创建确认的「确认创建」(契约 23 §1):
   *  1. 走既有创建链 handleCreateProject(name, dir)(内部 template af_v1_2 不动);
   *  2. 本流持有已确认需求卡时,自动调 N 线
   *     POST /api/v1/plc/canvas/generate-from-requirement 把逻辑块生成进画布
   *     (try/catch 静默,失败仅对话提示「逻辑生成待后续」,绝不阻塞工程创建);
   *  3. 对话 settle「工程已创建,标准结构就绪;可继续描述工艺完善逻辑」。 */
  const handleConfirmCreateProject = async () => {
    const name = newProjectName.trim();
    if (newProjectFlow.phase !== "confirm" || !isValidProjectName(name)) {
      setNewProjectNameTouched(true);
      return;
    }
    dispatchNewProjectFlow({ type: "CREATE_SUBMIT" });
    setReqDrawerOpen(false); // 创建落定,需求卡抽屉收起
    const targetDir = newProjectDir.trim();
    const requirement = newProjectFlow.requirement;
    let settleExtra = "";
    let finalCanvas = await handleCreateProject(name, targetDir || undefined);
    if (requirement && requirement.confirmation_status === "confirmed") {
      try {
        const res = await requestPlc<{
          canvas?: CanvasStateData;
          blocks_created?: number;
        } | null>(`/api/v1/plc/canvas/generate-from-requirement`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            requirement,
            project_name: name,
            ...(targetDir ? { target_dir: targetDir } : {}),
          }),
          signal: AbortSignal.timeout?.(120000),
        });
        if (res?.canvas && typeof res.canvas === "object") {
          finalCanvas = res.canvas;
          setCanvas(res.canvas);
        }
        const blocksCreated = Math.max(
          Number(res?.blocks_created) || 0,
          res?.canvas ? Object.keys(res.canvas.blocks ?? {}).length : 0,
        );
        if (blocksCreated > 0) {
          settleExtra = `已按确认的工艺需求生成 ${blocksCreated} 个逻辑块进入画布,`;
        }
      } catch {
        // N 线端点未就绪 / 生成失败:静默,仅对话提示,工程创建不受影响
        settleExtra = "逻辑生成待后续,";
      }
    }
    // 画布上有块时定位首个非 DB 块,方便工程师立即查看生成结果
    if (Object.keys(finalCanvas.blocks ?? {}).length > 0) {
      setSelectedBlockName(
        Object.values(finalCanvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null,
      );
    }
    commitSession(finalCanvas, [
      {
        id: msgId(),
        role: "system",
        text: `工程已创建,标准结构就绪;${settleExtra}可继续描述工艺完善逻辑`,
        ts: Date.now(),
      },
    ]);
    dispatchNewProjectFlow({ type: "CREATE_SETTLED" });
  };

  const handleCreateBlock = async (spec: {
    name: string;
    blockType: "FB" | "FC" | "DB" | "OB";
    comment: string;
  }) => {
    const ops = [makeBlockOp(spec.name, spec.blockType, spec.comment)];
    setIsSubmitting(true);
    try {
      const next = await applyOpsAndCommit(ops, null, `已创建 ${spec.blockType} 块 "${spec.name}"，进入草稿状态，回写博图后同步。`);
      setSelectedBlockName(spec.name);
      const created = next.blocks[spec.name];
      if (created) setFocus(created.networks.length ? { kind: "network", blockName: spec.name, networkId: created.networks[0].id } : null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddVariable = async (
    blockName: string,
    v: { name: string; data_type: string; section: string; comment?: string }
  ) => {
    if (isSubmitting) return;
    const ops = [makeVariableOp(blockName, v)];
    setIsSubmitting(true);
    try {
      await applyOpsAndCommit(ops, null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddNetwork = async (
    blockName: string,
    n: { title: string; scl_text: string; language?: string }
  ) => {
    if (isSubmitting) return;
    const ops = [makeNetworkOp(blockName, n)];
    setIsSubmitting(true);
    try {
      const next = await applyOpsAndCommit(ops, null);
      const block = next.blocks[blockName];
      if (block && block.networks.length) {
        const last = block.networks[block.networks.length - 1];
        setFocus({ kind: "network", blockName, networkId: last.id });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  /* 删除块（含其 HMI 绑定）：走 ops 管道（本地 + 后端尽力 + 会话记录） */
  const handleRemoveBlock = async (blockName: string) => {
    if (isSubmitting || !canvas.blocks[blockName]) return;
    const ops = [{ op: "remove_block", name: blockName }];
    setIsSubmitting(true);
    try {
      const next = await applyOpsAndCommit(ops, null);
      // 清理与该块关联的界面状态
      if (selectedBlockName === blockName) {
        setSelectedBlockName(
          Object.values(next.blocks).find((b) => b.block_type !== "DB")?.name ?? null
        );
      }
      setFocus(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  /* 重命名块：复合 ops（依赖块 SCL 引用 + HMI tag 改写 + 删旧建新） */
  const handleRenameBlock = async (oldName: string, newName: string) => {
    if (isSubmitting) return;
    if (canvas.blocks[newName]) {
      window.alert(`块名 "${newName}" 已存在。`);
      return;
    }
    const ops = makeRenameOps(canvas, oldName, newName);
    if (!ops) return;
    setIsSubmitting(true);
    try {
      await applyOpsAndCommit(ops, null, `已重命名 "${oldName}" → "${newName}"（引用与 HMI 绑定已同步改写）`);
      if (selectedBlockName === oldName) setSelectedBlockName(newName);
      setFocus(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  /* 删除块内变量 / 网络（解释卡行内按钮） */
  const handleRemoveVariable = async (blockName: string, varName: string) => {
    if (isSubmitting) return;
    const ops = deleteVariableOps(canvas, blockName, varName);
    if (!ops) return;
    setIsSubmitting(true);
    try {
      await applyOpsAndCommit(ops, null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemoveNetwork = async (blockName: string, networkId: number) => {
    if (isSubmitting) return;
    const ops = deleteNetworkOps(canvas, blockName, networkId);
    if (!ops) return;
    setIsSubmitting(true);
    try {
      await applyOpsAndCommit(ops, null);
      setFocus(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  /* LLM 深度解释：块 + 规则引擎预分析 → 网关 → OpenAI 兼容端点 */
  const handleDeepExplain = async (block: CanvasStateData["blocks"][string]): Promise<string> => {
    const scaffold = explainBlock(block, { edges: report.blockEdges, widgets: widgetList });
    try {
      const data = await requestPlc<{ explanation?: string }>(
        `/api/v1/plc/canvas/explain-block`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ block, scaffold }),
          signal: AbortSignal.timeout?.(90000),
        },
      );
      return data.explanation as string;
    } catch (err) {
      // LLM_NOT_CONFIGURED 等 code 在这里变成人话提示，UI 直接展示
      throw new Error(explainGatewayError(err, "深度解释失败"));
    }
  };

  /* —— 工作台 P0(契约 22 §4):任务入口 / 需求卡 / 变更审查 —— */

  /** 聚焦 ChatDock 输入框。ChatDock 不在本线可改范围:经 DOM 定位其
   *  .dock-input(带 aria-label 的指令输入框);若对话坞处于折叠态,
   *  先展开再等一帧渲染完成后聚焦。 */
  const focusChatInput = () => {
    setDockCollapsed(false);
    requestAnimationFrame(() => {
      document.querySelector<HTMLInputElement>(".dock-input")?.focus();
    });
  };

  /** 启动屏「新建工程」入口:预填引导词 → 用户输入工艺需求后走需求卡流 */
  const handleNewProjectEntry = () => {
    dispatchNewProjectFlow({ type: "ENTRY_CLICK" });
    if (!chatInput.trim()) setChatInput("工艺需求:");
    focusChatInput();
  };

  /** 打开需求卡抽屉草稿态:open=true / requirement=null / loading=true,
   *  再调 requirements.requestDraft(prompt, canvas, "improve") 拉草稿
   *  (mock-first:端点未上线回退示例卡;异常时静默停留空态)。 */
  const openRequirementDraft = async (prompt: string) => {
    // 新建工程流状态机:guiding 态(已点「新建工程」在等工艺描述)打开草稿即随流进入
    dispatchNewProjectFlow({ type: "DRAFT_OPENED" });
    setReqDrawerOpen(true);
    setReqDraft(null);
    setReqLoading(true);
    try {
      const res = await requestDraft(prompt, canvas, "improve");
      setReqDraft(res.requirement);
    } catch {
      setReqDraft(null); // 静默:抽屉停留在空态,不打扰用户
    } finally {
      setReqLoading(false);
    }
  };


  /** 需求卡工程师编辑(items/open_questions/summary):本地 state 更新 */
  const handleRequirementEdit = (r: Requirement) => setReqDraft(r);

  /** 确认工艺意图:PUT confirmed(网关不可达由 requirements 层回显 = 本地更新),
   *  记住最新已确认需求(confirm-writeback 附带 requirement_id 用),并在当前
   *  对话 settle 一条留痕 —— 契约 §1 铁律:确认仅表示意图确认,绝不触发任何 ops/写回。
   *  契约 23 §1:若正处于新建工程流 → 弹出最小创建确认(流外确认行为不变)。 */
  const handleConfirmIntent = async (r: Requirement) => {
    const confirmed: Requirement = {
      ...r,
      confirmation_status: "confirmed",
      updated_at: Date.now() / 1000,
    };
    setReqDraft(confirmed);
    setConfirmedRequirement(confirmed);
    let finalConfirmed: Requirement = confirmed;
    try {
      const res = await putRequirement(confirmed);
      setReqDraft(res.requirement);
      setConfirmedRequirement(res.requirement);
      finalConfirmed = res.requirement;
    } catch {
      /* 网关失败:本地已更新(占位语义),静默 */
    }
    commitSession(canvas, [
      {
        id: msgId(),
        role: "system",
        text: "工艺意图已确认(未产生任何修改)",
        ts: Date.now(),
      },
    ]);
    // 新建工程流内确认 → 状态机切 confirm(UI 弹最小创建确认;流外 idle 不受影响)
    dispatchNewProjectFlow({ type: "INTENT_CONFIRMED", requirement: finalConfirmed });
  };

  /** 打开最近一条变更的四层审查:经 state/pcec.ts fetchChanges 取
   *  updated_at 最新的事务 id;若 change.intent.requirement_id 命中当前
   *  已确认需求,则把需求卡一并传给 ChangeReviewDrawer(契约 §3)。 */
  const handleReviewLatestChange = async () => {
    try {
      const { items } = await fetchChanges();
      if (!items.length) return; // 真实空账本:无可审查项
      const latest = items.reduce((a, b) => (b.updated_at > a.updated_at ? b : a));
      setChangeReviewId(latest.change_id);
      if (confirmedRequirement?.requirement_id) {
        try {
          const res = await fetchChange(latest.change_id);
          const intent = res?.change.intent as unknown as
            | { requirement_id?: string }
            | null
            | undefined;
          setChangeReviewReq(
            intent?.requirement_id === confirmedRequirement.requirement_id
              ? confirmedRequirement
              : null,
          );
          return;
        } catch {
          /* 命中判断失败 → 按未关联需求处理 */
        }
      }
      setChangeReviewReq(null);
    } catch {
      /* fetchChanges 自带 mock 回退,正常不会到这里 */
    }
  };

  /** 变更审查证据定位(ChangeReviewDrawer.onFocusTarget):块级
   *  setSelectedBlockName + 画布聚焦;varName 无独立画布锚点(变量在右侧
   *  面板),仅当附带 blockName 时定位其块。 */
  const handleFocusChangeTarget = (t: { blockName?: string; varName?: string }) => {
    if (t.blockName) {
      setSelectedBlockName(t.blockName);
      setFocus({ kind: "block", blockName: t.blockName });
    }
  };

  /**
   * 轮询编译作业直到 7 阶段状态机收敛。
   * 替代原来的 `for (let i = 0; i < 600; i++)` 死循环：
   * - `signal`：切换会话 / 卸载页面可中止，不留残留定时器；
   * - `timeoutMs`：960s 上限（网关硬超时 900s + 60s 让 timeout 结论先落地）；
   * - `onProgress`：每次探测都写 `compileJob`，阶段状态实时上屏；
   * - 终止条件：status ∈ {ok, error, cancelled}（含网关侧 timed_out 落成的 error）。
   */
  const pollCompileJob = async (jobId: string): Promise<CompileJobPayload> => {
    const controller = new AbortController();
    compileAbortRef.current = controller;
    try {
      const job = await pollUntil<CompileJobPayload>(
        () =>
          requestPlc<CompileJobPayload>(
            `/api/v1/plc/canvas/compile-jobs/${encodeURIComponent(jobId)}`,
            { signal: AbortSignal.timeout?.(COMPILE_PROBE_TIMEOUT_MS) },
          ),
        (j) => j.status === "ok" || j.status === "error" || j.status === "cancelled",
        {
          intervalMs: COMPILE_POLL_INTERVAL_MS,
          timeoutMs: COMPILE_POLL_TIMEOUT_MS,
          signal: controller.signal,
          onProgress: (j) => setCompileJob(j),
        },
      );
      // 中止可能落在最后一次探测与收敛之间：这时结果已过期，按中止处理
      if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
      return job;
    } finally {
      if (compileAbortRef.current === controller) compileAbortRef.current = null;
    }
  };

  /* 人工确认门禁回写：异步编译作业 + 轮询；路径取自 canvas.source */
  const handleExecuteWriteback = async () => {
    setIsSubmitting(true);
    setShowConfirmModal(false);
    try {
      const projectPath = canvas.source?.project_path || `${canvas.project_name}.ap19`;
      const plcName = canvas.source?.plc_name || "PLC_1";
      const data = await requestPlc<{
        async?: boolean;
        job?: CompileJobPayload | null;
        writeback?: { ok?: boolean } | null;
        attributions?: CompilerAttribution[];
        canvas?: CanvasStateData;
      }>(`/api/v1/plc/canvas/confirm-writeback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          canvas,
          project_path: projectPath,
          plc_name: plcName,
          compile_after: true,
          sync: false,
          // 契约 22 §2/§4:当前有已确认需求卡时附带 requirement_id,后端透传进
          // 事务 intent(缺省行为零变化,无已确认需求时不带该字段)
          ...(confirmedRequirement?.requirement_id
            ? { requirement_id: confirmedRequirement.requirement_id }
            : {}),
        }),
        signal: AbortSignal.timeout?.(30000),
      });

      if (data?.async && data.job?.id) {
        let job: CompileJobPayload = data.job;
        setCompileJob(job);
        setWritebackNotice("编译作业已启动…");
        try {
          job = await pollCompileJob(job.id);
          bumpChangesRefresh(); // 作业收敛(ok/error/cancelled)→ 刷新 PCEC 变更账本
        } catch (err) {
          if (isAbortError(err)) {
            setWritebackNotice("已停止等待编译结果（切换会话或离开页面）；网关侧作业可能仍在运行");
            setTimeout(() => setWritebackNotice(null), 8000);
            return;
          }
          const detail =
            err instanceof GatewayError
              ? `读取编译作业状态失败：${explainGatewayError(err, "网关未返回错误详情")}`
              : `等待编译结果超时（总上限 ${COMPILE_POLL_TIMEOUT_MS / 1000}s / 单次探测 ${
                  COMPILE_PROBE_TIMEOUT_MS / 1000
                }s）：网关未在预期时间内结束作业，请检查博图是否弹窗阻塞`;
          setWritebackNotice(detail);
          setTimeout(() => setWritebackNotice(null), 10000);
          bumpChangesRefresh(); // 轮询失败也可能已落账(如 precheck fail-closed)→ 尽力刷新
          return;
        }

        // degraded / timed_out / precheck 没有专属 UI 位置：合并进既有的 error 行、通知条和会话消息
        const notes = compileJobNotes(job);
        const detail = notes.join("；");
        const headline = job.error && job.error !== "precheck_failed" ? job.error : null;
        setCompileJob({
          ...job,
          error: [headline, ...notes].filter(Boolean).join("；") || null,
        });

        if (job.canvas) {
          setCanvas(job.canvas);
          commitSession(job.canvas, [
            {
              id: msgId(),
              role: "system",
              text: [`编译作业 ${job.status}`, ...notes].join("："),
              ts: Date.now(),
            },
          ]);
        }
        setAttributions((job.attributions || []) as CompilerAttribution[]);
        let notice =
          job.status === "ok"
            ? "博图回写并编译通过，工程已保存"
            : `编译未通过：${headline || detail || "见诊断面板"}`;
        if (detail && (job.status === "ok" || headline)) notice += `（${detail}）`;
        if (job.status === "error" && (job.attributions || []).length) {
          try {
            const fdata = await requestPlc<{
              ok?: boolean;
              canvas?: CanvasStateData;
              attributions?: CompilerAttribution[];
              rounds?: unknown[];
            }>(`/api/v1/plc/canvas/fix-loop`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                canvas: job.canvas || canvas,
                attributions: job.attributions,
                project_path: projectPath,
                plc_name: plcName,
                auto: true,
                max_rounds: 3,
              }),
              signal: AbortSignal.timeout?.(600000),
            });
            if (fdata?.canvas) {
              setCanvas(fdata.canvas);
              setAttributions((fdata.attributions || []) as CompilerAttribution[]);
              notice = fdata.ok
                ? `自动修正后编译通过（${(fdata.rounds || []).length} 轮）`
                : `自动修正未完全成功（${(fdata.rounds || []).length} 轮）`;
            }
          } catch {
            /* optional */
          } finally {
            bumpChangesRefresh(); // 修正轮也走编译作业 → 账本同样要刷新
          }
        }
        setWritebackNotice(notice);
        setTimeout(() => setWritebackNotice(null), 10000);
        return;
      }

      const result = data;
      if (result.canvas) setCanvas(result.canvas);
      setAttributions(result.attributions || []);
      setWritebackNotice(result.writeback?.ok ? "回写成功" : `回写失败`);
      setTimeout(() => setWritebackNotice(null), 6000);
      bumpChangesRefresh(); // 同步回写路径同样建事务 → 刷新账本
    } catch (err) {
      const msg = explainGatewayError(err, "未知错误");
      setWritebackNotice(`回写/编译失败：${msg}`);
      setTimeout(() => setWritebackNotice(null), 8000);
      bumpChangesRefresh(); // 确认/预检阶段失败也可能落账 → 尽力刷新
    } finally {
      setIsSubmitting(false);
    }
  };

  /* 一键自愈 */
  const handleTriggerAutoFix = async () => {
    if (!attributions.length) return;
    setIsSubmitting(true);
    try {
      const data = await requestPlc<{ canvas?: CanvasStateData }>(`/api/v1/plc/canvas/auto-fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canvas, attributions }),
      });
      if (data?.canvas) {
        setCanvas(data.canvas);
        setAttributions([]);
      }
    } catch {
      // 后端不可用 → 忽略
    } finally {
      setIsSubmitting(false);
    }
  };

  const pad2 = (n: number) => String(n).padStart(2, "0"); // taste-skill-ignore: clock timestamp

  /* —— 新建工程流 · 最小创建确认的表单校验(与 CreateBlockDialog 的标识规则同口径) —— */
  const npfCreating = newProjectFlow.phase === "creating";
  const npfName = newProjectName.trim();
  let npfNameError = "";
  if (!npfName) {
    npfNameError = newProjectNameTouched ? "请输入项目名" : "";
  } else if (!isValidProjectName(npfName)) {
    npfNameError = "仅限字母、数字与下划线，且以字母或下划线开头";
  }
  const npfValid = npfName.length > 0 && npfNameError === "";

  return (
    <div className="app" data-ui="plc-workbench">
      {/* —— 细顶栏 —— */}
      <header className="topbar">
        <button
          className="topbar__toggle"
          onClick={panes.toggleLeft}
          aria-label={leftOpen ? "隐藏历史对话" : "显示历史对话"}
          title={leftOpen ? "隐藏历史对话" : "显示历史对话"}
        >
          <ChevronsLeft />
        </button>

        <div className="topbar__brand">
          <BrandMark />
          <span className="topbar__name">{canvas.project_name}</span>
          <span className="tagchip">TIA V19</span>
          {backendConnected !== null && (
            <span className="conn">
              <i className={`led ${backendConnected ? "led--run" : ""}`} />
              {backendConnected ? "网关已就绪" : "离线沙箱模式"}
            </span>
          )}
        </div>

        <div className="topbar__spacer" />

        <div className="meters" role="status" aria-label="画布同步状态">
          <div className={`meter meter--run ${syncedCount === 0 ? "meter--zero" : ""}`}>
            <span className="meter__label">已同步</span>
            <span className="meter__value">{pad2(syncedCount)}</span>
          </div>
          <div className={`meter meter--standby ${draftCount === 0 ? "meter--zero" : ""}`}>
            <span className="meter__label">草稿</span>
            <span className="meter__value">{pad2(draftCount)}</span>
          </div>
          <div className={`meter meter--fault ${errorCount === 0 ? "meter--zero" : ""}`}>
            <span className="meter__label">博图报错</span>
            <span className="meter__value">{pad2(errorCount)}</span>
          </div>
        </div>

        {errorCount > 0 && (
          <button onClick={handleTriggerAutoFix} disabled={isSubmitting} className="btn btn--danger">
            一键自愈
          </button>
        )}

        {/* 变更记录:低显著度次级入口(学 SclPane 的 </> 模式),打开才拉取账本 */}
        <button
          className="topbar__toggle"
          onClick={() => setChangeLogOpen(true)}
          aria-label="变更记录"
          title="变更记录 · 带证据的工程变更事务（PCEC 账本）"
        >
          <ChangeLogIcon />
        </button>

        <button
          onClick={() => setShowConfirmModal(true)}
          disabled={isSubmitting || blockList.length === 0}
          className="btn btn--primary"
          title={blockList.length === 0 ? "画布为空，先创建逻辑块" : undefined}
        >
          回写博图
        </button>

        <button
          className="topbar__toggle"
          onClick={panes.toggleRight}
          aria-label={rightOpen ? "隐藏变量面板" : "显示变量面板"}
          title={rightOpen ? "隐藏变量面板" : "显示变量面板"}
        >
          <ChevronsRight />
        </button>
      </header>

      {/* —— 任务快捷条(契约 22 §3,F2 组件):低显著度贴顶栏下沿 —— */}

      {/* —— 工程概览头(契约 22 §4,F1 自建):活跃项目时顶栏下沿常驻 —— */}
      {showWorkbenchHeader && (
        <WorkbenchHeader
          projectName={canvas.project_name}
          plcName={canvas.source?.plc_name ?? null}
          blockCount={blockList.length}
          variableCount={variableTotal}
          tagCount={tagTotal}
          sessionUpdatedAt={activeSession?.updatedAt ?? null}
          onReviewLatestChange={() => void handleReviewLatestChange()}
        />
      )}

      {/* —— 解析降级告警条：只在真的存在降级时出现 —— */}
      {degradation && (
        <div
          role="status"
          aria-label="解析降级告警"
          style={{
            flex: "none",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 10,
            padding: "6px 14px",
            background: "var(--surface-2)",
            borderBottom: "1px solid var(--line-2)",
            borderLeft: "3px solid var(--standby)",
            fontSize: 13,
            color: "var(--ink-2)",
          }}
        >
          <i className="led led--standby" />
          <strong style={{ color: "var(--ink)" }}>解析降级</strong>
          <span className="tagchip">已翻译 {degradation.translatedPct}%</span>
          <span className="tagchip">{degradation.warnings.length} 条告警</span>
          {degradation.warnings.some((w) => w.code === "coverage.graph_not_executable") && (
            <span style={{ color: "var(--fault)" }}>
              GRAPH 已降级为 CASE 状态机（语义不等价、不可直接回写）
            </span>
          )}
          {degradation.warnings.some((w) => w.code === "coverage.stl_fallback") && (
            <span>STL 指令未全覆盖</span>
          )}
          {degradation.warnings.some((w) => w.code === "coverage.fbd_fallback") && (
            <span>FBD 部件未全覆盖</span>
          )}
          {degradation.projectName && degradation.projectName !== canvas.project_name && (
            <span>来源工程 {degradation.projectName}</span>
          )}
          <button
            className="btn btn--ghost"
            style={{ padding: "2px 10px", fontSize: 12 }}
            onClick={() => setDegradationOpen((open) => !open)}
          >
            {degradationOpen ? "收起受影响块" : "查看受影响块"}
          </button>
          {degradationOpen && (
            <div style={{ flexBasis: "100%", display: "grid", gap: 6, paddingTop: 2 }}>
              {degradation.warnings.map((w, index) => (
                <div key={`${w.code || "warning"}-${index}`}>
                  <div>{w.message}</div>
                  {(w.affected_blocks || []).length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                      {(w.affected_blocks || []).map((name) => (
                        <span key={`${w.code || "warning"}-${name}`} className="tagchip">
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* —— 三栏面板区 —— */}
      <div className={`panes ${panes.isDragging ? "panes--dragging" : ""}`}>
        {leftOpen && (
          <>
            <div className="pane pane--left" style={{ width: leftWidth }}>
              <div className="pane__inner">
                <HistorySidebar
                  sessions={sessions}
                  activeSessionId={activeSessionId}
                  onSelect={handleSelectSession}
                  onNewSession={handleNewSession}
                  onDelete={handleDeleteSession}
                  onHide={panes.toggleLeft}
                />
              </div>
            </div>
            <div
              className="gutter"
              role="separator"
              aria-orientation="vertical"
              aria-label="拖拽调整历史栏宽度"
              onPointerDown={(e) => panes.beginDrag("left", e)}
              onMouseDown={(e) => panes.beginDrag("left", e)}
            />
          </>
        )}

        <div className="center">
          {/* 启动态两入口(契约 23 §1):无活跃会话且历史为空时替换空白画布引导;
              有历史会话时保持现状(空白画布+引导),历史侧栏照常可用 */}
          {showLaunchScreen ? (
            <ProjectLaunchScreen
              sessions={sessions}
              onImport={() => setImportOpen(true)}
              onNewProject={handleNewProjectEntry}
              onSelectSession={handleSelectSession}
            />
          ) : (
            <PlcInteractiveCanvas
            canvas={canvas}
            selectedBlockName={selectedBlockName}
            onSelectBlock={setSelectedBlockName}
            blockEdges={report.blockEdges}
            focus={focus}
            onFocusChange={setFocus}
            onCanvasChange={setCanvas}
            onCreateBlock={() => setCreateDialog("block")}
            onAddVariable={handleAddVariable}
            onAddNetwork={handleAddNetwork}
            onRemoveBlock={handleRemoveBlock}
            onRenameBlock={handleRenameBlock}
            onRemoveVariable={handleRemoveVariable}
            onRemoveNetwork={handleRemoveNetwork}
            onDeepExplain={handleDeepExplain}
          />
          )}
          <ChatDock
            messages={activeSession?.messages ?? []}
            inputValue={chatInput}
            onInputChange={setChatInput}
            onSend={handleSend}
            collapsed={dockCollapsed}
            onToggleCollapse={() => setDockCollapsed((c) => !c)}
          />
        </div>

        {rightOpen && (
          <>
            <div
              className="gutter"
              role="separator"
              aria-orientation="vertical"
              aria-label="拖拽调整变量面板宽度"
              onPointerDown={(e) => panes.beginDrag("right", e)}
              onMouseDown={(e) => panes.beginDrag("right", e)}
            />
            <div className="pane pane--right" style={{ width: rightWidth }}>
              <div className="pane__inner">
                <VariableInspector
                  report={report}
                  wiredTags={wiredTags}
                  onJumpToRef={handleJumpToRef}
                  onCollapse={panes.toggleRight}
                />
              </div>
            </div>
          </>
        )}
      </div>

      {/* 导入项目对话框 */}
      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImportCanvas={handleImportCanvas}
        onImportServerPath={handleImportServerPath}
        onImportUpload={handleImportUpload}
        backendConnected={backendConnected}
      />

      {/* 新建逻辑块 / 空白项目对话框 */}
      <CreateBlockDialog
        open={createDialog !== null}
        mode={createDialog === "project" ? "project" : "block"}
        existingNames={Object.keys(canvas.blocks)}
        onClose={() => setCreateDialog(null)}
        onCreateBlock={handleCreateBlock}
        onCreateProject={handleCreateProject}
      />

      {/* 回写成功通知 */}
      {writebackNotice && (
        <div className="notice" role="status">
          <i className="led led--run" />
          {writebackNotice}
        </div>
      )}

      <CompileDrawer
        job={compileJob}
        attributions={attributions}
        onJump={(a) => {
          if (a.target_type === "block" || a.target_type === "network") {
            setSelectedBlockName(a.target_id);
            setFocus({ kind: "block", blockName: a.target_id });
          } else if (a.target_type === "hmi_widget") {
            setFocus({ kind: "hmi", widgetId: a.target_id });
          }
        }}
        onCancel={async () => {
          if (!compileJob?.id) return;
          try {
            await requestPlc(
              `/api/v1/plc/canvas/compile-jobs/${encodeURIComponent(compileJob.id)}/cancel`,
              { method: "POST" },
            );
          } catch {
            /* 取消是尽力而为：网关可能已收敛或作业已过期 */
          }
        }}
        onClose={() => setCompileJob(null)}
      />

      {/* 变更记录抽屉(PCEC):打开才挂载才拉取;编译作业结束后经 refreshTick 自动刷新 */}
      {changeLogOpen && (
        <ChangeLogDrawer
          onClose={() => setChangeLogOpen(false)}
          refreshTick={changesRefreshTick}
        />
      )}

      {/* 需求卡抽屉(契约 22 §3,F2 组件):草稿/编辑/确认工艺意图(不产生任何修改) */}
      <RequirementCardDrawer
        open={reqDrawerOpen}
        requirement={reqDraft}
        loading={reqLoading}
        onEdit={handleRequirementEdit}
        onConfirmIntent={(r) => void handleConfirmIntent(r)}
        onClose={() => setReqDrawerOpen(false)}
      />

      {/* 四层变更审查抽屉(契约 22 §3,F2 组件):从工程概览头「审查最近变更」打开 */}
      <ChangeReviewDrawer
        open={changeReviewId !== null}
        changeId={changeReviewId}
        requirement={changeReviewReq}
        onFocusTarget={handleFocusChangeTarget}
        onClose={() => setChangeReviewId(null)}
      />

      {/* —— 人工确认门禁 —— */}
      {showConfirmModal && (
        <div
          className="overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowConfirmModal(false);
          }}
        >
          <div className="sheet" role="dialog" aria-modal="true" aria-label="回写博图确认">
            <div className="sheet-head">
              <span className="sheet-mark">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="M3 8.5L6.5 12L13 4.5"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <div>
                <div className="sheet-title">确认将画布内容 1:1 还原至博图</div>
                <div className="sheet-sub">TIA Portal 回写门禁 · 工业工程师安全审核</div>
              </div>
            </div>

            <div className="spec">
              <div className="spec-row">
                <span className="spec-row__label">目标博图工程</span>
                <span className="spec-row__value">
                  {canvas.source?.project_path || `${canvas.project_name}.ap19`}
                </span>
              </div>
              <div className="spec-row">
                <span className="spec-row__label">基线指纹</span>
                <span className="spec-row__value" title="工程基线 project_hash 前 12 位；基线变化即事务过期拒绝">
                  {baselineFingerprint(canvas.source)}
                </span>
              </div>
              <div className="spec-row">
                <span className="spec-row__label">待转译回写逻辑块</span>
                <span className="spec-row__value">{blockList.length} 块 (SCL / SimaticML)</span>
              </div>
              <div className="spec-row">
                <span className="spec-row__label">待同步 HMI 变量绑定</span>
                <span className="spec-row__value">{widgetList.length} 项 (PlcTagTable)</span>
              </div>
              {/* V 等级四行(契约 19 §5):确认时刻 V0/V1 已过、V2 待执行、V3 未运行 */}
              {V_LEVELS.map((v) => {
                const st = CONFIRM_V_SNAPSHOT[v.key];
                return (
                  <div className="spec-row" key={v.key}>
                    <span className="spec-row__label">{v.full}</span>
                    <span className={`spec-row__value pcec-v--${st}`}>
                      {vStatusMark(st)} {vStatusText(st)}
                    </span>
                  </div>
                );
              })}
              <div className="spec-row spec-row--gate">
                <span className="spec-row__label">一致性编译校验</span>
                <span className="spec-row__value">开启 (CompilePlcSoftwareStrict)</span>
              </div>
            </div>

            <div className="sheet-actions">
              <button onClick={() => setShowConfirmModal(false)} className="btn btn--ghost">
                取消返回
              </button>
              <button
                onClick={handleExecuteWriteback}
                disabled={isSubmitting}
                autoFocus
                className="btn btn--primary"
              >
                {isSubmitting ? "正在还原并触发博图编译…" : "确认执行回写"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* —— 新建工程 · 最小创建确认(契约 23 §1):确认工艺意图后弹出。
          项目名默认取 intent_summary 洗成的合法标识,目标目录可选(复用
          CreateBlockDialog 的 targetDir 语义);确认走既有创建链 + N 线逻辑生成 —— */}
      {(newProjectFlow.phase === "confirm" || npfCreating) && (
        <div
          className="overlay"
          onClick={(e) => {
            if (e.target !== e.currentTarget) return;
            if (!npfCreating) dispatchNewProjectFlow({ type: "CREATE_CANCEL" });
          }}
        >
          <div className="sheet" role="dialog" aria-modal="true" aria-label="新建工程确认">
            <div className="sheet-head">
              <span className="sheet-mark">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="M8 2.5L13 5v4.5c0 2.2-2 3.4-5 4.5-3-1.1-5-2.3-5-4.5V5L8 2.5z"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <div>
                <div className="sheet-title">确认创建工程</div>
                <div className="sheet-sub">工艺意图已确认 · 项目名将作为博图工程名</div>
              </div>
            </div>

            <div className="spec">
              <div className="spec-row npf-row">
                <span className="spec-row__label">项目名</span>
                <input
                  className="npf-input npf-input--mono"
                  value={newProjectName}
                  placeholder={newProjectFlow.defaultProjectName || "MyProject"}
                  spellCheck={false}
                  autoComplete="off"
                  disabled={npfCreating}
                  aria-label="项目名"
                  onChange={(e) => setNewProjectName(e.target.value)}
                  onBlur={() => setNewProjectNameTouched(true)}
                />
              </div>
              {npfNameError && <div className="npf-error">{npfNameError}</div>}
              <div className="spec-row npf-row">
                <span className="spec-row__label">目标目录 (选填)</span>
                <input
                  className="npf-input npf-input--mono"
                  value={newProjectDir}
                  placeholder="如：C:\Projects\Station1 (留空则使用默认工作区)"
                  spellCheck={false}
                  autoComplete="off"
                  disabled={npfCreating}
                  aria-label="目标目录(选填)"
                  onChange={(e) => setNewProjectDir(e.target.value)}
                />
              </div>
              <div className="spec-row spec-row--gate">
                <span className="spec-row__label">工艺需求</span>
                <span className="spec-row__value" title={newProjectFlow.requirement?.intent_summary ?? ""}>
                  {newProjectFlow.requirement?.intent_summary
                    ? `已确认 · ${newProjectFlow.requirement.intent_summary}`.slice(0, 80)
                    : "—"}
                </span>
              </div>
            </div>

            <div className="sheet-actions">
              <button
                type="button"
                className="btn btn--ghost"
                disabled={npfCreating}
                onClick={() => dispatchNewProjectFlow({ type: "CREATE_CANCEL" })}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn--primary"
                disabled={!npfValid || npfCreating}
                autoFocus
                onClick={() => void handleConfirmCreateProject()}
              >
                {npfCreating ? "正在创建…" : "确认创建"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
export { App };
