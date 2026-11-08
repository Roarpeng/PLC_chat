/**
 * 工程视角 · 默认折叠的右侧 420px 覆盖式抽屉。
 *
 * 6 组：① 契约与门禁 ② 还原度与编译 ③ 三动作 A·B·C ④ 差异清单逐项勾选
 *       ⑤ SCL 只读预览 ⑥ 真机状态
 * 折叠 / 展开是纯前端视图位（WizardState），不触发、不跳过、不替代任何后端调用。
 * 所有字段值来自 /state 与真实响应，不删信息、不伪装、不 mock。
 */
import React from "react";
import type {
  GFActionAvailability,
  GFActionCompileDiagnostics,
  GFActionKind,
  GFActionResult,
  GFBlocker,
  GFCompileDiagnostics,
  GFDeliverySummary,
  GFFidelityStatus,
  GFReverseProtection,
  GFSpecDiff,
  GFState,
  GFWhitelist,
} from "../state/greenfield";
import { GreenfieldChatFeed } from "./GreenfieldChatFeed";
import { GreenfieldGateBar } from "./GreenfieldGateBar";
import { DeliveryReview, type DeliverySection } from "./engineering/DeliveryReview";
import { NodeEditor } from "./engineering/NodeEditor";
import type { EngGroupKey } from "./steps/stepMachine";

export interface EngineeringViewData {
  state: GFState;
  whitelist: GFWhitelist | null;
  diff: GFSpecDiff | null;
  fidelity: GFFidelityStatus | null;
  compileDiagnostics: GFCompileDiagnostics | null;
  reverseProtection: GFReverseProtection | null;
  sclSources: Record<string, string> | null;
  pendingRealMachine: boolean;
  pendingLabel: string;
  actionResults: Partial<Record<GFActionKind, GFActionResult | null>>;
  actionLoading: GFActionKind | null;
  actionError: string;
  actionErrorCode: string;
  actionAvailability: Record<GFActionKind, GFActionAvailability>;
  actionCompileDiagnostics: GFActionCompileDiagnostics | null;
  diffChecked: Record<string, boolean>;
  checklistComplete: boolean;
  explicitConfirmed: boolean;
  writeBlockers: GFBlocker[];
  blockers: GFBlocker[];
  summary: Record<string, unknown> | null;
  confirmErrorCode: string;
  confirmErrorMessage: string;
  backendConfirmReason: string;
  actionFeedback: string;
  diffError: string;
  projectId: string;
  constraintNote: string;
  busy: boolean;
}

export interface EngineeringActions {
  onBack: () => void;
  onShowSummary: () => Promise<Record<string, unknown>>;
  onConfirm: () => void;
  onBeginEdit: () => void;
  onExportMermaid: () => void;
  onExportDraft: () => void;
  onImportDraft: (payload: unknown) => void;
  onGenerateProject: () => void;
  onDeliverTia: (mode: "auto" | "package") => void;
  onLoadReference: () => void;
  onGenerateDraft: () => void;
  onValidate: () => void;
  onRunActionA: () => void;
  onRunActionB: () => void;
  onRunActionC: () => void;
  onToggleDiffItem: (key: string, checked: boolean) => void;
  onConfirmDiff: (confirmed: boolean) => void;
  onRefreshDiff: () => void;
  onSendChat: (text: string) => void;
  onSendFiles: (files: File[]) => void;
  onSendPastedScl: (text: string) => void;
  onConfirmReceipt: () => void;
  onUploadFiles: (files: FileList | null) => void;
  onBindVar: (varKey: string, targetId: string, role: string) => void;
  onUnbindVar: (varKey: string, targetId?: string) => void;
  onPatchNodes: (ops: import("../state/greenfield").GFCanvasOp[]) => void;
}

export interface EngineeringDrawerProps {
  open: boolean;
  groups: Record<EngGroupKey, boolean>;
  onToggle: () => void;
  onToggleGroup: (key: EngGroupKey) => void;
  data: EngineeringViewData;
  actions: EngineeringActions;
}

interface GroupDef {
  key: EngGroupKey;
  no: string;
  title: string;
  hint: string;
}

const GROUPS: readonly GroupDef[] = [
  { key: "contract", no: "①", title: "契约与门禁", hint: "阶段、规格、五项前置、导入导出与确认" },
  { key: "fidelity", no: "②", title: "还原度与编译", hint: "fidelity_ok · compile_diagnostics" },
  { key: "actions", no: "③", title: "三动作 A·B·C", hint: "A 导出 / B 首次写入 / C 增量回写" },
  { key: "diff", no: "④", title: "差异清单逐项勾选", hint: "D11 显式确认前零副作用" },
  { key: "scl", no: "⑤", title: "SCL 只读预览", hint: "F13 降级：只读、无写回入口" },
  { key: "machine", no: "⑥", title: "真机状态", hint: "pending_real_machine 事实陈述" },
];

function scalar(value: unknown): string {
  if (value === null || value === undefined) return "—（后端未提供）";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number" || typeof value === "string") return String(value);
  if (Array.isArray(value)) return `${value.length} 项`;
  if (typeof value === "object") return `结构化明细（${Object.keys(value as object).length} 个字段）`;
  return String(value);
}

function summaryEntries(summary: Record<string, unknown> | null): Array<[string, string]> {
  if (!summary) return [];
  return Object.entries(summary).map(([key, value]) => [key, scalar(value)]);
}

export const EngineeringDrawer: React.FC<EngineeringDrawerProps> = ({
  open,
  groups,
  onToggle,
  onToggleGroup,
  data,
  actions,
}) => {
  const { state } = data;
  const latestSpec = state.specs[state.specs.length - 1];
  const delivery: GFDeliverySummary | null = state.delivery_summary ?? null;

  const commonDeliveryProps = {
    diff: data.diff,
    fidelity: data.fidelity,
    reverseProtection: data.reverseProtection,
    compileDiagnostics: data.compileDiagnostics,
    diffConfirmed: data.explicitConfirmed,
    onConfirmDiff: actions.onConfirmDiff,
    onRefreshDiff: actions.onRefreshDiff,
    busy: data.busy,
    pendingRealMachine: data.pendingRealMachine,
    sclSources: data.sclSources,
    actionAvailability: data.actionAvailability,
    actionResults: data.actionResults,
    actionLoading: data.actionLoading,
    actionError: data.actionError,
    actionErrorCode: data.actionErrorCode,
    onRunActionA: actions.onRunActionA,
    onRunActionB: actions.onRunActionB,
    onRunActionC: actions.onRunActionC,
    actionCompileDiagnostics: data.actionCompileDiagnostics,
    diffChecked: data.diffChecked,
    onToggleDiffItem: actions.onToggleDiffItem,
    checklistComplete: data.checklistComplete,
    explicitConfirmed: data.explicitConfirmed,
  };

  const renderContract = (): React.ReactNode => (
    <>
      <GreenfieldGateBar
        state={state}
        onBack={actions.onBack}
        projectId={data.projectId}
        confirmErrorCode={data.confirmErrorCode}
        confirmErrorMessage={data.confirmErrorMessage}
        writeBlockers={data.writeBlockers}
        pendingRealMachine={data.pendingRealMachine}
        diffConfirmed={data.explicitConfirmed}
        actionResults={data.actionResults}
        onShowSummary={actions.onShowSummary}
        onConfirm={actions.onConfirm}
        onBeginEdit={actions.onBeginEdit}
        onExportMermaid={actions.onExportMermaid}
        onExportDraft={actions.onExportDraft}
        onImportDraft={actions.onImportDraft}
        onGenerateProject={actions.onGenerateProject}
        onDeliverTia={actions.onDeliverTia}
        onLoadReference={actions.onLoadReference}
      />

      <div className="gf-eng__subhead">契约字段（值与 /state 一致）</div>
      <dl className="gf-eng__kv" data-ui="engineering-contract-fields">
        <dt>project_id</dt>
        <dd className="gf-eng__code">{state.project_id || data.projectId || "—"}</dd>
        <dt>阶段 / 阶段标签</dt>
        <dd>{state.stage} · {state.stage_label}</dd>
        <dt>spec_hash</dt>
        <dd className="gf-eng__code">{latestSpec?.spec_hash || "—（尚未冻结）"}</dd>
        <dt>框架基线</dt>
        <dd>{state.framework_baseline_version || "—"}</dd>
        <dt>step_order</dt>
        <dd>{state.ir_only_fields?.length ? `${state.ir_only_fields.length} 条附加字段` : "—（本阶段未单独返回）"}</dd>
        <dt>PCEC</dt>
        <dd>{state.counters ? `${Object.keys(state.counters).length} 组计数` : "—"}</dd>
        <dt>compile_diagnostics</dt>
        <dd>{data.compileDiagnostics ? `已返回 · ${data.compileDiagnostics.phase}` : "—（后端未提供，诚实降级）"}</dd>
        <dt>pending_real_machine</dt>
        <dd>{String(data.pendingRealMachine)}</dd>
        <dt>fidelity_ok</dt>
        <dd>{data.fidelity?.fidelity_ok === undefined ? "null（本轮不判定）" : String(data.fidelity.fidelity_ok)}</dd>
        <dt>D7 / D10 / D11 / N9</dt>
        <dd>门禁口径原样保留；逐项判定见下方清单</dd>
        <dt>A·B·C</dt>
        <dd>
          A {data.actionResults?.A ? "已执行" : "未执行"} · B {data.actionResults?.B ? "已执行" : "未执行"} · C {data.actionResults?.C ? "已执行" : "未执行"}
        </dd>
        <dt>spec_version</dt>
        <dd>{latestSpec ? `v${latestSpec.spec_version}` : "—（草稿）"}</dd>
        <dt>工程包</dt>
        <dd>{delivery ? delivery.zip_filename : "—（尚未生成）"}</dd>
      </dl>

      <div className="gf-eng__subhead">确认门禁逐项清单（{data.blockers.length} 项）</div>
      {data.blockers.length === 0 ? (
        <div className="gf-ok">五项前置全部满足，可确认。</div>
      ) : (
        <ul className="gf-eng__list">
          {data.blockers.map((item: GFBlocker, index: number) => (
            <li key={`${item.code}-${index}`}>
              <span className="gf-eng__code">{item.code}</span> · {item.reason}
            </li>
          ))}
        </ul>
      )}
      {data.writeBlockers.length > 0 && (
        <>
          <div className="gf-eng__subhead">后续写入锁定原因</div>
          <ul className="gf-eng__list">
            {data.writeBlockers.map((item: GFBlocker, index: number) => (
              <li key={`write-${item.code}-${index}`}>
                <span className="gf-eng__code">{item.code}</span> · {item.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.backendConfirmReason && (
        <div className="gf-eng__error" role="alert">
          后端确认返回：{data.backendConfirmReason}
        </div>
      )}

      <div className="gf-eng__subhead">工程视角摘要（结构化，非原始报文）</div>
      {summaryEntries(data.summary).length === 0 ? (
        <div className="gf-muted">尚未拉取工程视角摘要；进入确认步时会自动拉取。</div>
      ) : (
        <ul className="gf-eng__list">
          {summaryEntries(data.summary).map(([key, value]) => (
            <li key={key}>
              <span className="gf-eng__code">{key}</span> · {value}
            </li>
          ))}
        </ul>
      )}

      <div className="gf-eng__subhead">辅助动作</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="gf-btn gf-btn--xs gf-btn--ghost" onClick={actions.onValidate}>
          重新校验结构
        </button>
        <button type="button" className="gf-btn gf-btn--xs gf-btn--ghost" onClick={actions.onGenerateDraft}>
          按当前描述重建草稿
        </button>
        <label className="gf-btn gf-btn--xs gf-btn--ghost">
          上传辅助资料
          <input
            type="file"
            multiple
            hidden
            accept=".pdf,.xlsx,.xlsm,.csv,.scl,.txt,.db"
            onChange={(event) => actions.onUploadFiles(event.target.files)}
          />
        </label>
      </div>

      <details>
        <summary>结构节点（增删改 / 重命名 / 重挂 / 改标签）</summary>
        <NodeEditor ir={state.ir} busy={data.busy} onPatch={actions.onPatchNodes} />
      </details>

      <details>
        <summary>对话记录与增量修改</summary>
        <div className="gf-eng-drawer-chat">
          <GreenfieldChatFeed
            state={state}
            busy={data.busy}
            projectId={data.projectId}
            constraintNote={data.constraintNote}
            onSend={actions.onSendChat}
            onSendFiles={actions.onSendFiles}
            onSendPastedScl={actions.onSendPastedScl}
            onConfirmReceipt={actions.onConfirmReceipt}
          />
        </div>
      </details>

      {data.diffError && <div className="gf-eng__feedback">{data.diffError}</div>}
      {data.actionFeedback && <div className="gf-eng__feedback">{data.actionFeedback}</div>}
    </>
  );

  const renderFidelity = (): React.ReactNode => (
    <DeliveryReview
      {...commonDeliveryProps}
      visibleSections={["fidelity", "compile"] satisfies ReadonlyArray<DeliverySection>}
    />
  );

  const renderActions = (): React.ReactNode => (
    <DeliveryReview
      {...commonDeliveryProps}
      visibleSections={["triad", "steps"] satisfies ReadonlyArray<DeliverySection>}
    />
  );

  const renderDiff = (): React.ReactNode => (
    <DeliveryReview
      {...commonDeliveryProps}
      visibleSections={["diff"] satisfies ReadonlyArray<DeliverySection>}
    />
  );

  const renderScl = (): React.ReactNode => (
    <DeliveryReview
      {...commonDeliveryProps}
      visibleSections={["scl"] satisfies ReadonlyArray<DeliverySection>}
    />
  );

  const renderMachine = (): React.ReactNode => (
    <>
      <DeliveryReview
        {...commonDeliveryProps}
        visibleSections={["pending"] satisfies ReadonlyArray<DeliverySection>}
      />
      <div className="gf-eng__subhead">真机状态</div>
      <dl className="gf-eng__kv">
        <dt>pending_real_machine</dt>
        <dd>{String(data.pendingRealMachine)}</dd>
        <dt>说明</dt>
        <dd>{data.pendingLabel}</dd>
        <dt>反向保护</dt>
        <dd>
          {data.reverseProtection
            ? `allowed=${String(data.reverseProtection.allowed)} · drift=${data.reverseProtection.tia_side_drift}`
            : "—（后端未提供）"}
        </dd>
        <dt>差异清单显式确认</dt>
        <dd>{data.explicitConfirmed ? "已确认" : "未确认（D11：确认前零副作用）"}</dd>
      </dl>
      <button
        type="button"
        className="gf-btn gf-btn--xs gf-btn--danger"
        disabled={data.busy || data.writeBlockers.length > 0}
        title={data.writeBlockers.length > 0 ? data.writeBlockers.map((b) => b.reason).join("；") : "发起真机交付"}
        onClick={() => actions.onDeliverTia("auto")}
      >
        写入博途（真机）
      </button>
      {data.writeBlockers.length > 0 && (
        <ul className="gf-eng__list">
          {data.writeBlockers.map((item: GFBlocker, index: number) => (
            <li key={`machine-${item.code}-${index}`}>{item.reason}</li>
          ))}
        </ul>
      )}
    </>
  );

  const BODIES: Record<EngGroupKey, () => React.ReactNode> = {
    contract: renderContract,
    fidelity: renderFidelity,
    actions: renderActions,
    diff: renderDiff,
    scl: renderScl,
    machine: renderMachine,
  };

  return (
    <aside
      className={open ? "gf-eng-drawer gf-eng-drawer--open" : "gf-eng-drawer"}
      data-ui="engineering-drawer"
      aria-hidden={!open}
      aria-label="工程视角"
    >
      {/* 折叠态不渲染任何内容：主链首屏 DOM 中零契约术语泄露（ac-1 严格口径）。 */}
      {open && (
        <>
          <div className="gf-eng__header">
            <span className="gf-eng__header-title">工程视角</span>
            <span className="gf-eng__header-spacer" />
            <button type="button" className="gf-btn gf-btn--xs gf-btn--ghost" onClick={onToggle}>
              收起
            </button>
          </div>
          <div className="gf-eng__body">
            <p className="gf-muted" style={{ marginTop: 0 }}>
              审计与集成口径集中在此；展开或收起不会发起请求，也不会改变任何写入门禁。
            </p>
            {GROUPS.map((group) => (
              <section className="gf-eng-group" data-group={group.key} key={group.key}>
                <button
                  type="button"
                  className="gf-eng-group__head"
                  aria-expanded={!!groups[group.key]}
                  onClick={() => onToggleGroup(group.key)}
                >
                  <span className="gf-eng-group__no">{group.no}</span>
                  <span>{group.title}</span>
                  <span className="gf-eng-group__chevron">{groups[group.key] ? "－" : "＋"}</span>
                </button>
                {groups[group.key] && (
                  <div className="gf-eng-group__body">
                    <div className="gf-muted" style={{ marginBottom: 10 }}>{group.hint}</div>
                    {BODIES[group.key]()}
                  </div>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </aside>
  );
};
