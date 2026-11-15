import { useCallback, useState } from "react";
import { processosApi } from "./api";
import { Baselines } from "./Baselines";
import { CommissioningLedger } from "./CommissioningLedger";
import { DeploymentGateway } from "./DeploymentGateway";
import { FieldConsole } from "./FieldConsole";
import type { FieldView } from "./fieldui";
import { ImportView } from "./ImportView";
import { Launcher } from "./Launcher";
import { ALL_MACHINES, MachineCanvas } from "./MachineCanvas";
import { OrchestrationView } from "./OrchestrationView";
import { StationCanvas } from "./StationCanvas";
import { buildContract, useAppStore } from "./store";
import { Traceability } from "./Traceability";
import { Wizard } from "./Wizard";
import { Workspace } from "./Workspace";
import "./processos.css";

export function ProcessOSWorkbench() {
  const s = useAppStore();
  /* incident focused from the field console (entry ②/③) — handed to Traceability */
  const [fieldIncident, setFieldIncident] = useState("");
  /* object focused from the canvases (CM card click) — handed to Traceability */
  const [focusObject, setFocusObject] = useState("");
  /* PLAN §3.1 canvases: selected station + selected machine (project) */
  const [canvasStation, setCanvasStation] = useState("");
  const [canvasProject, setCanvasProject] = useState(ALL_MACHINES);

  const newConversation = useCallback(async () => {
    if (!s.project) return;
    const contractId = "PRJ_" + Math.random().toString(36).slice(2, 8).toUpperCase();
    try {
      await processosApi.createProject(buildContract(contractId, "新工艺"));
      const n = s.project.conversations.length + 1;
      s.addConversation(s.project.id, "工艺对话 " + n, contractId);
    } catch { /* surfaced in workspace */ }
  }, [s]);

  const openFieldIncident = useCallback((id: string) => {
    setFieldIncident(id);
    s.setView("trace");
  }, [s]);

  const openObject = useCallback((objectId: string) => {
    setFocusObject(objectId);
    s.setView("trace");
  }, [s]);

  const openStation = useCallback((stationId: string, projectId?: string) => {
    setCanvasStation(stationId);
    if (projectId && projectId !== ALL_MACHINES) setCanvasProject(projectId);
    s.setView("station");
  }, [s]);

  /* FieldConsole ① 的「查看工位画布」：以 physical_path 首段（工位名）解析
   * 工位对象；解析不到就落到整机画布，不猜测。 */
  const openStationByPath = useCallback((physicalPath: string) => {
    const name = (physicalPath.split("/")[0] ?? "").trim();
    processosApi.traceGraphs().then(g => {
      const st = g.PhysicalGraph.find(o =>
        o.kind === "station" && !!name && (o.display_name === name || (o.aliases ?? []).includes(name)));
      if (st) { setCanvasStation(st.object_id); s.setView("station"); }
      else s.setView("machine");
    }).catch(() => s.setView("machine"));
  }, [s]);

  const navField = useCallback((v: FieldView) => s.setView(v), [s]);
  const backToLauncher = useCallback(() => s.setView("launcher"), [s.setView]);

  if (s.view === "wizard") return <div className="po"><Wizard onCancel={() => s.setView("launcher")} onDone={(name, cid) => s.addProject(name, "new", "工艺契约 · " + name, cid)} /></div>;
  if (s.view === "import") return <div className="po"><ImportView onCancel={() => s.setView("launcher")} onDone={(name, cid) => s.addProject(name, "import", "重建工艺 · " + name, cid)} /></div>;
  if (s.view === "workspace" && s.project && s.conversation)
    return <div className="po">
      {/* Workbench 顶导：工位编排入口（需求 c，仅项目打开态可用；后续可在工位画布面包屑旁加跳转） */}
      <div className="pos-orch-entry">
        <button className="btn sm" onClick={() => s.setView("orch")}>工位编排</button>
        <span className="hint">Unit 级 EM 运行步序 · 资源占用 · 并行组（契约层声明）</span>
      </div>
      <Workspace project={s.project} conversation={s.conversation} onBack={() => s.setView("launcher")} onNewConversation={newConversation} onSwitchConversation={s.setActiveConv} /></div>;
  if (s.view === "orch" && s.project && s.conversation)
    return <div className="po"><OrchestrationView projectId={s.conversation.contractId} onBack={() => s.setView("workspace")} /></div>;

  /* field workbench (PLAN §3): three entrances + canvases + traceability + ledger + baselines + gateway */
  if (s.view === "field")
    return <div className="po"><FieldConsole onBack={backToLauncher} onNav={navField} onOpenIncident={openFieldIncident} onOpenStationByPath={openStationByPath} /></div>;
  if (s.view === "machine")
    return <div className="po"><MachineCanvas onBack={backToLauncher} onNav={navField} project={canvasProject} onSelectProject={setCanvasProject} onOpenStation={openStation} /></div>;
  if (s.view === "station")
    return <div className="po"><StationCanvas stationId={canvasStation} projectId={canvasProject !== ALL_MACHINES ? canvasProject : undefined} onBack={backToLauncher} onNav={navField} onBackToMachine={() => s.setView("machine")} onOpenObject={openObject} /></div>;
  if (s.view === "trace")
    return <div className="po"><Traceability onBack={backToLauncher} onNav={navField} focusIncidentId={fieldIncident} focusObjectId={focusObject} /></div>;
  if (s.view === "commissioning")
    return <div className="po"><CommissioningLedger onBack={backToLauncher} onNav={navField} /></div>;
  if (s.view === "baselines")
    return <div className="po"><Baselines onBack={backToLauncher} onNav={navField} /></div>;
  if (s.view === "gateway")
    return <div className="po"><DeploymentGateway onBack={backToLauncher} onNav={navField} /></div>;

  return (
    <div className="po">
      <Launcher projects={s.projects} onNew={() => s.setView("wizard")} onImport={() => s.setView("import")}
        onOpen={s.openConversation} onDelete={s.deleteProject} onField={() => s.setView("field")} />
    </div>
  );
}
