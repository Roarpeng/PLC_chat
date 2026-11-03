# V3.0 进度独立审计（Progress Audit）

审计对象：`docs/plc_chat_v3_0.html`（V3.0 研发级架构蓝图）P0 交付进度
审计基准：对当前工作区的**独立复核**，不转抄 `docs/08` / `docs/09` 的自报结论
审计方法：静态 API 核验 + 全量测试复跑 + 网关接线检查 + 文档谱系核对
审计日期：2026-11-03

## 0. 结论摘要

| 维度 | 判定 |
| --- | --- |
| V3.0 P0 代码与契约交付 | **属实**（新模块 API 静态核验全部存在；全量单测独立复跑 957 passed，EXIT=0） |
| 真机验收记录 | **采信**（09 的实测数字链完整自洽；本审计未复跑真机，避免触碰 TIA 工程） |
| 性能目标（5s / 96%） | **未达标**（实测最优 28.22s，1.88×；瓶颈在博途项目数据库编译，非 IPC 次数） |
| **对话主链接线** | **未接**（本审计新发现，见 §2.1：fast-writeback 栈是已验收的平行车道，网关零引用） |
| PCEC 关系 | **待定**（fast-writeback 为纯库，未挂账本门禁；接主链前必须过 PCEC） |
| 谱系 | **勘误**（见 §3："博世 OpCon AF"系 v3_0 文档误植，仓库 AF 线为西门子 SIOS 109817223） |

## 1. 独立复核证据

### 1.1 测试复跑（2026-11-03）

- 后端：`.venv/Scripts/python.exe -m pytest tests/unit -q` → **957 passed**（129.98s，EXIT=0）。与 09 自报一致。
  - 备注：用系统 Python 3.14 直跑会因缺 `pytest-asyncio` 报 29 个收集错误，属环境口径问题，非回归。
- 前端：`npx vitest run` → **17 文件 / 219 passed**；`tsc -b` 0 错。

### 1.2 新模块静态核验（声明的 API 全部存在）

| 模块 | 核验点（文件:行） |
| --- | --- |
| `plc_engine/mega_source.py` | `topological_sort()` :80、`CycleError` :32、`filter_dirty()` :167、`bundle()` :205、`write_bundle()` :258 |
| `plc_engine/dependency_closure.py` | `dependents_closure()` :140、`interface_closure()` :237、`mark_interface_change()` :258 |
| `plc_engine/slot_context_slicer.py` | `DEFAULT_TOKEN_BUDGET = 1500` :26、`ContextBudgetExceeded` :38、三级降级 + `assert_context_safe()` :206 |
| `plc_engine/writeback_heal.py` | `DEFAULT_MAX_RETRIES = 3` :47、熔断器（`streaks` 连败追踪）:150 |
| `FastWriteback.cs`（961 行） | 反射 `TiaPortal.ExclusiveAccess` + 优雅降级 :59-72、`incremental_blocks` / `full_software_interface_changed` 双编译路径、`CleanupExternalSource()` 生成后即焚 |
| `OpennessGuardrails.cs`（347 行）+ `Register-OpennessWhitelist.ps1` | 白名单 `Entry (N)` 子键格式、LAD/FBD 分流、IDB 刷新、多版本 DLL |

### 1.3 真机数字（采信 09 第 8 节，未复跑）

- 41 块 / 764KB UTF-8 BOM 单文件批次导入成功；`exclusiveAccessUsed=true`。
- 逐块基线 52.95s → Mega-Source 28.22s（**1.88×**）；`/fast-writeback` 全功能 27.52s。
- 接口变更传播真机实证：不标记 → 928 条 IDB 时间戳错误；标记 → 0 条。
- 三处真机缺陷（白名单注册表格式、`interface_changed` 映射缺失、错误树噪声）均已修复且有单测。

## 2. 本审计新增发现（08/09 未记录）

### 2.1 【关键】极速回写栈未接入对话主链

`gateway/` 全目录对 `writeback_pipeline` / `writeback_batch` / `mega_source` / `fast_writeback` **零引用**（grep 证实）。当前生产路径仍是：

```
对话 → chat_ops/refactor_pipeline → canvas_to_tia_bundle（逐块 .scl）→ changesets → execute_writeback（逐文件 CreateFromFile+GenerateBlocksFromSource）
```

09 所述"接真实回写通道全链路跑通"指 **CLI 直调**（`--cli status` → `/open` → `/fast-writeback`），不经网关。即：极速回写是**已交付、已真机验收、但未并线**的平行车道。主链用户在对话里触发的回写拿不到 1.88× 收益。

**并线要求**：网关回写编排切换到 `writeback_pipeline.build_plan() → writeback_batch → /fast-writeback`，且必须同时挂 **PCEC 账本**（变更事务、基线门禁、V0-V3 状态）——当前 fast-writeback 栈是纯库，无任何 PCEC 调用；不经账本并线将违反 v1.0 规范"变更审查必须调用既有守卫"的红线。

### 2.2 前端契约断线（沿自 docs/22 §3）

`TaskQuickBar`（四类任务入口：理解/诊断/完善/重构）组件已建、契约已定，但 `App.tsx` 未挂载——任务前缀词典仅存注释。挂载为小时级工作量。

### 2.3 release_packages/ 未入库

`HR001_AF_V1_2_Package/`（zap19 + 编译收据 + 64 块重构 SCL 源）是 docs/08 §4.1 的对照基准与真交付物，当前仍在未跟踪状态。本次审计随批入库（31MB）。

## 3. 谱系勘误："博世 OpCon" 与仓库 AF 线不同源

- 仓库自有研究（`docs/17` / `docs/18`）明确：所集成的是**西门子** Automation Framework（**SIOS 109817223**，ISA-88 Unit/EM/CM + PackML + LAF/LPML/LUC/LBC 库族），V3.0 归档为 P4 接口逆向源，实际采用 **V1.2 官方库模板**（`docs/23`）。
- `plc_engine/af/af_model.py` 的 `LAF_SelectJob` / `LBC_*` 均为西门子库名；真机产物 `Sequence.scl` 调用的 `LAF_ControlSclSequence` / `LAF_StatusSclSequence` 亦然。
- "博世 OpCon AF 六槽位"仅出现于 `plc_chat_v3_0.html`，全仓库 `.md` 契约线零出现；v3_0 与仓库正统文档线（`PLC_chat_突破性架构理解与演进方案.html` → `docs/19` PCEC → `docs/21-25` 工作台契约）**互不引用**，且有三处直接矛盾：TIA 版本（V14-17 vs V19）、技术栈（.NET 管线 vs Python 引擎 + C# CLI）、会话模型（常驻守护 vs 演进方案 §11 明确不建议持久会话）。
- **建议**：后续文档将 AF 统一称谓修正为"西门子 AF（SIOS 109817223）"，`docs/08`/`docs/09` 中沿用的"博世 LAF 库"等表述随之勘误；v3_0 的"六槽位单 FB"模板保持其已加的"教学示意"标注，验收以 EM 七文件真实结构为准。

## 4. 进度判定总表（对照 v3_0 六个 Tab）

| Tab | 要求 | 判定 | 依据 |
| --- | --- | --- | --- |
| 1 极速回写 | 五重提速 + C# 引擎 + 排故字典 | 代码✔ / 真机✔(1.88×) / 5s 目标✘ / **主链未接** | §1.2、§1.3、§2.1 |
| 2 七步契约 | 数据流 Schema 化 | ✔（`contracts.py` 七 DTO + `STEP_CONTRACTS`；Step5 切片器达标 1500 tokens） | §1.2 |
| 3 转译与解耦 | anyprogram2SCL + 读写矩阵 | ✔（`flgnet_fold.py` 44KB 折叠链、`decouple.py` 原有资产） | docs/08 §二 |
| 4 AF 重构引擎 | 六槽位模板 | ✔（以西门子 AF V1.2 EM 七文件结构实现，文档模板已标教学示意） | docs/08 §4.1 |
| 5 门禁与自愈 | R1-R5 + 3 次自愈 | ✔（fail-closed；自愈未接真实 LLM） | §1.2、09 §10-4 |
| 6 路线图 | P0 三项 / P1-P3 | P0✔；P1-P3 未启动（符合文档"剥离出主线"） | 09 §1 |

## 5. 剩余工作（按优先级）

| 级 | 事项 | 落点 |
| --- | --- | --- |
| **P0** | 极速回写并线主链 + 挂 PCEC 账本（事务/基线/V0-V3） | `gateway/app/services/plc/refactor_pipeline.py` 编排切换；`writeback_batch` 携带 `change_id` |
| P0 | 批次按 `knowHowProtected` 排除受保护块（真机遗留 3 错） | `writeback_pipeline.build_plan()` |
| P1 | IDB 声明追加的命名映射由上层注入；自愈 `repair_fn` 接真实 LLM | `writeback_batch` / `writeback_heal` |
| P1 | `TaskQuickBar` 挂载回 `App.tsx`（契约 22 §3） | `frontend/src/App.tsx` |
| P1 | 性能口径修正：以实测基线（1.88×，编译耗时主导）替代文档目标值 | v3_0 Tab1 + 09 |
| 文档 | AF 称谓勘误（西门子 SIOS 109817223） | 08/09/v3_0 |

## 6. 本次提交结构

1. `feat`：V3.0 P0 后端/引擎/C# 极速回写栈 + 既有网关与引擎改动 + 08/09 文档 + v3_0 蓝图入库
2. `feat`：前端"产品当班"设计系统重构（冷灰+钴蓝、草稿线稿首屏、按钮动效、lint/inspect 0 FAIL、219 测试绿）
3. `chore`：HR001 交付包与攻坚脚本入库 + 根目录 .gitignore
4. `docs`：本审计
5. `fix(security)`（2026-11-03 后续）：Mimosa 深扫 21 项 finding 三泳道修复（21→12，剩余逐项豁免）、
   agents 层 XML 守卫接线 9 处、`test_pcec_gateway` 账本隔离缺陷修复——详见 `docs/27-security-remediation.md`

## 7. 架构谱系补充（2026-11-03）

公开资料核实：博世 OpCon 为真实框架（Bosch Rexroth，基于 **CoDeSys 2.2**，现更名 Nexeed），
与 TIA/S7/Openness 回写链不同生态；"站点 FB 六槽位"无公开规范。本仓库 AF 线（西门子
SIOS 109817223，V1.2 库模板）为唯一与本工具链兼容的架构依赖；六槽位精华（槽位约束的
LLM 编辑）已由 `slot_context_slicer.py` 无品牌吸收。§3 谱系勘误据此成立。
