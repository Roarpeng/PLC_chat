/** 三视图画布：层级图可手动连线，步序/状态图按规格快照渲染（T04）。 */
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
import type { GFViews, GFEdge } from "../state/greenfield";

export interface GreenfieldPanelProps {
  views: GFViews | null;
  ir: Record<string, unknown> | null;
  legalKinds: string[];
  onConnect: (kind: string, connection: Connection) => void;
  onRemoveEdge: (edgeId: string) => void;
}

type ViewTab = "flow" | "seq" | "state";

const TABS: Array<{ key: ViewTab; label: string }> = [
  { key: "flow", label: "层级与连线" },
  { key: "seq", label: "步序与异常" },
  { key: "state", label: "模式与状态" },
];

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function buildNodes(ir: Record<string, unknown> | null): Node[] {
  if (!ir) return [];
  const groups: Array<{ key: string; label: string; color: string }> = [
    { key: "units", label: "工位", color: "#e6f1fb" },
    { key: "ems", label: "工序", color: "#e1f5ee" },
    { key: "control_nodes", label: "控制节点", color: "#faeeda" },
    { key: "cms", label: "设备", color: "#eeedfe" },
  ];
  const nodes: Node[] = [];
  let row = 0;
  for (const group of groups) {
    const items = asArray(ir[group.key]);
    items.forEach((item, index) => {
      nodes.push({
        id: String(item.id ?? `${group.key}_${index}`),
        position: { x: (index % 4) * 210, y: row * 115 },
        data: { label: String(item.business_label ?? item.name ?? item.id ?? "节点") },
        style: {
          background: group.color,
          border: "1px solid var(--line-2, #cbd5e1)",
          borderRadius: 8,
          padding: 8,
          fontSize: 12,
          width: 180,
        },
      });
    });
    if (items.length) row += 1;
  }
  for (const [index, id] of ["DB_UNITS", "IOMAP"].entries()) {
    nodes.push({
      id,
      position: { x: index * 210, y: row * 115 },
      data: { label: id === "DB_UNITS" ? "接口数据区（只读契约）" : "兼容映射边界（只读）" },
      style: { background: "#f1efe8", border: "1px dashed #888780", borderRadius: 8, padding: 8, fontSize: 12, width: 180 },
    });
  }
  return nodes;
}

function buildEdges(ir: Record<string, unknown> | null): Edge[] {
  return asArray(ir?.edges)
    .filter((edge) => {
      const mask = edge.view_mask;
      return !Array.isArray(mask) || mask.includes("flow");
    })
    .map((edge) => ({
      id: String(edge.id ?? ""),
      source: String(edge.src_id ?? ""),
      target: String(edge.dst_id ?? ""),
      label: String(edge.kind ?? ""),
      animated: edge.immutable === false,
      style: { stroke: edge.immutable === true ? "#94a3b8" : "#185fa5", strokeWidth: 1.5 },
    }));
}

export const GreenfieldPanel: React.FC<GreenfieldPanelProps> = ({
  views,
  ir,
  legalKinds,
  onConnect,
  onRemoveEdge,
}) => {
  const [tab, setTab] = useState<ViewTab>("flow");
  const [kind, setKind] = useState<string>(legalKinds[0] ?? "E_MSG_STEP");
  const hostRef = useRef<HTMLDivElement | null>(null);
  const nodes = useMemo(() => buildNodes(ir), [ir]);
  const edges = useMemo(() => buildEdges(ir), [ir]);
  const diagram = tab === "seq" ? views?.seq ?? "" : tab === "state" ? views?.state ?? "" : "";

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

  return (
    <section className="gf-panel" data-ui="greenfield-panel">
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
      </div>

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
            拖动节点端点即可连线；双击连线删除。非法连线会被即时拦截并说明原因。
          </div>
        </div>
      ) : (
        <div className="gf-diagram" ref={hostRef} />
      )}
    </section>
  );
}

export function toGfEdge(kind: string, connection: Connection): GFEdge {
  const src = connection.source ?? "";
  const dst = connection.target ?? "";
  return {
    id: `E_${kind}_${src}__${dst}`,
    kind,
    src_id: src,
    dst_id: dst,
    view_mask: ["flow"],
    origin: "user",
    label: kind,
  };
}
