/** 中栏三块（全局图 / SCL / HMI）的宽度分配。纯函数，不碰 DOM。 */

export type PaneKey = "graph" | "scl" | "hmi";

export const PANE_ORDER: PaneKey[] = ["graph", "scl", "hmi"];

export interface PaneWidths {
  graph: number;
  scl: number;
  hmi: number;
}

export interface PaneCollapsed {
  graph: boolean;
  scl: boolean;
  hmi: boolean;
}

/** 松手后仍展开时的最小可用宽度 */
export const MIN_W = 190;
/** 拖动中允许压到的下限（再小就是磁吸区） */
export const DRAG_FLOOR = 64;
/** 松手时低于该宽度则收成窄轨 */
export const SNAP_PX = 130;

export function expandedKeys(collapsed: PaneCollapsed): PaneKey[] {
  return PANE_ORDER.filter((k) => !collapsed[k]);
}

/**
 * 与被拖分隔条交换宽度的另一栏：优先右边下一展开栏，没有则向左借。
 * 这样最左缘、最右缘都不动，只挪中间那条缝。
 */
export function partnerOf(collapsed: PaneCollapsed, key: PaneKey): PaneKey | null {
  const keys = expandedKeys(collapsed);
  const i = keys.indexOf(key);
  if (i < 0) return null;
  if (i < keys.length - 1) return keys[i + 1];
  if (i > 0) return keys[i - 1];
  return null;
}

/**
 * 把展开栏的宽度缩放到正好等于 available。
 * 装得下时每栏不低于 MIN_W；装不下时一起缩小，保证总和不变——
 * 全局图左缘贴住历史栏，HMI 右缘贴住变量栏，不留缝也不溢出。
 */
export function fitPaneWidths(
  widths: PaneWidths,
  collapsed: PaneCollapsed,
  available: number,
): PaneWidths {
  const next: PaneWidths = { ...widths };
  const keys = expandedKeys(collapsed);
  if (keys.length === 0 || !(available > 0)) return next;

  const target = Math.max(0, Math.round(available));
  const floor = Math.min(MIN_W, target / keys.length);
  const desired = keys.map((k) => Math.max(1, widths[k]));
  const sum = desired.reduce((a, b) => a + b, 0);
  const scaled = desired.map((d) => (d / sum) * target);
  const locked = keys.map(() => false);

  for (let guard = 0; guard < 8; guard++) {
    let lockedSum = 0;
    let flexSum = 0;
    const flexIdx: number[] = [];
    scaled.forEach((v, i) => {
      if (locked[i]) lockedSum += v;
      else {
        flexSum += v;
        flexIdx.push(i);
      }
    });
    if (flexIdx.length === 0) break;
    const targetFlex = target - lockedSum;
    if (flexSum <= 0) {
      const each = targetFlex / flexIdx.length;
      flexIdx.forEach((i) => {
        scaled[i] = each;
      });
    } else {
      flexIdx.forEach((i) => {
        scaled[i] = (scaled[i] / flexSum) * targetFlex;
      });
    }
    let changed = false;
    flexIdx.forEach((i) => {
      if (scaled[i] < floor - 0.01) {
        scaled[i] = floor;
        locked[i] = true;
        changed = true;
      }
    });
    if (!changed) break;
  }

  const rounded = scaled.map((v) => Math.max(0, Math.round(v)));
  let drift = target - rounded.reduce((a, b) => a + b, 0);
  let i = rounded.length - 1;
  let guard = 0;
  while (drift !== 0 && rounded.length > 0 && guard++ < target + rounded.length + 4) {
    const idx = ((i % rounded.length) + rounded.length) % rounded.length;
    if (drift > 0) {
      rounded[idx] += 1;
      drift -= 1;
    } else if (rounded[idx] > 0) {
      rounded[idx] -= 1;
      drift += 1;
    }
    i -= 1;
  }
  keys.forEach((k, idx) => {
    next[k] = rounded[idx];
  });
  return next;
}

/**
 * 用按下时的宽度 + 总位移调整一对栏。两者之和不变，其余栏不动。
 */
export function resizePair(
  startWidths: PaneWidths,
  collapsed: PaneCollapsed,
  key: PaneKey,
  delta: number,
): PaneWidths {
  const partner = partnerOf(collapsed, key);
  if (!partner) return startWidths;
  const pair = startWidths[key] + startWidths[partner];
  const floor = Math.min(DRAG_FLOOR, pair / 2);
  const next = Math.round(Math.min(pair - floor, Math.max(floor, startWidths[key] + delta)));
  return { ...startWidths, [key]: next, [partner]: pair - next };
}

/** 松手且不收起时，把这一对拉回不小于 MIN_W（空间不够则平分）。 */
export function settlePair(
  widths: PaneWidths,
  collapsed: PaneCollapsed,
  key: PaneKey,
): PaneWidths {
  const partner = partnerOf(collapsed, key);
  if (!partner) return widths;
  const pair = widths[key] + widths[partner];
  const min = Math.min(MIN_W, pair / 2);
  let a = Math.min(pair - min, Math.max(min, widths[key]));
  if (a < MIN_W && pair - MIN_W >= min) a = MIN_W;
  a = Math.round(a);
  return { ...widths, [key]: a, [partner]: pair - a };
}
