import React, { useRef, useState } from 'react';
import type { StationHyperGraph } from '../../core/ir/afHyperGraph.types';

export interface TimeRibbonScrubberProps {
  layer: 'PROJECT' | 'STATION';
  station?: StationHyperGraph | null;
  focusedStepNo: number | null;
  isAutoPlaying?: boolean;
  onFocusStep: (stepNo: number | null) => void;
  onStepPrev?: () => void;
  onStepNext?: () => void;
  onToggleAutoPlay?: () => void;
  onSubmitPrompt?: (text: string) => void;
  onEditStep?: (stepId: string) => void;
  showWireLabels?: boolean;
  onToggleWireLabels?: () => void;
}

export const TimeRibbonScrubber: React.FC<TimeRibbonScrubberProps> = ({
  layer,
  station,
  focusedStepNo,
  isAutoPlaying = false,
  onFocusStep,
  onStepPrev,
  onStepNext,
  onToggleAutoPlay,
  onSubmitPrompt,
  onEditStep,
  showWireLabels = false,
  onToggleWireLabels,
}) => {
  const [promptText, setPromptText] = useState('');
  const promptRef = useRef('');

  const sortedSteps = station
    ? [...station.temporalSteps].sort((a, b) => a.stepNo - b.stepNo)
    : [];
  const step = sortedSteps.find(({ stepNo }) => stepNo === focusedStepNo);
  const nodesById = new Map(station?.spatialNodes.map((node) => [node.id, node]));
  const source = step ? nodesById.get(step.fromNode) : undefined;

  const handleStepPrev = () => {
    if (onStepPrev) {
      onStepPrev();
      return;
    }
    if (layer !== 'STATION' || sortedSteps.length === 0) return;
    if (focusedStepNo === null) {
      onFocusStep(sortedSteps[sortedSteps.length - 1].stepNo);
      return;
    }
    const idx = sortedSteps.findIndex((s) => s.stepNo === focusedStepNo);
    const prevIdx = idx < 0 ? sortedSteps.length - 1 : (idx - 1 + sortedSteps.length) % sortedSteps.length;
    onFocusStep(sortedSteps[prevIdx].stepNo);
  };

  const handleStepNext = () => {
    if (onStepNext) {
      onStepNext();
      return;
    }
    if (layer !== 'STATION' || sortedSteps.length === 0) return;
    if (focusedStepNo === null) {
      onFocusStep(sortedSteps[0].stepNo);
      return;
    }
    const idx = sortedSteps.findIndex((s) => s.stepNo === focusedStepNo);
    const nextIdx = idx < 0 ? 0 : (idx + 1) % sortedSteps.length;
    onFocusStep(sortedSteps[nextIdx].stepNo);
  };

  const handleSubmitPrompt = () => {
    const trimmed = promptRef.current.trim();
    if (!trimmed) return;
    onSubmitPrompt?.(trimmed);
    promptRef.current = '';
    setPromptText('');
  };

  return (
    <section className={`af5-ribbon ${step ? 'has-focused-step' : ''}`} aria-label="时序关键帧透镜">
      <div className="af5-ribbon-header">
        <div className="af5-ribbon-title-group">
          <span className="af5-lens-badge">工步时序</span>
          {layer === 'STATION' && onToggleWireLabels && (
            <button type="button" className="af5-btn af5-wire-label-toggle" aria-pressed={showWireLabels}
              onClick={onToggleWireLabels}>显示连线标签</button>
          )}
        </div>

        <div className="af5-ribbon-controls">
          <div className="af5-ai-prompt-box">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6366F1" strokeWidth="2" aria-hidden="true">
              <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" />
            </svg>
            <input
              type="text"
              className="af5-ai-prompt-input"
              aria-label="口述指令生成虚影连线"
              placeholder="口述指令生成虚影连线 (如: 增加NG抛料分支)..."
              value={promptText}
              onChange={(e) => {
                promptRef.current = e.target.value;
                setPromptText(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSubmitPrompt();
                }
              }}
            />
            <button
              type="button"
              className="af5-ai-prompt-submit"
              onClick={handleSubmitPrompt}
            >
              预览
            </button>
          </div>

          <div className="af5-playback-group">
            <button
              type="button"
              className="af5-playback-icon-btn"
              title="上一拍"
              aria-label="上一拍"
              onClick={handleStepPrev}
            >
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <path d="M10.3 3.2a.75.75 0 0 1 0 1.06L6.56 8l3.74 3.74a.75.75 0 1 1-1.06 1.06l-4.27-4.27a.75.75 0 0 1 0-1.06l4.27-4.27a.75.75 0 0 1 1.06 0Z" />
              </svg>
            </button>

            <button
              type="button"
              className="af5-playback-play-btn"
              onClick={onToggleAutoPlay}
            >
              {isAutoPlaying ? (
                <svg width="9" height="9" viewBox="0 0 12 12" fill="#DC2626" aria-hidden="true">
                  <rect x="2" y="2" width="8" height="8" rx="1.5" />
                </svg>
              ) : (
                <svg width="9" height="9" viewBox="0 0 12 12" fill="#059669" aria-hidden="true">
                  <path d="M3 2.2v7.6a.6.6 0 0 0 .92.5l6.1-3.8a.6.6 0 0 0 0-1l-6.1-3.8A.6.6 0 0 0 3 2.2Z" />
                </svg>
              )}
              <span>{isAutoPlaying ? '停止巡播' : '单拍巡播'}</span>
            </button>

            <button
              type="button"
              className="af5-playback-icon-btn"
              title="下一拍"
              aria-label="下一拍"
              onClick={handleStepNext}
            >
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <path d="M5.7 3.2a.75.75 0 0 0 0 1.06L9.44 8 5.7 11.74a.75.75 0 1 0 1.06 1.06l4.27-4.27a.75.75 0 0 0 0-1.06L6.76 3.2a.75.75 0 0 0-1.06 0Z" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <div className="af5-ribbon-track" data-ribbon-layer={layer}>
        {layer === 'PROJECT' || !station ? (
          <div className="af5-ribbon-subtitle">
            当前处于 L1 产线总图 · 双击任意工站进入 L2 后可使用「时序关键帧透镜」单拍拆解动作
          </div>
        ) : (
          <>
            <button
              type="button"
              data-step-filter="all"
              className={`af5-step-pill is-overview ${
                focusedStepNo === null ? 'is-active' : ''
              }`}
              onClick={() => onFocusStep(null)}
              aria-pressed={focusedStepNo === null}
            >
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <path d="M8 1.5 1.5 5 8 8.5 14.5 5 8 1.5ZM1.5 8.5 8 12l6.5-3.5M1.5 11.5 8 15l6.5-3.5" stroke="currentColor" strokeWidth="1.3" fill="none" />
              </svg>
              <span>{`全览 (${sortedSteps.length}拍)`}</span>
            </button>

            {sortedSteps.map((step, idx) => {
              const isCurrent = focusedStepNo === step.stepNo;
              return (
                <React.Fragment key={step.id}>
                  {idx > 0 && <span className="af5-step-arrow">→</span>}
                  <button
                    type="button"
                    data-step-no={step.stepNo}
                    className={`af5-step-pill ${isCurrent ? 'is-active' : ''}`}
                    onClick={() => onFocusStep(step.stepNo)}
                    aria-pressed={isCurrent}
                  >
                    <span className="af5-step-chip">{`S${step.stepNo}`}</span>
                    <span>{step.title}</span>
                  </button>
                </React.Fragment>
              );
            })}
          </>
        )}
      </div>
      {layer === 'STATION' && step && (
        <section className="af5-focused-step" aria-label={`S${step.stepNo} 工步详情`}>
          <header>
            <strong>{`S${step.stepNo} · ${step.title}`}</strong>
            {source && <span>来源 {source.title}</span>}
            {onEditStep && <button type="button" className="af5-btn" onClick={() => onEditStep(step.id)}>编辑工步</button>}
          </header>
          <ul>
            {step.invocations.map((invocation, index) => <li key={`${invocation.targetNodeId}:${index}`}>
              <span>{nodesById.get(invocation.targetNodeId)?.title ?? invocation.targetNodeId} · {invocation.actionLabel}</span>
              {invocation.waitPredicateScl && <span>等待 <code>{invocation.waitPredicateScl}</code></span>}
            </li>)}
          </ul>
        </section>
      )}
    </section>
  );
};
