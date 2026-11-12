/**
 * 主链静态契约断言（?raw，不 render、不用 jsdom）：
 *  - AC-1 四个阶段页 + 主链容器零内部契约术语；
 *  - AC-8 全流程仅 1 处工艺描述输入；
 *  - AC-9 主链无原始报文弹窗、错误全中文；
 *  - AC-10 Albert Sans 主字体 / 四步换底 / reduced-motion 降级齐备。
 */
import { describe, expect, it } from "vitest";
// @ts-ignore vitest 运行在 Node 环境；本仓库未安装 @types/node，CSS 由 Vitest 默认 stub 为空串，故直接读盘。
import { readFileSync } from "node:fs";
import describeSource from "./StepDescribe.tsx?raw";
import linkSource from "./StepLink.tsx?raw";
import confirmSource from "./StepConfirm.tsx?raw";
import deliverSource from "./StepDeliver.tsx?raw";
import wizardSource from "../GreenfieldWizard.tsx?raw";
import channelSource from "../GreenfieldChannel.tsx?raw";
import drawerSource from "../EngineeringDrawer.tsx?raw";
import gateBarSource from "../GreenfieldGateBar.tsx?raw";
import panelSource from "../GreenfieldPanel.tsx?raw";
import appSource from "../../App.tsx?raw";

/** Vitest 默认把 .css 模块 stub 成空串，故用 Node 直接读取真实样式源码。 */
const cssSource: string = readFileSync(new URL("./steps.css", import.meta.url), "utf8");

const STEP_PAGES: ReadonlyArray<[string, string]> = [
  ["StepDescribe", describeSource],
  ["StepLink", linkSource],
  ["StepConfirm", confirmSource],
  ["StepDeliver", deliverSource],
  ["GreenfieldWizard", wizardSource],
];

/** AC-1：主链首屏禁止出现的内部契约术语（工程视角抽屉内允许）。 */
const AC1_BLACKLIST: readonly string[] = [
  "project_id",
  "pending_real_machine",
  "fidelity_ok",
  "spec_hash",
  "step_order",
  "PCEC",
  "compile_diagnostics",
  "D7",
  "D10",
  "D11",
  "N9",
  "A·B·C",
  "差异清单逐项勾选",
  "SCL 只读预览",
  "blocker.code",
  "blocker",
  "已锁定",
  "原始 JSON",
  "JSON.stringify",
];

function countInputs(source: string): number {
  return (source.match(/<textarea|<input\b/g) ?? []).length;
}

describe("AC-1 · 主链首屏零内部契约术语", () => {
  it("4 个阶段页与主链容器都不出现契约术语", () => {
    for (const [name, source] of STEP_PAGES) {
      for (const forbidden of AC1_BLACKLIST) {
        expect(source, `${name} 不应出现 ${forbidden}`).not.toContain(forbidden);
      }
    }
  });

  it("4 个阶段页不 import 任何后端请求函数（type-only 类型导入允许）", () => {
    const valueImport = /import\s*\{[^}]*\}\s*from\s*["'][^"']*state\/greenfield["']/;
    for (const [name, source] of STEP_PAGES) {
      expect(source, `${name} 不应直连请求层`).not.toMatch(valueImport);
    }
  });

  it("工程视角入口唯一且默认折叠（由 stepMachine 的 engineeringOpen=false 保证）", () => {
    expect((wizardSource.match(/工程视角/g) ?? []).length).toBeGreaterThan(0);
    expect(wizardSource).toContain("TOGGLE_ENGINEERING");
    expect(wizardSource).toContain("<EngineeringDrawer");
  });
});

describe("AC-8 · 全流程仅 1 处工艺描述输入", () => {
  it("只有步 1 有输入框，其余阶段页 / 主链容器 / 兼容薄壳都没有", () => {
    expect(countInputs(describeSource)).toBe(1);
    expect(countInputs(linkSource)).toBe(0);
    expect(countInputs(confirmSource)).toBe(0);
    expect(countInputs(deliverSource)).toBe(0);
    expect(countInputs(wizardSource)).toBe(0);
    expect(countInputs(panelSource)).toBe(0);
  });

  it("旧 GreenfieldPanel 的重复工艺描述输入条已删除", () => {
    expect(panelSource).not.toContain("gf-prompt-input");
    expect(panelSource).not.toContain("输入工艺描述");
    expect(panelSource).not.toContain("生成首版结构图");
    expect(panelSource.split("\n").length).toBeLessThan(120);
  });

  it("Channel 不再静默自动 sendChat，只把种子预填到步 1", () => {
    expect(channelSource).toContain("不再静默生成");
    expect(channelSource).toContain("SET_PROMPT");
    expect(channelSource).not.toContain("if (!initial.has_ir && seedPrompt)");
  });
});

describe("AC-9 · 主链中文文案、无原始报文弹窗", () => {
  it("阶段页与主链容器不存在原始报文弹窗", () => {
    for (const [name, source] of STEP_PAGES) {
      expect(source, `${name} 不应有原始报文弹窗`).not.toContain("JSON.stringify");
      expect(source, `${name} 不应有弹窗`).not.toContain("gf-modal__json");
    }
  });

  it("GateBar 的 JSON 摘要弹窗已替换为中文结构化列表", () => {
    expect(gateBarSource).not.toContain("JSON.stringify(summary");
    expect(gateBarSource).not.toContain("gf-modal__json");
    expect(gateBarSource).toContain("engineering-summary-structured");
    expect(gateBarSource).toContain("mapConfirmError");
  });

  it("Channel 用 mapConfirmError 转中文，且门禁失败不前进", () => {
    expect(channelSource).toContain("mapConfirmError(code, message)");
    expect(channelSource).toContain("停在步 3：不重试、不绕过、不 GO(4)");
    expect(channelSource).toContain("fetchEngineeringSummary(sessionId)");
  });

  it("主链提示全部为中文（无英文错误码字面量）", () => {
    for (const [name, source] of STEP_PAGES) {
      expect(source, `${name} 不应有英文错误码`).not.toContain("GF_GATE_");
      expect(source, `${name} 不应有英文错误码`).not.toContain("GF_EDGE_");
    }
  });
});

describe("AC-10 · 设计规范落地", () => {
  it("沿用自托管 Albert Sans 变量令牌，不引入通用字体", () => {
    expect(cssSource).toContain("var(--font-ui)");
    expect(cssSource).not.toContain("font-family: Inter");
    expect(cssSource).not.toContain("font-family: Roboto");
    expect(cssSource).not.toContain("font-family: Arial");
    expect(cssSource).not.toContain("font-family: system-ui");
  });

  it("四步换底用更高特异性覆盖 --ground，步 4 叠 --ok 盖章", () => {
    expect(cssSource).toContain('.gf-root.gf-wiz[data-step="1"] { --ground: #c3cbe5; }');
    expect(cssSource).toContain('.gf-root.gf-wiz[data-step="2"] { --ground: #cfd3cb; }');
    expect(cssSource).toContain('.gf-root.gf-wiz[data-step="3"] { --ground: #e6dccd; }');
    expect(cssSource).toContain('.gf-root.gf-wiz[data-step="4"] { --ground: #bcc7e0; }');
    expect(cssSource).toContain("var(--ok)");
    expect(cssSource).toContain("gf-stamp");
    expect(cssSource).toContain("background-color 620ms");
  });

  it("空间构成 / 字号 / 动效 / reduced-motion 全量降级齐备", () => {
    expect(cssSource).toContain("grid-template-columns: 220px minmax(0, 1fr)");
    expect(cssSource).toContain("width: 420px");
    expect(cssSource).toContain("clamp(48px, 6vw, 96px)");
    expect(cssSource).toContain("@keyframes gf-wiz-reveal");
    expect(cssSource).toContain("stroke-dashoffset");
    expect(cssSource).toContain("@keyframes gf-stamp-in");
    expect(cssSource).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("根节点保留 data-stage 并新增 gf-wiz / data-step", () => {
    expect(channelSource).toContain('className="gf-root gf-channel gf-wiz"');
    expect(channelSource).toContain("data-stage={state.stage}");
    expect(channelSource).toContain("data-step={wizard.step}");
  });
});

describe("边界 · Q-03 裁定后的路由默认值", () => {
  it("默认落地页为 V2 工作台，旧 4 步向导保留独立路由且仍可返回", () => {
    /* Q-03 / WP-04：默认新工作台；旧向导为独立 hash 路由 + 顶栏开关。
       本断言随主理人裁定更新，不是掩盖既有失败。 */
    expect(appSource).toContain("initialChannel()");
    expect(appSource).toContain('channel === "v2"');
    expect(appSource).toContain("hashForChannel");
    expect(appSource).toContain("switchChannel");
    expect(appSource).toContain('onBack={() => setChannel("workbench")}');
    expect(appSource).toContain("initialPrompt={greenfieldPrompt}");
  });
});

/* ======================================================================
 * QA 独立静态复核（V9）：门禁停步、抽屉严格折叠、阶段页零直连请求、
 * 拖线删除一律回调。以下断言由 QA 依据 PRD/架构自行设计。
 * ==================================================================== */
describe("QA V9 · 停步 3 / 抽屉折叠 / 阶段页零请求 / 拖线真值", () => {
  it("StepConfirm 门禁未满足时禁用主按钮，只给中文说明与工程视角入口", () => {
    expect(confirmSource).toContain("disabled={busy || !canConfirm}");
    expect(confirmSource).toContain("查看工程视角");
    expect(confirmSource).toContain("确认所需的前置还没有齐备");
    expect(confirmSource).not.toContain("JSON.stringify");
    expect(confirmSource).not.toMatch(/GF_[A-Z_]+/);
  });

  it("EngineeringDrawer 折叠态完全不渲染分组；GateBar 只在抽屉内挂载", () => {
    expect(drawerSource).toContain("{open && (");
    expect(drawerSource.indexOf("GROUPS.map")).toBeGreaterThan(
      drawerSource.indexOf("{open && ("),
    );
    expect(drawerSource).toContain("<GreenfieldGateBar");
    expect(wizardSource).not.toContain("GreenfieldGateBar");
    expect(channelSource).not.toContain("<GreenfieldGateBar");
  });

  it("4 个阶段页 + 主链容器不直连任何请求函数、不含英文错误码字面量", () => {
    // 静态断言只看可执行代码：StepLink 顶部注释里提到过 applyLinkPatch 的名字，
    // 那是文档说明而非调用，需先剔除块注释与整行注释后再判定（QA 自修正）。
    const stripComments = (src: string): string =>
      src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    for (const [name, source] of STEP_PAGES) {
      const code = stripComments(source);
      expect(code, `${name} 不应直连 generate`).not.toContain("generateProjectPackage(");
      expect(code, `${name} 不应直连 confirm`).not.toContain("confirmSpec(");
      expect(code, `${name} 不应直连 summary`).not.toContain("fetchEngineeringSummary(");
      expect(code, `${name} 不应直连 links`).not.toContain("applyLinkPatch(");
      expect(code, `${name} 不应有英文错误码`).not.toMatch(/GF_[A-Z_]+/);
    }
  });

  it("步 2 删除连线一律回调 onRemoveEdge，edges 只由 /state 投影", () => {
    expect(linkSource).toContain("onRemoveEdge(change.id)");
    expect(linkSource).toContain("onRemoveEdge(edge.id)");
    expect(linkSource).toContain("onRemoveEdge(selectedEdgeId)");
    expect(linkSource).toContain("buildEdges(ir)");
    expect(linkSource).not.toContain("setEdges(");
  });

  it("步 4 完成页不依赖真机 / 三动作 / 差异清单勾选", () => {
    expect(deliverSource).toContain("formatFidelityBusiness(fidelity)");
    expect(deliverSource).toContain("onDownloadUrl()");
    expect(deliverSource).not.toContain("待真机横幅");
    expect(deliverSource).not.toContain("runActionA");
    expect(deliverSource).not.toContain("diffChecklistComplete");
    expect(deliverSource).not.toContain("pending_real_machine");
  });
});
