/**
 * WorkbenchShell — three-column V2 engineering workbench (WP-04).
 *
 * Frontend owns ONLY view/selection state (`reduceViewState`). Every edit is an
 * atomic SequencePatch with the CURRENT server `base_revision`; a 409 rolls back
 * the optimistic view and re-reads the authoritative IR, a 422 is annotated on
 * the offending node. Derived SCL / Trace are always re-fetched from the server
 * after a successful patch (IR -> Trace -> SCL three-way sync, US-3).
 */
import React, { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { GF_BASE, GFRequestError } from "../state/greenfield";
import {
  V2_API,
  buildSequencePatch,
  initialViewState,
  newRequestId,
  reduceViewState,
  v2Api,
  type JobView,
  type PatchRecord,
  type ValidationIssue,
  type WorkbenchView,
} from "../state/workbench_v2";
import { DiagnosticsPane, Inspector, ProjectTree, TopIdentityBar } from "./components";
import {
  DeliveryView, DeviceView, DiffView, OverviewView, SequenceView, TraceView,
  type DerivedData, type ViewProps,
} from "./views";
import "./workbench.css";

export interface WorkbenchShellProps {
  projectId?: string;
  onSwitch: (target: "legacy" | "classic") => void;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export const WorkbenchShell: React.FC<WorkbenchShellProps> = ({ projectId, onSwitch }) => {
  const pid = projectId || "prj_v2_workbench";
  const [state, dispatch] = useReducer(reduceViewState, initialViewState(pid));
  const [derived, setDerived] = useState<DerivedData | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const revisionRef = useRef(state.baseRevision);
  revisionRef.current = state.baseRevision;
  const irRef = useRef<Record<string, unknown>>({});

  const loadDerived = useCallback(async (revision: number) => {
    try {
      const [preview, simulation] = await Promise.all([
        v2Api.preview(pid, revision, newRequestId()),
        v2Api.simulate(pid, revision, newRequestId(), "normal_cycle"),
      ]);
      const p = asRecord(preview.data);
      const s = asRecord(simulation.data);
      setDerived({
        sclFiles: asRecord(p.scl_files) as Record<string, string>,
        trace: Array.isArray(s.trace) ? (s.trace as Array<Record<string, unknown>>) : [],
        manifest: asRecord(p.artifact_manifest),
        mermaid: String(p.mermaid ?? ""),
        sourceMap: asRecord(p.source_map),
        scenarios: asRecord(s.scenario),
      });
    } catch {
      /* offline: keep the last derived snapshot, never fabricate one */
    }
  }, [pid]);

  const loadAll = useCallback(async () => {
    try {
      const reply = await v2Api.getIr(pid);
      const data = asRecord(reply.data);
      const ir = asRecord(data.ir);
      irRef.current = ir;
      dispatch({
        type: "IR_LOADED",
        revision: Number(data.revision ?? 0),
        irSha256: String(data.ir_sha256 ?? ""),
        evidenceLevel: reply.evidence_level,
        ir,
      });
      revisionRef.current = Number(data.revision ?? 0);
      await loadDerived(revisionRef.current);
    } catch (err) {
      dispatch({ type: "PATCH_TRANSPORT_ERROR", message: err instanceof GFRequestError ? err.message : "无法读取服务端 IR" });
    }
    const jobId = new URLSearchParams(window.location.search).get("job_id");
    if (jobId) {
      try {
        const reply = await v2Api.job(jobId);
        if (reply.data) setJob(reply.data);
      } catch {
        setJob(null);
      }
    }
  }, [pid, loadDerived]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  /** One atomic patch. `reverseOps` is stored only for an explicit Undo re-issue. */
  const applyPatch = useCallback(async (
    ops: Array<Record<string, unknown>>,
    reverseOps: Array<Record<string, unknown>>,
    optimistic?: Record<string, unknown>,
  ) => {
    const record: PatchRecord = { ops, reverseOps, baseRevision: revisionRef.current, requestId: newRequestId() };
    dispatch({ type: "PATCH_START", record, optimistic });
    try {
      const reply = await v2Api.patch({
        project_id: pid,
        base_revision: record.baseRevision,
        request_id: record.requestId,
        ops,
      });
      if (reply.data) dispatch({ type: "PATCH_OK", result: reply.data });
      await loadAll(); // US-3: IR / Trace / SCL re-fetched together
    } catch (err) {
      if (err instanceof GFRequestError && err.status === 409) {
        const details = asRecord(err.details);
        dispatch({ type: "PATCH_CONFLICT", currentRevision: Number(details.current_revision ?? revisionRef.current + 1) });
        await loadAll(); // re-read authoritative IR, then user re-merges
        return;
      }
      if (err instanceof GFRequestError && err.status === 422) {
        const details = asRecord(err.details);
        const issues = (Array.isArray(details.issues) ? details.issues : []) as ValidationIssue[];
        dispatch({ type: "PATCH_REJECTED", issues, unchangedIrHash: String(details.unchanged_ir_hash ?? "") });
        return;
      }
      dispatch({ type: "PATCH_TRANSPORT_ERROR", message: err instanceof Error ? err.message : "Patch 请求失败" });
    }
  }, [pid, loadAll]);

  const onEdit = useCallback((stepId: string, field: string, value: unknown) => {
    const process = asRecord(irRef.current.process);
    const steps = Array.isArray(process.steps) ? process.steps as Array<Record<string, unknown>> : [];
    const step = steps.find((s) => String(s.id) === stepId) ?? {};
    const oldValue = step[field] ?? 0;
    const patch = buildSequencePatch(pid, revisionRef.current, stepId, field, value);
    void applyPatch(patch.ops, [{ op: "set_step_parameter", step_id: stepId, field, value: oldValue, source_id: stepId }]);
  }, [pid, applyPatch]);

  const onUndo = useCallback(() => {
    const record = state.undoStack[state.undoStack.length - 1];
    if (!record) return;
    dispatch({ type: "UNDO_READY", record });
    // Undo re-issues a patch against the CURRENT server revision (never a local copy).
    void applyPatch(record.reverseOps, record.ops);
  }, [state.undoStack, applyPatch]);

  const onRedo = useCallback(() => {
    const record = state.redoStack[state.redoStack.length - 1];
    if (!record) return;
    void applyPatch(record.ops, record.reverseOps);
  }, [state.redoStack, applyPatch]);

  const onSelectNode = useCallback((nodeId: string, data: Record<string, unknown>) => {
    dispatch({ type: "SELECT_NODE", nodeId, inspector: data });
  }, []);

  const onRunScenario = useCallback((scenario: string) => {
    void (async () => {
      try {
        const reply = await v2Api.simulate(pid, revisionRef.current, newRequestId(), scenario);
        const s = asRecord(reply.data);
        setDerived((prev) => ({
          sclFiles: prev?.sclFiles ?? {}, manifest: prev?.manifest ?? {}, mermaid: prev?.mermaid ?? "",
          sourceMap: prev?.sourceMap ?? {}, scenarios: asRecord(s.scenario),
          trace: Array.isArray(s.trace) ? (s.trace as Array<Record<string, unknown>>) : [],
        }));
      } catch {
        /* offline: keep last trace */
      }
    })();
  }, [pid]);

  const onSourcePackage = useCallback(() => {
    window.location.assign(`${GF_BASE}${V2_API}/projects/${encodeURIComponent(pid)}/source-package`);
  }, [pid]);

  const viewProps: ViewProps = {
    ir: irRef.current, state, derived, job, onEdit, onSelectNode, onUndo, onRedo, onRunScenario, onSourcePackage,
  };

  const renderView = (): React.ReactNode => {
    switch (state.activeView as WorkbenchView) {
      case "device": return <DeviceView {...viewProps} />;
      case "sequence": return <SequenceView {...viewProps} />;
      case "trace": return <TraceView {...viewProps} />;
      case "diff": return <DiffView {...viewProps} />;
      case "delivery": return <DeliveryView {...viewProps} />;
      default: return <OverviewView {...viewProps} />;
    }
  };

  return (
    <div className="wb-shell" data-ui="workbench-shell">
      <TopIdentityBar state={state} onSwitch={onSwitch} />
      <div className="wb-shell__body">
        <ProjectTree state={state} onSelectView={(view) => dispatch({ type: "SELECT_VIEW", view })} />
        <main className="wb-shell__main" data-ui="workbench-main">{renderView()}</main>
        <Inspector state={state} />
      </div>
      <DiagnosticsPane
        diagnostics={state.diagnostics}
        open={state.diagnosticsOpen}
        onToggle={() => dispatch({ type: "TOGGLE_DIAGNOSTICS" })}
      />
    </div>
  );
};
