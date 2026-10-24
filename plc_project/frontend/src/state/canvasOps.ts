/**
 * 画布操作纯逻辑：本地应用（applyOpsLocally）、指令意图（buildOpsFromPrompt）、
 * 操作摘要（summarizeOps）与 op 构造器。
 *
 * op 协议与后端 patch 协议保持一致（add_block / add_variable / add_network /
 * add_hmi_widget / add_tag）；本模块不依赖 React。
 */
import type { CanvasBlockData, CanvasNetworkData, CanvasStateData } from "../canvas/types";

export type PromptBlockType = "FB" | "FC" | "DB" | "OB";

/* ------------------------------------------------------------------ */
/* 块号 / 网络号分配                                                    */
/* ------------------------------------------------------------------ */

function nextNumberInBlocks(
  blocks: Record<string, CanvasBlockData>,
  blockType: string,
): number {
  let max = 0;
  for (const key of Object.keys(blocks)) {
    const b = blocks[key];
    if (b && b.block_type === blockType && typeof b.number === "number" && b.number > max) {
      max = b.number;
    }
  }
  return max + 1;
}

/** 指定类型下一个可用块号（同类型最大号 + 1，无同类型块时为 1） */
export function nextBlockNumber(
  canvas: CanvasStateData,
  blockType: "FB" | "FC" | "DB" | "OB",
): number {
  return nextNumberInBlocks(canvas.blocks, blockType);
}

function nextNetworkIdIn(networks: CanvasNetworkData[]): number {
  let max = 0;
  for (const n of networks) {
    if (n && typeof n.id === "number" && n.id > max) max = n.id;
  }
  return max + 1;
}

/* ------------------------------------------------------------------ */
/* op 构造器                                                            */
/* ------------------------------------------------------------------ */

/** 构造 add_block op；number 缺省由 applyOpsLocally 按 nextBlockNumber 补全 */
export function makeBlockOp(
  name: string,
  blockType: "FB" | "FC" | "DB" | "OB",
  comment: string,
  number?: number,
): any {
  const block: Record<string, any> = { name, block_type: blockType, comment };
  if (number !== undefined) block.number = number;
  return { op: "add_block", block };
}

/** 构造 add_variable op */
export function makeVariableOp(
  block: string,
  v: { name: string; data_type: string; section: string; comment?: string },
): any {
  const variable: Record<string, any> = {
    name: v.name,
    data_type: v.data_type,
    section: v.section,
  };
  if (v.comment !== undefined) variable.comment = v.comment;
  return { op: "add_variable", block, variable };
}

/** 构造 add_network op；id / language 缺省由 applyOpsLocally 补全 */
export function makeNetworkOp(
  block: string,
  n: { title: string; scl_text: string; language?: string; id?: number },
): any {
  const network: Record<string, any> = { title: n.title, scl_text: n.scl_text };
  if (n.language !== undefined) network.language = n.language;
  if (n.id !== undefined) network.id = n.id;
  return { op: "add_network", block, network };
}

/** 删除块内一个变量（update_block 整体替换 interface）；变量不存在返回 null */
export function deleteVariableOps(
  canvas: CanvasStateData,
  block: string,
  varName: string,
): any[] | null {
  const b = canvas.blocks[block];
  if (!b) return null;
  const rest = b.interface.filter((v) => v.name !== varName);
  if (rest.length === b.interface.length) return null;
  return [{ op: "update_block", name: block, patch: { interface: rest } }];
}

/** 删除块内一个网络（update_block 整体替换 networks）；网络不存在返回 null */
export function deleteNetworkOps(
  canvas: CanvasStateData,
  block: string,
  networkId: number,
): any[] | null {
  const b = canvas.blocks[block];
  if (!b) return null;
  const rest = b.networks.filter((n) => n.id !== networkId);
  if (rest.length === b.networks.length) return null;
  return [{ op: "update_block", name: block, patch: { networks: rest } }];
}

/** 重命名块：复合 ops——依赖块 SCL 引用改写 + HMI tag 改写 + 删旧建新 */
export function makeRenameOps(
  canvas: CanvasStateData,
  oldName: string,
  newName: string,
): any[] | null {
  const b = canvas.blocks[oldName];
  if (!b || oldName === newName) return null;
  if (canvas.blocks[newName]) return null; // 目标名已存在

  const refRe = new RegExp(`"${oldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\.`, "g");
  const tagPrefix = new RegExp(
    `^${oldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.`,
    "i",
  );

  const ops: any[] = [];
  // 1) 依赖块：SCL 中的 "Old". 引用改写为 "New".
  for (const [name, blk] of Object.entries(canvas.blocks)) {
    if (name === oldName) continue;
    const hit =
      blk.networks.some((n) => refRe.test(n.scl_text)) ||
      (!!blk.scl_body && refRe.test(blk.scl_body));
    refRe.lastIndex = 0;
    if (!hit) continue;
    ops.push({
      op: "update_block",
      name,
      patch: {
        networks: blk.networks.map((n) => ({
          ...n,
          scl_text: n.scl_text.replace(refRe, `"${newName}".`),
        })),
        ...(blk.scl_body
          ? { scl_body: blk.scl_body.replace(refRe, `"${newName}".`) }
          : {}),
      },
    });
    refRe.lastIndex = 0;
  }
  // 2) 绑定该块变量的 HMI 控件：tag 前缀改写
  for (const w of Object.values(canvas.hmi_widgets)) {
    if (w.plc_tag && tagPrefix.test(w.plc_tag)) {
      ops.push({
        op: "update_hmi_widget",
        id: w.id,
        patch: { plc_tag: w.plc_tag.replace(tagPrefix, `${newName}.`) },
      });
    }
  }
  // 3) 删旧建新
  ops.push({ op: "remove_block", name: oldName });
  ops.push({
    op: "add_block",
    block: { ...b, name: newName },
  });
  return ops;
}

/* ------------------------------------------------------------------ */
/* 本地应用（不可变更新，深拷贝受影响分支）                                */
/* ------------------------------------------------------------------ */

/**
 * 将 ops 应用到画布，返回新 CanvasStateData（原对象不被修改）。
 *
 * - add_block：缺省 number = nextBlockNumber；language 按 block_type
 *   （DB → "DB"，其余 → "SCL"）；status = "draft"；interface / networks
 *   元素补全 id / language / status。
 * - add_variable / add_network：目标块存在才应用，块 status → "draft"；
 *   add_network 的 id 缺省 = 该块网络最大 id + 1，language 缺省 "SCL"，
 *   status = "draft"。
 * - add_hmi_widget：current_value 缺省 false；status = "draft"。
 * - add_tag：tags[name] = tag，不影响块状态。
 * - 未知 op 忽略。
 */
export function applyOpsLocally(canvas: CanvasStateData, ops: any[]): CanvasStateData {
  const blocks = { ...canvas.blocks };
  const hmiWidgets = { ...canvas.hmi_widgets };
  const tags = { ...canvas.tags };

  for (const op of ops) {
    if (!op || typeof op !== "object") continue;
    switch (op.op) {
      case "add_block": {
        const src = op.block ?? {};
        const name: string = src.name;
        if (typeof name !== "string" || !name) break;
        const blockType: CanvasBlockData["block_type"] = src.block_type ?? "FB";
        const number =
          typeof src.number === "number" ? src.number : nextNumberInBlocks(blocks, blockType);
        const language =
          typeof src.language === "string" && src.language
            ? src.language
            : blockType === "DB"
              ? "DB"
              : "SCL";

        const networks: CanvasNetworkData[] = [];
        const rawNetworks: any[] = Array.isArray(src.networks) ? src.networks : [];
        for (const raw of rawNetworks) {
          const network: any = { ...raw };
          if (typeof network.id !== "number") network.id = nextNetworkIdIn(networks);
          if (typeof network.language !== "string" || !network.language) network.language = "SCL";
          network.status = network.status ?? "draft";
          networks.push(network);
        }

        blocks[name] = {
          name,
          block_type: blockType,
          number,
          language,
          comment: typeof src.comment === "string" ? src.comment : undefined,
          interface: (Array.isArray(src.interface) ? src.interface : []).map(
            (v: any) => ({ ...v }),
          ),
          networks,
          status: "draft",
        };
        break;
      }

      case "add_variable": {
        const target = blocks[op.block];
        if (!target || !op.variable || typeof op.variable.name !== "string") break;
        blocks[op.block] = {
          ...target,
          status: "draft",
          interface: [...target.interface, { ...op.variable }],
        };
        break;
      }

      case "add_network": {
        const target = blocks[op.block];
        if (!target || !op.network) break;
        const network: any = { ...op.network };
        if (typeof network.id !== "number") network.id = nextNetworkIdIn(target.networks);
        if (typeof network.language !== "string" || !network.language) network.language = "SCL";
        network.status = "draft";
        blocks[op.block] = {
          ...target,
          status: "draft",
          networks: [...target.networks, network],
        };
        break;
      }

      case "add_hmi_widget": {
        const w = op.widget ?? {};
        if (typeof w.id !== "string" || !w.id) break;
        hmiWidgets[w.id] = {
          ...w,
          current_value: w.current_value ?? false,
          status: "draft",
        };
        break;
      }

      case "update_hmi_widget": {
        const w = hmiWidgets[op.id];
        if (!w || !op.patch || typeof op.patch !== "object") break;
        hmiWidgets[op.id] = { ...w, ...op.patch, status: "draft" };
        break;
      }

      case "add_tag": {
        const t = op.tag ?? {};
        if (typeof t.name !== "string" || !t.name) break;
        tags[t.name] = { ...t };
        break;
      }

      case "remove_block": {
        const name: string = op.name;
        if (typeof name !== "string" || !name) break;
        if (!blocks[name]) break;
        delete blocks[name];
        // 绑定该块变量的 HMI 控件一并移除（避免悬空引用）
        for (const [id, w] of Object.entries(hmiWidgets)) {
          const prefix = `${name}.`;
          if ((w.plc_tag ?? "").toLowerCase().startsWith(prefix.toLowerCase())) {
            delete hmiWidgets[id];
          }
        }
        break;
      }

      case "update_block": {
        // 与后端同语义：patch 可含 comment / scl_body / interface / networks（整体替换），status → draft
        const target = blocks[op.name];
        if (!target || !op.patch || typeof op.patch !== "object") break;
        const next: CanvasBlockData = { ...target, status: "draft", errors: [] };
        if (typeof op.patch.comment === "string") next.comment = op.patch.comment;
        if (typeof op.patch.scl_body === "string") next.scl_body = op.patch.scl_body;
        if (Array.isArray(op.patch.interface)) {
          next.interface = op.patch.interface.map((v: any) => ({ ...v }));
        }
        if (Array.isArray(op.patch.networks)) {
          next.networks = op.patch.networks.map((n: any) => ({ ...n }));
        }
        blocks[op.name] = next;
        break;
      }

      default:
        break; // 未知 op 忽略
    }
  }

  return { ...canvas, blocks, hmi_widgets: hmiWidgets, tags };
}

/* ------------------------------------------------------------------ */
/* 操作摘要                                                             */
/* ------------------------------------------------------------------ */

/** ops → 中文摘要（分号连接，整体前缀 “已执行：”） */
export function summarizeOps(ops: any[]): string {
  const parts: string[] = [];
  for (const op of ops) {
    if (!op || typeof op !== "object") continue;
    switch (op.op) {
      case "add_block": {
        const b = op.block ?? {};
        parts.push(`创建 ${b.block_type ?? ""} 块 "${b.name ?? ""}"`);
        break;
      }
      case "add_variable": {
        const v = op.variable ?? {};
        parts.push(`新增变量 ${op.block}.${v.name ?? ""}`);
        break;
      }
      case "add_hmi_widget": {
        const w = op.widget ?? {};
        const kind =
          w.widget_type === "button" ? "按钮" : w.widget_type === "indicator" ? "指示灯" : "控件";
        parts.push(`新增 HMI ${kind}「${w.title ?? ""}」`);
        break;
      }
      case "add_network": {
        const n = op.network ?? {};
        parts.push(`${op.block} 追加网络「${n.title ?? ""}」`);
        break;
      }
      case "add_tag": {
        const t = op.tag ?? {};
        parts.push(`新增物理标签 ${t.name ?? ""}`);
        break;
      }
      case "remove_block": {
        parts.push(`删除块 "${op.name ?? ""}"（及其 HMI 绑定）`);
        break;
      }
      case "update_block": {
        const patchKeys = Object.keys(op.patch ?? {});
        parts.push(`修改块 ${op.name ?? ""}（${patchKeys.join("/")}）`);
        break;
      }
      case "update_hmi_widget": {
        parts.push(`更新 HMI 控件 ${op.id ?? ""}`);
        break;
      }
      default:
        parts.push(String(op.op));
        break;
    }
  }
  return `已执行：${parts.join("；")}`;
}

/* ------------------------------------------------------------------ */
/* 自然语言 → ops                                                        */
/* ------------------------------------------------------------------ */

/** 标识符词元（含起始位置） */
function identifierTokens(prompt: string): { text: string; start: number }[] {
  const re = /[A-Za-z_][A-Za-z0-9_]*/g;
  const out: { text: string; start: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(prompt)) !== null) out.push({ text: m[0], start: m.index });
  return out;
}

/** 从 from 位置起找第一个英文标识符 */
function identifierAfter(prompt: string, from: number): string | null {
  const re = /[A-Za-z_][A-Za-z0-9_]*/g;
  re.lastIndex = Math.max(0, from);
  const m = re.exec(prompt);
  return m ? m[0] : null;
}

const TYPE_WORDS = ["FB", "FC", "DB", "OB"];

/** “在/给 <块> 添加…” 句式（变量意图的强信号，用于避免创建块意图误抢） */
const DIRECTIVE_SHAPE = /(在|给)\s*[A-Za-z_][A-Za-z0-9_]*\s*(中)?\s*(添加|增加|加)/;

/** 意图 1：创建块 */
function matchCreateBlockIntent(prompt: string): any[] | null {
  if (!/(创建|新建|添加|建)/.test(prompt)) return null;
  const directiveShaped = DIRECTIVE_SHAPE.test(prompt);

  /* 1a. 中文类型词：功能块→FB、数据块→DB、组织块→OB，块名取其后英文标识符 */
  const cn = /(功能块|数据块|组织块)/.exec(prompt);
  if (cn) {
    const name = identifierAfter(prompt, cn.index + cn[1].length);
    if (name) {
      const type =
        cn[1] === "数据块" ? "DB" : cn[1] === "组织块" ? "OB" : "FB";
      return [makeBlockOp(name, type as PromptBlockType, prompt)];
    }
    return null; // 找不到块名 → 不匹配此意图
  }

  const tokens = identifierTokens(prompt);

  /* 1b. 独立类型词元 FB/FC/DB/OB，块名取其后的标识符 */
  if (!directiveShaped) {
    for (let i = 0; i < tokens.length; i++) {
      const upper = tokens[i].text.toUpperCase();
      if (TYPE_WORDS.indexOf(upper) >= 0) {
        const next = tokens
          .slice(i + 1)
          .find((t) => TYPE_WORDS.indexOf(t.text.toUpperCase()) < 0);
        if (next) {
          return [makeBlockOp(next.text, upper as PromptBlockType, prompt)];
        }
        return null; // 类型词后找不到块名 → 不匹配
      }
    }
  }

  /* 1c. FB_/FC_/DB_/OB_ 前缀标识符（如 “创建一个 FB_Sorter 块”） */
  if (!directiveShaped) {
    for (const t of tokens) {
      const m = /^(FB|FC|DB|OB)_/i.exec(t.text);
      if (m) return [makeBlockOp(t.text, m[1].toUpperCase() as PromptBlockType, prompt)];
    }
  }

  /* 1d. 创建/新建 + 其他“…块”中文表述 → 默认 FB */
  if (/(创建|新建)/.test(prompt) && /块/.test(prompt) && !directiveShaped) {
    const name = tokens.length ? tokens[0].text : null;
    if (name) return [makeBlockOp(name, "FB", prompt)];
  }
  return null;
}

/**
 * 意图 2 句式（规格原文：/(在|给)\s*(标识符)\s*(中)?(添加|增加|加)(一个)?(变量)?\s*(标识符)/，
 * 在各组之间补 \s* 以兼容 “加 一个 变量” 这类带空格的说法；标准句式行为一致）。
 */
const ADD_VAR_RE =
  /(在|给)\s*([A-Za-z_][A-Za-z0-9_]*)\s*(中)?\s*(添加|增加|加)\s*(一个)?\s*(变量)?\s*([A-Za-z_][A-Za-z0-9_]*)/;

/** 变量数据类型推断 */
function inferDataType(prompt: string): string {
  if (/布尔|开关|bool/i.test(prompt)) return "Bool";
  if (/整数|int/i.test(prompt)) return "Int";
  if (/实数|浮点|real/i.test(prompt)) return "Real";
  if (/字符串|string/i.test(prompt)) return "String";
  return "Bool";
}

/** 意图 2：给已存在的指定块加变量 */
function matchVariableIntent(prompt: string, canvas: CanvasStateData): any[] | null {
  const m = ADD_VAR_RE.exec(prompt);
  if (!m) return null;
  const blockName = m[2];
  const varName = m[7];
  if (!blockName || !varName) return null;
  if (!canvas.blocks[blockName]) return null;
  return [
    makeVariableOp(blockName, {
      name: varName,
      data_type: inferDataType(prompt),
      section: "VAR",
      comment: prompt,
    }),
  ];
}

/** 意图 3：急停（保持与原有 App.tsx 实现一致的 3 个 op；画布缺 MainDB/MotorCtrl 时跳过对应 op） */
function buildEstopOps(canvas: CanvasStateData): any[] {
  const ops: any[] = [];
  if (canvas.blocks["MainDB"]) {
    ops.push({
      op: "add_variable",
      block: "MainDB",
      variable: {
        name: "EmergencyStop",
        data_type: "Bool",
        section: "VAR",
        comment: "安全继电器急停连锁",
      },
    });
    ops.push({
      op: "add_hmi_widget",
      widget: {
        id: `btn_estop_${Date.now() % 1000}`,
        widget_type: "button",
        title: "紧急停止 (E-STOP)",
        x: 380,
        y: 40,
        width: 160,
        height: 52,
        plc_tag: "MainDB.EmergencyStop",
        data_type: "Bool",
        properties: { color: "red" },
      },
    });
  }
  if (canvas.blocks["MotorCtrl"]) {
    ops.push({
      op: "add_network",
      block: "MotorCtrl",
      network: {
        id: (canvas.blocks["MotorCtrl"]?.networks.length || 1) + 1,
        title: "急停安全切断网络 (Safety Interlock)",
        language: "SCL",
        scl_text:
          'IF "MainDB".EmergencyStop THEN\n    #RunningState := FALSE;\n    #RunOut := FALSE;\nEND_IF;',
      },
    });
  }
  return ops;
}

function firstBlockOfType(canvas: CanvasStateData, blockType: string): string | null {
  for (const key of Object.keys(canvas.blocks)) {
    if (canvas.blocks[key] && canvas.blocks[key].block_type === blockType) return key;
  }
  return null;
}

function firstBlockName(canvas: CanvasStateData): string | null {
  const keys = Object.keys(canvas.blocks);
  return keys.length ? keys[0] : null;
}

/** 意图 4：冷却泵（MainDB 缺失时退化为向第一个 DB 块加变量；无 DB 块返回 null 落入默认意图） */
function buildPumpOps(canvas: CanvasStateData): any[] | null {
  const variable = {
    name: "CoolingPumpActive",
    data_type: "Bool",
    section: "VAR",
    comment: "循环水泵运行状态",
  };
  if (canvas.blocks["MainDB"]) {
    return [
      { op: "add_variable", block: "MainDB", variable },
      {
        op: "add_hmi_widget",
        widget: {
          id: `lamp_pump_${Date.now() % 1000}`,
          widget_type: "indicator",
          title: "冷却水泵状态",
          x: 380,
          y: 140,
          width: 120,
          height: 86,
          plc_tag: "MainDB.CoolingPumpActive",
          data_type: "Bool",
        },
      },
    ];
  }
  const firstDb = firstBlockOfType(canvas, "DB");
  if (firstDb) {
    return [{ op: "add_variable", block: firstDb, variable }];
  }
  return null;
}

/** 疑似编辑指令的信号：兜底意图只对"看起来想改东西"的输入生效，
 * 纯提问/名词短语（"该项目的运行逻辑"/"当前功能块作用"）一律不造操作 */
const EDITISH_HINT = /(添加|增加|加|创建|新建|建|设|修改|改|配置|变量|信号|按钮|指示灯|控件|急停|网络|块)/;

/** 意图 5：默认——向第一个 DB 块（无 DB 则第一个块）加变量；完全无块返回 [] */
function buildDefaultOps(prompt: string, canvas: CanvasStateData): any[] {
  if (!EDITISH_HINT.test(prompt)) return []; // 无编辑信号的输入绝不乱改画布
  const target = firstBlockOfType(canvas, "DB") ?? firstBlockName(canvas);
  if (!target) return [];
  return [
    {
      op: "add_variable",
      block: target,
      variable: {
        name: `UserVar_${Date.now() % 1000}`,
        data_type: "Real",
        section: "VAR",
        comment: prompt,
      },
    },
  ];
}

/** 提取 ops 触及的块名（与后端 ops_touched_blocks 同规则），供预检按需收窄范围 */
export function touchedBlockNames(ops: any[]): string[] {
  const names: string[] = [];
  for (const op of ops || []) {
    if (!op || typeof op !== "object") continue;
    if (typeof op.block === "string" && op.block.trim()) {
      names.push(op.block.trim());
    } else if (op.block && typeof op.block === "object" && typeof op.block.name === "string" && op.block.name.trim()) {
      names.push(op.block.name.trim());
    } else if (
      (op.op === "update_block" || op.op === "remove_block") &&
      typeof op.name === "string" &&
      op.name.trim()
    ) {
      names.push(op.name.trim());
    }
  }
  return [...new Set(names)];
}

/**
 * 自然语言指令 → 画布操作。意图按序匹配：
 * 1. 创建块（创建/新建/添加/建 + FB|FC|DB|OB|功能块|数据块|组织块 或 FB_/… 前缀标识符）
 * 2. 给已存在的块加变量（在/给 <块> 添加/增加/加 <变量>）
 * 3. 急停 / 报警 / estop
 * 4. 冷却 / 泵 / pump
 * 5. 默认：向第一个 DB 块（无 DB 则第一个块）加变量——仅对疑似编辑指令生效；
 *    分析/提问类输入（"该项目的运行逻辑"）返回 []，不造修改。
 */
export function buildOpsFromPrompt(prompt: string, canvas: CanvasStateData): any[] {
  const createIntent = matchCreateBlockIntent(prompt);
  if (createIntent) return createIntent;

  const removeIntent = matchRemoveBlockIntent(prompt, canvas);
  if (removeIntent) return removeIntent;

  const renameIntent = matchRenameIntent(prompt, canvas);
  if (renameIntent) return renameIntent;

  const variableIntent = matchVariableIntent(prompt, canvas);
  if (variableIntent) return variableIntent;

  // 提问/分析类输入不当编辑——守卫放在关键词规则之前、结构化编辑意图之后：
  // 「怎么创建 FB X?」这类明确编辑意图仍执行（意图优先），
  // 而「分析项目的报警逻辑」不会再被 急停/报警 关键词误建成变量+按钮。
  if (looksLikeQuestion(prompt)) return [];

  const lower = prompt.toLowerCase();
  if (prompt.includes("急停") || prompt.includes("报警") || lower.includes("estop")) {
    return buildEstopOps(canvas);
  }
  if (prompt.includes("冷却") || prompt.includes("泵") || lower.includes("pump")) {
    const pumpOps = buildPumpOps(canvas);
    if (pumpOps) return pumpOps;
  }
  return buildDefaultOps(prompt, canvas);
}

/** 提问/分析类输入的信号：问号结尾，或含疑问词/分析动词（深度解释入口在前端面板） */
export function looksLikeQuestion(prompt: string): boolean {
  return (
    /[？?]\s*$/.test(prompt.trim()) ||
    /(什么是|是什么|为什么|怎么|怎样|如何|哪些|哪个|介绍|解释|说明|描述|分析|评价|总结|梳理|运行逻辑|控制逻辑|工作原理|原理|作用|用途|含义|功能|干嘛|干什么)/.test(
      prompt,
    )
  );
}

/** 意图：重命名块——“重命名/改名 X 为 Y”、“把 X 改名(为) Y”、“X 改名成 Y”；X 必须存在、Y 合法且不冲突 */
function matchRenameIntent(prompt: string, canvas: CanvasStateData): any[] | null {
  if (!/(重命名|改名|改名为|更名)/.test(prompt)) return null;
  const m =
    /(重命名|更名|把|将)?\s*([A-Za-z_][A-Za-z0-9_]*)\s*(重命名|更名|改名(为|成)?)\s*(为|成|到)?\s*([A-Za-z_][A-Za-z0-9_]*)/.exec(
      prompt,
    );
  // 句式 A：重命名 X 为 Y（动词在前）
  const a = /(重命名|更名)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(为|成|到)?\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(prompt);
  if (a && canvas.blocks[a[2]] && !canvas.blocks[a[4]] && a[2] !== a[4]) {
    return makeRenameOps(canvas, a[2], a[4]);
  }
  // 句式 B：把/将 X 改名(为) Y
  const b = /(把|将)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:重命名|更名|改名(为|成)?)\s*(为|成|到)?\s*([A-Za-z_][A-Za-z0-9_]*)/.exec(prompt);
  if (b && canvas.blocks[b[2]] && !canvas.blocks[b[5]] && b[2] !== b[5]) {
    return makeRenameOps(canvas, b[2], b[5]);
  }
  void m;
  return null;
}

/** 意图：删除块——“删除/删掉/移除 <类型词?> 块? <名>”，且名必须在画布中存在 */
function matchRemoveBlockIntent(prompt: string, canvas: CanvasStateData): any[] | null {
  if (!/(删除|删掉|移除|去掉)/.test(prompt)) return null;
  // “去掉/删除 变量” 类句式留给变量意图，不在此处理
  if (/(删除|删掉|移除|去掉).{0,4}变量/.test(prompt)) return null;
  const tokens = identifierTokens(prompt);
  const names = Object.keys(canvas.blocks);
  for (const t of tokens) {
    if (names.includes(t.text)) {
      // 该标识符前 6 字内出现删除动词才算目标（避免“删除 B 前先看 A”误伤）
      const before = prompt.slice(Math.max(0, t.start - 6), t.start);
      if (/(删除|删掉|移除|去掉)/.test(before)) {
        return [{ op: "remove_block", name: t.text }];
      }
    }
  }
  return null;
}
