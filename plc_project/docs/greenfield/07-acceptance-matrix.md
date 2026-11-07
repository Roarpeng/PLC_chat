# WP-10 全量验收矩阵与证据链（Agent I）

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 2 · Agent I · WP-10 全量验收与证据链 |
| 分支 / 基线 | `dev/greenfield-wp` / `9f7186b`（**未执行任何 git 操作**） |
| 日期 | 2026-11-06 |
| 性质 | **纯新增文件，不改任何产品代码**（`gateway/`、`plc_engine/`、`agents/`、`frontend/`、`industrial/` 一律未碰） |
| 独占新增 | `tools/greenfield_acceptance.py`、`tests/unit/test_greenfield_acceptance.py`、`docs/greenfield/07-acceptance-matrix.md`、`docs/greenfield/09-m4-review.md`、`evidence/` 目录模板与台账 |
| 契约 | `05-parallel-wp2-contract.md` §1/§2/§4/§5/§6；`04-parallel-wp-contract.md` §0 |
| 依据 | Plan v1.0 §2.2 / §3 M4 / §7.1 / §7.2 / §7.3 / §9.3；基线报告 v2.1 §9.2 / §9.3 / §13.6 / §13.9 / 附录 B |
| 真机事实来源 | `docs/greenfield/06-gate0-report.md`、`research/Gate0_环境与档位实测_2026-11-06.md`（**Agent F 归档，原样引用，不推断、不改写数字**） |
| 当前结论 | **`L1∧L2∧L3∧L4` 未全绿；`M4 未通过`，不可签署** |

---

## 0. 文档定位

本文是 **收口实测之前的验收框架 + 事实录入**：把 UC-01～UC-19 逐条映射到
「需求/决策 → 工作包 → 闸门 → 证据产物 → 当前状态」，定义 EvidenceBundle 归档结构，
汇总批次 1 + 批次 2 的未达成项。**真正的逐条勾选与 M4 签署由主 agent 收口实测后完成**。

> 真机结论只能引用 Agent F 归档或真实运行结果；**禁止编造真机编译数字**、禁止以离线单测
> 宣称 `L2/L4` 通过或「编译零错误」、禁止把 `pending` 视为通过。

---

## 1. 状态词与诚实口径

| 状态 | 含义 |
|---|---|
| `pass` | 用例完整通过且附真实证据；**离线单测不得把 L2/L4 标为本状态** |
| `fail` | 用例明确失败，附失败码与复现命令 |
| `pending_real_machine` | 需真机实测，或真机关键部分未闭环 / 待复测；**M4 在清零前保持未通过** |
| `not_run` | 本 Agent 仅编排步骤并留复现命令，未独立执行 / 核验；由主 agent 收口全量验收时核验 |
| `preexisting_baseline_failure` | 基线既有失败，已在 `main@f9d4a3d` worktree 实证，**排除且不得修复** |

**硬约束**（契约 05 §1 / §6、04 契约 §0）：

1. 禁止以离线单测宣称 `L1∧L2∧L3∧L4` 通过、宣称「编译零错误」、把 `pending` 视为通过；
2. **N9**：`fidelity_ok` 与 `compile_ok` 严格独立，禁止互相替代；warning 单列不并入成功；
3. **P0-D 档位结论由用户拍板**，Agent 只给「对照表 + 实测 + 推荐 + 依据」，不代拍；拍板前映射层维持「档位无关」；
4. **D12 hard refuse** 全程约束：不做在线下载 / online / run-stop / compare-to-PLC、F-block 与 Safety 写入、全局库、UI 自动化；
5. 真机只在 `AppData/Local/Temp/gf_real_*` 临时副本上操作，原始 `.ap19/.zap19` 仅 `cp` 读取，从不打开 / 写回；
6. `fidelity_ok=false` / `tia_side_drift>0` / `ExclusiveAccess` 失败 / 差异清单未确认，一律 fail-closed。

---

## 2. UC-01～UC-19 RTM 追溯矩阵

> 完整结构化数据见 `evidence/rtm.json`（编排器与单测的真相源）。下表为其人读版。
> 「工作包/归属」列按契约 05 §4 的 UC 归属表填写。

| UC | 场景 | 需求/决策 | 工作包 / 归属 | 闸门 | 层 | 证据产物 | 状态 | 真机结论 / 备注 |
|---|---|---|---|---|---|---|---|---|
| UC-01 | 档位兼容性最小样例导入编译 | D5 / Q7 | WP-00 · **F（真机）→ 用户拍板** | G0 | 前置 | 档位实测报告、四件套 JSON、V19 导入编译真实返回 | `pending_real_machine` | F 真机：四件套 **4/4 pass**；**文件夹版 1 Unit + 2 EM 分组编译 `errorCount=0`**（真实）。但 P0-D 拍板待用户、端到端全链未跑、Gate-0 = conditional-go，不计入 M4 通过 |
| UC-02 | 编译判定口径（error_count 与 warning 分离） | P0-A | WP-01 · C → 收口核验 | G1 | L2 | 结构化编译报告、compile_diagnostics 单测 | `pending_real_machine` | L2 涉真机，离线模式明确标注 pending；离线判定逻辑由 WP-01 交付，收口核验前不标 pass |
| UC-03 | TIA 不可用返回显式非成功且非 HTTP 200 | P0-A | WP-01 · C → 收口核验 | G1 | L2 | 接口响应记录、GF_TIA_UNAVAILABLE 映射记录 | `pending_real_machine` | 禁止把 `tia_unavailable` 包装成 `ok=true` / 200 静默成功；建议 `_error_status` 显式 503（04 契约 §7，待收口接线） |
| UC-04 | K1 探针消 `xml_package_unverified` | P0-B | WP-00 · **F（真机）→ G 接线** | G1 | L2 | 导入日志、PCEC、K1 复测真实返回 | `pending_real_machine` | **K1 探针实测失败**：自产 OB XML 导入返回 `openness_error`（culture `en-US` 不存在 + `StructuredText/v4` namespace 不正确），`exit_code=4`；`xml_package_unverified` 保持 `True`。按 F 正式口径 UC-04 标 pending（K1 待 G 修复模板后复测），失败事实用 `fail` 子检查留痕 |
| UC-05 | 三次增量不重载（3× `error_count==0` + PCEC 3 条 + 句柄复用） | D14 / D9 | WP-02 · **G（真机地基）+ 收口实测** | G1 | L4 地基 | P0-G 验收报告、PCEC 3 条、句柄复用记录 | `pending_real_machine` | **真机三次增量未实测**；P0-G 验收不等于 L4 通过 |
| UC-06 | `spec_hash` 全域 + 绕过 patch 写入测试失败 | D4 | WP-03 → 收口核验 | G1 | L3 | 单测报告、spec_hash 全域校验记录 | `not_run` | 纯离线可覆盖，本 Agent 未独立核验 |
| UC-07 | 从 `specs/vN.json` 重启重建画布（含拓扑） | D4 / P1-F | WP-03 + WP-05 → 收口核验 | G1/G2 | L3 | 重启恢复记录、specs/vN.json | `not_run` | 离线持久化可覆盖，收口核验前标 not_run |
| UC-08 | 正向覆盖 `coverage==1.0` + `coverage_matrix` | D1 | WP-05 → 收口核验 | G2 | L1 | fidelity_report.json、coverage_matrix | `not_run` | 纯离线校验器可覆盖；N9：不得据此宣称编译通过 |
| UC-09 | 负例·漏映射 `coverage<1` + `unmapped_spec_objects` | D1 | WP-05 → 收口核验 | G2/G3 | L1 | 负例报告 | `not_run` | 收口核验前标 not_run |
| UC-10 | 负例·臆造 `orphan==1` + `fidelity_ok=false` | D1 | WP-05 → 收口核验 | G2/G3 | L1 | 负例报告、orphan_blocks | `not_run` | 收口核验前标 not_run |
| UC-11 | 基线漂移 `drift!=0` 报警 | D2 | WP-07 → 收口核验 | G2 | L1 | baseline_manifest.json、基线校验记录 | `not_run` | 收口核验前标 not_run |
| UC-12 | 反向保护 D10：TIA 侧改无关块 → 第 4 次增量被阻止 | D10 | WP-04 + WP-06 · **H + 收口实测** | G2/G3 | L4 | 阻止记录、reverse_protection / tia_side_drift 报告 | `pending_real_machine` | **D11/D10 真机约束未验证**；`allowed=false` / `tia_side_drift>0` 必须 fail-closed 阻止，禁止先覆盖再提示 |
| UC-13 | 回滚演练（失败导入回到调用前状态） | D10 / RK12 | WP-06 · **H + 收口实测** | G2 | L4 | 回滚记录、写前备份 sha256 | `pending_real_machine` | 失败导入后回滚真机演练未实测 |
| UC-14 | 可复现：同输入重跑产物哈希一致 | L3 | WP-05 / WP-07 → 收口核验 | G2/G3 | L3 | reproducibility 记录、产物哈希 | `not_run` | 收口核验前标 not_run |
| UC-15 | §9.2 九步端到端（含步骤 7 Action B 真机编译） | D3 / D6 / D7 | **WP-10 · I（编排）+ 收口实测** | G3 | L1-L3（含 L2 真机） | 端到端验收报告、.zap19、fidelity_report、结构化编译报告 | `pending_real_machine` | F 归档明确：**未跑 Greenfield 生成链全链**（自然语言→冻结→生成→导入→编译）；本 Agent 只做九步步骤编排与复现命令留痕，不代跑 |
| UC-16 | §13.9 六条增量用例（全程 `fidelity_ok` 且 `tia_side_drift==0`） | D3 / D9 / D11 | **WP-10 · I（编排）+ 收口实测** | G3 | L4 | 增量 fidelity_report、PCEC、增量 EvidenceBundle | `pending_real_machine` | **真机三次增量未实测**；增量必须追加 6 个字段（见 §6） |
| UC-17 | `fidelity_ok=false` 时 Action B 被拒绝并给出原因 | D3 / N9 | WP-06 · **H** → 收口核验 | G3 | L1 | 拒绝记录、fidelity_report.json | `not_run` | B 以前者 `fidelity_ok==true` 为前提；纯前置校验可离线覆盖 |
| UC-18 | 编译错误回喂：注入 SCL 语法错误 → 自愈 → 复编译 `error=0` | P1-I | WP-08 → 收口实测 | G3 | L2 | PCEC 账本、结构化编译报告 | `pending_real_machine` | 涉真机编译，离线模式明确标注 pending |
| UC-19 | 确认前零副作用：四计数器恒 0 | D11 | WP-06 · **H** → 收口核验 | G3 | 硬门禁 | 计数器快照、confirm-diff 响应 | `not_run` | `confirmed!=true` 时 `ops/disk_writes/writebacks/generations` 恒 0（服务端强制 fail-closed） |

### 2.1 状态计数（UC 主状态）

| 状态 | 计数 | UC |
|---|---|---|
| `pass` | **0** | — |
| `fail` | **0** | UC-04 的 K1 探针**子检查**为 `fail`（按 F 口径整体仍 pending 待复测） |
| `pending_real_machine` | **10** | UC-01, 02, 03, 04, 05, 12, 13, 15, 16, 18 |
| `not_run` | **9** | UC-06, 07, 08, 09, 10, 11, 14, 17, 19 |
| `preexisting_baseline_failure` | **1**（排除项，非 UC） | `test_af_import.py::test_hr001_real_import_roles_and_freeze` |

> **`pass=0` 是诚实口径要求，不是验收缺漏**：契约 05 §1.4 / §6 明确「不得把离线单测标成 L2/L4 pass」、
> 「不得把 pending 视为通过」。F 真机归档的 `pass`/`fail` 事实集中在 `evidence/rtm.json` 的
> `gate0_facts` 如实录入；UC 逐条勾选要等主 agent 收口实测。

---

## 3. Agent F 真机归档结论（如实录入，不得与之矛盾）

| 事实 | 结论 | 出处 |
|---|---|---|
| 环境四件套 | **4/4 pass**（STEP 7 许可由临时副本上真实 `compile-plc` 编译验证有效） | 06 §1 / 归档 §4 |
| UC-01 文件夹版最小样例 | `create-block-group` 1U+2EM 3× `ok:true/saved:true`，随后 `compile-plc` → `errorCount=0 / warningCount=0 / state=Success`（**真实 CLI 返回**） | 06 §2.3 / 归档 §5.3 |
| UC-01 OB 编号真实先例改号 | 导入成功（`number=123` 生效），但编译 **`errorCount=30 / state=Error`**（真实失败：真实先例 XML 引用了本项目不存在的 `FB1000_StdSignal`/`DB1000_StdSignal`） | 06 §2.3 / 归档 §5.4 |
| UC-04 K1 探针 | **失败**：`openness_error`（culture `en-US` + `StructuredText/v4` namespace），`exit_code=4`；`xml_package_unverified` 保持 `True` | 06 §3 / 归档 §6 |
| Gate-0 判定 | **`conditional-go`**（环境/事实/对照表/真实结果就绪，但 P0-D 拍板待用户 + K1 失败，不满足完整 `go`） | 06 §5 |
| 软件单元版 | `--unit` 回退普通块分组（`path="Unit_01/OB123Unit01"`），本机 CPU 不具备软件单元能力；完整导入编译未干净跑通 | 06 §2.2 / 归档 §5.5 |
| **P0-D 档位结论** | **待用户拍板（Agent 不代拍）**；推荐结论「坚持 AF Basic 文件夹版」及依据见 06 §6；拍板前映射层维持「档位无关」 | 06 §6 / 契约 05 §1.3 |

> **诚实口径**：`errorCount=0` 仅对应 CanvasE2E 基线副本与「仅建分组」副本，**不是**「UC-01 端到端
> 样例零错误」；`errorCount=30` 是真实编译失败。二者均不可混为「编译零错误」，也不得据 F 的 G0
> 准入实测宣称 `L2/L4` 通过或 `L1∧L2∧L3∧L4` 达成。端到端全链（UC-15）属 WP-10 / M4，本轮未跑。

---

## 4. `L1∧L2∧L3∧L4` 复核口径

| 层 | 判定式 | 绑定 UC | 当前复核结论 |
|---|---|---|---|
| L1 逻辑等价 | `coverage==1.0 ∧ orphan==0 ∧ drift==0 ∧ tia_side_drift==0` | 08, 09, 10, 11, 15, 17, 19 | 未通过（`not_run` / 端到端 pending） |
| L2 可编译 | `compile_error==0` ∧ 四层静态门禁通过；warning 单列；`tia_unavailable` 显式失败 | 02, 03, 04, 15, 18 | **未通过（全部 `pending_real_machine`）** |
| L3 可复现 | 同 `spec_hash` 两次产物哈希一致 + 重启恢复 FROZEN vN | 06, 07, 14, 15 | 未通过（`not_run`） |
| L4 增量可迭代 | 同会话连续 ≥3 次增量，每次 `fidelity_ok` ∧ `error_count==0` ∧ `tia_side_drift==0`，项目未关闭/未重载/未新建 | 05, 12, 13, 15, 16 | **未通过（全部 `pending_real_machine`）** |

**复核结论：`L1∧L2∧L3∧L4` 未全绿 → `M4 未通过`。** G1 的 P0-G 不等于 L4 通过；完整 L4 还需
§13.9 六条用例的 `fidelity_ok` 与 `tia_side_drift==0`。

---

## 5. EvidenceBundle 归档结构（定义 + 使用说明）

完整机器可读定义见 `evidence/acceptance_template.json`；使用说明见 `evidence/README.md`。
归档根目录建议 `evidence/bundles/<project_id>/<spec_version>/`。

### 5.1 全量（full）模式 12 项清单（Plan §7.2 / 基线报告 §9.3）

`specs/vN.json`、`ir_snapshot`、四视图导出、连线清单、`open_questions` 清零记录、静态门禁结果、
`fidelity_report.json`、结构化编译报告、PCEC 账本、`baseline_manifest.json`、产物哈希、`.zap19` 归档。

### 5.2 增量（incremental）模式必须追加 6 字段（Plan §7.2 + 基线报告 §13.6）

| 字段 | 说明 |
|---|---|
| `mode` | `full` / `incremental` |
| `base_spec_version` | 本次增量所基于的规格版本 |
| `changed_source_ids[]` | 变更块 `source_id` 清单（来自 `/diff`） |
| `reverse_protection` | 反向保护裁决（`allowed=false` 必须 fail-closed 阻止写入，D10） |
| `tia_side_drift` | 第 4 指标，要求 0；`>0` 时 Action C 在 §13.5 步骤 3 被阻止 |
| `ob_number_deviations` | **OB 编号偏差留痕：属不纳入 1:1 的域，但必须留痕、禁止静默**；即使为空数组也要显式写出，不得省略，不参与 `fidelity_ok` 判定 |

- 增量字段缺任一 → 证据包不完整 → **M4 不得签署**；
- **N9**：`fidelity_report.json` 与结构化编译报告分别归档，`fidelity_ok` 与 `compile_ok` 禁止互相替代；
- 结构化编译报告只能来自真实 CLI / SessionServer HTTP 返回（含 `error_count` / `warnings` / `blocks` /
  `elapsed_ms` / `tia_version` / `project_path`），**禁止 mock / 离线推断冒充**。

### 5.3 使用流程

1. 冻结 vN 后按 `acceptance_template.json` 实例化一个 bundle 目录；
2. Action A（离线可校验）产出 `fidelity_report.json` + EvidenceBundle，不改 TIA；
3. Action B（真机，`fidelity_ok==true` 为前提）写入博途并产出结构化编译报告 + `.zap19`；
4. Action C（真机增量）追加 6 个增量字段 + 增量 `fidelity_report` + PCEC 账本；
5. 计算 `integrity.sha256`，供 L3 复现比对；
6. 主 agent 收口实测时逐条勾 UC，pending 清零后由用户签署 M4（见 `09-m4-review.md`）。

---

## 6. 编排器使用说明（`tools/greenfield_acceptance.py`）

```
cd <R>
./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline
./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline --out evidence/offline_run.json
./.venv/Scripts/python.exe tools/greenfield_acceptance.py --real-machine --workdir C:/.../Temp/gf_real_*/副本.ap19
```

- `--offline`：只跑可离线的静态检查（RTM / 证据模板 / 台账结构、L 层聚合、pending 清零检查），
  明确标注 **L2/L4 = `pending_real_machine`**；九步端到端 + 六条增量用例共 15 步仅做步骤编排，
  全部 `not_run` / `pending_real_machine` + 复现命令，**绝不连真机、绝不伪造结果**。
- `--real-machine`：**必须显式指定 `--workdir`**，且只允许 `AppData/Local/Temp/gf_real_*` 临时副本；
  检测到 `PLC_Openness_data` 原始路径即 fail-closed 拒绝。仅做护栏校验与一次真实 `status` 探针；
  **产品链逐条实测由主 agent 收口执行**，本工具不代跑、不伪造编译/导入结果。
- 输出结构化 JSON：`L1∧L2∧L3∧L4` 复核结论 + `M4 未通过` 判定 + pending 累计 + 步骤留痕。
- `--sync-ledger` 可把 RTM 的 pending 集合幂等累计进台账；**清零只能由主 agent 在真机证据齐备后执行**。

---

## 7. 已知基线既有失败（明确声明）

> **已知基线既有失败 `test_af_import.py::test_hr001_real_import_roles_and_freeze` 已在
> `main@f9d4a3d` worktree 实证，排除且不得修复。**

收口验收命令（契约 05 §5）：

```
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_af_import.py
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q
cd <R>/frontend && npm run test && npm run build
```

`test_frozen_legacy_files_have_zero_diff()` **必须 PASS**。禁止改 `legacy_baseline.json`、
`test_greenfield_legacy_guard.py` 及 sha256 冻结清单 41 个文件；本 Agent 未触碰上述任何文件。

---

## 8. 变更记录 / 遗留清单（批次 1 + 批次 2，可勾选）

> 以下均为**未达成 / 待收口**项，供主 agent 逐条核验勾选。**不代用户拍板、不代跑真机。**

### 8.1 决策与闸门

- [ ] **P0-D AF 档位结论待用户拍板**（唯一可能改变技术路线的未决项）；本 Agent 只写「待拍板 + 推荐结论引用 06-gate0-report.md §6」，**不代拍**；拍板前映射层维持「档位无关」
- [ ] Gate-0 判定为 **`conditional-go`**，未到完整 `go`（拍板硬缺 + K1 失败）
- [ ] 解除 conditional-go 的前置：用户拍板 + UC-04 K1 复测通过 + 涉真机项收口实测

### 8.2 真机实测（均 `pending_real_machine`）

- [ ] **UC-04 K1 未通过**：自产 OB XML 导入失败（`openness_error`：culture `en-US` / `StructuredText-v4` namespace）；`xml_package_unverified` 保持 `True`；修复模板属 Agent G，复测在 V19 真机
- [ ] **真机三次增量未实测**（UC-05 P0-G 地基 / UC-16 六条增量）：`/open` 一次 + 3× 覆盖 + 3× `error_count==0` + PCEC 3 条 + 句柄复用 + 不重载
- [ ] **D11 差异清单级显式确认 / D10 反向保护真机约束未验证**（UC-12 / UC-19）：第 4 次增量阻止、确认前零副作用计数器恒 0
- [ ] UC-13 失败导入后回滚演练真机未实测
- [ ] **UC-15 §9.2 九步端到端未跑**（F 归档明确未跑 Greenfield 生成链全链）；步骤 7 Action B 真机编译零错误待收口
- [ ] UC-18 编译错误回喂自愈 + 复编译 `error=0` 涉真机，未实测
- [ ] UC-02 / UC-03 编译判定与 `tia_unavailable` 显式失败口径待真机 / 接口层核验
- [ ] 软件单元版「完整导入编译」未在本机干净跑通（受 OB 模板阻断）
- [ ] 本机 CPU 具体型号未由实验直接读取（由 `--unit` 回退 + 源码约束推断为经典 S7-1200 类）
- [ ] `SW.PlcBlockGroup XML` 可导入性仍未确证（`folders.json` 非 SimaticML 导入对象）
- [ ] Q7 为最小核验包，未重新联网复核；Eigen 生成物具体档位/版本、ueet 公式官方确证属来源不足

### 8.3 收口接线 / 口径

- [ ] **三动作端点 `/action-a` `/action-b` `/action-c`**（契约 05 §3.2，Agent H 所有）：当前工作树 `gateway/app/routers/greenfield.py` 中未见该组路由（现有为 `/generate`、`/deliver-tia`、`/download-package`、`/diff`、`/confirm-diff` 等）；需主 agent 收口时核验是否已按契约接线
- [ ] 04 契约 §7 遗留：`_error_status` 建议把 `GF_TIA_UNAVAILABLE` / `GF_TIA_EXEC_ERROR` 显式映射 **503**；`/deliver-tia` docstring 的「HTTP 200，ZIP 交付不受影响」需改显式失败口径
- [ ] 04 契约 §7 遗留：前端编译门禁条 / `CompileDrawer` 文案需随 P0-A「warning 单列、不并入成功」口径同步
- [ ] 基线报告 §4.8 正文措辞「两动作 → 三动作」待整理版本同步改写（已在 §13.5 声明扩展）
- [ ] Attach 备选路径：保留不启用（仅当 P0-G 证明后台实例不可行时评估）
- [ ] F13 Monaco 只读审阅器未安装（`package.json` 无 `monaco`），按 DEP-08 走「纯文本 + 关键字高亮」降级，禁止擅自新增第三方依赖
- [ ] F16–F20 代码实施准入未启动（基线报告 §13.11：需用户另行拍板）
- [ ] 前端 `npm run test` / `npm run build` 零 TS 错误待收口统一执行

### 8.4 验收与证据链

- [ ] **`L1∧L2∧L3∧L4` 未全绿；`M4 未通过`，不可签署**
- [ ] `evidence/pending_real_machine.json` 台账 10 项未清零（`cleared=false`）；清零前 M4 必须保持未通过
- [ ] 真实 EvidenceBundle 尚未实例化归档（本批次只交付模板与台账）
- [ ] `test_frozen_legacy_files_have_zero_diff()` 收口时必须 PASS（基线既有失败按 §7 排除且不得修复）

---

## 9. 合规声明

- 未执行任何 git 操作；未改任何产品代码 / `legacy_baseline.json` / `test_greenfield_legacy_guard.py` /
  sha256 冻结清单 41 个文件 / C# 源码 / `tia_delivery.py`。
- 真机结论只引用 Agent F 归档或真实运行结果；未以 mock / 离线单测宣称 `L2/L4` 通过或「编译零错误」；
  未把 `tia_unavailable` 说成成功；未把 `pending` 视为通过。
- **P0-D 档位结论待用户拍板，本 Agent 未代拍。**
- D12 hard refuse 全程约束；N9 `fidelity_ok` 与 `compile_ok` 严格独立。
- 无绝对日期 / 人力排期、无编造数据；编译数字均标注来源与限定条件。

---

## 10. 真机实测补充（批次 2 · Agent M · 2026-11-06 收口实测）

> 本节由 **Agent M · V19 真机全量验收** 追加。完整报告见
> `docs/greenfield/10-real-machine-acceptance.md`，结构化真机报告（唯一数字真相源）见
> `evidence/uc05_real_machine_report.json`，复现脚本 `tools/run_uc05_real_machine.py`。
> **本节真机数字全部来自 TIA V19 `serve` 常驻会话的真实 HTTP / CLI 原始返回，非 mock / 非离线推断。**

### 10.1 本文 §2.1 状态计数的更新

本文 §2 / §2.1 的表格为**收口实测前**框架（`pass=0`、`pending_real_machine=10`）。本次收口实测后，
`evidence/rtm.json` 的 5 个 UC 主状态按下表更新
（`summary.by_status`: `pass=5 / pending_real_machine=5 / not_run=9 / fail=0`）：

| UC | 原状态 | 新状态 | 真机证据 |
|---|---|---|---|
| UC-02 | `pending_real_machine` | `pass` | 3× 真实 `/compile-plc` `errorCount=0`，`error_count` 与 `warnings=[]` 分离 |
| UC-03 | `pending_real_machine` | `pass` | serve 未启动探针：`available=false` / `GF_TIA_UNAVAILABLE` / `http_status=503` |
| UC-05 | `pending_real_machine` | `pass` | `/open=1` + 3× 增量 + 3× `errorCount=0` + PCEC 3 条 + 句柄复用 + 未重载 |
| UC-12 | `pending_real_machine` | `pass` | `allowed=false` / `tia_side_drift=1`，第 4 次增量被阻止（未写入） |
| UC-13 | `pending_real_machine` | `pass` | 失败导入 `openness_error`、项目 sha256 前后一致、备份恢复哈希一致 |

其余 UC 状态**一律未动**；`gate0_facts`（F 归档事实）原样保留。`evidence/pending_real_machine.json`
**保持 `cleared=false`、10 条 items 未删**（仅补 `agent_m_real_machine` 证据索引）：
**UC 主状态 pass ≠ 台账清零 ≠ L 层通过 ≠ M4 可签署**。

### 10.2 六项真机结果（逐次编译零错误）

| 用例 | 真实编译结果 | 判定 |
|---|---|---|
| UC-05 主（G `run_incremental_writebacks` / `/fast-writeback`） | 3× `state=Success / errorCount=0 / warningCount=0`；`/open=1`；PCEC `chg-9755507b46b1` / `chg-fc2cc2c59d12` / `chg-01d81eb59d27`；`session_handle` 复用 | pass（P0-G 地基） |
| UC-05 等价（K 修复的 3 个空网络 OB XML 变体 / `/import-xml`） | 3× `import.ok=true` + 3× `state=Success / errorCount=0 / warningCount=0` | pass（等价替代） |
| UC-12 | `check_reverse_guard`: `allowed=false / tia_side_drift=1 / blocked=[OB502_Unrelated]`；第 4 次不写入；阻止后编译 0/0 | pass |
| UC-13 | `openness_error`（culture `en-US`）；`.ap19` sha256 前后一致；编译 0/0；备份恢复 sha256 一致 | pass |
| UC-02 | 3× 真实 `errorCount=0 / warningCount=0`；`compile_diagnostics` `error_count=0 / warnings=[] / compile_ok=true` | pass（口径） |
| UC-03 | `session_status.available=false`；`open_project` `ok=false / GF_TIA_UNAVAILABLE / http_status=503` | pass（探针） |

> 诚实留痕：C# `/fast-writeback` 三次原始返回 `writtenBlockCount=0 / generatedNames=[]`
> （`compileScope=incremental_blocks`）未掩盖；UC-05 的 `spec_hash` 为等价输入内容哈希，
> **非 Greenfield 真实 `specs/vN.json spec_hash`**；UC-02 无原生含 warning 真机样本（用产品纯函数验证判定口径）；
> UC-12 判定为产品纯函数；UC-13 备份为文件系统级 `.ap19` 快照（未做 `.zap19` 归档恢复，D12 边界外）。

### 10.3 `L1∧L2∧L3∧L4` 复核与 M4（本次结论）

| 层 | 判定 | 依据 |
|---|---|---|
| L1 | **pending** | `coverage/orphan/drift` 离线校验与 UC-15 端到端未跑 |
| L2 | **pending** | 已有 6 次真实编译 0/0 与 UC-02/03 口径证据，但四层静态门禁全绿、UC-04/UC-18/UC-15 未闭环；G 编排返回 `l2_status=pending_real_machine` |
| L3 | **pending** | 同 `spec_hash` 两次产物哈希一致 + 重启恢复 FROZEN vN 未跑 |
| L4 | **pending** | UC-05 地基 + UC-12/13 已有真机结果，但 §13.9 六条的 `fidelity_ok` / `tia_side_drift==0`、UC-16 增量 EvidenceBundle 未闭环；G1 的 P0-G ≠ L4 |

> **`L1∧L2∧L3∧L4` 未全绿 → `M4 未通过 / 不可签署`**（`pending` 台账 `cleared=false`、items 未删、
> EvidenceBundle 未完整归档、P0-D 待拍板）。

### 10.4 `xml_package_unverified` 判断 / P0-D

- **`xml_package_unverified` 本轮仍不可消除，保持 `True`**：K 修复 + 本次 M 已双重真机证实「自产**空网络** OB XML 可导入并编译 0/0」，
  但 `folders.json` / `SW.PlcBlockGroup XML` 未测、Call 网络 OB（K caseB `errorCount=2`）与完整 AF 工程包联合导入编译未验证、
  UC-15 全链未跑、M4 门禁未过。UC-04 主状态**保持 `pending_real_machine`**（其他 UC 状态不动）。
- **P0-D 档位结论仍待用户拍板**（本 Agent 不代拍；拍板前映射层维持「档位无关」）；本次实测与档位正交，未推进该结论。

### 10.5 `greenfield_acceptance.py --real-machine`（任务 7）

已跑（`exit=0`）：`workdir_check.allowed=true`；`probe` 真实 `status` → `tiaVersion=V19 / opennessAvailable=true`；
`m4.m4_pass=false`、`pending.count=10`（该次运行在 RTM 状态更新**之前**）。该工具只做护栏 + 一次 status 探针，
**未替代逐条真机实测**。RTM 更新后另重跑 `--offline` 复核：`pass=5 / pending=5 / cleared=False`、
`L1∧L2∧L3∧L4 未全绿`、`M4 未通过`。复现命令见 `10-real-machine-acceptance.md` §11。

### 10.6 本次新增的已知遗留

- **状态迁移导致 `tests/unit/test_greenfield_acceptance.py` 3 个「收口前护栏」断言失败**
  （`test_rtm_status_counts_and_no_fake_pass` 的 `assert 5 == 0`、`test_pending_ledger_matches_rtm` /
  `test_offline_full_report_m4_not_pass` 的 `assert 5 == 10`；`3 failed, 19 passed`）。
  该单测锁定收口前 `pass=0 / pending=10`，**需主 agent 在台账清零 / M4 收口阶段同步**；
  本 Agent 未改该单测（不在独占可写清单），未改任何产品代码 / 冻结清单。
- UC-15 / UC-16 / UC-18 / UC-19、L1/L3 离线链、H 的 `/action-a/b/c` 接线、`_error_status` 显式 503 接线、
  Gate-0 `conditional-go`（未到完整 `go`）等仍未闭环；完整清单见 `10-real-machine-acceptance.md` §12。

### 10.7 安全与诚实口径

真机只在 `Temp/gf_real_m_20261106/` 临时副本上操作（源仅 `cp` 读取，原始 `.ap19/.zap19` 从未打开/写回）；
5 个 `serve` 会话全部 `POST /close` + 停止并复查端口（`leftover_process=false`）；一次性调用
`timeout -k 5 180`、整体脚本 `timeout -k 5 900`；D12 hard refuse、N9 严格分离全程约束；
未执行 git、未改产品代码 / C# 源码 / 冻结清单；**未以 mock 宣称 L2/L4 通过或编译零错误**。

---

## 11. 离线证据复核（批次 2 · Agent N · 2026-11-06）

> 本节由 **Agent N · 离线用例证据复核与 RTM 收口** 追加。**本节不是真机实测**：不占用 TIA 实例、
> 不跑 `--real-machine`、不产生任何编译 / 导入数字。目标是把批次 1/2 已有、此前未登记的**真实离线单测**
> 如实归档进 `evidence/rtm.json`。真相源：`evidence/rtm.json`（各 case 的 `offline_evidence` /
> `offline_verified_by` / `evidence_kind` / `caveat`）与 `summary.agent_n_offline_review`。

### 11.1 逐 UC 复核表（原 `not_run` 的 9 项，逐文件 `-q` 实跑）

| UC | 场景 | 原状态 → 新状态 | 单测文件（`tests/unit/`） | 用例名 | 实跑通过数 | 证据边界 |
|---|---|---|---|---|---|---|
| UC-06 | `spec_hash` 全域 + 绕过 patch 写入失败 | `not_run` → `pass`（offline） | `test_greenfield_ir.py` / `test_greenfield_patch_api.py` | `test_spec_hash_is_deterministic_and_covers_full_domain` / `test_patch_atomic_reject_keeps_ir` | 17 / 9 | 纯函数级哈希确定性 + patch 原子拒绝；非真机冻结链 |
| UC-07 | 从 `specs/vN.json` 重建画布（含拓扑） | `not_run` → `pass`（offline） | `test_greenfield_ir.py` | `test_specs_vn_json_rebuilds_canvas_including_topology` | 17 | FrozenSpec 快照单元级重建；**非服务进程真实重启** |
| UC-08 | 正向覆盖 `coverage==1.0` | `not_run` → `pass`（offline） | `test_greenfield_fidelity.py` | `test_minimal_sample_fidelity_ok_uc08` | 12 | N9：`fidelity_ok` ≠ `compile_ok` |
| UC-09 | 负例·漏映射 `coverage<1` | `not_run` → `pass`（offline） | `test_greenfield_fidelity.py` | `test_missing_artifact_reduces_coverage_uc09` | 12 | L1 校验器负例 |
| UC-10 | 负例·臆造 `orphan==1` | `not_run` → `pass`（offline） | `test_greenfield_fidelity.py` | `test_orphan_block_uc10` | 12 | L1 校验器负例 |
| UC-11 | 基线漂移 `drift!=0` 报警 | `not_run` → `pass`（offline） | `test_greenfield_fidelity.py` | `test_baseline_content_change_drift_uc11` | 12 | L1 校验器负例 |
| UC-14 | 可复现：同输入产物哈希一致 | `not_run` → `pass`（offline） | `test_greenfield_fidelity.py` / `test_greenfield_spec_diff.py` / `test_greenfield_gate.py` / `test_greenfield_e2e_delivery.py` | `test_reproducible_product_hash_uc14` / `test_build_baseline_manifest_deterministic_uc14` / `test_frozen_spec_is_reproducible_and_immutable` / `test_full_pipeline_three_pdfs_to_af_tia_zip_package` | 12 / 10 / 10 / 2 | 纯函数 / 内存态哈希确定性；**非真机 `.zap19` 两次产物哈希比对** |
| UC-17 | `fidelity_ok=false` 时 Action B 被拒 | `not_run` → `pass`（offline） | `test_greenfield_action_abc.py` | `test_uc17_action_b_rejected_when_action_a_fidelity_false` / `test_uc17_action_b_rejected_with_explicit_false_report` | 20 | TestClient / mock 会话前置门禁；非真机 Action B 写入链 |
| UC-19 | 确认前零副作用（四计数器恒 0） | `not_run` → `pass`（offline） | `test_greenfield_gate.py` / `test_greenfield_action_abc.py` | `test_confirm_diff_unconfirmed_keeps_zero_side_effects` / `test_no_side_effects_before_confirm` / `test_uc19_confirm_gate_zero_side_effects_service` / `_http` | 10 / 20 | 会话 / HTTP 层计数器；非真机差异清单级确认闭环 |

> 实跑命令均为 `cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/<具体文件> -q`，
> 7 个文件全部 `0 failed`：`ir 17 / patch_api 9 / spec_diff 10 / fidelity 12 / e2e_delivery 2 / gate 10 / action_abc 20`。
> 每个 case 在 `rtm.json` 中均附 `evidence_kind=offline_unit_test` 与 `caveat`。

### 11.2 状态计数变化（UC 主状态）

| 状态 | 复核前 | 复核后 | 说明 |
|---|---|---|---|
| `pass` | 5 | **14** | 5 个真机 pass（Agent M）+ **9 个离线 `offline_unit_test` pass（本次登记）** |
| `pending_real_machine` | 5 | **5** | **一律未动**：UC-01 / UC-04 / UC-15 / UC-16 / UC-18，确需真机全链 |
| `not_run` | 9 | **0** | 9 项全部找到离线实证并如实登记 |
| `fail` | 0 | 0 | — |
| `case_count` | 19 | **19** | 不变 |

### 11.3 边界与不变量（诚实口径）

- **离线 pass ≠ 真机 L2/L4 通过**：9 个 UC 的 `evidence_kind` 均为 `offline_unit_test`，`caveat` 明确
  「不等同真机 L2/L4 通过，也不使 M4 可签署」；未标任何 `L1/L2/L3/L4` 层为 `pass`。
- **L 层结论保持 Agent M 判定**：四层逐层仍 `pending`。即使 L1/L3 已有离线单测证据，仍因
  UC-15 端到端 / 四层静态门禁全绿 / EvidenceBundle 完整归档 / `tia_side_drift==0` 未闭环而不全绿；
  编排器 `aggregate_layers(offline)` 对 L2/L4 强制 `pending_real_machine`。
- **pending 台账未清零**：`evidence/pending_real_machine.json` 保持 `cleared=false`、`cleared_at=null`、
  10 条 `items` 一条未删，仅补 `agent_n_offline_review` 证据索引——**离线 pass 不使台账清零**。
- **M4 仍「未通过 / 不可签署」**：`--offline` 复核输出 `L1∧L2∧L3∧L4 未全绿`、
  `pending_cleared=false`、`m4_pass=false`；`09-m4-review.md` 签署栏仍「待用户签署」。
- **P0-D 档位结论待用户拍板**：本 Agent 不代拍，仅引用 `06-gate0-report.md` §6 推荐
  （坚持 AF Basic 文件夹版）；拍板前映射层维持「档位无关」。
- 未改任何产品代码 / C# 源码 / 冻结清单 / `uc05_real_machine_report.json`；未执行 git 操作、未跑真机。

### 11.4 护栏单测的最小同步

`tests/unit/test_greenfield_acceptance.py::test_rtm_status_counts_and_no_fake_pass` 原校验「所有 pass 必须带
真机证据三件套」，因本次 9 个离线 pass 而失败（`1 failed, 21 passed`）。已做**最小同步**：证据校验扩展为
「真机三件套 **OR** 离线单测四要素（`offline_evidence` / `offline_verified_by` / `evidence_kind` / `caveat`），
且离线 pass 不得挂真机证据、不得含 L2/L4 层」。**未回退主 agent 的动态自洽断言**；不变量
「pass 必须带证据」「涉 L2/L4 无真机证据不得 pass」「M4 未通过」全部保留。同步后 `22 passed`。

---

## 12. 批次 3 决策与范围（Agent P 追加，2026-11-07）

> 本节为**范围与责任分工追加**，不修改 §0–§11 任何既有文字；**§2 / §2.1 / §10.1 / §11.2 的 RTM 状态计数一律不动**（`pass` / `pending_real_machine` / `not_run` 等计数与逐 UC 状态由**主 agent 收口**按 P/Q/R 真实结果统一更新，Agent P 不碰 `evidence/rtm.json` / `pending_real_machine.json` / `acceptance_template.json` / `uc05_real_machine_report.json` 与 `10-real-machine-acceptance.md`）。
> 以下均为**待产出的验收目标与判定所需证据**，非既有结论；Agent P 未连真机、未跑测试，不宣称 `L2` / `L4` 通过、不宣称「编译零错误」、不宣称 `L1∧L2∧L3∧L4` 全绿、不宣称 `xml_package_unverified` 已消除、不宣称 M4 通过。

### 12.1 批次 3 前提

- **P0-D 已拍板**：用户 2026-11-06 编号「1」坚持「AF Basic 文件夹版」、暂不切「软件单元版」，正式记录 `11-p0d-decision.md`；映射层定型为文件夹版口径，Gate-0 升 `go`（准入放行），见 `06-gate0-report.md` §7。
- **范围**：本批次推进 5 个剩余 pending UC：**UC-01 / UC-04 / UC-15 / UC-16 / UC-18**（`13-batch3-contract.md` §3）。其余 UC 状态与计数不在本节改动范围。
- **保留口径**：`xml_package_unverified` 仍保持 `True`；`go` = 准入放行 ≠ `L1∧L2∧L3∧L4` 全绿 ≠ M4 可签署；M4 签署栏仍「待用户签署」，批次 3 最多推进到「证据齐备 / 待用户签署」。

### 12.2 五个 UC 的验收口径与证据产出责任人

> 责任人三分：**Q = 离线链**（验收编排器真实化 + 九步离线链，不连真机）、**R = 真机**（独占 TIA / SessionServer）、**主 agent = 收口台账**（`evidence/rtm.json` / `pending_real_machine.json` 等与 `10-real-machine-acceptance.md` 统一更新）。P 只产出决策与文档口径。

| UC | 目标 | 判定所需真实证据（待产出） | Q 离线链 | R 真机 | 主 agent 收口台账 |
|---|---|---|---|---|---|
| **UC-01** | 档位兼容性最小样例导入编译 | P0-D 用户拍板记录（`11-p0d-decision.md`）+ F 已有真机结果（文件夹版 1U+2EM 分组编译 `errorCount=0`，`06-gate0-report.md` §2.3 / 归档 §5.3，**仅对应建立分组结构后的 CanvasE2E 副本，非端到端全链**）+ Gate-0 升 `go` 决策记录（`06` §7）；**端到端全链仍由 UC-15 承担** | — | 端到端全链随 UC-15 步骤 7 | 按真实结果统一更新 RTM / pending 台账 |
| **UC-04** | K1 探针包级闭环 | 自产 `folders.json` / `SW.PlcBlockGroup XML` 在 V19 副本的**可导入性实测** + **完整 AF 包联合编译 `errorCount`**；据此给 `xml_package_unverified` 处置结论（**不擅自改**） | — | `evidence/uc04_package_probe.json`（包级复测真实结果） | 依据 R 的真实结果统一处置标志与台账；`xml_package_unverified` 是否消除**以 UC-04 包级真实结果为唯一依据** |
| **UC-15** | §9.2 九步端到端 | Q 真实驱动九步中离线可跑步骤（1–6、8、9）并留每步真实响应；R 真机完成步骤 7（Action B 编译 + `.zap19` + 结构化报告）；EvidenceBundle 实例化 | `evidence/nine_steps_offline_run.json`、离线可跑步骤真实响应、`evidence/uc15_evidence_bundle.json`（离线实例化） | `evidence/uc15_step7_real.json`（步骤 7 真机，判定目标为 Action B 编译 `error_count==0` + `.zap19` + 结构化报告，**待真机产出**） | 按 Q/R 真实结果统一更新 RTM / 台账与 `10-real-machine-acceptance.md` |
| **UC-16** | §13.9 六条增量 | R 真机：`/open` 一次 + 3 次差异确认覆盖 + 未重载校验 + D10 负例 + 回滚；增量 EvidenceBundle 六字段齐全、`fidelity_ok=true`、`tia_side_drift==0`、PCEC 可追溯（**均为判定目标，待真机证据**） | — | `evidence/uc16_incremental_real.json` | 按真实结果统一更新 RTM / 台账 |
| **UC-18** | 编译错误回喂 | R 真机：注入 1 个 SCL 语法错误 → 编译返回 error → 诊断定位 → 修正 → 复编译 `error_count==0`；warning 单列、账本可追溯；新通道派生层补编排函数（不改冻结的 `writeback_heal.py` / `compile_jobs.py`） | — | `evidence/uc18_compile_feedback_real.json` | 按真实结果统一更新 RTM / 台账 |

### 12.3 证据三件套与边界

- 所有 UC 状态变更须带**证据三件套**（真实返回 / 复现命令 / 证据文件路径）；真机失败项一律 `pending_real_machine` + 失败码 + 复现命令，绝不降级冒充（`13-batch3-contract.md` §5）。
- 台账（`evidence/rtm.json` / `pending_real_machine.json`）与 `10-real-machine-acceptance.md` 由主 agent 收口统一更新；Q 不连真机、不启动 SessionServer；**只有 Agent R 独占 TIA**。
- 本节不改动 §2.1 / §10.1 / §11.2 任何 RTM 状态计数；`M4 未通过 / 不可签署`、签署栏「待用户签署」口径不变。

---

## 附录 · 批次 4 RTM 状态迁移（2026-11-07，主 agent 收口）

| UC | 批次 3 状态 | 批次 4 状态 | 依据 |
|---|---|---|---|
| UC-04 | `pending_real_machine` | **pass** | `evidence/uc04_full_package_real.json`（W 独立包 5/5 + 0/0）、`evidence/uc04_product_package_real.json`（Y 正式包两轮各 10/10 + 0/0） |
| UC-16 | `pending_real_machine` | **pass** | `evidence/uc16_incremental_spec_chain.json`（V 真实 v1→v2）、`evidence/uc16_incremental_closed_real.json`（W 真机 Action C） |

最终 `by_status`: **`pass=19 / fail=0 / pending_real_machine=0 / not_run=0`**；`pending_uc_ids=[]`。
`gate0_facts` 的批次 2 历史快照（`uc04_k1_probe=fail`、`gate0_verdict=conditional-go`、`p0d_recommendation=pending_user_decision`）**未改动**，保留失败事实可追溯。

**不放水声明**：RTM 全 pass 不等于 L 层通过、不等于 `L1∧L2∧L3∧L4` 全绿、不等于 M4 可签署。
`xml_package_unverified` 仍 `True`、pending 台账 `cleared=false`、签署栏「待用户签署」。
