# WP-06 · 故障注入矩阵（G7 / PRD §6.2）

> 真实执行：`uv run pytest tests/unit/test_fault_injection_v2.py tests/unit/test_idempotency_v2.py tests/unit/test_recovery_v2.py -q -rf` → **18 passed**。
> 全量 v2 回归 `uv run pytest tests/unit/test_*_v2.py tests/contracts -q -rf` → T07 当批 202 passed；T01–T08 + QA 缺陷修复后最终 **212 passed / 0 failed**（QA 独立套件 36 passed）。
> 判据：**100% 失败任务不得发布 `NATIVE_ARCHIVED`**；失败保留 ledger 与可编辑设计；导出物与请求工程一致。

## 1. 落点（无空壳文件）

| 能力 | 落点 |
|---|---|
| append-only `job_events` / `stage_cursor` / `project_locks` | `gateway/app/services/plc/workspace_v2.py`（T01 已建 10 张表 + `BEGIN IMMEDIATE` 事务 + RLock） |
| 作业幂等（`idempotency_key` UNIQUE / `request_id` UNIQUE） | `workspace_v2.py` + `delivery_jobs_v2.start()` |
| 项目独占锁 / 单 STA 队列 | `workspace_v2.acquire_project_lock()` + `delivery_jobs_v2.run_chain()` |
| worker crash recovery | `delivery_jobs_v2.recover()` + 本文 `rollback_plan()`（检测现存工程与实际成果后按 stage 幂等续跑，不盲目重发） |
| 路径白名单 / 坏 XML / 坏 ZIP / schema migration / 最小披露 / 回滚策略 / 故障编排 | `gateway/app/services/plc/fault_injection_v2.py`（本批新增，**无空壳**） |

设计 §2.5 允许「继续沿用等价实现并在文档中说明落点」，故未新建 `job_ledger_v2.py` / `project_lock_v2.py` / `recovery_v2.py` / `path_whitelist_v2.py` 四个空壳；等价能力均已在上述真实实现中落地。

## 2. 故障注入矩阵（15 类，实测 14 类进矩阵 + 1 类单测）

| # | 故障 | 注入方式 | 期望 | 实测 |
|---|---|---|---|---|
| 1 | `path_missing` | create 回执缺 `create.projectPath` | `FAILED` / `ARCHIVE_MISSING`，不猜路径 | ✅ 拒绝 |
| 2 | `cpu_not_selected` | CPU skeleton 为空 | `CPU_TEMPLATE_NOT_SELECTED` | ✅ 拒绝 |
| 3 | `double_coil` | 同一步反向线圈同时置位 | `422` 命令资源冲突 | ✅ 拒绝 |
| 4 | `delete_referenced_fb` | 删仍被 kept 块引用的 FB | `WRITEBACK_FORBIDDEN` | ✅ 拒绝 |
| 5 | `modify_f_block` | 写 F-block | `WRITEBACK_FORBIDDEN` | ✅ 拒绝 |
| 6 | `baseline_drift` | expected ≠ actual baseline | `409 BASELINE_HASH_MISMATCH` | ✅ 拒绝 |
| 7 | `unknown_guard` | 非法 Guard AST 类型 | `422` | ✅ 拒绝 |
| 8 | `parallel_semantics` | `parallel_groups` 非空 | `UNSUPPORTED_PARALLEL_SEMANTICS` | ✅ 拒绝 |
| 9 | `compile_failed` | `error_count=3` | `FAILED` / `COMPILE_FAILED`，warning 单列 | ✅ 拒绝 |
| 10 | `archive_missing` | 精确 `archivePath` 不存在 | `FAILED` / `ARCHIVE_MISSING` | ✅ 拒绝 |
| 11 | `tia_unavailable` | worker 抛 `TiaUnavailableError` | 显式失败，非 200 / `ok=false` | ✅ 拒绝 |
| 12 | `worker_crash` | 租约过期 / 编译期中断 | `RECOVERY_REQUIRED` + stage 游标 | ✅ 拒绝发布 |
| 13 | `bad_xml` | DTD/ENTITY 注入、破损 XML | `BAD_XML_*`（defusedxml） | ✅ 拒绝 |
| 14 | `bad_zip` | 缺文件 / 坏 CRC / `../` 穿越 / 条目超限 | `BAD_ZIP_*` | ✅ 拒绝 |
| 15 | `duplicate_request` | 重复 `request_id` / `idempotency_key` | 幂等返回既有结果，不重复生成 | ✅ 不重复 |

`run_fault_matrix()` 汇总实测：`total=14`、`native_archived_published=0`、`all_failed_jobs_safe=true`；每个失败 job 的 `state ∈ {FAILED, RECOVERY_REQUIRED}` 且 `evidence_level != V19_real`，ledger 保留 FAILED/RECOVERY_REQUIRED 事件。

## 3. 安全工具实测

| 工具 | 断言 |
|---|---|
| `PathWhitelist` | 拒绝 `../../etc/passwd`、绝对路径、盘符路径、`..` 片段、控制字符、空路径；只允许白名单根内相对路径 |
| `reject_bad_xml` | 拒绝 `<!DOCTYPE` / `<!ENTITY` / 破损标签；接受合法 XML |
| `reject_bad_zip` | 拒绝含 `../escape.txt` 的 ZIP、坏 ZIP；接受合法 ZIP |
| `schema_migration_check` | 10 张冻结表全部存在，`missing_tables=[]` |
| `minimal_disclosure` | 只输出块索引 / 设备定义 / 当前步骤，`truncated` 标记；不携带 `components` 全量对象 / `legacy_raw` |
| `rollback_plan` | 保留 ledger 与失败阶段回执 → 检测现存工程 → 校验精确 sha256 → 按 stage 续跑 → **不盲目重发非幂等写入** |

## 4. 三级证据

本批全部为 **offline**（纯函数 / Schema / 静态检查）与 **mocked**（注入 fake worker 的编排验证）。
**没有任何 V19 real 编译/归档证据**；所有失败任务均不发布 `NATIVE_ARCHIVED`；`pending_real_machine` 与 `tia_unavailable` 严格区分。
