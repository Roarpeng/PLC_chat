# T01 · WP-00 基线复跑报告（真实输出）

> 生成时间：2026-11-09；执行人：寇豆码（工程师）；证据口径：offline / mocked / V19_real / pending_real_machine。
> 历史 `evidence/*.json` 未改动；本报告不把任何 mock 计入基线通过。

## 1. 环境实况

| 项 | 值 |
|---|---|
| 分支 | `refactor/v2-full` |
| 基线 HEAD（本批复跑时） | `e228226` |
| 基线 tag | `baseline/pre-v2-20261109` |
| Python | 3.13.14（`requires-python >= 3.11`） |
| uv | 0.9.17 |
| dotnet SDK | 8.0.423（**仅构建工具链**；Worker TargetFramework 仍为 `net481`） |
| Node | v22.22.2 |
| vitest | 5.0.4 |
| 基线审计输入 | `backup/pre_v2_20261109/baseline_audit.log`、`baseline_pytest.log`、`baseline_vitest.log`、`baseline_dotnet.log` |

**基线审计日志实况校正**：`baseline_audit.log` 的 vitest 段为空、dotnet 段只有 `build`；但同目录 `baseline_vitest.log` 实际存在并显示 23 files / 393 passed，`baseline_pytest.log` 显示 3 个 `F` + 1 个 `x`（未列测试名）、`PYTEST_EXIT=1`。本报告按实际复跑结果记录。

## 2. 三套基线复跑（本期实际执行）

### 2.1 pytest（全量）

| 命令 | 结果 |
|---|---|
| `uv run pytest tests -q --disable-warnings -rf` | 本机 300s 内到 72% 后超时（`exit=124`）：进度条前 4% 出现 3 个 `F` + 1 个 `x`，与基线摘要一致 |
| `.venv/Scripts/python.exe -m pytest tests -q --disable-warnings -rf --maxfail=3` | **3 failed, 73 passed in 8.69s**，`PYTEST_EXIT=1`（用于取真实失败名） |
| `.venv/Scripts/python.exe -m pytest tests -v ...`（timeout 90） | 定位到既有挂起测试：`tests/unit/test_canvas_import.py::test_import_canvas_from_zap19_with_incomplete_project`（`-v` 输出停在该用例，无 PASSED） |
| `.venv/Scripts/python.exe -m pytest tests --collect-only -q` | 1517 行，收集成功 |
| `uv run pytest tests/unit/test_*_v2.py tests/contracts -q -rf` | **162 passed, 0 failed**（本期新增） |
| 分批：`T02 39 / T03 27 / T04 46 passed` | 真实输出见 `docs/v2/evidence/T0*/` |

**结论**：3 个失败与 1 个 xfail 均为既有基线失败（详见 `pre_existing_failures.md`）；本期新增 162 项测试全部通过，**未引入任何新失败**。全量套件在本机存在既有慢/挂用例，已如实标注并隔离，未删除任何内核、未用 mock 顶替。

### 2.2 vitest（前端基线）

```
cd frontend && npm test -- --reporter=dot
VITEST_EXIT=0
Test Files  23 passed (23)
     Tests  393 passed (393)
```
原始输出：`docs/v2/evidence/T01/vitest_baseline.txt`。本期未改动前端任何文件，393 项与 `baseline_vitest.log` 声明值一致且为**实跑**通过（不是声明值）。

### 2.3 dotnet test（C# / net481）

```
dotnet test industrial/tia_openness_cli/TiaOpenness.sln -c Release
DOTNET_TEST_EXIT=0
已通过! - 失败: 0，通过: 110，已跳过: 0，总计: 110
```
- 首次复跑 109 passed / 1 failed：失败项是我新增的 `ArchiveContractTests.CreateProjectReceipt_UsesCreateProjectPath_CamelCase`（JSON 子串断言写法错误），**已修正源码断言后重跑 110/110 通过**。
- `dotnet build` 阶段仍有既有的 20 条 CS86xx 可空引用警告（与基线一致，未修改相关内核文件）。
- `TargetFramework=net481` 冻结未迁移（D-4）；`.NET 8` 仅构建 SDK。
- 原始输出：`docs/v2/evidence/T02/dotnet_test.txt`。

### 2.4 IR roundtrip / 语义哈希确定性

```
uv run python -c "..."
IR_ROUNDTRIP_EQUAL= True
IR_SHA256= sha256:3ee31ae438c7470835b41d4846ea5db12e7a9c792d641691650e7470d0268a4e
LAYOUT_EXCLUDED= True
DETERMINISTIC_SECOND_GENERATION= True
PATCH_REVISION= 1 HASH_CHANGED= True
```
原始输出：`docs/v2/evidence/T01/ir_roundtrip_semantic_hash.txt`。

## 3. G0 真机只读探测（V19_real，仅 status 回执）

命令：`uv run python scripts/probe_capability_v2.py --no-db`

真实 C# `status` 回执（原文摘要）：

```json
{"ok": true, "tiaRunning": false, "processCount": 0,
 "opennessAvailable": true, "opennessGroupInToken": true, "tiaVersion": "V19",
 "engineeringDll": "C:\\Program Files\\Siemens\\Automation\\Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll",
 "connected": false, "projectOpen": false,
 "message": "TIA Portal process not detected (Openness can still start WithoutUserInterface).",
 "_exit_code": 0}
```

- 探测性质：**只读**。未创建/打开/写入任何 TIA 工程。
- `evidence_level=V19_real` 仅针对该 status 回执；`tiaRunning=false`、`processCount=0`，CPU 候选未做 `CreateWithItem` 验证。
- 候选 CPU skeleton（需主理人指定，U-02）：
  1. `6ES7511-1AK02-0AB0/V2.9` — S7-1500 CPU 1511-1 PN
  2. `6ES7513-1AL02-0AB0/V2.9` — S7-1500 CPU 1513-1 PN
  3. `6ES7515-2AM02-0AB0/V2.9` — S7-1500 CPU 1515-2 PN
  4. `6ES7214-1AG40-0XB0/V4.5` — S7-1200 CPU 1214C DC/DC/DC
- 全部 `verified_create_with_item=false` → 未指定时不能自动选定，交付前置检查按 `CPU_TEMPLATE_NOT_SELECTED` 显式失败并留痕 pending_real_machine。
- 原始回执：`evidence/v2/T01/g0_probe.json`、`evidence/v2/T01/capability_probe.json`。

## 4. 三级证据结论

| 项 | 等级 |
|---|---|
| EngineeringIR / Patch / Guard / Trace / SCL / DriverCatalog / 契约测试 | offline |
| 交付事务链、归档绑定、Retrieve/reopen 负例（注入 fake worker） | mocked（**从不冒充真机成功**） |
| C# `status` 只读探测 | V19_real（仅探测回执） |
| 真实 `.ap19` 创建 → 编译 0 error → Save → Archive → `.zap19` → Retrieve/reopen → 精确下载 | **pending_real_machine（本批未执行，G5 待主理人/QA 串行调度）** |

## 5. 未完成 / 不冒充声明

- 本批**没有**取得 V19 real 全链证据；没有任何 `.zap19` 原生归档被发布；没有任何「交付完成」状态。
- README 的 1341 / 393 声明值按 Q-07 仅作为声明值引用；`xml_package_unverified=true` / M4 未通过 / 端到端未闭环口径未改。
- 全量 pytest 的既有慢/挂用例已隔离标记，未删除内核，未用 mock 顶替。
