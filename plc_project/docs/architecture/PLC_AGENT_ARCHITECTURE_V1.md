# PLC Agent 目标架构与 Greenfield / Brownfield 重构 RFC v1

> 日期：2026-11-09  
> 审查基线：`dev/greenfield-wp`，提交 `2856787847b0f769ee0581d96bc11fa48d3a4745`  
> 目标：自然语言 + 可编辑工艺 Canvas → AF 架构逻辑 → 真实 Siemens TIA Portal 原生工程。  
> 本文是方案与代码审查，不是现场 TIA V19 实机验收报告。

## 0. 业务边界与最终交付

- **新工程 (Greenfield)**：先在真实 TIA 中创建工程，提供硬件与设备组态的占位/后续人工配置能力；用户描述元器件后生成控制模块 (CM) 驱动；描述工艺后生成可编辑、可审核的步序/联锁/时序模型；确认后通过 Openness 写入 TIA，编译并生成与项目身份绑定的 **真实原生工程归档 `.zap19`**。
- **旧工程 (Brownfield)**：真实 `.ap19` 或 `.zap19` 导入→解析工程结构和软件逻辑→保持原有地址、编号、接口和不受控块→自然语言与 Canvas 共同生成显式 ChangeSet→确认后在原工程的**可回滚工作副本**上增删改→编译→归档。原件默认不可被无确认地覆盖。
- **硬件/组态占位**：`logical placeholder` 代表未分配物理设备/地址；`TIA skeleton` 是真实 TIA 工程。若要求执行 PLC 侧编译，需选择一个安装版支持的真实 CPU 或导入已有 CPU 工程模板，不能让不存在的 PLC 软件容器通过编译。用户无需在本产品界面填写实际 IO 地址；可留待 TIA 手工绑定。
- **交付状态严格区分**：`spec_frozen`、`source_package_ready`、`tia_project_created`、`tia_imported`、`tia_compiled`、`native_archive_ready`。仅 `native_archive_ready` 代表完整 TIA 项目完成。SCL/XML ZIP 叫“源码/导入包”，不得冒称完整可打开 TIA 项目。
- 严禁未经另外明确审批进行 PLC 在线下载、运行/停止、安全程序修改。普通急停逻辑描述只生成**外部安全状态的接口与联锁需求**，不自动生成 Safety/F 程序。

## 1. 当前代码资产（保留，不推倒重来）

| 能力 | 权威现有位置 | 结论 |
|---|---|---|
| AF Unit/EM/CM 数据模型和生成器 | `plc_engine/af/af_model.py`、`af_generator.py`、`af_linter.py` | 保留 |
| 唯一 Greenfield IR 和原子 patch | `plc_engine/af/greenfield_ir.py`、`greenfield_validator.py` | 保留/扩展 |
| 工艺三视图和 Mermaid 投影 | `plc_engine/af/greenfield_views.py` | 保留为只读投影，新增可编辑时序语义 |
| NL 草稿与事务修改 | `gateway/app/services/plc/greenfield_draft_llm.py`、`greenfield_chat.py` | 保留，增加 DriverSpec/SequenceSpec |
| AF 源码包 | `plc_engine/af/greenfield_delivery.py` | 保留为源产物生成器，禁止冒称原生项目 |
| TIA 创建/组态/导入/编译/归档 | `industrial/tia_openness_cli/src/TiaOpenness.Server/` | 保留为**唯一受控真实写端口** |
| Greenfield TIA 交付编排 | `gateway/app/services/plc/tia_delivery.py` | 加入原生归档、命名对齐和状态门禁 |
| 旧项目 Openness 导入和 AF 角色映射 | `gateway/app/services/plc/canvas_import.py`、`af_import.py`；`agents/plc/tia/` | 保留/接入统一模型 |
| 原有增量回写与 PCEC | `gateway/app/services/plc/greenfield_service.py` Action A/B/C、`plc_engine/pcec.py` | 保留，在受控工作副本上运行 |
| Web 工程工作台 | `frontend/src/shell/GreenfieldChannel.tsx`、`steps/` | 改造入口和交付条件；ReactFlow 复用 |

**不应继续开发的第二套权威后端**：`plc_gateway/` 已被仓库 README 标为历史副本，真实路由入口应统一到 `gateway/app`。

## 2. 审查发现（代码可追踪）

### G-01 · Greenfield 页面“完成”与原生工程交付脱节（P0）

`frontend/src/shell/GreenfieldChannel.tsx::onConfirmAndGenerate` 当前链：
`confirmSpec → generateProjectPackage → refresh → GO(4)`。
没有执行 `deliverTia(mode="auto")`、真实编译、`archive-project` 就进入第 4 步。
`steps/StepDeliver.tsx` 明确称真机核验不阻断“本轮交付完成”。
**修复方向**：第 4 步应显示交付分级状态；原生项目交付只能在 TIA 归档真实存在且校验通过后标完成。源码包允许下载，但必须清晰标为“离线源码包”。

### G-02 · 创建工程的 C# 结果契约未被 Python 正确消费（P0）

`industrial/tia_openness_cli/src/TiaOpenness.Server/Program.cs` 返回：
`{"ok":true,"create":{"ok":true,"projectPath":"<real .ap19>"}}`；
`gateway/app/services/plc/tia_delivery.py::_run_openness_import_compile` 原本读取顶层 `path/project` 并猜测 `.ap19`。
**修复方向**：从 `create.projectPath` 提取真实值，缺失则 fail-closed，避免错误路径上的二次写入。独立分支已给出小修复及离线测试（需要 CI 与 Windows 复核）。

### G-03 · 实机成功后依然只打出 SCL/XML ZIP（P0）

`tia_delivery.py::_assemble_tia_zip` 只装配 SCL、XML 和 `tia_delivery.json`，未包含 TIA 创建的原生项目/归档；
`/download-package` 返回源文件包。
**修复方向**：新建 `NativeTiaArtifact`；调用 Openness `archive-project` 生成 `.zap19`；按 project_id + spec_hash + job_id 保存真实 `zap_path`；下载前校验文件存在、hash、编译账本；独立提供原生归档下载 API。
历史 `/canvas/download-package` 存在枚举硬编码目录或临时文件夹取“第一个 zap19”的做法；不得复用于最终交付。

### G-04 · 硬件真实工程“占位”的语义不清（P0）

`frontend/src/shell/NewProjectWizard.tsx` 首先只保存 project_id/launch context，不能代表已调用真实 `Projects.Create`。
`tia_delivery.py` 可真正创建项目并使用 `Devices.CreateWithItem` 创建 CPU，但读取单个环境变量 `PLC_GREENFIELD_TIA_DEVICE_TYPE`，并且需要走完设计流程才触发。
**修复方向**：新建工程时提供清晰的“创建真实 TIA 框架”动作；以当前装机 CPU 号型/受支持模板作为最小编译基底；I/O/通讯网络等仍保留未绑定状态，不伪造物理地址。创建空 TIA 工程与可编译 PLC 工程显示不同状态。

### G-05 · 当前 Canvas 不等于可编辑时序图（P0）

`StepLink.tsx` 主要是 ReactFlow 设备节点及连线增删。
`greenfield_views.py` 的 `sequenceDiagram` 是从 IR 生成的 Mermaid **只读投影**；不能反向任意编辑 Mermaid 后自动保真回写。
**修复方向**：新增 `SequenceIR`（步骤、转移条件、并行/汇合、超时、报警、复位、模式）为统一语义源。
界面拆为“设备拓扑”和“工艺步序编辑器”；事件时间轴/波形时序作为验证视图（可编辑的时间参数须 patch 回 SequenceIR）。需区分**逻辑时序**与**真实时间仿真结果**；画图不代表控制程序已仿真或已验证。

### G-06 · 元器件驱动不是独立、一等公民（P1）

现有 `AfCm` + `LBC_*` 类型覆盖常见执行器，`af_generator.py` 已支持自动生成 CM 驱动片段。
但产品应明确区分 `ComponentDefinition`（设备类型）、`DriverSpec`（PLCopen 命令/状态、故障、手动、超时、限位、复位）、`DriverInstance`（该项目中设备及接口绑定）与 `SequenceIR`（工艺何时发什么指令）。
默认通道 `greenfield_delivery.py` 使用 `self_contained=True`，属于简化自举实现，**不等同官方 LBC/LAF 库实现**。正式库模式必须标明 AF 库版本、许可、可用类型和项目模板依赖，不能静默混用。

### G-07 · 旧工程与新工程形成两套 UX/状态源（P0）

旧工程使用 `/canvas/import[/upload]`、`CanvasState`、存量回写路径；新工程用 `/canvas/greenfield`、`GreenfieldIR`。
虽然旧工程已有 AF role overlay 和变更审计，但尚缺稳定的 `source block ↔ IR node ↔ generated block` 跨路径身份映射与共享工作区模型。
**修复方向**：引入 `ProjectWorkspace`，两种来源都映射到统一的规范化可编辑 ProjectIR，同时保留原始工程/块文件的不可变快照。不能强迫整个旧工程重生成 AF 后才允许编辑一个旧块。

### G-08 · 会话与工件标识需升级（P1）

`greenfield_session.py` 只在内存存未冻结草稿；后端重启可影响体验，旧工程事务还需严格目标工程身份。
**修复方向**：区分 `project_id`、`workspace_id`、`session_id`、`baseline_sha256`、`spec_hash`、`change_id`、`job_id`；所有写回与归档由后端使用这些标识验证基线，并以异步 job/进度审计，而非相信浏览器存储状态。

## 3. 建议目标模型

```text
ProjectWorkspace
  identity: project_id / base_project_path / baseline_hash / source_kind
  tia: version / cpu_template / archive / capabilities / connection
  references: immutable TIA Snapshot + parsed Block Index
  design:
    AFProject: Units -> EMs -> CM instances
    ComponentCatalog -> DriverSpec -> DriverInstance
    ProcessSpec -> SequenceIR -> Interlocks -> Alarms
    AddressBindings: symbolic|unbound|confirmed TIA tags
  edits: ChangeSet[] (add/update/delete/rename; references; before/after)
  freeze: FrozenSpec(spec_hash, baseline_hash, reviewer)
  delivery: NativeTiaArtifact(project_path, zap_path, sha256, compile_result)
```

**强约束**：模型只有一个语义真值。聊天、设备画布、步序编辑器都产生候选 Patch；由同一个 validator 先在副本上验证，再提交到 ProjectIR。Mermaid、SCL、XML、图形布局均为派生产物。旧项目不可解析块必须保留原字节和只读元信息。

## 4. Agent 拆分：职责分离，不靠一个大 Prompt

| Agent | 输入 | 产出 | 限制 |
|---|---|---|---|
| Project Agent | 新建/导入项目、V19 约束 | ProjectWorkspace、TIA skeleton | 不生成未经批准的物理 IO 配置 |
| Component Agent | “一只双作用气缸，两只磁性开关” | DriverSpec + CM + IO symbolic contract | LBC 优先复用，参数缺失要提示 |
| Process Agent | “夹紧到位后启动输送” | SequenceIR + 互锁 + 时序投影 | 不直接写 TIA |
| Review Agent | 人工图形修改、规则、项目上下文 | Candidate Patch + 影响分析 + 冲突问题 | 不能替代人审 |
| AF Compiler | FrozenSpec | 标准结构、SCL、XML、清单 | 强制 AF 版本矩阵、静态检查 |
| TIA Operator | Verified ChangeSet / PLC project ref | TIA 修改、编译、save、archive、证据 | Windows 受控服务、离线不下载 PLC |

技术实现先是一个有明确 Tool/Port 的编排器，不需要先引入六个独立 LLM。确定性解析、命名、diff、写入和编译都应靠代码，LLM 主要负责需求提取与候选 Patch。

## 5. 新工程闭环（必须保留人工审核）

```text
[选择项目名 + TIA V19 / CPU 基底模板]
  → Openness create-project (或从受控模板克隆)
  → verify real .ap19 + project_id / baseline hash
  → [真实 TIA 骨架已创建；未绑定硬件 IO]
  → NL 元件 → DriverSpec → AF CM
  → NL 工艺 → SequenceIR → 可编辑 Canvas
  → Validation → 工程师确认 → FrozenSpec
  → 生成依赖有序的 SCL/XML/调用块/标签表
  → Openness import / generate-from-source → compile
  → 失败: 定位 source_id 与 SCL 行号，回到 Review，不归档成功态
  → 成功: save → archive-project .zap19
  → hash+存在性+工程身份校验 → native_archive_ready → 下载
```

针对尚无 CPU 的用户可选择只创建空 TIA 项目：这时允许编辑/保存设计草稿，但不能以“PLC 编译通过”展示；必须在后续选择 CPU 或导入 PLC 模板后执行真正编译。

## 6. 旧工程闭环（最小修改优先）

```text
[导入 .ap19/.zap19]
  → 原件保留 + 新建工作副本 + baseline_sha256
  → Openness export full / list blocks / parse / AF-role overlay
  → 原块引用 ID、编号、DB 偏移、IO、F-block 标识锁定
  → NL 或 Canvas → Targeted ChangeSet
  → before/after 图、源码 diff、接口/交叉引用影响、删除依赖检查
  → 用户逐条确认 + baseline 未漂移
  → apply to copied project via single TIA session
  → compile + fidelity/unchanged block checks
  → 成功: save / archive / evidence；失败: 不替换原件
```

对旧项目“添加、修改、删除”分别验收。删除前必须完成调用关系与实例 DB 引用检查；涉及安全 F 程序、受保护块、无法证明行为等价的 LAD/GRAPH 网络拒绝自动改写并要求人工处理。默认仅改动明确选择的可写块；把全旧项目硬转换成 AF 结构不作为写回前置条件。

## 7. 重构模块边界（在现有目录上演进）

```text
gateway/app/
  routers/projects.py            # create/import/open/archived projects
  routers/design.py              # chat, device/sequence patch, validation, freeze
  routers/delivery.py            # native-tia job, progress, exact archive download
  services/plc/project_workspace.py  # ID + baselines + persistence
  services/plc/delivery_jobs.py      # transaction, compile diagnostics, exact artifacts

plc_engine/
  project_ir.py                  # 统一工程模型，复用 GF IR schema
  component/driver_spec.py       # 元件定义、标准 driver ports
  component/catalog.py          # AF/LBC driver 模板与版本能力矩阵
  process/sequence_ir.py         # 并行/分支/超时/转移条件
  process/sequence_validator.py  # 静态联锁/数据流/单写者校验
  diff/change_set.py             # add/update/delete + source identity
  af/*                           # 复用原有生成器和映射器

industrial/tia_openness_cli/     # 继续唯一 TIA 写入口，补 exact artifact/job
frontend/src/
  shell/ProjectWorkspace.tsx     # 统一新建/导入入口
  canvas/DeviceGraph.tsx         # 硬件逻辑/CM 节点
  canvas/SequenceEditor.tsx      # 编辑步序、条件、分支、并行
  canvas/TimingPreview.tsx       # 控制时序预览/仿真结果（注明来源）
  shell/DeliveryReview.tsx       # 真机状态、diff、编译、zap19
```

禁止简单复制 `greenfield_service.py`、`plc_gateway/` 再建第三套状态源；优先抽取 ports/contracts 并为两个工作流提供兼容适配器。拆分成小步 PR，保留旧 API 给现有消费者，逐步迁移并设置 deprecation gate。

## 8. 实施优先级与验收

| 阶段 | 要做的事 | 验收标准 |
|---|---|---|
| P0-1 工程真实身份 | 修复 `create.projectPath`；创建最小 .ap19 骨架；project/workspace 绑定 | 原生工程路径由 C# 原始返回；重新打开同一 .ap19；不使用猜测路径 |
| P0-2 真实交付 | 当前 AF 源包导入、编译；Openness archive 得真实 `.zap19`；下载严格绑定 job_id | 用户能从下载 `.zap19` 在同版本 TIA 复原打开，编译日志关联该工程 |
| P0-3 驱动 + 步序 | DriverSpec 与 SequenceIR，两套可编辑 Canvas，同 IR patch | NL 与手动编辑结果等价；指定元件拥有确定命令/状态/异常；步序更改后源码确实变化 |
| P0-4 旧项目最小回写 | import→target diff→确认→编辑工作副本→compile→archive | 三组实测：新增 FB/DB、修改可写 FB、删除无引用块；未触及块 hash 不变 |
| P1-1 AF 正式库模式 | 校验 AF V1.2 Basic/LBC 和 self-contained 模式边界 | 两模式显式标识；库缺失 fail-closed；不得把简化逻辑称为官方认证 |
| P1-2 工业级质量 | 故障注入、超时重试、跨进程恢复、并发工程锁、差异回滚 | 误写 0、错工程交付 0、失败不产生成功归档 |
| P1-3 可视化验证 | sequence step simulation / traces / coverage | 图形展示的预期时序与测试结果分开展示，不能以“渲染成功”冒充功能验证 |

### 建议第一个端到端验收用例

用“**双作用气缸 + 前后到位开关 + 启动按钮**”作为最小用例：

1. TIA V19 创建真实项目，CPU 选择受支持的实际模板；所有 IO 以符号占位，无虚构地址。
2. NL 生成 `cylClamp` 驱动：伸出/缩回请求、到位确认、互斥、超时、故障复位、手动/自动接口。
3. NL 生成工艺：启动 → 伸出 → 伸出确认 → 保持 → 缩回 → 缩回确认 → 完成；超时转故障，外部安全许可丢失禁止动作。
4. Canvas 手动修改“保持 1s → 2s”，并修改一个超时条件；变更传回同一 IR。
5. 人工审核后创建/导入/编译/保存/归档；返回明确 `archive_path` 和 `sha256`，在 TIA V19 重新打开。
6. 再导入该工程，NL 要求“缩回确认后新增计数器”，比较差异并仅修改相应块；确认后再次编译归档，原先其他块保持不变。
7. 错误路径、CPU 未选、编译失败、F-block 触碰、原工程 hash 漂移、并发编辑均必须拒绝，不得显示原生交付完成。

## 9. 当前审查边界

本次已经**阅读**代码与仓库内此前的 V19 测试报告，但未在本环境运行 TIA Portal、前端交互 E2E 或全量 pytest/vitest。仓库内的 `evidence/uc04_*.json`、`evidence/uc16_*.json` 支持此前的部分真机验证，不自动证明最新前端能产生端到端完整原生项目。

本 RFC 及 `create.projectPath` 修复应先作为隔离 PR 审核。后续大规模重构必须在独立分支分阶段进行，每一步以“真实工程重开、编译与原件保真”为验收基准。
