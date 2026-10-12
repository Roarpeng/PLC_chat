import type { CanvasFocusRequest } from "../../KnowledgeCanvas";

/** Brief / device-card → canvas. Default is inspect-only; `ask` opens Workbench. */
export type CanvasJumpIntent = {
  nodeId?: string;
  blockName?: string;
  /** Tag / sensor / device symbol — resolved like a block label. */
  symbol?: string;
  /** Open the right-side Workbench (double-click / 「问这节点」). */
  ask?: boolean;
};

export function canvasFocusFromJump(
  intent: CanvasJumpIntent,
  key = Date.now(),
): CanvasFocusRequest {
  const token = String(intent.blockName || intent.symbol || "").trim();
  return {
    key,
    nodeId: intent.nodeId,
    blockName: token || undefined,
    ask: Boolean(intent.ask),
  };
}

export function jumpToken(intent: CanvasJumpIntent): string {
  return String(intent.nodeId || intent.blockName || intent.symbol || "").trim();
}
