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
import { useResizablePanes } from "./state/useResizablePanes";
import type { CanvasStateData, CompileJobData, CompilerAttribution } from "./canvas/types";
import { CompileDrawer } from "./shell/CompileDrawer";
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
      persistSessions(list);
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
      const list = prev.map((s) => ({
        ...s,
        messages: s.messages.map((m) => (m.id === id ? { ...m, text } : m)),
      }));
      if (persist) persistSessions(list);
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
          persistSessions(list);
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
  const tryChatAnswerStream = async (prompt: string, phId: string): Promise<boolean> => {
    let sysText = "";
    let usage: Record<string, number> | null = null;
    try {
      const res = await fetch(`${GATEWAY_BASE}/api/v1/plc/canvas/chat-answer/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          canvas,
          prompt,
          context: { selected_block: selectedBlockName, focus },
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
        const data = await requestPlc<{ answer?: string; usage?: Record<string, number> }>(
          `/api/v1/plc/canvas/chat-answer`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              canvas,
              prompt,
              context: { selected_block: selectedBlockName, focus },
            }),
            signal: AbortSignal.timeout?.(120000),
          },
        );
        if (data?.answer) {
          sysText = data.answer;
          usage = data.usage || null;
        }
      } catch {
        return false;
      }
    }
    if (!sysText) return false;
    const u = usage || {};
    const hitRate = u.prompt_tokens
      ? Math.round(((u.prompt_cache_hit_tokens || 0) / u.prompt_tokens) * 100)
      : null;
    const footer =
      u.prompt_tokens || u.completion_tokens
        ? `\n\n（DeepSeek · 输入 ${u.prompt_tokens ?? "?"} tok${
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
              context: { selected_block: selectedBlockName, focus },
            }),
            signal: AbortSignal.timeout?.(60000),
          },
        );
        if (Array.isArray(data?.ops) && data.ops.length) {
          ops = data.ops;
          previewNote = `（${data.source || "chat-ops"}）`;
        }
      } catch {
        /* fall through to local rules */
      }
      if (!ops.length) {
        ops = localOps;
      }
      if (ops.length === 0) {
        // LLM 对提问正确返回空 ops 时也走问答（此前只兜本地意图）
        if (question && !answerTried) {
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
    setActiveSession(id);
    setCanvas(s.canvas);
    setSelectedBlockName(
      Object.values(s.canvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null
    );
    setFocus(null);
  };

  const handleNewSession = () => {
    abortCompilePoll();
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
    persistSessions(list);
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
    persistSessions(list);

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
  const handleCreateProject = (projectName: string) => {
    const fresh = blankCanvas(projectName);
    setCanvas(fresh);
    const s = makeSession(fresh, `新建空白项目 ${projectName}`);
    s.title = `空白 · ${projectName}`;
    s.messages = [
      { id: newSessionId(), role: "user", text: `新建空白项目 ${projectName}`, ts: Date.now() },
      {
        id: newSessionId(),
        role: "system",
        text: `已创建空白项目 ${projectName}。用对话指令（如"创建 FB ConveyorCtrl"）或"新建逻辑块"按钮开始构建，完成后可回写博图。`,
        ts: Date.now(),
      },
    ];
    const list = [s, ...sessions];
    setSessions(list);
    setActiveSession(s.id);
    persistSessions(list);
    setSelectedBlockName(null);
    setFocus(null);
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
        }),
        signal: AbortSignal.timeout?.(30000),
      });

      if (data?.async && data.job?.id) {
        let job: CompileJobPayload = data.job;
        setCompileJob(job);
        setWritebackNotice("编译作业已启动…");
        try {
          job = await pollCompileJob(job.id);
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
    } catch (err) {
      const msg = explainGatewayError(err, "未知错误");
      setWritebackNotice(`回写/编译失败：${msg}`);
      setTimeout(() => setWritebackNotice(null), 8000);
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

        <div className="topbar__actions">
          <button
            className="btn btn--ghost"
            onClick={() => setCreateDialog("project")}
            title="从零开始构建一个空白项目"
          >
            空白项目
          </button>
          <button
            className="btn btn--ghost"
            onClick={() => setImportOpen(true)}
            title="导入博图 Openness 导出的 XML 或服务器路径"
          >
            导入项目
          </button>
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
                <span className="spec-row__label">待转译回写逻辑块</span>
                <span className="spec-row__value">{blockList.length} 块 (SCL / SimaticML)</span>
              </div>
              <div className="spec-row">
                <span className="spec-row__label">待同步 HMI 变量绑定</span>
                <span className="spec-row__value">{widgetList.length} 项 (PlcTagTable)</span>
              </div>
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
    </div>
  );
};

export default App;
export { App };
