# V3.0 蓝图与仓库实现对照（Blueprint vs Repo）

对照对象：`docs/plc_chat_v3_0.html`（V3.0 研发级架构蓝图，Tab 2 的七步数据流契约为主干）

对照基准：`plc_project/` 下 `plc_engine/af/`、`agents/plc/tia/`、`plc_engine/scl_precheck.py` 的实际代码，以及 `release_packages/HR001_AF_V1_2_Package/refactored_scl_sources/` 的真实重构产物（该目录位于工作区根，与 `plc_project/` 同级）。

## 一、结论

V3.0 是目标态蓝图，不是现状描述——其中约 60% 的能力已在 `plc_engine/af`（六槽位 AF 模型与生成器）与 `agents/plc/tia`（FlgNet 折叠、解耦、回写编排）中落地，剩余 40% 集中在「单文件批量打包 + 拓扑排序 + 编译自愈」这条极速回写链路上，属于尚未实现的工程缺口。

## 二、七步对照表

| 步骤 | 文档主张 | 仓库现状 | 结论 |
| --- | --- | --- | --- |
| Step 1 `.zap` 解压与分类分流导出 | `IngestionService` 解压归档；SCL/STL/DB/UDT 走 `GenerateSource()` 导出明文，LAD/FBD 走 `Block.Export()` 导出 SimaticML XML，黑盒块单独归档 | `agents/plc/tia/importer.py` 已实现归档识别与工程落盘：`is_tia_archive_suffix()`、`classify_input()`、`stage_tia_project_tree()`、`_infer_tia_version()`、`ImportResult`；导出侧由 Openness worker 与 `openness_cli.py` 承担，产出 bundle 供后续解析 | 已实现 |
| Step 2 anyprogram2SCL 语法树转译 | 解析 `FlgNet` 的 `Parts` / `Wires`，按 UId 查找表 → 元件节点 → 能流拓扑 → 布尔代数合成四步，确定性输出 SCL 与读写依赖 | `agents/plc/tia/flgnet_fold.py`（44KB）实现完整折叠链：`_NetworkFolder` 逐网络遍历，`expr_to_scl()` 输出表达式文本，`fold_network()` / `fold_block()` / `fold_project()` 分层入口，`attach_folded()` 把折叠结果挂回 IR；AST 底座在 `simaticml.py`（56KB）、`scl.py`（64KB）、`ir.py`、`understanding.py` | 已实现 |
| Step 3 符号解耦与读写交叉矩阵 | `DependencyAnalyzer` 构建全局读写矩阵，识别执行器配对、步序寄存器、安全互锁、HMI 通信 DB | `agents/plc/tia/decouple.py` 提供解耦主体：`propose_decouple()` 输出解耦建议，`_pick_extract_network()` 选定待抽取网络，`nested_fb_coupling_notes()` 记录嵌套 FB 耦合风险，`_bidirectional_pairs()` / `_shared_instance_dbs()` 识别双向耦合与共享背景 DB；依赖图查询在 `graph_query.py`、`kg.py` | 已实现 |
| Step 4 博世 OpCon AF 六槽位重构 | `BoschAfRefactorEngine` 把解耦矩阵转成 `BoschStationAfModel`，气缸收敛到 Slot 5/6、互锁收敛到 Slot 4、步序收敛到 Slot 3 | `plc_engine/af/` 全量落地：`af_model.py` 定义 `AfProject` / `AfUnit` / `AfEm` / `AfEm0` / `AfCm` / `AfSequenceStep` / `AfSequence`；`af_generator.py` 的 `generate_af_project_blocks()` / `generate_af_unit_blocks()` / `generate_af_em_blocks()` 出块，EM0 由 `_generate_em0_blocks()` 单独处理；`af_mapper.py` 的 `LegacyToAfMapper` 完成老程序到 AF 候选映射；`af_numbering.py` 分配并校验 OB 号；另有 `planner.py`、`mermaid_parser.py`、`refactor.py`、`baseline.py` | 已实现 |
| Step 5 上下文切片与 LLM 受控槽位编辑 | `LlmSlotEditor` 只切片目标工站 Slot 3/4 与元件签名，LLM 仅输出 JSON Patch | 槽位模型与生成器已具备（`af_model.py` 的 `AfEm` / `AfSequenceStep`、`af_generator.py`），槽位级补丁协议见 `docs/23-af-builtin-contract.md`、`docs/25-gemini-refactor-contract.md`；**本轮补齐** `plc_engine/slot_context_slicer.py`：`slice_station_context()`（默认 1500 tokens、三级降级）、`assert_context_safe()`（拦截 Slot 2 与物理 Q 泄露）、`validate_slot_patch()`；契约 DTO 在 `plc_engine/contracts.py` | 已实现 |
| Step 6 静态语法预检与单文件打包 | 渲染 SCL 后跑 5 条静态 Linter，SHA-256 过滤脏块，按 Kahn 拓扑排序合并为单个带 BOM 的 `.scl` | 既有预检 `plc_engine/scl_precheck.py`（END 配对 / 声明注释）；**本轮补齐** `writeback_linter.py`（R1~R5）、`mega_source.py`（真 Kahn + `CycleError` + 脏块差分 + UTF-8 BOM 单文件打包）、`writeback_pipeline.py`（fail-closed 编排）、`contract_adapters.py`（契约互转） | 已实现 |
| Step 7 极速回写与编译闭环 | 单次 `CreateFromFile` + 单次 `GenerateBlocksFromSource`，`ExclusiveAccess` 冻结 UI，`ICompilable.Compile()` 后自动回传自愈 | 既有编排 `agents/plc/tia/writeback.py`（备份 / dry-run / manifest / restore hint）与 C# 底座 `TiaConnection.cs` / `BlockService.cs`；**本轮补齐** `agents/plc/tia/writeback_batch.py`（单文件批次，dry-run 默认 True）、`plc_engine/writeback_heal.py`（3 次自愈 + 熔断）、C# `FastWriteback.cs`（`ExclusiveAccess` + 分级增量编译 + 结构化错误树）、`OpennessGuardrails.cs` 与白名单脚本 | 已实现（运行时效果已真机验收，见 §五） |

统计：七步在**代码与契约层面全部已实现**（Step 1–4 原本已有，Step 5–7 由上一轮与本轮补齐）。缺口已从"缺模块"收敛为"缺真机运行时验收"：`ExclusiveAccess` 冻结 UI、分级增量编译耗时、端到端回写链路的实际效果必须在真实博途 / TIA Portal 上验证，详见 `docs/09-v3-completion-report.md` 第 9 节。

## 三、真实缺口清单

| 缺口 | 影响 | 建议落点文件 |
| --- | --- | --- |
| Mega-Source 单文件合并（全仓库 grep `Mega` 零命中） | 仍按块逐个导入，每个块各触发一次 IPC 事务启停与 SCL 解析器初始化，回写耗时不随块数摊薄 | 新增 `agents/plc/tia/bundle.py`，对外暴露 `bundle_blocks(artifacts) -> Path`，由 `writeback.py::prepare_writeback()` 调用后交给 worker |
| 拓扑排序（grep `topolog` 零命中） | 无法保证 `UDT → 子 FB → 上层 FB → InstanceDB` 的输出顺序，`GenerateBlocksFromSource` 会报「找不到数据类型或被调用块」 | 新增 `plc_engine/scl_graph.py`，提供 `order_blocks(blocks) -> list`；纯函数，可单测 |
| 反向依赖闭包（grep `closure` 零命中） | 改了 UDT 或子 FB 时，无法自动把受影响的调用方重新纳入回写集合，增量回写结果可能不自洽 | 同上 `plc_engine/scl_graph.py`，提供 `reverse_closure(seeds, edges) -> set`；与排序共用一张边表 |
| 编译错误自愈重试闭环（grep `self.heal\|selfheal` 零命中） | 编译报错后无结构化回传与自动重试，必须人工介入，回写链路无法无人值守 | `agents/plc/tia/writeback.py` 增加 `heal_loop()`，消费 worker 返回的 `errors` 与槽位上下文，重入 Step 5 |
| ExclusiveAccess（零命中，纯 C# API） | 有界面模式下 UI 线程仍逐节点重绘，20 个块的回写被 WPF 布局刷新拖住 | Openness worker 的 C# 侧回写入口（见 `docs/07-openness-worker.md`、`docs/0010-windows-openness-worker.md`），在批量生成段外包 `using (portal.ExclusiveAccess(...))` |
| 回写前 5 条静态门禁 | `scl_precheck.py` 只覆盖 END 配对与声明注释两项；作用域定界符、单线圈唯一性、CASE 内禁状态指令、类型隐式转换、BOM 校验五项缺位，低级报错会穿透到编译器，白耗 2~4 秒 IPC | `plc_engine/scl_precheck.py` 扩 `precheck_block()`：新增 `check_scope_delimiters()`、`check_single_coil()`、`check_stateful_in_case()`、`check_implicit_cast()`、`check_utf8_bom()` |

### 3.1 已补齐（2026-11-02）

上表前四条缺口已在上一轮全部落地，并额外补了一层编排；本轮并行补齐其余 6 组能力（含 C# 侧 `ExclusiveAccess` 与 Step 5 上下文切片器）：

| 原缺口 | 实际落点 | 关键 API |
| --- | --- | --- |
| 共享 DTO | `plc_engine/writeback_contract.py` | `BlockArtifact`、`TYPE_ORDER`、`sha256_text()`、`scl_block_name()` |
| Mega-Source 合并 + 拓扑排序 + 脏块过滤 | `plc_engine/mega_source.py` | `topological_sort()`（真 Kahn，环抛 `CycleError`）、`filter_dirty()`、`bundle()`、`write_bundle()`（UTF-8 BOM） |
| 反向依赖闭包 + 接口变更传播 | `plc_engine/dependency_closure.py` | `dependents_closure()`、`interface_closure()`、`mark_interface_change()`、`build_reverse_index()` |
| 回写前 5 条静态门禁 | `plc_engine/writeback_linter.py` | `lint_block()`、`lint_bundle()`、`assert_clean()`，规则 R1~R5 |
| 编排（上述四者的组合） | `plc_engine/writeback_pipeline.py` | `build_plan()`、`materialize()`、`WritebackBlocked`（fail-closed） |
| 七步数据契约全量形式化 | `plc_engine/contracts.py` | `RawProjectBundle` / `NormalizedBlockAst` / `DependencyGraphMatrix` / `BoschStationAfModel` / `PatchedSlotDelta` / `AfBatchSource` / `WritebackResult` / `SelfHealRequest` + `STEP_CONTRACTS` 索引、`step_contract()`、`contract_summary()` |
| 编译错误自愈闭环 | `plc_engine/writeback_heal.py` | 3 次自愈重试闭环、熔断、无进展检测；消费 `WritebackResult` 的结构化错误 → `SelfHealRequest` → 重入 Step 5 |
| 单文件批次回写适配器 | `agents/plc/tia/writeback_batch.py` | 单文件批次回写入口，把打包产物交给 Openness worker；`dry-run` 默认 `True` |
| 契约 ↔ 既有产物适配器 | `plc_engine/contract_adapters.py` | 七步契约 DTO 与 `BlockArtifact` / `BundleResult` / `WritebackPlan` 等既有模块产物互转 |
| Step 5 上下文切片 + Token 预算 + Patch 校验 | `plc_engine/slot_context_slicer.py` | `slice_station_context()`（默认 1500 tokens、三级降级、`ContextBudgetExceeded`）、`assert_context_safe()`（拦截 Slot 2 / 物理 Q 泄露）、`validate_slot_patch()` |
| C# 侧运行时能力（三件套） | `industrial/tia_openness_cli/src/TiaOpenness.Server/FastWriteback.cs` + `OpennessGuardrails.cs` + `tools/Register-OpennessWhitelist.ps1` | `ExclusiveAccess` 包裹、分级增量编译、结构化错误树、快照钩子、`CleanupExternalSource()` 生成后即焚；白名单注册、LAD/FBD 分流、IDB 刷新、多版本 DLL |

上表后 6 行为**本轮并行交付**：由各代码 lane 与文档 lane 同步落地，按「已交付」归档；各 lane 的测试数以各 lane 测试报告为准。C# 三件套归为一组能力，含 3 个文件。收口验收：全量 957 passed、本轮新增文件 ruff 零告警、C# 编译 0 错误（完整重编时有 16 条既有 nullable 警告，全部位于 `SessionServer.cs` / `ProjectService.cs` / `BlockService.cs`，本轮新增的 `FastWriteback.cs` / `OpennessGuardrails.cs` 零告警）。

设计取舍：门禁走 **fail-closed**——只要 R1~R3 任一报 error，`build_plan()` 就把 `planned_text` 置空、`materialize()` 抛 `WritebackBlocked`，整批拒绝写盘，不做"部分写入"。这与回写属破坏性操作的定位一致。

上述缺口在**代码层面已全部交付**：Step 7 的自愈重试闭环与 C# 侧的 `ExclusiveAccess` 包裹见 §3.1 本轮并行交付部分，不再列为未实现项。本机已具备 TIA Portal V19 环境，`ExclusiveAccess`、分级增量编译与端到端回写耗时均已在 `_sandbox/` 的项目副本上实测，详见 §五与 `docs/09-v3-completion-report.md` 的「真机验收记录」章节。

## 四、文档与实物的结构性差异

### 4.1「1 工站 = 1 个 FB 内 6 段」与真实产物不同构

文档 Tab 4 主张把整站逻辑收敛进**一个** FB 的 6 个槽位段。真实交付产物不是这个形状。

`release_packages/HR001_AF_V1_2_Package/refactored_scl_sources/` 下按 EM 分目录，标准 EM 每个目录 **7 个文件**：

| 文件 | 职责 |
| --- | --- |
| `Main.scl` | EM 主 FB，装配与调用入口 |
| `Startup.scl` | 初始化段 |
| `Sequence.scl` | 步序状态机 |
| `CallEquipment.scl` | 设备调用层 |
| `ControlNodes.scl` | 控制节点结构（启停/模式/复位） |
| `ProDiag.scl` | ProDiag 监控块 |
| `StepToString.scl` | 步号到文本的映射 |

目录划分为 `U1Em0_General`、`U1Em1_AutoStep`、`U1Em2_RobotAutoStep`、`U1Em3_HorDrillAutoStep`、`U1Em4_DownDrillAutoStep`、`U1Em5_DiamondAutostep`、`U1Em6_Kuka_General`、`U1Em7_FC2400VisualCalibration`、`U1Em8_FC2600FTControl`，另有 `U1_HR001` 单元层目录。其中 `U1Em0_General` 是特例，只有 `Main.scl`、`Startup.scl`、`ProDiag.scl` 3 个文件——与 `af_generator.py::_generate_em0_blocks()` 对 EM0 单独处理的实现一致。

`Sequence.scl` 的实现细节也与文档模板不同：用 `DInt` 型 `statStepCurrent` / `statStepNext` 双变量承载步序，调用博世 LAF 库的 `LAF_ControlSclSequence` / `LAF_StatusSclSequence` 管理转移，命令侧走 `controlNodes.sequence.commands`。文档模板里那句「每周期零化请求结构」的 `#statAutoCmd := #statEmptyCmd` 在真实产物中**不存在**。

值得注意：`plc_engine/af/` 的实现反而更接近真实产物——`AfEm` + `AfSequenceStep` + `AfCm` 的模型对应的是「EM 拆分 + 设备元件分离」，而不是「单 FB 六段」。文档 Tab 4 的模板应视为教学示意，不应作为生成器的验收依据。

### 4.2 回写规模被低估

文档按「约 20 个块」估算回写量。按 4.1 的实际结构，1 个 EM 就是 7 个块，一个单元（`U1_HR001`）含 4 个标准 EM 加 1 个 General EM，块数已达 4×7 + 3 = 31 个，尚未计入单元层块、UDT、全局 DB 与 InstanceDB。这意味着：

- 逐块导入的 IPC 开销按 31 起算而非 20，性能表中「IPC 启停 ×20」的基线偏乐观；
- Mega-Source 合并的收益随块数放大，优先级应高于文档给出的排序；
- 脏块过滤的实际命中率取决于「一次对话改动几个 EM」，跨 EM 需求会一次性打脏 7 个块，哈希缓存的分层粒度（按 EM 还是按块）需要提前定。

## 五、真机验收已完成（2026-11-02）

本机确认具备 TIA Portal V19 环境（`status` 返回 `opennessAvailable=true` / `opennessGroupInToken=true`），已在 `PLC_Openness_data/hr001/_sandbox/` 的**项目副本**上完成端到端验收，原始项目逐字节未改动。逐项实测数字见 `docs/09-v3-completion-report.md` 的「真机验收记录」章节。

| 验收项 | 实测结果 | 判定 |
| --- | --- | --- |
| 接真实回写通道 | `--cli status` → 常驻会话 `/open` → `/fast-writeback` 全链路跑通；41 块 / 764KB 带 UTF-8 BOM 单文件批次导入成功，`writtenBlockCount=41` | 已验收 |
| `ExclusiveAccess` 冻结 UI | `exclusiveAccessUsed=true`，反射获取有效租约，批量生成段无异常 | 已验收 |
| 分级增量编译 | `incremental_blocks` 与 `full_software_interface_changed` 两条路径均真实触发；未标记接口变更时复现 928 条 IDB 时间戳不一致错误，标记后同类错误归零 | 已验收 |
| 端到端耗时 | 逐块基线 52.95s → Mega-Source 单文件 28.22s，提速 24.73s（约 1.88×）；`/fast-writeback` 全功能路径 27.52s。**文档「5 秒内 / 89s→3.5s」目标值未达标** | 未达标 |
| 结构化错误树与白名单 | 错误树 1008 → 9 → 3 条（过滤容器节点与 `Compiling finished` 汇总噪声）；白名单脚本实机写入 `Entry (29)` / `Entry (30)` 并回读校验，新 exe 均能打开项目 | 已验收 |

真机抓到并已修复的三处真实缺陷：

1. `Register-OpennessWhitelist.ps1` 与 `OpennessGuardrails.cs` 的白名单注册表格式写错——真实格式是 `...\Whitelist\<app>.exe\Entry (N)` **子键** + `Path` / `DateModified` / `FileHash`（SHA256 字节的 Base64），不是父键下名为 `Entry` 的值。
2. `writeback_batch.py` 未把 `interface_changed` 映射到 C# 请求，导致走增量编译而漏刷新已存在的 Instance DB；新增 `to_fast_writeback_request()` 自动推断并配 10 个单测。
3. `FastWriteback.cs` 的错误树混入无描述容器节点与编译汇总消息，自愈 LLM 会为此生成无效补丁；已过滤，真机 9 条噪声降为 3 条真实错误。

全量单元测试 957 passed、ruff 零告警、C# `TiaOpenness.Server.csproj` 编译 0 错误。剩余事项仅四项：性能指标未达标；单文件批次仍含 3 条 know-how protected 块错误（应按 `list-blocks` 的 `knowHowProtected` 排除）；`compileScopeNote` 要求的 IDB 声明追加需由上层注入项目命名映射；自愈闭环未接真实 LLM。P1 / P2 / P3 按文档原文「剥离出当前核心开发主线」未启动。

文档侧收口：V3.0 文档 Tab 4 的「单 FB 六段」教学模板已加醒目提示块，指向 `plc_engine/af/af_generator.py` 与 `release_packages/`；块数盘点见 §4.2；Tab 1 性能数字经真机实测确认为目标值，其「已知偏差」块已注明不作验收指标。
