# WP-05 · Brownfield 接口与 Schema 契约（本期仅接口，禁止实机）

> 证据等级：**mocked / offline**。依据 Q-04 / 用户拍板第 3 条：
> **本期只留接口与 Schema；AC-02 不做实机验收；不允许任何 V19 real 增删改证据。**

## 1. 范围冻结

✅ 本期含：`SourceBinding` 完整记录、最小 `DiffPlan` 数据结构、反向引用闭包查询接口、API 占位端点、4+ 类负例拒绝、可选 **mocked** 编排演示（响应强制 `evidence_level=mocked`）。

❌ 本期不含：真实 `.ap19/.zap19` 导入后写回、Openness 写入 API、原件修改、ADD/MODIFY/DELETE 实机执行、AC-02 五步实机闭环、F-block / Safety 程序自动修改、任何 `V19_real` 写证据。

## 2. 实体

| 实体 | 字段 | 不变量 |
|---|---|---|
| `SourceBinding`（`plc_engine/changeplan/source_binding.py`） | `source_block_id` / `original_hash` / `source_span` / `ir_ids` / `writable` / `referenced_by` / `fidelity` + IR 基础字段 | `writable=requires_review`；F-block 与不可解析块 `is_protected()` 恒真；`original_hash` 保留原文 hash；不可解析块必须仍出现在绑定索引中 |
| `DiffPlan`（`diff_plan.py`） | `plan_id` / `ops` / `impact_closure` / `baseline_hash` / `hardware_hash` / `safety_block_hash` / `executable` | **`executable` 恒为 `false`**；只有声明，没有执行体；`evidence_level=mocked` |
| `DiffOp` | `op` ∈ ADD/MODIFY/KEEP/DELETE + `source_id` / `target` / `payload` | 只是声明，不触发任何 TIA 写入 |

`changeplan.SourceBinding` 继承 `engineering_ir.models.SourceBinding`（IR 内的轻量绑定投影）并扩展导入专用字段，避免两套重复定义；二者职责不同（IR 引用 vs 导入保真快照）。

## 3. 接口

| 接口 | 位置 | 行为 |
|---|---|---|
| `reverse_reference_closure(bindings, target_ids)` | `impact_closure.py` | 纯函数：返回传递引用目标的块 id（排序、确定性），不打开 TIA |
| `evaluate_diff_plan(plan, bindings, expected/actual_baseline_hash)` | `brownfield_guard.py` | 返回 `GuardIssue[]`；空列表也**不**授权实机写入 |
| `mocked_orchestrate(plan, bindings)` | `mocked_orchestrator.py` | 仅声明式回执：`applied=false` / `executable=false` / `evidence_level=mocked` / `real_tia_v19_tested=false` |
| `BrownfieldServiceV2.review(...)` | `gateway/app/services/plc/brownfield_v2.py` | 组装 plan + 跑负例门禁 + 可选 mocked 编排 |
| `POST /api/v2/brownfield/diffplan` | `routers/projects_v2.py` | 占位端点；负例命中返回 403/409，响应恒 `mocked` |

## 4. 负例拒绝清单（必须全部命中）

| # | 负例 | 拒绝码 | 行为 |
|---|---|---|---|
| 1 | F-block / Safety 块可写请求（或 `writable != requires_review`） | `WRITEBACK_FORBIDDEN` | 403；保留原块 |
| 2 | 删除仍被 kept 块引用的 FB | `WRITEBACK_FORBIDDEN` | 403；列出引用者 |
| 3 | 基线漂移（expected ≠ actual / plan.baseline_hash ≠ actual） | `BASELINE_HASH_MISMATCH` | 409 |
| 4 | 写原件 / 删原件 / 修改原件 | `WRITEBACK_FORBIDDEN` | 403；原件不动 |
| 5 | 不可解析 / 受保护块消失 | `WRITEBACK_FORBIDDEN` | 403；必须保留且 `fidelity` 标注 |
| 6 | `DiffPlan.executable=true` 或声明 V19 real 证据 | `EXECUTABLE_FORBIDDEN` / 断言失败 | 拒绝 |

## 5. 三级证据口径

- 本批所有 Brownfield 结论为 **mocked**（编排）或 **offline**（纯函数/Schema）。
- 任何响应不得出现 `evidence_level=V19_real`、`real_tia_v19_tested=true`、`applied=true`、`executable=true`。
- `writable=requires_review` 是 F-block / 受保护块的硬边界；`no findings` 只表示这些检查通过，不等于机器安全被证明。

## 6. 与 AC-02 的关系

AC-02（重新导入归档 → 仅修改关联序列 FB → 真实编译/归档 → 原件不动）**本期不作为实机验收**。
其接口与 Schema 在本期落地，实机 ADD/MODIFY/DELETE 属于范围外，任何优先级都不得顺手纳入。
