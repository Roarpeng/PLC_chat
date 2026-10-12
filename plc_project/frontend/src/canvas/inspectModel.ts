import type { PlcCitation, PlcJobDetail } from "../../api";
import type { ChatMsg } from "../../workbench/model";

export type PlcGraphType =
  | "OB"
  | "FB"
  | "FC"
  | "GDB"
  | "IDB"
  | "UDT"
  | "TAG"
  | "PROJECT"
  | "OTHER";

export type InspectableNode = {
  id: string;
  label: string;
  summary?: string;
  kind?: string;
  export_status?: string;
  source?: {
    block_name?: string;
    block_type?: string;
    export_status?: string;
    instance_of?: string | null;
    nest_depth?: number | null;
    project?: string;
    quote?: string;
    entity_kind?: string;
  };
};

type KnowledgeGraph = {
  nodes?: Array<{ id?: string; type?: string; props?: Record<string, unknown> }>;
  edges?: Array<{ source?: string; target?: string; type?: string }>;
};

export type ExportStatusTone = "ok" | "warn" | "fail" | "unknown";

export type NodeInspectView = {
  id: string;
  name: string;
  typeLabel: string;
  typeGlyph: string;
  graphType: PlcGraphType;
  exportStatus: string;
  exportTone: ExportStatusTone;
  duty: string;
  ioLines: string[];
  meaning: string;
  statusLines: string[];
  noteKey: string;
};

export type InspectContext = {
  job?: PlcJobDetail | null;
  knowledgeGraph?: KnowledgeGraph | null;
  signalSummaries?: string[];
};

function resolveGraphType(n: InspectableNode): PlcGraphType {
  const kind = String(n.kind || "");
  if (kind === "plc_project") return "PROJECT";
  if (kind === "plc_tag") return "TAG";
  if (kind === "plc_udt") return "UDT";
  if (kind === "plc_instance" || n.source?.entity_kind === "instance") return "IDB";
  const raw = String(n.source?.block_type || "")
    .trim()
    .toUpperCase()
    .replace(/^SW\.BLOCKS\./, "");
  if (raw === "OB" || kind === "plc_ob") return "OB";
  if (raw === "FC") return "FC";
  if (raw === "FB") return "FB";
  if (raw === "UDT") return "UDT";
  if (raw === "DB" || kind === "plc_db") return n.source?.instance_of ? "IDB" : "GDB";
  if (kind === "plc_block") return raw ? "OTHER" : "FB";
  return "OTHER";
}

const TYPE_LABEL: Record<PlcGraphType, string> = {
  OB: "组织块 OB",
  FB: "功能块 FB",
  FC: "功能 FC",
  GDB: "全局 DB",
  IDB: "实例 DB",
  UDT: "UDT",
  TAG: "标签 / 信号",
  PROJECT: "工程",
  OTHER: "其他节点",
};

const TYPE_GLYPH: Record<PlcGraphType, string> = {
  OB: "OB",
  FB: "FB",
  FC: "FC",
  GDB: "DB",
  IDB: "ID",
  UDT: "U",
  TAG: "T",
  PROJECT: "P",
  OTHER: "·",
};

export function typeGlyph(gt: string): string {
  return TYPE_GLYPH[gt as PlcGraphType] || "·";
}

export function typeLabel(gt: PlcGraphType): string {
  return TYPE_LABEL[gt] || gt;
}

function oneLine(text: string, max = 72): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

function blockRecord(job: PlcJobDetail | null | undefined, name: string) {
  const key = name.trim();
  if (!key) return undefined;
  return (job?.blocks || []).find((b) => String(b.name || "") === key) as
    | (NonNullable<PlcJobDetail["blocks"]>[number] & { status?: string })
    | undefined;
}

export function resolveExportStatus(
  node: InspectableNode,
  job?: PlcJobDetail | null,
): { label: string; tone: ExportStatusTone } {
  const raw = String(
    node.export_status ||
      node.source?.export_status ||
      blockRecord(job, String(node.source?.block_name || node.label || ""))?.status ||
      "",
  )
    .trim()
    .toLowerCase();

  if (raw === "exported" || raw === "converted" || raw === "ok") {
    return { label: "已导出", tone: "ok" };
  }
  if (raw === "failed" || raw === "error") {
    return { label: "导出失败", tone: "fail" };
  }
  if (raw === "skipped" || raw === "protected") {
    return { label: raw === "protected" ? "Know-how 保护" : "已跳过", tone: "warn" };
  }
  if (raw === "pending" || raw === "interface_only" || raw === "not_exported") {
    return { label: raw === "interface_only" ? "仅接口" : "待导出", tone: "warn" };
  }
  if (raw === "not_indexed") {
    return { label: "未索引", tone: "warn" };
  }

  const name = String(node.source?.block_name || node.label || "");
  const block = blockRecord(job, name);
  if (block?.protected) return { label: "Know-how 保护", tone: "warn" };
  if (block?.interface_only || block?.body_available === false) {
    return { label: "仅接口 / 无程序体", tone: "warn" };
  }
  if (block?.is_safety) return { label: "Safety", tone: "warn" };
  if (job?.export_ready && block) return { label: "已导出", tone: "ok" };
  if (node.kind === "plc_tag") return { label: "信号", tone: "unknown" };
  return { label: "未知", tone: "unknown" };
}

function ioFromBlock(job: PlcJobDetail | null | undefined, name: string): string[] {
  const block = blockRecord(job, name);
  if (!block) return [];
  const lines: string[] = [];
  const push = (dir: string, items?: string[]) => {
    for (const item of items || []) {
      if (lines.length >= 3) return;
      const t = String(item || "").trim();
      if (t) lines.push(`${dir} ${t}`);
    }
  };
  push("IN", block.inputs);
  push("OUT", block.outputs);
  push("INOUT", block.inouts);
  return lines;
}

function ioFromKnowledgeGraph(
  graph: KnowledgeGraph | null | undefined,
  node: InspectableNode,
): string[] {
  if (!graph) return [];
  const blockName = String(node.source?.block_name || node.label || "").trim();
  if (!blockName) return [];
  const bid = `Block::${blockName}`;
  const rows: string[] = [];
  for (const e of graph.edges || []) {
    const et = String(e.type || "");
    if (et !== "READS" && et !== "WRITES") continue;
    if (String(e.source || "") !== bid) continue;
    const tid = String(e.target || "");
    const name = tid.startsWith("Tag::") ? tid.slice(5) : tid.split("::").pop() || tid;
    if (!name) continue;
    const line = `${et === "READS" ? "读" : "写"} ${name}`;
    if (!rows.includes(line)) rows.push(line);
    if (rows.length >= 3) break;
  }
  return rows;
}

export function inspectNode(node: InspectableNode, ctx: InspectContext = {}): NodeInspectView {
  const gt = resolveGraphType(node);
  const name = String(node.label || node.source?.block_name || node.id);
  const blockName = String(node.source?.block_name || name);
  const exportInfo = resolveExportStatus(node, ctx.job);
  const summary = String(node.summary || node.source?.quote || "").trim();
  const ioLines = (
    ctx.signalSummaries?.length
      ? ctx.signalSummaries
      : ioFromBlock(ctx.job, blockName).concat(ioFromKnowledgeGraph(ctx.knowledgeGraph, node))
  )
    .map((line) => oneLine(String(line), 56))
    .filter(Boolean)
    .slice(0, 3);

  const statusLines = [
    `导出 ${exportInfo.label}`,
    node.source?.block_type ? `类型 ${node.source.block_type}` : `类型 ${TYPE_LABEL[gt]}`,
    node.source?.instance_of ? `实例 ← ${node.source.instance_of}` : "",
    node.source?.nest_depth ? `嵌套深度 ${node.source.nest_depth}` : "",
    node.source?.project ? `工程 ${node.source.project}` : "",
  ].filter(Boolean);

  return {
    id: node.id,
    name,
    typeLabel: TYPE_LABEL[gt],
    typeGlyph: TYPE_GLYPH[gt],
    graphType: gt,
    exportStatus: exportInfo.label,
    exportTone: exportInfo.tone,
    duty: oneLine(summary || `${TYPE_LABEL[gt]} · 职责未标注`, 88),
    ioLines,
    meaning: summary || "尚无职责说明。可在人注中补一句工程师口径。",
    statusLines,
    noteKey: `${ctx.job?.id || "local"}:${node.id}`,
  };
}

export function citationLocator(c: PlcCitation): string {
  const locator = String(c.locator || "").trim();
  if (locator) return locator;
  return [c.network, typeof c.line === "number" ? `line ${c.line}` : ""]
    .filter(Boolean)
    .join(" / ");
}

export function citationSnippet(c: PlcCitation): string {
  return String(c.snippet || c.evidence || "").trim();
}

export function citationsForNode(
  citations: PlcCitation[] | undefined,
  node: InspectableNode | null,
): PlcCitation[] {
  if (!citations?.length || !node) return [];
  const names = new Set(
    [node.id, node.label, node.source?.block_name].map((s) => String(s || "").trim()).filter(Boolean),
  );
  return citations.filter((c) => {
    if (c.nodeId && c.nodeId === node.id) return true;
    const block = String(c.block || "").trim();
    const target = String(c.target || "").trim();
    return (block && names.has(block)) || (target && names.has(target));
  });
}

export function nodeScopedMessages(messages: ChatMsg[], node: InspectableNode | null): ChatMsg[] {
  if (!node) return [];
  const labels = new Set(
    [node.label, node.source?.block_name].map((s) => String(s || "").trim()).filter(Boolean),
  );
  return messages.filter((m) => m.scopeLabel && labels.has(m.scopeLabel));
}

export function collectNodeCitations(
  messages: ChatMsg[],
  job: PlcJobDetail | null | undefined,
  node: InspectableNode | null,
): PlcCitation[] {
  if (!node) return [];
  const fromChat = messages.flatMap((m) => m.citations || []);
  const fromJob = (job?.chat || []).flatMap((c) => c.citations || []);
  const seen = new Set<string>();
  const out: PlcCitation[] = [];
  for (const c of citationsForNode([...fromChat, ...fromJob], node)) {
    const key = [c.block, citationLocator(c), citationSnippet(c), c.nodeId].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(c);
  }
  return out;
}
