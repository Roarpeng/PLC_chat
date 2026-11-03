/** LongTaskCenter 纯函数层:进行中集合 / upsert-patch-finish 生命周期 / 收尾清扫 / 顶栏芯片 / 秒表文案。 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LONG_TASK_LABELS,
  activeTasks,
  finishTask,
  formatElapsed,
  overflowCount,
  patchTask,
  sweepFinished,
  tasksBySession,
  tasksForOtherSessions,
  topbarChips,
  upsertTask,
  type LongTask,
} from "./longTasks";

/** 默认 running 的最小可跑任务;partial 覆盖任意字段 */
function makeTask(partial: Partial<LongTask> = {}): LongTask {
  return {
    id: "task-1",
    sessionId: "s1",
    kind: "refactor_pipeline",
    title: "重构流水线",
    startedAt: 1000,
    updatedAt: 1000,
    status: "running",
    ...partial,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("activeTasks:过滤 + 排序", () => {
  it("乱序输入只留 running,按 startedAt 升序(先启动在前)", () => {
    const tasks = [
      makeTask({ id: "c", startedAt: 3000 }),
      makeTask({ id: "done", startedAt: 500, status: "done" }),
      makeTask({ id: "a", startedAt: 1000 }),
      makeTask({ id: "b", startedAt: 2000 }),
      makeTask({ id: "err", startedAt: 4000, status: "error" }),
    ];
    expect(activeTasks(tasks).map((t) => t.id)).toEqual(["a", "b", "c"]);
  });

  it("空列表与全终态 → 空数组", () => {
    expect(activeTasks([])).toEqual([]);
    expect(
      activeTasks([
        makeTask({ id: "d1", status: "done" }),
        makeTask({ id: "e1", status: "error" }),
      ]),
    ).toEqual([]);
  });
});

describe("upsertTask:按 id 替换或前插", () => {
  it("新任务前插到队首,原顺序不动", () => {
    const a = makeTask({ id: "a", startedAt: 1000 });
    const b = makeTask({ id: "b", startedAt: 2000 });
    const fresh = makeTask({ id: "new", startedAt: 3000 });
    expect(upsertTask([a, b], fresh).map((t) => t.id)).toEqual(["new", "a", "b"]);
  });

  it("同 id 原位替换不增行,其余条目引用保持", () => {
    const a = makeTask({ id: "a", startedAt: 1000 });
    const b = makeTask({ id: "b", startedAt: 2000 });
    const replaced = makeTask({ id: "a", detail: "第二阶段:编译中" });
    const next = upsertTask([a, b], replaced);
    expect(next).toHaveLength(2);
    expect(next.map((t) => t.id)).toEqual(["a", "b"]);
    expect(next[0]).toBe(replaced);
    expect(next[1]).toBe(b);
  });
});

describe("patchTask / finishTask:目标不存在时静默忽略", () => {
  const tasks = [makeTask({ id: "a" })];

  it("patchTask 不存在的 id → 原数组引用原样返回", () => {
    expect(patchTask(tasks, "nope", { detail: "x" })).toBe(tasks);
  });

  it("finishTask 不存在的 id → 原数组引用原样返回", () => {
    expect(finishTask(tasks, "nope", "done")).toBe(tasks);
  });
});

describe("patchTask:局部合并", () => {
  it("只改补丁字段,自动刷 updatedAt 为当前时间", () => {
    vi.useFakeTimers();
    vi.setSystemTime(88_888);
    const a = makeTask({ id: "a", updatedAt: 1000, detail: "旧进度" });
    const next = patchTask([a], "a", { detail: "TIA 编译中" });
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ id: "a", detail: "TIA 编译中", updatedAt: 88_888 });
    expect(next[0].status).toBe("running"); // 未提及字段保持原值
    expect(next[0]).not.toBe(a); // 不可变更新,返回新条目
  });
});

describe("finishTask:收终态", () => {
  it("done/error 写入状态(error 附 errorText),此后 activeTasks 不再包含", () => {
    const a = makeTask({ id: "a" });
    const b = makeTask({ id: "b" });
    let tasks: LongTask[] = [a, b];
    tasks = finishTask(tasks, "a", "error", "映射失败");
    tasks = finishTask(tasks, "b", "done");
    expect(tasks.find((t) => t.id === "a")).toMatchObject({
      status: "error",
      errorText: "映射失败",
    });
    expect(tasks.find((t) => t.id === "b")).toMatchObject({ status: "done" });
    expect(activeTasks(tasks)).toEqual([]);
    expect(tasks).toHaveLength(2); // 终态保留(收尾展示窗口),不立即删除
  });
});

describe("sweepFinished:收尾展示窗口", () => {
  const NOW = 1_000_000;

  it("终态窗口内保留、窗口外清除,running 无论多旧永不清", () => {
    const tasks = [
      makeTask({ id: "fresh-done", status: "done", updatedAt: NOW - 100 }),
      makeTask({ id: "fresh-error", status: "error", updatedAt: NOW - 2499 }),
      makeTask({ id: "stale-done", status: "done", updatedAt: NOW - 2501 }),
      makeTask({ id: "old-running", startedAt: 1, updatedAt: NOW - 999_999 }),
    ];
    expect(sweepFinished(tasks, 2500, NOW).map((t) => t.id)).toEqual([
      "fresh-done",
      "fresh-error",
      "old-running",
    ]);
  });

  it("边界:now - updatedAt 恰好等于 keepMs → 过期清除(窗口为开区间)", () => {
    const tasks = [makeTask({ id: "edge", status: "done", updatedAt: NOW - 2500 })];
    expect(sweepFinished(tasks, 2500, NOW)).toEqual([]);
  });

  it("keepMs 缺省 2500:2000ms 内保留,3000ms 清除", () => {
    const tasks = [
      makeTask({ id: "in", status: "done", updatedAt: NOW - 2000 }),
      makeTask({ id: "out", status: "error", updatedAt: NOW - 3000 }),
    ];
    expect(sweepFinished(tasks, undefined, NOW).map((t) => t.id)).toEqual(["in"]);
  });
});

describe("tasksBySession / tasksForOtherSessions:会话切分", () => {
  it("二者互斥,并集(按 id)= activeTasks;终态两边都不进", () => {
    const tasks = [
      makeTask({ id: "a", sessionId: "s1", startedAt: 1000 }),
      makeTask({ id: "b", sessionId: "s2", startedAt: 2000 }),
      makeTask({ id: "c", sessionId: "s1", startedAt: 3000, status: "done" }),
      makeTask({ id: "d", sessionId: "s3", startedAt: 400 }),
      makeTask({ id: "e", sessionId: "s2", startedAt: 500, status: "error" }),
    ];
    const mine = tasksBySession(tasks, "s1");
    const others = tasksForOtherSessions(tasks, "s1");
    expect(mine.map((t) => t.id)).toEqual(["a"]);
    expect(others.map((t) => t.id)).toEqual(["d", "b"]); // 均按启动升序
    const mineIds = new Set(mine.map((t) => t.id));
    expect(others.every((t) => !mineIds.has(t.id))).toBe(true); // 互斥
    expect([...mine, ...others].map((t) => t.id).sort()).toEqual(
      activeTasks(tasks).map((t) => t.id).sort(),
    ); // 并集 = active
  });
});

describe("topbarChips / overflowCount:顶栏芯片", () => {
  const tasks = [
    makeTask({ id: "other-1", sessionId: "s2", startedAt: 100 }),
    makeTask({ id: "mine-1", sessionId: "s1", startedAt: 200 }),
    makeTask({ id: "other-2", sessionId: "s2", startedAt: 300 }),
    makeTask({ id: "mine-2", sessionId: "s1", startedAt: 400 }),
    makeTask({ id: "mine-3", sessionId: "s1", startedAt: 500 }),
  ];

  it("当前会话优先(即使其他会话启动更早),每段内按启动升序", () => {
    expect(topbarChips(tasks, "s1", 10).map((t) => t.id)).toEqual([
      "mine-1",
      "mine-2",
      "mine-3",
      "other-1",
      "other-2",
    ]);
  });

  it("超出 max 截断:默认 max=3;max=4 时跨会话芯片开始占位", () => {
    expect(topbarChips(tasks, "s1").map((t) => t.id)).toEqual(["mine-1", "mine-2", "mine-3"]);
    expect(topbarChips(tasks, "s1", 4).map((t) => t.id)).toEqual([
      "mine-1",
      "mine-2",
      "mine-3",
      "other-1",
    ]);
  });

  it("overflowCount = active 总数 - max,负数钳 0(恰好等于 max 时为 0,终态不计入)", () => {
    expect(overflowCount(tasks, "s1")).toBe(2); // 5 running - 3
    expect(overflowCount(tasks, "s1", 5)).toBe(0); // 恰好等于 max
    expect(overflowCount(tasks, "s1", 10)).toBe(0); // 不足 max 不为负
    expect(
      overflowCount([makeTask({ id: "x", status: "done" }), makeTask({ id: "y" })], "s1"),
    ).toBe(0); // 1 running < 3
  });
});

describe("formatElapsed:秒表文案", () => {
  it("m:ss 格式:0 → 0:00,分钟不补零、秒补两位(65s → 1:05)", () => {
    expect(formatElapsed(1000, 1000)).toBe("0:00");
    expect(formatElapsed(0, 65_000)).toBe("1:05");
    expect(formatElapsed(0, 307_000)).toBe("5:07");
  });

  it("满一小时进位 h:mm:ss:3599 → 59:59,3600 → 1:00:00,3661 → 1:01:01", () => {
    expect(formatElapsed(0, 3_599_000)).toBe("59:59");
    expect(formatElapsed(0, 3_600_000)).toBe("1:00:00");
    expect(formatElapsed(0, 3_661_000)).toBe("1:01:01");
  });

  it("now 早于 start(负值)防御为 0:00", () => {
    expect(formatElapsed(5000, 1000)).toBe("0:00");
  });
});

describe("LONG_TASK_LABELS:kind → 文字标签", () => {
  it("三键齐全,与 LongTaskKind 一一对应", () => {
    expect(Object.keys(LONG_TASK_LABELS).sort()).toEqual([
      "compile",
      "llm_answer",
      "refactor_pipeline",
    ]);
    expect(LONG_TASK_LABELS.refactor_pipeline).toBe("重构流水线");
    expect(LONG_TASK_LABELS.compile).toBe("编译回写");
    expect(LONG_TASK_LABELS.llm_answer).toBe("AI 分析");
  });
});
