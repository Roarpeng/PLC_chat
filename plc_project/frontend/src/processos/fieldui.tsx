import { useCallback, useEffect, useRef, useState } from "react";
import { ACTOR_ROLES, ROLE_LABELS, useActor, type ActorRoleName } from "./actor";
import { Icon } from "./views";

/* Field workbench views reachable from the field nav (naming follows the
   launcher/wizard/import views in store.ts). machine/station are the PLAN §3.1
   canvases: 整机画布 is a nav entry; 工位画布 is its drill-down (breadcrumb
   back, no nav highlight). */
export type FieldView = "field" | "machine" | "station" | "trace" | "commissioning" | "baselines" | "gateway";
export const FIELD_NAV: [FieldView, string][] = [
  ["field", "现场入口"],
  ["machine", "整机画布"],
  ["trace", "现场追溯"],
  ["commissioning", "调试台账"],
  ["baselines", "基线比对"],
  ["gateway", "部署网关"],
];

export function FieldTop({ view, onNav, onBack, title, hint }: {
  view: FieldView; onNav: (v: FieldView) => void; onBack: () => void; title: string; hint?: string;
}) {
  return (
    <div className="flow-top">
      <button className="back" onClick={onBack}><Icon name="back" /> 项目图纸夹</button>
      <h2>{title}</h2>
      <nav className="seg fieldnav" aria-label="现场工作台导航">
        {FIELD_NAV.map(([v, label]) => (
          <button key={v} className={view === v ? "on" : ""} onClick={() => onNav(v)}>{label}</button>
        ))}
      </nav>
      <div className="sp" />
      <ActorRoleWidget />
      {hint && <span className="hint fieldhint">{hint}</span>}
    </div>
  );
}

/** Top-bar role selector — demo identity pass-through, not production auth. */
export function ActorRoleWidget() {
  const { actor, update } = useActor();
  return (
    <label className="actorwidget" title="演示用身份传递，非生产认证">
      <span className="aw-k">身份</span>
      <input className="aw-id mono" value={actor.id} aria-label="操作者 ID"
        onChange={e => update({ ...actor, id: e.target.value })} />
      <select className="aw-role" value={actor.role} aria-label="角色"
        onChange={e => update({ ...actor, role: e.target.value as ActorRoleName })}>
        {ACTOR_ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
      </select>
      <span className="aw-note">演示用身份传递 · 非生产认证</span>
    </label>
  );
}

/* Semantic badges: ok / warn / err / info / ink / unknown (UNKNOWN fields) / sim (SIMULATED). */
export function Badge({ tone = "", children, title }: { tone?: "ok" | "warn" | "err" | "info" | "ink" | "unknown" | "sim" | ""; children: React.ReactNode; title?: string }) {
  return <span className={`badge${tone ? ` ${tone}` : ""}`} title={title}>{children}</span>;
}

export function Banner({ tone = "warn", children }: { tone?: "warn" | "err" | "info"; children: React.ReactNode }) {
  return <div className={`fc-banner ${tone}`} role="note">{children}</div>;
}

/* Toast, same pattern as Workspace. */
export function useFlash() {
  const [toast, setToast] = useState<{ msg: string; err?: boolean } | null>(null);
  const timer = useRef<number>(0);
  const flash = useCallback((msg: string, err?: boolean) => {
    setToast({ msg, err });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const el = <div className={`toast ${toast ? "show" : ""} ${toast?.err ? "err" : ""}`}>{toast?.msg}</div>;
  return { flash, toastEl: el };
}

export function verdictTone(v: string): "ok" | "err" | "warn" {
  if (v === "OK_TO_PROCEED" || v === "VERIFIED" || v === "COMMISSIONED") return "ok";
  if (v === "FROZEN_DRIFT" || v === "FAILED" || v === "FROZEN") return "err";
  return "warn"; // UNVERIFIED_ONLINE / ROLLED_BACK / unknown
}

export function riskTone(v: string): "ok" | "warn" | "err" | "unknown" {
  if (v === "NONE" || v === "LOW") return "ok";
  if (v === "MEDIUM") return "warn";
  if (v === "HIGH" || v === "RETAIN_DATA_RISK") return "err";
  return "unknown";
}

export function evidenceTone(v: string): "ok" | "info" | "sim" | "unknown" {
  if (v === "OT_READ") return "ok";
  if (v === "MANUAL" || v === "MANUAL_UPLOAD") return "info";
  if (v === "SIMULATED") return "sim";
  return "unknown";
}
