/* ==========================================================================
   blockRefs —— 聊天消息中的块名(FB/FC/DB/OB/UDT)可点击化(纯函数)
   已知块名来自 canvas.blocks 键集:词边界、大小写敏感、长名优先匹配,
   命中替换为 [块名](#block:编码名),MarkdownBody 把 #block: 链接渲染成
   跳转按钮。代码区(``` 围栏与 `行内代码`)不替换,避免污染代码展示——
   行内代码恰为块名的情形由 MarkdownBody 的 code 渲染器单独处理。
   vitest 覆盖见 blockRefs.test.ts。
   ========================================================================== */

/** 正则元字符转义 */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** ``` 围栏(流式中未闭合的围栏视为延续到文末)与 `行内代码` 区段 */
const CODE_REGION_RE = /```[\s\S]*?(?:```|$)|`[^`\n]*`/g;

/** 对单个非代码区段做块名 → markdown 链接替换 */
function linkifyChunk(chunk: string, blockRe: RegExp): string {
  return chunk.replace(blockRe, (name) => `[${name}](#block:${encodeURIComponent(name)})`);
}

/**
 * 把文本里出现的已知块名替换为 #block: 锚点链接(代码区除外)。
 * names 为空或文本不含任何块名时原样返回。
 */
export function linkifyBlockNames(text: string, names: Iterable<string>): string {
  const sorted = Array.from(new Set(names))
    .filter((n) => n && !/[`\\]/.test(n))
    .sort((a, b) => b.length - a.length);
  if (!text || sorted.length === 0) return text;
  // 长名优先进交替分支,避免 FB1010 被 FB10 截断;块名本就区分大小写
  const blockRe = new RegExp(`(?<![\\w])(?:${sorted.map(escapeRegExp).join("|")})(?![\\w])`, "g");
  let out = "";
  let cursor = 0;
  for (const match of text.matchAll(CODE_REGION_RE)) {
    const at = match.index ?? 0;
    if (at > cursor) out += linkifyChunk(text.slice(cursor, at), blockRe);
    out += match[0];
    cursor = at + match[0].length;
  }
  if (cursor < text.length) out += linkifyChunk(text.slice(cursor), blockRe);
  return out;
}
