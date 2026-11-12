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

**基线审计日志实况校正（含主理人补跑数据）**：原 `baseline_audit.log` 的 vitest 段为空、dotnet 段只有 `build`；但同目录 `baseline_vitest.log` 实际存在。主理人已补跑前端 vitest 基线并追加 `VITEST_EXIT=0` 到 `baseline_audit.log`，真实结果为 `Test Files 23 passed (23)`、`Tests 393 passed (393)`、vitest 5.0.4、耗时 **2.27s**（日志 `backup/pre_v2_20261109/baseline_vitest.log`）。`baseline_pytest.log` 显示 3 个 `F` + 1 个 `x`（未列测试名）、`PYTEST_EXIT=1`；`baseline_dotnet.log` 只有 `dotnet build`（20 warning / 0 error），**未跑 test**。本报告按实际复跑结果记录，不把声明值当作已验证。

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

### 2.2 vitest（前端基线 · 0 失败）

**主理人补跑基线（Q-07 输入，权威）**：`backup/pre_v2_20261109/baseline_vitest.log`
→ `Test Files 23 passed (23)`、`Tests 393 passed (393)`、vitest 5.0.4、耗时 2.27s、`VITEST_EXIT=0`（已追加到 `baseline_audit.log`）。**前端基线 0 失败。**

本批独立复跑（同一命令，交叉验证）：

```
cd frontend && npm test -- --reporter=dot
VITEST_EXIT=0
Test Files  23 passed (23)
     Tests  393 passed (393)
```
本批复跑耗时 1.43s，原始输出：`docs/v2/evidence/T01/vitest_baseline.txt`。本期未改动前端任何文件；两次实跑结果一致，均为 393 passed / 0 failed（不是 README 的未复跑声明值）。

### 2.3 dotnet test（C# / net481）

**基线实况（Q-07 要求补跑）**：`backup/pre_v2_20261109/baseline_dotnet.log` 此前只执行了 `dotnet build`（`DOTNET_EXIT=0`，**20 warning / 0 error**），**从未执行 `dotnet test`**。本批按裁定补跑 `dotnet test industrial/tia_openness_cli/TiaOpenness.sln -c Release` 并留真实输出；build 通过不等于测试通过，二者严格区分。

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

真实 C# `status` 回执（原文摘要，一手证据 `evidence/v2/T01/capability_probe.json` 第 50-70 行 + `g0_probe.json` 的 `status_receipt`）：

```json
{"ok": true, "tiaRunning": true, "processCount": 1,
 "opennessAvailable": true, "opennessGroupInToken": true, "tiaVersion": "V19",
 "engineeringDll": "C:\\Program Files\\Siemens\\Automation\\Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll",
 "connected": false, "projectOpen": false,
 "message": "TIA Portal process detected.",
 "_exit_code": 0}
```

**更正说明（P-06，主理人 2026-11-12 最终裁定）**：本节上方 JSON 是 **P1** 的一手 C# `status` 回执。此前「同一次探测 / 二手转述错误 / 统一 true/1」的裁定**已撤销**——忽略 `cpu_selection.json` 自带不同 receipt id 是误判。真实为**两次独立只读探测，各自真实**：

| | P1（T01/G0 探测） | P2（T05 CPU 选型时重新探测） |
|---|---|---|
| `probe_receipt_id` | `g0_d32beeb9478950dd` | `g0_acf8be499157d5b4` |
| `probed_at` | `2026-11-09T15:03:48.281136+00:00` | `2026-11-09T16:00:50.956689+00:00` |
| `tiaRunning` / `processCount` | `true` / `1` | `false` / `0` |
| message | `TIA Portal process detected.` | `TIA Portal process not detected (Openness can still start WithoutUserInterface).` |
| 一手证据位置 | `g0_probe.json` / `capability_probe.json` | `cpu_selection.json → capability_manifest.raw_probe_receipt` |

Portal 进程在两次探测之间退出，故数值不同属正常，**禁止互相覆盖、不得用转述错误解释**。QA 独立复核确认两个 `probe_receipt_id` 与 `probed_at` 均不同，并已撤销其上一轮「ID/时间相同」的旧判断。原 receipt id / probed_at 全部保留，不抹历史。

- 探测性质：**只读**。两次均未创建/打开/写入任何 TIA 工程；`tiaRunning` 仅表示探测时刻 Portal 进程是否存在，**不**代表 CreateWithItem 验证或交付全链成功。
- `evidence_level=V19_real` **仅覆盖只读 status 回执**：`real_tia_v19_chain_tested=false`、`evidence_scope=read_only_status_probe`、`g5_status=pending_real_machine`；绝不代表 AC-01/G5 已通过。CPU 候选均未做 `CreateWithItem` 验证。
- `docs/v2/evidence/T01/g0_probe_stdout.txt` 为 T01 原始命令 stdout，保留历史用词（含旧 `static_approved_candidate_v19`）不改；派生产物已统一为 `static_candidate_v19_unverified`。
- 原始回执：`evidence/v2/T01/g0_probe.json`、`capability_probe.json`、`cpu_selection.json`、`batch_receipt.json`。

- 候选 CPU skeleton（U-02 已由主理人指定 `6ES7511-1AK02-0AB0/V2.9`，状态 `selected_by_lead` + `verification_required=true` + `verified_create_with_item=false`，绝不冒充 approved/verified）：
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
