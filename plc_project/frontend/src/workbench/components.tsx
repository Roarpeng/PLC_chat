/** Shared Workbench chrome: evidence badge, project tree, inspector, diagnostics. */
import React from "react";
import {
  WORKBENCH_VIEWS,
  type Diagnostic,
  type WorkbenchView,
  type WorkbenchViewState,
} from "../state/workbench_v2";
import type { EvidenceLevel } from "./featureFlags";
import { PaperAppearance } from "../styles/kronos/PaperAppearance";
import { CreateProjectButton, ImportStationProject, ProjectLookup } from "./ProjectAccess";

const VIEW_ICON: Record<WorkbenchView, string> = {
  overview: "M3 3h14v14H3z M3 8h14 M8 8v9",
  device: "M5 5h10v10H5z M1 7h4 M1 13h4 M15 7h4 M15 13h4 M8 8h4v4H8z",
  sequence: "M7 2h6v4H7z M10 6v8 M4 9h12 M7 14h6v4H7z",
  trace: "M2 15h4V5h5v10h4V8h3",
  diff: "M4 3h9v14H4z M7 7h3 M7 11h3 M15 6h2v11h-2",
  delivery: "M3 7h14v10H3z M3 7l2-4h10l2 4 M8 11h4",
};

const LEVEL_LABEL: Readonly<Record<EvidenceLevel, string>> = {
  offline: "离线数据",
  mocked: "模拟编排",
  V19_real: "V19 真机",
  pending_real_machine: "待真机验证",
};

export const EvidenceBadge: React.FC<{ level: EvidenceLevel }> = ({ level }) => (
  <span className={`wb-badge wb-badge--${level}`} data-ui="evidence-badge" data-level={level}>
    {LEVEL_LABEL[level]}
  </span>
);

export const ProjectTree: React.FC<{
  state: WorkbenchViewState;
  projectLoaded: boolean;
  onSelectView: (view: WorkbenchView) => void;
}> = ({ state, projectLoaded, onSelectView }) => (
  <aside className="wb-tree" data-ui="project-tree">
    <div className="wb-panel-head k-ochre-head">
      <h2 className="k-title">工程目录</h2>
    </div>
    <nav className="wb-tree__nav" aria-label="工程视图">
      {WORKBENCH_VIEWS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`wb-tree__item ${state.activeView === item.id ? "is-active kronos-selected" : ""}`}
          aria-current={state.activeView === item.id ? "page" : undefined}
          onClick={() => onSelectView(item.id)}
          data-ui={`view-${item.id}`}
        >
          <svg viewBox="0 0 20 20" className="k-icon" aria-hidden="true"><path d={VIEW_ICON[item.id]} /></svg>
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
    {projectLoaded && (
      <details className="wb-tree__lookup">
        <summary>切换工程</summary>
        <ProjectLookup />
        <div className="af-inline"><CreateProjectButton /></div>
        <ImportStationProject />
      </details>
    )}
  </aside>
);

export const Inspector: React.FC<{ state: WorkbenchViewState }> = ({ state }) => {
  const selected = state.selectedNodeId;
  return (
    <aside className="wb-inspector" data-ui="inspector">
      <div className="wb-panel-head k-ochre-head">
        <h2 className="k-title">工程检查器</h2>
      </div>
      <div className="wb-inspector__inner">
        <div className="wb-inspector__hint">选中节点 <code>{selected ?? "—"}</code></div>
        {(state.nodeErrors[selected ?? ""] ?? []).map((err, idx) => (
          <div key={idx} className="wb-inspector__error" role="alert">{err}</div>
        ))}
        <section className="wb-inspector__block">
          <h3 className="wb-inspector__label">工程身份</h3>
          <dl>
            <dt>工程 ID</dt><dd>{state.irSha256 ? state.projectId : "—"}</dd>
            <dt>修订</dt><dd>{state.irSha256 ? state.baseRevision : "—"}</dd>
            <dt>IR SHA256</dt><dd>{state.irSha256 || "—"}</dd>
            <dt>AF Profile</dt><dd>{state.irSha256 ? state.afProfile : "—"}</dd>
          </dl>
        </section>
        <section className="wb-inspector__block">
          <h3 className="wb-inspector__label">服务端 IR 摘要</h3>
          {state.inspector ? (
            <pre className="wb-inspector__json k-well" data-ui="inspector-json">
              {JSON.stringify(state.inspector, null, 2).slice(0, 2600)}
            </pre>
          ) : (
            <p className="wb-inspector__placeholder k-hatch" data-ui="inspector-json">
              {state.irSha256 ? "在元器件或步序视图选择节点以查看详情。" : "打开工程后查看 IR 详情。"}
            </p>
          )}
        </section>
      </div>
    </aside>
  );
};

export const DiagnosticsPane: React.FC<{
  diagnostics: Diagnostic[];
  open: boolean;
  onToggle: () => void;
}> = ({ diagnostics, open, onToggle }) => (
  <section className={`wb-diagnostics ${open ? "is-open" : ""}`} data-ui="diagnostics">
    <button type="button" className="wb-diagnostics__toggle" onClick={onToggle} aria-expanded={open} aria-controls="wb-diagnostics-list">
      <svg viewBox="0 0 20 20" className="k-icon" aria-hidden="true"><path d="M3 5h14v10H3z M6 8l2 2-2 2 M10 12h4" /></svg>
      <span>诊断记录</span><span className="wb-mono">{diagnostics.length} 条</span>
      <span className="wb-diagnostics__chevron" aria-hidden="true">{open ? "⌃" : "⌄"}</span>
    </button>
    {open && (
      <div className="wb-diagnostics__list" id="wb-diagnostics-list">
        {diagnostics.length === 0 && <div className="wb-diagnostics__empty">暂无诊断</div>}
        {diagnostics.map((item, idx) => (
          <div key={idx} className={`wb-diagnostics__row wb-diagnostics__row--${item.level}`}>
            <span className="wb-mono">[{item.sourceId}]</span> {item.message}
          </div>
        ))}
      </div>
    )}
  </section>
);

export const TopIdentityBar: React.FC<{
  state: WorkbenchViewState;
  projectLoaded: boolean;
  onSwitch: (target: "legacy" | "classic") => void;
}> = ({ state, projectLoaded, onSwitch }) => (
  <header className="wb-topbar" data-ui="workbench-topbar">
    <a className="wb-skip" href="#workbench-main" onClick={(event) => {
      event.preventDefault();
      document.getElementById("workbench-main")?.focus();
    }}>跳到工程视图</a>
    <div className="wb-topbar__brand">
      <span className="wb-topbar__mark" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="k-icon"><path d={VIEW_ICON.device} /></svg>
      </span>
      <div><strong>PLC Co-Pilot</strong><span>统一工程工作台 V2</span></div>
    </div>
    <div className="wb-topbar__status">
      {projectLoaded ? <EvidenceBadge level={state.evidenceLevel} /> : <span className="wb-badge">未载入工程</span>}
      {state.conflict && (
        <span className="wb-topbar__conflict" role="alert">
          409 修订冲突 · rev {state.conflict.currentRevision}
        </span>
      )}
    </div>
    <div className="wb-topbar__actions">
      <button type="button" className="k-btn k-btn--sm" onClick={() => onSwitch("legacy")} data-ui="switch-legacy">
        旧版向导
      </button>
      <button type="button" className="k-btn k-btn--sm" onClick={() => onSwitch("classic")} data-ui="switch-classic">
        经典工作台
      </button>
      <PaperAppearance />
    </div>
  </header>
);
