import React, { useEffect, useMemo, useRef, useState } from "react";
import type {
  CanvasBlockData,
  CanvasHmiWidgetData,
  CanvasTagData,
} from "../canvas/types";
import { renderBlockScl } from "../canvas/sclRender";
import { highlightSclLines } from "../canvas/sclHighlight";
import { explainBlock, type BlockExplanation } from "../state/blockExplainer";
import "./sclpane.css";

export interface SclPaneProps {
  block: CanvasBlockData | null;
  edges: { from: string; to: string; count: number }[];
  widgets: CanvasHmiWidgetData[];
  /** 全局标签表（导入后在 SCL 栏空态 / 解释区展示） */
  tags?: Record<string, CanvasTagData>;
  /** 需要高亮定位的网络 id（变量面板跳转触发） */
  focusNetworkId: number | null;
  onAddVariable?: (
    blockName: string,
    v: { name: string; data_type: string; section: string; comment?: string }
  ) => void;
  onAddNetwork?: (
    blockName: string,
    n: { title: string; scl_text: string; language?: string }
  ) => void;
  /** 删除当前块（父级确认后走 ops 管道）；缺省时不显示删除按钮 */
  onRemoveBlock?: (blockName: string) => void;
  /** 重命名当前块；缺省时不显示重命名按钮 */
  onRenameBlock?: (oldName: string, newName: string) => void;
  /** 删除块内变量 / 网络（解释卡行内按钮）；缺省时不显示行内删除 */
  onRemoveVariable?: (blockName: string, varName: string) => void;
  onRemoveNetwork?: (blockName: string, networkId: number) => void;
  /** LLM 深度解释（App 发网关请求）；缺省时不显示按钮 */
  onDeepExplain?: (block: CanvasBlockData) => Promise<string>;
  /** 查看原始源码（低显著度入口 → 懒加载对比抽屉，契约 15 §5）；缺省时不显示入口 */
  onViewSource?: (blockName: string) => void;
}

/** 变量名合法性：字母或下划线开头，仅含字母、数字、下划线 */
const VAR_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** 分区下拉：展示短标签，提交外部源声明关键字 */
const SECTION_OPTIONS: { value: string; label: string }[] = [
  { value: "VAR_INPUT", label: "IN" },
  { value: "VAR_OUTPUT", label: "OUT" },
  { value: "VAR_IN_OUT", label: "IO" },
  { value: "VAR_STAT", label: "ST" },
  { value: "VAR_TEMP", label: "TM" },
  { value: "VAR", label: "VAR" },
];

/** 解释卡信号四组（非空才渲染） */
const SIGNAL_GROUPS: { key: keyof BlockExplanation["signals"]; label: string }[] = [
  { key: "inputs", label: "输入 IN" },
  { key: "outputs", label: "输出 OUT" },
  { key: "inOuts", label: "双向 IO" },
  { key: "statics", label: "静态 STAT" },
];

const STATUS_LABEL: Record<string, string> = {
  synced: "已同步",
  draft: "草稿",
  error: "存在错误",
};

/** 信号条目 "Name : Type" → 名称与类型拆分（无冒号时整体作为名称） */
function splitSignal(entry: string): { name: string; type: string } {
  const i = entry.indexOf(":");
  if (i < 0) return { name: entry.trim(), type: "" };
  return { name: entry.slice(0, i).trim(), type: entry.slice(i + 1).trim() };
}

/** 「查看原始源码」低显著度图标（</>） */
const SourceCodeIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path
      d="M6 4.5 2.5 8 6 11.5M10 4.5 13.5 8 10 11.5"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/** 中栏：SCL 源码栏（块解释卡 + 源码清单 + 添加变量/网络工具） */
export const SclPane: React.FC<SclPaneProps> = ({
  block,
  edges,
  widgets,
  tags = {},
  focusNetworkId,
  onAddVariable,
  onAddNetwork,
  onRemoveBlock,
  onRenameBlock,
  onRemoveVariable,
  onRemoveNetwork,
  onDeepExplain,
  onViewSource,
}) => {
  const [showExplain, setShowExplain] = useState(true);
  const [openTool, setOpenTool] = useState<"var" | "net" | null>(null);
  const [varName, setVarName] = useState("");
  const [varType, setVarType] = useState("Bool");
  const [varSection, setVarSection] = useState("VAR_INPUT");
  const [netTitle, setNetTitle] = useState("");
  const [netText, setNetText] = useState("");
  const [copied, setCopied] = useState(false);
  const [deep, setDeep] = useState<{ loading: boolean; text: string | null; error: string | null }>({
    loading: false,
    text: null,
    error: null,
  });
  const focusLineRef = useRef<HTMLDivElement | null>(null);

  const blockName = block?.name ?? null;
  const isDb = block?.block_type === "DB";

  // 切换选中块：收起表单并清空全部输入
  useEffect(() => {
    setOpenTool(null);
    setVarName("");
    setVarType("Bool");
    setVarSection("VAR_INPUT");
    setNetTitle("");
    setNetText("");
    setDeep({ loading: false, text: null, error: null });
  }, [blockName]);

  const explanation = useMemo<BlockExplanation | null>(
    () => (block ? explainBlock(block, { edges, widgets }) : null),
    [block, edges, widgets]
  );

  const sclLines = useMemo(
    () => (block ? renderBlockScl(block).split("\n") : []),
    [block]
  );

  /** 复制当前块外部源到剪贴板（成功后按钮短暂变为“已复制”） */
  const copyScl = async () => {
    if (!block) return;
    const text = renderBlockScl(block);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  /** 下载当前块为 .scl 外部源文件 */
  const downloadScl = () => {
    if (!block) return;
    const blob = new Blob([renderBlockScl(block)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${block.name}.scl`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 3000);
  };

  /** 删除当前块（工业安全语义：二次确认） */
  const confirmRemove = () => {
    if (!block || !onRemoveBlock) return;
    const bound = widgets.filter((w) =>
      (w.plc_tag ?? "").toLowerCase().startsWith(`${block.name.toLowerCase()}.`)
    ).length;
    const msg =
      bound > 0
        ? `删除块 "${block.name}"？绑定其变量的 ${bound} 个 HMI 控件将一并移除。`
        : `删除块 "${block.name}"？该操作可通过历史会话找回。`;
    if (window.confirm(msg)) onRemoveBlock(block.name);
  };

  /** 重命名当前块（校验标识符合法 + 由父级负责查重） */
  const promptRename = () => {
    if (!block || !onRenameBlock) return;
    const next = window.prompt(`重命名块 "${block.name}" 为：`, block.name);
    const name = (next ?? "").trim();
    if (!name || name === block.name) return;
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
      window.alert("块名必须是字母/下划线开头的英文标识符（不含空格与中文）。");
      return;
    }
    onRenameBlock(block.name, name);
  };

  /** 触发 LLM 深度解释（未配置时展示一次性指引，不弹错） */
  const runDeepExplain = async () => {
    if (!block || !onDeepExplain || deep.loading) return;
    setDeep({ loading: true, text: null, error: null });
    try {
      const text = await onDeepExplain(block);
      setDeep({ loading: false, text, error: null });
    } catch (err) {
      setDeep({ loading: false, text: null, error: err instanceof Error ? err.message : String(err) });
    }
  };

  // 定位行：含 "// Network <id>:" 注释的源码行（冒号确保 1 与 11 不互撞）
  const focusMarker =
    focusNetworkId != null ? `// Network ${focusNetworkId}:` : null;
  const focusLineIdx =
    focusMarker == null
      ? -1
      : sclLines.findIndex((l) => l.includes(focusMarker));

  // 变量面板跳转 → 滚动到目标网络行
  useEffect(() => {
    if (focusNetworkId == null) return;
    focusLineRef.current?.scrollIntoView({ block: "center" });
  }, [focusNetworkId, blockName]);

  const nameInvalid = varName.length > 0 && !VAR_NAME_RE.test(varName);
  const varFormValid = VAR_NAME_RE.test(varName) && varType.trim().length > 0;
  const netFormValid = netText.trim().length > 0;

  function toggleTool(tool: "var" | "net") {
    setOpenTool((cur) => (cur === tool ? null : tool));
  }

  function submitVariable() {
    if (!block || !varFormValid) return;
    onAddVariable?.(block.name, {
      name: varName.trim(),
      data_type: varType.trim(),
      section: isDb ? "VAR" : varSection,
    });
    setVarName("");
  }

  function submitNetwork() {
    if (!block || !netFormValid) return;
    onAddNetwork?.(block.name, {
      title: netTitle.trim() || `网络 ${block.networks.length + 1}`,
      scl_text: netText,
    });
    setNetTitle("");
    setNetText("");
  }

  return (
    <div className="sp">
      {/* 1. 头部行 */}
      <header className="sp-head">
        {block ? (
          <>
            <span className="sp-head__type">{block.block_type}</span>
            <span className="sp-head__name">"{block.name}"</span>
            <span
              className={`sp-led sp-led--${block.status}`}
              title={STATUS_LABEL[block.status] ?? block.status}
            />
            <span className="sp-head__grow" />
            <button
              type="button"
              className="sp-ghost"
              title="复制当前块的外部源 SCL 到剪贴板"
              onClick={() => void copyScl()}
            >
              {copied ? "已复制" : "复制"}
            </button>
            <button
              type="button"
              className="sp-ghost"
              title={`下载 ${block.name}.scl（TIA Portal 外部源，可直接导入）`}
              onClick={downloadScl}
            >
              下载
            </button>
            {onRenameBlock && (
              <button
                type="button"
                className="sp-ghost"
                title="重命名该块（自动改写其他块 SCL 引用与 HMI 绑定）"
                onClick={promptRename}
              >
                重命名
              </button>
            )}
            {onRemoveBlock && (
              <button
                type="button"
                className="sp-ghost sp-ghost--danger"
                title="删除该块（二次确认）"
                onClick={confirmRemove}
              >
                删除
              </button>
            )}
            <button
              type="button"
              className="sp-ghost"
              aria-pressed={showExplain}
              onClick={() => setShowExplain((v) => !v)}
            >
              解释
            </button>
            {onViewSource && (
              <button
                type="button"
                className="sp-ghost sp-ghost--icon"
                title={`查看 ${block.name} 原始源码（FlgNet XML / 直译 SCL / 归约追踪，按需加载）`}
                aria-label={`查看 ${block.name} 原始源码`}
                onClick={() => onViewSource(block.name)}
              >
                <SourceCodeIcon />
              </button>
            )}
          </>
        ) : (
          <span className="sp-head__title">SCL 源码</span>
        )}
      </header>

      {!block ? (
        /* 2. 无块空态：展示标签表与 HMI 绑定清单 */
        <div className="sp-empty">
          <p>点击全局图中的块，</p>
          <p>查看解释与源码</p>
          {Object.keys(tags).length > 0 && (
            <div className="sp-tagtable" aria-label="标签表">
              <div className="sp-tagtable__title">标签表 · {Object.keys(tags).length}</div>
              {Object.values(tags)
                .slice(0, 24)
                .map((t) => (
                  <div key={t.name} className="sp-tagrow">
                    <span className="sp-tagrow__name">{t.name}</span>
                    <span className="sp-tagrow__type">{t.data_type}</span>
                    <span className="sp-tagrow__addr">{t.logical_address}</span>
                  </div>
                ))}
              {Object.keys(tags).length > 24 && (
                <div className="sp-sig__more">… 等 {Object.keys(tags).length} 项</div>
              )}
            </div>
          )}
          {widgets.length > 0 && (
            <div className="sp-tagtable" aria-label="HMI 绑定">
              <div className="sp-tagtable__title">HMI 绑定 · {widgets.length}</div>
              {widgets.slice(0, 16).map((w) => (
                <div key={w.id} className="sp-tagrow">
                  <span className="sp-tagrow__name">{w.title || w.id}</span>
                  <span className="sp-tagrow__type">{w.widget_type}</span>
                  <span className="sp-tagrow__addr">{w.plc_tag || "—"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          {/* 3. 解释卡 */}
          {showExplain && explanation && (
            <section className="sp-explain" aria-label="块解释">
              <div className="sp-explain__headline">
                <span className="sp-explain__headlinetext">{explanation.headline}</span>
                {onDeepExplain && (
                  <button
                    type="button"
                    className="sp-ghost sp-deepbtn"
                    disabled={deep.loading}
                    title="调用 LLM 生成工程师向深度解释（需网关配置 PLC_LLM_* 环境变量）"
                    onClick={() => void runDeepExplain()}
                  >
                    {deep.loading ? "解释中…" : "深度解释"}
                  </button>
                )}
              </div>
              {deep.error && <div className="sp-deep__hint">{deep.error}</div>}
              {deep.text && <div className="sp-deep__text">{deep.text}</div>}
              <div className="sp-explain__role">{explanation.role}</div>

              {explanation.keywords.length > 0 && (
                <div className="sp-kws">
                  {explanation.keywords.map((kw, i) => (
                    <span key={`${kw}#${i}`} className="sp-kw">
                      {kw}
                    </span>
                  ))}
                </div>
              )}

              {SIGNAL_GROUPS.map(({ key, label }) => {
                const list = explanation.signals[key] ?? [];
                if (list.length === 0) return null;
                const shown = list.slice(0, 8);
                return (
                  <div key={String(key)} className="sp-sig">
                    <div className="sp-sig__title">{label}</div>
                    {shown.map((entry, i) => {
                      const { name, type } = splitSignal(entry);
                      return (
                        <div key={`${entry}#${i}`} className="sp-sigrow">
                          <span className="sp-sigrow__name">{name}</span>
                          {type ? <span className="sp-dots" /> : null}
                          {type ? (
                            <span className="sp-sigrow__type">{type}</span>
                          ) : null}
                          {onRemoveVariable && block && (
                            <button
                              type="button"
                              className="sp-rowdel"
                              aria-label={`删除变量 ${name}`}
                              title={`删除变量 ${name}`}
                              onClick={() =>
                                onRemoveVariable(
                                  block.name,
                                  name.split(/\s*[(:]/)[0].trim(),
                                )
                              }
                            >
                              ×
                            </button>
                          )}
                        </div>
                      );
                    })}
                    {list.length > 8 && (
                      <div className="sp-sig__more">… 等 {list.length} 项</div>
                    )}
                  </div>
                );
              })}

              {explanation.networks.length > 0 && (
                <div className="sp-nets">
                  {explanation.networks.map((n) => (
                    <div key={n.id} className="sp-net">
                      <div className="sp-net__head">
                        <span className="sp-net__headtext">
                          NW{n.id} {n.title}
                        </span>
                        {onRemoveNetwork && block && (
                          <button
                            type="button"
                            className="sp-rowdel"
                            aria-label={`删除网络 NW${n.id}`}
                            title={`删除网络 NW${n.id}（${n.title}）`}
                            onClick={() => onRemoveNetwork(block.name, n.id)}
                          >
                            ×
                          </button>
                        )}
                      </div>
                      {n.summary ? (
                        <div className="sp-net__sum">{n.summary}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}

              {(explanation.callsBlocks.length > 0 ||
                explanation.calledByBlocks.length > 0 ||
                explanation.hmiBound.length > 0) && (
                <div className="sp-rels">
                  {explanation.callsBlocks.length > 0 && (
                    <div className="sp-rel">
                      调用 →{" "}
                      <span className="sp-rel__v">
                        {explanation.callsBlocks.join("、")}
                      </span>
                    </div>
                  )}
                  {explanation.calledByBlocks.length > 0 && (
                    <div className="sp-rel">
                      被调用 ←{" "}
                      <span className="sp-rel__v">
                        {explanation.calledByBlocks.join("、")}
                      </span>
                    </div>
                  )}
                  {explanation.hmiBound.length > 0 && (
                    <div className="sp-rel">
                      HMI 绑定：
                      <span className="sp-rel__v">
                        {explanation.hmiBound.join("、")}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* 4. 源码区：行号 + 逐行高亮 */}
          <div className="sp-code">
            {sclLines.map((line, i) => (
              <div
                key={i}
                ref={i === focusLineIdx ? focusLineRef : undefined}
                className={
                  i === focusLineIdx ? "sp-line sp-line--focus" : "sp-line"
                }
              >
                <span className="sp-line__no">{i + 1}</span>
                <code className="sp-line__code">{highlightSclLines(line)}</code>
              </div>
            ))}
          </div>

          {/* 5. 工具区 */}
          <footer className="sp-tools">
            <div className="sp-tools__row">
              <button
                type="button"
                className={`sp-ghost${openTool === "var" ? " is-on" : ""}`}
                aria-expanded={openTool === "var"}
                onClick={() => toggleTool("var")}
              >
                添加变量
              </button>
              {!isDb && (
                <button
                  type="button"
                  className={`sp-ghost${openTool === "net" ? " is-on" : ""}`}
                  aria-expanded={openTool === "net"}
                  onClick={() => toggleTool("net")}
                >
                  添加网络
                </button>
              )}
            </div>

            {openTool === "var" && (
              <form
                className="sp-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  submitVariable();
                }}
              >
                <div className="sp-form__row">
                  <label className="sp-field sp-field--grow">
                    <span className="sp-field__label">名称</span>
                    <input
                      className="sp-input"
                      value={varName}
                      onChange={(e) => setVarName(e.target.value)}
                      placeholder="如 Speed_Set"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                  <label className="sp-field sp-field--type">
                    <span className="sp-field__label">类型</span>
                    <input
                      className="sp-input"
                      value={varType}
                      onChange={(e) => setVarType(e.target.value)}
                      placeholder="Bool"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                  {!isDb && (
                    <label className="sp-field sp-field--sec">
                      <span className="sp-field__label">分区</span>
                      <select
                        className="sp-input"
                        value={varSection}
                        onChange={(e) => setVarSection(e.target.value)}
                      >
                        {SECTION_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                {nameInvalid && (
                  <div className="sp-err">
                    名称需以字母或下划线开头，仅可含字母、数字与下划线
                  </div>
                )}
                <div className="sp-form__actions">
                  <button
                    type="button"
                    className="sp-ghost"
                    onClick={() => setOpenTool(null)}
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="sp-btn"
                    disabled={!varFormValid}
                  >
                    添加
                  </button>
                </div>
              </form>
            )}

            {openTool === "net" && (
              <form
                className="sp-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  submitNetwork();
                }}
              >
                <label className="sp-field">
                  <span className="sp-field__label">网络标题</span>
                  <input
                    className="sp-input"
                    value={netTitle}
                    onChange={(e) => setNetTitle(e.target.value)}
                    placeholder={`可留空，默认 网络 ${block.networks.length + 1}`}
                    autoComplete="off"
                  />
                </label>
                <label className="sp-field">
                  <span className="sp-field__label">SCL 代码</span>
                  <textarea
                    className="sp-input sp-textarea"
                    rows={5}
                    spellCheck={false}
                    value={netText}
                    onChange={(e) => setNetText(e.target.value)}
                    placeholder={"IF #Start THEN\n    #Run := TRUE;\nEND_IF;"}
                  />
                </label>
                <div className="sp-form__actions">
                  <button
                    type="button"
                    className="sp-ghost"
                    onClick={() => setOpenTool(null)}
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="sp-btn"
                    disabled={!netFormValid}
                  >
                    添加
                  </button>
                </div>
              </form>
            )}
          </footer>
        </>
      )}
    </div>
  );
};
