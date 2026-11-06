# EvidenceBundle 归档结构 · 使用说明（WP-10 / Agent I）

> 本目录为 **WP-10 全量验收与证据链** 的模板与台账，**纯新增、不改任何产品代码**。
> 依据：`docs/greenfield/05-parallel-wp2-contract.md` §1/§2/§4/§5/§6、`04-parallel-wp-contract.md` §0；
> `research/PLC_chat_产品开发Plan_v1.0_2026-11-06.md` §2.2 / §7.1 / §7.2 / §7.3 / §9.3；
> 基线报告 v2.1 §9.2 / §9.3 / §13.6 / §13.9 / 附录 B。

## 1. 目录内容

| 文件 | 作用 | 是否真相源 |
|---|---|---|
| `README.md` | 证据包使用说明与诚实口径 | 说明 |
| `rtm.json` | UC-01～UC-19 RTM 追溯矩阵 + F 真机归档事实 + 基线排除 | **是**（编排器与单测读取） |
| `acceptance_template.json` | EvidenceBundle 全量 12 项清单 + 增量 6 字段定义 | **是**（编排器与单测读取） |
| `pending_real_machine.json` | pending 台账累计与清零检查依据 | **是**（编排器读取） |
| `offline_run_*.json`（可选） | `greenfield_acceptance.py --out` 导出的离线运行留痕 | 运行产物 |

## 2. EvidenceBundle 归档结构

归档根目录建议：`evidence/bundles/<project_id>/<spec_version>/`。完整目录布局与逐项说明见
`acceptance_template.json` 的 `directory_layout` 与 `full_artifacts`。

### 2.1 全量（full）模式 12 项清单（Plan §7.2 / 基线报告 §9.3）

`specs/vN.json`、`ir_snapshot`、四视图导出、连线清单、`open_questions` 清零记录、静态门禁结果、
`fidelity_report.json`、结构化编译报告、PCEC 账本、`baseline_manifest.json`、产物哈希、`.zap19` 归档。

### 2.2 增量（incremental）模式必须追加 6 字段（Plan §7.2 + 基线报告 §13.6）

`mode`、`base_spec_version`、`changed_source_ids[]`、`reverse_protection`、`tia_side_drift`、
`ob_number_deviations`。

- `ob_number_deviations` 属**不纳入 1:1 的域**，但**必须留痕、禁止静默**：即使为空数组也要在
  `fidelity_report.json` / 增量 EvidenceBundle 中显式写出，不得省略该字段，也不得据其把 L1/L2 标为通过。
- `tia_side_drift > 0` 时 Action C 在 §13.5 步骤 3 即被阻止（D10，fail-closed）。
- 增量字段缺失任一 → 证据包不完整 → M4 不得签署。

### 2.3 N9 独立性

`fidelity_ok` 与 `compile_ok` 严格独立：`fidelity_report.json` 与结构化编译报告分别归档，
禁止互相替代；warning 单列、不并入成功；`tia_unavailable` 必须显式非 200。

## 3. RTM 状态词（5 种，不得混用）

`pass` / `fail` / `pending_real_machine` / `not_run` / `preexisting_baseline_failure`。

- **不得把离线单测标成 L2/L4 `pass`**；涉真机的 L2/L4 一律 `pending_real_machine`。
- **禁止**以离线单测宣称 `L1∧L2∧L3∧L4` 通过、宣称「编译零错误」、把 `pending` 视为通过。
- 所有真机结论只能引用 `docs/greenfield/06-gate0-report.md` / `research/Gate0_环境与档位实测_2026-11-06.md`
  （Agent F 归档）或真实运行结果，**禁止编造真机编译数字**。

### 3.1 离线单测证据登记口径（Agent N · 2026-11-06）

批次 1/2 已有真实离线单测且实跑通过的 UC，可在 `rtm.json` 中把主状态由 `not_run` 如实登记为 `pass`，
但**必须**同时标注 `evidence_kind: "offline_unit_test"`，并逐 case 附 `offline_evidence`
（单测文件路径 + 用例名 + 真实通过数）、`offline_verified_by`、`caveat`。口径边界：

- 离线 `pass` **仅代表离线单测证据**，不等同真机 L2/L4 通过、不标任何 L 层 `pass`、
  不使 `pending_real_machine.json` 清零（`cleared` 保持 `false`、items 不删）、不使 M4 可签署；
- 真机 `pass` 仍须带 `real_machine_evidence` / `real_machine_facts` / `verified_by` 三件套并指向
  `evidence/uc05_real_machine_report.json`；**两类证据口径严格分离，离线单测不得挂真机证据冒充**；
- 涉 L2/L4 且无真机证据的用例一律不得标 `pass`；
- 逐 UC 复核表见 `docs/greenfield/07-acceptance-matrix.md` §11，台账证据索引见
  `evidence/pending_real_machine.json#agent_n_offline_review`。

## 4. pending 台账与 M4 清零检查

- `pending_real_machine.json` 初始态 `cleared=false`，含 10 项 pending UC。
- 编排器 `--offline` 会从 `rtm.json` 聚合 pending 集合并与台账比对累计计数；
  `--sync-ledger` 可把差异写回；**清零只能由主 agent 在真机证据齐备后执行**。
- **M4 发布门禁在 pending 清零前必须保持未通过**（Plan §6.3 / 契约 05 §1.4 / §6）。

## 5. 已知基线既有失败（排除且不得修复）

`test_af_import.py::test_hr001_real_import_roles_and_freeze` 已在 `main@f9d4a3d` worktree 实证，
**排除且不得修复**。收口命令：

```
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_af_import.py
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q
```

`test_frozen_legacy_files_have_zero_diff()` 必须 PASS；冻结清单 / `legacy_baseline.json` /
`test_greenfield_legacy_guard.py` / sha256 冻结清单一律不碰。

## 6. P0-D 档位结论

**由用户拍板**，本目录文档只写「待拍板 + 推荐结论引用 F 报告」，**不代拍**。
推荐结论与依据见 `docs/greenfield/06-gate0-report.md` §6（坚持 AF Basic 文件夹版）；
拍板前映射层维持「档位无关」。

## 7. 运行编排器

```
cd <R>
./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline
./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline --out evidence/offline_run.json
./.venv/Scripts/python.exe tools/greenfield_acceptance.py --real-machine --workdir C:/Users/vboxuser/AppData/Local/Temp/gf_real_*/副本.ap19
```

- `--offline`：只跑可离线的静态检查（RTM / 证据模板 / 台账结构、L 层聚合、pending 清零检查），
  明确标注 **L2/L4 pending**；九步端到端与六条增量用例仅做步骤编排 + 留复现命令，
  全部 `not_run` / `pending_real_machine`，**绝不连真机、绝不伪造结果**。
- `--real-machine`：**必须**显式指定 `--workdir`，且路径须为 `AppData/Local/Temp/gf_real_*` 临时副本；
  检测到 `PLC_Openness_data` 原始路径即 fail-closed 拒绝。仅在此模式才尝试调用现有 CLI/HTTP，
  调用失败留 `not_run` / `fail` + 复现命令，不伪造。
- 输出结构化 JSON 含 `L1∧L2∧L3∧L4` 复核结论与 **M4 未通过** 判定。

## 8. 合规声明

- 未执行任何 git 操作；未改任何产品代码（`gateway/` / `plc_engine/` / `agents/` / `frontend/` / `industrial/`）；
  未改 `legacy_baseline.json`、`test_greenfield_legacy_guard.py` 及 sha256 冻结清单。
- D12 hard refuse 全程约束：不做在线下载 / online / run-stop / compare-to-PLC、F-block 与 Safety 写入、
  全局库、UI 自动化。
- 本目录为验收框架与模板，**不产出一个真实 EvidenceBundle**；真实证据包由主 agent 收口实测时按
  `acceptance_template.json` 实例化归档。
