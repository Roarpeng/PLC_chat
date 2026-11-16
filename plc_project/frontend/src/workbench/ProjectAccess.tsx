import React, { useState } from "react";
import { v2Api } from "../state/workbench_v2";
import { V2_ROUTE } from "./featureFlags";

function openProject(projectId: string) {
  const url = new URL(window.location.href);
  if (url.searchParams.get("project_id") !== projectId) url.searchParams.delete("job_id");
  url.searchParams.set("project_id", projectId);
  url.hash = V2_ROUTE;
  if (url.href === window.location.href) window.location.reload();
  else window.location.assign(url);
}

export function ProjectLookup() {
  const [id, setId] = useState("");
  return (
    <form className="wb-project-lookup" onSubmit={(event) => {
      event.preventDefault();
      if (id.trim()) openProject(id.trim());
    }}>
      <label>
        <span>工程 ID</span>
        <input
          className="k-ledger wb-mono"
          value={id}
          onChange={(event) => setId(event.target.value)}
          placeholder="prj_…"
          spellCheck={false}
          autoComplete="off"
          required
        />
      </label>
      <button type="submit" className="k-btn" disabled={!id.trim()}>打开工程</button>
    </form>
  );
}

export function CreateProjectButton() {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  async function createProject() {
    setCreating(true);
    setError("");
    try {
      const result = await v2Api.createProject();
      openProject(result.project_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法创建工程");
      setCreating(false);
    }
  }

  return (
    <>
      <button type="button" className="k-btn k-btn--clay" disabled={creating} onClick={createProject}>
        <span aria-hidden="true">＋</span> {creating ? "正在创建…" : "新建 V2 工程"}
      </button>
      {error && <p className="wb-inline-error" role="alert">{error}</p>}
    </>
  );
}

export function ImportStationProject() {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Awaited<ReturnType<typeof v2Api.importStation>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function inspect(confirm: boolean) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const result = await v2Api.importStation(file, confirm);
      if (confirm && result.project_id) openProject(result.project_id);
      else setReport(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取 AF 工程");
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="wb-tree__lookup">
      <summary>导入 AF 工程</summary>
      <div className="af-stack">
        <label>AF 画布 JSON、源码包或 .zap19
          <input type="file" accept=".json,.zip,.zap19" disabled={busy} onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setReport(null);
            setError("");
          }} />
        </label>
        <button className="k-btn k-btn--sm" disabled={!file || busy} onClick={() => void inspect(false)}>检查兼容性</button>
        {report && <>
          <p>{report.name} · {report.station_count} 工位{report.device_count === null ? "" : " · " + report.device_count + " 设备"}</p>
          <code>{report.af_profile}</code>
          {!report.can_import && <p>{report.compatible ? "已识别 AF 工位结构" : "AF 结构未通过兼容性检查"}</p>}
          {report.questions.slice(0, 8).map((issue, index) => <p key={index}>{issue.reason}</p>)}
          {report.can_import && <button className="k-btn k-btn--sm" disabled={busy} onClick={() => void inspect(true)}>确认导入</button>}
        </>}
        {error && <p role="alert" className="wb-inline-error">{error}</p>}
      </div>
    </details>
  );
}
