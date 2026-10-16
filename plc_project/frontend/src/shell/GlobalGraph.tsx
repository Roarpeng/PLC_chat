import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  useViewport,
  type Edge,
  type FitViewOptions,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { CanvasBlockData } from "../canvas/types";
import {
  computeLayout,
  gatherLayout,
  neighborhood,
  refreshGroupBoxes,
  type GraphEdgeLite,
  type ObGroup,
  type Pt,
} from "../state/graphLayout";
import "./globalgraph.css";

/* ==========================================================================
   GlobalGraph — 全局块连线图（React Flow @xyflow/react v12）
   布局由 ../state/graphLayout 的 computeLayout 提供（ELK 分层 + OB 分组框），
   本组件负责：自定义节点 / 只读分组框 / 计数着色连线 / 小地图 / 工具栏 /
   搜索 / ±2 跳聚焦 / 位置记忆（localStorage，按项目分档）。
   交互：拖空白平移、滚轮缩放（光标锚点）、拖节点自由摆放（记忆）、
   单击选中（延时 260ms 与双击区分）、双击下钻。
   ========================================================================== */

export type GlobalGraphEdge = GraphEdgeLite;

export interface GlobalGraphProps {
  blocks: CanvasBlockData[];
  edges: GraphEdgeLite[];
  selectedBlockName: string | null;
  onSelectBlock(name: string | null): void;
  /** 空态"新建逻辑块"按钮回调；缺省时不显示该按钮 */
  onCreateBlock?: () => void;
  /** 位置记忆的项目键（一般传 canvas.project_name） */
  projectKey?: string;
  /** 双击节点 → 下钻块内网络图 */
  onDrillDown?: (blockName: string) => void;
  /** 中栏子栏分隔条拖拽进行中：重排推迟到松手，拖拽中零布局计算 */
  paneDragging?: boolean;
}

/* —— 几何与记忆常量 —— */
const NODE_W = 156;
const NODE_H = 48;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;
const POS_KEY = "plc-copilot.graphpos.v1";
/** 单击与双击的区分窗口（毫秒） */
const CLICK_DELAY = 260;
/** 程序化视口动画（fitView duration 200ms）期间忽略 onMove 的"用户已触碰"标记 */
const PROG_GUARD_MS = 320;
/** 焦聚模式跳数 */
const FOCUS_HOPS = 2;

/* ==========================================================================
   位置记忆（localStorage，{[projectKey]:{[name]:Pt}}）
   ========================================================================== */

function loadPositions(projectKey: string): Record<string, Pt> {
  try {
    const raw = localStorage.getItem(POS_KEY);
    if (!raw) return {};
    const all = JSON.parse(raw) as Record<string, Record<string, Pt>>;
    return all?.[projectKey] ?? {};
  } catch {
    return {};
  }
}

function savePosition(projectKey: string, name: string, pos: Pt): void {
  try {
    const raw = localStorage.getItem(POS_KEY);
    const all = raw ? (JSON.parse(raw) as Record<string, Record<string, Pt>>) : {};
    const proj = all[projectKey] ?? {};
    proj[name] = pos;
    all[projectKey] = proj;
    localStorage.setItem(POS_KEY, JSON.stringify(all));
  } catch {
    /* 静默：隐私模式 / 配额满不拖垮画布 */
  }
}

function clearPositions(projectKey: string): void {
  try {
    const raw = localStorage.getItem(POS_KEY);
    if (!raw) return;
    const all = JSON.parse(raw) as Record<string, Record<string, Pt>>;
    delete all[projectKey];
    localStorage.setItem(POS_KEY, JSON.stringify(all));
  } catch {
    /* 静默 */
  }
}

/* ==========================================================================
   连线着色：引用计数 1→N 无级插值 灰白→橙（sqrt 拉开小数值差异）
   ========================================================================== */

function edgeRGB(count: number, maxCount: number): [number, number, number] {
  if (maxCount <= 1) return [201, 204, 196];
  const t = Math.sqrt(Math.min(1, Math.max(0, (count - 1) / (maxCount - 1))));
  return [
    Math.round(201 + (224 - 201) * t),
    Math.round(204 + (116 - 204) * t),
    Math.round(196 + (0 - 196) * t),
  ];
}

const EDGE_GRADIENT =
  "linear-gradient(90deg, rgb(201,204,196), rgb(224,116,0))"; // taste-skill-ignore: data colour-scale legend

/** 布局服务不可用时的兜底：等距网格 */
function fallbackLayout(blocks: CanvasBlockData[]): {
  positions: Record<string, Pt>;
  groups: (ObGroup & { x: number; y: number; w: number; h: number })[];
} {
  const positions: Record<string, Pt> = {};
  blocks.forEach((b, i) => {
    positions[b.name] = {
      x: 40 + (i % 6) * (NODE_W + 36),
      y: 40 + Math.floor(i / 6) * (NODE_H + 48),
    };
  });
  return { positions, groups: [] };
}

/* ==========================================================================
   自定义节点类型
   ========================================================================== */

type BlockNodeData = {
  block: CanvasBlockData;
  /** 当前选中块（受控 prop selectedBlockName） */
  sel: boolean;
  /** 选中块的 1 跳调用方/被调方：钢蓝描边提亮 */
  rel: boolean;
  /** 已有选中块时的无关节点：轻度退后 */
  out: boolean;
  /** 搜索未命中 → 整体淡化 */
  dim: boolean;
  onKeySelect: (name: string) => void;
  [key: string]: unknown;
};
type GgBlockNode = Node<BlockNodeData, "block">;

type GroupNodeData = {
  label: string;
  w: number;
  h: number;
  dim: boolean;
  [key: string]: unknown;
};
type GgGroupNode = Node<GroupNodeData, "obgroup">;

type GgNode = GgBlockNode | GgGroupNode;

/** 块节点：白底 156×48 + 顶部 3px 状态条 + 徽标/名称/comment 两行 */
function BlockNodeView({ data }: NodeProps<GgBlockNode>) {
  const b = data.block;
  const rawComment = (b.comment ?? "").trim();
  return (
    <div
      className={
        "gg-node gg-node--" +
        b.status +
        (data.sel ? " gg-node--sel" : "") +
        (data.rel ? " gg-node--rel" : "") +
        (data.out ? " gg-node--out" : "") +
        (data.dim ? " gg-node--dim" : "")
      }
      style={{ width: NODE_W, height: NODE_H }}
      role="button"
      tabIndex={0}
      aria-label={`${b.block_type} ${b.name}，单击选中，双击下钻，可拖拽摆放`}
      onKeyDown={(ev: ReactKeyboardEvent<HTMLDivElement>) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          data.onKeySelect(b.name);
        }
      }}
    >
      {/* 隐藏式锚点：source 底 / target 顶，仅作连线锚点 */}
      <Handle type="target" position={Position.Top} className="gg-h" isConnectable={false} />
      <span className="gg-node__bar" aria-hidden="true" />
      <span className="gg-node__row1">
        <span className="gg-node__badge">[{b.block_type}]</span>
        <span className="gg-node__name">&quot;{b.name}&quot;</span>
      </span>
      {rawComment && (
        <span className="gg-node__cmt" title={rawComment}>
          {rawComment}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} className="gg-h" isConnectable={false} />
    </div>
  );
}

/** 只读分组背景框：OB 调用链视觉容器（成员块不设 parentId，独立可拖） */
function ObGroupNodeView({ data }: NodeProps<GgGroupNode>) {
  return (
    <div
      className={"gg-group" + (data.dim ? " gg-group--dim" : "")}
      style={{ width: data.w, height: data.h }}
    >
      <span className="gg-group__label">{data.label}</span>
    </div>
  );
}

/** nodeTypes 必须模块级常量：避免每次渲染重建导致 React Flow 重挂载 */
const nodeTypes: NodeTypes = {
  block: BlockNodeView,
  obgroup: ObGroupNodeView,
};

/** 小地图节点颜色：状态色 */
const MINIMAP_STATUS: Record<string, string> = {
  synced: "#1F7A33",
  draft: "#8F5E00",
  error: "#B3261E",
};

/* ==========================================================================
   主组件（Provider 内），导出的 GlobalGraph 只包一层 ReactFlowProvider
   ========================================================================== */

const GlobalGraphCanvas: FC<GlobalGraphProps> = ({
  blocks,
  edges,
  selectedBlockName,
  onSelectBlock,
  onCreateBlock,
  projectKey = "_",
  onDrillDown,
  paneDragging = false,
}) => {
  const rf = useReactFlow();
  const zoom = useViewport().zoom;
  const wrapRef = useRef<HTMLDivElement>(null);

  /* —— 布局结果（computeLayout 异步产出）—— */
  const [positions, setPositions] = useState<Record<string, Pt>>({});
  const [groups, setGroups] = useState<(ObGroup & { x: number; y: number; w: number; h: number })[]>([]);
  const [layoutNonce, setLayoutNonce] = useState(0);
  /** 栏尺寸（节流后）：驱动布局参数（折行数/宽高比）随拖动重排 */
  const [paneSize, setPaneSize] = useState<{ w: number; h: number } | null>(null);

  /* —— 收拢动画定时器（声明在布局 effect 之前，重排时先行中止） —— */
  const gatherTimer = useRef<number | null>(null);
  const cancelGather = useCallback(() => {
    if (gatherTimer.current != null) {
      window.clearTimeout(gatherTimer.current);
      gatherTimer.current = null;
    }
  }, []);

  /* —— 栏尺寸监听：拖分隔条改变栏宽 → 节流重算布局（拖动中也排，不只等松手）。
        观察图栏面板父容器（永不因空态/重渲染被 React 重建）——直接观察
        .gg 本体会在其节点被重建后失效（观察器盯着脱离文档的死节点，
        尺寸恒为 0，再也不触发），这是"调大小不重排"的根因 —— */
  const layoutKeyRef = useRef("");
  const reportRef = useRef<(() => void) | null>(null);
  const hasBlocks = blocks.length > 0;
  /* 分隔条拖拽结束：立刻按最终栏宽再排一次（拖动过程中由下面的节流观察器跟着重排） */
  useEffect(() => {
    if (!paneDragging) reportRef.current?.();
  }, [paneDragging]);
  useEffect(() => {
    const el = (wrapRef.current?.parentElement ?? wrapRef.current) as HTMLDivElement | null;
    if (!el) return;
    let timer: number | null = null;
    let lastRun = 0;
    let last = { w: el.clientWidth, h: el.clientHeight };
    const report = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w === last.w && h === last.h) return;
      last = { w, h };
      setPaneSize({ w, h });
    };
    reportRef.current = report;
    /* 节流而不是防抖：拖动过程中大约每 120ms 重排一次，松手后的尾巴再补一次 */
    const schedule = () => {
      const now = performance.now();
      const wait = 120 - (now - lastRun);
      if (wait <= 0) {
        if (timer != null) {
          window.clearTimeout(timer);
          timer = null;
        }
        lastRun = now;
        report();
        return;
      }
      if (timer != null) return;
      timer = window.setTimeout(() => {
        timer = null;
        lastRun = performance.now();
        report();
      }, wait);
    };
    const ro = new ResizeObserver(() => schedule());
    ro.observe(el);
    return () => {
      ro.disconnect();
      if (timer != null) window.clearTimeout(timer);
    };
    // 空态 ↔ 有块 翻转时重挂（.gg 节点在空态不挂 ref）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasBlocks]);

  /* —— 交互状态 —— */
  const [query, setQuery] = useState("");
  const [focusMode, setFocusMode] = useState(false);

  /* —— React Flow 受控节点（拖拽由 onNodesChange 就地应用）—— */
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<GgNode>([]);

  /* —— 视口触碰标记：用户手动缩放/平移后，面板尺寸变化不再自动 fitView —— */
  const userTouchedRef = useRef(false);
  /** 程序化动画窗口：此间的 onMove 不算用户触碰 */
  const progRef = useRef(false);
  /** 单击延时器（与双击下钻互斥） */
  const clickTimer = useRef<number | null>(null);
  const matchIdx = useRef(0);

  useEffect(
    () => () => {
      if (clickTimer.current != null) window.clearTimeout(clickTimer.current);
    },
    []
  );

  /* —— 程序化 fitView（带动画保护窗）—— */
  const doFit = useCallback(
    (opts?: FitViewOptions) => {
      progRef.current = true;
      window.setTimeout(() => {
        progRef.current = false;
      }, PROG_GUARD_MS);
      try {
        void rf.fitView({ padding: 0.15, duration: 200, ...opts });
      } catch {
        /* 实例未就绪时静默 */
      }
    },
    [rf]
  );

  /* —— 布局：挂载 / blocks 变化 / 换项目 / 重排 / 栏宽高变化 时重算 —— */
  useEffect(() => {
    let dead = false;
    if (blocks.length === 0) {
      setPositions({});
      setGroups([]);
      return;
    }
    cancelGather(); // 重排覆盖位置：先行中止进行中的收拢动画
    // 本次重排是否仅由栏宽变化引发（blocks/项目/重排键都没变）：
    // 是 → fit 用瞬时（duration 0），避免拖动松手后又一轮视口动画
    const layoutKey = `${blocks.length}|${blocks[0]?.name ?? ""}|${projectKey}|${layoutNonce}`;
    const resizeOnly = layoutKeyRef.current === layoutKey;
    layoutKeyRef.current = layoutKey;
    const overrides = loadPositions(projectKey);
    // 按当前栏尺寸计算布局参数：目标宽高比（约束 ELK 总宽）+ 折行每行节点数上限
    const el = wrapRef.current;
    const paneW = el ? el.clientWidth : 900;
    const paneH = el ? el.clientHeight : 700;
    const aspect = Math.max(0.4, Math.min(2.5, paneW / Math.max(1, paneH)));
    const maxPerRow = Math.max(1, Math.floor((paneW - 80) / 184)); // 156 节点 + 28 间距
    computeLayout(blocks, edges, { overrides, aspect, maxPerRow })
      .then((res) => {
        if (dead) return;
        setPositions(res.positions);
        setGroups(res.groups);
        scheduleFit();
      })
      .catch(() => {
        if (dead) return;
        const fb = fallbackLayout(blocks);
        setPositions(fb.positions);
        setGroups(fb.groups);
        scheduleFit();
      });
    function scheduleFit() {
      /* 双 rAF + 余量：等 setNodes 与 React Flow 内部 store 应用完成；
         用户已手动缩放/平移过则不夺走视口；
         栏宽变化引发的重排绝不 fitView（用户正盯着自己的视口，
         被抢走就是"点下就跑"），只有挂载/重排按钮/换项目才适配 */
      window.setTimeout(() => {
        if (!dead && !userTouchedRef.current && !resizeOnly) doFit();
      }, 80);
    }
    return () => {
      dead = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocks, projectKey, layoutNonce, paneSize, doFit]);

  /* —— 搜索命中集合 / Enter 循环列表 —— */
  const hits = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return new Set(
      blocks.filter((b) => b.name.toLowerCase().includes(q)).map((b) => b.name)
    );
  }, [query, blocks]);

  const matchList = useMemo(
    () =>
      hits
        ? [...hits].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
        : [],
    [hits]
  );

  /* —— ±N 跳聚焦集合（开启且已有选中块时生效）—— */
  const nbSet = useMemo(() => {
    if (!focusMode || !selectedBlockName) return null;
    const s = neighborhood(selectedBlockName, edges, FOCUS_HOPS);
    s.add(selectedBlockName);
    return s;
  }, [focusMode, selectedBlockName, edges]);

  /* —— 1 跳关联集合（调用方 + 被调方，不含选中块）：rel 高亮 + 收拢依据 —— */
  const relSet = useMemo(() => {
    if (!selectedBlockName) return null;
    const s = neighborhood(selectedBlockName, edges, 1);
    s.delete(selectedBlockName);
    return s;
  }, [selectedBlockName, edges]);

  /* —— 节点派生：分组框在前（层级低），块在后 —— */
  const derivedNodes = useMemo<GgNode[]>(() => {
    const out: GgNode[] = [];
    for (const g of groups) {
      const names = g.ob ? [g.ob, ...g.members] : g.members;
      out.push({
        id: `grp:${g.key}`,
        type: "obgroup",
        position: { x: g.x, y: g.y },
        selectable: false,
        draggable: false,
        connectable: false,
        deletable: false,
        focusable: false,
        hidden: nbSet ? !names.some((n) => nbSet.has(n)) : false,
        data: {
          label: g.ob ? `${g.ob} 调用链` : "未挂 OB 调用链",
          w: g.w,
          h: g.h,
          dim: hits ? !names.some((n) => hits.has(n)) : false,
        },
      });
    }
    for (const b of blocks) {
      const p = positions[b.name];
      if (!p) continue;
      out.push({
        id: b.name,
        type: "block",
        position: { x: p.x, y: p.y },
        deletable: false,
        focusable: false,
        hidden: nbSet ? !nbSet.has(b.name) : false,
        data: {
          block: b,
          sel: b.name === selectedBlockName,
          rel: relSet?.has(b.name) ?? false,
          out: selectedBlockName != null && b.name !== selectedBlockName && !(relSet?.has(b.name) ?? false),
          dim: hits ? !hits.has(b.name) : false,
          onKeySelect: onSelectBlock,
        },
      });
    }
    return out;
  }, [blocks, positions, groups, nbSet, hits, selectedBlockName, relSet, onSelectBlock]);

  useEffect(() => {
    setRfNodes(derivedNodes);
  }, [derivedNodes, setRfNodes]);

  /* —— 分组框随位置变化重新聚合（布局 / 拖拽 / 收拢后始终包住成员） —— */
  useEffect(() => {
    setGroups((gs) => refreshGroupBoxes(gs, positions));
  }, [positions]);

  /* —— 边派生：计数着色 + 选中提亮/其余淡化 + 聚焦裁剪 —— */
  const maxCount = useMemo(() => {
    let m = 1;
    for (const e of edges) {
      if (positions[e.from] && positions[e.to] && e.count > m) m = e.count;
    }
    return m;
  }, [edges, positions]);

  const derivedEdges = useMemo<Edge[]>(() => {
    const list: Edge[] = [];
    for (const e of edges) {
      if (!positions[e.from] || !positions[e.to]) continue;
      const touchesSel =
        selectedBlockName != null && (e.from === selectedBlockName || e.to === selectedBlockName);
      // 关联边 = 直连选中块，或两端都在 1 跳关联集合内（兄弟互调）
      const on =
        selectedBlockName != null &&
        (touchesSel || (!!relSet && relSet.has(e.from) && relSet.has(e.to)));
      const dim = selectedBlockName != null && !on;
      const rgb = edgeRGB(e.count, maxCount);
      const col = dim
        ? `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.18)`
        : `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
      list.push({
        id: `${e.from}->${e.to}`,
        source: e.from,
        target: e.to,
        type: "default",
        selectable: false,
        focusable: false,
        deletable: false,
        hidden: nbSet ? !(nbSet.has(e.from) && nbSet.has(e.to)) : false,
        label: `×${e.count}`,
        labelStyle: {
          fill: col,
          fontFamily: "var(--sans)",
          fontSize: "9.5px",
          fontWeight: on ? 600 : 500,
        },
        labelShowBg: true,
        labelBgStyle: { fill: "#ffffff" },
        labelBgPadding: [2, 4],
        labelBgBorderRadius: 3,
        style: { stroke: col, strokeWidth: on ? (touchesSel ? 2.5 : 2) : 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: col, width: 12, height: 12 },
      });
    }
    list.sort((a, b) => (a.id ?? "").localeCompare(b.id ?? ""));
    return list;
  }, [edges, positions, selectedBlockName, relSet, nbSet, maxCount]);

  /* —— 栏宽变化只重排节点、不 fitView（避免拖动时视口被抢走）。
        重排由上方观察器按 120ms 节流触发，拖动过程中内容跟着折行。 —— */

  /* —— 聚焦模式：开启或选中块变化后 fitView 到可见子图 —— */
  useEffect(() => {
    if (!focusMode || !selectedBlockName) return;
    const t = window.setTimeout(() => doFit(), 60);
    return () => window.clearTimeout(t);
  }, [focusMode, selectedBlockName, doFit]);

  /* —— 聚焦收拢：点选块后，视口外的 1 跳调用方/被调方搬到它上下两排，
        被压到的无关节点向外让位；定时器逐帧插值节点模型位置，
        连线随模型同步重算（避免 CSS 过渡造成"边先跳、节点后滑"的撕裂）。
        注意用 setTimeout 而非 rAF：嵌入式浏览器后台化时 rAF 与 CSS 过渡
        一样会被冻结，定时器仍以 16ms 级触发 ——
        （gatherTimer / cancelGather 声明在布局 effect 之前，见上） —— */

  useEffect(() => {
    if (!selectedBlockName) return;
    const s = positions[selectedBlockName];
    if (!s) return;
    // "远" = 落在当前视口（外扩 96px）之外；视口不可用时退回距离阈值
    let isFar: ((n: string, p: Pt) => boolean) | undefined;
    const el = wrapRef.current;
    try {
      const vp = rf.getViewport();
      if (el && vp) {
        const z = vp.zoom || 1;
        const left = -vp.x / z;
        const top = -vp.y / z;
        const right = left + el.clientWidth / z;
        const bottom = top + el.clientHeight / z;
        const m = 96;
        isFar = (_n, p) =>
          p.x < left - m || p.x > right - NODE_W + m || p.y < top - m || p.y > bottom - NODE_H + m;
      }
    } catch {
      /* 实例未就绪：走 gatherLayout 的默认距离阈值 */
    }
    const res = gatherLayout(positions, edges, selectedBlockName, isFar ? { isFar } : undefined);
    if (res.moved.length === 0) return;
    const from = positions;
    const to = res.positions;
    cancelGather();
    const DUR = 380;
    const t0 = performance.now();
    const tick = () => {
      const k = Math.min(1, (performance.now() - t0) / DUR);
      if (k < 1) {
        const e = 1 - Math.pow(1 - k, 3); // easeOutCubic
        const interp: Record<string, Pt> = { ...from };
        for (const n of res.moved) {
          const a = from[n];
          const b = to[n];
          if (a && b) interp[n] = { x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e };
        }
        setPositions(interp);
        gatherTimer.current = window.setTimeout(tick, 16);
      } else {
        gatherTimer.current = null;
        // 收拢是自动行为：只改当前会话内的位置，不写入位置记忆——
        // 否则被收拢过的块会被当作"手动钉住"，栏宽调节的重排对它失效
        setPositions(to);
      }
    };
    gatherTimer.current = window.setTimeout(tick, 16);
    return cancelGather;
    // 故意只依赖选中名：收拢只在点选瞬间发生一次，位置/视口变化不重触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBlockName]);

  /* —— 交互回调 —— */

  const armClick = useCallback(
    (name: string) => {
      if (clickTimer.current != null) window.clearTimeout(clickTimer.current);
      clickTimer.current = window.setTimeout(() => {
        clickTimer.current = null;
        onSelectBlock(name);
      }, CLICK_DELAY);
    },
    [onSelectBlock]
  );

  const clearClick = useCallback(() => {
    if (clickTimer.current != null) {
      window.clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
  }, []);

  const handleNodeClick = useCallback(
    (_e: React.MouseEvent, node: GgNode) => {
      if (node.type === "block") armClick(node.id);
    },
    [armClick]
  );

  const handleNodeDoubleClick = useCallback(
    (_e: React.MouseEvent, node: GgNode) => {
      if (node.type !== "block" || !onDrillDown) return;
      clearClick(); // 双击不再触发单击选中
      onDrillDown(node.id);
    },
    [onDrillDown, clearClick]
  );

  const handlePaneClick = useCallback(() => {
    clearClick();
    onSelectBlock(null);
  }, [clearClick, onSelectBlock]);

  const handleNodeDrag = useCallback(() => {
    userTouchedRef.current = true;
    cancelGather(); // 用户手动拖拽优先，中止收拢动画
  }, [cancelGather]);

  /** 拖拽结束：位置写回派生源 + localStorage 记忆 */
  const handleNodeDragStop = useCallback(
    (_e: MouseEvent | TouchEvent, node: GgNode, dragged: GgNode[]) => {
      const list = dragged && dragged.length > 0 ? dragged : [node];
      const upd: Record<string, Pt> = {};
      for (const n of list) {
        if (n.type === "block") upd[n.id] = { x: n.position.x, y: n.position.y };
      }
      if (Object.keys(upd).length === 0) return;
      setPositions((prev) => ({ ...prev, ...upd }));
      for (const [name, p] of Object.entries(upd)) savePosition(projectKey, name, p);
      userTouchedRef.current = true;
    },
    [projectKey]
  );

  const handleMove = useCallback(() => {
    if (!progRef.current) userTouchedRef.current = true;
  }, []);

  const zoomBy = useCallback(
    (dir: 1 | -1) => {
      userTouchedRef.current = true;
      try {
        if (dir > 0) void rf.zoomIn({ duration: 200 });
        else void rf.zoomOut({ duration: 200 });
      } catch {
        /* 静默 */
      }
    },
    [rf]
  );

  const fitButton = useCallback(() => {
    userTouchedRef.current = false; // 恢复尺寸自适应
    doFit();
  }, [doFit]);

  /** 重排：清本项目位置记忆 → 重算自动布局 → 适应窗口 */
  const resetLayout = useCallback(() => {
    cancelGather();
    clearPositions(projectKey);
    setLayoutNonce((n) => n + 1); // 触发布局 effect（布局后自带 fitView）
  }, [projectKey, cancelGather]);

  const toggleFocus = useCallback(() => {
    setFocusMode((v) => !v);
    window.setTimeout(() => doFit(), 60); // 关闭后同样恢复全图视野
  }, [doFit]);

  const onSearchKey = useCallback(
    (ev: ReactKeyboardEvent<HTMLInputElement>) => {
      if (ev.key === "Escape") {
        setQuery("");
        matchIdx.current = 0;
        return;
      }
      if (ev.key !== "Enter") return;
      if (matchList.length === 0) return;
      const name = matchList[matchIdx.current % matchList.length];
      matchIdx.current = (matchIdx.current + 1) % matchList.length;
      doFit({ nodes: [{ id: name }], padding: 0.35, duration: 250, maxZoom: 1.2 });
    },
    [matchList, doFit]
  );

  /* —— 空态（保持原样式类名）—— */
  if (blocks.length === 0) {
    return (
      <div className="gg gg--empty">
        <div className="gg-empty__card">
          <div className="gg-empty__title">画布还是空的</div>
          <p className="gg-empty__text">
            全局连线图按 OB 调用链分组展示块之间的调用与引用关系。
            <br />
            创建第一个逻辑块后，即可在此查看全局结构。
          </p>
          {onCreateBlock && (
            <button type="button" className="btn btn--primary" onClick={onCreateBlock}>
              新建逻辑块
            </button>
          )}
          <p className="gg-empty__hint">或从顶部导入博图项目</p>
        </div>
      </div>
    );
  }

  return (
    <div className="gg" ref={wrapRef}>
      <ReactFlow<GgNode, Edge>
        className="gg-flow"
        nodes={rfNodes}
        edges={derivedEdges}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        zoomOnDoubleClick={false}
        panOnScroll={false}
        selectionOnDrag={false}
        nodesDraggable
        elementsSelectable
        nodesConnectable={false}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
        onPaneClick={handlePaneClick}
        onNodeClick={handleNodeClick}
        onNodeDoubleClick={handleNodeDoubleClick}
        onNodeDrag={handleNodeDrag}
        onNodeDragStop={handleNodeDragStop}
        onMove={handleMove}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1.5}
          color="rgba(27,30,28,0.10)"
        />
        <MiniMap
          className="gg-minimap"
          maskColor="rgba(27,30,28,0.08)"
          nodeStrokeWidth={2}
          nodeBorderRadius={3}
          nodeStrokeColor={() => "rgba(27,30,28,0.30)"}
          nodeColor={(n) => {
            const b = (n.data as { block?: CanvasBlockData }).block;
            return MINIMAP_STATUS[b?.status ?? ""] ?? "#C9CCC4";
          }}
        />
      </ReactFlow>

      {/* —— 搜索 + 只看相关（左上角）—— */}
      <div className="gg-searchbar">
        <input
          className="gg-searchbar__input"
          type="text"
          value={query}
          spellCheck={false}
          placeholder="搜索块名，Enter 跳转"
          aria-label="搜索块名"
          onChange={(e) => {
            setQuery(e.target.value);
            matchIdx.current = 0;
          }}
          onKeyDown={onSearchKey}
        />
        <button
          type="button"
          className={"gg-toolbtn" + (focusMode ? " gg-toolbtn--on" : "")}
          aria-pressed={focusMode}
          disabled={!selectedBlockName}
          title={
            selectedBlockName
              ? `只显示所选块 ±${FOCUS_HOPS} 跳内的相关块`
              : "先在画布上点选一个块"
          }
          onClick={toggleFocus}
        >
          只看相关 ±{FOCUS_HOPS} 跳
        </button>
      </div>

      {/* —— 缩放工具栏（右上角，自绘）—— */}
      <div className="gg-zoombar" role="toolbar" aria-label="视图控制">
        <button
          type="button"
          className="gg-zoombar__btn"
          aria-label="缩小"
          title="缩小"
          onClick={() => zoomBy(-1)}
        >
          −
        </button>
        <span className="gg-zoombar__pct">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="gg-zoombar__btn"
          aria-label="放大"
          title="放大"
          onClick={() => zoomBy(1)}
        >
          ＋
        </button>
        <button
          type="button"
          className="gg-zoombar__btn gg-zoombar__fit"
          title="适应窗口"
          onClick={fitButton}
        >
          适应
        </button>
        <button
          type="button"
          className="gg-zoombar__btn gg-zoombar__fit"
          title="重排：清除手动摆放，恢复自动布局"
          onClick={resetLayout}
        >
          重排
        </button>
      </div>

      {/* —— 引用次数色标（左下角；计数有区分度时才显示）—— */}
      {maxCount > 1 && (
        <div className="gg-legend" aria-hidden="true">
          <span className="gg-legend__label">引用次数</span>
          <span className="gg-legend__min">1</span>
          <span className="gg-legend__bar" style={{ background: EDGE_GRADIENT }} />
          <span className="gg-legend__max">{maxCount}</span>
        </div>
      )}
    </div>
  );
};

/** 对外组件：包一层 ReactFlowProvider，供 PlcInteractiveCanvas 直接渲染 */
export const GlobalGraph: FC<GlobalGraphProps> = (props) => (
  <ReactFlowProvider>
    <GlobalGraphCanvas {...props} />
  </ReactFlowProvider>
);
