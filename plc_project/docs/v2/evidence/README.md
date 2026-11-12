# V2 验收留痕目录说明

本目录保存 T01–T04 每批验收命令的**真实输出**（非手写结论）。

| 目录 | 内容 |
|---|---|
| `T01/v2_targeted_pytest.txt` | `uv run pytest tests/unit/test_*_v2.py tests/contracts -q -rf` → 162 passed |
| `T01/vitest_lead_baseline.txt` | 主理人补跑的前端基线日志只读副本（`backup/pre_v2_20261109/baseline_vitest.log`）→ 23 files / 393 passed / vitest 5.0.4 / 2.27s / `VITEST_EXIT=0`；原历史文件未改动 |
| `T01/vitest_baseline.txt` | 本批独立复跑 `cd frontend && npm test -- --reporter=dot` → 23 files / 393 passed，交叉验证前端基线 0 失败 |
| `T01/g0_probe_stdout.txt` | `uv run python scripts/probe_capability_v2.py --no-db` → 真实 C# status 回执 |
| `T01/ir_roundtrip_semantic_hash.txt` | IR roundtrip / UI layout 排除 / 二次生成确定性 / Patch revision |
| `T02/t02_pytest.txt` | T02 契约 + 负例 → 39 passed |
| `T02/dotnet_test.txt` | `dotnet test ... -c Release` → 110 passed / 0 failed (net481) |
| `T03/t03_pytest.txt` | DriverCatalog / FSM / validation → 27 passed |
| `T04/t04_pytest.txt` | GuardAST / 图算法 / Trace / SCL / SourceMap → 46 passed |
| `T05/vitest.txt` / `build.txt` | 前端 413 passed / `npm run build` EXIT=0 |
| `T05/vitest_lead_baseline.txt` | 主理人补跑前端基线（393 passed / 2.27s）只读副本 |
| `T05/cpu_selection_stdout.txt` / `cpu_verification_pytest.txt` | U-02 CPU 选型回执 / CreateWithItem 前置验证 8 passed |
| `T06/t06_pytest.txt` | Brownfield 接口 + Schema + 4 类负例 → 14 passed |
| `T07/t07_pytest.txt` | 15 类故障注入 / 幂等 / 恢复 → 18 passed |
| `T08/all_v2_pytest.txt` | T01–T08 全量 v2 → **212 passed / 0 failed** |
| `T08/qa_independent_pytest.txt` | QA 独立验收 `tests/qa_v2/` → **36 passed**（6 个源码缺陷已修） |
| `T08/vitest.txt` / `build.txt` / `dotnet_test.txt` | 413 passed / build EXIT=0 / dotnet 110 passed |
| `T08/full_pytest_maxfail3.txt` | 全量交叉复跑：`3 failed, 118 passed`（3 个 pre-existing F，名单与基线一致） |

结构化批次回执与 schema 见 `evidence/v2/batch_receipt.schema.json` 及
`evidence/v2/T01..T04/batch_receipt.json`（第 1 批）；第 2 批回执由主理人统一收口，
工程师不自行收口台账。G0 原始探测回执见 `evidence/v2/T01/g0_probe.json`、
`evidence/v2/T01/capability_probe.json`；CPU 选型回执见 `evidence/v2/T01/cpu_selection.json`；
统一验收结构见 `evidence/v2/acceptance/`。

QA 独立验收报告写 `docs/v2/qa/` 与 `evidence/v2/qa/`，工程师不写这两个目录、不写
`docs/v2/04-QA验收报告.md`，避免并发覆盖。

**口径**：历史 `evidence/*.json` 一律不改写；台账由主理人收口。
所有「编译零错误 / 归档完成 / 交付完成」在本批均无 V19 real 全链证据，
按 `pending_real_machine` 标注；`V19_real` 仅用于 T01 的只读 status 探测回执。

真机全链（`scripts/tia_delivery_chain_v2.py --real`）由主理人/QA 串行调度，
本批默认 dry-run，输出固定为 `pending_real_machine`。
