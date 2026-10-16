import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CanvasHmiWidgetData, CanvasStateData } from "./types";
import { GlobalGraph } from "../shell/GlobalGraph";
import { SclPane } from "../shell/SclPane";
import { HmiPane } from "../shell/HmiPane";
import { DrillDownPanel } from "../shell/DrillDownPanel";
import {
  SNAP_PX,
  expandedKeys,
  fitPaneWidths,
  resizePair,
  settlePair,
  type PaneCollapsed,
  type PaneKey,
  type PaneWidths,
} from "./centerPaneLayout";

export interface FocusTarget {
  kind: "block" | "network" | "hmi";
  blockName?: string;
  networkId?: number;
  widgetId?: string;
}

export interface BlockEdge {
  from: string;
  to: string;
  count: number;
}

interface Props {
  canvas: CanvasStateData;
  selectedBlockName: string | null;
  onSelectBlock: (name: string | null) => void;
  blockEdges: BlockEdge[];
  focus: FocusTarget | null;
  onFocusChange?: (focus: FocusTarget | null) => void;
  onCanvasChange: (canvas: CanvasStateData) => void;
  /* 从零构建 */
  onCreateBlock?: () => void;
  onAddVariable?: (
    blockName: string,
    v: { name: string; data_type: string; section: string; comment?: string }
  ) => void;
  onAddNetwork?: (
    blockName: string,
    n: { title: string; scl_text: string; language?: string }
  ) => void;
  onRemoveBlock?: (blockName: string) => void;
  onRenameBlock?: (oldName: string, newName: string) => void;
  onRemoveVariable?: (blockName: string, varName: string) => void;
  onRemoveNetwork?: (blockName: string, networkId: number) => void;
  onDeepExplain?: (block: CanvasStateData["blocks"][string]) => Promise<string>;
}

/* ------------------------------------------------------------------ */
/* 三栏子面板布局：相邻栏交换宽度，外缘始终贴住左右侧栏                   */
/* ------------------------------------------------------------------ */

interface CenterLayout {
  widths: PaneWidths;
  collapsed: PaneCollapsed;
}

const PANE_TITLES: Record<PaneKey, string> = {
  graph: "全局图",
  scl: "SCL 源码",
  hmi: "HMI 仿真",
};

const LAYOUT_KEY = "plc-copilot.centerpanes.v1";
const DEFAULT_LAYOUT: CenterLayout = {
  widths: { graph: 470, scl: 430, hmi: 340 },
  collapsed: { graph: false, scl: false, hmi: false },
};
const RAIL_W = 30;
/** 松手后写回的展开宽度下限（与 centerPaneLayout.MIN_W 一致） */
const RESTORE_W = 190;

function loadLayout(): CenterLayout {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return { ...DEFAULT_LAYOUT, widths: { ...DEFAULT_LAYOUT.widths }, collapsed: { ...DEFAULT_LAYOUT.collapsed } };
    const parsed = JSON.parse(raw) as Partial<CenterLayout>;
    const num = (v: unknown, d: number) =>
      typeof v === "number" && Number.isFinite(v) && v > 0 ? v : d;
    return {
      widths: {
        graph: num(parsed.widths?.graph, DEFAULT_LAYOUT.widths.graph),
        scl: num(parsed.widths?.scl, DEFAULT_LAYOUT.widths.scl),
        hmi: num(parsed.widths?.hmi, DEFAULT_LAYOUT.widths.hmi),
      },
      collapsed: {
        graph: !!parsed.collapsed?.graph,
        scl: !!parsed.collapsed?.scl,
        hmi: !!parsed.collapsed?.hmi,
      },
    };
  } catch {
    return { ...DEFAULT_LAYOUT, widths: { ...DEFAULT_LAYOUT.widths }, collapsed: { ...DEFAULT_LAYOUT.collapsed } };
  }
}

function outerWidth(el: HTMLElement): number {
  const s = getComputedStyle(el);
  return el.offsetWidth + (parseFloat(s.marginLeft) || 0) + (parseFloat(s.marginRight) || 0);
}

const ChevronLeft: React.FC = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M8 2.5 4.5 6 8 9.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ChevronRight: React.FC = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M4 2.5 7.5 6 4 9.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/* ------------------------------------------------------------------ */

export const PlcInteractiveCanvas: React.FC<Props> = ({
  canvas,
  selectedBlockName,
  onSelectBlock,
  blockEdges,
  focus,
  onFocusChange,
  onCanvasChange,
  onCreateBlock,
  onAddVariable,
  onAddNetwork,
  onRemoveBlock,
  onRenameBlock,
  onRemoveVariable,
  onRemoveNetwork,
  onDeepExplain,
}) => {
  const [layout, setLayout] = useState<CenterLayout>(() => loadLayout());
  const [draggingPane, setDraggingPane] = useState<PaneKey | null>(null);
  const layoutRef = useRef<CenterLayout>(layout);
  const subpanesRef = useRef<HTMLDivElement>(null);
  const paneRefs = useRef<Partial<Record<PaneKey, HTMLElement | null>>>({});
  const dragRef = useRef<null | {
    key: PaneKey;
    startX: number;
    startWidths: PaneWidths;
    pointerId: number;
  }>(null);
  /* 双击块下钻：块内网络流程图 */
  const [drillBlock, setDrillBlock] = useState<string | null>(null);
  const drillBlockData = drillBlock ? canvas.blocks[drillBlock] ?? null : null;

  const blockList = useMemo(() => Object.values(canvas.blocks), [canvas.blocks]);
  const widgetList = useMemo(() => Object.values(canvas.hmi_widgets), [canvas.hmi_widgets]);
  const selectedBlock = selectedBlockName ? canvas.blocks[selectedBlockName] ?? null : null;

  // 布局持久化（拖拽中不写）。写 ref：收起/适配发生在 layout effect 之后。
  useEffect(() => {
    if (draggingPane || dragRef.current) return;
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layoutRef.current));
    } catch {
      /* 静默 */
    }
  }, [layout, draggingPane]);

  // 跳转定位时自动展开目标栏（磁吸收起的栏在需要时弹开）
  useEffect(() => {
    if (!focus) return;
    setLayout((l) => {
      const key = focus.kind === "network" ? "scl" : focus.kind === "hmi" ? "hmi" : null;
      if (!key || !l.collapsed[key]) return l;
      const next = { ...l, collapsed: { ...l.collapsed, [key]: false } };
      layoutRef.current = next;
      return next;
    });
  }, [focus]);

  const togglePane = (key: PaneKey) => {
    const current = layoutRef.current;
    const next = { ...current, collapsed: { ...current.collapsed, [key]: !current.collapsed[key] } };
    layoutRef.current = next;
    setLayout(next);
  };

  /** 分隔条、窄轨和内边距之外，留给展开栏的像素 */
  const measureAvailable = () => {
    const root = subpanesRef.current;
    if (!root) return 0;
    const cs = getComputedStyle(root);
    const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    let chrome = pad;
    root.querySelectorAll<HTMLElement>(".subgutter, .subpane--rail").forEach((el) => {
      chrome += outerWidth(el);
    });
    return Math.max(0, root.clientWidth - chrome);
  };

  const applyDomWidths = (widths: PaneWidths) => {
    for (const key of expandedKeys(layoutRef.current.collapsed)) {
      const el = paneRefs.current[key];
      if (!el) continue;
      const px = `${Math.round(widths[key])}px`;
      if (el.style.width !== px) el.style.width = px;
    }
  };

  /** 每次提交后把展开栏铺满中区：左缘贴历史栏，右缘贴变量栏 */
  useLayoutEffect(() => {
    if (dragRef.current) return;
    const available = measureAvailable();
    if (available <= 0) return;
    const fitted = fitPaneWidths(layoutRef.current.widths, layoutRef.current.collapsed, available);
    layoutRef.current = { ...layoutRef.current, widths: fitted };
    applyDomWidths(fitted);
  });

  /* 侧栏拖动 / 窗口变化时中区变宽，但本组件不一定重渲染：观察器直接改宽度 */
  useEffect(() => {
    const root = subpanesRef.current;
    if (!root) return;
    let timer = 0;
    const ro = new ResizeObserver(() => {
      if (dragRef.current) return;
      const available = measureAvailable();
      if (available <= 0) return;
      const fitted = fitPaneWidths(layoutRef.current.widths, layoutRef.current.collapsed, available);
      layoutRef.current = { ...layoutRef.current, widths: fitted };
      applyDomWidths(fitted);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (!dragRef.current) setLayout({ ...layoutRef.current });
      }, 90);
    });
    ro.observe(root);
    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
    };
    // 测量函数闭包只读 ref，挂载一次即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 分隔条只跟相邻栏交换宽度，不触发整页重渲染；松手低于吸附阈值则收起 */
  const beginSubDrag = (key: PaneKey, e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    if (dragRef.current) return;
    const gutter = e.currentTarget;
    e.preventDefault();
    e.stopPropagation();

    const startWidths: PaneWidths = { ...layoutRef.current.widths };
    for (const k of expandedKeys(layoutRef.current.collapsed)) {
      const el = paneRefs.current[k];
      if (el) startWidths[k] = el.offsetWidth;
    }
    layoutRef.current = { ...layoutRef.current, widths: startWidths };
    dragRef.current = { key, startX: e.clientX, startWidths, pointerId: e.pointerId };
    try {
      gutter.setPointerCapture(e.pointerId);
    } catch {
      /* 个别环境不支持 capture，监听仍挂在分隔条上 */
    }

    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    setDraggingPane(key);

    const pane = paneRefs.current[key];
    const onMove = (ev: PointerEvent) => {
      const session = dragRef.current;
      if (!session || ev.pointerId !== session.pointerId) return;
      const widths = resizePair(
        session.startWidths,
        layoutRef.current.collapsed,
        key,
        ev.clientX - session.startX,
      );
      layoutRef.current = { ...layoutRef.current, widths };
      applyDomWidths(widths);
      const snap = widths[key] < SNAP_PX;
      pane?.classList.toggle("subpane--will-snap", snap);
      gutter.classList.toggle("subgutter--snap", snap);
    };
    const finish = (ev: PointerEvent) => {
      const session = dragRef.current;
      if (session && ev.pointerId !== session.pointerId) return;
      gutter.removeEventListener("pointermove", onMove);
      gutter.removeEventListener("pointerup", finish);
      gutter.removeEventListener("pointercancel", finish);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
      pane?.classList.remove("subpane--will-snap");
      gutter.classList.remove("subgutter--snap");
      dragRef.current = null;
      if (!session) {
        setDraggingPane(null);
        return;
      }
      const latest = layoutRef.current.widths[key];
      const moved = Math.abs(latest - session.startWidths[key]) >= 6;
      let next = layoutRef.current;
      if (moved && latest < SNAP_PX) {
        next = {
          widths: { ...next.widths, [key]: Math.max(RESTORE_W, latest) },
          collapsed: { ...next.collapsed, [key]: true },
        };
      } else if (moved) {
        next = { ...next, widths: settlePair(next.widths, next.collapsed, key) };
      } else {
        next = { ...next, widths: session.startWidths };
      }
      layoutRef.current = next;
      setDraggingPane(null);
      setLayout({ ...next });
    };

    gutter.addEventListener("pointermove", onMove);
    gutter.addEventListener("pointerup", finish);
    gutter.addEventListener("pointercancel", finish);
  };

  // HMI 触摸仿真：PLC 逻辑反馈（与后端无关的本地仿真）
  const handleWidgetClick = (w: CanvasHmiWidgetData) => {
    if (w.widget_type !== "button") return;
    const nextState = !w.current_value;
    const isStart = w.id.includes("start");
    const isStop = w.id.includes("stop") || w.id.includes("estop");

    const nextWidgets = { ...canvas.hmi_widgets };
    nextWidgets[w.id] = { ...w, current_value: nextState };

    if (isStart) {
      if (nextWidgets["lamp_run"]) nextWidgets["lamp_run"].current_value = true;
      if (nextWidgets["gauge_speed"]) nextWidgets["gauge_speed"].current_value = 1450;
    } else if (isStop) {
      if (nextWidgets["lamp_run"]) nextWidgets["lamp_run"].current_value = false;
      if (nextWidgets["gauge_speed"]) nextWidgets["gauge_speed"].current_value = 0;
    }

    onCanvasChange({ ...canvas, hmi_widgets: nextWidgets });
  };

  const renderPane = (key: PaneKey, children: React.ReactNode) => {
    const collapsed = layout.collapsed[key];
    if (collapsed) {
      return (
        <div className="subpane subpane--rail" style={{ width: RAIL_W }}>
          <button
            type="button"
            className="subpane__rail-btn"
            aria-label={`展开${PANE_TITLES[key]}`}
            title={`展开${PANE_TITLES[key]}`}
            onClick={() => togglePane(key)}
          >
            <span className="subpane__rail-label">{PANE_TITLES[key]}</span>
            <ChevronRight />
          </button>
        </div>
      );
    }
    return (
      <section
        ref={(el) => {
          paneRefs.current[key] = el;
        }}
        className="subpane"
        style={{ width: layoutRef.current.widths[key], flex: "0 0 auto" }}
        aria-label={PANE_TITLES[key]}
      >
        <div className="subpane__head">
          <span className="subpane__title">{PANE_TITLES[key]}</span>
          <button
            type="button"
            className="subpane__toggle"
            aria-label={`收起${PANE_TITLES[key]}`}
            title={`收起${PANE_TITLES[key]}（拖窄也会自动吸附）`}
            onClick={() => togglePane(key)}
          >
            <ChevronLeft />
          </button>
        </div>
        <div className="subpane__body">{children}</div>
      </section>
    );
  };

  const gutter = (key: PaneKey) => (
    <div
      className={
        "subgutter" +
        (draggingPane === key ? " subgutter--active" : "") +
        (layout.widths[key] < SNAP_PX && !layout.collapsed[key] ? " subgutter--snap" : "")
      }
      role="separator"
      aria-orientation="vertical"
      aria-label={`拖拽调整${PANE_TITLES[key]}宽度，拖到很小自动吸附收起`}
      onPointerDown={(e) => beginSubDrag(key, e)}
    />
  );

  return (
    <div className={"canvas-pane" + (draggingPane ? " canvas-pane--dragging" : "")}>
      <div className="subpanes" ref={subpanesRef}>
        {renderPane(
          "graph",
          <>
            <GlobalGraph
              paneDragging={draggingPane !== null}
              blocks={blockList}
              edges={blockEdges}
              selectedBlockName={selectedBlockName}
              onSelectBlock={onSelectBlock}
              onCreateBlock={onCreateBlock}
              projectKey={canvas.project_name}
              onDrillDown={(name) => setDrillBlock(name)}
            />
            {drillBlockData && (
              <DrillDownPanel
                block={drillBlockData}
                onBack={() => setDrillBlock(null)}
                onJumpNetwork={(networkId) => {
                  onFocusChange?.({ kind: "network", blockName: drillBlockData.name, networkId });
                  setDrillBlock(null);
                }}
              />
            )}
          </>
        )}
        {!layout.collapsed.graph && gutter("graph")}

        {renderPane(
          "scl",
          <SclPane
            block={selectedBlock}
            edges={blockEdges}
            widgets={widgetList}
            tags={canvas.tags}
            focusNetworkId={focus?.kind === "network" ? focus.networkId ?? null : null}
            onAddVariable={onAddVariable}
            onAddNetwork={onAddNetwork}
            onRemoveBlock={onRemoveBlock}
            onRenameBlock={onRenameBlock}
            onRemoveVariable={onRemoveVariable}
            onRemoveNetwork={onRemoveNetwork}
            onDeepExplain={onDeepExplain}
          />
        )}
        {!layout.collapsed.scl && gutter("scl")}

        {renderPane(
          "hmi",
          <HmiPane
            widgets={widgetList}
            devices={canvas.hmi_devices || []}
            focusWidgetId={focus?.kind === "hmi" ? focus.widgetId ?? null : null}
            onWidgetClick={handleWidgetClick}
          />
        )}
      </div>
    </div>
  );
};
