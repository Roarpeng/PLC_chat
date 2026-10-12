import { autoLayoutKnowledge, type KnowledgeCanvasData, type KnowledgeNode } from "../KnowledgeCanvas";
import type { PlcJobDetail } from "../api";

export const emptyCanvas = (): KnowledgeCanvasData => ({ nodes: [], edges: [] });

export function canvasGalaxyScore(c: KnowledgeCanvasData | null | undefined): number {
  if (!c?.edges?.length) return 0;
  const want = new Set(["CALLS", "USES", "INSTANCE_OF", "TYPED_AS", "DEPENDS_ON"]);
  return c.edges.filter((e) => want.has(String(e.label || "")) || e.user_created).length;
}

export function normalizeCanvas(raw: unknown): KnowledgeCanvasData {
  const c = (raw || {}) as { nodes?: unknown[]; edges?: unknown[] };
  const nodes = (c.nodes || []).map((n) => {
    const row = n as Record<string, unknown>;
    return {
      id: String(row.id),
      label: String(row.label || row.id),
      summary: row.summary ? String(row.summary) : "",
      kind: row.kind ? String(row.kind) : "insight",
      x: Number(row.x ?? 80),
      y: Number(row.y ?? 80),
      export_status: row.export_status ? String(row.export_status) : undefined,
      source: (row.source || {}) as KnowledgeNode["source"],
    };
  });
  const edges = (c.edges || []).map((e) => {
    const row = e as Record<string, unknown>;
    return {
      id: String(row.id || `${row.source}-${row.target}`),
      source: String(row.source),
      target: String(row.target),
      label: row.label ? String(row.label) : "",
      user_created: Boolean(row.user_created),
    };
  });
  return { nodes, edges };
}

// Convert a PLC job into a bounded knowledge galaxy while preserving block/tag identity.
export function plcCanvasFromJob(detail: PlcJobDetail): KnowledgeCanvasData | null {
  const blocks = detail.blocks || [];
  const structureUnits = detail.structure?.units || [];
  if (!blocks.length && !(detail.logic_graph?.nodes || []).length && !structureUnits.length) {
    return null;
  }
  const projectId = `plc_proj_${detail.id}`;
  const nodes: KnowledgeNode[] = [
    {
      id: projectId,
      label: String(detail.project_name || detail.id).slice(0, 28),
      summary: `PLC · ${blocks.length} blocks`,
      kind: "plc_project",
      x: 40,
      y: 40,
      source: { type: "plc", plc_job_id: detail.id, project: detail.project_name },
    },
  ];
  const known = new Set(nodes.map((n) => n.label));
  const incompleteBlocks = blocks.filter((b) => {
    const st = String(b.status || "exported");
    return st === "failed" || st === "skipped" || st === "pending";
  });
  const exportedBlocks = blocks.filter((b) => !incompleteBlocks.includes(b));
  const canvasCap = 120;
  const exportedRoom = Math.max(0, canvasCap - incompleteBlocks.length);
  const shownBlocks = [...incompleteBlocks, ...exportedBlocks.slice(0, exportedRoom)];
  const hiddenExported = Math.max(0, exportedBlocks.length - exportedRoom);
  shownBlocks.forEach((b) => {
    const btype = String(b.type || "Block").toUpperCase();
    const inst = String(b.instance_of || "").trim();
    const nestDepth = Number(b.nest_depth || 0);
    const exportStatus = String(
      b.status ||
        (b.protected ? "skipped" : b.interface_only ? "pending" : "exported"),
    );
    const kind =
      btype === "OB"
        ? "plc_ob"
        : btype === "UDT"
          ? "plc_udt"
          : btype === "DB" && inst
            ? "plc_instance"
            : btype === "DB"
              ? "plc_db"
              : "plc_block";
    const bits = [btype];
    if (exportStatus && exportStatus !== "exported") bits.push(exportStatus);
    if (b.status_reason) bits.push(String(b.status_reason));
    if (b.language) bits.push(String(b.language));
    if (b.networks != null) bits.push(`${b.networks} 网络`);
    if (inst) bits.push(`实例←${inst}`);
    if (nestDepth > 0) bits.push(`嵌套深度 ${nestDepth}`);
    if (b.interface_only || (b.protected && !b.body_available)) {
      bits.push("接口开放·程序体不可用");
    } else if (b.protected) {
      bits.push("Know-how 保护");
    }
    nodes.push({
      id: `plc_b_${detail.id}_${b.name}`,
      label: b.name,
      summary: b.comment || bits.join(" · "),
      kind,
      export_status: exportStatus,
      x: 0,
      y: 0,
      source: {
        type: "plc",
        plc_job_id: detail.id,
        block_name: b.name,
        block_type: b.type,
        instance_of: inst || undefined,
        nest_depth: nestDepth > 0 ? nestDepth : undefined,
        entity_kind: inst ? "instance" : "block",
        project: detail.project_name,
        export_status: exportStatus,
      },
    });
    known.add(b.name);
  });
  if (hiddenExported > 0) {
    nodes.push({
      id: `plc_overflow_${detail.id}`,
      label: `+${hiddenExported} 已导出未上画布`,
      summary: "已导出单元因画布上限未绘制；失败/跳过单元不会被静默省略",
      kind: "plc_block",
      x: 0,
      y: 0,
      source: {
        type: "plc",
        plc_job_id: detail.id,
        project: detail.project_name,
        export_status: "exported",
      },
    });
  }
  for (const unit of structureUnits) {
    const name = String(unit.name || "").trim();
    if (!name || known.has(name)) continue;
    if (unit.kind !== "device" && unit.kind !== "block" && unit.kind !== "db" && unit.kind !== "udt") {
      continue;
    }
    known.add(name);
    const st = String(unit.status || "pending");
    const kind =
      unit.kind === "device"
        ? "plc_device"
        : unit.kind === "udt"
          ? "plc_udt"
          : unit.kind === "db"
            ? "plc_db"
            : "plc_block";
    nodes.push({
      id: `plc_u_${detail.id}_${name}`,
      label: name,
      summary: [st, unit.reason, unit.detail].filter(Boolean).join(" · ") || st,
      kind,
      x: 0,
      y: 0,
      source: {
        type: "plc",
        plc_job_id: detail.id,
        block_name: unit.kind === "device" ? undefined : name,
        block_type: unit.type,
        project: detail.project_name,
        export_status: st,
      },
    });
  }
  for (const n of detail.knowledge_graph?.nodes || []) {
    if (String(n.type || "") !== "Block") continue;
    const props = (n.props || {}) as Record<string, unknown>;
    const name = String(props.name || String(n.id || "").split("::").pop() || "");
    if (!name || known.has(name)) continue;
    known.add(name);
    const btype = String(props.block_type || "DB").toUpperCase();
    const external = Boolean(props.external);
    const nestDepth = Number(props.nest_depth || 0);
    nodes.push({
      id: `plc_b_${detail.id}_${name}`,
      label: name,
      summary: external
        ? `${btype} · 多实例/外部引用（图谱）`
        : Boolean(props.interface_only)
          ? `${btype} · 接口开放·程序体不可用`
          : `${btype} · 由依赖引用补全`,
      kind: external
        ? "plc_instance"
        : btype === "OB"
          ? "plc_ob"
          : btype === "UDT"
            ? "plc_udt"
            : btype === "DB"
              ? "plc_db"
              : "plc_block",
      x: 0,
      y: 0,
      export_status: external ? "pending" : "exported",
      source: {
        type: "plc",
        plc_job_id: detail.id,
        block_name: name,
        block_type: btype,
        entity_kind: external ? "instance" : "block",
        instance_of: external
          ? String(props.instance_of || props.InstanceOfName || "").trim() || undefined
          : undefined,
        nest_depth: nestDepth > 0 ? nestDepth : undefined,
        project: detail.project_name,
      },
    });
  }
  // Tag tables as entry points (individual tags appear when a block is selected)
  const tagTables = (detail.knowledge_graph?.nodes || []).filter(
    (n) => String(n.type || "") === "TagTable",
  );
  const tagCountByTable = new Map<string, number>();
  for (const e of detail.knowledge_graph?.edges || []) {
    if (String(e.type || "") !== "CONTAINS") continue;
    const src = String(e.source || "");
    const tgt = String(e.target || "");
    if (!src.startsWith("TagTable::") || !tgt.startsWith("Tag::")) continue;
    const tname = src.slice("TagTable::".length);
    tagCountByTable.set(tname, (tagCountByTable.get(tname) || 0) + 1);
  }
  tagTables.slice(0, 16).forEach((n, i) => {
    const props = (n.props || {}) as Record<string, unknown>;
    const name = String(props.name || String(n.id || "").split("::").pop() || `Tags${i}`);
    if (known.has(name)) return;
    known.add(name);
    const count = tagCountByTable.get(name) || 0;
    nodes.push({
      id: `plc_tt_${detail.id}_${name}`,
      label: name,
      summary: count ? `标签表 · ${count} 个 Tag（点程序块查看 IO 子图）` : "标签表",
      kind: "plc_tag",
      x: 0,
      y: 0,
      source: {
        type: "plc",
        quote: name,
        plc_job_id: detail.id,
        project: detail.project_name,
      },
    });
  });
  const byLabel = new Map<string, string>();
  nodes.forEach((n) => {
    byLabel.set(n.label, n.id);
    byLabel.set(`Block::${n.label}`, n.id);
    if (n.kind === "plc_tag") byLabel.set(`TagTable::${n.label}`, n.id);
  });
  // Knowledge galaxy: CALLS / USES / INSTANCE_OF / TYPED_AS / DEPENDS_ON (full KG)
  const kgEdges = (detail.knowledge_graph?.edges || []) as Array<{
    source?: string;
    target?: string;
    type?: string;
    weight?: number;
  }>;
  const lgFallback = (detail.logic_graph?.edges || []) as Array<{
    source?: string;
    target?: string;
    type?: string;
    weight?: number;
  }>;
  const rawEdges = (kgEdges.length ? kgEdges : lgFallback)
    .filter((e) => {
      const t = String(e.type || "");
      return (
        t === "CALLS" ||
        t === "USES" ||
        t === "INSTANCE_OF" ||
        t === "TYPED_AS" ||
        t === "DEPENDS_ON"
      );
    })
    .slice()
    .sort((a, b) => {
      const rank: Record<string, number> = {
        CALLS: 0,
        USES: 1,
        INSTANCE_OF: 2,
        TYPED_AS: 3,
        DEPENDS_ON: 4,
      };
      return (
        (rank[String(a.type)] ?? 9) - (rank[String(b.type)] ?? 9) ||
        Number(b.weight || 1) - Number(a.weight || 1)
      );
    });
  const edges: KnowledgeCanvasData["edges"] = [];
  const seen = new Set<string>();
  for (const e of rawEdges) {
    if (edges.length >= 180) break;
    const src = String(e.source || "");
    const tgt = String(e.target || "");
    const et = String(e.type || "DEPENDS_ON");
    const sid =
      byLabel.get(src) || byLabel.get(src.includes("::") ? src.split("::").pop() || "" : src);
    const tid =
      byLabel.get(tgt) || byLabel.get(tgt.includes("::") ? tgt.split("::").pop() || "" : tgt);
    if (!sid || !tid || sid === tid || seen.has(`${sid}|${tid}|${et}`)) continue;
    seen.add(`${sid}|${tid}|${et}`);
    edges.push({
      id: `dep_${edges.length}_${sid}`,
      source: sid,
      target: tid,
      label: et,
      user_created: false,
    });
  }
  return {
    nodes: autoLayoutKnowledge(nodes, edges),
    edges,
  };
}
