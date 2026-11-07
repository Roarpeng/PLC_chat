# UC-04 完整 AF 包自洽化修复报告 · 批次 4 · Agent U

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 4 · **Agent U · UC-04 完整 AF 包自洽化（Call 网络 OB + FB + 实例 DB）** |
| 分支 / 基线 | `dev/greenfield-wp` / `3596fb9`（批次 3 收官，未执行任何 git 操作） |
| 日期 | 2026-11-07 |
| 契约 | `14-batch4-contract.md` §0 UC-04 根因 / §1 全局规则 / §2 所有权 / §3 UC-04 判据；`04-parallel-wp-contract.md` §0、`13-batch3-contract.md` §1/§5 继续生效 |
| 前序依据 | `evidence/uc04_package_probe.json`（批次 3 包级失败原始返回）、`docs/greenfield/08-k1-probe-fix.md`（K 的 XML 修复，尤其 §3 对照表 / §4.4 caseB） |
| 阶段 | **阶段 A（离线）**：不连真机 / 不启动 SessionServer / 不跑 TIA CLI / 不占用 8791/8000 |
| 独占改动 | `gateway/app/services/plc/tia_delivery.py`（仅 `_render_call_network` / `_render_ob_xml` + 新增 FB/DB 渲染函数）；**新增** `tools/build_full_af_package.py`、`tests/unit/test_greenfield_full_af_package.py`、本报告 |

---

## 0. 判定摘要（诚实口径）

> **本轮只完成「离线构造一个自洽的完整 AF 包」+ 离线单测。**
> 未连真机、未跑 `import-xml` / `compile-plc`、未启动任何服务。
> **不宣称 UC-04 通过 / 完整包编译零错误 / L2 通过**；`xml_package_unverified`
> 保持 `True`，由主 agent 在阶段 B 的 Agent W 真实结果出来后按证据决定。

- 修复了**两处根因**：① 完整 AF 包缺少被引用的 FB 块与全局实例 DB 块（包不自洽）；
  ② `_render_call_network` 从实例 DB 名反推 FB 名（模板假设错误）。
- 新增最小 FB / 实例 DB 块渲染（结构照真实 V19 导出先例），并产出**引用自洽**、
  **字节级可复现**的完整包（含 `import_order`）。
- 离线单测 `tests/unit/test_greenfield_full_af_package.py` 14 例通过（见 §7）。

---

## 1. 批次 3 的两处真实失败（来自 `evidence/uc04_package_probe.json`）

| # | 失败点 | 真实返回 | 定性 |
|---|---|---|---|
| 1 | `SW.PlcBlockGroup XML` 经 `import-xml --kind auto` / `--kind block` | `exit=4`、`ok=false`、`openness_error`：`Class of the 'Siemens.Engineering.SW.PlcBlockGroup' type at line number 7 ... is not supported.` | **非本轮要修的模板缺陷**：该类型不是可导入的 SimaticML 块对象。同探针里 `create-block-group` Openness API 两次 `ok=true / saved=true`（`AF_Unit_01/AF_EM_01`、`AF_Unit_01/AF_EM_02`），其后 `compile-plc` 仍 `errorCount=0`。产品链走 API，不走 XML 导入。 |
| 2 | Call 网络 OB `GF_U1EM1_CallOB` 导入 | `import.ok=false`、`exit=4`、`openness_error`：`The name 'GF_U1EM1_InstDB' cannot be used for "Call" at the object with UID '21'.` | **本轮主修**：根因见 §2。其余 4 个空网络 OB 导入成功；`joint_compile_raw` 的 `errorCount=0` 是在「Call OB 未进入项目」前提下的 0/0，**绝不包装成完整包编译通过**（证据文件 `joint_compile_honest_note` 已如实记录）。 |

K 的 `08-k1-probe-fix.md` §4.4 caseB 导入成功但编译 `errorCount=2`，原因是占位实例 DB
`K1_CallUnit_DB` / FB `K1_CallUnit` 在空项目中不存在——与上述根因②/①同源，
**非 namespace 缺陷，不掩盖**。

---

## 2. 本轮根因（已勘查确认，不重新推导）

1. **包不自洽**：批次 3 的完整 AF 包 `ob_files` 只含 5 个 OB，缺少被引用的
   **FB 块**与**全局实例 DB 块**。真实先例 `OB1Main.xml` 的 Call 网络引用
   `FB1000_StdSignal` / `DB1000_StdSignal`，同目录确有配套的
   `001_KL_Standard_FB_FB1000_StdSignal.xml` 与
   `001_KL_Standard_FB_DB1000_StdSignal.xml`。空项目里引用不存在的块 → 导入失败
   或编译 `errorCount=2`（K caseB 同源）。
2. **模板假设错误**：旧 `_render_call_network(call_db)` 用
   `call_fb = re.sub(r"_DB$", "", call_db)` 从实例 DB 名反推 FB 名。真实先例是
   **FB / DB 独立命名**（`FB1000_…` / `DB1000_…`），并非 `xxx_DB` → `xxx`。
   批次 3 传 `GF_U1EM1_InstDB`（不以 `_DB` 结尾），`call_fb` 退化为整个字符串，
   V19 在**导入阶段**即拒绝。
3. **`SW.PlcBlockGroup XML` 确证不可导入**——这是边界事实，不是要修的模板缺陷，
   本轮**不试图**让它可导入（见 §6）。

---

## 3. 逐字段对照表（自产旧模板 / 真实 V19 先例 / 修复后）

> 真实先例均为只读参考：`PLC_Openness_data/hr001/export/plc/CPU_1200/blocks/` 下
> `OB1Main.xml`、`001_KL_Standard_FB_FB1000_StdSignal.xml`、
> `001_KL_Standard_FB_DB1000_StdSignal.xml`。**未打开/修改任何 `.ap19/.zap19`。**

### 3.1 Call 网络（`OB1Main.xml:83-99`）

| 字段 | 自产旧模板（批次 3） | 真实 V19 先例 | 修复后 |
|---|---|---|---|
| `CallInfo.Name` 来源 | `re.sub(r"_DB$", "", call_db)`（从 DB 名反推） | `FB1000_StdSignal`（**独立命名**） | 新增 `call_fb` 显式指定；旧调用回退既有推导（向后兼容） |
| `CallInfo.Name` 批次 3 取值 | `GF_U1EM1_InstDB`（退化成整个 DB 名，V19 拒绝） | `FB1000_StdSignal` | `FB1000_StdSignal` |
| `Instance Scope` / `UId` | `GlobalVariable` / `22` | `GlobalVariable` / `22` | 不变 |
| `Component Name` | `call_db` | `DB1000_StdSignal` | `call_db`（独立命名，可不以 `_DB` 结尾） |
| `NetworkSource` namespace | `FlgNet/v5` | `FlgNet/v5` | 不变 |
| `Wire`：Powerrail + `NameCon en` | 有 | 有 | 不变 |
| `Call UId` / `Wire UId` | `21` / `23` | `21` / `23` | 不变 |

### 3.2 FB 块（`001_KL_Standard_FB_FB1000_StdSignal.xml`）

| 字段 | 自产旧模板（批次 3） | 真实 V19 先例 | 修复后 `render_fb_xml` |
|---|---|---|---|
| 根元素 | **不存在**（旧包无 FB 块） | `<SW.Blocks.FB ID="0">` | `<SW.Blocks.FB ID="0">` |
| `ProgrammingLanguage` | — | `LAD` | `LAD`（按先例） |
| `Interface` namespace | — | `.../SW/Interface/v5` | 同（K 已修复并真机确证的 namespace） |
| `Interface` Section | — | `Input` / `Output` / `InOut` / `Static`（含大量 `Member`） | 同四个 Section 名，但**全空**、不含任何 `Member` → 不虚构变量 / 地址 / Datatype |
| `<Name>` | — | `FB1000_StdSignal` | 参数 `fb_name`（默认 `FB1000_StdSignal`） |
| `<Number>` | — | `1000` | 参数 `fb_number`，原生指定 |
| `CompileUnit` / 网络 | — | 先例 FB **无** CompileUnit（ObjectList 仅 Title） | **无** CompileUnit / 无网络（最小，不虚构 rung） |
| `MultilingualText` culture | — | `zh-CN` / `en-US` / `de-DE`（项目自身 3 语言） | **仅 `zh-CN`**（K 修复口径，复用 `_render_multilingual`） |
| `HeaderVersion` / `IsIECCheckEnabled` / `SetENOAutomatically` | — | 有 | 保留 |
| `UDABlockProperties` / `UDAEnableTagReadback` | — | 有 | **省略**（最小可导入，差异留痕） |
| `AutoNumber` / `MemoryLayout` | — | 先例 FB 无 | 不新增（保持 FB 形态） |

### 3.3 全局实例 DB 块（`001_KL_Standard_FB_DB1000_StdSignal.xml`）

| 字段 | 自产旧模板（批次 3） | 真实 V19 先例 | 修复后 `render_instance_db_xml` |
|---|---|---|---|
| 根元素 | **不存在**（旧包无 DB 块；易被误猜为 `SW.Blocks.GlobalDB`） | **`<SW.Blocks.InstanceDB ID="0">`** | `<SW.Blocks.InstanceDB ID="0">`（**以先例为准，不猜**） |
| 关联 FB | — | `<InstanceOfName>FB1000_StdSignal</InstanceOfName>` / `<InstanceOfType>FB</InstanceOfType>` | `InstanceOfName` = `instance_of_fb`（= `call_fb` = 包内 FB `<Name>`）/ `InstanceOfType=FB` |
| `ProgrammingLanguage` | — | `DB` | `DB` |
| `Interface` | — | `.../SW/Interface/v5`，四 Section（含 `Member`，`Remanence=Retain`） | 同四个**空** Section（无 `Member`） |
| `<Name>` | — | `DB1000_StdSignal` | 参数 `db_name`（默认 `DB1000_StdSignal`） |
| `<Number>` | — | `1000` | 参数 `db_number`，原生指定 |
| `AutoNumber` / `DBAccessibleFromOPCUA` | — | `false` / `true` | 保留 |
| `MultilingualText` culture | — | 三语言 | **仅 `zh-CN`** |

> **与任务文字的差异说明**：任务描述提到「Interface 最小 Temp/Constant」——那是
> **K 修复后自产 OB 模板**的空 Interface 形态（OB 用 `Temp` / `Constant` Section）。
> 真实 FB / InstanceDB 先例的 Interface 是 `Input` / `Output` / `InOut` / `Static`。
> 本轮**以先例为准**用四个空 Section；「空 Section / 不虚构 Member」的最小化语义
> 与 OB 一致。此差异如实留痕，未猜、未混用。

### 3.4 OB 块（沿用 K 修复后模板，本轮仅新增可选参数）

| 字段 | 自产旧模板（K 修复后） | 真实 V19 先例 | 修复后 |
|---|---|---|---|
| culture | 仅 `zh-CN` | 三语言（项目自身配置） | 仅 `zh-CN`（**不变**） |
| 空网络 | `<NetworkSource />` | `<NetworkSource />`（`:1140`） | 不变 |
| Call 网络 | `FlgNet/v5` + `CallInfo`/`Instance`/`Wire` | 同（`:83-99`） | 不变，仅透传 `call_fb` |
| `Interface` | `Temp` / `Constant` 空 Section | `Temp` / `Constant` 空 Section | 不变 |
| `<Number>` | 参数化、原生指定 | `1` | 不变 |
| `<Created>` | `time.gmtime()` 当前时间 | 导出时间 | 新增可选 `created`：默认仍当前时间（旧行为不变）；完整包传固定值以保证字节级幂等 |
| `<SecondaryType>` / `LAD` / `AutoNumber=false` | 参数化 / 固定 | 同 | 不变 |

---

## 4. 新签名与向后兼容策略

```python
_render_call_network(call_db: str, call_fb: str = "") -> str
_render_ob_xml(
    *, ob_name, ob_number, secondary_type, call_db, title, tia_version,
    call_fb: str = "",          # U1 新增：FB 名（FB/DB 独立命名）
    created: str = "",          # U3 新增：固定 <Created>，用于幂等可复现
) -> str
render_fb_xml(*, fb_name, fb_number, programming_language="LAD",
              title="", tia_version="V19", created="") -> str          # U2 新增
render_instance_db_xml(*, db_name, db_number, instance_of_fb,
                       programming_language="DB", title="",
                       tia_version="V19", created="") -> str            # U2 新增
```

**向后兼容**：`call_fb` / `created` 均为带默认值的可选参数。
旧调用只传 `call_db` 时，`_render_call_network` 保守回退到既有
`re.sub(r"_DB$", "", call_db)` 推导 → `build_xml_supplement`（`tia_delivery.py:572`，
不传 `call_fb`）、K1 探针复现命令、`tools/run_batch3_real_machine.py` 的调用
**全部原样可跑、输出不变**；`test_greenfield_tia_delivery.py` /
`test_greenfield_k1_probe.py` 的旧断言（`call_db="…_CallUnit_DB"` →
`CallInfo.Name="…_CallUnit"`）继续通过。
**旧路径局限**：无法表达 FB / DB 独立命名，仅适用于 `xxx_DB` → `xxx` 命名的旧样本；
完整包必须走新路径 `call_fb`。

**原样保留（一行未动）**：G 的会话模式（`SessionModeTiaPort` /
`session_mode_enabled` / `run_incremental_writebacks`）、K 的 XML 修复
（culture 收敛 `zh-CN`、空网络 `<NetworkSource />`、`FlgNet/v5`、`<Number>` 原生指定）、
批次 3 的 `compile_feedback_heal()`（`tia_delivery.py:1906`）、`_render_multilingual`、
`_render_empty_network`、`build_xml_supplement`。
**未新增任何 import**（白名单 `test_sanctioned_phase2_module_whitelist` 不受影响）。

---

## 5. 完整包组成、引用关系、导入顺序、manifest 可复现结果

### 5.1 组成（`tools/build_full_af_package.py --out <dir>`）

| 文件 | 类型 | 说明 |
|---|---|---|
| `folders.json` | 文档化清单 | 供 `create-block-group` Openness API 消费；**非** SimaticML 对象 |
| `blocks/FB1000_StdSignal.xml` | `SW.Blocks.FB` | 被 Call 引用的 FB 块，`<Name>=FB1000_StdSignal`、`<Number>=1000` |
| `blocks/DB1000_StdSignal.xml` | `SW.Blocks.InstanceDB` | 全局实例 DB，`<Name>=DB1000_StdSignal`、`<InstanceOfName>=FB1000_StdSignal` |
| `ob/GF_U1_Startup.xml` | `SW.Blocks.OB` | 空网络 `<NetworkSource />`，`Number=1000` |
| `ob/GF_U1_Main.xml` | `SW.Blocks.OB` | 空网络 `<NetworkSource />`，`Number=1001` |
| `ob/GF_U1EM1_CallOB.xml` | `SW.Blocks.OB` | **Call 网络**，`Number=1012`，引用包内 FB/DB |
| `manifest.json` | 清单 | 逐文件 sha256 + `references` + `import_order` + 诚实标注 |

### 5.2 引用关系（逐字自洽，`references_self_consistent=true`）

```
GF_U1EM1_CallOB  --CallInfo.Name-->  FB1000_StdSignal  == blocks/FB1000_StdSignal.xml 的 <Name>
GF_U1EM1_CallOB  --Component.Name->  DB1000_StdSignal  == blocks/DB1000_StdSignal.xml 的 <Name>
DB1000_StdSignal --InstanceOfName->  FB1000_StdSignal  == blocks/FB1000_StdSignal.xml 的 <Name>
```

- FB / DB 独立命名（`FB1000_…` / `DB1000_…`），`DB1000_StdSignal` 刻意**不以 `_DB`
  结尾**，正是批次 3 失败输入形态；新路径用显式 `call_fb` 修好。
- `render_package()` **fail-closed**：任何 Call OB 的 `call_fb` / `call_db` 与包内
  FB / DB 名不一致即抛 `ValueError`，拒绝产出不自洽的包。
- `ob_entries=[]` 时**不虚构任何 OB**（无 `ob/` 文件、`generated_ob_count=0`、
  `references=[]`）；OB 号沿用批次 3 取值，不虚构地址。

### 5.3 导入顺序（`import_order`，供 W 按序导入）

```
1. blocks/FB1000_StdSignal.xml      (FB)
2. blocks/DB1000_StdSignal.xml      (DB / 实例 DB)
3. ob/GF_U1_Startup.xml             (OB，空网络)
4. ob/GF_U1_Main.xml                (OB，空网络)
5. ob/GF_U1EM1_CallOB.xml           (OB，Call 网络)
```

严格 **FB → DB → OB**：先建被调用块，再建引用它们的 Call OB。
`folders.json` 的分组经 `create-block-group` API 建立（**不在** import 序列里，
见 §6）。

### 5.4 manifest 可复现结果

- 固定 `<Created>=2000-01-01T00:00:00Z` + `json.dumps(..., sort_keys=True, indent=2)`，
  **不含真实时间戳**。
- 同样参数两次 `render_package()`：全部文件字节相同，`manifest.json` 内容 sha256
  一致（实测 `827cdac0041c4ea4…`）。
- `files` 逐条 `sha256` / `bytes` 可复算；`manifest.json` 自身不入清单（无自指）。
- 所有 XML culture 仅 `zh-CN`、`Interface/v5` + `FlgNet/v5`、`<Number>` 存在，
  离线 `xml.etree.ElementTree` 全部可解析。

---

## 6. `SW.PlcBlockGroup` 走 API 而非 XML 的边界

- 真机确证（`evidence/uc04_package_probe.json#probe_a`）：`SW.PlcBlockGroup XML`
  经 `import-xml --kind auto` / `--kind block` 均 `exit=4 / openness_error`
  （`… type … is not supported`），**不是可导入的 SimaticML 块对象**。
- 产品链走 `create-block-group` Openness API 建立文件夹（F 真机验证两次
  `ok=true / saved=true`）；`folders.json` 是**文档化清单**、供该 API 消费，
  `mechanism` 字段显式写明 `create-block-group Openness API (NOT … import-xml)`。
- **本轮不试图让 BlockGroup XML 可导入**，也不把它列入 `import_order`；这是
  边界厘清，不是模板缺陷修复。

---

## 7. 复现命令与单测结果

```bash
R="c:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"; cd "$R"

# 1) 构造完整包（--out 必填，默认不写产品目录）
./.venv/Scripts/python.exe tools/build_full_af_package.py \
  --out C:/Users/vboxuser/AppData/Local/Temp/gf_real_u_20261107/package

# 2) 离线单测（任务指定的 4 个文件）
./.venv/Scripts/python.exe -m pytest \
  tests/unit/test_greenfield_full_af_package.py \
  tests/unit/test_greenfield_tia_delivery.py \
  tests/unit/test_greenfield_k1_probe.py \
  tests/unit/test_greenfield_legacy_guard.py -q
```

`test_greenfield_full_af_package.py` 14 例（纯离线）：

| 用例组 | 覆盖点 |
|---|---|
| 引用自洽 | `CallInfo.Name` / `Component.Name` 与 FB/DB `<Name>` 逐字一致；`InstanceOfName` 回链 FB；DB 根为 `InstanceDB` 非 `GlobalDB` |
| XML 结构 | FB/DB/OB culture 仅 `zh-CN`、`Interface/v5` / `FlgNet/v5`、`<Number>` 存在、无 `StructuredText/v4`；FB 根 / LAD、DB / DB |
| 包与 manifest | `import_order` 完整且 FB→DB→OB；逐文件 sha256 可复算；两次渲染字节可复现；`build_package` 落盘一致；CLI `--out` |
| 向后兼容 / 不虚构 | 旧调用只传 `call_db` 合法且保留 `_DB` 推导；`ob_entries=[]` 不虚构 OB；不自洽引用 fail-closed |
| 诚实标注 | `xml_package_unverified` / `pending_real_machine` 保持 True、notes 明确 Agent W / 不宣称通过 |

> 本文件为**离线单测**，不构成 L2/L4 证据、不宣称真机导入成功或「编译零错误」。
> 真机数字只来自真实 CLI/HTTP 原始返回，本轮**未产生任何真机数字**。

---

## 8. 诚实边界与已知遗留

1. **真机未验证**：本轮纯离线构造 + 离线单测；未连真机、未启动 SessionServer、
   未跑 TIA CLI、未占用 8791/8000。FB / 实例 DB 块的「最小可导入」仅保证
   **与真实 V19 先例结构同构 + 离线 XML 合法**，其真实 `import-xml` /
   `compile-plc` 结果由**阶段 B 的 Agent W** 在 `Temp/gf_real_*` 临时副本上
   按 §5.3 `import_order` 验证。
2. **不宣称 UC-04 通过**：完整包联合导入编译 `errorCount=0 / warningCount=0 /
   state=Success` 尚未取得；不宣称「完整包编译零错误」、不宣称 L2 通过。
3. **`xml_package_unverified` 仍为 `True`**：本 Agent 未改任何产品代码标志位赋值，
   是否消除由主 agent 在 W 真实结果出来后按证据决定。
4. **K caseB `errorCount=2`** 是占位实例 DB / FB 不存在的同一根因，非 namespace
   缺陷，未掩盖。
5. **`SW.PlcBlockGroup XML` 不可导入**是确证边界事实，本轮未试图修复、未列入
   包导入序列；`folders.json` 走 `create-block-group` API。
6. **FB/DB 与先例的精简差异**（§3.2 / §3.3）：空 Section 无 `Member`、省略 UDA
   字段、省略实例数据的 `Remanence=Retain` 成员、culture 收敛 `zh-CN`——均为
   「最小可导入 / 不虚构」取舍，真机可用性由 W 验证。
7. **旧路径局限**：`call_fb` 未传时仍用 `_DB` 后缀推导，无法表达独立命名；
   保留仅为向后兼容。
8. **文件所有权**：未改 `evidence/rtm.json`、`pending_real_machine.json`、
   `uc15_evidence_bundle.json`、批次 2/3 既有真机证据、`legacy_baseline.json`、
   `test_greenfield_legacy_guard.py`、sha256 冻结清单 41 个文件、C# 源码、
   `greenfield_service.py` / 路由 / 前端 / `plc_engine/af/`；未执行任何 git 操作。
9. **全量 pytest 未跑**（由主 agent 收口统一跑）；本轮仅跑任务指定的 4 个单测文件。

---

## 9. 合规与诚实口径声明

- 真机相关操作：**本轮为零**（阶段 A 离线）。`PLC_Openness_data/` 下 3 个 XML
  仅作**只读模板参考**，未打开 / 修改任何原始 `.ap19` / `.zap19`。
- 所有离线断言覆盖的是**包内自洽性 / XML 结构 / 可复现性**，不替代真机导入编译。
- 未以 mock / 离线单测宣称 L2/L4 通过、未把 `pending_real_machine` 说成成功、
  未编造任何真机数字、未把 `xml_package_unverified` 改 False、未代签 M4。
