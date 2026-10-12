import type { PlcCoverage, PlcJobDetail, PlcStructureUnit } from "../api";

function coverageConvertedPct(cov: PlcCoverage | null | undefined): number {
  const total = Number(cov?.total_blocks || 0);
  const converted = Number(cov?.converted || 0);
  if (!total) return 0;
  return Math.max(0, Math.min(100, Math.round((converted / total) * 100)));
}

function topTodoParts(cov: PlcCoverage | null | undefined, limit = 4): Array<{ name: string; count: number }> {
  const top = cov?.top_untranslated_parts || [];
  if (top.length) {
    return top
      .map((r) => ({ name: String(r.name || ""), count: Number(r.count || 0) }))
      .filter((r) => r.name)
      .slice(0, limit);
  }
  return Object.entries(cov?.todo_histogram || {})
    .map(([name, count]) => ({ name, count: Number(count) }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit);
}

function obCallTree(detail: PlcJobDetail | null): string[] {
  const nodes = detail?.logic_graph?.nodes || [];
  const edges = (detail?.logic_graph?.edges || []).filter((e) => String(e.type || "") === "CALLS");
  if (!edges.length) return [];
  const labelOf = (id: string) => {
    const n = nodes.find((x) => String(x.id || "") === id);
    const props = (n?.props || {}) as Record<string, unknown>;
    const raw = String(n?.label || props.name || id);
    return raw.includes("::") ? raw.split("::").pop() || raw : raw;
  };
  const obs = nodes.filter((n) => {
    const props = (n.props || {}) as Record<string, unknown>;
    const t = String(n.type || props.block_type || "").toUpperCase();
    const name = String(props.name || n.label || "");
    return t === "OB" || /^ob\d+/i.test(name) || name === "Main";
  });
  const roots = obs.length ? obs : nodes.slice(0, 1);
  const lines: string[] = [];
  for (const ob of roots.slice(0, 2)) {
    const oid = String(ob.id || "");
    const kids = edges
      .filter((e) => String(e.source || "") === oid)
      .map((e) => labelOf(String(e.target || "")))
      .filter(Boolean);
    if (!kids.length) continue;
    lines.push(`${labelOf(oid)} → ${kids.slice(0, 8).join(" → ")}`);
  }
  return lines.slice(0, 3);
}

function statusClass(status: string): string {
  if (status === "failed") return "is-failed";
  if (status === "skipped" || status === "pending") return "is-warning";
  return "is-ok";
}

function incompleteUnits(detail: PlcJobDetail | null): PlcStructureUnit[] {
  const units = detail?.structure?.units || [];
  if (units.length) {
    return units.filter((u) => {
      const st = String(u.status || "");
      return st === "failed" || st === "skipped" || st === "pending";
    });
  }
  return (detail?.blocks || [])
    .filter((b) => {
      const st = String(b.status || "exported");
      return st === "failed" || st === "skipped" || st === "pending";
    })
    .map((b) => ({
      name: b.name,
      kind: b.type,
      type: b.type,
      status: String(b.status || "pending"),
      reason: b.status_reason,
      detail: b.status_detail,
      retryable: b.retryable,
    }));
}

export function PlcCoverageStrip({
  detail,
  busy,
  onRetryStructure,
}: {
  detail: PlcJobDetail | null;
  busy?: boolean;
  onRetryStructure?: (names?: string[]) => Promise<void> | void;
}) {
  const cov = detail?.coverage;
  const structure = detail?.structure;
  const counts = structure?.counts;
  const incomplete = incompleteUnits(detail);
  const hasStructure = Boolean(counts?.total || incomplete.length);
  if (!cov?.total_blocks && !hasStructure) return null;
  const pct = coverageConvertedPct(cov);
  const r = 16;
  const c = 2 * Math.PI * r;
  const dash = (pct / 100) * c;
  const todos = topTodoParts(cov);
  const tree = obCallTree(detail);
  const rate = Number(cov?.todo_rate || 0);
  const failed = Number(counts?.failed || 0);
  const skipped = Number(counts?.skipped || 0);
  const pending = Number(counts?.pending || 0);
  const retryable = incomplete.filter((u) => u.retryable).map((u) => u.name);
  const stripClass = failed ? "is-failed" : skipped || pending ? "is-warning" : "";
  return (
    <div className={`plc-coverage ${stripClass}`.trim()} aria-label="转换覆盖率与可信结构">
      <svg className="plc-coverage-ring" viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">
        <circle cx="20" cy="20" r={r} fill="none" stroke="var(--line)" strokeWidth="4" />
        <circle
          cx="20"
          cy="20"
          r={r}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="4"
          strokeDasharray={`${dash} ${c - dash}`}
          strokeLinecap="round"
          transform="rotate(-90 20 20)"
        />
        <text x="20" y="22" textAnchor="middle" fontSize="9" fill="currentColor">
          {pct}%
        </text>
      </svg>
      <div className="plc-coverage-meta">
        <div>
          已转换 {cov?.converted ?? 0}/{cov?.total_blocks ?? 0} · TODO{" "}
          {rate.toLocaleString(undefined, { style: "percent", maximumFractionDigits: 1 })}
          {cov?.safety_block_count ? ` · F-block ${cov.safety_block_count}` : ""}
        </div>
        {counts ? (
          <div className="plc-structure-counts">
            结构清单 {counts.total ?? 0}：exported {counts.exported ?? 0}
            {failed ? <span className="plc-status-failed"> · failed {failed}</span> : null}
            {skipped ? <span className="plc-status-skipped"> · skipped {skipped}</span> : null}
            {pending ? <span className="plc-status-pending"> · pending {pending}</span> : null}
          </div>
        ) : null}
        {todos.length ? (
          <div className="plc-coverage-todos">
            未译 Part：
            {todos.map((t) => (
              <span key={t.name} className="plc-chip">
                {t.name} × {t.count}
              </span>
            ))}
          </div>
        ) : (
          <div className="muted">无未译 Part</div>
        )}
        {tree.length ? <div className="plc-coverage-tree">OB 调用：{tree.join("；")}</div> : null}
        {incomplete.length ? (
          <div className="plc-structure-list" aria-label="未完整导出单元">
            {incomplete.slice(0, 12).map((u) => (
              <span
                key={`${u.kind}-${u.name}`}
                className={`plc-chip ${statusClass(String(u.status))}`}
                title={u.detail || u.reason || String(u.status)}
              >
                {u.name}
                <em>{u.status}</em>
                {u.reason ? ` ${u.reason}` : ""}
              </span>
            ))}
            {incomplete.length > 12 ? (
              <span className="muted">+{incomplete.length - 12} 项见清单</span>
            ) : null}
            {onRetryStructure ? (
              <button
                type="button"
                className="ghost compact plc-structure-retry"
                disabled={busy}
                title={
                  retryable.length
                    ? `重试 ${retryable.length} 个可恢复单元`
                    : "重新导出全部结构清单"
                }
                onClick={() => void onRetryStructure(retryable.length ? retryable : undefined)}
              >
                重试导出
              </button>
            ) : null}
          </div>
        ) : counts && counts.total ? (
          <div className="muted">结构清单完整，无静默缺块</div>
        ) : null}
      </div>
    </div>
  );
}
