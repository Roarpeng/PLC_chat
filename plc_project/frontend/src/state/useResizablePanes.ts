import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";

/** 三栏布局状态：宽度(px) + 左右开合；center 由 flex 占余 */
export interface PanesState {
  leftWidth: number;
  rightWidth: number;
  leftOpen: boolean;
  rightOpen: boolean;
}

const LEFT_MIN = 200;
const LEFT_MAX = 460;
const RIGHT_MIN = 280;
const RIGHT_MAX = 600;

const DEFAULT_STATE: PanesState = {
  leftWidth: 264,
  rightWidth: 336,
  leftOpen: true,
  rightOpen: true,
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** 带防护读取持久化布局；损坏 / 缺失回退默认值，宽度越界时收敛到合法区间 */
function readStoredState(storageKey: string): PanesState {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return { ...DEFAULT_STATE };
    const parsed = JSON.parse(raw) as Partial<PanesState> | null;
    if (!parsed || typeof parsed !== "object") return { ...DEFAULT_STATE };
    const leftWidth =
      typeof parsed.leftWidth === "number" && Number.isFinite(parsed.leftWidth)
        ? clamp(parsed.leftWidth, LEFT_MIN, LEFT_MAX)
        : DEFAULT_STATE.leftWidth;
    const rightWidth =
      typeof parsed.rightWidth === "number" && Number.isFinite(parsed.rightWidth)
        ? clamp(parsed.rightWidth, RIGHT_MIN, RIGHT_MAX)
        : DEFAULT_STATE.rightWidth;
    return {
      leftWidth,
      rightWidth,
      leftOpen: typeof parsed.leftOpen === "boolean" ? parsed.leftOpen : true,
      rightOpen: typeof parsed.rightOpen === "boolean" ? parsed.rightOpen : true,
    };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

/**
 * 三栏拖拽布局 hook。
 * - 拖拽分隔条实时更新宽度（left [200,460]，right [280,600]，center flex 占余）。
 * - 宽度 + 开合状态持久化到 localStorage（同一 storageKey），pointerup / toggle 时写入。
 * - 拖拽期间 body 设 cursor: col-resize 与 user-select: none，结束后还原。
 */
export function useResizablePanes(storageKey: string): {
  state: PanesState;
  toggleLeft(): void;
  toggleRight(): void;
  beginDrag(
    side: "left" | "right",
    e: React.PointerEvent<HTMLDivElement> | React.MouseEvent<HTMLDivElement>,
  ): void;
  isDragging: boolean;
} {
  const [state, setState] = useState<PanesState>(() => readStoredState(storageKey));
  const [isDragging, setIsDragging] = useState(false);

  /** 同步镜像：pointerup 时立即拿到最终宽度持久化，不等 React 提交 */
  const stateRef = useRef<PanesState>(state);
  const teardownRef = useRef<(() => void) | null>(null);
  /** 手势防重入：pointerdown 后到达的 mousedown（或反之）不重复启动拖拽 */
  const draggingRef = useRef(false);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  // 卸载保险：拖拽中途卸载时移除 window 监听并还原 body 样式
  useEffect(() => {
    return () => {
      teardownRef.current?.();
      teardownRef.current = null;
    };
  }, []);

  const persist = useCallback(
    (next: PanesState) => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* 静默：隐私模式 / 配额满 */
      }
    },
    [storageKey],
  );

  const apply = useCallback(
    (next: PanesState, persistNow: boolean) => {
      stateRef.current = next;
      setState(next);
      if (persistNow) persist(next);
    },
    [persist],
  );

  /** 只切 leftOpen；false 时 App 层把宽度渲染为 0 */
  const toggleLeft = useCallback(() => {
    const current = stateRef.current;
    apply({ ...current, leftOpen: !current.leftOpen }, true);
  }, [apply]);

  /** 只切 rightOpen；false 时 App 层把宽度渲染为 0 */
  const toggleRight = useCallback(() => {
    const current = stateRef.current;
    apply({ ...current, rightOpen: !current.rightOpen }, true);
  }, [apply]);

  /** 在分隔条按下时调用（pointerdown 优先；仅合成 mouse 事件的环境走 mousedown 兜底）：
   *  接管 window pointermove/pointerup（兼容 mouse 事件）完成拖拽 */
  const beginDrag = useCallback(
    (
      side: "left" | "right",
      e: React.PointerEvent<HTMLDivElement> | React.MouseEvent<HTMLDivElement>,
    ) => {
      if (e.button !== 0) return; // 仅主键拖拽
      if (draggingRef.current) return; // 同一手势已由另一种事件启动
      e.preventDefault();
      draggingRef.current = true;
      teardownRef.current?.(); // 正常不应有残留，防御性收尾

      const startX = e.clientX;
      const startWidth =
        side === "left" ? stateRef.current.leftWidth : stateRef.current.rightWidth;

      const prevCursor = document.body.style.cursor;
      const prevUserSelect = document.body.style.userSelect;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      setIsDragging(true);

      const onMove = (ev: PointerEvent | MouseEvent) => {
        const delta = ev.clientX - startX;
        const current = stateRef.current;
        if (side === "left") {
          apply(
            { ...current, leftWidth: clamp(startWidth + delta, LEFT_MIN, LEFT_MAX) },
            false,
          );
        } else {
          apply(
            { ...current, rightWidth: clamp(startWidth - delta, RIGHT_MIN, RIGHT_MAX) },
            false,
          );
        }
      };

      const finish = (commit: boolean) => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("pointerup", onPointerUp);
        window.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = prevCursor;
        document.body.style.userSelect = prevUserSelect;
        teardownRef.current = null;
        draggingRef.current = false;
        setIsDragging(false);
        if (commit) persist(stateRef.current); // 拖拽结束时持久化最终宽度
      };

      const onPointerUp = () => finish(true);
      const onMouseUp = () => finish(true);

      window.addEventListener("pointermove", onMove);
      window.addEventListener("mousemove", onMove);
      window.addEventListener("pointerup", onPointerUp);
      window.addEventListener("mouseup", onMouseUp);
      teardownRef.current = () => finish(false);
    },
    [apply, persist],
  );

  return { state, toggleLeft, toggleRight, beginDrag, isDragging };
}
