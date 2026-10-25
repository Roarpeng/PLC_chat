/**
 * 对话历史 → LLM 上下文的分级压缩(2026-10-25)。
 *
 * 设计立场(调研结论,详见 docs/20):
 * - 存储层永不压缩:localStorage/服务端账本是事实源,支持复制/回看/再展开;
 * - 压缩只发生在构建上下文的时刻,每次请求即时计算——没有定时器、没有
 *   "保持一段时间再压缩"的状态机,不存在压缩时机问题;
 * - 分级保真:最后一条助手消息近乎全文(指代性指令"按步骤全部修改"引用的
 *   步骤清单就在那里),更早消息规则压缩到首句+关键令牌,>6 轮丢弃;
 * - 纯规则、零额外 LLM 调用:压缩跑在编辑/问答关键路径上,不能引入
 *   新的延迟与故障点;超长会话(>30 轮)再升级滚动摘要(见 docs/20 展望)。
 */
import type { ChatMessage } from "./sessions";

/** 最近一条助手消息的保真上限(步骤清单通常 <1.2k 字) */
const LAST_ASSISTANT_BUDGET = 1200;
/** 其余消息的单条压缩上限 */
const PER_MSG_BUDGET = 100;
/** 最多携带的轮次 */
const MAX_TURNS = 6;
/** 整段 history 的总预算(字符) */
const TOTAL_BUDGET = 2400;

/** 去掉 markdown 结构噪声:标题符/表格/代码围栏/加粗/链接,折叠空白 */
function stripMarkdown(t: string): string {
  return t
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\|.*\|/g, " ")
    .replace(/^\s*[-*]\s+/gm, "")
    // 强调剥离只认星号:下划线在 PLC 标识符(FB_A / i_bEnable)里是常规字符
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

/** 去掉 token 成本脚注(DeepSeek · 输入 … tok)——纯噪声 */
function stripUsageFooter(t: string): string {
  return t.replace(/（DeepSeek[^）]*）\s*$/u, "").trim();
}

function compressOldMessage(text: string): string {
  const flat = stripMarkdown(stripUsageFooter(text));
  if (flat.length <= PER_MSG_BUDGET) return flat;
  // 取首句(或首个换行前的行),不足再补第二句,仍超则硬截断
  const m = flat.match(/^[^。.!?\n]+[。.!?\n]?/);
  let head = m ? m[0].trim() : flat.slice(0, PER_MSG_BUDGET);
  if (head.length < PER_MSG_BUDGET - 20) {
    const rest = flat.slice(head.length).trim();
    const m2 = rest.match(/^[^。.!?\n]+[。.!?\n]?/);
    if (m2) head = (head + " " + m2[0].trim()).trim();
  }
  return head.length > PER_MSG_BUDGET ? head.slice(0, PER_MSG_BUDGET - 1) + "…" : head;
}

export interface HistoryTurn {
  role: string;
  text: string;
  /** full=近乎保真(最后一条助手消息);brief=规则压缩 */
  fidelity: "full" | "brief";
}

/** 分级压缩:输入完整消息流,输出可直接入 prompt 的紧凑历史 */
export function compressHistory(messages: ChatMessage[]): HistoryTurn[] {
  const recent = messages.slice(-MAX_TURNS);
  // 找最近一条助手消息(在窗口内的下标)
  let lastAssistantIdx = -1;
  for (let i = recent.length - 1; i >= 0; i--) {
    if (recent[i].role !== "user") {
      lastAssistantIdx = i;
      break;
    }
  }
  const out: HistoryTurn[] = [];
  let budget = TOTAL_BUDGET;
  for (let i = 0; i < recent.length; i++) {
    const m = recent[i];
    const isLastAssistant = i === lastAssistantIdx;
    if (isLastAssistant) {
      let text = stripUsageFooter(stripMarkdown(m.text || ""));
      if (text.length > LAST_ASSISTANT_BUDGET) text = text.slice(0, LAST_ASSISTANT_BUDGET - 1) + "…";
      if (text.length <= budget) {
        out.push({ role: m.role, text, fidelity: "full" });
        budget -= text.length;
        continue;
      }
    }
    const brief = compressOldMessage(m.text || "");
    if (!brief) continue;
    if (brief.length > budget) break;
    out.push({ role: m.role, text: brief, fidelity: "brief" });
    budget -= brief.length;
  }
  return out;
}
