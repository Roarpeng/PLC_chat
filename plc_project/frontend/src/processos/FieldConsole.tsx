import { useCallback, useEffect, useState } from "react";
import { ApiError, processosApi } from "./api";
import { roleDeniedText } from "./actor";
import { Badge, FieldTop, useFlash, type FieldView } from "./fieldui";
import type { Incident, ObjectContext, ProjectSummary, RbacAuditEntry, RbacRoleMatrix } from "./types";
import { Icon } from "./views";

/* PLAN §3 — three field entrances: by station/device, by alarm code, by change
   set / project. QR codes are an ENTRY, never an authorization credential. */
function incidentMatchesAlarm(i: Incident, q: string): boolean {
  const needle = q.toUpperCase();
  const a = i.alarm ?? {};
  return [a.code, a.definition_id].some(v => String(v ?? "").toUpperCase().includes(needle));
}
function incidentChangeSets(i: Incident): string[] {
  const ids = (i.references as { change_set_ids?: unknown } | undefined)?.change_set_ids;
  return Array.isArray(ids) ? ids.map(String) : [];
}

/** 「查看工位画布」入口（无 hooks，可直接函数调用测试点击回调）。 */
export function OpenCanvasButton({ path, onOpen }: { path: string; onOpen: (physicalPath: string) => void }) {
  return (
    <button className="btn sm" data-testid="fc-open-canvas" onClick={() => onOpen(path)}
      title="按物理路径首段（工位）打开工位画布">
      查看工位画布 <Icon name="topo" size={12} />
    </button>
  );
}

function ContextCard({ ctx, onOpenCanvas }: { ctx: ObjectContext; onOpenCanvas?: (physicalPath: string) => void }) {
  return (
    <div className="obj-result" data-testid="obj-context">
      <div className="or-name">{ctx.display_name} <span className="mono or-id">{ctx.object_id}</span></div>
      <div className="or-path">{ctx.physical_path}</div>
      <div className="or-af">{Object.entries(ctx.af).map(([k, v]) => `${k}:${v}`).join(" · ") || "AF：UNKNOWN"}</div>
      <div className="or-meta">
        {ctx.source_map.length > 0
          ? <>源码映射 {ctx.source_map.length} 条 · {ctx.source_map[0].block_name}</>
          : <Badge tone="unknown">UNKNOWN · 无源码映射</Badge>}
      </div>
      <div className="or-meta">
        {ctx.alarm_definitions.length > 0
          ? ctx.alarm_definitions.slice(0, 4).map(a => <Badge key={a.definition_id} tone="warn" title={a.description}>{a.code}</Badge>)
          : <span className="hint">无关联报警定义</span>}
      </div>
      {onOpenCanvas && ctx.physical_path && <OpenCanvasButton path={ctx.physical_path} onOpen={onOpenCanvas} />}
    </div>
  );
}

export function FieldConsole({ onBack, onNav, onOpenIncident, onOpenStationByPath }: {
  onBack: () => void; onNav: (v: FieldView) => void; onOpenIncident: (incidentId: string) => void;
  onOpenStationByPath?: (physicalPath: string) => void;
}) {
  const { flash, toastEl } = useFlash();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [matrix, setMatrix] = useState<RbacRoleMatrix | null>(null);
  const [audit, setAudit] = useState<RbacAuditEntry[]>([]);

  // ① station / device name -> object context
  const [objName, setObjName] = useState("");
  const [objCtx, setObjCtx] = useState<ObjectContext | null>(null);
  const [objBusy, setObjBusy] = useState(false);
  // ② alarm code -> matching incidents
  const [alarmCode, setAlarmCode] = useState("");
  const [alarmHits, setAlarmHits] = useState<Incident[] | null>(null);
  // ③ change set / project
  const [changeQ, setChangeQ] = useState("");
  const [changeIncidents, setChangeIncidents] = useState<Incident[]>([]);
  const [changeProjects, setChangeProjects] = useState<ProjectSummary[]>([]);
  const [changeDone, setChangeDone] = useState(false);

  useEffect(() => {
    processosApi.projects().then(r => setProjects(r.projects)).catch(() => setProjects([]));
    processosApi.rbacRoles().then(r => setMatrix(r)).catch(() => setMatrix(null));
    processosApi.rbacAudit({ limit: 20 }).then(r => setAudit(r.entries)).catch(() => setAudit([]));
  }, []);

  const searchObject = useCallback(async () => {
    const q = objName.trim();
    if (!q) return;
    setObjBusy(true); setObjCtx(null);
    try {
      const obj = await processosApi.findObject(q);
      setObjCtx(await processosApi.objectContext(obj.object_id));
    } catch (e) {
      if (roleDeniedText(e)) flash(roleDeniedText(e)!, true);
      else flash(e instanceof ApiError ? `${e.status}: ${e.message}` : "未找到对象：" + q, true);
    } finally { setObjBusy(false); }
  }, [objName, flash]);

  const searchAlarm = useCallback(async () => {
    const q = alarmCode.trim();
    if (!q) return;
    try {
      const r = await processosApi.incidents();
      setAlarmHits(r.incidents.filter(i => incidentMatchesAlarm(i, q)));
    } catch (e) {
      if (roleDeniedText(e)) flash(roleDeniedText(e)!, true);
      else setAlarmHits([]);
    }
  }, [alarmCode, flash]);

  const searchChange = useCallback(() => {
    const q = changeQ.trim();
    if (!q) { setChangeDone(false); setChangeIncidents([]); setChangeProjects([]); return; }
    const needle = q.toUpperCase();
    setChangeProjects(projects.filter(p =>
      p.project_id.toUpperCase().includes(needle) || p.name.toUpperCase().includes(needle)));
    processosApi.incidents()
      .then(r => setChangeIncidents(r.incidents.filter(i => incidentChangeSets(i).some(c => c.toUpperCase().includes(needle)))))
      .catch(() => setChangeIncidents([]))
      .finally(() => setChangeDone(true));
  }, [changeQ, projects]);

  return (
    <div className="flow">
      <FieldTop view="field" onNav={onNav} onBack={onBack} title="现场入口"
        hint="按工位找设备 · 按报警找逻辑 · 按变更单找工程" />
      <div className="flow-body fc-body">
        <div className="note">二维码只是入口，不是授权凭证：扫描或输入后仍须按角色权限与现场流程逐项授权。</div>

        <div className="fc-grid">
          <section className="panel fc-card">
            <div className="panel-h"><Icon name="topo" size={14} /> ① 按工位找设备</div>
            <div className="panel-b">
              <div className="obj-search">
                <input value={objName} placeholder="工位 / 设备 / 组件名，如 夹紧气缸 A"
                  onChange={e => setObjName(e.target.value)} onKeyDown={e => e.key === "Enter" && searchObject()} />
                <button className="btn sm" onClick={searchObject} disabled={objBusy}>{objBusy ? "定位中…" : "定位"}</button>
              </div>
              {objCtx && <ContextCard ctx={objCtx} onOpenCanvas={onOpenStationByPath} />}
              {!objCtx && <div className="hint">定位后显示物理位置、AF 组织、源码映射与报警定义（按发生时的部署版本解析）。</div>}
            </div>
          </section>

          <section className="panel fc-card">
            <div className="panel-h"><Icon name="warn" size={14} /> ② 按报警找逻辑</div>
            <div className="panel-b">
              <div className="obj-search">
                <input value={alarmCode} placeholder="报警代码，如 CM_MOTION_TIMEOUT"
                  onChange={e => setAlarmCode(e.target.value)} onKeyDown={e => e.key === "Enter" && searchAlarm()} />
                <button className="btn sm" onClick={searchAlarm}>查找</button>
              </div>
              {alarmHits === null && <div className="hint">输入报警代码，列出相关问题单并跳转其排查路径（报警定位 ≠ 根因证明）。</div>}
              {alarmHits?.length === 0 && <div className="hint">没有匹配报警 <b className="mono">{alarmCode}</b> 的问题单。</div>}
              {alarmHits && alarmHits.length > 0 && (
                <div className="fc-hits">
                  {alarmHits.map(i => (
                    <button key={i.incident_id} className="fc-hit" onClick={() => onOpenIncident(i.incident_id)}>
                      <span className="mono">{i.incident_id}</span>
                      <span className="fc-hit-code">{String(i.alarm?.code || i.alarm?.definition_id || "")}</span>
                      <span className="fc-hit-path">{i.physical_path_at_event}</span>
                      <Icon name="arrow" size={12} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="panel fc-card">
            <div className="panel-h"><Icon name="doc" size={14} /> ③ 按变更单 / 项目找工程</div>
            <div className="panel-b">
              <div className="obj-search">
                <input value={changeQ} placeholder="变更单 chg_xxx 或项目 ID / 名称"
                  onChange={e => setChangeQ(e.target.value)} onKeyDown={e => e.key === "Enter" && searchChange()} />
                <button className="btn sm" onClick={searchChange}>查找</button>
              </div>
              {changeDone && changeProjects.length === 0 && changeIncidents.length === 0 &&
                <div className="hint">未匹配到项目或关联问题单。</div>}
              {changeProjects.length > 0 && (
                <div className="fc-hits">
                  {changeProjects.map(p => (
                    <div key={p.project_id} className="fc-hit static">
                      <span className="mono">{p.project_id}</span>
                      <span className="fc-hit-path">{p.name}</span>
                      <Badge tone="ink">rev {p.revision} · {p.steps} steps</Badge>
                    </div>
                  ))}
                </div>
              )}
              {changeIncidents.length > 0 && (
                <div className="fc-hits">
                  {changeIncidents.map(i => (
                    <button key={i.incident_id} className="fc-hit" onClick={() => onOpenIncident(i.incident_id)}>
                      <span className="mono">{i.incident_id}</span>
                      <span className="fc-hit-path">{incidentChangeSets(i).join(", ")}</span>
                      <Icon name="arrow" size={12} />
                    </button>
                  ))}
                </div>
              )}
              {!changeDone && <div className="hint">按变更单号（change_set_ids）或项目定位工程与相关问题单。</div>}
            </div>
          </section>
        </div>

        <section className="panel">
          <div className="panel-h">角色与审计（RBAC）<span className="sp" /><span className="hint">当前身份见右上角 · 演示用身份传递，非生产认证</span></div>
          <div className="panel-b fc-rbac">
            <div className="fc-roles">
              {!matrix && <div className="hint">角色清单加载中或不可用。</div>}
              {matrix?.roles.map(role => (
                <div key={role} className="fc-role">
                  <Badge tone="ink">{role}</Badge>
                  <span>{matrix.permissions && Object.keys(matrix.permissions).length > 0
                    ? `可执行 ${Object.entries(matrix.permissions)
                        .filter(([, roles]) => roles.includes(role)).length} 项动作`
                    : "权限矩阵未加载"}</span>
                </div>
              ))}
            </div>
            {audit.length > 0 && (
              <table className="ctable">
                <thead><tr><th>时间</th><th>身份</th><th>动作</th><th>结果</th></tr></thead>
                <tbody>{audit.slice(0, 10).map((a, i) => (
                  <tr key={i}>
                    <td className="mono">{String(a.ts ?? "")}</td>
                    <td>{String(a.actor_id ?? "")} · {String(a.role ?? "")}</td>
                    <td className="mono">{String(a.action ?? "")}</td>
                    <td>{a.result === "FORBIDDEN" ? <Badge tone="err">拒绝</Badge> : <Badge tone="ok">{String(a.result ?? "OK")}</Badge>}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        </section>
      </div>
      {toastEl}
    </div>
  );
}
