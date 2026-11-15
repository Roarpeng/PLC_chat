import { useRef, useState } from "react";
import { processosApi } from "./api";
import { buildContract } from "./store";
import { Icon } from "./views";

interface PNode { id: string; kind: string; name: string; fid: "EXACT" | "PARTIAL" | "OPAQUE" | "PROTECTED"; note: string }
const PARSED: PNode[] = [
  { id: "U_ASSEMBLY", kind: "UNIT", name: "装配工站", fid: "EXACT", note: "模式/状态结构可重建" },
  { id: "EM_CLAMP", kind: "EM", name: "夹紧单元", fid: "EXACT", note: "Job/Sequence 调用链清晰" },
  { id: "CM_CLAMP_CYL", kind: "CM", name: "夹紧气缸", fid: "PARTIAL", note: "反馈互锁分支未完全覆盖" },
  { id: "FB_Sequence", kind: "FB", name: "步序功能块", fid: "EXACT", note: "6 步 · 含超时出口" },
  { id: "OB_Main", kind: "OB", name: "主循环", fid: "PARTIAL", note: "间接调用，调用序需核对" },
  { id: "DB_Recipe", kind: "DB", name: "配方数据块", fid: "OPAQUE", note: "结构不完整，仅提取元数据" },
  { id: "F_SafetyGate", kind: "FB", name: "安全门联锁", fid: "PROTECTED", note: "F-block · 强制只读，零修改" },
];

export function ImportView({ onCancel, onDone }: { onCancel: () => void; onDone: (name: string, contractId: string) => void }) {
  const [file, setFile] = useState("");
  const [progress, setProgress] = useState(0);
  const [parsed, setParsed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const startParse = (name: string) => {
    setFile(name); setParsed(false); setProgress(0);
    let p = 0;
    const t = setInterval(() => {
      p += Math.random() * 22 + 8;
      if (p >= 100) { p = 100; clearInterval(t); setParsed(true); }
      setProgress(Math.min(100, Math.round(p)));
    }, 220);
  };

  const create = async () => {
    setBusy(true); setErr("");
    try {
      const contractId = "PRJ_IMP_" + Math.random().toString(36).slice(2, 7).toUpperCase();
      await processosApi.createProject(buildContract(contractId, "夹紧循环（重建）"));
      onDone(file.replace(/\.(zap19|ap19|zip)$/i, "") || "导入项目", contractId);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };

  return (
    <div className="flow">
      <div className="flow-top">
        <button className="back" onClick={onCancel}><Icon name="back" /> 返回</button>
        <h2>导入旧项目</h2>
        <div className="sp" />
        <span className="hint">工艺考古 + 清洁重建 · 原件只读</span>
      </div>

      <div className="flow-body">
        {!file && (
          <div className={`dropzone ${over ? "over" : ""}`} onClick={() => inputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={e => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) startParse(f.name); }}>
            <div className="dz-ic">⌗</div>
            <h3>拖入原生工程归档</h3>
            <p>.zap19 / .ap19 / .zip · 或点击选择文件</p>
            <input ref={inputRef} type="file" accept=".zap19,.ap19,.zip" style={{ display: "none" }}
              onChange={e => { const f = e.target.files?.[0]; if (f) startParse(f.name); }} />
          </div>
        )}

        {file && !parsed && (
          <div className="panel">
            <div className="panel-h">解析中 · {file}</div>
            <div className="panel-b">
              <div className="parsebar"><i style={{ width: progress + "%" }} /></div>
              <div className="hint">只读提取软件树 / 接口 / 调用图 / 标签 · 推断绑定源块并标注保真等级 · {progress}%</div>
            </div>
          </div>
        )}

        {parsed && (
          <>
            <div className="panel">
              <div className="panel-h">解析结果 · {file}<span className="sp" /><span className="hint">{PARSED.length} 个对象 · 原件 SHA256 未变</span></div>
              <div className="panel-b">
                <div className="nodegrid">
                  {PARSED.map(n => (
                    <div className="nodecard" key={n.id}>
                      <div className="nc-top"><span className="nc-tag">{n.kind}</span><span className="nc-name">{n.name}</span><span className={`fid ${n.fid}`}>{n.fid}</span></div>
                      <div className="nc-meta">{n.id} · {n.note}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="panel">
              <div className="panel-h">重建逻辑摘要</div>
              <div className="panel-b">
                <table className="ctable" data-ui>
                  <thead><tr><th>来源块</th><th>重建为</th><th>保真</th></tr></thead>
                  <tbody>
                    <tr><td>FB_Sequence</td><td>EM_CLAMP · Sequence（等待→伸出→保持→缩回→完成→故障）</td><td><span className="fid EXACT">EXACT</span></td></tr>
                    <tr><td>CM_ClampCyl</td><td>CM_CLAMP_CYL · 命令 Extend/Retract · 反馈 unbound</td><td><span className="fid PARTIAL">PARTIAL</span></td></tr>
                    <tr><td>F_SafetyGate</td><td>外部安全约束（不重建安全功能）</td><td><span className="fid PROTECTED">PROTECTED</span></td></tr>
                  </tbody>
                </table>
                <div className="note warn" style={{ marginTop: 12 }}>PARTIAL/OPAQUE 不声称行为等价；PROTECTED 零修改。重建为清洁 AF 契约后可在副本中编译，原件永不改写。</div>
                {err && <div className="note" style={{ marginTop: 12, color: "var(--err)" }}>{err}</div>}
              </div>
            </div>
            <div className="flow-foot">
              <button className="btn ghost" onClick={() => { setFile(""); setParsed(false); }}>重新选择</button>
              <button className="btn stamp" onClick={create} disabled={busy}>{busy ? "建立中…" : "建立项目并进入对话"} <Icon name="arrow" /></button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
