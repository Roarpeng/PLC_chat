import { describe, expect, it } from "vitest";
import appSource from "../App.tsx?raw";
import {
  REFACTOR_STAGE_NAMES,
  buildJobExportMessage,
  buildWritebackSubStages,
  extractCompileFromJobDetail,
  formatSelfHealProgress,
  getStageStatusText,
  parseRefactorIntent,
  pipelineActiveStage,
  pipelineProgressText,
  pipelineResultMessage,
  pipelineSettled,
  pipelineStageViews,
  refactorPipelinePackageUrl,
  type JobExportView,
  type RefactorPipelineResult,
  type RefactorPipelineStage,
} from "./refactorPipeline";
import {
  formatPlcCitations,
  gatewayBase,
  parseContentDispositionFilename,
} from "../lib/plcGateway";

describe("pipelineStageViews / pipelineActiveStage / pipelineSettled(进度卡视图层)", () => {
  it("阶段名中文化,未知段名原样透出,detail 透传", () => {
    const views = pipelineStageViews([
      { name: "refactor", status: "ok" },
      { name: "compile", status: "running", detail: "TIA 编译中" },
      { name: "custom_stage", status: "pending" },
    ]);
    expect(views.map((v) => v.label)).toEqual(["重构", "编译", "custom_stage"]);
    expect(views[1].status).toBe("running");
    expect(views[1].detail).toBe("TIA 编译中");
    expect(views[2].status).toBe("pending");
  });

  it("空输入空安全:null/undefined/[] → []", () => {
    expect(pipelineStageViews(null)).toEqual([]);
    expect(pipelineStageViews(undefined)).toEqual([]);
    expect(pipelineStageViews([])).toEqual([]);
  });

  it("活跃阶段:优先 running;无 running 取最后一个非 pending;全空 → null", () => {
    expect(pipelineActiveStage(pipelineStageViews([
      { name: "refactor", status: "ok" },
      { name: "compile", status: "running" },
    ]))?.key).toBe("compile");
    expect(pipelineActiveStage(pipelineStageViews([
      { name: "refactor", status: "ok" },
      { name: "compile", status: "pending" },
    ]))?.key).toBe("refactor");
    expect(pipelineActiveStage([])).toBeNull();
    expect(pipelineActiveStage(pipelineStageViews([{ name: "x", status: "pending" }]))).toBeNull();
  });

  it("settled:全终态(ok/skipped/error)才 true;running/pending 或空 → false", () => {
    expect(pipelineSettled(pipelineStageViews([
      { name: "refactor", status: "ok" },
      { name: "compile", status: "skipped" },
      { name: "fix_loop", status: "error" },
    ]))).toBe(true);
    expect(pipelineSettled(pipelineStageViews([
      { name: "refactor", status: "ok" },
      { name: "compile", status: "running" },
    ]))).toBe(false);
    expect(pipelineSettled([])).toBe(false);
  });
});

describe("parseRefactorIntent", () => {
  it("中文'重构'命中,默认要编译、不打包", () => {
    const it1 = parseRefactorIntent("帮我重构这个工程");
    expect(it1).toEqual({ refactor: true, wantCompile: true, wantPackage: false });
  });

  it("英文 refactor 大小写不敏感", () => {
    expect(parseRefactorIntent("Please Refactor the project").refactor).toBe(true);
    expect(parseRefactorIntent("REFACTOR now").refactor).toBe(true);
  });

  it("打包词族命中 wantPackage:打包/下载/交付/压缩包/zip/zap19", () => {
    for (const p of ["重构并打包", "重构后给我交付包", "下载一下", "导出压缩包", "给我 zip", "生成 zap19"]) {
      expect(parseRefactorIntent(p).wantPackage).toBe(true);
    }
    expect(parseRefactorIntent("重构并打包").refactor).toBe(true);
  });

  it("不编译/跳过编译字样关闭编译,其余默认要编译", () => {
    expect(parseRefactorIntent("重构但不编译").wantCompile).toBe(false);
    expect(parseRefactorIntent("重构,跳过编译").wantCompile).toBe(false);
    expect(parseRefactorIntent("不要编译,直接重构").wantCompile).toBe(false);
    expect(parseRefactorIntent("重构完编译一下").wantCompile).toBe(true);
  });

  it("无关输入:refactor=false,wantCompile 默认 true", () => {
    expect(parseRefactorIntent("创建 FB ConveyorCtrl")).toEqual({
      refactor: false,
      wantCompile: true,
      wantPackage: false,
    });
    expect(parseRefactorIntent("")).toEqual({ refactor: false, wantCompile: true, wantPackage: false });
  });
});

describe("pipelineProgressText", () => {
  const stages: RefactorPipelineStage[] = [
    { name: "refactor", status: "ok" },
    { name: "auto_fix", status: "running" },
    { name: "compile", status: "pending" },
    { name: "fix_loop", status: "pending" },
    { name: "package", status: "pending" },
  ];

  it("五段固定清单:完成 / 进行中… / 待开始", () => {
    expect(pipelineProgressText(stages)).toBe(
      ["▸ 重构 完成", "▸ 自动修复 进行中…", "▸ 编译 待开始", "▸ 编译修复循环 待开始", "▸ 打包 待开始"].join(
        "\n",
      ),
    );
  });

  it("skipped 附带原因 detail,无 detail 时不留空括号", () => {
    const s: RefactorPipelineStage[] = [
      { name: "compile", status: "skipped", detail: "本机未安装博图" },
      { name: "fix_loop", status: "skipped" },
    ];
    expect(pipelineProgressText(s)).toBe(
      ["▸ 编译 已跳过（本机未安装博图）", "▸ 编译修复循环 已跳过"].join("\n"),
    );
  });

  it("error 附带失败原因", () => {
    expect(pipelineProgressText([{ name: "refactor", status: "error", detail: "映射失败" }])).toBe(
      "▸ 重构 出错（映射失败）",
    );
  });

  it("自定义 stageNameMap 覆盖默认标签;未知段名原样透出", () => {
    expect(pipelineProgressText([{ name: "compile", status: "running" }], { compile: "编译校验" })).toBe(
      "▸ 编译校验 进行中…",
    );
    expect(pipelineProgressText([{ name: "deploy", status: "ok" }])).toBe("▸ deploy 完成");
  });

  it("stages 为空/缺失 → 启动占位文案", () => {
    expect(pipelineProgressText([])).toBe("已启动重构流水线…");
    expect(pipelineProgressText(undefined)).toBe("已启动重构流水线…");
    expect(pipelineProgressText(null)).toBe("已启动重构流水线…");
  });

  it("默认标签表覆盖契约五段", () => {
    expect(Object.keys(REFACTOR_STAGE_NAMES).sort()).toEqual(
      ["auto_fix", "compile", "fix_loop", "package", "refactor"].sort(),
    );
  });
});

describe("pipelineResultMessage", () => {
  const fullResult: RefactorPipelineResult = {
    report: {
      target_unit_name: "U1_HR001",
      ems: [
        { name: "EM1_装配", steps_count: 5, cms_count: 2 },
        { name: "EM2_检测", steps_count: 3, cms_count: 1 },
      ],
      af_blocks_created: Array.from({ length: 10 }, (_, i) => `U1Em1CM${i + 1}`),
      io_retention: { total_ios: 40, retained_ios: 40, percentage: 100 },
      interlocks: [{}, {}, {}],
      lint_findings: [
        { rule_id: "AF001", severity: "error", block_name: "U1Em1", message: "EM 缺少步序" },
        { rule_id: "AF002", severity: "warning", block_name: "U1Em2", message: "CM 命名不规范" },
        { rule_id: "AF003", severity: "warning", message: "注释缺失" },
      ],
      pending_blocks: Array.from({ length: 10 }, (_, i) => `Legacy${i + 1}`),
    },
    compile: { compiled: true, errors: [], warnings_count: 2 },
    package: { size_bytes: 204_800, file_count: 64 },
    warnings: ["w1", "w2", "w3", "w4", "w5", "w6", "w7"],
  };

  it("摘要自适应读取:EM 数/生成块数/I-O 保全/联锁/静态合规计数", () => {
    const msg = pipelineResultMessage(fullResult);
    expect(msg).toContain("### 西门子标准重构完成");
    expect(msg).toContain("`U1_HR001`");
    expect(msg).toContain("共 2 个标准 EM");
    expect(msg).toContain("**EM1_装配**: 5 个步序，2 个控制模块 (CM)");
    expect(msg).toContain("**标准块生成**: 10 个纯 SCL 官方规范块");
    expect(msg).toContain("40/40 (100%)");
    expect(msg).toContain("3 处联锁表达式");
    expect(msg).toContain("**静态合规审查**: 1 Errors, 2 Warnings");
  });

  it("pending_blocks:数量 + 前 8 个块名 + '等'截断提示", () => {
    const msg = pipelineResultMessage(fullResult);
    expect(msg).toContain("**以下 10 个块无法自动映射,保留原样待人工确认**");
    expect(msg).toContain("Legacy1、Legacy2、Legacy3、Legacy4、Legacy5、Legacy6、Legacy7、Legacy8 等");
    expect(msg).not.toContain("Legacy9");
  });

  it("pending_blocks 元素为 { name } 对象时自适应取名;不足 8 个不加'等'", () => {
    const msg = pipelineResultMessage({
      report: { pending_blocks: [{ name: "A" }, { name: "B" }, "C"] },
    });
    expect(msg).toContain("**以下 3 个块无法自动映射,保留原样待人工确认**：A、B、C");
    expect(msg).not.toContain("A、B、C 等");
  });

  it("编译通过:计数来自 compile 数据而非写死", () => {
    const msg = pipelineResultMessage(fullResult);
    expect(msg).toContain("已通过 — 0 Errors / 2 Warnings");
  });

  it("编译未通过:如实列 errors 前 10 条", () => {
    const msg = pipelineResultMessage({
      compile: {
        compiled: true,
        errors: Array.from({ length: 12 }, (_, i) => `E${i + 1}`),
        warnings_count: 0,
      },
    });
    expect(msg).toContain("未通过 — 12 Errors / 0 Warnings");
    expect(msg).toContain("1. E1");
    expect(msg).toContain("10. E10");
    expect(msg).not.toContain("11. E11");
    expect(msg).not.toContain("E12");
  });

  it("compiled=false:如实显示 skipped_reason,绝不写死 0 错误", () => {
    const msg = pipelineResultMessage({
      compile: { compiled: false, skipped_reason: "本机未安装博图" },
    });
    expect(msg).toContain("未编译（本机未安装博图）");
    expect(msg).not.toContain("0 Errors, 0 Warnings");
  });

  it("compile 整体缺失 → '未编译';报告缺失 → 合规审查明说无数据", () => {
    const msg = pipelineResultMessage({});
    expect(msg).toContain("- **西门子官方编译**: 未编译");
    expect(msg).toContain("**静态合规审查**: 报告未返回审查数据");
    // 绝不能再出现旧同步路径硬编码的合规结论
    expect(msg).not.toContain("静态合规审查: 0 Errors, 0 Warnings");
  });

  it("af_blocks_created 缺失时回落 af_blocks_count", () => {
    const msg = pipelineResultMessage({ report: { af_blocks_count: 42 } });
    expect(msg).toContain("**标准块生成**: 42 个纯 SCL 官方规范块");
  });

  it("warnings 只列前 5 条", () => {
    const msg = pipelineResultMessage(fullResult);
    expect(msg).toContain("#### 流水线提醒");
    expect(msg).toContain("5. w5");
    expect(msg).not.toContain("w6");
    expect(msg).not.toContain("w7");
  });

  it("传 jobId 时附交付包下载链接与体积信息", () => {
    const msg = pipelineResultMessage(fullResult, { jobId: "job-abc 123" });
    expect(msg).toContain("[下载交付包 (.zip)]");
    expect(msg).toContain("/api/v1/plc/canvas/refactor-pipeline/job-abc%20123/package");
    expect(msg).toContain("200.0 KB · 64 个文件");
  });

  it("不传 jobId 时无下载链接(旧同步路径复用同一渲染器)", () => {
    expect(pipelineResultMessage(fullResult)).not.toContain("下载交付包");
  });

  it("空 result 也能渲染,不抛异常", () => {
    const msg = pipelineResultMessage(null);
    expect(msg).toContain("### 西门子标准重构完成");
    expect(msg).toContain("画布已即时切换为标准结构视图");
  });

  it("refactorPipelinePackageUrl 拼 GATEWAY_BASE 与 encodeURIComponent", () => {
    expect(refactorPipelinePackageUrl("j1")).toBe("/api/v1/plc/canvas/refactor-pipeline/j1/package");
    expect(refactorPipelinePackageUrl("a b/c")).toBe("/api/v1/plc/canvas/refactor-pipeline/a%20b%2Fc/package");
  });
});

describe("pipelineResultMessage 等价性核对小节", () => {
  const base = {
    report: { target_unit_name: "U1_DemoLine", ems: [], af_blocks_created: [] },
    compile: { compiled: false, skipped_reason: "未请求", errors: [], warnings_count: 0 },
  } as any;

  it("有 equivalence 时渲染 IO 保全与语句变化(dropped=0 全部保留)", () => {
    const msg = pipelineResultMessage(
      {
        ...base,
        equivalence: {
          io_preserved: true,
          preserved_count: 12,
          dropped_count: 0,
          added_count: 2,
          dropped: [],
          statement_delta_pct: 33.3,
        },
      },
      { jobId: "j1" },
    );
    expect(msg).toContain("#### 等价性核对（文本级）");
    expect(msg).toContain("preserved 12 / dropped 0 / added 2");
    expect(msg).toContain("全部旧地址仍在交付物中");
    expect(msg).toContain("**语句数变化**: +33.3%");
    expect(msg).toContain("非行为等价性证明");
  });

  it("dropped>0 逐条列出前 5 个地址,delta 为 null 不渲染语句行", () => {
    const msg = pipelineResultMessage({
      ...base,
      equivalence: {
        io_preserved: false,
        preserved_count: 3,
        dropped_count: 7,
        added_count: 0,
        dropped: ["%Q0.0", "%Q0.1", "%Q0.2", "%Q0.3", "%Q0.4", "%Q0.5", "%Q0.6"],
        statement_delta_pct: null,
      },
    });
    expect(msg).toContain("dropped 7");
    expect(msg).toContain("%Q0.0、%Q0.1、%Q0.2、%Q0.3、%Q0.4 等");
    expect(msg).not.toContain("语句数变化");
  });

  it("无 equivalence 字段时不渲染小节", () => {
    const msg = pipelineResultMessage(base);
    expect(msg).not.toContain("等价性核对");
  });
});

describe("buildWritebackSubStages (5 个子阶段视图与状态映射)", () => {
  it("构建面向工程师的标准 5 个子阶段视图", () => {
    const stages = buildWritebackSubStages([]);
    expect(stages.map((s) => s.key)).toEqual([
      "static_gate",
      "topo_sort",
      "batch_write",
      "incremental_compile",
      "self_healing",
    ]);
    expect(stages[0].label).toContain("静态安全门禁");
    expect(stages[1].label).toContain("依赖拓扑排序");
    expect(stages[2].label).toContain("极速批次回写");
    expect(stages[3].label).toContain("增量软件编译");
    expect(stages[4].label).toContain("智能错误自愈");
  });

  it("映射底层 compile-jobs 原始阶段到 5 子阶段", () => {
    const raw = [
      { name: "prepare_work", status: "ok" },
      { name: "open_project", status: "ok" },
      { name: "write_plc", status: "ok" },
      { name: "compile_plc", status: "running" },
    ];
    const stages = buildWritebackSubStages(raw);
    expect(stages[0].status).toBe("ok");
    expect(stages[1].status).toBe("ok");
    expect(stages[2].status).toBe("ok");
    expect(stages[3].status).toBe("running");
    expect(stages[4].status).toBe("pending");
  });

  it("静态门禁被拦截时 status 为 intercepted 并提供 detail 细节", () => {
    const raw = [
      { name: "precheck", status: "error", detail: "规则 R2 违例：Slot 3 直写物理 Q" },
    ];
    const stages = buildWritebackSubStages(raw);
    expect(stages[0].status).toBe("intercepted");
    expect(stages[0].detail).toContain("规则 R2 违例");
  });

  it("自愈进行中展示轮次与进度信息", () => {
    const stages = buildWritebackSubStages(
      [
        { name: "compile_plc", status: "error" },
        { name: "fix_loop", status: "running" },
      ],
      { healingRound: 1, maxHealingRounds: 3 },
    );
    expect(stages[3].status).toBe("error");
    expect(stages[4].status).toBe("healing");
    expect(stages[4].detail).toContain("正在尝试第 1/3 轮自愈：修复 UDT 字段引用...");
  });

  it("自愈熔断时展示熔断告警与终态", () => {
    const stages = buildWritebackSubStages([], {
      circuitBroken: true,
      circuitBreakerAlert: "块 FB_ST10 连续出现同类错误 2 次，熔断器跳闸",
    });
    expect(stages[4].status).toBe("error");
    expect(stages[4].detail).toContain("连续出现同类错误");
  });
});

describe("getStageStatusText & pipelineSettled 拓展测试", () => {
  it("文案映射覆盖待开始、进行中、完成、已拦截、自愈中", () => {
    expect(getStageStatusText("pending")).toBe("待开始");
    expect(getStageStatusText("running")).toBe("进行中…");
    expect(getStageStatusText("ok")).toBe("完成");
    expect(getStageStatusText("blocked")).toBe("已拦截");
    expect(getStageStatusText("intercepted")).toBe("已拦截");
    expect(getStageStatusText("healing")).toBe("自愈中");
  });

  it("settled 判定包含 intercepted / blocked 终态，排除 healing 态", () => {
    expect(pipelineSettled([{ status: "ok" }, { status: "intercepted" }])).toBe(true);
    expect(pipelineSettled([{ status: "ok" }, { status: "blocked" }])).toBe(true);
    expect(pipelineSettled([{ status: "ok" }, { status: "healing" }])).toBe(false);
  });

  it("formatSelfHealProgress 格式化轮次与熔断说明", () => {
    expect(formatSelfHealProgress(2, 3, "修正槽位表达式")).toBe(
      "正在尝试第 2/3 轮自愈：修正槽位表达式",
    );
    expect(formatSelfHealProgress(1, 3, undefined, true)).toBe(
      "自愈已熔断：同类错误连续出现达到阈值，已停止自动重试",
    );
  });
});

/* ---- 防回归：打包分支不得产生写死结论、不得硬拼后端端口 ---- */

describe("打包分支交付包消息（实事求是，数据全部来自真实响应）", () => {
  const FORBIDDEN = [
    "0 Errors, 0 Warnings",
    "64 块 SCL",
    "HR001_AF_V1_2",
    "C:\\Users\\",
    "无任何缺失组件报错",
    "State=Success",
    ".zap19",
    ":8000",
  ];

  it("资源不存在：如实给出真实原因，无任何写死结论/块数/包名/本机路径", () => {
    const msg = buildJobExportMessage({
      jobId: "plc_abc123",
      available: false,
      reason: "Export package not ready（PLC_EXPORT_NOT_READY）",
    });
    expect(msg).toContain("当前作业暂无可下载交付包");
    expect(msg).toContain("PLC_EXPORT_NOT_READY");
    for (const f of FORBIDDEN) expect(msg).not.toContain(f);
  });

  it("资源存在：块数/文件数/包名/编译结果逐字来自真实响应而非写死", () => {
    const view: JobExportView = {
      jobId: "plc_xyz",
      available: true,
      filename: "ResearchOS_PLC_Result_LineA_plc_xyz.zip",
      exportUrl: "/api/v1/plc/jobs/plc_xyz/export",
      blockCount: 37,
      fileCount: 12,
      compile: { compiled: false, errors: 3, warnings: 5, note: "本机未安装博图" },
      status: "ready",
      projectName: "LineA",
    };
    const msg = buildJobExportMessage(view);
    expect(msg).toContain("ResearchOS_PLC_Result_LineA_plc_xyz.zip");
    expect(msg).toContain("**块数**：37");
    expect(msg).toContain("**源码文件数**：12");
    expect(msg).toContain("Errors 3 / Warnings 5");
    expect(msg).toContain("本机未安装博图");
    expect(msg).toContain("[下载真实导出包](/api/v1/plc/jobs/plc_xyz/export)");
    expect(msg).not.toContain("0 Errors, 0 Warnings");
    // 换一组真实数值，证明输出随响应变化、不是写死常量
    const other = buildJobExportMessage({
      ...view,
      blockCount: 8,
      fileCount: 2,
      compile: { compiled: true, errors: 1, warnings: 2 },
    });
    expect(other).toContain("**块数**：8");
    expect(other).not.toContain("**块数**：37");
    expect(other).toContain("Errors 1 / Warnings 2");
  });

  it("字段缺失：如实标注未返回，绝不补 0 或编造结论", () => {
    const msg = buildJobExportMessage({ jobId: "j", available: true });
    expect(msg).toContain("网关未返回文件名");
    expect(msg).toContain("网关未返回块数");
    expect(msg).toContain("网关未返回文件数");
    expect(msg).toContain("未返回编译结论");
    expect(msg).not.toContain("0 Errors, 0 Warnings");
    expect(msg).not.toContain("Errors 0");
  });
});

describe("extractCompileFromJobDetail：只从真实载荷读取编译结论", () => {
  it("report.compile 含真实数值时如实返回", () => {
    expect(
      extractCompileFromJobDetail({
        report: {
          compile: {
            compiled: false,
            errors: ["e1", "e2"],
            warnings_count: 7,
            skipped_reason: "未装博图",
          },
        },
      }),
    ).toEqual({ compiled: false, errors: 2, warnings: 7, note: "未装博图" });
  });

  it("无编译字段一律返回 null，不编造 0/0", () => {
    expect(extractCompileFromJobDetail({ blocks: [], coverage: {} })).toBeNull();
    expect(extractCompileFromJobDetail(null)).toBeNull();
    expect(extractCompileFromJobDetail(undefined)).toBeNull();
  });
});

describe("网关真实辅助函数（citations / 文件名 / 基址）", () => {
  it("formatPlcCitations 把网关真实 citations 字段渲染进 Markdown", () => {
    const text = formatPlcCitations([
      {
        block: "FB_Motor",
        locator: "Network 3 / line 2",
        snippet: "#q := #start OR #q;",
        source_status: "exported",
      },
      { block: "OB1", evidence: "CALL FB_Motor" },
    ]);
    expect(text).toContain("FB_Motor");
    expect(text).toContain("Network 3 / line 2");
    expect(text).toContain("#q := #start OR #q;");
    expect(text).toContain("exported");
    expect(text).toContain("CALL FB_Motor");
  });

  it("空 citations 返回空串（不编造引用源）", () => {
    expect(formatPlcCitations([])).toBe("");
    expect(formatPlcCitations(null)).toBe("");
    expect(formatPlcCitations(undefined)).toBe("");
  });

  it("parseContentDispositionFilename 抽取真实包名", () => {
    expect(
      parseContentDispositionFilename(
        'attachment; filename="ResearchOS_PLC_Result_A_1a2b3c4d.zip"',
      ),
    ).toBe("ResearchOS_PLC_Result_A_1a2b3c4d.zip");
    expect(parseContentDispositionFilename(null)).toBeNull();
  });

  it("gatewayBase() 是统一网关基址入口（字符串）", () => {
    expect(typeof gatewayBase()).toBe("string");
  });
});

describe("源码静态断言：App.tsx 打包分支不硬拼端口、不留写死结论", () => {
  it("删除 window.location 硬拼后端端口与 download-package 旧端点", () => {
    expect(appSource).not.toContain("window.location.protocol");
    expect(appSource).not.toContain('window.location.hostname + ":8000"');
    expect(appSource).not.toContain("download-package?package_type");
    expect(appSource).not.toContain(":8000");
    expect(appSource).toContain("gatewayBase()");
  });

  it("删除所有写死编译结论/块数/包名/本机绝对路径", () => {
    for (const forbidden of [
      "0 Errors, 0 Warnings",
      "64 块 SCL 源码",
      "HR001_AF_V1_2",
      "PLC_Openness_data",
      "无任何缺失组件报错",
      "State=Success",
      "TIA Portal V19 Openness 软件完全重建校验",
      "C:\\Users\\",
    ]) {
      expect(appSource).not.toContain(forbidden);
    }
    expect(appSource).toContain("当前作业暂无可下载交付包");
    expect(appSource).toContain("probePlcJobExport");
    expect(appSource).toContain("buildJobExportMessage");
  });
});

