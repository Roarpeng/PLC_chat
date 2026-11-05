import { useCallback, useEffect, useState } from "react";
import {
  chatPlcJob,
  fetchPlcJob,
  fetchPlcJobBrief,
  listPlcJobs,
  probePlcJobExport,
  plcJobExportUrl,
  type PlcChatMessage,
  type PlcExportProbe,
  type PlcJobDetail,
  type PlcJobSummary,
  type PlcProjectBrief,
} from "../lib/plcGateway";
import { pickActiveJobId } from "../state/sourceCompare";
import { ProjectBriefCard } from "../ProjectBrief";
import { PlcCoverageStrip } from "../CoverageStrip";
import { DeviceSensorPanel } from "../DeviceSensorPanel";
import { CitationSourceList } from "../canvas/CitationSourceList";
import type { CanvasJumpIntent } from "../canvas/jump";
import "./ProjectProgressPanel.css";

type Props = {
  projectName?: string;
  onClose: () => void;
  onJumpCanvas?: (intent: CanvasJumpIntent) => void;
};

const STATUS_TEXT: Record<string, string> = {
  ready: "就绪",
  running: "进行中",
  failed: "失败",
  error: "失败",
  queued: "排队中",
  pending: "待处理",
  cancelled: "已取消",
};

function statusText(status: string): string {
  return STATUS_TEXT[status] || status || "未注明";
}

function statusClass(status: string): string {
  if (status === "ready") return "is-ok";
  if (status === "failed" || status === "error" || status === "cancelled") return "is-fail";
  if (status === "running" || status === "queued" || status === "pending") return "is-warn";
  return "";
}

/** 耗时只从真实响应的 timing / progress.duration_ms 聚合；无数据返回 null。 */
function totalDuration(detail: PlcJobDetail | null, brief: PlcProjectBrief | null): string | null {
  const fmt = (ms: unknown): string | null => {
    const n = Number(ms);
    if (!Number.isFinite(n) || n < 0) return null;
    if (n < 1000) return `${Math.round(n)} ms`;
    if (n < 60_000) return `${(n / 1000).toFixed(1)} s`;
    return `${(n / 60_000).toFixed(1)} min`;
  };
  const timing = (brief?.timing || {}) as Record<string, unknown>;
  for (const key of ["total_ms", "skeleton_ms"]) {
    const d = fmt(timing[key]);
    if (d) return d;
  }
  const steps = Array.isArray(detail?.progress) ? detail?.progress ?? [] : [];
  const sum = steps.reduce(
    (acc, s) => acc + (typeof s?.duration_ms === "number" ? s.duration_ms : 0),
    0,
  );
  return sum > 0 ? fmt(sum) : null;
}

/**
 * 工程进度看板：单一数据源 = 真实网关 /jobs、/jobs/{id}、/jobs/{id}/brief、
 * /jobs/{id}/export。挂载三个原本只在 barrel 导出的孤儿组件；所有数值来自响应，
 * 缺失一律如实标注，绝不写死任何后端结论。
 */
export function ProjectProgressPanel({ projectName, onClose, onJumpCanvas }: Props) {
  const [jobs, setJobs] = useState<PlcJobSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PlcJobDetail | null>(null);
  const [brief, setBrief] = useState<PlcProjectBrief | null>(null);
  const [probe, setProbe] = useState<PlcExportProbe | null>(null);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [loadNote, setLoadNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [chatInput, setChatInput] = useState("");
  const [chatTurn, setChatTurn] = useState<PlcChatMessage | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatBusy, setChatBusy] = useState(false);

  const refreshJobs = useCallback(async () => {
    setBusy(true);
    setJobsError(null);
    try {
      const list = await listPlcJobs(20);
      setJobs(list);
      setSelectedId((cur) => {
        if (cur && list.some((j) => j.id === cur)) return cur;
        return pickActiveJobId(list, projectName || "") ?? list[0]?.id ?? null;
      });
    } catch (err) {
      setJobs([]);
      setJobsError(err instanceof Error ? err.message : "加载作业列表失败");
    } finally {
      setBusy(false);
    }
  }, [projectName]);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setBrief(null);
      setProbe(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setLoadNote(null);
    setDetail(null);
    setBrief(null);
    setProbe(null);
    void (async () => {
      const results = await Promise.allSettled([
        fetchPlcJob(selectedId),
        fetchPlcJobBrief(selectedId),
        probePlcJobExport(selectedId),
      ]);
      if (cancelled) return;
      const failures: string[] = [];
      if (results[0].status === "fulfilled") setDetail(results[0].value);
      else failures.push(`作业详情：${results[0].reason instanceof Error ? results[0].reason.message : String(results[0].reason)}`);
      if (results[1].status === "fulfilled") setBrief(results[1].value);
      else failures.push(`工程简报：${results[1].reason instanceof Error ? results[1].reason.message : String(results[1].reason)}`);
      if (results[2].status === "fulfilled") setProbe(results[2].value);
      else
        setProbe({
          exists: false,
          status: 0,
          filename: null,
          contentType: null,
          reason: `导出探测失败（${results[2].reason instanceof Error ? results[2].reason.message : String(results[2].reason)}）`,
        });
      setLoadNote(failures.length ? failures.join("；") : null);
      setBusy(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selected = jobs.find((j) => j.id === selectedId) || null;
  const cov = detail?.coverage ?? null;
  const todos = (cov?.top_untranslated_parts || []).slice(0, 6);
  const gaps = (brief?.export_gaps || []).slice(0, 8);
  const warnings: string[] = Array.isArray((cov as any)?.warnings) ? (cov as any).warnings : [];
  const duration = totalDuration(detail, brief);

  const risks: string[] = [];
  if (selected?.error) risks.push(`作业错误：${selected.error}`);
  if (selected && selected.status !== "ready") risks.push(`作业状态未就绪：${statusText(selected.status)}`);
  gaps.forEach((g) => risks.push(`导出缺口：${g.block}${g.reason ? `（${g.reason}）` : ""}`));
  warnings.forEach((w) => risks.push(`覆盖率告警：${w}`));
  if (!detail) risks.push("作业详情未返回，结构缺口无法核对");

  const askJob = useCallback(async () => {
    const q = chatInput.trim();
    if (!q || !selectedId) return;
    setChatBusy(true);
    setChatError(null);
    setChatTurn(null);
    try {
      setChatTurn(await chatPlcJob(selectedId, q));
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "块级只读问答失败");
    } finally {
      setChatBusy(false);
    }
  }, [chatInput, selectedId]);

  return (
    <div
      className="pp-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="pp-panel" role="dialog" aria-modal="true" aria-label="工程进度看板">
        <header className="pp-head">
          <div>
            <strong>工程进度看板</strong>
            <div className="muted">
              单一数据源：/jobs · /jobs/&#123;id&#125; · /jobs/&#123;id&#125;/brief · /jobs/&#123;id&#125;/export
            </div>
          </div>
          <div className="pp-head-actions">
            <button type="button" className="pp-btn" disabled={busy} onClick={() => void refreshJobs()}>
              刷新
            </button>
            <button type="button" className="pp-btn" onClick={onClose} aria-label="关闭进度看板">
              关闭
            </button>
          </div>
        </header>

        <div className="pp-body">
          <section className="pp-section">
            <h4>作业列表（GET /jobs?limit=20）</h4>
            <div className="pp-section-body">
              {jobsError ? <p className="pp-empty">加载失败：{jobsError}</p> : null}
              {jobs.length ? (
                <ul className="pp-jobs" aria-label="PLC 解析作业">
                  {jobs.map((j) => (
                    <li key={j.id}>
                      <button
                        type="button"
                        className={selectedId === j.id ? "on" : ""}
                        onClick={() => setSelectedId(j.id)}
                      >
                        <span className="pp-job-id">{j.id}</span>
                        <span className={`pp-badge ${statusClass(j.status)}`}>{statusText(j.status)}</span>
                        {j.project_name ? <span className="pp-job-name">{j.project_name}</span> : null}
                        <span className="pp-job-flags">
                          {typeof j.export_ready === "boolean"
                            ? `导出${j.export_ready ? "就绪" : "未就绪"}`
                            : "导出未知"}
                          {" · "}
                          {typeof j.brief_ready === "boolean"
                            ? `简报${j.brief_ready ? "就绪" : "未就绪"}`
                            : "简报未知"}
                          {j.ingest_phase ? ` · ${j.ingest_phase}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="pp-empty">网关 /jobs 未返回作业（列表为空或端点不可用）。</p>
              )}
            </div>
          </section>

          <section className="pp-section">
            <h4>状态 · 耗时 · 覆盖率 · TODO</h4>
            <div className="pp-section-body">
              {loadNote ? <p className="pp-empty">部分数据未返回：{loadNote}</p> : null}
              <div className="pp-kv">
                <span className="k">当前作业</span>
                <span>{selectedId || "未选中"}</span>
                <span className="k">作业状态</span>
                <span>{selected ? statusText(selected.status) : "网关未返回作业"}</span>
                <span className="k">耗时</span>
                <span>{duration || "网关未返回耗时（timing / progress.duration_ms 缺失）"}</span>
                <span className="k">覆盖率</span>
                <span>
                  {typeof cov?.total_blocks === "number" && typeof cov?.converted === "number"
                    ? `已转换 ${cov.converted}/${cov.total_blocks}${
                        typeof cov.todo_rate === "number"
                          ? ` · TODO ${(cov.todo_rate * 100).toFixed(1)}%`
                          : ""
                      }`
                    : "网关未返回覆盖率"}
                </span>
                <span className="k">TODO 部件</span>
                <span>
                  {todos.length
                    ? todos.map((t) => `${t.name || "?"} × ${t.count ?? 0}`).join("、")
                    : "网关未返回未译 Part"}
                </span>
              </div>
              {detail ? (
                <PlcCoverageStrip detail={detail} busy={busy} />
              ) : (
                <p className="pp-empty">作业详情未返回，覆盖率条暂不可用。</p>
              )}
            </div>
          </section>

          <section className="pp-section">
            <h4>风险与缺口（来自真实响应）</h4>
            <div className="pp-section-body">
              {risks.length ? (
                <ul className="pp-list">
                  {risks.map((r, i) => (
                    <li key={`${r}-${i}`}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p className="pp-empty">真实响应未给出风险/缺口条目。</p>
              )}
            </div>
          </section>

          <section className="pp-section">
            <h4>交付物（GET /jobs/&#123;id&#125;/export 真实探测）</h4>
            <div className="pp-section-body">
              {typeof selected?.export_ready === "boolean" ? (
                <p className="pp-empty">作业详情 export_ready：{String(selected.export_ready)}</p>
              ) : null}
              {!probe ? (
                <p className="pp-empty">选中作业后自动请求真实导出端点探测资源是否存在。</p>
              ) : probe.exists ? (
                <div>
                  <p className="pp-empty">
                    导出包：{probe.filename || "网关未返回文件名"}
                    {probe.contentType ? ` · ${probe.contentType}` : ""}
                  </p>
                  <a className="pp-download" href={plcJobExportUrl(selectedId || "")}>
                    下载真实导出包
                  </a>
                </div>
              ) : (
                <p className="pp-empty">
                  当前作业暂无可下载交付包。原因：{probe.reason || "网关未返回原因"}
                </p>
              )}
            </div>
          </section>

          <section className="pp-section">
            <h4>工程简报（GET /jobs/&#123;id&#125;/brief）</h4>
            <div className="pp-section-body">
              {brief ? (
                <ProjectBriefCard
                  brief={brief}
                  onAsk={(p) => setChatInput(p)}
                  onJumpCanvas={onJumpCanvas}
                />
              ) : (
                <p className="pp-empty">网关未返回工程简报。</p>
              )}
            </div>
          </section>

          <section className="pp-section pp-chat">
            <h4>基于该作业提问（POST /jobs/&#123;id&#125;/chat · 块级只读问答）</h4>
            <div className="pp-section-body">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void askJob();
                }}
              >
                <input
                  type="search"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="例如：这个块做什么？"
                  aria-label="块级只读问答输入"
                />
                <button type="submit" className="pp-btn" disabled={chatBusy || !chatInput.trim() || !selectedId}>
                  {chatBusy ? "提问中…" : "提问"}
                </button>
              </form>
              {chatError ? <p className="pp-empty">问答失败：{chatError}</p> : null}
              {chatTurn ? (
                <div className="pp-chat-answer">
                  <div className="pp-chat-text">{chatTurn.text}</div>
                  <CitationSourceList
                    citations={chatTurn.citations ?? []}
                    emptyHint="本次回答网关未返回引用源（citations 为空）。"
                  />
                </div>
              ) : null}
            </div>
          </section>

          <section className="pp-section">
            <h4>设备 / 传感器（GET /jobs/&#123;id&#125;/device-cards）</h4>
            <div className="pp-section-body">
              <DeviceSensorPanel jobId={selectedId} onJumpCanvas={onJumpCanvas} />
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
