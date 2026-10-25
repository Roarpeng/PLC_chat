import { useEffect, useState, type FC } from "react";
import {
  V_LEVELS,
  changeStatusGroup,
  changeStatusText,
  fetchChange,
  formatChangeTime,
  shortChangeId,
  vStatusOf,
  vStatusText,
  type PcecChange,
  type PcecOrigin,
} from "../state/pcec";
import { fetchSourceArtifact, type SourceArtifact } from "../state/sourceCompare";
import {
  REQUIREMENT_ITEM_KINDS,
  REQUIREMENT_SOURCE_LABELS,
  REQUIREMENT_STATUS_TEXT,
  mockRequirement,
  type Requirement,
} from "../state/requirements";
import "./requirements.css";

/* ==========================================================================
   ChangeReviewDrawer — 四层变更审查抽屉（契约 22 §3，正式版）
   从变更记录条目点「审查」打开：对一条 PCEC 事务做四层审查——
     ① 工艺差异：requirement.items 分组摘要 + 确认状态徽章（无关联 → 说明）
     ② 逻辑差异：change.impact.blocks / signals / hmi_widgets 三组清单，
        行可点击 → onFocusTarget({blockName} | {varName}) 定位画布证据
     ③ 源码差异：最简实现——左栏对 impact.blocks[0] 取 literal_scl 工件
        （复用 state/sourceCompare.fetchSourceArtifact，自带 mock 回退），
        右栏显示 change 摘要文本；无块 / 取不到 → 说明占位
     ④ 验证差异：复用 state/pcec 的 V_LEVELS / vStatusText 渲染四态
        （skipped / 未设 = 未运行，绝不渲染为通过）+ detail.diagnostics 列表
   数据：fetchChange(changeId)（pcec.ts 只读复用，mock-first 自动回退示例事务）；
   requirement 由 props 传入；changes/requirements 均不可用时显示内置示例并标注。
   Esc / 遮罩 / × 关闭。
   ========================================================================== */

export interface ChangeReviewDrawerProps {
  open: boolean;
  changeId: string | null;
  /** change.intent.requirement_id 命中时由 F1 传入；缺省且事务为示例时回退内置示例卡 */
  requirement?: Requirement | null;
  /** 证据定位回调（②逻辑差异行点击） */
  onFocusTarget: (t: { blockName?: string; varName?: string }) => void;
  onClose: () => void;
}

type TabKey = "process" | "logic" | "source" | "verify";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "process", label: "① 工艺差异" },
  { key: "logic", label: "② 逻辑差异" },
  { key: "source", label: "③ 源码差异" },
  { key: "verify", label: "④ 验证差异" },
];

/** 事务加载状态 */
type ChangeState = {
  status: "loading" | "ready";
  change: PcecChange | null;
  origin: PcecOrigin;
};

const CHANGE_LOADING: ChangeState = { status: "loading", change: null, origin: "gateway" };

/** ③ 左栏工件加载状态（按块缓存；切事务重置） */
type SourceState = {
  status: "idle" | "loading" | "ready";
  blockName: string | null;
  artifact: SourceArtifact | null;
};

const SOURCE_IDLE: SourceState = { status: "idle", blockName: null, artifact: null };

/** impact.blocks 缺失时退 touched_blocks（pcec meta 与完整事务的字段兼容） */
function impactBlocksOf(change: PcecChange | null): string[] {
  const impact = change?.impact;
  if (Array.isArray(impact?.blocks) && impact.blocks.length) return impact.blocks;
  return Array.isArray(change?.touched_blocks) ? change.touched_blocks : [];
}

function impactSignalsOf(change: PcecChange | null): string[] {
  const signals = change?.impact?.signals;
  return Array.isArray(signals) ? signals : [];
}

function impactWidgetsOf(change: PcecChange | null): string[] {
  const widgets = change?.impact?.hmi_widgets;
  return Array.isArray(widgets) ? widgets : [];
}

/** diagnostics 条目 → 一行文本（字符串直出；对象取 severity/message 等常见字段） */
function diagText(d: unknown): string {
  if (typeof d === "string") return d;
  if (d && typeof d === "object") {
    const r = d as Record<string, unknown>;
    const parts = [
      r.severity,
      r.message ?? r.text ?? r.description ?? r.title,
      r.path ?? r.block ?? r.block_name,
      r.line !== undefined ? `line ${String(r.line)}` : undefined,
    ]
      .filter((v) => v !== undefined && v !== null && String(v).trim() !== "")
      .map((v) => String(v));
    if (parts.length) return parts.join(" · ");
    try {
      return JSON.stringify(d);
    } catch {
      return String(d);
    }
  }
  return String(d ?? "");
}

function isFailDiag(d: unknown): boolean {
  if (d && typeof d === "object") {
    const sev = String((d as Record<string, unknown>).severity ?? "").toLowerCase();
    return sev.includes("error") || sev.includes("fail");
  }
  return false;
}

/** verification.detail.diagnostics（坏形态一律空数组） */
function diagnosticsOf(change: PcecChange | null): unknown[] {
  const detail = (change?.verification as Record<string, unknown> | null | undefined)?.detail;
  const diags = (detail as Record<string, unknown> | null | undefined)?.diagnostics;
  return Array.isArray(diags) ? diags : [];
}

export const ChangeReviewDrawer: FC<ChangeReviewDrawerProps> = ({
  open,
  changeId,
  requirement,
  onFocusTarget,
  onClose,
}) => {
  const [tab, setTab] = useState<TabKey>("process");
  const [changeState, setChangeState] = useState<ChangeState>(CHANGE_LOADING);
  const [source, setSource] = useState<SourceState>(SOURCE_IDLE);

  /* Esc 关闭（open=false 时不挂监听） */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  /* 打开 / 换 changeId → 拉完整事务（fetchChange 自带 mock 回退，绝不抛错） */
  useEffect(() => {
    if (!open || !changeId) {
      setChangeState(CHANGE_LOADING);
      return;
    }
    let alive = true;
    setChangeState(CHANGE_LOADING);
    setSource(SOURCE_IDLE);
    setTab("process");
    void fetchChange(changeId).then((res) => {
      if (!alive) return;
      setChangeState(
        res
          ? { status: "ready", change: res.change, origin: res.origin }
          : { status: "ready", change: null, origin: "gateway" },
      );
    });
    return () => {
      alive = false;
    };
  }, [open, changeId]);

  const change = changeState.status === "ready" ? changeState.change : null;
  const impactBlocks = impactBlocksOf(change);
  const firstBlock = impactBlocks[0] ?? null;

  /* 工艺差异页展示的需求：props 优先；事务为示例回退时补内置示例卡（标注） */
  const reqIsMockFallback = !requirement && changeState.origin === "mock";
  const shownRequirement: Requirement | null =
    requirement ?? (reqIsMockFallback ? mockRequirement() : null);

  /* ③ 源码差异：进入该 Tab 且有首个影响块时按需拉 literal_scl（按块缓存） */
  useEffect(() => {
    if (!open || tab !== "source" || !firstBlock) return;
    if (source.blockName === firstBlock && source.status !== "idle") return;
    let alive = true;
    setSource({ status: "loading", blockName: firstBlock, artifact: null });
    void fetchSourceArtifact(firstBlock, "literal_scl", {
      projectName: shownRequirement?.project_name || undefined,
    }).then((artifact) => {
      if (!alive) return;
      setSource({ status: "ready", blockName: firstBlock, artifact });
    });
    return () => {
      alive = false;
      setSource((prev) => (prev.status === "loading" ? { ...prev, status: "idle" } : prev));
    };
  }, [open, tab, firstBlock]);

  if (!open) return null;

  const verification = (change?.verification ?? {}) as Record<string, unknown>;
  const diagnostics = diagnosticsOf(change);

  /* ③ 右栏：change 摘要文本（意图 / 状态 / 影响块 / 时间） */
  const changeSummaryText = change
    ? [
        `事务 ${shortChangeId(change.change_id)} · ${changeStatusText(change.status)}`,
        `意图：${String(change?.intent?.summary ?? change?.intent?.request ?? "—")}`,
        `影响块：${impactBlocks.length ? impactBlocks.join(", ") : "—"}`,
        `更新：${formatChangeTime(change.updated_at ?? change.created_at)}`,
      ].join("\n")
    : "";

  return (
    <div
      className="crd-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="crd-card"
        role="dialog"
        aria-modal="true"
        aria-label="变更审查 · 四层差异"
      >
        <header className="crd-head">
          <div className="crd-head__title">
            <span className="crd-head__name">变更审查</span>
            <span className="crd-head__id" title={changeId ?? ""}>
              {changeId ? shortChangeId(changeId) : "—"}
            </span>
            {change && (
              <span className={"rcd-status rcd-status--" + changeStatusGroup(change.status)}>
                {changeStatusText(change.status)}
              </span>
            )}
          </div>
          <div className="crd-tabs" role="tablist" aria-label="四层审查">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={"crd-tab" + (tab === t.key ? " crd-tab--on" : "")}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button type="button" className="crd-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="crd-body">
          {changeState.status === "loading" && (
            <div className="crd-hint">正在拉取变更事务（未就绪时展示内置示例）…</div>
          )}

          {changeState.status === "ready" && !change && (
            <div className="crd-hint">事务不可用：changeId 为空或拉取失败且无示例可回退。</div>
          )}

          {changeState.status === "ready" && change && tab === "process" && (
            <div className="crd-panel">
              {shownRequirement ? (
                <>
                  <div className="crd-req__head">
                    <span className="crd-req__summary">
                      {shownRequirement.intent_summary || "（无意图摘要）"}
                    </span>
                    <span
                      className={
                        "rcd-status rcd-status--" + shownRequirement.confirmation_status
                      }
                    >
                      {REQUIREMENT_STATUS_TEXT[shownRequirement.confirmation_status]}
                    </span>
                    {reqIsMockFallback && (
                      <span className="rcd-origin rcd-origin--mock">示例需求卡</span>
                    )}
                  </div>
                  {REQUIREMENT_ITEM_KINDS.map(({ kind, label }) => {
                    const items = shownRequirement.items.filter((it) => it.kind === kind);
                    if (!items.length) return null;
                    return (
                      <div className="crd-list" key={kind}>
                        <div className="crd-list__head">
                          <span className="crd-list__title">{label}</span>
                          <span className="crd-list__count">{items.length}</span>
                        </div>
                        {items.map((it) => (
                          <div className="crd-row crd-row--plain" key={it.id}>
                            <span className={"rcd-src rcd-src--" + it.source}>
                              {REQUIREMENT_SOURCE_LABELS[it.source]}
                            </span>
                            {it.source === "engineering" && it.source_ref && (
                              <span className="rcd-ref" title={`证据定位：${it.source_ref}`}>
                                {it.source_ref}
                              </span>
                            )}
                            <span>{it.text}</span>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                  {shownRequirement.open_questions.length > 0 && (
                    <div className="crd-list">
                      <div className="crd-list__head">
                        <span className="crd-list__title" style={{ color: "var(--fault)" }}>
                          待工程师确认
                        </span>
                        <span className="crd-list__count">
                          {shownRequirement.open_questions.length}
                        </span>
                      </div>
                      {shownRequirement.open_questions.map((q, i) => (
                        <div className="crd-row crd-row--plain" key={i}>
                          <span style={{ color: "var(--fault)" }}>· {q}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="crd-hint">
                  未关联需求：这条事务产生于工艺需求卡功能上线之前，或由自由对话直接发起，
                  没有可对照的工艺意图拆解。新的写回可先经「确认工艺意图」建立关联。
                </div>
              )}
            </div>
          )}

          {changeState.status === "ready" && change && tab === "logic" && (
            <div className="crd-panel">
              <div className="crd-list">
                <div className="crd-list__head">
                  <span className="crd-list__title">受影响块</span>
                  <span className="crd-list__count">{impactBlocks.length}</span>
                </div>
                {impactBlocks.length === 0 && (
                  <div className="crd-row crd-row--plain">（无）</div>
                )}
                {impactBlocks.map((b) => (
                  <button
                    type="button"
                    className="crd-row"
                    key={`b-${b}`}
                    title="定位到画布中的块"
                    onClick={() => onFocusTarget({ blockName: b })}
                  >
                    <span className="crd-row__arrow">›</span>
                    <span>{b}</span>
                  </button>
                ))}
              </div>
              <div className="crd-list">
                <div className="crd-list__head">
                  <span className="crd-list__title">受影响信号</span>
                  <span className="crd-list__count">{impactSignalsOf(change).length}</span>
                </div>
                {impactSignalsOf(change).length === 0 && (
                  <div className="crd-row crd-row--plain">（无）</div>
                )}
                {impactSignalsOf(change).map((s) => (
                  <button
                    type="button"
                    className="crd-row"
                    key={`s-${s}`}
                    title="定位画布中的变量引用"
                    onClick={() => onFocusTarget({ varName: s })}
                  >
                    <span className="crd-row__arrow">›</span>
                    <span>{s}</span>
                  </button>
                ))}
              </div>
              <div className="crd-list">
                <div className="crd-list__head">
                  <span className="crd-list__title">受影响 HMI 元件</span>
                  <span className="crd-list__count">{impactWidgetsOf(change).length}</span>
                </div>
                {impactWidgetsOf(change).length === 0 && (
                  <div className="crd-row crd-row--plain">（无）</div>
                )}
                {impactWidgetsOf(change).map((w) => (
                  <div className="crd-row crd-row--plain" key={`w-${w}`} title="HMI 元件（画布暂无对应定位目标）">
                    <span className="crd-row__arrow">·</span>
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {changeState.status === "ready" && change && tab === "source" && (
            <div className="crd-panel">
              {!firstBlock ? (
                <div className="crd-hint">
                  本事务没有受影响块，无源码差异可对照（如纯变量 / HMI 变更）。
                </div>
              ) : (
                <div className="crd-diff">
                  <div className="crd-pane">
                    <div className="crd-pane__head">
                      <span className="crd-pane__label">改前 · 直译 SCL（{firstBlock}）</span>
                      <span className="crd-pane__meta">
                        {source.status === "loading" && <span>拉取中…</span>}
                        {source.status === "ready" &&
                          source.artifact?.origin === "mock" && (
                            <span className="rcd-origin rcd-origin--mock">示例</span>
                          )}
                        {source.status === "ready" &&
                          source.artifact?.origin === "gateway" && (
                            <span>job {source.artifact.job_id ?? "—"}</span>
                          )}
                      </span>
                    </div>
                    <div className="crd-pane__scroll">
                      {source.status !== "ready" ? (
                        <div className="crd-hint">正在按需拉取 literal_scl 工件…</div>
                      ) : (
                        <pre className="crd-pre">{source.artifact?.content ?? ""}</pre>
                      )}
                    </div>
                  </div>
                  <div className="crd-pane">
                    <div className="crd-pane__head">
                      <span className="crd-pane__label">改后 · 变更摘要</span>
                    </div>
                    <div className="crd-pane__scroll">
                      <pre className="crd-pre">{changeSummaryText}</pre>
                    </div>
                  </div>
                </div>
              )}
              <div className="crd-hint">
                最简对照：左栏为首个受影响块的 1:1 直译 SCL（服务端工件），右栏为本事务
                摘要；块级改前/改后逐行 diff 待回写工件落地后接入。
              </div>
            </div>
          )}

          {changeState.status === "ready" && change && tab === "verify" && (
            <div className="crd-panel">
              {V_LEVELS.map((v) => {
                const raw = verification[v.key];
                const st = vStatusOf(raw);
                const note =
                  v.key === "v2_tia_compile" &&
                  verification.detail &&
                  typeof verification.detail === "object" &&
                  (verification.detail as Record<string, unknown>).error_count !== undefined
                    ? `编译错误 ${String(
                        (verification.detail as Record<string, unknown>).error_count,
                      )} 处`
                    : raw === undefined
                      ? "未上报（按未运行展示）"
                      : "";
                return (
                  <div className="crd-vrow" key={v.key}>
                    <span className="crd-vrow__level" title={v.full}>
                      {v.label}
                    </span>
                    <span className={`crd-vrow__state crd-vrow__state--${st}`}>
                      {vStatusText(raw)}
                    </span>
                    <span className="crd-vrow__note">{note}</span>
                  </div>
                );
              })}
              <div className="crd-diags">
                <div className="crd-diags__title">诊断明细（detail.diagnostics）</div>
                {diagnostics.length === 0 ? (
                  <div className="crd-hint">（无诊断记录）</div>
                ) : (
                  diagnostics.map((d, i) => (
                    <div
                      key={i}
                      className={"crd-diag" + (isFailDiag(d) ? " crd-diag--fail" : "")}
                    >
                      {diagText(d)}
                    </div>
                  ))
                )}
              </div>
              <div className="crd-hint">未知 ≠ 通过：skipped / 未上报的等级一律按「未运行」展示。</div>
            </div>
          )}
        </div>

        <footer className="crd-foot">
          <span className="crd-foot__stats">
            {changeState.status !== "ready"
              ? "拉取中…"
              : changeState.origin === "mock"
                ? "网关事务未就绪 · 内置示例"
                : `网关事务 · ${shortChangeId(changeId)}`}
          </span>
          <span className="crd-foot__hint">Esc / 点击遮罩关闭 · ② 点击行定位画布证据</span>
        </footer>
      </section>
    </div>
  );
};
