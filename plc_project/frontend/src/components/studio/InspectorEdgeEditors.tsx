import React, { useEffect, useState } from 'react';
import type {
  ProjectCompoundEdge,
  ProjectCompoundStation,
  ProjectHyperGraph,
  SafetyGuardEdge,
  SelectedHyperEntity,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
} from '../../core/ir/afHyperGraph.types';
import { getRadialMethodsForClass } from '../../core/ir/motherClassRegistry';
import { cmPresetWait } from '../../core/ir/fieldIo';

const INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '5px 7px',
  fontSize: 11,
  borderRadius: 5,
  border: '1px solid var(--border-line, #D0C9BC)',
  background: 'var(--bg-card, #F7F4EE)',
  color: 'var(--ink-primary, #161514)',
};

const LABEL_STYLE: React.CSSProperties = {
  display: 'block',
  fontSize: 10,
  fontWeight: 600,
  color: 'var(--ink-secondary, #5C5A55)',
  marginBottom: 3,
};

const CARD_HEAD_STYLE: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: 'var(--ink-secondary, #5C5A55)',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
};

/* ==================== 1. 时序步连线与工艺逻辑编辑器 ==================== */
export const StepEdgeEditor: React.FC<{
  step: TemporalStepHyperEdge;
  station: StationHyperGraph;
  onUpdateStep?: (stepId: string, patch: Partial<TemporalStepHyperEdge>) => void;
  onDeleteStep?: (stepId: string) => void;
}> = ({ step, station, onUpdateStep, onDeleteStep }) => {
  const firstInv = step.invocations[0];
  const [stepNo, setStepNo] = useState<number>(step.stepNo);
  const [title, setTitle] = useState<string>(step.title);
  const [fromNode, setFromNode] = useState<string>(step.fromNode);
  const [fromPort, setFromPort] = useState<string>(step.fromPort);
  const [targetNodeId, setTargetNodeId] = useState<string>(firstInv?.targetNodeId ?? '');
  const [methodId, setMethodId] = useState<string>(firstInv?.methodId ?? '');
  const [actionLabel, setActionLabel] = useState<string>(firstInv?.actionLabel ?? '');
  const [targetState, setTargetState] = useState<string>(firstInv?.targetDiscreteState ?? '');
  const [sclStatement, setSclStatement] = useState<string>(firstInv?.sclStatement ?? '');
  const [waitPredicateScl, setWaitPredicateScl] = useState<string>(firstInv?.waitPredicateScl ?? '');
  const [branchPredicate, setBranchPredicate] = useState<'ALWAYS' | 'OK' | 'NG'>(
    step.branchPredicate ?? 'ALWAYS'
  );
  const [savedHint, setSavedHint] = useState(false);

  useEffect(() => {
    const inv = step.invocations[0];
    setStepNo(step.stepNo);
    setTitle(step.title);
    setFromNode(step.fromNode);
    setFromPort(step.fromPort);
    setTargetNodeId(inv?.targetNodeId ?? '');
    setMethodId(inv?.methodId ?? '');
    setActionLabel(inv?.actionLabel ?? '');
    setTargetState(inv?.targetDiscreteState ?? '');
    setSclStatement(inv?.sclStatement ?? '');
    setWaitPredicateScl(inv?.waitPredicateScl ?? '');
    setBranchPredicate(step.branchPredicate ?? 'ALWAYS');
  }, [step]);

  useEffect(() => {
    setSavedHint(false);
  }, [step.id]);

  const sourceNodeObj = station.spatialNodes.find((n) => n.id === fromNode);
  const targetNodeObj = station.spatialNodes.find((n) => n.id === targetNodeId);
  const craftMethods = targetNodeObj
    ? getRadialMethodsForClass(targetNodeObj.driverClass, targetNodeObj).filter((m) => !m.isGuard)
    : [];

  const handleFromNodeChange = (nextFrom: string) => {
    setFromNode(nextFrom);
    const node = station.spatialNodes.find((n) => n.id === nextFrom);
    if (node && node.outPorts.length > 0) {
      setFromPort(node.outPorts[0].id);
    }
  };

  const handleApplyMethodPreset = (selectedMethodId: string) => {
    const preset = craftMethods.find((m) => m.methodId === selectedMethodId);
    if (!preset) return;
    setMethodId(preset.methodId);
    setActionLabel(preset.label);
    setTargetState(preset.targetDiscreteState);
    setSclStatement(preset.sclCommand);
    if (targetNodeObj) {
      setWaitPredicateScl(cmPresetWait(targetNodeObj, preset));
    }
  };

  const handleSave = () => {
    if (!onUpdateStep) return;
    const baseInv = step.invocations[0] ?? {
      targetNodeId,
      targetPortId: 'IN_EXEC',
      methodId: methodId || 'CustomAction',
      actionLabel: actionLabel || title,
      targetDiscreteState: targetState || 'AtWork',
      sclStatement: sclStatement || '// Custom SCL',
      waitPredicateScl: waitPredicateScl || 'TRUE',
    };
    const updatedInv = {
      ...baseInv,
      targetNodeId: targetNodeId || baseInv.targetNodeId,
      targetPortId: craftMethods.find((method) => method.methodId === methodId)?.targetPortId ??
        (targetNodeId === baseInv.targetNodeId ? baseInv.targetPortId : targetNodeObj?.inPorts.find((port) => port.type === 'SEQ')?.id),
      methodId: methodId || baseInv.methodId,
      actionLabel: actionLabel.trim() || baseInv.actionLabel,
      targetDiscreteState: targetState.trim() || baseInv.targetDiscreteState,
      sclStatement,
      waitPredicateScl: waitPredicateScl.trim() || baseInv.waitPredicateScl,
    };
    const remaining = step.invocations.slice(1);
    onUpdateStep(step.id, {
      stepNo: Number.isFinite(stepNo) && stepNo > 0 ? Math.round(stepNo) : step.stepNo,
      title: title.trim() || step.title,
      fromNode: fromNode || step.fromNode,
      fromPort: fromPort.trim() || step.fromPort,
      branchPredicate,
      invocations: [updatedInv, ...remaining],
    });
    setSavedHint(true);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="step-edge-inspector">
      <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
        <div style={CARD_HEAD_STYLE}>时序步连线端点 (Topology Endpoints)</div>
        <div>
          <label style={LABEL_STYLE}>起点节点 (From Node)</label>
          <select
            value={fromNode}
            onChange={(e) => handleFromNodeChange(e.target.value)}
            style={INPUT_STYLE}
            data-testid="step-from-node-select"
          >
            {station.spatialNodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.title} ({n.id})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label style={LABEL_STYLE}>起点端口 (From Port)</label>
          {sourceNodeObj && sourceNodeObj.outPorts.length > 0 ? (
            <select
              value={fromPort}
              onChange={(e) => setFromPort(e.target.value)}
              style={INPUT_STYLE}
              data-testid="step-from-port-select"
            >
              {sourceNodeObj.outPorts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label} ({p.id})
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={fromPort}
              onChange={(e) => setFromPort(e.target.value)}
              style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
            />
          )}
        </div>

        <div>
          <label style={LABEL_STYLE}>目标执行器节点 (Target Node)</label>
          <select
            value={targetNodeId}
            onChange={(e) => setTargetNodeId(e.target.value)}
            style={INPUT_STYLE}
            data-testid="step-target-node-select"
          >
            {station.spatialNodes.filter((node) => node.driverClass !== 'FB_AF_DigitalInput').map((n) => (
              <option key={n.id} value={n.id}>
                {n.title} ({n.id})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
        <div style={CARD_HEAD_STYLE}>连线逻辑与 SCL 编译定义 (Step Logic)</div>

        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ width: 76 }}>
            <label style={LABEL_STYLE}>步号 (Step)</label>
            <input
              type="number"
              min={1}
              step={5}
              value={stepNo}
              onChange={(e) => setStepNo(Number(e.target.value))}
              style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
              data-testid="step-no-input"
            />
          </div>
          <div style={{ flex: 1 }}>
            <label style={LABEL_STYLE}>分支条件 (Branch Predicate)</label>
            <select
              value={branchPredicate}
              onChange={(e) => setBranchPredicate(e.target.value as 'ALWAYS' | 'OK' | 'NG')}
              style={INPUT_STYLE}
              data-testid="step-branch-select"
            >
              <option value="ALWAYS">ALWAYS (顺序必执行)</option>
              <option value="OK">OK (良品 / 判定通过分支)</option>
              <option value="NG">NG (不良 / 抛料异常分支)</option>
            </select>
          </div>
        </div>

        <div>
          <label style={LABEL_STYLE}>工步名称 (Step Title)</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            style={INPUT_STYLE}
            data-testid="step-title-input"
          />
        </div>

        {craftMethods.length > 0 && (
          <div>
            <label style={LABEL_STYLE}>套用母版工艺模板 (Method Preset)</label>
            <select
              value={craftMethods.some((m) => m.methodId === methodId) ? methodId : ''}
              onChange={(e) => handleApplyMethodPreset(e.target.value)}
              style={INPUT_STYLE}
              data-testid="step-method-preset-select"
            >
              <option value="">-- 选择工艺动作模板自动填充 --</option>
              {craftMethods.map((m) => (
                <option key={m.methodId} value={m.methodId}>
                  {m.label} ({m.sclCommand})
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label style={LABEL_STYLE}>动作描述标签 (Action Label)</label>
          <input
            type="text"
            value={actionLabel}
            onChange={(e) => setActionLabel(e.target.value)}
            style={INPUT_STYLE}
            data-testid="step-action-label-input"
          />
        </div>

        <div>
          <label style={LABEL_STYLE}>目标离散状态 (Target State)</label>
          <input
            type="text"
            value={targetState}
            onChange={(e) => setTargetState(e.target.value)}
            style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
            data-testid="step-target-state-input"
          />
        </div>

        <div>
          <label style={LABEL_STYLE}>SCL 调用指令 (SCL Statement)</label>
          <textarea
            rows={2}
            value={sclStatement}
            onChange={(e) => setSclStatement(e.target.value)}
            style={{
              ...INPUT_STYLE,
              fontFamily: 'var(--font-mono, monospace)',
              resize: 'vertical',
            }}
            data-testid="step-scl-input"
          />
        </div>

        <div>
          <label style={LABEL_STYLE}>步间跳转等待条件 (Wait Predicate SCL)</label>
          <input
            type="text"
            value={waitPredicateScl}
            onChange={(e) => setWaitPredicateScl(e.target.value)}
            style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
            data-testid="step-wait-scl-input"
          />
        </div>
      </div>

      {savedHint && (
        <div
          style={{
            fontSize: 11,
            color: 'var(--af5-emerald, #059669)',
            background: 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
            padding: '5px 8px',
            borderRadius: 6,
          }}
          data-testid="step-saved-hint"
        >
          ✓ 时序连线端点与逻辑已更新并重新校验
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          className="af5-btn af5-btn--primary"
          style={{ flex: 1, fontSize: 11 }}
          onClick={handleSave}
          data-testid="save-step-edge-btn"
        >
          💾 保存连线与逻辑修改
        </button>
        {onDeleteStep && (
          <button
            type="button"
            className="af5-btn af5-btn--vermilion"
            style={{ fontSize: 11, padding: '6px 10px' }}
            onClick={() => onDeleteStep(step.id)}
            title="删除该步序连线"
            data-testid="delete-step-edge-btn"
          >
            🗑️ 删除
          </button>
        )}
      </div>
    </div>
  );
};

/* ==================== 2. 安全互锁护栏连线编辑器 ==================== */
export const GuardEdgeEditor: React.FC<{
  guard: SafetyGuardEdge;
  station: StationHyperGraph;
  onUpdateGuard?: (edgeId: string, patch: Partial<SafetyGuardEdge>) => void;
  onDeleteGuard?: (edgeId: string) => void;
}> = ({ guard, station, onUpdateGuard, onDeleteGuard }) => {
  const [fromNode, setFromNode] = useState(guard.fromNode);
  const [toNode, setToNode] = useState(guard.toNode);
  const [requiredSourceState, setRequiredSourceState] = useState(guard.requiredSourceState);
  const [diagCodeHex, setDiagCodeHex] = useState(guard.diagCodeHex);
  const [humanDescription, setHumanDescription] = useState(guard.humanDescription);
  const [isHealthy, setIsHealthy] = useState(guard.isHealthy !== false);
  const [savedHint, setSavedHint] = useState(false);

  useEffect(() => {
    setFromNode(guard.fromNode);
    setToNode(guard.toNode);
    setRequiredSourceState(guard.requiredSourceState);
    setDiagCodeHex(guard.diagCodeHex);
    setHumanDescription(guard.humanDescription);
    setIsHealthy(guard.isHealthy !== false);
  }, [guard]);

  useEffect(() => {
    setSavedHint(false);
  }, [guard.id]);

  const sourceObj = station.spatialNodes.find((n) => n.id === fromNode);

  const handleSave = () => {
    if (!onUpdateGuard) return;
    onUpdateGuard(guard.id, {
      fromNode,
      toNode,
      requiredSourceState: requiredSourceState.trim() || guard.requiredSourceState,
      diagCodeHex: diagCodeHex.trim() || guard.diagCodeHex,
      humanDescription: humanDescription.trim() || guard.humanDescription,
      isHealthy,
    });
    setSavedHint(true);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="guard-edge-inspector">
      <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
        <div style={CARD_HEAD_STYLE}>永久安全护栏连线 (Guardrail Topology)</div>

        <div>
          <label style={LABEL_STYLE}>保护源节点 (Guard Source)</label>
          <select
            value={fromNode}
            onChange={(e) => setFromNode(e.target.value)}
            style={INPUT_STYLE}
            data-testid="guard-from-node-select"
          >
            {station.spatialNodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.title} ({n.id})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label style={LABEL_STYLE}>受控目标节点 (Guarded Target)</label>
          <select
            value={toNode}
            onChange={(e) => setToNode(e.target.value)}
            style={INPUT_STYLE}
            data-testid="guard-to-node-select"
          >
            {station.spatialNodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.title} ({n.id})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
        <div style={CARD_HEAD_STYLE}>互锁条件与阻断诊断逻辑 (Interlock Logic)</div>

        <div>
          <label style={LABEL_STYLE}>允许动作的前提安全状态 (Required Source State)</label>
          <input
            type="text"
            value={requiredSourceState}
            onChange={(e) => setRequiredSourceState(e.target.value)}
            style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
            data-testid="guard-required-state-input"
          />
          {sourceObj && sourceObj.discreteStates.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 5 }}>
              {sourceObj.discreteStates.map((st) => (
                <button
                  key={st}
                  type="button"
                  onClick={() => setRequiredSourceState(st)}
                  style={{
                    padding: '2px 6px',
                    fontSize: 10,
                    borderRadius: 4,
                    border:
                      requiredSourceState === st
                        ? '1px solid var(--af5-amber, #D97706)'
                        : '1px solid var(--border-line, #D0C9BC)',
                    background:
                      requiredSourceState === st
                        ? 'var(--af5-amber-soft, rgba(217, 119, 6, 0.12))'
                        : 'var(--bg-paper, #EFECE6)',
                    cursor: 'pointer',
                  }}
                >
                  {st}
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label style={LABEL_STYLE}>诊断字代码 (Diag Code Hex)</label>
          <input
            type="text"
            value={diagCodeHex}
            onChange={(e) => setDiagCodeHex(e.target.value)}
            style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
            data-testid="guard-diag-code-input"
          />
        </div>

        <div>
          <label style={LABEL_STYLE}>护栏语义描述 (Human Description)</label>
          <input
            type="text"
            value={humanDescription}
            onChange={(e) => setHumanDescription(e.target.value)}
            style={INPUT_STYLE}
            data-testid="guard-desc-input"
          />
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={isHealthy}
            onChange={(e) => setIsHealthy(e.target.checked)}
            data-testid="guard-healthy-checkbox"
          />
          <span>互锁信号当前处于健康导通状态 (TRUE)</span>
        </label>
      </div>

      {savedHint && (
        <div
          style={{
            fontSize: 11,
            color: 'var(--af5-emerald, #059669)',
            background: 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
            padding: '5px 8px',
            borderRadius: 6,
          }}
        >
          ✓ 安全护栏拓扑与互锁逻辑已更新
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          className="af5-btn af5-btn--primary"
          style={{ flex: 1, fontSize: 11 }}
          onClick={handleSave}
          data-testid="save-guard-edge-btn"
        >
          💾 保存护栏逻辑
        </button>
        {onDeleteGuard && (
          <button
            type="button"
            className="af5-btn af5-btn--vermilion"
            style={{ fontSize: 11, padding: '6px 10px' }}
            onClick={() => onDeleteGuard(guard.id)}
            title="删除该安全护栏连线"
            data-testid="delete-guard-edge-btn"
          >
            🗑️ 删除
          </button>
        )}
      </div>
    </div>
  );
};

/* ==================== 3. L1 跨站连线编辑器 ==================== */
export const L1EdgeEditor: React.FC<{
  edge: ProjectCompoundEdge;
  projectGraph: ProjectHyperGraph;
  onUpdateEdge?: (edgeId: string, patch: Partial<ProjectCompoundEdge>) => void;
  onDeleteEdge?: (edgeId: string) => void;
}> = ({ edge, projectGraph, onUpdateEdge, onDeleteEdge }) => {
  const [fromNode, setFromNode] = useState(edge.fromNode);
  const [fromPort, setFromPort] = useState(edge.fromPort);
  const [toNode, setToNode] = useState(edge.toNode);
  const [toPort, setToPort] = useState(edge.toPort);
  const [kind, setKind] = useState<'SEQ' | 'GUARD'>(edge.kind);
  const [label, setLabel] = useState(edge.label);
  const [diagCodeHex, setDiagCodeHex] = useState(edge.diagCodeHex ?? '');
  const [savedHint, setSavedHint] = useState(false);

  useEffect(() => {
    setFromNode(edge.fromNode);
    setFromPort(edge.fromPort);
    setToNode(edge.toNode);
    setToPort(edge.toPort);
    setKind(edge.kind);
    setLabel(edge.label);
    setDiagCodeHex(edge.diagCodeHex ?? '');
  }, [edge]);

  useEffect(() => {
    setSavedHint(false);
  }, [edge.id]);

  const fromStation = projectGraph.stations.find((s) => s.id === fromNode);
  const toStation = projectGraph.stations.find((s) => s.id === toNode);

  const handleSave = () => {
    if (!onUpdateEdge) return;
    onUpdateEdge(edge.id, {
      fromNode,
      fromPort,
      toNode,
      toPort,
      kind,
      label: label.trim() || edge.label,
      diagCodeHex: diagCodeHex.trim() || undefined,
    });
    setSavedHint(true);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="l1-edge-inspector">
      <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
        <div style={CARD_HEAD_STYLE}>L1 产线跨站连线与握手逻辑</div>

        <div>
          <label style={LABEL_STYLE}>上游工站 (From Station)</label>
          <select
            value={fromNode}
            onChange={(e) => {
              const nextId = e.target.value;
              setFromNode(nextId);
              const st = projectGraph.stations.find((s) => s.id === nextId);
              if (st?.outPorts[0]) setFromPort(st.outPorts[0].id);
            }}
            style={INPUT_STYLE}
            data-testid="l1-edge-from-select"
          >
            {projectGraph.stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>

        {fromStation && fromStation.outPorts.length > 0 && (
          <div>
            <label style={LABEL_STYLE}>上游输出端口</label>
            <select
              value={fromPort}
              onChange={(e) => setFromPort(e.target.value)}
              style={INPUT_STYLE}
            >
              {fromStation.outPorts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label style={LABEL_STYLE}>下游工站 (To Station)</label>
          <select
            value={toNode}
            onChange={(e) => {
              const nextId = e.target.value;
              setToNode(nextId);
              const st = projectGraph.stations.find((s) => s.id === nextId);
              if (st?.inPorts[0]) setToPort(st.inPorts[0].id);
            }}
            style={INPUT_STYLE}
            data-testid="l1-edge-to-select"
          >
            {projectGraph.stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>

        {toStation && toStation.inPorts.length > 0 && (
          <div>
            <label style={LABEL_STYLE}>下游输入端口</label>
            <select
              value={toPort}
              onChange={(e) => setToPort(e.target.value)}
              style={INPUT_STYLE}
            >
              {toStation.inPorts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label style={LABEL_STYLE}>跨站连线语义 (Edge Kind)</label>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as 'SEQ' | 'GUARD')}
            style={INPUT_STYLE}
            data-testid="l1-edge-kind-select"
          >
            <option value="SEQ">SEQ · 物流节拍交接握手</option>
            <option value="GUARD">GUARD · 跨站永久安全护栏</option>
          </select>
        </div>

        <div>
          <label style={LABEL_STYLE}>连线标签 / 逻辑说明</label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            style={INPUT_STYLE}
            data-testid="l1-edge-label-input"
          />
        </div>

        <div>
          <label style={LABEL_STYLE}>诊断字编码 (可选，如 16#0203)</label>
          <input
            type="text"
            value={diagCodeHex}
            onChange={(e) => setDiagCodeHex(e.target.value)}
            style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono, monospace)' }}
          />
        </div>
      </div>

      {savedHint && (
        <div
          style={{
            fontSize: 11,
            color: 'var(--af5-emerald, #059669)',
            background: 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
            padding: '5px 8px',
            borderRadius: 6,
          }}
        >
          ✓ 产线跨站连线逻辑已保存
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          className="af5-btn af5-btn--primary"
          style={{ flex: 1, fontSize: 11 }}
          onClick={handleSave}
          data-testid="save-l1-edge-btn"
        >
          💾 保存跨站连线
        </button>
        {onDeleteEdge && (
          <button
            type="button"
            className="af5-btn af5-btn--vermilion"
            style={{ fontSize: 11, padding: '6px 10px' }}
            onClick={() => onDeleteEdge(edge.id)}
            data-testid="delete-l1-edge-btn"
          >
            🗑️ 删除
          </button>
        )}
      </div>
    </div>
  );
};

/* ==================== 4. L1 复合工站节点检查器 ==================== */
export const L1StationEditor: React.FC<{
  stationCard: ProjectCompoundStation;
  projectGraph: ProjectHyperGraph;
  onUpdateStation?: (nodeId: string, patch: Partial<ProjectCompoundStation>) => void;
  onDeleteStation?: (nodeId: string) => void;
  onEnterStation?: (stationId: string) => void;
  onAddProjectEdge?: (edge: ProjectCompoundEdge) => void;
}> = ({
  stationCard,
  projectGraph,
  onUpdateStation,
  onDeleteStation,
  onEnterStation,
  onAddProjectEdge,
}) => {
  const [title, setTitle] = useState(stationCard.title);
  const [targetStationNodeId, setTargetStationNodeId] = useState<string>(
    projectGraph.stations.find((s) => s.id !== stationCard.id)?.id ?? ''
  );
  const [newEdgeKind, setNewEdgeKind] = useState<'SEQ' | 'GUARD'>('SEQ');
  const [newEdgeLabel, setNewEdgeLabel] = useState('物流交接握手');

  useEffect(() => {
    setTitle(stationCard.title);
    const firstOther = projectGraph.stations.find((s) => s.id !== stationCard.id);
    if (firstOther && !projectGraph.stations.some((s) => s.id === targetStationNodeId && s.id !== stationCard.id)) {
      setTargetStationNodeId(firstOther.id);
    }
  }, [stationCard, projectGraph.stations, targetStationNodeId]);

  const handleCreateCrossEdge = () => {
    if (!onAddProjectEdge || !targetStationNodeId) return;
    const targetCard = projectGraph.stations.find((s) => s.id === targetStationNodeId);
    if (!targetCard) return;
    const fromPort =
      stationCard.outPorts.find((p) => p.type === newEdgeKind)?.id ??
      stationCard.outPorts[0]?.id ??
      'P_HANDOVER';
    const toPort =
      targetCard.inPorts.find((p) => p.type === newEdgeKind)?.id ??
      targetCard.inPorts[0]?.id ??
      'P_IN';

    onAddProjectEdge({
      id: `E_L1_${Date.now().toString(36).slice(-5)}`,
      fromNode: stationCard.id,
      fromPort,
      toNode: targetCard.id,
      toPort,
      kind: newEdgeKind,
      label: newEdgeLabel.trim() || (newEdgeKind === 'GUARD' ? '跨站安全护栏' : '物流交接握手'),
      diagCodeHex: newEdgeKind === 'GUARD' ? '16#0299' : undefined,
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="l1-station-inspector">
      <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
        <div style={CARD_HEAD_STYLE}>L1 复合工站节点属性</div>
        <div>
          <label style={LABEL_STYLE}>工站标题</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            style={INPUT_STYLE}
            data-testid="l1-station-title-input"
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
          <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>L1 画布坐标 (X/Y):</span>
          <span style={{ fontFamily: 'var(--font-mono, monospace)' }} data-testid="l1-station-pos">
            ({Math.round(stationCard.position.x)}, {Math.round(stationCard.position.y)})
          </span>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          <button
            type="button"
            className="af5-btn"
            style={{ flex: 1, fontSize: 11 }}
            onClick={() =>
              onUpdateStation?.(stationCard.id, { title: title.trim() || stationCard.title })
            }
            data-testid="save-l1-station-btn"
          >
            💾 保存标题
          </button>
          <button
            type="button"
            className="af5-btn af5-btn--primary"
            style={{ flex: 1, fontSize: 11 }}
            onClick={() => onEnterStation?.(stationCard.stationId)}
            data-testid="enter-station-l2-btn"
          >
            🔍 进入 L2 工站
          </button>
          {onDeleteStation && (
            <button
              type="button"
              className="af5-btn af5-btn--vermilion"
              style={{ fontSize: 11, padding: '4px 8px' }}
              onClick={() => onDeleteStation(stationCard.id)}
              title="删除该工站及其关联连线"
              data-testid="delete-l1-station-btn"
            >
              🗑️
            </button>
          )}
        </div>
      </div>

      {projectGraph.stations.length > 1 && onAddProjectEdge && (
        <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
          <div style={CARD_HEAD_STYLE}>➕ 新增跨站连线</div>
          <div>
            <label style={LABEL_STYLE}>连向目标工站</label>
            <select
              value={targetStationNodeId}
              onChange={(e) => setTargetStationNodeId(e.target.value)}
              style={INPUT_STYLE}
            >
              {projectGraph.stations
                .filter((s) => s.id !== stationCard.id)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label style={LABEL_STYLE}>连线类型</label>
            <select
              value={newEdgeKind}
              onChange={(e) => {
                const k = e.target.value as 'SEQ' | 'GUARD';
                setNewEdgeKind(k);
                setNewEdgeLabel(k === 'GUARD' ? '跨站安全护栏' : '物流交接握手');
              }}
              style={INPUT_STYLE}
            >
              <option value="SEQ">SEQ · 物流交接握手</option>
              <option value="GUARD">GUARD · 跨站安全护栏</option>
            </select>
          </div>
          <div>
            <label style={LABEL_STYLE}>连线标签</label>
            <input
              type="text"
              value={newEdgeLabel}
              onChange={(e) => setNewEdgeLabel(e.target.value)}
              style={INPUT_STYLE}
            />
          </div>
          <button
            type="button"
            className="af5-btn af5-btn--primary"
            style={{ fontSize: 11 }}
            onClick={handleCreateCrossEdge}
            data-testid="quick-create-l1-edge-btn"
          >
            ➕ 建立跨站连线
          </button>
        </div>
      )}
    </div>
  );
};

/* ==================== 5. 快捷连线建立器与工站连线目录 ==================== */
export const QuickEdgeCreatorCard: React.FC<{
  selectedNode?: SpatialInstanceNode | null;
  station: StationHyperGraph;
  onAddTemporalStep?: (step: TemporalStepHyperEdge) => void;
  onAddGuardEdge?: (edge: SafetyGuardEdge) => void;
  onSelectEntity?: (entity: SelectedHyperEntity) => void;
}> = ({ selectedNode, station, onAddTemporalStep, onAddGuardEdge, onSelectEntity }) => {
  const targets = station.spatialNodes.filter((node) => node.driverClass !== 'FB_AF_DigitalInput');
  const defaultTarget =
    targets.find((n) => n.id !== selectedNode?.id && n.role !== 'BOUNDARY_IN')?.id ??
    station.spatialNodes[0]?.id ??
    '';
  const [fromNodeId, setFromNodeId] = useState<string>(selectedNode?.id ?? station.spatialNodes[0]?.id ?? '');
  const [toNodeId, setToNodeId] = useState<string>(defaultTarget);
  const [edgeMode, setEdgeMode] = useState<'STEP' | 'GUARD'>('STEP');

  useEffect(() => {
    if (selectedNode) {
      setFromNodeId(selectedNode.id);
      const other = targets.find((n) => n.id !== selectedNode.id && n.role !== 'BOUNDARY_IN');
      if (other) setToNodeId(other.id);
    }
  }, [selectedNode?.id, station.spatialNodes]);

  if (station.spatialNodes.length < 2) return null;

  const handleQuickAdd = () => {
    if (!fromNodeId || !toNodeId || fromNodeId === toNodeId) return;
    const fromNode = station.spatialNodes.find((n) => n.id === fromNodeId);
    const toNode = targets.find((n) => n.id === toNodeId);
    if (!fromNode || !toNode) return;

    if (edgeMode === 'GUARD') {
      const edge: SafetyGuardEdge = {
        id: `G_MANUAL_${Date.now().toString(36).slice(-5)}`,
        fromNode: fromNode.id,
        fromPort: fromNode.outPorts[0]?.id ?? 'OUT_DONE',
        toNode: toNode.id,
        toPort: toNode.inPorts.find((p) => p.type === 'GUARD')?.id ?? toNode.inPorts[0]?.id ?? 'IN_GUARD',
        requiredSourceState: fromNode.initialHomeState || fromNode.discreteStates[0] || 'AtHome',
        diagCodeHex: '16#0290',
        humanDescription: `${fromNode.title} 安全到位后允许 ${toNode.title} 动作`,
        isHealthy: true,
      };
      onAddGuardEdge?.(edge);
      onSelectEntity?.({ kind: 'GUARD', id: edge.id });
    } else {
      const maxStepNo = station.temporalSteps.reduce((m, s) => Math.max(m, s.stepNo), 0);
      const nextStepNo = maxStepNo + 10;
      const preset = getRadialMethodsForClass(toNode.driverClass, toNode).find((m) => !m.isGuard);
      const step: TemporalStepHyperEdge = {
        id: `T_MANUAL_S${nextStepNo}_${Date.now().toString(36).slice(-4)}`,
        stepNo: nextStepNo,
        title: `${toNode.title} ${preset?.label ?? '执行动作'}`,
        fromNode: fromNode.id,
        fromPort: fromNode.outPorts[0]?.id ?? 'OUT_DONE',
        branchPredicate: 'ALWAYS',
        invocations: [
          {
            targetNodeId: toNode.id,
            targetPortId: preset?.targetPortId ?? toNode.inPorts.find((port) => port.type === 'SEQ')?.id ?? 'IN_EXEC',
            methodId: preset?.methodId ?? 'Execute',
            actionLabel: preset?.label ?? '执行工艺动作',
            targetDiscreteState: preset?.targetDiscreteState ?? toNode.discreteStates[1] ?? 'AtWork',
            sclStatement: preset?.sclCommand ?? `#${toNode.id}.i_bCmdWork := TRUE;`,
            waitPredicateScl: cmPresetWait(toNode, preset),
            waitDescription: preset?.waitDescription ?? '执行完成到位',
          },
        ],
      };
      onAddTemporalStep?.(step);
      onSelectEntity?.({ kind: 'STEP', id: step.id });
    }
  };

  return (
    <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
      <div style={CARD_HEAD_STYLE}>➕ 新增节点连线与逻辑</div>

      <div style={{ display: 'flex', gap: 6 }}>
        <button
          type="button"
          className={`af5-btn ${edgeMode === 'STEP' ? 'af5-btn--primary' : ''}`}
          style={{ flex: 1, fontSize: 10, padding: '4px 6px' }}
          onClick={() => setEdgeMode('STEP')}
          data-testid="quick-mode-step-btn"
        >
          时序步连线
        </button>
        <button
          type="button"
          className={`af5-btn ${edgeMode === 'GUARD' ? 'af5-btn--primary' : ''}`}
          style={{ flex: 1, fontSize: 10, padding: '4px 6px' }}
          onClick={() => setEdgeMode('GUARD')}
          data-testid="quick-mode-guard-btn"
        >
          安全护栏连线
        </button>
      </div>

      <div>
        <label style={LABEL_STYLE}>起点节点 (From)</label>
        <select
          value={fromNodeId}
          onChange={(e) => setFromNodeId(e.target.value)}
          style={INPUT_STYLE}
          data-testid="quick-from-node-select"
        >
          {station.spatialNodes.map((n) => (
            <option key={n.id} value={n.id}>
              {n.title}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label style={LABEL_STYLE}>终点节点 (To)</label>
        <select
          value={toNodeId}
          onChange={(e) => setToNodeId(e.target.value)}
          style={INPUT_STYLE}
          data-testid="quick-to-node-select"
        >
          {targets
            .filter((n) => n.id !== fromNodeId)
            .map((n) => (
              <option key={n.id} value={n.id}>
                {n.title}
              </option>
            ))}
        </select>
      </div>

      <button
        type="button"
        className="af5-btn af5-btn--primary"
        style={{ fontSize: 11 }}
        onClick={handleQuickAdd}
        disabled={!fromNodeId || !toNodeId || fromNodeId === toNodeId}
        data-testid="quick-create-edge-btn"
      >
        ➕ 创建并编辑连线逻辑
      </button>
    </div>
  );
};
