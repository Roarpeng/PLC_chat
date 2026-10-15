/**
 * ResizeObserver 环境兜底 shim。
 *
 * 部分嵌入式浏览器（IAB/CEF 衍生）的 ResizeObserver 回调从不触发：
 * React Flow 等库依赖它测量容器，失效时表现为"节点可见、连线/小地图为 0×0"。
 * 本模块在应用渲染前做一次探针检测；原生失效时以
 * "window.resize + 定时轮询 offsetWidth/Height" 实现的等价物替换。
 * 真实浏览器（Chrome/Edge）探针通过，零副作用。
 */

type ROCallback = (
  entries: { target: Element; contentRect: DOMRectReadOnly }[],
  observer: ResizeObserver,
) => void;

class PollingResizeObserver implements ResizeObserver {
  private callback: ROCallback;
  private targets = new Map<Element, { w: number; h: number }>();
  private timer: number | null = null;
  private onWinResize = () => this.tick();

  constructor(callback: ROCallback) {
    this.callback = callback;
  }

  observe(target: Element): void {
    const el = target as HTMLElement;
    this.targets.set(target, { w: el.offsetWidth, h: el.offsetHeight });
    this.ensureTimer();
    // observe 后立即回报一次（对齐原生语义）
    this.report(target, el.offsetWidth, el.offsetHeight);
  }

  unobserve(target: Element): void {
    this.targets.delete(target);
    this.maybeStop();
  }

  disconnect(): void {
    this.targets.clear();
    this.maybeStop();
  }

  private ensureTimer(): void {
    if (this.timer != null) return;
    window.addEventListener("resize", this.onWinResize);
    // 120ms：拖拽调栏时内容重排跟手（观察目标少，开销可忽略）
    this.timer = window.setInterval(() => this.tick(), 120);
  }

  private maybeStop(): void {
    if (this.targets.size > 0 || this.timer == null) return;
    window.clearInterval(this.timer);
    window.removeEventListener("resize", this.onWinResize);
    this.timer = null;
  }

  private tick(): void {
    for (const [target, prev] of [...this.targets]) {
      const el = target as HTMLElement;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      if (w !== prev.w || h !== prev.h) {
        this.targets.set(target, { w, h });
        this.report(target, w, h);
      }
    }
  }

  private report(target: Element, w: number, h: number): void {
    const rect = { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h, toJSON: () => ({}) };
    try {
      this.callback([{ target, contentRect: rect as unknown as DOMRectReadOnly }], this as unknown as ResizeObserver);
    } catch {
      /* 回调异常不致命 */
    }
  }
}

/** 探针：原生 ResizeObserver 是否真的会回调（约 60ms 判定） */
async function nativeResizeObserverWorks(): Promise<boolean> {
  if (typeof ResizeObserver === "undefined") return false;
  return new Promise<boolean>((resolve) => {
    let settled = false;
    const done = (ok: boolean) => {
      if (settled) return;
      settled = true;
      ro.disconnect();
      probe.remove();
      resolve(ok);
    };
    const probe = document.createElement("div");
    probe.style.cssText = "position:fixed;left:-9999px;top:0;width:10px;height:10px";
    document.body.appendChild(probe);
    const ro = new ResizeObserver(() => done(true));
    ro.observe(probe);
    setTimeout(() => done(false), 60);
  });
}

/** 在应用渲染前调用：原生失效则替换为轮询实现 */
export async function ensureResizeObserver(): Promise<void> {
  const works = await nativeResizeObserverWorks();
  if (!works) {
    // eslint-disable-next-line no-console
    console.warn("[shim] 原生 ResizeObserver 未回调，启用轮询兜底实现");
    (window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
      PollingResizeObserver as unknown as typeof ResizeObserver;
  }
}
