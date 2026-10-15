/**
 * Graph layout & graph algorithms for the PLC global graph canvas.
 *
 * Pure TypeScript, no React / DOM. The only asynchronous path is the ELK
 * layout call inside `computeLayout()`; every failure path falls back to the
 * deterministic `simpleLayeredLayout()`.
 */
import ELK, { type ElkNode } from "elkjs/lib/elk.bundled.js";
import type { CanvasBlockData } from "../canvas/types";

// ------------------------------------------------------------------ contracts

export interface GraphEdgeLite {
  from: string;
  to: string;
  count: number;
}

export interface Pt {
  x: number;
  y: number;
}

/** One OB group: the OB plus the forward-reachable call-chain members. */
export interface ObGroup {
  key: string;
  ob: string;
  members: string[];
}

/** ObGroup plus its container bounding box (28px title bar already included). */
export type ObGroupBox = ObGroup & { x: number; y: number; w: number; h: number };

export interface LayoutResult {
  positions: Record<string, Pt>;
  groups: ObGroupBox[];
}

// ------------------------------------------------------------ geometry consts

/** Node footprint on the canvas. */
const NODE_W = 156;
const NODE_H = 48;
/** Simple fallback layout: horizontal gap, layer pitch, outer padding. */
const SIMPLE_GAP_X = 36;
const SIMPLE_LAYER_PITCH = 120;
const SIMPLE_PAD = 40;
/** Group frame: padding around members and the height of the title bar. */
const GROUP_PAD = 12;
const GROUP_TITLE_H = 28;

const STANDALONE = "standalone";
const GRP_PREFIX = "grp:";

// -------------------------------------------------------------------- helpers

function dedupeBlocks(blocks: CanvasBlockData[]): CanvasBlockData[] {
  const byName = new Map<string, CanvasBlockData>();
  for (const b of blocks) byName.set(b.name, b);
  return [...byName.values()];
}

function nameSort(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

function buildAdjacency(edges: { from: string; to: string }[], reverse: boolean): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    const key = reverse ? e.to : e.from;
    const value = reverse ? e.from : e.to;
    const list = adj.get(key);
    if (list) list.push(value);
    else adj.set(key, [value]);
  }
  return adj;
}

/** All block names inside a group's frame (the OB itself + members; standalone: members only). */
function groupFrameNames(g: ObGroup): string[] {
  return g.key === STANDALONE ? [...g.members] : [g.ob, ...g.members];
}

/** Aggregate a bounding box over laid-out members: pad 12 each side, +28 title bar on top. */
function aggregateGroupBox(
  names: string[],
  positions: Record<string, Pt>,
): { x: number; y: number; w: number; h: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of names) {
    const p = positions[n];
    if (!p) continue;
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x + NODE_W > maxX) maxX = p.x + NODE_W;
    if (p.y + NODE_H > maxY) maxY = p.y + NODE_H;
  }
  if (minX === Infinity) return { x: 0, y: 0, w: 0, h: 0 };
  return {
    x: minX - GROUP_PAD,
    y: minY - GROUP_PAD - GROUP_TITLE_H,
    w: maxX - minX + 2 * GROUP_PAD,
    h: maxY - minY + 2 * GROUP_PAD + GROUP_TITLE_H,
  };
}

// --------------------------------------------------------------- graph queries

/**
 * OB group membership. `edges` are directed call edges (from -> to); each OB is
 * treated as a root, its group collects the forward-reachable blocks (BFS).
 * OBs are mutually unreachable (BFS stops at other OBs), unknown names do not
 * chain. Blocks reachable from no OB end up in the "standalone" group, which
 * is omitted when empty.
 */
export function obGroups(blocks: CanvasBlockData[], edges: { from: string; to: string }[]): ObGroup[] {
  const unique = dedupeBlocks(blocks);
  const known = new Set(unique.map((b) => b.name));
  const obNames = unique.filter((b) => b.block_type === "OB").map((b) => b.name);
  const obSet = new Set(obNames);
  const forward = buildAdjacency(edges, false);

  const groups: ObGroup[] = [];
  const assigned = new Set<string>();

  for (const ob of [...obNames].sort(nameSort)) {
    const members = new Set<string>();
    const seen = new Set<string>([ob]);
    const queue: string[] = [ob];
    while (queue.length > 0) {
      const cur = queue.shift() as string;
      for (const next of forward.get(cur) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        if (!known.has(next) || obSet.has(next)) continue;
        members.add(next);
        assigned.add(next);
        queue.push(next);
      }
    }
    groups.push({ key: `ob:${ob}`, ob, members: [...members].sort(nameSort) });
  }

  const standaloneMembers = unique
    .filter((b) => b.block_type !== "OB" && !assigned.has(b.name))
    .map((b) => b.name)
    .sort(nameSort);
  if (standaloneMembers.length > 0) {
    groups.push({ key: STANDALONE, ob: "", members: standaloneMembers });
  }
  return groups;
}

/** Bidirectional N-hop neighbourhood (including the node itself): callers + callees, `hops` levels out. */
export function neighborhood(name: string, edges: { from: string; to: string }[], hops: number): Set<string> {
  const forward = buildAdjacency(edges, false);
  const backward = buildAdjacency(edges, true);
  const result = new Set<string>([name]);
  let frontier: string[] = [name];
  let remaining = Math.max(0, Math.floor(hops));
  while (remaining-- > 0 && frontier.length > 0) {
    const nextFrontier: string[] = [];
    for (const n of frontier) {
      for (const m of [...(forward.get(n) ?? []), ...(backward.get(n) ?? [])]) {
        if (!result.has(m)) {
          result.add(m);
          nextFrontier.push(m);
        }
      }
    }
    frontier = nextFrontier;
  }
  return result;
}

// --------------------------------------------------------- simple layered layout

/**
 * Deterministic fallback: three layers (OB / FB+FC / DB+UDT), nodes 156x48,
 * horizontal gap 36, layer pitch 120, outer padding 40. Long layers wrap into
 * sub-rows (opts.maxPerRow, default Infinity) so the graph stays narrow.
 * Group frames are aggregated from their members (+pad 12, +28px title bar).
 */
export function simpleLayeredLayout(
  blocks: CanvasBlockData[],
  edges: GraphEdgeLite[],
  overrides: Record<string, Pt> = {},
  opts?: { maxPerRow?: number },
): LayoutResult {
  const maxPerRow = Math.max(1, opts?.maxPerRow ?? Number.POSITIVE_INFINITY);
  const unique = dedupeBlocks(blocks);
  const rows: CanvasBlockData[][] = [
    unique.filter((b) => b.block_type === "OB"),
    unique.filter((b) => b.block_type === "FB" || b.block_type === "FC"),
    unique.filter((b) => b.block_type === "DB" || b.block_type === "UDT"),
  ];
  const SUB_ROW_PITCH = NODE_H + 64; // 折行子行间距
  const positions: Record<string, Pt> = {};
  let layerTop = SIMPLE_PAD;
  rows.forEach((row) => {
    row.sort((a, b) => nameSort(a.name, b.name));
    // 该层按 maxPerRow 折行后的子行数
    const subRows = Math.max(1, Math.ceil(row.length / maxPerRow));
    row.forEach((b, index) => {
      const pinnedAt = overrides[b.name];
      if (pinnedAt) {
        positions[b.name] = { x: pinnedAt.x, y: pinnedAt.y };
        return;
      }
      const col = index % maxPerRow;
      const subRow = Math.floor(index / maxPerRow);
      positions[b.name] = {
        x: SIMPLE_PAD + col * (NODE_W + SIMPLE_GAP_X),
        y: layerTop + subRow * SUB_ROW_PITCH,
      };
    });
    layerTop += subRows * NODE_H + (subRows - 1) * 64 + SIMPLE_LAYER_PITCH - NODE_H;
  });
  const groups = obGroups(unique, edges).map((g) => ({
    ...g,
    ...aggregateGroupBox(groupFrameNames(g), positions),
  }));
  return { positions, groups };
}

// ------------------------------------------------------------------ ELK layout

let elkSingleton: InstanceType<typeof ELK> | null = null;

/** What buildElkGraph produced, needed again when reading the layout back. */
interface ElkPlan {
  graph: ElkNode;
  containerIds: Set<string>;
  pinned: Set<string>;
  groups: ObGroup[];
}

/**
 * ELK layered layout with group containers. Blocks listed in
 * `opts.overrides` are pinned: they are excluded from ELK and keep their
 * override position; group frames containing pinned blocks are re-aggregated
 * afterwards (min/max + pad 12 + 28px title bar). Any ELK failure falls back
 * to `simpleLayeredLayout`.
 */
export async function computeLayout(
  blocks: CanvasBlockData[],
  edges: GraphEdgeLite[],
  opts?: { overrides?: Record<string, Pt>; aspect?: number; maxPerRow?: number },
): Promise<LayoutResult> {
  const overrides = opts?.overrides ?? {};
  const unique = dedupeBlocks(blocks);
  if (unique.length === 0) return { positions: {}, groups: [] };

  let plan: ElkPlan;
  try {
    if (!elkSingleton) elkSingleton = new ELK();
    plan = buildElkPlan(unique, edges, overrides);
  } catch (err) {
    elkSingleton = null;
    console.warn("[graphLayout] ELK initialisation failed, using simpleLayeredLayout:", err);
    return simpleLayeredLayout(unique, edges, overrides, { maxPerRow: opts?.maxPerRow });
  }

  // Every block pinned (or nothing left for ELK): positions come straight
  // from the overrides and the frames are aggregated around them.
  if (plan.graph.children.length === 0) {
    const positions: Record<string, Pt> = {};
    for (const b of unique) {
      const ov = overrides[b.name];
      if (ov) positions[b.name] = { x: ov.x, y: ov.y };
    }
    const groups = plan.groups.map((g) => ({ ...g, ...aggregateGroupBox(groupFrameNames(g), positions) }));
    return { positions, groups };
  }

  // 目标宽高比（栏宽/栏高，竖长栏 < 1）：供 ELK 参考（layered 同层仍单行，见下方宽度守卫）
  if (opts?.aspect && Number.isFinite(opts.aspect) && opts.aspect > 0) {
    plan.graph.layoutOptions = {
      ...(plan.graph.layoutOptions ?? {}),
      "elk.aspectRatio": String(opts.aspect),
    };
  }

  try {
    const result = await elkSingleton.layout(plan.graph);
    const laid = collectElkResult(result, plan, unique, edges, overrides);
    // 宽度守卫：elk.layered 的同层节点必排单行且忽略 aspectRatio；
    // 若结果宽度超出预算（maxPerRow 个节点宽），改用层内折行的确定性布局。
    if (opts?.maxPerRow && opts.maxPerRow > 0) {
      const xs = Object.values(laid.positions).map((p) => p.x);
      const width = Math.max(...xs, 0) - Math.min(...xs, 0) + NODE_W;
      const budget = opts.maxPerRow * (NODE_W + 28) + SIMPLE_PAD * 2;
      if (width > budget) {
        return simpleLayeredLayout(unique, edges, overrides, { maxPerRow: opts.maxPerRow });
      }
    }
    return laid;
  } catch (err) {
    elkSingleton = null; // let a later call retry the worker
    console.warn("[graphLayout] ELK layout failed, using simpleLayeredLayout:", err);
    return simpleLayeredLayout(unique, edges, overrides, { maxPerRow: opts?.maxPerRow });
  }
}

/**
 * Global layered options. They are applied to the root graph AND to every
 * group container: with `elk.hierarchyHandling=INCLUDE_CHILDREN` the layout
 * of a container's children reads the container's own options, not the root's.
 */
const ELK_GLOBAL_OPTIONS: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.spacing.nodeNode": "28",
  "elk.layered.spacing.nodeNodeBetweenLayers": "72",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
};

/**
 * Container padding [top=40, left=28, bottom=12, right=12]: 40px on top
 * reserve the 28px group title bar. NOTE: elkjs 0.12 only parses the
 * key=value form, the plain list form "[40,28,12,12]" is silently ignored.
 */
const ELK_CONTAINER_PADDING = "[top=40,left=28,bottom=12,right=12]";

function buildElkPlan(
  blocks: CanvasBlockData[],
  edges: GraphEdgeLite[],
  overrides: Record<string, Pt>,
): ElkPlan {
  const pinned = new Set(blocks.filter((b) => overrides[b.name]).map((b) => b.name));
  const groups = obGroups(blocks, edges);

  // One container per real OB group; pinned members stay out of ELK entirely.
  const containerOf = new Map<string, string>();
  const containers: ElkNode[] = [];
  for (const g of groups) {
    if (g.key === STANDALONE) continue;
    const containerId = `${GRP_PREFIX}${g.key}`;
    const children: ElkNode[] = groupFrameNames(g)
      .filter((n) => !pinned.has(n))
      .map((n) => ({ id: n, width: NODE_W, height: NODE_H }));
    if (children.length === 0) continue; // fully pinned group -> no container
    for (const c of children) containerOf.set(c.id, containerId);
    containers.push({
      id: containerId,
      width: NODE_W,
      height: NODE_H,
      layoutOptions: { ...ELK_GLOBAL_OPTIONS, "elk.padding": ELK_CONTAINER_PADDING },
      children,
    });
  }

  // Blocks without a group container hang directly off the root graph.
  const rootBlocks: ElkNode[] = blocks
    .filter((b) => !pinned.has(b.name) && !containerOf.has(b.name))
    .map((b) => ({ id: b.name, width: NODE_W, height: NODE_H }));

  // Edges live on the root graph. Cross-container edges attach to the
  // container ids; edges inside one container (or between root blocks)
  // attach to the member ids.
  const known = new Set(blocks.map((b) => b.name));
  const seenPairs = new Set<string>();
  const elkEdges: ElkNode["edges"] = [];
  for (const e of edges) {
    if (e.from === e.to) continue;
    if (!known.has(e.from) || !known.has(e.to)) continue;
    if (pinned.has(e.from) || pinned.has(e.to)) continue;
    const cf = containerOf.get(e.from);
    const ct = containerOf.get(e.to);
    const sameContainer = cf !== undefined && cf === ct;
    const src = cf !== undefined && !sameContainer ? cf : e.from;
    const tgt = ct !== undefined && !sameContainer ? ct : e.to;
    const pairKey = `${src}\u0000=>${tgt}`;
    if (seenPairs.has(pairKey)) continue;
    seenPairs.add(pairKey);
    elkEdges.push({ id: `e${seenPairs.size}`, sources: [src], targets: [tgt] });
  }

  const graph: ElkNode = {
    id: "root",
    layoutOptions: { ...ELK_GLOBAL_OPTIONS },
    children: [...containers, ...rootBlocks],
    edges: elkEdges,
  };
  return { graph, containerIds: new Set(containers.map((c) => c.id)), pinned, groups };
}

function collectElkResult(
  result: ElkNode,
  plan: ElkPlan,
  blocks: CanvasBlockData[],
  edges: GraphEdgeLite[],
  overrides: Record<string, Pt>,
): LayoutResult {
  const positions: Record<string, Pt> = {};
  for (const b of blocks) {
    const ov = overrides[b.name];
    if (ov) positions[b.name] = { x: ov.x, y: ov.y };
  }

  // Children of a container are relative to the container; root children are absolute.
  const containerBoxes = new Map<string, { x: number; y: number; w: number; h: number }>();
  for (const child of result.children ?? []) {
    if (plan.containerIds.has(child.id)) {
      const cx = child.x ?? 0;
      const cy = child.y ?? 0;
      containerBoxes.set(child.id, { x: cx, y: cy, w: child.width ?? 0, h: child.height ?? 0 });
      for (const m of child.children ?? []) {
        positions[m.id] = { x: cx + (m.x ?? 0), y: cy + (m.y ?? 0) };
      }
    } else {
      positions[child.id] = { x: child.x ?? 0, y: child.y ?? 0 };
    }
  }

  // Safety net: anything ELK did not place gets a deterministic fallback spot.
  const missing = blocks.filter((b) => !positions[b.name]);
  if (missing.length > 0) {
    const simple = simpleLayeredLayout(blocks, edges, overrides);
    for (const b of missing) positions[b.name] = simple.positions[b.name];
  }

  const groups: ObGroupBox[] = plan.groups.map((g) => {
    const frame = groupFrameNames(g);
    const containerId = g.key === STANDALONE ? undefined : `${GRP_PREFIX}${g.key}`;
    const containerBox =
      containerId !== undefined && containerBoxes.has(containerId) && !frame.some((n) => plan.pinned.has(n))
        ? containerBoxes.get(containerId)
        : undefined;
    return { ...g, ...(containerBox ?? aggregateGroupBox(frame, positions)) };
  });
  return { positions, groups };
}

// ------------------------------------------------------------ gather on select

/** Gather rows: vertical distance between the selected node's top and the row's top. */
const GATHER_ROW_DY = 144;
/** Gather rows: horizontal gap between neighbouring nodes. */
const GATHER_GAP_X = 28;
/** Default "far" threshold: nodes farther than this (euclidean) get gathered. */
const GATHER_DIST = 460;
/** Minimum breathing room enforced between any two rects (overlap test clearance). */
const GATHER_CLEAR = 20;

export interface GatherOptions {
  /** Decides whether a 1-hop neighbour is "far" and should be moved in. Default: euclidean distance > 460. */
  isFar?: (name: string, pt: Pt) => boolean;
}

export interface GatherResult {
  /** Full position table (untouched entries keep their original reference). */
  positions: Record<string, Pt>;
  /** Names that moved: gathered neighbours + unrelated nodes pushed out of the way. */
  moved: string[];
}

function rectsOverlap(a: Pt, b: Pt): boolean {
  return (
    a.x < b.x + NODE_W + GATHER_CLEAR &&
    b.x < a.x + NODE_W + GATHER_CLEAR &&
    a.y < b.y + NODE_H + GATHER_CLEAR &&
    b.y < a.y + NODE_H + GATHER_CLEAR
  );
}

/**
 * Pull far-away 1-hop callers/callees next to the selected block: callers in a
 * row above, callees in a row below (name-sorted, centred on the selection).
 * Near neighbours and the selection keep their positions; unrelated nodes that
 * end up overlapping the new cluster are pushed outward. Pure and
 * deterministic — the caller drives any animation. No relations → no-op.
 */
export function gatherLayout(
  positions: Record<string, Pt>,
  edges: { from: string; to: string }[],
  selected: string,
  opts?: GatherOptions
): GatherResult {
  const s = positions[selected];
  if (!s) return { positions, moved: [] };
  const isFar = opts?.isFar ?? ((_n: string, p: Pt) => Math.hypot(p.x - s.x, p.y - s.y) > GATHER_DIST);

  const callers = [...new Set(edges.filter((e) => e.to === selected && e.from !== selected).map((e) => e.from))];
  const callees = [...new Set(edges.filter((e) => e.from === selected && e.to !== selected).map((e) => e.to))];
  const hop1 = new Set([...callers, ...callees]);
  if (hop1.size === 0) return { positions, moved: [] };

  const next: Record<string, Pt> = { ...positions };
  const moved: string[] = [];
  /**
   * Rects everything must dodge: the selection, staying (near) neighbours, then
   * whatever gets placed or pushed. Unrelated nodes are deliberately NOT
   * registered — the cluster may land on them and push them out instead.
   */
  const occupied: Pt[] = [s];
  const unrelated: string[] = [];
  for (const [name, p] of Object.entries(positions)) {
    if (name === selected) continue;
    if (hop1.has(name)) {
      if (isFar(name, p)) continue; // will be re-placed below
      occupied.push(p); // near neighbour: immovable part of the cluster
    } else {
      unrelated.push(name);
    }
  }

  /** Park a node at `slot`, stepping right until it clears every occupied rect. */
  const place = (name: string, slot: Pt): void => {
    let p = { x: Math.round(slot.x), y: Math.round(slot.y) };
    for (let i = 0; i < 80 && occupied.some((o) => rectsOverlap(o, p)); i++) {
      p = { x: p.x + NODE_W + GATHER_GAP_X, y: p.y };
    }
    occupied.push(p);
    next[name] = p;
    moved.push(name);
  };

  const row = (names: string[], y: number): void => {
    const list = names.filter((n) => positions[n] && isFar(n, positions[n])).sort(nameSort);
    if (list.length === 0) return;
    const width = list.length * NODE_W + (list.length - 1) * GATHER_GAP_X;
    let x = s.x + NODE_W / 2 - width / 2;
    for (const n of list) {
      place(n, { x, y });
      x += NODE_W + GATHER_GAP_X;
    }
  };
  row(callers, s.y - GATHER_ROW_DY);
  row(callees, s.y + GATHER_ROW_DY);

  // Unrelated nodes that the new cluster landed on: push them outward along the
  // dominant axis away from the selection, then clear any residual overlap.
  for (const name of unrelated) {
    const p = next[name];
    if (!p || !occupied.some((o) => rectsOverlap(o, p))) continue;
    const dx = p.x + NODE_W / 2 - (s.x + NODE_W / 2);
    const dy = p.y + NODE_H / 2 - (s.y + NODE_H / 2);
    const useX = Math.abs(dx) >= Math.abs(dy) || dy === 0;
    const step = useX ? (dx >= 0 ? 1 : -1) * (NODE_W + GATHER_GAP_X) : 0;
    const stepY = useX ? 0 : (dy >= 0 ? 1 : -1) * (NODE_H + GATHER_GAP_X);
    let q = { x: p.x, y: p.y };
    for (let i = 0; i < 80 && occupied.some((o) => rectsOverlap(o, q)); i++) {
      q = { x: q.x + step, y: q.y + stepY };
    }
    next[name] = q;
    moved.push(name);
    occupied.push(q);
  }
  return { positions: next, moved };
}

/** Recompute ObGroup frame boxes from current positions (after gather / manual drag). */
export function refreshGroupBoxes(
  groups: ObGroupBox[],
  positions: Record<string, Pt>
): ObGroupBox[] {
  return groups.map((g) => ({ ...g, ...aggregateGroupBox(groupFrameNames(g), positions) }));
}
