import React, { useEffect, useMemo, useState } from "react";
import type { FocusTarget } from "./canvas/PlcInteractiveCanvas";
import { ChatDock } from "./shell/ChatDock";
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
/* 导入成功后自动生成工程简报 + 建议问题(briefing 纯函数,vitest 覆盖) */
import { buildBriefing, briefingToMessage } from "./state/briefing";
import {
  bootstrapRemoteMerge,
  hydrateRemoteSession,
  persistAndSync,
  syncSessionDelete,
} from "./state/sessionSync";
import { compressHistory } from "./state/historyContext";
/* L 线(契约 25 §2):画布面板 + 智能标签路由;工程一等实体类型来自 state/projects(P 线) */
import { WorkspacePanel } from "./shell/WorkspacePanel";
import { ProjectSidebar } from "./shell/ProjectSidebar";
import { OnboardingScreen } from "./shell/OnboardingScreen";
import {
  fetchProjects,
  fetchProject,
  fetchConversations,
  fetchConversation,
  createProject,
  createConversation,
  putProject,
  putConversation,
  migrateProjects,
  deleteProject as apiDeleteProject,
  deleteConversation as apiDeleteConversation,
  type ProjectMeta,
  type ConversationMeta,
} from "./state/projects";
import { extractMermaidSource, smartRoute, type CanvasTab } from "./shell/smartRoute";
import type { Project } from "./state/projects";
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
/* 重构流水线(纯函数层:意图解析/阶段进度/结果消息 + DTO 契约类型;
   网络请求仍按 /canvas/* 惯例留在本文件) */
import {
  parseRefactorIntent,
  pipelineProgressText,
  pipelineResultMessage,
  pipelineStageViews,
  type RefactorIntent,
  type RefactorPipelineJob,
  type RefactorPipelineRequestBody,
  type RefactorPipelineReport,
  type RefactorPipelineStage,
} from "./state/refactorPipeline";
import {
  activeTasks,
  finishTask,
  patchTask,
  sweepFinished,
  tasksBySession,
  upsertTask,
  LONG_TASK_LABELS,
  type LongTask,
  type LongTaskStatus,
} from "./state/longTasks";
import { buildOpsReview, type OpsReview } from "./state/opsReview";
import { LongTaskChips } from "./shell/LongTaskChips";

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

/** 作业轮询·两段式(真机实测:HR002 带编译流水线 27min,136 块全量写回 >1h;
 *  网关作业终态保留 1h(_JOB_RETENTION_S)。快段保交互灵敏,慢段撑满长编译,
 *  慢段总窗 60min 对齐保留期——超窗作业已被网关回收,再等也无结果)。
 *  旧 960s 单段上限会把仍在跑的作业误报成"等待失败"(真机案例 c0b2f7ff…)。 */
const POLL_FAST_INTERVAL_MS = 1_800;
const POLL_FAST_TIMEOUT_MS = 300_000; // 快段:前 5 分钟 1.8s/拍
const POLL_SLOW_INTERVAL_MS = 6_000; // 慢段:之后 6s/拍
const POLL_SLOW_TIMEOUT_MS = 3_600_000; // 慢段总窗 60min
const COMPILE_PROBE_TIMEOUT_MS = 15_000;
const REFACTOR_PIPELINE_PROBE_TIMEOUT_MS = 15_000;

/** 两段式轮询:快段超时(非中止)自动续慢段;慢段超时才真正抛错。
 *  中止(AbortError)原样上抛,保证会话切换/卸载语义不变。 */
async function pollUntilTwoPhase<T>(
  probe: () => Promise<T>,
  isDone: (value: T) => boolean,
  opts: { signal?: AbortSignal; onProgress?: (value: T) => void },
): Promise<T> {
  try {
    return await pollUntil(probe, isDone, {
      intervalMs: POLL_FAST_INTERVAL_MS,
      timeoutMs: POLL_FAST_TIMEOUT_MS,
      signal: opts.signal,
      onProgress: opts.onProgress,
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    return pollUntil(probe, isDone, {
      intervalMs: POLL_SLOW_INTERVAL_MS,
      timeoutMs: POLL_SLOW_TIMEOUT_MS,
      signal: opts.signal,
      onProgress: opts.onProgress,
    });
  }
}

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

/**
 * 任务引导前缀(契约 22 §4「任务流接线」):understand/diagnose/refactor 点击后
 * 预填进 ChatDock 输入框的引导词,仅是给 LLM 的任务语境提示,不改后端行为;
 * improve 不在此列 —— 它走需求卡草稿流(openRequirementDraft)。
 * 前缀词典集中在此,便于统一调整文案。
 */
/** 布局状态机(契约 25 §2 L 线):
 *  chat       纯对话全屏(默认,Gemini 式)
 *  split      对话(左,flex) + 画布(右,55% 起可拖)
 *  fullscreen 画布满铺 + 底部薄条对话输入(Esc 返回 split) */
type LayoutMode = "chat" | "split" | "fullscreen";

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

  /* —— L 线布局状态机(契约 25 §2):chat(默认)/split/fullscreen + 画布标签 —— */
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("chat");
  const [activeTab, setActiveTab] = useState<CanvasTab>("graph");

  /* 工程/对话管理(Gemini 式) */
  const [projectList, setProjectList] = useState<ProjectMeta[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [conversationList, setConversationList] = useState<ConversationMeta[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  /** P 线接线(契约 25 §1):activeProjectId 的 ref 镜像——commitSession 等闭包里
   *  读最新值做画布回写,与 activeSessionIdRef 同一手法 */
  const activeProjectIdRef = React.useRef<string | null>(null);
  const setActiveProject = (pid: string | null) => {
    activeProjectIdRef.current = pid;
    setActiveProjectId(pid);
  };
  /** 会话 ↔ P 线对话映射:本地会话 id → conversation_id(导入/新建注册时写入,
   *  侧栏选中服务端对话时反查本地会话;服务端对话水合进来后两端同 id) */
  const sessionConvMapRef = React.useRef<Map<string, string>>(new Map());
  /** 画布权威回写防抖句柄(putProject fire-and-forget,800ms 合并高频提交) */
  const projectCanvasSyncTimer = React.useRef<number | null>(null);
  /* —— LongTaskCenter(统一长任务中心):重构流水线/编译回写/AI 分析共用的
     任务登记。任务跟随自己的 sessionId 跑完(切会话不中止),结果写回所属
     会话;顶栏芯片 + 对话坞任务卡渲染同一份数据。 —— */
  const [longTasks, setLongTasks] = useState<LongTask[]>([]);
  const longTasksRef = React.useRef<LongTask[]>([]);
  longTasksRef.current = longTasks;
  /** 登记/补丁/收终态小工具(全部走纯函数 upsert/patch/finish,读最新 ref 防闭包过期) */
  const registerTask = (task: LongTask) => setLongTasks((prev) => upsertTask(prev, task));
  const patchLongTask = (id: string, patch: Partial<LongTask>) =>
    setLongTasks((prev) => patchTask(prev, id, patch));
  const finishLongTask = (id: string, status: LongTaskStatus, errorText?: string) =>
    setLongTasks((prev) => finishTask(prev, id, status, errorText));
  /* 终态收尾窗口:结束后保留 2.5s 供芯片/卡片显示绿色收尾,随后清扫 */
  useEffect(() => {
    if (!longTasks.some((t) => t.status !== "running")) return;
    const t = window.setTimeout(() => setLongTasks((prev) => sweepFinished(prev)), 2600);
    return () => window.clearTimeout(t);
  }, [longTasks]);
  /* 浏览器标签标题:有任务在跑时给出页面级提示 */
  useEffect(() => {
    const running = activeTasks(longTasks);
    document.title = running.length
      ? `● ${running[0].title} 进行中 — PLC Co-Pilot`
      : "PLC Co-Pilot · 数字孪生画布与博图闭环工作台";
  }, [longTasks]);
  /** split 态画布宽度占主区百分比:初始 55%,拖拽调整,最小 20% */
  const [canvasPct, setCanvasPct] = useState(55);
  const [draggingCanvas, setDraggingCanvas] = useState(false);
  const splitRef = React.useRef<HTMLDivElement | null>(null);
  /** 最新一份 Mermaid 源码(画布时序图标签数据源,AI 回答 settle 时更新) */
  const [latestMermaid, setLatestMermaid] = useState<string | null>(null);
  /** 画布内嵌变更审查(与对话内弹出的 ChangeReviewDrawer 分账,避免双开) */
  const [canvasReviewId, setCanvasReviewId] = useState<string | null>(null);
  const [canvasReviewReq, setCanvasReviewReq] = useState<Requirement | null>(null);
  /**
   * 工程一等实体占位(契约 25 §1,P 线接线):当前画布所属工程。
   * P 线 projects API 就绪后由它供给;此刻恒为 null,L 线不依赖非空假设。
   */
  const activeProject = useMemo<Project | null>(() => null, []);
  void activeProject;

  /** [画布]顶栏按钮:chat→split 展开;split→chat 收起;fullscreen→split 还原 */
  const toggleCanvasPane = () => {
    setLayoutMode((mode) => (mode === "chat" ? "split" : mode === "fullscreen" ? "split" : "chat"));
  };

  /** fullscreen 态 Esc → 返回 split(契约 §2) */
  useEffect(() => {
    if (layoutMode !== "fullscreen") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLayoutMode("split");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [layoutMode]);

  /** split 态分隔线拖拽:按主区宽度换算画布百分比,夹在 20%~85% */
  const onCanvasGutterDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDraggingCanvas(true);
  };
  const onCanvasGutterMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingCanvas || !splitRef.current) return;
    const rect = splitRef.current.getBoundingClientRect();
    const pct = ((rect.right - e.clientX) / rect.width) * 100;
    setCanvasPct(Math.min(85, Math.max(20, pct)));
  };
  const onCanvasGutterUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setDraggingCanvas(false);
  };

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

  /** 在飞的重构流水线轮询：与编译轮询同规则——切换会话 / 卸载页面时中止，
      避免过期结果写入新会话、占位消息永远停在"进行中" */
  const refactorAbortRef = React.useRef<AbortController | null>(null);
  const abortRefactorPoll = React.useCallback(() => {
    refactorAbortRef.current?.abort();
    refactorAbortRef.current = null;
  }, []);
  useEffect(() => abortRefactorPoll, [abortRefactorPoll]);
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

  /* 变量交叉引用分析 */
  const report = useMemo(() => analyzeCanvas(canvas), [canvas]);
  const wiredTags = useMemo(() => Object.values(canvas.tags), [canvas.tags]);

  /* 状态统计 */
  const blockList = useMemo(() => Object.values(canvas.blocks), [canvas.blocks]);
  /** 块名清单(ChatDock 消息里的块名可点击化:blockRefs.linkifyBlockNames 的字典) */
  const blockNameList = useMemo(() => Object.keys(canvas.blocks), [canvas.blocks]);
  const widgetList = useMemo(() => Object.values(canvas.hmi_widgets), [canvas.hmi_widgets]);
  const draftCount =
    blockList.filter((b) => b.status === "draft").length +
    widgetList.filter((w) => w.status === "draft").length;

  /** 画布草稿块计数(供智能路由在异步 settle 后读到最新值,避免闭包过期) */
  const draftCountOf = (c: CanvasStateData) =>
    Object.values(c.blocks).filter((b) => b.status === "draft").length +
    Object.values(c.hmi_widgets).filter((w) => w.status === "draft").length;
  const draftCountRef = React.useRef(draftCount);
  useEffect(() => {
    draftCountRef.current = draftCount;
  }, [draftCount]);

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

  /* 画布最新引用镜像:长任务(编译/重构流水线)完成时读它做"脏守卫"——
   * 任务运行期间用户又改了画布(对象已换)时,结果不再自动覆盖画布。 */
  const canvasRef = React.useRef(canvas);
  canvasRef.current = canvas;
  /** 会话列表镜像:P 线对话消息同步读最新会话(标题/消息/updatedAt) */
  const sessionsRef = React.useRef(sessions);
  sessionsRef.current = sessions;
  /** 回写在飞防重入(独立于对话输入锁:编译耗时可达数十分钟,不许占住聊天) */
  const writebackInFlightRef = React.useRef(false);

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
    scheduleProjectCanvasSync(nextCanvas);
    if (!activeSessionIdRef.current) {
      setActiveSession(pendingId);
      return pendingId;
    }
    return activeSessionIdRef.current;
  };

  /** 顶栏长任务芯片点击:跳回任务所属会话(需要时切回分栏)并滚动到锚定消息 */
  const handleJumpToLongTask = (task: LongTask) => {
    if (!sessions.some((s) => s.id === task.sessionId)) return;
    if (layoutMode === "fullscreen") setLayoutMode("split");
    setDockCollapsed(false);
    handleSelectSession(task.sessionId);
    if (task.messageId) {
      window.setTimeout(() => {
        document
          .querySelector(`[data-mid="${CSS.escape(task.messageId || "")}"]`)
          ?.scrollIntoView({ block: "center", behavior: "smooth" });
      }, 320);
    }
  };

  /** 后台长任务的结果写回"它所属的会话"(用户可能已切走):
   *  只更新目标会话的消息与画布快照;会话不存在(已删)则静默跳过。
   *  与 commitSession 的差别:不新建会话、不动当前激活态。 */
  const commitSessionFor = (sessionId: string, nextCanvas: CanvasStateData, msgs: ChatMessage[]) => {
    setSessions((prev) => {
      const cur = prev.find((s) => s.id === sessionId);
      if (!cur) return prev; // 会话已删除:结果无处落,静默
      const list = [
        { ...cur, messages: msgs.length ? [...cur.messages, ...msgs] : cur.messages, updatedAt: Date.now(), canvas: nextCanvas },
        ...prev.filter((s) => s.id !== sessionId),
      ];
      persistAndSync(list);
      return list;
    });
  };

  /* ---------------- P 线接线(契约 25 §1):工程一等实体 ---------------- */

  /** 画布权威回写(防抖 800ms 合并):活跃工程存在时 fire-and-forget putProject,
   *  同时把活跃会话的消息 upsert 进 P 线对话(putConversation)——没有这步,
   *  侧栏工程树里的对话永远是空壳,点进去(尤其跨设备水合)看不到历史消息。
   *  失败静默——本地 localStorage 仍是第一层,服务端只是工程容器权威副本。 */
  const scheduleProjectCanvasSync = (nextCanvas: CanvasStateData) => {
    const pid = activeProjectIdRef.current;
    if (!pid) return;
    if (projectCanvasSyncTimer.current != null) window.clearTimeout(projectCanvasSyncTimer.current);
    projectCanvasSyncTimer.current = window.setTimeout(() => {
      projectCanvasSyncTimer.current = null;
      void putProject({
        id: pid,
        name: nextCanvas.project_name || pid,
        updatedAt: Date.now(),
        canvas: nextCanvas,
      });
      const sid = activeSessionIdRef.current;
      const convId = sid ? sessionConvMapRef.current.get(sid) : undefined;
      const session = sid ? sessionsRef.current.find((s) => s.id === sid) : undefined;
      if (convId && session) {
        void putConversation({
          id: convId,
          projectId: pid,
          title: session.title || "新对话",
          createdAt: session.createdAt ?? session.updatedAt,
          updatedAt: Date.now(),
          messages: session.messages,
        });
      }
    }, 800);
  };

  /** 导入/新建后把工程与首对话注册到服务端(P 线),并接进侧栏:
   *  - createProject(name, canvas) + createConversation → 两个列表即时更新;
   *  - 本地会话 id ↔ conversation_id 记入映射,侧栏选中可反查;
   *  - 网关缺席/失败全部静默(mock-first):本地会话照常工作,只是不出现在工程树下 */
  const registerProjectForSession = async (
    name: string,
    canvasToRegister: CanvasStateData,
    conversationTitle: string,
    localSessionId: string,
    initialMessages?: ChatMessage[],
  ): Promise<void> => {
    try {
      const proj = await createProject(name, canvasToRegister);
      if (!proj?.id) return;
      const conv = await createConversation(proj.id, conversationTitle);
      setProjectList((prev) => (prev.some((p) => p.id === proj.id) ? prev : [proj, ...prev]));
      if (conv?.id) {
        setConversationList((prev) => (prev.some((c) => c.id === conv.id) ? prev : [...prev, conv]));
        sessionConvMapRef.current.set(localSessionId, conv.id);
        sessionConvMapRef.current.set(conv.id, localSessionId);
        /* 首批消息即刻入对话:不等下一次 commit——否则刚导入的工程,对话是空壳,
           点进去(尤其刷新/跨设备水合)看不到导入消息与简报 */
        if (initialMessages?.length) {
          void putConversation({
            id: conv.id,
            projectId: proj.id,
            title: conversationTitle,
            createdAt: Date.now(),
            updatedAt: Date.now(),
            messages: initialMessages,
          });
        }
      }
      setActiveProject(proj.id);
    } catch {
      /* mock-first:注册失败不阻塞本地流程 */
    }
  };

  /* 启动水合:先触发 legacy 会话迁移(幂等,沿用原 session id 作对话 id →
     本地同 id 历史会话点开即命中,跨设备也有完整消息/画布),再拉工程树 +
     各工程对话,侧栏从此反映服务端真实状态(mock-first,网关缺席不阻塞)。 */
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await migrateProjects();
      if (cancelled) return;
      const projects = await fetchProjects();
      if (cancelled) return;
      setProjectList(projects);
      if (!projects.length) return;
      const convLists = await Promise.all(projects.map((p) => fetchConversations(p.id)));
      if (cancelled) return;
      setConversationList(convLists.flat());
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

    // L 线(契约 25 §2):编辑结果 settle 后跑智能标签路由(draftCount 用编辑后画布)
    applySmartRoute(systemText ?? summarizeOps(ops), { draftCount: draftCountOf(next) });

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
    // 问答/分析回答不自动路由画布(不切标签/不选中块/不滑入)——分析里几乎必含块名,
    // 自动摊开会抢走画布控制权;块名改为在消息里可点击,由用户主动打开。
    // 回答中的 ```mermaid 围栏仍流入画布时序图标签数据源(不回归)。
    const mermaid = extractMermaidSource(sysText);
    if (mermaid) setLatestMermaid(mermaid);
    return true;
  };

  /* 旧版同步重构(POST /canvas/refactor):流水线端点不可用(404/网关未升级/网络)
     时的兜底。报告文案统一走 pipelineResultMessage(自适应读取 lint_findings),
     不再硬编码"静态合规审查: 0 Errors, 0 Warnings"。 */
  const runLegacySyncRefactor = async (phId: string): Promise<boolean> => {
    try {
      const targetUnit = `U1_${canvas.project_name || "HR001"}`;
      const refResult = await requestPlc<{
        canvas: CanvasStateData;
        report: RefactorPipelineReport;
      }>("/api/v1/plc/canvas/refactor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canvas, target_unit_name: targetUnit }),
      });
      if (!refResult?.canvas) return false;
      setCanvas(refResult.canvas);
      updateMessageText(
        phId,
        pipelineResultMessage(
          { canvas: refResult.canvas, report: refResult.report, warnings: [] },
        ) + "\n\n> 注：网关暂不支持重构流水线，本次走旧版同步重构，未执行编译与打包。",
      );
      commitSession(refResult.canvas, []); // 刷新会话画布快照(消息已由占位原位更新)
      return true;
    } catch (e) {
      console.warn("Refactor error:", e);
      return false;
    }
  };

  /* 作业式重构流水线:POST 拿 job_id → pollUntil 轮询(1.8s/拍,960s 上限,可被
     会话切换/卸载中止) → 占位消息原位刷新各阶段进度 → 收敛后 setCanvas +
     会话落快照 + pipelineResultMessage 收尾。POST 失败(404/网络)返回 false,
     由旧同步路径兜底;作业已在跑之后的一切失败都如实写进占位消息,不再回退
     (重跑同步重构只会把同一个失败再执行一遍)。 */
  const runRefactorPipeline = async (
    intent: RefactorIntent,
    phId: string,
  ): Promise<boolean> => {
    let jobId = "";
    const canvasAtStart = canvasRef.current; // 脏守卫基准:完成后画布被改过则不自动覆盖
    const body: RefactorPipelineRequestBody = {
      canvas,
      project_name: canvas.project_name,
      do_compile: intent.wantCompile,
      auto_fix: true,
    };
    try {
      const data = await requestPlc<{ job_id?: string; id?: string }>(
        `/api/v1/plc/canvas/refactor-pipeline`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout?.(30000),
        },
      );
      jobId = String(data?.job_id ?? data?.id ?? "");
      if (!jobId) return false;
    } catch (err) {
      console.warn("Refactor pipeline unavailable, fallback to sync refactor:", err);
      return false;
    }

    // 进度占位(轮询期间只改内存不落盘,收敛时统一 persist);
    // 同步登记 LongTaskCenter:顶栏芯片+对话坞任务卡渲染同一任务
    const taskSessionId = activeSessionIdRef.current ?? "";
    let lastStages: RefactorPipelineStage[] | undefined;
    const paint = (job: RefactorPipelineJob) => {
      lastStages = job.stages;
      updateMessageText(
        phId,
        `### 重构流水线\n\n${pipelineProgressText(job.stages)}\n\n> 作业 ${job.id} · 完成后自动更新结果`,
        false,
      );
    };
    registerTask({
      id: phId,
      sessionId: taskSessionId,
      kind: "refactor_pipeline",
      title: LONG_TASK_LABELS.refactor_pipeline,
      startedAt: Date.now(),
      updatedAt: Date.now(),
      status: "running",
      stages: [],
      detail: `作业 ${jobId}`,
      messageId: phId,
    });
    const paintCard = (stages: RefactorPipelineStage[] | undefined) => {
      patchLongTask(phId, { stages: pipelineStageViews(stages) });
    };
    updateMessageText(phId, "已启动重构流水线…", false);

    const controller = new AbortController();
    refactorAbortRef.current = controller;
    try {
      const job = await pollUntilTwoPhase<RefactorPipelineJob>(
        () =>
          requestPlc<RefactorPipelineJob>(
            `/api/v1/plc/canvas/refactor-pipeline/${encodeURIComponent(jobId)}`,
            { signal: AbortSignal.timeout?.(REFACTOR_PIPELINE_PROBE_TIMEOUT_MS) },
          ),
        (j) => j.status === "ok" || j.status === "error" || j.status === "cancelled",
        {
          signal: controller.signal,
          onProgress: (j) => {
            paint(j);
            paintCard(j.stages);
          },
        },
      );
      // 中止可能落在最后一次探测与收敛之间：结果已过期，按中止处理
      if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
      paintCard(job.stages); // 终态阶段也进卡(完成/出错态可见)

      if (job.status === "ok" && job.result?.canvas) {
        finishLongTask(phId, "done");
        if (canvasRef.current !== canvasAtStart && activeSessionIdRef.current === taskSessionId) {
          // 脏守卫:流水线跑的几十分钟里用户又改了画布——结果不自动覆盖
          updateMessageText(
            phId,
            pipelineResultMessage(job.result, { jobId }) +
              "\n\n> 注意：流水线运行期间画布又有新的修改，结果未自动应用到画布（避免覆盖你的改动）；确认后可重新发起。",
          );
          return true;
        }
        updateMessageText(phId, pipelineResultMessage(job.result, { jobId }));
        if (activeSessionIdRef.current === taskSessionId) {
          setCanvas(job.result.canvas);
          commitSession(job.result.canvas, []); // 刷新会话画布快照
        } else {
          // 用户已切到别的会话:结果写回流水线所属会话,不打扰当前画布
          commitSessionFor(taskSessionId, job.result.canvas, []);
        }
        return true;
      }
      // error / cancelled / ok 但无画布 —— 如实报错并附出错阶段 detail
      finishLongTask(phId, "error", job.error || undefined);
      const badStage = (job.stages || []).find((s) => s.status === "error");
      const head =
        job.status === "cancelled" ? "### 重构流水线已取消" : "### 重构流水线执行失败";
      updateMessageText(
        phId,
        `${head}\n\n${pipelineProgressText(job.stages)}${
          badStage?.detail ? `\n\n**失败原因**: ${badStage.detail}` : ""
        }${job.error ? `\n\n> ${job.error}` : ""}\n\n> 作业 ${job.id}`,
      );
      return true;
    } catch (err) {
      if (isAbortError(err)) {
        // 卸载页面中止:在占位消息上留下结论,任务收 error 态
        paintCard(lastStages);
        finishLongTask(phId, "error", "已停止等待(页面卸载)");
        updateMessageText(
          phId,
          `### 重构流水线\n\n${pipelineProgressText(lastStages)}\n\n> 已停止等待流水线结果（离开页面）；网关侧作业可能仍在运行。作业 ${jobId}`,
        );
        return true;
      }
      finishLongTask(phId, "error", explainGatewayError(err, "轮询失败"));
      updateMessageText(
        phId,
        `### 重构流水线等待超时\n\n${explainGatewayError(err, "网关未返回错误详情")}\n\n> 作业 ${jobId} · 已等待 65 分钟仍未收敛。真实 TIA 编译通常 30 分钟内完成;若网关侧仍在运行,作业号保留(终态保留 1 小时),稍后刷新可查;若博图被弹窗阻塞,请先处理弹窗后重新发起。`,
      );
      return true;
    } finally {
      if (refactorAbortRef.current === controller) refactorAbortRef.current = null;
    }
  };

  /* 发送自然语言指令：优先后端 /canvas/chat-ops，失败回落本地规则引擎。
     用户消息与"正在思考…"占位立即上屏（不等网络），结果原位写入占位。
     LongTaskCenter 语义:消息落账后整个处理链转后台(isSubmitting 即释),
     多条消息可并行处理——问答/分析/流水线天然并行;**编辑类 ops 段由
     opsBusyRef 串行**(防画布写竞态,决策点 2)。 */
  const opsBusyRef = React.useRef(false);
  /** 待确认 ops 批次:消息 id → 原始 ops(只在内存;刷新即失效→确认卡标 expired) */
  const opsByMsgRef = React.useRef<Map<string, any[]>>(new Map());
  const handleSend = async () => {
    const prompt = chatInput.trim();
    if (!prompt || isSubmitting) return;
    setChatInput("");
    const phId = msgId();
    const sendSessionId = activeSessionIdRef.current;
    commitSession(canvas, [
      { id: msgId(), role: "user", text: prompt, ts: Date.now() },
      { id: phId, role: "system", text: "正在思考…", ts: Date.now() },
    ], prompt);
    const settle = (text: string) => updateMessageText(phId, text);
    void (async () => {
      try {
        await runSendFlow(prompt, phId, sendSessionId);
      } catch (err) {
        settle(`处理失败：${explainGatewayError(err, "未知错误")}`);
      }
    })();
  };

  /** handleSend 的后台处理链(原 try 块整体;编辑段内部自带 ops 串行锁) */
  const runSendFlow = async (prompt: string, phId: string, sendSessionId: string | null) => {
    {
      const settle = (text: string) => updateMessageText(phId, text);
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
          updateMessageText(
            phId,
            "当前是空白画布，还没有项目上下文。请先在左侧「历史对话」中点选你导入的工程会话" +
              "（或点「导入项目」）,再问我项目问题,我就能基于真实块和逻辑来分析。",
          );
          return;
        }
        answerTried = true;
        /* AI 分析也是长任务:登记 LongTaskCenter(轻量细条+顶栏芯片),
           结束(成功/失败/LLM 判为编辑类)即收态 */
        registerTask({
          id: phId,
          sessionId: sendSessionId ?? "",
          kind: "llm_answer",
          title: LONG_TASK_LABELS.llm_answer,
          startedAt: Date.now(),
          updatedAt: Date.now(),
          status: "running",
          detail: prompt.slice(0, 40),
          messageId: phId,
        });
        const answered = await tryChatAnswerStream(prompt, phId);
        finishLongTask(phId, answered ? "done" : "error", answered ? undefined : "已转编辑链处理");
        if (answered) return;
      }
      // 重构意图先于打包意图判定(顺序要求):prompt 同时含"重构 + 打包/下载"时
      // 不再被打包固定文案抢占 —— 流水线 package 阶段天然产出交付包并附下载链接。
      // 画布为空时不算重构(无块可重构),落回下方既有分支。
      const intent = parseRefactorIntent(prompt);
      const isRefactor = intent.refactor && Object.keys(canvas.blocks).length > 0;
      if (isRefactor) {
        // 后台执行:流水线可长达数十分钟,不许占住对话输入锁(真机反馈:编译/
        // 重构期间提问无法发送且无任何反应)。进度由进度卡+占位消息双通道呈现;
        // 期间用户再编辑画布由完成处的脏守卫兜底(不自动覆盖)。
        void (async () => {
          // 作业式流水线(POST + 轮询,进度原位刷新);端点不可用(404/网络)时回退旧同步重构
          if (await runRefactorPipeline(intent, phId)) return;
          if (await runLegacySyncRefactor(phId)) return;
          // 两级都未接手(网关缺席等):占位不留"正在思考…"
          updateMessageText(phId, "重构未执行：网关不可达或端点暂不可用，请稍后重试。");
        })();
        return;
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
        const pkgMsg = `### 西门子标准重构项目打包就绪\n\n` +
          `**官方编译验证**：已通过西门子 TIA Portal V19 Openness 软件完全重建校验，**0 Errors, 0 Warnings (State=Success)**。\n\n` +
          `#### 1. Web 直接下载连接 (点击立即下载)\n` +
          `- [**点击直接下载：博图 V19 原生工程归档包 (.zap19)**](${zapUrl})\n` +
          `- [**点击直接下载：完整交付母包 (.zip，含 64 块 SCL 源码 + I/O 保全表 + 编译收据)**](${zipUrl})\n` +
          `- [查看 Openness 官方编译收据 (.json)](${rptUrl})\n\n` +
          `#### 2. 本地项目同目录存储位置（与导入工程同目录）\n` +
          `- 交付母包与 .zap19 已直接放置在导入项目的同一个目录下：\n` +
          `  \`C:\\Users\\vboxuser\\Desktop\\Project\\Code\\PLC_chat\\PLC_Openness_data\\hr001\\\`\n` +
          `  - \`HR001_AF_V1_2.zap19\`\n` +
          `  - \`HR001_AF_V1_2_Package.zip\`\n` +
          `  - \`compile_receipt.json\`\n` +
          `  - \`io_retention_matrix.csv\`\n\n` +
          `#### 3. 编译验证说明\n` +
          `下载后在博图 V19 菜单点击「项目 -> 恢复 (Retrieve)」选择 \`HR001_AF_V1_2.zap19\` 即可直接打开编译，无任何缺失组件报错。`;
        commitSession(canvas, [{ id: phId, role: "system", text: pkgMsg, ts: Date.now() }]);
        return;
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
      // 修改确认块(人工确认门禁):对话产出的 ops 不再直接应用——渲染确认卡,
      // 每条附"内容理解";工程师点「确认应用」才走 预检→写画布(锁内)。
      // 原始 ops 存 ref(消息里只存轻量 items);预检挪到确认时执行。
      opsByMsgRef.current.set(phId, ops);
      const review = buildOpsReview(ops, previewNote || undefined);
      updateMessageText(
        phId,
        `已解析出 **${review.items.length} 项修改**，等待确认：请核对每条的"内容理解"后选择应用或放弃。`,
      );
      updateMessageOps(phId, review);
      return;
    }
  };

  /** 确认应用修改确认块:ops 仍在 ref(刷新即失效);预检 + 串行锁内写画布 */
  const handleConfirmOps = (mid: string) => {
    const ops = opsByMsgRef.current.get(mid);
    if (!ops?.length) {
      patchOpsReviewStatus(mid, "expired");
      updateMessageText(mid, "该批修改已失效（页面刷新后待确认批次不保留），请重新发送指令。");
      return;
    }
    if (opsBusyRef.current) {
      setWritebackNotice("上一条编辑还在执行中，请稍候再确认");
      setTimeout(() => setWritebackNotice(null), 4000);
      return;
    }
    opsBusyRef.current = true;
    void (async () => {
      try {
        // 预检(与编译门禁同语义:只查 ops 触及的块)
        try {
          const pre = await requestPlc<{ ok?: boolean; errors?: Array<{ message?: string }> }>(
            `/api/v1/plc/canvas/precheck`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                canvas: applyOpsLocally(canvasRef.current, ops),
                block_names: touchedBlockNames(ops),
              }),
              signal: AbortSignal.timeout?.(10000),
            },
          );
          if (pre && pre.ok === false) {
            const unique = [...new Set((pre.errors || []).map((e: any) => e.message))];
            patchOpsReviewStatus(mid, "rejected");
            updateMessageText(mid, `本地预检未通过，未应用修改：${unique.join("；") || "未知错误"}`);
            return;
          }
        } catch {
          /* precheck optional */
        }
        await applyOpsAndCommit(ops, null, summarizeOps(ops), { reuseSystemId: mid });
        patchOpsReviewStatus(mid, "applied");
        opsByMsgRef.current.delete(mid);
      } catch (err) {
        patchOpsReviewStatus(mid, "rejected");
        updateMessageText(mid, `应用失败：${explainGatewayError(err, "未知错误")}`);
      } finally {
        opsBusyRef.current = false;
      }
    })();
  };

  /** 放弃修改确认块:不动画布,卡片转已放弃 */
  const handleRejectOps = (mid: string) => {
    opsByMsgRef.current.delete(mid);
    patchOpsReviewStatus(mid, "rejected");
    updateMessageText(mid, "已放弃该批修改（画布未做任何改动）。");
  };

  /** 消息上 opsReview 状态补丁(跨会话按 id 定位) */
  const patchOpsReviewStatus = (mid: string, status: OpsReview["status"]) => {
    setSessions((prev) => {
      let hit = false;
      const list = prev.map((s) => ({
        ...s,
        messages: s.messages.map((m) => {
          if (m.id !== mid || !m.opsReview || m.opsReview.status === status) return m;
          hit = true;
          return { ...m, opsReview: { ...m.opsReview, status } };
        }),
      }));
      return hit ? (persistAndSync(list), list) : prev;
    });
  };

  /** 消息挂载/替换 opsReview(确认卡本体) */
  const updateMessageOps = (mid: string, review: OpsReview) => {
    setSessions((prev) => {
      let hit = false;
      const list = prev.map((s) => ({
        ...s,
        messages: s.messages.map((m) => {
          if (m.id !== mid) return m;
          hit = true;
          return { ...m, opsReview: review };
        }),
      }));
      return hit ? (persistAndSync(list), list) : prev;
    });
  };

  /* 刷新后待确认批次过期:原始 ops 只在内存 ref,刷新即失——挂载时把所有
     pending 确认卡标记 expired,按钮消失并说明原因,不冒充可确认 */
  useEffect(() => {
    const stale = sessionsRef.current.some((s) =>
      s.messages.some((m) => m.opsReview?.status === "pending"),
    );
    if (!stale) return;
    setSessions((prev) => {
      const list = prev.map((s) => ({
        ...s,
        messages: s.messages.map((m) =>
          m.opsReview?.status === "pending"
            ? { ...m, opsReview: { ...m.opsReview, status: "expired" as const } }
            : m,
        ),
      }));
      persistAndSync(list);
      return list;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---- 迟到结果回填:轮询超时/中止 ≠ 作业失败——网关侧可能仍在跑并最终成功
     (真机案例 c0b2f7ff…:27min 收敛 ok,但前端 16min 已写"等待失败",结果
     从未送达)。延迟 6s 等 bootstrapRemoteMerge(挂载即跑的远程会话合并,会用
     自己的快照整体覆盖 sessions)落地后再扫,避免回填被合并冲掉;再扫描
     会话里"等待超时/等待失败/已停止等待"消息中保留的作业号逐一探测:
     终态 ok → 重构画布+报告回填该会话(活跃会话同步上屏);
     其余终态/404(过 1h 保留期) → 标记已处理不再探测;running → 下次再探。
     作业号经 16 位 hex 白名单校验后才进 URL(防消息文本注入)。 */
  useEffect(() => {
    const JOB_ID_RE = /^[0-9a-f]{16}$/;
    const done = new Set<string>(
      (localStorage.getItem("plc-copilot.reconciledJobs.v1") || "")
        .split(",")
        .filter((x) => JOB_ID_RE.test(x)),
    );
    const markDone = (id: string) => {
      done.add(id);
      try {
        localStorage.setItem("plc-copilot.reconciledJobs.v1", [...done].join(","));
      } catch {
        /* 静默 */
      }
    };
    const pending: Array<{ sessionId: string; mid: string; jobId: string }> = [];
    for (const s of sessionsRef.current) {
      for (const m of s.messages) {
        if (m.role !== "system") continue;
        const t = m.text || "";
        if (
          !(
            t.includes("### 重构流水线等待超时") ||
            t.includes("### 重构流水线等待失败") ||
            t.includes("已停止等待流水线结果")
          )
        ) {
          continue;
        }
        const jm = t.match(/作业 ([0-9a-f]{16})/);
        const jid = Array.isArray(jm) ? (jm[1] ?? "") : "";
        if (jid && JOB_ID_RE.test(jid) && !done.has(jid)) {
          pending.push({ sessionId: s.id, mid: m.id, jobId: jid });
        }
      }
    }
    if (!pending.length) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (cancelled) return;
      void runReconcile(pending, markDone, () => cancelled);
    }, 6000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 迟到回填的实际探测/写回(由挂载 effect 延迟 6s 触发,避开启动合并窗口) */
  const runReconcile = async (
    pending: Array<{ sessionId: string; mid: string; jobId: string }>,
    markDone: (id: string) => void,
    isCancelled: () => boolean,
  ) => {
    for (const { sessionId, mid, jobId } of pending) {
      if (isCancelled()) return;
      try {
        const job = await requestPlc<RefactorPipelineJob>(
          "/api/v1/plc/canvas/refactor-pipeline/" + encodeURIComponent(jobId),
          { signal: AbortSignal.timeout?.(10000) },
        );
        if (job.status === "ok" && job.result?.canvas) {
          commitSessionFor(sessionId, job.result.canvas, [
            {
              id: msgId(),
              role: "system",
              text:
                pipelineResultMessage(job.result, { jobId }) +
                `\n\n> 迟到回填：此前“等待超时”的作业 ${jobId} 已在网关侧完成，结果现已补回本会话。`,
              ts: Date.now(),
            },
          ]);
          setSessions((prev) => {
            const list = prev.map((s) =>
              s.id === sessionId
                ? {
                    ...s,
                    messages: s.messages.map((m) =>
                      m.id === mid && !m.text.includes("迟到回填")
                        ? {
                            ...m,
                            text: m.text + `\n\n> 迟到回填：作业 ${jobId} 稍后完成，结果已补回（见下一条消息）。`,
                          }
                        : m,
                    ),
                  }
                : s,
            );
            persistAndSync(list);
            return list;
          });
          if (activeSessionIdRef.current === sessionId) {
            setCanvas(job.result.canvas);
            setSelectedBlockName(
              Object.values(job.result.canvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null,
            );
          }
          markDone(jobId);
        } else if (job.status === "error" || job.status === "cancelled") {
          markDone(jobId);
        }
        /* running → 留待下次加载再探 */
      } catch {
        markDone(jobId); /* 404(过保留期)/网络错:不再探测 */
      }
    }
  };

  /* 会话切换 / 新建 / 删除 —— LongTaskCenter 语义:长任务跟随自己的会话
     继续跑(不因切换中止),完成时写回所属会话;此处不再 abort。 */
  const handleSelectSession = (id: string) => {
    const s = sessions.find((x) => x.id === id);
    if (!s) return;
    dispatchNewProjectFlow({ type: "RESET" }); // 离开新建工程流
    setActiveSession(id);
    /* P 线:切回挂靠工程的会话时恢复活跃工程上下文(画布回写依赖它) */
    const convId = sessionConvMapRef.current.get(id);
    const conv = convId ? conversationList.find((c) => c.id === convId) : undefined;
    if (conv) setActiveProject(conv.projectId);
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
    dispatchNewProjectFlow({ type: "RESET" }); // 离开新建工程流
    setActiveSession(null);
    setActiveProject(null);
    setCanvas(blankCanvas(""));
    setSelectedBlockName(null);
    setFocus(null);
    setChatInput("");
    setDockCollapsed(false);
  };

  /** 侧栏选中 P 线对话(按 conversation_id):优先映射到本地会话;服务端有而本地无
   *  (刷新后/别的机器创建)时水合——拉对话消息 + 工程画布,物化为本地会话后进画布。
   *  水合失败静默返回(网关缺席时侧栏本就拉不到对话,此分支常态不可达)。 */
  const handleSelectConversation = (cid: string) => {
    const conv = conversationList.find((c) => c.id === cid);
    if (!conv) return;
    const mapped = sessionConvMapRef.current.get(cid);
    const localId =
      mapped && sessions.some((s) => s.id === mapped) ? mapped : (
        sessions.some((s) => s.id === cid) ? cid : null
      );
    if (localId) {
      setActiveProject(conv.projectId);
      handleSelectSession(localId);
      return;
    }
    void (async () => {
      const [remote, proj] = await Promise.all([
        fetchConversation(cid),
        fetchProject(conv.projectId),
      ]);
      if (!remote || !proj) {
        // 水合失败不再静默:工程师看得见为什么点了没反应
        setWritebackNotice(`无法从服务端加载对话「${conv.title}」(网关不可达或数据缺失)`);
        setTimeout(() => setWritebackNotice(null), 6000);
        return;
      }
      const s = makeSession(proj.canvas, remote.title);
      s.id = cid; // 与服务端对话同 id:二次选中走本地快路径
      s.messages = remote.messages ?? [];
      setSessions((prev) => {
        const list = [s, ...prev.filter((x) => x.id !== cid)];
        persistAndSync(list);
        return list;
      });
      /* 不回查 handleSelectSession:setSessions 是异步的,此刻闭包里的 sessions
         还没有这条新会话,find 会落空静默 return(真机复现:刷新后点侧栏对话
         画布仍空白)。这里直接内联设置激活态与画布。 */
      dispatchNewProjectFlow({ type: "RESET" });
      setActiveSession(cid);
      setActiveProject(conv.projectId);
      setCanvas(proj.canvas);
      setSelectedBlockName(
        Object.values(proj.canvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null
      );
      setFocus(null);
    })();
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
    /* 该会话的在飞长任务收 error 态(结果已无处可写),芯片不再悬挂 */
    for (const t of tasksBySession(longTasksRef.current, id)) {
      finishLongTask(t.id, "error", "会话已删除");
    }
    if (activeSessionId === id) {
      setActiveSession(null);
      setCanvas(blankCanvas(""));
      setSelectedBlockName(null);
    }
  };

  /** 侧栏删除对话:服务端 P 线对话 + 映射到的本地会话一起删;删的是活跃会话
   *  则复位到空白态(镜像 handleDeleteSession 的活跃分支);工程计数本地扣减。 */
  const handleDeleteConversation = (cid: string) => {
    const conv = conversationList.find((c) => c.id === cid);
    const localId = sessionConvMapRef.current.get(cid) ?? cid;
    sessionConvMapRef.current.delete(cid);
    sessionConvMapRef.current.delete(localId);
    setConversationList((prev) => prev.filter((c) => c.id !== cid));
    if (conv) {
      setProjectList((prev) =>
        prev.map((p) =>
          p.id === conv.projectId
            ? { ...p, conversationCount: Math.max(0, (p.conversationCount ?? 1) - 1) }
            : p,
        ),
      );
    }
    void apiDeleteConversation(cid).then((ok) => {
      if (!ok) {
        setWritebackNotice("对话在服务端删除失败(网关不可达),刷新后可能重新出现");
        setTimeout(() => setWritebackNotice(null), 8000);
      }
    });
    // 本地会话存在则同步删除(legacy 同步通道一并清)
    if (sessions.some((s) => s.id === localId)) {
      const list = sessions.filter((s) => s.id !== localId);
      setSessions(list);
      persistAndSync(list);
      void syncSessionDelete(localId);
      /* 该会话在飞长任务收 error 态(结果无处落) */
      for (const t of tasksBySession(longTasksRef.current, localId)) {
        finishLongTask(t.id, "error", "会话已删除");
      }
      if (activeSessionIdRef.current === localId) {
        setActiveSession(null);
        setCanvas(blankCanvas(""));
        setSelectedBlockName(null);
        setFocus(null);
      }
    }
  };

  /* 变量引用跳转 */
  const handleJumpToRef = (ref: VarRef) => {    if (ref.kind === "network") {
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
    const brief = buildBriefing(imported);
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
      /* 工程简报:makeSession 已有机制上追加 system 消息(ServerPath/Upload 均经由本函数) */
      { id: newSessionId(), role: "system", text: briefingToMessage(brief), ts: Date.now() },
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
    /* P 线注册:导入的工程成为一等实体,对话挂进工程树(侧栏立即可见),
       导入消息+简报即刻写入对话;mock-first——网关缺席时静默,本地会话照常 */
    void registerProjectForSession(
      imported.project_name || sourceName,
      imported,
      s.title,
      s.id,
      s.messages,
    );
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
    const sessionId = commitSession(finalCanvas, [
      {
        id: msgId(),
        role: "system",
        text: `工程已创建,标准结构就绪;${settleExtra}可继续描述工艺完善逻辑`,
        ts: Date.now(),
      },
    ]);
    dispatchNewProjectFlow({ type: "CREATE_SETTLED" });
    /* P 线注册:新建工程与既有导入路径同构——工程一等实体 + 首对话入树 */
    void registerProjectForSession(name, finalCanvas, `工程 · ${name}`, sessionId);
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

  /** 解析最新一条变更事务(供两处消费):updated_at 最新的 change_id;
   *  若 change.intent.requirement_id 命中当前已确认需求,把需求卡一并带回。 */
  const resolveLatestChange = async (): Promise<{
    id: string | null;
    req: Requirement | null;
  }> => {
    try {
      const { items } = await fetchChanges();
      if (!items.length) return { id: null, req: null }; // 真实空账本:无可审查项
      const latest = items.reduce((a, b) => (b.updated_at > a.updated_at ? b : a));
      if (confirmedRequirement?.requirement_id) {
        try {
          const res = await fetchChange(latest.change_id);
          const intent = res?.change.intent as unknown as
            | { requirement_id?: string }
            | null
            | undefined;
          return {
            id: latest.change_id,
            req:
              intent?.requirement_id === confirmedRequirement.requirement_id
                ? confirmedRequirement
                : null,
          };
        } catch {
          /* 命中判断失败 → 按未关联需求处理 */
        }
      }
      return { id: latest.change_id, req: null };
    } catch {
      /* fetchChanges 自带 mock 回退,正常不会到这里 */
      return { id: null, req: null };
    }
  };

  /** 打开最近一条变更的四层审查(对话内模态抽屉):工程概览头「审查最近变更」入口 */
  const handleReviewLatestChange = async () => {
    const { id, req } = await resolveLatestChange();
    if (!id) return;
    setChangeReviewId(id);
    setChangeReviewReq(req);
  };

  /**
   * L 线智能标签路由接线(契约 25 §2):AI 回答 settle 后调用。
   * 命中 → 切画布标签 + chat 态自动滑入 split;scl 命中附带 focusBlock
   * (setSelectedBlock);review 命中解析最新事务供画布内嵌审查视图;
   * 回答含 ```mermaid 围栏 → 更新 latestMermaid(时序图标签数据源)。
   * override.draftCount 允许调用方传入"刚编辑后"的草稿数,绕开闭包过期。
   */
  const applySmartRoute = (text: string, override?: { draftCount?: number }) => {
    const mermaid = extractMermaidSource(text);
    if (mermaid) setLatestMermaid(mermaid);
    const route = smartRoute(text, {
      selectedBlock: selectedBlockName ?? undefined,
      hasMermaid: !!mermaid,
      draftCount: override?.draftCount ?? draftCountRef.current,
    });
    if (!route) return;
    if (route.tab === "scl" && route.focusBlock) setSelectedBlockName(route.focusBlock);
    setActiveTab(route.tab);
    if (route.autoOpen) setLayoutMode((mode) => (mode === "chat" ? "split" : mode));
    if (route.tab === "review") {
      void resolveLatestChange().then(({ id, req }) => {
        setCanvasReviewId(id);
        setCanvasReviewReq(req);
      });
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

  /** 聊天消息中点击块名(FB/FC/DB/OB) → 画布滑入并在 SCL 标签摊开该块 */
  const handleOpenBlockFromChat = React.useCallback(
    (name: string) => {
      if (!canvas.blocks[name]) return;
      setSelectedBlockName(name);
      setFocus({ kind: "block", blockName: name });
      setActiveTab("scl");
      setLayoutMode((mode) => (mode === "chat" ? "split" : mode));
    },
    [canvas.blocks],
  );

  /**
   * 轮询编译作业直到 7 阶段状态机收敛。
   * 替代原来的 `for (let i = 0; i < 600; i++)` 死循环：
   * - `signal`：切换会话 / 卸载页面可中止，不留残留定时器；
   * - `timeoutMs`：960s 上限（网关硬超时 900s + 60s 让 timeout 结论先落地）；
   * - `onProgress`：每次探测都写 `compileJob`，阶段状态实时上屏；
   * - 终止条件：status ∈ {ok, error, cancelled}（含网关侧 timed_out 落成的 error）。
   */
  const pollCompileJob = async (
    jobId: string,
    onProgress?: (job: CompileJobPayload) => void,
  ): Promise<CompileJobPayload> => {
    const controller = new AbortController();
    compileAbortRef.current = controller;
    try {
      const job = await pollUntilTwoPhase<CompileJobPayload>(
        () =>
          requestPlc<CompileJobPayload>(
            `/api/v1/plc/canvas/compile-jobs/${encodeURIComponent(jobId)}`,
            { signal: AbortSignal.timeout?.(COMPILE_PROBE_TIMEOUT_MS) },
          ),
        (j) => j.status === "ok" || j.status === "error" || j.status === "cancelled",
        {
          signal: controller.signal,
          onProgress: (j) => {
            setCompileJob(j);
            onProgress?.(j);
          },
        },
      );
      // 中止可能落在最后一次探测与收敛之间：这时结果已过期，按中止处理
      if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
      return job;
    } finally {
      if (compileAbortRef.current === controller) compileAbortRef.current = null;
    }
  };

  /* 人工确认门禁回写：异步编译作业 + 轮询；路径取自 canvas.source。
   * 不占对话输入锁:编译轮询可达数十分钟,期间必须还能提问(真机反馈:
   * 编译中提问无法发送且无反应);防重入用独立 ref。 */
  const handleExecuteWriteback = async () => {
    if (writebackInFlightRef.current) return;
    writebackInFlightRef.current = true;
    const canvasAtStart = canvasRef.current;
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
        /* LongTaskCenter:编译也是长任务(顶栏芯片常驻指示,轮询实时刷 detail) */
        const compileTaskId = `compile-${job.id}`;
        const compileSessionId = activeSessionIdRef.current ?? "";
        registerTask({
          id: compileTaskId,
          sessionId: compileSessionId,
          kind: "compile",
          title: LONG_TASK_LABELS.compile,
          startedAt: Date.now(),
          updatedAt: Date.now(),
          status: "running",
          detail: `编译作业 ${job.id.slice(0, 10)} · 回写 ${canvas.project_name}`,
        });
        try {
          job = await pollCompileJob(job.id, (j) => {
            patchLongTask(compileTaskId, {
              detail: `编译作业 ${j.id.slice(0, 10)} · ${j.status === "running" ? "进行中" : j.status}`,
            });
          });
          bumpChangesRefresh(); // 作业收敛(ok/error/cancelled)→ 刷新 PCEC 变更账本
        } catch (err) {
          if (isAbortError(err)) {
            finishLongTask(compileTaskId, "error", "已停止等待(页面卸载)");
            setWritebackNotice("已停止等待编译结果（离开页面）；网关侧作业可能仍在运行");
            setTimeout(() => setWritebackNotice(null), 8000);
            return;
          }
          const detail =
            err instanceof GatewayError
              ? `读取编译作业状态失败：${explainGatewayError(err, "网关未返回错误详情")}`
              : `等待编译结果超时（总上限 65 分钟：快段 5 分钟 + 慢段 60 分钟）：网关未在预期时间内结束作业，请检查博图是否弹窗阻塞`;
          setWritebackNotice(detail);
          setTimeout(() => setWritebackNotice(null), 10000);
          finishLongTask(compileTaskId, "error", "等待编译结果失败");
          bumpChangesRefresh(); // 轮询失败也可能已落账(如 precheck fail-closed)→ 尽力刷新
          return;
        }

        // degraded / timed_out / precheck 没有专属 UI 位置：合并进既有的 error 行、通知条和会话消息
        finishLongTask(
          compileTaskId,
          job.status === "ok" ? "done" : "error",
          job.status === "ok" ? undefined : (job.error || undefined),
        );
        const notes = compileJobNotes(job);
        const detail = notes.join("；");
        const headline = job.error && job.error !== "precheck_failed" ? job.error : null;
        setCompileJob({
          ...job,
          error: [headline, ...notes].filter(Boolean).join("；") || null,
        });

        if (job.canvas) {
          const compileMsg: ChatMessage = {
            id: msgId(),
            role: "system",
            text: [`编译作业 ${job.status}`, ...notes].join("："),
            ts: Date.now(),
          };
          const onCompileSession = activeSessionIdRef.current === compileSessionId;
          const commitCompileResult = (c: CanvasStateData, msg: ChatMessage) => {
            if (onCompileSession) commitSession(c, [msg]);
            else commitSessionFor(compileSessionId, c, [msg]);
          };
          if (canvasRef.current !== canvasAtStart) {
            // 脏守卫:编译期间用户又改了画布——结果不自动覆盖,消息照记
            commitCompileResult(canvasRef.current, {
              ...compileMsg,
              text: [
                `编译作业 ${job.status}`,
                ...notes,
                "（编译期间画布有新的修改，结果未自动覆盖画布，确认后可重新回写）",
              ].join("："),
            });
            setWritebackNotice("编译期间画布又有修改：结果保留在对话中，未自动覆盖画布");
            setTimeout(() => setWritebackNotice(null), 10000);
          } else {
            if (onCompileSession) setCanvas(job.canvas);
            commitCompileResult(job.canvas, compileMsg);
          }
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
              if (canvasRef.current !== canvasAtStart) {
                notice += "（期间画布又有修改，修正结果未自动覆盖画布）";
              } else {
                setCanvas(fdata.canvas);
              }
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
      writebackInFlightRef.current = false; // 释放防重入(不占对话锁)
    }
  };

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
    <div className="app">
      {/* —— 细顶栏(契约 25 §2 L 线简化):状态指示灯 + 变更记录 + 回写博图 + [画布] —— */}
      <header className="topbar" data-ui="topbar">
        {backendConnected !== null && (
          <span className="conn" title={backendConnected ? "网关已就绪" : "离线沙箱模式"}>
            <i className={`led ${backendConnected ? "led--run" : "led--standby"}`} />
            {backendConnected ? "网关已就绪" : "离线沙箱模式"}
          </span>
        )}

        <div className="topbar__spacer" />

        {/* LongTaskCenter:页面级长任务指示(任何布局可见;点击跳回所属会话) */}
        <LongTaskChips
          tasks={longTasks}
          currentSessionId={activeSessionId}
          onJump={handleJumpToLongTask}
        />

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

        {/* [画布]:chat↔split 展开/收起;fullscreen 态点它先还原 split */}
        <button
          className="topbar__toggle"
          onClick={toggleCanvasPane}
          aria-pressed={layoutMode !== "chat"}
          aria-label={layoutMode === "chat" ? "打开画布" : "收起画布"}
          title={
            layoutMode === "chat"
              ? "打开画布面板（全局图 / SCL / HMI / 变量 / 时序图）"
              : layoutMode === "fullscreen"
                ? "还原为分栏对话"
                : "收起画布，回到纯对话"
          }
        >
          <span className="topbar__canvas-toggle">[画布]</span>
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

      {/* 引导屏(无工程时) */}
      {showOnboarding && (
        <OnboardingScreen
          onImport={() => {
            setShowOnboarding(false);
            setImportOpen(true);
          }}
          onNewFromChat={(prompt) => {
            setShowOnboarding(false);
            handleNewSession();
            /* 引导屏里敲好的工艺句子随行带入新对话（handleNewSession 会清空输入，故在其后写回） */
            if (prompt) setChatInput(prompt);
          }}
        />
      )}

      {/* —— L 线布局壳(契约 25 §2):chat / split / fullscreen 三态状态机 —— */}
      <div className={`shell shell--${layoutMode}${draggingCanvas ? " shell--dragging" : ""}`}>
        {/* 左侧工程栏挂载点(S 线):ProjectSidebar 渲染进 #sidebar-slot;fullscreen 态 CSS 收窄 */}
        <ProjectSidebar
          projects={projectList}
          activeProjectId={activeProjectId}
          conversations={conversationList}
          activeConversationId={activeSessionId}
          collapsed={sidebarCollapsed || layoutMode === "fullscreen"}
          onSelectProject={(pid) => {
            setActiveProject(pid);
            const conv = conversationList.find((c) => c.projectId === pid);
            if (conv) handleSelectConversation(conv.id);
          }}
          onSelectConversation={handleSelectConversation}
          onDeleteConversation={handleDeleteConversation}
          onNewConversation={() => handleNewSession()}
          onNewProject={() => setShowOnboarding(true)}
          onDeleteProject={(pid) => {
            void apiDeleteProject(pid).then(() => {
              setProjectList((prev) => prev.filter((p) => p.id !== pid));
              if (activeProjectId === pid) {
                setActiveProjectId(null);
                handleNewSession();
              }
            });
          }}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        />

        <div className="shell-main">
          {layoutMode === "fullscreen" ? (
            /* fullscreen:画布满铺 + 底部薄条(输入框保留,展开回 split) */
            <div className="shell-fullscreen">
              <WorkspacePanel
                activeTab={activeTab}
                onActiveTabChange={setActiveTab}
                fullscreen
                onToggleMaximize={() => setLayoutMode("split")}
                onClose={() => setLayoutMode("chat")}
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
                crossReport={report}
                wiredTags={wiredTags}
                onJumpToRef={handleJumpToRef}
                mermaidText={latestMermaid}
                requirement={reqDraft}
                requirementLoading={reqLoading}
                onRequirementEdit={handleRequirementEdit}
                onConfirmIntent={(r) => void handleConfirmIntent(r)}
                reviewChangeId={canvasReviewId}
                reviewRequirement={canvasReviewReq}
                onReviewFocusTarget={handleFocusChangeTarget}
              />
              <div className="shell-thinbar">
                <button
                  type="button"
                  className="shell-thinbar__btn"
                  onClick={() => setLayoutMode("split")}
                  aria-label="展开对话,还原分栏"
                  title="展开对话（还原分栏）"
                >
                  ⌃
                </button>
                <input
                  className="dock-input shell-thinbar__input"
                  value={chatInput}
                  placeholder="对话输入保留中…（Enter 发送 / 点左侧按钮展开对话）"
                  aria-label="指令输入（画布全屏薄条）"
                  spellCheck={false}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void handleSend();
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => void handleSend()}
                  disabled={isSubmitting || !chatInput.trim()}
                >
                  发送
                </button>
              </div>
            </div>
          ) : layoutMode === "split" ? (
            /* split:对话(左,flex) + 画布(右,canvasPct%,可拖) */
            <div className="shell-split" ref={splitRef}>
              <div className="shell-chat">
                <ChatDock
                  messages={activeSession?.messages ?? []}
                  inputValue={chatInput}
                  onInputChange={setChatInput}
                  onSend={handleSend}
                  collapsed={dockCollapsed}
                  onToggleCollapse={() => setDockCollapsed((c) => !c)}
                  onSuggestion={(text) => {
                    setChatInput(text);
                    setTimeout(() => handleSend(), 50);
                  }}
                  blockNames={blockNameList}
                  onOpenBlock={handleOpenBlockFromChat}
                  tasks={tasksBySession(longTasks, activeSessionId ?? "")}
                  onConfirmOps={handleConfirmOps}
                  onRejectOps={handleRejectOps}
                />
              </div>
              <div
                className="shell-gutter"
                role="separator"
                aria-orientation="vertical"
                aria-label="拖拽调整画布宽度"
                onPointerDown={onCanvasGutterDown}
                onPointerMove={onCanvasGutterMove}
                onPointerUp={onCanvasGutterUp}
                onPointerCancel={onCanvasGutterUp}
              />
              <div className="shell-canvas" style={{ width: `${canvasPct}%` }}>
                <WorkspacePanel
                  activeTab={activeTab}
                  onActiveTabChange={setActiveTab}
                  fullscreen={false}
                  onToggleMaximize={() => setLayoutMode("fullscreen")}
                  onClose={() => setLayoutMode("chat")}
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
                  crossReport={report}
                  wiredTags={wiredTags}
                  onJumpToRef={handleJumpToRef}
                  mermaidText={latestMermaid}
                  requirement={reqDraft}
                  requirementLoading={reqLoading}
                  onRequirementEdit={handleRequirementEdit}
                  onConfirmIntent={(r) => void handleConfirmIntent(r)}
                  reviewChangeId={canvasReviewId}
                  reviewRequirement={canvasReviewReq}
                  onReviewFocusTarget={handleFocusChangeTarget}
                />
              </div>
            </div>
          ) : (
            /* chat(默认):纯对话满铺,ChatDock 占整个主区 */
            <div className="chat-stage">
              {showLaunchScreen && (
                <div className="chat-stage__launch">
                  <ProjectLaunchScreen
                    sessions={sessions}
                    onImport={() => setImportOpen(true)}
                    onNewProject={handleNewProjectEntry}
                    onSelectSession={handleSelectSession}
                  />
                </div>
              )}
              <ChatDock
                messages={activeSession?.messages ?? []}
                inputValue={chatInput}
                onInputChange={setChatInput}
                onSend={handleSend}
                collapsed={dockCollapsed}
                onToggleCollapse={() => setDockCollapsed((c) => !c)}
                onSuggestion={(text) => {
                  setChatInput(text);
                  setTimeout(() => handleSend(), 50);
                }}
                blockNames={blockNameList}
                onOpenBlock={handleOpenBlockFromChat}
                tasks={tasksBySession(longTasks, activeSessionId ?? "")}
                onConfirmOps={handleConfirmOps}
                onRejectOps={handleRejectOps}
              />
            </div>
          )}
        </div>
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
