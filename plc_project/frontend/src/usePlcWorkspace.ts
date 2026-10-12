import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
  type RefObject,
} from "react";
import {
  cancelTask,
  connectResearchStream,
  deleteResearchTask,
  fetchPlcBrief,
  fetchPlcJob,
  fetchTask,
  listResearchTasks,
  optimizePlcJob,
  retryPlcStructure,
  postChatTurn,
  writebackPlcJob,
  resumeTask,
  unwrapTask,
  plcZapUrl,
  waitForPlcJob,
  type PlcCitation,
  type PlcJobDetail,
  type PlcProjectBrief,
} from "../api";
import {
  canvasFocusFromJump,
  jumpToken,
  type CanvasJumpIntent,
  type NodeWorkbenchTab,
} from "./canvas/index";
import { demoKnowledgeCanvas, demoPlcJob } from "./canvas/demoFixture";
import {
  canvasGalaxyScore,
  emptyCanvas,
  normalizeCanvas,
  plcCanvasFromJob,
} from "./canvasModel";
import {
  formatPlcProgress,
  formatWritebackRecap,
  sclDiffsForFocus,
  writebackHintForBlock,
} from "./detail";
import {
  autoLayoutKnowledge,
  type CanvasFocusRequest,
  type KnowledgeCanvasData,
  type KnowledgeNode,
} from "../KnowledgeCanvas";
import {
  attachCitationNodes,
  chatScopeFromNode,
  isPlcScopeNode,
  mentionFromText,
  pretty,
  titleFromQuery,
  type ChatMsg,
  type ChatScope,
  type Topic,
} from "../workbench/model";
import {
  mergeCitations,
  mergeEvents,
  mergeInterrupts,
} from "../workbench/collections";
import {
  collectCitations,
  collectEvents,
  collectInterrupts,
  normalizeCitations,
  normalizeEvent,
  normalizeInterrupts,
  type CitationItem,
  type InterruptItem,
  type ResearchEvent,
} from "../researchModel";

export type PlcSendOptions = {
  message: string;
  file?: File | null;
  focusNodeId?: string | null;
  blockName?: string | null;
  displayUser?: string;
  scopeLabel?: string;
};

export type PlcCanvasTab = "canvas" | "brief" | "sensors" | "timeline" | "citations";

export const ENGINEER_HANDOVER_PROMPTS = [
  {
    id: "q1_hardware",
    label: "硬件/传感器",
    prompt: "这个工程有哪些硬件和传感器？请按已导出证据列出；未导出或未建索引的标「未导出/未索引」，不要编造。",
  },
  {
    id: "q2_run_logic",
    label: "运行逻辑",
    prompt: "主循环怎么跑？入口 OB 和顶层调用链是什么？请引用块名与网络/行，并附源片段。",
  },
  {
    id: "q3_hitl_adjust",
    label: "如何调整",
    prompt: "如果要改这段运行逻辑，HITL 该怎么确认调整？不要自动写回 SCL，只说明确认路径。",
  },
] as const;

export function usePlcWorkspace() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [plcJobId, setPlcJobId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [interrupts, setInterrupts] = useState<InterruptItem[]>([]);
  const [plcJob, setPlcJob] = useState<PlcJobDetail | null>(null);
  const [canvas, setCanvas] = useState<KnowledgeCanvasData>(emptyCanvas);
  const [chatScope, setChatScope] = useState<ChatScope | null>(null);
  const [canvasFocus, setCanvasFocus] = useState<CanvasFocusRequest | null>(null);
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const [citations, setCitations] = useState<CitationItem[]>([]);
  const [canvasTab, setCanvasTab] = useState<PlcCanvasTab>("canvas");
  const [workbenchOpen, setWorkbenchOpen] = useState(false);
  const [workbenchTab, setWorkbenchTab] = useState<NodeWorkbenchTab>("meaning");
  const [noteFocusKey, setNoteFocusKey] = useState(0);
  const [switchCue, setSwitchCue] = useState<string | null>(null);
  const switchCueTimer = useRef<number | null>(null);
  const lastWorkbenchNode = useRef<string | null>(null);
  const [projectBrief, setProjectBrief] = useState<PlcProjectBrief | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const active = topics.find((t) => t.id === activeId) || null;

  const refreshTopics = useCallback(async () => {
    try {
      const tasks = await listResearchTasks().catch(() => []);
      setTopics(
        (tasks || [])
          .map((t) => {
            const row = t as {
              id?: string;
              query?: string;
              status?: string;
              route?: string;
              plc_job_id?: string;
              result?: { plc_job_id?: string };
            };
            return {
              id: String(row.id || ""),
              title: titleFromQuery(String(row.query || row.id || "")),
              status: String(row.status || "unknown"),
              route: row.route,
              plcJobId: row.plc_job_id || row.result?.plc_job_id || null,
            };
          })
          .filter((t) => t.id),
      );
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void refreshTopics();
    return () => wsRef.current?.close();
  }, [refreshTopics]);

  useEffect(() => {
    try {
      if (!new URLSearchParams(window.location.search).has("canvasDemo")) return;
      setCanvas(demoKnowledgeCanvas());
      setPlcJob(demoPlcJob());
      setPlcJobId("demo-canvas");
      setStatus("canvas-demo");
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function pushMsg(
    role: ChatMsg["role"],
    content: string,
    extra?: { citations?: PlcCitation[]; scopeLabel?: string },
  ) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const at = Date.now();
    setMessages((prev) => [
      ...prev,
      { id, role, content, at, citations: extra?.citations, scopeLabel: extra?.scopeLabel },
    ]);
    return id;
  }

  function focusComposer() {
    window.requestAnimationFrame(() => {
      const el = composerRef.current;
      if (!el) return;
      el.focus();
      el.scrollIntoView({ block: "nearest" });
    });
  }

  function flashSwitchCue(label: string) {
    if (switchCueTimer.current) window.clearTimeout(switchCueTimer.current);
    setSwitchCue(`已切换节点 · ${label}`);
    switchCueTimer.current = window.setTimeout(() => setSwitchCue(null), 2200);
  }

  function applyChatScope(node: KnowledgeNode | null) {
    if (!node || !isPlcScopeNode(node)) {
      setChatScope(null);
      lastWorkbenchNode.current = null;
      setWorkbenchOpen(false);
      return;
    }
    const next = chatScopeFromNode(node);
    if (
      workbenchOpen &&
      lastWorkbenchNode.current &&
      lastWorkbenchNode.current !== next.nodeId
    ) {
      flashSwitchCue(next.label);
    }
    lastWorkbenchNode.current = next.nodeId;
    setChatScope(next);
  }

  function clearChatScope() {
    setChatScope(null);
    lastWorkbenchNode.current = null;
    setWorkbenchOpen(false);
    setCanvasFocus({ key: Date.now(), clear: true });
  }

  function onAskInChat(node: KnowledgeNode) {
    applyChatScope(node);
    setCanvasTab("canvas");
    setWorkbenchOpen(true);
    setWorkbenchTab("run");
    focusComposer();
  }

  function onViewSources(node: KnowledgeNode) {
    applyChatScope(node);
    setCanvasTab("canvas");
    setWorkbenchOpen(true);
    setWorkbenchTab("run");
  }

  function onMarkNote(node: KnowledgeNode) {
    applyChatScope(node);
    setCanvasTab("canvas");
    setWorkbenchOpen(true);
    setWorkbenchTab("meaning");
    setNoteFocusKey(Date.now());
  }

  function jumpToCanvasNode(intent: CanvasJumpIntent) {
    const token = jumpToken(intent);
    const node =
      (intent.nodeId ? canvas.nodes.find((n) => n.id === intent.nodeId) : undefined) ||
      canvas.nodes.find(
        (n) =>
          n.id === token ||
          n.source?.block_name === token ||
          n.label === token ||
          n.label === intent.symbol,
      );
    if (node) applyChatScope(node);
    setCanvasTab("canvas");
    setCanvasFocus(canvasFocusFromJump(intent));
    if (intent.ask && node) {
      setWorkbenchOpen(true);
      setWorkbenchTab("run");
    }
  }

  function onFocusNode(ref: string) {
    const token = String(ref || "").trim();
    if (!token) return;
    jumpToCanvasNode({
      nodeId: token.startsWith("plc_") || token.startsWith("sig_") ? token : undefined,
      blockName: token,
    });
  }

  function scopedNode(): KnowledgeNode | null {
    if (!chatScope) return null;
    return (
      canvas.nodes.find((n) => n.id === chatScope.nodeId) || {
        id: chatScope.nodeId,
        label: chatScope.label,
        kind: chatScope.kind,
        x: 0,
        y: 0,
        source: { type: "plc", block_name: chatScope.blockName },
      }
    );
  }

  function scopedPrompts(scope: ChatScope): string[] {
    const tag = scope.kind === "plc_tag";
    const prompts = tag
      ? ["这个信号干什么?", "谁读写它", "谁读写这些信号?"]
      : ["这个块干什么?", "展开 SCL", "分析逻辑", "嵌套链?", "理解逻辑", "优化逻辑", "优化SCL", "确认反写", "谁调用它 / 它调用谁", "谁读写这些信号?", "优化建议"];
    if (scope.looksLikeOutput) prompts.push("有没有互锁?");
    return prompts;
  }

  function projectPrompts() {
    return (projectBrief?.engineer_prompts?.length
      ? projectBrief.engineer_prompts
      : ENGINEER_HANDOVER_PROMPTS.map((p) => ({ ...p }))
    ).map((p) => ({ id: p.id, label: p.label, prompt: p.prompt }));
  }

  function onScopePrompt(prompt: string) {
    const node = scopedNode();
    if (node) void onDeepDive(node, prompt);
  }

  function onProjectPrompt(prompt: string) {
    void sendTurn({ message: prompt, displayUser: prompt });
  }

  function startNew() {
    wsRef.current?.close();
    setActiveId(null);
    setMessages([]);
    setDraft("");
    setFile(null);
    setStatus("");
    setInterrupts([]);
    setEvents([]);
    setCitations([]);
    setCanvasTab("canvas");
    setPlcJob(null);
    setPlcJobId(null);
    setChatScope(null);
    setCanvasFocus(null);
    setWorkbenchOpen(false);
    setSwitchCue(null);
    lastWorkbenchNode.current = null;
    setCanvas(emptyCanvas());
    setProjectBrief(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function deleteTopic(topic: Topic, e: MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    e.preventDefault();
    if (!window.confirm(`删除历史对话「${topic.title}」？`)) return;
    try {
      await deleteResearchTask(topic.id);
      setTopics((prev) => prev.filter((t) => t.id !== topic.id));
      if (activeId === topic.id) startNew();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }

  async function clearAllTopics() {
    if (!topics.length) return;
    if (!window.confirm(`清空全部 ${topics.length} 条历史对话？`)) return;
    const ids = topics.map((t) => t.id);
    await Promise.allSettled(ids.map((id) => deleteResearchTask(id)));
    setTopics([]);
    startNew();
  }

  function applyCanvasFromTask(task: ReturnType<typeof unwrapTask>, fallback?: unknown) {
    const result = (task.result || {}) as Record<string, unknown>;
    const raw = result.knowledge_canvas ?? fallback;
    if (raw) {
      const next = normalizeCanvas(raw);
      if (next.nodes.length || next.edges.length) {
        const laid = {
          ...next,
          nodes: autoLayoutKnowledge(next.nodes, next.edges),
          edges: next.edges,
        };
        setCanvas((prev) => {
          // Don't let a sparse chat canvas wipe a richer PLC galaxy (causes edge flash on click)
          if (
            canvasGalaxyScore(prev) > canvasGalaxyScore(laid) &&
            prev.nodes.length >= Math.max(1, laid.nodes.length - 2)
          ) {
            return prev;
          }
          return laid;
        });
        return laid;
      }
    }
    return null;
  }

  function applyCanvasFromPlcJob(detail: PlcJobDetail) {
    const next = plcCanvasFromJob(detail);
    if (next) setCanvas(next);
  }

  async function hydratePlc(jobId: string) {
    const detail = await fetchPlcJob(jobId);
    setPlcJob(detail);
    setPlcJobId(jobId);
    try {
      const brief = await fetchPlcBrief(jobId);
      setProjectBrief(brief);
    } catch {
      setProjectBrief(null);
    }
    return detail;
  }

  async function openTopic(topic: Topic) {
    wsRef.current?.close();
    setActiveId(topic.id);
    setBusy(true);
    setStatus("…");
    setCanvas(emptyCanvas());
    setPlcJob(null);
    setPlcJobId(null);
    setChatScope(null);
    setCanvasFocus(null);
    setWorkbenchOpen(false);
    setSwitchCue(null);
    lastWorkbenchNode.current = null;
    setEvents([]);
    setCitations([]);
    setCanvasTab("canvas");
    try {
      const body = await fetchTask(topic.id);
      const task = unwrapTask(body);
      const result = (task.result || {}) as Record<string, unknown>;
      const linked =
        task.plc_job_id ||
        (typeof result.plc_job_id === "string" ? result.plc_job_id : null);
      setStatus(String(task.status || ""));
      setInterrupts(collectInterrupts(task));
      setEvents(collectEvents(task));
      setCitations(collectCitations(task));
      setPlcJobId(linked || null);
      applyCanvasFromTask(task);
      const assistant =
        String(result.assistant_message || "") ||
        pretty(task.result) ||
        String(task.status || "");
      setMessages([
        { id: "q", role: "user", content: topic.title, at: Date.now() },
        { id: "a", role: "assistant", content: assistant, at: Date.now() },
      ]);
      if (linked) {
        let detail = await hydratePlc(linked);
        if (detail.status !== "ready" && detail.status !== "failed") {
          setStatus(formatPlcProgress(detail));
          detail = await waitForPlcJob(linked, {
            intervalMs: 1500,
            onProgress: (d) => {
              setPlcJob(d);
              setStatus(formatPlcProgress(d));
              if (d.brief_ready) {
                void fetchPlcBrief(linked)
                  .then(setProjectBrief)
                  .catch(() => undefined);
              }
            },
          });
          setPlcJob(detail);
        }
        if (detail.chat?.length) {
          const base = Date.now();
          setMessages(
            detail.chat.map((c, i) => ({
              id: `c${i}`,
              role: c.role === "user" ? "user" : "assistant",
              content: c.content,
              at: base + i,
              citations: c.citations,
              scopeLabel: c.block_name || mentionFromText(c.content) || undefined,
            })),
          );
        }
        // Always rebuild star from job so legacy grid canvases get fixed.
        if (detail.status === "ready") {
          applyCanvasFromPlcJob(detail);
          setStatus("ready");
        } else if (detail.status === "failed") {
          setStatus("failed");
        }
      } else if (task.route !== "plc") {
        connectWs(topic.id);
      }
    } catch (err) {
      setMessages([
        {
          id: "err",
          role: "system",
          content: err instanceof Error ? err.message : String(err),
          at: Date.now(),
        },
      ]);
      setStatus("error");
    } finally {
      setBusy(false);
    }
  }

  function connectWs(id: string) {
    wsRef.current?.close();
    wsRef.current = connectResearchStream(id, (event) => {
      const etype = String(event.event_type || event.type || "");
      const payload = (event.payload || {}) as Record<string, unknown>;
      const ev = normalizeEvent(event);
      if (ev) setEvents((prev) => mergeEvents(prev, [ev]));
      if (etype === "task.status") setStatus(String(payload.status || ""));
      if (etype === "interrupt.required" || etype === "interrupt") {
        setInterrupts((prev) =>
          mergeInterrupts(prev, normalizeInterrupts([payload]).filter((x) => !x.resolved)),
        );
      }
      if (etype === "interrupt.resolved" || etype === "interrupt_resolved") {
        setInterrupts([]);
      }
      if (etype === "citation.added" || etype === "citation") {
        setCitations((prev) => mergeCitations(prev, normalizeCitations([payload])));
      }
      if (etype === "message.delta" && payload.text) {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.id.startsWith("stream-")) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + String(payload.text) },
            ];
          }
          return [
            ...prev,
            {
              id: `stream-${Date.now()}`,
              role: "assistant",
              content: String(payload.text),
              at: Date.now(),
            },
          ];
        });
      }
    });
  }

  async function sendTurn(opts: PlcSendOptions) {
    setBusy(true);
    const display = opts.displayUser || opts.message;
    if (display) {
      pushMsg("user", display, {
        scopeLabel: opts.scopeLabel || mentionFromText(display) || undefined,
      });
    }
    const parsing =
      Boolean(opts.file) ||
      /\.(zap\d*|ap\d+|xml|zip)\b/i.test(opts.message) ||
      /解析|上传|工程/.test(opts.message);
    const progressId = parsing
      ? pushMsg(
          "system",
          "正在解析 PLC 工程：检测输入 → Openness/XML → PLC-IR → 逻辑图/知识图谱…",
        )
      : null;
    try {
      const turn = await postChatTurn({
        message: opts.message,
        taskId: activeId,
        file: opts.file,
        focusNodeId: opts.focusNodeId,
        blockName: opts.blockName,
        canvasEdges: canvas.edges.filter((e) => e.user_created),
        canvasPositions: canvas.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y })),
      });
      const task = turn.task;
      const id = task.id;
      if (!id) throw new Error("未返回任务 ID");
      const topic: Topic = {
        id,
        title: titleFromQuery(task.query || display),
        status: String(task.status || ""),
        route: turn.route,
        plcJobId: turn.plc_job_id,
      };
      setTopics((prev) => [topic, ...prev.filter((t) => t.id !== id)]);
      setActiveId(id);
      setStatus(String(task.status || ""));
      setInterrupts(collectInterrupts(task));
      setEvents((prev) => mergeEvents(prev, collectEvents(task)));
      setCitations((prev) => mergeCitations(prev, collectCitations(task)));
      pushMsg("assistant", turn.assistant_message || "", {
        citations: attachCitationNodes(turn.citations, canvas.nodes),
      });
      const linked = turn.plc_job_id || task.plc_job_id;
      // Node deep-dive / describe: keep current galaxy; only hydrate chat/job text.
      const isNodeFocus = Boolean(opts.focusNodeId || opts.blockName);
      if (!isNodeFocus || canvasGalaxyScore(canvas) === 0) {
        const applied = applyCanvasFromTask(task, turn.knowledge_canvas);
        if (linked) {
          let detail = await hydratePlc(String(linked));
          if (detail.status !== "ready" && detail.status !== "failed") {
            detail = await waitForPlcJob(String(linked), {
              intervalMs: 1500,
              onProgress: (d) => {
                setPlcJob(d);
                if (d.brief_ready) {
                  void fetchPlcBrief(String(linked))
                    .then(setProjectBrief)
                    .catch(() => undefined);
                }
                const label = formatPlcProgress(d);
                setStatus(label);
                if (progressId) {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === progressId ? { ...m, content: `正在解析 PLC 工程：${label}` } : m,
                    ),
                  );
                }
              },
            });
            setPlcJob(detail);
            setPlcJobId(detail.id);
          }
          if (progressId) {
            setMessages((prev) => prev.filter((m) => m.id !== progressId));
          }
          if (detail.status === "failed") {
            pushMsg("system", detail.error || "PLC 解析失败");
            setStatus("failed");
          } else if (detail.status === "ready") {
            setStatus("ready");
            const hasGalaxy = canvasGalaxyScore(applied) > 0 || canvasGalaxyScore(canvas) > 0;
            if (!applied?.nodes.length || !hasGalaxy) {
              applyCanvasFromPlcJob(detail);
            }
            const welcome = [...(detail.chat || [])]
              .reverse()
              .find((c) => c.role === "assistant");
            if (welcome?.content) {
              setMessages((prev) => {
                for (let i = prev.length - 1; i >= 0; i -= 1) {
                  if (prev[i].role === "assistant") {
                    const next = prev.slice();
                    next[i] = {
                      ...next[i],
                      content: welcome.content,
                      citations: attachCitationNodes(
                        welcome.citations || next[i].citations,
                        canvas.nodes,
                      ),
                    };
                    return next;
                  }
                }
                return prev;
              });
            }
          }
        } else {
          if (progressId) {
            setMessages((prev) => prev.filter((m) => m.id !== progressId));
          }
          if (turn.route === "research") connectWs(id);
        }
      } else if (linked) {
        if (progressId) {
          setMessages((prev) => prev.filter((m) => m.id !== progressId));
        }
        await hydratePlc(String(linked));
      } else {
        if (progressId) {
          setMessages((prev) => prev.filter((m) => m.id !== progressId));
        }
        if (turn.route === "research") connectWs(id);
      }
      void refreshTopics();
    } catch (err) {
      if (progressId) {
        setMessages((prev) => prev.filter((m) => m.id !== progressId));
      }
      const raw = err instanceof Error ? err.message : String(err);
      const expired =
        /SESSION_EXPIRED|会话已失效|Missing ['"]?tsk_|找不到 tsk_/i.test(raw) ||
        /找不到 job_/i.test(raw);
      if (expired) {
        const staleId = activeId;
        setActiveId(null);
        setPlcJob(null);
        setPlcJobId(null);
        setCanvas(emptyCanvas());
        if (staleId) {
          setTopics((prev) => prev.filter((t) => t.id !== staleId));
        }
        pushMsg(
          "system",
          raw.includes("会话已失效")
            ? raw
            : "会话已失效（Gateway 重启后内存任务已清空）。请点「新建」并重新上传工程后再提问。",
        );
      } else {
        pushMsg("system", raw);
      }
      setStatus("error");
    } finally {
      setBusy(false);
    }
  }

  async function onSend(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = draft.trim();
    if ((!text && !file) || busy) return;
    const attached = file;
    setDraft("");
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
    const fallback = text || `解析工程文件 ${attached?.name || ""}`.trim();
    const display = text || (attached ? `（上传 ${attached.name}）` : "");
    if (attached) {
      await sendTurn({
        message: fallback,
        file: attached,
        displayUser: display,
      });
      return;
    }
    const mentioned = mentionFromText(text);
    if (mentioned) {
      await sendTurn({
        message: fallback,
        file: attached,
        focusNodeId: chatScope?.nodeId,
        blockName: mentioned,
        displayUser: display,
        scopeLabel: mentioned,
      });
      return;
    }
    if (chatScope) {
      await sendTurn({
        message: `@${chatScope.blockName} ${fallback}`,
        file: attached,
        focusNodeId: chatScope.nodeId,
        blockName: chatScope.blockName,
        displayUser: display,
        scopeLabel: chatScope.label,
      });
      return;
    }
    await sendTurn({
      message: fallback,
      file: attached,
      displayUser: display,
    });
  }

  async function onDeepDive(node: KnowledgeNode, question: string) {
    applyChatScope(node);
    const scope = chatScopeFromNode(node);
    const block = scope.blockName;
    const q = question.trim();
    const message = block ? `@${block} ${q}` : q;
    await sendTurn({
      message,
      focusNodeId: node.id,
      blockName: block || null,
      displayUser: q,
      scopeLabel: scope.label || undefined,
    });
  }

  async function onRetryStructure(names?: string[]) {
    if (!plcJobId || busy) return;
    setBusy(true);
    try {
      await retryPlcStructure(plcJobId, names || []);
      setStatus("queued");
      pushMsg(
        "system",
        names?.length
          ? `正在重试结构导出：${names.slice(0, 8).join(", ")}${names.length > 8 ? "…" : ""}`
          : "正在重试全部结构导出（Openness / XML 清单）",
      );
      const detail = await waitForPlcJob(plcJobId, {
        intervalMs: 1500,
        onProgress: (d) => {
          setPlcJob(d);
          setStatus(formatPlcProgress(d));
        },
      });
      setPlcJob(detail);
      if (detail.status === "ready") {
        applyCanvasFromPlcJob(detail);
        const failed = Number(detail.structure?.counts?.failed || 0);
        const skipped = Number(detail.structure?.counts?.skipped || 0);
        const pending = Number(detail.structure?.counts?.pending || 0);
        pushMsg(
          "assistant",
          failed || skipped || pending
            ? `结构重试完成：failed=${failed} skipped=${skipped} pending=${pending}。清单中的缺口不会被静默省略。`
            : "结构重试完成：清单完整。",
        );
        setStatus("ready");
      } else if (detail.status === "failed") {
        setStatus("failed");
        pushMsg("system", detail.error || "结构重试失败");
      }
    } catch (err) {
      pushMsg("system", err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onOptimizePropose() {
    if (!plcJobId || busy) return;
    setBusy(true);
    try {
      const data = await optimizePlcJob(plcJobId, {
        message: "优化工程逻辑并准备反写",
        blockName:
          chatScope && chatScope.kind !== "plc_tag" ? chatScope.blockName : undefined,
      });
      const detail = await hydratePlc(plcJobId);
      const plan =
        String(detail.optimize_plan || data.optimize_plan || "").trim() ||
        "（无优化计划文本）";
      const opsFromCs = detail.changeset?.ops;
      const ops =
        typeof data.ops === "number"
          ? data.ops
          : Array.isArray(opsFromCs)
            ? opsFromCs.length
            : 0;
      const skipped = data.skipped || detail.scl_skipped || [];
      const diffs = data.scl_diffs || detail.scl_diffs || [];
      const skipLines = skipped
        .slice(0, 24)
        .map((s) => `- \`${s.block || "?"}\`：${s.reason || ""}${s.detail ? ` — ${s.detail}` : ""}`)
        .join("\n");
      const diffLines = diffs
        .slice(0, 8)
        .map((d) => {
          const body = String(d.diff || "").trim() || "(unchanged importable SCL)";
          return `#### \`${d.block || "?"}\`${d.new_block ? "（新建）" : ""}\n\n\`\`\`diff\n${body}\n\`\`\``;
        })
        .join("\n\n");
      const extra = [
        skipLines ? `### 跳过（拒绝写程序体）\n\n${skipLines}` : "",
        diffLines ? `### SCL diff\n\n${diffLines}` : "",
      ]
        .filter(Boolean)
        .join("\n\n");
      pushMsg(
        "assistant",
        `### 优化提案（HITL）\n\n已生成 **${ops}** 条变更操作（含 SCL 改写/解耦）。请审阅 **SCL diff** 与跳过列表后再点节点「确认反写」或画布「确认反写 zap」。\n\n${plan}${extra ? `\n\n${extra}` : ""}`,
      );
      setStatus("optimize_proposed");
    } catch (err) {
      pushMsg("system", err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmWriteback(blockName?: string | null) {
    if (!plcJobId || busy) return;
    const focus = String(blockName || "").trim() || undefined;
    let projectPath = String(plcJob?.project_path || "").trim();
    if (!projectPath) {
      const entered = window.prompt("请输入 TIA 工程路径（.ap19/.apxx）：");
      if (entered == null) return;
      projectPath = entered.trim();
      if (!projectPath) {
        pushMsg("system", "需要工程路径才能确认反写");
        return;
      }
    }
    setBusy(true);
    try {
      const data = await writebackPlcJob(plcJobId, projectPath, {
        archiveZap: true,
        blockName: focus || null,
      });
      const detail = await hydratePlc(plcJobId);
      const recap = formatWritebackRecap(data, detail, focus);
      const zap = String(
        (detail.writeback as { zap_path?: string } | null)?.zap_path ||
          data.zap_path ||
          "",
      );
      if (zap) {
        const name = String(zap).split(/[/\\]/).pop() || "archive.zap";
        pushMsg("assistant", `${recap}\n\n[${name}](${plcZapUrl(plcJobId)})`);
      } else {
        pushMsg("assistant", recap.trim() ? recap : "### 确认反写\n未返回导入/编译/归档结果。");
      }
      setStatus("writeback_done");
    } catch (err) {
      pushMsg("system", err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onResume(resolution: string, interruptId?: string) {
    if (!activeId) return;
    setBusy(true);
    try {
      await resumeTask(activeId, resolution, interruptId);
      pushMsg("system", resolution);
      const body = await fetchTask(activeId);
      const task = unwrapTask(body);
      setStatus(String(task.status || ""));
      setInterrupts(collectInterrupts(task));
      setEvents((prev) => mergeEvents(prev, collectEvents(task)));
      setCitations((prev) => mergeCitations(prev, collectCitations(task)));
      applyCanvasFromTask(task);
    } catch (err) {
      pushMsg("system", err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    if (!activeId) return;
    setBusy(true);
    try {
      await cancelTask(activeId);
      setStatus("cancelled");
      pushMsg("system", "已取消");
    } catch (err) {
      pushMsg("system", err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const writebackHintFor = useCallback(
    (blockName: string) => writebackHintForBlock(plcJob, blockName),
    [plcJob],
  );
  const sclPreviewFor = useCallback(
    (blockName: string) => sclDiffsForFocus(plcJob, blockName),
    [plcJob],
  );

  return {
    active,
    activeId,
    busy,
    canvas,
    canvasFocus,
    canvasTab,
    chatEndRef: chatEndRef as RefObject<HTMLDivElement | null>,
    chatScope,
    citations,
    composerRef: composerRef as RefObject<HTMLTextAreaElement | null>,
    draft,
    events,
    file,
    fileRef: fileRef as RefObject<HTMLInputElement | null>,
    interrupts,
    messages,
    plcJob,
    plcJobId,
    projectBrief,
    topics,
    status,
    applyChatScope,
    clearAllTopics,
    clearChatScope,
    deleteTopic,
    onCancel,
    onConfirmWriteback,
    onDeepDive,
    onFocusNode,
    onAskInChat,
    onViewSources,
    onMarkNote,
    jumpToCanvasNode,
    workbenchOpen,
    workbenchTab,
    noteFocusKey,
    switchCue,
    setWorkbenchOpen,
    setWorkbenchTab,
    onOptimizePropose,
    onRetryStructure,
    onProjectPrompt,
    onScopePrompt,
    projectPrompts,
    onResume,
    onSend,
    openTopic,
    sclPreviewFor,
    scopedPrompts,
    sendTurn,
    setCanvas,
    setCanvasTab,
    setDraft,
    setFile,
    startNew,
    writebackHintFor,
  };
}
