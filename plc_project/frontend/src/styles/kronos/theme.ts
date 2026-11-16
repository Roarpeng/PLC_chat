import "./kronos.css";
import "./appearance.css";
import "./kronos.js";

export type PaperTheme = "auto" | "day" | "rubbing";

declare global {
  interface Window {
    KRONOS?: {
      init(options: { alive: string }): { destroy(): void };
      getTheme(): PaperTheme;
      setTheme(mode: PaperTheme): void;
    };
  }
}

// The upstream browser bundle exposes KRONOS on window.
const runtime = window.KRONOS?.init({ alive: ".k-btn, .wb-btn, [data-kronos-alive]" });
if (import.meta.hot) import.meta.hot.dispose(() => runtime?.destroy());
