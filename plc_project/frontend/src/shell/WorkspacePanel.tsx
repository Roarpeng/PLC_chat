import React, { useEffect, useState } from "react";
import { PlcInteractiveCanvas, type BlockEdge, type FocusTarget } from "../canvas/PlcInteractiveCanvas";
import { SclPane } from "./SclPane";
import { HmiPane } from "./HmiPane";
import { VariableInspector } from "./VariableInspector";
import { RequirementCardDrawer } from "./RequirementCardDrawer";
import { ChangeReviewDrawer } from "./ChangeReviewDrawer";
import type { CanvasStateData } from "../canvas/types";
import type { CrossRefReport, VarRef } from "../state/crossRef";
import type { Requirement } from "../state/requirements";
import type { CanvasTab } from "./smartRoute";
import "./WorkspacePanel.css";

/* ==========================================================================
   WorkspacePanel —— 画布面板（契约 25 §2，L 线）
   右侧滑入的工程画布：左边缘 48px 竖向图标标签栏（工业感按钮式）+ 内容区。
   全局图 / SCL / HMI / 变量四个标签复用现有组件（只 import 挂载，不重写）；
   时序图标签接收最新 Mermaid 源码就地渲染 SVG；需求卡 / 变更审查标签把
   两个抽屉组件经 CSS 内嵌（.wsp-drawerhost 把 fixed 覆盖层收进面板区域）。
   props 全部由 App 传入（接线照旧），本组件不持有业务状态。
   ========================================================================== */

export interface WorkspacePanelProps {
  /** 当前激活标签（App 持有：智能路由 / 用户点击都会改它） */
  activeTab: CanvasTab;
  onActiveTabChange: (tab: CanvasTab) => void;
  /** fullscreen 态：面板占满主区（App 侧布局语义，这里只影响按钮图标） */
  fullscreen: boolean;
  /** split → fullscreen / fullscreen → split */
  onToggleMaximize: () => void;
  /** 关闭画布 → chat 态 */
  onClose: () => void;

  /* —— 画布数据与交互（与 PlcInteractiveCanvas / SclPane / HmiPane 同源） —— */
  canvas: CanvasStateData;
  selectedBlockName: string | null;
  onSelectBlock: (name: string | null) => void;
  blockEdges: BlockEdge[];
  focus: FocusTarget | null;
  onFocusChange: (focus: FocusTarget | null) => void;
  onCanvasChange: (canvas: CanvasStateData) => void;
  /* 从零构建 / 编辑回调（PlcInteractiveCanvas 与 SclPane 共用同一组） */
  onCreateBlock: () => void;
  onAddVariable: (
    blockName: string,
    v: { name: string; data_type: string; section: string; comment?: string },
  ) => void;
  onAddNetwork: (
    blockName: string,
    n: { title: string; scl_text: string; language?: string },
  ) => void;
  onRemoveBlock: (blockName: string) => void;
  onRenameBlock: (oldName: string, newName: string) => void;
  onRemoveVariable: (blockName: string, varName: string) => void;
  onRemoveNetwork: (blockName: string, networkId: number) => void;
  onDeepExplain: (block: CanvasStateData["blocks"][string]) => Promise<string>;

  /* —— 变量交叉引用（变量标签） —— */
  crossReport: CrossRefReport;
  /** 物理接线标签（canvas.tags 的 values，App 已 memo） */
  wiredTags: CanvasStateData["tags"][string][];
  onJumpToRef: (ref: VarRef) => void;

  /* —— 时序图标签：最新一份 Mermaid 源码（null → 空态提示） —— */
  mermaidText: string | null;

  /* —— 需求卡标签（RequirementCardDrawer 只读内嵌） —— */
  requirement: Requirement | null;
  requirementLoading: boolean;
  onRequirementEdit: (r: Requirement) => void;
  onConfirmIntent: (r: Requirement) => void;

  /* —— 变更审查标签（ChangeReviewDrawer 内嵌） —— */
  reviewChangeId: string | null;
  reviewRequirement: Requirement | null;
  onReviewFocusTarget: (t: { blockName?: string; varName?: string }) => void;
}

/** 竖向图标标签栏定义（glyph 用工业感符号，悬停 tooltip = 标签名） */
const TABS: Array<{ key: CanvasTab; glyph: string; label: string }> = [
  { key: "graph", glyph: "▣", label: "全局图" },
  { key: "scl", glyph: "▤", label: "SCL" },
  { key: "hmi", glyph: "⚡", label: "HMI" },
  { key: "vars", glyph: "⊞", label: "变量" },
  { key: "mermaid", glyph: "⏱", label: "时序图" },
  { key: "req", glyph: "📋", label: "需求卡" },
  { key: "review", glyph: "🧾", label: "变更审查" },
];

/* ------------------------------------------------------------------ */
/* Mermaid SVG 渲染（与 ChatDock 同款懒加载口径，作用域独立避免互抢 id） */
/* ------------------------------------------------------------------ */

let mermaidModule: Promise<typeof import("mermaid")> | null = null;

function loadMermaid(): Promise<typeof import("mermaid")> {
  if (!mermaidModule) {
    mermaidModule = import("mermaid").then((mod) => {
      mod.default.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
      return mod;
    });
  }
  return mermaidModule;
}

let mermaidRenderSeq = 0;

const MermaidView: React.FC<{ code: string }> = ({ code }) => {
  const [svg, setSvg] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const renderId = `wsp-mmd-${++mermaidRenderSeq}`;
    setFailed(false);
    loadMermaid()
      .then((mod) => mod.default.render(renderId, code))
      .then(({ svg: out }) => {
        if (!cancelled) setSvg(out);
      })
      .catch(() => {
        const leftover = document.getElementById(renderId);
        if (leftover) leftover.remove();
        if (!cancelled) {
          setSvg("");
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed || !svg) {
    return (
      <pre className="wsp-mermaid-fallback">
        <code>{code}</code>
      </pre>
    );
  }
  return <div className="wsp-mermaid-svg" dangerouslySetInnerHTML={{ __html: svg }} />;
};

/* ------------------------------------------------------------------ */

export const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  activeTab,
  onActiveTabChange,
  fullscreen,
  onToggleMaximize,
  onClose,
  canvas,
  selectedBlockName,
  onSelectBlock,
  blockEdges,
  focus,
  onFocusChange,
  onCanvasChange,
  onCreateBlock,
  onAddVariable,
  onAddNetwork,
  onRemoveBlock,
  onRenameBlock,
  onRemoveVariable,
  onRemoveNetwork,
  onDeepExplain,
  crossReport,
  wiredTags,
  onJumpToRef,
  mermaidText,
  requirement,
  requirementLoading,
  onRequirementEdit,
  onConfirmIntent,
  reviewChangeId,
  reviewRequirement,
  onReviewFocusTarget,
}) => {
  const widgetList = Object.values(canvas.hmi_widgets);
  const selectedBlock = selectedBlockName ? canvas.blocks[selectedBlockName] ?? null : null;
  const activeLabel = TABS.find((t) => t.key === activeTab)?.label ?? "";

  return (
    <section
      className={"wsp" + (fullscreen ? " wsp--fullscreen" : "")}
      role="region"
      aria-label="工程画布面板"
      data-tab={activeTab}
    >
      {/* 竖向图标标签栏：~48px 工业按钮条，--accent 高亮当前 */}
      <nav className="wsp-rail" role="tablist" aria-orientation="vertical" aria-label="画布标签">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={activeTab === t.key}
            title={t.label}
            aria-label={t.label}
            className={"wsp-rail__btn" + (activeTab === t.key ? " wsp-rail__btn--on" : "")}
            onClick={() => onActiveTabChange(t.key)}
          >
            <span className="wsp-rail__glyph" aria-hidden="true">
              {t.glyph}
            </span>
          </button>
        ))}
      </nav>

      <div className="wsp-main">
        {/* 顶栏：当前标签名 + 最大化 + 关闭 */}
        <header className="wsp-head">
          <span className="wsp-head__title">{activeLabel}</span>
          <span className="wsp-head__spacer" />
          <button
            type="button"
            className="wsp-head__btn"
            onClick={onToggleMaximize}
            aria-label={fullscreen ? "还原为分栏" : "最大化画布"}
            title={fullscreen ? "还原为分栏（Esc）" : "最大化画布"}
          >
            {fullscreen ? "⤡" : "⤢"}
          </button>
          <button
            type="button"
            className="wsp-head__btn"
            onClick={onClose}
            aria-label="关闭画布"
            title="关闭画布（回到纯对话）"
          >
            ✕
          </button>
        </header>

        {/* 内容区：占满剩余，组件复用只挂载（切标签即换内容，卸载其余） */}
        <div className="wsp-body">
          {activeTab === "graph" && (
            <PlcInteractiveCanvas
              canvas={canvas}
              selectedBlockName={selectedBlockName}
              onSelectBlock={onSelectBlock}
              blockEdges={blockEdges}
              focus={focus}
              onFocusChange={onFocusChange}
              onCanvasChange={onCanvasChange}
              onCreateBlock={onCreateBlock}
              onAddVariable={onAddVariable}
              onAddNetwork={onAddNetwork}
              onRemoveBlock={onRemoveBlock}
              onRenameBlock={onRenameBlock}
              onRemoveVariable={onRemoveVariable}
              onRemoveNetwork={onRemoveNetwork}
              onDeepExplain={onDeepExplain}
            />
          )}

          {activeTab === "scl" && (
            <SclPane
              block={selectedBlock}
              edges={blockEdges}
              widgets={widgetList}
              tags={canvas.tags}
              focusNetworkId={focus?.kind === "network" ? focus.networkId ?? null : null}
              onAddVariable={onAddVariable}
              onAddNetwork={onAddNetwork}
              onRemoveBlock={onRemoveBlock}
              onRenameBlock={onRenameBlock}
              onRemoveVariable={onRemoveVariable}
              onRemoveNetwork={onRemoveNetwork}
              onDeepExplain={onDeepExplain}
            />
          )}

          {activeTab === "hmi" && (
            <HmiPane
              widgets={widgetList}
              devices={canvas.hmi_devices || []}
              focusWidgetId={focus?.kind === "hmi" ? focus.widgetId ?? null : null}
              onWidgetClick={(w) => onFocusChange({ kind: "hmi", widgetId: w.id })}
            />
          )}

          {activeTab === "vars" && (
            <VariableInspector
              report={crossReport}
              wiredTags={wiredTags}
              onJumpToRef={onJumpToRef}
              onCollapse={onClose}
            />
          )}

          {activeTab === "mermaid" &&
            (mermaidText ? (
              <div className="wsp-mermaid">
                <MermaidView code={mermaidText} />
              </div>
            ) : (
              <div className="wsp-empty">还没有时序图。对话里生成的 Mermaid 图会自动流到这里。</div>
            ))}

          {activeTab === "req" && (
            <div className="wsp-drawerhost">
              <RequirementCardDrawer
                open
                requirement={requirement}
                loading={requirementLoading}
                onEdit={onRequirementEdit}
                onConfirmIntent={onConfirmIntent}
                onClose={() => onActiveTabChange("graph")}
              />
            </div>
          )}

          {activeTab === "review" && (
            <div className="wsp-drawerhost">
              <ChangeReviewDrawer
                open
                changeId={reviewChangeId}
                requirement={reviewRequirement}
                onFocusTarget={onReviewFocusTarget}
                onClose={() => onActiveTabChange("graph")}
              />
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
