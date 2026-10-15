# 13 · Pretext.js（@chenglou/pretext）评估结论

日期：2026-10-14 · 版本实测：0.0.9 · 官网：https://pretextjs.net/zh

## 它是什么（先澄清名称误会）

Pretext 是一个**纯算术的文本测量库**（5KB gzip）：`prepare()` 用一次 Canvas
measureText 完成分词与宽度缓存，之后 `layout(prepared, width, lineHeight)`
在不触碰 DOM 的情况下算出多行文本的行数与高度。

它**不是**排版/布局引擎，也不负责面板拖拽、分栏、渲染。用户建议的
"排版、拖拽、大小调节、渲染"四项中，前三项与它无关（本项目已用
CSS flex 分割栏 + pointer 事件实现，且拖拽路径上没有任何 DOM 回流测量），
第四项它只测不画。

## 本机实测（内嵌浏览器 + 项目真实字体）

实验页在 IAB 内运行，字体取自全局图节点真实计算样式
（`500 12px "IBM Plex Mono"` 块名 / `400 11px Barlow` 注释）：

| 维度 | pretext | 浏览器 DOM | 差异 |
|---|---|---|---|
| ASCII 块名自然宽 | 112.16px | 112.17px | 0.01px |
| 中文块名自然宽 | 85.20px | 85.20px | 0.01px |
| 中英混合注释自然宽 | 280.03px | 280.05px | 0.01px |
| 136px 内折行行数 | 3 | 3 | 一致 |
| pre-wrap SCL 行数（520px） | 5 | 5 | 一致 |
| 3000 次行高计算 | 9.3ms（3.1µs/次） | 926.7ms（309µs/次，强制回流） | ~100× |

结论：在内嵌浏览器里像素级准确（含 CJK、含 `whiteSpace:'pre-wrap'`
模式——官网 FAQ 的"暂不覆盖 pre-wrap"已过时，0.0.9 的 README 明确支持），
速度优势真实存在（官网宣称 300-600×，IAB 实测 ~100×）。

## 结论：现在不接入，记录触发条件

当前没有它要解决的热点：

1. **分栏/拖拽/宽度调节** — CSS flex + 指针增量，路径上无回流测量，无瓶颈。
2. **文本渲染** — 全部走 DOM，量级（几十块、几百行 SCL、几十条消息）
   浏览器自身排版绰绰有余；块名/注释截断由 CSS `text-overflow: ellipsis`
   按像素裁剪，比任何 JS 预测量更简单直接（本次顺手删掉了组件里
   按字符数的冗余 JS 截断，改为 title 悬停显示全文）。
3. **虚拟滚动** — 尚未做也尚不需要。

**触发条件（满足其一时回来接入）**：
- 单块 SCL 超过 ~2000 行或消息列表超过 ~500 条，滚动出现掉帧
  → 用 `prepare(text, monoFont, {whiteSpace:'pre-wrap'})` + `layout()`
  预计算行高，做零误差行级虚拟化（这是它的教科书场景）；
- 需要在无 DOM 的环境（Web Worker / 测试）里断言文本尺寸；
- 需要文本"收缩包裹"宽度（`measureLineStats().maxLineWidth`）。

接入方式（届时）：`npm i @chenglou/pretext`，注意 dist 是多文件 ESM，
必须整目录进打包器（不能单文件拷贝）；vitest/jsdom 没有 Canvas
measureText，相关逻辑需注入度量函数或走浏览器端测试。
