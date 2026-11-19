import React from 'react';
import type {
  VerificationReport,
  VerifierViolation,
} from '../../core/ir/afHyperGraph.types';
import '../../styles/afStudioV5.css';

export interface VerificationReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  report: VerificationReport | null;
  stationName?: string;
  onApplyAutoFix?: (violation: VerifierViolation) => void;
  onReverify?: () => void;
}

const VIOLATION_KIND_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  COLLISION_REACHABLE: {
    label: '物理机械干涉',
    color: 'var(--af5-vermilion, #DC2626)',
    bg: 'var(--af5-vermilion-soft, rgba(220, 38, 38, 0.11))',
  },
  GUARD_CYCLE_DEADLOCK: {
    label: '护栏死锁环路',
    color: 'var(--af5-vermilion, #DC2626)',
    bg: 'var(--af5-vermilion-soft, rgba(220, 38, 38, 0.11))',
  },
  MISSING_GUARDRAIL: {
    label: '缺失安全护栏',
    color: 'var(--af5-amber, #D97706)',
    bg: 'var(--af5-amber-soft, rgba(217, 119, 6, 0.12))',
  },
  ACTUATOR_CONTENTION: {
    label: '执行器并发冲突',
    color: 'var(--af5-amber, #D97706)',
    bg: 'var(--af5-amber-soft, rgba(217, 119, 6, 0.12))',
  },
  UNREACHABLE_STEP: {
    label: '不可达时序步',
    color: 'var(--ink-secondary, #5C5A55)',
    bg: 'var(--bg-subtle, #E5E0D5)',
  },
};

export const VerificationReportModal: React.FC<VerificationReportModalProps> = ({
  isOpen,
  onClose,
  report,
  stationName = '当前工站',
  onApplyAutoFix,
  onReverify,
}) => {
  if (!isOpen) return null;

  const violations = report?.violations ?? [];
  const warnings = report?.warnings ?? [];
  const passed = report?.passed ?? false;

  const missingGuardrails = violations.filter((v) => v.kind === 'MISSING_GUARDRAIL');

  return (
    <div
      className="af5-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="verification-report-modal"
    >
      <div
        className="af5-modal"
        style={{
          width: '100%',
          maxWidth: 680,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-card, #F7F4EE)',
        }}
      >
        {/* 弹窗头部 */}
        <div className="af5-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>🛡️</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
                符号学静态形式化验证报告
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                {stationName} · 状态空间穷举与超图护栏可达性证明
              </div>
            </div>
          </div>

          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 8px', fontSize: 12 }}
            onClick={onClose}
            aria-label="关闭弹窗"
            data-testid="close-verifier-modal-btn"
          >
            ✕
          </button>
        </div>

        {/* 核心指标概览卡片 */}
        <div
          style={{
            padding: '12px 20px',
            background: passed
              ? 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))'
              : 'var(--af5-vermilion-soft, rgba(220, 38, 38, 0.11))',
            borderBottom: '1px solid var(--border-line, #D0C9BC)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
          data-testid="verifier-summary-banner"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 22 }}>{passed ? '✅' : '⚠️'}</span>
            <div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: passed ? 'var(--af5-emerald, #059669)' : 'var(--af5-vermilion, #DC2626)',
                }}
                data-testid="verifier-status-text"
              >
                {passed ? '形式化验证全部通过 (VERIFICATION PASSED)' : '发现形式化安全违例 (VIOLATIONS DETECTED)'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                探索状态: {report?.exploredStateCount ?? 0} 个 | 耗时: {report?.elapsedMs ?? 0} ms | 违例: {violations.length} 项 | 警告: {warnings.length} 项
              </div>
            </div>
          </div>

          {onReverify && (
            <button
              type="button"
              className="af5-btn"
              onClick={onReverify}
              style={{ fontSize: 11, padding: '4px 10px' }}
              data-testid="reverify-btn"
            >
              🔄 重新验证
            </button>
          )}
        </div>

        {/* 违规列表 */}
        <div className="af5-modal-body" style={{ flex: 1, overflowY: 'auto' }} data-testid="verifier-violations-list">
          {violations.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {violations.map((violation, idx) => {
                const kindMeta = VIOLATION_KIND_LABELS[violation.kind] || {
                  label: violation.kind,
                  color: 'var(--ink-primary, #161514)',
                  bg: 'var(--bg-subtle, #E5E0D5)',
                };

                const isMissingGuard = violation.kind === 'MISSING_GUARDRAIL';

                return (
                  <div
                    key={idx}
                    className="af5-card"
                    style={{
                      padding: '10px 14px',
                      background: 'var(--bg-paper, #EFECE6)',
                      borderLeft: `4px solid ${kindMeta.color}`,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 6,
                    }}
                    data-testid={`violation-card-${idx}`}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span
                          style={{
                            fontSize: 10,
                            padding: '2px 6px',
                            borderRadius: 4,
                            background: kindMeta.bg,
                            color: kindMeta.color,
                            fontWeight: 700,
                          }}
                        >
                          {kindMeta.label}
                        </span>

                        {typeof violation.stepNo === 'number' && (
                          <span
                            style={{
                              fontSize: 10,
                              fontFamily: 'var(--font-mono, monospace)',
                              color: 'var(--ink-secondary, #5C5A55)',
                            }}
                          >
                            工步: S{violation.stepNo}
                          </span>
                        )}

                        {violation.nodeId && (
                          <span
                            style={{
                              fontSize: 10,
                              fontFamily: 'var(--font-mono, monospace)',
                              color: 'var(--ink-secondary, #5C5A55)',
                            }}
                          >
                            节点: {violation.nodeId}
                          </span>
                        )}
                      </div>

                      {/* 漏护栏一键修复按钮 */}
                      {isMissingGuard && onApplyAutoFix && (
                        <button
                          type="button"
                          className="af5-btn af5-btn--emerald"
                          style={{ fontSize: 11, padding: '2px 8px' }}
                          onClick={() => onApplyAutoFix(violation)}
                          title="自动注入缺失护栏超边"
                          data-testid={`auto-fix-btn-${idx}`}
                        >
                          🛡️ 一键注入护栏
                        </button>
                      )}
                    </div>

                    <div style={{ fontSize: 11, color: 'var(--ink-primary, #161514)', lineHeight: 1.4 }}>
                      {violation.message}
                    </div>

                    {violation.suggestedGuardEdge && (
                      <div
                        style={{
                          fontSize: 10,
                          fontFamily: 'var(--font-mono, monospace)',
                          padding: '4px 8px',
                          background: 'var(--bg-card, #F7F4EE)',
                          borderRadius: 4,
                          border: '1px solid var(--border-line, #D0C9BC)',
                          color: 'var(--af5-emerald, #059669)',
                        }}
                      >
                        推荐补全护栏: {violation.suggestedGuardEdge.humanDescription} ({violation.suggestedGuardEdge.diagCodeHex})
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div
              style={{
                padding: '30px 20px',
                textAlign: 'center',
                color: 'var(--af5-emerald, #059669)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 8,
              }}
              data-testid="verifier-clean-state"
            >
              <span style={{ fontSize: 32 }}>🛡️</span>
              <div style={{ fontWeight: 700, fontSize: 13 }}>恭喜，未发现任何安全违例与护栏缺失！</div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                所有空间执行器在全部时序步工况下均满足防撞护栏偏序约束。
              </div>
            </div>
          )}

          {/* 警告列表 */}
          {warnings.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-secondary, #5C5A55)', marginBottom: 6 }}>
                工程警告 (Warnings): {warnings.length} 项
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {warnings.map((w, wIdx) => (
                  <div
                    key={wIdx}
                    style={{
                      fontSize: 10,
                      padding: '4px 8px',
                      background: 'var(--bg-subtle, #E5E0D5)',
                      borderRadius: 4,
                      color: 'var(--ink-secondary, #5C5A55)',
                    }}
                  >
                    ⚠️ {w}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 弹窗底部操作栏 */}
        <div className="af5-modal-footer">
          <div style={{ fontSize: 11, color: 'var(--ink-tertiary, #8C887B)' }}>
            {missingGuardrails.length > 0
              ? `尚有 ${missingGuardrails.length} 处漏护栏可一键修复`
              : '形式化拓扑符合工业安全基准'}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            {missingGuardrails.length > 1 && onApplyAutoFix && (
              <button
                type="button"
                className="af5-btn af5-btn--emerald"
                onClick={() => {
                  missingGuardrails.forEach((v) => onApplyAutoFix(v));
                }}
                data-testid="auto-fix-all-btn"
              >
                🛡️ 修复全部漏护栏 ({missingGuardrails.length})
              </button>
            )}

            <button type="button" className="af5-btn" onClick={onClose} data-testid="close-verifier-btn">
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
