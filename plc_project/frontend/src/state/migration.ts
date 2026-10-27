/**
 * 旧 sessions(localStorage)→ 新 Project/Conversation 本地迁移(契约 docs/25 §1 · P 线)。
 *
 * 一次性启动迁移:
 * - 读旧 localStorage ``plc-copilot.sessions.v1`` → 按 project_name
 *   (canvas.project_name → 标题「·」后段 → 标题)分组 → 每组建一个 Project
 *   (画布取自该组首个会话)+ N 个 Conversation(消息流);
 * - 逐个 putProject / putConversation 上传网关;任一失败即视为网关不可达,
 *   退化为纯本地迁移(新 key 照写、不上传;服务端副本可由
 *   POST /canvas/projects/migrate 从服务端旧 sessions 补齐);
 * - 写新 key ``plc-copilot.projects.v1`` + 标记 ``plc-copilot.migrated.v1="done"``;
 * - 旧 key 不删(只标记),迁移失败/回滚时数据仍在。
 */
import { loadSessions } from "./sessions";
import {
  newConversationId,
  newProjectId,
  putConversation,
  putProject,
} from "./projects";
import type { Conversation, Project } from "./projects";
import { blankCanvas } from "./tiaXmlImport";
import type { CanvasStateData } from "../canvas/types";
import type { ChatSession } from "./sessions";

export const OLD_SESSIONS_KEY = "plc-copilot.sessions.v1";
export const PROJECTS_KEY = "plc-copilot.projects.v1";
export const MIGRATED_KEY = "plc-copilot.migrated.v1";
const UNNAMED = "未命名工程";

/** 新 key 中的一条:工程 + 其对话(S 线侧栏可直接消费) */
export interface ProjectRecord {
  project: Project;
  conversations: Conversation[];
}

export interface MigrationStats {
  projects_migrated: number;
  conversations_migrated: number;
  /** false = 网关不可达,纯本地迁移(未上传) */
  uploaded: boolean;
  /** true = 之前已迁移过,本次直接跳过 */
  skipped: boolean;
}

/** 是否已完成迁移(标记存在且为 "done") */
export function isMigrated(): boolean {
  try {
    return localStorage.getItem(MIGRATED_KEY) === "done";
  } catch {
    return false;
  }
}

/** 工程名提取优先级,与后端 project_store._project_name_from_session 保持一致 */
export function projectNameFromSession(session: ChatSession): string {
  const canvasName = (session.canvas as { project_name?: unknown } | undefined)?.project_name;
  if (typeof canvasName === "string" && canvasName.trim()) return canvasName.trim();
  const title = typeof session.title === "string" ? session.title : "";
  if (title.includes("·")) {
    const part = (title.split("·").pop() ?? "").trim();
    if (part) return part;
  }
  return title.trim() || UNNAMED;
}

/** 读新 key;不存在 / JSON 损坏 → [] */
export function loadProjectRecords(): ProjectRecord[] {
  try {
    const raw = localStorage.getItem(PROJECTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ProjectRecord[]) : [];
  } catch {
    return [];
  }
}

function persistProjectRecords(records: ProjectRecord[]): void {
  try {
    localStorage.setItem(PROJECTS_KEY, JSON.stringify(records));
  } catch {
    /* 静默:隐私模式 / 配额满 */
  }
}

function markMigrated(): void {
  try {
    localStorage.setItem(MIGRATED_KEY, "done");
  } catch {
    /* 静默 */
  }
}

function isCanvas(v: unknown): v is CanvasStateData {
  return !!v && typeof v === "object";
}

/**
 * 执行迁移(幂等:已迁移直接返回 skipped)。流程见文件头;
 * 网关不可达时纯本地迁移,绝不抛错。
 */
export async function migrateLocalSessions(): Promise<MigrationStats> {
  if (isMigrated()) {
    return { projects_migrated: 0, conversations_migrated: 0, uploaded: false, skipped: true };
  }
  const now = Date.now();
  const byName = new Map<string, ProjectRecord>();
  for (const session of loadSessions()) {
    const name = projectNameFromSession(session);
    let record = byName.get(name);
    if (!record) {
      record = {
        project: {
          id: newProjectId(),
          name,
          createdAt: session.createdAt ?? now,
          updatedAt: session.updatedAt ?? now,
          canvas: isCanvas(session.canvas) ? session.canvas : blankCanvas(name),
        },
        conversations: [],
      };
      byName.set(name, record);
    }
    // 组内最新会话时间代表工程 updated_at
    record.project.updatedAt = Math.max(record.project.updatedAt ?? 0, session.updatedAt ?? 0);
    record.conversations.push({
      id: newConversationId(),
      projectId: record.project.id,
      title: session.title || "新对话",
      createdAt: session.createdAt ?? now,
      updatedAt: session.updatedAt ?? now,
      messages: Array.isArray(session.messages) ? session.messages : [],
    });
  }
  const records = [...byName.values()];

  // 上传:任一失败即判定网关不可达,停止后续上传(避免无谓重试风暴)
  let uploaded = true;
  for (const record of records) {
    if (!(await putProject(record.project))) {
      uploaded = false;
      break;
    }
    for (const conversation of record.conversations) {
      if (!(await putConversation(conversation))) {
        uploaded = false;
        break;
      }
    }
    if (!uploaded) break;
  }

  // 无论是否上传成功,本地新结构都落盘并打标记(旧 key 不删,数据仍可回溯)
  persistProjectRecords(records);
  markMigrated();
  return {
    projects_migrated: records.length,
    conversations_migrated: records.reduce((n, r) => n + r.conversations.length, 0),
    uploaded,
    skipped: false,
  };
}
