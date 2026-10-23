import { useEffect, useMemo, useRef, useState, type FC } from "react";
import type { CanvasBlockData } from "../canvas/types";
import { renderBlockScl } from "../canvas/sclRender";
import {
  SOURCE_KINDS,
  fetchSourceArtifact,
  mockArtifact,
  resolveActivePlcJobId,
  type SourceArtifact,
  type SourceKind,
} from "../state/sourceCompare";
import "./sourcecompare.css";

/* ==========================================================================
   SourceCompareDrawer — 块详情「查看原始源码」对比抽屉（契约 15 §5）
   打开才挂载（懒加载）：左侧服务端工件（FlgNet XML 默认折叠 / 直译 SCL /
   归约追踪，顶部小型 kind 切换），右侧当前画布块 SCL；
   网关工件 404 / 不可达 → 内置电机启保停示例回退（origin 徽标提示），
   Esc / 遮罩 / × 关闭。只读展示：内容进 <pre>，不进任何受控输入。
   ========================================================================== */

export interface SourceCompareDrawerProps {
  /** 要对比的块（父层保证非空才渲染） */
  block: CanvasBlockData;
  /** 当前画布工程名（解析活跃 PLC 作业用） */
  projectName: string;
  onClose(): void;
}

/** 左侧工件的加载状态（按 kind 缓存，切换回来不重复拉取） */
type LeftState = {
  status: "idle" | "loading" | "ready";
  artifact: SourceArtifact | null;
};

const IDLE: LeftState = { status: "idle", artifact: null };

const initialLeft = (): Record<SourceKind, LeftState> => ({
  flgnet_xml: IDLE,
  literal_scl: IDLE,
  ast_trace: IDLE,
});

/** 左栏标题（kind 相关） */
const KIND_PANE_TITLES: Record<SourceKind, string> = {
  flgnet_xml: "FlgNet XML（原始导入）",
  literal_scl: "直译 SCL（1:1 布尔直译）",
  ast_trace: "归约追踪（ast_trace）",
};

/** 左栏默认折叠策略：XML 长、默认折叠；两种文本视图默认展开 */
const DEFAULT_COLLAPSED: Record<SourceKind, boolean> = {
  flgnet_xml: true,
  literal_scl: false,
  ast_trace: false,
};

const countLines = (text: string): number =>
  text.length ? text.replace(/\n$/, "").split("\n").length : 0;

export const SourceCompareDrawer: FC<SourceCompareDrawerProps> = ({
  block,
  projectName,
  onClose,
}) => {
  const [kind, setKind] = useState<SourceKind>("flgnet_xml");
  const [left, setLeft] = useState<Record<SourceKind, LeftState>>(initialLeft);
  const [collapsed, setCollapsed] = useState<Record<SourceKind, boolean>>(DEFAULT_COLLAPSED);
  /** 活跃 PLC 作业 id：打开时解析一次（null = 无 ready 作业，直接走 mock） */
  const jobIdRef = useRef<string | null | undefined>(undefined);
  /** left 状态镜像：kind 切回时免重复拉取（读最新值，不进依赖） */
  const leftRef = useRef(left);
  useEffect(() => {
    leftRef.current = left;
  }, [left]);

  /* Esc 关闭（与 DrillDownPanel 同款） */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /* 打开时才解析活跃 job（一次），随后按需拉当前 kind 的工件；已缓存/在途的 kind 跳过 */
  useEffect(() => {
    let alive = true;
    const load = async () => {
      if (jobIdRef.current === undefined) {
        jobIdRef.current = await resolveActivePlcJobId(projectName);
        if (!alive) return;
      }
      if (leftRef.current[kind].status !== "idle") return;
      setLeft((prev) => ({ ...prev, [kind]: { status: "loading", artifact: null } }));
      const artifact = await fetchSourceArtifact(block.name, kind, {
        jobId: jobIdRef.current,
      });
      if (!alive) return;
      setLeft((prev) => ({ ...prev, [kind]: { status: "ready", artifact } }));
    };
    void load();
    return () => {
      alive = false;
      // 快速切换 kind 时中止挂起结果：在途的 loading 复位为 idle，
      // 切回该 kind 才能重新拉取，避免永远停在「加载中…」
      setLeft((prev) =>
        prev[kind].status === "loading" ? { ...prev, [kind]: IDLE } : prev,
      );
    };
  }, [block.name, kind, projectName]);

  const leftState = left[kind];
  const leftArtifact = leftState.artifact;

  /* 右栏：当前画布块的 SCL（与主视图同一渲染源）；空块退内置示例 */
  const currentScl = useMemo(() => {
    const text = renderBlockScl(block).trim();
    return text || mockArtifact(block.name, "literal_scl").content;
  }, [block]);

  const leftText = leftArtifact?.content ?? "";
  const origin = leftArtifact?.origin ?? null;

  return (
    <div
      className="sc-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="sc-card"
        role="dialog"
        aria-modal="true"
        aria-label={`${block.block_type} ${block.name} 原始源码对比`}
      >
        <header className="sc-head">
          <div className="sc-title">
            <span className="sc-title__type">[{block.block_type}]</span>
            <span className="sc-title__name">&quot;{block.name}&quot;</span>
            <span className="sc-title__suffix">· 原始源码对比</span>
          </div>
          <div className="sc-kindtabs" role="tablist" aria-label="源码工件类别">
            {SOURCE_KINDS.map((k) => (
              <button
                key={k.kind}
                type="button"
                role="tab"
                aria-selected={kind === k.kind}
                className={kind === k.kind ? "is-active" : ""}
                onClick={() => setKind(k.kind)}
              >
                {k.label}
              </button>
            ))}
          </div>
          <button type="button" className="sc-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="sc-body">
          {/* 左：服务端工件（按需懒加载） */}
          <div className="sc-pane" role="tabpanel" aria-label={KIND_PANE_TITLES[kind]}>
            <div className="sc-pane__head">
              <button
                type="button"
                className="sc-pane__toggle"
                aria-expanded={!collapsed[kind]}
                onClick={() =>
                  setCollapsed((prev) => ({ ...prev, [kind]: !prev[kind] }))
                }
                title={collapsed[kind] ? "展开内容" : "折叠内容"}
              >
                <span className={"sc-chev" + (collapsed[kind] ? "" : " sc-chev--open")}>›</span>
                <span className="sc-pane__label">{KIND_PANE_TITLES[kind]}</span>
              </button>
              <span className="sc-pane__meta">
                {leftState.status !== "ready" ? (
                  <span className="sc-origin">加载中…</span>
                ) : (
                  <>
                    {origin === "mock" && <span className="sc-origin sc-origin--mock">内置示例</span>}
                    {leftText && <span>{countLines(leftText)} 行</span>}
                  </>
                )}
              </span>
            </div>
            {!collapsed[kind] && (
              <div className="sc-pane__scroll">
                {leftState.status !== "ready" ? (
                  <div className="sc-hint">正在按需拉取（未就绪时展示内置电机启保停示例）…</div>
                ) : (
                  <pre className="sc-pre">{leftText}</pre>
                )}
              </div>
            )}
          </div>

          {/* 右：当前画布 SCL（只读） */}
          <div className="sc-pane" role="tabpanel" aria-label="当前 SCL">
            <div className="sc-pane__head">
              <span className="sc-pane__label">当前 SCL（画布）</span>
              <span className="sc-pane__meta">{countLines(currentScl)} 行</span>
            </div>
            <div className="sc-pane__scroll">
              <pre className="sc-pre">{currentScl}</pre>
            </div>
          </div>
        </div>

        <footer className="sc-foot">
          <span className="sc-foot__stats">
            {origin === "gateway"
              ? `网关工件 · job ${leftArtifact?.job_id ?? "?"}`
              : "网关工件未就绪，已回退内置示例"}
          </span>
          <span className="sc-foot__hint">Esc / 点击遮罩关闭 · 左：服务端原始工件 · 右：当前画布 SCL</span>
        </footer>
      </section>
    </div>
  );
};
