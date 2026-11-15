# aiCoPlc · 现场变更与交接闭环 · 实现状态（STATUS）

> 版本：1.0 · 2026-11-15 · 配套设计稿：[aiCoPlc_FieldChange_Handover_PLAN.md](./aiCoPlc_FieldChange_Handover_PLAN.md)
> 本文记录 PLAN（FC-00~FC-18 及全部章节要求）的**实际交付状态、测试证据、真机凭证与诚实边界**。所有数字均经主 Agent 独立复跑验证。

## 1. 总体验证数字（最终回归）

| 维度 | 结果 | 说明 |
|---|---|---|
| 后端 pytest | **373/373 通过**（`plc_project/processos/tests`） | 275 基线 + 向导 27 + 修错 23 + 导入 19 + 编排 29 |
| 前端 vitest | **513/515**（`plc_project/frontend`） | 唯二失败为工作树既有 `plc_project/docs/v2/*.md` 删除导致的 ENOENT（非本功能引入，未处理用户工作树） |
| TypeScript | `tsc --noEmit` 0 错误 | |
| 真机编译 | **V19_real 全链通过** | 见 §4 |
| 服务冒烟 | 重启存活实测 | 杀进程→同库重启（未 reseed）→ 问题单与四张关联图完整恢复、稳定 object_id 不变 |

运行方式：`python tools/devctl.py up processos`（:8010，SQLite 持久化经 `PROCESSOS_DB` 开启）+ `up gateway` / `up web`。

## 2. FC 任务包 → 实现映射

| 任务包 | 模块（plc_project 下） | 关键测试 |
|---|---|---|
| FC-00 四图 + 稳定 ID | `processos/registry/` + `processos/store/persistence.py`（重启存活） | test_traceability / test_persistence |
| FC-01 SourceMap | `processos/sourcemap/`（块级定位下限，不虚构行号） | test_traceability |
| FC-02 Incident/AlarmMap | `processos/incident/` | test_traceability / test_acceptance_drill |
| FC-03 三基线 + DriftGate | `processos/baselines/`（B1/B2/B3、compare/gate_change/gate_delivery、UNVERIFIED_ONLINE） | test_baselines 13 |
| FC-04 语义 Patch + 审核 | `processos/contract/patch.py` + api/app.py 门禁（审批者分离） | test_acceptance_drill 关 6 |
| FC-05 Impact Report | `processos/impact/`（15 字段、UNKNOWN 阻断高风险） | test_impact 8 |
| FC-06/07/08 合规/状态机/回归 | `processos/semantics/` + `scenario/` + BEHAVIOR_REGRESSION 门禁（先 409 阻断→场景同步→放行） | test_safety_gates 7 |
| FC-09/10/11 原生交付 | v2 网关链 + `processos/native/`；**本轮新增真机凭证**（§4） | test_native / test_acceptance_drill 关 6-7 |
| FC-12/13 Incident Console/交接 | `frontend/src/processos/Traceability.tsx` + handover 上下文 + 就绪校验 | test_handover_readiness 19 |
| FC-14 投产账本 | `processos/commissioning/` + CommissioningLedger.tsx | test_commissioning 6 |
| FC-15/16/17 遥测/差异/回收 | `processos/telemetry/`（SIMULATED 强制标注、无删除端点、MANAGED_NATIVE_OVERRIDE、frozen） | test_telemetry 14 |
| FC-18 受控部署网关 | `processos/deployment/`（fail-closed、无一键上线、backend=None→501） | test_deployment_gateway 13 |
| §7 RBAC + 审计 | `processos/rbac/`（7 角色 17 action、403 入审计） | test_rbac 14 |
| §8 端点补全 | preview（diff+影响+测试计划）/ 工件下载（防穿越）/ 幂等键 / 租约锁 | test_changeset_preview / test_job_artifacts / test_idempotency / test_locks |
| §10 八关验收 | `processos/tests/test_acceptance_drill.py`（八关 + 负路径 DRIFT_DETECTED） | 9 |
| §11 十错误码 | `processos/safety/errors.py`，全部有显式抛出点 | 各门禁测试 |
| §12 九工件 | `processos/artifacts/`（compile_receipt 如实标 mocked/V19_real） | test_pr_bundle 4 |

## 3. 双入口前端交互（用户新增需求）

| 入口/步骤 | 实现 | 测试 |
|---|---|---|
| 新建 a：硬件组态 + IO/符号预览 | Wizard 硬件步骤 + 符号表面板（symbolic_only） | wizard.steps 16 |
| 新建 b：工位→执行器→步序 | **结构化步序编排步骤**（guard/动作/超时/故障出口；下一步仅限既有步骤，无画线交互）+ `POST /projects/from-spec`（fail-closed 校验） | test_spec_builder 27 |
| 新建 c：工位间编排 | **OrchestrationView**（顺序轨/并行组/资源互斥/冲突提示）+ `set_operation_schedule` op（双重校验、契约往返无损承载 `ProcessContract.schedule`） | test_schedule_op 29 + orchestration 19 |
| 新建 d：修错闭环 | **DiagnosticsPanel**：编译诊断→SourceMap 定位对象/步骤（歧义不猜、UNMAPPED_NATIVE_CODE 显式）+ 修复提案白/黑名单（七类禁止）+ 全量/建议增量范围与受影响块清单 | test_diagnostics 23 + diagnostics 14 |
| 导入 第0步：基线比对 | 三色 verdict / 无基线黄条 + 块级哈希 diff | importer 内 |
| 导入 a：结构解析 | **真解析**（SimaticML XML 防御性解析）→ 保真度四级（EXACT/PARTIAL/OPAQUE/PROTECTED；PROTECTED 认领 403）→ 认领映射落对象图 | test_importer 19 + import.smoke 12 |
| 导入 b/c：更新与编译 | 语义 Patch + Impact + 审批（前轮）+ 门禁顺序 + BUILD_VERIFIED 导出 | 前轮各测试 |
| 画布 | MachineCanvas / StationCanvas（只读分层、UNKNOWN 徽章、无输出操作） | canvas.smoke 8 |
| 现场轴 | FieldConsole 三入口 + 基线/账本/网关/遥测面板 + 角色选择器 | 各 smoke |

## 4. 真机 V19 凭证（V19_real）

- 凭证目录：`plc_project/evidence/v2/real/processos_attempt_01/`（chain_receipt.json + PRJ_CLAMP_REAL.zap19 + stages/ + run_info.txt）
- 结果：7 阶段全过（OPEN→IMPORT→COMPILE **0 错误/2 警告**→SAVE→ARCHIVE→HASH→RETRIEVE_REOPEN），`delivery_complete=true`
- 归档 sha256：`b01954dad1053743ca8ba7ac780865d72ba65297f69edf7f2d908d633f99ea3c`（独立复算一致）
- 复现：`uv run ... python scripts/processos_real_compile_skeleton.py --ob-mode ladxml`
- 排障过程中发现并修复的真问题：
  1. codegen 缺口：unit 角色 FB 无 SCL 发射器（mock 发现不了）→ `processos/codegen/scl.py::_gen_unit`
  2. 本机 TIA V19 ExternalSources 生成的 OB（含空体）一律 inconsistent → OB 改走 SimaticML XML + `Blocks.Import(Override)`（v1 真机先例模式）
  3. SimaticML 文档内 ID 必须全局唯一（多网络渲染时）

## 5. 诚实边界

1. Unit 生成器当前为**透传壳**：跨工位调度语义已入契约（`contract.schedule`），生成 SCL 暂未承载（OrchestrationView 固定横幅标注；生成器扩展后自动生效）。
2. 增量编译为**建议范围**（compile-scope）；当前交付链全量编译，分级增量由 C# FastWriteback 承接。
3. 导入链「工艺重建」为占位（结构认领已真实落库，UI 明示「工艺重建待后续」）。
4. RBAC 为演示级 header 身份（非生产认证，模块 docstring 声明）；幂等缓存与租约锁为单进程语义。
5. 真实 OT 遥测通道未接（§6.4 允许的手工降级已实现）；B2 demo 哈希为派生标识，真实哈希仅 V19 回执（processos_attempt_01）。
6. `plc_project/docs/v2/*.md` 在工作树中的删除为用户先行的文档重组，2 个前端 ENOENT 失败源于此，未在本次提交内处理。

## 6. 交付方式记录

多 Agent 协作：主 Agent（契约锁定/派发/仲裁/独立复核）+ 子 Agent A~N 分域并行（持久化/基线/影响/现场侧/RBAC/前端/集成/补缺/画布/向导/导入/修错/编排）；系统性坑位（sqlite 跨线程、闭包注解、FastAPI 0.143、Mimosa SQL 扫描）均沉淀为各任务书纪律条款。
