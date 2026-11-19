import type {
  SafetyGuardEdge,
  SpatialInstanceNode,
  TemporalStepHyperEdge,
} from '../ir/afHyperGraph.types';

export interface PinnedSugiyamaOptions {
  canvasWidth?: number;
  canvasHeight?: number;
  nodeWidth?: number;
  nodeHeight?: number;
}

export interface PinnedSugiyamaResult {
  nodes: SpatialInstanceNode[];
  placedAddedNodes: SpatialInstanceNode[];
}

interface RectBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

function cloneNode(node: SpatialInstanceNode): SpatialInstanceNode {
  return {
    ...node,
    position: { x: node.position.x, y: node.position.y },
    discreteStates: [...node.discreteStates],
    cohesiveIoMap: { ...node.cohesiveIoMap },
    inPorts: node.inPorts.map((p) => ({ ...p })),
    outPorts: node.outPorts.map((p) => ({ ...p })),
  };
}

function rectsOverlap(a: RectBox, b: RectBox, margin: number): boolean {
  return (
    a.x < b.x + b.w + margin &&
    a.x + a.w + margin > b.x &&
    a.y < b.y + b.h + margin &&
    a.y + a.h + margin > b.y
  );
}

function hasAnyCollision(candidate: RectBox, occupied: RectBox[], margin: number): boolean {
  for (const box of occupied) {
    if (rectsOverlap(candidate, box, margin)) {
      return true;
    }
  }
  return false;
}

function computeSugiyamaLayers(
  allNodes: SpatialInstanceNode[],
  guardEdges: SafetyGuardEdge[],
  temporalSteps: TemporalStepHyperEdge[]
): {
  layerById: Map<string, number>;
  neighborsById: Map<string, Set<string>>;
  maxLayer: number;
} {
  const nodeById = new Map<string, SpatialInstanceNode>();
  const rawDirected = new Map<string, string[]>();
  const neighborsById = new Map<string, Set<string>>();

  for (const n of allNodes) {
    nodeById.set(n.id, n);
    rawDirected.set(n.id, []);
    neighborsById.set(n.id, new Set<string>());
  }

  const addEdge = (fromId: string, toId: string) => {
    if (fromId === toId || !nodeById.has(fromId) || !nodeById.has(toId)) return;
    rawDirected.get(fromId)!.push(toId);
    neighborsById.get(fromId)!.add(toId);
    neighborsById.get(toId)!.add(fromId);
  };

  for (const step of temporalSteps) {
    for (const inv of step.invocations) {
      addEdge(step.fromNode, inv.targetNodeId);
    }
  }
  for (const g of guardEdges) {
    addEdge(g.fromNode, g.toNode);
  }

  // DFS 消除有向环回边，构造无环 DAG 用于最长路径分层
  const acyclicAdj = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const n of allNodes) {
    acyclicAdj.set(n.id, []);
    inDegree.set(n.id, 0);
  }

  const color = new Map<string, 0 | 1 | 2>();
  const dfsBreakCycles = (u: string) => {
    color.set(u, 1);
    for (const v of rawDirected.get(u) ?? []) {
      const state = color.get(v) ?? 0;
      if (state === 1) continue; // 忽略回边
      acyclicAdj.get(u)!.push(v);
      inDegree.set(v, (inDegree.get(v) ?? 0) + 1);
      if (state === 0) {
        dfsBreakCycles(v);
      }
    }
    color.set(u, 2);
  };

  for (const n of allNodes) {
    if ((color.get(n.id) ?? 0) === 0) {
      dfsBreakCycles(n.id);
    }
  }

  const hasBoundaryIn = allNodes.some((n) => n.role === 'BOUNDARY_IN');
  const layerById = new Map<string, number>();
  for (const n of allNodes) {
    if (n.role === 'BOUNDARY_IN') {
      layerById.set(n.id, 0);
    } else {
      layerById.set(n.id, hasBoundaryIn ? 1 : 0);
    }
  }

  // 拓扑最长路径分层
  const topoQueue: string[] = [];
  for (const n of allNodes) {
    if ((inDegree.get(n.id) ?? 0) === 0) {
      topoQueue.push(n.id);
    }
  }

  let head = 0;
  while (head < topoQueue.length) {
    const u = topoQueue[head++];
    const uLayer = layerById.get(u) ?? 0;
    for (const v of acyclicAdj.get(u) ?? []) {
      const vNode = nodeById.get(v);
      const minRank = vNode?.role === 'BOUNDARY_IN' ? 0 : uLayer + 1;
      if (minRank > (layerById.get(v) ?? 0)) {
        layerById.set(v, minRank);
      }
      const nextDeg = (inDegree.get(v) ?? 0) - 1;
      inDegree.set(v, nextDeg);
      if (nextDeg === 0) {
        topoQueue.push(v);
      }
    }
  }

  let maxInternalLayer = 0;
  for (const n of allNodes) {
    if (n.role !== 'BOUNDARY_OUT') {
      maxInternalLayer = Math.max(maxInternalLayer, layerById.get(n.id) ?? 0);
    }
  }
  for (const n of allNodes) {
    if (n.role === 'BOUNDARY_OUT') {
      layerById.set(n.id, Math.max(layerById.get(n.id) ?? 0, maxInternalLayer + 1));
    }
  }

  let maxLayer = 1;
  for (const val of layerById.values()) {
    maxLayer = Math.max(maxLayer, val);
  }

  return { layerById, neighborsById, maxLayer };
}

function findCollisionFreeSlot(
  idealX: number,
  idealY: number,
  occupied: RectBox[],
  bounds: {
    canvasWidth: number;
    canvasHeight: number;
    nodeWidth: number;
    nodeHeight: number;
    paddingX: number;
    paddingY: number;
    margin: number;
  }
): { x: number; y: number } {
  const { canvasWidth, canvasHeight, nodeWidth, nodeHeight, paddingX, paddingY, margin } = bounds;
  const maxX = Math.max(paddingX, canvasWidth - nodeWidth - paddingX);
  const maxY = Math.max(paddingY, canvasHeight - nodeHeight - paddingY);

  const clampedX = Math.round(Math.max(paddingX, Math.min(maxX, idealX)));
  const clampedY = Math.round(Math.max(paddingY, Math.min(maxY, idealY)));

  // 1. 优先尝试理想重心槽位
  if (!hasAnyCollision({ x: clampedX, y: clampedY, w: nodeWidth, h: nodeHeight }, occupied, margin)) {
    return { x: clampedX, y: clampedY };
  }

  // 2. 在画布边界内生成步进候选网格，按距理想重心距离升序选取无碰撞槽位
  const stepX = Math.max(40, Math.round((nodeWidth + margin) / 4));
  const stepY = Math.max(36, Math.round((nodeHeight + margin) / 4));

  const xCoords = new Set<number>([clampedX]);
  for (let x = paddingX; x <= maxX; x += stepX) xCoords.add(Math.round(x));
  xCoords.add(Math.round(maxX));

  const yCoords = new Set<number>([clampedY]);
  for (let y = paddingY; y <= maxY; y += stepY) yCoords.add(Math.round(y));
  yCoords.add(Math.round(maxY));

  const candidates: Array<{ x: number; y: number; score: number }> = [];
  for (const x of xCoords) {
    for (const y of yCoords) {
      candidates.push({
        x,
        y,
        score: Math.abs(x - clampedX) * 1.15 + Math.abs(y - clampedY),
      });
    }
  }
  candidates.sort((a, b) => a.score - b.score || a.y - b.y || a.x - b.x);

  for (const c of candidates) {
    if (!hasAnyCollision({ x: c.x, y: c.y, w: nodeWidth, h: nodeHeight }, occupied, margin)) {
      return { x: c.x, y: c.y };
    }
  }

  // 3. 若画布内已满，在现有占用包络外延展无碰撞网格槽位（保证 100% 不重叠）
  const maxOccupiedBottom = occupied.reduce((m, b) => Math.max(m, b.y + b.h), paddingY);
  const startExtY = Math.round(maxOccupiedBottom + margin + 4);
  const cols = Math.max(1, Math.floor((canvasWidth - paddingX * 2 + margin) / (nodeWidth + margin)));

  for (let row = 0; row < 100; row++) {
    for (let col = 0; col < cols; col++) {
      const x = Math.round(paddingX + col * (nodeWidth + margin));
      const y = Math.round(startExtY + row * (nodeHeight + margin));
      if (!hasAnyCollision({ x, y, w: nodeWidth, h: nodeHeight }, occupied, margin)) {
        return { x, y };
      }
    }
  }

  return { x: clampedX, y: startExtY };
}

/**
 * 算法四：锚点锁定 (isPinned) 增量无跳动 Sugiyama 分层布局器。
 * 严格保证所有 `isPinned === true` 节点坐标 0 像素位移，对未锚定节点与新增节点
 * 按拓扑层与邻接重心排序，并通过矩形碰撞检测落入空闲无重叠槽位。
 */
export function layoutWithPinnedAnchors(
  existingNodes: SpatialInstanceNode[],
  addedNodes: SpatialInstanceNode[],
  guardEdges: SafetyGuardEdge[],
  temporalSteps: TemporalStepHyperEdge[],
  options?: PinnedSugiyamaOptions
): PinnedSugiyamaResult {
  const canvasWidth = options?.canvasWidth ?? 1200;
  const canvasHeight = options?.canvasHeight ?? 760;
  const nodeWidth = options?.nodeWidth ?? 252;
  const nodeHeight = options?.nodeHeight ?? 170;
  const paddingX = 36;
  const paddingY = 64;
  const margin = 16;

  const addedIdSet = new Set(addedNodes.map((n) => n.id));
  const mergedClones: SpatialInstanceNode[] = [];
  const indexById = new Map<string, number>();

  for (const node of existingNodes) {
    indexById.set(node.id, mergedClones.length);
    mergedClones.push(cloneNode(node));
  }
  for (const node of addedNodes) {
    const existingIdx = indexById.get(node.id);
    if (existingIdx !== undefined) {
      mergedClones[existingIdx] = cloneNode(node);
    } else {
      indexById.set(node.id, mergedClones.length);
      mergedClones.push(cloneNode(node));
    }
  }

  const { layerById, neighborsById, maxLayer } = computeSugiyamaLayers(
    mergedClones,
    guardEdges,
    temporalSteps
  );

  const occupiedRects: RectBox[] = [];
  const positionedPosById = new Map<string, { x: number; y: number }>();
  const movableNodes: Array<{ node: SpatialInstanceNode; order: number; layer: number }> = [];

  mergedClones.forEach((node, idx) => {
    if (node.isPinned) {
      // 绝对不变量：isPinned 节点零位移
      occupiedRects.push({
        x: node.position.x,
        y: node.position.y,
        w: nodeWidth,
        h: nodeHeight,
      });
      positionedPosById.set(node.id, { x: node.position.x, y: node.position.y });
    } else {
      movableNodes.push({
        node,
        order: idx,
        layer: layerById.get(node.id) ?? 0,
      });
    }
  });

  // 按 Sugiyama 拓扑层升序处理可移动节点
  const layersMap = new Map<number, Array<{ node: SpatialInstanceNode; order: number }>>();
  for (const entry of movableNodes) {
    const list = layersMap.get(entry.layer) ?? [];
    list.push({ node: entry.node, order: entry.order });
    layersMap.set(entry.layer, list);
  }

  const sortedLayerNums = Array.from(layersMap.keys()).sort((a, b) => a - b);
  const usableWidth = Math.max(nodeWidth, canvasWidth - paddingX * 2 - nodeWidth);

  for (const layerNum of sortedLayerNums) {
    const group = layersMap.get(layerNum)!;

    // 邻接重心 Y 计算
    const withBarycenter = group.map((item) => {
      const neighbors = neighborsById.get(item.node.id) ?? new Set<string>();
      const positionedNeighborYs: number[] = [];
      for (const nbId of neighbors) {
        const nbPos = positionedPosById.get(nbId);
        if (nbPos) positionedNeighborYs.push(nbPos.y);
      }

      const fallbackY =
        item.node.position.y > 0
          ? item.node.position.y
          : Math.round((canvasHeight - nodeHeight) / 2);
      const barycenterY =
        positionedNeighborYs.length > 0
          ? positionedNeighborYs.reduce((acc, y) => acc + y, 0) / positionedNeighborYs.length
          : fallbackY;

      return { ...item, barycenterY };
    });

    withBarycenter.sort((a, b) => a.barycenterY - b.barycenterY || a.order - b.order);

    const layerRatio = maxLayer > 0 ? layerNum / maxLayer : 0.5;
    const pinnedSameLayerXs = mergedClones
      .filter((n) => n.isPinned && (layerById.get(n.id) ?? 0) === layerNum)
      .map((n) => n.position.x);

    const idealLayerX =
      pinnedSameLayerXs.length > 0
        ? pinnedSameLayerXs.reduce((acc, x) => acc + x, 0) / pinnedSameLayerXs.length
        : paddingX + layerRatio * usableWidth;

    for (const item of withBarycenter) {
      const slot = findCollisionFreeSlot(idealLayerX, item.barycenterY, occupiedRects, {
        canvasWidth,
        canvasHeight,
        nodeWidth,
        nodeHeight,
        paddingX,
        paddingY,
        margin,
      });

      item.node.position = { x: slot.x, y: slot.y };
      occupiedRects.push({ x: slot.x, y: slot.y, w: nodeWidth, h: nodeHeight });
      positionedPosById.set(item.node.id, slot);
    }
  }

  const placedAddedNodes = mergedClones.filter((n) => addedIdSet.has(n.id));

  return {
    nodes: mergedClones,
    placedAddedNodes,
  };
}
