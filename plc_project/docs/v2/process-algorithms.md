# WP-03 · SequenceIR / GuardAST / Trace / SCL Lowering（离线算法）

> 证据等级：**offline**。Trace 是「预测模型 · 非在线 PLC 波形」，不是实机验证。
> 实现位置：`plc_engine/process/`。

## 1. GuardAST（强类型，禁止 eval）

- 值类型：`BOOL / TIME / INT`（TIME 以毫秒整数表达）。
- 节点：`CONST / SIGNAL / AND / OR / NOT / EQ / NE / LT / LE / GT / GE / ELAPSED_GE`。
- `GuardAST.from_dict()` 拒绝任何 `expression / expr / text / code / eval / formula` 自由文本键；未知节点直接抛 `GuardValidationError`。
- `validate_types()` 做静态类型检查；`evaluate_detailed()` 对未知信号、类型不匹配一律 fail-closed（False + issue）。
- `guard_to_scl()` 把同一 AST 编译为 SCL 布尔表达式（如 `(#CmdStart AND NOT (#SensorIn))`、`T#2000ms`），模拟器与 SCL 共享语义。

## 2. 图校验（A3 / A4）

| 检查 | 算法 | 失败行为 |
|---|---|---|
| 可达性 | BFS（含 exception/timeout 边） | 不可达步骤 → 422 |
| 非终止循环 | Tarjan SCC + 无出口判定 | SCC 无外部边 → 422 |
| 分支优先级/互斥 | 同出边 priority 唯一，或 AST 中显式 `signal` / `NOT signal` 互斥证明 | 无法证明 → 422 |
| 超时与 FAULT 路径 | 每个 `max_duration_ms>0` 步骤必须有 failure_target 或 TIMEOUT exception；运动步骤必须有异常路径 | 缺失 → 422 |
| 命令资源冲突 | `arbitrate_single_writer()` + 反向命令对（extend/retract、start/stop…） | 双线圈/写者冲突 → 422 |
| 并行语义 | `parallel_groups` 非空 | `UNSUPPORTED_PARALLEL_SEMANTICS` fail-closed，阻止交付 |
| 单写者 | 每个 COMMAND 端口必须声明唯一 writer | 缺失 → 422 |

`unknown == fail`：通过检查只代表这些规则通过，不等于机器安全被证明。

## 3. 确定性扫描周期模拟器（A5）

固定顺序（`contracts.SCAN_ORDER`，与 SCL Lowering 一致）：

```
FREEZE_INPUT_SNAPSHOT → EVALUATE_TYPED_GUARDS →
RESOLVE_PRIORITY_AND_EXCLUSIVITY → ATOMIC_TRANSITION →
COMPOSE_ACTIONS → ARBITRATE_SINGLE_WRITER →
TICK_DRIVER_FSMS → EMIT_OUTPUTS_AND_ALARMS
```

`TraceFrame` 字段：cycle / time_ms / active_step / conditions / actions / driver_states / outputs / alarms / source_map_refs / evidence_level / data_source / notice。

五个场景（`build_standard_scenarios()`，全部 offline）：

| 场景 | 输入 | 期望终态（golden） |
|---|---|---|
| normal_cycle | CmdStart、SensorOut@100、HoldDone@1200、SensorIn@1600、CmdStart=OFF@2200 | S0（循环回待机） |
| extend_timeout | 永不给 SensorOut | FAULT + `EXTEND_TIMEOUT` |
| retract_timeout | 给 SensorOut，永不给 SensorIn | FAULT |
| safety_permit_lost | SafetyPermit=False@500 | FAULT，所有输出被抑制 |
| fault_reset | 超时进 FAULT 后 Reset@3500 + CmdStart=OFF | S0 |

失败返回 `shortest_counterexample()` 的最短步序路径（示例 `["S0","FAULT"]`），而非一行「仿真失败」。

## 4. SCL Lowering + SourceMap（A6）

```
Frozen IR + pinned AFProfile + template_sha256
  → 静态门禁（9 类检查）
  → UDT → FB_Drivers / FB_Sequence → DB_Sequence → OB_Main
  → 每行带 source_id 注解 + N:N SourceMap
  → ArtifactManifest{files, sha256, import_order, dependencies}
```

- 依赖顺序显式校验：`UDT → FB/FC → instance DB → call OB`。
- **不编造块号**（`block_number=None`）；FB 名来自显式 IR/catalog 数据，**不从 DB 命名反推**。
- `SourceMap` 支持一个 IR id → 多行/多 TIA 块，一个 TIA 块 → 多个 IR id；编译诊断 `TIA block + line → IR 节点 → Canvas 红色标记`。
- 语义文件与 manifest hash 不含时间戳；时间戳只进 `receipt`。同冻结 IR + AFProfile + 模板 hash 二次生成 hash 一致（`assert_deterministic()`）。
- US-3：S2 `min_duration_ms` 1000 → 2000 后，IR / Trace / SCL 常量 `T#1000ms → T#2000ms` / manifest hash 三方同步；仅改 `views.layout` 不触发任何重生成。

## 5. Golden 快照

`tests/snapshots/v2/`：5 个 `*.golden.scl` + `manifest.golden.json` + `trace_scenarios.golden.json`。
由 `uv run python scripts/gen_golden_v2.py` 生成，测试逐字节/逐 hash 比对。

## 6. 范围外（明确不实现）

HMI、Software Unit、**并行 Step 运行语义**（Fork/Join 仅可展示并阻止交付）、在线下装/运行/停止、F-block 自动修改、V20/V21、Brownfield 实机增删改、物理组态自动规划。
