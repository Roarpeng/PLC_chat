import type {
  CanvasBlockData,
  CanvasHmiWidgetData,
  CanvasNetworkData,
  CanvasVariableData,
} from "../canvas/types";

/* ------------------------------------------------------------------ */
/* 契约类型（UI 按此消费）                                               */
/* ------------------------------------------------------------------ */

export interface NetworkSummary {
  id: number;
  title: string;
  /** 1-2 句中文 */
  summary: string;
}

export interface BlockExplanation {
  /** 一句话作用（≤30 字，卡片标题） */
  headline: string;
  /** 块类型职责 + 注释（2-3 句） */
  role: string;
  signals: {
    /** 元素格式 "Name (Type) 注释"，注释无则省略 */
    inputs: string[];
    outputs: string[];
    inOuts: string[];
    statics: string[];
  };
  /** DB 块为空数组 */
  networks: NetworkSummary[];
  /** 本块 SCL 中全局引用的目标块名（去重，∩ edges 块名全集） */
  callsBlocks: string[];
  /** edges 中指向本块的来源块名（去重） */
  calledByBlocks: string[];
  /** 绑定本块变量的 HMI 控件标题（"HMI · 标题"） */
  hmiBound: string[];
  /** 识别出的模式标签，供 UI 做徽标 */
  keywords: string[];
}

/* ------------------------------------------------------------------ */
/* 基础常量与工具                                                       */
/* ------------------------------------------------------------------ */

const HEADLINE_MAX = 30;

/** 局部引用：#Var */
const LOCAL_REF_RE = /#([A-Za-z_][A-Za-z0-9_]*)/g;
/** 全局引用："Blk".Var */
const GLOBAL_REF_RE = /"([A-Za-z_][A-Za-z0-9_]*)"\.([A-Za-z_][A-Za-z0-9_]*)/g;
/** 全局引用（仅块名）：`"Blk".` */
const GLOBAL_BLOCK_REF_RE = /"([A-Za-z_][A-Za-z0-9_]*)"\./g;
/** IF/ELSIF ... THEN 之间的条件文本（惰性匹配到最近的 THEN） */
const CONDITION_RE = /\b(?:IF|ELSIF)\b([\s\S]*?)\bTHEN\b/g;

const TYPE_ROLES: Record<CanvasBlockData["block_type"], string> = {
  OB: "循环调度入口，按扫描周期执行，是整个程序的组织块",
  FB: "带静态记忆的工艺功能块：内部状态跨扫描周期保持，适合自锁、模式机等有状态控制",
  FC: "无状态函数块：纯输入→输出变换，不带记忆",
  DB: "全局数据寄存表：为逻辑块提供参数与状态存取",
  UDT: "用户自定义数据类型（UDT）：定义可复用的结构化数据模板，不参与扫描执行",
};

const TYPE_NOUNS: Record<CanvasBlockData["block_type"], string> = {
  OB: "组织块",
  FB: "功能块",
  FC: "函数",
  DB: "数据块",
  UDT: "数据类型",
};

const TYPE_DEFAULT_HEADLINE: Record<CanvasBlockData["block_type"], string> = {
  OB: "主调度组织块",
  FB: "工艺功能块",
  FC: "逻辑函数块",
  DB: "全局数据寄存块",
  UDT: "自定义数据类型",
};

/** 截断到 max 字（超出时以 … 结尾，保证长度 ≤ max） */
function clip(text: string, max: number): string {
  const t = text.trim();
  return t.length <= max ? t : t.slice(0, max - 1) + "…";
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 本块全部 SCL 文本：各网络 scl_text + 块级 scl_body（若有） */
function combinedScl(block: CanvasBlockData): string {
  const parts: string[] = [];
  for (const nw of block.networks ?? []) {
    if (nw.scl_text) parts.push(nw.scl_text);
  }
  if (block.scl_body) parts.push(block.scl_body);
  return parts.join("\n");
}

/** 提取 IF/ELSIF ... THEN 的条件片段（matchEach 内部克隆正则，无 lastIndex 污染） */
function extractConditions(scl: string): string[] {
  const out: string[] = [];
  for (const m of scl.matchAll(CONDITION_RE)) out.push(m[1]);
  return out;
}

interface SignalBuckets {
  inputs: string[];
  outputs: string[];
  inOuts: string[];
  statics: string[];
}

/** section 归桶：VAR_INPUT→inputs、VAR_OUTPUT→outputs、VAR_IN_OUT→inOuts、其余→statics */
function bucketOf(section: string): keyof SignalBuckets {
  const s = String(section ?? "").toUpperCase();
  if (s === "VAR_INPUT" || s === "INPUT") return "inputs";
  if (s === "VAR_OUTPUT" || s === "OUTPUT") return "outputs";
  if (s === "VAR_IN_OUT" || s === "VAR_INOUT" || s === "IN_OUT" || s === "INOUT") return "inOuts";
  return "statics";
}

/* ------------------------------------------------------------------ */
/* keywords 模式识别                                                    */
/* ------------------------------------------------------------------ */

const KEYWORD_ORDER = ["自锁", "互锁", "急停", "定时", "计数", "手自动", "调速", "报警"];

/** 纯文本规则（扫描 SCL 文本；均不带 /g，test 无状态） */
const TEXT_KEYWORD_RULES: { label: string; re: RegExp }[] = [
  { label: "定时", re: /\b(?:TON|TOF|TP|IEC_TIMER)\b|定时/i },
  { label: "计数", re: /\b(?:CTU|CTD|CTUD|IEC_COUNTER)\b|计数|counter/i },
  { label: "手自动", re: /manual|auto|模式|mode/i },
  { label: "调速", re: /speed|rpm|变频|调速/i },
  { label: "报警", re: /alarm|报警|warning/i },
];

/** 接口类型规则（TON/IEC_TIMER 等通常只出现在变量声明里） */
const TYPE_KEYWORD_RULES: { label: string; re: RegExp }[] = [
  { label: "定时", re: /\b(?:TON|TOF|TP|IEC_TIMER)\b/i },
  { label: "计数", re: /\b(?:CTU|CTD|CTUD|IEC_COUNTER)\b/i },
];

/** 自锁：某 VAR_OUTPUT/VAR_STAT 名既被 := TRUE 赋值，又出现在条件判断中 */
function detectSelfHold(block: CanvasBlockData, scl: string, conditions: string[]): boolean {
  const latchable = new Set(
    (block.interface ?? [])
      .filter(v => {
        const b = bucketOf(v.section);
        return b === "outputs" || b === "statics";
      })
      .map(v => v.name),
  );
  for (const name of latchable) {
    const assignedTrue = new RegExp("#" + escapeRe(name) + "\\s*:=\\s*[^;]*\\bTRUE\\b", "i").test(scl);
    if (!assignedTrue) continue;
    if (conditions.some(c => c.includes("#" + name))) return true;
  }
  return false;
}

/** 互锁/联锁：文本标记，或单个 IF 条件里 ≥2 个 AND 连接的输入变量 */
function detectInterlock(scl: string, conditions: string[]): boolean {
  if (/互锁|联锁|interlock/i.test(scl)) return true;
  for (const cond of conditions) {
    if (!/\bAND\b/i.test(cond)) continue;
    const vars = new Set<string>();
    for (const m of cond.matchAll(LOCAL_REF_RE)) vars.add(m[1]);
    if (vars.size >= 2) return true;
  }
  return false;
}

/** 急停/安全：含 急停/EStop/EMERGENCY/Safety/Fault 且存在条件块内的 := FALSE 复位逻辑 */
function detectEStop(scl: string, conditions: string[]): boolean {
  if (!/急停|estop|emergency|safety|\bfault\b/i.test(scl)) return false;
  return /:=\s*FALSE\b/i.test(scl) && conditions.length > 0;
}

function detectKeywords(block: CanvasBlockData, scl: string, conditions: string[]): string[] {
  const found = new Set<string>();
  if (detectSelfHold(block, scl, conditions)) found.add("自锁");
  if (detectInterlock(scl, conditions)) found.add("互锁");
  if (detectEStop(scl, conditions)) found.add("急停");
  for (const rule of TEXT_KEYWORD_RULES) {
    if (rule.re.test(scl)) found.add(rule.label);
  }
  const joinedTypes = (block.interface ?? []).map(v => String(v.data_type ?? "")).join(" ");
  for (const rule of TYPE_KEYWORD_RULES) {
    if (rule.re.test(joinedTypes)) found.add(rule.label);
  }
  return KEYWORD_ORDER.filter(k => found.has(k));
}

/* ------------------------------------------------------------------ */
/* headline / role                                                      */
/* ------------------------------------------------------------------ */

function buildHeadline(block: CanvasBlockData, keywords: string[]): string {
  const comment = String(block.comment ?? "").trim();
  if (block.block_type === "DB") {
    const suffix = "，承载 " + (block.interface ?? []).length + " 个工艺信号";
    if (!comment) return TYPE_DEFAULT_HEADLINE.DB + suffix;
    return comment.length + suffix.length <= HEADLINE_MAX
      ? comment + suffix
      : clip(comment, HEADLINE_MAX);
  }
  if (comment) return clip(comment, HEADLINE_MAX);
  if (keywords.length > 0) {
    const shown = keywords.slice(0, 4);
    const tail = keywords.length > 4 ? "等" : "";
    return clip("含" + shown.join("、") + tail + "逻辑的" + TYPE_NOUNS[block.block_type], HEADLINE_MAX);
  }
  return TYPE_DEFAULT_HEADLINE[block.block_type] ?? "逻辑块";
}

/** 接口/网络规模描述（作为 role 的补充句） */
function scaleSentence(block: CanvasBlockData): string | null {
  const iface = block.interface ?? [];
  if (block.block_type === "DB" || block.block_type === "UDT") {
    return iface.length ? "共 " + iface.length + " 个数据字段" : null;
  }
  const buckets = splitSignals(block);
  const groups: string[] = [];
  if (buckets.inputs.length) groups.push("输入 " + buckets.inputs.length);
  if (buckets.outputs.length) groups.push("输出 " + buckets.outputs.length);
  if (buckets.inOuts.length) groups.push("InOut " + buckets.inOuts.length);
  if (buckets.statics.length) groups.push("静态 " + buckets.statics.length);
  const nwCount = (block.networks ?? []).length;
  if (groups.length && nwCount) return "接口含 " + groups.join("、") + "，组织为 " + nwCount + " 个逻辑网络";
  if (groups.length) return "接口含 " + groups.join("、");
  if (nwCount) return "逻辑组织为 " + nwCount + " 个网络";
  return null;
}

function buildRole(block: CanvasBlockData): string {
  const sentences: string[] = [TYPE_ROLES[block.block_type] ?? "PLC 逻辑块"];
  const comment = String(block.comment ?? "").trim();
  if (comment) sentences.push("注释：" + comment);
  const scale = scaleSentence(block);
  if (scale) sentences.push(scale);
  if (block.status === "error") sentences.push("注意：当前存在编译诊断待处理");
  return sentences.join("。") + "。";
}

/* ------------------------------------------------------------------ */
/* signals                                                              */
/* ------------------------------------------------------------------ */

function formatSignal(v: CanvasVariableData): string {
  const base = v.name + " (" + v.data_type + ")";
  const comment = String(v.comment ?? "").trim();
  return comment ? base + " " + comment : base;
}

function splitSignals(block: CanvasBlockData): SignalBuckets {
  const signals: SignalBuckets = { inputs: [], outputs: [], inOuts: [], statics: [] };
  for (const v of block.interface ?? []) {
    signals[bucketOf(v.section)].push(formatSignal(v));
  }
  return signals;
}

/* ------------------------------------------------------------------ */
/* 网络摘要                                                             */
/* ------------------------------------------------------------------ */

function summarizeNetworks(block: CanvasBlockData): NetworkSummary[] {
  if (block.block_type === "DB") return [];
  return (block.networks ?? []).map((nw: CanvasNetworkData) => ({
    id: nw.id,
    title: String(nw.title ?? "").trim() || "网络 " + nw.id,
    summary: summarizeNetwork(block, nw),
  }));
}

function summarizeNetwork(block: CanvasBlockData, nw: CanvasNetworkData): string {
  const scl = String(nw.scl_text ?? "");
  if (!scl.trim()) return "空网络（尚未编写逻辑）";
  if (scl.trimStart().startsWith("// 图形网络") || scl.includes("引用符号：")) {
    return summarizeGraphicNetwork(scl);
  }
  return summarizeSclNetwork(block, scl);
}

/** 图形网络：解析"引用符号："后的符号清单 */
function summarizeGraphicNetwork(scl: string): string {
  const m = scl.match(/引用符号[：:]\s*([^\r\n]*)/);
  const symbols = m
    ? m[1]
        .split(/[，,、;；]\s*/)
        .map(s => s.trim())
        .filter(Boolean)
    : [];
  if (symbols.length) {
    const shown =
      symbols.length > 8
        ? symbols.slice(0, 8).join("、") + " 等 " + symbols.length + " 个符号"
        : symbols.join("、");
    return "图形逻辑网络（LAD/FBD），信号流涉及：" + shown;
  }
  return "图形逻辑网络（LAD/FBD），梯形图/功能图连线逻辑，源码以博图工程为准";
}

function firstLocalRef(texts: string[], filter?: (name: string) => boolean): string | undefined {
  for (const t of texts) {
    for (const m of t.matchAll(LOCAL_REF_RE)) {
      if (!filter || filter(m[1])) return m[1];
    }
  }
  return undefined;
}

/** "与 X 块交互（读取 a，写入 b）" */
function describeGlobalInteraction(scl: string): string {
  const writes = new Map<string, Set<string>>();
  for (const m of scl.matchAll(/"([A-Za-z_][A-Za-z0-9_]*)"\.([A-Za-z_][A-Za-z0-9_]*)\s*:=/g)) {
    if (!writes.has(m[1])) writes.set(m[1], new Set());
    writes.get(m[1])!.add(m[2]);
  }
  const reads = new Map<string, Set<string>>();
  for (const m of scl.matchAll(GLOBAL_REF_RE)) {
    if (writes.get(m[1])?.has(m[2])) continue;
    if (!reads.has(m[1])) reads.set(m[1], new Set());
    reads.get(m[1])!.add(m[2]);
  }
  const blockNames: string[] = [];
  for (const name of [...writes.keys(), ...reads.keys()]) {
    if (!blockNames.includes(name)) blockNames.push(name);
  }
  if (!blockNames.length) return "";
  const capVars = (vars: string[]): string =>
    vars.length <= 3 ? vars.join("、") : vars.slice(0, 3).join("、") + " 等 " + vars.length + " 个变量";
  const phrases = blockNames.slice(0, 2).map(b => {
    const parts: string[] = [];
    const r = [...(reads.get(b) ?? [])];
    const w = [...(writes.get(b) ?? [])];
    if (r.length) parts.push("读取 " + capVars(r));
    if (w.length) parts.push("写入 " + capVars(w));
    return "与 " + b + " 块交互（" + (parts.join("，") || "引用若干变量") + "）";
  });
  const more = blockNames.length > 2 ? "，另涉及 " + (blockNames.length - 2) + " 个块" : "";
  return phrases.join("，") + more;
}

function summarizeSclNetwork(block: CanvasBlockData, scl: string): string {
  const conditions = extractConditions(scl);
  const branchCount = (scl.match(/\b(?:IF|ELSIF)\b/g) || []).length;

  // 赋值目标 #X := …，以及置位（:= TRUE）/ 复位（:= FALSE）
  const targets: string[] = [];
  const setNames: string[] = [];
  const resetNames: string[] = [];
  for (const m of scl.matchAll(/#([A-Za-z_][A-Za-z0-9_]*)\s*:=\s*([^;\n]*)/g)) {
    const name = m[1];
    if (!targets.includes(name)) targets.push(name);
    const rhs = m[2].trim().toUpperCase();
    if (rhs.startsWith("TRUE")) {
      if (!setNames.includes(name)) setNames.push(name);
    } else if (rhs.startsWith("FALSE")) {
      if (!resetNames.includes(name)) resetNames.push(name);
    }
  }

  // 主要输入：条件里首个 VAR_INPUT（退化为条件内首个局部引用）
  const inputNames = new Set<string>();
  const outputNames = new Set<string>();
  for (const v of block.interface ?? []) {
    const b = bucketOf(v.section);
    if (b === "inputs") inputNames.add(v.name);
    else if (b === "outputs") outputNames.add(v.name);
  }
  const mainInput =
    firstLocalRef(conditions, n => inputNames.has(n)) ?? firstLocalRef(conditions);
  // 主要输出：首个 VAR_OUTPUT 赋值目标（退化为首个赋值目标）
  const mainOutput = targets.find(t => outputNames.has(t)) ?? targets[0];

  const actionParts: string[] = [];
  const tailParts: string[] = [];
  const lead = setNames[0];
  if (lead) {
    const verb = outputNames.has(lead) ? "置位" : "置位内部状态";
    const seg = mainInput ? "当 #" + mainInput + " 条件成立时" + verb + " #" + lead : verb + " #" + lead;
    const driven = mainOutput && mainOutput !== lead ? "，并驱动 #" + mainOutput : "";
    actionParts.push(seg + driven);
    if (resetNames.length) tailParts.push("停止条件满足时复位 #" + resetNames[0]);
  } else if (mainInput && mainOutput && resetNames.includes(mainOutput)) {
    actionParts.push("当 #" + mainInput + " 条件成立时复位 #" + mainOutput);
  } else if (mainInput && mainOutput) {
    actionParts.push("当 #" + mainInput + " 条件成立时驱动 #" + mainOutput);
  } else if (targets.length) {
    const list = targets.length <= 6 ? targets.map(t => "#" + t).join("、") : targets.length + " 个信号";
    actionParts.push("对 " + list + " 赋值");
  }

  const parts2: string[] = [];
  if (branchCount > 0) {
    const ops: string[] = [];
    if (conditions.some(c => /\bAND\b/i.test(c))) ops.push("与");
    if (conditions.some(c => /\bOR\b/i.test(c))) ops.push("或");
    if (conditions.some(c => /\bNOT\b/i.test(c))) ops.push("非");
    parts2.push(
      ops.length
        ? "含 " + branchCount + " 个条件分支，条件组合包含 " + ops.join("、") + " 逻辑"
        : "含 " + branchCount + " 个条件分支",
    );
  }
  const interaction = describeGlobalInteraction(scl);
  if (interaction) parts2.push(interaction);

  const sentence1 = actionParts.concat(tailParts).join("；");
  const sentence2 = parts2.join("，");
  if (!sentence1 && !sentence2) return "纯顺序赋值逻辑，无分支与跨块交互";
  return [sentence1, sentence2].filter(Boolean).join("。") + "。";
}

/* ------------------------------------------------------------------ */
/* 关系：calls / calledBy / hmiBound                                    */
/* ------------------------------------------------------------------ */

function collectCallsBlocks(
  block: CanvasBlockData,
  scl: string,
  edges: { from: string; to: string; count: number }[],
): string[] {
  const known = new Set<string>();
  for (const e of edges ?? []) {
    known.add(e.from);
    known.add(e.to);
  }
  const out: string[] = [];
  for (const m of scl.matchAll(GLOBAL_BLOCK_REF_RE)) {
    const name = m[1];
    if (name === block.name || !known.has(name) || out.includes(name)) continue;
    out.push(name);
  }
  return out;
}

function collectCalledBy(block: CanvasBlockData, edges: { from: string; to: string }[]): string[] {
  const out: string[] = [];
  for (const e of edges ?? []) {
    if (e.to === block.name && !out.includes(e.from)) out.push(e.from);
  }
  return out;
}

function collectHmiBound(block: CanvasBlockData, widgets: CanvasHmiWidgetData[]): string[] {
  const prefix = block.name.toLowerCase() + ".";
  const out: string[] = [];
  for (const w of widgets ?? []) {
    const tag = String(w.plc_tag ?? "")
      .replace(/"/g, "")
      .trim()
      .toLowerCase();
    if (tag.startsWith(prefix)) out.push("HMI · " + w.title);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* 主入口                                                               */
/* ------------------------------------------------------------------ */

/**
 * 块逻辑与作用解释（纯函数、确定性、离线、全中文）：
 * - headline：块注释截断 → keywords 拼接 → 类型默认文案（DB 追加"承载 N 个工艺信号"）。
 * - role：块类型职责 + 注释 + 接口规模，status=error 追加诊断提示。
 * - networks：图形网络解析引用符号；SCL 网络提取条件分支/置位复位/跨块交互拼装 1-2 句摘要。
 * - 关系：callsBlocks（SCL 全局引用 ∩ edges 块名）、calledByBlocks（edges 指入）、
 *   hmiBound（plc_tag 前缀匹配，大小写不敏感）。
 */
export function explainBlock(
  block: CanvasBlockData,
  ctx: { edges: { from: string; to: string; count: number }[]; widgets: CanvasHmiWidgetData[] },
): BlockExplanation {
  const scl = combinedScl(block);
  const conditions = extractConditions(scl);
  const keywords = detectKeywords(block, scl, conditions);

  return {
    headline: buildHeadline(block, keywords),
    role: buildRole(block),
    signals: splitSignals(block),
    networks: summarizeNetworks(block),
    callsBlocks: collectCallsBlocks(block, scl, ctx.edges ?? []),
    calledByBlocks: collectCalledBy(block, ctx.edges ?? []),
    hmiBound: collectHmiBound(block, ctx.widgets ?? []),
    keywords,
  };
}
