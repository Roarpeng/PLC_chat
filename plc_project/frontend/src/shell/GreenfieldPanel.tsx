/**
 * 新建工程画布左/中主区（Agent D · 前端批次）：
 * - 上半区：设备交互拓扑（逻辑级占位，可收起/可撤销）
 * - 下半区：对话生成 Mermaid 逻辑 + 四视图 + 「交付结果与差异确认」区
 *
 * 展示层业务语言（P1-G / Q6）：统一「工站 / 执行单元 / 执行件 / 设备交互」；
 * `Unit / EM / CM` 只允许出现在「工程视角」开关打开时的层级视图徽标里。
 * **禁止改 IR 语义**：节点编辑一律走契约 §3 `POST /patch` 的 op，前端只组装 ops。
 *
 * 交付结果区（F20 / D11 / D10 / N9 / P1-I / DEP-08）：
 * - SpecDiff 三清单（带 source_id）+ 显式勾选确认；
 * - reverse_protection 阻止提示；
 * - fidelity 状态（绝不显示成「编译通过」）；
 * - 结构化编译诊断（error_count / warnings 单列 / 块清单）+ 状态反馈；
 * - F13 降级：纯文本 SCL 只读预览 + 关键字高亮，无任何写回 TIA 的编辑入口。
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { highlightSclLines } from "../canvas/sclHighlight";
import {
  GF_ACTION_B_STEPS,
  GF_ACTION_C_STEPS,
  GF_COMPILE_STEPS,
  actionStepStatus,
  compileStepStatus,
  diffItemKey,
  formatCompileVerdict,
  formatFidelityLabel,
  pendingRealMachineLabel,
  type GFActionAvailability,
  type GFActionCompileDiagnostics,
  type GFActionKind,
  type GFActionResult,
  type GFCanvasOp,
  type GFCompileDiagnostics,
  type GFEdge,
  type GFFidelityStatus,
  type GFHardwareTopology,
  type GFHwNode,
  type GFNodeKind,
  type GFReverseProtection,
  type GFSpecDiff,
  type GFSourceBlock,
  type GFStepNode,
  type GFViews,
} from "../state/greenfield";

export interface GreenfieldPanelProps {
  views: GFViews | null;
  ir: Record<string, unknown> | null;
  hardware: GFHardwareTopology | null;
  legalKinds: string[];
  prompt: string;
  busy: boolean;
  selectedHwNodeId: string | null;
  selectedTargetId: string;
  onSelectHwNode: (hwNodeId: string | null) => void;
  onSelectTarget: (targetId: string) => void;
  onPromptChange: (value: string) => void;
  onGenerateDraft: () => void;
  onMountCm: (cmId: string, hwNodeId: string) => void;
  onUnmountCm: (cmId: string) => void;
  onRemoveHwNode: (hwNodeId: string) => void;
  onResetTopology: () => void;
  onEditStepField: (stepId: string, field: string, value: unknown) => void;
  onConnect: (kind: string, connection: Connection) => void;
  onRemoveEdge: (edgeId: string) => void;

  /* —— 本批次新增 —— */
  projectId?: string;
  diff?: GFSpecDiff | null;
  fidelity?: GFFidelityStatus | null;
  reverseProtection?: GFReverseProtection | null;
  compileDiagnostics?: GFCompileDiagnostics | null;
  diffConfirmed?: boolean;
  onConfirmDiff?: (confirmed: boolean) => void;
  onRefreshDiff?: () => void;
  onPatchNodes?: (ops: GFCanvasOp[]) => void;
  actionFeedback?: string;
  pendingRealMachine?: boolean;
  sclSources?: Record<string, string> | null;

  /* —— F20 三动作（Action A·B·C）—— */
  actionAvailability?: Record<GFActionKind, GFActionAvailability>;
  actionResults?: Partial<Record<GFActionKind, GFActionResult | null>>;
  actionLoading?: GFActionKind | null;
  actionError?: string;
  actionErrorCode?: string;
  onRunActionA?: () => void;
  onRunActionB?: () => void;
  onRunActionC?: () => void;
  actionCompileDiagnostics?: GFActionCompileDiagnostics | null;
  /** 差异清单逐项勾选状态（key = `${分组}:${source_id}`）。 */
  diffChecked?: Record<string, boolean>;
  onToggleDiffItem?: (key: string, checked: boolean) => void;
  /** 逐项勾选是否齐全（D11 显式确认前置）。 */
  checklistComplete?: boolean;
  /** D11：逐项勾选齐全 ∧ 显式确认标志。 */
  explicitConfirmed?: boolean;
}

type ViewTab = "step_flow" | "flow" | "seq" | "state" | "delivery";

const TABS: Array<{ key: ViewTab; label: string }> = [
  { key: "step_flow", label: "步序流程图 (Mermaid)" },
  { key: "flow", label: "工程视角 · 层级与设备交互连线" },
  { key: "seq", label: "时序与异常联动" },
  { key: "state", label: "PackML 模式与状态机" },
  { key: "delivery", label: "交付结果与差异确认" },
];

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

/** 业务语言徽标；engineeringView=true 时才出现 AF 术语（仅工程视角面板）。 */
const BUSINESS_TAG: Record<string, { business: string; af: string }> = {
  UN: { business: "工站", af: "Unit" },
  EM: { business: "执行单元", af: "EM" },
  CM: { business: "执行件", af: "CM" },
  CN: { business: "控制节点", af: "ControlNode" },
  ST: { business: "步序", af: "Step" },
  SF: { business: "安全", af: "Safety" },
};

function buildNodes(ir: Record<string, unknown> | null, engineeringView: boolean): Node[] {
  if (!ir) return [];
  const groups: Array<[string, Array<Record<string, unknown>>, number]> = [
    ["UN", asArray(ir.units), 20],
    ["EM", asArray(ir.ems), 130],
    ["CM", asArray(ir.cms), 250],
    ["CN", asArray(ir.control_nodes), 370],
    ["ST", asArray(ir.steps), 490],
    ["SF", asArray(ir.safety), 610],
  ];
  const nodes: Node[] = [];
  for (const [tag, items, y] of groups) {
    items.forEach((item, index) => {
      const id = String(item.id ?? `${tag}_${index}`);
      const label = String(item.business_label ?? item.name ?? item.symbol ?? id);
      const meta = BUSINESS_TAG[tag] ?? { business: tag, af: tag };
      const badge = engineeringView ? meta.af : meta.business;
      nodes.push({
        id,
        position: { x: 30 + index * 200, y },
        data: { label: `[${badge}] ${label}` },
        style: {
          borderRadius: 0,
          border: "2px solid #141414",
          background: tag === "CM" ? "#e6dccd" : "#f6f7fb",
          color: "#141414",
          padding: "6px 10px",
          fontSize: 12,
          fontFamily: "'Albert Sans', 'Segoe UI', sans-serif",
        },
      });
    });
  }
  return nodes;
}

function buildEdges(ir: Record<string, unknown> | null): Edge[] {
  if (!ir) return [];
  return asArray(ir.edges).map((edge) => ({
    id: String(edge.id),
    source: String(edge.src_id),
    target: String(edge.dst_id),
    label: `${String(edge.kind)}${edge.origin === "manual" ? " · 手动连线" : ""}`,
    style: {
      stroke: edge.origin === "manual" ? "#0f5257" : "#7b8095",
      strokeWidth: edge.origin === "manual" ? 2 : 1.5,
    },
  }));
}

const BUS_BADGE_MAP: Record<string, { label: string; cls: string }> = {
  Backplane: { label: "S7-1500 背板总线", cls: "gf-bus-badge gf-bus-badge--backplane" },
  Profinet: { label: "PROFINET IO 实时总线", cls: "gf-bus-badge gf-bus-badge--profinet" },
  TCP_IP: { label: "Industrial Ethernet / TCP", cls: "gf-bus-badge gf-bus-badge--tcp" },
};

/* ==========================================================================
 * NodeEditor（导出给 GreenfieldLinkPanel 复用）：工站 / 执行单元 / 执行件
 * 增删改 + 重命名 + 重挂 + 改标签，全部走 `POST /patch` 的 op（原子拒绝时
 * 由 gfRequest 把 422 映射为中文，整批回滚、画布不变）。
 * ========================================================================== */
export interface NodeEditorProps {
  ir: Record<string, unknown> | null;
  busy?: boolean;
  onPatch: (ops: GFCanvasOp[]) => void;
}

const NODE_KIND_LABEL: Record<GFNodeKind, string> = {
  unit: "工站",
  em: "执行单元",
  cm: "执行件",
};

interface NodeRowProps {
  id: string;
  kind: GFNodeKind;
  name: string;
  label: string;
  parentId: string;
  parents: Array<{ id: string; label: string }>;
  busy?: boolean;
  onPatch: (ops: GFCanvasOp[]) => void;
}

const NodeRow: React.FC<NodeRowProps> = ({
  id,
  kind,
  name,
  label,
  parentId,
  parents,
  busy,
  onPatch,
}) => {
  const [draftName, setDraftName] = useState(name);
  const [draftLabel, setDraftLabel] = useState(label);
  const [draftParent, setDraftParent] = useState(parentId);

  useEffect(() => {
    setDraftName(name);
    setDraftLabel(label);
    setDraftParent(parentId);
  }, [id, name, label, parentId]);

  const changed =
    draftName !== name || draftLabel !== label || (parents.length > 0 && draftParent !== parentId);

  return (
    <div className="gf-node-row" data-node-id={id}>
      <div className="gf-node-row__head">
        <span className="gf-node-kind">{NODE_KIND_LABEL[kind]}</span>
        <code className="gf-node-id">{id}</code>
        <span className="gf-muted">业务标签与名称可直接改写</span>
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--ghost gf-node-row__del"
          disabled={busy}
          title={`删除该${NODE_KIND_LABEL[kind]}（走 /patch remove_node）`}
          onClick={() => onPatch([{ op: "remove_node", node_id: id }])}
        >
          删除
        </button>
      </div>
      <div className="gf-node-row__fields">
        <label className="gf-node-field">
          <span>业务标签</span>
          <input
            type="text"
            value={draftLabel}
            disabled={busy}
            onChange={(e) => setDraftLabel(e.target.value)}
          />
        </label>
        <label className="gf-node-field">
          <span>名称</span>
          <input
            type="text"
            value={draftName}
            disabled={busy}
            onChange={(e) => setDraftName(e.target.value)}
          />
        </label>
        {parents.length > 0 && (
          <label className="gf-node-field">
            <span>重挂到</span>
            <select
              value={draftParent}
              disabled={busy}
              onChange={(e) => setDraftParent(e.target.value)}
            >
              {parents.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--primary"
          disabled={busy || !changed || !draftLabel.trim()}
          title="按差异组装 rename_node / relabel_node / reparent_node 三个 op，一次原子提交"
          onClick={() => {
            const ops: GFCanvasOp[] = [];
            if (draftLabel !== label) {
              ops.push({ op: "relabel_node", node_id: id, label: draftLabel.trim() });
            }
            if (draftName !== name) {
              ops.push({ op: "rename_node", node_id: id, name: draftName.trim() });
            }
            if (parents.length > 0 && draftParent !== parentId) {
              ops.push({ op: "reparent_node", node_id: id, parent_id: draftParent });
            }
            if (ops.length > 0) onPatch(ops);
          }}
        >
          保存变更
        </button>
      </div>
    </div>
  );
};

export const NodeEditor: React.FC<NodeEditorProps> = ({ ir, busy, onPatch }) => {
  const units = useMemo(() => asArray(ir?.units), [ir]);
  const ems = useMemo(() => asArray(ir?.ems), [ir]);
  const cms = useMemo(() => asArray(ir?.cms), [ir]);

  const unitOptions = units.map((u) => ({
    id: str(u.id),
    label: str(u.business_label) || str(u.name) || str(u.id),
  }));
  const emOptions = ems.map((e) => ({
    id: str(e.id),
    label: str(e.business_label) || str(e.name) || str(e.id),
  }));

  const [addKind, setAddKind] = useState<GFNodeKind>("unit");
  const [addLabel, setAddLabel] = useState("");
  const [addName, setAddName] = useState("");
  const [addParent, setAddParent] = useState("");

  const parentOptions = addKind === "em" ? unitOptions : addKind === "cm" ? emOptions : [];

  const canAdd =
    !busy &&
    addLabel.trim().length > 0 &&
    (addKind === "unit" || addParent.length > 0);

  const submitAdd = () => {
    if (!canAdd) return;
    const label = addLabel.trim();
    const name = addName.trim() || label;
    let ops: GFCanvasOp[] = [];
    // ops 字段以服务端 IRPatch.from_dict / _apply_node_op 为准：
    // add_* 负载放 node，父节点用 parent_id，标签用 business_label（写进 node）。
    if (addKind === "unit") {
      ops = [{ op: "add_unit", node: { name, business_label: label } }];
    } else if (addKind === "em") {
      ops = [{ op: "add_em", parent_id: addParent, node: { name, business_label: label } }];
    } else {
      ops = [{ op: "add_cm", parent_id: addParent, node: { business_label: label } }];
    }
    onPatch(ops);
    setAddLabel("");
    setAddName("");
  };

  return (
    <div className="gf-node-editor" data-ui="greenfield-node-editor">
      <div className="gf-node-editor__hint">
        节点增删改 / 重命名 / 重挂 / 改标签均走 <code>POST /patch</code> 的原子 op；
        提交后由服务端重投影并刷新四视图（步序流程图 · 层级 · 时序 · 状态机），变更事件入账。
      </div>

      <div className="gf-node-add">
        <span className="gf-muted">新增：</span>
        <select
          value={addKind}
          disabled={busy}
          onChange={(e) => {
            setAddKind(e.target.value as GFNodeKind);
            setAddParent("");
          }}
        >
          <option value="unit">工站</option>
          <option value="em">执行单元</option>
          <option value="cm">执行件</option>
        </select>
        <input
          type="text"
          placeholder="业务标签（如：夹紧工位）"
          value={addLabel}
          disabled={busy}
          onChange={(e) => setAddLabel(e.target.value)}
        />
        <input
          type="text"
          placeholder="名称（可选）"
          value={addName}
          disabled={busy}
          onChange={(e) => setAddName(e.target.value)}
        />
        {parentOptions.length > 0 && (
          <select
            value={addParent}
            disabled={busy}
            onChange={(e) => setAddParent(e.target.value)}
          >
            <option value="">选择所属{addKind === "em" ? "工站" : "执行单元"}</option>
            {parentOptions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--primary"
          disabled={!canAdd}
          onClick={submitAdd}
        >
          + 新增{NODE_KIND_LABEL[addKind]}
        </button>
      </div>

      <div className="gf-node-list">
        {units.length === 0 && ems.length === 0 && cms.length === 0 && (
          <div className="gf-muted gf-node-empty">
            当前画布还没有结构节点。可先在对话中描述工艺生成首版，或直接用上方「新增」建立工站。
          </div>
        )}
        {units.map((u) => (
          <NodeRow
            key={str(u.id)}
            id={str(u.id)}
            kind="unit"
            name={str(u.name)}
            label={str(u.business_label) || str(u.name)}
            parentId=""
            parents={[]}
            busy={busy}
            onPatch={onPatch}
          />
        ))}
        {ems.map((e) => (
          <NodeRow
            key={str(e.id)}
            id={str(e.id)}
            kind="em"
            name={str(e.name)}
            label={str(e.business_label) || str(e.name)}
            parentId={str(e.unit_id)}
            parents={unitOptions}
            busy={busy}
            onPatch={onPatch}
          />
        ))}
        {cms.map((c) => (
          <NodeRow
            key={str(c.id)}
            id={str(c.id)}
            kind="cm"
            name={str(c.id)}
            label={str(c.business_label) || str(c.id)}
            parentId={str(c.em_id)}
            parents={emOptions}
            busy={busy}
            onPatch={onPatch}
          />
        ))}
      </div>
    </div>
  );
};

/* ==========================================================================
 * 交付结果区：差异清单（D11）+ 反向保护（D10）+ fidelity（N9）+
 * 编译诊断（P1-I）+ F13 只读 SCL 预览（DEP-08）
 * ========================================================================== */
interface DeliveryReviewProps {
  diff?: GFSpecDiff | null;
  fidelity?: GFFidelityStatus | null;
  reverseProtection?: GFReverseProtection | null;
  compileDiagnostics?: GFCompileDiagnostics | null;
  diffConfirmed?: boolean;
  onConfirmDiff?: (confirmed: boolean) => void;
  onRefreshDiff?: () => void;
  busy?: boolean;
  pendingRealMachine?: boolean;
  sclSources?: Record<string, string> | null;
  /* —— F20 三动作 —— */
  actionAvailability?: Record<GFActionKind, GFActionAvailability>;
  actionResults?: Partial<Record<GFActionKind, GFActionResult | null>>;
  actionLoading?: GFActionKind | null;
  actionError?: string;
  actionErrorCode?: string;
  onRunActionA?: () => void;
  onRunActionB?: () => void;
  onRunActionC?: () => void;
  actionCompileDiagnostics?: GFActionCompileDiagnostics | null;
  diffChecked?: Record<string, boolean>;
  onToggleDiffItem?: (key: string, checked: boolean) => void;
  checklistComplete?: boolean;
  explicitConfirmed?: boolean;
}

function sourceBlockLabel(block: GFSourceBlock): string {
  const payloadKeys = Object.keys(block.payload ?? {}).slice(0, 3);
  return `${block.source_id} · ${block.kind}${payloadKeys.length ? ` · ${payloadKeys.join("/")}` : ""}`;
}

const DeliveryReview: React.FC<DeliveryReviewProps> = ({
  diff,
  fidelity,
  reverseProtection,
  compileDiagnostics,
  diffConfirmed,
  onConfirmDiff,
  onRefreshDiff,
  busy,
  pendingRealMachine,
  sclSources,
  actionAvailability,
  actionResults,
  actionLoading,
  actionError,
  actionErrorCode,
  onRunActionA,
  onRunActionB,
  onRunActionC,
  actionCompileDiagnostics,
  diffChecked,
  onToggleDiffItem,
  checklistComplete,
  explicitConfirmed,
}) => {
  const fidelityLabel = formatFidelityLabel(fidelity);
  const protection = reverseProtection ?? fidelity?.reverse_protection ?? null;
  const blocked = !!protection && (protection.allowed === false || (protection.tia_side_drift ?? 0) > 0);
  const diagnostics = compileDiagnostics ?? null;
  const phase = diagnostics?.phase ?? "idle";
  const sclEntries = Object.entries(sclSources ?? {});
  const diffGroups: Array<{ key: "changed" | "added" | "removed"; title: string; blocks: GFSourceBlock[] }> = [
    { key: "changed", title: "变更", blocks: diff?.changed ?? [] },
    { key: "added", title: "新增", blocks: diff?.added ?? [] },
    { key: "removed", title: "移除", blocks: diff?.removed ?? [] },
  ];
  const hasDiff = diffGroups.some((g) => g.blocks.length > 0);
  const compileVerdict = formatCompileVerdict(
    actionCompileDiagnostics ?? diagnostics,
    pendingRealMachine,
  );
  const triad: Array<{ kind: GFActionKind; label: string; title: string; run?: () => void }> = [
    { kind: "A", label: "Action A · 导出工程包", title: "离线可校验、不写 TIA；产出 fidelity 报告与 EvidenceBundle", run: onRunActionA },
    { kind: "B", label: "Action B · 首次写入博途编译", title: "前置：Action A 的 fidelity_ok=true + 差异清单显式确认（D11）", run: onRunActionB },
    { kind: "C", label: "Action C · 调试期增量回写", title: "§13.5 八步；前置：差异清单显式确认（D11）+ 反向保护通过", run: onRunActionC },
  ];
  const cSteps = actionResults?.C?.steps ?? [];
  const bSteps = actionResults?.B?.steps ?? [];
  const shownSteps = cSteps.length > 0 ? cSteps : bSteps;

  return (
    <div className="gf-delivery" data-ui="greenfield-delivery-review">
      <div className="gf-delivery__pending">
        涉真机验收项：<strong>pending_real_machine</strong>
        {pendingRealMachine !== false ? "（本批次无真机，不宣称 L2 / L4 通过，不宣称编译零错误）" : ""}
        <div className="gf-muted">{pendingRealMachineLabel(pendingRealMachine)}</div>
      </div>

      {/* —— F20 三动作（§3.2）：A 导出 / B 首次写入 / C 增量回写 —— */}
      <section className="gf-review-section" data-ui="greenfield-action-triad">
        <div className="gf-review-section__head">
          <strong>三动作 · 交付结果区操作入口</strong>
          <span className="gf-muted">B 须在 A 的 fidelity_ok=true 后可用；C 须在差异清单显式确认后可用（D11）</span>
        </div>
        <div className="gf-action-triad">
          {triad.map((item) => {
            const avail = actionAvailability?.[item.kind] ?? {
              enabled: false,
              reason: "尚未获取三动作状态（未连接网关或状态未返回）",
            };
            const loading = actionLoading === item.kind;
            const disabled = !avail.enabled || !!busy || loading;
            return (
              <div className="gf-action-card" key={item.kind}>
                <button
                  type="button"
                  className="gf-btn gf-btn--primary"
                  disabled={disabled}
                  title={avail.enabled ? item.title : avail.reason}
                  onClick={() => item.run?.()}
                >
                  {loading ? "处理中…" : item.label}
                </button>
                <div className={avail.enabled ? "gf-muted" : "gf-bad-text"}>
                  {avail.enabled ? avail.reason : `已锁定：${avail.reason}`}
                </div>
                {actionResults?.[item.kind] && (
                  <div className="gf-muted">
                    上次结果：{actionResults[item.kind]?.ok ? "完成" : "被阻止 / 未通过"}
                    {actionResults[item.kind]?.fidelity_ok !== undefined && (
                      <> · 还原度校验 fidelity_ok={String(actionResults[item.kind]?.fidelity_ok)}</>
                    )}
                    {actionResults[item.kind]?.compile_ok !== undefined && (
                      <> · 本次编排 compile_ok={String(actionResults[item.kind]?.compile_ok)}</>
                    )}
                    {actionResults[item.kind]?.tia_written === false && <> · 未写 TIA（待真机）</>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {actionError && (
          <div className="gf-bad" role="alert">
            <strong>动作被拒绝（{actionErrorCode || "网关拒绝"}）：</strong>
            <div>{actionError}</div>
            <div className="gf-muted">服务端 fail-closed，未产生任何越权写入（D11 / D10）。</div>
          </div>
        )}
      </section>

      {/* —— §13.5 八步进度（step_order）与每步结果 —— */}
      <section className="gf-review-section" data-ui="greenfield-action-steps">
        <div className="gf-review-section__head">
          <strong>step_order（§13.5 八步）进度与每步结果</strong>
          <span className="gf-muted">顺序由服务端真实响应给出，未执行的步骤显示「待执行」，禁止臆造</span>
        </div>
        <div className="gf-compile-steps">
          {GF_ACTION_C_STEPS.map((step) => {
            const st = actionStepStatus(cSteps.length > 0 ? cSteps : undefined, step.key);
            const cls = st === "done" ? "done" : st === "failed" ? "active" : "todo";
            const suffix = st === "done" ? " · 完成" : st === "failed" ? " · 失败" : "";
            return (
              <span key={step.key} className={`gf-compile-step gf-compile-step--${cls}`} title={step.key}>
                {step.label}{suffix}
              </span>
            );
          })}
        </div>
        <div className="gf-muted">
          {shownSteps.length > 0
            ? `步骤明细：${shownSteps
                .map((s) => `${s.step}=${s.ok ? "ok" : "blocked"}${s.detail ? `(${s.detail})` : ""}`)
                .join("；")}`
            : "尚未执行 B / C，八步进度均为待执行；step_order / 每步结果只展示服务端真实返回"}
        </div>
        {bSteps.length > 0 && (
          <div className="gf-muted">
            Action B 四步：{GF_ACTION_B_STEPS.map((s) => `${s.label}:${actionStepStatus(bSteps, s.key)}`).join(" · ")}
          </div>
        )}
      </section>

      {/* —— 编译诊断（P1-I 展示层，不改后端 compile_jobs.py / writeback_heal.py）—— */}
      <section className="gf-review-section">
        <div className="gf-review-section__head">
          <strong>结构化编译诊断与状态反馈</strong>
          <span className="gf-muted">generate → compile → 诊断 → 修正 → 复编译（仅展示与状态机）</span>
        </div>
        {/* N9：compile_ok 用 error_count / warnings 单列展示；真机未跑显示「待真机」而非「成功」 */}
        <div className={compileVerdict.ok ? "gf-fidelity gf-fidelity--ok" : "gf-fidelity"}>
          <strong>{compileVerdict.label}</strong>
          <span className="gf-muted">{compileVerdict.detail}</span>
        </div>
        <div className="gf-compile-steps">
          {GF_COMPILE_STEPS.map((step) => (
            <span
              key={step.key}
              className={`gf-compile-step gf-compile-step--${compileStepStatus(phase, step.key)}`}
            >
              {step.label}
            </span>
          ))}
        </div>
        {diagnostics ? (
          <div className="gf-compile-report">
            <div className="gf-compile-metric">
              <span className="gf-muted">error_count</span>
              <strong className={diagnostics.error_count > 0 ? "gf-bad-text" : "gf-ok-text"}>
                {diagnostics.error_count}
              </strong>
              <span className="gf-muted">（warning 单列，绝不并入成功）</span>
            </div>
            <div className="gf-compile-cols">
              <div>
                <div className="gf-side-title">warnings（单列，{diagnostics.warnings.length} 条）</div>
                {diagnostics.warnings.length === 0 ? (
                  <div className="gf-muted">无 warning 条目</div>
                ) : (
                  diagnostics.warnings.map((w, i) => (
                    <div className="gf-warning" key={`${w}-${i}`}>· {w}</div>
                  ))
                )}
              </div>
              <div>
                <div className="gf-side-title">块清单（{diagnostics.blocks.length} 块）</div>
                {diagnostics.blocks.length === 0 ? (
                  <div className="gf-muted">后端未提供块清单</div>
                ) : (
                  diagnostics.blocks.slice(0, 20).map((b, i) => (
                    <div className="gf-muted" key={`${b.name}-${i}`}>
                      {b.name} · {b.block_type ?? "—"} · 错误 {b.error_count ?? 0} / 警告 {b.warning_count ?? 0}
                    </div>
                  ))
                )}
              </div>
            </div>
            {diagnostics.tia_unavailable && (
              <div className="gf-bad">TIA 真机环境不可用，本次编译判定未执行（非编译通过）。</div>
            )}
            {diagnostics.note && <div className="gf-muted">{diagnostics.note}</div>}
          </div>
        ) : actionCompileDiagnostics ? (
          <div className="gf-compile-report">
            <div className="gf-compile-metric">
              <span className="gf-muted">error_count</span>
              <strong className={actionCompileDiagnostics.error_count > 0 ? "gf-bad-text" : "gf-ok-text"}>
                {actionCompileDiagnostics.error_count}
              </strong>
              <span className="gf-muted">（warning 单列，绝不并入成功）</span>
            </div>
            <div className="gf-compile-cols">
              <div>
                <div className="gf-side-title">warnings（单列，{(actionCompileDiagnostics.warnings ?? []).length} 条）</div>
                {(actionCompileDiagnostics.warnings ?? []).length === 0 ? (
                  <div className="gf-muted">无 warning 条目</div>
                ) : (
                  (actionCompileDiagnostics.warnings ?? []).map((w, i) => (
                    <div className="gf-warning" key={`${w}-${i}`}>· {String(w)}</div>
                  ))
                )}
              </div>
              <div>
                <div className="gf-side-title">状态 / 诊断（真实响应）</div>
                <div className="gf-muted">status：{actionCompileDiagnostics.status ?? "—"}</div>
                <div className="gf-muted">l2_status：{actionCompileDiagnostics.l2_status ?? "—"}</div>
                <div className="gf-muted">static_gate_passed：{String(actionCompileDiagnostics.static_gate_passed ?? "—")}</div>
                {actionCompileDiagnostics.reason && (
                  <div className="gf-muted">reason：{actionCompileDiagnostics.reason}</div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="gf-muted">
            后端尚未返回结构化编译诊断（诚实降级：不虚构 error_count，也不宣称编译零错误）。
          </div>
        )}
      </section>

      {/* —— fidelity（N9）—— */}
      <section className="gf-review-section">
        <div className="gf-review-section__head">
          <strong>还原度校验（fidelity）</strong>
          <span className="gf-muted">只表达 L1 逻辑等价；与「编译通过」是两个独立验收层，禁止互相替代（N9）</span>
        </div>
        <div className={fidelityLabel.ok ? "gf-fidelity gf-fidelity--ok" : "gf-fidelity"}>
          <strong>{fidelityLabel.label}</strong>
          <span className="gf-muted">{fidelityLabel.detail}</span>
        </div>
        {!!fidelity?.ob_number_deviations && (
          <div className="gf-muted">OB 编号偏差已留痕（不纳入 1:1 域，禁止静默）</div>
        )}
      </section>

      {/* —— 差异清单（F20 / D11 / D10）—— */}
      <section className="gf-review-section">
        <div className="gf-review-section__head">
          <strong>差异清单（SpecDiff）</strong>
          {onRefreshDiff && (
            <button
              type="button"
              className="gf-btn gf-btn--xs gf-btn--ghost"
              disabled={busy}
              onClick={onRefreshDiff}
            >
              重新计算差异
            </button>
          )}
        </div>

        {blocked && (
          <div className="gf-blocked" role="alert">
            <strong>TIA 侧存在手工改动，已阻止覆盖</strong>
            <div className="gf-muted">
              被阻止的 source_id：{(protection?.blocked_source_ids ?? []).join("、") || "—"}
              {protection?.reason ? ` · ${protection.reason}` : ""}
            </div>
            <div className="gf-muted">按 D10 fail-closed：不覆盖、不「先覆盖再提示」。</div>
          </div>
        )}

        {hasDiff ? (
          <div className="gf-diff-groups">
            {diffGroups.map((group) => (
              <div className="gf-diff-group" key={group.key}>
                <div className="gf-side-title">
                  {group.title}（{group.blocks.length}）
                </div>
                {group.blocks.length === 0 ? (
                  <div className="gf-muted">无</div>
                ) : (
                  group.blocks.map((block, index) => {
                    const key = diffItemKey(group.key, block, index);
                    return (
                      <label className="gf-diff-item" key={key}>
                        <input
                          type="checkbox"
                          checked={!!diffChecked?.[key]}
                          disabled={busy}
                          onChange={(e) => onToggleDiffItem?.(key, e.target.checked)}
                        />
                        <code>{sourceBlockLabel(block)}</code>
                        <span className="gf-muted">（{group.title} · source_id：{block.source_id}）</span>
                      </label>
                    );
                  })
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="gf-muted">
            暂无差异清单（后端未返回 SpecDiff 或版本未发生变化）。未确认前不会产生任何写入。
          </div>
        )}

        {/* D11：逐项勾选齐全后才能显式确认；显式确认前所有写入按钮 disabled 且说明原因 */}
        <label className="gf-diff-confirm">
          <input
            type="checkbox"
            checked={!!diffConfirmed}
            disabled={busy || !checklistComplete}
            onChange={(e) => onConfirmDiff?.(e.target.checked)}
          />
          <span>
            我已逐条核对上述差异清单并<strong>逐项勾选</strong>，现<strong>显式确认</strong>后才允许后续写入（D11：确认前零副作用计数器恒 0）
          </span>
        </label>
        <div className="gf-muted">
          逐项勾选：{checklistComplete ? "已齐全" : "未齐全（请先勾选全部变更 / 新增 / 移除项）"}；
          当前状态：{explicitConfirmed ? "已显式确认（D11 后续写入解锁）" : "未显式确认（A 之外的所有写入按钮已锁定）"}
        </div>
      </section>

      {/* —— F13 降级：纯文本 SCL 只读预览 + 关键字高亮 —— */}
      <section className="gf-review-section">
        <div className="gf-review-section__head">
          <strong>SCL 只读预览（F13 降级）</strong>
          <span className="gf-muted">纯文本 + 关键字高亮 · 未引入 Monaco · 无任何写回 TIA 的编辑入口</span>
        </div>
        {sclEntries.length === 0 ? (
          <div className="gf-muted">
            暂无只读预览内容：尚未生成产物或后端未提供 SCL 源，不会虚构任何代码或地址条目。
          </div>
        ) : (
          <div className="gf-scl-preview">
            {sclEntries.map(([name, code]) => (
              <div className="gf-scl-block" key={name}>
                <div className="gf-scl-block__head">
                  <code>{name}</code>
                  <span className="gf-muted">只读</span>
                </div>
                <pre className="gf-scl-block__code">
                  {code.split("\n").map((line, i) => (
                    <div className="gf-scl-line" key={i}>
                      <span className="gf-scl-line__no">{i + 1}</span>
                      <span className="gf-scl-line__text">{highlightSclLines(line)}</span>
                    </div>
                  ))}
                </pre>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};

/* ==========================================================================
 * 主面板
 * ========================================================================== */
export const GreenfieldPanel: React.FC<GreenfieldPanelProps> = ({
  views,
  ir,
  hardware,
  legalKinds,
  prompt,
  busy,
  selectedHwNodeId,
  selectedTargetId,
  onSelectHwNode,
  onSelectTarget,
  onPromptChange,
  onGenerateDraft,
  onMountCm,
  onUnmountCm,
  onRemoveHwNode,
  onResetTopology,
  onEditStepField,
  onConnect,
  onRemoveEdge,
  projectId,
  diff,
  fidelity,
  reverseProtection,
  compileDiagnostics,
  diffConfirmed,
  onConfirmDiff,
  onRefreshDiff,
  onPatchNodes,
  actionFeedback,
  pendingRealMachine,
  sclSources,
  actionAvailability,
  actionResults,
  actionLoading,
  actionError,
  actionErrorCode,
  onRunActionA,
  onRunActionB,
  onRunActionC,
  actionCompileDiagnostics,
  diffChecked,
  onToggleDiffItem,
  checklistComplete,
  explicitConfirmed,
}) => {
  const [tab, setTab] = useState<ViewTab>("step_flow");
  const [kind, setKind] = useState<string>(legalKinds[0] ?? "E_MSG_STEP");
  const [showMermaidSource, setShowMermaidSource] = useState<boolean>(false);
  const [hwCollapsed, setHwCollapsed] = useState<boolean>(false);
  const [engineeringView, setEngineeringView] = useState<boolean>(false);
  const [editingStepId, setEditingStepId] = useState<string>("");
  const [condDraft, setCondDraft] = useState<string>("");
  const [actionDraft, setActionDraft] = useState<string>("");
  const hostRef = useRef<HTMLDivElement | null>(null);

  const nodes = useMemo(() => buildNodes(ir, engineeringView), [ir, engineeringView]);
  const edges = useMemo(() => buildEdges(ir), [ir]);
  const cms = useMemo(() => asArray(ir?.cms), [ir]);
  const stepNodes: GFStepNode[] = useMemo(
    () => views?.step_flow?.nodes ?? [],
    [views],
  );

  const activeStep = useMemo(
    () => stepNodes.find((s) => s.id === (editingStepId || selectedTargetId)) ?? stepNodes[0] ?? null,
    [stepNodes, editingStepId, selectedTargetId],
  );

  useEffect(() => {
    if (activeStep) {
      setCondDraft(activeStep.transition_condition || "TRUE");
      setActionDraft((activeStep.actions || []).join(", "));
    }
  }, [activeStep?.id, activeStep?.transition_condition, activeStep?.actions]);

  const diagram = useMemo(() => {
    if (tab === "step_flow") return views?.step_flow?.mermaid || views?.flow || "";
    if (tab === "seq") return views?.seq ?? "";
    if (tab === "state") return views?.state ?? "";
    return views?.flow ?? "";
  }, [tab, views]);

  useEffect(() => {
    if (tab === "flow" || tab === "delivery" || !diagram) return;
    let cancelled = false;
    void (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
        const result = await mermaid.render(`gf-${tab}-${Date.now()}`, diagram);
        if (!cancelled && hostRef.current) hostRef.current.innerHTML = result.svg;
      } catch (error) {
        if (!cancelled && hostRef.current) {
          hostRef.current.textContent = `图渲染失败：${String(error)}`;
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, diagram]);

  const hwNodes: GFHwNode[] = hardware?.nodes ?? [];
  const hwLinks = hardware?.links ?? [];
  const customNodeIds = hardware?.custom_node_ids ?? [];
  const customMounts = hardware?.custom_cm_mounts ?? {};

  const patchNodes = (ops: GFCanvasOp[]) => {
    if (onPatchNodes) onPatchNodes(ops);
  };

  return (
    <div className="gf-center-stack" data-ui="greenfield-panel">
      {/* ==================== 上半区：设备交互拓扑（逻辑级占位） ==================== */}
      <section className="gf-hw-pane" data-ui="greenfield-hardware-pane">
        <div className="gf-pane-header">
          <div className="gf-pane-header__title">
            <span className="gf-pane-step-tag">上区 · 设备交互拓扑（逻辑级占位）</span>
            <span>{hwCollapsed ? "已收起——具体物理组态在博途中完成" : "逻辑设备节点 / PROFINET 机器人 / TCP 上位机与执行件驱动挂载"}</span>
          </div>
          <div className="gf-pane-header__meta">
            <button
              type="button"
              className="gf-btn gf-btn--xs gf-btn--ghost"
              disabled={busy}
              onClick={() => setHwCollapsed((v) => !v)}
            >
              {hwCollapsed ? "展开拓扑" : "收起拓扑"}
            </button>
            {!hwCollapsed && (
              <button
                type="button"
                className="gf-btn gf-btn--xs gf-btn--ghost"
                disabled={busy}
                title="撤销全部挂载 / 变量绑定 / 手工节点，回到自动推导的拓扑"
                onClick={onResetTopology}
              >
                撤销拓扑编辑
              </button>
            )}
            {selectedHwNodeId && (
              <button
                type="button"
                className="gf-btn gf-btn--xs gf-btn--ghost"
                onClick={() => onSelectHwNode(null)}
              >
                清除硬件筛选 ({selectedHwNodeId})
              </button>
            )}
            {!hwCollapsed && (
              <span className="gf-muted">
                共 {hwNodes.length} 个节点 · {hwLinks.length} 条设备交互连接（点击卡片筛选右侧变量）
              </span>
            )}
          </div>
        </div>

        <div className="gf-hw-grid" style={hwCollapsed ? { display: "none" } : undefined}>
          {hwNodes.map((node) => {
            const busMeta = BUS_BADGE_MAP[node.protocol] ?? {
              label: node.protocol,
              cls: "gf-bus-badge",
            };
            const isSelected = selectedHwNodeId === node.id;
            const mountedCms = cms.filter((cm) =>
              (node.mounted_cm_ids ?? []).includes(String(cm.id)),
            );
            return (
              <div
                key={node.id}
                className={`gf-hw-card gf-hw-card--${node.kind.toLowerCase()}${isSelected ? " gf-hw-card--selected" : ""}`}
                onClick={() => onSelectHwNode(isSelected ? null : node.id)}
              >
                <div className="gf-hw-card__top">
                  <span className={busMeta.cls}>{busMeta.label}</span>
                  {node.slot && <span className="gf-hw-slot">{node.slot}</span>}
                  {node.tag_count > 0 && <span className="gf-hw-lock">契约锁定</span>}
                  {customNodeIds.includes(node.id) && (
                    <button
                      type="button"
                      className="gf-hw-card__remove"
                      title="移除该手工新增节点"
                      disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveHwNode(node.id);
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>
                <div className="gf-hw-card__title">{node.label}</div>
                <div className="gf-hw-card__stats">
                  {node.address_range && <span>地址段: {node.address_range}</span>}
                  {node.tag_count !== undefined && <span>绑定点/成员: {node.tag_count}</span>}
                </div>
                {mountedCms.length > 0 && (
                  <div className="gf-hw-card__cms">
                    {mountedCms.map((cm) => {
                      const cmId = String(cm.id);
                      const cmLabel = String(cm.business_label || cm.name || cmId);
                      const cmType = String(cm.cm_type || cm.device_type || "执行件");
                      return (
                        <span
                          key={cmId}
                          className={`gf-cm-chip${selectedTargetId === cmId ? " gf-cm-chip--active" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectTarget(cmId);
                          }}
                          title={`${cmId} / ${cmType}（点击作为右侧变量绑定目标）`}
                        >
                          {cmLabel} · 执行件
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* 执行件挂载分配条（"" = 自动推导，即撤销该执行件的手工挂载） */}
        {!hwCollapsed && cms.length > 0 && hwNodes.length > 0 && (
          <div className="gf-hw-mountbar">
            <span className="gf-muted">执行件挂载至逻辑设备节点：</span>
            {cms.map((cm) => {
              const cmId = String(cm.id);
              const cmName = String(cm.business_label || cm.name || cmId);
              const derivedHw =
                hwNodes.find((n) => (n.mounted_cm_ids ?? []).includes(cmId))?.id ?? "HW_CPU";
              const currentHw = customMounts[cmId] ?? derivedHw;
              return (
                <label key={cmId} className="gf-hw-mount-item">
                  <span
                    className={selectedTargetId === cmId ? "gf-mount-label gf-mount-label--active" : "gf-mount-label"}
                    onClick={() => onSelectTarget(cmId)}
                  >
                    {cmName}
                  </span>
                  <select
                    value={currentHw}
                    disabled={busy}
                    onChange={(e) => {
                      if (e.target.value) onMountCm(cmId, e.target.value);
                      else onUnmountCm(cmId);
                    }}
                  >
                    <option value="">自动（推导）</option>
                    {hwNodes.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.label}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
        )}
      </section>

      {/* ==================== 下半区：对话生成 Mermaid 逻辑 / 交付结果 ==================== */}
      <section className="gf-logic-pane" data-ui="greenfield-logic-pane">
        {/* 工艺对话输入条 */}
        <div className="gf-prompt-bar" data-ui="greenfield-chat">
          <span className="gf-pane-step-tag">下区 · 对话生成 Mermaid 逻辑</span>
          {projectId && <span className="gf-project-tag" title="项目上下文：project_id 贯穿会话 / 拓扑 / 资料 / 规格 / 产物">项目 {projectId}</span>}
          <input
            type="text"
            className="gf-prompt-input"
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                e.preventDefault();
                onGenerateDraft();
              }
            }}
            placeholder="输入工艺描述（例如：视觉引导与KUKA机器人上下料涂胶打磨工位，气缸夹紧与真空吸盘配合，光幕或急停触发安全中止）…"
          />
          <button
            type="button"
            className="gf-btn gf-btn--primary"
            disabled={busy}
            onClick={onGenerateDraft}
          >
            生成首版结构图
          </button>
        </div>

        {actionFeedback && (
          <div className="gf-action-feedback" role="status">{actionFeedback}</div>
        )}

        {/* 视图切换栏 + Mermaid 源码开关 */}
        <div className="gf-tabs">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={tab === item.key ? "gf-tab gf-tab--active" : "gf-tab"}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
          {tab === "flow" && (
            <label className="gf-kind">
              设备交互连线类型
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                {legalKinds.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
          )}
          {tab === "flow" && (
            <label className="gf-engineering-toggle" title="AF 工程术语仅允许出现在工程视角面板；默认一律使用业务语言">
              <input
                type="checkbox"
                checked={engineeringView}
                onChange={(e) => setEngineeringView(e.target.checked)}
              />
              工程视角（显示 AF 术语）
            </label>
          )}
          {tab !== "delivery" && (
            <button
              type="button"
              className={showMermaidSource ? "gf-tab gf-tab--active gf-tab--right" : "gf-tab gf-tab--right"}
              onClick={() => setShowMermaidSource((v) => !v)}
            >
              {showMermaidSource ? "收起 Mermaid 源码" : "查看 Mermaid 源码 (自动同步)"}
            </button>
          )}
        </div>

        {/* 主逻辑视图区 */}
        <div className="gf-logic-content">
          {tab === "delivery" ? (
            <DeliveryReview
              diff={diff}
              fidelity={fidelity}
              reverseProtection={reverseProtection}
              compileDiagnostics={compileDiagnostics}
              diffConfirmed={diffConfirmed}
              onConfirmDiff={onConfirmDiff}
              onRefreshDiff={onRefreshDiff}
              busy={busy}
              pendingRealMachine={pendingRealMachine}
              sclSources={sclSources}
              actionAvailability={actionAvailability}
              actionResults={actionResults}
              actionLoading={actionLoading}
              actionError={actionError}
              actionErrorCode={actionErrorCode}
              onRunActionA={onRunActionA}
              onRunActionB={onRunActionB}
              onRunActionC={onRunActionC}
              actionCompileDiagnostics={actionCompileDiagnostics}
              diffChecked={diffChecked}
              onToggleDiffItem={onToggleDiffItem}
              checklistComplete={checklistComplete}
              explicitConfirmed={explicitConfirmed}
            />
          ) : tab === "flow" ? (
            <div className="gf-flow">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                fitView
                onConnect={(connection) => onConnect(kind, connection)}
                onEdgeDoubleClick={(_, edge) => onRemoveEdge(edge.id)}
                proOptions={{ hideAttribution: true }}
              >
                <Background />
                <Controls />
              </ReactFlow>
              <div className="gf-flow__hint">
                拖动节点端点即可手动连线；双击连线删除。任何连线修改将实时同步至 Mermaid 源码与步序规格。
                画布默认使用业务语言（工站 / 执行单元 / 执行件 / 设备交互）；勾选「工程视角」才显示 AF 术语。
              </div>
              {onPatchNodes && (
                <div className="gf-flow__node-editor">
                  <NodeEditor ir={ir} busy={busy} onPatch={patchNodes} />
                </div>
              )}
            </div>
          ) : (
            <div className="gf-mermaid-workspace">
              <div className="gf-diagram" ref={hostRef} />

              {/* 步序流程图交互编辑栏 */}
              {tab === "step_flow" && stepNodes.length > 0 && (
                <div className="gf-step-inspector">
                  <div className="gf-step-pills">
                    <span className="gf-muted">点击步序设为右侧变量绑定目标：</span>
                    {stepNodes.map((st) => {
                      const active = (activeStep?.id ?? "") === st.id;
                      return (
                        <button
                          key={st.id}
                          type="button"
                          className={active ? "gf-step-pill gf-step-pill--active" : "gf-step-pill"}
                          onClick={() => {
                            setEditingStepId(st.id);
                            onSelectTarget(st.id);
                          }}
                        >
                          S{st.step_id} · {st.name}
                        </button>
                      );
                    })}
                  </div>

                  {activeStep && (
                    <div className="gf-step-editor">
                      <div className="gf-step-editor__field">
                        <label>当前步序</label>
                        <strong>
                          {activeStep.id} (S{activeStep.step_id}: {activeStep.name})
                        </strong>
                      </div>
                      <div className="gf-step-editor__field">
                        <label>转换条件 (Transition)</label>
                        <input
                          type="text"
                          value={condDraft}
                          onChange={(e) => setCondDraft(e.target.value)}
                          placeholder="如 %I0.0 或 KUKA.In.Send.StartWork"
                        />
                        <button
                          type="button"
                          className="gf-btn gf-btn--xs"
                          onClick={() =>
                            onEditStepField(
                              activeStep.id,
                              `steps.${activeStep.id}.transition_condition`,
                              condDraft,
                            )
                          }
                        >
                          同步至 Mermaid
                        </button>
                      </div>
                      <div className="gf-step-editor__field">
                        <label>动作列表 (Actions, 逗号分隔)</label>
                        <input
                          type="text"
                          value={actionDraft}
                          onChange={(e) => setActionDraft(e.target.value)}
                          placeholder="如 执行件_Cyl1.enable:=TRUE, KUKA.Out.Recv.CmdRun"
                        />
                        <button
                          type="button"
                          className="gf-btn gf-btn--xs"
                          onClick={() =>
                            onEditStepField(
                              activeStep.id,
                              `steps.${activeStep.id}.actions`,
                              actionDraft
                                .split(",")
                                .map((s) => s.trim())
                                .filter(Boolean),
                            )
                          }
                        >
                          同步至 Mermaid
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Mermaid 源码实时同步抽屉 */}
          {showMermaidSource && tab !== "delivery" && (
            <aside className="gf-mermaid-drawer">
              <div className="gf-mermaid-drawer__head">
                <strong>Mermaid 实时源码 ({tab})</strong>
                <span className="gf-muted">手动连线 / 变量绑定自动同步</span>
              </div>
              <pre className="gf-mermaid-drawer__code">{diagram || "// 尚未生成 Mermaid 图"}</pre>
            </aside>
          )}
        </div>
      </section>
    </div>
  );
};

export function toGfEdge(kind: string, connection: Connection): GFEdge {
  const src = String(connection.source ?? "");
  const dst = String(connection.target ?? "");
  return {
    id: `E_MANUAL_${kind}_${src}_${dst}`,
    kind,
    src_id: src,
    dst_id: dst,
    view_mask: ["flow"],
    origin: "manual",
  };
}
