import { describe, expect, it } from "vitest";
import {
  fitPaneWidths,
  partnerOf,
  resizePair,
  settlePair,
  type PaneCollapsed,
  type PaneWidths,
} from "./centerPaneLayout";

const open: PaneCollapsed = { graph: false, scl: false, hmi: false };
const base: PaneWidths = { graph: 470, scl: 430, hmi: 340 };

describe("fitPaneWidths", () => {
  it("展开栏宽度之和等于可用宽度，左右外缘不留缝", () => {
    const fitted = fitPaneWidths(base, open, 900);
    expect(fitted.graph + fitted.scl + fitted.hmi).toBe(900);
  });

  it("空间足够时每栏不低于最小宽度", () => {
    const fitted = fitPaneWidths({ graph: 40, scl: 40, hmi: 800 }, open, 1200);
    expect(fitted.graph).toBeGreaterThanOrEqual(190);
    expect(fitted.scl).toBeGreaterThanOrEqual(190);
    expect(fitted.hmi).toBeGreaterThanOrEqual(190);
    expect(fitted.graph + fitted.scl + fitted.hmi).toBe(1200);
  });

  it("空间不够时一起缩小，总和仍等于可用宽度", () => {
    const fitted = fitPaneWidths(base, open, 300);
    expect(fitted.graph + fitted.scl + fitted.hmi).toBe(300);
    expect(fitted.graph).toBeGreaterThan(0);
  });

  it("收起的栏不参与分配", () => {
    const collapsed: PaneCollapsed = { graph: true, scl: false, hmi: false };
    const fitted = fitPaneWidths(base, collapsed, 800);
    expect(fitted.graph).toBe(base.graph);
    expect(fitted.scl + fitted.hmi).toBe(800);
  });
});

describe("resizePair", () => {
  it("只交换相邻两栏，HMI 宽度不变所以右缘不动", () => {
    const next = resizePair(base, open, "graph", 80);
    expect(next.graph + next.scl).toBe(base.graph + base.scl);
    expect(next.hmi).toBe(base.hmi);
    expect(next.graph).toBe(base.graph + 80);
  });

  it("拖到下限后不再侵占另一栏", () => {
    const next = resizePair(base, open, "graph", -5000);
    expect(next.graph).toBeGreaterThanOrEqual(64);
    expect(next.graph + next.scl).toBe(base.graph + base.scl);
  });

  it("右边没有展开栏时向左借，总和不变", () => {
    const collapsed: PaneCollapsed = { graph: false, scl: false, hmi: true };
    expect(partnerOf(collapsed, "scl")).toBe("graph");
    const next = resizePair(base, collapsed, "scl", 40);
    expect(next.scl).toBe(base.scl + 40);
    expect(next.graph + next.scl).toBe(base.graph + base.scl);
    expect(next.hmi).toBe(base.hmi);
  });
});

describe("settlePair", () => {
  it("松手后把过窄但未磁吸的栏抬回最小宽度", () => {
    const dragged = resizePair(base, open, "graph", -(base.graph - 150));
    expect(dragged.graph).toBe(150);
    const settled = settlePair(dragged, open, "graph");
    expect(settled.graph).toBeGreaterThanOrEqual(190);
    expect(settled.graph + settled.scl).toBe(dragged.graph + dragged.scl);
  });
});
