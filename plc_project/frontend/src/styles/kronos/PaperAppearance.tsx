import React, { useState } from "react";
import type { PaperTheme } from "./theme";

export function PaperAppearance() {
  const [theme, setTheme] = useState<PaperTheme>(
    () => typeof window === "undefined" ? "auto" : window.KRONOS?.getTheme() ?? "auto",
  );
  return (
    <label className="paper-appearance">
      <span>外观</span>
      <select
        aria-label="外观"
        value={theme}
        onChange={(event) => {
          const mode = event.target.value as PaperTheme;
          window.KRONOS?.setTheme(mode);
          setTheme(mode);
        }}
      >
        <option value="auto">跟随系统</option>
        <option value="day">宣纸</option>
        <option value="rubbing">墨拓</option>
      </select>
    </label>
  );
}
