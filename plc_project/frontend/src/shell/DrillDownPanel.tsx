import { useEffect, useMemo, type FC } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  Position,
  type DefaultEdgeOptions,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { CanvasBlockData } from "../canvas/types";
import { explainBlock } from "../state/blockExplainer";
import "./drilldown.css";

/* ==========================================================================
   DrillDownPanel — 双击块下钻：块内网络流程图
   覆盖层模态：Esc / 遮罩点击 / × = onBack；
   网络按 id 升序纵向链式（NW1→NW2→…，y 间隔 130，x 居中 240），
   节点点击 = onJumpNetwork(网络 id)（父级聚焦 SCL 栏并关闭本面板）；
   DB / 空块不渲染 ReactFlow，显示居中提示。
   ========================================================================== */

export interface DrillDownPanelProps {
  /** 下钻的块（父层保证非空才渲染） */
  block: CanvasBlockData;
  /** 返回全局图 */
  onBack(): void;
  /** 点击某网络 → 父级聚焦 SCL 栏对应网络并关闭本面板 */
  onJumpNetwork(networkId: number): void;
}

/** 网络链式布局：x 固定 220 宽节点居中于 240，y 每级间隔 130 */
const CHAIN_X = 240;
const CHAIN_STEP_Y = 130;

/** 无摘要兜底文案 */
const NO_SUMMARY = "（无摘要）";

/** 空态文案 */
const EMPTY_TEXT = "该块没有可执行网络（数据块或尚未编写逻辑）";

/* —— 自定义节点数据（type alias 以满足 Record<string, unknown> 约束） —— */

type NwNodeData = {
  nwId: number;
  /** "NW1" 徽标 */
  label: string;
  title: string;
  summary: string;
  onJump: (networkId: number) => void;
  /** 链上是否存在上游（决定是否渲染顶部 target handle） */
  hasPrev: boolean;
  /** 链上是否存在下游（决定是否渲染底部 source handle） */
  hasNext: boolean;
};

type NwNode = Node<NwNodeData, "nw">;

/** 网络节点卡片：顶部 3px accent 条 + NW 徽标/标题（两行截断）+ 摘要（三行省略） */
function NwNodeCard({ data }: NodeProps<NwNode>) {
  return (
    <div className="dd-nw">
      <button
        type="button"
        className="dd-nw__btn"
        onClick={() => data.onJump(data.nwId)}
        title={`定位 ${data.label} 源码`}
      >
        <span className="dd-nw__head">
          <span className="dd-nw__no">{data.label}</span>
          <span className="dd-nw__title">{data.title}</span>
        </span>
        <span className="dd-nw__summary">{data.summary}</span>
      </button>
      {data.hasPrev ? <Handle type="target" position={Position.Top} isConnectable={false} /> : null}
      {data.hasNext ? <Handle type="source" position={Position.Bottom} isConnectable={false} /> : null}
    </div>
  );
}

const nodeTypes: NodeTypes = { nw: NwNodeCard };

/** 默认连线：var(--line-2) 1.5px + 箭头，无 label */
const defaultEdgeOptions: DefaultEdgeOptions = {
  style: { stroke: "var(--line-2)", strokeWidth: 1.5 },
  markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#c9ccc4" },
};

export const DrillDownPanel: FC<DrillDownPanelProps> = ({ block, onBack, onJumpNetwork }) => {
  /** 块解释（纯函数）：本面板只消费 networks（id/title/summary） */
  const networks = useMemo(
    () => explainBlock(block, { edges: [], widgets: [] }).networks,
    [block],
  );

  /** 纵向链式布局：按 id 升序，NW1→NW2→…；单网络/无网络均照常处理 */
  const { nodes, edges } = useMemo(() => {
    const sorted = [...networks].sort((a, b) => a.id - b.id);
    const ns: NwNode[] = sorted.map((nw, i) => ({
      id: `dd-n-${nw.id}`,
      type: "nw" as const,
      position: { x: CHAIN_X, y: i * CHAIN_STEP_Y },
      draggable: false,
      data: {
        nwId: nw.id,
        label: `NW${nw.id}`,
        title: nw.title,
        summary: nw.summary && nw.summary.trim() ? nw.summary.trim() : NO_SUMMARY,
        onJump: onJumpNetwork,
        hasPrev: i > 0,
        hasNext: i < sorted.length - 1,
      },
    }));
    const es: Edge[] = [];
    for (let i = 1; i < sorted.length; i++) {
      es.push({
        id: `dd-e-${sorted[i - 1].id}-${sorted[i].id}`,
        source: `dd-n-${sorted[i - 1].id}`,
        target: `dd-n-${sorted[i].id}`,
        type: "default",
      });
    }
    return { nodes: ns, edges: es };
  }, [networks, onJumpNetwork]);

  /** Esc = onBack */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  return (
    <div
      className="dd-overlay"
      onClick={e => {
        if (e.target === e.currentTarget) onBack();
      }}
    >
      <section
        className="dd-card"
        role="dialog"
        aria-modal="true"
        aria-label={`${block.block_type} ${block.name} 网络流程`}
      >
        <header className="dd-head">
          <button type="button" className="dd-back" onClick={onBack}>
            <span aria-hidden="true">←</span> 返回全局图
          </button>
          <div className="dd-title">
            <span className="dd-title__type">[{block.block_type}]</span>
            <span className="dd-title__name">&quot;{block.name}&quot;</span>
            <span className="dd-title__suffix">· 网络流程</span>
          </div>
          <button type="button" className="dd-close" onClick={onBack} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="dd-body">
          {networks.length === 0 ? (
            <div className="dd-empty">{EMPTY_TEXT}</div>
          ) : (
            <ReactFlowProvider>
              <ReactFlow<NwNode>
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                defaultEdgeOptions={defaultEdgeOptions}
                fitView
                fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
                minZoom={0.15}
                maxZoom={2}
                nodesDraggable={false}
                nodesConnectable={false}
                zoomOnDoubleClick={false}
                proOptions={{ hideAttribution: true }}
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={22}
                  size={1.4}
                  color="rgba(27,30,28,0.04)"
                />
              </ReactFlow>
            </ReactFlowProvider>
          )}
        </div>

        <footer className="dd-foot">
          <span className="dd-foot__stats">
            {networks.length} 个网络 · 语言 {block.language || "SCL"}
          </span>
          <span className="dd-foot__hint">点击网络可在 SCL 栏定位源码</span>
        </footer>
      </section>
    </div>
  );
};
