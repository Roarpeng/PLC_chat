# V2 验收留痕目录说明

本目录保存 T01–T04 每批验收命令的**真实输出**（非手写结论）。

| 目录 | 内容 |
|---|---|
| `T01/v2_targeted_pytest.txt` | `uv run pytest tests/unit/test_*_v2.py tests/contracts -q -rf` → 162 passed |
| `T01/vitest_baseline.txt` | `cd frontend && npm test -- --reporter=dot` → 23 files / 393 passed |
| `T01/g0_probe_stdout.txt` | `uv run python scripts/probe_capability_v2.py --no-db` → 真实 C# status 回执 |
| `T01/ir_roundtrip_semantic_hash.txt` | IR roundtrip / UI layout 排除 / 二次生成确定性 / Patch revision |
| `T02/t02_pytest.txt` | T02 契约 + 负例 → 39 passed |
| `T02/dotnet_test.txt` | `dotnet test ... -c Release` → 110 passed / 0 failed (net481) |
| `T03/t03_pytest.txt` | DriverCatalog / FSM / validation → 27 passed |
| `T04/t04_pytest.txt` | GuardAST / 图算法 / Trace / SCL / SourceMap → 46 passed |

结构化批次回执与 schema 见 `evidence/v2/batch_receipt.schema.json` 及
`evidence/v2/T01..T04/batch_receipt.json`；G0 原始探测回执见
`evidence/v2/T01/g0_probe.json` 与 `evidence/v2/T01/capability_probe.json`。

**口径**：历史 `evidence/*.json` 一律不改写；台账由主理人收口。
所有「编译零错误 / 归档完成 / 交付完成」在本批均无 V19 real 全链证据，
按 `pending_real_machine` 标注；`V19_real` 仅用于 T01 的只读 status 探测回执。

真机全链（`scripts/tia_delivery_chain_v2.py --real`）由主理人/QA 串行调度，
本批默认 dry-run，输出固定为 `pending_real_machine`。
