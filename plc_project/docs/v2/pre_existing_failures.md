# 既有基线失败隔离清单（Q-07 / U-01）

> 原则：**单列隔离标记、不删内核、不掩盖、不用 mock 顶替；本期代码不得引入新失败。**
> 基线依据：`backup/pre_v2_20261109/baseline_pytest.log`（`PYTEST_EXIT=1`，3 个 `F` + 1 个 `x`，未列测试名）。
> 本批实际复跑命令：`.venv/Scripts/python.exe -m pytest tests -q --disable-warnings -rf --maxfail=3` → `3 failed, 73 passed in 8.69s`。

## 0. 三套基线口径（主理人补充裁定输入，逐条明确）

| 套 | 基线事实 | 本批处置与真实输出 |
|---|---|---|
| ① 前端 vitest | **基线 0 失败**：主理人补跑 `Test Files 23 passed (23)`、`Tests 393 passed (393)`、vitest 5.0.4、耗时 2.27s、`VITEST_EXIT=0`（`backup/pre_v2_20261109/baseline_vitest.log`，已追加到 `baseline_audit.log`） | 本批独立复跑同一命令同为 393 passed / 0 failed，留痕 `docs/v2/evidence/T01/vitest_baseline.txt`；本期未改动前端任何文件，前端基线 0 失败且本批 0 新失败 |
| ② pytest | **基线 `PYTEST_EXIT=1`**：`baseline_pytest.log` 摘要为 3 个 `F` + 1 个 `x`（xfail），**未列具体测试名** | 完整 `-rf` 全量复跑在本机因既有挂起用例超时（见 §3）；按 Q-07 用 `--maxfail=3 -rf` 实跑取得 3 个真实失败名（见 §1，非推测）、1 个既有 xfail（见 §2），并单列隔离标记 |
| ③ dotnet | 此前**只执行 `dotnet build`**（`DOTNET_EXIT=0`，**20 warning / 0 error**），**从未执行 `dotnet test`** | 本批补跑 `dotnet test industrial/tia_openness_cli/TiaOpenness.sln -c Release` → **110 passed / 0 failed**（首次 1 个新增测试断言写法错误已修正后重跑通过），真实输出 `docs/v2/evidence/T02/dotnet_test.txt`；20 条 CS86xx 可空引用警告为既有基线，未改内核。build 通过 ≠ 测试通过，严格区分 |

## 1. pre-existing failure（3 项，全部与本期代码无交集）

**测试名取得方式（Q-07 / U-01）**：基线日志只给 3 个 `F` 摘要、无测试名；本批用
`.venv/Scripts/python.exe -m pytest tests -q --disable-warnings -rf --maxfail=3`（真实输出 `3 failed, 73 passed in 8.69s`）复跑取到下列真实名称，不是从进度条推测。完整全量 `-rf` 因既有挂起用例在本机 300s 超时，已按 §3 交叉复跑并如实标注。

| # | 测试名 | 失败原因（真实输出） | 与本期关系 |
|---|---|---|---|
| 1 | `tests/unit/test_af_engine.py::test_get_startup_zip` | `FileNotFoundError: AF V1.2 asset 'Automation_Framework_Startup_PROJ_V1_2.zip' not found under .../docs` | 仓库缺失 AF V1.2 启动 ZIP 资产；本期未改 `plc_engine/af/*` 公共行为 |
| 2 | `tests/unit/test_af_import.py::test_hr001_real_import_roles_and_freeze` | **归因更正（P-08）**：真实失败为 `tests/unit/test_af_import.py:322` 的 `AssertionError: assert 'global' == 'em'`（AF 角色推断断言）；`:304` 的 skipif 未触发说明 HR001 夹具**存在**，补齐 AF V1.2 ZIP **不会**让该用例通过 | 角色推断逻辑需独立评估；本期未触碰 `af_import` |
| 3 | `tests/unit/test_af_phase3.py::test_api_new_project_with_af_template` | `gateway/app/routers/plc.py:885 create_new_project_endpoint → clone_startup_template → get_startup_zip` 抛同一 `FileNotFoundError` | v1 路由保持注册且公共行为不变；本期只增加一行 `include_router(projects_v2.router)` |

隔离标记：`PRE_EXISTING_FAILURE` — 不修、不删、不跳过、不用 mock 顶替。**#1/#3 需补齐 AF V1.2 资产文件；#2 需独立评估 AF 角色推断逻辑（`'global' == 'em'` 断言），补 ZIP 无效**（P-08 归因更正，QA 实跑证明）。三者均属独立的资源/风险评估任务，不在本期 WP 范围。

## 2. pre-existing xfail（1 项）

基线日志中的 `x` 为既有预期失败（xfail），不是本期引入。全量 `-rf` 摘要与基线一致（`3 F + 1 x`）。

## 3. 既有挂起用例（本机环境，非失败、非本期引入）

| 项 | 说明 |
|---|---|
| `tests/unit/test_canvas_import.py::test_import_canvas_from_zap19_with_incomplete_project` | `pytest -v`（timeout 90）输出停在该用例且无 PASSED；全量命令 300s 超时（`exit=124`）时进度约 9%；`--ignore` 隔离后 300s 可推进到 72%，说明套件整体在本机偏慢。该测试文件本期**完全未修改**。 |
| 处置 | 用 `--ignore=tests/unit/test_canvas_import.py` / `--maxfail=3` 交叉复跑取得完整失败统计；如实标注，不删除、不伪装通过。 |

## 4. 本期新增代码是否引入新失败

| 检查 | 结果 |
|---|---|
| `uv run pytest tests/unit/test_*_v2.py tests/contracts -q -rf` | **162 passed / 0 failed** |
| T02 分批 | 39 passed / 0 failed |
| T03 分批 | 27 passed / 0 failed |
| T04 分批 | 46 passed / 0 failed |
| `dotnet test ... -c Release` | 110 passed / 0 failed（首次 1 个新增测试断言写法错误已修正并重跑通过） |
| `npm test -- --reporter=dot` | 393 passed / 0 failed（前端未改动） |

**结论：本期新增代码引入的新失败数 = 0。** 3 个 `F` + 1 个 `x` 与挂起用例全部为 pre-existing，已按 Q-07 隔离标记。

## 5. 禁止事项复核

- ❌ 未删除 `industrial/tia_openness_cli`、`plc_engine/af`、`plc_engine/pcec.py` 任何能力。
- ❌ 未把任何 mock / offline 结果写成 V19 real 通过。
- ❌ 未改写历史 `evidence/*.json` 与 61 份历史 docs 的结论。
- ✅ `xml_package_unverified=true` / M4 未通过 / Greenfield 端到端未闭环口径保持不变。
