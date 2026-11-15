import { useCallback } from "react";
import { processosApi } from "./api";
import { ImportView } from "./ImportView";
import { Launcher } from "./Launcher";
import { buildContract, useAppStore } from "./store";
import { Wizard } from "./Wizard";
import { Workspace } from "./Workspace";
import "./processos.css";

export function ProcessOSWorkbench() {
  const s = useAppStore();

  const newConversation = useCallback(async () => {
    if (!s.project) return;
    const contractId = "PRJ_" + Math.random().toString(36).slice(2, 8).toUpperCase();
    try {
      await processosApi.createProject(buildContract(contractId, "新工艺"));
      const n = s.project.conversations.length + 1;
      s.addConversation(s.project.id, "工艺对话 " + n, contractId);
    } catch { /* surfaced in workspace */ }
  }, [s]);

  if (s.view === "wizard") return <div className="po"><Wizard onCancel={() => s.setView("launcher")} onDone={(name, cid) => s.addProject(name, "new", "工艺契约 · " + name, cid)} /></div>;
  if (s.view === "import") return <div className="po"><ImportView onCancel={() => s.setView("launcher")} onDone={(name, cid) => s.addProject(name, "import", "重建工艺 · " + name, cid)} /></div>;
  if (s.view === "workspace" && s.project && s.conversation)
    return <div className="po"><Workspace project={s.project} conversation={s.conversation} onBack={() => s.setView("launcher")} onNewConversation={newConversation} onSwitchConversation={s.setActiveConv} /></div>;

  return (
    <div className="po">
      <Launcher projects={s.projects} onNew={() => s.setView("wizard")} onImport={() => s.setView("import")} onOpen={s.openConversation} onDelete={s.deleteProject} />
    </div>
  );
}
