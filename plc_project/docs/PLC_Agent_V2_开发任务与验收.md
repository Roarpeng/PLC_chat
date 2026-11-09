# PLC Agent V2.0 — 可直接实施的开发任务包

> 日期：2026-11-09；代码基线：`Roarpeng/PLC_chat` 的 `dev/greenfield-wp` 分支。
>
> 先阅读同目录 HTML《PLC_Agent_V2_架构设计与开发蓝图.html》；本清单用于分配给 Cursor/Codex/Claude Code 等开发 Agent。任务在真实仓库执行，本文本身不是已实施代码。

## 一、不可推翻的工程原则

1. **目标产品**：Siemens PLC 工程智能体，新建与存量工程共用编辑内核。新建工程必须通过真实 TIA Portal V19 创建，硬件/组态仅占位，允许实际 CPU skeleton 与后续手工 IO 配置。
2. **AF 档位**：延续用户在 `docs/greenfield/11-p0d-decision.md` 已确认的 AF Basic **文件夹版**。不自动切换 TIA Software Unit。工程锁定 AF profile、库版本、模板 hash。
3. **核心数据**：`EngineeringIR` 唯一可写语义真值；聊天、设备图、时序图以结构化 Patch 修改；Mermaid、Trace、SCL、XML 为派生物。
4. **职责**：DriverSpec 描述元件行为（命令/反馈/超时/故障）；SequenceIR 描述工艺（步骤/条件/动作/分支/超时）。二者分离。
5. **写回**：LLM 不直接执行任意 SCL 或 TIA 命令；必须候选 Patch → 确定性校验 → 人工审核 → ChangeSet → 工作副本 → TIA Compile → Save → Archive。
6. **交付**：源码 ZIP 与 TIA `.zap19` 不等价；只有源项目精确绑定的真实 `.zap19` 经校验后才允许 `NATIVE_ARCHIVED` 状态。
7. **安全**：禁止未批准的在线下载/运行/停止 PLC；不得自动修改 Safety/F 程序，普通软件联锁不可冒充安全回路。
8. **迁移**：不得复制 `plc_gateway/` 建另一套后端，不破坏现有 `gateway/app`、`plc_engine/af`、`industrial/tia_openness_cli` 的稳定能力；重构分小 PR，每个必须含负例测试。

## 二、可分配任务（每个 task 是一份独立 PR）

### TASK-00A：基线审计和契约冻结

- 前置：无。
- 文件范围：`docs/architecture/`、`tests/contracts/`、CI；此任务先不改变业务逻辑。
- 动作：列出并实际运行现有后端 pytest、前端 vitest/build、C# dotnet test；记录提交 SHA、版本、失败列表；读取 AGENTS.md 与 `docs/greenfield/11-p0d-decision.md`；生成 v2 migration contract。
- 交付：`baseline-report.md` + `contracts.md` + Git commit。
- 验收：所有旧 API 的请求/响应字段有 golden test；失败真实留痕，不把 mock 算真机。

### TASK-00B：EngineeringIR v2 与 SourceBinding 兼容层

- 前置：TASK-00A。
- 文件范围：`plc_engine/engineering_ir/`、`tests/unit/test_engineering_ir_*.py`，**避免直接改写旧 `greenfield_ir.py` 的公共行为**。
- 动作：定义 `ProjectWorkspace`, `AFProfile`, `ComponentDefinition`, `DriverSpec`, `SequenceIR`, `SourceBinding`, `ChangeSet`, `ArtifactManifest`；实现 v1→v2 adapter；语义数据和 UI Layout 独立；版本、`base_revision`、`ir_hash`、稳定 ID。
- 验收：序列化/反序列化 roundtrip，100 次随机 Patch 原子性，版本冲突 409，非法字段 422，旧 fixture 零字段丢失。

### TASK-01A：Openness 创建工程响应、真实路径、模板能力

- 前置：TASK-00A；可与 TASK-00B 并行但只允许改自己的文件。
- 文件范围：`gateway/app/services/plc/tia_delivery.py`、`industrial/tia_openness_cli/`、路径契约测试。
- 动作：核对 C# `create-project` 返回 `{ok,create:{projectPath}}`；Python 正确读取 `create.projectPath`；真实工程身份、CPU device type 前置检查；失败不猜路径。
- 验收：V19 真实 create / reopen；缺失 CPU 或路径时显式失败。之前 Draft PR #1 已提供路径修复起点，需要审查是否合并及回归后再施工。

### TASK-01B：原生 TIA 归档与下载

- 前置：TASK-01A。
- 文件范围：`gateway/app/services/plc/native_delivery.py`、`delivery_jobs.py`、`artifact_store.py`、新 API router、前端交付状态。
- 动作：严格写入事务：create/open→import/generate→compile→save→archive→hash→artifact_id；结构化错误诊断；展示源码 ZIP / Native `.zap19` 两类产物。
- 验收：真实 `.zap19` 可 Retrieve 和 reopen；当前 job 不能下载其他 job 的旧归档；编译失败无 NATIVE_ARCHIVED；重复请求幂等。

### TASK-02A：DriverCatalog 和四类标准元器件

- 前置：TASK-00B。
- 文件范围：`plc_engine/components/`、相关独立测试。
- 动作：首批双作用气缸/单作用执行器/DI/DO/电机启停，定义 typed ports、状态、超时、反馈、故障复位、手自动和模板映射。正式 LBC 与 self-contained 编译模式显式区分。
- 验收：同一驱动模板可用于两套不同工艺；未绑定物理 IO 不生成虚构地址；反向输出不会同时置位；所有必需端口校验生效。

### TASK-03A：SequenceIR + GuardAST + Graph Validation

- 前置：TASK-00B，依赖 TASK-02A 的命令端口契约。
- 文件范围：`plc_engine/process/`，不得直接修改 UI。
- 动作：实现 SFC-like steps/actions/transitions，Guard AST（BOOL/TIME/INT、AND/OR/NOT/比较），BFS 可达性、Tarjan SCC、分支冲突/优先级、超时及 Fault 路径、命令资源冲突。第一版不支持的并行语义拒绝编译。
- 验收：正常循环、伸出超时、缩回超时、失去安全许可、故障复位五个用例；不可达、冲突、非法类型等负例。

### TASK-03B：离线扫描周期 Trace、AF SCL Lowering 和 SourceMap

- 前置：TASK-03A、TASK-02A。
- 文件范围：`plc_engine/process/`、`plc_engine/af` 的适配层。
- 动作：定义扫描周期顺序，产出确定性 Trace；将 IR lowering 为 AF block units；构建 UDT/FB/DB/OB 依赖图与导入顺序；生成 SourceMap；错误能映射到具体 IR 节点。不要仅从 DB 命名反推 FB 名。
- 验收：同版本输入二次生成语义 hash 一致；Trace 与 SCL 语义一致；V19 实际编译 0 errors；失败定位到源节点。

### TASK-04A：统一工程工作台 Shell

- 前置：TASK-00B 的 OpenAPI/schema；可在 mock contract 下提前实现 UI。
- 文件范围：`frontend/src/workbench/`、工作台路由和状态；保留旧四步入口作为兼容路线。
- 动作：项目树、设备拓扑、步序编辑、时间 Trace、源码、Diff、Copilot、底部 diagnostics；前端只持视图与选择状态，真实数据由服务端 revision 主导。
- 验收：刷新后工作区不丢失；跨页面操作同一 project_id；版本冲突恢复；无 mock 执行结果被标为真机成功。

### TASK-04B：双向 SequenceCanvas 编辑

- 前置：TASK-03A、TASK-04A。
- 文件范围：`frontend/src/workbench/canvas/SequenceEditor.tsx` 等。
- 动作：Step/Transition/Action 自定义节点，命名连接端口，双击编辑动作、转移条件、超时、异常、模式；每次修改发 `SequencePatch(base_revision)`；服务端成功后刷新派生 SCL 和 Trace。右侧动态 Inspector 显示源数据，不私建图内真值。
- 验收：手工把 Hold 1s 改为 2s，IR/Trace/SCL 三方同步；无效 Guard/缺少异常分支在节点显示错误；Undo/Redo 不绕开后端 revision。

### TASK-05A：Brownfield SourceBinding 和最小 ChangeSet

- 前置：TASK-00B、TASK-03B；旧工程解析代码需维持可用。
- 文件范围：`plc_engine/changeplan/`、`gateway/app/services/plc/canvas_import.py` 的 adapter。
- 动作：导入 `.ap19/.zap19`，原件不动；原块 GUID 或稳定 ID、类型、编号、原文 hash、被引用者、可写能力与 IR entities 建 SourceBinding；针对新增/修改/删除构造最小 DiffPlan，做删除依赖、单写者、签名和版本检查。
- 验收：真实项目中仅批准目标块变化；不能解析/受保护/F-block 仍保留且不可随意写；删除被引用块被拒绝。

### TASK-05B：Brownfield 在工作副本上增量编译、归档

- 前置：TASK-05A + TASK-01B。
- 文件范围：`native_delivery.py`、增量事务编排与测试；真实 TIA Worker 独占。
- 动作：基线复查 → 导出工作副本 → 写入确定性变更 → 真实编译 → 差异和保真复核 → 保存/归档；失败保留证据并拒绝发布。
- 验收：ADD / MODIFY / DELETE 各一真实副本用例通过；受影响块和原件 hash 留痕；重复指令不会重复导入。

### TASK-06A：工业质量与失败恢复

- 前置：TASK-01B、TASK-05B。
- 文件范围：作业层、文件存储、日志、安全规则、CI。
- 动作：作业幂等、项目锁、worker crash recovery、schema migration、路径白名单、权限、上下文最小披露、坏 XML/ZIP 拒绝、回滚策略。
- 验收：至少 10 类故障注入覆盖；100% 失败任务不发布 `NATIVE_ARCHIVED`；导出物与请求工程一致。

## 三、统一 API 草案

```text
POST   /api/v2/projects
GET    /api/v2/projects/{id}
GET    /api/v2/projects/{id}/ir
GET    /api/v2/projects/{id}/blocks
POST   /api/v2/projects/{id}/intent
POST   /api/v2/projects/{id}/patches
POST   /api/v2/projects/{id}/validate
POST   /api/v2/projects/{id}/simulate
POST   /api/v2/projects/{id}/preview
POST   /api/v2/projects/{id}/changesets
POST   /api/v2/changesets/{id}/approve
POST   /api/v2/projects/{id}/deliveries
GET    /api/v2/delivery-jobs/{id}
GET    /api/v2/delivery-jobs/{id}/events
GET    /api/v2/artifacts/{id}/download
```

协议要求：所有变更请求携带 `project_id`、`base_revision`、`request_id`；正式交付携带 `approved_changeset_id`、`expected_baseline_hash`、`idempotency_key`；下载使用 `artifact_id` 的精确授权关联。

## 四、最小上线验收 — 两个案例

**AC-01 Greenfield：**

1. `Projects.Create` 真实创建 `.ap19`，CPU 型号来自装机支持列表或已批准模板。
2. NL “一只双作用气缸、伸出/缩回限位、3 秒超时”生成完整 `DriverSpec`，地址仍 `unbound`。
3. NL “启动→伸出→到位→保持→缩回→完成，超时故障”生成 `SequenceIR`。
4. 在 Canvas 中将保持 1s 改 2s，看到 IR Patch / Trace / SCL diff。
5. 用户批准，TIA V19 真实导入、编译 `error_count=0`、Save、Archive、Retrieve/reopen 成功。
6. 用户可以下载关联 job 的 `.zap19` 和完整 evidence。

**AC-02 Brownfield：**

1. 将 AC-01 工程归档重新导入，保留原始工程 hash 和完整块索引。
2. NL “缩回到位后，增加一次计数”，仅修改关联序列 FB、必要的变量/DB。
3. Before/After 差异展示具体目标块和引用影响，人工批准。
4. 仅工作副本应用变更，真实编译/归档成功；原件不动，其他块未出现未批准变化。
5. 删除被引用块、写 F-block、基线漂移、TIAPortal 不可用等负例全部拒绝。

## 五、Agent 交付模板（每次提交必须填写）

```text
Task ID:
Base commit SHA:
Changed files:
New/changed API & schema:
Why not a parallel implementation:
Tests executed (exact commands + pass/fail counts):
Real TIA V19 tested? yes/no (raw evidence path):
Existing behavior compatibility:
Unresolved risks:
PR URL:
Next task unblocker:
```

## 六、最先执行的主 Agent 指令

> 先阅读 `AGENTS.md`、`plc_project/README.md`、`docs/greenfield/11-p0d-decision.md` 和本开发任务包。仅处理 TASK-00A 与 TASK-00B，不要开始全仓重构。审查当前 `GreenfieldIR/CanvasState/AfProject` 字段和调用位置，设计 EngineeringIR v2 schema、兼容 adapter、原子 patch 契约和负例测试。在独立分支提交一个最小 PR，报告真实测试与未验证事项。保留 AF Basic 文件夹版、已有 PCEC 与 Openness 能力；不碰原始 TIA 项目或 Safety/F 程序。
