# V19 真机全链原始回执目录（当前为空）

G5（Greenfield-only 真实 `.zap19` 归档链）尚未执行，状态 `pending_real_machine`。
本目录**故意为空**：不得放入 mock / offline 产物冒充 V19 real 回执。

主理人/QA 串行调度真机后，应在此归档：
`create-project` 原始回执、`compile-plc` 回执（`error_count=0`）、`save-project` 回执、
`archive-project` 精确 `archivePath` + `sha256`、`retrieve` 的 `reopenOk` 回执、
精确 `artifact_id` 下载校验记录，并在 `docs/v2/03-验收矩阵.md` 中更新证据等级。
