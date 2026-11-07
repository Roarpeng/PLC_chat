# 批次 3 · V19 真机全链收官报告（UC-04 / UC-15 步骤 7 / UC-16 / UC-18）

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 3 · **Agent R · V19 真机全链收官**（本批次唯一允许连真机 / TIA / SessionServer 的 agent） |
| 分支 / 基线 | `dev/greenfield-wp` / `6986699`（**未执行任何 git 操作**） |
| 日期 | 2026-11-07 |
| 契约 | `13-batch3-contract.md`（§0 拍板 / §1 全局规则 / §2 所有权 / §3 五个 UC 口径 / §5 诚实边界）；`04-parallel-wp-contract.md` §0、`05-parallel-wp2-contract.md` §1/§6 继续生效 |
| 真机探针 | `industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe --cli ...` / `serve`（HTTP `127.0.0.1:8791`） |
| Python | `<R>/.venv/Scripts/python.exe` |
| 真机副本根 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_r_20261107/`（只读源 `PLC_Openness_data/openness_e2e/CanvasE2E`，仅 `cp`/`copytree`，**从未打开或写回原始 `.ap19/.zap19`**） |
| 复现脚本 | `tools/run_batch3_real_machine.py`（新增，可选复现脚本）；`--only <case>` 可单独重跑 |
| 原始返回唯一真相源 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_r_20261107/raw_all.json`（含全部真实 CLI / HTTP 原始 JSON、exit code、复现命令） |
| 本轮独占新增文件 | `evidence/uc04_package_probe.json`、`evidence/uc15_step7_real.json`、`evidence/uc16_incremental_real.json`、`evidence/uc18_compile_feedback_real.json`、本报告、`tools/run_batch3_real_machine.py`、`tests/unit/test_greenfield_batch3_real.py`；`gateway/app/services/plc/tia_delivery.py` **仅新增** UC-18 编排函数 |

---

## 0. 判定摘要（诚实口径）

> **用户最关心的「回写博途 TIA V19 编译零错误」：本次在多个独立临时副本上拿到多组真实编译 `errorCount=0 / warningCount=0 / state=Success`**（UC-15 步骤 7 Action B、UC-16 三次增量、UC-18 修正后复编译、UC-04 探针编译），全部来自真实 CLI / HTTP 原始返回。
> **但这不等于「Greenfield 端到端全链编译零错误」，更不等于 L2/L4 通过或 M4 可签署。**

逐条边界：

- UC-15 步骤 7（`run_action_b` 注入真机 `SessionModeTiaPort`）：`compile_ok=true`、`error_count=0`、`.zap19` 真实归档、结构化报告齐全 —— **真机项 pass**（产品仍返回 `l2_status=pending_real_machine`，N9 口径）。
- UC-16 三次增量：`/open=1`、句柄复用、3× 编译 `0/0`、PCEC 3 条、六字段真实值、`tia_side_drift=0` —— **本次新实测 pass**（增量 fidelity 口径仍有缺口，见 §4）。
- UC-18：注入 1 个 **SCL 语法错误** → 编译 `errorCount=2` → 诊断定位 → 修正 SCL → 复编译 `errorCount=0`，三段真实诊断 + 账本引用 —— **真机项 pass**（首次过程性失败如实留痕）。
- UC-04 包级：`SW.PlcBlockGroup XML` **确证不可经 import-xml 导入**；完整 AF 包的 **Call 网络 OB 导入失败**（本次新发现的模板参数约束）。**完整 AF 包「含 Call 网络 OB 联合导入编译零错误」未达成**，`xml_package_unverified` **仍须保持 True**。

- **不宣称 L2 / L4 通过、不宣称「Greenfield 全链编译零错误」、不宣称 M4 通过或代签**；`xml_package_unverified` 未擅自改 `False`；证据台账（`rtm.json` / `pending_real_machine.json` / `acceptance_template.json` / Q、M 既有证据文件）一律未改。

---

## 1. 环境、方法与安全合规

### 1.1 环境（沿用 F 实测，仅做一次 status 健康检查）

`--cli status` 本次真实返回：`opennessAvailable=true`、`opennessGroupInToken=true`、`tiaVersion=V19`、`connected=false`、`projectOpen=false`（原始返回见 `raw_all.json` 生成前的一次性预检，STEP 7 许可有效性由本次多组真实编译 `state=Success` 再次印证）。**未重复探测环境四件套。**

### 1.2 方法

- **one-shot CLI 链**（R1 包级、R4 编译回喂）：每条 `TiaOpenness.Server.exe --cli <cmd>` 独立进程自行 open / 操作 / save / close；`import-xml` 内部 `SaveProject()` 持久化，后续 `compile-plc` 重新打开可见（F/K 已实证）。
- **serve 常驻会话**（R2/R3）：每 case 独立副本 + 一个 `serve --host 127.0.0.1 --port 8791`，`POST /open` 一次保持会话；`SessionModeTiaPort` 包装 `openness_session` 的 `/open`、`/fast-writeback`、`/compile-plc`、`/save`；运行时包装记录每次真实 HTTP 原始返回（不改源码）。R2 走 `greenfield_service.run_action_b`，R3 走 `tia_delivery.run_incremental_writebacks`。
- **编译数字**取自 `/compile-plc` 真实返回 `{"ok":true,"scope":"full_software","compile":{"ok":true,"apiAvailable":true,"state":"Success","errorCount":0,"warningCount":0,...}}`，经产品 `build_compile_diagnostics` / `_compile_verdict` 归一为结构化诊断（warning 单列、不并入成功）。

### 1.3 安全规则逐条落实

| 规则 | 落实 |
|---|---|
| 只在 `Temp/gf_real_*` 临时副本操作 | 全部在 `gf_real_r_20261107/`，每 case 独立副本；源项目仅 `shutil.copytree` 读取 |
| 禁止打开/写回 `PLC_Openness_data/` 原始 `.ap19/.zap19` | 从未打开；无 `SaveProject()` 写回原始路径；未删除任何原始文件 |
| 每个真机子进程超时 | 每条 CLI `subprocess.run(timeout=300)`；HTTP 独立超时（`/open`、编译 300s，其余 180s）；预检/复现命令附 `timeout -k 5 180` |
| `serve` 用完停止、不遗留 | 每个 case `finally` 里 `POST /close` + `terminate/kill` + 端口复查；R2/R3 `serve_stop.leftover_process=false`，全局 `serve_leftover_after_all=false` |
| 禁止 git 操作 | 0 次 |
| 禁止改冻结清单 / 白名单基线 / C# 源码 | 41 个冻结文件、`legacy_baseline.json`、`test_greenfield_legacy_guard.py`、`FastWriteback.cs` 等未触碰；`tia_delivery.py` 仅追加 UC-18 函数、未新增任何 import |
| D12 hard refuse | 无在线下载 / online / run-stop / compare-to-PLC、无 F-block/Safety、无 UI 自动化；全程 `withoutUi` 工程侧离线 |
| 禁止伪造数字 | 所有 `errorCount` / `warningCount` / `state` / exit code / PCEC 条数 / sha256 均来自真实 CLI/HTTP 原始返回，集中归档于 `raw_all.json`，本报告附复现命令 |

---

## 2. 逐 UC 真实结果

### 2.1 R1 · UC-04 包级 K1 复测 → `evidence/uc04_package_probe.json`

**成功项（真机证据）**

| 项 | 路径 | 真实返回 |
|---|---|---|
| 文件夹清单可经 API 建立 | `--cli create-block-group --group AF_Unit_01/AF_EM_01` | `ok=true, saved=true, exit=0`（第二组 `AF_Unit_01/AF_EM_02` 同） |
| 探针后项目未破坏 | `--cli compile-plc` | `errorCount=0 / warningCount=0 / state=Success` |
| 完整 AF 包 4 个空网络 OB | `--cli import-xml --kind auto` 逐个 | 4× `ok=true`（`GF_U1_Startup/1000`、`GF_U1_Main/1001`、`GF_U1EM1_Startup/1010`、`GF_U1EM1_Main/1011`） |
| 联合编译（当前可导入子集） | `--cli compile-plc` | `errorCount=0 / warningCount=0 / state=Success` |

**失败项（如实记录，不掩盖）**

| 项 | 真实返回（原始 JSON） | 结论 |
|---|---|---|
| `SW.PlcBlockGroup XML` import（`--kind auto`） | `exit=4, ok=false, openness_error`: `Class of the 'Siemens.Engineering.SW.PlcBlockGroup' type at line number 7 ... is not supported.` | **确证不可作为 SimaticML 块对象导入** |
| `SW.PlcBlockGroup XML` import（`--kind block`） | 同上 `exit=4, ok=false` | 显式块路径同样拒绝 |
| 完整 AF 包 Call 网络 OB `GF_U1EM1_CallOB` | `exit=4, ok=false, openness_error`: `Cannot create the 'SW.Blocks.CompileUnit' object ... The name 'GF_U1EM1_InstDB' cannot be used for "Call" at the object with UID '21'.` | **导入阶段即失败、未进入项目**；暴露自产 Call 网络 OB 对 `call_db` 命名的约束（本次 `call_db` 无 `_DB` 后缀，`_render_call_network` 无法剥离合法 FB 名）。与 K caseB（`import.ok=true`、编译 `errorCount=2`）性质不同，如实标注差异 |

> **关键诚实口径**：R1b 的联合编译 `0/0` 是在 **Call 网络 OB 导入失败、未进入项目** 的前提下取得（仅 4 个空网络 OB 生效）。**「含至少一个 Call 网络 OB 的完整 AF 包联合导入 + 编译零错误」未达成**，绝不把该 `0/0` 包装成完整包编译通过。

**复现命令**（Git Bash，完整版见 evidence `repro_commands`）：

```bash
R="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"; EXE="$R/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe"
timeout -k 5 180 "$EXE" --cli import-xml --project <Temp/R1a-blockgroup/proj/CanvasE2E.ap19> --xml <r1_SW_PlcBlockGroup.xml> --kind auto
timeout -k 5 180 "$EXE" --cli create-block-group --project <...> --plc PLC_1 --group AF_Unit_01/AF_EM_01
cd "$R" && ./.venv/Scripts/python.exe -c "from gateway.app.services.plc.tia_delivery import _render_ob_xml; ...（生成 5 个 OB）"
逐个 timeout -k 5 180 "$EXE" --cli import-xml --kind auto ; timeout -k 5 180 "$EXE" --cli compile-plc --project <...> --plc PLC_1
cd "$R" && ./.venv/Scripts/python.exe tools/run_batch3_real_machine.py --only R1a-blockgroup  # 或 R1b-package
```

原始 JSON 索引：`raw_all.json#cases/R1a-blockgroup`、`#cases/R1b-package`。

### 2.2 R2 · UC-15 步骤 7 真机 → `evidence/uc15_step7_real.json`

以 Action A 的 `fidelity_ok=true`（UC-17 前置，引用 Q 的 `uc15_evidence_bundle.json#fidelity_ok` 离线 L1 真实值）为前提，`confirmed=true`（D11 差异清单显式确认），在临时副本上走 `open_project → fast_writeback(overwrite=True) → compile_plc → save_project`。

| 工件 | 真实结果 |
|---|---|
| `step_order` | `open_project → fast_writeback → compile_plc → save_project` |
| **结构化编译报告** | `status=compiled`、`error_count=0`、`warnings=[]`（单列）、`blocks=[]`、`elapsed_ms≈1034.01`、`tia_version=V19`、`project_path=<Temp副本.ap19>`、`static_gate_passed=true`、`compile_ok=true`；`l2_status=pending_real_machine`、`pending_real_machine=true`、`xml_package_unverified=true` 如实保留 |
| **`.zap19` 归档** | `archive-project` 真实产物 `Temp/gf_real_r_20261107/r2_archive/CanvasE2E_step7.zap19`，`exists=true`、`sha256=033e7dc00a85c7813475b57e81d0070410a574bac89db2aac8a3e69eb38b9114`、`bytes=326869`、`archive_cli_ok=true`（serve 停止后执行，项目文件解锁） |
| **PCEC 账本** | Action B（首次写入，`mode=full`）本身增量账本 `count_on_disk=0`（诚实）；EvidenceBundle 的 `pcec_ledger` 工件对应增量 3 条由 UC-16 产出，见 `uc16_incremental_real.json#pcec_ledger` |
| D11 负例 | `confirmed=false` → `blocked=true`、`code=GF_ACTION_CONFIRM_REQUIRED`、`zero_side_effects=true`（不写 TIA） |

`missing_artifacts_now_filled` 字段给出主 agent 可直接补进 `uc15_evidence_bundle.json` 的 3 项缺项（`structured_compile_report` / `zap19_archive` / `pcec_ledger`）的 `present=true` + `evidence_ref` + 真实值，**不补假数据**。

复现：`cd <R> && ./.venv/Scripts/python.exe tools/run_batch3_real_machine.py --only R2-action-b`；原始 JSON 索引 `raw_all.json#cases/R2-action-b`。

### 2.3 R3 · UC-16 §13.9 六条增量（L4 证据）→ `evidence/uc16_incremental_real.json`

**本次新实测**（在 M 方法学基础上的新一次真机运行）：

| 项 | 真实值 |
|---|---|
| `/open` | `open_call_count=1`、`handle_reused=true` |
| 三次差异清单 D11 | 3 条显式确认（改 EM 步序 / 新增 CM / 改交互连线，等价 SCL 外部源变体）→ 覆盖 → 编译 |
| 三次编译 | 3× `errorCount=0 / warningCount=0 / state=Success` |
| 项目未关闭/未重载/未新建 | `close=0 / create=0 / archive=0`，`health_openProject` 全程唯一 |
| **PCEC** | `pcec_count=3`，`change_ids=[chg-b8821cd188c9, chg-b92d7051fa6c, chg-e77be136b2a0]`，磁盘 `count_on_disk=3`（3/3） |
| G 编排 | `ok=true, status=ok, mode=incremental, increment_count=3, l2_status=pending_real_machine` |

**增量 EvidenceBundle 六字段真实值**：

| 字段 | 真实值 |
|---|---|
| `mode` | `incremental` |
| `base_spec_version` | `null`（诚实：本次未跑 Greenfield 冻结规格链，无真实 `specs/vN.json` 产物，不冒充） |
| `changed_source_ids` | `["R_FC_Inc1","R_FC_Inc2","R_FC_Inc3"]` |
| `reverse_protection` | `{allowed:true, drift_count:0, tia_side_drift:0, blocked_source_ids:[], reason:"TIA 侧块哈希与上次生成物一致,允许增量覆盖(D10 反向保护通过)"}`（产品纯函数 `check_reverse_guard` 对真实块内容哈希快照计算，非 mock） |
| `tia_side_drift` | `0` |
| `ob_number_deviations` | `[]`（**显式留痕、不静默**：本次增量块为 FC 外部源，不涉及 OB 编号物理偏差） |

`fidelity_ok`：引用 Q 的 `uc15_evidence_bundle.json#fidelity_ok=true`（离线 L1 全量逻辑等价真实值），并明确「本次无真实 Greenfield 冻结规格链产物、增量 `FidelityChecker(mode=incremental)` 未闭环」，不冒充、不宣称 §13.9 增量 fidelity 已闭环。N9：`fidelity_ok` 与 `compile_ok` 严格分离，L4 的「每次 `error_count==0`」由三次真实编译承担。

**引用 M 既有证据（本次不重做，已注明）**：D10 负例 `uc05_real_machine_report.json#cases/UC-12`（`allowed=false, tia_side_drift=1`、第 4 次增量 `attempted=false/blocked=true/routes_called=[]`）；UC-13 回滚演练 `#cases/UC-13`（`ap19_unchanged_after_failed_import=true`、备份 `matches_pre_write_sha256=true`）。

复现：`cd <R> && ./.venv/Scripts/python.exe tools/run_batch3_real_machine.py --only R3-incremental`；原始 JSON 索引 `raw_all.json#cases/R3-incremental`。

### 2.4 R4 · UC-18 编译错误回喂 → `evidence/uc18_compile_feedback_real.json`

**新通道派生层**：`gateway/app/services/plc/tia_delivery.py` **仅新增**纯编排函数 `compile_feedback_heal(...)`（接收结构化 `CompileDiagnostics` → 定位错误块/行 → 生成可复现修正建议 → 触发复编译回调 → 返回「注入前/失败/修正后」三段诊断 + 账本引用）。**未新增任何 import**（`test_sanctioned_phase2_module_whitelist` PASS）、原样保留 G 会话模式与 K XML 修复代码、未改冻结的 `writeback_heal.py` / `compile_jobs.py` / `scl_precheck.py`。

**真机三段（全部来自真实 `--cli compile-plc` 原始返回）**：

| 段 | 动作 | 真实 `errorCount` / `state` |
|---|---|---|
| 注入前 | 干净副本编译 | `0` / `Success`（`warningCount=0`） |
| 失败 | 注入 1 个 **SCL 语法错误**（`R_FC_BadSyntax.scl` 的 BEGIN 段非法 token `@@@BAD_SCL_SYNTAX@@@`，`generate-from-source` 生成不一致 FC）→ 编译 | `2` / `Error`，`inconsistentBlocks=["R_FC_BadSyntax"]`，`message="Compile State=Error errors=2 warnings=0"` |
| 修正后 | 修正为合法 SCL（`R_FC_BadSyntax_fixed.scl`，`#tmp := 1;`）→ `generate-from-source(overwrite)` → 复编译 | `0` / `Success`（`warningCount=0`） |

`compile_feedback_heal`：`heal_ok=true`、`located_errors.blocks=["R_FC_BadSyntax"]`、`fix_proposal.target_blocks=["R_FC_BadSyntax"]`、`ledger_ref=evidence/uc18_compile_feedback_real.json#heal`；账本可追溯（坏/修 SCL sha256、三段原始返回索引）。warning 单列、不并入 `compile_ok`。

**首次过程性失败（如实留痕、不隐瞒）**：首跑脚本编排缺陷（坏 FC 未修正 + 混入 Call 网络 OB 注入）导致三段恒为 `{2,2,2}`、`heal_ok=false`、`status=fail`。原始返回完整保留于 `raw_all.json#cases/R4-compile-feedback-first-attempt`；修正链路后 `--only R4-compile-feedback` 重跑 `status=pass`。属过程性失败，非真机能力缺失。

**离线单测**：`tests/unit/test_greenfield_batch3_real.py` `7 passed`，仅验证编排结构与诚实口径，**不计入真机证据、不冒充三段诊断**。

复现：`cd <R> && ./.venv/Scripts/python.exe tools/run_batch3_real_machine.py --only R4-compile-feedback`；原始 JSON 索引 `raw_all.json#cases/R4-compile-feedback`。

---

## 3. `xml_package_unverified` 处置建议（**不擅自改 False**）

> **建议：仍须保持 `xml_package_unverified = True`。本 Agent 未改产品代码任何标志位赋值，仅给结论与依据，由主 agent 收口决定。**

依据（全部来自本次 UC-04 包级真实结果）：

1. **`SW.PlcBlockGroup XML` 已真机确证不可经 `import-xml` 导入**（`openness_error: ...PlcBlockGroup type ... is not supported`，`exit=4`）。整个 `xml_supplement` 包不能标为「已验证可导入」，只能降级为「OB XML 可导入（K 已证）+ 文件夹清单须经 `create-block-group` API 建立」。
2. **完整 AF 包的 Call 网络 OB 导入阶段即失败**（本次新发现的 `call_db` 命名约束：`The name 'GF_U1EM1_InstDB' cannot be used for "Call"`），含 Call 网络 OB 的完整包联合编译零错误未达成。
3. 本轮为临时副本上的包级探针 / 联合导入，**非 `deliver_tia` auto 通道端到端全链**（UC-15/16/18 由本批次其它 case 承担，端到端全链仍待主 agent 收口）。
4. 契约 §0 / §5：消除须以 UC-04 包级真实结果为唯一依据，且由主 agent 收口决定；任何 agent 不得擅自改 `False` 或代签 M4。

---

## 4. `L1∧L2∧L3∧L4` 逐层判定所需证据是否齐备

> 判定规则：只有拿到真实证据的层才考虑 `pass`；**本 Agent 不标任何层 pass，最终判定由主 agent 收口**。

| 层 | 本次 / 前序真实证据 | 仍缺 / 边界 | 齐备性 |
|---|---|---|---|
| **L1 逻辑等价** | Q 离线全量 `fidelity_ok=true`（`uc15_evidence_bundle.json`）、四视图/连线清单/静态门禁离线实例化 | `coverage==1.0 / orphan==0 / drift==0` 的 `fidelity_report.json` 完整校验链、UC-08/09/10/11、UC-15 端到端全链闭环 | **部分齐备**（引用 Q，主 agent 收口） |
| **L2 可编译** | 本次多组真实编译 `errorCount=0`（R2 Action B、R3 三次增量、R4 复编译、R1 探针）+ `static_gate_passed=true` + UC-02/03 口径（M 既有） | **UC-04 包级 Call 网络 OB 导入失败**、`xml_package_unverified=True`、G 编排返回 `l2_status=pending_real_machine`、四层静态门禁全绿收口 | **证据接近齐备但有明确缺口**：不据真机编译宣称 L2 通过 |
| **L3 可复现** | Q 九步步骤 8：同冻结 spec 两次产物哈希一致（`evidence_bundle_sha256_equal=true`、`zip_sha256_equal=true`、`artifact_hashes_equal=true`，引用 `nine_steps_offline_run.json`） | 本次未新跑重启恢复 FROZEN vN（UC-06/07/14 离线部分由主 agent 收口） | **引用既有**（主 agent 收口） |
| **L4 增量可迭代** | 本次 R3：`/open=1` + 3× `errorCount=0` + PCEC 3 条 + 句柄复用 + 未重载 + 六字段真实值 + `tia_side_drift=0`；D10 负例 / UC-13 回滚引用 M | **增量 `fidelity_ok` 未由 Greenfield 冻结规格链闭环**（`base_spec_version=null`、引用 Q 离线 L1）、§13.9 每次 `fidelity_ok` 口径、UC-16 增量 EvidenceBundle 正式归档 | **大部分齐备、增量 fidelity 口径未闭环**：G1 地基 ≠ L4 完整通过，不宣称 L4 通过 |

> 复核结论：`L1∧L2∧L3∧L4` **未全绿** → **`M4 未通过 / 不可签署`**。UC 主状态 `pass` ≠ L 层通过 ≠ M4 可签署。

---

## 5. M4 与 P0-D

- **M4**：签署栏始终「**待用户签署**」。本批次最多把结论推进到「证据齐备 / 待用户签署」；**任何 agent 不得把 `m4_signable` 置 true 并宣称 M4 通过**。本 Agent **未代签、未改 `rtm.json` / `pending_real_machine.json` / `acceptance_template.json`**（台账由主 agent 收口统一更新）。
- **P0-D**：用户已于 2026-11-06 以编号「1」正式拍板 **坚持「AF Basic 文件夹版」，暂不切「软件单元版」**（`06-gate0-report.md` §7、`11-p0d-decision.md`、Gate0 归档 §10）。**P0-D 是用户结论，本 Agent 只做记录与执行，不重新论证、不代拍**；映射层文件夹版口径不变、`framework_baseline` 语义不变。

---

## 6. 复用 / 引用 F、K、M、Q 证据清单（区分「本次新实测」与「引用既有」）

| 来源 | 性质 | 内容 |
|---|---|---|
| **本次新实测（Agent R）** | 真机 | UC-04 包级（`SW.PlcBlockGroup` 导入失败、`create-block-group` 成功、完整 AF 包联合导入/编译）；UC-15 步骤 7（Action B 编译 0/0、`.zap19` sha256、结构化报告、D11 负例）；UC-16 三次增量（六字段、PCEC 3 条、`tia_side_drift=0`）；UC-18 SCL 注入/修正/复编译三段诊断；`status` 预检一次；R4 首次过程性失败留痕 |
| **引用 Q（既有）** | 离线实例化真实响应 | `uc15_evidence_bundle.json`（12 项工件缺 3 项、`fidelity_ok=true`、spec_hash）；`nine_steps_offline_run.json`（步骤 1–6/8/9、步骤 7 `pending_real_machine`、产物哈希一致） |
| **引用 M（既有）** | 真机（批次 2） | `uc05_real_machine_report.json#cases/UC-12`（D10 负例）、`#cases/UC-13`（回滚演练）、`#cases/UC-05`（三次增量 P0-G 方法学）；`10-real-machine-acceptance.md`（serve 会话、PCEC 核对、`tia_unavailable` 口径） |
| **引用 K（既有）** | 真机探针（批次 2） | `08-k1-probe-fix.md`（`_render_ob_xml` 修复方式：culture 仅 `zh-CN`、空网络 `<NetworkSource />`、`FlgNet/v5` Call 网络；caseA 编译 0/0、caseB 编译 `errorCount=2` 的事实）—— 本轮 R1/R4 直接复用其生成方式与复现命令 |
| **引用 F（既有）** | 真机归档（批次 2） | `research/Gate0_环境与档位实测_2026-11-06.md`（环境四件套、CLI 命令、`create-block-group` 3× 成功、`--cli status`）、`06-gate0-report.md` §7（P0-D 用户拍板） |

> 注：UC-04 本次新实测的 Call 网络 OB 失败与 K caseB 事实并列留痕（失败阶段不同：本次导入即拒绝、K 导入成功而编译报错），不互相掩盖。

---

## 7. 单测结果（离线，不连真机）

指定子集（含新增单测）：

```
cd <R> && ./.venv/Scripts/python.exe -m pytest \
  tests/unit/test_greenfield_tia_delivery.py \
  tests/unit/test_greenfield_session_mode.py \
  tests/unit/test_greenfield_legacy_guard.py \
  tests/unit/test_greenfield_batch3_real.py -q
```

结果：**`33 passed`**（其中 `test_frozen_legacy_files_have_zero_diff` 零 diff 护栏 PASS、`test_sanctioned_phase2_module_whitelist` PASS、新增 `test_greenfield_batch3_real.py` 7 passed）。**未跑全量 pytest**（主 agent 收口统一跑）。离线单测不构成 L2/L4 证据、不宣称真机编译零错误。

---

## 8. 已知遗留（诚实清单）

1. **`xml_package_unverified` 仍保持 `True`**：`SW.PlcBlockGroup XML` 不可导入、完整 AF 包 Call 网络 OB 导入失败，包级/全链未闭环（见 §3）。
2. **UC-04 完整 AF 包（含 Call 网络 OB）联合导入编译未达成**：Call 网络 OB `import-xml` 阶段即失败；需修正自产 `_render_call_network` 的 `call_db` 命名约束或补齐被引用实例 DB 后重测。
3. **L1 / L3 离线链、UC-15 端到端全链、UC-16 增量 `fidelity_ok`（Greenfield 冻结规格链）未闭环**：`base_spec_version=null`、增量 `FidelityChecker` 未计算（引用 Q 离线 L1 真值并标边界）。
4. **L2 / L4 层判定仍 `pending`**：G 编排返回 `l2_status=pending_real_machine`、`pending_real_machine=true`；产品 `compile_diagnostics` 的 `pending_real_machine=true` 如实保留，不静默消除。
5. **M4 未通过 / 不可签署**：`L1∧L2∧L3∧L4` 未全绿、pending 台账未清零（由主 agent 收口）；本 Agent 未改任何证据台账。
6. **PCEC 口径**：UC-15 步骤 7（Action B，首次 `mode=full`）增量账本 0 条，增量 3 条来自 UC-16；主 agent 补 `uc15_evidence_bundle.json#pcec_ledger` 时须注明来源。
7. **R4 首次过程性失败**：三段恒为 `{2,2,2}` 的原始返回保留在 `raw_all.json#cases/R4-compile-feedback-first-attempt`；重跑 pass 不掩盖首次失败。
8. **无原生含 warning 的真机编译样本**：warning 单列口径由产品 `evaluate_compile` 纯函数验证（M 既有），三段编译 `warningCount` 均为 0。
9. **culture 收敛 `zh-CN` 的适用边界**（K §7）：对含 `zh-CN` 的中文项目已验证；纯英文/其它语言项目未测。
10. **本机 CPU 具体型号未由实验直接读取**（沿用 F 推断：经典 S7-1200 类，不支持软件单元）；与用户 P0-D 文件夹版拍板一致。

---

## 9. 合规与诚实口径声明

- 真机操作**只在** `C:/Users/vboxuser/AppData/Local/Temp/gf_real_r_20261107/` 临时副本上进行；`PLC_Openness_data/` 原始 `.ap19/.zap19` 仅被 `cp`/`copytree` 读取，从未打开、从未 `SaveProject()` 写回原始路径、未删除任何原始文件。
- 每个真机子进程/HTTP 调用有超时保护；每个 `serve` 常驻进程 `POST /close` + `terminate/kill` + 端口复查，`leftover_process=false`、全局 `serve_leftover_after_all=false`。
- **所有编译/导入数字均来自真实 CLI / HTTP 原始返回**，集中归档于 `raw_all.json` 并在本报告附复现命令；**未伪造任何 `errorCount` / `warningCount` / `state` / exit code / PCEC 条数 / sha256**（UC-04 Call 网络 OB 导入失败、R4 首次过程性失败均如实记录）。
- 未以 mock / 离线单测宣称 `L2/L4` 通过、未宣称「Greenfield 全链编译零错误」、未把 `tia_unavailable` / `pending_real_machine` 说成成功、未把 UC 主状态 `pass` 说成 L 层通过或 M4 可签署。
- D12 hard refuse 全程约束；N9 `fidelity_ok` 与 `compile_ok` 严格分离；warning 单列不并入成功；`ob_number_deviations` 显式留痕；`xml_package_unverified` 未擅自改 `False`。
- **未执行任何 git 操作**；未改冻结清单 41 文件、`legacy_baseline.json`、`test_greenfield_legacy_guard.py`、C# 源码、`greenfield_service.py` / `greenfield.py` 路由、前端、`plc_engine/af/`、`industrial/`；`tia_delivery.py` 仅追加 UC-18 编排函数、未新增 import。
- **P0-D 档位结论为用户拍板，本 Agent 未代拍；M4 未代签。**
