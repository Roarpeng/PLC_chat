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
  zap_name?: string;
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
  mode?: string;
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

/**
 * 回写与重构核心 5 个子阶段视图定义（docs/plc_chat_v3_0.html Tab 5）:
 * 1) 静态安全门禁 (R1~R5 Linter 检查)
 * 2) 依赖拓扑排序 (Kahn Topological Sort)
 * 3) 极速批次回写 (Mega-Source BOM 打包写入)
 * 4) 增量软件编译 (TIA Incremental Compile)
 * 5) 智能错误自愈 (Structured Self-Healing)
 */
export const WRITEBACK_SUB_STAGES = [
  "static_gate",
  "topo_sort",
  "batch_write",
  "incremental_compile",
  "self_healing",
] as const;

export type WritebackSubStageKey = (typeof WRITEBACK_SUB_STAGES)[number];

export const WRITEBACK_STAGE_LABELS: Record<string, string> = {
  static_gate: "静态安全门禁 (R1~R5 Linter 检查)",
  topo_sort: "依赖拓扑排序 (Kahn Topological Sort)",
  batch_write: "极速批次回写 (Mega-Source BOM 打包写入)",
  incremental_compile: "增量软件编译 (TIA Incremental Compile)",
  self_healing: "智能错误自愈 (Structured Self-Healing)",
  // 别名与底层任务映射支持
  linter: "静态安全门禁 (R1~R5 Linter 检查)",
  prepare_work: "静态安全门禁 (R1~R5 Linter 检查)",
  precheck: "静态安全门禁 (R1~R5 Linter 检查)",
  refactor: "依赖拓扑排序 (Kahn Topological Sort)",
  open_project: "依赖拓扑排序 (Kahn Topological Sort)",
  write_plc: "极速批次回写 (Mega-Source BOM 打包写入)",
  write_hmi: "极速批次回写 (Mega-Source BOM 打包写入)",
  compile_plc: "增量软件编译 (TIA Incremental Compile)",
  compile_hmi: "增量软件编译 (TIA Incremental Compile)",
  compile: "增量软件编译 (TIA Incremental Compile)",
  fix_loop: "智能错误自愈 (Structured Self-Healing)",
  auto_fix: "智能错误自愈 (Structured Self-Healing)",
};

/** 状态文案映射（待开始、进行中、完成、已拦截、自愈中、已跳过、出错） */
export const STAGE_STATUS_TEXT: Record<string, string> = {
  pending: "待开始",
  running: "进行中…",
  ok: "完成",
  blocked: "已拦截",
  intercepted: "已拦截",
  healing: "自愈中",
  skipped: "已跳过",
  error: "出错",
};

export function getStageStatusText(status: string): string {
  return STAGE_STATUS_TEXT[status] ?? String(status ?? "");
}

/** 阶段默认技术说明 */
export const STAGE_DEFAULT_DETAILS: Record<string, string> = {
  static_gate: "校验符号作用域定界符、单线圈唯一性、CASE状态机规则及UTF-8 BOM头（R1~R5）",
  topo_sort: "Kahn 拓扑排序：按 UDT -> 被调用子块 -> 工站主FB -> 数据块排序输出",
  batch_write: "SHA-256增量过滤，单文件 Mega-Source 打包极速写入 TIA",
  incremental_compile: "调用 TIA Openness 执行增量编译并精准解析诊断日志",
  self_healing: "结构化抽取可用字段白名单，限制受控槽位精准修补并设熔断保护",
};

export interface WritebackStageView {
  key: WritebackSubStageKey;
  label: string;
  status: "pending" | "running" | "ok" | "skipped" | "error" | "blocked" | "intercepted" | "healing" | string;
  detail?: string;
  round?: number;
  maxRounds?: number;
}

export interface BuildWritebackSubStagesOptions {
  healingRound?: number;
  maxHealingRounds?: number;
  circuitBroken?: boolean;
  circuitBreakerAlert?: string;
  blockedReason?: string;
  compileError?: string;
}

/**
 * 将底层杂散的作业阶段（prepare_work, open_project, write_plc, compile_plc 等）
 * 或重构阶段结构化规整为工程师友好的 5 个标准子阶段视图。
 */
export function buildWritebackSubStages(
  rawStages?: Array<{ name: string; status: string; detail?: string; message?: string }> | null,
  options?: BuildWritebackSubStagesOptions,
): WritebackStageView[] {
  const list = Array.isArray(rawStages) ? rawStages : [];
  const mapByName: Record<string, { status: string; detail?: string }> = {};
  for (const s of list) {
    if (s && s.name) {
      mapByName[s.name] = {
        status: s.status,
        detail: s.detail || s.message,
      };
    }
  }

  // 1. static_gate
  let gateStatus = "pending";
  let gateDetail = STAGE_DEFAULT_DETAILS.static_gate;
  const precheck = mapByName.precheck || mapByName.prepare_work || mapByName.linter || mapByName.static_gate;
  if (precheck) {
    if (precheck.status === "error" || precheck.status === "blocked" || precheck.status === "intercepted") {
      gateStatus = "intercepted";
      gateDetail = options?.blockedReason || precheck.detail || "静态门禁规则校验未通过，已拦截回写";
    } else if (precheck.status === "running") {
      gateStatus = "running";
      gateDetail = "正在执行 R1~R5 内存级静态门禁校验…";
    } else if (precheck.status === "ok") {
      gateStatus = "ok";
      gateDetail = "静态门禁校验全部通过（R1~R5 无违例）";
    }
  }

  // 2. topo_sort
  let topoStatus = "pending";
  let topoDetail = STAGE_DEFAULT_DETAILS.topo_sort;
  const topo = mapByName.refactor || mapByName.open_project || mapByName.topo_sort;
  if (topo) {
    if (topo.status === "running") {
      topoStatus = "running";
      topoDetail = "正在计算 Kahn 依赖拓扑序，先 UDT 后 FB…";
    } else if (topo.status === "ok") {
      topoStatus = "ok";
      topoDetail = "拓扑依赖无环，定义顺序已对齐";
    } else if (topo.status === "error") {
      topoStatus = "error";
      topoDetail = topo.detail || "依赖分析失败，存在未知符号或循环引用";
    }
  }

  // 3. batch_write
  let writeStatus = "pending";
  let writeDetail = STAGE_DEFAULT_DETAILS.batch_write;
  const write = mapByName.write_plc || mapByName.batch_write || mapByName.mega_source;
  if (write) {
    if (write.status === "running") {
      writeStatus = "running";
      writeDetail = "Mega-Source BOM 外部源写入博途中…";
    } else if (write.status === "ok") {
      writeStatus = "ok";
      writeDetail = write.detail || "外部源批量回写完成";
    } else if (write.status === "error") {
      writeStatus = "error";
      writeDetail = write.detail || "外部源写入失败";
    }
  }

  // 4. incremental_compile
  let compileStatus = "pending";
  let compileDetail = STAGE_DEFAULT_DETAILS.incremental_compile;
  const compile = mapByName.compile_plc || mapByName.compile || mapByName.incremental_compile;
  if (compile) {
    if (compile.status === "running") {
      compileStatus = "running";
      compileDetail = "调用博途增量编译中…";
    } else if (compile.status === "ok") {
      compileStatus = "ok";
      compileDetail = compile.detail || "增量编译通过（0 Errors）";
    } else if (compile.status === "error") {
      compileStatus = "error";
      compileDetail = options?.compileError || compile.detail || "编译发现错误，待智能自愈处理";
    } else if (compile.status === "skipped") {
      compileStatus = "skipped";
      compileDetail = compile.detail || "未触发编译";
    }
  }

  // 5. self_healing
  let healStatus = "pending";
  let healDetail = STAGE_DEFAULT_DETAILS.self_healing;
  const heal = mapByName.fix_loop || mapByName.auto_fix || mapByName.self_healing;
  if (options?.circuitBroken) {
    healStatus = "error";
    healDetail = options.circuitBreakerAlert || "自愈熔断保护跳闸：同类错误连续出现达到阈值，已停止重试";
  } else if (options?.healingRound && options.healingRound > 0) {
    healStatus = "healing";
    const maxR = options.maxHealingRounds || 3;
    healDetail = `正在尝试第 ${options.healingRound}/${maxR} 轮自愈：修复 UDT 字段引用...`;
  } else if (heal) {
    if (heal.status === "running" || heal.status === "healing") {
      healStatus = "healing";
      healDetail = heal.detail || "正在尝试自愈：分析报错并生成受控槽位补丁…";
    } else if (heal.status === "ok") {
      healStatus = "ok";
      healDetail = heal.detail || "错误已自愈修复并通过复检";
    } else if (heal.status === "skipped") {
      healStatus = "skipped";
      healDetail = heal.detail || "编译通过，无需自愈";
    } else if (heal.status === "error") {
      healStatus = "error";
      healDetail = heal.detail || "自愈未能完全解决报错";
    }
  }

  // 如果后续阶段已启动，前序阶段推导完成
  if (topoStatus === "ok" || topoStatus === "running") {
    if (gateStatus === "pending") gateStatus = "ok";
  }
  if (writeStatus === "ok" || writeStatus === "running") {
    if (gateStatus === "pending") gateStatus = "ok";
    if (topoStatus === "pending") topoStatus = "ok";
  }
  if (compileStatus === "ok" || compileStatus === "running" || compileStatus === "error") {
    if (gateStatus === "pending") gateStatus = "ok";
    if (topoStatus === "pending") topoStatus = "ok";
    if (writeStatus === "pending") writeStatus = "ok";
  }
  if (compileStatus === "ok" && healStatus === "pending") {
    healStatus = "skipped";
    healDetail = "编译通过，无需自愈";
  }

  return [
    { key: "static_gate", label: WRITEBACK_STAGE_LABELS.static_gate, status: gateStatus, detail: gateDetail },
    { key: "topo_sort", label: WRITEBACK_STAGE_LABELS.topo_sort, status: topoStatus, detail: topoDetail },
    { key: "batch_write", label: WRITEBACK_STAGE_LABELS.batch_write, status: writeStatus, detail: writeDetail },
    { key: "incremental_compile", label: WRITEBACK_STAGE_LABELS.incremental_compile, status: compileStatus, detail: compileDetail },
    {
      key: "self_healing",
      label: WRITEBACK_STAGE_LABELS.self_healing,
      status: healStatus,
      detail: healDetail,
      round: options?.healingRound,
      maxRounds: options?.maxHealingRounds,
    },
  ];
}

/** 格式化自愈轮次与状态文案 */
export function formatSelfHealProgress(
  round: number,
  maxRounds = 3,
  actionDesc?: string,
  circuitBroken = false,
): string {
  if (circuitBroken) {
    return "自愈已熔断：同类错误连续出现达到阈值，已停止自动重试";
  }
  return `正在尝试第 ${round}/${maxRounds} 轮自愈${actionDesc ? `：${actionDesc}` : ""}`;
}

/* ---- 阶段进度视图模型(供 ChatDock 进度卡渲染) ---- */

/** 单阶段视图:label 已中文化,status 原样(联态放宽) */
export type PipelineStageView = {
  key: string;
  label: string;
  status: RefactorPipelineStage["status"];
  detail?: string;
};

/** stages → 视图模型(空安全;未知段名原样透出,与 pipelineProgressText 同口径) */
export function pipelineStageViews(
  stages: RefactorPipelineStage[] | null | undefined,
  stageNameMap?: Record<string, string>,
): PipelineStageView[] {
  const names = stageNameMap ?? REFACTOR_STAGE_NAMES;
  const list = Array.isArray(stages) ? stages : [];
  return list.map((s) => ({
    key: String(s?.name ?? ""),
    label: names[s?.name] ?? String(s?.name ?? ""),
    status: s?.status ?? "pending",
    detail: typeof s?.detail === "string" ? s.detail : undefined,
  }));
}

/** 当前活跃阶段:优先 running/healing;无 running 取最后一个非 pending(收尾态可见);全空 → null */
export function pipelineActiveStage(views: Array<{ key?: string; status?: string; [k: string]: any }>): any | null {
  const running = views.find((v) => v.status === "running" || v.status === "healing");
  if (running) return running;
  for (let i = views.length - 1; i >= 0; i--) {
    if (views[i].status !== "pending") return views[i];
  }
  return null;
}

/** 全部阶段抵达终态(ok/skipped/error/blocked/intercepted) → true(进度卡据此停在完成态) */
export function pipelineSettled(views: Array<{ status?: string }>): boolean {
  return (
    views.length > 0 &&
    views.every((v) => {
      const s = v?.status ?? "";
      return s === "ok" || s === "skipped" || s === "error" || s === "blocked" || s === "intercepted";
    })
  );
}

/**
 * 生成进度清单文本(每段一行,供聊天占位消息原位刷新):
 * "▸ 重构 完成 / ▸ 自动修复 进行中… / ▸ 编译 待开始"。
 * skipped/error/blocked/intercepted/healing 附带 detail 说明;stages 为空时给启动占位文案。
 */
export function pipelineProgressText(
  stages: Array<{ name?: string; label?: string; status?: string; detail?: string }> | null | undefined,
  stageNameMap?: Record<string, string>,
): string {
  const names = stageNameMap ?? REFACTOR_STAGE_NAMES;
  const list = Array.isArray(stages) ? stages : [];
  if (!list.length) return "已启动重构流水线…";
  return list
    .map((s) => {
      const rawName = s?.name || (s as any)?.key || "";
      const label = s?.label || (names[rawName] ?? rawName);
      const status = s?.status ?? "pending";
      const statusText = STAGE_STATUS_TEXT[status] ?? String(status);
      const detail = typeof s?.detail === "string" && s.detail.trim() ? s.detail.trim() : "";
      if (detail && (status === "skipped" || status === "error" || status === "blocked" || status === "intercepted" || status === "healing")) {
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

/** 博途原生工程归档下载地址(.zap19 / .zap, 拼 GATEWAY_BASE) */
export function refactorPipelineZapUrl(jobId: string): string {
  return `${GATEWAY_BASE}/api/v1/plc/canvas/refactor-pipeline/${encodeURIComponent(jobId)}/zap`;
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
    const zapName = pkg.zap_name || "工程归档包 (.zap19)";
    const sizeNote =
      typeof pkg.size_bytes === "number"
        ? `（${(pkg.size_bytes / 1024).toFixed(1)} KB · ${pkg.file_count ?? "?"} 个文件）`
        : "";
    lines.push(
      "",
      `#### 交付物下载（博途直接导入）`,
      `- [下载交付包 (.zip)](${refactorPipelinePackageUrl(opts.jobId)})${sizeNote} —— **解压即得 ${zapName} 归档**，内含全量 SCL 源码、IO 保留表与编译收据。`,
      `- [直接下载博途工程归档 (${zapName})](${refactorPipelineZapUrl(opts.jobId)}) —— 西门子 TIA Portal 原生归档，可在博途中通过「项目 -> 恢复 (Retrieve)」直接打开。`,
    );
  }

  lines.push(
    "",
    "画布已即时切换为标准结构视图。你可以点击任意块查看生成的 SCL 源码，或直接通过自然语言向我描述工艺需求！",
  );
  return lines.join("\n");
}

/* ---- 打包/下载分支的交付包消息（实事求是：一切数值来自真实网关响应） ---- */

/** 编译结论：只从真实 job 详情自适应读取，缺失为 null（前端绝不写死 0 Errors）。 */
export type JobExportCompile = {
  compiled?: boolean;
  errors?: number;
  warnings?: number;
  note?: string;
};

/**
 * 从 GET /jobs/{id} 的真实载荷里自适应提取编译结论。
 * 解析作业本身通常不含编译结论（那是回写/重构流水线收据），找不到就返回 null，
 * 由消息层如实说明"网关未返回编译结论"，绝不编造 Errors/Warnings 数字。
 */
export function extractCompileFromJobDetail(detail: unknown): JobExportCompile | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, unknown>;
  const candidates = [d.report, d.writeback, d.changeset, d.compile];
  for (const raw of candidates) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    const compile = (
      r.compile && typeof r.compile === "object" ? r.compile : r
    ) as Record<string, unknown>;
    const hasCompiled = typeof compile.compiled === "boolean";
    const errors = Array.isArray(compile.errors) ? compile.errors.length : undefined;
    const warnings =
      typeof compile.warnings_count === "number"
        ? compile.warnings_count
        : Array.isArray(compile.warnings)
          ? compile.warnings.length
          : undefined;
    if (hasCompiled || errors !== undefined || warnings !== undefined) {
      return {
        ...(hasCompiled ? { compiled: compile.compiled as boolean } : {}),
        ...(errors !== undefined ? { errors } : {}),
        ...(warnings !== undefined ? { warnings } : {}),
        ...(typeof compile.skipped_reason === "string"
          ? { note: compile.skipped_reason }
          : {}),
      };
    }
  }
  return null;
}

/** 打包分支消息的真实数据来源（无任何写死结论/数字/包名/路径）。 */
export type JobExportView = {
  jobId: string;
  available: boolean;
  /** 不存在时的真实原因（来自探测响应 / 网关错误码 / 网络错误）。 */
  reason?: string | null;
  /** 来自 Content-Disposition 的真实包名；null 表示网关未返回文件名。 */
  filename?: string | null;
  /** 由 gatewayBase() 拼出的真实导出端点 URL。 */
  exportUrl?: string;
  /** 来自 GET /jobs/{id} 的真实块数；null 表示网关未返回。 */
  blockCount?: number | null;
  /** 来自 GET /jobs/{id} 的真实源码文件数；null 表示网关未返回。 */
  fileCount?: number | null;
  /** 来自 GET /jobs/{id} 的真实编译结论；null 表示未返回。 */
  compile?: JobExportCompile | null;
  status?: string | null;
  projectName?: string | null;
};

/**
 * 构建「打包/下载」分支的 Markdown 消息。
 * 块数/文件数/编译结果/包名/下载链接一律来自真实响应；资源不存在或字段缺失时
 * 如实说明，绝不写死编译结论数字、块数、包名或本机绝对路径。
 */
export function buildJobExportMessage(view: JobExportView): string {
  if (!view.available) {
    const reason = (view.reason || "").trim() || "网关未返回可下载交付包";
    return [
      "### 当前作业暂无可下载交付包",
      "",
      `原因：${reason}`,
      "",
      `> 作业号：\`${view.jobId}\`。以上依据网关真实响应，未附带任何编译结论或交付文件清单；请先导入并解析工程、完成回写/打包后再请求交付包。`,
    ].join("\n");
  }
  const lines: string[] = ["### 交付包（来自网关真实导出）", ""];
  lines.push(`- **作业号**：\`${view.jobId}\``);
  if (view.projectName) lines.push(`- **工程**：${view.projectName}`);
  if (view.status) lines.push(`- **作业状态**：${view.status}`);
  lines.push(
    view.filename
      ? `- **交付包名**：\`${view.filename}\`（来自导出响应 Content-Disposition）`
      : "- **交付包名**：网关未返回文件名",
  );
  lines.push(
    typeof view.blockCount === "number"
      ? `- **块数**：${view.blockCount}（来自作业详情）`
      : "- **块数**：网关未返回块数",
  );
  lines.push(
    typeof view.fileCount === "number"
      ? `- **源码文件数**：${view.fileCount}（来自作业详情）`
      : "- **源码文件数**：网关未返回文件数",
  );
  const c = view.compile;
  if (!c) {
    lines.push("- **编译结果**：网关 job 详情未返回编译结论，本次不给 Errors/Warnings 数字");
  } else {
    const errs = typeof c.errors === "number" ? c.errors : null;
    const warns = typeof c.warnings === "number" ? c.warnings : null;
    const compiled =
      c.compiled === true ? "已编译" : c.compiled === false ? "未编译" : "编译态未注明";
    const note = c.note ? `（${c.note}）` : "";
    const counts =
      errs !== null || warns !== null
        ? ` — Errors ${errs ?? "?"} / Warnings ${warns ?? "?"}`
        : "";
    lines.push(`- **编译结果**：${compiled}${note}${counts}（来自作业详情真实字段）`);
  }
  lines.push("", "#### 下载");
  lines.push(
    view.exportUrl
      ? `- [下载真实导出包](${view.exportUrl})`
      : "- 网关未提供导出链接",
  );
  lines.push(
    "",
    "> 以上块数、文件数、编译结果与包名均来自网关真实响应；未返回的数据已明确标注，不做任何推断。",
  );
  return lines.join("\n");
}
