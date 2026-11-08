/**
 * 工位 02 · 连线：全幅 ReactFlow 画布为主操作。
 *
 * 唯一真值在 /state：nodes / edges 只由 ir 投影；新增 / 删除一律回调到
 * GreenfieldChannel 的 applyLinkPatch(add_edge / remove_edge) 后 refresh 回读，
 * 本地只保存「选中哪条线」这一视图位，绝不乐观增删。
 */
import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GFViews, GFWhitelist } from "../../state/greenfield";
import { buildEdges, buildNodes } from "./canvasUtils";
import { validateConnection, type StepBaseProps, type WizardStep } from "./stepMachine";

export interface StepLinkProps extends StepBaseProps {
  step: WizardStep;
  ir: Record<string, unknown> | null;
  views: GFViews | null;
  whitelist: GFWhitelist | null;
  edgeKind: string;
  onEdgeKindChange: (kind: string) => void;
  onConnect: (kind: string, connection: Connection) => void;
  onRemoveEdge: (edgeId: string) => void;
  linkError: string;
  edgesCount: number;
  reportOk: boolean;
  moreInputs?: React.ReactNode;
}

function asConnection(value: Edge | Connection): Connection {
  return {
    source: String(value.source ?? ""),
    target: String(value.target ?? ""),
    sourceHandle: value.sourceHandle ?? null,
    targetHandle: value.targetHandle ?? null,
  };
}

export const StepLink: React.FC<StepLinkProps> = ({
  step,
  busy,
  error,
  completed,
  onBackStep,
  onNext,
  onOpenEngineering,
  onClearError,
  ir,
  views,
  whitelist,
  edgeKind,
  onEdgeKindChange,
  onConnect,
  onRemoveEdge,
  linkError,
  edgesCount,
  reportOk,
  moreInputs,
}) => {
  const [selectedEdgeId, setSelectedEdgeId] = useState<string>("");
  const [localHint, setLocalHint] = useState<string>("");
  const invalidReasonRef = useRef<string>("");

  const kinds = whitelist?.edge_kinds ?? [];
  const activeKind = edgeKind || kinds[0] || "";

  const nodes = useMemo(() => buildNodes(ir, false), [ir]);
  const edges = useMemo<Edge[]>(
    () =>
      buildEdges(ir).map((edge) => ({
        ...edge,
        selected: edge.id === selectedEdgeId,
      })),
    [ir, selectedEdgeId],
  );

  const isValidConnection = useCallback(
    (value: Edge | Connection): boolean => {
      const verdict = validateConnection(asConnection(value), whitelist, ir, activeKind);
      invalidReasonRef.current = verdict.ok ? "" : verdict.reason;
      return verdict.ok;
    },
    [whitelist, ir, activeKind],
  );

  const onConnectEnd = useCallback(() => {
    const reason = invalidReasonRef.current;
    invalidReasonRef.current = "";
    setLocalHint(reason);
  }, []);

  const onEdgesChange = useCallback(
    (changes: EdgeChange<Edge>[]) => {
      for (const change of changes) {
        if (change.type === "remove") {
          onRemoveEdge(change.id);
          setSelectedEdgeId("");
        } else if (change.type === "select") {
          setSelectedEdgeId(change.selected ? change.id : "");
        }
      }
    },
    [onRemoveEdge],
  );

  const hint = linkError || localHint;

  return (
    <div className="gf-step-link" data-step={step} data-ui="wizard-step-link">
      <div className="gf-wiz__kicker">工位 02 · 手动连线</div>
      <h2 className="gf-wiz__title">把设备连起来</h2>
      <p className="gf-wiz__lead">
        从设备节点右侧的连接桩拖到另一个节点，松开即可新增一条关系；选中连线后按
        Delete / Backspace，或点下方的删除按钮即可移除。画布始终以服务端最新结果为准。
      </p>

      {completed && <div className="gf-wiz__done">本步已完成 · {edgesCount} 条设备关系</div>}

      <div className="gf-step-link__toolbar">
        <label className="gf-step-link__kind">
          关系类型
          <select
            value={activeKind}
            disabled={busy || kinds.length === 0}
            onChange={(event) => onEdgeKindChange(event.target.value)}
          >
            {kinds.length === 0 && <option value="">暂不可用</option>}
            {kinds.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        <span className="gf-muted">
          当前 {edgesCount} 条关系 · {reportOk ? "结构校验通过" : "结构校验尚未通过"}
        </span>
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--ghost"
          disabled={!selectedEdgeId || busy}
          onClick={() => {
            onRemoveEdge(selectedEdgeId);
            setSelectedEdgeId("");
          }}
        >
          × 删除选中连线
        </button>
      </div>

      <div className="gf-step-link__canvas" data-ui="wizard-link-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          deleteKeyCode={["Delete", "Backspace"]}
          isValidConnection={isValidConnection}
          onConnect={(connection: Connection) => {
            setLocalHint("");
            onConnect(activeKind, connection);
          }}
          onConnectEnd={onConnectEnd}
          onEdgesChange={onEdgesChange}
          onEdgeDoubleClick={(_, edge: Edge) => onRemoveEdge(edge.id)}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      <div className="gf-step-link__hint gf-link-pulse">
        非法连线会被立即拒绝并给出中文说明，画布保持服务端原样。双击连线同样可删除。
      </div>

      {hint && (
        <div className="gf-wiz__error" role="alert">
          {hint}
        </div>
      )}
      {error && (
        <div className="gf-wiz__error" role="alert">
          {error}
          {onClearError && (
            <button
              type="button"
              className="gf-btn gf-btn--xs gf-btn--ghost"
              onClick={onClearError}
            >
              知道了
            </button>
          )}
        </div>
      )}

      {moreInputs && <div className="gf-step-link__more">{moreInputs}</div>}

      <div className="gf-wiz__actions">
        {onBackStep && (
          <button type="button" className="gf-btn gf-btn--ghost" onClick={onBackStep}>
            返回上一步
          </button>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--primary gf-wiz__primary"
          disabled={busy}
          onClick={onNext}
        >
          下一步：确认
        </button>
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onOpenEngineering}>
          工程视角
        </button>
      </div>
    </div>
  );
};
