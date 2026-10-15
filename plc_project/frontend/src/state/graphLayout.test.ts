import { describe, expect, it } from "vitest";
import { simpleLayeredLayout, obGroups, neighborhood, gatherLayout, refreshGroupBoxes } from "./graphLayout";
import type { CanvasBlockData } from "../canvas/types";

const blk = (name: string, block_type: CanvasBlockData["block_type"]): CanvasBlockData => ({
  name, block_type, number: 1, language: "SCL", interface: [], networks: [], status: "synced",
});

const blocks = [blk("OB1", "OB"), blk("Main", "OB"), blk("FB1", "FB"), blk("FC1", "FC"), blk("dbA", "DB"), blk("udtX", "UDT")];
const edges = [
  { from: "OB1", to: "FB1", count: 1 },
  { from: "OB1", to: "dbA", count: 2 },
  { from: "FB1", to: "dbA", count: 1 },
];

describe("obGroups", () => {
  it("OB 可达集归属；无入链块归 standalone", () => {
    const g = obGroups(blocks, edges);
    const ob1 = g.find((x) => x.ob === "OB1");
    expect([...(ob1?.members ?? [])].sort()).toEqual(["FB1", "dbA"]);
    const main = g.find((x) => x.ob === "Main");
    expect(main?.members).toEqual([]);
    const standalone = g.find((x) => x.key === "standalone");
    expect([...(standalone?.members ?? [])].sort()).toEqual(["FC1", "udtX"]);
  });
});

describe("neighborhood", () => {
  it("双向 1 跳包含调用者与被调用者", () => {
    const n = [...neighborhood("FB1", edges, 1)];
    expect(n.sort()).toEqual(["FB1", "OB1", "dbA"]);
  });
  it("2 跳扩展到 Main（OB1 的另一可达块 dbA 已在 1 跳；Main 经 OB1 需反向）", () => {
    const n2 = [...neighborhood("dbA", edges, 2)];
    expect(n2).toContain("OB1");
    expect(n2).toContain("FB1");
    expect(n2).toContain("dbA");
  });
});

describe("simpleLayeredLayout", () => {
  it("OB 层在最上、DB/UDT 在最下，全部块有坐标", () => {
    const { positions } = simpleLayeredLayout(blocks, edges);
    expect(positions.OB1.y).toBeLessThan(positions.FB1.y);
    expect(positions.FB1.y).toBeLessThan(positions.dbA.y);
    expect(positions.udtX.y).toBe(positions.dbA.y);
    expect(Object.keys(positions)).toHaveLength(blocks.length);
  });
  it("overrides 钉住的块使用给定坐标", () => {
    const { positions } = simpleLayeredLayout(blocks, edges, { FB1: { x: 999, y: 888 } });
    expect(positions.FB1).toEqual({ x: 999, y: 888 });
  });
  it("maxPerRow 折行：同层第 maxPerRow+1 个节点换行（y 增大、x 回列首）", () => {
    const many = Array.from({ length: 5 }, (_, i) => blk(`FB${i + 1}`, "FB"));
    const { positions } = simpleLayeredLayout(many, [], {}, { maxPerRow: 2 });
    // FB1/FB2 第一行同 y；FB3 换行 y 更大、x 回到列首（与 FB1 同 x）
    expect(positions.FB2.y).toBe(positions.FB1.y);
    expect(positions.FB3.y).toBeGreaterThan(positions.FB1.y);
    expect(positions.FB3.x).toBe(positions.FB1.x);
    expect(positions.FB5.y).toBeGreaterThan(positions.FB3.y);
    // 总宽不超过两列
    const maxX = Math.max(...Object.values(positions).map((p) => p.x));
    expect(maxX).toBeLessThan(40 + 2 * (156 + 36));
  });
});

describe("gatherLayout", () => {
  const gEdges = [
    { from: "Caller1", to: "SEL", count: 1 },
    { from: "Caller2", to: "SEL", count: 2 },
    { from: "SEL", to: "Callee1", count: 1 },
  ];
  const overlapsPair = (a: { x: number; y: number }, b: { x: number; y: number }) =>
    Math.abs(a.x - b.x) < 156 && Math.abs(a.y - b.y) < 48;

  it("远邻居收拢：caller 排上方、callee 排下方，均落在选中块 460px 内", () => {
    const positions: Record<string, { x: number; y: number }> = {
      SEL: { x: 500, y: 500 },
      Caller1: { x: 500, y: 5000 },
      Caller2: { x: 5600, y: 500 },
      Callee1: { x: 3000, y: 3000 },
      X: { x: 60, y: 60 },
    };
    const res = gatherLayout(positions, gEdges, "SEL");
    expect(res.moved.sort()).toEqual(["Callee1", "Caller1", "Caller2"]);
    expect(res.positions.Caller1.y).toBe(500 - 144);
    expect(res.positions.Caller2.y).toBe(500 - 144);
    expect(res.positions.Callee1.y).toBe(500 + 144);
    expect(res.positions.X).toEqual({ x: 60, y: 60 }); // 无关且不碍事 → 不动
    for (const n of res.moved) {
      const d = Math.hypot(res.positions[n].x - 500, res.positions[n].y - 500);
      expect(d).toBeLessThan(460);
    }
    // 两 caller 排一行：x 依次递增且不重叠
    expect(res.positions.Caller2.x).toBeGreaterThan(res.positions.Caller1.x + 155);
  });

  it("近邻居不动（默认 460px 阈值内）", () => {
    const positions: Record<string, { x: number; y: number }> = {
      SEL: { x: 500, y: 500 },
      Caller1: { x: 340, y: 356 },
      Callee1: { x: 340, y: 644 },
    };
    const res = gatherLayout(positions, gEdges, "SEL");
    expect(res.moved).toEqual([]);
    expect(res.positions.Caller1).toEqual({ x: 340, y: 356 });
  });

  it("无调用关系 → no-op；选中块缺坐标 → no-op", () => {
    const positions = { SEL2: { x: 0, y: 0 }, X: { x: 900, y: 900 } };
    expect(gatherLayout(positions, gEdges, "SEL2").moved).toEqual([]);
    expect(gatherLayout(positions, gEdges, "Missing").positions).toBe(positions);
  });

  it("被收拢簇压到的无关块被推开，最终全图无硬重叠", () => {
    const positions: Record<string, { x: number; y: number }> = {
      SEL: { x: 500, y: 500 },
      Callee1: { x: 3000, y: 3000 },
      X: { x: 470, y: 640 }, // 正好落在 callee 目标槽 {500,644} 上
    };
    const res = gatherLayout(positions, gEdges, "SEL");
    expect(res.moved).toContain("X");
    expect(res.positions.Callee1.y).toBe(644);
    const pts = Object.values(res.positions);
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        expect(overlapsPair(pts[i], pts[j])).toBe(false);
      }
    }
  });

  it("isFar 谓词可覆盖默认距离阈值（视口外判定由组件注入）", () => {
    const positions: Record<string, { x: number; y: number }> = {
      SEL: { x: 500, y: 500 },
      Caller1: { x: 340, y: 356 }, // 距离 190 < 460，默认不动
    };
    const strict = gatherLayout(positions, gEdges, "SEL", { isFar: () => true });
    expect(strict.moved).toEqual(["Caller1"]);
    expect(strict.positions.Caller1).toEqual({ x: 500, y: 356 }); // 单节点行居中于选中块上方
  });
});

describe("refreshGroupBoxes", () => {
  it("成员位置变化后分组框重新包住全部成员", () => {
    const lay = simpleLayeredLayout(blocks, edges);
    const moved = { ...lay.positions, dbA: { x: 5000, y: 4000 } };
    const refreshed = refreshGroupBoxes(lay.groups, moved);
    const ob1 = refreshed.find((g) => g.ob === "OB1");
    expect(ob1).toBeDefined();
    expect(ob1!.x).toBeLessThanOrEqual(5000);
    expect(ob1!.x + ob1!.w).toBeGreaterThanOrEqual(5000 + 156);
  });
});
