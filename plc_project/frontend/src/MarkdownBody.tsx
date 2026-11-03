import { Children, createElement, useMemo, type ReactNode } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import { DiffLines } from "./SclDiffPreview";

/** Matches footnote citation markers: `[^C1]`, `[^1]`. */
const CITATION_REF_RE = /(\[\^C?\d+\])/;

function citationIndex(marker: string): string {
  const m = marker.match(/\[\^C?(\d+)\]/);
  return m ? m[1] : "";
}

/** Wrap inline `[^Cn]` markers in `<span data-citation-ref="n">` for the rail. */
function withCitationRefs(children: ReactNode): ReactNode {
  return Children.map(children, (child, i) => {
    if (typeof child !== "string") return child;
    const parts = child.split(CITATION_REF_RE);
    if (parts.length <= 1) return child;
    return parts.map((part, j) => {
      if (!CITATION_REF_RE.test(part)) return part;
      const n = citationIndex(part);
      if (!n) return part;
      return createElement(
        "span",
        { key: `${i}-${j}`, className: "citation-ref", "data-citation-ref": n },
        part,
      );
    });
  });
}

/** `#block:` 锚点前缀(blockRefs.linkifyBlockNames 生成的块名链接) */
const BLOCK_HREF_PREFIX = "#block:";

function decodeBlockHref(href: string): string {
  try {
    return decodeURIComponent(href);
  } catch {
    return href;
  }
}

/**
 * 渲染器集合。blockNames + onOpenBlock 齐备时:
 * - `#block:名` 锚链接 → 可点击块引用按钮(在画布打开该块);
 * - 行内代码恰为已知块名 → 同款按钮(LLM 常用行内代码书写块名)。
 * 其余渲染路径与无块名 props 时完全一致。
 */
function makeComponents(
  blockNames: Set<string> | undefined,
  onOpenBlock: ((name: string) => void) | undefined,
): Components {
  const blockRefEnabled = !!blockNames && !!onOpenBlock;
  const renderBlockRef = (name: string, children: ReactNode) =>
    blockRefEnabled ? (
      <button
        type="button"
        className="dock-blockref"
        title={`在画布打开 ${name}`}
        onClick={() => onOpenBlock?.(name)}
      >
        {children}
      </button>
    ) : null;
  return {
    pre({ children, ...props }) {
      return (
        <pre className="md-pre" {...props}>
          {children}
        </pre>
      );
    },
    code({ className, children, ...props }) {
      const text = String(children).replace(/\n$/, "");
      const isBlock = Boolean(className) || text.includes("\n");
      if (isBlock) {
        const lang = (className || "").replace(/^language-/, "") || "scl";
        if (lang === "diff") {
          return <DiffLines text={text} />;
        }
        return (
          <code className={`md-code-block language-${lang}`} {...props}>
            {text}
          </code>
        );
      }
      if (blockRefEnabled && blockNames!.has(text)) {
        return renderBlockRef(text, text);
      }
      return (
        <code className="md-code-inline" {...props}>
          {children}
        </code>
      );
    },
    a({ href, children, ...props }) {
      if (blockRefEnabled && typeof href === "string" && href.startsWith(BLOCK_HREF_PREFIX)) {
        const name = decodeBlockHref(href.slice(BLOCK_HREF_PREFIX.length));
        if (blockNames!.has(name)) return renderBlockRef(name, children);
      }
      return (
        <a href={href} {...props}>
          {children}
        </a>
      );
    },
    p({ children }) {
      return <p className="md-p">{withCitationRefs(children)}</p>;
    },
    ul({ children }) {
      return <ul className="md-ul">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="md-ol">{children}</ol>;
    },
    li({ children }) {
      return <li className="md-li">{withCitationRefs(children)}</li>;
    },
    strong({ children }) {
      return <strong className="md-strong">{children}</strong>;
    },
  };
}

type Props = {
  content: string;
  className?: string;
  /** 已知块名集合(canvas.blocks 键):命中的 #block: 链接与行内代码块名渲染为可点击块引用 */
  blockNames?: Set<string>;
  /** 点击块引用 → 打开对应功能块(未传时按普通链接/行内代码渲染) */
  onOpenBlock?: (name: string) => void;
};

/** Render assistant / PLC answers as Markdown (SCL fences, bold, lists). */
export default function MarkdownBody({ content, className, blockNames, onOpenBlock }: Props) {
  const components = useMemo(
    () => makeComponents(blockNames, onOpenBlock),
    [blockNames, onOpenBlock],
  );
  return (
    <div className={className ? `markdown-body ${className}` : "markdown-body"}>
      <ReactMarkdown components={components}>{content}</ReactMarkdown>
    </div>
  );
}
