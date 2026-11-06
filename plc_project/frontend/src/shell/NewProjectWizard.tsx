/**
 * NewProjectWizard（F10 / P1-F / D7）：四步向导，合并启动屏原有「新建工程」与
 * 「从零生成标准工程」双入口。
 *
 *  - 步骤 1 建立项目：**第一步生成 project_id** 并在后续每一步持续展示，贯穿
 *    会话 / 拓扑 / 资料 / 规格 / 产物；
 *  - 步骤 2 工艺描述：可选，可留空（稍后在工作台对话补充）；
 *  - 步骤 3 资料：DB 编号与 IO 表上传为**可选**（D7）。未上传时也能完成拓扑与
 *    逻辑确认，UI 只登记用户真实填写的编号 / 真实选择的文件名，**不虚构任何
 *    物理地址（%I / %Q）或 OB 条目**；
 *  - 步骤 4 确认并进入：落盘 project_id 与启动上下文，交回 ProjectLaunchScreen。
 *
 * 依赖：只复用 `state/greenfield.ts` 的现成机制，不新增第三方依赖。
 */
import React, { useState } from "react";
import {
  createProjectId,
  saveLaunchContext,
  saveProjectId,
  type GFLaunchContext,
} from "../state/greenfield";
import "./greenfield.css";

export interface NewProjectWizardProps {
  onComplete: (context: GFLaunchContext) => void;
  onCancel: () => void;
}

type WizardStep = 1 | 2 | 3 | 4;

const STEPS: Array<{ step: WizardStep; title: string; desc: string }> = [
  { step: 1, title: "建立项目", desc: "生成 project_id，锁定项目身份" },
  { step: 2, title: "工艺描述", desc: "可选：描述工艺，稍后也可在对话补充" },
  { step: 3, title: "资料登记", desc: "可选：DB 编号 / IO 表，可跳过（D7）" },
  { step: 4, title: "确认进入", desc: "汇总并进入逻辑工作台" },
];

const NO_UPLOAD_NOTE =
  "未上传资料：拓扑与逻辑确认不依赖物理地址或 OB 条目；系统不会虚构任何地址 / OB 编号，产物中的 ob_entries 留空。";

export const NewProjectWizard: React.FC<NewProjectWizardProps> = ({ onComplete, onCancel }) => {
  // project_id 在第一步生成（组件挂载即第一步），全程持有并展示。
  const [projectId] = useState<string>(() => createProjectId());
  const [step, setStep] = useState<WizardStep>(1);
  const [projectName, setProjectName] = useState("新建工程");
  const [prompt, setPrompt] = useState("");
  const [dbNumber, setDbNumber] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);

  const hasUploads = dbNumber.trim().length > 0 || uploadedFiles.length > 0;

  const finish = () => {
    const context: GFLaunchContext = {
      project_id: projectId,
      project_name: projectName.trim() || "新建工程",
      prompt: prompt.trim(),
      has_uploads: hasUploads,
      no_upload_note: hasUploads ? undefined : NO_UPLOAD_NOTE,
      db_number: dbNumber.trim() || undefined,
      uploaded_files: uploadedFiles.length ? uploadedFiles : undefined,
      created_at: new Date().toISOString(),
    };
    // project_id 落盘，供 GreenfieldChannel 启动时 ensureProjectId() 复用。
    saveProjectId(projectId);
    saveLaunchContext(context);
    onComplete(context);
  };

  return (
    <div className="gf-wizard-backdrop" data-ui="new-project-wizard-backdrop">
      <div className="gf-root gf-wizard" data-ui="new-project-wizard">
        <div className="gf-wizard__head">
          <div>
            <div className="gf-wizard__title">新建工程 · 四步向导</div>
            <div className="gf-muted">合并后的单一入口：项目身份 → 工艺 → 可选资料 → 确认进入</div>
          </div>
          <button type="button" className="gf-btn gf-btn--xs gf-btn--ghost" onClick={onCancel}>
            取消
          </button>
        </div>

        <div className="gf-wizard__project">
          <span className="gf-muted">project_id（第一步生成，贯穿全程）</span>
          <code>{projectId}</code>
        </div>

        <div className="gf-wizard__steps">
          {STEPS.map((item) => (
            <div
              key={item.step}
              className={
                step === item.step
                  ? "gf-wizard-step gf-wizard-step--active"
                  : step > item.step
                    ? "gf-wizard-step gf-wizard-step--done"
                    : "gf-wizard-step"
              }
            >
              <span className="gf-wizard-step__no">{item.step}</span>
              <div>
                <strong>{item.title}</strong>
                <div className="gf-muted">{item.desc}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="gf-wizard__body">
          {step === 1 && (
            <div className="gf-wizard-pane">
              <div className="gf-side-title">项目身份</div>
              <div className="gf-muted">
                项目是工程容器的一等公民。此编号将绑定本轮会话、逻辑拓扑、资料、
                冻结规格与派生产物，全程不变。
              </div>
              <label className="gf-wizard-field">
                <span>项目名称</span>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="如：装配工位"
                />
              </label>
              <div className="gf-wizard-readonly">
                <span className="gf-muted">project_id</span>
                <code>{projectId}</code>
                <span className="gf-muted">（自动生成，不可编辑）</span>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="gf-wizard-pane">
              <div className="gf-side-title">工艺描述（可选）</div>
              <div className="gf-muted">
                可直接描述工站 / 执行单元 / 执行件与设备交互；留空也能继续，进入工作台后在对话里补充。
              </div>
              <textarea
                className="gf-textarea"
                rows={5}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="例如：视觉引导与机器人上下料工位，气缸夹紧与真空吸盘配合，急停触发安全中止…"
              />
              <div className="gf-muted">可跳过此步：没有工艺描述时不会生成任何臆造的结构。</div>
            </div>
          )}

          {step === 3 && (
            <div className="gf-wizard-pane">
              <div className="gf-side-title">资料登记（DB 编号 / IO 表，可选 · D7）</div>
              <div className="gf-wizard-optional">
                这一步<strong>可以整步跳过</strong>：没有上传资料时同样能完成拓扑与逻辑确认。
                下方只登记你真实填写的编号与真实选择的文件名，不会生成任何示例地址、
                %I/%Q 地址表或 OB 条目。实际解析上传仍在工作台对话区完成（单一入口）。
              </div>
              <label className="gf-wizard-field">
                <span>DB 编号（可选，留空即不登记）</span>
                <input
                  type="text"
                  value={dbNumber}
                  onChange={(e) => setDbNumber(e.target.value)}
                  placeholder="仅在确有资料时填写真实编号"
                />
              </label>
              <label className="gf-btn gf-btn--xs gf-btn--ghost gf-wizard-file">
                选择 IO 表 / DB 文档（可选）
                <input
                  type="file"
                  multiple
                  hidden
                  accept=".pdf,.xlsx,.xlsm,.csv,.scl,.txt,.db"
                  onChange={(e) => {
                    const names = Array.from(e.target.files ?? []).map((f) => f.name);
                    setUploadedFiles(names);
                    e.target.value = "";
                  }}
                />
              </label>
              {uploadedFiles.length > 0 ? (
                <div className="gf-wizard-files">
                  <div className="gf-side-title">已登记的真实文件名（{uploadedFiles.length}）</div>
                  {uploadedFiles.map((name) => (
                    <div className="gf-muted" key={name}>· {name}</div>
                  ))}
                </div>
              ) : (
                <div className="gf-wizard-nodata">
                  {NO_UPLOAD_NOTE}
                </div>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="gf-wizard-pane">
              <div className="gf-side-title">确认并进入逻辑工作台</div>
              <div className="gf-wizard-summary">
                <div><span className="gf-muted">project_id：</span><code>{projectId}</code></div>
                <div><span className="gf-muted">项目名称：</span>{projectName.trim() || "新建工程"}</div>
                <div>
                  <span className="gf-muted">工艺描述：</span>
                  {prompt.trim() ? `${prompt.trim().slice(0, 60)}${prompt.trim().length > 60 ? "…" : ""}` : "（留空，进入后在对话补充）"}
                </div>
                <div>
                  <span className="gf-muted">资料：</span>
                  {hasUploads
                    ? `已登记 ${uploadedFiles.length} 个文件${dbNumber.trim() ? ` · DB ${dbNumber.trim()}` : ""}`
                    : "未上传（可跳过）"}
                </div>
              </div>
              {!hasUploads && <div className="gf-wizard-nodata">{NO_UPLOAD_NOTE}</div>}
              <div className="gf-wizard__pending">
                涉真机验收项：<strong>pending_real_machine</strong>（本批次无真机，不宣称 L2 / L4 通过，不宣称编译零错误）
              </div>
            </div>
          )}
        </div>

        <div className="gf-wizard__footer">
          <div className="gf-muted">第 {step} / 4 步 · project_id {projectId}</div>
          <div className="gf-wizard__nav">
            {step > 1 && (
              <button
                type="button"
                className="gf-btn gf-btn--ghost"
                onClick={() => setStep((s) => (s - 1) as WizardStep)}
              >
                上一步
              </button>
            )}
            {(step === 2 || step === 3) && (
              <button
                type="button"
                className="gf-btn gf-btn--ghost"
                onClick={() => setStep((s) => (s + 1) as WizardStep)}
              >
                跳过此步
              </button>
            )}
            {step < 4 ? (
              <button
                type="button"
                className="gf-btn gf-btn--primary"
                disabled={step === 1 && !projectName.trim()}
                onClick={() => setStep((s) => (s + 1) as WizardStep)}
              >
                下一步
              </button>
            ) : (
              <button type="button" className="gf-btn gf-btn--danger" onClick={finish}>
                确认并进入逻辑工作台
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
