# Gate-0 准入报告（WP-00 · Agent F）

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 2 · Agent F（Gate-0 准入 / AF 档位实测 / 事实核验包） |
| 分支 / 基线 | `dev/greenfield-wp` / `9f7186b`（**未执行任何 git 操作**） |
| 日期 | 2026-11-06 |
| 契约 | `docs/greenfield/05-parallel-wp2-contract.md`（§0/§1/§4/§6）；`04-parallel-wp-contract.md` §0 |
| 依据 | Plan v1.0 §3 G0 / §5 WP-00 / §6.1 / §7.1 UC-01·UC-04 / §9.3；基线报告 §6 P0-D / §11.2 / §12 / §13.11 |
| 真机探针 | `industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe --cli status` |
| 真机副本根 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_gate0_20261106/`（只读源 `PLC_Openness_data/openness_e2e/CanvasE2E`，仅 `cp`，从未打开/写回原始文件） |
| 新增文件 | `tools/gate0_precheck.py`、本报告、仓库根 `research/Gate0_环境与档位实测_2026-11-06.md`（`<R>/research` 不存在，按任务要求落仓库根） |
| 产品代码改动 | **无**（未碰 `gateway/`、`plc_engine/`、`agents/`、`frontend/`、`industrial/`、冻结清单、C# 源码） |

---

## 0. 判定摘要

> **Gate-0 判定：`conditional-go`（有条件放行）**

- 环境四件套 **4/4 通过**（STEP 7 许可已由一次**真实 `compile-plc` 编译**验证有效，非 mock/离线推断）；
- 档位对照表 + V19 真机最小样例导入/编译**真实结果**已产出；Q7 核验包三态标注完成；
- 但 **P0-D 档位结论须由用户拍板（本 Agent 不代拍）**，且 **UC-04 K1 探针实测失败**（自产 XML 不可导入，`xml_package_unverified` 不能消除）。因此**不满足 Plan §3 G0 的完整 `go` 判据**，不得进入「档位相关映射层定型」。
- **在用户拍板前，映射层维持「档位无关」设计**（Plan §0 Q5 / §9.3、契约 §1.3），仅推进离线可工作包。
- 本报告**不宣称 L2 / L4 通过、不宣称「全链编译零错误」**；所有编译数字均为对应副本上的真实 CLI 返回。

---

## 1. 四件套预检结果（Plan §6.1）

脚本：`tools/gate0_precheck.py`（标准库，复用真实探针，fail-closed，不静默降级；`python tools/gate0_precheck.py` 可直接调用）。
探针原始返回：

```json
{"ok":true,"tiaRunning":false,"processCount":0,"opennessAvailable":true,
 "opennessGroupInToken":true,"tiaVersion":"V19",
 "engineeringDll":"C:\\Program Files\\Siemens\\Automation\\Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll",
 "connected":false,"projectOpen":false,
 "message":"TIA Portal process not detected (Openness can still start WithoutUserInterface)."}
```

| # | 预检项 | 判定 | 证据 |
|---|---|---|---|
| 1 | TIA Portal **V19** + 有效 STEP 7 许可 | **pass**（经真实验证） | `tiaVersion=V19`；`engineeringDll` 存在且为 `Portal V19\PublicAPI\V19`。许可有效性由临时副本上真实 `compile-plc` 确认：`apiAvailable=true`、`state=Success`、`errorCount=0`、`warningCount=0`、`exit_code=0`。**`status` 本身不含许可字段**，故脚本默认运行此项为 `unknown`，须用 `--verify-license <临时副本.ap19>` 抬到 `pass`（见 §1.1） |
| 2 | Openness 用户组 token + 防火墙白名单 | **pass** | `opennessGroupInToken=true`；`opennessAvailable=true`（DCOM/白名单可连）。未见显式命名防火墙规则，按契约 §0 同口径以探针可连为间接证据 |
| 3 | V19 版 `Siemens.Engineering.dll` + F-block 拒绝边界 | **pass** | DLL 路径存在且含 `V19`；`BlockService.cs:290/300/360/419/459` 含 `XmlLooksLikeSafety` / `Refusing Blocks.Import for Safety` 硬拒绝；`README.md:53` `Out of scope (hard refuse)` 段落存在 |
| 4 | 项目文件锁归属（D9 专用后台实例） | **pass** | `tiaRunning=false`、`processCount=0`、`connected=false`、`projectOpen=false` → 可用 `WithoutUserInterface` 后台实例独占项目 |

### 1.1 脚本两种调用与 fail-closed 负例（实测）

| 调用 | overall | check1 | 退出码 | 说明 |
|---|---|---|---|---|
| `python tools/gate0_precheck.py` | `unknown` | `unknown` | `2` | 许可未做真实编译验证 → **不静默降级为 pass** |
| `... --verify-license <Temp/gf_real_*/proj2/CanvasE2E.ap19>` | `pass` | `pass` | `0` | 真实编译 `state=Success/errorCount=0` → 许可有效 |
| 负例：`--verify-license` 指向 `PLC_Openness_data` 原始 `.ap19` | `unknown` | `unknown` | `2` | `license_verify=refused`：安全护栏拒绝原始路径，决不误判 pass |
| 负例：`--probe` 指向不存在的 exe | `fail` | 4 项全 `fail` | `1` | 探针不可用 → 全 fail，不降级 |

> 判定口径：许可有效性 = 「编译 API 可真实调用并返回 `State`」，与项目 `errorCount` 无关（errorCount 单列留痕）。脚本对 `--verify-license` 内置 `PLC_Openness_data` 路径拒绝，落实契约 §1.1「只在临时副本上操作」。

---

## 2. UC-01 档位兼容性实测（真机，归属 F）

### 2.1 实测方法与样本

- 源项目 `PLC_Openness_data/openness_e2e/CanvasE2E`（`PLC_1`，含 `Main` OB1、`PumpCtrl` FB1）**只读复制**到 `Temp/gf_real_gate0_20261106/cases/<case>/proj/`，每个 case 独立副本，避免相互污染；每个真机子进程 `timeout -k 5 180`。
- 另测 `HR001_AF_V19` 副本：`open-project` 返回 `ok:false / not_found / "No PLC software found in project."`（空壳项目，无 PLC software）——如实记录，不作为档位结论依据。
- 最小样例 = **1 Unit + 2 EM 的 AF 文件夹版分组结构**（`Unit_01`、`Unit_01/EM_01`、`Unit_01/EM_02`），通过 Openness `BlockGroup` API 构造。
- OB 编号样本：`tia_delivery.py` **自产** `_render_ob_xml`（`Number=1/123`）+ **真机 V19 导出先例** `PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/OB1Main.xml`（最小改 `Name/Number/culture`）。

### 2.2 档位对照表（P0-D 核心产物）

| 维度 | **文件夹版（AF Basic / 块分组）** | **软件单元版（SIOS 109817223 口径）** |
|---|---|---|
| 组织载体 | `PlcSoftware.BlockGroup` → `Groups`（嵌套路径 `Unit_01/EM_01`） | `PlcSoftware.SoftwareUnitGroup.SoftwareUnits` |
| 本机 V19 构造实测 | `create-block-group --group Unit_01` / `Unit_01/EM_01` / `Unit_01/EM_02` **3× `{"ok":true,...,"saved":true}`** | `import-xml --unit Unit_01` 导入成功，但 `list-blocks` 显示 `path="Unit_01/OB123Unit01"` → **落在普通块分组，未创建真正软件单元** |
| CPU 约束 | 经典 CPU（含 S7-1200）即可 | **S7-1500 特性**：`BlockService.cs:703-705` 注释 + `:2231` `"SoftwareUnitGroup not available on this PLC"`；SIOS C1 要求 S7-1500 / V19 Up3 / ProDiag / OPC UA |
| 导入可行性 | **可行**（`create-block-group` 成功、`SaveProject` 成功） | 本机 CPU **不可行**：`FindSoftwareUnit` 返回 null → 回退 `FindOrCreateBlockGroup`（`BlockService.cs:223-226`），静默降级为文件夹分组 |
| OB 编号规则（ueet） | SimaticML XML `<Number>` **可原生指定**：实测 `<Number>123</Number>` → `list-blocks` 显示 `number=123` | 编号机制与档位无关（同左）；但 ueet 公式本身仍为社区来源，见 §4 |
| 编译 `error_count` | 分组结构建立后 `compile-plc`：`errorCount=0 / warningCount=0 / state=Success` | 未干净跑通（受 OB 模板阻断，标 `pending_real_machine`）；用真实先例改号导入后编译 `errorCount=30`（见 §2.3） |
| 与官方 AF/Eigen 生态关系 | PRD 现行口径（`01-greenfield-prd.md:19-26` 明确「不采用 AF V3 软件单元」） | 官方 AF 标准组织方式（C2「每个 Unit 与每个 EM 各有独立 Software Unit」） |

### 2.3 导入 / 编译真实结果（关键字段）

| Case | 命令（复现见归档 §2） | 真实返回关键字段 | 退出码 |
|---|---|---|---|
| 基线编译（许可验证） | `compile-plc --project <CanvasE2E 副本>` | `compile: ok=true, apiAvailable=true, state=Success, errorCount=0, warningCount=0, message="Compile State=Success errors=0 warnings=0"` | 0 |
| 文件夹版 1U+2EM | `create-block-group` ×3 → `compile-plc` | 3× `ok:true/saved:true`；`list-blocks` count=2；`compile errorCount=0` | 0 |
| OB 编号（真实先例改 `Number=123`） | `import-xml --xml OB123_from_real.xml --kind auto` | `import.ok=true, importedNames=["OB123Unit01"], save.ok=true`；`list-blocks OB` → `OB123Unit01 number=123` | 0 |
| 同上 · 编译 | `compile-plc` | **`compile.ok=false, state=Error, errorCount=30, warningCount=0, inconsistentBlocks=["OB123Unit01"], error.code=compile_failed, compilerErrors=["PLC_1 ","Compiling finished (errors: 30; warnings: 0)"]`** | 6 |
| 软件单元落位 | `import-xml --unit Unit_01 --xml OB123_from_real.xml` | `import.ok=true`；`list-blocks` → `path="Unit_01/OB123Unit01"`（普通块分组，非软件单元） | 0 |

> 诚实口径：`errorCount=30` 是**真实编译失败**（真实先例 XML 引用了本项目不存在的 `FB1000_StdSignal`/`DB1000_StdSignal`），不是「编译零错误」，也不以 mock 顶替；基线 `errorCount=0` 仅对应 CanvasE2E 基线副本本身。二者不可混为「UC-01 最小样例端到端零错误」——端到端全链（自然语言→冻结→生成→导入→编译）属 UC-15 / WP-10，本轮未跑。

---

## 3. UC-04 K1 探针（真机，归属 F → G 接线）

判定：**未通过（K1 失败）**。检查对象为 `tia_delivery.py` 自产 `xml_supplement/ob/*.xml`（由 `build_xml_supplement` → `_render_ob_xml` 生成）与 `xml_supplement/folders.json`。**未改 `tia_delivery.py`（Agent G 所有）**。

### 3.1 自产 OB XML 原样导入：失败

`import-xml --project <副本> --xml <自产 OB1Main.xml / OB123Unit01.xml> --kind auto`：

```json
{"import":{"ok":false,"overwrite":false,
 "error":{"code":"openness_error",
 "message":"Error when calling method 'Import' of type 'Siemens.Engineering.SW.Blocks.PlcBlockComposition'.\r\n\r\nCannot import multilingual text with culture 'en-US' at line number 37 at line position 12: the specified culture does not exist within the current project.","retryable":false}}}
```

`exit_code=4`；`list-blocks OB` 仍只有 `Main`（未新增 OB）；`compile-plc` 仍 `errorCount=0`（项目未被改动）。

### 3.2 根因（诊断性变体，非改产品代码）

| 变体 | 真实失败 | 结论 |
|---|---|---|
| 原样自产 XML | `culture 'en-US' ... does not exist within the current project` | 自产模板硬编码 `zh-CN/en-US/de-DE`（复刻自另一项目导出先例），与目标项目语言设置不匹配 |
| 仅保留 `zh-CN` | `The namespace '.../SW/NetworkSource/StructuredText/v4' is incorrect` | 第二根因：`ProgrammingLanguage=LAD` 却用 `StructuredText/v4`；真机 V19 导出先例 `OB1Main.xml:83` 用 `FlgNet/v5` |
| 去掉多语言文本 | 同上 `StructuredText/v4` namespace 错误 | 与 culture 无关的结构性不兼容 |

> 对照物：`PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/OB1Main.xml`（真实 V19 导出）使用 `<FlgNet xmlns=".../FlgNet/v5">` + `<Number>1</Number>` + `<AutoNumber>false</AutoNumber>`，且 culture 同为 `zh-CN/en-US/de-DE`。**最小改动该真实先例（仅改 Name/Number/culture）即可导入成功**（§2.3），反证自产模板的缺陷在模板本身，而非 V19 不接受 OB XML 导入。

### 3.3 `folders.json` 与结论

- `folders.json` 是**文档化文件夹清单**（`tia_delivery.py:63-67` `_FOLDER_NOTE`：文件夹/软件单元分组与 OB 一样不能由 SCL 外部源生成（BR-3），`SW.PlcBlockGroup XML` 可导入性未确证），**本身不是 `import-xml` 的 SimaticML 对象**，不能「直接导入成功」。
- 其描述的分组可经 `create-block-group`（Openness `BlockGroup` API）建立，UC-01 已实测 3× 成功 → 为 Phase 3 自动建立分组提供路径；但 `SW.PlcBlockGroup XML 可导入性` 本轮**仍未确证**。

**UC-04 结论**：自产 OB XML 在 V19 导入失败，`xml_package_unverified` **不可消除，必须保持 `True`**；UC-04 标 `pending_real_machine`（K1 待 Agent G 修复模板后复测）。失败码 `openness_error`；复现命令见归档 §2。

---

## 4. Q7 最小事实核验包（三态标注）

> 口径：Q7 为**最小核验包**，不重做全量调研；依据为项目内已有存档 `research/CODESYS4_WebIDE_调研成果存档_2026-11-06.md` / `...对标差距与下一步建议_2026-11-06.md` 与**本次 V19 真机实测**。本次**未重新联网二次核验**（PL-03 / §9.3 建议对外发布前补独立事实核查）。

| # | 待核事实 | 三态 | 来源 / 本地依据 |
|---|---|---|---|
| ① | Eigen 官方「生成的项目遵循 **Siemens Automation Framework**」表述 | **已查证事实（本地存档转引西门子官方来源）** | 存档 `:112` A5 — [Siemens China 英文新闻稿](https://w1.siemens.com.cn/news_en/news_articles_en/21971.aspx)「生成的项目遵循 Siemens Automation Framework，西门子对 TIA Portal 项目结构的最佳实践参考」；A2/A3 佐证「生成完整标准项目，可直接在 TIA Portal 打开」。**限定**：来源为存档转引，本次未联网复核；基线报告 §11.2 明列「Eigen 生成项目所用 AF 的具体版本与档位」**来源不足**；RK1「档位可能不兼容」是**推断**，非事实（存档 `:135,156` 明确标注「推断，非结论」） |
| ② | SIOS 109817223 软件单元口径 | **已查证事实（存档引用 SIOS 官方手册）+ 本机实测印证** | 存档 `:128` C1 [AF V1.2 中文手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_Automation_Framework_DOC_V1_2_CN.pdf)（ISA-88、要求 TIA V19 Up3 / S7-1500 / WinCC Unified / ProDiag / OPC UA）；`:129` C2 [AF v2.2 英文手册](https://support.industry.siemens.com/cs/attachments/109817223/109817223_AutomationFramework_DOC_V2_2_3_en.pdf)「每个 Unit 与每个 EM 各有独立 Software Unit」；`:130` C3 社区「PLC 结构的解决方案以软件单元为基础」（与 C2 互证）。**本机实测印证**：`--unit` 落位 `path="Unit_01/OB123Unit01"`（回退普通块分组），源码 `:2231` `"SoftwareUnitGroup not available on this PLC"` → 本机 CPU 不具备软件单元能力。**限定**：手册 PDF 为存档引用，本次未下载原件；「Eigen 生成物是否即软件单元版」仍属**推断 / 来源不足** |
| ③ | OB 编号规则（ueet / 不可原生指定） | **推断 / 来源不足（社区 + 行业来源）**，另附**本次真机实测细化证据** | 存档 `:121` B4 [Industrial Monitor Direct](https://industrialmonitordirect.com/blogs/knowledgebase/s7-1200-ob-number-assignment-during-tia-portal-source-import)「TIA Portal 无原生参数指定 OB 编号，按导入顺序算法分配」（行业来源，强度中等）；`:131` C4 [plcjs AF 深度解析](https://bbs.plcjs.com/thread-652457-1-2.html)「AF 强制 OB 编号规则 ueet（u/ee/t，例 OB2001=Unit2 Main）」（社区来源，强度中等）。**实测细化**：SimaticML **XML 导入路径**下 `<Number>` 可原生指定（`number=123` 生效，真实先例亦含 `<Number>`），故 B4「不可原生指定」应限定为**外部源 SCL 导入路径**；ueet 公式本身**未经 SIOS 官方手册确证 → 来源不足**；导入后必须编译（真实先例改号后 `errorCount=30`） |

---

## 5. Gate-0 判定与证据链

### 5.1 Plan §3 G0 `go` 判据逐条核对

| go 判据 | 状态 | 证据 |
|---|---|---|
| 档位对照表 | ✅ | 本报告 §2.2 |
| V19 最小样例导入编译结果 | ✅（真实） | 本报告 §2.3；归档 §3–§5 原始 JSON |
| **明确拍板结论** | ❌ **待用户拍板** | 契约 §1.3 / Plan §0 Q5 / §9.3：Agent **不得代拍** |
| 环境预检全通过 | ✅ | 本报告 §1（`--verify-license` 后 4/4 pass） |
| 核验包结论标注「已查证／推断」 | ✅ | 本报告 §4 三态 |

附加风险项：**UC-04 K1 探针失败**（§3），`xml_package_unverified` 未消除。

### 5.2 判定：`conditional-go`

- 环境、事实口径、档位对照表、真实导入/编译结果均已就绪 → G0 的「准入准备」完成，可放行**离线可工作包**与**档位无关的映射层设计**；
- 但「明确拍板结论」硬缺 + K1 失败，故**不是 `go`**；也未到「全面 `no-go`」（环境可用、实测已产出，非「禁止一切档位工作」）。
- 按 Plan §3 `no-go` 处置与契约 §1.3：**在用户拍板前，映射层维持「档位无关」设计，不进入任何档位相关的映射层定型**。

### 5.3 解除 `conditional-go` → `go` 的前置条件（均非本 Agent 可代）

1. **用户对 P0-D 档位拍板**（Plan §0 Q5 / §9.3）——本 Agent 只给「对照表 + 实测 + 推荐结论 + 依据」，见 §6；
2. **UC-04 K1 复测通过**：Agent G 修复自产 OB XML 模板（culture 适配 + `FlgNet/v5`）后，在 V19 真机导入成功并消除 `xml_package_unverified`；
3. 涉真机验收项在证据栏统一保持 `pending_real_machine`，**M4 发布门禁在 pending 清零前保持未通过**（契约 §1.4 / §6）。

### 5.4 证据链

`status 探针` → `tools/gate0_precheck.py`（四件套 JSON）→ `Temp/gf_real_gate0_20261106/cases/*/{import,list_ob,list_blocks,compile,create_groups}.json`（真机原始返回）→ 本报告 §1–§4 → `research/Gate0_环境与档位实测_2026-11-06.md`（复现命令与原始数据索引）。全程无 mock、无离线结果冒称 L2/L4、无 `tia_unavailable` 包装成功。

---

## 6. P0-D 推荐结论（**待用户拍板，Agent 不代拍**）

> 本节只给「对照表 + 实测 + 推荐结论 + 依据」。**最终档位由用户拍板**（契约 §1.3、Plan §0 Q5 / §9.3）。**结论前映射层维持「档位无关」。**

**推荐结论：坚持「AF Basic 文件夹版」（PRD 现行口径），暂不切「软件单元版」。**

依据（逐条对应 §2.2 对照表与 §2.3 实测）：

1. **本机 CPU 不具备软件单元能力**：`import-xml --unit` 实测回退为普通块分组（`path="Unit_01/OB123Unit01"`）；源码 `BlockService.cs:2231` `"SoftwareUnitGroup not available on this PLC"`，注释 `:703-705` 明确软件单元是 S7-1500 特性。切软件单元版需更换硬件目标（S7-1500 + V19 Up3 + ProDiag/OPC UA，SIOS C1），超出本期范围且与 N8「不把物理组态做进产品」冲突。
2. **文件夹版经 Openness 实测可用**：1 Unit + 2 EM 嵌套分组 3× 创建成功、`SaveProject` 成功、编译 `errorCount=0`。
3. **OB 编号不构成切换理由**：ueet 类编号在 SimaticML XML 路径可通过 `<Number>` 原生指定（实测 `number=123` 生效），无需软件单元；`ob_number_deviations` 留痕机制（基线报告 RK2 / Plan §7.2）继续适用。
4. **与 Eigen/AF 生态的兼容性仍是推断**：RK1「档位可能不兼容」为推断（Q7 ① / 存档 `:135,156`），无直接证据证明「Eigen 生成物 = 软件单元版」；Eigen 生成物具体档位/版本**来源不足**（基线报告 §11.2）。**故不能据此当结论改口径**。
5. **K1 探针与档位选择正交**：自产 XML 导入失败（culture/namespace 缺陷）是 `tia_delivery.py` 模板问题（Agent G 接线），两种档位都需先修复；不构成「必须切软件单元版」的依据。

**触发式应对（Plan §8.4）**：若用户拍板「切软件单元版」→ 冻结映射层定型，重评 F6 / 附录 A / `framework_baseline` 版本，走 §9.2 变更评估。在此之前一律「档位无关」。

---

## 附录 A　Q6 术语三层映射（正式口径归档）

| 用户语言 | 内部 / AF 术语 | 代码对象 | 依据 |
|---|---|---|---|
| **工站** | **Unit**（ISA-88 工艺单元） | `GFUnit` / `AfUnit` | Plan 附录 A / Q6；基线报告附录 A；04 契约 §4 |
| **执行单元** | **EM**（Equipment Module） | `GFEm` / `AfEm` | 同上 |
| **执行件** | **CM**（Control Module） | `GFCm` / `AfCm` | 同上 |

- 展示层：AF 术语 `Unit/EM/CM` 只允许出现在**工程视角面板**；画布用「工站 / 执行单元 / 执行件 / 设备交互」；`business_label` 为现成载体，**禁止改 IR 语义**（04 契约 §4）。
- 遗留：Plan §9.3 提示「若『执行件』实际指 EM+CM 合并，需回编号修正 §4.5 / §5 / 附录 A」——本轮按 Q6 已确认的三层落档，未擅自改口径。

## 附录 B　合规与诚实口径声明

- D12 hard refuse：未做在线下载 / online / run-stop / compare-to-PLC、未碰 F-block/Safety、未做 UI 自动化；所有真机命令为 `withoutUi:true` 工程侧离线操作。
- 未执行任何 git 操作；未改任何产品代码、`legacy_baseline.json`、`test_greenfield_legacy_guard.py`、sha256 冻结清单 41 个文件、C# 源码、`tia_delivery.py`。
- 真机操作**只在** `Temp/gf_real_gate0_20261106/` 临时副本上进行；`PLC_Openness_data/` 原始 `.ap19/.zap19` 仅被 `cp` 读取，从未打开、从未 `SaveProject()` 写回。
- 所有真机子进程 `timeout -k 5 180`；失败一律 fail-closed + 如实记录失败码/复现命令；**未以 mock/离线结果宣称 L2/L4 通过或「编译零错误」，未把 `tia_unavailable` 说成成功**。
- 无绝对日期/人力排期、无编造数据；外部来源均为项目内已有存档转引，三态标注见 §4。

## 附录 C　已知遗留（诚实清单）

1. **P0-D 档位结论待用户拍板**——本 Agent 未代拍；拍板前映射层维持档位无关。
2. **UC-04 K1 未通过**：自产 OB XML 导入失败（`openness_error`：culture `en-US` / `StructuredText-v4` namespace），`xml_package_unverified` 保持 `True`；修复与复测属 Agent G / WP-01。
3. **`folders.json` 非 SimaticML 导入对象**：是文档化清单；其描述的分组经 `create-block-group` 可建，但 `SW.PlcBlockGroup XML` 可导入性仍未确证（`_FOLDER_NOTE` 口径）。
4. **软件单元版「完整导入编译」未在本机干净跑通**（受 OB 模板阻断，标 `pending_real_machine`）；结论基于源码约束 + `--unit` 落位实测，非完整软件单元工程验收。
5. **本机 CPU 具体型号未由本次实验直接读取**（由 `--unit` 回退行为 + `BlockService.cs` 约束推断为经典 S7-1200 类 CPU）。
6. **未跑 Greenfield 生成链全链**（自然语言→冻结→生成→导入→编译），`UC-15` 端到端属 WP-10 / M4；`L1∧L2∧L3∧L4` 未达成，M4 保持未通过。
7. **Q7 为最小核验包，未重新联网核验**（PL-03 / §9.3）；Eigen 生成物具体档位/版本、ueet 公式官方确证均属**来源不足**。
8. **编译 `errorCount=30` 为真实失败**（真实先例 XML 引用不存在块）；仅基线项目编译 `errorCount=0`，二者不可混为「样例端到端零错误」。
9. 诊断过程性失败（如实记录，非主结论）：`export-block Main` 返回 `inconsistent_blocks`（one-shot 独立会话不保留编译态）；若干诊断变体触发 `rung must have at least two connections`、python 路径风格 `not_found` 等，详见归档 §6。
