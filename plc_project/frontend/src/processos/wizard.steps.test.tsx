import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { saveActor } from "./actor";
import { ApiError } from "./api";
import { createProjectFromSpec, signalTable, validateSpec } from "./apiWizard";
import {
  IoSignalTable, StepCardView, buildSpecPayload, commandOptions, feedbackUnion,
  resolveNext, stepCardErrors, targetChoices, wizAddStep, wizDelStep, wizMoveStep, wizPatchStep,
} from "./Wizard";
import type { WizOp, WizStep } from "./Wizard";
import type { CpuEntry, DeviceCatalog, FieldDevice } from "./types";

/* Node-environment tests (no jsdom), pattern of views.smoke / canvas.smoke:
   pure step-list mutators and presentational cards are driven directly. */

const catalog: DeviceCatalog = {
  device_types: {
    cylinder: {
      label: "气缸", commands: ["Extend", "Retract"], feedback: ["Extended", "Retracted"],
      params: [], io: { DI: 2, DQ: 2, AI: 0, AQ: 0 }, conflict: ["Extended", "Retracted"],
    },
    sensor: {
      label: "传感器", commands: [], feedback: ["Detected"],
      params: [], io: { DI: 1, DQ: 0, AI: 0, AQ: 0 }, conflict: null,
    },
  },
  cpus: [], io_modules: [],
};
const cpu: CpuEntry = { series: "S7-1500", order_no: "6ES7511-1AK02-0AB0", firmware: "V2.9", label: "CPU 1511-1 PN" };
const devices: FieldDevice[] = [
  { type: "cylinder", name: "夹紧气缸", id: "CM_CLAMP_CYL", params: { timeout_ms: 3000, hold_ms: 2000 } },
  { type: "sensor", name: "到位检测", id: "CM_SENSE", params: {} },
];

const mkStep = (id: string, name: string, over: Partial<WizStep> = {}): WizStep => ({
  id, name, guardSignal: "", guardValue: true, commands: [], timeoutMs: 3000,
  failureTarget: "", nextMode: "auto", nextId: "", ...over,
});
const mkOp = (over: Partial<WizOp> = {}): WizOp => ({
  em: "EM_01", name: "夹紧", resourceIds: ["CM_CLAMP_CYL"],
  steps: [mkStep("S_1", "夹紧"), mkStep("S_2", "检测")], ...over,
});
const payload = () => buildSpecPayload({
  name: "装配站", cpu, deviceName: "PLC_1",
  network: { ip: "192.168.0.1", subnet: "255.255.255.0", device_name: "plc_1" },
  devices, ops: [mkOp({
    steps: [
      mkStep("S_1", "夹紧", { guardSignal: "Extended", commands: ["Extend"], failureTarget: "S_3" }),
      mkStep("S_2", "检测", { guardSignal: "Detected", guardValue: false, timeoutMs: 2000 }),
      mkStep("S_3", "故障", { timeoutMs: 0 }),
    ],
  })],
});

/* ---------- 步骤卡增删改（纯列表操作，与向导共用同一函数） ---------- */

describe("wizard step list mutators", () => {
  it("add appends a default step card (timeout 3000, next auto)", () => {
    const ops = wizAddStep([mkOp()], 0);
    expect(ops[0].steps).toHaveLength(3);
    const added = ops[0].steps[2];
    expect(added.timeoutMs).toBe(3000);
    expect(added.nextMode).toBe("auto");
    expect(added.id).toMatch(/^S_[A-Z0-9]+$/);
  });

  it("del removes the card; references to it become dangling (surfaced as errors)", () => {
    let ops = [mkOp()];
    const s2 = ops[0].steps[1];
    ops = wizDelStep(ops, 0, s2.id);
    expect(ops[0].steps.map(s => s.id)).toEqual(["S_1"]);
    const errs = stepCardErrors(
      mkStep("S_1", "x", { nextMode: "id", nextId: s2.id, failureTarget: s2.id }),
      ops[0].steps, ["Extend", "Retract"], ["Extended", "Retracted"]);
    expect(errs.join(" ")).toContain("下一步指向的步骤已删除");
    expect(errs.join(" ")).toContain("故障出口指向的步骤已删除");
  });

  it("move swaps neighbours and clamps at the ends", () => {
    let ops = [mkOp()];
    ops = wizMoveStep(ops, 0, "S_1", -1);                    // first step cannot move up
    expect(ops[0].steps.map(s => s.id)).toEqual(["S_1", "S_2"]);
    ops = wizMoveStep(ops, 0, "S_1", 1);
    expect(ops[0].steps.map(s => s.id)).toEqual(["S_2", "S_1"]);
  });

  it("patch edits fields in place", () => {
    const ops = wizPatchStep([mkOp()], 0, "S_1", { name: "伸出", commands: ["Extend"] });
    expect(ops[0].steps[0].name).toBe("伸出");
    expect(ops[0].steps[0].commands).toEqual(["Extend"]);
  });
});

/* ---------- 连线约束：下一步仅限既有步骤 ---------- */

describe("next-target constraints (no free-form wiring)", () => {
  it("targetChoices lists existing steps only, excluding self", () => {
    const steps = [mkStep("S_1", "a"), mkStep("S_2", "b"), mkStep("S_3", "c")];
    expect(targetChoices(steps, "S_2")).toEqual(["S_1", "S_3"]);
  });

  it("auto next resolves to the sequential successor; last step ends the sequence", () => {
    const steps = [mkStep("S_1", "a"), mkStep("S_2", "b"), mkStep("S_3", "c")];
    expect(resolveNext(steps[0], 0, steps)).toBe("S_2");
    expect(resolveNext(steps[2], 2, steps)).toBe("");
    expect(resolveNext(mkStep("S_1", "a", { nextMode: "id", nextId: "S_3" }), 0, steps)).toBe("S_3");
  });

  it("StepCardView offers only feedback signals as guards and only existing steps as next", () => {
    const steps = [mkStep("S_1", "a"), mkStep("S_2", "b"), mkStep("S_3", "c")];
    const html = renderToString(
      <StepCardView step={steps[1]} index={1} stepIds={steps.map(s => s.id)}
        commandOpts={["Extend", "Retract"]} feedbackOpts={feedbackUnion(devices, catalog)}
        errors={[]} onPatch={() => { }} onDel={() => { }} onMove={() => { }} canUp canDown />);
    for (const fb of ["Extended", "Retracted", "Detected"]) expect(html).toContain(`<option value="${fb}">`);
    expect(html).not.toContain('<option value="Extend">');   // commands are not guard signals
    expect(html).toContain('<option value="S_1">');
    expect(html).toContain('<option value="S_3">');
    expect(html).not.toContain('<option value="S_2">S_2');   // self excluded
    expect(html).toContain("仅既有步骤");
    expect(html).toContain("自动 · 时序后继");
  });

  it("StepCardView renders inline card errors in red copy", () => {
    const html = renderToString(
      <StepCardView step={mkStep("S_1", "a")} index={0} stepIds={["S_1"]}
        commandOpts={[]} feedbackOpts={[]} errors={["超时必须大于 0 ms"]}
        onPatch={() => { }} onDel={() => { }} onMove={() => { }} canUp canDown />);
    expect(html).toContain("超时必须大于 0 ms");
  });
});

/* ---------- guard 信号来自反馈并集 / IO 符号预览 ---------- */

describe("signal derivation", () => {
  it("feedbackUnion merges feedback across all devices", () => {
    expect(feedbackUnion(devices, catalog)).toEqual(["Extended", "Retracted", "Detected"]);
  });

  it("commandOptions unions the commands of the operation's resources", () => {
    expect(commandOptions(devices, catalog, ["CM_CLAMP_CYL"])).toEqual(["Extend", "Retract"]);
    expect(commandOptions(devices, catalog, [])).toEqual([]);
  });

  it("signalTable derives one row per feedback (I) and command (Q); unknown types -> UNKNOWN", () => {
    const rows = signalTable(devices, catalog);
    expect(rows).toHaveLength(5);                            // cylinder 2fb+2cmd, sensor 1fb+0cmd
    const ext = rows.find(r => r.signal === "Extended")!;
    expect(ext).toMatchObject({ dir: "I", deviceId: "CM_CLAMP_CYL", symbol: "CM_CLAMP_CYL.ExtendedFb" });
    expect(rows.find(r => r.signal === "Extend")).toMatchObject({ dir: "Q", symbol: "CM_CLAMP_CYL.ExtendCmd" });
    const unknown = signalTable([{ type: "phaser", name: "X", id: "CM_X", params: {} }], catalog);
    expect(unknown).toHaveLength(1);
    expect(unknown[0].kind).toBe("UNKNOWN");
    expect(unknown[0].symbol).toBe("UNKNOWN");
  });

  it("IoSignalTable renders the read-only table with the symbolic_only policy note", () => {
    const html = renderToString(<IoSignalTable devices={devices} cat={catalog} />);
    expect(html).toContain("IO / 符号预览");
    expect(html).toContain("CM_CLAMP_CYL.ExtendedFb");
    expect(html).toContain("符号命名策略：symbolic_only");
    expect(html).toContain("只读");
    expect(html.match(/<\/tr>/g)?.length).toBe(6);           // header + 5 rows
  });
});

/* ---------- 提交 payload 形状与客户端校验 ---------- */

describe("spec payload and client-side validation", () => {
  it("buildSpecPayload produces operations/steps matching the locked spec shape", () => {
    const p = payload();
    expect(p.name).toBe("装配站");
    expect(p.cpu?.order_no).toBe(cpu.order_no);
    expect(p.devices).toHaveLength(2);
    expect(p.devices[0]).toMatchObject({ type: "cylinder", id: "CM_CLAMP_CYL" });
    const steps = p.operations[0].steps;
    expect(steps.map(s => s.id)).toEqual(["S_1", "S_2", "S_3"]);
    expect(steps[0].guard).toEqual({ signal: "Extended", op: "==", value: true });
    expect(steps[1].guard).toEqual({ signal: "Detected", op: "==", value: false });
    expect("guard" in steps[2]).toBe(false);                 // 无 guard 不占位
    expect(steps[0].actions).toEqual([{ command: "Extend" }]);
    expect(steps[0].timeout_ms).toBe(3000);
    expect(steps[0].failure_target).toBe("S_3");
    expect(steps[0].next).toBe("S_2");                       // auto -> successor
    expect(steps[2].next).toBe("");                          // last auto -> end
    expect("timeout_ms" in steps[2]).toBe(false);            // 0 -> omitted
    expect(p.operations[0].resource_ids).toEqual(["CM_CLAMP_CYL"]);
  });

  it("validateSpec accepts the valid payload and mirrors backend fail-closed rules", () => {
    expect(validateSpec(payload(), catalog)).toEqual([]);
    const dangling = payload();
    dangling.operations[0].steps[0].next = "S_GONE";
    expect(validateSpec(dangling, catalog).join(" ")).toContain("不存在");
    const badCmd = payload();
    badCmd.operations[0].steps[0].actions = [{ command: "Vibrate" }];
    expect(validateSpec(badCmd, catalog).join(" ")).toContain("不属于");
    const noTimeout = payload();
    noTimeout.operations[0].steps[0].timeout_ms = -1;
    expect(validateSpec(noTimeout, catalog).join(" ")).toContain("超时");
    const noSteps = payload();
    noSteps.operations[0].steps = [];
    expect(validateSpec(noSteps, catalog).join(" ")).toContain("至少");
    const noResource = payload();
    noResource.operations[0].resource_ids = ["CM_NOPE"];
    expect(validateSpec(noResource, catalog).join(" ")).toContain("不存在");
  });
});

/* ---------- apiWizard 绑定（含 actor 头注入） ---------- */

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_url: string, _init: any) => ({
    ok: status >= 200 && status < 300, status, statusText: "x",
    text: async () => JSON.stringify(body),
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}
afterEach(() => vi.unstubAllGlobals());

describe("createProjectFromSpec binding", () => {
  it("POSTs the spec to /projects/from-spec with actor headers", async () => {
    saveActor({ id: "op_li", role: "Builder" });
    const fn = mockFetch(200, { project_id: "PRJ_SPECX", revision: 1, profile_id: "p", contract: { id: "PRJ_SPECX" } });
    const r = await createProjectFromSpec(payload());
    expect(r.project_id).toBe("PRJ_SPECX");
    expect(r.revision).toBe(1);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/projects/from-spec");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Actor-Id"]).toBe("op_li");
    expect(init.headers["X-Actor-Role"]).toBe("Builder");
    expect(init.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(init.body);
    expect(body.operations[0].steps).toHaveLength(3);
    expect(body.operations[0].steps[0].guard).toEqual({ signal: "Extended", op: "==", value: true });
    expect(body.devices).toHaveLength(2);
  });

  it("maps a 422 {error} body to ApiError with status", async () => {
    mockFetch(422, { error: "OP_EM_01.S_1: next 'S_GONE' does not reference a step of this operation" });
    await expect(createProjectFromSpec(payload())).rejects.toBeInstanceOf(ApiError);
    mockFetch(422, { error: "OP_EM_01.S_1: next 'S_GONE' does not reference a step of this operation" });
    await expect(createProjectFromSpec(payload())).rejects.toMatchObject({ status: 422 });
  });
});
