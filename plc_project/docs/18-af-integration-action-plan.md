# 18 · AF 集成具体行动计划(A 方案:自举 AF Profile → 官方库对齐)

日期:2026-10-24 · 依据:docs/17 调研报告 + 两份官方手册全文(V3.0 330 页 / Basic V2.2.4 296 页,提取存档 `tmp_validate/af_research/`)+ AF V3.0 参考工程包(V20,待装 V20 后启用)。
已确认决策:**A 方案**(先自举,后对齐官方库);**新建与存量重构都遵守 AF 架构**;V20 就绪前不依赖官方库文件。

## 0. 关键技术约束(决定实现形态)

1. **External Source 无法创建软件单元/文件夹**:我们的 TIA 写回主通道是 SCL 外部源(V19 已验证)。因此 P1–P3 采用 **AF Basic 文件夹版架构语义**(逻辑分层在 IR/画布),TIA 内块名带命名空间前缀(`U1_`、`U1EM2_`)保证可读与唯一;物理文件夹/软件单元归属留待 XML 导入通道(P4)。
2. **OB 不能由外部源生成**:Unit/EM 的 OB 骨架走 **SimaticML XML 导入通道**(CLI 已有 Import 能力,标签表已走此路);纯逻辑(FB/DB/UDT)走 SCL 外部源。
3. **自举 ≠ 简化语义**:状态机/接口结构严格按 PackML + AF 数据流(单向、接口 DB 族、ControlNode 中枢、PLCOpen CM 接口),只把官方库块(LAF/LPML/LUC/LBC)替换为等价自研 SCL 块——P4 时块名对调即可切换。

## 1. P1 内核 AF Profile(自举)——1 个迭代

**交付物:`plc_engine/af/` 模块族**

| 文件 | 内容 |
|---|---|
| `af_model.py` | AF IR:`AfMachine{global, units[]}`;`AfUnit{no,name,ems[],modeStateCfg}`;`AfEm{no,name,jobs[],sequence,cms[]}`;`AfCm{kind(motor/valve/sensor/pid/…),io}`;与 canvas 块互转(canvas 块增 `af_path` 元数据,如 `U1.EM2.CM3`) |
| `af_packml.py` | PackML 枚举(DINT):modes(Production/Maintenance/Manual/自定义≤16)、states 17 态、commands(Start/Stop/Reset/Clear/Hold/Suspend/Abort/Unhold/Unsuspend/Complete)+ 每模式使能位集 |
| `af_blocks.py` | 自举块族(等价官方块,纯 SCL):`AFB_StateMachine`(≈LPML UnitModeStateManager)、`AFB_StatusCollector`/`AFB_InterfaceManager`(≈LUC)、`AFB_SelectJob`(≈LAF_SelectJob,五状态 ready/interlocked/active/completed/aborted)、`AFB_Interlink`/`AFB_ControlEm`、CM 基类 `AFB_CmBase`(PLCOpen:enable/valid/busy/error/status + 命令/监控 UDT)、电机/阀/传感器三个首批 CM 实现 |
| `af_templates.py` | 生成器:Unit 包(OB Startup/Main[XML] + `FB CallUnit` + `DB Alarms/Config` + 状态机调用 + 历史环形缓冲 8 步)、EM 包(OB[XML] + `FB CallEquipment` + `FB Sequence`[SCL 步序+Job 分派] + `DB Config/ControlNodes/HmiInterface` + `FC StepToString`)、Global 接口 DB 族(`DB Data/Units/Hmi/Relations/Allocation` + 常量 `NO_OF_UNITS`/`U#_EM#`)、UDT 族(ControlNode/UnitFeedback/EmFeedback/ModeStateCurrent/History) |
| `af_ob_numbering.py` | OB 号分配:`[Unit+10][EM][t]` 公式 + Central/Safety/Global 固定号段,冲突检测 |
| `af_linter.py` | 门禁规则:①层级唯一父(U→EM→CM);②数据流方向(EM 不写 Unit DB、跨层只经 Relations);③序列↔CM 只经 ControlNodes;④CM 接口必须 PLCOpen 五信号;⑤命名空间前缀/OB 号/RDS 格式;⑥状态机命令必须经 InterfaceManager 合流。输出 violations 挂 canvas 块 errors + precheck 集成 |
| `af_naming.py` | RDS 简化版:位置标识 + 功能标识 → 块/变量命名串 |

**验收(P1 出口标准)**:NL 指令「创建一个 AF 工程:1 个单元 U1_Test,含进料 EM(J1_Init/J2_Feed)与电机/阀 CM」→ 生成全套 SCL+XML → **回写真机 TIA(V19)编译零错** → 画布呈现 AF 层级 → linter 零违规。测试:每模块单测 + 生成快照测试 + linter 规则测试。

## 2. P2 新建路径 NL→AF——半个迭代

- 意图识别扩展(chat_ops 意图 + canvasOps):「创建单元/工位」→Unit;「添加功能组/工序」→EM;「添加电机/阀/传感器/ PID」→CM(映射到 `AFB_Cm*`);「加急停」→ Global 保留位 + Safety 建议提示;
- 生成落位:新块自动带 `af_path`,OB 号自动分配,常量表自动维护(NO_OF_UNITS 等);
- 对话解释:块详情面板展示 AF 层级与角色(Unit/EM/CM/接口 DB)。

**验收**:NL 依次描述一个小机型(单元+2 EM+3 CM+手动/自动模式),全程不接触底层块名,产出与 P1 样例等价并编译通过。

## 3. P3 存量重构映射器——1 个迭代(HR001 试点)

- **特征映射器** `af_mapper.py`:对导入工程给 AF 角色建议——
  - 块名/结构特征:步序字+自锁(FB1060_AutoStep 型)→ Unit 状态机候选;设备分组(FB1080_Component 型多实例)→ EM 候选;单设备小 FB(FB5002 安全门型)→ CM/EM 候选;DB10xx 参数/状态库 → Global 接口 DB 候选;
  - 输出:**映射建议清单**(块 → AF 角色 + 证据 + 置信度),画布新面板「AF 重构建议」,**人工逐条确认**(默认不应用);
- 确认后:IR 标注 af_path + linter 报告差距清单(哪些数据流/命名不合规)→ 修复建议进对话循环(接现有自愈通道);
- **铁律**:映射不自动改写语义;确认前原始块不动;Safety 块永不重写。

**验收**:HR001 89 块产出完整映射建议,用户确认 1 个 Unit 试点(FB1060 簇)重构后回写编译通过、步序语义等价(用 16 号报告的等价性方法回归)。

## 4. P4 官方库对齐(装 TIA V20 后)——1 个迭代

- 从 AF V3.0 参考工程(.ap20)逆向 LAF/LPML/LUC/LBC 块接口与 UDT(Openness 导出);
- `af_blocks.py` 加"官方库后端":同模板切换为调用 `LAF_*`/`LPMLV2022_*`/LBC ControlNode 版块(库文件经全局库导入通道进工程);
- HMI 模板(header/导航/状态机画面)、RDS 全量、软件单元/文件夹 XML 导入;
- SIMIT/PLCSIM 工作区接入数字孪生沙盒(可选)。

## 5. 里程碑与依赖

| 阶段 | 内容 | 依赖 | 验证 |
|---|---|---|---|
| P1 | 内核 AF Profile + 样例闭环 | 无 | 真机 V19 编译零错 |
| P2 | NL 新建走 AF | P1 | NL 端到端 |
| P3 | 存量映射重构 | P1 | HR001 试点等价回归 |
| P4 | 官方库对齐 | **TIA V20 安装** | 与官方工程结构比对 |

风险与对策:OB XML 导入通道未在 V19 验证过 OB 类型 → P1 第一周先做通道探针;自举块与官方块语义差异 → P4 逐块接口比对表;存量映射误判 → 默认建议+人工确认制。
