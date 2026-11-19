import type { ProjectCompoundStation, StationOperation, StationOrchestration } from '../../core/ir/afHyperGraph.types';
import {
  initialOrchestrationRun, isOrchestrationBound, orchestrationPhaseLabels,
  type OrchestrationEvent, type OrchestrationRun,
} from '../../core/ir/stationOrchestration';

interface Props {
  title: string;
  stationId: string;
  plan: StationOrchestration;
  sentDurationSeconds?: number;
  receivedDurationSeconds?: number;
  onSendJob: (stationId: string, durationSeconds: number) => void;
  stations: ProjectCompoundStation[];
  run?: OrchestrationRun;
  onChange: (plan: StationOrchestration) => void;
  onEvent: (event: OrchestrationEvent) => void;
}

const advance: Partial<Record<OrchestrationRun['phase'], [OrchestrationEvent, string]>> = {
  idle: ['start', '开始模拟'],
  ready: ['ready', '工位就绪'],
  running: ['done', '操作完成'],
  pause: ['paused', '已在允许位置暂停'],
  'change-ready': ['ready', '附件位就绪'],
  changing: ['done', '附件更换完成'],
  return: ['returned', '已返回原作业位置'],
  resume: ['resumed', '已恢复原工步'],
};

export function StationOrchestrationEditor({
  title, stationId, plan, stations, run, sentDurationSeconds, receivedDurationSeconds, onSendJob, onChange, onEvent,
}: Props) {
  const physicalStations = stations.filter((station) => station.kind !== 'LOGIC');
  const state = run ?? initialOrchestrationRun(plan);
  const next = advance[state.phase];
  const active = state.phase !== 'idle' && state.phase !== 'fault' && state.phase !== 'done';
  const step = plan.operations[state.operationIndex];
  const inAttachmentStation = state.phase === 'change-ready' || state.phase === 'changing';
  const currentOperation = inAttachmentStation ? plan.interrupt : step;
  const valid = isOrchestrationBound(plan, stations);
  const patchOperation = (index: number, patch: Partial<StationOperation>) => onChange({
    ...plan, operations: plan.operations.map((operation, at) => at === index ? { ...operation, ...patch } : operation),
  });
  const stationSelect = (value: string, onSelect: (stationId: string) => void) => (
    <select value={physicalStations.some(({ stationId }) => stationId === value) ? value : ''} onChange={(event) => onSelect(event.target.value)}>
      <option value="">待绑定工位</option>
      {physicalStations.map((station) => <option key={station.stationId} value={station.stationId}>{station.title}</option>)}
    </select>
  );
  const dispatch = plan.jobDispatch;
  if (dispatch) {
    const receivers = stations.filter((station) => station.kind === 'LOGIC' && station.stationId !== stationId);
    const duration = dispatch.durationSeconds;
    const validDuration = typeof duration === 'number' && Number.isFinite(duration) && duration > 0;
    const canSend = validDuration && receivers.some((receiver) => receiver.stationId === dispatch.stationId);
    return (
      <section className="af5-orchestration" aria-label="作业时间下发">
        <header><h2>{title}</h2></header>
        <fieldset>
          <legend>作业任务</legend>
          <label className="af5-station-field">
            接收工位
            <select value={dispatch.stationId} onChange={(event) => onChange({ ...plan, jobDispatch: { ...dispatch, stationId: event.target.value } })}>
              <option value="">选择接收工位</option>
              {receivers.map((receiver) => <option key={receiver.stationId} value={receiver.stationId}>{receiver.title}</option>)}
            </select>
          </label>
          <label className="af5-station-field">
            作业时间（秒）
            <input type="number" min="0" step="any" value={duration ?? ''} onChange={(event) => {
              const value = event.target.valueAsNumber;
              onChange({ ...plan, jobDispatch: { ...dispatch, durationSeconds: Number.isFinite(value) && value > 0 ? value : undefined } });
            }} />
          </label>
          <div className="af5-orchestration-actions">
            <button type="button" className="af5-btn af5-btn--primary" disabled={!canSend} onClick={() => {
              if (canSend) onSendJob(dispatch.stationId, duration);
            }}>模拟下发作业时间</button>
            <button type="button" className="af5-btn" onClick={() => onChange({ ...plan, jobDispatch: undefined })}>切换到工位编排</button>
          </div>
          {sentDurationSeconds !== undefined && <p role="status">最近模拟下发 {sentDurationSeconds} 秒</p>}
        </fieldset>
      </section>
    );
  }

  return (
    <section className="af5-orchestration" aria-label="虚拟工位编排">
      <header>
        <p>虚拟逻辑工位</p>
        <h2>{title}</h2>
      </header>
      {receivedDurationSeconds !== undefined && <p role="status">已接收作业时间 {receivedDurationSeconds} 秒</p>}
      {plan.operations.length === 0 && !plan.interrupt && receivedDurationSeconds === undefined &&
        <button type="button" className="af5-btn" onClick={() => onChange({ ...plan, jobDispatch: { stationId: '' } })}>配置作业时间下发</button>}
      <fieldset disabled={active}>
        <legend>跨工位作业顺序</legend>
        <label className="af5-station-field">
          初始末端工具
          <input value={plan.initialTool} onChange={(event) => onChange({ ...plan, initialTool: event.target.value })} placeholder="留空表示无工具" />
        </label>
        {plan.operations.map((operation, index) => (
          <div key={index} className="af5-orchestration-row" role="group" aria-label={`工步 ${index + 1}`}>
            <span>{index + 1}</span>
            <label className="af5-station-field">调用工位{stationSelect(operation.stationId, (stationId) => patchOperation(index, { stationId }))}</label>
            <label className="af5-station-field">操作请求<input value={operation.command} onChange={(event) => patchOperation(index, { command: event.target.value })} /></label>
            <label className="af5-station-field">
              完成后的工具
              <select value={operation.mountedToolAfter === undefined ? 'keep' : operation.mountedToolAfter === null ? 'empty' : 'set'}
                onChange={(event) => patchOperation(index, { mountedToolAfter: event.target.value === 'keep' ? undefined : event.target.value === 'empty' ? null : '' })}>
                <option value="keep">保持当前工具</option><option value="empty">卸下工具</option><option value="set">装上工具</option>
              </select>
              {typeof operation.mountedToolAfter === 'string' && <input aria-label="装上的工具" value={operation.mountedToolAfter}
                onChange={(event) => patchOperation(index, { mountedToolAfter: event.target.value })} />}
            </label>
            <label><input type="checkbox" checked={Boolean(operation.allowInterrupt)}
              onChange={(event) => patchOperation(index, { allowInterrupt: event.target.checked })} /> 可暂停换附件</label>
            <button className="af5-btn" type="button" aria-label={`删除工步 ${index + 1}`}
              onClick={() => onChange({ ...plan, operations: plan.operations.filter((_, at) => at !== index) })}>删除</button>
          </div>
        ))}
        <button className="af5-btn" type="button" onClick={() => onChange({ ...plan, operations: [...plan.operations, { stationId: '', command: '' }] })}>加工步</button>
      </fieldset>
      <fieldset disabled={active}>
        <legend>作业中断与续作</legend>
        <label><input type="checkbox" checked={Boolean(plan.interrupt)}
          onChange={(event) => onChange({ ...plan, interrupt: event.target.checked ? { stationId: '', command: '' } : undefined })} /> 启用附件更换请求</label>
        {plan.interrupt && <>
          <label className="af5-station-field">附件工位{stationSelect(plan.interrupt.stationId, (stationId) => onChange({ ...plan, interrupt: { stationId, command: plan.interrupt!.command } }))}</label>
          <label className="af5-station-field">更换请求<input value={plan.interrupt.command}
            onChange={(event) => onChange({ ...plan, interrupt: { stationId: plan.interrupt!.stationId, command: event.target.value } })} /></label>
        </>}
      </fieldset>
      <fieldset>
        <legend>离线握手模拟</legend>
        <p role="status">{orchestrationPhaseLabels[state.phase]} · 末端工具 {state.tool || '无'}{active && step ? ` · 工步 ${state.operationIndex + 1}` : ''}</p>
        {active && currentOperation && <p>当前请求：{physicalStations.find(({ stationId }) => stationId === currentOperation.stationId)?.title} · {currentOperation.command}</p>}
        <div className="af5-orchestration-actions">
          {next && <button className="af5-btn af5-btn--primary" type="button" disabled={!valid} onClick={() => onEvent(next[0])}>{next[1]}</button>}
          {active && plan.interrupt && <button className="af5-btn" type="button" onClick={() => onEvent(state.request ? 'request-off' : 'request-on')}>
            {state.request ? '撤销附件请求信号' : '置位附件请求信号'}
          </button>}
          {active && <button className="af5-btn" type="button" onClick={() => onEvent('fault')}>模拟工位故障</button>}
          {state.phase !== 'idle' && <button className="af5-btn" type="button" onClick={() => onEvent('reset')}>重置模拟</button>}
        </div>
        {!valid && <p>绑定全部操作的工位和请求名称后，可开始模拟。</p>}
      </fieldset>
    </section>
  );
}
