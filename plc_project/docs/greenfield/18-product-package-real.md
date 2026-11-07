# 正式产品通道 XML 补充包 V19 真机验证报告 · 批次 4 · Agent Y

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 4 收口阶段 · **Agent Y · 正式产品通道 `deliver_tia(mode="package")` 产出的 `xml_supplement/` 的 V19 真机验证**（决定 `xml_package_unverified` 能否消除、UC-04 是否完全闭环） |
| 分支 / 基线 | `dev/greenfield-wp` / `3596fb9`（**未执行任何 git 操作**） |
| 日期 | 2026-11-07 |
| 契约 | `14-batch4-contract.md` §1 全局规则（真机安全 / TIA 独占 / 诚实口径 / M4 不代签 / `xml_package_unverified` 不擅自改）；本阶段为唯一连真机 / TIA / SessionServer 的 agent，W、X 均已结束且不占资源 |
| 前序依据 | W：`evidence/uc04_full_package_real.json`（U 独立包 5/5 导入 + 编译 0/0，方法学复用）、`tools/run_batch4_real_machine.py`；X：`17-product-channel-wiring.md`、`tests/unit/test_greenfield_supplement_self_consistent.py`；U：`14-uc04-package-fix.md`；K：`08-k1-probe-fix.md` |
| 阶段 | **真机（V19，临时副本）**；纯 `--cli` 一次性调用，未启动 `serve` 常驻进程，8791 从未监听 |
| 独占可写（全部新增，未改任何既有文件） | `evidence/uc04_product_package_real.json`、`docs/greenfield/18-product-package-real.md`（本报告）、`tools/run_product_package_real.py`；过程真相源 `Temp/gf_real_y4_20261107/raw_all.json` |
| 真机副本 | `C:/Users/vboxuser/AppData/Local/Temp/gf_real_y4_20261107/case_Y-1/proj/CanvasE2E.ap19`（首轮）、`.../case_Y-2/proj/CanvasE2E.ap19`（独立干净副本复测） |

---

## 0. 判定摘要（诚实口径）

> **本轮完成「正式产品通道产出的 `xml_supplement/` 在 V19 临时副本上按 `import_order` 逐项真机导入 + 编译」的独立验证，两轮全部成功。**
> 两轮各 **10/10 块导入 `ok=true / exit_code=0`**、`create-block-group` **3/3**、`list-blocks` 入项目、
> `compile-plc` 真实 **`state=Success / errorCount=0 / warningCount=0 / exit_code=0`**。
>
> **但不宣称 L2 / L4 通过、不宣称「Greenfield 全链编译零错误」、不宣称 UC-04 已由本 Agent 完全闭环、不宣称 M4 可签署。**
> `xml_package_unverified` / `pending_real_machine` 在代码与 manifest 中仍为 `True`，本 Agent **未改任何标志位赋值**；
> 是否消除由主 agent 收口按证据决定（§4）。N9：`fidelity_ok` ≠ `compile_ok`；warning 单列不并入成功。
> 所有真机数字均来自真实 `TiaOpenness.Server.exe --cli` 原始 JSON，附复现命令与副本路径于 `evidence/uc04_product_package_real.json`。

**与 W 的关键区别（本任务核心）**：W 验证的是 U 的 `tools/build_full_af_package.py` **独立构造包**
（`FB1000_StdSignal` / `DB1000_StdSignal`、3 个 OB、固定编号 1000/1001/1012、不过门禁）；
本轮验证的是**正式产品通道**交付 ZIP 内的 `xml_supplement/`
（2 FB + 2 实例 DB + 6 OB，命名 `U1_KukaVisionStation_CallUnit` / `…_CallUnit_DB` 等，编号取自真实
`blocks_manifest`）。**命名 / 编号 / 路径 / 门禁 / 块数全不同，W 结论不可直接套用**，已由本 Agent 逐项独立真机验证（§3）。

---

## 1. Y1 · 正式包产出与结构核对

### 1.1 生成方式与产物

用 `<R>/.venv/Scripts/python.exe`，复用 `tests/unit/test_greenfield_tia_delivery.py::_frozen_session`
构造真实冻结会话（`load_reference_fixture → revalidate → engineering_summary → confirm_and_freeze`），
调 `tia_delivery.deliver_tia(session, mode="package")`，把返回的 `zip_bytes` 写到
`Temp/gf_real_y4_20261107/product_package.zip` 并解压 `xml_supplement/`（**未修改 ZIP 内任何内容**）。
`PLC_WORK_DIR` 指向 `Temp/.../work`，staged 包 / PCEC 账本全部落在临时目录，不写产品目录。

- 交付 ZIP：`76756`（Y-1）/ `76759`（Y-2）字节；`zip_sha256` 两轮不同（见 §1.2 注）。
- `xml_supplement/` 共 **14 个成员**：`blocks/*.xml` 4、`ob/*.xml` 6、`folders.json`、`README.md`、`manifest.json`（另 3 个目录项）。
- `manifest.json` 与解压后磁盘字节一致；`result` 回执（另一条交付路径）的 `generated_blocks` / `skipped_blocks` /
  `import_order` / `references_self_consistent` 与 `manifest.json` 逐字段相等。

### 1.2 `manifest.json` 真实值（原样记录）

| 字段 | 真实值 |
|---|---|
| `xml_package_unverified` | **`true`** |
| `pending_real_machine` | **`true`** |
| `references_self_consistent` | **`true`** |
| `generated_blocks` | **4 项**（2 `FB` + 2 `InstanceDB`） |
| `skipped_blocks` | **`[]`** |
| `import_order` | **10 项，严格 2 FB → 2 实例 DB → 6 OB** |
| `ob_count` | `6` |
| `skipped_obs` | 3 个 ProDiag（`U1Em0_General_ProDiag` 1007 / `U1Em1_Station1_ProDiag` 1012 / `U1_KukaVisionStation_ProDiag` 1002），按 K1 存量口径跳过 |

`generated_blocks`（编号取自真实 `blocks_manifest`，未虚构）：

| name | type | number | instance_of_fb | referenced_by_obs |
|---|---|---|---|---|
| `U1Em1_Station1_CallEquipment` | FB | 1010 | — | `U1Em1_Station1_Main` / `_Startup` |
| `U1Em1_Station1_CallEquipment_DB` | InstanceDB | 1015 | `U1Em1_Station1_CallEquipment` | 同上 |
| `U1_KukaVisionStation_CallUnit` | FB | 1001 | — | `U1_KukaVisionStation_Main` / `_Startup` |
| `U1_KukaVisionStation_CallUnit_DB` | InstanceDB | 1011 | `U1_KukaVisionStation_CallUnit` | 同上 |

`import_order`（10 项）：

```
1  xml_supplement/blocks/U1Em1_Station1_CallEquipment.xml          (FB)
2  xml_supplement/blocks/U1_KukaVisionStation_CallUnit.xml         (FB)
3  xml_supplement/blocks/U1Em1_Station1_CallEquipment_DB.xml       (实例 DB)
4  xml_supplement/blocks/U1_KukaVisionStation_CallUnit_DB.xml      (实例 DB)
5  xml_supplement/ob/U1Em0_General_Main.xml                       (OB, 空网络)
6  xml_supplement/ob/U1Em0_General_Startup.xml                    (OB, 空网络)
7  xml_supplement/ob/U1Em1_Station1_Main.xml                      (OB, Call)
8  xml_supplement/ob/U1Em1_Station1_Startup.xml                   (OB, Call)
9  xml_supplement/ob/U1_KukaVisionStation_Main.xml                 (OB, Call)
10 xml_supplement/ob/U1_KukaVisionStation_Startup.xml              (OB, Call)
```

> 与 X 离线自检一致（`import_order` 10 项、`references_self_consistent=True`、`skipped_blocks=[]`），本轮为**真机实测**。
> **注**：正式包 XML 的 `<Created>` 用 `time.gmtime()` 当前时间（X 报告 §1），**非字节级可复现**：
> 两轮 `zip_sha256` / `manifest_sha256` 不同（Y-1 `631c72d1…` / `51939a8d…`，Y-2 `5d11adee…` / `005ce2db…`）。
> 逐文件 sha256 核对针对各自同一份包；两轮不同生成实例均通过，反证结论不依赖某一次时间戳。

### 1.3 逐文件 sha256 核对（与 `generated_blocks` / `generated_obs` 记录）

对 `manifest.json` 中 4 个 `generated_blocks` + 6 个 `generated_obs` 共 **10 个 XML** 逐文件复算
`hashlib.sha256(原始字节)`，与清单 `sha256`（格式 `sha256:`+hex）比对：**10/10 `match=true`**，
`per_file_sha256_all_match=true`；`all_members_sha256` 另列 `xml_supplement/` 全部 14 个成员的 sha256。
sha256 明细见 `evidence/uc04_product_package_real.json#y1_structure.per_file_sha256_recompute`。

### 1.4 Python XML 解析逐字一致核对

用 `xml.etree.ElementTree` 解析（按 localname 去 namespace：`CallInfo` / `Component` 在 `FlgNet/v5`，
块 `<Name>` / `<InstanceOfName>` 为无 namespace 元素），逐 OB 核对：

| OB | `CallInfo.Name` | `Component.Name` | 包内 FB `<Name>` | 包内 DB `<Name>` | DB `InstanceOfName` | 判定 |
|---|---|---|---|---|---|---|
| `U1Em0_General_Main` | — | — | — | — | — | 空网络 OB，无 Call 引用 |
| `U1Em0_General_Startup` | — | — | — | — | — | 空网络 OB，无 Call 引用 |
| `U1Em1_Station1_Main` | `U1Em1_Station1_CallEquipment` | `U1Em1_Station1_CallEquipment_DB` | 逐字一致 | 逐字一致 | `U1Em1_Station1_CallEquipment` | `all_consistent` |
| `U1Em1_Station1_Startup` | 同上 | 同上 | 逐字一致 | 逐字一致 | 同上 | `all_consistent` |
| `U1_KukaVisionStation_Main` | `U1_KukaVisionStation_CallUnit` | `U1_KukaVisionStation_CallUnit_DB` | 逐字一致 | 逐字一致 | `U1_KukaVisionStation_CallUnit` | `all_consistent` |
| `U1_KukaVisionStation_Startup` | 同上 | 同上 | 逐字一致 | 逐字一致 | 同上 | `all_consistent` |

4 个 Call OB 均满足：`CallInfo.Name == 包内 FB <Name>`、`Component.Name == 包内 DB <Name>`、
`DB InstanceOfName == FB <Name>`，且产品通道约定 `call_fb == re.sub(r"_DB$", "", call_db)` 成立。
`xml_references_all_consistent=true`（6/6，其中 2 个空网络 OB 记为无 Call 引用）。
**未发现不一致**；未修改 ZIP 内容。

---

## 2. Y2 · V19 真机按序导入 + 编译

### 2.1 安全与环境

- `--cli status` 真实返回：`tiaVersion=V19`、`tiaRunning=false`、`processCount=0`、
  `opennessAvailable=true`、`opennessGroupInToken=true`、`engineeringDll` 含 `Portal V19`。
- 只读源 `PLC_Openness_data/openness_e2e/CanvasE2E` 仅 `shutil.copytree` 复制到
  `Temp/gf_real_y4_20261107/case_Y-*/proj/`，**从不打开/写回原始 `.ap19`/`.zap19`**、不删除原始文件。
- 所有真机子进程 `subprocess.run(timeout=180)`，复现命令附 `timeout -k 5 180`；
  全程 `--cli` 一次性调用，**未启动 `serve` 常驻进程**，8791 从未监听。
- D12 hard refuse：不做在线下载 / online / run-stop / compare-to-PLC、不碰 F-block/Safety、不做 UI 自动化。

### 2.2 两轮设置与导入前基线（编号冲突核查）

| 轮次 | 副本 `.ap19` | 包 `zip_sha256` | 导入前基线块数 | 基线块 |
|---|---|---|---|---|
| Y-1 首轮 | `case_Y-1/proj/CanvasE2E.ap19` | `sha256:631c72d1…` | **2** | `Main`(OB 1)、`PumpCtrl`(FB 1) |
| Y-2 独立复测 | `case_Y-2/proj/CanvasE2E.ap19` | `sha256:5d11adee…` | **2** | 同上 |

- 两轮均为**从只读源全新复制的干净副本**，导入前基线各仅 2 块，**不含 W 独立包**
  （`FB1000_StdSignal` / `DB1000_StdSignal` / `OB1000` 等）遗留的任何同号块；本目录与 W 的
  `gf_real_w4_20261107/` 完全隔离。故**未发生「同号块导致导入失败」**，无需因冲突重测。
- 正式包内部存在**跨类型同号**（如 `OB1001` 与 `FB1001`、`OB1010` 与 `FB1010`、
  `OB1011` 与 `DB1011`；`OB1000` 与 W 独立包 `OB1000` 同号）。TIA 不同类型编号空间独立，
  真机全部共存、导入成功、编译 0/0（与 W 副本 `Main`=OB1 / `PumpCtrl`=FB1 同号共存同理）。
- 除首轮外，另做 **Y-2 一轮全新独立干净副本 + 新生成包复测**（两轮 zip sha256 不同），
  同样 10/10 导入 + 编译 0/0，排除时间戳偶然性与 W 遗留块影响。

### 2.3 逐项 `import-xml --kind auto` 真实返回（按 `import_order`，Y-1 轮；Y-2 同）

| # | path | `ok` | `exit_code` | `importedNames` | `kind_resolved` | error |
|---|---|---|---|---|---|---|
| 1 | `blocks/U1Em1_Station1_CallEquipment.xml` | true | 0 | `U1Em1_Station1_CallEquipment` | block | — |
| 2 | `blocks/U1_KukaVisionStation_CallUnit.xml` | true | 0 | `U1_KukaVisionStation_CallUnit` | block | — |
| 3 | `blocks/U1Em1_Station1_CallEquipment_DB.xml` | true | 0 | `U1Em1_Station1_CallEquipment_DB` | block | — |
| 4 | `blocks/U1_KukaVisionStation_CallUnit_DB.xml` | true | 0 | `U1_KukaVisionStation_CallUnit_DB` | block | — |
| 5 | `ob/U1Em0_General_Main.xml` | true | 0 | `U1Em0_General_Main` | block | — |
| 6 | `ob/U1Em0_General_Startup.xml` | true | 0 | `U1Em0_General_Startup` | block | — |
| 7 | `ob/U1Em1_Station1_Main.xml` | true | 0 | `U1Em1_Station1_Main` | block | — |
| 8 | `ob/U1Em1_Station1_Startup.xml` | true | 0 | `U1Em1_Station1_Startup` | block | — |
| 9 | `ob/U1_KukaVisionStation_Main.xml` | true | 0 | `U1_KukaVisionStation_Main` | block | — |
| 10 | `ob/U1_KukaVisionStation_Startup.xml` | true | 0 | `U1_KukaVisionStation_Startup` | block | — |

`imports_all_ok=true`（两轮各 10/10）。`SW.PlcBlockGroup XML` 仍**不可** `import-xml`（批次 3 已确证
`exit=4/openness_error`），本轮**未试图**导入它；文件夹改走 API（§2.4）。
每项完整 CLI 原始返回（`command` / `args` / `_exit_code` / `_stdout` / `_stderr` / `json`）见
`evidence/uc04_product_package_real.json#y2_real_machine.runs[*].imports_itemized[*].raw_original`。

### 2.4 `create-block-group`（按 `folders.json`，两轮各 3/3）

| group | `ok` | `saved` | `exit_code` |
|---|---|---|---|
| `00_Types_UDT` | true | true | 0 |
| `30_Equipment_Modules` | true | true | 0 |
| `90_Compat_Frozen_Boundary` | true | true | 0 |

`create_block_groups_all_ok=true`。`folders.json` 是**文档化清单**（非 SimaticML 对象）；
`create-block-group` 仅**建立分组**，未把块逐一移入分组（该归属关系本轮未验证，列入遗留）。

### 2.5 `list-blocks` 核对（Y-1 轮；Y-2 同）

导入后 `count=12`、`byType={OB:7, FB:3, DB:2}`（基线 2 + 新增 10）：

```
OB 1 Main | OB 1006 U1Em0_General_Main | OB 1005 U1Em0_General_Startup
OB 1011 U1Em1_Station1_Main | OB 1010 U1Em1_Station1_Startup
OB 1001 U1_KukaVisionStation_Main | OB 1000 U1_KukaVisionStation_Startup
FB 1 PumpCtrl | FB 1010 U1Em1_Station1_CallEquipment | FB 1001 U1_KukaVisionStation_CallUnit
DB 1015 U1Em1_Station1_CallEquipment_DB | DB 1011 U1_KukaVisionStation_CallUnit_DB
```

10 个新增块的**名称与编号与 `generated_blocks` / `generated_obs` 逐项吻合**。

### 2.6 `compile-plc` 原始返回（两轮一致）

```json
{"ok":true,
 "project":{"ok":true,"projectPath":"...\\case_Y-1\\proj\\CanvasE2E.ap19","projectName":"CanvasE2E",
            "plcName":"PLC_1","deviceName":"PLC_1","message":"Project opened via TIA Openness."},
 "compile":{"ok":true,"apiAvailable":true,"state":"Success","errorCount":0,"warningCount":0,
            "inconsistentBlocks":["Compiling finished (errors: 0; warnings: 0)"],
            "message":"Compile State=Success errors=0 warnings=0"}}
```

| 轮 | `errorCount` | `warningCount` | `state` | `inconsistentBlocks` | `exit_code` |
|---|---|---|---|---|---|
| Y-1 | **0** | **0**（单列，不并入成功） | **Success** | `Compiling finished (errors: 0; warnings: 0)` | **0** |
| Y-2 | **0** | **0** | **Success** | 同上 | **0** |

> 以上 0/0 是**本次「正式包 10 块按序导入到干净副本后」这一次真机编译**的真实返回，
> **不是** Greenfield 端到端全链（UC-15 / M4）的编译结论，不宣称「编译零错误」泛指全链。

### 2.7 两轮对比与中间失败

| 项 | Y-1 | Y-2 |
|---|---|---|
| 生成包 `zip_sha256` | `631c72d1…` | `5d11adee…`（不同，时间戳不同） |
| 副本 | `case_Y-1` | `case_Y-2`（全新独立） |
| 导入前基线 | 2 块（干净） | 2 块（干净） |
| 逐项导入 | 10/10 `ok` / `exit=0` | 10/10 `ok` / `exit=0` |
| 文件夹 | 3/3 `ok/saved` | 3/3 `ok/saved` |
| 导入后块 | 12（OB7/FB3/DB2） | 12（OB7/FB3/DB2） |
| 编译 | `Success` 0/0 `exit=0` | `Success` 0/0 `exit=0` |

**两轮均为单轮完成，无失败、无重试、无被掩盖的中间轮次**；全部原始返回完整保留在
`Temp/gf_real_y4_20261107/raw_all.json`（`source_raw_sha256=sha256:0e3146b3…`）。
`intermediate_failures=[]`。

---

## 3. 与 W 独立包验证的差异（结论可否套用）

| 维度 | W 的独立包（U `tools/build_full_af_package.py`） | 正式产品通道（本轮） |
|---|---|---|
| 生成方式 | 离线 CLI 脚本 `--out <dir>` | `deliver_tia(_frozen_session, mode="package")`，经**四层静态门禁 + PCEC** |
| 产物路径 | 输出目录根 `blocks/*.xml` + `ob/*.xml` + `folders.json` + `manifest.json` | 交付 ZIP 内 `xml_supplement/{blocks,ob}/*.xml` + `folders.json` + `README.md` + `manifest.json` + `tia_delivery.json` |
| FB / DB 命名 | `FB1000_StdSignal` / `DB1000_StdSignal`（独立命名，不以 `_DB` 结尾） | `U1_KukaVisionStation_CallUnit` / `…_CallUnit_DB`、`U1Em1_Station1_CallEquipment` / `…_CallEquipment_DB`（`xxx_DB→xxx` 约定） |
| 编号来源 | 脚本常量 `1000/1000`；OB `1000/1001/1012` | 真实 `blocks_manifest`：FB `1001/1010`、DB `1011/1015`、OB `1000/1001/1005/1006/1010/1011` |
| 块数 / `import_order` | **5 项**（1 FB + 1 DB + 3 OB） | **10 项**（2 FB + 2 实例 DB + 6 OB），另 3 ProDiag `skipped_obs` |
| `folders.json` | `AF_Unit_01` / `AF_Unit_01/AF_EM_01` / `root`，含 `mechanism` + `schema` | `00_Types_UDT` / `30_Equipment_Modules` / `90_Compat_Frozen_Boundary` 三组，无 `mechanism/schema` |
| 静态门禁 / PCEC | 不经过 | 经过 |
| `<Created>` / 可复现性 | 固定 `2000-01-01T00:00:00Z`，字节级可复现，manifest sha256 固定 `827cdac…` | `time.gmtime()` 当前时间，非字节级可复现，两轮 sha256 不同 |
| 真机验证状态 | W 已验证 5/5 导入 + 编译 0/0 | 本轮之前 X 仅离线自洽 + 离线单测；**本轮由 Agent Y 两轮独立真机验证** |

**结论可否套用：不可直接套用。** 命名约定、编号来源、产物路径、是否过门禁、块数、时间戳可复现性均不同；
W 的 5/5 + 0/0 只证明「U 独立构造探针包」可导入编译，**不能**据此断言正式产品通道包可导入编译。
本轮已按任务要求由 Agent Y 对正式包**逐项**真机验证（10/10 导入 + 编译 0/0 + 两轮独立复测），
而非复用 W 结论。

---

## 4. `xml_package_unverified` 处置建议（**不代决定、不改标志**）

> **建议：按任务给定判据，主 agent 收口时『可考虑消除 `xml_package_unverified`』，但必须严格限定范围。**
> 本 Agent **未改**产品代码任何标志位赋值；代码与 `manifest.json` 中该标志仍为 `true`。

**判据已满足**：正式包所有 FB/DB/OB 导入成功（两轮各 10/10 `ok=true`）+ 编译 `errorCount=0`
（两轮 `Success` 0/0 `exit=0`）。

**依据（真机）**：
1. `deliver_tia(mode="package")` ZIP 内 `xml_supplement/` 10 项块按 `import_order`（FB→DB→OB）逐项
   `--cli import-xml --kind auto` 真实 `ok=true / exit=0 / importedNames` 逐项核对，两轮各 10/10；
   `skipped_blocks=[]`、`references_self_consistent=true`（Y1 结构核对 + XML 解析逐字一致亦通过）。
2. 两轮独立干净副本 `compile-plc` 真实 `state=Success / errorCount=0 / warningCount=0 / exit=0`；
   `list-blocks` 导入后 12 块，名称编号与 `blocks_manifest` / `generated_blocks` 逐项吻合。
3. `folders.json` 3 组经 `create-block-group` Openness API 建立（3/3 `ok/saved/exit=0`），
   与「文件夹走 API、非 `SW.PlcBlockGroup` XML import」口径一致。
4. 两轮不同生成实例（zip sha256 不同）+ 不同全新干净副本（基线各 2 块）+ 导入前无 W 遗留同号块，
   排除时间戳偶然性与编号冲突，结论可复现。

**必须限定的范围（limits）**：
- `SW.PlcBlockGroup XML` 仍**不可** `import-xml`（批次 3 已确证 `exit=4/openness_error`）；本轮按
  `folders.json` 经 API 建 3 组，**未试图改变该边界**，也**未把块逐一移入分组**（API 仅建组）。
- 本轮是临时副本上的**包级按序导入 + 编译**，**非** `deliver_tia(mode="auto")` 端到端全链
  （自然语言 → 冻结 → 生成 → 导入 → 编译，UC-15 / M4），后者由主 agent 收口。
- FB / 实例 DB 相对真实 V19 先例**有精简**（空 Section 无 Member、省略 UDA、culture 收敛 `zh-CN`，
  U §3.2/§3.3、X §6）；真机证明可导入可编译，**非逐字段等同先例**。
- culture 收敛 `zh-CN` 边界（K §7）：对含 `zh-CN` 的 CanvasE2E 已验证；**纯英文 / 其它语言项目未测**。
- 正式包 `<Created>` 用 `time.gmtime()`，**非字节级可复现**；两轮不同生成实例均通过，但不构成
  「任意时刻产物字节相同」。
- 3 个 ProDiag 类 OB 按 K1 存量口径 `skipped_obs` 跳过、未生成 XML、**未真机验证**。

**诚实边界**：`fidelity_ok ≠ compile_ok`；warning 单列（`warningCount=0`）不并入成功；不宣称 L2 / L4 通过、
不宣称「Greenfield 全链编译零错误」、不宣称 UC-04 已由本 Agent 完全闭环、**不宣称 M4 可签署、不代签 M4**。

---

## 5. 复现命令

```bash
R="C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"; cd "$R"
EXE="$R/industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe"
PY="$R/.venv/Scripts/python.exe"  # 用 <R>/.venv/Scripts/python.exe
AP="C:/Users/vboxuser/AppData/Local/Temp/gf_real_y4_20261107/case_Y-1/proj/CanvasE2E.ap19"

# 1) 生成正式产品包 + Y1 结构核对 + Y2 真机（脚本，含 180s 子进程超时）
"$PY" tools/run_product_package_real.py --case Y-1
#    独立干净副本复测：再跑 --case Y-2（旧轮原始 JSON 保留在 raw_all.json）

# 2) 单项复现（均 timeout -k 5 180）
timeout -k 5 180 "$EXE" --cli status
timeout -k 5 180 "$EXE" --cli list-blocks --project "$AP"                       # 导入前基线（干净副本 2 块）
timeout -k 5 180 "$EXE" --cli import-xml --project "$AP" --xml <TEMP/xml_supplement/按 import_order> --kind auto   # 逐项 FB→DB→OB
timeout -k 5 180 "$EXE" --cli create-block-group --project "$AP" --plc PLC_1 --group 00_Types_UDT
timeout -k 5 180 "$EXE" --cli create-block-group --project "$AP" --plc PLC_1 --group 30_Equipment_Modules
timeout -k 5 180 "$EXE" --cli create-block-group --project "$AP" --plc PLC_1 --group 90_Compat_Frozen_Boundary
timeout -k 5 180 "$EXE" --cli list-blocks --project "$AP" [--type OB|FB|DB]
timeout -k 5 180 "$EXE" --cli compile-plc --project "$AP" --plc PLC_1
```

> 真相源：`Temp/gf_real_y4_20261107/raw_all.json`（两轮全部 CLI 原始返回）；
> 结构化证据：`evidence/uc04_product_package_real.json`（`source_raw_sha256=sha256:0e3146b3…`）。

---

## 6. 验证：单测与进程清理

**单测**（任务指定，未跑全量 pytest）：

```
cd <R> && ./.venv/Scripts/python.exe -m pytest \
  tests/unit/test_greenfield_legacy_guard.py \
  tests/unit/test_greenfield_supplement_self_consistent.py -q
```

- 结果：**`13 passed in 13.40s`**。
- 精确确认两个关键护栏：`-k "frozen_legacy_files_have_zero_diff or sanctioned_phase2_module_whitelist" -v`
  → **`2 passed, 11 deselected`**（`test_frozen_legacy_files_have_zero_diff` PASS、
  `test_sanctioned_phase2_module_whitelist` PASS）。

**进程 / 端口清理确认**（真机操作全部结束后）：

| 检查 | 结果 |
|---|---|
| `TiaOpenness.Server` 进程 | **无**（无真机 CLI / serve 残留） |
| `8791` LISTEN 连接 | **无**（`Get-NetTCPConnection -LocalPort 8791 -State Listen` 为空） |
| `http://127.0.0.1:8791/health` | **不可达**（无法连接到远程服务器） |
| 其它 Siemens 进程 | 5 个 TIA 安装自带常驻服务（Help Viewer / Tracing / Telemetry / TiaAdminNotifier），与本任务启动前一致，非本任务启动或遗留 |

---

## 7. 合规与诚实口径 / 已知遗留

- **只写 3 个产品目录文件**（全部新增）：`evidence/uc04_product_package_real.json`、
  `docs/greenfield/18-product-package-real.md`、`tools/run_product_package_real.py`；
  过程真相源与探查/生成辅助脚本仅在 `Temp/gf_real_y4_20261107/`。
- **未改**任何产品代码（`gateway/` / `plc_engine/` / `agents/` / `frontend/` / `industrial/`）、
  `legacy_baseline.json`、`test_greenfield_legacy_guard.py`、sha256 冻结清单 41 个文件；
  **未改** `evidence/rtm.json` / `pending_real_machine.json` / `acceptance_template.json` /
  `uc15_evidence_bundle.json` / 任何既有证据文件；**未执行任何 git 操作**；**未代签 M4**；
  **未擅自改 `xml_package_unverified`**（仍 `true`）。
- 真机操作只在 `Temp/gf_real_y4_20261107/` 临时副本；原始 `.ap19` 仅 `cp` 读取，从不打开 / 写回 / 删除；
  每个真机子进程设超时；全程 `--cli` 一次性，未启 `serve`；D12 hard refuse 严格遵守。
- 所有真机数字来自真实 CLI 原始 JSON，失败即如实记录（本轮两轮均无失败、无掩盖）；
  未以离线单测 / mock 宣称 L2/L4 通过或「编译零错误」。

**已知遗留（诚实列出）**：
1. `deliver_tia(mode="auto")` 端到端全链（UC-15 / M4）未跑，`xml_package_unverified` 消除、
   `pending_real_machine` 清零、证据台账（`rtm.json` 等）更新均归**主 agent 收口**。
2. `SW.PlcBlockGroup XML` 仍不可 `import-xml`；块与文件夹分组的**归属关系**未通过 API 逐一验证
   （`create-block-group` 仅建组）。
3. FB / 实例 DB 精简差异、culture 收敛 `zh-CN` 的纯英文 / 其它语言项目边界未测；正式包非字节级可复现。
4. 3 个 ProDiag 类 OB 按存量口径 `skipped_obs` 跳过、未生成 XML、未真机验证。
5. 全量 pytest 未跑（按任务要求仅跑指定 2 个单测文件；主 agent 收口统一跑全量）。
6. 与 W 独立包不等价（§3）；本结论**仅针对正式产品通道 `xml_supplement/` 包级真机导入编译**，
   不外推到独立包或端到端全链。
