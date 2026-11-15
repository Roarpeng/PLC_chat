import type { ReactNode } from "react";
import type { Contract, Step } from "./types";

export function Icon({ name, size = 15 }: { name: "check" | "cross" | "warn" | "arrow" | "plus" | "import" | "topo" | "back" | "doc"; size?: number }) {
  const p: Record<string, ReactNode> = {
    check: <path d="M3 8.5l3.5 3.5L13 4" />,
    cross: <path d="M4 4l8 8M12 4l-8 8" />,
    warn: <><path d="M8 2.5l6 10.5H2z" /><path d="M8 6.5v3M8 11.4v.2" /></>,
    arrow: <path d="M3 8h10M9 4l4 4-4 4" />,
    plus: <path d="M8 3v10M3 8h10" />,
    import: <><path d="M8 2v8M5 7l3 3 3-3" /><path d="M2.5 11v2.5h11V11" /></>,
    topo: <><rect x="2" y="2" width="5" height="4" /><rect x="9" y="10" width="5" height="4" /><path d="M4.5 6v2.5h8V10" /></>,
    back: <path d="M13 8H3M7 4L3 8l4 4" />,
    doc: <><path d="M4 2h6l3 3v9H4z" /><path d="M10 2v3h3M6 8h5M6 11h5" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>{p[name]}</svg>;
}

function Crosshair({ x, y }: { x: number; y: number }) {
  return <g className="ln-thin"><path d={`M${x - 7},${y}h14M${x},${y - 7}v14`} /><circle cx={x} cy={y} r="3" /></g>;
}

/* The subject's own object: a double-acting cylinder, drafted with dimensions. */
export function ClampDrawing({ animate = true }: { animate?: boolean }) {
  const d = animate ? "draw-anim" : "";
  return (
    <svg data-ui viewBox="0 0 560 330" width="100%" style={{ maxWidth: 560 }}>
      <Crosshair x={16} y={16} /><Crosshair x={544} y={16} /><Crosshair x={16} y={314} /><Crosshair x={544} y={314} />
      {/* center line */}
      <path className="ln-thin" d="M70,160 H520" strokeDasharray="10 4 2 4" />
      {/* barrel */}
      <rect className={`ln-fill ${d}`} style={{ ["--len" as string]: 700 }} x="120" y="110" width="240" height="100" />
      <rect className="ln" x="112" y="104" width="14" height="112" />
      <rect className="ln" x="354" y="104" width="14" height="112" />
      {/* piston + rod */}
      <path className="ln" d="M240,110 V210" />
      <rect className="ln-fill" x="234" y="118" width="12" height="84" />
      <rect className={`ln-fill ${d}`} style={{ ["--len" as string]: 320 }} x="368" y="150" width="120" height="20" />
      <path className="ln" d="M488,144 h12 v32 h-12 M500,150 v20" />
      {/* ports */}
      <rect className="ln" x="150" y="92" width="18" height="18" />
      <rect className="ln" x="312" y="92" width="18" height="18" />
      <path className="ln-thin" d="M159,92 V70 H120" /><text className="ln-label" x="60" y="74">Extend</text>
      <path className="ln-thin" d="M321,92 V70 H360" /><text className="ln-label" x="364" y="74">Retract</text>
      {/* feedback sensors */}
      <path className="ln-thin" d="M140,210 v18 M340,210 v18" />
      <text className="ln-label" x="118" y="244">Extended</text>
      <text className="ln-label" x="318" y="244">Retracted</text>
      {/* stroke dimension */}
      <path className="ln-dim" d="M120,278 H500" /><path className="ln-dim" d="M120,272 v12M500,272 v12" />
      <path className="ln-dim" d="M120,278 l8,-3 v6 z M500,278 l-8,-3 v6 z" fill="var(--stamp)" />
      <text className="ln-dimtext" x="280" y="272" textAnchor="middle">行程 200 mm</text>
      {/* bore dimension */}
      <path className="ln-dim" d="M96,110 V210" /><path className="ln-dim" d="M90,110 h12M90,210 h12" />
      <text className="ln-dimtext" x="84" y="165" textAnchor="middle" transform="rotate(-90 84 165)">缸径 Ø40</text>
      <text className="ln-text" x="120" y="306" style={{ fontFamily: "var(--serif)", fontWeight: 600 }}>CM_CLAMP_CYL · 双作用气缸</text>
      <text className="ln-label" x="430" y="306">比例 1:2</text>
    </svg>
  );
}

export function MiniTopo({ kind }: { kind: "new" | "import" }) {
  return (
    <svg data-ui viewBox="0 0 300 120" width="100%" height="120">
      <rect className="ln-thin" x="20" y="14" width="260" height="92" strokeDasharray="5 4" />
      <text className="ln-label" x="30" y="30">UNIT</text>
      <rect className="ln" x="40" y="42" width="90" height="48" />
      <text className="ln-label" x="50" y="60">EM</text>
      <rect className="ln-fill" x="52" y="66" width="66" height="18" />
      <rect className="ln" x="170" y="42" width="90" height="48" />
      <text className="ln-label" x="180" y="60">{kind === "import" ? "EM·解析" : "EM"}</text>
      <rect className="ln-fill" x="182" y="66" width="66" height="18" />
      <path className="ln-thin" d="M130,66 H170" />
    </svg>
  );
}

export function TopologyDrawing({ nodes }: { nodes: { id: string; kind: string; name: string }[] }) {
  const units = nodes.filter(n => n.kind === "unit");
  const ems = nodes.filter(n => n.kind === "em");
  const cms = nodes.filter(n => n.kind === "cm");
  return (
    <svg data-ui viewBox="0 0 640 400" width="100%" style={{ maxWidth: 640 }}>
      <Crosshair x={14} y={14} /><Crosshair x={626} y={14} /><Crosshair x={14} y={386} /><Crosshair x={626} y={386} />
      <rect className="ln-thin" x="30" y="30" width="580" height="340" strokeDasharray="6 4" />
      <text className="ln-label" x="44" y="50">硬件拓扑 · UNIT {units[0]?.id ?? "U_ASSEMBLY"}</text>
      {ems.length === 0 && cms.length === 0 && <text className="ln-label" x="320" y="200" textAnchor="middle">从右侧添加 EM / CM，拓扑将在此绘制</text>}
      {ems.map((em, i) => {
        const x = 60 + (i % 2) * 290, y = 80 + Math.floor(i / 2) * 150;
        return <g key={em.id}>
          <rect className="ln-fill" x={x} y={y} width="250" height="120" />
          <text className="ln-text" x={x + 14} y={y + 24}>{em.name}</text>
          <text className="ln-label" x={x + 14} y={y + 42}>{em.id} · EM</text>
          {cms.filter(c => (c as { parent?: string }).parent === em.id).map((cm, j) => (
            <g key={cm.id}><rect className="ln" x={x + 14} y={y + 54 + j * 26} width="220" height="22" /><text className="ln-label" x={x + 24} y={y + 69 + j * 26}>{cm.id} · {cm.name}</text></g>
          ))}
        </g>;
      })}
    </svg>
  );
}

export function Sfc({ steps, sel, onSelect, showGuards = true, showTimeout = true, showGrid = true }: {
  steps: Step[]; sel: string; onSelect: (id: string) => void; showGuards?: boolean; showTimeout?: boolean; showGrid?: boolean;
}) {
  const main = steps.filter(s => !s.is_fault);
  const fault = steps.find(s => s.is_fault);
  const X = 70, W = 252, H = 62, GAP = 104, top = 30;
  const y = (i: number) => top + i * GAP;
  const height = top + main.length * GAP + 30;
  const fx = 410, fw = 210, fy = y(1);
  return (
    <svg data-ui viewBox={`0 0 660 ${height}`} width="660" height={height}>
      <defs>
        <pattern id="sfcgrid" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.9" fill="var(--line)" /></pattern>
        <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="var(--line3)" /></marker>
        <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="var(--err)" /></marker>
        <marker id="arg" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="var(--ok)" /></marker>
      </defs>
      {showGrid && <rect x="0" y="0" width="660" height={height} fill="url(#sfcgrid)" />}
      {main.map((s, i) => {
        const yy = y(i);
        const meta = [s.duration_ms ? `保持 ${s.duration_ms / 1000}s` : "", s.timeout_ms ? `超时 ${s.timeout_ms / 1000}s` : ""].filter(Boolean).join(" · ");
        return (
          <g key={s.id}>
            {i < main.length - 1 && <>
              <line className="sfc-line" x1={X + W / 2} y1={yy + H} x2={X + W / 2} y2={y(i + 1)} markerEnd="url(#ar)" />
              <line className="sfc-line" x1={X + W / 2 - 16} y1={yy + H + (GAP - H) / 2} x2={X + W / 2 + 16} y2={yy + H + (GAP - H) / 2} strokeWidth={2.5} />
              {showGuards && <text className="sfc-guard" x={X + W / 2 + 24} y={yy + H + (GAP - H) / 2 + 4}>{s.guard || (s.duration_ms ? `t≥${s.duration_ms / 1000}s` : "TRUE")}</text>}
            </>}
            {showTimeout && s.timeout_ms && fault && <>
              <path className="sfc-timeout" d={`M${X + W},${yy + H / 2} L${fx - 20},${yy + H / 2} L${fx - 20},${fy + 30} L${fx},${fy + 30}`} markerEnd="url(#arr)" />
              <text className="sfc-guard" x={fx - 26} y={yy + H / 2 - 6} textAnchor="end" fill="var(--err)">{s.timeout_ms / 1000}s</text>
            </>}
            <g className={`sfc-node ${sel === s.id ? "sel" : ""}`} onClick={() => onSelect(s.id)}>
              <rect className="sfc-box" x={X} y={yy} width={W} height={H} rx={2} />
              <text className="sfc-title" x={X + 16} y={yy + 25}>{s.name}</text>
              <text className="sfc-id" x={X + W - 14} y={yy + 25} textAnchor="end">{s.id}</text>
              {meta && <text className="sfc-meta" x={X + 16} y={yy + 45}>{meta}</text>}
            </g>
          </g>
        );
      })}
      {fault && <>
        {showTimeout && <path className="sfc-reset" d={`M${fx + fw / 2},${fy + 62} L${fx + fw / 2},${y(main.length - 1) + H + 26} L34,${y(main.length - 1) + H + 26} L34,${y(0) + H / 2} L${X},${y(0) + H / 2}`} markerEnd="url(#arg)" />}
        {showGuards && <text className="sfc-guard" x={fx + fw / 2 - 6} y={y(main.length - 1) + H + 20} textAnchor="end" fill="var(--ok)">复位 → {fault.next}</text>}
        <g className={`sfc-node fault ${sel === fault.id ? "sel" : ""}`} onClick={() => onSelect(fault.id)}>
          <rect className="sfc-box" x={fx} y={fy} width={fw} height={62} rx={2} />
          <text className="sfc-title" x={fx + 16} y={fy + 25} fill="var(--err)">{fault.name}</text>
          <text className="sfc-id" x={fx + fw - 14} y={fy + 25} textAnchor="end">{fault.id}</text>
          <text className="sfc-meta" x={fx + 16} y={fy + 45}>命令清零 · 锁存</text>
        </g>
      </>}
    </svg>
  );
}

export function DeviceView({ contract }: { contract: Contract }) {
  const op = contract.operations[0];
  const res = contract.resources[0];
  return (
    <svg data-ui viewBox="0 0 660 380" width="660" height="380">
      <rect x="14" y="14" width="632" height="352" rx={2} fill="var(--sheet)" stroke="var(--verified)" strokeDasharray="6 4" strokeWidth="1.3" />
      <text x="32" y="42" fill="var(--verified)" style={{ font: "600 14px var(--sans)" }}>{contract.unit} · 装配工站</text>
      <text x="32" y="60" fill="var(--faint)" style={{ font: "11px var(--sans)" }}>Unit · 模式 / 状态 / 许可由 AF 基线管理</text>
      <rect x="60" y="84" width="540" height="250" rx={2} fill="var(--sheet2)" stroke="var(--ink)" strokeWidth="1.4" />
      <text x="80" y="112" fill="var(--ink)" style={{ font: "600 14px var(--sans)" }}>{op?.em} · {op?.name}</text>
      <text x="80" y="130" fill="var(--faint)" style={{ font: "11px var(--mono)" }}>EM · {op?.steps.length} steps · Sequence</text>
      <line x1="330" y1="140" x2="330" y2="164" stroke="var(--line3)" strokeWidth="1.4" />
      <rect x="120" y="164" width="420" height="150" rx={2} fill="var(--sheet)" stroke="var(--ink)" strokeWidth="1.4" />
      <text x="140" y="192" fill="var(--ink)" style={{ font: "600 13px var(--sans)" }}>{res?.name}</text>
      <text x="140" y="210" fill="var(--faint)" style={{ font: "11px var(--mono)" }}>{res?.id} · CM · LBC 待 G0 验证</text>
      <text x="140" y="240" fill="var(--faint)" style={{ font: "11px var(--sans)" }}>命令</text>
      {res?.commands.map((c, i) => <g key={c}><circle cx="150" cy={258 + i * 22} r="4" fill="var(--ink)" /><text x="162" y={262 + i * 22} fill="var(--ink)" style={{ font: "12px var(--mono)" }}>{c}</text></g>)}
      <text x="520" y="240" fill="var(--faint)" style={{ font: "11px var(--sans)" }} textAnchor="end">反馈</text>
      {res?.feedback.map((f, i) => <g key={f}><circle cx="510" cy={258 + i * 22} r="4" fill="var(--warn)" /><text x="498" y={262 + i * 22} fill="var(--ink)" style={{ font: "12px var(--mono)" }} textAnchor="end">{f}</text><text x="498" y={274 + i * 22} fill="var(--warn)" style={{ font: "9px var(--mono)" }} textAnchor="end">unbound</text></g>)}
    </svg>
  );
}

export function highlight(code: string) {
  const esc = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc
    .replace(/\b(FUNCTION_BLOCK|END_FUNCTION_BLOCK|ORGANIZATION_BLOCK|END_ORGANIZATION_BLOCK|VAR_INPUT|VAR_OUTPUT|VAR_TEMP|VAR|END_VAR|BEGIN|CASE|END_CASE|IF|THEN|ELSE|END_IF|AND|OR|NOT|TRUE|FALSE|DATA_BLOCK|END_DATA_BLOCK)\b/g, '<span class="kw">$1</span>')
    .replace(/(\/\/[^\n]*)/g, '<span class="cm">$1</span>')
    .replace(/(T#\d+ms)/g, '<span class="num">$1</span>');
}

export function CodeView({ files, file, onFile }: { files: Record<string, string>; file: string; onFile: (f: string) => void }) {
  return (
    <div data-ui>
      <div className="filetabs">{Object.keys(files).map(f => <button key={f} className={`filetab ${file === f ? "on" : ""}`} onClick={() => onFile(f)}>{f}</button>)}</div>
      <div className="codeview" dangerouslySetInnerHTML={{ __html: highlight(files[file] || "// 生成中…") }} />
    </div>
  );
}

export function TraceView({ results }: { results: { scenario_id: string; passed: boolean; fault_reason: string; reached: string[] }[] }) {
  return (
    <div data-ui style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {results.map(r => (
        <div key={r.scenario_id} style={{ border: "1px solid var(--line2)", background: "var(--sheet)", padding: "12px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <span style={{ fontWeight: 600 }}>{r.scenario_id}</span>
            <span style={{ fontSize: 12, padding: "1px 8px", border: "1px solid", borderColor: r.passed ? "var(--ok)" : "var(--err)", color: r.passed ? "var(--ok)" : "var(--err)" }}>{r.passed ? "PASS" : "FAIL"}</span>
            {r.fault_reason && <span style={{ fontSize: 12, color: "var(--err)" }}>{r.fault_reason}</span>}
          </div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>{r.reached.join(" → ")}</div>
        </div>
      ))}
    </div>
  );
}
