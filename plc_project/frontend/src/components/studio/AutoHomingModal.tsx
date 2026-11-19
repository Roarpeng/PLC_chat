import React, { useEffect, useState } from 'react';
import type {
  HomingSynthesisResult,
  StationHyperGraph,
} from '../../core/ir/afHyperGraph.types';
import { synthesizeSafeHomingSequence } from '../../core/algorithms/autoHomingSynth';
import '../../styles/afStudioV5.css';

export interface AutoHomingModalProps {
  isOpen: boolean;
  onClose: () => void;
  station: StationHyperGraph | null;
  onApplyHoming?: (result: HomingSynthesisResult) => void;
}

const STAGE_LABELS = [
  'Stage 0: 传感器自检与接口握手',
  'Stage 1: 夹爪开 / 真空破除',
  'Stage 2: 垂直轴 Z 提升退避',
  'Stage 3: 水平轴 X/Y 复位到原点',
];

function computeSafeHoming(station: StationHyperGraph, partPresent: boolean): HomingSynthesisResult | null {
  try {
    const targetStation: StationHyperGraph = partPresent
      ? {
          ...station,
          spatialNodes: station.spatialNodes.map((n) =>
            n.driverClass === 'FB_AF_Gripper' ? { ...n, hasPartPresentSensor: true } : n
          ),
        }
      : station;
    return synthesizeSafeHomingSequence(targetStation, { stationId: station.stationId });
  } catch (e) {
    console.error('Auto homing synthesis failed:', e);
    return null;
  }
}

export const AutoHomingModal: React.FC<AutoHomingModalProps> = ({
  isOpen,
  onClose,
  station,
  onApplyHoming,
}) => {
  const [hasPart, setHasPart] = useState(false);
  const [homingResult, setHomingResult] = useState<HomingSynthesisResult | null>(() =>
    station && isOpen ? computeSafeHoming(station, false) : null
  );
  const [selectedTab, setSelectedTab] = useState<'layers' | 'scl'>('layers');

  const recompute = (partPresent: boolean) => {
    if (!station) return;
    setHomingResult(computeSafeHoming(station, partPresent));
  };

  useEffect(() => {
    if (isOpen && station) {
      setHomingResult(computeSafeHoming(station, hasPart));
    }
  }, [isOpen, station?.stationId, hasPart]);

  if (!isOpen || !station) {
    return null;
  }

  const handleApply = () => {
    if (homingResult && onApplyHoming) {
      onApplyHoming(homingResult);
    }
    onClose();
  };

  return (
    <div
      className="af5-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="auto-homing-modal"
    >
      <div
        className="af5-modal"
        style={{
          width: '100%',
          maxWidth: 720,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-card, #F7F4EE)',
        }}
      >
        {/* 弹窗头部 */}
        <div className="af5-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>🏠</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
                自动归航偏序分层合成 (Kahn Auto-Homing)
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                工站: {station.stationName} ({station.stationId}) · Kahn 偏序无碰撞拓扑分层
              </div>
            </div>
          </div>

          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 8px', fontSize: 12 }}
            onClick={onClose}
            aria-label="关闭弹窗"
            data-testid="close-homing-modal-btn"
          >
            ✕
          </button>
        </div>

        {/* 弹窗控制栏 */}
        <div
          style={{
            padding: '10px 20px',
            background: 'var(--bg-subtle, #E5E0D5)',
            borderBottom: '1px solid var(--border-line, #D0C9BC)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
          }}
        >
          {/* 带料分支开关 */}
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              color: 'var(--ink-primary, #161514)',
            }}
          >
            <input
              type="checkbox"
              checked={hasPart}
              onChange={(e) => {
                const next = e.target.checked;
                setHasPart(next);
                recompute(next);
              }}
              data-testid="homing-has-part-checkbox"
            />
            <span>工件在位保护分支 (hasPart=true)</span>
          </label>

          {/* 切换分层树 / 生成代码 */}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className={`af5-btn ${selectedTab === 'layers' ? 'af5-btn--primary' : ''}`}
              style={{ padding: '3px 10px', fontSize: 11 }}
              onClick={() => setSelectedTab('layers')}
              data-testid="tab-layers-btn"
            >
              分层拓扑树
            </button>
            <button
              type="button"
              className={`af5-btn ${selectedTab === 'scl' ? 'af5-btn--primary' : ''}`}
              style={{ padding: '3px 10px', fontSize: 11 }}
              onClick={() => setSelectedTab('scl')}
              data-testid="tab-scl-btn"
            >
              生成 SCL 代码
            </button>
          </div>
        </div>

        {/* 带料警告徽章 */}
        {hasPart && (
          <div
            style={{
              margin: '12px 20px 0',
              padding: '8px 12px',
              borderRadius: 8,
              background: 'var(--af5-amber-soft, rgba(217, 119, 6, 0.12))',
              border: '1px solid var(--af5-amber-border, rgba(217, 119, 6, 0.32))',
              color: 'var(--af5-amber, #D97706)',
              fontSize: 12,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
            data-testid="homing-part-warning-badge"
          >
            <span style={{ fontSize: 16 }}>⚠️</span>
            <div>
              <strong>带料安全分支激活:</strong> 检测到夹爪/吸盘持有工件，归航序列将保持保压与夹持路径，严禁张开释放物料，避免高位掉料！
            </div>
          </div>
        )}

        {/* 弹窗内容区 */}
        <div className="af5-modal-body" style={{ flex: 1, overflowY: 'auto' }}>
          {/* Kahn 偏序分层标准流水线指示 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              background: 'var(--bg-subtle, #E5E0D5)',
              borderRadius: 8,
              fontSize: 10,
              fontWeight: 600,
              color: 'var(--ink-secondary, #5C5A55)',
              gap: 4,
              overflowX: 'auto',
            }}
            data-testid="homing-kahn-pipeline-bar"
          >
            <span>Stage 0: 传感器自检</span>
            <span>→</span>
            <span>Stage 1: 夹爪开/真空破除</span>
            <span>→</span>
            <span>Stage 2: 垂直轴 Z 提升</span>
            <span>→</span>
            <span>Stage 3: 水平轴 X/Y 复位</span>
          </div>

          {selectedTab === 'layers' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="homing-layers-tree">
              {homingResult && homingResult.hasCycleDeadlock && (
                <div
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    background: 'var(--af5-vermilion-soft, rgba(220, 38, 38, 0.11))',
                    border: '1px solid var(--af5-vermilion-border, rgba(220, 38, 38, 0.35))',
                    color: 'var(--af5-vermilion, #DC2626)',
                    fontSize: 12,
                  }}
                  data-testid="homing-cycle-deadlock-alert"
                >
                  <strong>检测到护栏死锁环路:</strong> 节点 [{homingResult.cycleNodeIds.join(', ')}] 存在相互依赖，无法通过 Kahn 偏序分层。
                </div>
              )}

              {/* 渲染 Kahn 拓扑层级 */}
              {homingResult && homingResult.concurrentLayers.length > 0 ? (
                homingResult.concurrentLayers.map((layerNodes, idx) => {
                  const stageTitle = STAGE_LABELS[idx] || `Stage ${idx}: 并发动作层`;
                  const layerActs = homingResult.layerActions[idx] || [];

                  return (
                    <div
                      key={idx}
                      className="af5-card"
                      style={{
                        padding: '10px 14px',
                        background: 'var(--bg-paper, #EFECE6)',
                        borderLeft: '4px solid var(--af5-klein, #2563EB)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 6,
                      }}
                      data-testid={`homing-stage-${idx}`}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontWeight: 700,
                          fontSize: 12,
                          color: 'var(--ink-primary, #161514)',
                        }}
                      >
                        <span>{stageTitle}</span>
                        <span
                          style={{
                            fontSize: 10,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: 'var(--bg-subtle, #E5E0D5)',
                            color: 'var(--ink-secondary, #5C5A55)',
                          }}
                        >
                          {layerNodes.length} 个执行器并发
                        </span>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                        {layerNodes.map((node, nodeIdx) => {
                          const action = layerActs[nodeIdx];
                          return (
                            <div
                              key={node.id}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                fontSize: 11,
                                padding: '4px 8px',
                                background: 'var(--bg-card, #F7F4EE)',
                                borderRadius: 6,
                                border: '1px solid var(--border-line, #D0C9BC)',
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span style={{ fontWeight: 600 }}>{node.title}</span>
                                <span
                                  style={{
                                    fontFamily: 'var(--font-mono, monospace)',
                                    fontSize: 10,
                                    color: 'var(--ink-secondary, #5C5A55)',
                                  }}
                                >
                                  ({node.instanceDb})
                                </span>
                                {action?.partPresentProtected && (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      padding: '1px 4px',
                                      borderRadius: 4,
                                      background: 'var(--af5-amber-soft, rgba(217, 119, 6, 0.12))',
                                      color: 'var(--af5-amber, #D97706)',
                                      fontWeight: 600,
                                    }}
                                  >
                                    保压保持
                                  </span>
                                )}
                              </div>

                              <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10 }}>
                                <code>{action?.sclSnippet || `${node.instanceDb}.RetractHome();`}</code>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div style={{ padding: 20, textAlign: 'center', color: 'var(--ink-tertiary, #8C887B)' }}>
                  工站暂无可归航执行器节点
                </div>
              )}
            </div>
          ) : (
            /* 生成的 SCL 代码块 */
            <div
              className="af5-drawer-code"
              style={{
                borderRadius: 8,
                padding: 12,
                maxHeight: 380,
                overflowY: 'auto',
              }}
              data-testid="homing-generated-scl"
            >
              <pre style={{ margin: 0 }}>
                {homingResult?.generatedHomeScl || '// 暂无生成的归航代码'}
              </pre>
            </div>
          )}
        </div>

        {/* 弹窗底部操作栏 */}
        <div className="af5-modal-footer">
          <button
            type="button"
            className="af5-btn"
            onClick={() => recompute(hasPart)}
            data-testid="recompute-homing-btn"
          >
            🔄 重新计算
          </button>

          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="af5-btn" onClick={onClose} data-testid="cancel-homing-btn">
              取消
            </button>
            <button
              type="button"
              className="af5-btn af5-btn--emerald"
              onClick={handleApply}
              data-testid="apply-homing-btn"
            >
              ✓ 应用为归航逻辑
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
