import { useState } from "react";
import { ApiError, processosApi } from "./api";
import { roleDeniedText } from "./actor";
import { Badge, evidenceTone } from "./fieldui";
import type { TelemetryEvent } from "./types";

/* FC-15 — object event timeline with evidence levels. SIMULATED data must stay
   visibly flagged; manual uploads are MANUAL evidence, never OT readings. */
function EventRow({ e }: { e: TelemetryEvent }) {
  return (
    <div className={`tl-row ${e.evidence_level === "SIMULATED" ? "sim" : ""}`}>
      <span className="tl-time mono">{e.event_time}</span>
      <span className="tl-src mono">{e.source}</span>
      <Badge tone={evidenceTone(e.evidence_level)}>{e.evidence_level || "UNKNOWN"}</Badge>
      {e.quality && <Badge>{e.quality}</Badge>}
      <code className="tl-payload">{JSON.stringify(e.payload)}</code>
    </div>
  );
}

export function TelemetryPanel({ objectId }: { objectId?: string }) {
  const [oid, setOid] = useState(objectId ?? "");
  const [events, setEvents] = useState<TelemetryEvent[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ event_time: "", quality: "REPORTED", payload: "{}" });
  const [ok, setOk] = useState("");

  const load = async () => {
    const q = oid.trim();
    if (!q) return;
    setBusy(true); setErr("");
    try { setEvents((await processosApi.objectTelemetry(q)).events); }
    catch (e) { setEvents([]); setErr(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)); }
    finally { setBusy(false); }
  };

  const upload = async () => {
    const q = oid.trim();
    if (!q) { setErr("请先填写 object_id"); return; }
    let payload: Record<string, unknown>;
    try { payload = JSON.parse(form.payload || "{}") as Record<string, unknown>; }
    catch { setErr("payload 不是合法 JSON"); return; }
    setErr(""); setBusy(true);
    try {
      // evidence_level 由后端按 source 推导（MANUAL_UPLOAD -> MANUAL），前端不传
      await processosApi.ingestEvent({
        object_id: q, source: "MANUAL_UPLOAD",
        event_time: form.event_time || new Date().toISOString(),
        payload, quality: form.quality,
      });
      setOk("手工证据已登记（MANUAL）");
      setEvents((await processosApi.objectTelemetry(q)).events);
    } catch (e) {
      const denied = roleDeniedText(e);
      setErr(denied ?? (e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)));
    } finally { setBusy(false); }
  };

  return (
    <div className="tl-panel">
      <div className="obj-search">
        <input value={oid} placeholder="object_id" onChange={e => setOid(e.target.value)}
          onKeyDown={e => e.key === "Enter" && load()} />
        <button className="btn sm" onClick={load} disabled={busy}>{busy ? "加载中…" : "加载时间线"}</button>
      </div>
      {err && <div className="note" style={{ color: "var(--err)" }}>{err}</div>}
      {ok && <div className="note" style={{ color: "var(--ok)" }}>{ok}</div>}
      {events !== null && (
        <div className="tl-list">
          {events.length === 0 && <div className="hint">该对象暂无事件；可通过下方表单人工上传证据。</div>}
          {events.map(e => <EventRow key={e.event_id} e={e} />)}
        </div>
      )}
      <div className="tl-form">
        <div className="field"><label>事件时间</label>
          <input type="datetime-local" value={form.event_time} onChange={e => setForm({ ...form, event_time: e.target.value })} /></div>
        <div className="field"><label>质量位</label>
          <select value={form.quality} onChange={e => setForm({ ...form, quality: e.target.value })}>
            <option>REPORTED</option><option>GOOD</option><option>BAD</option><option>UNCERTAIN</option>
          </select></div>
        <div className="field"><label>payload（JSON）</label>
          <textarea className="tl-json" rows={3} value={form.payload} onChange={e => setForm({ ...form, payload: e.target.value })} /></div>
        <div className="ctrlrow">
          <button className="btn sm" onClick={upload} disabled={busy}>手工上报（source=MANUAL_UPLOAD）</button>
        </div>
        <div className="hint">手工上传只登记 MANUAL 证据；模拟数据必须由后端以 SIMULATED 标注进入，前端不会把模拟数据渲染成真机读数。</div>
      </div>
    </div>
  );
}
