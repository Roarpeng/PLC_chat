/**
 * Project / Conversation 两层模型 —— 前端 API 层(契约 docs/25 §1 · P 线)。
 *
 * Project = 工程容器(唯一权威画布);Conversation = 纯消息流(不存画布)。
 * 服务端 wire 格式为 snake_case(id/name/updated_at/conversation_count/
 * project_id/...),本层做 snake↔camel 映射,对前端暴露 camelCase(对齐
 * sessions.ts 的既有约定;S 线 ProjectSidebar 依赖 ProjectMeta /
 * ConversationMeta 两个类型名与字段 shape,不可破坏)。
 *
 * mock-first:全部走 requestPlc;404 / 网络错 → 空数组 / null / false,
 * 不抛错——网关缺席不阻塞 UI,调用方可先用本地状态开发。
 */
import type { CanvasStateData } from "../canvas/types";
import { requestPlc } from "../lib/plcGateway";
import type { ChatMessage } from "./sessions";

/** 工程 meta(列表口径,不含画布) */
export interface ProjectMeta {
  /** "prj-<hex12>" */
  id: string;
  name: string;
  createdAt?: number;
  updatedAt: number;
  /** 该工程下对话数(服务端 meta.conversation_count) */
  conversationCount?: number;
}

/** 完整工程(含唯一权威画布) */
export interface Project extends ProjectMeta {
  canvas: CanvasStateData;
}

/** 对话 meta(列表口径,不含消息) */
export interface ConversationMeta {
  /** "cv-<hex12>" */
  id: string;
  /** 所属工程(FK → Project) */
  projectId: string;
  title: string;
  createdAt?: number;
  updatedAt: number;
}

/** 完整对话(含 messages,永不携带画布——画布属于工程) */
export interface Conversation extends ConversationMeta {
  messages: ChatMessage[];
}

/* ---------------- snake_case wire ↔ camelCase 类型 ---------------- */

type Wire = Record<string, unknown>;

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function toProjectMeta(raw: Wire): ProjectMeta {
  return {
    id: str(raw.id),
    name: str(raw.name ?? raw.project_name),
    createdAt: num(raw.created_at ?? raw.createdAt),
    updatedAt: num(raw.updated_at ?? raw.updatedAt),
    conversationCount: num(raw.conversation_count ?? raw.conversationCount),
  };
}

function toProject(raw: Wire): Project | null {
  if (!str(raw.id)) return null;
  return {
    ...toProjectMeta(raw),
    canvas: (raw.canvas ?? {}) as CanvasStateData,
  };
}

function toConversationMeta(raw: Wire): ConversationMeta {
  return {
    id: str(raw.id),
    projectId: str(raw.project_id ?? raw.projectId),
    title: str(raw.title),
    createdAt: num(raw.created_at ?? raw.createdAt),
    updatedAt: num(raw.updated_at ?? raw.updatedAt),
  };
}

function toConversation(raw: Wire): Conversation | null {
  if (!str(raw.id)) return null;
  return {
    ...toConversationMeta(raw),
    messages: Array.isArray(raw.messages) ? (raw.messages as ChatMessage[]) : [],
  };
}

/** Project → wire body(PUT /canvas/projects/{id}) */
function projectToWire(p: Project): Wire {
  return {
    id: p.id,
    project_name: p.name,
    canvas: p.canvas,
    created_at: p.createdAt ?? p.updatedAt,
    updated_at: p.updatedAt,
  };
}

/** Conversation → wire body(PUT /canvas/conversations/{id}) */
function conversationToWire(c: Conversation): Wire {
  return {
    id: c.id,
    project_id: c.projectId,
    title: c.title,
    messages: c.messages,
    created_at: c.createdAt ?? c.updatedAt,
    updated_at: c.updatedAt,
  };
}

/* ---------------- id 生成 ---------------- */

const ID_ALPHABET = "0123456789abcdef";

function hex12(): string {
  let out = "";
  for (let i = 0; i < 12; i++) out += ID_ALPHABET[Math.floor(Math.random() * 16)];
  return out;
}

/** "prj-" + 12 位 hex(本地建工程时生成;服务端 POST 也会自己生成) */
export function newProjectId(): string {
  return "prj-" + hex12();
}

/** "cv-" + 12 位 hex */
export function newConversationId(): string {
  return "cv-" + hex12();
}

/* ---------------- Project ---------------- */

/** 工程列表 meta;网关不可达 / 404 → [](不抛错) */
export async function fetchProjects(): Promise<ProjectMeta[]> {
  try {
    const data = await requestPlc<Wire[]>("/api/v1/plc/canvas/projects");
    return Array.isArray(data) ? data.map(toProjectMeta) : [];
  } catch {
    return [];
  }
}

/** 单工程完整对象(含画布);不存在 / 网络错 → null */
export async function fetchProject(id: string): Promise<Project | null> {
  try {
    return toProject((await requestPlc<Wire>(
      `/api/v1/plc/canvas/projects/${encodeURIComponent(id)}`,
    )) as Wire);
  } catch {
    return null;
  }
}

/** 整工程 upsert(画布唯一权威写入口);失败 → null */
export async function putProject(project: Project): Promise<ProjectMeta | null> {
  try {
    const meta = await requestPlc<Wire>(
      `/api/v1/plc/canvas/projects/${encodeURIComponent(project.id)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectToWire(project)),
      },
    );
    return toProjectMeta((meta ?? {}) as Wire);
  } catch {
    return null;
  }
}

/** 删除工程(服务端级联删其全部对话);失败 → false */
export async function deleteProject(id: string): Promise<boolean> {
  try {
    await requestPlc(`/api/v1/plc/canvas/projects/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return true;
  } catch {
    return false;
  }
}

/** 新建工程;未传 canvas 则服务端建空白画布。失败 → null */
export async function createProject(
  name: string,
  canvas?: CanvasStateData,
): Promise<Project | null> {
  try {
    return toProject((await requestPlc<Wire>("/api/v1/plc/canvas/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_name: name, ...(canvas ? { canvas } : {}) }),
    })) as Wire);
  } catch {
    return null;
  }
}

/* ---------------- Conversation ---------------- */

/** 某工程下对话 meta 列表;网关不可达 / 404 → [] */
export async function fetchConversations(projectId: string): Promise<ConversationMeta[]> {
  try {
    const data = await requestPlc<Wire[]>(
      `/api/v1/plc/canvas/projects/${encodeURIComponent(projectId)}/conversations`,
    );
    return Array.isArray(data) ? data.map(toConversationMeta) : [];
  } catch {
    return [];
  }
}

/** 单对话完整对象(含 messages);不存在 / 网络错 → null */
export async function fetchConversation(id: string): Promise<Conversation | null> {
  try {
    return toConversation((await requestPlc<Wire>(
      `/api/v1/plc/canvas/conversations/${encodeURIComponent(id)}`,
    )) as Wire);
  } catch {
    return null;
  }
}

/** 整对话 upsert(只带消息不带画布);失败 → null */
export async function putConversation(
  conversation: Conversation,
): Promise<ConversationMeta | null> {
  try {
    const meta = await requestPlc<Wire>(
      `/api/v1/plc/canvas/conversations/${encodeURIComponent(conversation.id)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(conversationToWire(conversation)),
      },
    );
    return toConversationMeta((meta ?? {}) as Wire);
  } catch {
    return null;
  }
}

/** 删除对话(服务端同步所属工程 conversation_count);失败 → false */
export async function deleteConversation(id: string): Promise<boolean> {
  try {
    await requestPlc(`/api/v1/plc/canvas/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return true;
  } catch {
    return false;
  }
}

/** 在工程下新建空对话(title 缺省由服务端补「新对话」);失败 → null */
export async function createConversation(
  projectId: string,
  title: string,
): Promise<Conversation | null> {
  try {
    return toConversation((await requestPlc<Wire>(
      `/api/v1/plc/canvas/projects/${encodeURIComponent(projectId)}/conversations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      },
    )) as Wire);
  } catch {
    return null;
  }
}
