import { describe, expect, it } from "vitest";
import { makeSession, groupSessions, relativeTime, newSessionId } from "./sessions";
import type { CanvasStateData } from "../canvas/types";

const canvas: CanvasStateData = {
  project_name: "T",
  blocks: {},
  hmi_widgets: {},
  tags: {},
};

describe("makeSession", () => {
  it("标题取首消息截断 16 字，无消息为 新对话", () => {
    const a = makeSession(canvas, "增加急停信号并添加红色急停按钮以及一堆其他内容");
    expect(a.title).toHaveLength(17); // 16 字 + …
    expect(a.title.endsWith("…")).toBe(true);
    expect(a.messages).toHaveLength(1);
    expect(a.messages[0].role).toBe("user");
    const b = makeSession(canvas);
    expect(b.title).toBe("新对话");
    expect(b.messages).toHaveLength(0);
  });

  it("会话 id 唯一且带 s- 前缀", () => {
    expect(newSessionId().startsWith("s-")).toBe(true);
    expect(newSessionId()).not.toBe(newSessionId());
  });
});

describe("groupSessions", () => {
  const DAY = 24 * 3600 * 1000;
  const now = Date.now();
  const mk = (id: string, updatedAt: number) => ({ ...makeSession(canvas), id, updatedAt });

  it("按 今天/昨天/7天内/更早 分组且空组不出现", () => {
    const now = Date.now();
    const today0 = new Date(now); today0.setHours(0, 0, 0, 0);
    const t0 = today0.getTime();
    const groups = groupSessions([
      mk("a", now - 60_000),          // 今天
      mk("b", t0 - 3600 * 1000),      // 昨天（当日零点前 1 小时，不依赖当前时刻）
      mk("c", t0 - 5 * DAY),          // 7 天内
      mk("d", t0 - 30 * DAY),         // 更早
    ]);
    expect(groups.map((g) => g.label)).toEqual(["今天", "昨天", "7 天内", "更早"]);
    expect(groups[0].items.map((s) => s.id)).toEqual(["a"]);
  });

  it("空列表返回空分组", () => {
    expect(groupSessions([])).toEqual([]);
  });
});

describe("relativeTime", () => {
  it("分钟内为 刚刚/N 分钟前", () => {
    const now = Date.now();
    expect(relativeTime(now - 10_000)).toBe("刚刚");
    expect(relativeTime(now - 5 * 60_000)).toBe("5 分钟前");
  });
});
