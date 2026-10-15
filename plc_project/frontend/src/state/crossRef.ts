import type { CanvasStateData } from "../canvas/types";

/** 变量定义：key = `${blockName}.${name}` */
export interface VarDef {
  key: string;
  blockName: string;
  name: string;
  section: string;
  dataType: string;
  comment?: string;
}

/** 对某变量的一次引用（SCL 网络 或 HMI 元件） */
export interface VarRef {
  kind: "network" | "hmi";
  blockName?: string;
  networkId?: number;
  widgetId?: string;
  label: string;
}

/** 一个变量 = 定义 + 全部引用 */
export interface VarEntry {
  def: VarDef;
  refs: VarRef[];
}

export interface CrossRefReport {
  /** 全部变量条目，按块/接口插入序 */
  entries: VarEntry[];
  /** HMI 绑定了不存在的变量 */
  hmiUnbound: { widgetId: string; widgetTitle: string; tag: string }[];
  /** SCL 中引用了不存在的变量（局部 #X 或全局 "Blk".X），同一网络内重复表达式去重 */
  unknownRefs: { blockName: string; networkId: number; expr: string }[];
  /** 块级引用边：from(引用块) → to(被引用块)，按 (from,to) 去重并累计引用次数 */
  blockEdges: { from: string; to: string; count: number }[];
  stats: { total: number; unused: number; undefined: number };
}

/** 局部引用：#Var */
const LOCAL_REF_RE = /#([A-Za-z_][A-Za-z0-9_]*)/g;
/** 全局引用："Blk".Var */
const GLOBAL_REF_RE = /"([A-Za-z_][A-Za-z0-9_]*)"\.([A-Za-z_][A-Za-z0-9_]*)/g;

/**
 * 变量交叉引用分析（纯函数）：
 * - 定义来自各块 interface；同块内重名变量合并到同一 entry（refs 合并）。
 * - 网络扫描 scl_text：#X → 本块变量；"Blk".X → 全局变量；解析不到则记 unknownRefs。
 * - HMI 扫描 plc_tag（形如 "MainDB.StartCmd"）；解析不到则记 hmiUnbound。
 */
export function analyzeCanvas(canvas: CanvasStateData): CrossRefReport {
  const entryMap = new Map<string, VarEntry>();

  // 1) 定义：遍历块 interface，按插入序生成 entry
  for (const block of Object.values(canvas.blocks ?? {})) {
    for (const variable of block.interface ?? []) {
      const key = block.name + "." + variable.name;
      if (!entryMap.has(key)) {
        entryMap.set(key, {
          def: {
            key,
            blockName: block.name,
            name: variable.name,
            section: variable.section,
            dataType: variable.data_type,
            comment: variable.comment,
          },
          refs: [],
        });
      }
    }
  }

  const unknownRefs: CrossRefReport["unknownRefs"] = [];
  const unknownSeen = new Set<string>();
  const edgeMap = new Map<string, { from: string; to: string; count: number }>();

  const reportUnknown = (blockName: string, networkId: number, expr: string) => {
    const dedupeKey = blockName + "|" + networkId + "|" + expr;
    if (unknownSeen.has(dedupeKey)) return;
    unknownSeen.add(dedupeKey);
    unknownRefs.push({ blockName, networkId, expr });
  };

  // 2) 网络引用：扫描每块每个网络的 scl_text
  for (const block of Object.values(canvas.blocks ?? {})) {
    for (const network of block.networks ?? []) {
      const scl = network.scl_text ?? "";

      // 2a) 局部引用 #X → 该块.名
      for (const match of scl.matchAll(LOCAL_REF_RE)) {
        const entry = entryMap.get(block.name + "." + match[1]);
        if (entry) {
          entry.refs.push({
            kind: "network",
            blockName: block.name,
            networkId: network.id,
            label: block.name + " · NW" + network.id,
          });
        } else {
          reportUnknown(block.name, network.id, match[0]);
        }
      }

      // 2b) 全局引用 "Blk".Var → 块名.变量名
      for (const match of scl.matchAll(GLOBAL_REF_RE)) {
        const entry = entryMap.get(match[1] + "." + match[2]);
        if (entry) {
          entry.refs.push({
            kind: "network",
            blockName: block.name,
            networkId: network.id,
            label: block.name + " · NW" + network.id,
          });
        } else {
          reportUnknown(block.name, network.id, match[0]);
        }

        // 块级引用边聚合（仅全局网络引用产生跨块边）
        const edgeKey = block.name + "\u2192" + match[1];
        const edge = edgeMap.get(edgeKey);
        if (edge) {
          edge.count += 1;
        } else {
          edgeMap.set(edgeKey, { from: block.name, to: match[1], count: 1 });
        }
      }
    }
  }

  // 3) HMI 引用：plc_tag 形如 "MainDB.StartCmd"（兼容带引号写法 "MainDB".StartCmd）
  const hmiUnbound: CrossRefReport["hmiUnbound"] = [];
  for (const widget of Object.values(canvas.hmi_widgets ?? {})) {
    const tag = String(widget.plc_tag ?? "").replace(/"/g, "").trim();
    if (!tag) continue; // 未绑定变量的元件不算 "绑定了不存在的变量"
    const entry = entryMap.get(tag);
    if (entry) {
      entry.refs.push({ kind: "hmi", widgetId: widget.id, label: "HMI · " + widget.title });
    } else {
      hmiUnbound.push({ widgetId: widget.id, widgetTitle: widget.title, tag: widget.plc_tag });
    }
  }

  // 4) 汇总
  const entries = Array.from(entryMap.values());
  const unused = entries.reduce((acc, entry) => acc + (entry.refs.length === 0 ? 1 : 0), 0);

  return {
    entries,
    hmiUnbound,
    unknownRefs,
    blockEdges: Array.from(edgeMap.values()),
    stats: {
      total: entries.length,
      unused,
      undefined: hmiUnbound.length + unknownRefs.length,
    },
  };
}
