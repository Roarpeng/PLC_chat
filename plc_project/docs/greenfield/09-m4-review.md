# M4 发布门禁复核报告（模板 · **待用户签署**）

| 项 | 值 |
|---|---|
| 报告性质 | **复核报告模板 / 签署栏空白**；WP-10 收口实测后由主 agent 填写实测证据，再由用户签署 |
| 当前状态 | **待用户签署** |
| 当前复核结论 | **`M4 未通过`，不可签署** |
| 分支 / 基线 | `dev/greenfield-wp` / `9f7186b`（未执行任何 git 操作） |
| 日期 | 2026-11-06 |
| 编制 | Agent I · WP-10（纯新增文档，不改产品代码） |
| 依据 | Plan v1.0 §2.2 / §3 M4 / §7.2 / §7.3 / §9.3；契约 05 §4 / §5 / §6；基线报告 v2.1 §13.9 |
| 配套 | `07-acceptance-matrix.md`、`evidence/rtm.json`、`evidence/acceptance_template.json`、`evidence/pending_real_machine.json` |

> **本模板不代用户签署、不代用户拍板、不代跑真机。** 所有真机结论只能引用
> `06-gate0-report.md` / `research/Gate0_环境与档位实测_2026-11-06.md`（Agent F 归档）或真实运行结果。
> 禁止以离线单测宣称 `L1∧L2∧L3∧L4` 通过、宣称「编译零错误」、把 `pending` 视为通过。

---

## 1. M4 判定式

```
M4 可签署 = (L1 ∧ L2 ∧ L3 ∧ L4 全绿)
          ∧ (pending_real_machine 台账清零：cleared=true 且 items 为空)
          ∧ (EvidenceBundle 完整归档：full 12 项 + 增量 6 字段齐全)
          ∧ (UC-01～UC-19 逐条核验，含两个负例与回滚演练)
          ∧ (变更记录 / 遗留清单齐备)
          ∧ (审批人（用户）签署)
```

**当前判定：`M4 未通过`**（依据 `tools/greenfield_acceptance.py --offline` 复核输出）：

| 条件 | 当前 | 结论 |
|---|---|---|
| L1 ∧ L2 ∧ L3 ∧ L4 | 未全绿（L2/L4 全部 `pending_real_machine`） | 不满足 |
| pending 台账清零 | 10 项未清零，`cleared=false` | 不满足 |
| EvidenceBundle 完整归档 | 仅模板与台账，真实证据包未实例化 | 不满足 |
| UC 逐条核验 | 19 UC：`pass=14`（5 真机 pass + 9 离线 `offline_unit_test` pass）/ `pending_real_machine=5` / `not_run=0`；离线 pass 不等同真机层通过、不使台账清零 | 不满足（pending 台账未清零、四层未全绿） |
| 变更记录 / 遗留清单 | 已产出（`07-acceptance-matrix.md` §8） | 已就绪 |
| 离线单测证据登记（Agent N） | 9 个 UC 已附 `offline_evidence` / `caveat`，逐 UC 复核表见 `07-acceptance-matrix.md` §11 | 已完成（**非 M4 判定条件**，不改变 M4 未通过） |
| 审批人签署 | **待用户签署** | 不满足 |

---

## 2. `L1∧L2∧L3∧L4` 逐层复核表

| 层 | 判定式 | 绑定 UC | 复核状态 | 证据产物（收口时填实测归档路径） | 复核结论 |
|---|---|---|---|---|---|
| L1 逻辑等价 | `coverage==1.0 ∧ orphan==0 ∧ drift==0 ∧ tia_side_drift==0` | 08, 09, 10, 11, 15, 17, 19 | 未通过（离线单测证据已登记：UC-08/09/10/11/17/19；但 UC-15 端到端 pending、四层门禁未全绿 → 层仍 pending） | `fidelity_report.json`、负例报告、`baseline_manifest.json` | 待补 |
| L2 可编译 | `compile_error==0` ∧ 四层静态门禁通过；warning 单列；`tia_unavailable` 显式失败 | 02, 03, 04, 15, 18 | **未通过（全部 `pending_real_machine`）** | 结构化编译报告、K1 导入日志 | 待补 |
| L3 可复现 | 同 `spec_hash` 两次产物哈希一致 + 重启恢复 FROZEN vN | 06, 07, 14, 15 | 未通过（离线单测证据已登记：UC-06/07/14；但非真机 `.zap19` 两次产物哈希比对、UC-15 端到端 pending → 层仍 pending） | reproducibility 记录、`.zap19`、`specs/vN.json` | 待补 |
| L4 增量可迭代 | 同会话连续 ≥3 次增量，每次 `fidelity_ok` ∧ `error_count==0` ∧ `tia_side_drift==0`，项目未关闭/未重载/未新建 | 05, 12, 13, 15, 16 | **未通过（全部 `pending_real_machine`）** | 增量 `fidelity_report`、PCEC 3 条、句柄复用记录 | 待补 |

> G1 的 P0-G 验收**不等于** L4 通过；完整 L4 还需 §13.9 六条用例的 `fidelity_ok` 与 `tia_side_drift==0`。
> **N9**：`fidelity_ok` 与 `compile_ok` 独立，禁止互相替代。

**离线复核结论：四层均未判定通过 → `L1∧L2∧L3∧L4` 未全绿。**

---

## 3. EvidenceBundle 归档核对表

### 3.1 全量（full）12 项

| # | 产物 | 归档状态（收口填） |
|---|---|---|
| 1 | `specs/vN.json` | [ ] |
| 2 | `ir_snapshot` | [ ] |
| 3 | 四视图导出 | [ ] |
| 4 | 连线清单 | [ ] |
| 5 | `open_questions` 清零记录 | [ ] |
| 6 | 静态门禁结果 | [ ] |
| 7 | `fidelity_report.json` | [ ] |
| 8 | 结构化编译报告（真实 CLI/HTTP 返回） | [ ] |
| 9 | PCEC 账本 | [ ] |
| 10 | `baseline_manifest.json` | [ ] |
| 11 | 产物哈希 | [ ] |
| 12 | `.zap19` 归档 | [ ] |

### 3.2 增量（incremental）必须追加 6 字段

| # | 字段 | 归档状态（收口填） |
|---|---|---|
| 1 | `mode` | [ ] |
| 2 | `base_spec_version` | [ ] |
| 3 | `changed_source_ids[]` | [ ] |
| 4 | `reverse_protection` | [ ] |
| 5 | `tia_side_drift` | [ ] |
| 6 | `ob_number_deviations`（**必须留痕、禁止静默**；属不纳入 1:1 的域，不参与 `fidelity_ok`） | [ ] |

> 增量字段缺任一 → 证据包不完整 → **M4 不得签署**。

---

## 4. pending 台账清零状态

| 项 | 当前值 |
|---|---|
| `evidence/pending_real_machine.json` `cleared` | `false` |
| items 条数 | 10（UC-01, 02, 03, 04, 05, 12, 13, 15, 16, 18） |
| 清零条件 | 真机（或对应收口核验）产出真实结构化证据并由主 agent 逐条核验；**禁止以离线单测 / mock / 人工观感清零** |
| 结论 | **未清零 → M4 必须保持未通过** |

> Agent N 离线证据复核（2026-11-06）：9 个 UC 已登记为 `offline_unit_test` `pass`（仅离线单测证据），
> 仅在本台账补 `agent_n_offline_review` 证据索引；**`cleared` 仍 `false`、10 条 `items` 一条未删**——
> 离线 pass 不使台账清零。UC-01 / UC-04 / UC-15 / UC-16 / UC-18 五个 `pending_real_machine` 仍需真机全链。

---

## 5. 收口验收命令（由主 agent 统一执行）

```
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_af_import.py
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_acceptance.py -q
cd <R> && ./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline
cd <R>/frontend && npm run test && npm run build
```

> **已知基线既有失败 `test_af_import.py::test_hr001_real_import_roles_and_freeze` 已在
> `main@f9d4a3d` worktree 实证，排除且不得修复。**
> `test_frozen_legacy_files_have_zero_diff()` **必须 PASS**；冻结清单 / `legacy_baseline.json` /
> `test_greenfield_legacy_guard.py` / sha256 冻结清单一律不碰。

---

## 6. 待用户拍板 / 待主 agent 收口项（摘要）

- **P0-D AF 档位结论：待用户拍板**（Agent 不代拍）。推荐结论与依据引用
  `06-gate0-report.md` §6（坚持 AF Basic 文件夹版）；拍板前映射层维持「档位无关」。
- Gate-0 = **`conditional-go`**，未到完整 `go`；UC-04 K1 未通过（`xml_package_unverified` 保持 `True`）。
- 真机三次增量（UC-05 / UC-16）、D10/D11 真机约束、UC-15 九步端到端、UC-13 回滚演练等均未实测。
- 三动作端点 `/action-a` `/action-b` `/action-c`（契约 05 §3.2）需收口时核验接线。
- 完整可勾选清单见 `07-acceptance-matrix.md` §8。

### 6.1 本次离线证据复核完成项（Agent N · 待办勾选状态更新）

> 以下为**证据登记类**待办，已如实完成并勾选；**均非 M4 签署前条件**，不改变
> `M4 未通过 / 不可签署`、不改变四层 pending、不使台账清零，也**不勾选 §7 任何签署前勾选项**。

- [x] 逐条复核原 `not_run` 的 9 个 UC，找到对应真实离线单测并逐文件 `-q` 实跑（7 文件 / 全部 `0 failed`）
- [x] 在 `evidence/rtm.json` 把 9 个 UC 由 `not_run` 如实更新为 `offline_unit_test` `pass`，逐 case 附
      `offline_evidence` / `offline_verified_by` / `evidence_kind` / `caveat`
- [x] 同步 `summary.by_status`（`pass=14 / pending_real_machine=5 / not_run=0`）、`case_count=19` 与
      `agent_n_offline_review` 说明
- [x] `pending_real_machine.json` 补 `agent_n_offline_review` 证据索引；`cleared=false`、items 10 条未删
- [x] `07-acceptance-matrix.md` 追加「离线证据复核」一节（逐 UC 单测路径 / 通过数 / 边界）
- [x] 护栏单测 `test_greenfield_acceptance.py` 最小同步（区分真机 / 离线证据口径），`22 passed`
- [x] **P0-D 档位结论已由用户于 2026-11-06 以编号「1」拍板**：坚持「AF Basic 文件夹版」、暂不切「软件单元版」（正式决策记录见 `11-p0d-decision.md`，依据 `06-gate0-report.md` §6 推荐结论）。本项由 Agent P 归档用户结论、**不代拍**；§6 摘要与 §7 说明中「待用户拍板」为批次 2 历史状态文字，按保留可追溯性要求原样保留、不改写
- [ ] `L1∧L2∧L3∧L4` 全绿 / pending 台账清零 / EvidenceBundle 完整归档 / UC-15 端到端 / 真机全链——仍不勾选

> **批次 3（Agent P 追加，2026-11-07）**：**批次 3 结论最多推进到「证据齐备 / 待用户签署」，不得由 agent 宣布 M4 通过**。
> 本节其余待办保持未勾；签署栏（§7）仍为「待用户签署」，「签署前必须确认的勾选项」由用户签署时确认，Agent 不代勾、不代签、不改动签署栏任何文字。

---

## 7. 审批人签署栏（**待用户签署**）

> 本节所有签署字段**留空**，由用户（PLC_chat 项目负责人与最终决策者）在收口实测完成、
> `M4 可签署` 判定成立后亲笔填写。**当前状态：待用户签署，不得代签。**
>
> Agent N 离线证据复核后**仍不代签**：9 个离线 `offline_unit_test` `pass` 仅登记离线单测证据，
> 不勾选下表任何「签署前必须确认」项；四层仍 pending、台账未清零、P0-D 待用户拍板。
> **P0-D 档位结论待用户拍板**（推荐结论引用 `06-gate0-report.md` §6），本 Agent 不代拍。

| 角色 | 姓名 / 标识 | 复核结论（通过 / 不通过 / 待补证据） | 签署 | 日期 |
|---|---|---|---|---|
| 审批人（用户） |  |  | **待用户签署** |  |
| 主 agent（收口实测） |  |  | 待填写 |  |
| WP-10 编制（Agent I） | Agent I | 已提交框架与事实录入；`M4 未通过` 为当前诚实结论 | 编制完成 | 2026-11-06 |

| 签署前必须确认的勾选项 | 状态 |
|---|---|
| `L1∧L2∧L3∧L4` 复核报告已附真实证据且四层全绿 | [ ] |
| `pending_real_machine` 台账已清零（`cleared=true` 且 items 为空） | [ ] |
| UC-01～UC-19 逐条核验（含 §9.2 九步两个负例、§13.9 六条含 D10 阻止与回滚演练） | [ ] |
| EvidenceBundle 12 项 + 增量 6 字段完整归档，产物哈希可复现 | [ ] |
| P0-D 档位结论已由用户拍板并留痕 | [ ] |
| 变更记录 / 遗留清单齐备，已知基线既有失败已排除且未修复 | [ ] |
| 收口验收命令全部通过，`test_frozen_legacy_files_have_zero_diff()` PASS | [ ] |

---

## 8. 诚实口径声明

- 本报告为**模板**，当前 `M4 未通过`；未以离线单测宣称 `L2/L4` 通过或「编译零错误」，
  未把 `pending` 视为通过，未把 `tia_unavailable` 说成成功。
- `errorCount=0` 仅对应 Agent F 归档中 CanvasE2E 基线副本与「仅建分组」副本；`errorCount=30` 为真实编译
  失败。二者均非「UC-01 端到端样例零错误」，不得据此宣称全链编译通过。
- 未执行任何 git 操作；未改产品代码 / 冻结清单 / C# 源码；D12 hard refuse 全程约束；
  N9 `fidelity_ok` 与 `compile_ok` 严格独立。
- **P0-D 档位结论待用户拍板，本 Agent 未代拍**；审批人签署栏**待用户签署，未代签**。

---

## 附录 · 批次 3 复核结论（2026-11-07，主 agent 收口，不代签）

> 本节为追加记录，签署栏状态不变：**待用户本人签署**。

| 复核项 | 批次 3 结论 |
|---|---|
| P0-D 档位 | 用户 2026-11-06 编号「1」已拍板 AF Basic 文件夹版（`11-p0d-decision.md`）；Gate-0 升 `go`（准入放行） |
| RTM | `pass=17 / fail=0 / pending_real_machine=2 / not_run=0`；pending 为 **UC-04 / UC-16** |
| L1 | `pass`（九步离线链 + 真实服务重启恢复、产物哈希可复现） |
| L2 | **未通过**：UC-04 包级两处真实失败（`SW.PlcBlockGroup` 不可导入、Call 网络 OB 导入失败） |
| L3 | `pass`（同一 v1 spec 重跑 Action A，三项哈希一致） |
| L4 | **未通过**：UC-16 增量 `fidelity` / `base_spec_version=null` 未闭环 |
| `L1∧L2∧L3∧L4` | **未全绿** |
| `xml_package_unverified` | 仍为 `True`，未擅自消除 |
| pending 台账 | `cleared=false`，历史 items 未删 |
| **M4** | **未通过 / 不可签署**，最多推进到「证据齐备 / 待用户签署」 |

新增证据：`evidence/uc04_package_probe.json`、`uc15_step7_real.json`、`uc16_incremental_real.json`、
`uc18_compile_feedback_real.json`、`uc15_restart_recovery.json`、`nine_steps_offline_run.json`、
`uc15_evidence_bundle.json`；汇总见 `10-real-machine-acceptance.md` 附录与 `12-batch3-real-machine.md`。

**签署前仍需完成**：① UC-04 完整 AF 包（含 Call 网络 OB）导入编译闭环；② UC-16 增量
`FidelityChecker(mode=incremental)` 与真实 `specs/vN.json` 规格链闭环；③ pending 台账逐条核验清零；
④ 用户本人签署。以上四项任一未完成，M4 保持未通过。
