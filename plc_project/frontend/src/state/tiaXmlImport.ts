/**
 * 浏览器端 SimaticML XML → 画布（CanvasStateData）导入。
 *
 * 纯逻辑模块：不依赖 React。DOMParser 仅在 {@link parseTiaXmlFiles} 内使用，
 * XML 结构解析拆分为可独立测试的纯函数 {@link parseBlockDocument} /
 * {@link parseTagTableDocument}（接收已解析好的 Document，便于在无浏览器
 * DOMParser 的环境下做逻辑验证）。
 *
 * 兼容仓库 fixture（plc_project/tests/fixtures/tia_exports/）的导出结构：
 * - 块导出：工程元素 `SW.Blocks.FB` / `SW.Blocks.FC` / `SW.Blocks.OB` /
 *   `SW.Blocks.GlobalDB` / `SW.Blocks.InstanceDB`；fixture 兼容变体
 *   `SW.Blocks.ObjectSW` 按块名前缀 FB_/FC_/OB_ 推断类型，默认 FB。
 * - 标签表导出：`SW.Tags.PlcTagTable > SW.Tags.PlcTag`。
 *
 * @example 类型检查用示例（tsc 下可直接校验）
 * const file: TiaImportFile = { name: "FB_Motor.xml", text: "<Document/>" };
 * parseTiaXmlFiles([file], "MyProject").then((r: TiaImportResult) => {
 *   r.blocksParsed; r.tagsParsed; r.errors; r.canvas.project_name;
 * });
 */
import type {
  CanvasBlockData,
  CanvasNetworkData,
  CanvasStateData,
  CanvasTagData,
  CanvasVariableData,
} from "../canvas/types";

export interface TiaImportFile {
  /** 文件名（仅用于错误定位 / 展示） */
  name: string;
  /** XML 文本内容 */
  text: string;
}

export interface TiaImportResult {
  /** 导入产出的画布快照（project_name = projectName 参数） */
  canvas: CanvasStateData;
  /** 成功解析的块数量（重复覆盖的也计入） */
  blocksParsed: number;
  /** 成功解析的物理标签数量 */
  tagsParsed: number;
  /** 逐文件错误记录；单文件失败不中断整体导入 */
  errors: { file: string; message: string }[];
}

/* ------------------------------------------------------------------ */
/* 通用 DOM 小工具（仅依赖 tagName / children / getAttribute /          */
/* textContent / getElementsByTagName，均为标准 DOM API）               */
/* ------------------------------------------------------------------ */

/** 取直接子元素中第一个标签名为 tag 的元素 */
function childByTag(el: Element | null | undefined, tag: string): Element | null {
  if (!el) return null;
  const kids = el.children;
  for (let i = 0; i < kids.length; i++) {
    if (kids[i].tagName === tag) return kids[i];
  }
  return null;
}

function childElements(el: Element | null | undefined): Element[] {
  if (!el) return [];
  const kids = el.children;
  const out: Element[] = [];
  for (let i = 0; i < kids.length; i++) out.push(kids[i]);
  return out;
}

function textOf(el: Element | null | undefined): string {
  return el ? el.textContent ?? "" : "";
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Interface Section Name → SCL 声明关键字 */
const SECTION_MAP: Record<string, string> = {
  None: "VAR",
  Input: "VAR_INPUT",
  Output: "VAR_OUTPUT",
  InOut: "VAR_IN_OUT",
  Static: "VAR_STAT",
  Temp: "VAR_TEMP",
  Constant: "VAR",
};

/**
 * 找到块工程元素：文档中第一个以 "SW.Blocks." 开头的元素（先序遍历，
 * 外层块元素必然先于其内部的 InterfaceSection / CompileUnit 出现）。
 */
function findEngineeringElement(doc: Document): Element | null {
  const all = doc.getElementsByTagName("*");
  for (let i = 0; i < all.length; i++) {
    const tag = all[i].tagName;
    if (tag && tag.indexOf("SW.Blocks.") === 0) return all[i];
  }
  return null;
}

/** MultilingualText[CompositionName=comp] > ObjectList > MultilingualTextItem > AttributeList > Text，取第一个非空 */
function firstMultilingualText(root: Element, composition: string): string {
  const nodes = root.getElementsByTagName("MultilingualText");
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].getAttribute("CompositionName") !== composition) continue;
    const items = nodes[i].getElementsByTagName("MultilingualTextItem");
    for (let j = 0; j < items.length; j++) {
      const attr = childByTag(items[j], "AttributeList");
      const text = textOf(childByTag(attr, "Text")).trim();
      if (text) return text;
    }
  }
  return "";
}

/** 块 / 标签级注释（CompositionName="Comment" 的 MultilingualText） */
function commentOf(root: Element): string | undefined {
  const text = firstMultilingualText(root, "Comment");
  return text || undefined;
}

/** Member 级注释：Member > Comment > Text（容错：无 Text 子元素时取 Comment 聚合文本） */
function memberCommentOf(member: Element): string | undefined {
  const comment = member.getElementsByTagName("Comment")[0];
  if (!comment) return undefined;
  const textEl = comment.getElementsByTagName("Text")[0];
  const text = (textEl ? textEl.textContent : comment.textContent ?? "").trim();
  return text || undefined;
}

/** 工程元素 tagName → 画布块类型（ObjectSW 等兼容变体按块名前缀推断，默认 FB） */
function blockTypeOf(eng: Element, blockName: string): CanvasBlockData["block_type"] {
  switch (eng.tagName) {
    case "SW.Blocks.FB":
      return "FB";
    case "SW.Blocks.FC":
      return "FC";
    case "SW.Blocks.OB":
      return "OB";
    case "SW.Blocks.GlobalDB":
    case "SW.Blocks.InstanceDB":
      return "DB";
    default: {
      if (/^FC_/i.test(blockName)) return "FC";
      if (/^OB_/i.test(blockName)) return "OB";
      return "FB"; // FB_ 前缀与无法识别的情况一律默认 FB
    }
  }
}

/** AttributeList > Number 文本解析；缺失 / 非法返回 NaN */
function readNumberAttribute(eng: Element): number {
  const attr = childByTag(eng, "AttributeList");
  const raw = parseInt(textOf(childByTag(attr, "Number")).trim(), 10);
  return Number.isFinite(raw) ? raw : NaN;
}

/** LAD/FBD 图形网络 → 两行注释型 scl_text（引用符号去重列表 + 图形逻辑提示） */
function graphicNetworkScl(unit: Element): string {
  const symbols: string[] = [];
  const parts: string[] = [];
  const flg = unit.getElementsByTagName("FlgNet")[0];
  if (flg) {
    // FlgNet > Parts > Access > Symbol > Component[Name]（含嵌套在 Part 内的 Access）
    const accesses = flg.getElementsByTagName("Access");
    for (let i = 0; i < accesses.length; i++) {
      const symbol = accesses[i].getElementsByTagName("Symbol")[0];
      if (!symbol) continue;
      const components = symbol.getElementsByTagName("Component");
      for (let j = 0; j < components.length; j++) {
        const name = components[j].getAttribute("Name");
        if (name && symbols.indexOf(name) < 0) symbols.push(name);
      }
    }
    // Part[Name]（Contact / Coil / Call 等）
    const partEls = flg.getElementsByTagName("Part");
    for (let i = 0; i < partEls.length; i++) {
      const name = partEls[i].getAttribute("Name");
      if (name && parts.indexOf(name) < 0) parts.push(name);
    }
  }
  const refs = symbols.concat(parts);
  return `// 图形网络（LAD/FBD），引用符号：${refs.join(", ")}\n// 图形逻辑，源码以博图工程为准`;
}

/* ------------------------------------------------------------------ */
/* 纯函数：块 / 标签表结构解析                                           */
/* ------------------------------------------------------------------ */

/**
 * 解析块导出 Document → CanvasBlockData。
 *
 * @param doc 已解析的 XML Document（须包含 SW.Blocks.* 工程元素）
 * @param fallbackNumber 块号缺省（Number 缺失 / NaN）时使用的编号，默认 1；
 *   parseTiaXmlFiles 内传入 NaN 再按“同类型最大号 + 1”回填。
 * @throws Document 不是可识别的块导出或缺少 Name 时抛错
 */
export function parseBlockDocument(doc: Document, fallbackNumber = 1): CanvasBlockData {
  const eng = findEngineeringElement(doc);
  if (!eng) throw new Error("不是可识别的 SimaticML 块导出");

  const attr = childByTag(eng, "AttributeList");
  const name = textOf(childByTag(attr, "Name")).trim();
  if (!name) throw new Error("块缺少 Name 属性，无法导入");

  const blockType = blockTypeOf(eng, name);
  const numberRaw = readNumberAttribute(eng);
  const number = Number.isFinite(numberRaw) ? numberRaw : fallbackNumber;
  const language = textOf(childByTag(attr, "ProgrammingLanguage")).trim() || "SCL";
  const comment = commentOf(eng);

  /* 接口：SW.Blocks.InterfaceSection > Sections > Section[Name] > Member[Name,Datatype] */
  const interfaceVars: CanvasVariableData[] = [];
  const ifaceSection = eng.getElementsByTagName("SW.Blocks.InterfaceSection")[0];
  if (ifaceSection) {
    for (const section of childElements(childByTag(ifaceSection, "Sections"))) {
      if (section.tagName !== "Section") continue;
      const sectionName = section.getAttribute("Name") ?? "";
      const mapped = SECTION_MAP[sectionName] ?? "VAR";
      for (const member of childElements(section)) {
        if (member.tagName !== "Member") continue;
        const memberName = member.getAttribute("Name") ?? "";
        if (!memberName) continue;
        const variable: CanvasVariableData = {
          name: memberName,
          data_type: member.getAttribute("Datatype") ?? "",
          section: mapped,
        };
        const memberComment = memberCommentOf(member);
        if (memberComment) variable.comment = memberComment;
        interfaceVars.push(variable);
      }
    }
  }

  /* 网络：ObjectList > SW.Blocks.CompileUnit[CompositionName="Networks"]，顺序即编号 1..n */
  const networks: CanvasNetworkData[] = [];
  const units = eng.getElementsByTagName("SW.Blocks.CompileUnit");
  for (let i = 0; i < units.length; i++) {
    const unit = units[i];
    const composition = unit.getAttribute("CompositionName");
    if (composition && composition !== "Networks") continue;
    const unitAttr = childByTag(unit, "AttributeList");
    const unitLanguage =
      textOf(childByTag(unitAttr, "ProgrammingLanguage")).trim() || language;
    const title = firstMultilingualText(unit, "Title");

    let sclText = "";
    const structured = unit.getElementsByTagName("StructuredText")[0];
    if (structured) sclText = (structured.textContent ?? "").trim();
    if (!sclText) sclText = graphicNetworkScl(unit); // LAD/FBD 图形网络

    networks.push({
      id: networks.length + 1,
      title: title || `网络 ${networks.length + 1}`,
      language: unitLanguage,
      scl_text: sclText,
      status: "synced",
    });
  }

  const block: CanvasBlockData = {
    name,
    block_type: blockType,
    number,
    language,
    interface: interfaceVars,
    networks,
    status: "synced",
  };
  if (comment) block.comment = comment;
  return block;
}

/**
 * 解析标签表导出 Document → CanvasTagData[]。
 * 结构：SW.Tags.PlcTagTable > ObjectList > SW.Tags.PlcTag > AttributeList
 * （Name / DataTypeName / LogicalAddress）+ MultilingualText[Comment]。
 * @throws Document 不含 SW.Tags.PlcTagTable 时抛错
 */
export function parseTagTableDocument(doc: Document): CanvasTagData[] {
  const tables = doc.getElementsByTagName("SW.Tags.PlcTagTable");
  if (!tables.length) throw new Error("不是可识别的 SimaticML 标签表导出");
  const tags: CanvasTagData[] = [];
  for (let t = 0; t < tables.length; t++) {
    const tagEls = tables[t].getElementsByTagName("SW.Tags.PlcTag");
    for (let i = 0; i < tagEls.length; i++) {
      const attr = childByTag(tagEls[i], "AttributeList");
      const name = textOf(childByTag(attr, "Name")).trim();
      if (!name) continue;
      const tag: CanvasTagData = {
        name,
        data_type: textOf(childByTag(attr, "DataTypeName")).trim(),
        logical_address: textOf(childByTag(attr, "LogicalAddress")).trim(),
      };
      const comment = commentOf(tagEls[i]);
      if (comment) tag.comment = comment;
      tags.push(tag);
    }
  }
  return tags;
}

/* ------------------------------------------------------------------ */
/* 导入入口                                                             */
/* ------------------------------------------------------------------ */

/** 空画布：无块 / 无 HMI 控件 / 无标签 */
export function blankCanvas(projectName: string): CanvasStateData {
  return {
    project_name: projectName,
    blocks: {},
    hmi_widgets: {},
    tags: {},
  };
}

/** 同类型现有最大块号 + 1（无同类型块时为 1） */
function nextNumberForType(
  blocks: Record<string, CanvasBlockData>,
  blockType: CanvasBlockData["block_type"],
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

/**
 * 批量解析 SimaticML XML 导出 → 画布。
 *
 * - 单文件先按块导出识别（存在 SW.Blocks.* 后代），再按标签表识别
 *   （存在 SW.Tags.PlcTagTable 后代），都不是则记 error。
 * - 解析失败的文件逐条记入 errors，不中断整体导入。
 * - 块名冲突：后者覆盖前者并记 error “块 X 重复导入，已覆盖”。
 * - 块与网络的 status 一律 "synced"。
 * - async 仅为兼容调用方（内部同步完成）。
 */
export async function parseTiaXmlFiles(
  files: TiaImportFile[],
  projectName: string,
): Promise<TiaImportResult> {
  const canvas = blankCanvas(projectName);
  const errors: { file: string; message: string }[] = [];
  let blocksParsed = 0;
  let tagsParsed = 0;

  for (const file of files) {
    /* 1. XML 解析 */
    let doc: Document | null = null;
    try {
      doc = new DOMParser().parseFromString(file.text, "text/xml");
    } catch (e) {
      errors.push({ file: file.name, message: `XML 解析失败：${errorMessage(e)}` });
      continue;
    }
    if (!doc || doc.getElementsByTagName("parsererror").length > 0) {
      errors.push({ file: file.name, message: "XML 解析失败（parsererror）" });
      continue;
    }

    /* 2. 先试块导出 */
    if (findEngineeringElement(doc)) {
      try {
        const block = parseBlockDocument(doc, Number.NaN);
        if (!Number.isFinite(block.number)) {
          block.number = nextNumberForType(canvas.blocks, block.block_type);
        }
        if (canvas.blocks[block.name]) {
          errors.push({ file: file.name, message: `块 ${block.name} 重复导入，已覆盖` });
        }
        canvas.blocks[block.name] = block;
        blocksParsed += 1;
      } catch (e) {
        errors.push({ file: file.name, message: errorMessage(e) });
      }
      continue;
    }

    /* 3. 再试标签表导出 */
    if (doc.getElementsByTagName("SW.Tags.PlcTagTable").length > 0) {
      try {
        for (const tag of parseTagTableDocument(doc)) {
          canvas.tags[tag.name] = tag;
          tagsParsed += 1;
        }
      } catch (e) {
        errors.push({ file: file.name, message: errorMessage(e) });
      }
      continue;
    }

    /* 4. 无法识别 */
    errors.push({ file: file.name, message: "不是可识别的 SimaticML 导出" });
  }

  return { canvas, blocksParsed, tagsParsed, errors };
}
