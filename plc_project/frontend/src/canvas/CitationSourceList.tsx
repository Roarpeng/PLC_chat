import type { PlcCitation } from "../../api";
import { citationLocator, citationSnippet } from "./inspectModel";

type Props = {
  citations: PlcCitation[];
  emptyHint?: string;
  onJump?: (ref: string) => void;
};

/** Accepts M3 citation shape `{block, locator, snippet}` and older evidence fields. */
export function CitationSourceList({ citations, emptyHint, onJump }: Props) {
  if (!citations.length) {
    return (
      <div className="cite-empty" role="status">
        <p>{emptyHint || "尚无引用源。落地后将显示 block · locator · snippet。"}</p>
        <div className="cite-placeholder" aria-hidden>
          <div className="cite-row">
            <code>Block</code>
            <span className="cite-loc">locator</span>
          </div>
          <p className="cite-snip">snippet…</p>
        </div>
      </div>
    );
  }
  return (
    <ul className="cite-list" aria-label="引用源">
      {citations.map((c, i) => {
        const loc = citationLocator(c);
        const snip = citationSnippet(c);
        const ref = c.nodeId || c.block || "";
        const status = String(c.source_status || "").trim();
        return (
          <li key={`${c.block}-${loc}-${i}`} className="cite-item">
            {ref && onJump ? (
              <button type="button" className="cite-jump" onClick={() => onJump(ref)}>
                <code>{c.block || ref}</code>
              </button>
            ) : (
              <code>{c.block || "—"}</code>
            )}
            {loc ? <span className="cite-loc">{loc}</span> : null}
            {status ? <span className="cite-status">{status}</span> : null}
            {snip ? <p className="cite-snip">{snip}</p> : <p className="cite-snip muted">无 snippet</p>}
          </li>
        );
      })}
    </ul>
  );
}
