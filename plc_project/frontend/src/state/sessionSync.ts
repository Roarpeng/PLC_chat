/**
 * 会话历史服务端同步 —— 历史跟服务走,不跟浏览器走(2026-10-24 升级)。
 *
 * 策略:
 * - localStorage 仍是第一层(离线可用、零延迟读);
 * - 启动时 bootstrapRemoteMerge:拉服务端 meta 列表做并集(新者胜),
 *   服务端独有/更新的会话以「占位会话」进入列表,点击时再拉全量(懒加载,
 *   避免启动即下载 30×2MB 画布);
 * - 本地每次变更 persistAndSync:写 localStorage + 按会话防抖 1.5s 推服务端;
 *   本地删除 → 显式删除服务端;
 * - 所有网络失败静默降级为纯本地模式,不打扰用户。
 */
import type { CanvasStateData } from "../canvas/types";
import { requestPlc } from "../lib/plcGateway";
import type { ChatSession } from "./sessions";
import { persistSessions } from "./sessions";
import { blankCanvas } from "./tiaXmlImport";

/** 会话 meta(服务端列表项,无画布) */
export interface SessionMeta {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  msgCount: number;
}

/** 占位会话标记:正文还在服务端,点选时拉全量 */
declare module "./sessions" {
  interface ChatSession {
    pendingRemote?: boolean;
  }
}

export async function fetchRemoteSessions(): Promise<SessionMeta[]> {
  return requestPlc<SessionMeta[]>("/api/v1/plc/canvas/sessions");
}

/** 服务端删除墓碑 {id: deletedAt}——命中即本地丢弃且永不再上传 */
export async function fetchRemoteDeleted(): Promise<Record<string, number>> {
  try {
    const d = await requestPlc<{ deleted: Record<string, number> }>(
      "/api/v1/plc/canvas/sessions/deleted",
    );
    return d?.deleted || {};
  } catch {
    return {};
  }
}

export async function fetchRemoteSession(id: string): Promise<ChatSession | null> {
  try {
    return await requestPlc<ChatSession>(`/api/v1/plc/canvas/sessions/${encodeURIComponent(id)}`);
  } catch {
    return null;
  }
}

async function putRemoteSession(session: ChatSession): Promise<boolean> {
  try {
    await requestPlc(`/api/v1/plc/canvas/sessions/${encodeURIComponent(session.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...session, pendingRemote: undefined }),
    });
    return true;
  } catch {
    return false;
  }
}

/* ---------------- 按会话防抖推送 ---------------- */

const PUSH_DELAY_MS = 1500;
const pushTimers = new Map<string, number>();
/** 已知墓碑(bootstrap 时刷新):这些 id 刻意不推送,防删除复活 */
const knownTombstones = new Set<string>();

export function scheduleSessionPush(session: ChatSession): void {
  if (knownTombstones.has(session.id)) return;
  const sid = session.id;
  const prev = pushTimers.get(sid);
  if (prev) window.clearTimeout(prev);
  const t = window.setTimeout(() => {
    pushTimers.delete(sid);
    void putRemoteSession(session);
  }, PUSH_DELAY_MS);
  pushTimers.set(sid, t);
}

/** 删除服务端会话。返回是否成功——失败必须让 UI 报错,不能静默(否则刷新即复活)。 */
export async function syncSessionDelete(id: string): Promise<boolean> {
  const prev = pushTimers.get(id);
  if (prev) window.clearTimeout(prev);
  pushTimers.delete(id);
  try {
    await requestPlc(`/api/v1/plc/canvas/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    knownTombstones.add(id);
    return true;
  } catch {
    return false;
  }
}

/* ---------------- 写 localStorage + 差量推送 ---------------- */

const lastSyncedAt = new Map<string, number>();

export function persistAndSync(list: ChatSession[]): void {
  persistSessions(list);
  for (const s of list) {
    if (s.pendingRemote) continue; // 占位会话正文在服务端,不回推
    if (knownTombstones.has(s.id)) continue; // 已删除:绝不复活
    if (lastSyncedAt.get(s.id) === s.updatedAt) continue;
    lastSyncedAt.set(s.id, s.updatedAt);
    scheduleSessionPush(s);
  }
}

/* ---------------- 启动合并 ---------------- */

/**
 * 服务端 meta 与本地会话并集(每 id 取 updatedAt 新者)。返回合并后的完整
 * 列表;本地独有/更新的会话同时排程上传(老历史迁移上服务端)。
 * 网关不可达时原样返回本地列表。
 */
export async function bootstrapRemoteMerge(local: ChatSession[]): Promise<ChatSession[]> {
  let metas: SessionMeta[];
  try {
    metas = await fetchRemoteSessions();
  } catch {
    return local;
  }
  const deleted = await fetchRemoteDeleted();
  knownTombstones.clear();
  for (const id of Object.keys(deleted)) knownTombstones.add(id);
  // 墓碑命中:本地丢弃且不上传(即使本地看起来"更新"——防止陈旧副本复活)
  const alive = local.filter((s) => !knownTombstones.has(s.id));
  const byId = new Map(alive.map((s) => [s.id, s]));
  const merged = [...alive];
  const remoteIds = new Set<string>();
  for (const meta of metas) {
    if (!meta?.id) continue;
    remoteIds.add(meta.id);
    if (knownTombstones.has(meta.id)) continue; // 竞态:删除与列表并发
    const cur = byId.get(meta.id);
    const remoteNewer = !cur || (meta.updatedAt ?? 0) > (cur.updatedAt ?? 0);
    if (!remoteNewer) continue;
    // 占位会话:标题/时间来自服务端,正文点击时拉
    const placeholder: ChatSession = {
      id: meta.id,
      title: meta.title || "远程会话",
      createdAt: meta.createdAt ?? meta.updatedAt ?? 0,
      updatedAt: meta.updatedAt ?? 0,
      messages: [],
      canvas: blankCanvas("") as CanvasStateData,
      pendingRemote: true,
    };
    const idx = merged.findIndex((s) => s.id === meta.id);
    if (idx >= 0) merged[idx] = placeholder;
    else merged.push(placeholder);
  }
  // 本地独有或本地更新 → 迁移上服务端(墓碑中的绝不推)
  for (const s of alive) {
    if (remoteIds.has(s.id)) {
      const meta = metas.find((m) => m.id === s.id)!;
      if ((s.updatedAt ?? 0) > (meta.updatedAt ?? 0)) scheduleSessionPush(s);
    } else {
      scheduleSessionPush(s);
    }
  }
  merged.sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
  return merged;
}

/** 点选占位会话时拉全量;失败返回 null(继续用占位,提示用户) */
export async function hydrateRemoteSession(session: ChatSession): Promise<ChatSession | null> {
  const full = await fetchRemoteSession(session.id);
  if (!full || !Array.isArray(full.messages)) return null;
  lastSyncedAt.set(full.id, full.updatedAt ?? 0);
  return full;
}
