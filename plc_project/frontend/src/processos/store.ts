import { useCallback, useEffect, useState } from "react";
import { processosApi } from "./api";
import type { Contract } from "./types";

export interface Conversation { id: string; title: string; contractId: string; created: string; }
export interface Project { id: string; name: string; kind: "new" | "import"; created: string; scale: string; conversations: Conversation[]; }
export type View = "launcher" | "wizard" | "import" | "workspace";

const KEY = "processos.projects.v1";
const uid = (p: string) => p + "_" + Math.random().toString(36).slice(2, 9);
const today = () => new Date().toISOString().slice(0, 10);

/* A valid clamp contract matching the ProcessOS kernel fixture, so a newly
   created project compiles/validates/simulates for real. */
export function buildContract(id: string, name = "夹紧循环"): Contract {
  const cm = "CM_" + id.replace(/[^A-Za-z0-9]/g, "").slice(0, 8).toUpperCase() + "_CYL";
  const em = "EM_" + id.replace(/[^A-Za-z0-9]/g, "").slice(0, 8).toUpperCase();
  const A = (command: string, value: boolean) => ({ target: cm, command, value });
  return {
    id, name: name + "工艺契约", target_framework: "siemens-af-basic@unverified", unit: "U_ASSEMBLY", schema: "process-contract/1.0",
    resources: [{ id: cm, name: "夹紧气缸（双作用）", kind: "cylinder", commands: ["Extend", "Retract"], feedback: ["Extended", "Retracted"], status: ["Busy", "Done", "Error"], exclusive: true, io_bindings: { Extended: "unbound", Retracted: "unbound" } }],
    operations: [{
      id: "OP_" + em, name, unit: "U_ASSEMBLY", em, resource_ids: [cm],
      preconditions: ["unit.auto_permit", "air.ok", "guard.closed"],
      steps: [
        { id: "S_WAIT", name: "等待启动", entry: [], cyclic: [], exit: [], guard: "Start AND SafetyPermit", duration_ms: 0, timeout_ms: 0, next: "S_EXTEND", failure_target: "", is_fault: false, reset_guard: "" },
        { id: "S_EXTEND", name: "伸出夹紧", entry: [A("Extend", true)], cyclic: [], exit: [A("Extend", false)], guard: "Extended", duration_ms: 0, timeout_ms: 3000, next: "S_HOLD", failure_target: "S_FAULT", is_fault: false, reset_guard: "" },
        { id: "S_HOLD", name: "保持夹紧", entry: [], cyclic: [], exit: [], guard: "", duration_ms: 2000, timeout_ms: 0, next: "S_RETRACT", failure_target: "", is_fault: false, reset_guard: "" },
        { id: "S_RETRACT", name: "缩回释放", entry: [A("Retract", true)], cyclic: [], exit: [A("Retract", false)], guard: "Retracted", duration_ms: 0, timeout_ms: 3000, next: "S_DONE", failure_target: "S_FAULT", is_fault: false, reset_guard: "" },
        { id: "S_DONE", name: "完成", entry: [], cyclic: [], exit: [], guard: "", duration_ms: 0, timeout_ms: 0, next: "S_WAIT", failure_target: "", is_fault: false, reset_guard: "" },
        { id: "S_FAULT", name: "故障保持", entry: [], cyclic: [], exit: [], guard: "", duration_ms: 0, timeout_ms: 0, next: "S_WAIT", failure_target: "", is_fault: true, reset_guard: "Reset AND Retracted AND NOT Extended" },
      ],
      acceptance: ["normal_cycle", "extend_timeout", "retract_timeout", "conflicting_feedback", "permit_loss", "fault_reset"],
    }],
    invariants: [{ id: "INV_NO_SIMULTANEOUS", expr: "NOT (Extend AND Retract)", scope: cm, severity: "error" }],
    open_questions: [{ id: "Q_SAFETY_STOP", question: "全局安全许可撤销时气缸应保持还是退回？须现场工程决策。", affects: ["OP_" + em, cm], severity: "blocking", resolution: null, resolved_by: null }],
    scenarios: [
      { id: "normal_cycle", name: "正常循环", kind: "normal", description: "反馈依序到位" },
      { id: "extend_timeout", name: "伸出超时", kind: "fault", description: "3 秒未到位" },
      { id: "retract_timeout", name: "缩回超时", kind: "fault", description: "缩回 3 秒未到位" },
      { id: "conflicting_feedback", name: "矛盾反馈", kind: "fault", description: "双反馈同时有效" },
      { id: "permit_loss", name: "许可丢失", kind: "fault", description: "保持中许可撤销" },
      { id: "fault_reset", name: "故障复位", kind: "normal", description: "安全条件复位" },
    ],
  } as Contract;
}

function seed(): Project[] {
  return [
    {
      id: "prj_hr001", name: "夹紧工站 · HR001", kind: "import", created: "2026-11-12", scale: "1:2",
      conversations: [
        { id: "cv_clamp", title: "夹紧循环工艺", contractId: "PRJ_CLAMP", created: "2026-11-12" },
        { id: "cv_feed", title: "送料单元概念", contractId: "PRJ_FEED", created: "2026-11-13" },
        { id: "cv_reset", title: "故障复位复盘", contractId: "PRJ_RESET", created: "2026-11-14" },
      ],
    },
    {
      id: "prj_assembly", name: "装配工站 · 新建", kind: "new", created: "2026-11-14", scale: "1:5",
      conversations: [{ id: "cv_assy", title: "装配节拍规划", contractId: "PRJ_ASSY", created: "2026-11-14" }],
    },
  ];
}

export function useAppStore() {
  const [projects, setProjects] = useState<Project[]>(() => {
    try { const raw = localStorage.getItem(KEY); if (raw) return JSON.parse(raw) as Project[]; } catch { /* */ }
    return seed();
  });
  const [view, setView] = useState<View>("launcher");
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [activeConv, setActiveConv] = useState<string | null>(null);

  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(projects)); } catch { /* */ } }, [projects]);

  const project = projects.find(p => p.id === activeProject) ?? null;
  const conversation = project?.conversations.find(c => c.id === activeConv) ?? null;

  const openConversation = useCallback((pid: string, cid: string) => {
    setActiveProject(pid); setActiveConv(cid); setView("workspace");
  }, []);

  const addProject = useCallback((name: string, kind: "new" | "import", firstConvTitle: string, contractId: string) => {
    const pid = uid("prj"); const cid = uid("cv");
    const proj: Project = { id: pid, name, kind, created: today(), scale: kind === "import" ? "1:2" : "1:5", conversations: [{ id: cid, title: firstConvTitle, contractId, created: today() }] };
    setProjects(prev => [proj, ...prev]); setActiveProject(pid); setActiveConv(cid); setView("workspace");
    return proj;
  }, []);

  const addConversation = useCallback((pid: string, title: string, contractId: string) => {
    const cid = uid("cv");
    setProjects(prev => prev.map(p => p.id === pid ? { ...p, conversations: [...p.conversations, { id: cid, title, contractId, created: today() }] } : p));
    setActiveConv(cid);
    return cid;
  }, []);

  const deleteProject = useCallback((pid: string) => {
    setProjects(prev => prev.filter(p => p.id !== pid));
    if (activeProject === pid) { setActiveProject(null); setActiveConv(null); setView("launcher"); }
  }, [activeProject]);

  const renameConversation = useCallback((pid: string, cid: string, title: string) => {
    setProjects(prev => prev.map(p => p.id === pid ? { ...p, conversations: p.conversations.map(c => c.id === cid ? { ...c, title } : c) } : p));
  }, []);

  return { projects, project, conversation, view, setView, activeProject, activeConv, openConversation, addProject, addConversation, deleteProject, renameConversation, setActiveProject, setActiveConv };
}

/* Ensure a conversation's contract exists in the kernel, then load it. */
export async function ensureContract(contractId: string): Promise<{ contract: Contract; revision: number }> {
  try {
    const r = await processosApi.getProject(contractId);
    return { contract: r.contract, revision: r.revision };
  } catch {
    if (contractId === "PRJ_CLAMP") {
      const d = await processosApi.demo();
      return { contract: d.contract, revision: d.revision };
    }
    const c = buildContract(contractId);
    const created = await processosApi.createProject(c);
    return { contract: c, revision: created.revision };
  }
}
