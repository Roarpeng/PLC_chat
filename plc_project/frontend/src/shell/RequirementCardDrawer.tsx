import { useEffect, type FC } from "react";
import {
  MOCK_REQUIREMENT_ID,
  REQUIREMENT_ITEM_KINDS,
  REQUIREMENT_SOURCE_LABELS,
  REQUIREMENT_STATUS_TEXT,
  TASK_KIND_LABELS,
  shortRequirementId,
  type Requirement,
} from "../state/requirements";
import "./requirements.css";

/* ==========================================================================
   RequirementCardDrawer — 需求卡抽屉（契约 22 §3，正式版）
   工艺需求先行的核心交互：intent_summary（可编辑）、items 按五类分组渲染
   （前置 / 正常序列 / 异常分支 / 约束 / 验收），每条带三态来源徽章——
   engineering=绿·工程证据（附 source_ref 文本）/ user=蓝·用户输入 /
   inferred=琥珀·AI 推断；open_questions 红色「待工程师确认」区。
   底部主按钮「确认工艺意图」+ 副文案「确认仅表示工艺意图已确认，不会修改工程」
   ——confirmed 后按钮徽章化并禁用（铁律：确认不产生任何 ops / 写回，由 F1
   持有 requirement 并回调 onEdit / onConfirmIntent 决定持久化）。
   loading → 骨架；Esc / 遮罩 / × 关闭；示例卡（mock id）显示「示例」徽标。
   ========================================================================== */

export interface RequirementCardDrawerProps {
  open: boolean;
  requirement: Requirement | null;
  /** 草稿生成 / 拉取中 → 骨架屏 */
  loading?: boolean;
  /** 工程师编辑（intent_summary / items 文本 / open_questions），回传整个新对象 */
  onEdit: (r: Requirement) => void;
  /** 仅确认工艺意图（F1 负责 PUT confirmed；本按钮绝不触发 ops / 写回） */
  onConfirmIntent: (r: Requirement) => void;
  /** 一键生成标准结构工程块 */
  onGenerateAf?: (r: Requirement) => void;
  onClose: () => void;
}

export const RequirementCardDrawer: FC<RequirementCardDrawerProps> = ({
  open,
  requirement,
  loading = false,
  onEdit,
  onConfirmIntent,
  onGenerateAf,
  onClose,
}) => {
  /* Esc 关闭（与 ChangeLogDrawer 同款；open=false 时不挂监听） */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const confirmed = requirement?.confirmation_status === "confirmed";
  const isMock = requirement?.requirement_id === MOCK_REQUIREMENT_ID;

  /* —— 编辑回调：全部走 onEdit 回传整个新对象（父层持有唯一数据源） —— */

  const editSummary = (text: string) => {
    if (!requirement) return;
    onEdit({ ...requirement, intent_summary: text });
  };

  const editItemText = (itemId: string, text: string) => {
    if (!requirement) return;
    onEdit({
      ...requirement,
      items: requirement.items.map((it) => (it.id === itemId ? { ...it, text } : it)),
    });
  };

  const editQuestion = (index: number, text: string) => {
    if (!requirement) return;
    onEdit({
      ...requirement,
      open_questions: requirement.open_questions.map((q, i) => (i === index ? text : q)),
    });
  };

  return (
    <div
      className="rcd-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="rcd-card"
        role="dialog"
        aria-modal="true"
        aria-label="工艺需求卡 · 需求先行"
      >
        <header className="rcd-head">
          <div className="rcd-head__main">
            <span className="rcd-head__name">工艺需求卡</span>
            {requirement && (
              <span className="rcd-head__id" title={requirement.requirement_id}>
                {shortRequirementId(requirement.requirement_id)}
              </span>
            )}
            {requirement && (
              <span className="rcd-head__sub" title={requirement.project_name}>
                {requirement.project_name || "—"} ·{" "}
                {TASK_KIND_LABELS[requirement.task_kind] ?? requirement.task_kind}
              </span>
            )}
            {isMock && <span className="rcd-origin rcd-origin--mock">示例</span>}
            {requirement && (
              <span className={`rcd-status rcd-status--${requirement.confirmation_status}`}>
                {REQUIREMENT_STATUS_TEXT[requirement.confirmation_status]}
              </span>
            )}
          </div>
          <button type="button" className="rcd-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="rcd-body">
          {loading && (
            <div className="rcd-skeleton" aria-label="需求卡生成中">
              <div className="rcd-skeleton__bar rcd-skeleton__bar--w40" />
              <div className="rcd-skeleton__bar rcd-skeleton__bar--w85" />
              <div className="rcd-skeleton__bar rcd-skeleton__bar--w60" />
              <div className="rcd-skeleton__bar rcd-skeleton__bar--w85" />
              <div className="rcd-skeleton__bar rcd-skeleton__bar--w60" />
              <div className="rcd-skeleton__bar rcd-skeleton__bar--w40" />
              <div className="rcd-hint">正在生成需求卡草稿（不确定的内容会标「AI 推断」并进待确认区）…</div>
            </div>
          )}

          {!loading && !requirement && (
            <div className="rcd-hint">
              暂无需求卡：从任务条选择「完善工艺逻辑」或在对话里描述工艺意图，
              可生成一张草稿卡（后端未就绪时展示内置示例）。
            </div>
          )}

          {!loading && requirement && (
            <>
              {/* —— 工艺意图（一句话，可编辑） —— */}
              <div className="rcd-section">
                <label className="rcd-section__title" htmlFor="rcd-summary">
                  工艺意图
                </label>
                <input
                  id="rcd-summary"
                  type="text"
                  className="rcd-summary"
                  value={requirement.intent_summary}
                  aria-label="工艺意图（可编辑）"
                  placeholder="一句话说清这次要实现的工艺意图"
                  onChange={(e) => editSummary(e.target.value)}
                />
              </div>

              {/* —— items 五类分组（每条：来源徽章 + 证据 ref + 可编辑文本） —— */}
              {REQUIREMENT_ITEM_KINDS.map(({ kind, label }) => {
                const items = requirement.items.filter((it) => it.kind === kind);
                return (
                  <div className="rcd-group" key={kind}>
                    <div className="rcd-group__title">
                      {label}
                      <span className="rcd-group__count">{items.length}</span>
                    </div>
                    {items.length === 0 && (
                      <div className="rcd-group__empty">（本类暂无条目）</div>
                    )}
                    {items.map((it) => (
                      <div className="rcd-item" key={it.id}>
                        <span
                          className={`rcd-src rcd-src--${it.source}`}
                          title={
                            it.source === "engineering"
                              ? `工程证据${it.source_ref ? ` · ${it.source_ref}` : ""}`
                              : it.source === "user"
                                ? "来自工程师的输入"
                                : "AI 根据工程推断，待工程师确认"
                          }
                        >
                          {REQUIREMENT_SOURCE_LABELS[it.source]}
                        </span>
                        {it.source === "engineering" && it.source_ref && (
                          <span className="rcd-ref" title={`证据定位：${it.source_ref}`}>
                            {it.source_ref}
                          </span>
                        )}
                        <input
                          type="text"
                          className="rcd-item__text"
                          value={it.text}
                          aria-label={`${label}条目（可编辑）`}
                          onChange={(e) => editItemText(it.id, e.target.value)}
                        />
                      </div>
                    ))}
                  </div>
                );
              })}

              {/* —— 待工程师确认（红区，可编辑） —— */}
              <div className="rcd-questions">
                <div className="rcd-questions__title">待工程师确认</div>
                {requirement.open_questions.length === 0 && (
                  <div className="rcd-questions__empty">（无待确认问题）</div>
                )}
                {requirement.open_questions.map((q, i) => (
                  <input
                    key={i}
                    type="text"
                    className="rcd-question"
                    value={q}
                    aria-label={`待确认问题 ${i + 1}（可编辑）`}
                    onChange={(e) => editQuestion(i, e.target.value)}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        {!loading && requirement && (
          <footer className="rcd-foot">
            <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
              {confirmed ? (
                <>
                  <button
                    type="button"
                    className="rcd-confirm rcd-confirm--done"
                    disabled
                    aria-disabled="true"
                    title="工艺意图已确认（确认不产生任何工程修改）"
                  >
                    ✓ 工艺意图已确认
                  </button>
                  {onGenerateAf && (
                    <button
                      type="button"
                      className="rcd-confirm"
                      style={{ background: "var(--accent, #0066cc)", color: "#fff" }}
                      onClick={() => onGenerateAf(requirement)}
                      title="根据已确认的工艺意图自动生成标准工程块"
                    >
                      ⚡ 一键生成 PLC 逻辑方案
                    </button>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  className="rcd-confirm"
                  onClick={() => onConfirmIntent(requirement)}
                >
                  确认工艺意图
                </button>
              )}
            </div>
            <span className="rcd-foot__note">
              确认仅表示工艺意图已确认；点击「生成 PLC 逻辑方案」将按内置工程标准自动构建模块化结构并提交四层审查
            </span>
          </footer>
        )}
      </section>
    </div>
  );
};
