import React, { useMemo, useState } from "react";
import type { CanvasTagData } from "../canvas/types";
import type { CrossRefReport, VarEntry, VarRef } from "../state/crossRef";
import "./variables.css";

export interface VariableInspectorProps {
  /** 交叉引用分析报告 */
  report: CrossRefReport;
  /** 物理接线标签表（canvas.tags 的 values） */
  wiredTags: CanvasTagData[];
  /** 点击引用项 → 父级定位到中栏对应块/网络或 HMI */
  onJumpToRef(ref: VarRef): void;
  /** 隐藏本栏 */
  onCollapse(): void;
}

/** 摘要胶囊过滤模式 */
type FilterMode = "all" | "unused" | "undefined";

/** 列表分组：块名 + 该块（过滤后）的变量条目 */
interface BlockGroup {
  blockName: string;
  entries: VarEntry[];
}

export const VariableInspector: React.FC<VariableInspectorProps> = ({
  report,
  wiredTags,
  onJumpToRef,
  onCollapse,
}) => {
  const [filter, setFilter] = useState<FilterMode>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set<string>());

  // 轻量兜底：契约字段缺失时不至于整栏崩掉
  const entries = report?.entries ?? [];
  const unknownRefs = report?.unknownRefs ?? [];
  const hmiUnbound = report?.hmiUnbound ?? [];
  const stats = report?.stats ?? { total: entries.length, unused: 0, undefined: 0 };
  const tags = Array.isArray(wiredTags) ? wiredTags : [];

  const q = query.trim().toLowerCase();

  /** 过滤 + 搜索（name / blockName / dataType，大小写不敏感）组合生效，按块分组 */
  const groups = useMemo<BlockGroup[]>(() => {
    const matched = entries.filter((entry) => {
      if (filter === "unused" && entry.refs.length > 0) return false;
      if (q) {
        const hit =
          entry.def.name.toLowerCase().includes(q) ||
          entry.def.blockName.toLowerCase().includes(q) ||
          entry.def.dataType.toLowerCase().includes(q);
        if (!hit) return false;
      }
      return true;
    });
    const out: BlockGroup[] = [];
    const index = new Map<string, number>();
    for (const entry of matched) {
      const at = index.get(entry.def.blockName);
      if (at === undefined) {
        index.set(entry.def.blockName, out.length);
        out.push({ blockName: entry.def.blockName, entries: [entry] });
      } else {
        out[at].entries.push(entry);
      }
    }
    return out;
  }, [entries, filter, q]);

  const hasIssues = unknownRefs.length > 0 || hmiUnbound.length > 0;
  const hideVarRows = filter === "undefined"; // 未定义过滤：列表区只渲染问题区
  const canvasEmpty = entries.length === 0;
  const noMatch = !hideVarRows && !canvasEmpty && groups.length === 0;

  const toggleExpanded = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /** 点击已激活的胶囊 = 取消过滤，回到“变量” */
  const applyFilter = (mode: FilterMode) => {
    setFilter((prev) => (prev === mode ? "all" : mode));
  };

  return (
    <div className="vi-root">
      {/* 1. 头部：标题 + 隐藏按钮 */}
      <div className="vi-head">
        <div className="vi-title">变量与交叉引用</div>
        <button
          type="button"
          className="vi-hide"
          aria-label="隐藏变量面板"
          title="隐藏变量面板"
          onClick={onCollapse}
        >
          <svg
            viewBox="0 0 16 16"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M3.5 3.5 8 8 3.5 12.5" />
            <path d="M8.5 3.5 13 8 8.5 12.5" />
          </svg>
        </button>
      </div>

      {/* 2 + 3. 状态摘要胶囊 + 搜索 */}
      <div className="vi-controls">
        <div className="vi-pills" role="group" aria-label="状态过滤">
          <button
            type="button"
            className={"vi-pill vi-pill--all" + (filter === "all" ? " is-on" : "")}
            aria-pressed={filter === "all"}
            onClick={() => applyFilter("all")}
          >
            <span className="vi-pill__label">变量</span>
            <span className="vi-pill__num">{stats.total}</span>
          </button>
          <button
            type="button"
            className={"vi-pill vi-pill--unused" + (filter === "unused" ? " is-on" : "")}
            aria-pressed={filter === "unused"}
            onClick={() => applyFilter("unused")}
          >
            <span className="vi-pill__label">未使用</span>
            <span className={"vi-pill__num" + (stats.unused > 0 ? " is-positive" : "")}>
              {stats.unused}
            </span>
          </button>
          <button
            type="button"
            className={"vi-pill vi-pill--undef" + (filter === "undefined" ? " is-on" : "")}
            aria-pressed={filter === "undefined"}
            onClick={() => applyFilter("undefined")}
          >
            <span className="vi-pill__label">未定义</span>
            <span className={"vi-pill__num" + (stats.undefined > 0 ? " is-positive" : "")}>
              {stats.undefined}
            </span>
          </button>
        </div>

        <div className="vi-search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索变量 / 块 / 类型…"
            aria-label="搜索变量、块或类型"
            spellCheck={false}
          />
        </div>
      </div>

      {/* 4 + 5. 问题区（列表顶部） + 变量列表 */}
      <div className="vi-list">
        {hasIssues && (
          <div className="vi-issues">
            {unknownRefs.map((u, i) => (
              <div className="vi-issue" key={"unk-" + i}>
                <div className="vi-issue__main">
                  <span className="vi-issue__expr" title={u.expr}>
                    {u.expr}
                  </span>
                  <span className="vi-issue__loc">
                    {u.blockName} · NW{u.networkId}
                  </span>
                </div>
                <div className="vi-issue__note">引用了未定义的变量</div>
              </div>
            ))}
            {hmiUnbound.map((h, i) => (
              <div className="vi-issue" key={"hmi-" + i}>
                <div className="vi-issue__main">
                  <span className="vi-issue__expr" title={h.tag}>
                    {h.tag}
                  </span>
                  <span className="vi-issue__loc">{h.widgetTitle}</span>
                </div>
                <div className="vi-issue__note">HMI 绑定的变量不存在</div>
              </div>
            ))}
          </div>
        )}

        {hideVarRows ? (
          !hasIssues && <div className="vi-empty">没有未定义的变量。</div>
        ) : canvasEmpty ? (
          <div className="vi-empty">画布中还没有变量定义。</div>
        ) : noMatch ? (
          <div className="vi-empty">没有匹配的变量。</div>
        ) : (
          groups.map((group) => (
            <section className="vi-group" key={group.blockName}>
              <div className="vi-group__head">
                <span className="vi-group__name" title={group.blockName}>
                  {group.blockName}
                </span>
                <span className="vi-group__count">{group.entries.length}</span>
              </div>
              {group.entries.map((entry) => {
                const open = expanded.has(entry.def.key);
                const unused = entry.refs.length === 0;
                return (
                  <div className={"vi-var" + (open ? " is-open" : "")} key={entry.def.key}>
                    <button
                      type="button"
                      className="vi-var__head"
                      aria-expanded={open}
                      title={unused ? "未使用" : entry.refs.length + " 处引用"}
                      onClick={() => toggleExpanded(entry.def.key)}
                    >
                      <span className="vi-var__name">#{entry.def.name}</span>
                      <span className="vi-dots" aria-hidden="true" />
                      <span className="vi-var__type">{entry.def.dataType}</span>
                      <span className={"vi-var__count" + (unused ? " is-zero" : "")}>
                        {unused ? "未使用" : entry.refs.length}
                      </span>
                    </button>
                    {entry.def.comment ? (
                      <div className="vi-var__comment" title={entry.def.comment}>
                        {entry.def.comment}
                      </div>
                    ) : null}
                    {open && (
                      <div className="vi-var__refs">
                        {entry.refs.length === 0 ? (
                          <div className="vi-var__norefs">暂无引用</div>
                        ) : (
                          entry.refs.map((ref, j) => (
                            <button
                              type="button"
                              className="vi-ref"
                              key={entry.def.key + "-" + j}
                              title={ref.label}
                              onClick={() => onJumpToRef(ref)}
                            >
                              <span
                                className={
                                  "vi-ref__badge" +
                                  (ref.kind === "hmi" ? " vi-ref__badge--hmi" : "")
                                }
                              >
                                {ref.kind === "hmi" ? "HMI" : "NW"}
                              </span>
                              <span className="vi-ref__label">{ref.label}</span>
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </section>
          ))
        )}
      </div>

      {/* 6. 底部物理标签表（纯展示） */}
      {tags.length > 0 && (
        <div className="vi-tags">
          <div className="vi-tags__head">物理标签表</div>
          <div className="vi-tags__list">
            {tags.map((tag, i) => (
              <div className="vi-tag-row" key={tag.name + "-" + i} title={tag.comment || tag.name}>
                <span className="vi-tag-row__name">{tag.name}</span>
                <span className="vi-dots" aria-hidden="true" />
                <span className="vi-tag-row__addr">{tag.logical_address}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
