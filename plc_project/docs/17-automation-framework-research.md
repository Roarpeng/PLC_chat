# 17 · Siemens Automation Framework 深度调研报告(内核集成前研)

日期:2026-10-24 · 来源:官方 AF V3.0 手册(2026-06 版)与 AF Basic V2.2 手册在线文档全文抓取(存档于 `tmp_validate/af_research/`)。

## 1. AF 是什么

西门子官方的**离散自动化标准化工程框架**(SIOS 109817223),定位:给机械制造商(OEM)与终端客户提供"可靠、开放、模块化"的 TIA Portal 工程平台,让不同机型共享同一程序架构。两个版本:

| 版本 | 定位 | 库 | 结构载体 |
|---|---|---|---|
| **AF(V3.0)** | 中高端机型 | **LAF**(Library of Automation Framework,核心块)+ LPML(PackML 状态机)+ LUC(单元控制) | **软件单元**(Software Units)每 Unit/EM 独立 |
| **AF Basic(V2.2)** | 中低端、S7-1200/Unified Basic Panels | **LBC**(基础控制库,CM 实现)+ LPML + LUC + LAF | **文件夹结构**(无软件单元) |

本质 = **西门子把 ISA-88 + OMAC PackML + 自家编程风格指南 + 参考标识系统(RDS)打包成一个可直接复制的工程模板 + 全局库**。

## 2. 核心架构(官方手册还原)

### 2.1 ISA-88 物理模型(层级)

```
Process Cell(产线,多 Unit 组合)
└── Unit(单元 = 独立加工设备,如反应釜/工作站;含状态机,一次只持一个批次)
    └── Equipment Module / EM(功能组 = 围绕一个工艺目的的 CM 集合,自带顺序控制、异常保持逻辑、可共享可仲裁)
        └── Control Module / CM(最低层 = 直接对应传感器/执行器:泵/阀/电机/PID 回路;接 IO,含设备级异常保护)
```

- 自上而下:**模块可独立运行/测试/克隆**,类型-实例(TIA 类型版本)提高复用。
- EM 分区准则:同类工艺目的、自包含、可复用、能独立运行、异常尽量封闭在 EM 内。
- **共享 EM**:多 Unit 运行时仲裁分配(alloc/lock),由 Unit 层裁决。

### 2.2 Mode & State 模型(OMAC PackML)

- 每个 Unit 一台状态机;**默认 OMAC PackML(TR88)**,LAF 提供 `LAF_typeModes/States/StateCommands/ModeCurrent/StateCurrent`(DINT 表示)。
- **模式**(最多 16):Production(必选)/Maintenance/Manual/自定义(最多 13 用户模式)。
- **状态**全集:Clearing/Stopped/Resetting/Idle/Starting/**Execute**/Stopping/Holding/Held/Unholding/Suspending/Suspended/Unsuspending/Completing/Completed/Aborting/Aborted —— 分"动作态(ING)"与"等待态"。
- 命令可来自:HMI 操作员、线上其他系统、过程自身(如缺料/故障)→ 由 Unit 的 Mode-State Manager 统一裁决。
- 可配置:每模式启用哪些状态/迁移、Hold/Complete 迁移许可。

### 2.3 PLC 程序分部与数据流(严格单向)

程序分部及**读写关系矩阵**(防环):

- **Central Functions**:可读写所有部;其他部不得写它(经自有 DB 供其读);产出经 Global 下发。
- **Safety**:唯一的中心安全部(F-RuntimeGroup);**不主动读写任何部**,其他部经 `DB DataToSafety / DataFromSafety` 与之交换单向数据。
- **Global**:纯数据枢纽(无逻辑,除变量监控报警)。接口 DB:`DB Data`(单元级全局)、`DB Units`(Unit 状态+EM 反馈,HMI 也读)、`DB Hmi`(HMI 控制接口)、`DB Relations`(跨 Unit/EM 直连交换)、`DB Allocation`(共享模块分配)。
- **Unit**:读写 Global/Safety/Library;经 FB **`CallUnit`** 执行(状态/模式/状态机、命令合并、报警→命令)。
- **EM**:读写 Global/Safety/Library;经 FB **`CallEquipment`** 执行(顺序+CM 调用,向 Unit 回 SC[StateComplete] 与命令)。
- **Motion**:TO 由 OB Servo/Interpolator 处理;高性能路径命令直接进 motion cycle(OB PreInterpolator)。

### 2.4 Unit 内部信号流(AF Basic 细节)

```
EM 反馈 + Unit 自身状态 → FB LUC_StatusCollector(生成过程接口)
→ FB LUC_InterfaceManager(合并外部命令源:HMI/IT/过程)
→ FB LPMLV2022_UnitModeStateManager(裁决模式/状态)
→ 写 DB Units → EM 读取执行 → 反馈回 Unit(下一周期)
伴随:LUC_SetModeCurrent/SetStateCurrent/UpdateModeStateHistory(最近 8 步)
      LPMLV2022_UnitModeStateTimes(各状态停留时间统计)
```

块清单:`OB Startup/Main/ProDiag` + `FB CallUnit` + `FC CollectAlarms` + `DB Alarms/DB Config`(RDS、栈灯行为、OPC UA 使能、状态机配置 enableModes/enableStates/enableModeTransitions/enableHold/enableComplete、特殊功能)。

### 2.5 EM 内部结构与 Job/Sequencer

- 块:`OB Startup/Main` + `FB CallEquipment` + `FB Sequence` + `FC StepToString` + `DB Config / DB ControlNodes / DB HmiInterface / DB Alarms`。
- **执行次序**:评估与 Unit 的联锁状态 → 传感器类 CM → Unit 状态映射到序列前置条件 → **Job 选择** → 序列执行 → CM 复位/使能评估 → 执行器类 CM → 报警收集 → 事件触发命令 → **StateComplete(SC) 判定与汇总**。
- **Job Control**(`LAF_SelectJob` 每作业一实例):输入 startCondition/interlock/jobNumber/singleCycleJob;输出 readyToStart/startInterlocked/active/completed/aborted —— 作业 = EM 的一项功能(初始化/输送/……)。
- **Sequencer**:LAD 与 SCL 双模板(`LAF_ControlLadSequence` 等负责保持/单步/初始化),步骤号经 StepToString 转可读字符串。
- **Interlink**:`LUC_InterlinkToParent` 支持 EM 与 Unit 解联(调试/冗余),解联后 `LAF_ControlEm` 可仿真 Unit 模式状态直接操作 EM;联/解联仅允许在配置的状态(默认 Idle/Stopped/Aborted)。
- **CM 接口 = PLCOpen**:至少 `enable` 入;`valid/busy/error/status` 出;AF 用 **ControlNode UDT** 版 LBC:命令 UDT + 监控 UDT + 命令配置 UDT 归一到 control node,序列只与 `DB ControlNodes` 交互(集中数据枢纽,禁止序列直连 CM 引脚)。

### 2.6 OB 编号公式(执行顺序保障)

```
OB 号 = [uu][ee][t]   uu=Unit号+10;ee=0(Unit)/EM号;t: 2/3/4=Unit 的 Startup/Main/ProDiag,6/7/8=EM 的
例:Unit0-EM1 → 11016/11017/11018;Unit1-EM2 → 11226/11227/11228
固定:Central Functions Startup=100/Main=1/ProDiag=250;Safety=251;Global=252
```

### 2.7 软件单元与命名(V3.0)

- 软件单元:`Central Functions`/`Global`/`LibraryObjectsUsed`(必选,无命名空间)、`Safety`/`Motion`(可选)、`Ux_UnitName`、`UxEMy_EmName`(每 Unit/EM 一个,带命名空间,可整单元克隆不改名)。
- 跨单元访问必须配 **relations + publish**;TO 不能进软件单元。
- 紧凑布局(单软件单元合并所有 EM)为备选。
- **Reference Designation System(RDS)**:位置标识(Plant→Area→Zone→Station→Cabinet)+ 功能标识(设备/器件)唯一编号一切对象;**文件夹编号** `<U><EM>_EmName`(如 `12_Em2_Template_SCL` = Unit1-EM2);全局常量 `NO_OF_UNITS` + 各单元号常量。

### 2.8 HMI 架构与规范

- **页头 header**(`DB Hmi.mainHeader[n]`)→ `LAF_PanelHmi` 分发到选中 Unit 的 `unitHmiInterface`,反向合并状态回显;多面板/多 PLC 场景内建(Panel Management)。
- 导航:Main → Sub → Third → **Unit 导航**;Machine Overview;每 EM 的 faceplate 接 `DB HmiInterface`;状态机可视化画面(状态图+历史 8 步+时间统计);Operation Lock 机制;统一色板。
- 风格:遵循 Siemens Programming Style Guide(S7-1200/1500)+ Safety Guideline + WinCC Unified 工程指南,已登记少量偏差(NF005/006 大小写、NF007 前缀、DA005 形参传数据——库块强制接口,调用环境块允许直接访问本软件单元内 DB)。

## 3. 与本项目现状对照

| AF 维度 | 本项目现状 | 差距 |
|---|---|---|
| 物理模型 U/EM/CM | 无此概念;块是平铺列表(演示画布)或导入工程的原始结构(HR001 的 FB10xx 平铺) | **核心差距**:Process-IR 与 canvas 均无 ISA-88 层级 |
| Mode/State | 无 PackML;HR001 有 MainStep 步序字(非标准状态机) | 需引入状态机模板 |
| 接口 DB 体系(Data/Units/Hmi/ControlNodes/Relations/Allocation) | 无;变量平铺在块接口/DB | 生成器需产出接口 DB 族 |
| CM PLCOpen 接口 | 无统一 CM 抽象 | 需 CM 模板(命令/监控/配置 UDT) |
| OB 编号/软件单元/文件夹规范 | NL 生成块无编号体系 | 生成器需编号分配器 |
| HMI 导航/faceplate/header | HMI 仿真面板为自由控件 | 可后置 |
| RDS 命名 | 匈牙利前缀(i_b/q_b)风格 | RDS 为增量项 |
| 写回 TIA(External Source/编译闭环) | **已打通**(真实 TIA 全绿) | 是集成的落地面 ✅ |

**有利条件**:我们的 LAD→SCL 逆向、NL 编辑、编译自愈、回写链路已验证;AF 的 Unit/EM/CM 骨架在 SCL 层完全可由外部源生成(块+DB 均为 SCL/DB 文本),不强依赖图形工程。

## 4. 内核集成方案(建议)

**原则:AF 成为代码生成的"目标架构档位(AF Profile)",Process-IR → AF 结构化 SCL;新建/重构/修复三条路径全部过 AF 校验。**

1. **内核新增 `AF Profile` 模块**(plc_engine/af/):
   - `af_model.py`:U/EM/CM/Job/SC/ModeState 的 IR 扩展(canvas block 增加 af_level: unit/em/cm/global 等元数据);
   - `af_templates.py`:Unit 骨架(OB Startup/Main + CallUnit + DB Alarms/Config + 状态机调用)、EM 骨架(CallEquipment + Sequence + Job + ControlNodes/HmiInterface + SC)、CM 骨架(PLCOpen 接口 + 命令/监控 UDT)、Global 接口 DB 族;
   - `af_ob_numbering.py`:OB 号分配器(公式实现);
   - `af_linter.py`:合规校验(层级唯一父、数据流方向、ControlNodes 中枢、命名/RDS、OB 号),接入现有 precheck/编译门禁与"一键自愈"提示。
2. **三条路径落点**:
   - **新建**(NL → Process-IR → SCL):IR 先物化为 AF 结构(把"泵/阀/电机"落为 CM,工艺步骤落为 EM Job/Sequence,设备单元落为 Unit),再生成;
   - **重构**(legacy LAD/SCL → 结构化):逆向产物按 AF 模式**归类映射**(现有 FB1060_AutoStep 步序字 → PackML 状态机候选;FB10xx 设备块 → CM/EM 候选),映射是建议+人工确认,不自动改写语义;
   - **修复**:修复后的输出必须仍过 af_linter,防"修一个破坏架构"。
3. **库依赖策略(关键决策)**:
   - **方案 A(推荐起步)**:**自举最小实现**——不依赖官方 LAF/LUC/LPML/LBC 文件,由模板生成等价的简化 SCL(自研 mini 状态机 + PLCOpen CM + ControlNode UDT),保证零外部依赖即可编译回写;
   - **方案 B(完整对齐)**:用户提供 AF 库(.al19 全局库文件)→ 导入工程 → 生成代码直接调用 LAF/LPML/LBC 官方块。需要你确认手上是否有 AF/AF Basic 的库文件与版本。
4. **写回适配**:AF 生成的 DB/OB 均走既有 External Source 通道(OB 需 XML 形式或工程内已有——OB 默认不可外部源导入,**OB 生成需走 Openness 导入 XML 路径,这是我们 CLI 已有的 Import 能力**)。

## 5. 落地路线(建议四阶段)

1. **P1 内核骨架**:af_model + templates(Unit/EM/CM/接口 DB)+ OB 编号 + linter;演示画布可生成一个 AF 结构的样例 Unit+EM+CM 并回写编译通过;
2. **P2 新建路径**:NL 新建块默认走 AF Profile(类型识别:电机/阀/缸→CM;工艺流程→EM Job;工位→Unit);
3. **P3 重构路径**:legacy→AF 映射建议器(基于块名/结构特征),HITL 确认后落 IR;
4. **P4 完整对齐**:接入官方 LAF/LPML/LBC(若取得库文件)+ HMI header/导航模板 + RDS 命名。

## 6. 待确认决策

1. 目标档位:**AF Basic(文件夹版,适配你现网 S7-1200/V19)** 还是 **AF V3(软件单元版)**?建议先 Basic。
2. 是否能取得官方 AF/AF Basic 库文件(.al17/.al19)与示例工程?决定方案 A/B。
3. 存量工程(HR001 类)是否要求最终"AF 化",还是仅新建部分 AF 化?
