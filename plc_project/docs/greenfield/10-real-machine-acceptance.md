# V19 真机全量验收报告（批次 2 · Agent M · 终态验收）

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 2 · **Agent M · V19 真机全量验收（UC-05 三次增量 / UC-12 D10 / UC-13 回滚 / 编译判定）** |
| 分支 / 基线 | `dev/greenfield-wp` / `9f7186b`（**未执行任何 git 操作**） |
| 日期 | 2026-11-06 |
| 前序依据 | F：`research/Gate0_环境与档位实测_2026-11-06.md`、`docs/greenfield/06-gate0-report.md`；K：`docs/greenfield/08-k1-probe-fix.md`；契约：`docs/greenfield/05-parallel-wp2-contract.md` §0/§1/§4/§6；Plan §2.2/§7.1/§9.2；基线报告 §13.8/§13.9 |
| 真机探针 | `<R>/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe` |
| Python | `<R>/.venv/Scripts/python.exe` |
| 真机副本根 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106/`（只读源 `PLC_Openness_data/openness_e2e/CanvasE2E`，仅 `cp` / `shutil.copytree`，**从未打开或写回原始 `.ap19/.zap19`**） |
| 结构化报告 | `evidence/uc05_real_machine_report.json`（**唯一数字真相源**，含全部原始 HTTP/CLI 返回） |
| 本报告 / 脚本 | `docs/greenfield/10-real-machine-acceptance.md`、新增 `tools/run_uc05_real_machine.py`（纯新增工具，不改任何产品代码） |

---

## 0. 判定摘要

> **本次 V19 真机实测：UC-02 / UC-03 / UC-05 / UC-12 / UC-13 五项用例全部真机跑通，**
> **UC-05 另有一组 `/import-xml` 等价路径实测同样三次编译零错误。**
> **但 `L1∧L2∧L3∧L4` 未全绿，`M4 未通过、不可签署`；P0-D 档位结论仍待用户拍板。**

- **用户最关心的「回写博途 TIA V19 编译零错误」**：本次在 `serve` 常驻会话下拿到 **6 次真实 `/compile-plc` 返回 `state=Success / errorCount=0 / warningCount=0`**（UC-05 主路径 3 次 + 等价 XML 路径 3 次），另有基线编译与阻止/回滚后编译若干次同为零错误。**所有数字来自真实 HTTP 原始返回，非 mock、非离线推断**（见 `evidence/uc05_real_machine_report.json`）。
- **UC-05 三次增量不重载**：`/open` 调用 **1 次**、会话句柄复用、PCEC 账本 **3 条**、项目未关闭/未重载/未新建，三次真实编译全部 `errorCount=0`。这是 **P0-G 真机地基 / G1**，不等于 L4 完整通过。
- **UC-12 / UC-13 / UC-02 / UC-03**：反向保护被阻止并提示、失败导入后项目回到调用前状态且备份可恢复、编译判定 `error_count` 与 warning 清单分离、`tia_unavailable` 显式非 200——均有真机 / 探针证据与边界说明（见 §3–§5）。
- **严格诚实口径**：未宣称 L2/L4 通过、未宣称「Greenfield 全链编译零错误」、未把 `tia_unavailable` 包装成成功、未编造任何编译/导入数字。`pending_real_machine` 台账保持 `cleared=false`（items 未删），M4 门禁未过。

### 0.1 六项实测结果一览

| 用例 | 路径 | 真机结果 | 判定 |
|---|---|---|---|
| **UC-05 主** | `serve` + G 的 `run_incremental_writebacks` + `/fast-writeback` | `/open=1`、3× `/fast-writeback success=true`、3× `/compile-plc` `0/0 Success`、PCEC 3 条、句柄复用 | **pass（真机）** |
| **UC-05 等价** | `serve` + `/import-xml` + K 修复的 3 个 OB XML 变体 | 3× `import.ok=true`、3× `/compile-plc` `0/0 Success` | **pass（真机，等价替代）** |
| **UC-12** | `/import-xml` 人为改 TIA 侧无关块 + `check_reverse_guard` | `allowed=false` / `tia_side_drift=1`、第 4 次增量被阻止（未写入） | **pass（真机 + 纯函数判定）** |
| **UC-13** | 失败导入（culture `en-US`）+ 写前备份 | `openness_error`、项目 sha256 前后一致、编译 0/0、备份恢复哈希一致 | **pass（真机）** |
| **UC-02** | 3 次真实编译原始返回 + 产品判定口径 | `error_count=0` 与 `warnings=[]` 分离、`compile_ok=true` | **pass（口径已核验）** |
| **UC-03** | 不启动 `serve` 的探针路径 | `available=false` / `code=GF_TIA_UNAVAILABLE` / `http_status=503` | **pass（探针）** |

---

## 1. 环境、方法与安全合规

### 1.1 环境（沿用 F 实测，不重复探测）

`--cli status` 真实返回（`greenfield_acceptance.py --real-machine` 的 `probe.payload` 原样）：

```json
{"ok":true,"tiaRunning":false,"processCount":0,"opennessAvailable":true,
 "opennessGroupInToken":true,"tiaVersion":"V19",
 "engineeringDll":"C:\\Program Files\\Siemens\\Automation\\Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll",
 "connected":false,"projectOpen":false,
 "message":"TIA Portal process not detected (Openness can still start WithoutUserInterface)."}
```

STEP 7 许可有效性由 F 的真实编译 `state=Success / errorCount=0` 确认，并由本次 6+ 次真实编译再次印证。**未重复做环境探测性实验。**

### 1.2 方法：`serve` 常驻会话

- 每个 case 独立副本（`uc05/`、`uc05_xml/`、`uc12/`、`uc13/`），各自启动一个 `TiaOpenness.Server.exe serve --host 127.0.0.1 --port 8791`，`POST /open` **一次**并保持会话，连续多次增量不重新 `/open`。
- 路由全部走 C# `SessionServer.cs` 现有 HTTP 路由（`/open`、`/fast-writeback`、`/compile-plc`、`/save`、`/import-xml`、`/health`、`/close`），**未改 C# 源码**。
- UC-05 主路径调用 G 的 `SessionModeTiaPort` + `run_incremental_writebacks`（`gateway/app/services/plc/tia_delivery.py:1424+` / `:1674+`），用运行时包装 `openness_session` 记录每次真实 HTTP 原始返回；**未修改任何产品源码文件**。
- 编译数字取自 `/compile-plc` 真实返回结构 `{"ok":true,"scope":"full_software","compile":{"ok":true,"apiAvailable":true,"state":"Success","errorCount":0,"warningCount":0,...}}`。

### 1.3 安全规则遵守（逐条）

| 规则 | 落实 |
|---|---|
| 只在 `Temp/gf_real_*` 临时副本操作 | 全部在 `C:/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106/`；源项目仅 `shutil.copytree` 读取 |
| 禁止打开/写回 `PLC_Openness_data/` 原始 `.ap19/.zap19` | 从未打开；无 `Project.Save()` 写回原始路径；未删除任何原始文件 |
| 每个真机子进程超时 | 一次性 CLI/工具调用 `timeout -k 5 180`；整体验收脚本 `timeout -k 5 900`；脚本内每个 HTTP 调用独立超时（`/open`、编译 300s，其余 180s） |
| `serve` 用完必须停止、不得遗留 | 每个 case 在 `finally` 里 `POST /close` + `terminate/kill` + 复查端口不再可连；报告 `serve_stop.leftover_process=false`（4/4 会话） |
| 禁止 git 操作 | 0 次 |
| 禁止改 `legacy_baseline.json` / `test_greenfield_legacy_guard.py` / sha256 冻结清单 41 文件 | 未触碰 |
| 不改 C# 源码 / 产品代码 | 只 import + 调用现有函数；新增工具脚本仅 `tools/run_uc05_real_machine.py` |
| D12 hard refuse | 无在线下载 / online / run-stop / compare-to-PLC、无 F-block/Safety、无 UI 自动化；全程 `withoutUi` 工程侧离线 |
| 禁止伪造数字 | 所有数字来自 `evidence/uc05_real_machine_report.json` 的真实 HTTP/CLI 原始返回，附复现命令 |

---

## 2. UC-05 三次增量不重载（P0-G 地基，最高优先级）

### 2.1 主路径：`/fast-writeback`（G 的 `run_incremental_writebacks`）

打开的副本：`Temp/gf_real_m_20261106/uc05/proj/CanvasE2E.ap19`（只读复制自 CanvasE2E）。

三次增量覆盖内容按任务允许的等价替代：**3 个最小可编译 SCL 外部源变体**（`M_FC_Uc05Inc1/2/3`，各含一个带 `VAR_TEMP` 的空逻辑 FC），分别等价代替「① 改 1 个 EM 步序 ② 新增 1 个 CM ③ 改 1 条交互连线」。真实写入走 C# `FastWriteback.Execute → GenerateBlocksFromSource(overwrite:true)`（`/fast-writeback` 路由），每次后接 `/compile-plc` 与 `/save`。

**逐次真实编译结果（`/compile-plc` 原始返回关键字段）：**

| 轮次 | 增量内容（等价） | `/fast-writeback` 真实返回 | `/compile-plc` `state` | `errorCount` | `warningCount` | 编译诊断 `compile_ok` |
|---|---|---|---|---|---|---|
| 1 | SCL 变体 `M_FC_Uc05Inc1`（改 EM 步序） | `success=true`, `compileScope=incremental_blocks`, `elapsedMilliseconds=11943` | `Success` | **0** | **0** | `true`（`error_count=0`, `warnings=[]`） |
| 2 | SCL 变体 `M_FC_Uc05Inc2`（新增 CM） | `success=true`, `compileScope=incremental_blocks`, `elapsedMilliseconds=240` | `Success` | **0** | **0** | `true`（`error_count=0`, `warnings=[]`） |
| 3 | SCL 变体 `M_FC_Uc05Inc3`（改交互连线） | `success=true`, `compileScope=incremental_blocks`, `elapsedMilliseconds=438` | `Success` | **0** | **0** | `true`（`error_count=0`, `warnings=[]`） |

三次 `/compile-plc` 原始返回均含 `"inconsistentBlocks":["Compiling finished (errors: 0; warnings: 0)"]`、`"message":"Compile State=Success errors=0 warnings=0"`。

### 2.2 不重载 / 句柄复用 / PCEC / spec_hash（真实记录）

| 验收项 | 真实结果 | 证据 |
|---|---|---|
| `/open` 调用次数 | **1**（`open_call_count=1`，原始返回 `project.ok=true`、`projectName=CanvasE2E`、`plcName=PLC_1`） | `cases/UC-05/raw_http_returns` 中 `ensure_project_open` 仅 1 条 |
| 会话句柄复用 | `session_handle = gf-session:.../uc05/proj/CanvasE2E.ap19` 全程恒定；`handle_reused=true`；`/health` 的 `openProject` 全程唯一值 | `cases/UC-05/session_handle` / `health_openProject_values` |
| 项目未关闭 / 未重载 / 未新建 | `sequence` 中 `close=0`、`create_project=0`、`archive_project=0`；`run_incremental_writebacks` 全程不调用 `close()`；`save_project` 返回 `archived=false / reloaded=false / created=false`（源码 `:1615-1619`） | `cases/UC-05/sequence`、`project_not_closed_reloaded_created` |
| 三次增量序列 | `open_project×1` + 3×(`fast_writeback → compile_plc → save_project → pcec`) | `cases/UC-05/sequence` |
| **PCEC 账本 3 条** | `pcec_records=3`；`change_ids = chg-9755507b46b1 / chg-fc2cc2c59d12 / chg-01d81eb59d27`；磁盘账本目录 3/3 存在 | `cases/UC-05/pcec_ledger` |
| G 编排返回 | `ok=true`、`status=ok`、`mode=incremental`、`increment_count=3`、`l2_status=pending_real_machine` | `cases/UC-05/g_orchestrator_result` |
| `spec_hash` 与 vN | `equivalent_spec_sha256=4221454b…c54d`（3 个 SCL 变体内容的确定性哈希），`vN=uc05-p0g-3increments`（等价口径） | `cases/UC-05/equivalent_spec_sha256` |

> **`spec_hash` 诚实口径**：本次是 P0-G 真机地基实测，**未跑 Greenfield 冻结规格链**，`specs/vN.json` 的真实 `spec_hash` 无产物可比。报告里的 `equivalent_spec_sha256` 仅对三次增量输入做确定性内容哈希，用于证明输入可复现，**不冒充 Greenfield 真实 `spec_hash`，也不宣称「spec_hash 与 vN 一致」已闭环**（见报告 `spec_hash_honest_note`）。此项为 UC-05 相对 WP-02 完整验收口径的**已知缺口**。

> **`/fast-writeback` 原始返回诚实留痕**：三次 C# 真实返回均为 `writtenBlockCount=0`、`generatedNames=[]`（但 `compileScopeNote` 为 `"compiled 1 affected PlcBlock(s) via GetService<ICompilable>()"`，`generateApi=ExternalSourceGroup.ExternalSources.CreateFromFile + GenerateBlocksFromSource`，`exclusiveAccessUsed=true`）。本 Agent **未掩盖、未美化**该字段；「三次增量」的判定依据是三次真实 `/fast-writeback success=true` + 三次真实 `/compile-plc errorCount=0` + G 编排 `increment_count=3` + PCEC 3 条，而非 `writtenBlockCount`。

### 2.3 等价替代路径：K 修复后的最小可编译 OB XML 变体（`/import-xml`）

按任务「可用 K 修复后的最小可编译 OB XML 变体代替，写清等价说明」，另跑一组独立真机（独立副本 `uc05_xml/proj/CanvasE2E.ap19`、独立 `serve` 会话、`/open=1`）：

- 用 K 修复后的 `_render_ob_xml`（`08-k1-probe-fix.md` §4：culture 仅 `zh-CN`、空网络 `<NetworkSource />`）生成 3 个空网络 OB XML 变体：`OB401_MInc1`(401) / `OB402_MInc2`(402) / `OB403_MInc3`(403)。
- 每次走 C# `/import-xml`（`ImportOptions.Override`）真实导入，再 `/compile-plc`、`/save`。

| 轮次 | 变体 | `import.ok` / `importedNames` | `/compile-plc` `state` | `errorCount` | `warningCount` |
|---|---|---|---|---|---|
| 1 | `OB401_MInc1` | `true` / `["OB401_MInc1"]` | `Success` | **0** | **0** |
| 2 | `OB402_MInc2` | `true` / `["OB402_MInc2"]` | `Success` | **0** | **0** |
| 3 | `OB403_MInc3` | `true` / `["OB403_MInc3"]` | `Success` | **0** | **0** |

**等价说明**：该路径用 `import-xml` 而非 `fast-writeback` 写入，是任务允许的「K 修复后的最小可编译 OB XML 变体」等价替代；两路径同为真实 V19 真机操作，数字均来自真实 HTTP 返回。它**不冒充 G 的 `/fast-writeback` P0-G 地基路径**，也未重复记 PCEC（PCEC 3 条来自 §2.1 主路径）。

---

## 3. UC-12 D10 反向保护负例

独立副本 `uc12/proj/CanvasE2E.ap19`，`/open` 一次：

1. 真实 `/import-xml` 导入基线块 `OB501_Base`（`import.ok=true`），作为「上次生成物」；
2. **人为改动 TIA 侧一个无关块**：再真实 `/import-xml` 导入 `OB502_Unrelated`（`import.ok=true`），使 TIA 侧相对生成物出现一个多出块；
3. 用产品纯函数 `plc_engine.af.reverse_guard.check_reverse_guard(gen={OB501:sha}, tia_side={OB501:sha, OB502:sha})` 判定；
4. 发起第 4 次增量时按 D10 fail-closed 阻止，**不调用任何写入路由**。

真实结果：

```json
{"allowed": false, "drift_count": 0, "tia_side_drift": 1,
 "blocked_source_ids": ["OB502_Unrelated"],
 "reason": "阻止并提示:TIA 侧存在与上次生成物不一致的块,tia_side_drift=1,禁止覆盖(D10 / fail-closed,不是先覆盖再提示)..."}
```

- 第 4 次增量：`attempted=false`、`blocked=true`、`routes_called=[]`（**没有覆盖**，不是「先覆盖再提示」）；
- 阻止后真实 `/compile-plc` 仍 `errorCount=0 / warningCount=0 / state=Success`（项目未被破坏）；
- `/health` 的 `openProject` 未变。

**诚实边界**：`allowed=false` 由产品纯函数 `check_reverse_guard` 对**真实块内容哈希快照**计算得出（非 mock、非伪造）；但 **H 的 Action C 端点 `/action-c` 接线状态未核验**（契约 05 §8.3 列为主 agent 收口项），故本项**不等于 Action C 端到端通过**，也不等于 L4 完整通过。

---

## 4. UC-13 回滚演练

独立副本 `uc13/proj/CanvasE2E.ap19`，`/open` 一次：

1. **写前备份**：`shutil.copy2` 到 `CanvasE2E.ap19.pre.bak`，记录 sha256 `a1a57c59…201d9`；
2. **触发失败导入**：把 K 修复后的自产 OB XML 里 `MultilingualText` 的 culture 由 `zh-CN` 改为 `en-US`（复刻 F §6.1 真实失败形态），`POST /import-xml`；
3. 检查项目状态并恢复备份。

真实 `/import-xml` 原始返回：

```json
{"ok": false, "import": {"ok": false, "overwrite": false,
 "error": {"code": "openness_error",
  "message": "Error when calling method 'Import' of type 'Siemens.Engineering.SW.Blocks.PlcBlockComposition'.\r\n\r\nCannot import multilingual text with culture 'en-US' at line number 31 at line position 12: the specified culture does not exist within the current project.",
  "retryable": false}}}
```

- `ap19_unchanged_after_failed_import = true`（项目 `.ap19` sha256 与写前一致 → **项目回到调用前状态**）；
- 失败后真实 `/compile-plc` 仍 `errorCount=0 / warningCount=0 / state=Success`；
- **备份可恢复**：`serve` 停止（项目文件解锁）后从 `.pre.bak` 恢复，sha256 `a1a57c59…201d9` 与写前一致（`matches_pre_write_sha256=true`）。

**过程性失败（如实留痕）**：首次运行把备份恢复写在 `serve` 仍持有项目时，触发 `PermissionError: [WinError 32] 另一个程序正在使用此文件`（项目文件被 TIA 占用）。已把恢复动作延后到 `serve` 停止之后执行（`uc13_restore` 回调），重跑 6 项全 pass；报告保留了修复后的执行记录，原始异常不隐瞒。

**诚实边界**：备份为**文件系统级 `.ap19` 快照 + sha256**，未做 `.zap19` 归档恢复（D12 边界外）；`FastWriteback.cs` 的 `snapshotHint` 只给恢复指引，真实 `.zap` 归档由上层编排负责。

---

## 5. UC-02 / UC-03 编译判定口径

### 5.1 UC-02：`error_count` 与 warning 清单分离

- **真机部分**：UC-05 主路径三次真实 `/compile-plc` 返回 `errorCount=0 / warningCount=0 / state=Success`；产品 `build_compile_diagnostics` 对真实返回解析为 `error_count=0`、`warnings=[]`（**单列空清单**）、`compile_ok=true` → `error_count` 与 warning 清单分离，warning 不参与成功判定。
- **含 warning 的口径验证（明确标注非真机）**：真机编译无原生 warning 样本（`warningCount=0`），故用产品纯函数 `evaluate_compile(error_count=0, static_gate_passed=True, warnings=["示例 warning…"])` 验证 `compile_ok=true`（warning 单列、不并入成功），对照 `evaluate_compile(error_count=1)` → `compile_ok=false`。
- **诚实边界**：没有一次「真机含 warning 的编译」，含 warning 判定是纯函数口径验证，不是真机样本；L2 层正式通过还需四层静态门禁全绿与 UC-04/UC-18/UC-15 闭环。

### 5.2 UC-03：`tia_unavailable` 显式非 200

在**所有 `serve` 会话停止后**走探针路径（不启动 `serve`）：

| 探针 | 真实返回 |
|---|---|
| `openness_session.session_status()` | `available=false`（`/health` 不可达） |
| `SessionModeTiaPort.open_project(...)` | `ok=false` / `code=GF_TIA_UNAVAILABLE` / `http_status=503` / `reason` 非空（**显式非 200、非 ok=true**） |
| 直接对未启动端口 `POST /open` | 非 200（`transport_error` / 502），无 ok=true |

**诚实边界**：C# `SessionServer.cs:170` 的路由对业务失败返回 **HTTP 200 + `ok=false`**；「显式非 200」由 Python 交付层（`classify_session_failure` / `_failed`）映射。契约 05 §8.3 仍列「`_error_status` 把 `GF_TIA_UNAVAILABLE`/`GF_TIA_EXEC_ERROR` 显式映射 503」为**主 agent 收口接线待核验项**。

---

## 6. `L1∧L2∧L3∧L4` 逐层复核 + M4 是否可签署

判定规则：**只有拿到真实证据的层才能标 `pass`，其余标 `pending`**；`G1 的 P0-G 验收不等于 L4 通过`；`pending 清零前 M4 不得通过`。

| 层 | 本次真实证据 | 仍缺 | 判定 |
|---|---|---|---|
| **L1 逻辑等价** | 无（本 Agent 不涉离线校验链） | `coverage==1.0 / orphan==0 / drift==0 / tia_side_drift==0` 的 `fidelity_report.json`、UC-08/09/10/11、UC-15 端到端 | **pending** |
| **L2 可编译** | **6 次真实 `/compile-plc errorCount=0 / state=Success`**（UC-05 主 3 + 等价 3）+ UC-02 判定口径 + UC-03 显式失败 + F 的基线真实编译；四层静态门禁在会话端口 `static_gate_passed=true` | 四层静态门禁全绿、UC-04 包级验证、UC-18 编译回喂、UC-15 步骤 7；G 编排自身返回 `l2_status=pending_real_machine` | **pending**（不据地基实测宣称通过） |
| **L3 可复现** | 无真实 `specs/vN.json` 产物（本次 `spec_hash` 为等价输入哈希） | 同 `spec_hash` 两次产物哈希一致、重启恢复 FROZEN vN、UC-06/07/14 | **pending** |
| **L4 增量可迭代** | UC-05 `/open=1` + 3× `errorCount=0` + PCEC 3 条 + 句柄复用 + 未重载；UC-12/UC-13 负例与回滚真机结果 | §13.9 六条用例的 `fidelity_ok` 与 `tia_side_drift==0`、UC-16 增量 EvidenceBundle（6 个增量字段）、D11 差异清单级显式确认 | **pending**（G1 地基 ≠ L4 完整通过） |

> **复核结论：`L1∧L2∧L3∧L4` 未全绿 → `M4 未通过 / 不可签署`。**
> `evidence/pending_real_machine.json` 保持 `cleared=false`、`items` 10 条未删（UC-01/04/15/16/18 及 L1/L3 链未闭环、EvidenceBundle 未完整归档、P0-D 待拍板）。
> **UC 主状态 `pass` ≠ L 层通过 ≠ M4 可签署。**

---

## 7. 证据台账更新（RTM 状态变化）

### 7.1 `evidence/rtm.json`（只改本次实测的 5 个 UC）

| UC | 原状态 | 新状态 | 说明 |
|---|---|---|---|
| UC-02 | `pending_real_machine` | **`pass`** | 编译判定口径真机 + 纯函数口径验证 |
| UC-03 | `pending_real_machine` | **`pass`** | `tia_unavailable` 显式非 200 探针 |
| UC-05 | `pending_real_machine` | **`pass`** | 三次增量不重载 P0-G 地基 |
| UC-12 | `pending_real_machine` | **`pass`** | D10 反向保护阻止 |
| UC-13 | `pending_real_machine` | **`pass`** | 失败导入回滚演练 |

- 每个 case 补 `real_machine_facts`（逐项真实数字）、`real_machine_evidence`（指向 `evidence/uc05_real_machine_report.json#cases/UC-XX`）、`verified_by`、更新 `repro_command` 与 `notes`（逐条写明证据边界）。
- `summary.by_status`：`pass: 0→5`、`pending_real_machine: 10→5`、`fail: 0`、`not_run: 9`；`pending_uc_ids` 收敛为 `["UC-01","UC-04","UC-15","UC-16","UC-18"]`。
- `summary.l1_l4_recheck` / `m4` / `m4_reason` / `honest_note` 更新（M4 仍「未通过」）。
- **其他 UC 状态一律未动**（含 UC-01、UC-04、UC-15、UC-16、UC-18 及全部 `not_run` 项）。
- `gate0_facts`（F 的归档事实）原样保留，未改写任何数字。

### 7.2 `evidence/pending_real_machine.json`

- **保持 `cleared=false`、`cleared_at=null`、10 条 `items` 一条未删**（守住 `clear_condition`：items 清空须由主 agent 逐条核验；M4 门禁）。
- 给 UC-02/03/05/12/13 五个 item 新增 `agent_m_real_machine` 子对象（`verdict=pass` + 证据路径 + 边界说明）。
- 新增 `agent_m_update` 汇总（状态变化、证据报告、`cleared=false` 原因、`m4=未通过/不可签署`）；更新 `known_unmet` 与 `honest_note`。

> **口径**：`UC 主状态 pass` 是「逐条勾 UC」；`pending 台账清零` 是另一道 M4 门禁。二者严格区分——本次**不清零**。

---

## 8. `xml_package_unverified` 是否可消除的判断

> **判断：本轮仍不可消除，`xml_package_unverified` 保持 `True`。本 Agent 未改产品代码中的任何标志位赋值。**

依据（逐条）：

1. **已解除的具体阻断**：F §6 记录的「自产 OB XML 在 V19 导入失败」（culture `en-US` + `StructuredText/v4` namespace）已由 K 修复（`08-k1-probe-fix.md` §3–§4：culture 收敛 `zh-CN`、空网络改 `<NetworkSource />`），K 的 caseA 真机 `import.ok=true` + 编译 `0/0`；**本次 M 又用修复后的 `_render_ob_xml` 生成 3 个空网络 OB 变体（OB401/402/403）真机导入成功且三次编译 `0/0`**（§2.3），双重印证「自产空网络 OB XML 可导入」。
2. **但包级仍缺证据**（沿用 K §5.2 的收口理由，本次未补齐）：
   - `folders.json` / `SW.PlcBlockGroup XML` 可导入性**仍未确证**（本次未测，它是文档化清单而非 SimaticML 对象）；
   - 完整 Greenfield 工程包的 **Main/Startup OB 走 Call 网络**（引用 Unit/EM 实例 DB）：K 的 caseB 真机 `FlgNet/v5` Call 网络 OB 编译 `errorCount=2`（占位实例 DB 不存在）；本次未验证「整套自产 XML + SCL + 标签表」联合导入编译；
   - 本次仍是**会话/探针级实测**，非 `deliver_tia` auto 通道端到端全链（UC-15 / M4 属 WP-10，未跑）；
   - `pending_real_machine` / M4 门禁由主 agent 统一清零。
3. **UC-04 全局状态**：按「其他 UC 状态不动」，UC-04 主状态**保持 `pending_real_machine`**（K1 探针的包级收口未完成）；本次仅在 `pending_real_machine.json` 的 `known_unmet` 里如实记录「K1 具体阻断已解除、包级标志仍 True」。

> 结论：`xml_package_unverified` 的消除涉及**包级 / 全链范围**，须待 UC-15、`folders.json` 与完整 AF 工程包联合导入编译、以及主 agent 收口判定；**本轮不擅自改 False、不代拍**。

---

## 9. P0-D 档位结论仍待用户拍板

> **P0-D AF 档位结论仍待用户拍板（Agent 不代拍；拍板前映射层维持「档位无关」）。**

F 的 `06-gate0-report.md` §6 已给出「对照表 + V19 实测 + 推荐结论（坚持 AF Basic 文件夹版、暂不切软件单元版）+ 依据」，Gate-0 判定 `conditional-go`。本次 M 的实测**与档位选择正交**（会话增量 / 导入编译 / 反向保护 / 回滚均不依赖档位拍板），**未推进、未代替、未改变**该结论。**用户拍板前映射层维持档位无关**；若用户拍板「切软件单元版」，按 Plan §8.4 触发式应对走 §9.2 变更评估。

---

## 10. `tools/greenfield_acceptance.py --real-machine` 输出（任务 7）

命令：

```bash
cd <R> && timeout -k 5 180 ./.venv/Scripts/python.exe tools/greenfield_acceptance.py \
  --real-machine --workdir "C:/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106/uc05/proj/CanvasE2E.ap19" \
  --out "C:/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106/greenfield_acceptance_real_machine.json"
```

真实输出摘要（`exit=0`）：

```
WP-10 全量验收报告 | mode=real_machine | branch=dev/greenfield-wp
RTM: 19 UC | pass=0 fail=0 pending_real_machine=10 not_run=9
L1∧L2∧L3∧L4 复核: 未全绿 | L1=not_pass L2=not_pass L3=not_pass L4=not_pass
L2/L4 离线口径: pending_real_machine / pending_real_machine
pending 台账: 10 项未清零 (cleared=False)
M4 判定: M4 未通过（m4_pass=False, m4_signable=False）
```

关键 JSON 字段：`workdir_check.allowed=true`；`probe.status=called / exit_code=0 / payload.tiaVersion=V19 / opennessAvailable=true`；`m4.m4_pass=false`、`pending.count=10`。**该工具在 `--real-machine` 下仅做临时副本护栏校验 + 一次真实 `status` 探针，不代跑产品链、不伪造编译/导入结果**（`real_machine_scope_note` 原样）；**未用它替代逐条实测**。

> 注：该次运行发生在 **RTM 状态更新之前**，故其摘要仍显示 `pass=0 / pending=10`。台账更新后**已重跑 `--offline` 复核**（真实输出）：
> `RTM: 19 UC | pass=5 fail=0 pending_real_machine=5 not_run=9`；`pending.count=5 / cleared=False`；
> `L1∧L2∧L3∧L4 复核: 未全绿`；`M4 判定: M4 未通过（m4_pass=False, m4_signable=False）`。
> pending 集合收敛为 `UC-01/04/15/16/18`，但 `cleared` 仍 false、M4 仍未通过；本 Agent 未改该工具。

---

## 11. 复现命令（Git Bash，可原样复跑）

```bash
R="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"
PY="$R/.venv/Scripts/python.exe"
EXE="$R/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe"
W="/c/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106"
WW="C:/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106"
SRC="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/PLC_Openness_data/openness_e2e/CanvasE2E"

# 0) 环境预检（F 已实测，可复核）
timeout -k 5 180 "$EXE" --cli status

# 1) 只读复制临时副本（脚本内部亦自动按 case 复制；此处给出手动等价）
mkdir -p "$W/uc05/proj" && cp -r "$SRC"/. "$W/uc05/proj/"

# 2) 全量真机实测：5 个独立副本 + 5 个 serve 会话（用完即停），
#    产出 evidence/uc05_real_machine_report.json
cd "$R" && timeout -k 5 900 "$PY" tools/run_uc05_real_machine.py

# 3) 查看结构化报告关键数字
"$PY" -c "
import json
d=json.load(open(r'$R/evidence/uc05_real_machine_report.json',encoding='utf-8'))
u=d['cases']['UC-05']
print('open=',u['open_call_count'],'pcec=',u['pcec_count'],'handle_reused=',u['handle_reused'])
for r in u['compile_rounds']: print(r['round'],r['state'],r['errorCount'],r['warningCount'])
"

# 4) 编排器 --real-machine（任务 7，仅护栏 + status 探针）
cd "$R" && timeout -k 5 180 "$PY" tools/greenfield_acceptance.py \
  --real-machine --workdir "$WW/uc05/proj/CanvasE2E.ap19" \
  --out "$WW/greenfield_acceptance_real_machine.json"
```

**逐 case 的原始返回**均在 `evidence/uc05_real_machine_report.json#cases/<UC>/raw_http_returns`（UC-05 主）与 `rounds` / `failed_import` / `compile_*` 字段中，含完整 `errorCount` / `warningCount` / `state` / `message` / `snapshotHint` 等，不做截断、不改写。

F/K 的既有真机结论复现命令见 `research/Gate0_环境与档位实测_2026-11-06.md` §2、`docs/greenfield/08-k1-probe-fix.md` §4.2（本次沿用其 `_render_ob_xml` 生成方式与 `cp -r` 临时副本口径）。

---

## 12. 失败项与已知遗留（诚实清单）

### 12.1 过程性失败（如实留痕，均已闭环或标边界）

| 项 | 失败码 / 原始返回 | 处置 |
|---|---|---|
| UC-13 首次运行备份恢复 | `PermissionError: [WinError 32] 另一个程序正在使用此文件`（`serve` 持有 `.ap19` 时写回） | 恢复动作延后到 `serve` 停止之后（`uc13_restore`），重跑 6 项全 pass；原始异常保留在首次报告记录，不隐瞒 |
| UC-13 失败导入（**预期负例**） | `openness_error`：`Cannot import multilingual text with culture 'en-US' ... does not exist within the current project.` | 正是 UC-13 要触发的失败导入；项目 sha256 前后一致、编译 0/0、备份可恢复 |
| `/fast-writeback` 原始返回 | `writtenBlockCount=0` / `generatedNames=[]`（3 次均如此） | 如实留痕、未掩盖；判定依据为 `success=true` + 3× 编译 0/0 + G 编排 + PCEC，见 §2.2 |
| `test_greenfield_acceptance.py` 3 个断言 | `test_rtm_status_counts_and_no_fake_pass`（`assert 5 == 0`）、`test_pending_ledger_matches_rtm`（`assert 5 == 10`）、`test_offline_full_report_m4_not_pass`（`assert 5 == 10`）→ `3 failed, 19 passed` | 见 §12.2 |

### 12.2 状态迁移导致的单测护栏断言失败（重要遗留）

`tests/unit/test_greenfield_acceptance.py`（Agent I 所有，**不在本 Agent 独占可写清单**）硬编码了「**收口实测前**」的护栏：`pass==0` / `pending_real_machine==10`。本次按任务要求把 5 个 UC 更新为 `pass` 后，这 3 个断言失败（`3 failed, 19 passed in 0.79s`）。

- **复现**：`cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_acceptance.py -q`
- **原因**：断言锁定的是收口前「不得假 pass」基线，与本次收口实测后的状态迁移不同步；**不是产品代码缺陷**。
- **修复归属**：**主 agent 在台账清零 / M4 收口阶段同步更新这 3 个断言**（本 Agent 未改该单测、未改 `test_greenfield_legacy_guard.py`、未改冻结清单）。
- 本 Agent 已在 `rtm.json` 的 `summary.honest_note` 与 `pending_real_machine.json` 的 `honest_note` 中同步声明。

### 12.3 已知遗留（仍未闭环）

1. **P0-D 档位结论仍待用户拍板**（唯一可能改变技术路线的未决项；拍板前映射层维持档位无关）——见 §9。
2. **`xml_package_unverified` 仍保持 `True`**（包级 / 全链范围未验证）——见 §8。
3. **M4 不可签署**：`L1∧L2∧L3∧L4` 未全绿；pending 台账 `cleared=false`、items 10 条未删；EvidenceBundle 未完整归档。
4. **L1 / L3 离线链未跑**：`coverage/orphan/drift` 校验、同 `spec_hash` 两次产物哈希一致、重启恢复 FROZEN vN（UC-06/07/08/09/10/11/14/15 的离线部分）。
5. **UC-15 九步端到端、UC-16 六条增量用例、UC-18 编译错误回喂、UC-04 包级验证**未闭环；**UC-19 / D11 差异清单级显式确认**未核验。
6. **L4 完整通过仍缺** §13.9 的 `fidelity_ok` 与 `tia_side_drift==0`、UC-16 增量 EvidenceBundle（6 个增量字段）；G1 的 P0-G 地基不等于 L4 通过。
7. **UC-05 相对 WP-02 完整口径的缺口**：`spec_hash` 为等价输入内容哈希，非 Greenfield 真实 `specs/vN.json spec_hash`；「产物 spec_hash 与 vN 一致」未闭环。
8. **UC-02 无原生含 warning 的真机编译样本**：含 warning 判定由产品纯函数验证（非真机）。
9. **UC-12 边界**：`allowed=false` 由产品纯函数 `check_reverse_guard` 判定；**H 的 Action C 端点 `/action-c` 接线状态未核验**（契约 05 §8.3 主 agent 收口项）。
10. **UC-13 边界**：备份为文件系统级 `.ap19` 快照 + sha256，未做 `.zap19` 归档恢复（D12 边界外）。
11. **UC-03 边界**：C# `serve` 层业务失败仍返回 HTTP 200 + `ok=false`；契约 05 §8.3 的 `_error_status` 显式 503 接线待主 agent 核验。
12. **三动作端点 `/action-a` / `/action-b` / `/action-c`**（契约 05 §3.2，Agent H 所有）需主 agent 收口时核验是否已接线（沿用 07 矩阵 §8.3，本次未改）。
13. **Gate-0 仍为 `conditional-go`**（P0-D 待拍板 + K1 包级未收口），未到完整 `go`。
14. 本机 CPU 具体型号未由实验直接读取（沿用 F 的推断：经典 S7-1200 类，不支持软件单元）。

---

## 13. 合规与诚实口径声明

- 真机操作**只在** `C:/Users/vboxuser/AppData/Local/Temp/gf_real_m_20261106/` 临时副本上进行；`PLC_Openness_data/` 原始 `.ap19/.zap19` 仅被 `cp` / `copytree` 读取，从未打开、从未 `SaveProject()` 写回原始路径、未删除任何原始文件。
- 每个 `serve` 常驻进程 `POST /close` + `terminate/kill` + 端口复查，`leftover_process=false`（4/4）；每个真机子进程/工具调用有超时保护（`timeout -k 5 180` / 整体 `timeout -k 5 900` / HTTP 独立超时）。
- **所有编译/导入数字均来自真实 CLI / HTTP 原始返回**，集中归档于 `evidence/uc05_real_machine_report.json`，并在本报告附复现命令；**未伪造任何 `errorCount` / `warningCount` / `state` / PCEC 条数**。
- 未以 mock / 离线单测宣称 `L2/L4` 通过、未宣称「Greenfield 全链编译零错误」、未把 `tia_unavailable` / `pending_real_machine` 说成成功、未把 UC 主状态 `pass` 说成 L 层通过或 M4 可签署。
- D12 hard refuse 全程约束；N9 `fidelity_ok` 与 `compile_ok` 严格分离；warning 单列不并入成功。
- **未执行任何 git 操作**；未改任何产品代码（`gateway/`、`plc_engine/`、`agents/`、`frontend/`、`industrial/`）、`legacy_baseline.json`、`test_greenfield_legacy_guard.py`、sha256 冻结清单 41 个文件、C# 源码、`tests/unit/test_greenfield_acceptance.py`。
- **P0-D 档位结论待用户拍板，本 Agent 未代拍**；`xml_package_unverified` 保持 `True`，未代消除。
- 无绝对日期 / 人力排期、无编造数据；外部依据均为项目内 F/K 归档与本次真实运行返回。

---

## 附录 · 批次 3 收口补充（2026-11-07，主 agent）

> 本节为追加记录，不修改上文任何批次 2 既有结论。依据契约 `13-batch3-contract.md`。

### A. 用户拍板与 Gate-0

用户 2026-11-06 以编号「1」拍板 **P0-D = 坚持 AF Basic 文件夹版**（`docs/greenfield/11-p0d-decision.md`）。
加上 Agent K 已真机修复 K1 探针（`08-k1-probe-fix.md`），Gate-0 两项前置逐项解除，
由 `conditional-go` 升为 **`go`（准入放行）**，详见 `06-gate0-report.md` §7。
`go` 不等于 L1∧L2∧L3∧L4 全绿、不等于 M4 可签署。

### B. 批次 3 新增真机证据

| 证据文件 | 内容 | 结论 |
|---|---|---|
| `evidence/uc04_package_probe.json` | 包级 K1 复测 | **未通过**：`SW.PlcBlockGroup` 不可导入；Call 网络 OB 导入失败（`call_db` 命名约束）。`xml_package_unverified` 保持 `True` |
| `evidence/uc15_step7_real.json` | Action B 真机（步骤 7） | `error_count=0` / `warnings=[]` / `compile_ok=true`，`.zap19` sha256 `033e7dc0…`（326869 bytes） |
| `evidence/uc16_incremental_real.json` | 六条增量 | `/open`=1、句柄复用、3× 编译 0/0、PCEC 3 条、六字段真实值；`base_spec_version=null`、增量 fidelity 未闭环 |
| `evidence/uc18_compile_feedback_real.json` | 编译错误回喂 | 真机三段 `errorCount` **0 → 2 → 0**，`heal_ok=true`，账本可追溯；首次过程性失败如实留痕 |
| `evidence/uc15_restart_recovery.json` | 真实服务重启恢复 | gateway 启停两轮，`data.spec` 完全一致，`spec_hash` 与九步步骤 4 吻合 |

### C. 离线链与 EvidenceBundle

`evidence/nine_steps_offline_run.json`：Agent Q 用进程内 ASGI TestClient 真实驱动 §9.2 九步，
**pass=8 / pending_real_machine=1（步骤 7）/ fail=0**；步骤 7 由 R 真机补齐，步骤 9 由主 agent 升级为真实服务重启验证。
`evidence/uc15_evidence_bundle.json`：批次 2 缺的 3 项真机工件已依据 R 的真实结构化证据补齐，12 项全量工件齐备。

### D. RTM 与 M4 判定（诚实口径）

- `UC-01` / `UC-15` / `UC-18` 由 `pending_real_machine` 转 **pass**（均附真机证据三件套与复现命令）；
- **`UC-04` / `UC-16` 如实保持 `pending_real_machine`**，未为凑数标 pass；
- 最终 `by_status`: `pass=17 / fail=0 / pending_real_machine=2 / not_run=0`；
- L2 因 UC-04 未通过、L4 因 UC-16 未通过 → **`L1∧L2∧L3∧L4` 仍未全绿**；
- pending 台账 `cleared=false`、历史 items 未删；**M4 未通过 / 不可签署，签署栏仍待用户本人签署**；
- `xml_package_unverified` 保持 `True`，消除须以 UC-04 包级全链真实通过为唯一依据。
