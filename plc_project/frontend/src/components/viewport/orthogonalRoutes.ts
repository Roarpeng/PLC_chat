export interface Point2D { x: number; y: number }
export interface RouteBox { left: number; right: number; top: number; bottom: number }

interface RoutedEdge {
  key: string;
  p1: Point2D;
  p2: Point2D;
  labelWidth: number;
  opacity: number;
}

interface EdgeRoute {
  d: string;
  label: Point2D;
  leader?: string;
}

const samePoint = (a: Point2D, b: Point2D) => a.x === b.x && a.y === b.y;
const boxFor = (p: Point2D, width: number): RouteBox => ({
  left: p.x - width / 2 - 4,
  right: p.x + width / 2 + 4,
  top: p.y - 14,
  bottom: p.y + 14,
});
const overlaps = (a: RouteBox, b: RouteBox) =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

type Segment = [Point2D, Point2D];
const segments = (points: Point2D[]): Segment[] => points.slice(1)
  .map((point, i): Segment => [points[i], point]).filter(([a, b]) => !samePoint(a, b));
const span = (a: number, b: number, c: number, d: number) =>
  Math.max(0, Math.min(Math.max(a, b), Math.max(c, d)) - Math.max(Math.min(a, b), Math.min(c, d)));
const length = ([a, b]: Segment) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
const intersects = ([a, b]: Segment, rect: RouteBox) => a.x === b.x
  ? a.x > rect.left && a.x < rect.right && span(a.y, b.y, rect.top, rect.bottom) > 0
  : a.y > rect.top && a.y < rect.bottom && span(a.x, b.x, rect.left, rect.right) > 0;
const sharedLength = ([a, b]: Segment, [c, d]: Segment) =>
  a.x === b.x && c.x === d.x && a.x === c.x ? span(a.y, b.y, c.y, d.y)
    : a.y === b.y && c.y === d.y && a.y === c.y ? span(a.x, b.x, c.x, d.x) : 0;

export function orthogonalPath(points: Point2D[]): string {
  const first = points[0];
  return segments(points).reduce((path, [a, b]) => path +
    (a.x === b.x ? ` V ${b.y}` : ` H ${b.x}`), `M ${first.x} ${first.y}`);
}

export function routeOrthogonalEdges(edges: RoutedEdge[], nodeBoxes: RouteBox[]): Map<string, EdgeRoute> {
  const routes = new Map<string, EdgeRoute>();
  const usedSegments: Segment[] = [];
  const labels: RouteBox[] = [];
  const fromLanes = new Map<string, number>();
  const toLanes = new Map<string, number>();
  const ordered = [...edges].sort((a, b) => b.opacity - a.opacity || a.key.localeCompare(b.key));
  for (const edge of ordered) {
    const lane = (p: Point2D, counts: Map<string, number>) => {
      const key = `${p.x},${p.y}`;
      const index = counts.get(key) ?? 0;
      counts.set(key, index + 1);
      return 15 + index * 9;
    };
    const { p1, p2, labelWidth } = edge;
    const source = { x: p1.x + lane(p1, fromLanes), y: p1.y };
    const target = { x: Math.max(4, p2.x - lane(p2, toLanes)), y: p2.y };
    const obstacles = nodeBoxes.map((box) => ({ left: box.left - 5, right: box.right + 5, top: box.top - 5, bottom: box.bottom + 5 }));
    const middleY = Math.round((source.y + target.y) / 2);
    const lanes = new Set([source.y, target.y, middleY, ...Array.from({ length: 18 }, (_, i) =>
      middleY + (i % 2 ? 1 : -1) * 29 * (1 + Math.floor(i / 2))),
      ...obstacles.flatMap((box) => [box.top - 13, box.bottom + 13])]);
    const candidates = [...lanes].filter((y) => y >= 58).map((y) =>
      [p1, source, { x: source.x, y }, { x: target.x, y }, target, p2]);
    if (source.x <= target.x) {
      const middleX = Math.round((source.x + target.x) / 2);
      for (const x of [middleX, source.x, target.x, ...obstacles.flatMap((box) => [box.left - 12, box.right + 12])]) {
        if (x >= source.x && x <= target.x) {
          candidates.push([p1, source, { x, y: source.y }, { x, y: target.y }, target, p2]);
        }
      }
    }
    let chosen = candidates[0];
    let best = Infinity;
    for (const points of candidates) {
      const links = segments(points);
      const interior = segments(points.slice(1, -1));
      const score = links.length * 10 + links.reduce((sum, leg) => sum + length(leg), 0)
        + interior.reduce((sum, leg) => sum
          + obstacles.filter((box) => intersects(leg, box)).length * 10000
          + usedSegments.reduce((overlap, used) => overlap + sharedLength(leg, used) * 2, 0)
          + labels.filter((box) => intersects(leg, box)).length * 90, 0);
      if (score < best) { best = score; chosen = points; }
    }
    usedSegments.push(...segments(chosen.slice(1, -1)));
    if (labelWidth === 0) {
      routes.set(edge.key, { d: orthogonalPath(chosen), label: p1 });
      continue;
    }
    const labelSegments = segments(chosen.slice(1, -1)).sort((a, b) =>
      (length(b) + (b[0].y === b[1].y ? 30 : 0)) - (length(a) + (a[0].y === a[1].y ? 30 : 0)));
    const positions = labelSegments.flatMap(([a, b]) => [0.5, 0.3, 0.7, 0.15, 0.85].map((fraction) => ({
      x: a.x + (b.x - a.x) * fraction, y: a.y + (b.y - a.y) * fraction,
    })));
    const anchor = positions[0] ?? source;
    const clear = (point: Point2D) => {
      const box = boxFor(point, labelWidth);
      return box.left >= 2 && box.top >= 55 && !nodeBoxes.some((other) => overlaps(box, other))
        && !labels.some((other) => overlaps(box, other));
    };
    let label = positions.find(clear);
    let leader: string | undefined;
    if (!label) {
      const x = Math.max(labelWidth / 2 + 8, anchor.x);
      let y = Math.max(72, anchor.y);
      while (!clear({ x, y })) y += 29;
      label = { x, y };
      leader = orthogonalPath([anchor, { x, y: anchor.y }, label]);
    }
    labels.push(boxFor(label, labelWidth));
    routes.set(edge.key, { d: orthogonalPath(chosen), label, leader });
  }
  return routes;
}
