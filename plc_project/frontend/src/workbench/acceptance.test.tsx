/**
 * WP-07 frontend acceptance contract (pure logic, no DOM rendering).
 *
 * The vitest environment is `node`, so this file deliberately contains no
 * component rendering; it asserts the shared acceptance documents, evidence
 * levels, D-3 wording and the "no native download without V19 real" rule.
 */
// @ts-ignore vitest 运行在 Node 环境；本仓库未安装 @types/node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { canShowNativeDownload, deliveryNotice, type JobView } from "../state/workbench_v2";
import { channelFromHash, V2_WORKBENCH_DEFAULT } from "./featureFlags";

const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), "utf-8");

const baseJob: JobView = {
  job_id: "j_acc", state: "QUEUED", native_artifact: null,
  evidence_level: "pending_real_machine", evidence_id: "", compile: null, notice: "",
};

describe("WP-07 unified acceptance (offline contract)", () => {
  it("acceptance matrix maps AC-01 six steps and G0-G7 with evidence levels", () => {
    const text = read("../../../docs/v2/03-验收矩阵.md");
    for (let step = 1; step <= 6; step += 1) expect(text).toContain(`| ${step} |`);
    for (const gate of ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]) expect(text).toContain(gate);
    expect(text).toContain("evidence_level");
  });

  it("G5 is pending_real_machine and never marked passed", () => {
    const gates = read("../../../docs/v2/g0-g7-matrix.md");
    const line = gates.split("\n").find((l) => l.includes("**G5**") || l.startsWith("| G5")) ?? "";
    expect(line).toContain("pending_real_machine");
    expect(line).toContain("NOT PASSED");
    expect(line).not.toContain("已通过");
  });

  it("acceptance receipt never claims delivery complete", () => {
    const receipt = JSON.parse(read("../../../evidence/v2/acceptance/acceptance_receipt.json"));
    expect(receipt.status).toBe("pending_real_machine");
    expect(receipt.real_tia_v19_tested).toBe(false);
    expect(receipt.delivery_complete).toBe(false);
    expect(receipt.native_artifacts_published).toBe(0);
    expect(receipt.gates.G5.status).toBe("NOT PASSED");
  });

  it("D-3 P0 wording is the source-package wording", () => {
    const deliver = read("../shell/steps/StepDeliver.tsx");
    const machine = read("../shell/steps/stepMachine.ts");
    expect(deliver).toContain("源码包就绪（非原生工程）");
    expect(machine).toContain("源码包就绪（非原生工程）");
    expect(`${deliver}${machine}`).not.toContain("本轮交付完成");
    expect(`${deliver}${machine}`).not.toContain("交付完成");
    expect(deliver).toContain("NATIVE_ARCHIVED");
    expect(deliver).not.toContain("pending_real_machine"); // AC-1: no internal contract term on wizard first screen
  });

  it("no native download button without a V19 real full chain", () => {
    expect(canShowNativeDownload(baseJob)).toBe(false);
    expect(canShowNativeDownload({ ...baseJob, state: "FAILED" })).toBe(false);
    expect(canShowNativeDownload({ ...baseJob, state: "NATIVE_ARCHIVED", evidence_level: "mocked" })).toBe(false);
    expect(deliveryNotice(baseJob)).toContain("pending_real_machine");
    expect(deliveryNotice(baseJob)).not.toContain("交付完成");
  });

  it("V2 workbench is default; legacy wizard keeps its own route", () => {
    expect(V2_WORKBENCH_DEFAULT).toBe(true);
    expect(channelFromHash("")).toBe("v2");
    expect(channelFromHash("#/legacy")).toBe("greenfield");
  });
});
