import { describe, expect, it } from "vitest";
import { buildBriefing, briefingToMessage } from "./briefing";
import type { CanvasBlockData, CanvasStateData } from "../canvas/types";

function blank(): CanvasStateData {
  return { project_name: "", blocks: {}, hmi_widgets: {}, tags: {} };
}

function block(partial: Partial<CanvasBlockData> & { name: string }): CanvasBlockData {
  return {
    block_type: "FB",
    number: 1,
    language: "SCL",
    interface: [],
    networks: [],
    status: "synced",
    ...partial,
  };
}

describe("buildBriefing", () => {
  it("空画布:全部计数为 0,建议为默认四条", () => {
    const b = buildBriefing(blank());
    expect(b.blockCount).toBe(0);
    expect(b.convertibleCount).toBe(0);
    expect(b.pendingCount).toBe(0);
    expect(b.interfaceOnlyCount).toBe(0);
    expect(b.tagCount).toBe(0);
    expect(b.networkCount).toBe(0);
    expect(b.suggestions).toHaveLength(4);
    const joined = b.suggestions.join("\n");
    expect(joined).toContain("结构");
    expect(joined).toContain("安全联锁");
    expect(joined).toContain("时序图");
    expect(joined).toContain("重构");
    expect(joined).not.toContain("仿真");
  });

  it("含 DB:synced 的 DB 块不计入可转换,空接口 DB 不计入仅接口", () => {
    const c = blank();
    c.blocks = {
      MainDB: block({ name: "MainDB", block_type: "DB", language: "DB", interface: [] }),
      FB1: block({
        name: "FB1",
        language: "SCL",
        interface: [{ name: "x", data_type: "Bool", section: "VAR_INPUT" }],
        networks: [
          { id: 1, title: "n", language: "SCL", scl_text: "#x := TRUE;", status: "synced" },
        ],
      }),
    };
    c.tags = { I0: { name: "I0", data_type: "Bool", logical_address: "%I0.0" } };
    const b = buildBriefing(c);
    expect(b.blockCount).toBe(2);
    // DB 块 synced+DB 语言 → 不算可转换;FB1 SCL 语言 ≠ DB → 算
    expect(b.convertibleCount).toBe(1);
    expect(b.interfaceOnlyCount).toBe(0);
    expect(b.tagCount).toBe(1);
    expect(b.networkCount).toBe(1);
  });

  it("含 draft 块:计入可转换,建议含重构且无仿真", () => {
    const c = blank();
    c.blocks = {
      Draft1: block({ name: "Draft1", status: "draft", interface: [] }),
    };
    const b = buildBriefing(c);
    expect(b.convertibleCount).toBe(1);
    // 非 DB 且空接口 → 仅接口
    expect(b.interfaceOnlyCount).toBe(1);
    expect(b.suggestions).toHaveLength(4);
    const joined = b.suggestions.join("\n");
    expect(joined).toContain("重构");
    expect(joined).not.toContain("仿真");
  });

  it("含 pending:errors 带「待人工确认」计入 pendingCount", () => {
    const c = blank();
    c.blocks = {
      Keep: block({
        name: "Keep",
        language: "LAD",
        errors: ["AF 转换待人工确认:图形语言保留原始形态"],
      }),
      Clean: block({
        name: "Clean",
        interface: [{ name: "y", data_type: "Int", section: "VAR" }],
      }),
    };
    const b = buildBriefing(c);
    expect(b.pendingCount).toBe(1);
    // Keep 是 LAD 语言 → 可转换;Clean 是 SCL ≠ DB → 也可转换
    expect(b.convertibleCount).toBe(2);
  });

  it("含 HMI:建议加入仿真", () => {
    const c = blank();
    c.blocks = {
      FB1: block({
        name: "FB1",
        interface: [{ name: "x", data_type: "Bool", section: "VAR_INPUT" }],
      }),
    };
    c.hmi_widgets = {
      lamp: {
        id: "lamp", widget_type: "indicator", title: "Lamp", x: 0, y: 0, width: 1, height: 1,
        plc_tag: "FB1.x", data_type: "Bool", current_value: false, status: "synced",
      },
    };
    const b = buildBriefing(c);
    expect(b.suggestions).toHaveLength(4);
    const joined = b.suggestions.join("\n");
    expect(joined).toContain("仿真");
  });

  it("draft + HMI 同时存在:重构与仿真都在,仍为 4 条", () => {
    const c = blank();
    c.blocks = { D1: block({ name: "D1", status: "draft" }) };
    c.hmi_widgets = {
      w: {
        id: "w", widget_type: "button", title: "W", x: 0, y: 0, width: 1, height: 1,
        plc_tag: "t", data_type: "Bool", current_value: false, status: "synced",
      },
    };
    const b = buildBriefing(c);
    expect(b.suggestions).toHaveLength(4);
    const joined = b.suggestions.join("\n");
    expect(joined).toContain("重构");
    expect(joined).toContain("仿真");
  });
});

describe("briefingToMessage", () => {
  it("包含 📋 表头、关键数字与编号建议", () => {
    const b = buildBriefing({
      project_name: "HR002",
      blocks: {
        OB1: block({
          name: "OB1",
          block_type: "OB",
          interface: [{ name: "a", data_type: "Bool", section: "VAR_INPUT" }],
          networks: [
            { id: 1, title: "n1", language: "SCL", scl_text: ";", status: "synced" },
            { id: 2, title: "n2", language: "SCL", scl_text: ";", status: "synced" },
          ],
        }),
        Keep: block({
          name: "Keep",
          language: "LAD",
          errors: ["AF 转换待人工确认:保留原始形态"],
        }),
      },
      hmi_widgets: {},
      tags: {
        t1: { name: "t1", data_type: "Bool", logical_address: "%I0.0" },
        t2: { name: "t2", data_type: "Bool", logical_address: "%I0.1" },
      },
    });
    const msg = briefingToMessage(b);
    expect(msg).toContain("📋");
    expect(msg).toContain("HR002");
    expect(msg).toContain("2 个"); // blockCount
    expect(msg).toContain("2 段"); // networkCount
    expect(msg).toContain("2 个"); // tagCount
    expect(msg).toContain("1"); // convertible / pending / interfaceOnly
    expect(msg).toContain("1. ");
    expect(msg).toContain("4. ");
    expect(msg).toContain("安全联锁");
  });

  it("未命名工程回落默认名,不抛错", () => {
    const msg = briefingToMessage(buildBriefing(blank()));
    expect(msg).toContain("未命名工程");
    expect(msg).toContain("📋");
  });
});
