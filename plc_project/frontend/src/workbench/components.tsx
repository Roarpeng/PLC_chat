/** Shared Workbench chrome: evidence badge, project tree, inspector, diagnostics. */
import React from "react";
import {
  WORKBENCH_VIEWS,
  type Diagnostic,
  type WorkbenchView,
  type WorkbenchViewState,
} from "../state/workbench_v2";
import type { EvidenceLevel } from "./featureFlags";

const LEVEL_LABEL: Readonly<Record<EvidenceLevel, string>> = {
  offline: "offline · 离线",
  mocked: "mocked · 编排",
  V19_real: "V19 real · 真机",
  pending_real_machine: "pending_real_machine · 待真机",
};

export const EvidenceBadge: React.FC<{ level: EvidenceLevel }> = ({ level }) => (
  <span className={`wb-badge wb-badge--${level}`} data-ui="evidence-badge" data-level={level}>
    {LEVEL_LABEL[level]}
  </span>
);

export const ProjectTree: React.FC<{
  state: WorkbenchViewState;
  onSelectView: (view: WorkbenchView) => void;
}> = ({ state, onSelectView }) => (
  <aside className="wb-tree" data-ui="project-tree">
    <div className="wb-tree__title">PROJECT EXPLORER</div>
    <div className="wb-tree__project">{state.projectId || "（未选择工程）"}</div>
    <div className="wb-tree__meta">rev {state.baseRevision} · {state.irSha256.slice(7, 15) || "—"}</div>
    <nav className="wb-tree__nav">
      {WORKBENCH_VIEWS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`wb-tree__item ${state.activeView === item.id ? "is-active" : ""}`}
          onClick={() => onSelectView(item.id)}
          data-ui={`view-${item.id}`}
        >
          {item.label}
        </button>
      ))}
    </nav>
    <div className="wb-tree__section">工程骨架</div>
    <ul className="wb-tree__nodes">
      <li>TIA V19 骨架</li>
      <li>Unit 01 · EM01 Clamp</li>
      <li>CM01 cylClamp</li>
      <li>Block Index（服务端派生）</li>
    </ul>
    <div className="wb-tree__foot">视图与选择状态仅存前端；工程真值来自服务端 revision。</div>
  </aside>
);

export const Inspector: React.FC<{ state: WorkbenchViewState }> = ({ state }) => {
  const selected = state.selectedNodeId;
  return (
    <aside className="wb-inspector" data-ui="inspector">
      <div className="wb-inspector__title">INSPECTOR</div>
      <div className="wb-inspector__hint">
        源数据来自服务端 IR，不私建图内真值。选中节点：{selected ?? "（无）"}
      </div>
      {(state.nodeErrors[selected ?? ""] ?? []).map((err, idx) => (
        <div key={idx} className="wb-inspector__error" role="alert">{err}</div>
      ))}
      <section className="wb-inspector__block">
        <div className="wb-inspector__label">项目身份</div>
        <dl>
          <dt>project_id</dt><dd>{state.projectId}</dd>
          <dt>revision</dt><dd>{state.baseRevision}</dd>
          <dt>ir_sha256</dt><dd className="wb-mono">{state.irSha256 || "—"}</dd>
          <dt>AFProfile</dt><dd>{state.afProfile}</dd>
          <dt>evidence</dt><dd>{state.evidenceLevel}</dd>
        </dl>
      </section>
      <section className="wb-inspector__block">
        <div className="wb-inspector__label">服务端 IR 摘要（只读）</div>
        <pre className="wb-inspector__json" data-ui="inspector-json">
          {JSON.stringify(state.inspector ?? {}, null, 2).slice(0, 2600)}
        </pre>
      </section>
      <section className="wb-inspector__block">
        <div className="wb-inspector__label">ENGINEERING COPILOT</div>
        <p className="wb-inspector__hint">
          仅产出候选 Patch；批准 ChangeSet 与启动 TIA 交付由后端显式人工操作，LLM 不持有该工具。
        </p>
      </section>
    </aside>
  );
};

export const DiagnosticsPane: React.FC<{
  diagnostics: Diagnostic[];
  open: boolean;
  onToggle: () => void;
}> = ({ diagnostics, open, onToggle }) => (
  <section className={`wb-diagnostics ${open ? "is-open" : ""}`} data-ui="diagnostics">
    <button type="button" className="wb-diagnostics__toggle" onClick={onToggle}>
      DIAGNOSTICS · {diagnostics.length} 条 {open ? "▾" : "▸"}
    </button>
    {open && (
      <div className="wb-diagnostics__list">
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
  onSwitch: (target: "legacy" | "classic") => void;
}> = ({ state, onSwitch }) => (
  <header className="wb-topbar" data-ui="workbench-topbar">
    <span className="wb-topbar__brand">PLC AGENT V2 · 统一工程工作台</span>
    <span className="wb-topbar__field">project <b>{state.projectId}</b></span>
    <span className="wb-topbar__field">rev <b>{state.baseRevision}</b></span>
    <span className="wb-topbar__field wb-mono">{state.afProfile}</span>
    <EvidenceBadge level={state.evidenceLevel} />
    <span className="wb-topbar__spacer" />
    {state.conflict && (
      <span className="wb-topbar__conflict" role="alert">
        409 冲突 · current_revision={state.conflict.currentRevision}
      </span>
    )}
    <button type="button" className="wb-topbar__btn" onClick={() => onSwitch("legacy")} data-ui="switch-legacy">
      旧 4 步向导
    </button>
    <button type="button" className="wb-topbar__btn" onClick={() => onSwitch("classic")} data-ui="switch-classic">
      经典工作台
    </button>
  </header>
);
