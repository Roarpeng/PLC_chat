import { describe, expect, it } from "vitest";
import { linkifyBlockNames } from "./blockRefs";

/* ==========================================================================
   blockRefs —— 聊天文本里已知块名 → #block: 链接替换的规则化测试
   ========================================================================== */

const NAMES = ["FB10", "FB1010", "FB1010_Parameter", "DB1001_SysMode", "FC1060", "OB1"];

describe("linkifyBlockNames", () => {
  it("普通文本里的已知块名替换为 #block: 链接", () => {
    expect(linkifyBlockNames("参数集中在 DB1001_SysMode 里", NAMES)).toBe(
      "参数集中在 [DB1001_SysMode](#block:DB1001_SysMode) 里",
    );
    // 无下划线块名同样命中(字典匹配,不靠命名样式猜测)
    expect(linkifyBlockNames("FC1060 与 OB1 协同", NAMES)).toBe(
      "[FC1060](#block:FC1060) 与 [OB1](#block:OB1) 协同",
    );
  });

  it("长名优先:FB1010_Parameter 不被 FB1010/FB10 截断", () => {
    expect(linkifyBlockNames("见 FB1010_Parameter", NAMES)).toBe(
      "见 [FB1010_Parameter](#block:FB1010_Parameter)",
    );
  });

  it("词边界:拼进更长词的不命中(大小写敏感)", () => {
    expect(linkifyBlockNames("AFB10 和 FB10600 不是块", NAMES)).toBe("AFB10 和 FB10600 不是块");
    expect(linkifyBlockNames("fb10 小写不算", NAMES)).toBe("fb10 小写不算");
  });

  it("代码区不替换:``` 围栏与 `行内代码` 原样保留", () => {
    const text = "看 `FC1060` 的实现:\n```scl\nCALL FC1060\n```\n完毕";
    expect(linkifyBlockNames(text, NAMES)).toBe(text);
  });

  it("流式中未闭合的 ``` 围栏视为代码区,不替换", () => {
    const text = "FC1060 如下:\n```scl\nCALL ";
    expect(linkifyBlockNames(text, NAMES)).toBe("[FC1060](#block:FC1060) 如下:\n```scl\nCALL ");
  });

  it("含空格的块名整体命中,href 走编码", () => {
    expect(linkifyBlockNames("周期任务是 OB30_Cyclic interrupt", ["OB30_Cyclic interrupt"])).toBe(
      "周期任务是 [OB30_Cyclic interrupt](#block:OB30_Cyclic%20interrupt)",
    );
  });

  it("无已知块名 / 空文本 / 无命中 原样返回", () => {
    expect(linkifyBlockNames("FB10", [])).toBe("FB10");
    expect(linkifyBlockNames("", NAMES)).toBe("");
    expect(linkifyBlockNames("普通句子", NAMES)).toBe("普通句子");
  });
});
