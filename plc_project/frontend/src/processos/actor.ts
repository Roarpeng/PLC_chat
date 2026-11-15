import { useEffect, useState } from "react";
import { ApiError } from "./api";

/* PLAN §7 — seven roles. This is a DEMO identity pass-through (X-Actor-* headers),
   not production authentication; the UI states this next to the selector. */
export const ACTOR_ROLES = [
  "Viewer", "FieldEngineer", "Reviewer", "Builder",
  "ReleaseApprover", "CommissioningEngineer", "Admin",
] as const;
export type ActorRoleName = (typeof ACTOR_ROLES)[number];

export const ROLE_LABELS: Record<ActorRoleName, string> = {
  Viewer: "查看",
  FieldEngineer: "现场工程师",
  Reviewer: "复核",
  Builder: "构建",
  ReleaseApprover: "发布审批",
  CommissioningEngineer: "调试工程师",
  Admin: "管理",
};

export interface ActorIdentity { id: string; role: ActorRoleName }

export const DEFAULT_ACTOR: ActorIdentity = { id: "demo_operator", role: "Viewer" };
const KEY = "processos.actor.v1";
const EVT = "processos:actor-changed";

/* localStorage may be absent (node tests) — fall back to module memory. */
const mem: { actor?: string } = {};
function ls(): Pick<Storage, "getItem" | "setItem"> | null {
  try { if (typeof localStorage !== "undefined") return localStorage; } catch { /* */ }
  return null;
}

export function loadActor(): ActorIdentity {
  try {
    const raw = ls()?.getItem(KEY) ?? mem.actor;
    if (raw) {
      const v = JSON.parse(raw) as Partial<ActorIdentity>;
      if (v && (ACTOR_ROLES as readonly string[]).includes(String(v.role)))
        return { id: String(v.id || DEFAULT_ACTOR.id), role: v.role as ActorRoleName };
    }
  } catch { /* corrupted entry -> default */ }
  return { ...DEFAULT_ACTOR };
}

export function saveActor(a: ActorIdentity): void {
  const raw = JSON.stringify(a);
  try { ls()?.setItem(KEY, raw); } catch { /* */ }
  mem.actor = raw;
  try { if (typeof window !== "undefined") window.dispatchEvent(new Event(EVT)); } catch { /* */ }
}

/** Demo identity headers attached to every /api/processos call. */
export function actorHeaders(): Record<string, string> {
  const a = loadActor();
  return { "X-Actor-Id": a.id, "X-Actor-Role": a.role };
}

export function useActor() {
  const [actor, setActor] = useState<ActorIdentity>(loadActor);
  useEffect(() => {
    const on = () => setActor(loadActor());
    try { window.addEventListener(EVT, on); } catch { /* */ }
    return () => { try { window.removeEventListener(EVT, on); } catch { /* */ } };
  }, []);
  const update = (a: ActorIdentity) => { saveActor(a); setActor(a); };
  return { actor, update };
}

/** Uniform 403 ROLE_FORBIDDEN copy: tells the user which role the call needs. */
export function roleDeniedText(e: unknown): string | null {
  if (e instanceof ApiError && (e.code === "ROLE_FORBIDDEN" || e.status === 403)) {
    const need = e.requiredRole || "更高权限角色";
    return `权限不足（ROLE_FORBIDDEN）：该操作需要 ${need}，当前身份为 ${loadActor().role}。演示环境可在右上角切换身份。`;
  }
  return null;
}
