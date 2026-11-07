# 正式产品通道 `build_xml_supplement` 的 FB/DB 自洽接线 · 批次 4 · Agent X

| 项 | 值 |
|---|---|
| 批次 / 角色 | 批次 4 收口阶段 · **Agent X · 正式产品通道 `build_xml_supplement` 的 FB/DB 自洽接线** |
| 分支 / 基线 | `dev/greenfield-wp` / `3596fb9`（批次 3 收官，未执行任何 git 操作） |
| 日期 | 2026-11-07 |
| 契约 | `14-batch4-contract.md` §1 全局规则（冻结清单零触碰 / 不擅自改 `xml_package_unverified` / 不连真机）、§2 文件所有权；`14-uc04-package-fix.md`（U 的逐字段对照表） |
| 前序依据 | U：`tools/build_full_af_package.py`、`tests/unit/test_greenfield_full_af_package.py`、`14-uc04-package-fix.md`；W：`evidence/uc04_full_package_real.json`（独立包 V19 真机 5/5 导入 + 编译 0/0） |
| 阶段 | **纯离线**：不连真机 / 不启动 SessionServer / 不跑 TIA CLI / 不占用 8791/8000 |
| 独占改动 | `gateway/app/services/plc/tia_delivery.py`（**仅** `build_xml_supplement` + 两处 manifest 组装）；**新增** `tests/unit/test_greenfield_supplement_self_consistent.py`、本报告 |

---

## 0. 判定摘要（诚实口径）

> **本轮只完成「正式产品通道产出的 XML 补充包在包内引用自洽」+ 离线单测。**
> 未连真机、未跑 `import-xml` / `compile-plc`、未启动任何服务。
> **不宣称正式包真机导入通过 / 完整包编译零错误 / UC-04 完全闭环**；
> `xml_package_unverified` / `pending_real_machine` 保持 `True`，由主 agent 收口按证据决定。

- 修复的是**产品通道接线缺口**：U 已修模板并新增 `render_fb_xml` /
  `render_instance_db_xml` / `_render_ob_xml(call_fb=...)`，W 已在 V19 临时副本上真机验证
  **U 的独立构造脚本**产出的完整 AF 包；但 `gateway/app/services/plc/tia_delivery.py::build_xml_supplement()`
  此前仍**只遍历 `blocks_manifest` 里的 OB** 生成 `xml_supplement/ob/*.xml`，不生成被 Call
  网络引用的 FB 块与实例 DB 块。用户拿正式交付 ZIP 按 XML 补充包导入时仍会因缺块失败。
- 本轮把 U 的渲染能力**接线到正式通道**：按产品通道自身命名约定，从 `blocks_manifest`
  查真实 FB/DB 条目取真实 `number`，生成 `xml_supplement/blocks/*.xml`，并把 `call_fb`
  透传给 `_render_ob_xml`，使 `CallInfo.Name` / `Component.Name` / `InstanceOfName` 与包内
  `<Name>` 逐字一致；增量扩展返回 dict 与两处 manifest 组装，新增离线单测。
- **真机边界**：W 的 `evidence/uc04_full_package_real.json` 验证对象是
  `tools/build_full_af_package.py --out ...` 产出的**独立包**；**正式产品通道产出的本包
  尚未单独做真机导入编译验证**，由后续 agent 在临时副本上按 `import_order` 验证。

---

## 1. U 独立包 vs 正式产品通道的差异（本次接线根因）

| 维度 | U 的独立构造脚本 `tools/build_full_af_package.py` | 正式产品通道 `deliver_tia` → `build_xml_supplement` |
|---|---|---|
| 触发方式 | `python tools/build_full_af_package.py --out <dir>`（离线 CLI） | `deliver_tia(session, mode="package\|auto")` / `/deliver-tia` 端点 |
| 产物根目录 | 直接 `blocks/*.xml` + `ob/*.xml` + `folders.json` + `manifest.json` | 交付 ZIP 内 `xml_supplement/ob/*.xml` + `xml_supplement/folders.json` + `xml_supplement/manifest.json` + `tia_delivery.json` |
| FB / 实例 DB 块 | **有**（`render_fb_xml` / `render_instance_db_xml`，U 新增） | **接线前：无**（本轮补齐为 `xml_supplement/blocks/*.xml`） |
| FB / DB 命名 | **独立命名** `FB1000_StdSignal` / `DB1000_StdSignal`（刻意不以 `_DB` 结尾，复刻真实 V19 先例） | `FB 名 = re.sub(r"_DB$", "", call_db)`、`DB 名 = call_db`（`xxx_DB` → `xxx`），SCL 源产物本身就是这个形态 |
| FB / DB 编号来源 | 脚本常量 `DEFAULT_FB_NUMBER=1000` / `DEFAULT_DB_NUMBER=1000` | **`delivery["blocks_manifest"]` 里真实 FB / DB 条目的 `number`**（不虚构） |
| `call_fb` 来源 | `ob_entries` 显式配置（fail-closed 校验） | 从 OB 的 SCL 用 `_CALL_DB_RE` 提取 `call_db` 后按产品通道约定推导 |
| `<Created>` 时间戳 | 固定 `2000-01-01T00:00:00Z`（字节级可复现） | 沿用 `time.gmtime()`（与既有 OB XML 一致，本轮不改） |
| 静态门禁 / PCEC | 不经过 | 经过四层静态门禁 + PCEC 账本（既有编排，本轮不动） |
| 真机验证状态 | **已由 W 在独立包上验证**（5/5 导入、编译 0/0 Success） | **尚未单独真机验证**（本轮仅离线自洽 + 离线单测） |

U 的脚本是**证明「FB + 实例 DB + Call OB 自洽包可真机导入编译」的探针级证据**；正式通道是
**用户实际拿到的交付物**。两者模板同源（同一 `tia_delivery.py` 内 U 新增的渲染函数），
但命名约定、编号来源、产物路径、是否过门禁均不同，**不能把独立包的真机结论直接套到正式包**。

---

## 2. 两套命名约定为何不同（不混用、不互相覆盖）

| | U 独立包 | 正式产品通道 |
|---|---|---|
| 约定 | FB / DB **独立命名**（`FB1000_…` / `DB1000_…`） | `call_db` 以 `_DB` 结尾，`call_fb = re.sub(r"_DB$", "", call_db)` |
| 依据 | 真实 V19 导出先例 `OB1Main.xml` 引用 `FB1000_StdSignal` / `DB1000_StdSignal`，二者**不是** `xxx_DB → xxx` 关系；批次 3 把 `GF_U1EM1_InstDB` 传进旧推导导致 FB 名退化被 V19 拒绝 | 正式通道 SCL 源由 AF 生成器产出，实例 DB 名天然带 `_DB` 后缀（如 `U1_KukaVisionStation_CallUnit_DB`），对应 FB 名去掉 `_DB`；存量测试 `test_greenfield_tia_delivery.py:413-414` 断言 `CallInfo.Name="U1_KukaVisionStation_CallUnit"` / `Component.Name="U1_KukaVisionStation_CallUnit_DB"` |
| `_render_ob_xml` 参数 | 走新路径显式 `call_fb`（可独立命名） | 本轮传 `call_fb=re.sub(r"_DB$", "", call_db)`，**与旧路径不传 `call_fb` 时的回退推导逐字一致**，故存量断言不变 |

**为何不改正式通道去迁就独立命名**：正式通道的 FB / DB 名必须与 `blocks_manifest`（SCL 源
产物）逐字一致，否则包内 SCL 块与 XML 块名字对不上；独立命名是 U 探针用来复现/修复批次 3
失败输入的**构造选择**，不是产品通道既有数据的真实形态。`_render_call_network(call_fb="")`
的旧回退（K1 探针 / U 兼容测试）**原样保留**，两套约定各自成立、互不覆盖。

---

## 3. 本次接线内容

### X1 · `build_xml_supplement` 生成配套 FB / 实例 DB XML（不虚构编号）

对每个**成功生成且带 `call_db`** 的 OB：

1. 按 OB 的 SCL（`_CALL_DB_RE`）提取 `call_db`；按 `call_db` 聚合引用它的 OB 名列表
   （`refs_by_call_db`），**同名块被多个 OB 引用只生成一次**。
2. `call_db` **不以 `_DB` 结尾** → 不猜 FB 名，**跳过并留痕**（`skipped_blocks`，
   `reason` 写明「不以 _DB 结尾 …不猜 FB 名」）。
3. `call_fb = re.sub(r"_DB$", "", call_db)`；在 `delivery["blocks_manifest"]` 里查
   `block_type == "FB" and name == call_fb` 与 `block_type == "DB" and name == call_db`
   的**真实条目**，取其真实 `number`。
4. **任一真实条目找不到** → **不虚构编号**，跳过并把原因写入 `skipped_blocks`
   （`reason: "blocks_manifest 无对应 FB/DB 条目（缺 …），按 K1 口径不虚构编号"`）。
5. 找到 → 调用同文件 U 新增的
   `render_fb_xml(fb_name=call_fb, fb_number=..., tia_version=...)` 与
   `render_instance_db_xml(db_name=call_db, db_number=..., instance_of_fb=call_fb, tia_version=...)`
   生成 XML，写入 `xml_supplement/blocks/<name>.xml`，**全部 `.encode("utf-8-sig")`**。
6. 给 `_render_ob_xml` 传 `call_fb=call_fb`（成功解析时），保证 `CallInfo.Name` /
   `Component.Name` / DB `InstanceOfName` 与包内 FB/DB `<Name>` 逐字一致；
   未成功解析时传空串，走旧回退（逐字结果与接线前一致）。

> U 的渲染函数、`_render_call_network` / `_render_ob_xml` / `_render_multilingual`、
> G 会话模式、K XML 修复、批次 3 `compile_feedback_heal` **一行未动**；
> **未新增任何 import**（`test_sanctioned_phase2_module_whitelist` 不受影响）。

### X2 · 返回 dict 增量扩展 + 两处 manifest 同步（向后兼容）

`build_xml_supplement` 返回 dict **保留原有全部键**：
`ob_files` / `generated_obs` / `skipped_obs` / `folders` / `supplement_files` /
`xml_package_unverified`；**增量新增**：

| 键 | 含义 |
|---|---|
| `generated_blocks` | 每项含 `name` / `type`（`FB` \| `InstanceDB`）/ `number` / `path` / `sha256` / `referenced_by_obs`（DB 项另含 `instance_of_fb`） |
| `skipped_blocks` | 跳过原因清单（非 `_DB` 后缀 / 缺真实 FB/DB 条目） |
| `import_order` | 严格 **FB → DB → OB** 的实际路径序列（先被引用块，后引用它们的 Call OB） |
| `references_self_consistent` | bool：无跳过块且每个带 `call_db` 的 OB 都成功配套生成 FB/DB |

`supplement_files` **新增** `xml_supplement/blocks/*.xml` 键（不改原有键：
`xml_supplement/ob/*.xml`、`folders.json`、`README.md`、`manifest.json` 占位）。

两处 manifest 组装都同步了 `generated_blocks` / `skipped_blocks` / `import_order` /
`references_self_consistent`：

| # | 位置 | 函数 / 对象 | 作用 |
|---|---|---|---|
| 1 | `tia_delivery.py` `_stage_package` 内 `manifest = {...}`（约 899–920 行区段，接线后行号顺延） | `xml_supplement/manifest.json` | 落盘 + 打进最终 ZIP 的补充包清单 |
| 2 | `tia_delivery.py` `deliver_tia` 收尾 `receipt = {...}`（约 1470–1480 行区段，接线后行号顺延） | `tia_delivery.json` 回执 / `deliver_tia` 返回值 | 另一条交付路径的清单，避免出现「缺 `generated_blocks`」的路径 |

两处均**保留** `xml_package_unverified: True` 与 `pending_real_machine: True` 不变
（第 2 处的值分别来自 `supplement["xml_package_unverified"]` 与
`diagnostics.pending_real_machine`，本轮未改任何标志位赋值）；`pending_reason` / `note`
更新为准确描述：

> 「自产 OB/FB/DB XML 已在独立包探针级真机验证（见 `evidence/uc04_full_package_real.json`），
> **正式产品通道产出的本包尚未单独真机验证**」

`xml_supplement/README.md` 补 `blocks/*.xml`、`import_order`（FB → DB → OB）与诚实边界说明。

### X3 · 新增离线单测

`tests/unit/test_greenfield_supplement_self_consistent.py`（8 例，纯离线），复用
`tests.unit.test_greenfield_tia_delivery._frozen_session` 构造真实会话，覆盖：ZIP 内 blocks
存在、CallInfo/Component 与 `<Name>` 逐字一致、`InstanceOfName` 回链 FB、`import_order`
FB→DB→OB、`references_self_consistent`、manifest 诚实标志、真实编号/去重/sha256、
缺条目与非 `_DB` 后缀不虚构且留痕。

### X4 · 本报告

即本文件。

---

## 4. 接线前后 `build_xml_supplement` 差异一览

| 项 | 接线前 | 接线后 |
|---|---|---|
| `supplement_files` 键 | `ob/*.xml`、`folders.json`、`README.md`、`manifest.json` | 上述 **+ `blocks/*.xml`**（增量，不改原键） |
| 返回 dict 键 | 6 个原键 | 6 个原键 **+ 4 个增量键**（`generated_blocks` / `skipped_blocks` / `import_order` / `references_self_consistent`） |
| OB 引用块 | 只生成 OB XML，Call 指向包内不存在的 FB/DB | 配套生成 FB / 实例 DB XML，引用逐字自洽 |
| OB XML 的 `call_fb` | 不传（旧回退 `re.sub`） | 成功解析时显式传（值与旧回退逐字一致） |
| 跳过条件 | 仅 ProDiag 类 OB（`skipped_obs`） | 另增：非 `_DB` 后缀 / 缺真实 FB/DB 条目（`skipped_blocks`） |
| 编号来源 | 仅 OB 号来自 `blocks_manifest`+IR | FB/DB 号**同样**来自 `blocks_manifest` 真实条目，缺失不虚构 |
| 诚实标志 | `xml_package_unverified=True` | **不变**（`True`），`pending_reason`/`note` 更新为准确口径 |

---

## 5. 正式包 `import_order` 与引用自洽校验结果（**离线自检**）

以下为离线直接调用 `build_xml_supplement` 的真实打印结果（参考冻结会话，
`blocks_manifest` 含 4 个带 `call_db` 的 OB 对应真实 FB/DB 条目），**不是真机结论**：

```
generated_blocks（4 项，按 name 去重；每 DB 被 Main + Startup 两个 OB 引用）：
  U1Em1_Station1_CallEquipment      | FB         | 1010 | ref=[U1Em1_Station1_Main, U1Em1_Station1_Startup]
  U1Em1_Station1_CallEquipment_DB  | InstanceDB | 1015 | ref=[U1Em1_Station1_Main, U1Em1_Station1_Startup]
  U1_KukaVisionStation_CallUnit     | FB         | 1001 | ref=[U1_KukaVisionStation_Main, U1_KukaVisionStation_Startup]
  U1_KukaVisionStation_CallUnit_DB | InstanceDB | 1011 | ref=[U1_KukaVisionStation_Main, U1_KukaVisionStation_Startup]
skipped_blocks: []
references_self_consistent: True
```

`import_order`（严格 FB → DB → OB，共 10 项）：

```
1. xml_supplement/blocks/U1Em1_Station1_CallEquipment.xml        (FB)
2. xml_supplement/blocks/U1_KukaVisionStation_CallUnit.xml       (FB)
3. xml_supplement/blocks/U1Em1_Station1_CallEquipment_DB.xml     (实例 DB)
4. xml_supplement/blocks/U1_KukaVisionStation_CallUnit_DB.xml    (实例 DB)
5..10. xml_supplement/ob/*.xml                                    (6 个 OB，ProDiag 三类已按存量口径跳过)
```

引用逐字一致校验（离线字符串/ET 解析）：

```
<CallInfo Name="U1_KukaVisionStation_CallUnit" ...>  == FB XML 的 <Name>
<Component Name="U1_KukaVisionStation_CallUnit_DB" /> == DB XML 的 <Name>
DB <InstanceOfName>U1_KukaVisionStation_CallUnit</InstanceOfName> == FB XML 的 <Name>
```

存量断言 `test_greenfield_tia_delivery.py:413-414` 的两个字符串**逐字不变**。
FB/DB `<Number>` 分别取 `1001/1011`、`1010/1015`（真实 `blocks_manifest` 值），未虚构。

---

## 6. 真机验证边界（严格）

1. **W 的真机证据范围**：`evidence/uc04_full_package_real.json` 的 5/5 导入 +
   `errorCount=0 / warningCount=0 / state=Success`，验证对象是
   `tools/build_full_af_package.py --out ...` 产出的**独立包**（`FB1000_StdSignal` /
   `DB1000_StdSignal` 独立命名、固定时间戳、不过静态门禁/PCEC）。
2. **正式产品通道产出的本包尚未单独真机验证**：本轮纯离线接线 + 离线单测，
   未连真机 / 未启动 SessionServer / 未跑 TIA CLI / 未占用端口。FB/DB/OB XML 的
   「最小可导入」仅保证**与 U 已真机验证的模板同源 + 包内引用自洽 + 离线 XML 合法**，
   其真实 `import-xml` / `compile-plc` 结果由**后续 agent** 在
   `AppData/Local/Temp/gf_real_*` 临时副本上按 `import_order` 验证。
3. **不宣称**：不宣称正式包真机导入成功 / 完整包编译零错误 / L2 通过 /
   UC-04 完全闭环；不编造任何真机编译数字；`xml_package_unverified` 保持 `True`。
4. **已知既有边界延续**：`SW.PlcBlockGroup` XML 不可 `import-xml` 导入（走
   `create-block-group` API，`folders.json` 是文档化清单）；FB/实例 DB 相对真实 V19
   先例有精简（空 Section 无 Member、省略 UDA、culture 收敛 `zh-CN`）；K caseB
   `errorCount=2` 是占位块不存在的同源根因，未掩盖。
5. **待后续 agent 的正式包真机项**：按 `xml_supplement/manifest.json` 的 `import_order`
   （FB → DB → OB）在临时副本逐项 `import-xml`、按 `folders.json` 走
   `create-block-group` API、`compile-plc` 取真实返回；结论回填前
   `pending_real_machine` 不得消除。

---

## 7. 复现命令

```bash
R="C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project"; cd "$R"

# 1) 本轮验证（任务指定 5 个单测文件；主 agent 收口统一跑全量，本轮不跑全量）
./.venv/Scripts/python.exe -m pytest \
  tests/unit/test_greenfield_supplement_self_consistent.py \
  tests/unit/test_greenfield_tia_delivery.py \
  tests/unit/test_greenfield_k1_probe.py \
  tests/unit/test_greenfield_full_af_package.py \
  tests/unit/test_greenfield_legacy_guard.py -q

# 2) 离线自检：直接调 build_xml_supplement 打印 generated_blocks / import_order / 自洽标志
#    （纯离线，不写产品目录；见本报告 §5）
```

> **不要跑全量 pytest**（主 agent 收口统一跑）；本轮未执行任何 git 操作。

---

## 8. 合规与诚实口径声明 / 已知遗留

- **只写 3 个文件**：`gateway/app/services/plc/tia_delivery.py`（仅 `build_xml_supplement`
  与两处 manifest 组装）、`tests/unit/test_greenfield_supplement_self_consistent.py`（新增）、
  本报告（新增）。未改 U 的渲染函数、G 会话模式、K XML 修复、批次 3
  `compile_feedback_heal`、`tools/build_full_af_package.py`、U 的 14 例单测。
- 未改 `legacy_baseline.json`、`test_greenfield_legacy_guard.py`、sha256 冻结清单
  41 个文件、`evidence/rtm.json` / `pending_real_machine.json` / 批次 2·3 既有真机证据、
  C# 源码、`package.json`；未新增第三方依赖；未新增 `tia_delivery.py` 的 import。
- **已知遗留（诚实列出）**：
  1. **正式产品通道产出的本包尚未单独真机验证** —— 本轮最关键遗留，见 §6。
  2. 独立包真机结论（W）与正式包不等价：命名约定、编号来源、产物路径、是否过门禁均不同。
  3. `xml_package_unverified` / `pending_real_machine` 仍为 `True`，由主 agent 收口按证据决定。
  4. 全量 pytest 未跑（主 agent 收口统一跑）；本轮仅跑任务指定的 5 个单测文件。
  5. FB/实例 DB 的精简差异、culture 收敛 `zh-CN` 的语言边界、SW.PlcBlockGroup 走 API
     等既有边界延续，本轮未改变。
