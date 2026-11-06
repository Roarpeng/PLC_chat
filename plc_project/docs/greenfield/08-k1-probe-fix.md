# UC-04 K1 探针修复报告（自产 XML 可导入性）· 批次 2 · Agent K

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 2 · **Agent K · UC-04 K1 探针修复（自产 XML 可导入性）** |
| 分支 / 基线 | `dev/greenfield-wp` / `9f7186b`（**未执行任何 git 操作**） |
| 日期 | 2026-11-06 |
| 契约 | `05-parallel-wp2-contract.md` §1 / §4 UC-04 / §6 诚实口径；`04-parallel-wp-contract.md` §0 |
| 前序依据 | F 的 `research/Gate0_环境与档位实测_2026-11-06.md` §6、`docs/greenfield/06-gate0-report.md` §3 |
| 真机探针 | `industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe --cli ...` |
| Python | `<R>/.venv/Scripts/python.exe` |
| 真机副本根 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_k1_20261106/`（只读源 `PLC_Openness_data/openness_e2e/CanvasE2E`，仅 `cp`，从未打开/写回原始 `.ap19/.zap19`） |
| 独占改动 | `gateway/app/services/plc/tia_delivery.py`（**仅自产 XML 生成/清单部分**）、**新增** `tests/unit/test_greenfield_k1_probe.py`、**新增** 本报告 |

---

## 0. 判定摘要

> **UC-04 K1 探针（临时副本 / 探针级）：通过。**
> 自产 OB XML 的两个真实缺陷（culture `en-US` 不匹配、`StructuredText/v4` namespace 不正确）
> 已修复；修复后的自产 OB XML 在 **TIA V19 真机副本**上 **导入成功**，且空网络 OB 导入后
> **编译 `errorCount=0 / warningCount=0 / state=Success`**（与基线持平，无新增错误）。

- 证据全部来自 `TiaOpenness.Server.exe --cli` 的真实返回（见 §4），非 mock / 非离线推断。
- **但本轮不擅自消除 `xml_package_unverified`**：代码里该标志**保持 `True`**，处置建议见 §5，
  由主 agent 收口决定。本轮是**探针级**复测（用 `_render_ob_xml` 直接生成 + CLI `import-xml`），
  不是 `deliver_tia` auto 通道的端到端真机验收（UC-15 / M4 属 WP-10）。
- **不宣称 L2/L4 通过、不宣称「Greenfield 全链编译零错误」**；`errorCount=0` 仅对应
  「向 CanvasE2E 副本导入一个空网络 OB 后」这次真机编译。

---

## 1. 定位：自产 XML 与真实 V19 导出先例

### 1.1 自产 XML 的生成位置（代码内字符串模板，无独立模板文件）

`gateway/app/services/plc/tia_delivery.py`：

| 产物 | 生成位置 | 形态 |
|---|---|---|
| `xml_supplement/ob/*.xml` | `_render_ob_xml`（line ~400）→ `_render_multilingual` / `_render_call_network` / `_render_empty_network` | **代码内 f-string 字符串常量**，由 `build_xml_supplement`（line ~508）遍历 `blocks_manifest` 中 `block_type=="OB"` 的条目调用 |
| `xml_supplement/folders.json` | `build_xml_supplement` 内 `json.dumps({"folders":..., "note": _FOLDER_NOTE})` | **文档化清单**（`_FOLDER_NOTE`，line ~64），非 SimaticML 对象，不是 `import-xml` 目标 |
| `xml_supplement/manifest.json` | `_stage_package`（line ~742） | 诚实标注 `xml_package_unverified` / `pending_real_machine` |

> 结论：**没有独立 XML 模板文件**，全部是 `tia_delivery.py` 内字符串常量，故只改该文件。
> `folders.json` 的分组可经 `create-block-group`（F §5.3 已 3× 实测成功）建立，但
> `SW.PlcBlockGroup XML` 可导入性**仍未确证**（本轮未测，见 §7）。

### 1.2 真实 V19 导出先例与黄金参考样本

| 文件 | 作用 |
|---|---|
| `PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/OB1Main.xml` | **真实 V19 Openness 导出先例**（LAD OB，`FlgNet/v5`，空 CompileUnit 用 `<NetworkSource />`） |
| `Temp/gf_real_gate0_20261106/cases/uc01_obnum_real/OB123_from_real.xml` | **黄金参考**：真实先例最小改 `Name`/`Number` + 仅保留 `zh-CN`；F 实测 `import.ok=true`，编译 `errorCount=30`（引用不存在块） |
| `Temp/gf_real_gate0_20261106/uc04/OB1Main.xml` / `OB123Unit01.xml` | F 归档的**修复前自产** OB XML（culture 三语言 + `StructuredText/v4` 空网络），导入失败 |
| `Temp/gf_real_gate0_20261106/uc04/OB123_ref_fixed.xml` | F 的诊断变体（仅 zh-CN + `FlgNet/v5` 空网络）；**未真机验证导入**（`cases/uc04_diag/import_variant.json` 为路径风格 `not_found`，见 §1.3） |

### 1.3 F 的两个真实缺陷（复述，作为修复依据）

| 缺陷 | F 真机失败码 / 原始返回 | 依据 |
|---|---|---|
| ① culture | `openness_error`：`Cannot import multilingual text with culture 'en-US' at line number 37 ... does not exist within the current project.`（`cases/uc04_ob1/import.json`，exit=4） | 自产模板硬编码 `zh-CN/en-US/de-DE`（复刻自 hr001 三语言项目），目标项目 CanvasE2E 不含 `en-US`/`de-DE` |
| ② namespace | `The namespace 'http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v4' is incorrect.`（`cases/uc04_diag2a/import.json`） | `ProgrammingLanguage=LAD` 却用 SCL/ST 的 `StructuredText/v4` 空网络；真实先例用 `FlgNet/v5`，空 CompileUnit 用 `<NetworkSource />` |

> F 的诊断变体 `a_zhCN_only.xml`（仅 zh-CN）**绕过 culture 后仍失败于 `StructuredText/v4`**，
> 反证两缺陷相互独立、都在自产模板本身；最小改动真实先例（仅 Name/Number/culture）即可导入
> 成功，反证 V19 本身接受 OB XML 导入。

---

## 2. 逐字段对照表（自产 XML vs 真实 V19 先例）

| # | 字段 | 真实 V19 先例 `hr001/OB1Main.xml` | 修复前自产 `_render_ob_xml` | 缺陷判定 | 修复后自产 |
|---|---|---|---|---|---|
| 1 | 根 / Engineering | `<Document>` + `<Engineering version="V19" />` | 同 | 一致 | 不变 |
| 2 | OB 元素 | `<SW.Blocks.OB ID="0">` | 同 | 一致 | 不变 |
| 3 | Interface namespace | `.../SW/Interface/v5` | 同 | 一致 | 不变 |
| 4 | `MultilingualText` culture | `zh-CN` / `en-US` / `de-DE`（hr001 项目自身 3 语言） | `zh-CN` / `en-US` / `de-DE`（硬编码复刻） | **缺陷①**：目标项目仅含 `zh-CN`，多余 culture → `openness_error` | 仅 `zh-CN`（项目实际支持语言） |
| 5 | `NetworkSource`（有 Call 网络） | `<FlgNet xmlns=".../FlgNet/v5">` + `<Call>` + `<Instance>` + `<Wire>`(`Powerrail` + `NameCon en`)，如 `:83-99` | `_render_call_network` 已是 `FlgNet/v5` 同构 | 一致（本分支无缺陷） | 不变 |
| 6 | `NetworkSource`（空网络 / 无 Call） | `<NetworkSource />` 空自闭合（空 CompileUnit，`:1140`） | `<StructuredText xmlns=".../StructuredText/v4">` + `<Token Text=";" UId="21" />` | **缺陷②**：LAD 下 namespace 不正确 | `<NetworkSource />` |
| 7 | `ProgrammingLanguage` | `LAD` | `LAD` | 一致（但空网络 ST 形态与 LAD 冲突） | 不变 |
| 8 | `<Number>` | `1` | 参数化（IR `ob_numbers` 交叉核对，K6/K7） | 一致 | 不变 |
| 9 | `<AutoNumber>` | `false` | `false` | 一致 | 不变 |
| 10 | `<SecondaryType>` | `ProgramCycle` | 参数化（Main/Startup） | 一致 | 不变 |
| 11 | `SW.PlcBlockGroup` / `folders.json` | 不作为独立 OB XML 对象导出 | 文档化清单 `folders.json` | 可导入性未确证（**遗留**，非本轮缺陷） | 不变（明确降级） |

---

## 3. 修复内容（只改自产 XML 生成部分）

### 3.1 culture（缺陷①）

`tia_delivery.py`：新增模块常量 `_OB_MULTILINGUAL_CULTURES = ("zh-CN",)`；
`_render_multilingual` 的 for 循环由硬编码 `("zh-CN", "en-US", "de-DE")` 改为遍历该常量。

- **依据（不猜测）**：F 的**真机**诊断变体（仅 zh-CN 绕过 culture 校验）与黄金样本
  `OB123_from_real.xml`（仅 zh-CN，`import.ok=true`）双重验证。
- **语义**：`MultilingualTextItem` 的 culture 必须是**目标项目已存在的语言**；多余 culture
  报 `openness_error`、缺失 culture 不报错。真实先例的 3 culture 是 hr001 项目自身配置，
  不是通用可导入格式。收敛到中文项目通用的 `zh-CN`；**资料缺失时明确降级，不静默近似**
  其它语言（未虚构 en-US/de-DE 文本）。
- `_render_ob_xml` / `build_xml_supplement` 签名与参数**不变**（F 的复现命令可原样复跑）。

### 3.2 namespace（缺陷②）

`tia_delivery.py`：`_render_empty_network()` 由

```
<NetworkSource><StructuredText xmlns=".../StructuredText/v4">
  <Token Text=";" UId="21" />
</StructuredText></NetworkSource>
```

改为

```
<NetworkSource />
```

- **依据（不猜测）**：真实 V19 导出先例 `OB1Main.xml:1140` 的空 CompileUnit 就是
  `<NetworkSource />` 自闭合（无 FlgNet、无 StructuredText）；改回先例形态，**不引入**
  `StructuredText/v4` 错误 namespace，也不自行构造可能违反 LAD rung 约束
  （`A rung must have at least two connections ...`，F §6.3）的伪 FlgNet 网络。
- 有 `call_db` 的 `_render_call_network`（`FlgNet/v5` + 完整 2-connection Wire）**保持原样**，
  本就与先例 `:83-99` 一致。

### 3.3 保持不变（诚实口径 / 所有权边界）

- `xml_package_unverified` 在 `build_xml_supplement` / `_stage_package` / `deliver_tia`
  回执中的值**全部保持 `True`**，未改一处赋值。
- `ob_entries` 留空、`greenfield_upload.py` 不虚构条目：未改（不属本 Agent 所有权）。
- **Agent G 的会话模式段**（`SessionModeTiaPort` / `TiaSessionPort` /
  `run_incremental_writebacks` / `session_mode_enabled` / `_run_session_mode_import_compile`，
  line 1346+）**原样保留，一行未动**。
- 未改 `greenfield.py` / `greenfield_service.py`（H）、前端（J）、C# `industrial/`、
  `planner.py` 等冻结文件；**未新增任何 import**（白名单 `test_sanctioned_phase2_module_whitelist`
  只查 import，不受影响）。

---

## 4. UC-04 真机复测（V19，临时副本）

### 4.1 环境与结构化证据

`--cli status`（真实，`Temp/gf_real_k1_20261106/status.json`）：

```json
{"ok":true,"tiaRunning":false,"processCount":0,"opennessAvailable":true,
 "opennessGroupInToken":true,"tiaVersion":"V19",
 "engineeringDll":"C:\\Program Files\\Siemens\\Automation\\Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll",
 "connected":false,"projectOpen":false}
```

| 项 | 值 |
|---|---|
| TIA 版本 | `V19`（`status.tiaVersion`，`engineeringDll` 含 V19） |
| Openness | `opennessAvailable=true`、`opennessGroupInToken=true` |
| 只读源 | `PLC_Openness_data/openness_e2e/CanvasE2E`（仅 `cp`） |
| 临时副本 A | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_k1_20261106/caseA/proj/CanvasE2E.ap19` |
| 临时副本 B | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_k1_20261106/caseB/proj/CanvasE2E.ap19` |
| 子进程超时 | 每个真机子进程 `timeout -k 5 180` |
| 自产 XML | `OB123_K1Fixed.xml`（空网络 `<NetworkSource />` + 仅 zh-CN + Number=123）、`OB124_K1Fixed_Call.xml`（`FlgNet/v5` Call 网络 + 仅 zh-CN + Number=124），均由**修复后** `_render_ob_xml` 生成 |
| D12 | 无在线下载 / online / run-stop / compare-to-PLC、无 F-block/Safety、无 UI 自动化；全程 `withoutUi` 工程侧离线 |

### 4.2 复现命令（Git Bash）

```bash
R="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"
EXE="$R/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe"
PY="$R/.venv/Scripts/python.exe"
SRC="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/PLC_Openness_data/openness_e2e/CanvasE2E"
W="/c/Users/vboxuser/AppData/Local/Temp/gf_real_k1_20261106"
WW="C:/Users/vboxuser/AppData/Local/Temp/gf_real_k1_20261106"

# 1) 只读复制临时副本（每 case 独立），禁止打开/写回原始 .ap19/.zap19
mkdir -p "$W/caseA/proj" "$W/caseB/proj"
cp -r "$SRC"/. "$W/caseA/proj/"; cp -r "$SRC"/. "$W/caseB/proj/"

# 2) 用修复后的 _render_ob_xml 生成自产 OB XML（与 F §2.4 复现参数一致）
cd "$R" && "$PY" -c "
from gateway.app.services.plc.tia_delivery import _render_ob_xml
import pathlib
out = pathlib.Path(r'$WW')
for name,num,db in [('OB123_K1Fixed',123,''),('OB124_K1Fixed_Call',124,'K1_CallUnit_DB')]:
    x = _render_ob_xml(ob_name=name, ob_number=num, secondary_type='ProgramCycle',
                       call_db=db, title='AF V1.2 '+name, tia_version='V19')
    (out/(name+'.xml')).write_bytes(x.encode('utf-8-sig'))
"

# 3) status 预检
timeout -k 5 180 "$EXE" --cli status

# 4) caseA：空网络 OB 导入 / 列块 / 编译
APW="$WW/caseA/proj/CanvasE2E.ap19"
timeout -k 5 180 "$EXE" --cli import-xml   --project "$APW" --xml "$WW/OB123_K1Fixed.xml" --kind auto
timeout -k 5 180 "$EXE" --cli list-blocks  --project "$APW" --type OB
timeout -k 5 180 "$EXE" --cli compile-plc  --project "$APW" --plc PLC_1

# 5) caseB：FlgNet Call 网络 OB 导入 / 列块 / 编译（独立副本）
APW="$WW/caseB/proj/CanvasE2E.ap19"
timeout -k 5 180 "$EXE" --cli import-xml   --project "$APW" --xml "$WW/OB124_K1Fixed_Call.xml" --kind auto
timeout -k 5 180 "$EXE" --cli list-blocks  --project "$APW" --type OB
timeout -k 5 180 "$EXE" --cli compile-plc  --project "$APW" --plc PLC_1
```

### 4.3 caseA 真实返回（空网络 OB，`<NetworkSource />` + 仅 zh-CN + Number=123）

| 步骤 | 关键字段（真实 CLI 返回） | exit |
|---|---|---|
| `import-xml` | `import.ok=true`、`importedNames=["OB123_K1Fixed"]`、`api="BlockGroup.Blocks.Import(FileInfo, ImportOptions.Override)"`、`save.ok=true` | 0 |
| `list-blocks --type OB` | `count=2`；`Main`(OB,1,LAD)、`OB123_K1Fixed`(OB,**123**,LAD) | 0 |
| `compile-plc` | `compile.ok=true`、`apiAvailable=true`、`state=Success`、**`errorCount=0`**、**`warningCount=0`**、`message="Compile State=Success errors=0 warnings=0"` | 0 |

`caseA/import.json` 关键字段原文：

```json
{"import":{"ok":true,"xmlPath":"C:\\...\\OB123_K1Fixed.xml","overwrite":true,"kind":"block",
 "importedNames":["OB123_K1Fixed"],
 "api":"BlockGroup.Blocks.Import(FileInfo, ImportOptions.Override)",
 "message":"Imported 1 item(s): OB123_K1Fixed."},
 "save":{"ok":true,"message":"Project saved."}}
```

`caseA/compile.json` 关键字段原文：

```json
{"compile":{"ok":true,"apiAvailable":true,"state":"Success","errorCount":0,"warningCount":0,
 "inconsistentBlocks":["Compiling finished (errors: 0; warnings: 0)"],
 "message":"Compile State=Success errors=0 warnings=0"}}
```

> 对比 F 的基线编译（CanvasE2E 副本，`errorCount=0`）：导入自产空网络 OB 后编译仍
> `0/0 Success` → **无新增错误**。这是本轮 K1 主判定依据。

### 4.4 caseB 真实返回（`FlgNet/v5` Call 网络 + 仅 zh-CN + Number=124）

| 步骤 | 关键字段（真实 CLI 返回） | exit |
|---|---|---|
| `import-xml` | `import.ok=true`、`importedNames=["OB124_K1Fixed_Call"]`、`save.ok=true` | 0 |
| `list-blocks --type OB` | `count=2`；`Main`(OB,1)、`OB124_K1Fixed_Call`(OB,**124**,LAD) | 0 |
| `compile-plc` | `compile.ok=false`、`state=Error`、**`errorCount=2`**、`warningCount=0`、`inconsistentBlocks=["OB124_K1Fixed_Call"]` | 6 |

`caseB/compile.json` 关键字段原文：

```json
{"compile":{"ok":false,"apiAvailable":true,"state":"Error","errorCount":2,"warningCount":0,
 "inconsistentBlocks":["OB124_K1Fixed_Call"],
 "message":"Compile State=Error errors=2 warnings=0",
 "error":{"code":"compile_failed","compilerErrors":["PLC_1 ","Compiling finished (errors: 2; warnings: 0)"],"retryable":false}}}
```

> **诚实口径**：caseB 的 `errorCount=2` 是**真实编译失败**，非编造、非掩盖。原因是该
> Call 网络引用了占位实例 DB `K1_CallUnit_DB` / FB `K1_CallUnit`，在空 CanvasE2E 项目中
> 不存在（与 F 的黄金样本 `OB123_from_real.xml` 编译 30 错误同性质）。**导入 `ok=true`
> 已证明 `FlgNet/v5` + culture 修复有效**；编译错误属内容依赖，不是 XML 模板 / namespace
> 缺陷，且 caseB **不作为** K1「编译无新增错误」的判定样本（该判定用 caseA 的无外部依赖
> 空网络 OB）。

### 4.5 证据文件索引（均在临时副本根，非仓库内）

| 文件 | 内容 |
|---|---|
| `status.json` | V19 / Openness 预检 |
| `OB123_K1Fixed.xml` / `OB124_K1Fixed_Call.xml` | 修复后 `_render_ob_xml` 自产 XML |
| `caseA/{import,list_ob,compile}.json` | 空网络 OB 导入 / 列块 / 编译原始返回（K1 主判定） |
| `caseB/{import,list_ob,compile}.json` | FlgNet 分支导入 / 列块 / 编译原始返回（补充佐证） |
| `caseA/proj/` / `caseB/proj/` | 两份临时 `.ap19` 副本（只在此打开 / 保存） |

---

## 5. 判定与 `xml_package_unverified` 处置建议

### 5.1 K1 探针判定

- **K1（自产 OB XML 可导入性）在临时副本 / 探针级：通过。** 两个缺陷（culture、
  namespace）均修复；caseA 导入成功 + 编译 `0/0 Success` 且无新增错误；caseB 导入成功
  证明 `FlgNet/v5` 分支同样可导入。
- 对照 F 的失败：修复前 `openness_error`（en-US）/`StructuredText/v4 is incorrect`；
  修复后两者均不再出现。

### 5.2 `xml_package_unverified` 处置建议（**不擅自消除**）

> **建议：本轮保持 `xml_package_unverified = True`**（代码未改任何一处赋值），
> 由主 agent 收口决定是否消除。给出结论与依据如下，供收口判断：

**支持「可考虑消除」的依据**：K1 针对的自产 `xml_supplement/ob/*.xml` 已由 V19 真机
证实可导入（caseA/caseB 双分支），F 报告 §3 所记的「自产 OB XML 不可导入」这一具体阻断
已解除。

**仍建议保持 True / 收口前须补齐的项**：

1. **`folders.json` / `SW.PlcBlockGroup XML` 可导入性仍未确证**（F §3.3 / 06 报告附录 C-3）：
   本轮未测；它是文档化清单，不是 `import-xml` 的 SimaticML 对象。若要把整个
   `xml_supplement` 包标为「已验证」，需单独确证或明确降级范围。
2. **本轮是探针级复测，非 `deliver_tia` auto 通道真机验收**：用 `_render_ob_xml` 直接生成
   + CLI `import-xml`，未跑 WP-10 的端到端全链（自然语言 → 冻结 → 生成 → 导入 → 编译，
   UC-15 / M4）。`L1∧L2∧L3∧L4` 未达成。
3. **完整 Greenfield 工程包的 Main/Startup OB 走 Call 网络**，会引用 Unit/EM 实例 DB；
   caseB 的 `errorCount=2` 提示：只有相应 FB/DB 齐备时编译才可能 0 错误。本轮未在
   完整 AF 工程包语境下验证「整套自产 XML + SCL + 标签表」联合导入编译。
4. **`pending_real_machine` / M4 门禁**由主 agent 统一清零（契约 §1.4 / §6），单 Agent
   不改全局判定。

> 结论口径：K1 探针**通过**（有真机证据），但 `xml_package_unverified` 的消除涉及上述
> 包级 / 全链范围，**本 Agent 不代拍、不擅自改 False**。

---

## 6. 单测结果（离线，不连真机）

新增 `tests/unit/test_greenfield_k1_probe.py`（8 个用例，纯字符串 / 纯函数断言）：

| 用例 | 断言 |
|---|---|
| `test_ob_xml_cultures_match_target_project_language` | culture 仅 `zh-CN`，无 `en-US`/`de-DE`；3 个 MultilingualText 块各 1 culture |
| `test_ob_xml_never_uses_structuredtext_v4_namespace` | 不含 `StructuredText/v4` / `StructuredText` / `<Token>`；含 `Interface/v5` |
| `test_ob_xml_call_network_uses_flgnet_v5_like_precedent` | 有 call_db → `FlgNet/v5` + `CallInfo` + `Instance/Component` + `Powerrail` + `NameCon en`（逐字段对照先例 `:83-99`） |
| `test_ob_xml_empty_network_matches_precedent_empty_compileunit` | 空网络为 `<NetworkSource />`，无 FlgNet / 无 StructuredText（对照先例 `:1140`） |
| `test_ob_xml_structure_stable_and_reproducible` | 除时间戳外两次渲染逐字节相等；根 / Engineering / OB / Number / LAD 骨架稳定 |
| `test_build_xml_supplement_no_fabricated_ob_when_no_ob_in_manifest` | OB manifest 为空 → `ob_files={}`、`generated_obs=[]`、不虚构 OB |
| `test_folders_json_is_documentation_manifest_not_simaticml` | `folders.json` 含 note / folders，非 `<Document>` / `<SW.Blocks` 对象 |
| `test_manifest_keeps_xml_package_unverified_true` | `xml_package_unverified` 保持 `True`（诚实口径，不擅自消除） |

验证命令（任务指定 4 个文件）：

```
cd <R> && ./.venv/Scripts/python.exe -m pytest \
  tests/unit/test_greenfield_k1_probe.py \
  tests/unit/test_greenfield_tia_delivery.py \
  tests/unit/test_greenfield_session_mode.py \
  tests/unit/test_greenfield_legacy_guard.py -q
```

结果：**`34 passed`**（含 `test_frozen_legacy_files_have_zero_diff` 零 diff 护栏 PASS、
`test_sanctioned_phase2_module_whitelist` PASS）。

> 本文件为离线单测，**不构成 L2/L4 证据、不宣称真机导入成功或「编译零错误」**；
> 真机数字全部来自 §4 的真实 CLI 返回。

---

## 7. 已知遗留（诚实清单）

1. **`folders.json` / `SW.PlcBlockGroup XML` 可导入性未确证**：仍是文档化清单；分组可经
   `create-block-group` 建立（F 已实测），但 XML 直接导入未测。
2. **未跑 Greenfield 端到端全链**（UC-15 / WP-10 / M4）；本轮为探针级（直接调
   `_render_ob_xml` + CLI `import-xml`），非 `deliver_tia` auto 通道真机验收。
3. **caseB 编译 `errorCount=2` 是真实失败**（占位实例 DB 不存在），非模板缺陷；完整 AF
   工程包联合导入编译未验证，「整套包编译零错误」未达成、未宣称。
4. **culture 收敛到 `zh-CN` 的适用边界**：对含 `zh-CN` 的中文项目（如 CanvasE2E）已真机
   验证；**纯英文 / 其它语言项目**未测——若目标项目不含 `zh-CN`，仍可能触发同类
   `openness_error`。属于「资料缺失明确降级」场景，本轮未做自适应项目语言的动态探测
   （避免无真机依据的猜测）。建议收口阶段如需多语言，按目标项目语言配置
   `_OB_MULTILINGUAL_CULTURES` 并各自真机复测。
5. **`xml_package_unverified` 保持 `True`**，UC-04 的全局状态与 M4 门禁由主 agent 收口；
   本 Agent 未改判定、未代拍。
6. **P0-D 档位结论仍待用户拍板**（F 报告 §6），与本次 K1 修复正交，本轮不涉及。
7. **未执行任何 git 操作**；未改 `legacy_baseline.json`、`test_greenfield_legacy_guard.py`、
   sha256 冻结清单 41 个文件、C# `industrial/`、前端、H 的 greenfield 服务、Agent G 会话段。

---

## 8. 合规与诚实口径声明

- 真机操作**只在** `Temp/gf_real_k1_20261106/` 临时副本上进行；`PLC_Openness_data/`
  原始 `.ap19/.zap19` 仅被 `cp` 读取，从未打开、从未 `SaveProject()` 写回原始路径；
  未删除任何原始文件。
- 每个真机子进程 `timeout -k 5 180`；所有数字（导入结果、`errorCount` / `warningCount` /
  `state`、exit code、TIA 版本）均来自真实 CLI 返回。
- D12 hard refuse：无在线下载 / online / run-stop / compare-to-PLC，未碰 F-block/Safety，
  无 UI 自动化；全程 `withoutUi` 工程侧离线。
- **未以 mock / 离线单测宣称 L2/L4 通过或「编译零错误」，未把 `tia_unavailable` /
  `pending_real_machine` 说成成功，未编造任何真机结果**（caseB 的 2 个编译错误如实记录）。
- 未执行任何 git 操作；未改冻结清单 / 白名单基线 / 他人所有权文件。

---

## 9. 收口状态说明（Agent L · 批次 2 收口，2026-11-06）

> 本节为**状态追加**，不修改 §0–§8 任何结论；K1 探针判定、`xml_package_unverified`
> 处置建议、真机证据与单测数字一律以 §0 / §4 / §5 / §6 原文为准。

| 项 | 状态 |
|---|---|
| K1 探针（自产 OB XML 可导入性） | **探针级已通过、待全链验证**。§4 caseA：V19 真机副本导入 `ok=true`、编译 `errorCount=0 / warningCount=0 / state=Success`；caseB 导入亦成功（`errorCount=2` 属占位实例 DB 缺失，为真实失败但非模板缺陷）。仅代表探针级结论，不代表包级 / 全链通过 |
| `xml_package_unverified` | **本轮保持 `True` 不改**（§5.2 依据：`folders.json` / `SW.PlcBlockGroup XML` 可导入性未确证、`deliver_tia` auto 通道端到端全链 UC-15 / M4 未跑、完整 AF 工程包联合导入编译未验证） |
| 待验证 | ① `folders.json` / `SW.PlcBlockGroup XML` 可导入性；② UC-15 端到端全链（自然语言 → 冻结 → 生成 → 导入 → 编译）；③ 整套自产 XML + SCL + 标签表联合导入编译 |
| L2 / L4 / M4 | 仍 `pending_real_machine`；K1 探针通过**不构成** L2/L4 通过，不宣称「Greenfield 全链编译零错误」；N9 `fidelity_ok` 与 `compile_ok` 严格分离 |
| `evidence/rtm.json` | 状态判定**本轮不改**（归真机验收 agent / 主 agent）；rtm 中 UC-04 的 F 早期失败事实与本节 K 的探针级通过属并行时序差异，均如实留痕 |

**结论口径**：K1 探针级已通过、待全链验证；`xml_package_unverified` 保持 `True`，
全局 UC / M4 判定由主 agent 收口，本 Agent 不代拍、不改已有结论。
