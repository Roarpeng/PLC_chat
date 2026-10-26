# 23 · AF 内置化三线契约(两入口 / 导入自动 AF 化 / 新建全 AF)

依据:用户 4 点指示 + 三点确认(需求卡并入新建;不可证等价→保留原样+标注;官方 V1.2 库优先)。复用外部会话 `plc_engine/af/*` 引擎,**禁止平行造轮子**。

## 0. 产品原则(全线遵守)

- **AF 对用户隐形**:用户可见文案零"AF/架构/软件单元"术语(模块名/代码标识保留);
- **物理冻结铁律(导入线)**:存量工程的 DB 布局与偏移、绝对 IO 地址、符号表、OB 编号与调用顺序、F/安全块——**一字不动**;"AF 化"= 逻辑层(SCL 直译已有)+ AF 角色覆盖层(af_role 标注);
- **诚实边界**:无法证明等价的块保留原始形态,标 `af_pending_manual` + 原因,绝不静默近似;
- 所有自动转换经 PCEC 留痕(kind=`af_import`),四层审查可见。

## 1. U 线(UI 两入口去 AF 术语)

- 启动屏 **两个入口**:「导入工程」(现有逻辑不变)、「**新建工程**」;
- 新建工程流:点击 → 打开需求卡草稿(用户输入工艺需求,LLM 生成七字段卡)→ 「确认工艺意图」后弹出**最小创建确认**(项目名,默认取 intent_summary 洗成合法标识;目标目录可选,复用 CreateBlockDialog 的 targetDir 逻辑)→ 调既有创建链(template af_v1_2)→ 画布就绪后对话提示「工程已创建,可继续描述工艺生成逻辑」;
- 全部用户可见文案去 AF:启动屏第三个入口删除;按钮描述改「从工艺需求开始,自动生成标准结构工程」类中性文案;TaskQuickBar/WorkbenchHeader 若含 AF 字样一并清理;
- 只改:App.tsx、ProjectLaunchScreen.tsx、少量 css;F 线组件 props 不变。

## 2. I 线(导入自动 AF 化,后端)

- 新 `gateway/app/services/plc/af_import.py`:
  - `analyze_import(canvas) -> AfImportReport`:`LegacyToAfMapper(canvas).analyze()` 复用 → {conformant: bool, roles: {block_name: "unit|em|cm|global|safety|unknown"}, pending: [{block, reason}], coverage};
  - `apply_af_overlay(canvas, report) -> CanvasState`:对已解析块挂 `af_role`(canvas block 新增可选字段,缺省无,兼容);SCL 直译已在导入链完成(勿重复);**F/safety 块与 DB 型块一律 role=global/safety 不动**;pending 块保持原 status + errors 附「AF 转换待人工确认:原因」;
  - 转换经 PCEC:new_change(kind="af_import", request="导入自动AF化", touched=已标注块, baseline=工程基线) → v0/v1 pass → approved(自动转换由导入动作承载,approval.reviewer="auto_import",events 注明) → applied;
- 接入:canvas/import/upload 成功路径(try/except 兜底,失败仅 warning 不阻塞导入);响应 data 增 `"af_analysis": {conformant, roles_count, pending_count}`;报告存 `PLC_WORK_DIR/af_reports/<project>-<ts>.json`;
- API:`GET /api/v1/plc/canvas/af/report/latest?project=<name>` → 最新报告;
- 测试:HR001 夹具(hr001 export 已有缓存)——roles 非空、DB 块不动、pending 诚实、PCEC 事务生成、导入失败兜底。

## 3. N 线(新建全 AF 链,后端)

- 先侦察:外部会话已在网关加了什么(templates/af 创建端点、`clone_startup_template` 调用点)——**有则复用扩展,无则新建**;
- 新端点 `POST /api/v1/plc/canvas/generate-from-requirement`:body {requirement(完整对象,须 confirmed), project_name, target_dir?} → 校验 confirmed(未确认 400 REQUIREMENT_NOT_CONFIRMED)→ `af.planner`/文本规划(复用 `_plan_em_from_text` 等)构建 AfProject → `generate_af_project_blocks` → 合成 CanvasState(块带软件单元命名 `U#_EM#_名`,status=draft)→ `lint_af_canvas` + 既有 `scl_precheck` 双门禁(IEC 61131:标识符合法/PLCLopen 五信号/命名前缀 i_/o_/stat_)→ 返回 {canvas, linter_findings, blocks_created};
- 前端对接(最小):该端点由「确认工艺意图后的工程创建链」调用(U 线创建工程后,若存在 confirmed requirement → 自动调本端点把逻辑块生成进画布);U 线只调 API,逻辑在后端;
- 测试:confirmed 校验、从含设备与步骤的需求生成块、linter 发现注入、IEC 违规示例被拦截。

## 4. 收口验收

后端+前端全量测试绿;浏览器端到端:①导入 HR001 → 响应含 af_analysis、画布块带角色、无物理变更(块数/标签数不变);②新建工程 → 输入工艺需求 → 需求卡确认 → 工程创建+逻辑块生成+lint 零错误;③所有界面文案无"AF"字样(收口 grep 前端用户可见字符串)。
