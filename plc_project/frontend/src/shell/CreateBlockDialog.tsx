import React, { useEffect, useRef, useState } from "react";
import "./createblock.css";

export interface CreateBlockSpec {
  name: string;
  blockType: "FB" | "FC" | "DB" | "OB";
  comment: string;
}

export interface CreateBlockDialogProps {
  open: boolean;
  /** block = 新建逻辑块；project = 新建空白项目 */
  mode: "block" | "project";
  /** mode=block 时用于块名查重 */
  existingNames: string[];
  onClose(): void;
  onCreateBlock(spec: CreateBlockSpec): void;
  onCreateProject(projectName: string, targetDir?: string): void;
}

/** SCL 标识符合法字符：字母/下划线开头，仅字母、数字、下划线 */
const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

const BLOCK_TYPES = ["FB", "FC", "DB", "OB"] as const;

const BLOCK_TYPE_CAPTIONS: Record<CreateBlockSpec["blockType"], string> = {
  FB: "功能块",
  FC: "函数",
  DB: "数据块",
  OB: "组织块",
};

export const CreateBlockDialog: React.FC<CreateBlockDialogProps> = ({
  open,
  mode,
  existingNames,
  onClose,
  onCreateBlock,
  onCreateProject,
}) => {
  const [name, setName] = useState("");
  const [targetDir, setTargetDir] = useState("");
  const [blockType, setBlockType] = useState<CreateBlockSpec["blockType"]>("FB");
  const [comment, setComment] = useState("");
  const [touched, setTouched] = useState(false);
  const nameRef = useRef<HTMLInputElement | null>(null);

  // 打开时复位表单并自动聚焦第一个输入框
  useEffect(() => {
    if (!open) return;
    setName("");
    setTargetDir("");
    setBlockType("FB");
    setComment("");
    setTouched(false);
    const t = window.setTimeout(() => nameRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open, mode]);

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

  const isBlock = mode === "block";
  const trimmed = name.trim();

  let nameError = "";
  if (!trimmed) {
    nameError = touched ? (isBlock ? "请输入块名" : "请输入项目名") : "";
  } else if (!IDENTIFIER_RE.test(trimmed)) {
    nameError = "仅限字母、数字与下划线，且以字母或下划线开头";
  } else if (isBlock && existingNames.some((n) => (n ?? "").toLowerCase() === trimmed.toLowerCase())) {
    nameError = "已存在同名块，请换一个名称";
  }
  const valid = trimmed.length > 0 && nameError === "";

  const submit = () => {
    if (!valid) {
      setTouched(true);
      return;
    }
    if (isBlock) {
      onCreateBlock({ name: trimmed, blockType, comment: comment.trim() });
    } else {
      onCreateProject(trimmed, targetDir.trim());
    }
    onClose();
  };

  return (
    <div
      className="cbd-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="cbd-card"
        role="dialog"
        aria-modal="true"
        aria-label={isBlock ? "新建逻辑块" : "新建空白项目"}
      >
        <div className="cbd-head">
          <div className="cbd-heading">
            <div className="cbd-title">{isBlock ? "新建逻辑块" : "新建空白项目"}</div>
            <div className="cbd-sub">
              {isBlock ? "在当前项目中定义一个新块并加入画布" : "创建一个不含任何块的空白工程画布"}
            </div>
          </div>
          <button type="button" className="cbd-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </div>

        <form
          className="cbd-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="cbd-body">
            <label className="cbd-field">
              <span className="cbd-label">{isBlock ? "块名" : "项目名"}</span>
              <input
                ref={nameRef}
                className="cbd-input cbd-input--mono"
                value={name}
                placeholder={isBlock ? "FB_Motor" : "MyProject"}
                spellCheck={false}
                autoComplete="off"
                onChange={(e) => setName(e.target.value)}
                onBlur={() => setTouched(true)}
              />
              {nameError && <span className="cbd-error">{nameError}</span>}
            </label>

            {isBlock ? (
              <>
                <div className="cbd-field">
                  <span className="cbd-label">类型</span>
                  <div className="cbd-seg" role="radiogroup" aria-label="块类型">
                    {BLOCK_TYPES.map((t) => (
                      <button
                        type="button"
                        key={t}
                        role="radio"
                        aria-checked={blockType === t}
                        className={"cbd-seg__opt" + (blockType === t ? " cbd-seg__opt--on" : "")}
                        onClick={() => setBlockType(t)}
                      >
                        <span className="cbd-seg__code">{t}</span>
                        <span className="cbd-seg__cap">{BLOCK_TYPE_CAPTIONS[t]}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <label className="cbd-field">
                  <span className="cbd-label">注释（选填）</span>
                  <input
                    className="cbd-input"
                    value={comment}
                    placeholder="如：传送带电机控制"
                    onChange={(e) => setComment(e.target.value)}
                  />
                </label>
              </>
            ) : (
              <>
                <label className="cbd-field" style={{ marginTop: 12 }}>
                  <span className="cbd-label">项目存放文件夹 (选定目录)</span>
                  <input
                    className="cbd-input cbd-input--mono"
                    value={targetDir}
                    placeholder="如：C:\Projects\Station1 (选填，留空则使用默认工作区)"
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(e) => setTargetDir(e.target.value)}
                  />
                  <span style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 4 }}>
                    后续生成过程中的 SCL 源码、数据字典与归档包均存放在此文件夹下。
                  </span>
                </label>
                <p className="cbd-note">从零开始：遵循西门子 AF V1.2 标准构建空白工程画布，完成后可打包与回写博图。</p>
              </>
            )}
          </div>

          <div className="cbd-actions">
            <span className="cbd-actions__grow" />
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="btn btn--primary" disabled={!valid}>
              {isBlock ? "创建" : "创建空白画布"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
