/** opsReview 纯函数层单测:逐条内容理解 + 批次视图。 */
import { describe, expect, it } from "vitest";
import { buildOpsReview, explainOp } from "./opsReview";

describe("explainOp:逐条内容理解", () => {
  it("add_block:类型语义+草稿生效链路+变量数/注释", () => {
    const r = explainOp({
      op: "add_block",
      block: { name: "FB_Conveyor", block_type: "FB", interface: [{}, {}, {}], comment: "输送机" },
    });
    expect(r.badge).toBe("新增块");
    expect(r.title).toContain("FB_Conveyor");
    expect(r.understanding).toContain("功能块");
    expect(r.understanding).toContain("3 个接口变量");
    expect(r.understanding).toContain("输送机");
    expect(r.understanding).toContain("回写");
  });

  it("add_variable:分区语义(静态区=有记忆)", () => {
    const r = explainOp({ op: "add_variable", block: "FB_Motor", variable: { name: "Speed", data_type: "Real", section: "VAR_STAT" } });
    expect(r.title).toBe("FB_Motor.Speed : Real");
    expect(r.understanding).toContain("静态区(有记忆)");
  });

  it("add_network / add_hmi_widget(含绑定与未绑定两种)", () => {
    expect(explainOp({ op: "add_network", block: "FB_X", network: { title: "急停", language: "SCL" } }).title).toContain("急停");
    const bound = explainOp({ op: "add_hmi_widget", widget: { widget_type: "button", title: "启动", plc_tag: "DB1.Start" } });
    expect(bound.title).toContain("DB1.Start");
    const unbound = explainOp({ op: "add_hmi_widget", widget: { widget_type: "indicator", title: "运行" } });
    expect(unbound.understanding).toContain("暂未绑定");
  });

  it("update_block_scl 与 update_block 分支:逻辑/接口/仅注释三种口径", () => {
    expect(explainOp({ op: "update_block_scl", name: "FB_A", scl_body: "#Run := TRUE;" }).badge).toBe("修改逻辑");
    const iface = explainOp({ op: "update_block", name: "FB_B", patch: { interface: [] } });
    expect(iface.understanding).toContain("背景 DB");
    const comment = explainOp({ op: "update_block", name: "FB_C", patch: { comment: "x" } });
    expect(comment.badge).toBe("改注释");
    expect(comment.understanding).toContain("不改逻辑");
  });

  it("remove_block:画布删除与博图原件不受影响的边界", () => {
    const r = explainOp({ op: "remove_block", name: "FB_OLD" });
    expect(r.understanding).toContain("不受影响");
  });

  it("add_tag:地址冲突提示;未知 op 原样透出;非对象防御", () => {
    expect(explainOp({ op: "add_tag", tag: { name: "I_EStop", data_type: "Bool", logical_address: "%I0.0" } }).title).toContain("%I0.0");
    const unk = explainOp({ op: "custom_future_op", x: 1 });
    expect(unk.badge).toBe("custom_future_op");
    expect(explainOp(null).badge).toBe("未知");
  });
});

describe("buildOpsReview:批次视图", () => {
  it("pending 状态 + 逐条映射 + note 透传/空省略", () => {
    const r = buildOpsReview(
      [
        { op: "add_block", block: { name: "FB_A", block_type: "FB", interface: [] } },
        { op: "add_variable", block: "FB_A", variable: { name: "X", data_type: "Bool", section: "VAR" } },
      ],
      "  根据你的描述生成的修改  ",
    );
    expect(r.status).toBe("pending");
    expect(r.items).toHaveLength(2);
    expect(r.items[0].badge).toBe("新增块");
    expect(r.note).toBe("根据你的描述生成的修改");
    expect(buildOpsReview([{ op: "add_tag", tag: { name: "T" } }]).note).toBeUndefined();
  });

  it("空/非法输入空安全", () => {
    expect(buildOpsReview(null as any).items).toEqual([]);
    expect(buildOpsReview([]).items).toEqual([]);
  });
});
