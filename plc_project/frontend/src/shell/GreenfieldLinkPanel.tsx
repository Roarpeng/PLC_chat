/**
 * 新建工程画布右栏（绑定变量工作台 + 外部只读契约解析 + 结构校验）：
 * - 支持上传外部文档（PDF / XLSX / CSV / SCL）或一键载入参考实例（PLC_IO.pdf + KUKA DB720 + PC DB1900）
 * - 展示三类变量：外部锁定 IO 表（%I/%Q/%IW/%QW）、外部冻结标准访问 DB（DB720 / DB1900 带 @Byte.Bit 偏移）、内部生成的变量（控制节点与执行件 PLCOpen 五信号）
 * - 支持一键将任意变量绑定至当前选中的工艺步序或执行件，并实时同步至 Mermaid 逻辑图
 * - 用户可见文案统一业务语言（工站 / 执行单元 / 执行件 / 设备交互），仅工程视角可切换
 */
import React, { useMemo, useRef, useState } from "react";
import type {
  GFCanvasOp,
  GFReport,
  GFState,
  GFVariableCatalog,
  GFWhitelist,
} from "../state/greenfield";
import { NodeEditor } from "./GreenfieldPanel";

export interface GreenfieldLinkPanelProps {
  whitelist: GFWhitelist | null;
  report: GFReport | null;
  state: GFState;
  busy: boolean;
  selectedHwNodeId: string | null;
  selectedTargetId: string;
  onSelectTarget: (targetId: string) => void;
  onUploadFiles: (files: FileList | null) => void;
  onUploadPastedScl: (sclText: string) => void;
  onConfirmReceipt: () => void;
  onBindVar: (varKey: string, targetId: string, role: string) => void;
  onUnbindVar: (varKey: string, targetId?: string) => void;
  onValidate: () => void;
  /** 结构节点增删改 / 重命名 / 重挂 / 改标签：走契约 §3 `POST /patch` op。 */
  onPatchNodes?: (ops: GFCanvasOp[]) => void;
  /** 最近一次变更事件的反馈文案。 */
  actionFeedback?: string;
}

type RightTab = "ext_io" | "ext_db" | "int_var" | "rules" | "nodes";

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

export const GreenfieldLinkPanel: React.FC<GreenfieldLinkPanelProps> = ({
  whitelist,
  report,
  state,
  busy,
  selectedHwNodeId,
  selectedTargetId,
  onSelectTarget,
  onUploadFiles,
  onUploadPastedScl,
  onConfirmReceipt,
  onBindVar,
  onUnbindVar,
  onValidate,
  onPatchNodes,
  actionFeedback,
}) => {
  const [activeTab, setActiveTab] = useState<RightTab>("ext_io");
  const [search, setSearch] = useState<string>("");
  const [selectedDbName, setSelectedDbName] = useState<string>("ALL");
  const [showPasteBox, setShowPasteBox] = useState<boolean>(false);
  const [pastedScl, setPastedScl] = useState<string>("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const catalog: GFVariableCatalog = useMemo(
    () =>
      state.hardware?.variable_catalog ?? {
        external_io: [],
        external_db: [],
        internal_vars: [],
        counts: {
          external_io: 0,
          external_db: 0,
          internal_vars: 0,
        },
      },
    [state.hardware],
  );

  const bindTargets = useMemo(() => {
    const steps = asArray(state.ir?.steps).map((s) => ({
      id: String(s.id),
      label: `[步序 S${String(s.step_id ?? "")}] ${String(s.name ?? s.id)}`,
      kind: "STEP",
    }));
    const cms = asArray(state.ir?.cms).map((c) => ({
      id: String(c.id),
      label: `[执行件] ${String(c.business_label ?? c.name ?? c.id)} (${String(c.cm_type ?? c.device_type ?? "")})`,
      kind: "执行件",
    }));
    return [...steps, ...cms];
  }, [state.ir]);

  const effectiveTargetId =
    selectedTargetId || (bindTargets.length > 0 ? bindTargets[0].id : "");

  const kw = search.trim().toLowerCase();

  const filteredIo = useMemo(() => {
    return catalog.external_io.filter((item) => {
      if (selectedHwNodeId && item.hw_node_id !== selectedHwNodeId) return false;
      if (!kw) return true;
      return (
        item.name.toLowerCase().includes(kw) ||
        item.logical_address.toLowerCase().includes(kw) ||
        item.comment.toLowerCase().includes(kw)
      );
    });
  }, [catalog.external_io, selectedHwNodeId, kw]);

  const dbGroups = useMemo(() => {
    const byDb = new Map<string, typeof catalog.external_db>();
    for (const item of catalog.external_db) {
      if (selectedHwNodeId && item.hw_node_id !== selectedHwNodeId) continue;
      const list = byDb.get(item.db_name) ?? [];
      list.push(item);
      byDb.set(item.db_name, list);
    }
    return Array.from(byDb.entries()).map(([db_name, allMembers]) => ({
      db_name,
      total_count: allMembers.length,
      members: allMembers.filter((m) => {
        if (!kw) return true;
        return (
          m.name.toLowerCase().includes(kw) ||
          String(m.offset).toLowerCase().includes(kw) ||
          m.data_type.toLowerCase().includes(kw) ||
          m.comment.toLowerCase().includes(kw)
        );
      }),
    }));
  }, [catalog.external_db, selectedHwNodeId, kw]);

  const filteredDbs = useMemo(() => {
    return dbGroups.filter(
      (g) => (selectedDbName === "ALL" || g.db_name === selectedDbName) && g.members.length > 0,
    );
  }, [dbGroups, selectedDbName]);

  const filteredInternal = useMemo(() => {
    return catalog.internal_vars.filter((v) => {
      if (!kw) return true;
      return (
        v.name.toLowerCase().includes(kw) ||
        v.owner_id.toLowerCase().includes(kw) ||
        v.role.toLowerCase().includes(kw)
      );
    });
  }, [catalog.internal_vars, kw]);

  const violations = report?.violations ?? [];
  const questions = [...(report?.open_questions ?? []), ...(state.notes ?? [])];

  return (
    <details className="gf-wiz-more" data-ui="greenfield-more-inputs">
      <summary className="gf-wiz-more__summary">更多输入方式（辅助）</summary>
      <div className="gf-wiz-more__body">
        <aside className="gf-side" data-ui="greenfield-link-panel">
      {/* 顶部：外部文档解析与锁定状态 */}
      <div className="gf-var-header">
        <div className="gf-var-header__top">
          <span className="gf-pane-step-tag">右区 · 绑定变量</span>
          <label className="gf-btn gf-btn--xs gf-btn--primary">
            + 上传外部文档 (PDF/XLSX/CSV/SCL)
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              accept=".pdf,.xlsx,.xlsm,.csv,.scl,.txt,.db"
              onChange={(event) => {
                onUploadFiles(event.target.files);
                if (fileRef.current) fileRef.current.value = "";
              }}
            />
          </label>
          <button
            type="button"
            className="gf-btn gf-btn--xs gf-btn--ghost"
            onClick={() => setShowPasteBox((v) => !v)}
          >
            {showPasteBox ? "收起粘贴" : "粘贴 SCL"}
          </button>
        </div>

        {showPasteBox && (
          <div className="gf-paste-box">
            <textarea
              className="gf-textarea gf-textarea--small"
              value={pastedScl}
              onChange={(e) => setPastedScl(e.target.value)}
              placeholder="直接粘贴 DATA_BLOCK ... 的 SCL 文本"
            />
            <button
              type="button"
              className="gf-btn gf-btn--xs gf-btn--primary"
              disabled={busy || !pastedScl.trim()}
              onClick={() => {
                onUploadPastedScl(pastedScl);
                setPastedScl("");
                setShowPasteBox(false);
              }}
            >
              解析粘贴 DB
            </button>
          </div>
        )}

        {state.receipt && (
          <div className="gf-receipt">
            <div className="gf-muted">
              解析回执 {state.receipt.receipt_id} · {state.receipt.status} · 接收{" "}
              {state.receipt.items_accepted}/{state.receipt.items_total}
              {state.receipt.user_confirmed ? " · 已锁定" : " · 待确认"}
            </div>
            {!state.receipt.user_confirmed && (
              <button
                type="button"
                className="gf-btn gf-btn--xs gf-btn--primary"
                disabled={state.receipt.status !== "parsed" || busy}
                onClick={onConfirmReceipt}
              >
                确认解析结果并锁定资料
              </button>
            )}
            {(state.receipt.errors ?? []).slice(0, 4).map((err, idx) => (
              <div className="gf-bad" key={`${err.code}-${idx}`}>
                <span className="gf-bad__code">{err.code}</span>
                <span>
                  {err.file}:{err.row} · {err.message}
                </span>
              </div>
            ))}
          </div>
        )}

        {state.has_contract ? (
          <div className="gf-lock">
            外部契约已冻结：IO 绝对地址与 DB720 / DB1900 标准偏移量严禁改动，程序仅通过 FC_IoMap / FC_Compat 边界访问
          </div>
        ) : (
          <div className="gf-muted">
            可上传外部 PDF/Excel IO 表与 DB 文档，或点击顶栏「载入参考实例」
          </div>
        )}
      </div>

      {/* 绑定目标选择器 + 搜索框 */}
      <div className="gf-var-toolbar">
        <div className="gf-var-target-row">
          <span className="gf-muted">绑定目标：</span>
          <select
            className="gf-var-select"
            value={effectiveTargetId}
            onChange={(e) => onSelectTarget(e.target.value)}
          >
            {bindTargets.length === 0 && <option value="">请先生成工艺逻辑</option>}
            {bindTargets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <input
          type="search"
          className="gf-var-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索变量名 / %I %Q 地址 / @Byte.Bit 偏移 / 注释…"
        />
      </div>

      {/* 四标签切换：外部 IO / 外部 DB / 内部生成 / 校验规则 */}
      <div className="gf-var-tabs">
        <button
          type="button"
          className={activeTab === "ext_io" ? "gf-var-tab gf-var-tab--active" : "gf-var-tab"}
          onClick={() => setActiveTab("ext_io")}
        >
          外部 IO ({catalog.counts?.external_io ?? catalog.external_io.length})
        </button>
        <button
          type="button"
          className={activeTab === "ext_db" ? "gf-var-tab gf-var-tab--active" : "gf-var-tab"}
          onClick={() => setActiveTab("ext_db")}
        >
          外部 DB ({catalog.counts?.external_db ?? catalog.external_db.length})
        </button>
        <button
          type="button"
          className={activeTab === "int_var" ? "gf-var-tab gf-var-tab--active" : "gf-var-tab"}
          onClick={() => setActiveTab("int_var")}
        >
          内部变量 ({catalog.counts?.internal_vars ?? catalog.internal_vars.length})
        </button>
        <button
          type="button"
          className={activeTab === "rules" ? "gf-var-tab gf-var-tab--active" : "gf-var-tab"}
          onClick={() => setActiveTab("rules")}
        >
          校验 {report?.ok ? "通过" : `(${violations.length})`}
        </button>
        <button
          type="button"
          className={activeTab === "nodes" ? "gf-var-tab gf-var-tab--active" : "gf-var-tab"}
          onClick={() => setActiveTab("nodes")}
          title="工站 / 执行单元 / 执行件的增删改、重命名、重挂与改标签"
        >
          结构节点
        </button>
      </div>

      {/* 标签内容列表 */}
      <div className="gf-var-list">
        {activeTab === "ext_io" && (
          <>
            {filteredIo.length === 0 ? (
              <div className="gf-muted gf-var-empty">
                暂无匹配的外部 IO 变量（上传 PLC_IO.pdf / CSV 或点击顶栏「载入参考实例」）
              </div>
            ) : (
              filteredIo.map((item) => {
                const bound = item.bound_targets ?? [];
                return (
                  <div className="gf-var-row" key={item.key}>
                    <div className="gf-var-row__main">
                      <span
                        className={`gf-addr-badge ${item.direction.startsWith("I") ? "gf-addr-badge--in" : "gf-addr-badge--out"}`}
                      >
                        {item.logical_address}
                      </span>
                      <strong className="gf-var-name">{item.name}</strong>
                      <span className="gf-type-badge">{item.data_type}</span>
                      <span className="gf-lock-mini" title="物理地址不可变"></span>
                    </div>
                    <div className="gf-var-row__sub">
                      <span className="gf-muted">{item.comment || item.hw_node_id}</span>
                      <div className="gf-var-row__actions">
                        {bound.map((targetId, idx) => (
                          <span
                            key={`${targetId}-${idx}`}
                            className="gf-bound-chip"
                            onClick={() => onUnbindVar(item.key, targetId)}
                            title="点击解除绑定"
                          >
                            → {targetId} ×
                          </span>
                        ))}
                        {effectiveTargetId && (
                          <button
                            type="button"
                            className="gf-btn gf-btn--xs gf-btn--ghost"
                            disabled={busy}
                            onClick={() =>
                              onBindVar(
                                item.key,
                                effectiveTargetId,
                                item.direction.startsWith("I") ? "condition" : "action",
                              )
                            }
                          >
                            + 绑定
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </>
        )}

        {activeTab === "ext_db" && (
          <>
            {dbGroups.length > 0 && (
              <div className="gf-db-filter">
                <button
                  type="button"
                  className={selectedDbName === "ALL" ? "gf-step-pill gf-step-pill--active" : "gf-step-pill"}
                  onClick={() => setSelectedDbName("ALL")}
                >
                  全部 DB ({dbGroups.length} 块)
                </button>
                {dbGroups.map((db) => (
                  <button
                    key={db.db_name}
                    type="button"
                    className={
                      selectedDbName === db.db_name
                        ? "gf-step-pill gf-step-pill--active"
                        : "gf-step-pill"
                    }
                    onClick={() => setSelectedDbName(db.db_name)}
                  >
                    {db.db_name} ({db.total_count})
                  </button>
                ))}
              </div>
            )}

            {filteredDbs.length === 0 ? (
              <div className="gf-muted gf-var-empty">
                暂无外部冻结 DB（上传 KUKA_DATA.pdf / PC_DATA.pdf / SCL 或点击顶栏「载入参考实例」）
              </div>
            ) : (
              filteredDbs.map((db) => (
                <div className="gf-db-group" key={db.db_name}>
                  <div className="gf-db-group__head">
                    <strong>{db.db_name}</strong>
                    <span className="gf-lock-mini">
                       Standard Access (S7_Optimized_Access := 'FALSE')
                    </span>
                  </div>
                  {db.members.slice(0, 120).map((m) => {
                    const bound = m.bound_targets ?? [];
                    return (
                      <div className="gf-var-row" key={m.key}>
                        <div className="gf-var-row__main">
                          <span className="gf-offset-badge">@{m.offset}B</span>
                          <strong className="gf-var-name">{m.name}</strong>
                          <span className="gf-type-badge">{m.data_type}</span>
                        </div>
                        <div className="gf-var-row__sub">
                          <span className="gf-muted">{m.comment || m.full_symbol}</span>
                          <div className="gf-var-row__actions">
                            {bound.map((targetId, idx) => (
                              <span
                                key={`${targetId}-${idx}`}
                                className="gf-bound-chip"
                                onClick={() => onUnbindVar(m.key, targetId)}
                                title="点击解除绑定"
                              >
                                → {targetId} ×
                              </span>
                            ))}
                            {effectiveTargetId && (
                              <button
                                type="button"
                                className="gf-btn gf-btn--xs gf-btn--ghost"
                                disabled={busy}
                                onClick={() => onBindVar(m.key, effectiveTargetId, "auto")}
                              >
                                + 绑定
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  {db.members.length > 120 && (
                    <div className="gf-muted gf-var-more">
                      已显示前 120 项（共 {db.members.length} 项，可通过上方搜索框精准过滤）
                    </div>
                  )}
                </div>
              ))
            )}
          </>
        )}

        {activeTab === "int_var" && (
          <>
            {filteredInternal.length === 0 ? (
              <div className="gf-muted gf-var-empty">
                请先在对话中生成工艺结构图，系统将自动生成控制节点与执行件 PLCOpen 五信号内部变量
              </div>
            ) : (
              filteredInternal.map((v) => (
                <div className="gf-var-row" key={v.key}>
                  <div className="gf-var-row__main">
                    <span className="gf-internal-badge">{v.group}</span>
                    <strong className="gf-var-name">{v.name}</strong>
                    <span className="gf-type-badge">{v.data_type}</span>
                  </div>
                  <div className="gf-var-row__sub">
                    <span className="gf-muted">{v.role} · {v.owner_id}</span>
                    <div className="gf-var-row__actions">
                      {effectiveTargetId && (
                        <button
                          type="button"
                          className="gf-btn gf-btn--xs gf-btn--ghost"
                          disabled={busy}
                          onClick={() =>
                            onBindVar(
                              v.key,
                              effectiveTargetId,
                              v.role === "STATUS" ? "condition" : "action",
                            )
                          }
                        >
                          + 绑定
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </>
        )}

        {activeTab === "rules" && (
          <div className="gf-rules-pane">
            <div className="gf-side-section">
              <div className="gf-side-title">结构校验</div>
              <button type="button" className="gf-btn gf-btn--ghost" onClick={onValidate}>
                重新校验
              </button>
              {!report && <div className="gf-muted">尚未生成规格</div>}
              {report?.ok && <div className="gf-ok">全部通过，可以继续「确认设备逻辑并锁定还原契约」</div>}
              {violations.map((item, index) => (
                <div className="gf-bad" key={`${item.code}-${index}`}>
                  <span className="gf-bad__code">{item.code}</span>
                  <span>{item.message}</span>
                  <span className="gf-muted">
                    定位：{item.view || "结构"} / {item.node_id || item.edge_id || "—"}
                  </span>
                </div>
              ))}
            </div>

            <div className="gf-side-section">
              <div className="gf-side-title">允许的连线白名单</div>
              <div className="gf-chips">
                {(whitelist?.edge_kinds ?? []).map((item) => (
                  <span className="gf-chip" key={item}>{item}</span>
                ))}
              </div>
            </div>

            <div className="gf-side-section">
              <div className="gf-side-title">规格附加字段 (IR-Only)</div>
              {(state.ir_only_fields ?? []).slice(0, 12).map((item, index) => (
                <div className="gf-muted" key={index}>
                  {String(item.path ?? item.field ?? item.label ?? JSON.stringify(item))}
                </div>
              ))}
            </div>

            <div className="gf-side-section">
              <div className="gf-side-title">工程日志与待确认项</div>
              {questions.length === 0 ? (
                <div className="gf-muted">无</div>
              ) : (
                questions.slice(0, 10).map((question, index) => (
                  <div className="gf-muted" key={index}>· {question}</div>
                ))
              )}
            </div>
          </div>
        )}

        {activeTab === "nodes" && (
          <div className="gf-node-editor-wrap" data-ui="greenfield-link-node-editor">
            <div className="gf-node-editor__hint">
              工站 / 执行单元 / 执行件的增删改、重命名、重挂与改标签；变更走
              <code> POST /patch </code> 原子 op，提交后四视图同步刷新。
            </div>
            <NodeEditor
              ir={state.ir}
              busy={busy}
              onPatch={onPatchNodes ?? (() => undefined)}
            />
            {actionFeedback && (
              <div className="gf-action-feedback" role="status">{actionFeedback}</div>
            )}
          </div>
        )}
      </div>
        </aside>
      </div>
    </details>
  );
};
