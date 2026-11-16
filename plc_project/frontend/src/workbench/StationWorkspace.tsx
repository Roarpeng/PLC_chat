import React, { useEffect, useState } from "react";
import { GF_BASE, GFRequestError } from "../state/greenfield";
import { V2_API, newRequestId, v2Api, type JobView, type WorkbenchViewState } from "../state/workbench_v2";
import { DiagnosticsPane, TopIdentityBar } from "./components";
import { CreateProjectButton, ImportStationProject, ProjectLookup } from "./ProjectAccess";
import { StationCanvas } from "./StationCanvas";
import { StationTimeline } from "./StationFlowEditor";
import { StationDevices, StationHardware } from "./StationHardware";
import { StationSteps } from "./StationSteps";
import { actionNode, designDiff, emptyFlow, entityId, insertBefore, type Device, type DeviceProfile, type Flow, type Station, type StationDesign } from "./stationDesign";
import "./station-workspace.css";

type View = "hardware" | "stations" | "devices" | "steps" | "flow" | "timeline" | "review" | "delivery";
type Issue = { node_id?: string; source_id?: string; reason: string };
type Proposal = Awaited<ReturnType<typeof v2Api.intent>>;
type Frame = { time_ms: number; name: string; event: string; station_id: string; node_id: string };
type SourceLink = { canvas_node_id: string; scl_file: string; scl_line: number; tia_block: string };
const SCENARIOS = [["normal_cycle", "正常反馈"], ["feedback_timeout", "反馈超时"], ["negative_feedback", "条件不成立"], ["interlock_blocked", "启动许可未满足"], ["interlock_lost", "运行中联锁失效"], ["handoff_timeout", "交接确认超时"]];
const TERMINAL = ["FAILED", "NATIVE_ARCHIVED", "RECOVERY_REQUIRED", "CANCELLED"];

function issuesFrom(error: unknown): Issue[] {
  if (error instanceof GFRequestError) {
    const issues = (error.details as { issues?: Issue[] } | null)?.issues;
    if (Array.isArray(issues) && issues.length) return issues;
  }
  return [{ reason: error instanceof Error ? error.message : "工程操作失败" }];
}

export function StationWorkspace({ initial, previousRelease, state, onSwitch }: {
  initial: StationDesign; previousRelease: { id: string; revision: number } | null;
  state: WorkbenchViewState; onSwitch: (target: "legacy" | "classic") => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [catalog, setCatalog] = useState<DeviceProfile[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [saved, setSaved] = useState(initial);
  const [revision, setRevision] = useState(state.baseRevision);
  const [history, setHistory] = useState<StationDesign[]>([]);
  const [future, setFuture] = useState<StationDesign[]>([]);
  const [view, setView] = useState<View>("flow");
  const [scope, setScope] = useState("");
  const [node, setNode] = useState("");
  const [stationName, setStationName] = useState("");
  const [busy, setBusy] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [release, setRelease] = useState(previousRelease);
  const [jobId, setJobId] = useState(() => new URLSearchParams(window.location.search).get("job_id") ?? "");
  const [job, setJob] = useState<JobView | null>(null);
  const [compareRevision, setCompareRevision] = useState("");
  const [versions, setVersions] = useState<number[]>([]);
  const [baseline, setBaseline] = useState<StationDesign | null>(null);
  const [preview, setPreview] = useState<{ files: Record<string, string>; path: string; links: SourceLink[] } | null>(null);
  const [trace, setTrace] = useState<Frame[]>([]);
  const [status, setStatus] = useState("");
  const dirty = draft !== saved;
  const pid = state.projectId;
  const selectedStation = draft.stations.find((item) => item.id === scope);

  useEffect(() => {
    let live = true;
    v2Api.stationCatalog().then((entries) => { if (live) setCatalog(entries); })
      .catch(() => { if (live) setCatalogError("设备目录读取失败。"); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [dirty]);

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const reply = await v2Api.job(jobId);
        if (!active) return;
        if (reply.data) {
          setJob(reply.data);
          if (TERMINAL.includes(reply.data.state)) return;
        }
      } catch (error) {
        if (active && error instanceof GFRequestError && error.status === 404) return;
      }
      if (active) timer = window.setTimeout(() => void poll(), 3000);
    };
    void poll();
    return () => { active = false; window.clearTimeout(timer); };
  }, [jobId]);

  function select(next: View, nextScope = "") {
    setView(next);
    if (nextScope !== scope || !["steps", "flow", "timeline"].includes(next)) setNode("");
    if (nextScope !== scope) {
      setTrace([]);
      setProposal(null);
    }
    setScope(nextScope);
    if (next === "review") void run(async () => {
      const list = await v2Api.revisions(pid);
      setVersions(list.map((entry) => entry.revision));
    });
  }

  function update(next: StationDesign) {
    setHistory((items) => [...items.slice(-39), draft]);
    setFuture([]);
    setDraft(next);
    setPreview(null);
    setTrace([]);
  }

  function updateFlow(flow: Flow, additions: { device?: Device; station?: Station } = {}) {
    const { device, station } = additions;
    update(selectedStation ? {
      ...draft, stations: draft.stations.map((item) => item.id === scope ? { ...item, ...(station?.id === scope ? station : {}), flow,
        devices: device ? item.devices.some((entry) => entry.id === device.id) ?
          item.devices.map((entry) => entry.id === device.id ? device : entry) : [...item.devices, device] : item.devices } : item),
    } : { ...draft, flow, stations: station ?
      draft.stations.some((item) => item.id === station.id) ? draft.stations.map((item) => item.id === station.id ? station : item) :
        [...draft.stations, station] : draft.stations });
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setIssues([]);
    setStatus("");
    try {
      await action();
    } catch (error) {
      setIssues(issuesFrom(error));
      setDiagnosticsOpen(true);
    } finally {
      setBusy(false);
    }
  }

  async function commit(value: StationDesign, base: number) {
    const result = await v2Api.patch({
      project_id: pid, base_revision: base, request_id: newRequestId(),
      ops: [{ op: "set_station_design", design: value }],
    });
    if (!result.ok || !result.data) throw new Error(result.message || "草稿未保存");
    setRevision(result.data.revision);
    setSaved(value);
    setDraft(value);
    setStatus("草稿已保存");
    return result.data.revision;
  }

  async function readServer() {
    const response = await v2Api.getIr(pid);
    const design = response.data?.ir.station_design as StationDesign | undefined;
    if (!design || !response.data) throw new Error("无法读取服务器草稿。");
    setDraft(design);
    setSaved(design);
    setRevision(response.data.revision);
    setHistory([]);
    setFuture([]);
    setProposal(null);
    setPreview(null);
    setTrace([]);
  }

  async function validate() {
    const current = dirty ? await commit(draft, revision) : revision;
    const result = await v2Api.validate(pid, current, newRequestId());
    const report = result.data as { passed?: boolean; issues?: Issue[] } | null;
    setIssues(report?.issues ?? []);
    setDiagnosticsOpen(!report?.passed);
    setStatus(report?.passed ? "工程校验通过" : "请处理诊断中的问题");
    return { ok: Boolean(report?.passed), revision: current };
  }

  function jump(issue: Issue) {
    const id = issue.node_id || issue.source_id || "";
    const station = draft.stations.find((item) => [item.id, ...item.devices.map((device) => device.id),
      ...(item.interlocks ?? []).map((condition) => condition.id),
      ...item.flow.nodes.flatMap((node) => [node.id, ...node.permissions?.map((rule) => rule.id) ?? []]),
      ...item.flow.edges.map((edge) => edge.id), ...item.flow.wires?.map((wire) => wire.id) ?? []].includes(id));
    if (station) {
      const deviceScope = station.devices.some((item) => item.id === id) || station.interlocks?.some((item) => item.id === id);
      const owner = station.flow.nodes.find((item) => item.permissions?.some((rule) => rule.id === id));
      select(deviceScope ? "devices" : "flow", station.id);
      setNode(owner?.id ?? station.flow.edges.find((edge) => edge.id === id)?.from_id ?? station.flow.wires?.find((wire) => wire.id === id)?.from_id ?? id);
    } else if (draft.flow.nodes.some((item) => item.id === id) || draft.flow.edges.some((item) => item.id === id) || draft.flow.wires?.some((item) => item.id === id) || id === "flow") {
      select("flow");
      setNode(draft.flow.edges.find((edge) => edge.id === id)?.from_id || draft.flow.wires?.find((wire) => wire.id === id)?.from_id || id);
    } else {
      select("hardware");
    }
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "nearest" }));
  }

  const tab = (label: string, next: View, nextScope = "") => (
    <button type="button" className="af-nav-item" disabled={busy} aria-current={view === next && scope === nextScope ? "page" : undefined}
      onClick={() => select(next, nextScope)}>{label}</button>
  );
  const changes = designDiff(saved, draft);
  const suggested = proposal?.ops[0]?.design as StationDesign | undefined;
  const suggestedChanges = suggested ? designDiff(saved, suggested) : [];
  const proposedStation = suggested?.stations.find((item) => item.id === scope);
  const proposedFlow = scope ? proposedStation?.flow : suggested?.flow;

  return (
    <div className="wb-shell af-shell">
      <TopIdentityBar state={state} projectLoaded onSwitch={(target) => {
        if (!dirty || window.confirm("草稿有尚未保存的修改。离开当前工作台？")) onSwitch(target);
      }} />
      <div className="af-workspace" aria-busy={busy}>
        <aside className="af-tree" aria-label="工程目录">
          <div className="k-ochre-head"><h2 className="k-title">工程目录</h2></div>
          <div className="af-tree-body">
            <p className="af-tree-project">{draft.name}</p>
            <code>rev {revision} {dirty ? "· 草稿" : ""}</code>
            <nav>
              {tab("项目画布", "flow")}
              {tab("硬件组态", "hardware")}
              {tab("工位清单", "stations")}
              {draft.stations.map((item) => (
                <div className="af-tree-station" key={item.id}>
                  {tab(item.name, "flow", item.id)}
                  {scope === item.id && <>
                    {tab("工位设备", "devices", item.id)}
                    {tab("动作步骤", "steps", item.id)}
                    {tab("工位时序", "timeline", item.id)}
                  </>}
                </div>
              ))}
              {tab("项目时序", "timeline")}
              {tab("变更审核", "review")}
              {tab("AF 生成", "delivery")}
            </nav>
            <details className="af-switch">
              <summary>切换工程</summary>
              <ProjectLookup />
              <CreateProjectButton />
              <ImportStationProject />
            </details>
          </div>
        </aside>
        <main id="workbench-main" tabIndex={-1} className={"af-main" + (view === "flow" ? " af-main-canvas" : "")}>
          <header className="af-toolbar">
            <div><div className="af-breadcrumb">
              {selectedStation ? <><button type="button" disabled={busy} onClick={() => select("flow")}>{draft.name}</button><span>/</span><span>工位画布</span></> : <span>{view === "flow" ? "项目画布" : "项目"}</span>}
            </div>
              <h1 className="k-title">{selectedStation?.name ?? draft.name}</h1>
            </div>
            <div className="af-toolbar-actions">
              <button className="k-btn k-btn--sm" disabled={!history.length || busy} onClick={() => {
                setFuture([draft, ...future]); setDraft(history[history.length - 1]); setHistory(history.slice(0, -1));
                setPreview(null); setTrace([]);
              }}>撤销</button>
              <button className="k-btn k-btn--sm" disabled={!future.length || busy} onClick={() => {
                setHistory([...history, draft]); setDraft(future[0]); setFuture(future.slice(1));
                setPreview(null); setTrace([]);
              }}>重做</button>
              <button className="k-btn k-btn--sm" disabled={busy} onClick={() => void run(async () => { await validate(); })}>检查工程</button>
              <button className="k-btn k-btn--clay k-btn--sm" disabled={!dirty || busy} onClick={() => void run(async () => { await commit(draft, revision); })}>保存草稿</button>
            </div>
          </header>
          {status && <p className="af-status" role="status">{status}</p>}
          {issues.length > 0 && <div className="af-errors" role="status">
            {issues.slice(0, 8).map((issue, index) => <button className="af-error-link" key={index} onClick={() => jump(issue)}>{issue.reason}</button>)}
            <button className="k-btn k-btn--sm" disabled={busy} onClick={() => {
              if (!dirty || window.confirm("重新读取会丢弃本地未保存的修改。继续？")) void run(readServer);
            }}>重新读取</button>
          </div>}
          <fieldset className="af-content" disabled={busy}>
            {view === "hardware" && <>
              <div className="af-pane">
                <label>项目名称<input value={draft.name} maxLength={100} onChange={(event) => update({ ...draft, name: event.target.value })} /></label>
              </div>
              <StationHardware hardware={draft.hardware} update={(hardware) => update({ ...draft, hardware })} />
              <button className="k-btn" onClick={() => select("stations")}>继续配置工位 →</button>
            </>}
            {view === "stations" && <section className="af-pane">
              <h2 className="k-title">工位清单</h2>
              <form className="af-inline" onSubmit={(event) => {
                event.preventDefault();
                if (!stationName.trim()) return;
                const item = { id: entityId("st"), name: stationName.trim(), devices: [], flow: emptyFlow() };
                update({ ...draft, stations: [...draft.stations, item] });
                setStationName("");
                select("flow", item.id);
              }}>
                <label>工位名称<input value={stationName} maxLength={100} onChange={(event) => setStationName(event.target.value)} /></label>
                <button type="submit" className="k-btn k-btn--sm" disabled={!stationName.trim()}>创建工位</button>
              </form>
              {draft.stations.map((item) => (
                <div className="af-record" key={item.id}>
                  <label>工位名称<input value={item.name} onChange={(event) => update({
                    ...draft, stations: draft.stations.map((station) => station.id === item.id ? { ...station, name: event.target.value } : station),
                  })} /></label>
                  <span>{item.devices.length} 个设备</span>
                  <button className="k-btn k-btn--sm" onClick={() => select("flow", item.id)}>进入工位</button>
                  <button className="k-btn k-btn--sm" disabled={draft.flow.nodes.some((entry) => entry.station_ids.includes(item.id))}
                    onClick={() => update({ ...draft, stations: draft.stations.filter((station) => station.id !== item.id) })}>移除工位</button>
                </div>
              ))}
            </section>}
            {view === "devices" && selectedStation && <>
              {catalogError && <p role="alert" className="wb-inline-error">{catalogError}</p>}
              <StationDevices key={scope} station={selectedStation} hardware={draft.hardware} catalog={catalog}
                update={(item) => update({ ...draft, stations: draft.stations.map((station) => station.id === scope ? item : station) })}
                onDescribe={() => {
                  select("flow", scope);
                  document.getElementById("af-intent-text")?.focus();
                }}
                onAction={(device, preset) => {
                  const item = actionNode(device, preset);
                  try {
                    updateFlow(insertBefore(selectedStation.flow, item));
                    select("flow", scope);
                    setNode(item.id);
                  } catch (reason) {
                    setIssues(issuesFrom(reason));
                    select("steps", scope);
                  }
                }}
              />
              <button className="k-btn" onClick={() => select("steps", scope)}>打开动作步骤 →</button>
            </>}
            {view === "steps" && selectedStation && <StationSteps key={scope} station={selectedStation} catalog={catalog}
              selected={node} select={setNode} update={updateFlow} openGraph={() => select("flow", scope)} />}
            {view === "flow" && <>
              {catalogError && selectedStation && <p role="alert" className="wb-inline-error">{catalogError}</p>}
              <StationCanvas key={scope || "project"} flow={selectedStation?.flow ?? draft.flow} station={selectedStation}
                stations={suggested?.stations ?? draft.stations} hardware={draft.hardware} selected={node} select={setNode}
                catalog={catalog} openStation={(id) => select("flow", id)} preview={proposedFlow} previewStation={proposedStation}
                problemIds={new Set(issues.flatMap((item) => [item.node_id ?? "", item.source_id ?? ""]))} projectFlow={draft.flow} update={updateFlow} />
            </>}
            {view === "timeline" && <>
                <StationTimeline flow={selectedStation?.flow ?? draft.flow} select={setNode} selected={node} update={updateFlow} />
                <div className="af-inline">
                  {SCENARIOS.map(([id, name]) => <button className="k-btn k-btn--sm" key={id} onClick={() => void run(async () => {
                    setTrace([]);
                    const current = dirty ? await commit(draft, revision) : revision;
                    const result = await v2Api.simulate(pid, current, newRequestId(), id, scope);
                    const report = result.data as { trace?: Frame[]; issues?: Issue[]; notice?: string } | null;
                    setTrace(report?.trace ?? []);
                    setIssues(report?.issues ?? []);
                    setDiagnosticsOpen(Boolean(report?.issues?.length));
                    setStatus(report?.issues?.length ? "请处理时序诊断中的问题" : report?.notice ?? "");
                  })}>{name}</button>)}
                </div>
                {trace.length > 0 && <TraceReview frames={trace} jump={(frame) => jump({ node_id: frame.node_id, reason: frame.name })}
                  labels={Object.fromEntries(draft.stations.map((item) => [item.id, item.name]))} />}
            </>}
            {view === "review" && <section className="af-pane">
              <h2 className="k-title">变更审核</h2>
              <label>比较基线<select value={compareRevision} onChange={(event) => {
                const selected = event.target.value;
                setCompareRevision(selected);
                if (!selected) { setBaseline(null); return; }
                void run(async () => {
                  const response = await v2Api.getIr(pid, Number(selected));
                  const design = response.data?.ir.station_design as StationDesign | undefined;
                  if (!design) throw new Error("该修订没有 AF 工位画布。");
                  setBaseline(design);
                });
              }}>
                <option value="">最近保存的草稿</option>
                {versions.map((item) => <option key={item} value={item}>修订 {item}</option>)}
              </select></label>
              <ChangeReview changes={baseline ? designDiff(baseline, draft) : changes} />
              {release && <p>最近确认生成：修订 {release.revision}</p>}
            </section>}
            {view === "delivery" && <section className="af-pane">
              <h2 className="k-title">AF 生成</h2>
              <div className="af-inline">
                <button className="k-btn k-btn--sm" onClick={() => void run(async () => {
                  const check = await validate();
                  if (!check.ok) return;
                  const result = await v2Api.preview(pid, check.revision, newRequestId());
                  const files = (result.data?.scl_files ?? {}) as Record<string, string>;
                  const mapping = result.data?.source_map as { mappings?: SourceLink[] } | undefined;
                  setPreview({ files, path: Object.keys(files)[0] ?? "", links: mapping?.mappings ?? [] });
                })}>生成 SCL 预览</button>
                <label>确认人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
                <button className="k-btn k-btn--sm" disabled={!reviewer.trim()} onClick={() => void run(async () => {
                  const check = await validate();
                  if (!check.ok) return;
                  const frozen = await v2Api.freeze(pid, check.revision);
                  const approved = await v2Api.approve(frozen.changeset_id, reviewer.trim(), frozen.before_hash);
                  setRelease({ id: approved.approved_changeset_id, revision: check.revision });
                  setStatus("已确认生成版本");
                })}>确认此修订</button>
              </div>
              {release && <a className="k-btn k-btn--sm" href={GF_BASE + V2_API + "/projects/" + encodeURIComponent(pid) +
                "/source-package?changeset_id=" + encodeURIComponent(release.id)}>下载 AF 源码包 · rev {release.revision}</a>}
              <hr className="k-perforation k-perforation--on-card" />
              <div className="af-inline">
                <button className="k-btn k-btn--sm"
                  disabled={!release || dirty || release.revision !== revision || Boolean(jobId && (!job || !TERMINAL.includes(job.state)))}
                  onClick={() => {
                    if (!release) return;
                    void run(async () => {
                      const queued = await v2Api.compileStation(pid, release.id);
                      const url = new URL(window.location.href);
                      url.searchParams.set("job_id", queued.job_id);
                      window.history.replaceState(null, "", url);
                      setJob(null);
                      setJobId(queued.job_id);
                    });
                  }}>V19 编译并归档</button>
                {jobId && <span role="status" className="wb-mono">{job?.state ?? "QUEUED"}</span>}
                {job?.compile && <span className="wb-mono">{job.compile.error_count} 错误 · {job.compile.warning_count} 警告</span>}
                {job?.native_artifact && job.evidence_level === "V19_real" && job.native_artifact.reopen_ok &&
                  <a className="k-btn k-btn--sm" href={GF_BASE + V2_API + "/artifacts/" + encodeURIComponent(job.native_artifact.artifact_id) +
                    "/download?" + new URLSearchParams({ project_id: pid, job_id: job.job_id, sha256: job.native_artifact.sha256 })}>下载 .zap19</a>}
              </div>
              <p className="af-context">在独立的 V19 工程中编译并验证重新打开。请填写 CPU 的完整目录标识，扩展模块清单随源码包提供。</p>
              {job && TERMINAL.includes(job.state) && job.state !== "NATIVE_ARCHIVED" && <p role="status">{job.notice}</p>}
              {job?.diagnostics?.map((item, index) => item.node_id
                ? <button className="af-error-link" key={index} onClick={() => jump(item)}>{item.reason}</button>
                : <p key={index}>{item.reason}</p>)}
              {preview?.path && <>
                <label>SCL 文件<select aria-label="SCL 文件" value={preview.path} onChange={(event) => setPreview({ ...preview, path: event.target.value })}>
                  {Object.keys(preview.files).map((path) => <option value={path} key={path}>{path}</option>)}
                </select></label>
                <pre className="k-well af-source">{preview.files[preview.path]}</pre>
                <div className="af-inline">
                  {[...new Map(preview.links.filter((item) => item.scl_file === preview.path)
                    .map((item) => [item.canvas_node_id, item])).values()].slice(0, 30).map((item) =>
                    <button type="button" key={item.canvas_node_id} className="k-btn k-btn--sm" onClick={() =>
                      jump({ node_id: item.canvas_node_id, reason: item.tia_block })}>查看画布 · L{item.scl_line}</button>)}
                </div>
              </>}
            </section>}
          </fieldset>
          <section className="af-ai af-pane" aria-label="自然语言编辑">
            <h2 className="k-title">自然语言编辑</h2>
            <form className="af-inline" onSubmit={(event) => {
              event.preventDefault();
              if (!message.trim() || busy) return;
              void run(async () => {
                const current = dirty ? await commit(draft, revision) : revision;
                const proposal = await v2Api.intent(pid, current, message.trim(), { station_id: scope, node_id: node });
                if (proposal.ops.length) select("flow", scope);
                setProposal(proposal);
              });
            }}>
              <label>{selectedStation ? selectedStation.name : "项目范围"}
                <textarea id="af-intent-text" value={message} maxLength={4000} onChange={(event) => setMessage(event.target.value)}
                  placeholder={selectedStation ? "例如：工件到位后，夹爪夹紧，再让伺服到工作位" : "例如：创建「工具工位 A」和「工具工位 B」"} />
              </label>
              <button className="k-btn" disabled={busy || !message.trim()}>预览修改</button>
            </form>
            {proposal && <div className="af-proposal">
              {proposal.questions?.map((question) => <p key={question}>{question}</p>)}
              {suggested && <>
                <p>{proposal.explanation} <small>{proposal.mode === "offline" ? "离线指令解析" : "模型提案"}</small></p>
                <button className="k-btn k-btn--clay k-btn--sm" disabled={busy || dirty || proposal.base_revision !== revision} onClick={() => void run(async () => {
                  await commit(suggested, proposal.base_revision);
                  setHistory((items) => [...items.slice(-39), draft]);
                  setFuture([]);
                  setProposal(null);
                  setMessage("");
                  select("flow", scope);
                })}>应用修改</button>
                {(dirty || proposal.base_revision !== revision) && <p>草稿已变化，请重新预览。</p>}
                <details><summary>查看变更明细</summary><ChangeReview changes={suggestedChanges} /></details>
              </>}
              <button className="k-btn k-btn--sm" onClick={() => setProposal(null)}>关闭预览</button>
            </div>}
          </section>
        </main>
      </div>
      <DiagnosticsPane diagnostics={issues.map((issue) => ({ sourceId: issue.node_id ?? issue.source_id ?? "工程", level: "error", message: issue.reason }))}
        open={diagnosticsOpen} onToggle={() => setDiagnosticsOpen(!diagnosticsOpen)} />
    </div>
  );
}

function TraceReview({ frames, labels, jump }: { frames: Frame[]; labels: Record<string, string>; jump: (frame: Frame) => void }) {
  const scopes = [...new Set(frames.map((item) => item.station_id))];
  const last = Math.max(frames[frames.length - 1]?.time_ms ?? 0, 10);
  const laneHeight = 36;
  const width = 720;
  const x = (time: number) => 140 + time / last * 560;
  return <section className="af-trace" aria-label="离线时序">
    <svg viewBox={"0 0 " + width + " " + ((scopes.length + 1) * laneHeight)} role="img" aria-label="工位时间轴">
      {scopes.map((scope, index) => {
        const lane = index * laneHeight + 20;
        return <g key={scope}>
          <text x="8" y={lane + 4}>{(labels[scope] ?? "项目").slice(0, 14)}</text>
          <line x1="140" x2="700" y1={lane} y2={lane} />
          {frames.filter((item) => item.station_id === scope).slice(0, 250).map((item, i) =>
            <circle key={i} cx={x(item.time_ms)} cy={lane} r="4"><title>{item.time_ms} ms · {item.name} · {item.event}</title></circle>)}
        </g>;
      })}
      <text x="140" y={scopes.length * laneHeight + 10}>0 ms</text>
      <text x="700" textAnchor="end" y={scopes.length * laneHeight + 10}>{last} ms</text>
    </svg>
    {frames.slice(0, 180).map((item, index) => <button key={index} className="af-trace-row" onClick={() => jump(item)}>
      <code>{item.time_ms} ms</code><span>{item.name}</span><code>{item.event}</code>
    </button>)}
  </section>;
}

function ChangeReview({ changes }: { changes: ReturnType<typeof designDiff> }) {
  return changes.length ? (
    <div className="af-changes">
      {changes.map((item) => <details key={item.id}>
        <summary>{item.kind} · {item.name} <code>{item.id}</code></summary>
        <div className="af-fields">
          <pre className="k-well">{JSON.stringify(item.before ?? null, null, 2)}</pre>
          <pre className="k-well">{JSON.stringify(item.after ?? null, null, 2)}</pre>
        </div>
      </details>)}
    </div>
  ) : <p>暂无差异。</p>;
}
