import { useCallback, useEffect, useRef, useState, type FC } from "react";
import {
  V_LEVELS,
  changeJsonPreview,
  changeStatusGroup,
  changeStatusText,
  fetchChange,
  fetchChanges,
  formatChangeTime,
  shortChangeId,
  vStatusOf,
  vStatusText,
  type PcecChange,
  type PcecChangeMeta,
  type PcecOrigin,
  type PcecVLevelKey,
} from "../state/pcec";
import "./changelog.css";

/* ==========================================================================
   ChangeLogDrawer — 顶栏「变更记录」抽屉（契约 19 §5）
   打开才挂载（懒加载）才拉取 GET /api/v1/plc/canvas/changes；
   条目 = 短 id + 时间 + 意图摘要 + 状态徽章 + 四 V 徽章（V0 结构 /
   V1 静态 / V2 编译 / V3 行为）+ 影响块数；点条目展开完整事务 JSON 摘要
   （<pre>，超长截断）。网关 404 / 不可达 → 内置示例事务（「示例」徽标）。
   refreshTick 递增（编译作业结束）→ 打开中的抽屉自动重拉账本与展开行。
   Esc / 遮罩 / × 关闭。只读展示，不进任何受控输入。
   ========================================================================== */

export interface ChangeLogDrawerProps {
  onClose(): void;
  /** 外部事件计数（编译作业结束由 App 递增）→ 打开中自动刷新 */
  refreshTick?: number;
}

/** 账本列表加载状态 */
type ListState = {
  status: "loading" | "ready";
  items: PcecChangeMeta[];
  origin: PcecOrigin;
};

/** 单条事务详情加载状态（按 change_id 缓存，重拉账本时清空） */
type DetailState = {
  status: "loading" | "ready" | "error";
  change: PcecChange | null;
  origin: PcecOrigin;
};

const LIST_LOADING: ListState = { status: "loading", items: [], origin: "gateway" };

/** 条目摘要展示兜底：summary → intent.request → kind → — */
function metaSummary(meta: PcecChangeMeta): string {
  const text = meta.summary || meta.kind;
  return text.trim() || "—";
}

/**
 * 条目四 V 徽章取值：详情已拉到用详情（最新），否则用 meta 携带的摘要，
 * 再否则全部未设（显示为「未运行」弱化态，展开后点亮）。
 */
function vBadgeSources(
  meta: PcecChangeMeta,
  detail: DetailState | undefined,
): Record<PcecVLevelKey, string | undefined> {
  const fromDetail = detail?.change?.verification as Record<string, unknown> | null | undefined;
  const fromMeta = (meta.verification ?? {}) as Record<string, unknown>;
  const src = (fromDetail && typeof fromDetail === "object" ? fromDetail : null) ?? fromMeta;
  return {
    v0_parsed: src.v0_parsed as string | undefined,
    v1_static: src.v1_static as string | undefined,
    v2_tia_compile: src.v2_tia_compile as string | undefined,
    v3_behavior: src.v3_behavior as string | undefined,
  };
}

export const ChangeLogDrawer: FC<ChangeLogDrawerProps> = ({ onClose, refreshTick = 0 }) => {
  const [list, setList] = useState<ListState>(LIST_LOADING);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, DetailState>>({});

  const expandedIdRef = useRef<string | null>(null);
  useEffect(() => {
    expandedIdRef.current = expandedId;
  }, [expandedId]);

  /* 拉单条详情（写 loading 占位，fetchChange 自带 mock 回退，绝不抛错） */
  const loadDetail = useCallback(async (id: string) => {
    setDetails((prev) => ({ ...prev, [id]: { status: "loading", change: null, origin: "gateway" } }));
    const res = await fetchChange(id);
    setDetails((prev) => ({
      ...prev,
      [id]: res
        ? { status: "ready", change: res.change, origin: res.origin }
        : { status: "error", change: null, origin: "gateway" },
    }));
  }, []);

  /** 重拉账本；keepExpanded 非空时连同其详情一起刷新（编译刚收敛，状态要新） */
  const reload = useCallback(
    async (keepExpanded: string | null) => {
      setList(LIST_LOADING);
      const res = await fetchChanges();
      setList({ status: "ready", items: res.items, origin: res.origin });
      setDetails({});
      if (keepExpanded) void loadDetail(keepExpanded);
    },
    [loadDetail],
  );

  /* 打开即拉取（懒加载：父层保证打开才挂载） */
  useEffect(() => {
    void reload(null);
  }, [reload]);

  /* refreshTick 递增（编译作业结束）→ 打开中的抽屉重拉；
     首跑（挂载）不重复拉，避免与上一条 effect 双发 */
  const lastTickRef = useRef(refreshTick);
  useEffect(() => {
    if (lastTickRef.current === refreshTick) return;
    lastTickRef.current = refreshTick;
    void reload(expandedIdRef.current);
  }, [refreshTick, reload]);

  /* Esc 关闭（与 SourceCompareDrawer 同款） */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /* 展开行无缓存时拉详情 */
  useEffect(() => {
    if (expandedId && !details[expandedId]) void loadDetail(expandedId);
  }, [expandedId, details, loadDetail]);

  const toggleRow = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const isMock = list.status === "ready" && list.origin === "mock";

  return (
    <div
      className="cl-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="cl-card"
        role="dialog"
        aria-modal="true"
        aria-label="变更记录 · 工程变更事务账本"
      >
        <header className="cl-head">
          <div className="cl-title">
            <span className="cl-title__name">变更记录</span>
            <span className="cl-title__sub">带证据的工程变更事务 · PCEC 账本</span>
            {isMock && <span className="cl-origin cl-origin--mock">示例</span>}
          </div>
          <button type="button" className="cl-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="cl-list" role="list">
          {list.status === "loading" && <div className="cl-hint">正在拉取变更账本（未就绪时展示内置示例）…</div>}

          {list.status === "ready" && list.items.length === 0 && (
            <div className="cl-hint">
              账本为空：还没有可审计的工程变更事务。「回写博图」确认执行后，每一次写回都会在这里记一条带证据的事务。
            </div>
          )}

          {list.status === "ready" &&
            list.items.map((meta) => {
              const expanded = expandedId === meta.change_id;
              const detail = details[meta.change_id];
              const badges = vBadgeSources(meta, detail);
              const group = changeStatusGroup(meta.status);
              return (
                <div key={meta.change_id} className={"cl-row" + (expanded ? " cl-row--open" : "")} role="listitem">
                  <button
                    type="button"
                    className="cl-row__head"
                    aria-expanded={expanded}
                    onClick={() => toggleRow(meta.change_id)}
                    title={expanded ? "收起事务详情" : "展开完整事务 JSON 摘要"}
                  >
                    <span className={"cl-chev" + (expanded ? " cl-chev--open" : "")}>›</span>
                    <span className="cl-id" title={meta.change_id}>
                      {shortChangeId(meta.change_id)}
                    </span>
                    <span className="cl-time">{formatChangeTime(meta.updated_at)}</span>
                    <span className="cl-summary">{metaSummary(meta)}</span>
                    <span className={"cl-status cl-status--" + group}>
                      {changeStatusText(meta.status)}
                    </span>
                    <span className="cl-vs">
                      {V_LEVELS.map((v) => {
                        const value = badges[v.key];
                        const cls = value === undefined ? "cl-v--off" : `cl-v--${vStatusOf(value)}`;
                        return (
                          <span
                            key={v.key}
                            className={"cl-v " + cls}
                            title={`${v.full} · ${vStatusText(value)}`}
                          >
                            {v.label}
                          </span>
                        );
                      })}
                    </span>
                    <span className="cl-touched" title="影响块数">
                      {meta.touched_count} 块
                    </span>
                  </button>

                  {expanded && (
                    <div className="cl-row__detail">
                      <div className="cl-detail__bar">
                        <span className="cl-detail__label">
                          事务 {shortChangeId(meta.change_id)} · 完整 JSON 摘要
                        </span>
                        {detail?.status === "ready" && detail.origin === "mock" && (
                          <span className="cl-origin cl-origin--mock">示例</span>
                        )}
                        {detail?.status === "loading" && <span className="cl-detail__meta">详情拉取中…</span>}
                        {detail?.status === "error" && (
                          <span className="cl-detail__meta">详情暂不可用</span>
                        )}
                      </div>
                      <pre className="cl-pre">{changeJsonPreview(detail?.change ?? null)}</pre>
                    </div>
                  )}
                </div>
              );
            })}
        </div>

        <footer className="cl-foot">
          <span className="cl-foot__stats">
            {list.status !== "ready"
              ? "拉取中…"
              : isMock
                ? "网关账本未就绪 · 内置示例事务"
                : `网关账本 · ${list.items.length} 条事务`}
          </span>
          <span className="cl-foot__hint">Esc / 点击遮罩关闭 · 点击条目展开完整事务 · 未知 ≠ 通过</span>
        </footer>
      </section>
    </div>
  );
};
