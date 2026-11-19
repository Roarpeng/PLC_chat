import React, { useEffect, useState } from 'react';
import type {
  CameraFlyToStage,
  CutSetTraceResult,
} from '../../core/ir/afHyperGraph.types';
import '../../styles/afStudioV5.css';

export interface CutSetModalProps {
  isOpen: boolean;
  onClose: () => void;
  cutSetTrace: CutSetTraceResult | null;
  onStepFaultCruise?: (stageIndex: 1 | 2 | 3) => void;
  onStopFaultCruise?: () => void;
  currentActiveStage?: CameraFlyToStage | null;
}

const EMERGENCY_STAGES: Array<{
  stageIndex: 1 | 2 | 3;
  title: string;
  subtitle: string;
  desc: string;
  actionTag: string;
  color: string;
}> = [
  {
    stageIndex: 1,
    title: 'Stage 1: 软减速阻尼 (Soft Deceleration)',
    subtitle: '伺服减速释放动能，阻尼降速至安全速度',
    desc: '控制所有运动伺服轴依 S 型减速曲线降速，避免机械惯性冲击与工件脱轨飞出。',
    actionTag: '软减速降载',
    color: 'var(--af5-amber, #D97706)',
  },
  {
    stageIndex: 2,
    title: 'Stage 2: 避障寻安全位 (Obstacle Avoidance)',
    subtitle: '垂直轴避让提升，执行器退避至独立安全区',
    desc: '气缸与伺服沿干涉护栏反向退避至 AtHome 空间，夹爪/吸盘进入保压夹持锁定。',
    actionTag: '避障位锁定',
    color: 'var(--af5-klein, #2563EB)',
  },
  {
    stageIndex: 3,
    title: 'Stage 3: 机械抱闸切断 (Mechanical Brake Cutoff)',
    subtitle: '电磁抱闸失电下闸，动力主接触器切断隔离',
    desc: '触发 STO 安全力矩关断与气路机械锁止阀，完成电气隔离与最小证伪割集物理定位。',
    actionTag: '抱闸与电气隔离',
    color: 'var(--af5-vermilion, #DC2626)',
  },
];

export const CutSetModal: React.FC<CutSetModalProps> = ({
  isOpen,
  onClose,
  cutSetTrace,
  onStepFaultCruise,
  onStopFaultCruise,
  currentActiveStage,
}) => {
  const [activeStageIndex, setActiveStageIndex] = useState<1 | 2 | 3>(
    currentActiveStage?.stageIndex ?? 1
  );
  const [isPlaying, setIsPlaying] = useState<boolean>(false);

  useEffect(() => {
    if (currentActiveStage) {
      setActiveStageIndex(currentActiveStage.stageIndex);
    }
  }, [currentActiveStage?.stageIndex]);

  // 播放巡航动画定时器
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    if (isPlaying) {
      timer = setInterval(() => {
        setActiveStageIndex((prev) => {
          const next = prev === 3 ? 1 : ((prev + 1) as 1 | 2 | 3);
          onStepFaultCruise?.(next);
          return next;
        });
      }, 2000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isPlaying, onStepFaultCruise]);

  if (!isOpen) return null;

  const handleSelectStage = (idx: 1 | 2 | 3) => {
    setIsPlaying(false);
    setActiveStageIndex(idx);
    onStepFaultCruise?.(idx);
  };

  const togglePlay = () => {
    setIsPlaying(!isPlaying);
  };

  const handleClose = () => {
    setIsPlaying(false);
    onStopFaultCruise?.();
    onClose();
  };

  return (
    <div
      className="af5-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
      data-testid="cut-set-modal"
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
            <span style={{ fontSize: 16 }}>⚡</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
                跨工站因果追溯与最小割集证伪
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                受阻: {cutSetTrace?.blockedStationId ?? 'ST20'} (工步 S{cutSetTrace?.blockedStepNo ?? 20}) → 根因穿透定位
              </div>
            </div>
          </div>

          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 8px', fontSize: 12 }}
            onClick={handleClose}
            aria-label="关闭弹窗"
            data-testid="close-cutset-modal-btn"
          >
            ✕
          </button>
        </div>

        {/* 割集诊断摘要横幅 */}
        <div
          style={{
            padding: '12px 20px',
            background: 'var(--af5-vermilion-soft, rgba(220, 38, 38, 0.11))',
            borderBottom: '1px solid var(--border-line, #D0C9BC)',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
          data-testid="cutset-diagnosis-summary"
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 14, color: 'var(--af5-vermilion, #DC2626)', fontWeight: 700 }}>
                ● 割集穿透定位结果
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontFamily: 'var(--font-mono, monospace)',
                  padding: '1px 6px',
                  borderRadius: 4,
                  background: 'var(--af5-vermilion, #DC2626)',
                  color: '#fff',
                  fontWeight: 700,
                }}
              >
                FALSIFIED
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button
                type="button"
                className={`af5-btn ${isPlaying ? 'af5-btn--vermilion' : ''}`}
                style={{ fontSize: 11, padding: '3px 10px' }}
                onClick={togglePlay}
                data-testid="play-cruise-btn"
              >
                {isPlaying ? '⏸ 暂停巡航' : '▶ 播放停机巡航'}
              </button>
            </div>
          </div>

          <div style={{ fontSize: 11, color: 'var(--ink-primary, #161514)', lineHeight: 1.4 }}>
            {cutSetTrace?.diagnosisSummary || '正在沿跨站布尔 DAG 剪枝健康边并反向追溯唯一断开割集...'}
          </div>

          {/* 割集关键节点与电气端子 */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 12,
              fontSize: 10,
              paddingTop: 4,
              borderTop: '1px solid rgba(220, 38, 38, 0.2)',
              color: 'var(--ink-secondary, #5C5A55)',
            }}
          >
            <div>
              受阻节点: <strong style={{ color: 'var(--ink-primary, #161514)' }}>{cutSetTrace?.blockedNodeId || 'INST_ST20_GRIP'}</strong>
            </div>
            <div>
              根因工站: <strong style={{ color: 'var(--af5-vermilion, #DC2626)' }}>{cutSetTrace?.rootCauseStationId || 'ST10'}</strong>
            </div>
            <div>
              根因节点: <strong style={{ color: 'var(--af5-vermilion, #DC2626)' }}>{cutSetTrace?.rootCauseNodeId || 'DB_ST10_CylTransfer'}</strong>
            </div>
            <div>
              物理端子: <strong style={{ fontFamily: 'var(--font-mono, monospace)' }}>{cutSetTrace?.rootPhysicalTerminal || '%I0.4'}</strong>
            </div>
            <div>
              电柜线号: <strong style={{ fontFamily: 'var(--font-mono, monospace)' }}>{cutSetTrace?.rootCabinetWireTag || 'TB10-X2:14'}</strong>
            </div>
          </div>
        </div>

        {/* 割集红线超边 (Cut-Set Edges) */}
        <div
          style={{
            padding: '8px 20px',
            background: 'var(--bg-subtle, #E5E0D5)',
            borderBottom: '1px solid var(--border-line, #D0C9BC)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 11,
          }}
          data-testid="cutset-edges-bar"
        >
          <span style={{ fontWeight: 700, color: 'var(--ink-secondary, #5C5A55)' }}>
            红线割集超边 (Cut-Set Edges):
          </span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(cutSetTrace?.falsifiedEdgeIds ?? ['G_ST20_ST10_HOME', 'E_L1_2']).map((edgeId) => (
              <span
                key={edgeId}
                style={{
                  padding: '1px 6px',
                  borderRadius: 4,
                  background: 'var(--af5-vermilion-soft, rgba(220, 38, 38, 0.11))',
                  border: '1px solid var(--af5-vermilion-border, rgba(220, 38, 38, 0.35))',
                  color: 'var(--af5-vermilion, #DC2626)',
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: 10,
                  fontWeight: 600,
                }}
                data-testid={`cutset-edge-${edgeId}`}
              >
                {edgeId}
              </span>
            ))}
          </div>
        </div>

        {/* 三段式紧急停机巡航状态 */}
        <div className="af5-modal-body" style={{ flex: 1, overflowY: 'auto' }} data-testid="cutset-cruise-stages">
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>
            三段式紧急停机巡航控制 (Three-Stage Fault Cruise)
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {EMERGENCY_STAGES.map((stg) => {
              const isActive = activeStageIndex === stg.stageIndex;

              return (
                <div
                  key={stg.stageIndex}
                  className="af5-card"
                  style={{
                    padding: '12px 16px',
                    background: isActive ? 'var(--bg-paper, #EFECE6)' : 'var(--bg-card, #F7F4EE)',
                    borderLeft: `5px solid ${stg.color}`,
                    borderColor: isActive ? stg.color : 'var(--border-line, #D0C9BC)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    cursor: 'pointer',
                    boxShadow: isActive ? '0 2px 8px rgba(0,0,0,0.08)' : 'none',
                    transition: 'all 0.2s ease',
                  }}
                  onClick={() => handleSelectStage(stg.stageIndex)}
                  data-testid={`cruise-stage-card-${stg.stageIndex}`}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          color: isActive ? stg.color : 'var(--ink-primary, #161514)',
                        }}
                      >
                        {stg.title}
                      </span>
                      {isActive && (
                        <span
                          style={{
                            fontSize: 10,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: stg.color,
                            color: '#fff',
                            fontWeight: 700,
                          }}
                        >
                          ACTIVE
                        </span>
                      )}
                    </div>

                    <button
                      type="button"
                      className="af5-btn"
                      style={{
                        padding: '2px 8px',
                        fontSize: 10,
                        border: isActive ? `1px solid ${stg.color}` : undefined,
                        color: isActive ? stg.color : undefined,
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSelectStage(stg.stageIndex);
                      }}
                      data-testid={`step-stage-btn-${stg.stageIndex}`}
                    >
                      单步停机 →
                    </button>
                  </div>

                  <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)', fontWeight: 500 }}>
                    {stg.subtitle}
                  </div>

                  <div style={{ fontSize: 10, color: 'var(--ink-tertiary, #8C887B)', lineHeight: 1.4 }}>
                    {stg.desc}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 弹窗底部操作栏 */}
        <div className="af5-modal-footer">
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className={`af5-btn ${activeStageIndex === 1 ? 'af5-btn--primary' : ''}`}
              style={{ fontSize: 11 }}
              onClick={() => handleSelectStage(1)}
              data-testid="btn-stage-1"
            >
              1. 软减速阻尼
            </button>
            <button
              type="button"
              className={`af5-btn ${activeStageIndex === 2 ? 'af5-btn--primary' : ''}`}
              style={{ fontSize: 11 }}
              onClick={() => handleSelectStage(2)}
              data-testid="btn-stage-2"
            >
              2. 避障寻安全位
            </button>
            <button
              type="button"
              className={`af5-btn ${activeStageIndex === 3 ? 'af5-btn--primary' : ''}`}
              style={{ fontSize: 11 }}
              onClick={() => handleSelectStage(3)}
              data-testid="btn-stage-3"
            >
              3. 机械抱闸切断
            </button>
          </div>

          <button type="button" className="af5-btn" onClick={handleClose} data-testid="close-cutset-btn">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
};
