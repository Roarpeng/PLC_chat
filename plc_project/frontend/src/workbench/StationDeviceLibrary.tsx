import React, { useState } from "react";
import type { DeviceProfile } from "./stationDesign";

export function StationDeviceLibrary({ catalog, onAdd }: { catalog: DeviceProfile[]; onAdd: (item: DeviceProfile) => void }) {
  const [expanded, setExpanded] = useState(true);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const categories = [...new Set(catalog.map((item) => item.category))];
  const keyword = query.trim().toLowerCase();
  const matches = catalog.filter((item) => (!category || item.category === category) &&
    [item.label, item.interface, ...item.aliases].some((text) => text.toLowerCase().includes(keyword)));
  return <div className="af-device-library">
    <div className="af-section-head">
      <h3>添加设备</h3>
      <button type="button" className="k-btn k-btn--sm" aria-expanded={expanded} aria-controls="af-device-library-results"
        onClick={() => setExpanded(!expanded)}>{expanded ? "收起设备库" : "展开设备库"}</button>
    </div>
    {expanded && <div id="af-device-library-results">
      <label className="af-device-search">搜索设备<input type="search" value={query} placeholder="气缸、伺服、电动夹爪、光电…"
        onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="af-category-bar" aria-label="设备类别">
        {["", ...categories].map((item) => <button type="button" key={item} className="k-btn k-btn--sm"
          aria-pressed={item === category} onClick={() => setCategory(item)}>{item || "全部"}</button>)}
      </div>
      {!matches.length && <p className="k-hatch">{catalog.length ? "没有匹配的设备。" : "正在读取设备库。"}</p>}
      <div role="list" className="af-catalog-grid">
        {matches.map((entry) => <article role="listitem" className="af-catalog-item" key={entry.id}>
          <div className="af-catalog-head">
            <h4>{entry.label}</h4>
            <span className={entry.supported ? "af-ready" : "af-pending"}>{entry.supported ? "支持 AF 生成" : "待配套驱动"}</span>
          </div>
          <p>{entry.interface}</p>
          {entry.actions.length > 0 && <p className="af-catalog-actions">{entry.actions.map((action) => action.label).join(" · ")}</p>}
          <button type="button" className="k-btn k-btn--sm" aria-label={"添加" + entry.label} onClick={() => onAdd(entry)}>添加</button>
        </article>)}
      </div>
    </div>}
  </div>;
}
