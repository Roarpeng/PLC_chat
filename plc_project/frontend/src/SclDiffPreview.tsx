import { useState } from "react";

export type SclDiffItem = {
  block?: string;
  before?: string;
  after?: string;
  diff?: string;
  new_block?: boolean;
};

type Pane = "diff" | "after" | "before";

export function DiffLines({ text }: { text: string }) {
  const lines = text.replace(/\n$/, "").split("\n");
  return (
    <code className="md-code-block language-diff">
      {lines.map((line, i) => {
        let cls = "scl-diff-ctx";
        if (
          line.startsWith("+++") ||
          line.startsWith("---") ||
          line.startsWith("diff ") ||
          line.startsWith("index ")
        ) {
          cls = "scl-diff-meta";
        } else if (line.startsWith("@@")) {
          cls = "scl-diff-hunk";
        } else if (line.startsWith("+")) {
          cls = "scl-diff-add";
        } else if (line.startsWith("-")) {
          cls = "scl-diff-del";
        }
        return (
          <span key={i} className={cls}>
            {line}
            {"\n"}
          </span>
        );
      })}
    </code>
  );
}

function SclSource({ text }: { text: string }) {
  return (
    <pre className="md-pre scl-diff-pre">
      <code className="md-code-block language-scl">{text.replace(/\n$/, "")}</code>
    </pre>
  );
}

function OneDiff({ item }: { item: SclDiffItem }) {
  const [pane, setPane] = useState<Pane>(item.diff?.trim() ? "diff" : "after");
  const name = item.block || "?";
  const diff = String(item.diff || "").trim();
  const after = String(item.after || "").trim();
  const before = String(item.before || "").trim();
  const panes: Array<{ id: Pane; label: string; enabled: boolean }> = [
    { id: "diff", label: "Diff", enabled: Boolean(diff) },
    { id: "after", label: "改写后", enabled: Boolean(after) },
    { id: "before", label: "改写前", enabled: Boolean(before) },
  ];
  const active = panes.find((p) => p.id === pane && p.enabled)?.id || panes.find((p) => p.enabled)?.id;
  return (
    <article className="scl-preview-card">
      <header className="scl-preview-head">
        <strong className="scl-preview-title">
          SCL 预览 · `{name}`
          {item.new_block ? <span className="scl-preview-badge">新建</span> : null}
        </strong>
        <div className="scl-preview-tabs" role="tablist" aria-label={`${name} SCL 预览`}>
          {panes.map((p) => (
            <button
              key={p.id}
              type="button"
              role="tab"
              aria-selected={active === p.id}
              disabled={!p.enabled}
              className={active === p.id ? "is-active" : ""}
              onClick={() => p.enabled && setPane(p.id)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </header>
      <div className="scl-preview-pane" data-pane={active}>
        {active === "diff" && diff ? (
          <pre className="md-pre scl-diff-pre">
            <DiffLines text={diff} />
          </pre>
        ) : null}
        {active === "after" && after ? <SclSource text={after} /> : null}
        {active === "before" && before ? <SclSource text={before} /> : null}
        {!diff && !after && !before ? (
          <p className="scl-preview-empty">该块没有可展示的 SCL 文本。</p>
        ) : null}
      </div>
    </article>
  );
}

export function looksLikeSclPreviewMessage(content: string): boolean {
  return /\*\*优化SCL|### 优化提案/.test(content);
}

export function stripSclPreviewFences(content: string): string {
  return content.replace(/\n```(?:diff|scl)[^\n]*\n[\s\S]*?\n```/g, "").trimEnd();
}

export function previewFocusFromMessage(content: string): string | null {
  const hit = content.match(/\*\*优化SCL\*\*（`([^`]+)`）/);
  return hit?.[1] || null;
}

type Props = {
  diffs: SclDiffItem[];
  emptyHint?: string;
};

export default function SclDiffPreview({ diffs, emptyHint }: Props) {
  const items = diffs.filter((d) => d.diff?.trim() || d.after?.trim() || d.before?.trim());
  if (!items.length) {
    if (!emptyHint) return null;
    return <p className="scl-preview-empty">{emptyHint}</p>;
  }
  return (
    <div className="scl-preview-stack">
      {items.map((d, i) => (
        <OneDiff key={`${d.block || "block"}-${i}`} item={d} />
      ))}
    </div>
  );
}

