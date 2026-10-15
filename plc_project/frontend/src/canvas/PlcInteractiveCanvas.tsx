import React, { useEffect, useMemo, useRef, useState } from "react";
import type { CanvasHmiWidgetData, CanvasStateData } from "./types";
import { GlobalGraph } from "../shell/GlobalGraph";
import { SclPane } from "../shell/SclPane";
import { HmiPane } from "../shell/HmiPane";
import { DrillDownPanel } from "../shell/DrillDownPanel";

export interface FocusTarget {
  kind: "network" | "hmi";
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
/* 三栏子面板布局：宽度可拖 + 磁吸折叠（拖过阈值松手即收起）             */
/* ------------------------------------------------------------------ */

type PaneKey = "graph" | "scl" | "hmi";

interface CenterLayout {
  widths: Record<PaneKey, number>;
  collapsed: Record<PaneKey, boolean>;
}

const PANE_TITLES: Record<PaneKey, string> = {
  graph: "全局图",
  scl: "SCL 源码",
  hmi: "HMI 仿真",
};

/** 子栏从左到右的顺序（分割拖拽与重分配依赖） */
const PANE_ORDER: PaneKey[] = ["graph", "scl", "hmi"];

const LAYOUT_KEY = "plc-copilot.centerpanes.v1";
const DEFAULT_LAYOUT: CenterLayout = {
  widths: { graph: 470, scl: 430, hmi: 340 },
  collapsed: { graph: false, scl: false, hmi: false },
};
const MIN_W = 190;
const MAX_W = 980;
const DRAG_FLOOR = 64; // 拖拽过程中允许压到的最小像素（再往下就是吸附区）
const SNAP_PX = 130; // 松手时低于该宽度 → 磁吸收起
const RAIL_W = 30;

function loadLayout(): CenterLayout {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return { ...DEFAULT_LAYOUT };
    const parsed = JSON.parse(raw) as Partial<CenterLayout>;
    const num = (v: unknown, d: number) =>
      typeof v === "number" && Number.isFinite(v) ? Math.min(MAX_W, Math.max(MIN_W, v)) : d;
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
    return { ...DEFAULT_LAYOUT };
  }
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
  const dragRef = useRef<null | { key: PaneKey; latest: number }>(null);
  /* 双击块下钻：块内网络流程图 */
  const [drillBlock, setDrillBlock] = useState<string | null>(null);
  const drillBlockData = drillBlock ? canvas.blocks[drillBlock] ?? null : null;

  const blockList = useMemo(() => Object.values(canvas.blocks), [canvas.blocks]);
  const widgetList = useMemo(() => Object.values(canvas.hmi_widgets), [canvas.hmi_widgets]);
  const selectedBlock = selectedBlockName ? canvas.blocks[selectedBlockName] ?? null : null;

  // 布局持久化（拖拽中不写）
  useEffect(() => {
    if (draggingPane) return;
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch {
      /* 静默 */
    }
  }, [layout, draggingPane]);

  // 跳转定位时自动展开目标栏（磁吸收起的栏在需要时弹开）
  useEffect(() => {
    if (!focus) return;
    if (focus.kind === "network") {
      setLayout((l) =>
        l.collapsed.scl ? { ...l, collapsed: { ...l.collapsed, scl: false } } : l
      );
    } else if (focus.kind === "hmi") {
      setLayout((l) =>
        l.collapsed.hmi ? { ...l, collapsed: { ...l.collapsed, hmi: false } } : l
      );
    }
  }, [focus]);

  const togglePane = (key: PaneKey) => {
    setLayout((l) => ({ ...l, collapsed: { ...l.collapsed, [key]: !l.collapsed[key] } }));
  };

  /** 分隔条拖拽：只调本栏宽度，其余栏由 CSS flex 按比例伸缩补偿（逐帧、无重叠）；
   *  松手低于吸附阈值 → 磁吸收起（宽度回落合法区间供展开恢复） */
  const beginSubDrag = (
    key: PaneKey,
    e: React.PointerEvent<HTMLDivElement> | React.MouseEvent<HTMLDivElement>
  ) => {
    if (e.button !== 0) return;
    if (dragRef.current) return;
    e.preventDefault();
    const startX = e.clientX;
    // 以元素当前真实渲染宽为基点（flex 可能已按比例调整过）
    const paneEl = (e.currentTarget as HTMLElement).previousElementSibling as HTMLElement | null;
    const startW = paneEl ? paneEl.getBoundingClientRect().width : layout.widths[key];
    dragRef.current = { key, latest: startW };
    setDraggingPane(key);

    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: PointerEvent | MouseEvent) => {
      const latest = Math.max(DRAG_FLOOR, startW + (ev.clientX - startX));
      if (dragRef.current) dragRef.current.latest = latest;
      setLayout((l) => ({ ...l, widths: { ...l.widths, [key]: latest } }));
    };
    const finish = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
      const latest = dragRef.current?.latest ?? startW;
      dragRef.current = null;
      setDraggingPane(null);
      setLayout((l) => {
        if (latest < SNAP_PX) {
          // 磁吸：收起为轨道
          return {
            widths: { ...l.widths, [key]: Math.max(latest, MIN_W) },
            collapsed: { ...l.collapsed, [key]: true },
          };
        }
        return { ...l, widths: { ...l.widths, [key]: Math.min(latest, MAX_W) } };
      });
    };
    const onUp = () => finish();

    window.addEventListener("pointermove", onMove);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("mouseup", onUp);
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
    const nearSnap = layout.widths[key] < SNAP_PX;
    return (
      <section
        className={"subpane" + (nearSnap && draggingPane === key ? " subpane--will-snap" : "")}
        style={{ width: layout.widths[key] }}
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
      onMouseDown={(e) => beginSubDrag(key, e)}
    />
  );

  return (
    <div className={"canvas-pane" + (draggingPane ? " canvas-pane--dragging" : "")}>
      <div className="subpanes">
        {renderPane(
          "graph",
          <>
            <GlobalGraph
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
            focusWidgetId={focus?.kind === "hmi" ? focus.widgetId ?? null : null}
            onWidgetClick={handleWidgetClick}
          />
        )}
      </div>
    </div>
  );
};
