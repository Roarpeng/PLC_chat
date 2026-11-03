/**
 * 重构流水线(POST /api/v1/plc/canvas/refactor-pipeline + 轮询)的纯函数层:
 * DTO 契约类型、意图解析、阶段进度文案、结果汇总消息、交付包链接。
 *
 * 网络请求留在 App.tsx(与 /canvas/* 其余端点同约定,见 lib/plcGateway.ts
 * 头注释),本模块不发起任何 IO —— vitest 无 mock 即可全覆盖。
 *
 * 后端契约(与流水线端点一字不差):
 * - stages 固定五段:refactor / auto_fix / compile / fix_loop / package;
 * - 作业收敛状态 ∈ {ok, error, cancelled},running 为进行中;
 * - result.compile.compiled=false 时必须如实展示 skipped_reason,
 *   前端绝不写死"0 Errors, 0 Warnings"(旧同步路径的历史 bug)。
 */
import { GATEWAY_BASE } from "../lib/plcGateway";
import type { CanvasStateData } from "../canvas/types";

/* ---- DTO 契约类型 ---- */

/** 流水线单阶段(status 联合放宽到 string:后端新增态不至于让前端崩) */
export type RefactorPipelineStage = {
  name: string;
  status: "pending" | "running" | "ok" | "skipped" | "error" | string;
  detail?: string;
};

/** 编译阶段产物:compiled=false 时 skipped_reason 说明原因 */
export type RefactorPipelineCompile = {
  compiled?: boolean;
  skipped_reason?: string;
  errors?: string[];
  warnings_count?: number;
};

/** 打包阶段产物元信息 */
export type RefactorPipelinePackage = {
  size_bytes?: number;
  file_count?: number;
};

/** 重构报告(旧同步 /canvas/refactor 与流水线 result.report 同构,字段自适应读取) */
export type RefactorPipelineReport = {
  target_unit_name?: string;
  ems?: Array<{ name?: string; steps_count?: number; cms_count?: number }>;
  af_blocks_created?: string[];
  af_blocks_count?: number;
  /** 无法自动映射的块:元素可能是纯块名或 { name } 对象,自适应取名 */
  pending_blocks?: Array<string | { name?: string }>;
  io_retention?: { total_ios?: number; retained_ios?: number; percentage?: number };
  interlocks?: unknown[];
  lint_findings?: Array<{
    rule_id?: string;
    severity?: string;
    block_name?: string;
    message?: string;
  }>;
  [key: string]: unknown;
};

/** 等价性核对摘要(result.equivalence,后端 equivalence.py 生成) */
export type RefactorPipelineEquivalence = {
  io_preserved?: boolean;
  preserved_count?: number;
  dropped_count?: number;
  added_count?: number;
  dropped?: string[];
  statement_delta_pct?: number | null;
};

/** 作业收敛产物(result 字段) */
export type RefactorPipelineResult = {
  canvas?: CanvasStateData | null;
  report?: RefactorPipelineReport | null;
  compile?: RefactorPipelineCompile | null;
  equivalence?: RefactorPipelineEquivalence | null;
  package?: RefactorPipelinePackage | null;
  warnings?: string[];
};

/** GET /api/v1/plc/canvas/refactor-pipeline/{job_id} 的整体载荷 */
export type RefactorPipelineJob = {
  id: string;
  status: "running" | "ok" | "error" | "cancelled" | string;
  stage?: string | null;
  stages?: RefactorPipelineStage[];
  result?: RefactorPipelineResult | null;
  error?: string | null;
};

/** POST /api/v1/plc/canvas/refactor-pipeline 请求体 */
export type RefactorPipelineRequestBody = {
  canvas: CanvasStateData;
  project_name?: string;
  do_compile?: boolean;
  auto_fix?: boolean;
};

/* ---- 意图解析 ---- */

export type RefactorIntent = {
  refactor: boolean;
  wantCompile: boolean;
  wantPackage: boolean;
};

/** 重构命中词(大小写不敏感,兼容旧路径的 toLowerCase 判定);"不要编译/不编译/跳过编译"关闭编译 */
const REFACTOR_RE = /重构|refactor/i;
const PACKAGE_RE = /打包|下载|交付|压缩包|zip|zap/i;
const NO_COMPILE_RE = /不(?:要)?编译|跳过编译/;

/**
 * 从自然语言 prompt 解析流水线意图。
 * - refactor:命中 /重构|refactor/;
 * - wantCompile:默认 true,出现"不编译/不要编译/跳过编译"字样才关;
 * - wantPackage:命中 /打包|下载|交付|压缩包|zip|zap/。
 */
export function parseRefactorIntent(prompt: string): RefactorIntent {
  const p = prompt ?? "";
  return {
    refactor: REFACTOR_RE.test(p),
    wantCompile: !NO_COMPILE_RE.test(p),
    wantPackage: PACKAGE_RE.test(p),
  };
}

/* ---- 阶段进度文案 ---- */

/** 阶段名 → 中文标签(契约五段 + 未知段名原样透出) */
export const REFACTOR_STAGE_NAMES: Record<string, string> = {
  refactor: "重构",
  auto_fix: "自动修复",
  compile: "编译",
  fix_loop: "编译修复循环",
  package: "打包",
};

const STAGE_STATUS_TEXT: Record<string, string> = {
  pending: "待开始",
  running: "进行中…",
  ok: "完成",
  skipped: "已跳过",
  error: "出错",
};

/**
 * 生成进度清单文本(每段一行,供聊天占位消息原位刷新):
 * "▸ 重构 完成 / ▸ 自动修复 进行中… / ▸ 编译 待开始"。
 * skipped/error 附带 detail(如跳过原因);stages 为空时给启动占位文案。
 */
export function pipelineProgressText(
  stages: RefactorPipelineStage[] | null | undefined,
  stageNameMap?: Record<string, string>,
): string {
  const names = stageNameMap ?? REFACTOR_STAGE_NAMES;
  const list = Array.isArray(stages) ? stages : [];
  if (!list.length) return "已启动重构流水线…";
  return list
    .map((s) => {
      const label = names[s.name] ?? s.name;
      const statusText = STAGE_STATUS_TEXT[s.status] ?? String(s.status ?? "");
      const detail = typeof s.detail === "string" && s.detail.trim() ? s.detail.trim() : "";
      if (detail && (s.status === "skipped" || s.status === "error")) {
        return `▸ ${label} ${statusText}（${detail}）`;
      }
      return `▸ ${label} ${statusText}`.trimEnd();
    })
    .join("\n");
}

/* ---- 结果汇总消息 ---- */

/** 交付包下载地址(直接作 Markdown 链接用,拼 GATEWAY_BASE) */
export function refactorPipelinePackageUrl(jobId: string): string {
  return `${GATEWAY_BASE}/api/v1/plc/canvas/refactor-pipeline/${encodeURIComponent(jobId)}/package`;
}

/** pending_blocks 自适应取名:元素为纯块名或 { name } 对象,过滤空值 */
function pendingBlockNames(rpt: RefactorPipelineReport): string[] {
  const raw = Array.isArray(rpt.pending_blocks) ? rpt.pending_blocks : [];
  return raw
    .map((p) => (typeof p === "string" ? p : String(p?.name ?? "")))
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * 流水线收敛后的最终 Markdown 消息:
 * - 报告摘要(EM 数/生成块数/I-O 保全/联锁/静态合规,全部自适应读取,缺失明说);
 * - pending_blocks:数量 + 前 8 个块名,明确"无法自动映射,保留原样待人工确认";
 * - 编译结果:compiled=false 如实显示 skipped_reason 或"未编译",绝不写死 0 错误;
 *   errors 前 10 条逐条列出;
 * - 流水线 warnings 前 5 条;
 * - 交付包下载链接(传 jobId 才有,旧同步路径没有)。
 */
export function pipelineResultMessage(
  result: RefactorPipelineResult | null | undefined,
  opts?: { jobId?: string },
): string {
  const r = result ?? {};
  const rpt = r.report ?? {};
  const ems = Array.isArray(rpt.ems) ? rpt.ems : [];
  const afCreated = Array.isArray(rpt.af_blocks_created) ? rpt.af_blocks_created : [];
  const afCount =
    afCreated.length || (typeof rpt.af_blocks_count === "number" ? rpt.af_blocks_count : 0);
  const io = rpt.io_retention ?? {};
  const interlocks = Array.isArray(rpt.interlocks) ? rpt.interlocks.length : 0;
  const findings = Array.isArray(rpt.lint_findings) ? rpt.lint_findings : [];
  const lintErrors = findings.filter((f) => String(f.severity ?? "").toLowerCase() === "error").length;
  const lintWarnings = findings.filter((f) => String(f.severity ?? "").toLowerCase() === "warning").length;

  const lines: string[] = ["### 西门子标准重构完成", "", "工程已重构为官方标准的模块化结构："];
  lines.push(`- **主单元 (Unit)**: \`${rpt.target_unit_name || "U1"}\``);
  const emLines = ems
    .map((e) => `  - **${e.name ?? "?"}**: ${e.steps_count ?? 0} 个步序，${e.cms_count ?? 0} 个控制模块 (CM)`);
  lines.push(
    `- **装备模块 (Equipment Modules)**: 共 ${ems.length} 个标准 EM${emLines.length ? `\n${emLines.join("\n")}` : ""}`,
  );
  lines.push(`- **标准块生成**: ${afCount} 个纯 SCL 官方规范块`);
  if (rpt.io_retention) {
    lines.push(`- **物理 I/O 保全**: ${io.retained_ios ?? 0}/${io.total_ios ?? 0} (${io.percentage ?? 100}%)`);
  }
  lines.push(`- **安全联锁保全**: ${interlocks} 处联锁表达式已注入控制节点`);
  // 静态合规:如实读 lint_findings 计数;报告缺失时明说,绝不写死 0/0
  lines.push(
    Array.isArray(rpt.lint_findings)
      ? `- **静态合规审查**: ${lintErrors} Errors, ${lintWarnings} Warnings`
      : `- **静态合规审查**: 报告未返回审查数据`,
  );
  findings.slice(0, 5).forEach((f) => {
    const where = f.block_name ? `${f.block_name}：` : "";
    lines.push(`  - [${f.severity ?? "?"}] ${where}${f.message || f.rule_id || ""}`.trimEnd());
  });

  const pending = pendingBlockNames(rpt);
  if (pending.length) {
    const shown = pending.slice(0, 8).join("、");
    lines.push(
      "",
      `**以下 ${pending.length} 个块无法自动映射,保留原样待人工确认**：${shown}${pending.length > 8 ? " 等" : ""}`,
    );
  }

  const compile = r.compile;
  const errs = compile && Array.isArray(compile.errors) ? compile.errors : [];
  lines.push("", "#### 编译结果");
  if (compile && compile.compiled === true) {
    lines.push(
      errs.length
        ? `- **西门子官方编译**: 未通过 — ${errs.length} Errors / ${compile.warnings_count ?? 0} Warnings`
        : `- **西门子官方编译**: 已通过 — ${errs.length} Errors / ${compile.warnings_count ?? 0} Warnings`,
    );
    errs.slice(0, 10).forEach((e, i) => lines.push(`  ${i + 1}. ${e}`));
  } else {
    const reason = (compile?.skipped_reason ?? "").trim();
    lines.push(`- **西门子官方编译**: 未编译${reason ? `（${reason}）` : ""}`);
  }

  // 等价性核对(文本级):IO 地址保全与语句数变化,缺失时不出小节
  const eqv = r.equivalence;
  if (eqv && typeof eqv === "object") {
    lines.push("", "#### 等价性核对（文本级）");
    const dropped = Array.isArray(eqv.dropped) ? eqv.dropped : [];
    const verdict =
      eqv.dropped_count === 0
        ? "全部旧地址仍在交付物中"
        : `${dropped.slice(0, 5).join("、")}${(eqv.dropped_count ?? 0) > 5 ? " 等" : ""}`;
    lines.push(
      `- **IO 地址保全**: preserved ${eqv.preserved_count ?? 0} / dropped ${eqv.dropped_count ?? 0} / added ${eqv.added_count ?? 0}（${verdict}）`,
    );
    if (typeof eqv.statement_delta_pct === "number") {
      lines.push(`- **语句数变化**: ${eqv.statement_delta_pct >= 0 ? "+" : ""}${eqv.statement_delta_pct.toFixed(1)}%`);
    }
    lines.push("- 口径：文本级/地址级核对，非行为等价性证明（详见包内 equivalence_report.json）");
  }

  const warns = (Array.isArray(r.warnings) ? r.warnings : [])
    .filter((w) => typeof w === "string" && w.trim());
  if (warns.length) {
    lines.push("", "#### 流水线提醒");
    warns.slice(0, 5).forEach((w, i) => lines.push(`${i + 1}. ${w.trim()}`));
  }

  if (opts?.jobId) {
    const pkg = r.package ?? {};
    const sizeNote =
      typeof pkg.size_bytes === "number"
        ? `（${(pkg.size_bytes / 1024).toFixed(1)} KB · ${pkg.file_count ?? "?"} 个文件）`
        : "";
    lines.push("", `[下载交付包 (.zip)](${refactorPipelinePackageUrl(opts.jobId)})${sizeNote}`);
  }

  lines.push(
    "",
    "画布已即时切换为标准结构视图。你可以点击任意块查看生成的 SCL 源码，或直接通过自然语言向我描述工艺需求！",
  );
  return lines.join("\n");
}
