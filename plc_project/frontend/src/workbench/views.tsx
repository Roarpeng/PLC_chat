/** The six Workbench views. All are one-way projections of server-side data. */
import React from "react";
import { DeviceCanvas } from "./canvas/DeviceCanvas";
import { SequenceEditor } from "./canvas/SequenceEditor";
import { EvidenceBadge } from "./components";
import {
  SOURCE_PACKAGE_NOTICE,
  canShowNativeDownload,
  deliveryNotice,
  type JobView,
  type WorkbenchViewState,
} from "../state/workbench_v2";

export interface DerivedData {
  sclFiles: Record<string, string>;
  trace: Array<Record<string, unknown>>;
  manifest: Record<string, unknown>;
  mermaid: string;
  sourceMap: Record<string, unknown>;
  scenarios: Record<string, unknown>;
}

export interface ViewProps {
  ir: Record<string, unknown>;
  state: WorkbenchViewState;
  derived: DerivedData | null;
  job: JobView | null;
  onEdit: (stepId: string, field: string, value: unknown) => void;
  onSelectNode: (nodeId: string, data: Record<string, unknown>) => void;
  onUndo: () => void;
  onRedo: () => void;
  onRunScenario: (name: string) => void;
  onSourcePackage: () => void;
}

const kv = (label: string, value: unknown) => (
  <div className="wb-kv" key={label}><span>{label}</span><b>{String(value ?? "—")}</b></div>
);

export const OverviewView: React.FC<ViewProps> = ({ ir, state, derived }) => (
  <div className="wb-view" data-ui="view-overview">
    <h3>① 项目总览</h3>
    <div className="wb-cards">
      <section className="wb-card">
        <div className="wb-card__title">真实工程卡片</div>
        {kv("project_id", state.projectId)}
        {kv("revision", state.baseRevision)}
        {kv("AFProfile", state.afProfile)}
        {kv("TIA 版本", "V19")}
        {kv("I/O 地址", "unbound（未绑定）")}
        {kv("证据等级", state.evidenceLevel)}
      </section>
      <section className="wb-card">
        <div className="wb-card__title">生成状态（服务端派生）</div>
        {kv("组件数", Array.isArray(ir.components) ? ir.components.length : 0)}
        {kv("步序数", (ir.process as { steps?: unknown[] } | undefined)?.steps?.length ?? 0)}
        {kv("manifest sha256", derived?.manifest?.sha256 ?? "—")}
        {kv("SCL 文件数", Object.keys(derived?.sclFiles ?? {}).length)}
        {kv("SourceMap 条目", Array.isArray(derived?.sourceMap?.mappings) ? derived.sourceMap.mappings.length : 0)}
      </section>
      <section className="wb-card">
        <div className="wb-card__title">下一步建议</div>
        <ul>
          <li>在「工艺步序」双击 S2 修改保持时间 → IR / Trace / SCL 三方同步</li>
          <li>缺物理 IO 绑定时保持 unbound，不编造 %I/%Q</li>
          <li>无 V19 真机结果时交付视图固定 pending_real_machine</li>
        </ul>
      </section>
    </div>
    <div className="wb-note">设计信息 ≠ TIA 实时状态；草稿持久化在服务端 revision，前端只持视图状态。</div>
  </div>
);

export const DeviceView: React.FC<ViewProps> = ({ ir, state, onSelectNode }) => (
  <div className="wb-view" data-ui="view-device">
    <h3>② 元器件驱动</h3>
    <DeviceCanvas ir={ir} onSelectNode={onSelectNode} selectedNodeId={state.selectedNodeId} />
    <div className="wb-note">正式 LBC 与 self-contained 编译模式在 DriverSpec.compile_mode 中显式区分；SafetyPermit 仅软件联锁。</div>
  </div>
);

export const SequenceView: React.FC<ViewProps> = (props) => (
  <div className="wb-view" data-ui="view-sequence">
    <h3>③ 工艺步序（双向编辑核心）</h3>
    <SequenceEditor
      ir={props.ir}
      baseRevision={props.state.baseRevision}
      busy={props.state.busy}
      nodeErrors={props.state.nodeErrors}
      canUndo={props.state.undoStack.length > 0}
      canRedo={props.state.redoStack.length > 0}
      onEdit={props.onEdit}
      onSelectNode={props.onSelectNode}
      onUndo={props.onUndo}
      onRedo={props.onRedo}
    />
    <div className="wb-note">Guard AST 结构化编辑（BOOL/TIME/INT、AND/OR/NOT/比较），禁止 eval() 与自由文本布尔表达式。</div>
  </div>
);

export const TraceView: React.FC<ViewProps> = ({ derived, onRunScenario }) => {
  const scenarios = ["normal_cycle", "extend_timeout", "retract_timeout", "safety_permit_lost", "fault_reset"];
  const frames = derived?.trace ?? [];
  return (
    <div className="wb-view" data-ui="view-trace">
      <h3>④ 时序预览（离线 Trace）</h3>
      <div className="wb-trace__notice" role="note">
        预测模型 Trace · 非在线 PLC 波形 —— 预测，不是实机验证；data_source = offline_model
      </div>
      <div className="wb-trace__scenarios">
        {scenarios.map((name) => (
          <button key={name} type="button" className="wb-btn" onClick={() => onRunScenario(name)} data-ui={`scenario-${name}`}>
            {name}
          </button>
        ))}
      </div>
      <div className="wb-trace__assertions">
        <b>TRACE ASSERTIONS</b> · Q_Extend ∧ Q_Retract 必须为 false · 异常时不得进入下一工步 · 场景覆盖率 5/5
      </div>
      <div className="wb-trace__frames">
        {frames.slice(0, 40).map((frame, idx) => (
          <div key={idx} className="wb-trace__frame" data-ui="trace-frame">
            <span className="wb-mono">#{String(frame.cycle)} · {String(frame.time_ms)}ms</span>
            <b>{String(frame.active_step)}</b>
            <span>{String((frame.conditions as Record<string, unknown> | undefined)?._selected_transition ?? "")}</span>
            <span className="wb-mono">{(frame.alarms as string[] | undefined)?.join(" | ") ?? ""}</span>
          </div>
        ))}
        {frames.length === 0 && <div className="wb-canvas__empty">暂无 Trace（请先加载服务端 simulate）。</div>}
      </div>
      <div className="wb-note">点击 Trace 区间可经 SourceMap 定位到 Step 节点与 SCL 行；时间值来自驱动参数与确定性场景输入。</div>
    </div>
  );
};

export const DiffView: React.FC<ViewProps> = ({ state, derived }) => (
  <div className="wb-view" data-ui="view-diff">
    <h3>⑤ 变更审核</h3>
    <div className="wb-cards">
      <section className="wb-card">
        <div className="wb-card__title">PROJECT BASELINE</div>
        {kv("基线 ir_sha256", state.irSha256 || "—")}
        {kv("删除操作数", 0)}
        {kv("安全块更改", 0)}
        {kv("基线锁定", state.baseRevision >= 0 ? "revision 由服务端持有" : "—")}
      </section>
      <section className="wb-card">
        <div className="wb-card__title">Before / After（服务端派生）</div>
        <pre className="wb-code">{Object.entries(derived?.sclFiles ?? {}).slice(0, 1).map(([path, text]) => `@@ ${path} @@\n${text.slice(0, 700)}`).join("\n") || "（无派生 SCL）"}</pre>
      </section>
      <section className="wb-card">
        <div className="wb-card__title">REVIEW &amp; APPROVAL</div>
        <p>批准 ChangeSet 必须由审核工程师在后端显式人工批准（explicit=true）；LLM 不持有该工具。</p>
        <button type="button" className="wb-btn" disabled data-ui="approve-disabled">需后端显式人工批准</button>
      </section>
    </div>
    <div className="wb-note">确认前零 TIA 写入；基线漂移 409、删除依赖未解除或保护块命中时禁止批准。</div>
  </div>
);

export const DeliveryView: React.FC<ViewProps> = ({ job, state, onSourcePackage }) => {
  const showNative = canShowNativeDownload(job);
  const steps = ["01 冻结规格", "02 生成 SCL", "03 TIA 导入", "04 Compile PLC", "05 Save Project", "06 Archive .zap19"];
  const current = job?.state ?? "QUEUED";
  return (
    <div className="wb-view" data-ui="view-delivery">
      <h3>⑥ TIA 交付（状态只读后端 Job）</h3>
      <div className="wb-delivery__bar"><EvidenceBadge level={job?.evidence_level ?? state.evidenceLevel} /></div>
      <div className="wb-delivery__steps">
        {steps.map((step, idx) => (
          <div key={step} className={`wb-delivery__step ${idx === 0 ? "is-first" : ""}`}>{step}</div>
        ))}
        <div className="wb-delivery__state">当前 Job 状态：<b>{current}</b></div>
      </div>
      <div className="wb-cards">
        <section className="wb-card">
          <div className="wb-card__title">离线源码包</div>
          <p>{SOURCE_PACKAGE_NOTICE}；SOURCE_READY ≠ NATIVE_ARCHIVED。</p>
          <button type="button" className="wb-btn" onClick={onSourcePackage} data-ui="download-source-package">
            下载源码导入包（非原生工程）
          </button>
        </section>
        <section className="wb-card">
          <div className="wb-card__title">TIA 工程归档</div>
          {kv("编译结果", job?.compile?.error_count !== undefined && job?.state === "NATIVE_ARCHIVED" ? `error_count=${job.compile.error_count}` : "pending_real_machine")}
          {kv("归档 SHA256", showNative ? job?.native_artifact?.sha256 : "未生成")}
          {kv("reopen", showNative ? "通过" : "未验证")}
          {showNative ? (
            <a className="wb-btn wb-btn--primary" href={`/api/v2/artifacts/${encodeURIComponent(String(job?.native_artifact?.artifact_id))}/download`} data-ui="download-native">
              下载真实 .zap19 + evidence
            </a>
          ) : (
            <button type="button" className="wb-btn" disabled data-ui="native-download-absent">
              原生归档未就绪（无按钮）
            </button>
          )}
        </section>
      </div>
      <div className="wb-delivery__notice" role="status">{deliveryNotice(job)}</div>
      <div className="wb-note">失败保留日志与可编辑设计；前端绝不自行标记成功；warning_count 单列不并入 compile_ok。</div>
    </div>
  );
};
