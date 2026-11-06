/**
 * 新建工程画布左/中主区（上下双层）：
 * - 上半区：硬件物理拓扑（PLC CPU + DI/DQ/AI/AQ 模块 + KUKA 机器人 [DB720] + 上位机 PC [DB1900] + 挂载 CM）
 * - 下半区：对话生成 Mermaid 逻辑（步序流程图 + 层级连线图 + 时序图 + PackML 状态机 + Mermaid 源码实时同步）
 * 不展示实时 SCL 代码预览，保持架构/硬件/逻辑/变量视图纯净。
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
import type {
  GFEdge,
  GFHardwareTopology,
  GFHwNode,
  GFStepNode,
  GFViews,
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
}

type ViewTab = "step_flow" | "flow" | "seq" | "state";

const TABS: Array<{ key: ViewTab; label: string }> = [
  { key: "step_flow", label: "步序流程图 (Mermaid)" },
  { key: "flow", label: "AF 层级与手动连线" },
  { key: "seq", label: "时序与异常联动" },
  { key: "state", label: "PackML 模式与状态机" },
];

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function buildNodes(ir: Record<string, unknown> | null): Node[] {
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
      const label = String(item.name ?? item.symbol ?? id);
      nodes.push({
        id,
        position: { x: 30 + index * 200, y },
        data: { label: `[${tag}] ${label}` },
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
    label: `${String(edge.kind)}${edge.origin === "manual" ? " · 手动" : ""}`,
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
}) => {
  const [tab, setTab] = useState<ViewTab>("step_flow");
  const [kind, setKind] = useState<string>(legalKinds[0] ?? "E_MSG_STEP");
  const [showMermaidSource, setShowMermaidSource] = useState<boolean>(false);
  const [hwCollapsed, setHwCollapsed] = useState<boolean>(false);
  const [editingStepId, setEditingStepId] = useState<string>("");
  const [condDraft, setCondDraft] = useState<string>("");
  const [actionDraft, setActionDraft] = useState<string>("");
  const hostRef = useRef<HTMLDivElement | null>(null);

  const nodes = useMemo(() => buildNodes(ir), [ir]);
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
    if (tab === "flow" || !diagram) return;
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

  return (
    <div className="gf-center-stack" data-ui="greenfield-panel">
      {/* ==================== 上半区：硬件拓扑（逻辑级占位，可收起/可撤销） ==================== */}
      <section className="gf-hw-pane" data-ui="greenfield-hardware-pane">
        <div className="gf-pane-header">
          <div className="gf-pane-header__title">
            <span className="gf-pane-step-tag">上区 · 硬件拓扑（逻辑级占位）</span>
            <span>{hwCollapsed ? "已收起——具体物理组态在博途中完成" : "PLC 机架模块 / PROFINET 机器人 / TCP 上位机与 CM 驱动挂载"}</span>
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
                共 {hwNodes.length} 个节点 · {hwLinks.length} 条连接（点击卡片筛选右侧变量）
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
                      const cmType = String(cm.cm_type || cm.device_type || "CM");
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
                          {cmLabel} · {cmType}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* CM 挂载分配条（"" = 自动（推导），即撤销该 CM 的手工挂载） */}
        {!hwCollapsed && cms.length > 0 && hwNodes.length > 0 && (
          <div className="gf-hw-mountbar">
            <span className="gf-muted">CM 设备挂载至物理硬件：</span>
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

      {/* ==================== 下半区：对话生成 Mermaid 逻辑 ==================== */}
      <section className="gf-logic-pane" data-ui="greenfield-logic-pane">
        {/* 工艺对话输入条 */}
        <div className="gf-prompt-bar" data-ui="greenfield-chat">
          <span className="gf-pane-step-tag">下区 · 对话生成 Mermaid 逻辑</span>
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
              连线类型
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                {legalKinds.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            className={showMermaidSource ? "gf-tab gf-tab--active gf-tab--right" : "gf-tab gf-tab--right"}
            onClick={() => setShowMermaidSource((v) => !v)}
          >
            {showMermaidSource ? "收起 Mermaid 源码" : "查看 Mermaid 源码 (自动同步)"}
          </button>
        </div>

        {/* 主逻辑视图区 */}
        <div className="gf-logic-content">
          {tab === "flow" ? (
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
              </div>
            </div>
          ) : (
            <div className="gf-mermaid-workspace">
              <div className="gf-diagram" ref={hostRef} />

              {/* 步序流程图交互编辑栏（修改步序条件/动作或从右侧绑定变量后实时重绘 Mermaid） */}
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
                          placeholder="如 CM_Cyl1.enable:=TRUE, KUKA.Out.Recv.CmdRun"
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
          {showMermaidSource && (
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
