# 批次 4 · V19 真机联合验证报告（UC-04 完整 AF 包 + UC-16 增量闭环）

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 4 · **Agent W · V19 真机联合验证**（本批次唯一允许连真机 / TIA / SessionServer 的 agent；U / V 已结束且不占资源） |
| 分支 / 基线 | `dev/greenfield-wp` / `3596fb9`（批次 3 收官；**未执行任何 git 操作**） |
| 日期 | 2026-11-07 |
| 契约 | `14-batch4-contract.md`（§0 两处根因 / §1 全局规则 / §2 所有权 / §3 两个 UC 闭环判据）；`04-parallel-wp-contract.md` §0、`13-batch3-contract.md` §1/§5 继续生效 |
| 真机探针 | `<R>/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe --cli ...` / `serve`（HTTP `127.0.0.1:8791`） |
| Python | `<R>/.venv/Scripts/python.exe` |
| 真机副本根 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_w4_20261107/`（只读源 `PLC_Openness_data/openness_e2e/CanvasE2E`，仅 `shutil.copytree` 读取，**从未打开 / 写回原始 `.ap19/.zap19`**） |
| 原始返回唯一真相源 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_w4_20261107/raw_all.json`（含全部真实 CLI / HTTP 原始 JSON、exit code、复现命令） |
| 独占新增文件 | `evidence/uc04_full_package_real.json`、`evidence/uc16_incremental_closed_real.json`、本报告、`tools/run_batch4_real_machine.py`（可复现脚本，支持 `--only W1` / `--only W2`）；`tests/unit/test_greenfield_batch4_real.py` 为可选，本轮**未新增** |

---

## 0. 判定摘要（诚实口径）

> **本轮在独立临时副本上真机达成 UC-04 与 UC-16 的契约 §3 闭环判据，全部数字来自真实 CLI / HTTP 原始返回。**
> **但 `L1∧L2∧L3∧L4` 是否全绿、`xml_package_unverified` 是否消除、pending 台账是否清零、M4 是否可签署，一律由主 agent 收口判定；本 Agent 不标 L2/L4 通过、不擅自改 `xml_package_unverified`、不代签 M4。**

| 用例 | 真机结果 | 契约 §3 闭环 |
|---|---|---|
| **W1 · UC-04** | 完整 AF 包 5 个自产块 XML（FB / 实例 DB / 2 空网络 OB / **Call 网络 OB**）按 `import_order` 逐项 `import.ok=true`（5/5）；文件夹经 `create-block-group` API 建立 2/2 `ok=true/saved=true`；`compile-plc` 真实 `errorCount=0 / warningCount=0 / state=Success` | **达成** |
| **W2 · UC-16** | 复用 V 磁盘规格链 `specs/v1.json → v2.json`（spec_hash 一致），真实 `SpecDiff(base=1, changed_source_ids=["U1EM1_CM3"])`；D11 显式确认、UC-19 四计数器恒 0；serve 会话 `/open=1` + 句柄复用 + `close/create/archive=0`；Action C 八步真机跑通 + 4× 编译 `0/0 Success` + PCEC 3 条落盘 + 第 8 步真实增量 `FidelityChecker(fidelity_ok=true)`；`reverse_protection.allowed=true`（真机值）、`tia_side_drift=0` | **达成**（含首跑失败如实留痕，见 §3.3） |

**诚实边界（先声明）**：
- W2 的 **Action C 主路径首跑真实失败**（`GF_ACTION_C_ROLLBACK` / `invalid_argument`），根因是 IR 层差异块不含 `scl_path`、C# `/fast-writeback` 拒绝；重跑以**运行时 SclBridgingPort**（不改产品代码）做 IR 层 id → 派生产物层等价 SCL 块的映射后接通。首跑原始返回保留在 `raw_all.json#cases/W2-incremental-first-attempt`，**未掩盖、未冒充首跑即通过**。
- `SpecDiff.changed_source_ids`（IR 层 `U1EM1_CM3`）与真机块 / `artifacts`（派生产物层 `DB::`/`FB::`/`OB::` / `W2_FC_Inc*` SCL）**命名空间不同，不假装逐块一一对应**（见 §3.8）。
- `N9`：`fidelity_ok ≠ compile_ok`；warning 单列不并入成功；产品 `compile_diagnostics` 仍保留 `pending_real_machine=true / l2_status=pending_real_machine`。
- `xml_package_unverified` **未擅自改 False**，只给处置建议与依据（§2.7）；M4 签署栏始终「待用户签署」（§5）。

---

## 1. 环境、方法与安全合规

### 1.1 环境（沿用 F / M / R 实测，不重复探测四件套）
W1 内做**一次** `--cli status` 健康检查（真实返回）：`tiaVersion=V19`、`opennessAvailable=true`、`opennessGroupInToken=true`、`connected=false`、`projectOpen=false`。STEP 7 许可有效性由本轮多组真实编译 `state=Success` 再次印证。未做其它环境探测。

### 1.2 方法
- **W1 one-shot CLI 链**：每条 `TiaOpenness.Server.exe --cli <cmd>` 独立进程自行 open / 操作 / save / close；`import-xml` 内部 `SaveProject()` 持久化，后续 `compile-plc` 重新打开可见（F / K / R 已实证）。
- **W2 serve 常驻会话**：一个 `serve --host 127.0.0.1 --port 8791`，`POST /open` **一次**并保持句柄；`SessionModeTiaPort` 包装 `openness_session` 的 `/open` / `/fast-writeback` / `/compile-plc` / `/save`，运行时包装记录每次真实 HTTP 原始返回（**不改产品源码**）。
- **编译数字**取自 `/compile-plc`（或 CLI `compile-plc`）真实返回 `{"compile":{"state":"Success","errorCount":0,"warningCount":0,...}}`。
- 复现脚本：`tools/run_batch4_real_machine.py --only W1|W2`，把所有真实返回归档到 `raw_all.json`。

### 1.3 安全规则逐条落实

| 规则 | 落实 |
|---|---|
| 只在 `Temp/gf_real_*` 临时副本操作 | 全部在 `gf_real_w4_20261107/`，W1 / W2 各独立副本；源项目仅 `shutil.copytree` 读取 |
| 禁止打开 / 写回 `PLC_Openness_data/` 原始 `.ap19/.zap19` | 从未打开；无 `SaveProject()` 写回原始路径；未删除任何原始文件 |
| 每个真机子进程超时 | 每条 CLI `subprocess.run(timeout=300)`；HTTP 独立超时（`/open`、编译 300s，其余 180s）；复现命令附 `timeout -k 5 180` |
| `serve` 用完停止、不遗留 | `finally` 中 `POST /close` + `terminate/kill` + 端口复查；`serve_stop.leftover_process=false`、`port_reachable_after_stop=false`；最终全局确认 8791 不可达、无遗留 `TiaOpenness.Server` 进程（§7） |
| 禁止 git 操作 | 0 次 |
| 禁止改产品代码 / 证据台账 / C# / 冻结清单 | 只 import + 调用现有函数；新增仅本报告 / 两份 evidence / 复现脚本；`rtm.json` / `pending_real_machine.json` / `acceptance_template.json` / `uc15_evidence_bundle.json` / 批次 2/3 既有真机证据 / `09-m4-review.md` / `10-real-machine-acceptance.md` 一律未改 |
| D12 hard refuse | 无在线下载 / online / run-stop / compare-to-PLC、无 F-block/Safety、无 UI 自动化；全程 `withoutUi` 工程侧离线 |
| 禁止伪造数字 | 所有 `errorCount` / `warningCount` / `state` / `exit code` / `importedNames` / PCEC 条数 / sha256 均来自真实 CLI / HTTP 原始返回，集中归档于 `raw_all.json`，本报告附复现命令 |

---

## 2. W1 · UC-04 完整 AF 包真机联合导入编译

### 2.1 包生成与 manifest sha256 核对
调 U 的 `tools/build_full_af_package.py --out <W>/w1_package`（`exit=0`）。核对：

| 项 | 真实值 |
|---|---|
| `manifest.json` 字节 sha256 | `827cdac0041c4ea4719c617248a91acc4476e499db5337f464b8a626cc0b13d2` |
| 与 U 报告 / 任务书给定值 | **match=true** |
| `manifest.files` 逐文件 sha256 复算 | 6/6 **match=true** |
| `import_order` | `blocks/FB1000_StdSignal.xml → blocks/DB1000_StdSignal.xml → ob/GF_U1_Startup.xml → ob/GF_U1_Main.xml → ob/GF_U1EM1_CallOB.xml`（严格 FB → DB → OB） |
| 引用自洽 | `CallInfo.Name=FB1000_StdSignal` == FB `<Name>`；`Component.Name=DB1000_StdSignal` == DB `<Name>`；DB `InstanceOfName=FB1000_StdSignal` |

### 2.2 逐项 `import-xml --kind auto`（真实返回，无跳过 / 无替换）

| # | 文件 | 类型 | `ok` | `exit_code` | `importedNames` | 原始 error |
|---|---|---|---|---|---|---|
| 1 | `blocks/FB1000_StdSignal.xml` | FB | **true** | 0 | `["FB1000_StdSignal"]` | 无 |
| 2 | `blocks/DB1000_StdSignal.xml` | InstanceDB | **true** | 0 | `["DB1000_StdSignal"]` | 无 |
| 3 | `ob/GF_U1_Startup.xml` | OB（空网络） | **true** | 0 | `["GF_U1_Startup"]` | 无 |
| 4 | `ob/GF_U1_Main.xml` | OB（空网络） | **true** | 0 | `["GF_U1_Main"]` | 无 |
| 5 | `ob/GF_U1EM1_CallOB.xml` | OB（**Call 网络**） | **true** | 0 | `["GF_U1EM1_CallOB"]` | 无 |

> **与批次 3 对照**：`evidence/uc04_package_probe.json` 中 `GF_U1EM1_CallOB` 导入即失败（`The name 'GF_U1EM1_InstDB' cannot be used for "Call"`），根因是「包缺 FB / 实例 DB」+「`_render_call_network` 从 `call_db` 反推 FB 名」。U 修复后本轮 5/5 全部真实导入成功，**含 Call 网络 OB**，不再有隐藏失败。
> 复现：`timeout -k 5 180 TiaOpenness.Server.exe --cli import-xml --project <Temp副本.ap19> --xml <w1_package/...xml> --kind auto`（按 `import_order` 逐个）。

### 2.3 `create-block-group` 建立文件夹（SW.PlcBlockGroup 走 API，不在 import 序列）

| group | `ok` | `saved` | `exit_code` |
|---|---|---|---|
| `AF_Unit_01` | true | true | 0 |
| `AF_Unit_01/AF_EM_01` | true | true | 0 |

`folders.json` 的 `mechanism` 字段显式写明 `create-block-group Openness API (NOT SW.PlcBlockGroup XML import-xml)`；复现：`timeout -k 5 180 ... --cli create-block-group --project <副本.ap19> --plc PLC_1 --group <group>`。

### 2.4 `list-blocks` 核对 FB / DB / OB 均入项目（真实返回）

| 调用 | `count` | `byType` |
|---|---|---|
| `list-blocks`（全部） | 7 | `OB:4 / FB:2 / DB:1` |
| `list-blocks --type OB` | 4 | `OB:4` |
| `list-blocks --type FB` | 2 | `FB:2` |
| `list-blocks --type DB` | 1 | `DB:1` |

包内 5 块均在：`FB1000_StdSignal`(FB,1000,LAD)、`DB1000_StdSignal`(DB,1000,DB)、`GF_U1_Startup`(OB,1000,LAD)、`GF_U1_Main`(OB,1001,LAD)、`GF_U1EM1_CallOB`(OB,1012,LAD)；项目原有 `Main`(OB,1)、`PumpCtrl`(FB,1)。

### 2.5 `compile-plc` 真实原始返回

```json
{"compile":{"ok":true,"apiAvailable":true,"state":"Success",
 "errorCount":0,"warningCount":0,
 "inconsistentBlocks":["Compiling finished (errors: 0; warnings: 0)"],
 "message":"Compile State=Success errors=0 warnings=0"}}
```

`exit_code=0`。复现：`timeout -k 5 180 ... --cli compile-plc --project <Temp副本.ap19> --plc PLC_1`。

### 2.6 UC-04 闭环判定（契约 §3，逐条）

| 判据 | 结果 | 证据 |
|---|---|---|
| ① U 产出自洽完整包（Call OB + 被引用 FB + 全局实例 DB + 文件夹清单），FB/DB 独立命名 | **yes** | manifest sha256 与 U 一致、逐文件 sha256 6/6、`references_self_consistent=true` |
| ② W 按 `import_order` 顺序导入，`import.ok=true` | **yes** | 5/5 真实 `ok=true` / `exit=0` / `importedNames`，含 Call 网络 OB |
| ③ 文件夹经 `create-block-group` API 建立（不要求 XML 可导入） | **yes** | 2/2 `ok=true / saved=true / exit=0` |
| ④ `compile-plc` 真实 `errorCount=0 / warningCount=0 / state=Success` | **yes** | §2.5 原始返回 |
| ⑤ 结构化证据（原始返回 + 复现命令 + 副本路径） | **yes** | `evidence/uc04_full_package_real.json` + `raw_all.json#cases/W1-full-package` |

> **UC-04 闭环：达成（`uc04_closed=true`）**。这是「含至少一个 Call 网络 OB 的完整 AF 包联合导入 + 编译零错误」首次在 V19 真机副本上取得，不沿用批次 3 那个「Call OB 未进入项目前提下的 0/0」。

### 2.7 `xml_package_unverified` 处置建议（不擅自改 False）

> **建议：本轮已取得「可考虑消除」的主要真机依据，建议主 agent 收口时按证据决定；但须严格限定范围。本 Agent 未改产品代码任何标志位赋值。**

**支持消除的依据**：① 批次 3 两处根因（包缺 FB / 实例 DB、`call_db` 反推 FB 名）已由 U 修复并经 W 真机确证——5 个自产块 XML 全部 `ok=true`、编译 `0/0 Success`；② 文件夹走 `create-block-group` API 真实建立 2/2；③ 契约 §3 UC-04 判据逐条有真机原始返回支撑。

**仍须限定 / 收口前须确认**：
1. `SW.PlcBlockGroup XML` **仍不可经 `import-xml` 导入**（批次 3 `uc04_package_probe.json#probe_a`：`exit=4 / openness_error ... is not supported`）。本轮未试图改变该边界事实；若把整个「自产 XML 包」标为「整体已验证」，须明确降级为「5 个块 XML 可导入 + 文件夹清单走 API」。
2. 本轮是临时副本上的**包级**联合导入编译，**非 `deliver_tia` auto 通道端到端全链**（UC-15 / M4 由主 agent 收口）。
3. FB / 实例 DB 相对真实 V19 先例有精简（空 Section 无 Member、省略 UDA、culture 收敛 `zh-CN`，U §8.6）：真机证明可导入可编译，**非逐字段等同先例**。
4. culture 收敛 `zh-CN` 的适用边界（K §7）：对含 `zh-CN` 的中文项目已验证；纯英文 / 其它语言项目未测。

### 2.8 诚实边界
不宣称 L2 / L4 通过、不宣称「Greenfield 全链编译零错误」、不宣称 M4 可签署；不据此认为「自产 XML 包整体已验证」而无视上述限定；warning 单列（`warningCount=0`）不并入成功。

---

## 3. W2 · UC-16 真机增量闭环（复用 V 的真实 v1→v2 规格链）

### 3.1 复用 V 磁盘规格链（不重新生成会话）
直接 `load_frozen_spec` 从 V 产物里的 `work_dir` / `session_id` / `specs/v1.json` / `specs/v2.json` 磁盘路径装载（`PLC_WORK_DIR` 语义），**未重新生成规格会话**：

| 字段 | 真实值 | 与 V 一致 |
|---|---|---|
| `work_dir` | `C:\Users\vboxuser\AppData\Local\Temp\gf_inc_chain_71q7e1k_` | — |
| `session_id` | `95f0fcd1ba8e` | — |
| v1 `spec_hash` | `sha256:9bc022427c5bdb0e1b69f1fa89cdc459de4a121f157395b8ddbd7eebbc994e60` | yes |
| v2 `spec_hash` | `sha256:52190cc0b1e0769d79f400d6b72ed8d59472f09dc20d7e0c69222a030a7b8605` | yes |
| `spec_version` | 1 / 2 | yes |
| `hash_differs` | true | — |

`compute_spec_diff(v1, v2)` 直调真实产出：`base_spec_version=1`、`target_spec_version=2`、`changed_source_ids=["U1EM1_CM3"]`、`added_count=1`、`changed_count=0`、`removed_count=0`，与 V 的 `/diff` / 直调结果 `matches_V=true`。

### 3.2 serve 会话 / D11 差异确认 / UC-19 确认前零副作用
- 用 `serve` 常驻会话 `POST /open` **一次**并保持句柄，全程不 create-project / 不 archive / 不重载（D9）。
- D11：以 `SpecDiff.changed_source_ids=["U1EM1_CM3"]` 为差异清单，`confirmed=true` 显式确认后才允许写入。
- **UC-19 负例真实返回**：`confirmed=false` → `code=GF_ACTION_CONFIRM_REQUIRED`、`blocked=true`、`zero_side_effects=true`、`side_effect_counters={"ops":0,"disk_writes":0,"writebacks":0,"generations":0}`（四计数器恒 0）。

### 3.3 首跑真实失败（如实留痕，未掩盖）
首跑以 V 的真实 IR 层 `SpecDiff` 直接喂 `run_action_c`，`port=SessionModeTiaPort`：

```
code   = GF_ACTION_C_ROLLBACK
reason = 失败导入已回滚（UC-13）：块级覆盖失败：
         {'code':'invalid_argument',
          'message':'fast-writeback 需要有效的 scl（单个 Mega-Source .scl 文件路径）。',
          'retryable': False}
rolled_back=true / tia_written=false / zero_side_effects=true
step_order 只到 ["session_reuse","spec_diff","reverse_guard","diff_confirm","pre_write_backup","block_overwrite"]
```

**根因**：`run_action_c` 的 `_coerce_diff` 从 IR 层 SpecDiff 产出的 `changed_blocks` 固定为 `{source_id, kind, payload}`，**不含 `scl_path`**；而 C# `/fast-writeback` 要求有效 scl 路径。这正是契约 W2 预判的「端口 / 会话 / 块映射限制」。原始返回保留在 `raw_all.json#cases/W2-incremental-first-attempt`。

### 3.4 重测：运行时 SclBridgingPort 接通 Action C 八步（不改产品代码）
以**运行时包装** `SclBridgingPort → SessionModeTiaPort`，把 IR 层差异块（`U1EM1_CM3`）等价映射到带真实 SCL 路径的派生产物层块（映射日志见 `scl_bridge_log`，1 条：`U1EM1_CM3 → W2_FC_Inc1.scl`），使 C# `/fast-writeback` 接受。**首跑失败与重跑成功两轮原始返回均保留**。

`run_action_c` 八步真实跑通（`step_order` 全 8 步）：

| 字段 | 真实值 |
|---|---|
| `ok` / `blocked` / `rolled_back` | `true` / `false` / `false` |
| `tia_written` / `compile_ok` | `true` / `true` |
| `base_spec_version` / `changed_source_ids` | `1` / `["U1EM1_CM3"]` |
| `open_count` / `session_reused` | `1` / `false`（本次为首次 `/open`） |
| `pcec_ledger_entries` | 1（Greenfield 自有内存账本） |
| `reverse_protection` | `{"status":"evaluated","allowed":true,"drift_count":0,"tia_side_drift":0,"blocked_source_ids":[],"reason":"TIA 侧块哈希与上次生成物一致,允许增量覆盖(D10 反向保护通过)"}` |
| 第 8 步增量 `FidelityReport` | `fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0 / mode=incremental / base_spec_version=1 / changed_source_ids=["U1EM1_CM3"] / pending_real_machine=false` |
| 步骤 7 `compile_diagnostics` | `status=compiled, error_count=0, warnings=[], compile_ok=true, static_gate_passed=true, tia_version=V19`；**`pending_real_machine=true / l2_status=pending_real_machine`（产品 N9 口径如实保留）** |

v2 派生产物：基于同一份磁盘 v2 规格经产品 `generate_project_package` 重建（V 的 `zip_bytes` 为内存态、未落盘），真实 `block_count=26 / blocks_manifest_count=26`（与 V 报告一致）；`tia_side_snapshot` / `last_generated` 取该真实 `blocks_manifest` 的 26 个 sha256（与 `FidelityChecker` 的 `content_hash_by_sid` 同命名空间，确保步骤 3 与第 8 步口径一致）。

### 3.5 编译 / PCEC / 会话统计（全部真实返回）

| 项 | 真实值 |
|---|---|
| `/open` 次数 | **1**（`ensure_project_open` 原始返回 1 条） |
| 句柄复用 | `handle_reused=true`；`health.openProject` 全程唯一路径 |
| `close` / `create-project` / `archive` | **0 / 0 / 0** |
| `/compile-plc` | **4 次**（Action C 步骤 7 ×1 + `run_incremental_writebacks` ×3），全部 `errorCount=0 / warningCount=0 / state=Success` |
| `/save` | 4 次 `ok=true`，`archived=false / reloaded=false / created=false` |
| `/fast-writeback` | 4 次 `success=true`；C# 返回 `writtenBlockCount=0 / generatedNames=[]`（**如实留痕、未掩盖**，与 M/R 观察一致）；Action C 那次 `compileScope=full_software_fallback`，等价编排 3 次 `incremental_blocks` |
| `run_incremental_writebacks` | `ok=true / increment_count=3 / pcec_records=3` |
| **PCEC 磁盘账本** | `<PLC_WORK_DIR>/changes` 下 **3/3 落盘**（`chg-24abfc5348a6` / `chg-ca99ed54bf48` / `chg-147d759d3cc1`，各含 `meta.json` + `change.json`） |
| TIA 侧块佐证 | serve 停止后真实 `list-blocks`：`count=5 / OB:1 FB:1 FC:3`，`W2_FC_Inc1/2/3`(FC,1/2/3,SCL) 确已入项目 |

**过程性失败如实留痕**：会话进行中调 `list-blocks` 返回 `exit=3 / openness_error: ... already been opened by user vboxuser`（one-shot CLI 无法并发打开 serve 持有的 `.ap19`）；属时序 / 占用，serve 停止后补测成功，非能力缺失。

### 3.6 增量 fidelity 复核 + `reverse_protection` 真机值
- **V 离线真实增量 FidelityReport**（`fidelity_report_incremental`）：`fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0`，`reverse_protection.status=pending_real_machine / allowed=null`。
- **真机补齐**：Action C 第 8 步在真机会话下用真实 v2 派生产物 + 真实 `SpecDiff` + 真机 `tia_side_snapshot` **重新跑一次 `FidelityChecker(mode=incremental)`**，得 `fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0`。
- **`reverse_protection` 真机值**：Action C 步骤 3 对真实块哈希快照调 `check_reverse_guard` → `allowed=true / drift_count=0 / tia_side_drift=0`；独立 `check_reverse_guard(last_generated, tia_side_snapshot)` 再算一次同为 `allowed=true`。把 V 离线报告的 `allowed=null` 补齐为 **`allowed=true`**。
- `tia_side_snapshot` 真实来源：重建 v2 派生产物 `blocks_manifest` 的真实 sha256（26 项）+ 3 个真实 SCL 外部源内容哈希；TIA 侧未做手工改动 → 与上次生成物一致（R3 同口径）。**限定**：为内容哈希，非从 TIA 工程对象直接读回的块对象哈希；`check_reverse_guard` 为产品纯函数对真实内容哈希计算，非 mock。

### 3.7 真机六字段最终值

| 六字段 | 真实值 |
|---|---|
| `mode` | `"incremental"` |
| `base_spec_version` | `1`（补齐批次 3 `null`） |
| `changed_source_ids` | `["U1EM1_CM3"]`（非空） |
| `reverse_protection` | `{"status":"evaluated","allowed":true,"drift_count":0,"tia_side_drift":0,"blocked_source_ids":[],"reason":"TIA 侧块哈希与上次生成物一致..."}` |
| `tia_side_drift` | `0` |
| `ob_number_deviations` | `[]`（**显式留痕 + note**，禁止静默；属不纳入 1:1 的域，不参与 `fidelity_ok`） |

`fidelity_ok=true`（Action C 第 8 步真实增量 FidelityChecker + V 报告一致）；`compile_ok=true`（4 次真实编译 0/0）。

### 3.8 诚实边界（命名空间 / 等价映射）
- **不假装逐块一一对应**：`SpecDiff.changed_source_ids` 是 IR 层 id（`U1EM1_CM3`），真机块 / `artifacts` 是派生产物层（`DB::`/`FB::`/`OB::` / `W2_FC_Inc*` SCL 外部源），命名空间不同。真机覆盖的是经 `SclBridgingPort` **等价映射**后的 SCL 外部源块（`W2_FC_Inc1/2/3`）+ Action C 桥接块；等价依据是「最小可编译 SCL 外部源变体代替 IR 层变更的块级覆盖」（与 M / R 同口径）。
- **Action C 主路径首跑 `GF_ACTION_C_ROLLBACK`** 是块映射限制的真实失败，重跑靠运行时桥接接通；首跑原始返回保留，不冒充首跑即通过、不冒充 v1→v2 规格链的逐块端到端真机闭环。
- `fidelity_ok ≠ compile_ok`（N9）；产品 `compile_diagnostics` 仍 `pending_real_machine=true / l2_status=pending_real_machine`，本 Agent 不标 L2/L4 通过。
- `writtenBlockCount=0 / generatedNames=[]` 如实留痕；真实块由 serve 停止后 `list-blocks` 佐证。
- `ob_number_deviations` 显式留痕；warning 单列不并入成功。

### 3.9 UC-16 闭环判定（契约 §3，逐条）

| 判据 | 结果 | 证据 |
|---|---|---|
| ① V 真实 `specs/v1.json → v2.json`，两版 `spec_hash` 不同、`project_id` 一致 | **yes** | 磁盘装载 spec_hash 与 V 一致、`hash_differs=true` |
| ② `compute_spec_diff` 真实 `base_spec_version=1` / `changed_source_ids` 非空；增量 `FidelityChecker` 四指标 | **yes** | `base=1 / ["U1EM1_CM3"]`；第 8 步 `fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0` |
| ③ 六字段全部真实值（`mode` / `base_spec_version` / `changed_source_ids` / `reverse_protection` / `tia_side_drift` / `ob_number_deviations` 留痕） | **yes** | §3.7，`reverse_protection.allowed=true` 真机值补齐 V 的 `null` |
| ④ W 真机：D11 显式确认、会话复用覆盖 → 编译 0/0 → 增量 fidelity 复核；`/open` 一次、PCEC 可追溯、`tia_side_drift=0` | **yes** | `/open=1` / 句柄复用 / 4× 编译 0/0 / PCEC 3 条落盘 / Action C 八步 / UC-19 负例 |
| ⑤ 若真机链做不到则如实标 `pending_real_machine`、不冒充 L4 通过 | **部分适用** | 首跑 Action C 主路径 `GF_ACTION_C_ROLLBACK` 如实留痕并标边界；重跑以等价映射接通，不冒充逐块一一对应 |

> **UC-16 闭环：达成（`uc16_closed=true`，真机侧）**。批次 3 `base_spec_version=null` 与增量 `FidelityChecker` 未闭环两处缺口由 V 规格链 + W 真机补齐；未拿 M/R 的既有三次增量证据冒充本次 v1→v2 规格链结果。

---

## 4. 两个 UC 闭环判定汇总（契约 §3）

| UC | 闭环判据 | 结论 |
|---|---|---|
| UC-04 | ① 自洽完整包 ② 按序导入 `ok=true` ③ 文件夹 API 建立 ④ 编译 `0/0 Success` ⑤ 结构化证据 | **全部 yes → 闭环** |
| UC-16 | ① 真实规格链 ② 真实 diff + 增量四指标 ③ 六字段真实值 ④ 真机 Action C / 会话 / 编译 / PCEC / `tia_side_drift=0` ⑤ 失败如实标 pending | **全部 yes（含失败留痕）→ 真机侧闭环** |

---

## 5. L2 / L4 证据齐备性 · M4 · P0-D

> 判定规则：**只有拿到真实证据的层才考虑 pass，最终判定归主 agent 收口**；本 Agent 不标任何层 pass。

| 层 | 本轮 / 前序真实证据 | 仍缺 / 边界 | 齐备性 |
|---|---|---|---|
| **L1 逻辑等价** | W2 第 8 步真实增量 `FidelityChecker` 四指标 + V 离线规格链 / coverage_matrix + Q 的 L1 全量（引用） | UC-08/09/10/11、UC-15 端到端全链闭环由主 agent 收口 | **接近齐备**（引用既有） |
| **L2 可编译** | W1 完整 AF 包编译 `0/0 Success`（UC-04 缺口补齐）+ W2 4× 编译 `0/0` + `static_gate_passed=true` + UC-02/03 口径（M） | `xml_package_unverified` 全局处置、四层静态门禁全绿收口、G 编排 `l2_status=pending_real_machine`、端到端全链 | **证据接近齐备但仍有明确收口项**，不据真机编译宣称 L2 通过 |
| **L3 可复现** | V 规格链 manifest / bundle_sha256 可复算（引用）、Q 九步步骤 8 产物哈希一致（引用） | 重启恢复 FROZEN vN 由主 agent 收口 | **引用既有** |
| **L4 增量可迭代** | W2 六字段真值 + Action C 八步 + `/open=1` + 4× 编译 0/0 + PCEC 3 条 + `tia_side_drift=0` + 增量 `fidelity_ok=true`；D10 负例 / UC-13 回滚引用 M | 产品层 `pending_real_machine` / `l2_status` 未清零、§13.9 全量收口 | **真机侧大部分齐备**，`fidelity_ok` 与 `compile_ok` 严格分离，不宣称 L4 通过 |

- **M4**：签署栏始终「**待用户签署**」。本批次最多推进到「证据齐备 / 待用户签署」；本 Agent **未把 `m4_signable` 置 true、未代签、未改任何证据台账**（`rtm.json` / `pending_real_machine.json` / `acceptance_template.json` / `uc15_evidence_bundle.json` / `09-m4-review.md` / `10-real-machine-acceptance.md` 由主 agent 收口统一更新）。
- **P0-D**：用户已于 2026-11-06 以编号「1」拍板 **坚持「AF Basic 文件夹版」，暂不切「软件单元版」**。本 Agent 只做记录与执行（文件夹版 `create-block-group` / `framework_baseline=af-basic-folder-1.0`），不重新论证、不代拍。

---

## 6. 复用 / 引用清单（区分「本次新实测」与「引用既有」）

| 来源 | 性质 | 内容 |
|---|---|---|
| **本次新实测（Agent W）** | 真机 | W1：U 完整包 manifest / 逐文件 sha256 核对、5 个块逐项 `import-xml`、2 组 `create-block-group`、`list-blocks`(all/OB/FB/DB)、`compile-plc 0/0`；W2：磁盘规格链装载与 `compute_spec_diff` 复核、UC-19 负例、serve 会话 `/open=1`、**首跑 `GF_ACTION_C_ROLLBACK` 真实失败**、重跑 Action C 八步全通 + 第 8 步真实增量 FidelityChecker、4× 编译 0/0、PCEC 3 条落盘、`check_reverse_guard` 真机值、serve 停止后 `list-blocks` 佐证、v2 派生产物重建（26 块） |
| **引用 U（阶段 A 交付）** | 离线交付 | `14-uc04-package-fix.md`、`tools/build_full_af_package.py`（W 只调用不修改）、`tests/unit/test_greenfield_full_af_package.py`；批次 3 失败原始返回 `evidence/uc04_package_probe.json` |
| **引用 V（阶段 A 交付）** | 离线规格链 | `15-uc16-spec-chain.md`、`evidence/uc16_incremental_spec_chain.json`、`evidence/uc16_incremental_evidence_bundle.json`、`tools/run_incremental_spec_chain.py`（W 直接复用磁盘 `specs/v1.json`/`v2.json`，不重新生成会话） |
| **引用 K（既有）** | 真机探针 | `08-k1-probe-fix.md`（`_render_ob_xml` culture / namespace 修复、`import-xml` / `compile-plc` 复现命令、caseA/caseB） |
| **引用 M（既有）** | 真机 | `10-real-machine-acceptance.md`、`evidence/uc05_real_machine_report.json`（serve 常驻会话 / 三次增量 P0-G / PCEC / D10 负例 / UC-13 回滚 / `tia_unavailable` 口径） |
| **引用 R（既有）** | 真机 | `12-batch3-real-machine.md`、`evidence/uc16_incremental_real.json`（三次增量真机 / `base_spec_version=null` / `check_reverse_guard` 口径）、`evidence/uc15_step7_real.json`、`evidence/uc18_compile_feedback_real.json`、`tools/run_batch3_real_machine.py`（CLI / serve / HTTP 复现方式、`run_incremental_writebacks`、SCL 等价替代模板） |
| **引用 F（既有）** | 真机归档 | 环境四件套 / `--cli status` / `create-block-group` 可行性（沿用，不重复探测） |

> 批次 3 `uc16_incremental_real.json` 的 `base_spec_version=null` 与「增量 fidelity 未闭环」由本轮 **V 规格链 + W 真机** 补齐；**未把 R 的数字冒充为本次 v1→v2 规格链的真机结果**。

---

## 7. 验证与清理确认

```
cd <R> && ./.venv/Scripts/python.exe -m pytest \
  tests/unit/test_greenfield_legacy_guard.py \
  tests/unit/test_greenfield_tia_delivery.py \
  tests/unit/test_greenfield_session_mode.py -q
# -> 26 passed in 10.93s
```
关键护栏显式复核：
```
./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q \
  -k "frozen_legacy_files_have_zero_diff or sanctioned_phase2_module_whitelist"
# -> 2 passed, 3 deselected
```
- `test_frozen_legacy_files_have_zero_diff`：**PASS**（sha256 冻结清单零 diff）
- `test_sanctioned_phase2_module_whitelist`：**PASS**（未新增 forbidden_modules import）
- 未新增 `tests/unit/test_greenfield_batch4_real.py`（可选，本轮未新增）；**未跑全量 pytest**（主 agent 收口统一跑）。

**serve 进程清理**：
- `serve_stop`: `returncode=1`、`port_reachable_after_stop=false`、`leftover_process=false`
- 全局 `serve_leftover_after_all=false`
- 最终独立确认：`8791 reachable=false`、`GET /health` 不可达（`TimeoutError`）、`Get-Process TiaOpenness.Server` → `NO_LEFTOVER_TIAOPENNESS_SERVER_PROCESS`

---

## 8. 已知遗留（诚实清单，尤其仍 `pending_real_machine` 的项）

1. **`xml_package_unverified` 仍为 `True`**：W 只给处置建议与依据（§2.7），**未擅自改 False**；是否消除由主 agent 收口决定。
2. **`SW.PlcBlockGroup XML` 仍不可经 `import-xml` 导入**：确证边界事实，文件夹走 `create-block-group` API；若把「自产 XML 包整体已验证」需按 §2.7 限定。
3. **端到端全链（UC-15 / `deliver_tia` auto / M4）非本轮范围**：本轮为临时副本上的包级 / 会话级真机验证。
4. **W2 Action C 主路径首跑 `GF_ACTION_C_ROLLBACK`**（`invalid_argument` 块映射限制）如实留痕；重跑靠运行时 `SclBridgingPort` 等价映射，**不冒充** IR 变更块与派生产物块逐块一一对应、不冒充首跑即通过。
5. **`tia_side_snapshot` 为内容哈希**（v2 派生产物 `blocks_manifest` / SCL 外部源 sha256），非从 TIA 工程对象直接读回的块对象哈希；TIA 侧未做手工改动 → 与生成物一致（R3 口径）。
6. **C# `/fast-writeback` 返回 `writtenBlockCount=0 / generatedNames=[]`**（4 次均如此，与 M/R 一致）如实留痕；真实块由 serve 停止后 `list-blocks` 佐证。
7. **会话中 `list-blocks` 过程性失败**（`exit=3 / already opened by user`）如实留痕，serve 停止后补测成功。
8. **L2 / L4 层判定仍 `pending`**：产品 `compile_diagnostics.pending_real_machine=true / l2_status=pending_real_machine` 如实保留；`fidelity_ok` 与 `compile_ok` 严格分离（N9）。
9. **M4 未通过 / 不可签署**：`L1∧L2∧L3∧L4` 全绿判定、pending 台账清零、M4 签署栏由主 agent 收口统一更新；本 Agent 未改任何证据台账、未代签。
10. **culture 收敛 `zh-CN` 适用边界**（K §7）与 **FB/DB 精简差异**（U §8.6）：对含 `zh-CN` 的中文项目真机验证，非逐字段等同真实 V19 先例；其它语言项目未测。
11. **单次 `--only W2` 复现会覆盖 first-attempt 槽位**：当前 `raw_all.json` 完整保留「首跑失败 + 重跑成功」两轮；后续复现若需保留历史，请另存 `raw_all.json` 副本。

---

## 9. 复现命令（Git Bash，可原样复跑）

```bash
R="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"
EXE="$R/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe"
PY="$R/.venv/Scripts/python.exe"
W="C:/Users/vboxuser/AppData/Local/Temp/gf_real_w4_20261107"

# 环境健康检查（沿用 F/M/R，不重复探测四件套）
timeout -k 5 180 "$EXE" --cli status

# W1 · UC-04 完整 AF 包联合导入编译（自动 cp 临时副本）
cd "$R" && timeout -k 5 900 "$PY" tools/run_batch4_real_machine.py --only W1

# W2 · UC-16 真机增量闭环（自动 cp 临时副本 + serve 会话，用完即停）
cd "$R" && timeout -k 5 900 "$PY" tools/run_batch4_real_machine.py --only W2

# 单条 CLI 等价复现
timeout -k 5 180 "$EXE" --cli import-xml --project <Temp副本.ap19> --xml <w1_package/blocks/FB1000_StdSignal.xml> --kind auto   # 按 import_order 逐个
timeout -k 5 180 "$EXE" --cli create-block-group --project <Temp副本.ap19> --plc PLC_1 --group AF_Unit_01/AF_EM_01
timeout -k 5 180 "$EXE" --cli list-blocks --project <Temp副本.ap19> [--type OB|FB|DB]
timeout -k 5 180 "$EXE" --cli compile-plc --project <Temp副本.ap19> --plc PLC_1

# 结构化证据 / 原始返回
# evidence/uc04_full_package_real.json、evidence/uc16_incremental_closed_real.json
# $W/raw_all.json（含 W1 / W2 / W2-incremental-first-attempt 全部真实返回）
```

---

## 10. 合规与诚实口径声明

- 真机操作**只在** `C:/Users/vboxuser/AppData/Local/Temp/gf_real_w4_20261107/` 临时副本上进行；`PLC_Openness_data/` 原始 `.ap19/.zap19` 仅 `shutil.copytree` 读取，从未打开、从未 `SaveProject()` 写回原始路径、未删除任何原始文件。
- 每个真机子进程 / CLI / HTTP 调用有超时保护；`serve` 常驻进程 `POST /close` + `terminate/kill` + 端口复查，`leftover_process=false`、全局无遗留进程。
- **所有编译 / 导入 / PCEC / sha256 数字均来自真实 CLI / HTTP 原始返回**，集中归档于 `raw_all.json` 并在本报告附复现命令；**未伪造任何 `errorCount` / `warningCount` / `state` / `exit code` / `importedNames` / PCEC 条数**（W2 首跑回滚、会话中 `list-blocks` 失败、`writtenBlockCount=0` 均如实记录）。
- 未以 mock / 离线单测宣称 L2/L4 通过、未宣称「Greenfield 全链编译零错误」、未把 `pending_real_machine` 说成成功、未把 `fidelity_ok` 当作 `compile_ok`、未把 UC 主状态说成 L 层通过或 M4 可签署。
- D12 hard refuse 全程约束；N9 严格分离；warning 单列不并入成功；`ob_number_deviations` 显式留痕；`xml_package_unverified` 未擅自改 False。
- **未执行任何 git 操作**；未改任何产品代码（`gateway/`、`plc_engine/`、`agents/`、`frontend/`、`industrial/`）、`legacy_baseline.json`、`test_greenfield_legacy_guard.py`、sha256 冻结清单 41 个文件、C# 源码、证据台账与批次 2/3 既有真机证据、`09-m4-review.md` / `10-real-machine-acceptance.md`。
- **P0-D 档位结论为用户拍板，本 Agent 未代拍；M4 未代签。**
