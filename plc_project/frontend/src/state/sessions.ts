import type { CanvasStateData } from "../canvas/types";

/** 单条聊天消息 */
export interface ChatMessage {
  id: string;
  role: "user" | "system";
  text: string;
  ts: number;
}

/** 一个会话 = 消息流 + 画布快照 */
export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
  /** 画布快照 */
  canvas: CanvasStateData;
}

const STORAGE_KEY = "plc-copilot.sessions.v1";
const DAY_MS = 24 * 60 * 60 * 1000;
const ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";

function randomSuffix(length: number): string {
  let out = "";
  for (let i = 0; i < length; i++) {
    out += ID_ALPHABET[Math.floor(Math.random() * ID_ALPHABET.length)];
  }
  return out;
}

/** "s-" + 时间戳36进制 + 随机4字符 */
export function newSessionId(): string {
  return "s-" + Date.now().toString(36) + randomSuffix(4);
}

function newMessageId(): string {
  return "m-" + Date.now().toString(36) + randomSuffix(4);
}

/** 读取 localStorage 中的会话列表；不存在 / JSON 损坏返回 []，结果按 updatedAt 降序 */
export function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const list: ChatSession[] = parsed.filter(
      (item): item is ChatSession =>
        !!item &&
        typeof item === "object" &&
        typeof item.id === "string" &&
        Array.isArray(item.messages),
    );
    list.sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
    return list;
  } catch {
    return [];
  }
}

/** 写回 localStorage，异常静默（隐私模式 / 配额满） */
export function persistSessions(list: ChatSession[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* 静默 */
  }
}

/** 由画布快照创建新会话；title 取 firstMessage 去空格后截断 16 字符（超出加 …），无则 "新对话" */
export function makeSession(canvas: CanvasStateData, firstMessage?: string): ChatSession {
  const now = Date.now();
  const cleaned = (firstMessage ?? "").replace(/\s+/g, "");
  const title =
    cleaned.length > 16 ? cleaned.slice(0, 16) + "…" : cleaned.length > 0 ? cleaned : "新对话";
  const messages: ChatMessage[] = [];
  if (firstMessage && firstMessage.trim().length > 0) {
    messages.push({ id: newMessageId(), role: "user", text: firstMessage, ts: now });
  }
  return { id: newSessionId(), title, createdAt: now, updatedAt: now, messages, canvas };
}

function startOfDay(ts: number): number {
  const d = new Date(ts);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** 按天分组：今天 / 昨天 / 7 天内 / 更早。输入应已按 updatedAt 降序；空分组不输出 */
export function groupSessions(
  list: ChatSession[],
): Array<{ label: string; items: ChatSession[] }> {
  const now = Date.now();
  const todayStart = startOfDay(now);
  const yesterdayStart = startOfDay(now - DAY_MS);
  const weekStart = startOfDay(now - 7 * DAY_MS);
  const buckets: Array<{ label: string; items: ChatSession[] }> = [
    { label: "今天", items: [] },
    { label: "昨天", items: [] },
    { label: "7 天内", items: [] },
    { label: "更早", items: [] },
  ];
  for (const session of list) {
    const ts = typeof session.updatedAt === "number" ? session.updatedAt : 0;
    if (ts >= todayStart) buckets[0].items.push(session);
    else if (ts >= yesterdayStart) buckets[1].items.push(session);
    else if (ts >= weekStart) buckets[2].items.push(session);
    else buckets[3].items.push(session);
  }
  return buckets.filter((bucket) => bucket.items.length > 0);
}

function pad2(n: number): string {
  return n < 10 ? "0" + n : String(n);
}

/** 刚刚(<60s) / N 分钟前(<60m) / HH:MM(今天) / 昨天 HH:MM / M月d日(今年) / YYYY年M月d日 */
export function relativeTime(ts: number): string {
  const now = Date.now();
  const diff = now - ts;
  if (diff < 60 * 1000) return "刚刚";
  if (diff < 60 * 60 * 1000) return Math.floor(diff / (60 * 1000)) + " 分钟前";
  const d = new Date(ts);
  const hm = pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  if (ts >= startOfDay(now)) return hm;
  if (ts >= startOfDay(now - DAY_MS)) return "昨天 " + hm;
  const n = new Date(now);
  if (d.getFullYear() === n.getFullYear()) return d.getMonth() + 1 + "月" + d.getDate() + "日";
  return d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日";
}
