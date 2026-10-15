import React, { useEffect, useRef, useState } from "react";
import type { CanvasStateData } from "../canvas/types";
import { parseTiaXmlFiles } from "../state/tiaXmlImport";
import type { TiaImportFile } from "../state/tiaXmlImport";
import "./import.css";

/** 示例工程文件（public/demo-import）；任一 404 时静默禁用示例按钮 */
const DEMO_FILES = [
  "/demo-import/FB_Motor.xml",
  "/demo-import/DB_MotorInst.xml",
  "/demo-import/Main_OB1.xml",
  "/demo-import/HMI.xml",
];

export interface ImportDialogProps {
  open: boolean;
  onClose(): void;
  /** 前端解析成功后回调（.xml 上传） */
  onImportCanvas(canvas: CanvasStateData, sourceName: string): void;
  /** 服务器路径导入（App 发请求）；reject 时对话框内显示 err.message */
  onImportServerPath(path: string, projectName: string): Promise<void>;
  /** 归档上传导入（.zap19/.ap19/.zip，经网关解包 + Openness）；reject 时显示 err.message */
  onImportUpload(file: File, projectName: string): Promise<void>;
  /** 网关连接状态：null = 未知 */
  backendConnected: boolean | null;
}

type ImportTab = "upload" | "server";

/** 归档类文件：浏览器无法解析，必须经网关 */
const ARCHIVE_SUFFIXES = [".zap", ".zap15", ".zap16", ".zap17", ".zap18", ".zap19", ".zap20", ".zip", ".ap17", ".ap18", ".ap19", ".ap20"];
const ACCEPT_ATTR = ".xml," + ARCHIVE_SUFFIXES.join(",");

const isArchive = (name: string) => {
  const lower = name.toLowerCase();
  return ARCHIVE_SUFFIXES.some((s) => lower.endsWith(s));
};

export const ImportDialog: React.FC<ImportDialogProps> = ({
  open,
  onClose,
  onImportCanvas,
  onImportServerPath,
  onImportUpload,
  backendConnected,
}) => {
  const [tab, setTab] = useState<ImportTab>("upload");
  const [projectName, setProjectName] = useState("ImportedProject");
  const [files, setFiles] = useState<TiaImportFile[]>([]);
  const [archive, setArchive] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [summary, setSummary] = useState<{ blocks: number; tags: number } | null>(null);
  const [issues, setIssues] = useState<{ file: string; message: string }[]>([]);
  const [serverPath, setServerPath] = useState("");
  const [serverProject, setServerProject] = useState("");
  const [serverBusy, setServerBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [demoMissing, setDemoMissing] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // 打开时复位全部瞬态状态
  useEffect(() => {
    if (!open) return;
    setTab("upload");
    setProjectName("ImportedProject");
    setFiles([]);
    setArchive(null);
    setUploading(false);
    setDragOver(false);
    setParsing(false);
    setSummary(null);
    setIssues([]);
    setServerPath("");
    setServerProject("");
    setServerBusy(false);
    setServerError(null);
  }, [open]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const resolvedProject = projectName.trim() || "ImportedProject";

  /** 选择 / 拖入文件：.xml 进本地解析列表；归档（.zap19 等）单独持有并清空 xml 列表（互斥路径） */
  const addFiles = async (list: FileList | File[]) => {
    const dropped = Array.from(list);
    const incomingXml = dropped.filter((f) => f.name.toLowerCase().endsWith(".xml"));
    const incomingArchive = dropped.find((f) => isArchive(f.name));
    if (!incomingXml.length && !incomingArchive) {
      setIssues([
        {
          file: "",
          message:
            "支持的格式：TIA Portal Openness 导出的 .xml，或 .zap19/.zap20 工程归档（经网关解包）",
        },
      ]);
      return;
    }
    if (incomingArchive) {
      setArchive(incomingArchive);
      setFiles([]);
      setSummary(null);
      setIssues([]);
      // 项目名还是默认值时，自动取归档名（去后缀）
      if (!projectName.trim() || projectName.trim() === "ImportedProject") {
        setProjectName(incomingArchive.name.replace(/\.[^.]+$/, ""));
      }
      return;
    }
    const read = await Promise.all(
      incomingXml.map(async (f) => ({ name: f.name, text: await f.text() })),
    );
    setArchive(null);
    setFiles((prev) => {
      const map = new Map(prev.map((p) => [p.name, p]));
      for (const r of read) map.set(r.name, r);
      return Array.from(map.values());
    });
    setSummary(null);
    setIssues([]);
  };

  const removeFile = (name: string) => {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  /** 载入示例项目：任一文件 404 → 静默禁用按钮并 title 提示 */
  const loadDemo = async () => {
    if (demoMissing || demoLoading) return;
    setDemoLoading(true);
    try {
      const loaded = await Promise.all(
        DEMO_FILES.map(async (url) => {
          const res = await fetch(url);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const name = url.slice(url.lastIndexOf("/") + 1);
          return { name, text: await res.text() };
        }),
      );
      setFiles(loaded);
      setProjectName("MotorDemo");
      setSummary(null);
      setIssues([]);
    } catch {
      setDemoMissing(true);
    } finally {
      setDemoLoading(false);
    }
  };

  /** 前端解析：成功（至少解析出 1 块或 1 标签）→ 回调并关闭；全部失败则就地显示错误 */
  const runParse = async () => {
    if (!files.length || parsing) return;
    setParsing(true);
    setSummary(null);
    setIssues([]);
    try {
      const result = await parseTiaXmlFiles(files, resolvedProject);
      if (result.blocksParsed + result.tagsParsed > 0) {
        setSummary({ blocks: result.blocksParsed, tags: result.tagsParsed });
        setIssues(result.errors ?? []);
        onImportCanvas(result.canvas, resolvedProject);
        onClose();
      } else {
        setIssues(
          result.errors?.length
            ? result.errors
            : [{ file: "", message: "未能从所选文件解析出任何块或标签，请确认导出的是 TIA Portal Openness 块 / 标签表 XML" }],
        );
      }
    } catch (err) {
      setIssues([{ file: "", message: err instanceof Error ? err.message : String(err) }]);
    } finally {
      setParsing(false);
    }
  };

  /** 归档上传导入（经网关解包 + Openness，可能需要 1–3 分钟） */
  const runUploadImport = async () => {
    if (!archive || uploading || backendConnected === false) return;
    setUploading(true);
    setIssues([]);
    try {
      await onImportUpload(archive, resolvedProject);
      onClose();
    } catch (err) {
      setIssues([
        { file: archive.name, message: err instanceof Error ? err.message : String(err) },
      ]);
    } finally {
      setUploading(false);
    }
  };

  /** 服务器路径导入：成功关闭；失败在对话框内显示 err.message */
  const runServerImport = async () => {
    const path = serverPath.trim();
    if (!path || serverBusy || backendConnected === false) return;
    setServerBusy(true);
    setServerError(null);
    try {
      await onImportServerPath(path, serverProject.trim());
      onClose();
    } catch (err) {
      setServerError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerBusy(false);
    }
  };

  return (
    <div
      className="imp-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="imp-card" role="dialog" aria-modal="true" aria-label="导入博图项目">
        <div className="imp-head">
          <div className="imp-heading">
            <div className="imp-title">导入博图项目</div>
            <div className="imp-sub">.zap19 工程归档（经网关解包）或 Openness 导出的块 / 标签表 XML</div>
          </div>
          <button type="button" className="imp-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="imp-body">
          <div className="imp-tabs" role="tablist" aria-label="导入方式">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "upload"}
              className={"imp-tab" + (tab === "upload" ? " imp-tab--on" : "")}
              onClick={() => setTab("upload")}
            >
              上传文件
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "server"}
              className={"imp-tab" + (tab === "server" ? " imp-tab--on" : "")}
              onClick={() => setTab("server")}
            >
              服务器路径
            </button>
          </div>

          {tab === "upload" ? (
            <>
              <label className="imp-field">
                <span className="imp-label">项目名</span>
                <input
                  className="imp-input"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="ImportedProject"
                  spellCheck={false}
                />
              </label>

              <div className="imp-field">
                <span className="imp-label">项目文件</span>
                <button
                  type="button"
                  className={"imp-drop" + (dragOver ? " imp-drop--over" : "")}
                  onClick={() => fileRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOver(false);
                    void addFiles(e.dataTransfer.files);
                  }}
                >
                  <span className="imp-drop__main">拖拽 .zap19 工程归档或 .xml 导出文件到此处，或点击选择</span>
                  <span className="imp-drop__hint">.zap19/.zap20 需经网关解包；.xml 可离线解析</span>
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  accept={ACCEPT_ATTR}
                  className="imp-file-input"
                  onChange={(e) => {
                    const el = e.target;
                    void addFiles(el.files ?? []);
                    el.value = "";
                  }}
                />

                {archive && (
                  <div className="imp-files">
                    <div className="imp-file imp-file--archive">
                      <span className="imp-file__name" title={archive.name}>
                        {archive.name}（{(archive.size / 1024 / 1024).toFixed(1)} MB · 经网关解包导入）
                      </span>
                      <button
                        type="button"
                        className="imp-file__x"
                        aria-label={"移除 " + archive.name}
                        onClick={() => setArchive(null)}
                      >
                        ×
                      </button>
                    </div>
                    {uploading && (
                      <div className="imp-note">
                        正在解包工程并通过 TIA Openness 导出，可能需要 1–3 分钟，请勿关闭…
                      </div>
                    )}
                    {backendConnected === false && !uploading && (
                      <div className="imp-warn">
                        网关未连接：.zap 归档无法本地解析，请启动网关或改用 .xml 导出文件
                      </div>
                    )}
                  </div>
                )}

                {files.length > 0 && (
                  <div className="imp-files">
                    {files.map((f) => (
                      <div className="imp-file" key={f.name}>
                        <span className="imp-file__name" title={f.name}>
                          {f.name}
                        </span>
                        <button
                          type="button"
                          className="imp-file__x"
                          aria-label={"移除 " + f.name}
                          onClick={() => removeFile(f.name)}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {summary && (
                <div className="imp-summary">
                  解析 {summary.blocks} 块 · {summary.tags} 标签
                </div>
              )}
              {issues.length > 0 && (
                <div className="imp-issues">
                  {issues.map((it, i) => (
                    <div className="imp-issue" key={i}>
                      {it.file ? it.file + "：" + it.message : it.message}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <label className="imp-field">
                <span className="imp-label">服务器路径</span>
                <input
                  className="imp-input imp-input--mono"
                  value={serverPath}
                  onChange={(e) => {
                    setServerPath(e.target.value);
                    setServerError(null);
                  }}
                  placeholder={"D:\\Projects\\MyPlant 或其 Blocks 导出目录"}
                  spellCheck={false}
                />
              </label>

              <label className="imp-field">
                <span className="imp-label">项目名（可空 = 后端自动）</span>
                <input
                  className="imp-input"
                  value={serverProject}
                  onChange={(e) => setServerProject(e.target.value)}
                  placeholder="留空则由后端自动确定"
                />
              </label>

              <p className="imp-note">
                路径需在网关 PLC_PATH_ALLOWLIST 白名单内；支持 .zap19/.zap20 归档、解压后的工程目录或
                Openness 导出 XML 目录（.apxx/.zap 需网关侧安装 TIA Openness）。
              </p>

              {backendConnected === false && (
                <div className="imp-warn">网关未连接，服务器导入不可用（可改用上传 XML）</div>
              )}

              {serverError && <div className="imp-err">{serverError}</div>}
            </>
          )}
        </div>

        <div className="imp-actions">
          {tab === "upload" ? (
            archive ? (
              <>
                <button
                  type="button"
                  className="btn btn--ghost imp-btn-sm"
                  disabled={uploading}
                  onClick={() => setArchive(null)}
                >
                  移除归档
                </button>
                <span className="imp-actions__grow" />
                <button type="button" className="btn btn--ghost" onClick={onClose} disabled={uploading}>
                  取消
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={uploading || backendConnected === false}
                  onClick={() => void runUploadImport()}
                >
                  {uploading ? "解包导入中…" : "上传并解析（经网关）"}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn--ghost imp-btn-sm"
                  disabled={demoMissing || demoLoading}
                  title={demoMissing ? "示例文件不存在" : undefined}
                  onClick={() => void loadDemo()}
                >
                  {demoLoading ? "载入中…" : "载入示例项目"}
                </button>
                <span className="imp-actions__grow" />
                <button type="button" className="btn btn--ghost" onClick={onClose}>
                  取消
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={files.length === 0 || parsing}
                  onClick={() => void runParse()}
                >
                  {parsing ? "解析中…" : "解析并导入"}
                </button>
              </>
            )
          ) : (
            <>
              <span className="imp-actions__grow" />
              <button type="button" className="btn btn--ghost" onClick={onClose}>
                取消
              </button>
              <button
                type="button"
                className="btn btn--primary"
                disabled={!serverPath.trim() || serverBusy || backendConnected === false}
                onClick={() => void runServerImport()}
              >
                {serverBusy ? "导入中…" : "从服务器导入"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
