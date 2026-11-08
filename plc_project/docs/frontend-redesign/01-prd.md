# PLC_chat 前端交互壳重构 · 增量 PRD（01）

> 文档类型：增量 PRD（简单 PRD 口径）｜版本 v1.0｜产出：许清楚（产品经理）
> 本轮只做需求分析与文档，**不修改任何产品代码**。本文是架构师/工程师的唯一需求输入。

---

## 0. 项目信息

| 项 | 内容 |
|---|---|
| Language | 中文（与用户语言一致） |
| Programming Language | 沿用现状：Vite 6 + React 19 + TypeScript 5.7 + 自研 CSS 变量设计系统 `greenfield.css`；画布复用已在依赖中的 `@xyflow/react ^12.12.0`（另有 `elkjs` / `mermaid` / `@fontsource/albert-sans`）。**不新增 UI 框架、不新增动效库**（项目未安装 Motion 库，动效走 CSS-only） |
| Project Name | `plc_chat_frontend_shell_redesign` |
| 原始需求复述 | 用户（项目负责人）原话：「项目前端太不合理了！完全无法体验！熟悉并且给出你的理解」。主理人给出理解与 6 条编号建议后，用户批复：「1，2，3，4 按照 design fornt 技能来构造前端」。即 **1/2/3/4 已批准，5（演示模式）与 6（隐藏存量工作台）本轮明确不做** |
| 增量性质 | 只重写前端「交互壳」；后端契约、既有业务能力、项目终态验收口径一律不变 |

---

## 1. 已批准口径（逐字转写为需求）

以下 4 条为决策者已拍板内容，逐字保留，需求池中的条目均由此映射而来：

1. **先定一条 4 步可体验主链**：自然语言描述 → 人工手动连线 → 确认 → 拿到工程包。所有契约/审计信息（D7/D10/D11/N9、fidelity_ok、spec_hash、step_order、PCEC、compile_diagnostics、pending_real_machine、A/B/C 三动作、差异清单逐项勾选、SCL 只读预览等）收进「工程视角」二级面板，**默认折叠**，不得出现在主链首屏。
2. **只重写交互壳，后端契约一律不动**：改动范围限于前端 `App.tsx` 路由 + `GreenfieldChannel / Panel / GateBar` 三个组件（可新增阶段页组件），把 1393 行 `GreenfieldPanel.tsx` 拆成 4 个阶段页；后端 `/state`、`/confirm`、`/generate`、`/deliver-tia`、A/B/C 等接口与 `state/greenfield.ts` 现有 API 保持可复用，不得改后端任何文件。
3. **单独定义「体验完成态」**：以「导出工程包 + fidelity 报告」作为用户可见的完成终点，**不依赖 TIA 真机**；`pending_real_machine` 等真机口径收进工程视角。注意：这不改变项目终态验收口径（TIA V19 编译零错误仍然有效），只是不拿它当 UI 首屏负担。
4. **手动连线做成画布拖线**：复用已在依赖中的 `@xyflow/react`（React Flow），把现有 `GreenfieldLinkPanel.tsx` 的下拉框/表单降级为辅助输入，主操作是在画布上拖拽连线。

---

## 2. 现状问题（本次要解决的）

- **首屏错配**：`App.tsx` 3354 行，双通道 `workbench | greenfield` + 三态布局 + 十余个抽屉；`showLaunchScreen = !activeSessionId && canvasEmpty`，用过一次后启动屏不再出现，新建入口只剩顶栏「+ 新建工程」小按钮；默认首屏是**已冻结不开发的存量工作台**。
- **契约前置**：向导首屏最显眼的是 `project_id（第一步生成，贯穿全程）` 与 `pending_real_machine`；`GreenfieldGateBar` 顶栏常驻 `pending_real_machine` 徽标、A·B·C 状态、8 格梯级进度、基线/spec_hash；确认弹窗直接 `JSON.stringify(summary)` 吐 JSON；界面到处是「已锁定：…」与 `blocker.code`。
- **重复输入**：向导第 2 步「工艺描述」与 `GreenfieldPanel.tsx:1167` 通道内第二个「输入工艺描述」输入框重复。
- **巨石组件**：`GreenfieldPanel.tsx` 1393 行单组件塞入上区拓扑、下区 Mermaid、右区变量绑定、三动作、step_order 八步、编译诊断、fidelity、差异清单、SCL 只读预览。
- **连线主操作错位**：React Flow 已在 `GreenfieldPanel` 挂载，`onConnect` / `toGfEdge` / `applyLinkPatch(add_edge/remove_edge)` 均已接线——**能力不缺，是被埋没**：右栏 `GreenfieldLinkPanel` 的下拉框/表单占据了主操作位。
- **没有成功态**：确认需 5 项前置；A→B→C 中 B 需 A 的 `fidelity_ok=true`、C 需差异清单逐项勾选；11-07 工作日志 UC-04 包级复测未通过、L2/L4 未通过、M4 不可签署 → UI 把「未完成」原样前置给使用者，终点恒为「待真机」，体验上永远走不到头。
- **可复用基础（非问题，是约束）**：`greenfield_service.py:167` 首版 IR 为确定性 planner、零 LLM 依赖；`state/greenfield.ts` 已有 `fetchState / sendChat / createDraft / applyLinkPatch / confirmSpec / generateProjectPackage / deliverTia / downloadPackageUrl / fetchEngineeringSummary / runActionA·B·C / confirmDiff / diffChecklistComplete / canConfirm / confirmBlockers / mapConfirmError` 等完整 API；`greenfield.css` 已有「SFC 步序块 + 阶段换底」设计系统；前端现有测试 330 passed。

---

## 3. 产品目标（3 个正交目标）

- **G1 可体验**：提供一条 4 步端到端可走通的主链，每一步都有明确的进入条件、主操作与「本步已完成」状态；主链首屏零内部契约术语。
- **G2 契约隐形但完整**：所有契约/审计信息不删除、不篡改，统一收进默认折叠的「工程视角」，按需可完整展开；后端接口与数据完整性零改动。
- **G3 有终点的成功态**：以「导出工程包 + fidelity 报告」为可见完成终点，不依赖 TIA 真机即可到达；真机口径只作为工程视角里的事实陈述。

---

## 4. 用户故事（覆盖 4 步主链每一步）

| # | 用户故事 | 对应步 |
|---|---|---|
| US-1 | As a 工艺工程师, I want 用一句自然语言描述产线并立刻看到解析出的设备/步序草图, so that 我不必先理解 project_id、规格版本和门禁就能开始工作 | 步 1 描述 |
| US-2 | As a 工艺工程师, I want 在画布上从设备节点的连接桩拖出连线来定义交互关系，并能选中删除, so that 我凭直觉完成拓扑，而不是填下拉框表单 | 步 2 连线 |
| US-3 | As a 工艺工程师, I want 一个只讲业务语言的确认页（我描述了什么、连了什么、将拿到什么）, so that 我不被 JSON、错误码和「已锁定」清单打断就能放心确认 | 步 3 确认 |
| US-4 | As a 工艺工程师, I want 一键导出工程包后看到明确的「已完成」页（含 fidelity 报告摘要与下载入口）, so that 我知道这一轮工作已经交付完成，而不是永远「待真机」 | 步 4 拿到工程包 |
| US-5 | As a 系统集成/审计人员, I want 随时展开「工程视角」看到全部契约、门禁、编译诊断、三动作与 SCL 只读预览, so that 排障与合规信息一处不丢 | 工程视角 |
| US-6 | As a 使用者, I want 在任意步返回上一步修改且不丢失已填描述与连线, so that 改错不需要从头重来 | 主链通用 |

---

## 5. 需求池

优先级：**P0 = Must have（本轮必做）｜P1 = Should have｜P2 = Nice to have**

### P0（Must have）

- **P0-1 四步主链与阶段页**：新增主链步骤状态机（step 1..4）与 4 个独立阶段页组件；`App.tsx` 只调整路由/挂载点。把 1393 行 `GreenfieldPanel.tsx` 的职责拆散到 4 个阶段页 + 工程视角，不再由单组件承载全部信息。〔映射批准项 1、2〕
- **P0-2 主链首屏零术语**：主链首屏及 4 个阶段页**不得**出现 `project_id / pending_real_machine / fidelity_ok / spec_hash / step_order / PCEC / compile_diagnostics / D7 / D10 / D11 / N9 / A·B·C 动作标签 / 差异清单逐项勾选 / SCL 只读预览 / blocker.code / 「已锁定：…」/ 原始 JSON**。它们统一收进「工程视角」二级面板，**默认折叠**，界面上只保留一个入口。〔映射批准项 1〕
- **P0-3 步 1「描述」**：全流程「工艺描述」输入框**只保留 1 处**（消除向导第 2 步与通道内 `GreenfieldPanel:1167` 的重复输入）；提交后展示业务化的解析草图（工站/执行单元/执行件/步序），给出「下一步：连线」。复用 `sendChat` / `createDraft` / `fetchState` 与 `buildTopologyConstraints`，结果来自真实后端。〔映射批准项 1〕
- **P0-4 步 2「连线」**：以 `@xyflow/react` 画布为**主操作**——从节点连接桩拖出可新增连线、选中连线可删除、非法连线被拒绝并给中文提示；复用现有 `onConnect` / `toGfEdge` / `applyLinkPatch({op:"add_edge"|"remove_edge"})` 与 `whitelist.edge_kinds`。`GreenfieldLinkPanel.tsx` 的下拉框/表单**降级为辅助输入**（默认折叠的次要面板，标题如「更多输入方式」），不再是主操作，其数据绑定不删。〔映射批准项 4〕
- **P0-5 步 3「确认」**：只呈现业务语言摘要（描述原文 / 已连关系概览 / 将产出「工程包 + 还原度报告」）与一个主按钮「确认并生成工程包」；**禁止** `JSON.stringify(summary)` 弹窗、禁止外露 `blocker.code` 与锁定清单。后端仍调用 `/confirm` 及既有门禁函数（`canConfirm` / `confirmBlockers` / `gateReason`），前置未满足时用中文说明「还差什么、去哪补」并提供跳到工程视角的入口，错误经 `mapConfirmError` 转中文。〔映射批准项 1〕
- **P0-6 步 4「完成态」**：以「导出工程包 + fidelity 报告」为用户可见终点，展示完成页：成功态标题、fidelity 报告摘要（业务化措辞、如实不伪装）、「下载工程包」（`downloadPackageUrl`）、次入口「重新调整」「开始新工程」。**到达该页不依赖 TIA 真机、不依赖 A/B/C 完成、不依赖差异清单勾选**；不显示「待真机」横幅。〔映射批准项 3〕
- **P0-7 工程视角二级面板**：默认 `collapsed`，一个入口；展开后按分组承载 D7/D10/D11/N9、`fidelity_ok`、`spec_hash`、`step_order`、PCEC、`compile_diagnostics`、`pending_real_machine`、A/B/C 三动作、差异清单逐项勾选、SCL 只读预览等**全部**字段，组内可再折叠。折叠/展开是纯前端视图状态，**不触发、不跳过、不替代任何后端调用与写入门禁**；工程视角内仍可完成原 A/B/C 与差异清单确认能力。〔映射批准项 1、3〕
- **P0-8 范围与契约约束**：改动限于 `App.tsx` 路由挂载点、`GreenfieldChannel` / `GreenfieldPanel` / `GreenfieldGateBar`（可新增阶段页组件与其样式）；`GreenfieldLinkPanel` 仅允许最小化的「降级」改动。**不得修改后端任何文件**；`state/greenfield.ts` 现有导出 API 签名与行为保持可复用（不删函数、不改签名，允许追加纯前端辅助函数）。〔映射批准项 2〕
- **P0-9 回归基线**：`npm run build`（`tsc -b && vite build`）通过；`npm run test` 通过且通过数不低于现状 330（无回退、无新增 skip）。〔映射批准项 2〕
- **P0-10 四态与可读性**：loading / busy / error / empty 四态齐全，主链所有提示与错误为中文可读文案（`formatGfError` / `mapConfirmError`），不出现原始英文 error code；焦点可见、键盘可达。

### P1（Should have）

- **P1-1** 任意步可前进/后退，返回时保留已填描述与已画连线，不重新请求生成。
- **P1-2** 步 2 画布自动布局（复用已在依赖中的 `elkjs`），支持连线撤销/重做。
- **P1-3** 完成页支持复制/下载 fidelity 报告摘要（Markdown）。
- **P1-4** 步 1 输入框提供 2–3 条**可点击的示例描述文案**（仅为占位/快捷填入，点击后仍走真实 `/chat` 生成 IR；**不是演示模式，不提供任何离线 mock 数据或假结果**）。
- **P1-5** 无障碍：画布连线支持键盘删除、`focus-visible`、`prefers-reduced-motion` 全量降级。
- **P1-6** 阶段纸底随 4 步推进换色（沿用现有 `data-stage` 换底机制，改为 step 驱动）。

### P2（Nice to have）

- **P2-1** 工程视角记住上次展开/分组状态（localStorage，纯前端）。
- **P2-2** 完成页支持打印/导出一页式交付摘要。
- **P2-3** 步 2 画布小地图（MiniMap）与缩放控制。

---

## 6. UI 设计稿（文字描述）

> 依据用户点名的 `frontend-design` 技能规范转写：**先定一个大胆且自洽的美学方向 → production-grade → 拒绝通用 AI 审美 → 字体/色彩/动效/空间构成给出具体约束**。技能原文要点已逐条落到下面的可执行约束中。

### 6.1 美学方向：工业蓝图 / 制图室（Blueprint Atelier）

- **Purpose（目的）**：给工艺工程师一张「能画、能走完、能盖章交付」的工程图纸，而不是一个展示后端契约的审计台。使用者是懂产线、不懂 `spec_hash` 的人。
- **Tone（调性）**：**克制的工业制图美学 / refined utilitarian**——冷静、精确、有纸张质感、有仪器感；不是 SaaS 仪表盘，不是聊天机器人皮肤，不是消费级玩具。选择「refined minimalism + 工业母题」，靠**意图性**而非堆特效取胜。
- **Concept（自洽母题）**：沿用并强化现有 `greenfield.css` 的「**SFC 步序块 + 左右 8px 连接桩**」母题——整个界面就是一条 4 节点的步序带，每个阶段页是图纸上的一个「工位」，而用户在步 2 拖出的连线，与界面本身的步序连线是同一种视觉语言。**一张图纸，既是导航，也是工作内容**。
- **Differentiation（记忆点）**：**「纸会随阶段换底」**——用户走完 4 步，整张纸从冷蓝图纸 → 鼠尾草 → 砂 → 冰蓝，最后叠加一枚 `--ok` 盖章色，从「草稿」变成「已交付的完成图」。这是唯一要被人记住的一件事，所有动效与配色都为它服务。
- **明确拒绝（generic AI aesthetics）**：紫色渐变/白底、玻璃拟态、圆角卡片+投影、渐变按钮、居中三栏等宽网格、每块都描边、`Inter / Roboto / Arial / system-ui` 作主字体、被用滥的 `Space Grotesk`、散点式无意义微交互。**不得收敛到通用后台模板**。
- **production-grade**：真实接口、真实数据、零 mock；四态齐全；TypeScript 严格；不破坏 330 项既有测试；`prefers-reduced-motion` 降级有效。

### 6.2 字体

- 主字体沿用已自托管的 **Albert Sans**（`@fontsource/albert-sans`，现有 `--font-ui`），中文回退 `PingFang SC / Microsoft YaHei`。**不使用 Inter / Roboto / Arial / system-ui 作为主 UI 字体，不引入新的展示字体依赖**。
- 通过「字重 + 字距 + 字号」制造展示层：阶段大标题/超大序号用 600 字重、负字距 `-0.02em`、大字号（沿用 `--fs-head: clamp(1.5rem, 1.1rem + 1.6vw, 2.25rem)`，步序带序号可放大到 `clamp(48px, 6vw, 96px)` 作水印式数字），正文 500/400。
- **数字与代码用等宽**：`ui-monospace / SFMono-Regular / Consolas / monospace` 系统栈（不新增依赖），**仅**用于工程视角内的 hash、绝对地址、SCL 预览；主链不出现等宽技术串。
- 正文 ≥16px（`--fs-body`），小字 ≥13px（`--fs-small`），**禁止 <13px**；行高 1.5。

### 6.3 色彩

- 沿用现有 CSS 变量令牌，不另起一套：
  - 主动作深青 `--accent #0f5257`（`--accent-deep #0b3e42`）；墨 `--ink #141414`；成功 `--ok #2e6b46` **专用于步 4 完成态**；破坏级赭红 `--danger #a03123` **仅用于工程视角内的高危动作**，不进主链。
  - 纸面 `--paper-1 #eef0f7` / `--paper-2 #f6f7fb` / `--paper-3 #f0f1ee` **靠色阶分层，不用边框**；静止态无阴影、无渐变、**方角**。
- **四步换底**（`--ground`）：步 1 蓝图纸 `#c3cbe5` → 步 2 鼠尾草 `#cfd3cb` → 步 3 砂 `#e6dccd` → 步 4 冰蓝 `#bcc7e0` + 完成态 `--ok` 盖章点缀。
- **Dominant + sharp accent，反对平均分配**：大面积极简纸色，深青只出现在「当前步节点」与「当前步唯一主按钮」上；每屏最多 1 个强调色块 + 1 个主按钮，其余全部退到纸色/墨色。

### 6.4 动效

- 项目**未安装 Motion 库**（`package.json` 无 `framer-motion` / `motion`），依技能「Prioritize CSS-only solutions」执行，**纯 CSS，不新增动效依赖**：
  1. **一次编排好的入场**：首屏加载时，左侧 4 个工位节点 + 主工作区按 `animation-delay` 依次 staggered reveal（40–80ms 阶梯），只做一次；不做散点微交互。
  2. **signature move**：阶段换底 `background-color 620ms ease`（沿用现有慢速换底），是「纸在变」而不是「页面在跳」。
  3. **拖线反馈**：连线绘制用 `stroke-dashoffset` 行进，落点连接桩一次短脉冲；新增/删除连线有 120–180ms 的淡入淡出。
  4. **完成页盖章**：一次性 `scale + opacity` 入场（约 320ms），不循环、不弹跳。
  5. **hover 惊喜**：纸块 hover 反相为墨块（沿用 `.gf-block--ink`），而非抬升阴影。
- **必须保留** `prefers-reduced-motion: reduce` 全量降级（现有已实现）。
- **禁止**：常驻 loading 旋转、飘浮/视差、自动轮播、无限循环动画、弹跳缓动。

### 6.5 空间构成

- **非对称、破格、大留白**：左侧固定约 220px **竖排 4 个大号工位节点**（不是顶部细进度条），右侧为主工作区；不做等宽三栏、不做居中卡片网格。
- 主工作区内容左对齐、限最大宽度，右侧留出大块空白「纸面」；超大阶段序号以**水印式重叠**（overlap / grid-breaking）压在纸面上，不占位。
- **工程视角是右侧抽屉**：从右滑入、覆盖主链而非挤压主链，默认完全不可见；展开宽度约 420px。
- 密度控制：主链每屏只有一个主操作区 + 一个主按钮；信息密度全部让给工程视角（受控密度）。

### 6.6 四步各屏布局

**全局骨架**：左「工位步序带」（4 节点 + 完成态点亮）+ 右「阶段工作区」+ 右上角**单一**「工程视角」入口（默认折叠）。顶栏极简：业务项目名（**不显示 `project_id`**）+ 返回工作台。

| 屏 | 布局与内容 |
|---|---|
| **步 1 描述** | 中央偏左一个超大自然语言输入框（占位给示例描述文案，P1-4），下方以轻量节点/列表预览「解析出的设备与步序草图」；右下唯一主按钮「下一步：连线」。全屏无任何 hash / 版本 / 门禁 / 真机字样。完成态：草图出现 + 步序带节点 1 点亮。 |
| **步 2 连线** | 主区为全幅 `@xyflow/react` 画布：节点是工站/执行单元/执行件，用方角纸块 + 左右 8px 连接桩（沿用 `.gf-block` 母题）；从桩拖出新增连线、选中连线按 Delete 或点 × 删除、非法连线用桩点颜色 + 一行中文提示反馈（白名单取自 `whitelist.edge_kinds`）。原 `GreenfieldLinkPanel` 的下拉/表单收在画布**右下角默认折叠**的小面板「更多输入方式」，明确为辅助输入。底部主按钮「下一步：确认」。完成态：连线数 > 0 且校验通过，节点 2 点亮。 |
| **步 3 确认** | 一页三段式业务摘要：「你要做的事」（描述原文）/「你连的关系」（节点·连线数量 + 缩略图）/「你将拿到」（工程包 + 还原度报告）；一个深青主按钮「确认并生成工程包」。前置未满足时，用一句中文说明缺什么 + 「查看工程视角」跳转，**不展示 code、JSON、锁定清单**。完成态：生成成功后节点 3 点亮并进入步 4。 |
| **步 4 完成** | 整屏完成态：大号「工程包已就绪」+ `--ok` 盖章图形 + fidelity 报告摘要（业务化措辞、如实呈现，不伪装达标也不阻断完成）+ 醒目「下载工程包」按钮 + 次入口「重新调整」「开始新工程」。**此屏即用户可见终点**：无「待真机」横幅、无 A/B/C 状态条、无差异清单。真机口径仅在展开工程视角后出现。 |

### 6.7 工程视角折叠方式

- 右上角**单一入口**「工程视角」，默认 `collapsed`（首屏完全不可见，DOM 可存在但视觉隐藏，主链无任何契约术语泄露）。
- 点击展开为**右侧抽屉**（滑入约 240ms，宽约 420px，覆盖而非挤压），内部按分组再折叠：**① 契约与门禁**（D7/D10/D11/N9、spec_hash、step_order、PCEC、blocker 明细）**② 还原度与编译**（fidelity_ok、compile_diagnostics）**③ 三动作 A·B·C** **④ 差异清单逐项勾选** **⑤ SCL 只读预览** **⑥ 真机状态**（pending_real_machine）。
- 所有原字段**原样保留、值与 `/state` 一致**，仅位置从首屏移入抽屉；组标题可用工程术语（这是给审计/集成人员看的）。
- 折叠/展开是**纯前端视图状态**，不改变任何请求、不跳过任何写入门禁；抽屉内仍可完成差异清单逐项勾选、A/B/C、SCL 预览等原能力。

---

## 7. 明确的「不做」清单

1. **不做「演示模式」（建议 5）**：不引入离线 mock 数据、假 IR、假 fidelity、假成功态。P1-4 的示例描述仅是可点击的输入占位文案，仍走真实 `/chat`。
2. **不隐藏 / 不删除 / 不改动存量工作台（建议 6）**：存量工作台保持现状可达，顶栏保留显式返回入口；本轮只把**默认落地页**改为 4 步主链，而非把存量藏起来。
3. **不改后端任何文件**：`/state`、`/confirm`、`/generate`、`/deliver-tia`、A/B/C、`greenfield_service.py`、`gateway/` 等一律不动；`state/greenfield.ts` 现有 API 签名与行为不删不改。
4. **不改项目终态验收口径**：TIA V19 编译零错误、`真机全绿 = L1∧L2∧L3∧L4`、M4 发布门禁仍然有效且仍为未通过；`pending_real_machine` 不删除、不篡改、不伪装成成功。本轮只是不把它们当作 UI 首屏负担。
5. **不删信息**：契约/审计信息只是移到默认折叠的工程视角，完整性与可追溯性不降低。
6. **不新增第三方依赖**：不引入 MUI / Tailwind / framer-motion / 新字体包；复用 `@xyflow/react` / `elkjs` / `mermaid` / `@fontsource/albert-sans`。
7. **不改动与本轮无关的存量组件/样式**（`App.tsx` 仅路由挂载点例外），不新增构建配置或新脚本入口。
8. **不把 A/B/C、差异清单勾选、TIA 真机设为到达完成页的前置**。

---

## 8. 验收口径（可判定）

| # | 验收项 | 判定方式 |
|---|---|---|
| AC-1 | **主链首屏零内部契约术语** | 全新会话进入，步 1 屏幕/DOM 中不出现：`project_id`、`pending_real_machine`、`fidelity_ok`、`spec_hash`、`step_order`、`PCEC`、`compile_diagnostics`、`D7/D10/D11/N9`、A/B/C 动作标签、`blocker`、code 原文、「已锁定」、原始 JSON；仅「工程视角」入口可见 |
| AC-2 | **4 步各有完成态** | 步 1→2→3→4 每步有唯一主按钮 + 明确的本步完成视觉（步序带节点点亮 + 完成文案）；任意步可返回上一步且不丢已填描述与连线 |
| AC-3 | **拖线可新增/删除** | 步 2 画布从节点桩拖到另一节点可新增 1 条连线并在图上可见；选中后可删除且图上消失；刷新后与 `/state` 数据一致（复用 `add_edge/remove_edge`）；非法连线被拒并有中文提示 |
| AC-4 | **导出后可见完成页** | 走完步 3 触发生成后进入步 4，出现「工程包已就绪」类成功文案 + 可用「下载工程包」链接 + fidelity 报告摘要；**无需 TIA 真机、无需 A/B/C、无需差异清单勾选**即可到达 |
| AC-5 | **工程视角默认折叠** | 首屏面板不可见；点入口展开后可见分组内 `fidelity_ok` / `spec_hash` / `compile_diagnostics` / `pending_real_machine` / A·B·C / 差异清单逐项勾选 / SCL 只读预览，字段值与 `/state` 一致；折叠状态下主链仍能走完 |
| AC-6 | **拆分与范围** | 存在 4 个独立阶段页组件，`GreenfieldPanel.tsx` 不再作为 1393 行单组件承载全部信息；`App.tsx` 仅路由挂载点改动；后端目录零 diff；`state/greenfield.ts` 现有导出函数签名不变 |
| AC-7 | **构建与回归** | `npm run build` 通过；`npm run test` 通过且通过数 ≥ 330（无回退、无新增 skip） |
| AC-8 | **消除重复输入** | 全流程「工艺描述」输入框仅 1 处 |
| AC-9 | **文案** | 主链所有可见提示/错误为中文，不出现原始英文 error code；不存在 `JSON.stringify(summary)` 弹窗 |
| AC-10 | **设计规范** | 主字体为 Albert Sans（非 Inter/Roboto/Arial/system-ui）；无紫色渐变、无新增 UI/动效依赖；`prefers-reduced-motion` 下动效降级生效 |

---

## 9. 待确认问题（均非阻塞，主理人可按推荐默认值代采用）

| # | 问题 | 推荐默认值 |
|---|---|---|
| Q1 | 无活跃会话/新会话时，是否默认进入 4 步主链？ | **是**。默认落地页改为 4 步主链；存量工作台不隐藏，顶栏保留显式返回入口（兼顾「不做建议 6」）。**主理人可按推荐默认值代采用** |
| Q2 | 是否允许改 `GreenfieldLinkPanel.tsx`？批准项 2 的范围未列它，但批准项 4 要求把它降级 | **允许最小化改动**：仅布局降级为默认折叠的「更多输入方式」辅助面板，不改其 props / 数据绑定；优先通过 `GreenfieldChannel` 容器层实现。**主理人可按推荐默认值代采用** |
| Q3 | fidelity 报告未达标时，完成页如何呈现？ | **仍显示完成态**（工程包已生成），fidelity 结论以中文业务措辞如实展示（不伪装达标、不阻断完成），原始 `fidelity_ok` 明细留在工程视角。**主理人可按推荐默认值代采用** |
| Q4 | 步 3 后端 `/confirm` 仍有 5 项硬门禁，前置未满足时主链如何引导？ | 主链给一句中文说明 + 「查看工程视角」跳转，逐项清单只在工程视角展开，不在主链铺开。**主理人可按推荐默认值代采用** |
| Q5 | 阶段页文件命名与样式归属？ | `frontend/src/shell/steps/StepDescribe.tsx` / `StepLink.tsx` / `StepConfirm.tsx` / `StepDeliver.tsx` + 一份新增 `steps.css`（或在 `greenfield.css` 追加新段），全局变量令牌复用不重写。**主理人可按推荐默认值代采用** |
| Q6 | 是否新增前端测试覆盖 4 步路由与拖线增删？ | **是**，新增纯逻辑/渲染测试，不修改既有 330 项断言。**主理人可按推荐默认值代采用** |

> 以上 6 项均为非阻塞项，架构师可直接按推荐默认值开展设计，无需等待用户答复；如主理人有不同判断，以主理人裁定为准。
