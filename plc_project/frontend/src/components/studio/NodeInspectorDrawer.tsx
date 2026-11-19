import React, { useState } from 'react';
import type {
  AfStudioWorkspaceData,
  ProjectCompoundEdge,
  ProjectCompoundStation,
  ProjectHyperGraph,
  SafetyGuardEdge,
  SelectedHyperEntity,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
} from '../../core/ir/afHyperGraph.types';
import {
  GuardEdgeEditor,
  L1EdgeEditor,
  L1StationEditor,
  QuickEdgeCreatorCard,
  StepEdgeEditor,
} from './InspectorEdgeEditors';
import { CmFieldBindings } from './FieldIoEditor';
import '../../styles/afStudioV5.css';

export interface NodeInspectorDrawerProps {
  isOpen: boolean;
  onClose?: () => void;
  selectedNodeId: string | null;
  selectedEntity?: SelectedHyperEntity;
  layer?: 'PROJECT' | 'STATION';
  projectGraph?: ProjectHyperGraph | null;
  station: StationHyperGraph | null;
  fieldIoWorkspace?: AfStudioWorkspaceData;
  onBindFieldPoint?: (nodeId: string, portId: string, pointId: string) => string | undefined;
  onOpenPointTable?: () => void;
  onUpdateNode?: (nodeId: string, patch: Partial<SpatialInstanceNode>) => void;
  onDeleteNode?: (nodeId: string) => void;
  onCenterFocus?: (nodeId: string) => void;
  onSelectStep?: (stepNo: number) => void;
  onSelectEntity?: (entity: SelectedHyperEntity) => void;
  onAddGuardEdge?: (edge: SafetyGuardEdge) => void;
  onUpdateGuardEdge?: (edgeId: string, patch: Partial<SafetyGuardEdge>) => void;
  onDeleteGuardEdge?: (edgeId: string) => void;
  onAddTemporalStep?: (step: TemporalStepHyperEdge) => void;
  onUpdateTemporalStep?: (stepId: string, patch: Partial<TemporalStepHyperEdge>) => void;
  onDeleteTemporalStep?: (stepId: string) => void;
  onUpdateProjectStation?: (nodeId: string, patch: Partial<ProjectCompoundStation>) => void;
  onDeleteProjectStation?: (nodeId: string) => void;
  onAddProjectEdge?: (edge: ProjectCompoundEdge) => void;
  onUpdateProjectEdge?: (edgeId: string, patch: Partial<ProjectCompoundEdge>) => void;
  onDeleteProjectEdge?: (edgeId: string) => void;
  onEnterStation?: (stationId: string) => void;
}

export const NodeInspectorDrawer: React.FC<NodeInspectorDrawerProps> = ({
  isOpen,
  onClose,
  selectedNodeId,
  selectedEntity = null,
  layer = 'STATION',
  projectGraph = null,
  station,
  fieldIoWorkspace,
  onBindFieldPoint,
  onOpenPointTable,
  onUpdateNode,
  onDeleteNode,
  onCenterFocus,
  onSelectStep,
  onSelectEntity,
  onAddGuardEdge,
  onUpdateGuardEdge,
  onDeleteGuardEdge,
  onAddTemporalStep,
  onUpdateTemporalStep,
  onDeleteTemporalStep,
  onUpdateProjectStation,
  onDeleteProjectStation,
  onAddProjectEdge,
  onUpdateProjectEdge,
  onDeleteProjectEdge,
  onEnterStation,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editDb, setEditDb] = useState('');
  const [editIo, setEditIo] = useState<Record<string, string>>({});
  const [simulatedState, setSimulatedState] = useState<string>('');
  const [minSafePos, setMinSafePos] = useState<number>(0);
  const [maxSafePos, setMaxSafePos] = useState<number>(450);

  const effectiveNodeId =
    selectedNodeId ?? (selectedEntity?.kind === 'NODE' ? selectedEntity.id : null);
  const selectedNode = station && effectiveNodeId
    ? station.spatialNodes.find((n) => n.id === effectiveNodeId) ?? null
    : null;
  const selectedStep =
    station && selectedEntity?.kind === 'STEP'
      ? station.temporalSteps.find((s) => s.id === selectedEntity.id) ?? null
      : null;
  const selectedGuard =
    station && selectedEntity?.kind === 'GUARD'
      ? station.guardEdges.find((g) => g.id === selectedEntity.id) ?? null
      : null;
  const selectedL1Edge =
    projectGraph && selectedEntity?.kind === 'L1_EDGE'
      ? projectGraph.edges.find((e) => e.id === selectedEntity.id) ?? null
      : null;
  const selectedL1Station =
    projectGraph && selectedEntity?.kind === 'STATION'
      ? projectGraph.stations.find((s) => s.id === selectedEntity.id) ?? null
      : null;

  // Initialize editing fields when selected node changes
  React.useEffect(() => {
    if (selectedNode) {
      setEditTitle(selectedNode.title);
      setEditDb(selectedNode.instanceDb);
      setSimulatedState(selectedNode.initialHomeState || selectedNode.discreteStates[0] || 'Unknown');
      setIsEditing(false);
    }
  }, [selectedNode?.id]);

  if (!isOpen) {
    return null;
  }

  // Incoming and outgoing guardrails
  const incomingGuards: SafetyGuardEdge[] = station && selectedNode
    ? station.guardEdges.filter((g) => g.toNode === selectedNode.id)
    : [];

  const outgoingGuards: SafetyGuardEdge[] = station && selectedNode
    ? station.guardEdges.filter((g) => g.fromNode === selectedNode.id)
    : [];

  // Associated temporal steps
  const associatedSteps: TemporalStepHyperEdge[] = station && selectedNode
    ? station.temporalSteps.filter(
        (s) =>
          s.fromNode === selectedNode.id ||
          s.invocations.some((inv) => inv.targetNodeId === selectedNode.id)
      )
    : [];

  const handleSaveEdit = () => {
    if (selectedNode && onUpdateNode) {
      onUpdateNode(selectedNode.id, {
        title: editTitle.trim() || selectedNode.title,
        instanceDb: editDb.trim() || selectedNode.instanceDb,
        cohesiveIoMap: Object.fromEntries(Object.entries(editIo).map(([key, value]) => [key, value.trim()])),
        ioSummaryText: Object.keys(editIo).some((key) => editIo[key].trim() !== selectedNode.cohesiveIoMap[key])
          ? undefined : selectedNode.ioSummaryText,
      });
    }
    setIsEditing(false);
  };

  const handleDelete = () => {
    if (!selectedNode || !onDeleteNode) return;
    onDeleteNode(selectedNode.id);
  };

  const handleFocus = () => {
    if (selectedNode && onCenterFocus) {
      onCenterFocus(selectedNode.id);
    }
  };

  return (
    <aside
      className="af5-sidebar-right af5-node-inspector-drawer"
      style={{
        width: 320,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--bg-paper, #EFECE6)',
        borderLeft: '1px solid var(--border-line, #D0C9BC)',
        padding: '14px 16px',
        gap: 12,
        overflowY: 'auto',
        userSelect: 'none',
        zIndex: 25,
      }}
      data-testid="node-inspector-drawer"
    >
      {/* 抽屉顶部标题栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 10,
          borderBottom: '1px solid var(--border-line, #D0C9BC)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span style={{ fontSize: 13, fontWeight: 700, whiteSpace: 'nowrap' }}>
            {selectedStep
              ? '时序步连线与逻辑编辑器'
              : selectedGuard
                ? '安全护栏逻辑编辑器'
                : selectedL1Edge
                  ? '产线跨站连线编辑器'
                  : selectedL1Station
                    ? 'L1 复合工站属性'
                    : '执行器属性检查器'}
          </span>
          {(selectedNode || selectedEntity) && (
            <span
              style={{
                fontSize: 10,
                fontFamily: 'var(--font-mono, monospace)',
                color: 'var(--ink-secondary, #5C5A55)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              #{(selectedNode?.id ?? selectedEntity?.id) || ''}
            </span>
          )}
        </div>

        {onClose && (
          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 8px', fontSize: 11, borderRadius: 6 }}
            onClick={onClose}
            title="收起检查器"
            aria-label="收起检查器"
            data-testid="close-inspector-btn"
          >
            ✕
          </button>
        )}
      </div>

      {selectedStep && station ? (
        <StepEdgeEditor
          step={selectedStep}
          station={station}
          onUpdateStep={onUpdateTemporalStep}
          onDeleteStep={onDeleteTemporalStep}
        />
      ) : selectedGuard && station ? (
        <GuardEdgeEditor
          guard={selectedGuard}
          station={station}
          onUpdateGuard={onUpdateGuardEdge}
          onDeleteGuard={onDeleteGuardEdge}
        />
      ) : selectedL1Edge && projectGraph ? (
        <L1EdgeEditor
          edge={selectedL1Edge}
          projectGraph={projectGraph}
          onUpdateEdge={onUpdateProjectEdge}
          onDeleteEdge={onDeleteProjectEdge}
        />
      ) : selectedL1Station && projectGraph ? (
        <L1StationEditor
          stationCard={selectedL1Station}
          projectGraph={projectGraph}
          onUpdateStation={onUpdateProjectStation}
          onDeleteStation={onDeleteProjectStation}
          onEnterStation={onEnterStation}
          onAddProjectEdge={onAddProjectEdge}
        />
      ) : !selectedNode ? (
        /* 未选中实体时的占位引导与连线速查/创建工具 */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--ink-tertiary, #8C887B)',
              fontSize: 12,
              gap: 6,
              textAlign: 'center',
              padding: '16px 12px',
            }}
            data-testid="inspector-empty-state"
          >
            <div style={{ fontSize: 22 }}>🔍</div>
            <div>未选中执行器节点</div>
            <div style={{ fontSize: 11, lineHeight: 1.5 }}>
              点击节点或任意连线可编辑/删除；选中节点或连线后也可按 Delete 键删除
            </div>
          </div>

          {layer === 'PROJECT' && projectGraph && projectGraph.edges.length > 0 && (
            <div className="af5-card" style={{ padding: 12, gap: 6, display: 'flex', flexDirection: 'column' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-secondary, #5C5A55)' }}>
                跨站连线清单 ({projectGraph.edges.length})
              </div>
              {projectGraph.edges.map((edge) => (
                <div key={edge.id} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <button
                    type="button"
                    className="af5-btn"
                    style={{
                      flex: 1,
                      minWidth: 0,
                      justifyContent: 'space-between',
                      fontSize: 10,
                      padding: '4px 8px',
                      textAlign: 'left',
                    }}
                    onClick={() => onSelectEntity?.({ kind: 'L1_EDGE', id: edge.id })}
                    data-testid={`inspector-list-l1-edge-${edge.id}`}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {edge.label}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono, monospace)', opacity: 0.7 }}>{edge.kind}</span>
                  </button>
                  {onDeleteProjectEdge && (
                    <button
                      type="button"
                      className="af5-btn af5-btn--vermilion"
                      style={{ padding: '4px 7px', fontSize: 10, flexShrink: 0 }}
                      title="删除此跨站连线"
                      onClick={() => onDeleteProjectEdge(edge.id)}
                      data-testid={`quick-delete-l1-edge-${edge.id}`}
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {layer === 'STATION' && station && (
            <>
              <QuickEdgeCreatorCard
                station={station}
                onAddTemporalStep={onAddTemporalStep}
                onAddGuardEdge={onAddGuardEdge}
                onSelectEntity={onSelectEntity}
              />

              {(station.temporalSteps.length > 0 || station.guardEdges.length > 0) && (
                <div className="af5-card" style={{ padding: 12, gap: 6, display: 'flex', flexDirection: 'column' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-secondary, #5C5A55)' }}>
                    当前工站连线逻辑列表
                  </div>
                  {station.temporalSteps.map((s) => (
                    <div key={s.id} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <button
                        type="button"
                        className="af5-btn"
                        style={{
                          flex: 1,
                          minWidth: 0,
                          justifyContent: 'space-between',
                          fontSize: 10,
                          padding: '4px 8px',
                          textAlign: 'left',
                        }}
                        onClick={() => {
                          onSelectEntity?.({ kind: 'STEP', id: s.id });
                          onSelectStep?.(s.stepNo);
                        }}
                        data-testid={`inspector-list-step-${s.id}`}
                      >
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          S{s.stepNo} · {s.title}
                        </span>
                        <span style={{ color: 'var(--af5-klein, #2563EB)' }}>编辑</span>
                      </button>
                      {onDeleteTemporalStep && (
                        <button
                          type="button"
                          className="af5-btn af5-btn--vermilion"
                          style={{ padding: '4px 7px', fontSize: 10, flexShrink: 0 }}
                          title="删除此时序连线"
                          onClick={() => onDeleteTemporalStep(s.id)}
                          data-testid={`quick-delete-step-${s.id}`}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                  {station.guardEdges.map((g) => (
                    <div key={g.id} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <button
                        type="button"
                        className="af5-btn"
                        style={{
                          flex: 1,
                          minWidth: 0,
                          justifyContent: 'space-between',
                          fontSize: 10,
                          padding: '4px 8px',
                          textAlign: 'left',
                        }}
                        onClick={() => onSelectEntity?.({ kind: 'GUARD', id: g.id })}
                        data-testid={`inspector-list-guard-${g.id}`}
                      >
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          🛡️ {g.humanDescription}
                        </span>
                        <span style={{ color: 'var(--af5-amber, #D97706)' }}>{g.diagCodeHex}</span>
                      </button>
                      {onDeleteGuardEdge && (
                        <button
                          type="button"
                          className="af5-btn af5-btn--vermilion"
                          style={{ padding: '4px 7px', fontSize: 10, flexShrink: 0 }}
                          title="删除此安全护栏连线"
                          onClick={() => onDeleteGuardEdge(g.id)}
                          data-testid={`quick-delete-guard-${g.id}`}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        /* 选中节点的详细属性展示 */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 1. 基本信息卡片 */}
          <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--ink-secondary, #5C5A55)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              基本信息 (Basic Info)
            </div>

            {isEditing ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <label style={{ fontSize: 10, color: 'var(--ink-secondary, #5C5A55)' }}>实例名称</label>
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '4px 6px',
                      fontSize: 11,
                      borderRadius: 4,
                      border: '1px solid var(--border-line, #D0C9BC)',
                    }}
                    data-testid="edit-node-title-input"
                  />
                </div>
                <div>
                  <label style={{ fontSize: 10, color: 'var(--ink-secondary, #5C5A55)' }}>背景数据块 (Instance DB)</label>
                  <input
                    type="text"
                    value={editDb}
                    onChange={(e) => setEditDb(e.target.value)}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '4px 6px',
                      fontSize: 11,
                      fontFamily: 'var(--font-mono, monospace)',
                      borderRadius: 4,
                      border: '1px solid var(--border-line, #D0C9BC)',
                    }}
                    data-testid="edit-node-db-input"
                  />
                </div>
                {!selectedNode.cmProfile && Object.entries(editIo).map(([key, value]) => (
                  <label className="af5-station-field" key={key}>
                    {key}
                    <input value={value} placeholder="待绑定" onChange={(event) => setEditIo({ ...editIo, [key]: event.target.value })} />
                  </label>
                ))}
                <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 4 }}>
                  <button
                    type="button"
                    className="af5-btn"
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={() => setIsEditing(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="af5-btn af5-btn--primary"
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={handleSaveEdit}
                    data-testid="save-node-edit-btn"
                  >
                    保存
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>实例名称:</span>
                  <span style={{ fontWeight: 700 }} data-testid="inspector-node-title">{selectedNode.title}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>驱动母版:</span>
                  <span style={{ fontFamily: 'var(--font-mono, monospace)' }} data-testid="inspector-node-driver">
                    {selectedNode.driverClass}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>背景 DB:</span>
                  <span style={{ fontFamily: 'var(--font-mono, monospace)' }} data-testid="inspector-node-db">
                    {selectedNode.instanceDb}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>工位归属:</span>
                  <span>{station?.stationName || station?.stationId}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>空间坐标 (X/Y):</span>
                  <span style={{ fontFamily: 'var(--font-mono, monospace)' }} data-testid="inspector-node-position">
                    ({Math.round(selectedNode.position.x)}, {Math.round(selectedNode.position.y)})
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* 2. 离散状态集与当前仿真状态 */}
          <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--ink-secondary, #5C5A55)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              离散状态与仿真 (States & Simulation)
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>当前仿真状态:</span>
              <span
                style={{
                  padding: '2px 8px',
                  borderRadius: 6,
                  background: 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
                  color: 'var(--af5-emerald, #059669)',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono, monospace)',
                }}
                data-testid="inspector-sim-state-badge"
              >
                {simulatedState}
              </span>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
              {selectedNode.discreteStates.map((st) => (
                <button
                  key={st}
                  type="button"
                  onClick={() => setSimulatedState(st)}
                  style={{
                    padding: '2px 6px',
                    fontSize: 10,
                    borderRadius: 4,
                    border: simulatedState === st ? '1px solid var(--af5-emerald, #059669)' : '1px solid var(--border-line, #D0C9BC)',
                    background: simulatedState === st ? 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))' : 'var(--bg-paper, #EFECE6)',
                    color: simulatedState === st ? 'var(--af5-emerald, #059669)' : 'var(--ink-primary, #161514)',
                    cursor: 'pointer',
                  }}
                  data-testid={`state-chip-${st}`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          {selectedNode.cmProfile && station && fieldIoWorkspace && onBindFieldPoint && onOpenPointTable ? (
            <CmFieldBindings key={selectedNode.id} workspace={fieldIoWorkspace} stationId={station.stationId}
              node={selectedNode} onBind={(portId, pointId) => onBindFieldPoint(selectedNode.id, portId, pointId)}
              onOpenPointTable={onOpenPointTable} />
          ) : <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--ink-secondary, #5C5A55)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              物理引脚映射 (Cohesive I/O Map)
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
              {Object.entries(selectedNode.cohesiveIoMap).length > 0 ? (
                Object.entries(selectedNode.cohesiveIoMap).map(([k, v]) => (
                  <div
                    key={k}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '2px 4px',
                      background: 'var(--bg-paper, #EFECE6)',
                      borderRadius: 4,
                    }}
                  >
                    <span style={{ fontFamily: 'var(--font-mono, monospace)', color: 'var(--ink-secondary, #5C5A55)' }}>
                      {k}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono, monospace)', fontWeight: 600 }}>
                      {v || '待绑定'}
                    </span>
                  </div>
                ))
              ) : (
                <div style={{ color: 'var(--ink-tertiary, #8C887B)', fontSize: 10 }}>无内聚引脚配置</div>
              )}
            </div>
          </div>}

          {/* 4. 安全软边界 */}
          <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--ink-secondary, #5C5A55)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              安全软边界 (Safe Soft Limits)
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>MinSafePos (软下限):</span>
                <input
                  type="number"
                  value={minSafePos}
                  onChange={(e) => setMinSafePos(Number(e.target.value))}
                  style={{
                    width: 70,
                    textAlign: 'right',
                    padding: '2px 4px',
                    fontSize: 11,
                    fontFamily: 'var(--font-mono, monospace)',
                    border: '1px solid var(--border-line, #D0C9BC)',
                    borderRadius: 4,
                  }}
                  data-testid="input-min-safe-pos"
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: 'var(--ink-secondary, #5C5A55)' }}>MaxSafePos (软上限):</span>
                <input
                  type="number"
                  value={maxSafePos}
                  onChange={(e) => setMaxSafePos(Number(e.target.value))}
                  style={{
                    width: 70,
                    textAlign: 'right',
                    padding: '2px 4px',
                    fontSize: 11,
                    fontFamily: 'var(--font-mono, monospace)',
                    border: '1px solid var(--border-line, #D0C9BC)',
                    borderRadius: 4,
                  }}
                  data-testid="input-max-safe-pos"
                />
              </div>
            </div>
          </div>

          {/* 5. 关联时序步与输入/输出护栏超边 */}
          <div className="af5-card" style={{ padding: 12, gap: 8, display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: 'var(--ink-secondary, #5C5A55)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              拓扑超边关联 (Hyperedges)
            </div>

            {/* 输入护栏 */}
            <div>
              <div style={{ fontSize: 10, color: 'var(--ink-secondary, #5C5A55)', marginBottom: 2 }}>
                输入防撞护栏 (In Guardrails): {incomingGuards.length} 条
              </div>
              {incomingGuards.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {incomingGuards.map((g) => (
                    <div key={g.id} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <button
                        type="button"
                        onClick={() => onSelectEntity?.({ kind: 'GUARD', id: g.id })}
                        style={{
                          flex: 1,
                          minWidth: 0,
                          textAlign: 'left',
                          fontSize: 10,
                          padding: '4px 6px',
                          background: 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
                          borderRadius: 4,
                          border: 'none',
                          borderLeft: '2px solid var(--af5-emerald, #059669)',
                          cursor: 'pointer',
                        }}
                        title="点击编辑该安全护栏连线逻辑"
                        data-testid={`guard-in-${g.id}`}
                      >
                        {g.humanDescription} ({g.diagCodeHex}) ✏️
                      </button>
                      {onDeleteGuardEdge && (
                        <button
                          type="button"
                          onClick={() => onDeleteGuardEdge(g.id)}
                          style={{
                            padding: '3px 6px',
                            fontSize: 10,
                            borderRadius: 4,
                            border: '1px solid var(--af5-vermilion-border, rgba(220,38,38,0.35))',
                            background: 'var(--af5-vermilion-soft, rgba(220,38,38,0.1))',
                            color: '#DC2626',
                            cursor: 'pointer',
                          }}
                          title="删除此输入护栏"
                          data-testid={`quick-delete-guard-${g.id}`}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 10, color: 'var(--ink-tertiary, #8C887B)' }}>无输入护栏</div>
              )}
            </div>

            {/* 输出护栏 */}
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 10, color: 'var(--ink-secondary, #5C5A55)', marginBottom: 2 }}>
                输出保护护栏 (Out Guardrails): {outgoingGuards.length} 条
              </div>
              {outgoingGuards.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {outgoingGuards.map((g) => (
                    <div key={g.id} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <button
                        type="button"
                        onClick={() => onSelectEntity?.({ kind: 'GUARD', id: g.id })}
                        style={{
                          flex: 1,
                          minWidth: 0,
                          textAlign: 'left',
                          fontSize: 10,
                          padding: '4px 6px',
                          background: 'var(--af5-klein-soft, rgba(37, 99, 235, 0.10))',
                          borderRadius: 4,
                          border: 'none',
                          borderLeft: '2px solid var(--af5-klein, #2563EB)',
                          cursor: 'pointer',
                        }}
                        title="点击编辑该安全护栏连线逻辑"
                        data-testid={`guard-out-${g.id}`}
                      >
                        {g.humanDescription} ({g.diagCodeHex}) ✏️
                      </button>
                      {onDeleteGuardEdge && (
                        <button
                          type="button"
                          onClick={() => onDeleteGuardEdge(g.id)}
                          style={{
                            padding: '3px 6px',
                            fontSize: 10,
                            borderRadius: 4,
                            border: '1px solid var(--af5-vermilion-border, rgba(220,38,38,0.35))',
                            background: 'var(--af5-vermilion-soft, rgba(220,38,38,0.1))',
                            color: '#DC2626',
                            cursor: 'pointer',
                          }}
                          title="删除此输出护栏"
                          data-testid={`quick-delete-guard-${g.id}`}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 10, color: 'var(--ink-tertiary, #8C887B)' }}>无输出护栏</div>
              )}
            </div>

            {/* 关联时序步 */}
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 10, color: 'var(--ink-secondary, #5C5A55)', marginBottom: 2 }}>
                关联工步 (Temporal Steps): {associatedSteps.length} 个
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {associatedSteps.map((s) => (
                  <div
                    key={s.id}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      borderRadius: 4,
                      background: 'var(--bg-paper, #EFECE6)',
                      border: '1px solid var(--border-line, #D0C9BC)',
                      overflow: 'hidden',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        onSelectStep?.(s.stepNo);
                        onSelectEntity?.({ kind: 'STEP', id: s.id });
                      }}
                      style={{
                        padding: '2px 5px',
                        fontSize: 10,
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                      }}
                      title={`${s.title} · 点击编辑步序连线逻辑`}
                      data-testid={`step-chip-${s.stepNo}`}
                    >
                      S{s.stepNo} ✏️
                    </button>
                    {onDeleteTemporalStep && (
                      <button
                        type="button"
                        onClick={() => onDeleteTemporalStep(s.id)}
                        style={{
                          padding: '2px 5px',
                          fontSize: 10,
                          background: 'rgba(220, 38, 38, 0.08)',
                          color: '#DC2626',
                          border: 'none',
                          borderLeft: '1px solid var(--border-line, #D0C9BC)',
                          cursor: 'pointer',
                        }}
                        title={`删除步序 S${s.stepNo}`}
                        data-testid={`quick-delete-step-${s.id}`}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {station && (
            <QuickEdgeCreatorCard
              selectedNode={selectedNode}
              station={station}
              onAddTemporalStep={onAddTemporalStep}
              onAddGuardEdge={onAddGuardEdge}
              onSelectEntity={onSelectEntity}
            />
          )}

          {/* 6. 操作按钮 */}
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            {!isEditing && (
              <button
                type="button"
                className="af5-btn"
                style={{ flex: 1, fontSize: 11 }}
                onClick={() => {
                  setEditTitle(selectedNode.title);
                  setEditDb(selectedNode.instanceDb);
                  setEditIo(selectedNode.cohesiveIoMap);
                  setIsEditing(true);
                }}
                data-testid="edit-node-btn"
              >
                ✏️ 编辑属性
              </button>
            )}

            <button
              type="button"
              className="af5-btn"
              style={{ flex: 1, fontSize: 11 }}
              onClick={handleFocus}
              data-testid="focus-node-btn"
            >
              🎯 居中聚焦
            </button>

            <button
              type="button"
              className="af5-btn af5-btn--vermilion"
              style={{ fontSize: 11, padding: '6px 10px' }}
              onClick={handleDelete}
              title="删除此节点及其连线"
              data-testid="delete-node-btn"
            >
              🗑️ 删除节点
            </button>
          </div>
        </div>
      )}
    </aside>
  );
};
