import { describe, expect, it } from "vitest";
import { analyzeCanvas } from "./crossRef";
import type { CanvasStateData } from "../canvas/types";

function fixture(): CanvasStateData {
  return {
    project_name: "T",
    blocks: {
      OB1: {
        name: "OB1", block_type: "OB", number: 1, language: "SCL", interface: [],
        networks: [
          { id: 1, title: "c", language: "SCL", scl_text: '"MainDB".Run := TRUE;', status: "synced" },
        ],
        status: "synced",
      },
      FB1: {
        name: "FB1", block_type: "FB", number: 1, language: "SCL",
        interface: [
          { name: "Start", data_type: "Bool", section: "VAR_INPUT" },
          { name: "Busy", data_type: "Bool", section: "VAR_STAT" },
        ],
        networks: [
          {
            id: 1, title: "n1", language: "SCL",
            scl_text: 'IF #Start AND "MainDB".Run THEN\n    #Busy := TRUE;\nEND_IF;\n"Ghost".Missing := 1;',
            status: "synced",
          },
        ],
        status: "synced",
      },
      MainDB: {
        name: "MainDB", block_type: "DB", number: 1, language: "DB",
        interface: [
          { name: "Run", data_type: "Bool", section: "VAR" },
          { name: "Idle", data_type: "Bool", section: "VAR" },
        ],
        networks: [],
        status: "synced",
      },
    },
    hmi_widgets: {
      ok: { id: "ok", widget_type: "indicator", title: "OK", x: 0, y: 0, width: 1, height: 1, plc_tag: "MainDB.Run", data_type: "Bool", current_value: false, status: "synced" },
      bad: { id: "bad", widget_type: "indicator", title: "BAD", x: 0, y: 0, width: 1, height: 1, plc_tag: "MainDB.NotExist", data_type: "Bool", current_value: false, status: "synced" },
    },
    tags: {
      Start_PB: { name: "Start_PB", data_type: "Bool", logical_address: "%I0.0" },
    },
  };
}

describe("analyzeCanvas", () => {
  const r = analyzeCanvas(fixture());

  it("定义总数 = 所有块接口变量", () => {
    expect(r.stats.total).toBe(4);
  });

  it("局部与全局引用正确归属", () => {
    const busy = r.entries.find((e) => e.def.key === "FB1.Busy");
    expect(busy?.refs.some((x) => x.kind === "network" && x.blockName === "FB1")).toBe(true);
    const run = r.entries.find((e) => e.def.key === "MainDB.Run");
    expect(run?.refs.length).toBe(3); // OB1 NW1 + FB1 NW1 + HMI ok
    expect(run?.refs.some((x) => x.kind === "hmi")).toBe(true);
  });

  it("未使用变量识别（Idle 无引用）", () => {
    const idle = r.entries.find((e) => e.def.key === "MainDB.Idle");
    expect(idle?.refs.length).toBe(0);
    expect(r.stats.unused).toBe(1);
  });

  it("未定义引用（SCL Ghost + HMI NotExist）", () => {
    expect(r.unknownRefs.some((u) => u.expr.includes("Ghost"))).toBe(true);
    expect(r.hmiUnbound.some((h) => h.tag === "MainDB.NotExist")).toBe(true);
    expect(r.stats.undefined).toBe(2);
  });

  it("块级引用边聚合（OB1→MainDB 与 FB1→MainDB，各 1 次）", () => {
    const edge = (from: string) => r.blockEdges.find((e) => e.from === from);
    expect(edge("OB1")?.to).toBe("MainDB");
    expect(edge("OB1")?.count).toBe(1);
    expect(edge("FB1")?.to).toBe("MainDB");
    expect(edge("FB1")?.count).toBe(1);
    // Ghost 目标不存在于画布：分析层记录该边（供诊断），UI 层按节点存在性过滤
    expect(r.blockEdges.some((e) => e.to === "Ghost")).toBe(true);
  });
});
