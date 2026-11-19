import React from 'react';
import type {
  GhostGraphTransaction,
  VerificationReport,
} from '../../core/ir/afHyperGraph.types';

export interface GhostDiffBannerProps {
  transaction: GhostGraphTransaction | null;
  verifierReport?: VerificationReport | null;
  onCommit: () => void;
  onDiscard: () => void;
  onAutoFixGuard?: () => void;
}

const IGNORED_FOCUS_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

function hasTagName(node: unknown): node is { tagName?: string; isContentEditable?: boolean } {
  return typeof node === 'object' && node !== null;
}

export function isEditableFocusTarget(
  target: EventTarget | null,
  activeElement?: Element | null
): boolean {
  const candidates = [target, activeElement];
  for (const el of candidates) {
    if (!hasTagName(el)) continue;
    const tag = typeof el.tagName === 'string' ? el.tagName.toUpperCase() : '';
    if (IGNORED_FOCUS_TAGS.has(tag) || el.isContentEditable === true) {
      return true;
    }
  }
  return false;
}

export function handleGhostBannerKeydown(
  event: Pick<KeyboardEvent, 'key' | 'target' | 'preventDefault' | 'ctrlKey' | 'metaKey' | 'altKey'>,
  callbacks: { onCommit: () => void; onDiscard: () => void },
  activeElement?: Element | null
): boolean {
  if (isEditableFocusTarget(event.target, activeElement)) {
    return false;
  }
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.altKey) {
    event.preventDefault();
    callbacks.onCommit();
    return true;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    callbacks.onDiscard();
    return true;
  }
  return false;
}

export function GhostDiffBanner({
  transaction,
  verifierReport,
  onCommit,
  onDiscard,
  onAutoFixGuard,
}: GhostDiffBannerProps): React.ReactElement | null {
  React.useEffect(() => {
    if (!transaction || typeof window === 'undefined') return;
    const listener = (event: KeyboardEvent) => {
      const activeElement = typeof document !== 'undefined' ? document.activeElement : null;
      handleGhostBannerKeydown(event, { onCommit, onDiscard }, activeElement);
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, [transaction, onCommit, onDiscard]);

  if (!transaction) return null;

  const addedNodeCount = transaction.addedNodes.length;
  const addedStepCount = transaction.addedTemporalSteps.length;
  const addedGuardCount = transaction.addedGuardEdges.length;
  const hasChanges = Boolean(addedNodeCount || addedStepCount || addedGuardCount);

  const isPassed = hasChanges && (verifierReport ? verifierReport.passed : transaction.verificationPassed);
  const violations = verifierReport?.violations ?? [];
  const warningMessages = Array.from(
    new Set([...(verifierReport?.warnings ?? []), ...transaction.verifierWarnings])
  ).filter((msg) => msg.trim().length > 0);
  const hasAlerts = !isPassed || violations.length > 0;

  return (
    <div
      className="af5-ghost-banner af5-banner af5-banner--ghost"
      role="region"
      aria-label="神经符号 AI 虚影事务预览"
      data-station-id={transaction.stationId}
      data-verified={isPassed ? 'true' : 'false'}
      style={{
        pointerEvents: 'auto',
        background: hasAlerts
          ? 'linear-gradient(135deg, #4F46E5 0%, #6366F1 65%, #991B1B 100%)'
          : 'linear-gradient(135deg, #4F46E5 0%, #6366F1 100%)',
        color: '#FFFFFF',
        padding: '10px 16px',
        borderRadius: '14px',
        border: hasAlerts ? '1.5px solid rgba(254, 202, 202, 0.7)' : '1px solid rgba(255, 255, 255, 0.24)',
        boxShadow: '0 14px 32px -8px rgba(79, 70, 229, 0.42)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        maxWidth: '760px',
        width: '100%',
        fontFamily: 'var(--font-sans, Inter, sans-serif)',
      }}
    >
      <div
        className="af5-ghost-banner__main"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          flexWrap: 'wrap',
        }}
      >
        <div
          className="af5-ghost-banner__info"
          style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: '1 1 320px', minWidth: 0 }}
        >
          <div
            className="af5-ghost-banner__header"
            style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}
          >
            <span
              className="af5-ghost-banner__badge"
              style={{
                fontSize: '10px',
                fontFamily: 'var(--font-mono, monospace)',
                fontWeight: 700,
                letterSpacing: '0.06em',
                padding: '2px 7px',
                borderRadius: '6px',
                backgroundColor: 'rgba(255, 255, 255, 0.18)',
                color: '#EEF2FF',
              }}
            >
              GHOST DIFF · {transaction.stationId}
            </span>
            <span
              className="af5-ghost-banner__summary"
              style={{ fontSize: '13px', fontWeight: 700, lineHeight: 1.35 }}
            >
              {transaction.summary}
            </span>
          </div>

          <div
            className="af5-ghost-banner__meta"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              flexWrap: 'wrap',
              fontSize: '11px',
              color: '#E0E7FF',
            }}
          >
            <span className="af5-ghost-banner__counts" style={{ fontWeight: 600 }}>
              新增 {addedNodeCount} 个实例 · {addedStepCount} 条虚影超边
              {addedGuardCount > 0 ? ` · ${addedGuardCount} 条护栏` : ''}
            </span>
            <span aria-hidden="true">·</span>
            <span className="af5-ghost-banner__pin-hint">既有锚定节点保持零位移</span>
            <span aria-hidden="true">·</span>
            <span
              className="af5-ghost-banner__verify-status"
              style={{
                fontWeight: 700,
                color: isPassed ? '#A7F3D0' : '#FECACA',
              }}
            >
              {isPassed
                ? `✔ 符号验证通过${verifierReport ? ` (${verifierReport.elapsedMs}ms · ${verifierReport.exploredStateCount} 状态)` : ''}`
                : `⚠ 静态符号验证发现 ${Math.max(1, violations.length)} 项风险`}
            </span>
          </div>
        </div>

        <div
          className="af5-ghost-banner__actions"
          style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}
        >
          {hasAlerts && onAutoFixGuard && (
            <button
              type="button"
              className="af5-ghost-banner__btn af5-ghost-banner__btn--fix"
              onClick={onAutoFixGuard}
              style={{
                padding: '6px 11px',
                borderRadius: '8px',
                border: '1px solid rgba(254, 243, 199, 0.85)',
                backgroundColor: '#FEF3C7',
                color: '#92400E',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              🛡️ 一键补齐防撞护栏
            </button>
          )}
          <button
            type="button"
            className="af5-ghost-banner__btn af5-ghost-banner__btn--commit"
            onClick={onCommit}
            style={{
              padding: '6px 12px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: '#FFFFFF',
              color: '#4338CA',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: '0 2px 6px rgba(15, 23, 42, 0.16)',
            }}
          >
            ✓ 实化采纳 (Ctrl+Enter)
          </button>
          <button
            type="button"
            className="af5-ghost-banner__btn af5-ghost-banner__btn--discard"
            onClick={onDiscard}
            style={{
              padding: '6px 10px',
              borderRadius: '8px',
              border: '1px solid rgba(255, 255, 255, 0.25)',
              backgroundColor: 'rgba(15, 23, 42, 0.24)',
              color: '#FFFFFF',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ✕ 撤回 (Esc)
          </button>
        </div>
      </div>

      {hasAlerts && (
        <div
          className="af5-ghost-banner__alert"
          role="alert"
          style={{
            backgroundColor: 'rgba(127, 29, 29, 0.45)',
            border: '1px solid rgba(254, 202, 202, 0.5)',
            borderRadius: '10px',
            padding: '8px 10px',
            fontSize: '11px',
            color: '#FEF2F2',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
          }}
        >
          <div style={{ fontWeight: 700 }}>
            碰撞 / 死锁静态符号验证告警（建议先补齐防撞护栏后再采纳）
          </div>
          {violations.map((v, idx) => (
            <div key={`${v.kind}-${v.stepNo ?? idx}`} className="af5-ghost-banner__violation">
              [{v.kind}{v.stepNo !== undefined ? ` · S${v.stepNo}` : ''}] {v.message}
            </div>
          ))}
          {warningMessages.map((w, idx) => (
            <div key={`warn-${idx}`} className="af5-ghost-banner__warning">
              • {w}
            </div>
          ))}
        </div>
      )}

      {!hasAlerts && warningMessages.length > 0 && (
        <div
          className="af5-ghost-banner__notes"
          style={{
            fontSize: '11px',
            color: '#E0E7FF',
            opacity: 0.92,
          }}
        >
          {warningMessages.join(' · ')}
        </div>
      )}
    </div>
  );
}
