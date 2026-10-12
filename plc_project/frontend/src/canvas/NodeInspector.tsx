import type { KnowledgeNode } from "../../KnowledgeCanvas";
import { inspectNode, type InspectContext } from "./inspectModel";

type Props = {
  node: KnowledgeNode;
  ctx?: InspectContext;
  busy?: boolean;
  onAsk: (node: KnowledgeNode) => void;
  onViewSources: (node: KnowledgeNode) => void;
  onMarkNote: (node: KnowledgeNode) => void;
  onClose: () => void;
};

export function NodeInspector({
  node,
  ctx,
  busy,
  onAsk,
  onViewSources,
  onMarkNote,
  onClose,
}: Props) {
  const view = inspectNode(node, ctx);
  return (
    <aside className="kg-inspector" aria-label="节点速览">
      <div className="kg-inspector-head">
        <div className="kg-inspector-title">
          <span className={`kg-type-glyph gt-${view.graphType}`} aria-hidden>
            {view.typeGlyph}
          </span>
          <strong>{view.name}</strong>
        </div>
        <button type="button" className="ghost compact" onClick={onClose} aria-label="关闭速览">
          关闭
        </button>
      </div>
      <div className="kg-inspector-meta">
        <span>{view.typeLabel}</span>
        <span className={`kg-export-dot tone-${view.exportTone}`} title={view.exportStatus}>
          {view.exportStatus}
        </span>
      </div>
      <p className="kg-inspector-duty">{view.duty}</p>
      {view.ioLines.length ? (
        <ul className="kg-inspector-io" aria-label="关键 I/O">
          {view.ioLines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="kg-inspector-io muted">暂无 I/O 摘要</p>
      )}
      <div className="kg-inspector-actions">
        <button type="button" className="btn-primary compact" disabled={busy} onClick={() => onAsk(node)}>
          问这节点
        </button>
        <button type="button" className="ghost compact" onClick={() => onViewSources(node)}>
          看引用源
        </button>
        <button type="button" className="ghost compact" onClick={() => onMarkNote(node)}>
          标记人注
        </button>
      </div>
    </aside>
  );
}
