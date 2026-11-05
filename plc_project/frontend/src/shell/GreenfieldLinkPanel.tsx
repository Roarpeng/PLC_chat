/** 右栏：连线白名单、实时校验、只读契约与只存在于规格中的字段（T04）。 */
import React from "react";
import type { GFReport, GFState, GFWhitelist } from "../state/greenfield";

export interface GreenfieldLinkPanelProps {
  whitelist: GFWhitelist | null;
  report: GFReport | null;
  state: GFState;
  onValidate: () => void;
}

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="gf-side-section">
    <div className="gf-side-title">{title}</div>
    {children}
  </div>
);

export const GreenfieldLinkPanel: React.FC<GreenfieldLinkPanelProps> = ({
  whitelist,
  report,
  state,
  onValidate,
}) => {
  const violations = report?.violations ?? [];
  const questions = [...(report?.open_questions ?? []), ...(state.notes ?? [])];

  return (
    <aside className="gf-side" data-ui="greenfield-link-panel">
      <Section title="结构校验">
        <button type="button" className="gf-btn gf-btn--ghost" onClick={onValidate}>
          重新校验
        </button>
        {!report && <div className="gf-muted">尚未生成规格</div>}
        {report?.ok && <div className="gf-ok">全部通过，可以继续确认</div>}
        {violations.map((item, index) => (
          <div className="gf-bad" key={`${item.code}-${index}`}>
            <span className="gf-bad__code">{item.code}</span>
            <span>{item.message}</span>
            <span className="gf-muted">定位：{item.view || "结构"} / {item.node_id || item.edge_id || "—"}</span>
          </div>
        ))}
      </Section>

      <Section title="允许的连线">
        <div className="gf-chips">
          {(whitelist?.edge_kinds ?? []).map((item) => (
            <span className="gf-chip" key={item}>{item}</span>
          ))}
        </div>
      </Section>

      <Section title="会被拦截的连线">
        {(whitelist?.illegal_edges ?? []).slice(0, 10).map((item) => (
          <div className="gf-muted" key={item.code}>
            {item.code} · {item.reason}
          </div>
        ))}
      </Section>

      <Section title="只在规格中、图上不表达的字段">
        {(state.ir_only_fields ?? []).slice(0, 12).map((item, index) => (
          <div className="gf-muted" key={index}>
            {String(item.path ?? item.field ?? item.label ?? JSON.stringify(item))}
          </div>
        ))}
        {(!state.ir_only_fields || state.ir_only_fields.length === 0) && (
          <div className="gf-muted">无</div>
        )}
      </Section>

      <Section title="只读兼容资料">
        {state.has_contract ? (
          <div className="gf-lock">已锁定：结构与绝对地址不可改动</div>
        ) : (
          <div className="gf-muted">尚未上传兼容资料</div>
        )}
        {state.receipt && (
          <div className="gf-muted">
            解析回执 {state.receipt.receipt_id} · {state.receipt.status} ·
            接收 {state.receipt.items_accepted}/{state.receipt.items_total}
            {state.receipt.user_confirmed ? " · 已确认" : " · 待确认"}
          </div>
        )}
        {(state.receipt?.errors ?? []).slice(0, 8).map((error, index) => (
          <div className="gf-bad" key={`${error.code}-${index}`}>
            <span className="gf-bad__code">{error.code}</span>
            <span>{error.file}:{error.row} {error.column} · {error.message}</span>
          </div>
        ))}
      </Section>

      <Section title="待确认问题">
        {questions.length === 0 ? (
          <div className="gf-muted">无</div>
        ) : (
          questions.slice(0, 10).map((question, index) => (
            <div className="gf-muted" key={index}>· {question}</div>
          ))
        )}
      </Section>
    </aside>
  );
};
