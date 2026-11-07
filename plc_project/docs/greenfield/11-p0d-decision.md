# P0-D 用户拍板决策记录（AF 档位 / 映射层定型方向）

| 项 | 值 |
|---|---|
| 决策项 | **P0-D**：AF 档位结论与 Greenfield 映射层定型方向 |
| 决策人 | **用户**（PLC_chat 项目负责人与最终决策者） |
| 拍板编号 | 「1」 |
| 决策日期 | **2026-11-06** |
| 归档 | 批次 3 · Agent P · 2026-11-07（**本记录由 agent 归档用户结论，不代拍**） |
| 分支 / 基线 | `dev/greenfield-wp` / `6986699`（未执行任何 git 操作） |
| 契约 | `docs/greenfield/13-batch3-contract.md` §0 / §1 / §2 / §5；前序 `04-parallel-wp-contract.md` §0、`05-parallel-wp2-contract.md` §1 / §6 继续生效 |
| 关联 | `06-gate0-report.md`（§2.2 / §5 / §6 / 新增 §7）、`08-k1-probe-fix.md`、仓库根 `research/Gate0_环境与档位实测_2026-11-06.md` |

> **本记录由 agent 归档用户结论，不代拍、不重新论证、不代用户做技术路线选择。**
> 用户拍板前的「档位无关 / 待拍板」历史状态文字，在 `06-gate0-report.md` §0 / §5 / §6、`05-parallel-wp2-contract.md` §1.3 / §6、F 归档 §7 / §9、`10-real-machine-acceptance.md` §9 等处**原样保留、不改写**，以保留历史判定可追溯性。

---

## 1. 决策内容

用户于 **2026-11-06** 以编号「**1**」正式拍板：

> **P0-D 档位结论 = 坚持「AF Basic 文件夹版」，暂不切「软件单元版」**（采纳 `06-gate0-report.md` §6 推荐结论）。

据此，Greenfield 映射层由「档位无关」**定型为文件夹版口径**；Gate-0 由 `conditional-go` 升为 `go`（准入放行），详见 `06-gate0-report.md` §7。

---

## 2. 依据（引用既有归档，不新增论证、不编造数据）

| # | 依据 | 出处 | 要点（原样引用，附限定） |
|---|---|---|---|
| 1 | 档位对照表 | `06-gate0-report.md` **§2.2** | 组织载体、本机 V19 构造实测、CPU 约束、导入可行性、OB 编号规则、编译 `error_count`、与官方 AF / Eigen 生态关系七个维度的「文件夹版 vs 软件单元版」对照 |
| 2 | P0-D 推荐结论与 5 条依据 | `06-gate0-report.md` **§6** | 推荐「坚持 AF Basic 文件夹版（PRD 现行口径）、暂不切软件单元版」；本机 CPU 不具备软件单元能力、文件夹版经 Openness 实测可用、OB 编号不构成切换理由、Eigen / AF 兼容性仍是推断、K1 探针与档位选择正交 |
| 3 | F 真机结果（文件夹版） | `research/Gate0_环境与档位实测_2026-11-06.md` **§5.3 / §7**；`06-gate0-report.md` §2.3 | V19 副本 1 Unit + 2 EM：`create-block-group` 3× `{"ok":true,...,"saved":true}`，随后 `compile-plc` → `errorCount=0 / warningCount=0 / state=Success`（**真实 CLI 返回**）。**限定**：仅对应 CanvasE2E 副本上建立分组结构后的编译，不是 Greenfield 端到端全链的编译结论 |
| 4 | F 真机结果（软件单元版） | `research/Gate0_环境与档位实测_2026-11-06.md` **§5.5**；`06-gate0-report.md` §2.2 | `--unit` 导入后 `path="Unit_01/OB123Unit01"` 落在普通块分组、未创建真正软件单元；源码 `BlockService.cs:2231` `"SoftwareUnitGroup not available on this PLC"`；完整导入编译未干净跑通（`pending_real_machine`） |
| 5 | K 修复结果（K1 探针级） | `08-k1-probe-fix.md` **§4 caseA / §5.1** | 自产 OB XML 两缺陷（culture `en-US`、`StructuredText/v4` namespace）修复后，V19 真机副本 `import.ok=true` + 编译 `errorCount=0 / warningCount=0 / state=Success`，K1 探针判定「通过」。**限定**：探针级（空网络 OB），非包级 / 端到端全链；caseB Call 网络 OB 编译 `errorCount=2` 为真实失败 |
| 6 | Gate-0 `conditional-go` 两项前置 | `06-gate0-report.md` **§5.2 / §5.3**；`13-batch3-contract.md` §0 | 「P0-D 待拍板」由本决策解除；「K1 探针失败」由 K 的探针级真机复测通过解除 → Gate-0 升 `go`（准入放行） |

> **依据边界**：以上真机数字均为 F / K 归档中对应副本上的真实返回，本记录只做引用，不推断、不改写、不外推为「Greenfield 全链编译通过」，不宣称 `L2` / `L4` 通过。

---

## 3. 生效范围

1. **映射层定型**：由「档位无关」定型为 **AF Basic 文件夹版口径**（`PlcSoftware.BlockGroup.Groups` 嵌套分组路径，如 `Unit_01/EM_01`）；不进入软件单元版（`SoftwareUnitGroup.SoftwareUnits`）定型。
2. **Gate-0 升级**：`conditional-go` → **`go`（准入放行）**，即准入准备完成、可进入档位相关映射层定型；两项前置的逐项解除见 `06-gate0-report.md` §7。
3. **`go` 的严格限定**：`go` = 准入放行，**不等于** `L1∧L2∧L3∧L4` 全绿、**不等于** M4 可签署；M4 签署栏始终「待用户签署」。

---

## 4. 不变更项（本次拍板不改、agent 不得擅动）

| # | 不变更项 | 口径 |
|---|---|---|
| 1 | `framework_baseline` 语义 | 保持不变；不因档位定型重评 / 改写其语义与版本（重评仅在「未来改切软件单元版」触发条件下走变更评估） |
| 2 | 软件单元版 | **暂不切**；存量重构链冻结不变 |
| 3 | `xml_package_unverified` | **维持 `True`**。K 只验证了 OB XML 探针级；`folders.json` / `SW.PlcBlockGroup XML` 可导入性、完整 AF 包联合编译、端到端全链未闭环。**是否消除由本批次 Agent R 的 UC-04 包级复测真实结果决定**；不得擅自改任何代码里的该标志，不得在文档里宣称已消除 |
| 4 | 存量重构链 / 冻结清单 | sha256 冻结清单 41 个文件、`legacy_baseline.json`、`test_greenfield_legacy_guard.py` 一律不碰；不改任何产品代码（`gateway/`、`plc_engine/`、`agents/`、`frontend/`、`industrial/`） |
| 5 | 证据台账 | `evidence/rtm.json` / `pending_real_machine.json` / `acceptance_template.json` / `uc05_real_machine_report.json`、`10-real-machine-acceptance.md` 由主 agent 收口统一更新；Agent P 不改 |
| 6 | M4 门禁 | `M4 未通过 / 不可签署` 口径不变；签署栏仍「待用户签署」，agent 不代签、不把 `m4_signable` 置 true |

---

## 5. 触发条件（未来若改切软件单元版）

按 `06-gate0-report.md` §6「触发式应对（Plan §8.4）」与 `10-real-machine-acceptance.md` §9 同口径：

> **若未来改切「软件单元版」→ 须冻结映射层定型，重评 F6 / 附录 A / `framework_baseline` 版本，走 Plan §9.2 变更评估**；并须重新评估硬件目标（S7-1500 + V19 Up3 + ProDiag / OPC UA，SIOS C1）与 N8「不把物理组态做进产品」的冲突。

在用户另行拍板改切之前，一律按本记录第 1 节「文件夹版」执行；agent 不得自行触发、不得代拍。

---

## 6. 诚实边界与归档声明

- **本记录由 agent 归档用户结论，不代拍**：决策人、拍板编号、拍板日期、决策内容均来自用户已给出的结论，agent 只做记录与执行，未重新论证、未代做技术路线选择。
- 不宣称 `L2` / `L4` 通过、不宣称「编译零错误」、不宣称 `L1∧L2∧L3∧L4` 全绿、不宣称 `xml_package_unverified` 已消除、不宣称 M4 通过或代用户签署。
- `xml_package_unverified` 与 M4 的保留口径：**`xml_package_unverified` 仍保持 `True`**（探针级 OB XML 已验证，`folders.json` / `SW.PlcBlockGroup XML` 可导入性、完整 AF 包联合编译、端到端全链未闭环，由 UC-04 包级复测真实结果决定）；**M4 仍「未通过 / 不可签署」，签署栏「待用户签署」**，批次 3 结论最多推进到「证据齐备 / 待用户签署」。
- 未连真机、未启动任何服务、未跑 pytest、未执行任何 git 操作；只写本决策记录与契约 `13-batch3-contract.md` §2 授权的另 5 个文档（均为末尾追加 / 勾选状态更新）。
- 无绝对日期 / 人力排期、无编造来源或数据；所有真机数字均标注出处与限定条件。
