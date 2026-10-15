import React from "react";

/** IEC 61131-3 SCL 关键字表（与后端渲染方言一致） */
const SCL_KEYWORDS = new Set([
  "IF", "THEN", "ELSIF", "ELSE", "END_IF",
  "CASE", "OF", "END_CASE",
  "FOR", "TO", "BY", "DO", "END_FOR",
  "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT",
  "FUNCTION_BLOCK", "END_FUNCTION_BLOCK",
  "FUNCTION", "END_FUNCTION",
  "DATA_BLOCK", "END_DATA_BLOCK",
  "ORGANIZATION_BLOCK", "END_ORGANIZATION_BLOCK",
  "STRUCT", "END_STRUCT",
  "VAR", "END_VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_STAT", "VAR_TEMP", "VAR_IN_OUT",
  "CONST", "END_CONST", "TYPE", "END_TYPE",
  "BEGIN", "TRUE", "FALSE",
  "AND", "OR", "XOR", "NOT", "MOD",
  "RETURN", "EXIT", "CONTINUE",
]);

const SCL_TOKEN_RE =
  /(\/\/[^\n]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)/g;

function tokenize(code: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let key = 0;
  let last = 0;
  code.replace(
    SCL_TOKEN_RE,
    (match: string, com: string, str: string, num: string, word: string, offset: number) => {
      if (offset > last) out.push(code.slice(last, offset));
      if (com) out.push(<span key={key++} className="tok-com">{com}</span>);
      else if (str) out.push(<span key={key++} className="tok-str">{str}</span>);
      else if (num) out.push(<span key={key++} className="tok-num">{num}</span>);
      else if (word && SCL_KEYWORDS.has(word.toUpperCase()))
        out.push(<span key={key++} className="tok-kw">{word}</span>);
      else out.push(match);
      last = offset + match.length;
      return match;
    }
  );
  if (last < code.length) out.push(code.slice(last));
  return out;
}

/** 整段 SCL 着色（含换行，用于 pre） */
export function highlightScl(code: string): React.ReactNode {
  return tokenize(code);
}

/** 单行 SCL 着色（用于逐行渲染的清单视图） */
export function highlightSclLines(line: string): React.ReactNode {
  if (line === "") return "\u00A0";
  return tokenize(line);
}
