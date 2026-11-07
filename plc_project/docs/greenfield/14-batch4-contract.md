# 批次 4 契约 · 闭环 UC-04 / UC-16

| 项 | 值 |
|---|---|
| 日期 | 2026-11-07 |
| 分支 | `dev/greenfield-wp`，基线 commit `3596fb9`（批次 3 收官） |
| 前序契约 | `04-parallel-wp-contract.md` §0、`05-parallel-wp2-contract.md` §1/§6、`13-batch3-contract.md` §1/§5 继续生效 |
| 本轮目标 | 闭环最后 2 个 pending UC：UC-04 完整 AF 包（含 Call 网络 OB）导入编译、UC-16 增量 fidelity + 真实 `specs/vN.json` 规格链 |
| 用户授权 | 「继续闭环 UC-04/UC-16」（2026-11-07） |

---

## §0 两个 pending 的真实根因（已勘查，不要重新推导）

### UC-04
批次 3 `evidence/uc04_package_probe.json` 的两处真实失败：

1. `SW.PlcBlockGroup XML` 经 `import-xml --kind auto|block` 均失败（`exit=4 / openness_error`，
   `"Class of the 'Siemens.Engineering.SW.PlcBlockGroup' type ... is not supported."`）。
   该类型**不是可导入的 SimaticML 块对象**；产品链应走 `create-block-group` Openness API 建立文件夹
   （F 已真机验证 `AF_Unit_01/AF_EM_01`、`AF_Unit_01/AF_EM_02` 两次 `ok=true/saved=true`）。
   → **不是要走通 XML 导入，而是要确认产品链用 API 路径、清单与产物一致**。
2. Call 网络 OB `GF_U1EM1_CallOB` 导入即失败：
   `"The name 'GF_U1EM1_InstDB' cannot be used for "Call" at the object with UID '21'."`
   根因有两层：
   - **包不自洽**：完整 AF 包只含 5 个 OB，**缺少被引用的 FB 块与全局实例 DB 块**。
     真实 V19 先例 `PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/OB1Main.xml` 的
     Call 网络引用 `FB1000_StdSignal` / `DB1000_StdSignal`，而同目录确有
     `001_KL_Standard_FB_FB1000_StdSignal.xml` 与 `001_KL_Standard_FB_DB1000_StdSignal.xml`。
   - **模板假设错误**：`tia_delivery.py::_render_call_network` 用
     `call_fb = re.sub(r"_DB$", "", call_db)` 从实例 DB 名反推 FB 名；真实先例是
     **FB / DB 独立命名**（`FB1000_…` / `DB1000_…`），并非 `xxx_DB` → `xxx` 关系。
     批次 3 传入 `GF_U1EM1_InstDB`（不以 `_DB` 结尾）导致 FB 名退化为整个字符串。

K 的 caseB（`08-k1-probe-fix.md` §4.4）导入成功但编译 `errorCount=2`，是同一根因的另一种表现
（占位 `K1_CallUnit_DB` / `K1_CallUnit` 在空项目中不存在），**非模板 namespace 缺陷**，不得掩盖。

### UC-16
批次 3 `evidence/uc16_incremental_real.json` 已拿到 `/open`=1、3× 编译 0/0、PCEC 3 条、
六字段真实值，但 **`base_spec_version=null`**、`fidelity_ok` 引用 Q 的离线 L1 全量真值、
增量 `FidelityChecker(mode=incremental)` 未闭环 —— 因为 R 走的是纯 CLI 块级覆盖，
**没有真实 Greenfield 冻结规格链 `specs/v1.json → specs/v2.json`**。

已具备的能力（不要重写）：
- `plc_engine/af/spec_diff.py::compute_spec_diff(base_spec, target_spec, *, base_blocks, target_blocks)`
- `plc_engine/af/fidelity.py::FidelityChecker.check(spec, artifacts, *, mode, base_spec_version, diff, tia_side_snapshot)`
- `tools/run_nine_steps.py` 的 TestClient 驱动链（v1 冻结、`specs/v1.json` 落盘可复现）
- `/begin-edit`、`/patch`、`/diff`、`/confirm-diff`、`/action-c` 服务端端点

---

## §1 全局规则（不可违反）

1. **sha256 冻结清单零触碰**：`tests/fixtures/greenfield/legacy_baseline.json` 的 41 个文件
   （含 `planner.py`、`compile_jobs.py`、`writeback_heal.py`、`scl_precheck.py`、`pcec.py`、
   `writeback_batch.py`、`af_import.py`、`FastWriteback.cs`、`smartRoute.ts`、
   `WorkspacePanel.tsx`、`ChatDock.tsx`、`gateway/app/routers/plc.py`、`io_import.py`、
   `db_import.py`）与 `tests/unit/test_greenfield_legacy_guard.py` 一律不改。
   `tia_delivery.py` 是 sanctioned 模块可改，但**不得新增 forbidden_modules 的 import**。
2. **禁止任何 git 操作**（add/commit/checkout/stash/reset/worktree）——主 agent 统一提交。
3. **真机安全**：只允许 `C:/Users/vboxuser/AppData/Local/Temp/gf_real_*` 临时副本；先 `cp` 再打开；
   **禁止**打开/修改 `PLC_Openness_data/` 下任何原始 `.ap19`/`.zap19`（该目录下的 XML 仅作**只读模板参考**）；
   禁止 `SaveProject()` 写回原始路径；每个真机子进程设超时（`timeout -k 5 180`）；`serve` 用完必须停止。
4. **阶段与 TIA 独占**：阶段 A 的 U / V **一律不连真机、不启动 SessionServer、不占用 8791/8000**；
   阶段 B 的 W 是**唯一**允许连真机 / TIA / SessionServer 的 agent。
5. **诚实口径**（N9 / D12 / §6）：`fidelity_ok` ≠ `compile_ok` ≠ L 层通过 ≠ M4 可签署；
   离线单测 / mock 不得标 L2/L4 pass、不得宣称「编译零错误」；真机数字只来自真实 CLI/HTTP
   原始返回并附复现命令，**失败即如实记录、禁止编造**；`ob_number_deviations` 必须留痕；
   `pending_real_machine` 不得静默消除；warning 单列不并入成功。
6. **M4 不得代签**：签署栏始终「待用户签署」；本批次最多推进到「证据齐备 / 待用户签署」，
   任何 agent 不得把 `m4_signable` 置 true 并宣称 M4 通过。
7. **`xml_package_unverified` 不得擅自改 False**：是否消除由主 agent 在 W 的真实结果出来后
   按证据决定；任何 agent 只给结论与依据。
8. D12 hard refuse：不做在线下载 / online / run-stop / compare-to-PLC、不碰 F-block/Safety、不做 UI 自动化。
9. 已知基线既有失败 `tests/unit/test_af_import.py::test_hr001_real_import_roles_and_freeze`
   排除且不得修复；存量 `test_canvas_import.py` 的 2 条 UTF-8/GBK 线程警告属既有问题，不修。
10. 不得新增第三方依赖、不改 C# 源码、不改 `package.json`。

---

## §2 阶段与文件所有权

### 阶段 A（并行，均不连真机）

| Agent | 角色 | 独占可写文件 |
|---|---|---|
| **U** | UC-04 模板修复 + 完整 AF 包构造 | `gateway/app/services/plc/tia_delivery.py`（**仅** `_render_call_network` / `_render_ob_xml` 及新增的 FB/DB 渲染函数；**必须原样保留** G 会话模式、K XML 修复、批次 3 `compile_feedback_heal`）；**新增** `tools/build_full_af_package.py`、`tests/unit/test_greenfield_full_af_package.py`、`docs/greenfield/14-uc04-package-fix.md` |
| **V** | UC-16 真实规格链 + 增量 fidelity | **新增** `tools/run_incremental_spec_chain.py`、`tests/unit/test_greenfield_incremental_chain.py`、`evidence/uc16_incremental_spec_chain.json`、`evidence/uc16_incremental_evidence_bundle.json`、`docs/greenfield/15-uc16-spec-chain.md`；**不改任何产品代码**、不改 `tools/run_nine_steps.py`（只读复用） |

### 阶段 B（U / V 完成后，单 agent 独占 TIA）

| Agent | 角色 | 独占可写文件 |
|---|---|---|
| **W** | V19 真机联合验证 | **新增** `evidence/uc04_full_package_real.json`、`evidence/uc16_incremental_closed_real.json`、`docs/greenfield/16-batch4-real-machine.md`、`tools/run_batch4_real_machine.py`（可选）、`tests/unit/test_greenfield_batch4_real.py`（可选）；**不改任何产品代码**、不改证据台账 |

### 阶段 C（主 agent 收口）
`evidence/rtm.json`、`evidence/pending_real_machine.json`、`evidence/uc15_evidence_bundle.json`、
`docs/greenfield/09-m4-review.md`、`10-real-machine-acceptance.md`、`12-batch3-real-machine.md`、
`xml_package_unverified` 全局处置、全量回归、git 提交。

> U / V / W 一律**不改** `evidence/rtm.json`、`pending_real_machine.json`、`acceptance_template.json`、
> `uc15_evidence_bundle.json`、批次 2/3 的既有真机证据文件（只读引用）。

---

## §3 验收口径

### UC-04 闭环判据
1. U 产出**自洽的完整 AF 包**：Call OB + 被引用的 FB 块 + 全局实例 DB 块 + 文件夹清单；
   `call_fb` / `call_db` 独立配置，FB/DB 命名与真实 V19 先例同构；模板离线单测通过。
2. W 在临时副本上按顺序导入（FB → DB → OB，或 CLI 支持的整体导入），`import.ok=true`；
   文件夹经 `create-block-group` API 建立（**不要求** `SW.PlcBlockGroup` XML 可导入）；
   `compile-plc` 真实 `errorCount=0 / warningCount=0 / state=Success`。
3. 产出结构化证据（原始返回 + 复现命令 + 副本路径）、`xml_package_unverified` 处置建议。
4. 若仍失败 → 如实记录失败码与原始返回，UC-04 保持 `pending_real_machine`，**禁止冒充通过**。

### UC-16 闭环判据
1. V 用真实端点产出 `specs/v1.json` → `specs/v2.json`（v2 由 `/patch` 真实编辑后 `/confirm` 冻结），
   两版 `spec_hash` 不同、`project_id` 一致。
2. `compute_spec_diff(v1, v2)` 产出真实 `changed_source_ids` 与 `base_spec_version=1`；
   `FidelityChecker.check(mode="incremental", base_spec_version=1, diff=...)` 产出
   `fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0`。
3. 增量 EvidenceBundle 六字段全部为**真实值**（`mode=incremental`、`base_spec_version=1`、
   `changed_source_ids` 非空、`reverse_protection`、`tia_side_drift=0`、`ob_number_deviations` 留痕）。
4. W 真机：Action C 以 v1→v2 差异清单显式确认（D11）为前提，会话复用覆盖 → 编译 0/0 →
   增量 fidelity 复核；`/open` 一次、PCEC 可追溯、`tia_side_drift=0`。
5. 若真机链做不到 → 如实标 `pending_real_machine`，离线报告不得冒充真机 L4 通过。

## §4 验收命令（主 agent 收口执行）

```
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_af_import.py
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q
cd <R> && ./.venv/Scripts/python.exe tools/greenfield_acceptance.py --offline
cd <R>/frontend && npm run test && npm run build
git diff --name-only  # 核对零冻结文件被触碰
```
