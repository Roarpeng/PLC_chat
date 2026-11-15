import type { Project } from "./store";
import { ClampDrawing, Icon, MiniTopo } from "./views";

export function Launcher({ projects, onNew, onImport, onOpen, onDelete }: {
  projects: Project[]; onNew: () => void; onImport: () => void;
  onOpen: (pid: string, cid: string) => void; onDelete: (pid: string) => void;
}) {
  return (
    <div className="launch">
      <div className="launch-top">
        <div className="wordmark"><span className="mk">A</span>aiCoPlc · ProcessOS</div>
        <div className="sp" />
        <span className="meta">工艺编译平台 · Siemens AF · TIA V19</span>
      </div>

      <div className="launch-hero">
        <div className="hero-copy">
          <h1>把工艺，编译成工程图纸。</h1>
          <p>AF-FIRST 工艺编译：描述设备应当如何工作，ProcessOS 绘出符合 AF 契约的控制逻辑，逐场景验证，经人工批准后交付可追溯的原生 TIA 工程。</p>
          <div className="hero-actions">
            <button className="btn primary lg" onClick={onNew}><Icon name="plus" /> 新建项目</button>
            <button className="btn lg" onClick={onImport}><Icon name="import" /> 导入旧项目</button>
          </div>
        </div>
        <div className="hero-fig">
          <ClampDrawing />
          <div className="figcap"><span>图号 PRJ-001 · 双作用气缸</span><span>比例 1:2 · 第三角投影</span></div>
        </div>
      </div>

      <div className="launch-projects">
        <div className="lp-head"><h2>项目图纸夹 · {projects.length} 个</h2></div>
        <div className="projgrid">
          <button className="projcard newcard" onClick={onNew}>
            <span className="plus">+</span>
            <span>新建项目<br /><span style={{ fontSize: 12 }}>从硬件拓扑开始</span></span>
          </button>
          {projects.map(p => (
            <div className="projcard" key={p.id} onClick={() => p.conversations[0] && onOpen(p.id, p.conversations[0].id)}>
              <span className={`pc-kind ${p.kind === "import" ? "imp" : ""}`}>{p.kind === "import" ? "导入" : "新建"}</span>
              <div className="pc-fig"><MiniTopo kind={p.kind} /></div>
              <div className="pc-body">
                <div className="pc-name">{p.name}</div>
                <div className="pc-meta">
                  <span>{p.conversations.length} 段对话</span>
                  <span>比例 {p.scale}</span>
                  <span>{p.created}</span>
                </div>
              </div>
              <button className="iconbtn" style={{ position: "absolute", bottom: 12, right: 12, width: 30, height: 30 }}
                onClick={e => { e.stopPropagation(); onDelete(p.id); }} title="删除项目"><Icon name="cross" size={13} /></button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
