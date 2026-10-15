import { describe, expect, it } from "vitest";
import {
  applyOpsLocally,
  makeRenameOps,
  deleteVariableOps,
  deleteNetworkOps,
  buildOpsFromPrompt,
  summarizeOps,
} from "./canvasOps";
import type { CanvasStateData } from "../canvas/types";

function fixture(): CanvasStateData {
  return {
    project_name: "T",
    blocks: {
      MainOB: {
        name: "MainOB",
        block_type: "OB",
        number: 1,
        language: "SCL",
        interface: [],
        networks: [
          { id: 1, title: "scan", language: "SCL", scl_text: '"MainDB".Run := TRUE;', status: "synced" },
        ],
        status: "synced",
      },
      MotorCtrl: {
        name: "MotorCtrl",
        block_type: "FB",
        number: 10,
        language: "SCL",
        interface: [
          { name: "Start", data_type: "Bool", section: "VAR_INPUT" },
          { name: "RunOut", data_type: "Bool", section: "VAR_OUTPUT" },
        ],
        networks: [
          {
            id: 1,
            title: "hold",
            language: "SCL",
            scl_text: 'IF #Start THEN\n    "MainDB".Run := TRUE;\nEND_IF;\n#RunOut := TRUE;',
            status: "synced",
          },
          { id: 2, title: "estop", language: "SCL", scl_text: '"MainDB".Run := FALSE;', status: "synced" },
        ],
        status: "synced",
      },
      MainDB: {
        name: "MainDB",
        block_type: "DB",
        number: 1,
        language: "DB",
        interface: [
          { name: "Run", data_type: "Bool", section: "VAR" },
          { name: "Speed", data_type: "Real", section: "VAR" },
        ],
        networks: [],
        status: "synced",
      },
    },
    hmi_widgets: {
      lamp: { id: "lamp", widget_type: "indicator", title: "L", x: 0, y: 0, width: 10, height: 10, plc_tag: "MainDB.Run", data_type: "Bool", current_value: false, status: "synced" },
      btn: { id: "btn", widget_type: "button", title: "B", x: 0, y: 0, width: 10, height: 10, plc_tag: "MotorCtrl.Start", data_type: "Bool", current_value: false, status: "synced" },
    },
    tags: {},
  };
}

describe("applyOpsLocally", () => {
  it("add_block 补全编号/语言/状态", () => {
    const next = applyOpsLocally(fixture(), [
      { op: "add_block", block: { name: "Conv", block_type: "FB" } },
    ]);
    const b = next.blocks.Conv;
    expect(b).toBeTruthy();
    expect(b.block_type).toBe("FB");
    expect(b.language).toBe("SCL");
    expect(b.status).toBe("draft");
    expect(b.number).toBeGreaterThan(10);
  });

  it("remove_block 级联移除绑定该块变量的 HMI 控件", () => {
    const next = applyOpsLocally(fixture(), [{ op: "remove_block", name: "MainDB" }]);
    expect(next.blocks.MainDB).toBeUndefined();
    expect(next.hmi_widgets.lamp).toBeUndefined(); // MainDB.Run
    expect(next.hmi_widgets.btn).toBeDefined(); // MotorCtrl.Start 不受影响
  });

  it("update_block 替换 interface / networks 并置 draft", () => {
    const next = applyOpsLocally(fixture(), [
      {
        op: "update_block",
        name: "MotorCtrl",
        patch: { networks: [{ id: 9, title: "only", language: "SCL", scl_text: ";", status: "draft" }] },
      },
    ]);
    expect(next.blocks.MotorCtrl.networks).toHaveLength(1);
    expect(next.blocks.MotorCtrl.networks[0].id).toBe(9);
    expect(next.blocks.MotorCtrl.status).toBe("draft");
  });

  it("update_hmi_widget 局部补丁合并", () => {
    const next = applyOpsLocally(fixture(), [
      { op: "update_hmi_widget", id: "lamp", patch: { plc_tag: "MainDB.Speed" } },
    ]);
    expect(next.hmi_widgets.lamp.plc_tag).toBe("MainDB.Speed");
    expect(next.hmi_widgets.lamp.title).toBe("L"); // 未指定字段保留
  });

  it("不可变：原画布对象不被修改", () => {
    const c = fixture();
    applyOpsLocally(c, [{ op: "remove_block", name: "MainDB" }]);
    expect(c.blocks.MainDB).toBeDefined();
  });
});

describe("makeRenameOps", () => {
  it("重命名改写依赖块 SCL 引用与 HMI tag，并删旧建新", () => {
    const ops = makeRenameOps(fixture(), "MainDB", "PlantDB");
    expect(ops).toBeTruthy();
    const next = applyOpsLocally(fixture(), ops!);
    expect(next.blocks.MainDB).toBeUndefined();
    expect(next.blocks.PlantDB).toBeDefined();
    expect(next.blocks.PlantDB.interface[0].name).toBe("Run");
    expect(next.blocks.MotorCtrl.networks[0].scl_text).toContain('"PlantDB".Run');
    expect(next.blocks.MotorCtrl.networks[0].scl_text).not.toContain('"MainDB".Run');
    expect(next.blocks.MainOB.networks[0].scl_text).toContain('"PlantDB".Run');
    expect(next.hmi_widgets.lamp.plc_tag).toBe("PlantDB.Run");
  });

  it("目标名冲突或同名返回 null", () => {
    expect(makeRenameOps(fixture(), "MainDB", "MotorCtrl")).toBeNull();
    expect(makeRenameOps(fixture(), "MainDB", "MainDB")).toBeNull();
  });
});

describe("deleteVariableOps / deleteNetworkOps", () => {
  it("删变量生成 interface 替换补丁", () => {
    const ops = deleteVariableOps(fixture(), "MainDB", "Speed");
    expect(ops).toBeTruthy();
    const next = applyOpsLocally(fixture(), ops!);
    expect(next.blocks.MainDB.interface.map((v) => v.name)).toEqual(["Run"]);
  });

  it("变量不存在返回 null", () => {
    expect(deleteVariableOps(fixture(), "MainDB", "Nope")).toBeNull();
  });

  it("删网络生成 networks 替换补丁", () => {
    const ops = deleteNetworkOps(fixture(), "MotorCtrl", 2);
    const next = applyOpsLocally(fixture(), ops!);
    expect(next.blocks.MotorCtrl.networks.map((n) => n.id)).toEqual([1]);
  });
});

describe("buildOpsFromPrompt", () => {
  it("创建块意图", () => {
    const ops = buildOpsFromPrompt("创建 FB ConveyorCtrl", fixture());
    expect(ops[0].op).toBe("add_block");
    expect(ops[0].block.name).toBe("ConveyorCtrl");
  });
  it("指定块加变量意图（类型推断 Real）", () => {
    const ops = buildOpsFromPrompt("在 MainDB 中添加变量 SpeedSet 实数", fixture());
    expect(ops[0].op).toBe("add_variable");
    expect(ops[0].block).toBe("MainDB");
    expect(ops[0].variable.data_type).toBe("Real");
  });
  it("删除块意图", () => {
    const ops = buildOpsFromPrompt("删除块 MotorCtrl", fixture());
    expect(ops).toEqual([{ op: "remove_block", name: "MotorCtrl" }]);
  });
  it("重命名意图（把 X 改名为 Y）", () => {
    const ops = buildOpsFromPrompt("把 MainDB 改名为 PlantDB", fixture());
    expect(ops).toBeTruthy();
    const next = applyOpsLocally(fixture(), ops!);
    expect(next.blocks.PlantDB).toBeDefined();
    expect(next.blocks.MotorCtrl.networks[0].scl_text).toContain('"PlantDB".Run');
  });
  it("重命名意图（重命名 X 为 Y）", () => {
    const ops = buildOpsFromPrompt("重命名 MotorCtrl 为 DriveCtrl", fixture());
    expect(ops).toBeTruthy();
    const next = applyOpsLocally(fixture(), ops!);
    expect(next.blocks.DriveCtrl).toBeDefined();
    expect(next.blocks.MotorCtrl).toBeUndefined();
    expect(next.hmi_widgets.btn.plc_tag).toBe("DriveCtrl.Start");
  });
});

describe("summarizeOps", () => {
  it("复合 ops 摘要包含各操作", () => {
    const s = summarizeOps([
      { op: "remove_block", name: "A" },
      { op: "update_block", name: "B", patch: { interface: [] } },
    ]);
    expect(s).toContain("删除块");
    expect(s).toContain("修改块 B");
    expect(s).toContain("interface");
  });
});
