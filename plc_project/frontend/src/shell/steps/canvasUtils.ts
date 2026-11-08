/**
 * 画布纯函数投影：把后端 /state 的 IR 投影成 ReactFlow 的 nodes / edges，
 * 并把拖线动作翻译成后端 `POST /links` 认识的 GFEdge。
 *
 * 唯一真值在 /state：本模块只做只读投影，不做任何本地增删；新增 / 删除连线
 * 一律由 GreenfieldChannel 走 applyLinkPatch 后 refresh() 回读。
 */
import type { Connection, Edge, Node } from "@xyflow/react";
import type { GFEdge } from "../../state/greenfield";

export { validateConnection } from "./stepMachine";

/** 业务语言徽标；engineeringView=true 时才出现 AF 术语（仅工程视角面板）。 */
export const BUSINESS_TAG: Record<string, { business: string; af: string }> = {
  UN: { business: "工站", af: "Unit" },
  EM: { business: "执行单元", af: "EM" },
  CM: { business: "执行件", af: "CM" },
  CN: { business: "控制节点", af: "ControlNode" },
  ST: { business: "步序", af: "Step" },
  SF: { business: "安全", af: "Safety" },
};

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

/** IR → ReactFlow 节点（方角纸块 + 8px 连接桩母题由节点样式还原）。 */
export function buildNodes(
  ir: Record<string, unknown> | null,
  engineeringView: boolean = false,
): Node[] {
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
          fontSize: 13,
          fontFamily: "var(--font-ui)",
        },
      });
    });
  }
  return nodes;
}

/** IR.edges → ReactFlow 连线（含手动连线标记；selection 由 StepLink 本地视图位叠加）。 */
export function buildEdges(ir: Record<string, unknown> | null): Edge[] {
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

/** 拖线动作 → 后端 `add_edge` 负载。后端白名单仍是唯一裁定。 */
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
