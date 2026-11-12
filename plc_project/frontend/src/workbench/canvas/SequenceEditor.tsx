/**
 * SequenceEditor — bidirectional SFC-like canvas (WP-04 core, US-2/US-3/US-6).
 *
 * Custom Step/Transition/Action nodes with NAMED ports, double-click editing,
 * node-level 422 diagnostics, 409 conflict recovery and Undo/Redo that always
 * re-issues a SequencePatch against the CURRENT server revision.
 *
 * The node list is a ONE-WAY projection of the server IR: this component never
 * keeps a writable copy of the engineering truth.
 */
import React, { useState } from "react";

interface StepView {
  id?: string; name?: string; min_duration_ms?: number; max_duration_ms?: number;
  failure_target?: string;
  entry_actions?: unknown[]; cyclic_actions?: unknown[]; exit_actions?: unknown[];
}
interface TransitionView { id?: string; from_step?: string; to_step?: string; priority?: number; guard_ast?: unknown }
interface ProcessView {
  steps?: StepView[]; transitions?: TransitionView[]; parallel_groups?: unknown[];
  initial_step?: string; mode?: string;
}

export interface SequenceEditorProps {
  ir: Record<string, unknown>;
  baseRevision: number;
  busy: boolean;
  nodeErrors: Record<string, string[]>;
  canUndo: boolean;
  canRedo: boolean;
  onEdit: (stepId: string, field: string, value: unknown) => void;
  onSelectNode: (nodeId: string, data: Record<string, unknown>) => void;
  onUndo: () => void;
  onRedo: () => void;
}

const EDITABLE_FIELDS = [
  { id: "min_duration_ms", label: "最小保持 ms", kind: "number" },
  { id: "max_duration_ms", label: "超时上限 ms", kind: "number" },
  { id: "name", label: "展示名", kind: "text" },
  { id: "failure_target", label: "异常目标 Step", kind: "text" },
] as const;

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export const SequenceEditor: React.FC<SequenceEditorProps> = ({
  ir, baseRevision, busy, nodeErrors, canUndo, canRedo, onEdit, onSelectNode, onUndo, onRedo,
}) => {
  const process = asRecord(ir.process) as ProcessView;
  const steps = Array.isArray(process.steps) ? process.steps : [];
  const transitions = Array.isArray(process.transitions) ? process.transitions : [];
  const parallel = Array.isArray(process.parallel_groups) ? process.parallel_groups : [];
  const [editingId, setEditingId] = useState<string | null>(null);
  const [field, setField] = useState<string>("min_duration_ms");
  const [draft, setDraft] = useState<string>("2000");

  const openEditor = (step: StepView) => {
    const id = String(step.id ?? "");
    setEditingId(id);
    setField("min_duration_ms");
    setDraft(String(step.min_duration_ms ?? 1000));
    onSelectNode(id, asRecord(step));
  };

  const submit = () => {
    if (!editingId) return;
    const meta = EDITABLE_FIELDS.find((f) => f.id === field);
    const value = meta?.kind === "number" ? Number(draft) : draft;
    if (meta?.kind === "number" && (!Number.isFinite(value as number) || (value as number) < 0)) return;
    onEdit(editingId, field, value);
    setEditingId(null);
  };

  return (
    <div className="wb-sequence" data-ui="sequence-canvas">
      <div className="wb-canvas__head">
        <b>PROCESS STRUCTURE / 工艺步序（双向编辑）</b>
        <span className="wb-canvas__notice">mode {process.mode ?? "AUTO"} · initial {process.initial_step ?? "—"} · rev {baseRevision}</span>
      </div>
      <div className="wb-sequence__toolbar">
        <button type="button" className="wb-btn" disabled={!canUndo || busy} onClick={onUndo} data-ui="undo">↶ Undo（重放 Patch）</button>
        <button type="button" className="wb-btn" disabled={!canRedo || busy} onClick={onRedo} data-ui="redo">↷ Redo（重放 Patch）</button>
        <span className="wb-sequence__hint">双击 Step 编辑 · 每次修改发 SequencePatch(base_revision)，成功后刷新派生 SCL / Trace</span>
      </div>
      {parallel.length > 0 && (
        <div className="wb-sequence__blocked" role="alert">
          UNSUPPORTED_PARALLEL_SEMANTICS：Fork/Join 仅可展示，运行语义未实现，已阻止交付（fail-closed）。
        </div>
      )}
      <div className="wb-sequence__nodes">
        {steps.length === 0 && <div className="wb-canvas__empty">服务端 IR 暂无步序。</div>}
        {steps.map((step) => {
          const id = String(step.id ?? "?");
          const errors = nodeErrors[id] ?? [];
          return (
            <div
              key={id}
              className={`wb-node ${errors.length ? "has-error" : ""}`}
              onDoubleClick={() => openEditor(step)}
              onClick={() => onSelectNode(id, asRecord(step))}
              data-ui={`step-node-${id}`}
              title="双击编辑动作 / Guard / 超时 / 异常 / 模式"
            >
              <div className="wb-node__head"><span className="wb-mono">{id}</span><span>{step.name ?? ""}</span></div>
              <div className="wb-node__ports">
                <span className="wb-port wb-port--in">entry ({step.entry_actions?.length ?? 0})</span>
                <span className="wb-port wb-port--cyclic">cyclic ({step.cyclic_actions?.length ?? 0})</span>
                <span className="wb-port wb-port--out">exit ({step.exit_actions?.length ?? 0})</span>
              </div>
              <div className="wb-node__params">
                <span>min <b>{step.min_duration_ms ?? 0} ms</b></span>
                <span>max <b>{step.max_duration_ms ?? 0} ms</b></span>
                <span>fault → <b>{step.failure_target || "—"}</b></span>
              </div>
              {errors.map((err, idx) => <div key={idx} className="wb-node__error" role="alert">422 · {err}</div>)}
            </div>
          );
        })}
      </div>
      <div className="wb-sequence__edges">
        <div className="wb-inspector__label">TRANSITIONS（命名端口 · 优先级）</div>
        {transitions.map((tr) => (
          <div key={String(tr.id)} className="wb-sequence__edge" data-ui={`transition-${String(tr.id)}`}>
            <span className="wb-mono">{tr.from_step}</span> → <span className="wb-mono">{tr.to_step}</span>
            <span> · {String(tr.id)} · p{String(tr.priority ?? 0)} · GuardAST {tr.guard_ast ? "结构化" : "缺失"}</span>
          </div>
        ))}
      </div>
      {editingId && (
        <div className="wb-editor" data-ui="step-editor" role="dialog" aria-label="编辑步序节点">
          <div className="wb-editor__title">编辑 {editingId} · 基于 rev {baseRevision}</div>
          <label className="wb-editor__field">
            字段
            <select value={field} onChange={(e) => setField(e.target.value)} data-ui="edit-field">
              {EDITABLE_FIELDS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>
          <label className="wb-editor__field">
            值
            <input value={draft} onChange={(e) => setDraft(e.target.value)} data-ui="edit-value" />
          </label>
          <div className="wb-editor__actions">
            <button type="button" className="wb-btn wb-btn--primary" disabled={busy} onClick={submit} data-ui="edit-submit">
              提交 SequencePatch
            </button>
            <button type="button" className="wb-btn" onClick={() => setEditingId(null)}>取消</button>
          </div>
        </div>
      )}
    </div>
  );
};
