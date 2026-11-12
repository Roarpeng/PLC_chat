# V2 统一验收证据目录（结构定义，台账由主理人收口）

本目录只定义结构与本批状态，**不改写历史 `evidence/*.json`**，不代替主理人收口。

| 文件 | 用途 |
|---|---|
| `acceptance_receipt.json` | 整体验收发布回执（G0–G7 签发状态 + 三级证据 + 真机状态） |
| `ac01_matrix.json` | AC-01 六步逐条证据等级映射（由 QA/主理人复核后填充最终真机回执） |
| `raw/` | 真机 V19 全链原始回执目录（**当前为空**：G5 未执行，pending_real_machine） |

**当前状态**：G5 / AC-01 第 1、5、6 步一律 `pending_real_machine`；不得写入「已通过」「交付完成」；
不得把 `mocked` / `offline` 结果升级为 `V19_real`。QA 独立验收报告写 `docs/v2/qa/` 与 `evidence/v2/qa/`，本目录不写。
