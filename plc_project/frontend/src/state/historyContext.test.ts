/** 对话历史分级压缩(historyContext)。 */
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "./sessions";
import { compressHistory } from "./historyContext";

function msg(role: "user" | "system", text: string, id = Math.random().toString()): ChatMessage {
  return { id, role, text, ts: Date.now() };
}

describe("compressHistory 分级压缩", () => {
  it("最后一条助手消息近乎全文(步骤清单可被指代解析),去脚注", () => {
    const steps = msg(
      "system",
      "建议步骤:\n1. 在 FB_A 添加变量 i_bEnable Bool\n2. 修改 NW2 互锁\n\n（DeepSeek · 输入 1234 tok · 缓存命中 50% · 输出 567 tok）",
    );
    const out = compressHistory([msg("user", "帮我优化启动"), steps]);
    const last = out[out.length - 1];
    expect(last.fidelity).toBe("full");
    expect(last.text).toContain("i_bEnable");
    expect(last.text).not.toContain("DeepSeek");
    expect(last.text).not.toContain("tok");
  });

  it("更早消息压到首句+关键令牌,markdown 噪声剥离", () => {
    const long = msg(
      "system",
      "# 架构分析\n| 块 | 作用 |\n|---|---|\n| FB1060 | 步序 |\n第一句结论:FB1060_AutoStep 是主状态机。第二句补充:FB1040 负责回原点。第三句无关内容略。",
    );
    const out = compressHistory([long, msg("system", "最新回答")]);
    const brief = out[0];
    expect(brief.fidelity).toBe("brief");
    expect(brief.text.length).toBeLessThanOrEqual(100);
    expect(brief.text).toContain("FB1060_AutoStep");
    expect(brief.text).not.toContain("|");
  });

  it("超过 6 轮丢弃,总预算受限", () => {
    const msgs: ChatMessage[] = [];
    for (let i = 0; i < 10; i++) msgs.push(msg("user", `消息${i}` + "哈".repeat(50)));
    const out = compressHistory(msgs);
    expect(out.length).toBeLessThanOrEqual(6);
    const total = out.reduce((a, b) => a + b.text.length, 0);
    expect(total).toBeLessThanOrEqual(2400);
  });

  it("空消息流返回空", () => {
    expect(compressHistory([])).toEqual([]);
  });
});
