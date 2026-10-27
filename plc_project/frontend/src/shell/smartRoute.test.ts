import { describe, expect, it } from "vitest";
import { extractMermaidSource, findBlockReference, smartRoute } from "./smartRoute";

/* ==========================================================================
   smartRoute —— 契约 25 §2 智能标签路由表的规则化测试
   ========================================================================== */

describe("smartRoute 规则表（契约 25 §2）", () => {
  it("① 块名引用 → scl + focusBlock（第一个引用块）", () => {
    expect(smartRoute("已更新 FB_Motor 的联锁逻辑", {})).toEqual({
      tab: "scl",
      autoOpen: true,
      focusBlock: "FB_Motor",
    });
    // 多个块名：取第一个
    expect(smartRoute("比较 FB_A 与 FB_B 的时序", {})?.focusBlock).toBe("FB_A");
    // 小写/无下划线不算块名模式
    expect(smartRoute("fb_motor 已更新", {})).toBeNull();
    expect(smartRoute("MotorCtrl 已更新", {})).toBeNull();
  });

  it("① SCL 分区关键字不触发路由（denylist）", () => {
    expect(smartRoute("接口分区含 VAR_INPUT 与 VAR_OUTPUT", {})).toBeNull();
    expect(findBlockReference("VAR_TEMP 声明临时变量")).toBeNull();
  });

  it("① 当前选中块被原词提及也路由到 scl（无下划线块名）", () => {
    expect(smartRoute("这个 ConveyorCtrl 的逻辑如下…", { selectedBlock: "ConveyorCtrl" })).toEqual({
      tab: "scl",
      autoOpen: true,
      focusBlock: "ConveyorCtrl",
    });
  });

  it("② hasMermaid → mermaid", () => {
    expect(smartRoute("交互时序如下", { hasMermaid: true })).toEqual({
      tab: "mermaid",
      autoOpen: true,
    });
  });

  it("优先级：块名引用先于 mermaid（按契约规则顺序）", () => {
    const r = smartRoute("FB_Motor 参与时序如下", { hasMermaid: true });
    expect(r?.tab).toBe("scl");
    expect(r?.focusBlock).toBe("FB_Motor");
  });

  it("③ draftCount>0 且回答含「生成|创建|新增」→ graph；无草稿不切", () => {
    expect(smartRoute("已生成新的逻辑块", { draftCount: 2 })).toEqual({
      tab: "graph",
      autoOpen: true,
    });
    expect(smartRoute("已创建", { draftCount: 0 })).toBeNull();
    expect(smartRoute("已新增块", {})).toBeNull();
  });

  it("④ 「变量|交叉引用」→ vars", () => {
    expect(smartRoute("以下是变量清单", {})?.tab).toBe("vars");
    expect(smartRoute("生成交叉引用报告", {})?.tab).toBe("vars");
  });

  it("⑤ 「HMI|触摸屏|仿真」→ hmi", () => {
    expect(smartRoute("HMI 画面已就绪", {})?.tab).toBe("hmi");
    expect(smartRoute("触摸屏布局建议…", {})?.tab).toBe("hmi");
    expect(smartRoute("启动仿真验证", {})?.tab).toBe("hmi");
  });

  it("⑥ 「回写|编译」→ review", () => {
    expect(smartRoute("回写已确认，见事务", {})?.tab).toBe("review");
    expect(smartRoute("编译未通过：1 error", {})?.tab).toBe("review");
  });

  it("⑦ 无命中 → null（不切标签）；空文本同样 null", () => {
    expect(smartRoute("你好，我是 PLC 副驾", {})).toBeNull();
    expect(smartRoute("", { hasMermaid: true })).toBeNull();
  });

  it("命中即带 autoOpen=true（canvas 未打开时由 App 滑入 split）", () => {
    const r = smartRoute("编译通过", {});
    expect(r?.autoOpen).toBe(true);
  });
});

describe("extractMermaidSource", () => {
  it("提取最后一份 mermaid 围栏（容忍开栏尾缀与空白）", () => {
    const text =
      "前文\n```mermaid title=A\nsequenceDiagram\n  A->>B: 1\n```\n中段\n```mermaid\nsequenceDiagram\n  A->>B: 2\n```\n";
    expect(extractMermaidSource(text)).toBe("sequenceDiagram\n  A->>B: 2");
  });

  it("无围栏 → null", () => {
    expect(extractMermaidSource("普通回答，没有图")).toBeNull();
  });
});
