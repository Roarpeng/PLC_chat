/**
 * 兼容薄壳：画布纯函数 → steps/canvasUtils；节点编辑 → engineering/NodeEditor；
 * 交付结果区 → engineering/DeliveryReview；阶段页 → steps/*。
 * 保留既有 import 契约（toGfEdge / NodeEditor / DeliveryReview），并提供可选的
 * 「工程视图」薄组件（硬件卡片 + Mermaid 切换）。重复工艺描述输入条已删除。
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import type { GFHardwareTopology, GFViews } from "../state/greenfield";
export { toGfEdge } from "./steps/canvasUtils";
export { NodeEditor } from "./engineering/NodeEditor";
export { DeliveryReview } from "./engineering/DeliveryReview";
export interface GreenfieldPanelProps {
  views?: GFViews | null;
  ir?: Record<string, unknown> | null;
  hardware?: GFHardwareTopology | null;
  legalKinds?: string[];
  busy?: boolean;
  projectId?: string;
}
type ViewTab = "step_flow" | "flow" | "seq" | "state";
const TABS: ReadonlyArray<{ key: ViewTab; label: string }> = [
  { key: "step_flow", label: "步序流程图" },
  { key: "flow", label: "层级与设备交互" },
  { key: "seq", label: "时序与异常联动" },
  { key: "state", label: "PackML 模式与状态机" },
];

export const GreenfieldPanel: React.FC<GreenfieldPanelProps> = ({
  views = null,
  hardware = null,
  busy = false,
}) => {
  const [tab, setTab] = useState<ViewTab>("step_flow");
  const [showSource, setShowSource] = useState<boolean>(false);
  const hostRef = useRef<HTMLDivElement | null>(null);

  const diagram = useMemo(() => {
    if (tab === "step_flow") return views?.step_flow?.mermaid || views?.flow || "";
    if (tab === "seq") return views?.seq ?? "";
    if (tab === "state") return views?.state ?? "";
    return views?.flow ?? "";
  }, [tab, views]);

  useEffect(() => {
    if (!diagram || tab === "flow") return;
    let cancelled = false;
    void (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
        const result = await mermaid.render(`gf-panel-${tab}-${Date.now()}`, diagram);
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

  const hwNodes = hardware?.nodes ?? [];

  return (
    <div className="gf-center-stack" data-ui="greenfield-panel">
      <section className="gf-hw-pane">
        <div className="gf-pane-header">
          <div className="gf-pane-header__title">
            <span className="gf-pane-step-tag">工程视图 · 逻辑设备拓扑</span>
            <span>共 {hwNodes.length} 个逻辑设备节点（只读概览）</span>
          </div>
        </div>
        <div className="gf-hw-grid">
          {hwNodes.map((node) => (
            <div className="gf-hw-card" key={node.id}>
              <div className="gf-hw-card__title">{node.label}</div>
              <div className="gf-hw-card__stats">
                {node.address_range && <span>地址段：{node.address_range}</span>}
                <span>协议：{node.protocol}</span>
              </div>
            </div>
          ))}
          {hwNodes.length === 0 && <div className="gf-muted">后端尚未返回逻辑设备节点。</div>}
        </div>
      </section>

      <section className="gf-logic-pane">
        <div className="gf-tabs">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={tab === item.key ? "gf-tab gf-tab--active" : "gf-tab"}
              disabled={busy}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            className={showSource ? "gf-tab gf-tab--active gf-tab--right" : "gf-tab gf-tab--right"}
            onClick={() => setShowSource((v) => !v)}
          >
            {showSource ? "收起图源码" : "查看图源码"}
          </button>
        </div>
        <div className="gf-logic-content">
          <div className="gf-diagram" ref={hostRef} />
          {showSource && <pre className="gf-mermaid-drawer__code">{diagram || "// 尚未生成图"}</pre>}
        </div>
      </section>
    </div>
  );
};
