import React, { useEffect, useMemo, useState } from "react";
import { PlcInteractiveCanvas, type FocusTarget } from "./canvas/PlcInteractiveCanvas";
import { HistorySidebar } from "./shell/HistorySidebar";
import { ChatDock } from "./shell/ChatDock";
import { VariableInspector } from "./shell/VariableInspector";
import { ImportDialog } from "./shell/ImportDialog";
import { CreateBlockDialog } from "./shell/CreateBlockDialog";
import { defaultCanvas } from "./state/defaultCanvas";
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
} from "./state/canvasOps";
import { blankCanvas } from "./state/tiaXmlImport";
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

const API_BASE = "http://localhost:8000";

const msgId = () => "m-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

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
  const [canvas, setCanvas] = useState<CanvasStateData>(defaultCanvas);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  /* 对话坞 */
  const [chatInput, setChatInput] = useState("");
  const [dockCollapsed, setDockCollapsed] = useState(false);

  /* 中栏：选中块驱动（三栏并存，无标签页） */
  const [selectedBlockName, setSelectedBlockName] = useState<string | null>("MotorCtrl");
  const [focus, setFocus] = useState<FocusTarget | null>(null);

  /* 导入 / 从零构建 */
  const [importOpen, setImportOpen] = useState(false);
  const [createDialog, setCreateDialog] = useState<null | "block" | "project">(null);

  /* 回写门禁 */
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [attributions, setAttributions] = useState<CompilerAttribution[]>([]);
  const [compileJob, setCompileJob] = useState<CompileJobData | null>(null);
  const [writebackNotice, setWritebackNotice] = useState<string | null>(null);

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

  // 拉取后端默认画布
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/plc/canvas/default`)
      .then((res) => res.json())
      .then((data) => {
        if (data && data.ok && data.data) {
          setCanvas(data.data);
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
    let id = activeSessionId;
    let list: ChatSession[];
    if (!id) {
      const s = makeSession(nextCanvas, firstPrompt);
      s.messages = [...s.messages, ...msgs];
      id = s.id;
      list = [s, ...sessions];
    } else {
      const cur = sessions.find((s) => s.id === id);
      if (!cur) {
        const s = makeSession(nextCanvas, firstPrompt);
        s.messages = [...s.messages, ...msgs];
        id = s.id;
        list = [s, ...sessions];
      } else {
        list = [
          { ...cur, messages: [...cur.messages, ...msgs], updatedAt: Date.now(), canvas: nextCanvas },
          ...sessions.filter((s) => s.id !== id),
        ];
      }
    }
    setSessions(list);
    setActiveSessionId(id);
    persistSessions(list);
    return id;
  };

  /* 通用 ops 管道：本地乐观应用（立即渲染 + 记会话），后端结果后台和解 */
  const editSeqRef = React.useRef(0);

  const applyOpsAndCommit = async (
    ops: any[],
    userText: string | null,
    systemText?: string
  ): Promise<CanvasStateData> => {
    const seq = ++editSeqRef.current;
    const next = applyOpsLocally(canvas, ops);

    // 立即乐观渲染 + 会话记录（不等网络）
    setCanvas(next);
    const msgs: ChatMessage[] = [];
    if (userText) msgs.push({ id: msgId(), role: "user", text: userText, ts: Date.now() });
    msgs.push({ id: msgId(), role: "system", text: systemText ?? summarizeOps(ops), ts: Date.now() });
    const sessionId = commitSession(next, msgs, userText ?? undefined);

    // 后端尽力同步：成功且期间无新编辑时，用权威结果和解（同时刷新会话快照）
    fetch(`${API_BASE}/api/v1/plc/canvas/patch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operations: ops, canvas }),
      signal: AbortSignal.timeout?.(4000),
    })
      .then((res) => res.json())
      .then((json) => {
        if (!json || !json.ok || !json.data) return;
        if (editSeqRef.current !== seq) return; // 期间已有新编辑，放弃过期结果
        const remote = json.data as CanvasStateData;
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

  /* 发送自然语言指令：优先后端 /canvas/chat-ops，失败回落本地规则引擎 */
  const handleSend = async () => {
    const prompt = chatInput.trim();
    if (!prompt || isSubmitting) return;
    setIsSubmitting(true);
    setChatInput("");
    try {
      let ops: any[] = [];
      let previewNote = "";
      try {
        const res = await fetch(`${API_BASE}/api/v1/plc/canvas/chat-ops`, {
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
        });
        const json = await res.json();
        if (json?.ok && Array.isArray(json.data?.ops) && json.data.ops.length) {
          ops = json.data.ops;
          previewNote = `（${json.data.source || "chat-ops"}）`;
        }
      } catch {
        /* fall through to local rules */
      }
      if (!ops.length) {
        ops = buildOpsFromPrompt(prompt, canvas);
      }
      if (ops.length === 0) {
        commitSession(canvas, [
          { id: msgId(), role: "user", text: prompt, ts: Date.now() },
          {
            id: msgId(),
            role: "system",
            text: "暂未识别出可执行的画布操作，试试：创建 FB ConveyorCtrl / 在 ConveyorCtrl 中添加变量 Speed Real / 添加急停按钮。",
            ts: Date.now(),
          },
        ], prompt);
        return;
      }
      // Local precheck when ops touch SCL
      try {
        const pre = await fetch(`${API_BASE}/api/v1/plc/canvas/precheck`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ canvas: applyOpsLocally(canvas, ops) }),
          signal: AbortSignal.timeout?.(10000),
        });
        const preJson = await pre.json();
        if (preJson?.data && preJson.data.ok === false) {
          const errs = (preJson.data.errors || []).map((e: any) => e.message).join("；");
          commitSession(canvas, [
            { id: msgId(), role: "user", text: prompt, ts: Date.now() },
            {
              id: msgId(),
              role: "system",
              text: `本地预检未通过，未应用修改：${errs || "未知错误"}`,
              ts: Date.now(),
            },
          ], prompt);
          return;
        }
      } catch {
        /* precheck optional */
      }
      await applyOpsAndCommit(ops, `${prompt}${previewNote}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  /* 会话切换 / 新建 / 删除 */
  const handleSelectSession = (id: string) => {
    const s = sessions.find((x) => x.id === id);
    if (!s) return;
    setActiveSessionId(id);
    setCanvas(s.canvas);
    setSelectedBlockName(
      Object.values(s.canvas.blocks).find((b) => b.block_type !== "DB")?.name ?? null
    );
    setFocus(null);
  };

  const handleNewSession = () => {
    setActiveSessionId(null);
    setCanvas(defaultCanvas);
    setSelectedBlockName("MotorCtrl");
    setFocus(null);
    setChatInput("");
    setDockCollapsed(false);
  };

  const handleDeleteSession = (id: string) => {
    const list = sessions.filter((s) => s.id !== id);
    setSessions(list);
    persistSessions(list);
    if (activeSessionId === id) {
      setActiveSessionId(null);
      setCanvas(defaultCanvas);
      setSelectedBlockName("MotorCtrl");
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
    setActiveSessionId(s.id);
    persistSessions(list);

    setCanvas(imported);
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
        const res = await fetch(
          `${API_BASE}/api/v1/plc/canvas/import/progress/${encodeURIComponent(progressId)}`,
        );
        const json = await res.json().catch(() => null);
        const msg = json?.data?.message;
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
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path,
          project_name: projectName,
          progress_id: progressId,
        }),
        // 大型 .zap（如 HR002 15MB/72 块）网关解包+解析实测约 45s：30s 会先超时
        signal: AbortSignal.timeout?.(180000),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json || !json.ok) {
        const detail = json?.detail;
        const message =
          detail && typeof detail === "object" && detail.message
            ? detail.message
            : detail && typeof detail === "string"
            ? detail
            : `导入失败（HTTP ${res.status}）`;
        throw new Error(message);
      }
      const data = json.data;
      const imported: CanvasStateData = data.canvas;
      const name = imported.project_name || projectName || "ImportedProject";
      handleImportCanvas(imported, name);
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
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/import/upload`, {
        method: "POST",
        body: form,
        signal: AbortSignal.timeout?.(180000),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json || !json.ok) {
        const detail = json?.detail;
        const message =
          detail && typeof detail === "object" && detail.message
            ? detail.message
            : detail && typeof detail === "string"
            ? detail
            : `导入失败（HTTP ${res.status}）`;
        throw new Error(message);
      }
      const imported: CanvasStateData = json.data.canvas;
      const name =
        json.data.canvas.project_name ||
        projectName.trim() ||
        file.name.replace(/\.(zap\d*|ap1\d|zip)$/i, "");
      handleImportCanvas(imported, name);
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
    setActiveSessionId(s.id);
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
    const res = await fetch(`${API_BASE}/api/v1/plc/canvas/explain-block`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, scaffold }),
      signal: AbortSignal.timeout?.(90000),
    });
    const json = await res.json().catch(() => null);
    const detail = json?.detail;
    const message =
      detail && typeof detail === "object" && detail.message ? detail.message : detail && typeof detail === "string" ? detail : null;
    if (!res.ok || !json?.ok) {
      throw new Error(message ?? `深度解释失败（HTTP ${res.status}）`);
    }
    return json.data.explanation as string;
  };

  /* 人工确认门禁回写：异步编译作业 + 轮询；路径取自 canvas.source */
  const handleExecuteWriteback = async () => {
    setIsSubmitting(true);
    setShowConfirmModal(false);
    try {
      const projectPath = canvas.source?.project_path || `${canvas.project_name}.ap19`;
      const plcName = canvas.source?.plc_name || "PLC_1";
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/confirm-writeback`, {
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
      const json = await res.json();
      if (!json?.ok || !json.data) {
        const detail = json?.detail;
        const msg =
          detail && typeof detail === "object" && detail.message
            ? String(detail.message)
            : detail && typeof detail === "string"
            ? detail
            : "writeback failed";
        throw new Error(msg);
      }

      if (json.data.async && json.data.job?.id) {
        let job: CompileJobData = json.data.job;
        setCompileJob(job);
        setWritebackNotice("编译作业已启动…");
        for (let i = 0; i < 600; i++) {
          await new Promise((r) => setTimeout(r, 1000));
          const jr = await fetch(`${API_BASE}/api/v1/plc/canvas/compile-jobs/${job.id}`);
          const jjson = await jr.json();
          if (jjson?.ok && jjson.data) {
            job = jjson.data;
            setCompileJob(job);
            if (job.status === "ok" || job.status === "error" || job.status === "cancelled") break;
          }
        }
        if (job.canvas) {
          setCanvas(job.canvas);
          commitSession(job.canvas, [
            { id: msgId(), role: "system", text: `编译作业 ${job.status}`, ts: Date.now() },
          ]);
        }
        setAttributions((job.attributions || []) as CompilerAttribution[]);
        let notice =
          job.status === "ok"
            ? "博图回写并编译通过，工程已保存"
            : `编译未通过：${job.error || "见诊断面板"}`;
        if (job.status === "error" && (job.attributions || []).length) {
          try {
            const fr = await fetch(`${API_BASE}/api/v1/plc/canvas/fix-loop`, {
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
            const fjson = await fr.json();
            if (fjson?.ok && fjson.data?.canvas) {
              setCanvas(fjson.data.canvas);
              setAttributions((fjson.data.attributions || []) as CompilerAttribution[]);
              notice = fjson.data.ok
                ? `自动修正后编译通过（${(fjson.data.rounds || []).length} 轮）`
                : `自动修正未完全成功（${(fjson.data.rounds || []).length} 轮）`;
            }
          } catch {
            /* optional */
          }
        }
        setWritebackNotice(notice);
        setTimeout(() => setWritebackNotice(null), 10000);
        return;
      }

      const result = json.data;
      if (result.canvas) setCanvas(result.canvas);
      setAttributions(result.attributions || []);
      setWritebackNotice(result.writeback?.ok ? "回写成功" : `回写失败`);
      setTimeout(() => setWritebackNotice(null), 6000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
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
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/auto-fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canvas, attributions }),
      });
      const json = await res.json();
      if (json && json.ok && json.data?.canvas) {
        setCanvas(json.data.canvas);
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
          await fetch(`${API_BASE}/api/v1/plc/canvas/compile-jobs/${compileJob.id}/cancel`, {
            method: "POST",
          });
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
