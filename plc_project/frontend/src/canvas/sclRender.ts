import type { CanvasBlockData } from "./types";

/**
 * SCL 外部源方言渲染（与后端 canvas_model.get_full_scl 保持 1:1 一致）：
 * - 声明区结束统一 END_VAR；VAR_STAT 在外部源中写作 VAR；
 * - 声明区不带行内注释（注释由 SimaticML XML 承载）；
 * - 块头后只允许属性块；网络标题以代码区注释行呈现。
 */
const SECTION_KEYWORD: Record<string, string> = {
  VAR_INPUT: "VAR_INPUT",
  VAR_OUTPUT: "VAR_OUTPUT",
  VAR_IN_OUT: "VAR_IN_OUT",
  VAR_STAT: "VAR",
  VAR_TEMP: "VAR_TEMP",
  VAR: "VAR",
};

export function renderBlockScl(block: CanvasBlockData): string {
  const lines: string[] = [];
  const btype = block.block_type.toUpperCase();

  if (btype === "DB") {
    lines.push(`DATA_BLOCK "${block.name}"`);
    lines.push("STRUCT");
    for (const v of block.interface) {
      const init = v.initial_value ? ` := ${v.initial_value}` : "";
      lines.push(`    ${v.name} : ${v.data_type}${init};`);
    }
    lines.push("END_STRUCT;");
    lines.push("BEGIN");
    lines.push("END_DATA_BLOCK");
    return lines.join("\n") + "\n";
  }

  if (btype === "UDT") {
    if (block.scl_body && block.scl_body.trim()) {
      return block.scl_body.trim() + "\n";
    }
    lines.push(`TYPE "${block.name}"`);
    lines.push("STRUCT");
    for (const v of block.interface) {
      const init = v.initial_value ? ` := ${v.initial_value}` : "";
      lines.push(`    ${v.name} : ${v.data_type}${init};`);
    }
    lines.push("END_STRUCT;");
    lines.push("END_TYPE");
    return lines.join("\n") + "\n";
  }

  const kw =
    btype === "FB" ? "FUNCTION_BLOCK" : btype === "FC" ? "FUNCTION" : "ORGANIZATION_BLOCK";
  lines.push(`${kw} "${block.name}"`);

  const sections = new Map<string, typeof block.interface>();
  for (const v of block.interface) {
    const key = v.section.toUpperCase();
    const list = sections.get(key) ?? [];
    list.push(v);
    sections.set(key, list);
  }
  for (const [sec, vars] of sections) {
    lines.push(SECTION_KEYWORD[sec] ?? "VAR");
    for (const v of vars) {
      const init = v.initial_value ? ` := ${v.initial_value}` : "";
      lines.push(`    ${v.name} : ${v.data_type}${init};`);
    }
    lines.push("END_VAR");
  }

  lines.push("BEGIN");
  if (block.scl_body && block.scl_body.trim()) {
    lines.push(block.scl_body.trim());
  } else {
    for (const net of block.networks) {
      if (net.title) lines.push(`    // Network ${net.id}: ${net.title}`);
      if (net.scl_text.trim()) {
        lines.push("    " + net.scl_text.trim().replace(/\n/g, "\n    "));
      }
    }
  }
  lines.push(`END_${kw}`);
  return lines.join("\n") + "\n";
}

export function renderAllScl(blocks: CanvasBlockData[]): string {
  return blocks
    .map(
      (b) =>
        `// ================================================================\n` +
        `// BLOCK: "${b.name}" (${b.block_type}) · TIA PORTAL SCL SOURCE\n` +
        `// ================================================================\n` +
        renderBlockScl(b)
    )
    .join("\n");
}
