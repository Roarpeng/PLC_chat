# HR001 AF V1.2 重构工程发布包

## 1. 工程交付概览
- **项目名称**: HR001_PLC_20260509 (西门子 S7-1200 / TIA Portal V19)
- **目标架构**: Siemens Automation Framework (AF) V1.2
- **归档格式**: Siemens TIA Portal V19 官方归档包 (`.zap19`) 及完整发布包 (`.zip`)
- **归档文件**: `HR001_AF_V1_2.zap19` (15,647,358 字节)
- **发布包文件**: `HR001_AF_V1_2_Package.zip` (15,605,817 字节)

## 2. 核心重构达标验证
1. **100% 纯 SCL 改写 (0 LAD)**:
   - 全工程共计 41 个 Function Block (FB)。
   - 原项目中 28 个 LAD FB 全部重构改写为纯 SCL 代码。
   - 原项目中 13 个原生 SCL FB 保持原生架构，修正自身实例访问与类型安全。
   - 经 TIA Openness 现场实时扫描：**SCL FBs = 41，LAD FBs = 0**，达成 100% SCL。
2. **AF 装备模块 (Equipment Module) 架构层级**:
   - 项目树已完整建立并包含 13 个 AF 用户组：
     - `U1_HR001`: 单元主控
     - `U1Em0_General`: 公共控制模块
     - `U1Em1_AutoStep`: 自动流程核心模块
     - `U1Em2_RobotAutoStep`: 机器人协同控制模块
     - `U1Em3_HorDrillAutoStep`: 水平钻孔模块
     - `U1Em4_VerDrillAutoStep`: 垂直钻孔模块
     - `U1Em5_FeedAutoStep`: 进料供料模块
     - `U1Em6_Kuka_General`: 机器人通用通讯模块
     - `U1Em7_FC2600CCControl`: 视觉通讯模块
     - `U1Em8_FC2600FTControl`: 力控调整模块
     - `001_KL_Standard_Lib`: 标准库模块
     - `002_Err_Prompt`: 报警与提示模块
     - `099_System_OB`: 系统中断与循环组织块
3. **物理 I/O 与数据块偏移 100% 保留**:
   - 全部 113 个物理 I/O 测点（包括安全门、夹具、各工位气缸在位、钻孔传感器等）保持原物理地址（%I / %Q）1:1 严格映射。
   - 非优化访问数据块保留 `{ S7_Optimized_Access := 'FALSE' }`，保证数据块字节偏移（Byte Offset）100% 与原项目完全一致。
4. **编译 0 错误 (0 Errors)**:
   - 经 TIA Portal Openness 原生 `ICompilable.Compile()` 严格编译验证：
     - **Compile State: Warning (Success)**
     - **Error Count: 0**
     - **Warning Count: 92**（均为常规精度/未初始化参数提示，无任何语法或类型错误）

## 3. Web UI 下载与本地路径
- **Web UI HTTP 下载接口**:
  - TIA 归档包: [下载 HR001_AF_V1_2.zap19](http://localhost:8000/api/v1/plc/canvas/download-package?package_type=zap19)
  - 完整发布包: [下载 HR001_AF_V1_2_Package.zip](http://localhost:8000/api/v1/plc/canvas/download-package?package_type=zip)
- **本地归档文件**:
  - `PLC_Openness_data/hr001/HR001_AF_V1_2.zap19`
  - `release_packages/HR001_AF_V1_2_Package/HR001_AF_V1_2.zap19`
