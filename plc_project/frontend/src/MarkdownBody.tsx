import { Children, createElement, type ReactNode } from "react";
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

const components: Components = {
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
    return (
      <code className="md-code-inline" {...props}>
        {children}
      </code>
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

type Props = {
  content: string;
  className?: string;
};

/** Render assistant / PLC answers as Markdown (SCL fences, bold, lists). */
export default function MarkdownBody({ content, className }: Props) {
  return (
    <div className={className ? `markdown-body ${className}` : "markdown-body"}>
      <ReactMarkdown components={components}>{content}</ReactMarkdown>
    </div>
  );
}
