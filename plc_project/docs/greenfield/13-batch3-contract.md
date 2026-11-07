# 批次 3 契约 · P0-D 拍板后收官（UC-01/04/15/16/18）

| 项 | 值 |
|---|---|
| 日期 | 2026-11-07 |
| 分支 | `dev/greenfield-wp`，基线 commit `6986699` |
| 前序契约 | `04-parallel-wp-contract.md` §0、`05-parallel-wp2-contract.md` §1/§6 继续生效 |
| 本轮目标 | 用户已拍板 P0-D → 推进剩余 5 个 pending UC 的真机全链与证据闭环，给出 M4 复核结论 |

---

## §0 用户拍板结论（本批次唯一新增前置事实）

用户于 2026-11-06 以编号「1」正式拍板：

> **P0-D 档位结论 = 坚持「AF Basic 文件夹版」，暂不切「软件单元版」**（采纳 `06-gate0-report.md` §6 推荐结论）。

据此：

- Gate-0 的两项 `conditional-go` 前置中，**「P0-D 待拍板」已解除**；另一项「K1 探针失败」已由 Agent K 在 V19 副本上真机修复并复测通过（自产 OB XML 导入成功 + 编译 0/0），故 **Gate-0 可由 `conditional-go` 升为 `go`（准入放行）**，可由决策记录正式归档。
- 映射层从「档位无关」**定型为文件夹版口径**；不得改动 `framework_baseline` 语义、不得切换软件单元版。
- **`xml_package_unverified` 仍保持 `True`**：K 只验证了 OB XML 探针级；`folders.json` / `SW.PlcBlockGroup XML` 可导入性、含 Call 网络的完整 AF 包联合编译、端到端全链尚未闭环。是否消除须由本批次 UC-04 包级复测的真实结果决定，**任何 agent 不得擅自改 False**。
- **P0-D 是用户结论，agent 只做记录与执行，不得重新论证或代拍。**

## §1 全局规则（不可违反）

1. **sha256 冻结清单零触碰**：`tests/fixtures/greenfield/legacy_baseline.json` 的 41 个文件（含 `planner.py`、`compile_jobs.py`、`writeback_heal.py`、`scl_precheck.py`、`pcec.py`、`writeback_batch.py`、`af_import.py`、`FastWriteback.cs`、`smartRoute.ts`、`WorkspacePanel.tsx`、`ChatDock.tsx`、`gateway/app/routers/plc.py`、`io_import.py`、`db_import.py`）与 `tests/unit/test_greenfield_legacy_guard.py` 一律不改。`tia_delivery.py` 是 sanctioned 模块可改，但**不得新增 forbidden_modules 的 import**。
2. **禁止任何 git 操作**（add/commit/checkout/stash/reset/worktree）——主 agent 统一提交。
3. **真机安全**：只允许在 `C:/Users/vboxuser/AppData/Local/Temp/gf_real_*` 临时副本上操作；先 `cp` 再打开；**禁止**打开/修改 `PLC_Openness_data/` 下任何原始 `.ap19`/`.zap19`；禁止 `SaveProject()` 写回原始路径；每个真机子进程设超时（`timeout -k 5 180`）；`serve` 常驻进程用完必须停止。
4. **TIA 实例独占**：本批次**只有 Agent R 可连真机/TIA/SessionServer**；P、Q 一律不连真机、不占用 8791/8000 之外的真机资源。
5. **诚实口径**（N9 / D12 / §6）：
   - `fidelity_ok` ≠ `compile_ok` ≠ L 层通过 ≠ M4 可签署；
   - 离线单测 / mock 不得标 L2/L4 pass、不得宣称「编译零错误」；
   - `tia_unavailable` 显式非 200；warning 单列不并入成功；
   - 所有真机数字必须来自真实 CLI/HTTP 原始返回并附复现命令，**失败即如实记录，禁止编造**；
   - `ob_number_deviations` 必须留痕；`pending_real_machine` 不得静默消除。
6. **M4 不得代签**：M4 签署栏始终为「待用户签署」。本批次最多把结论推进到「证据齐备 / 待用户签署」，**任何 agent 不得把 `m4_signable` 置 true 并宣称 M4 通过**。
7. D12 hard refuse：不做在线下载 / online / run-stop / compare-to-PLC、不碰 F-block/Safety、不做 UI 自动化。
8. 已知基线既有失败 `tests/unit/test_af_import.py::test_hr001_real_import_roles_and_freeze`（`FB1060_AutoStep` 角色 `em` vs `global`）已在 `main@f9d4a3d` worktree 实证，**排除且不得修复**。
9. 不得新增第三方依赖、不改 C# 源码、不改 `package.json`。

## §2 文件所有权（三两组互不相交）

| Agent | 角色 | 独占可写文件 | 禁止 |
|---|---|---|---|
| **P** | 决策固化与文档 | `docs/greenfield/06-gate0-report.md`（末尾追加 §7）、`docs/greenfield/05-parallel-wp2-contract.md`（末尾追加）、`docs/greenfield/07-acceptance-matrix.md`（末尾追加）、`docs/greenfield/09-m4-review.md`、**新增** `docs/greenfield/11-p0d-decision.md`、仓库根 `research/Gate0_环境与档位实测_2026-11-06.md`（末尾追加） | 不改 `evidence/rtm.json`、`pending_real_machine.json`（由主 agent 收口统一更新）；不改任何产品代码；不连真机 |
| **Q** | 验收编排器真实化 + 九步离线链 | `tools/greenfield_acceptance.py`、`tests/unit/test_greenfield_acceptance.py`、**新增** `tools/run_nine_steps.py`、**新增** `tests/unit/test_greenfield_nine_steps.py`、**新增** `evidence/nine_steps_offline_run.json`（运行时产物）、**新增** `evidence/uc15_evidence_bundle.json`（离线实例化） | 不改 `evidence/rtm.json` / `pending_real_machine.json` / `acceptance_template.json`；不连真机、不启动 SessionServer；不改产品代码 |
| **R** | V19 真机全链（独占 TIA） | **新增** `evidence/uc04_package_probe.json`、`evidence/uc16_incremental_real.json`、`evidence/uc18_compile_feedback_real.json`、`evidence/uc15_step7_real.json`、`docs/greenfield/12-batch3-real-machine.md`、`tools/run_batch3_real_machine.py`（可选）、`tests/unit/test_greenfield_batch3_real.py`（可选）；`gateway/app/services/plc/tia_delivery.py` **仅允许新增**编译诊断回喂编排函数（UC-18），不得改会话模式与 XML 修复代码 | 不改 `evidence/rtm.json` / `pending_real_machine.json`；不改 `greenfield_service.py` / `greenfield.py` 路由；不改冻结清单；不改 C# |

> 台账（`rtm.json` / `pending_real_machine.json`）与 `10-real-machine-acceptance.md` 由**主 agent 收口**按 P/Q/R 的真实结果统一更新，避免并行写冲突。

## §3 本轮 5 个 UC 的验收口径

| UC | 目标 | 判定所需真实证据 |
|---|---|---|
| **UC-01** | 档位兼容性最小样例导入编译 | P0-D 用户拍板记录 + F 已有真机结果（文件夹版 1U+2EM 编译 0 错误）+ Gate-0 升 `go` 的决策记录；**端到端全链仍由 UC-15 承担** |
| **UC-04** | K1 探针包级闭环 | 自产 `folders.json` / `SW.PlcBlockGroup XML` 在 V19 副本的可导入性实测 + 完整 AF 包联合编译 `errorCount`；据此给 `xml_package_unverified` 处置结论（不擅自改） |
| **UC-15** | §9.2 九步端到端 | Q 真实驱动九步中离线可跑步骤（1–6、8、9）并留每步真实响应；R 真机完成步骤 7（Action B 编译零错误 + `.zap19` + 结构化报告）；EvidenceBundle 实例化 |
| **UC-16** | §13.9 六条增量 | R 真机：`/open` 一次 + 3 次差异确认覆盖 + 未重载校验 + D10 负例 + 回滚；增量 EvidenceBundle 六字段齐全、`fidelity_ok=true`、`tia_side_drift==0`、PCEC 可追溯 |
| **UC-18** | 编译错误回喂 | R 真机：注入 1 个 SCL 语法错误 → 编译返回 error → 诊断定位 → 修正 → 复编译 `error_count==0`；warning 单列、账本可追溯；新通道派生层补编排函数（不改冻结的 `writeback_heal.py`/`compile_jobs.py`） |

## §4 验收命令（主 agent 收口执行）

```
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_af_import.py
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q
cd <R> && ./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline
cd <R>/frontend && npm run test && npm run build
git diff --name-only  # 核对零冻结文件被触碰
```

## §5 诚实边界（本批次必须继续保留）

- 即便 5 个 UC 全绿、L1∧L2∧L3∧L4 判定全 pass，**M4 仍须用户本人签署**；
- `xml_package_unverified` 的消除须以 UC-04 包级真实结果为唯一依据；
- 真机失败项一律 `pending_real_machine` + 失败码 + 复现命令，绝不降级冒充；
- 所有 UC 状态变更必须带证据三件套（真实返回 / 复现命令 / 证据文件路径）。
