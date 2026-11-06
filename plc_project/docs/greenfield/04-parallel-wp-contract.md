# Greenfield 并行工作包接口契约（批次 1）

| 项 | 值 |
|---|---|
| 批次 | 离线可并行批次：WP-01 / WP-03 / WP-04 / WP-05 校验器 / WP-07 / WP-08 / WP-09 |
| 分支 | `dev/greenfield-wp` |
| 基线 | `f9d4a3d`（main，提交前全部在途改动已归档） |
| 依据 | `research/PLC_chat_产品开发Plan_v1.0_2026-11-06.md` §5 / §6.3 / §9.1；基线报告 v2.1 §13.8 |
| 性质 | 4 个并行 agent 的**唯一共享契约**；本批次**不含**真机验收 |
| 路径前缀 | `<ROOT>` = `C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project` |

---

## 0. 全局规则（所有 agent 必须遵守）

1. **只写自己所有权范围内的文件**。需要改他人文件时**不要动手**，在返回结果里写 `NEEDS_OTHER_OWNER: <文件> — <原因>`。
2. **禁止执行任何 git 操作**（add / commit / checkout / stash / reset）。并行期间 git 由主 agent 统一操作。
3. **禁止修改** `tests/fixtures/greenfield/legacy_baseline.json` 与 `tests/unit/test_greenfield_legacy_guard.py`。
4. **禁止触碰** SHA256 冻结清单中的 41 个文件，尤其：`plc_engine/af/planner.py`、`compile_jobs.py`、`writeback_heal.py`、`writeback_batch.py`、`industrial/.../FastWriteback.cs`、`plc_engine/pcec.py`、`gateway/app/routers/plc.py`、`io_import.py`、`db_import.py`、`frontend/src/shell/smartRoute.ts` / `WorkspacePanel.tsx` / `ChatDock.tsx`。
5. **禁止注册或调用** `forbidden_endpoints`：`/canvas/confirm-writeback`、`/canvas/compile-jobs`、`/canvas/generate-from-requirement`、`/canvas/generate-from-mermaid`、`/canvas/refactor`、`/canvas/chat-ops`。Greenfield 路由不得产生 canvas ops、不得建 PCEC 事务。
6. **禁止改 C# 侧** `industrial/tia_openness_cli/` 下任何文件；禁止改 `agents/plc/tia/openness_cli.py`（属 WP-02，本批次不做）。
7. **fail-closed**：`fidelity_ok=false` / `tia_side_drift>0` / `ExclusiveAccess` 失败 / 差异清单未确认，一律阻止写入，不降级为「尽力而为」。
8. **N9**：`fidelity_ok` 与 `compile_ok` 是两个独立层，禁止互相替代。本批次无真机，所有涉 TIA 结论一律标 `pending_real_machine`，**禁止**宣称 L2 / L4 通过或「编译零错误」。
9. **遵守 N1–N9**：不做在线调试/下载/仿真、不做 HMI、不做云 SaaS/账号体系、不把物理组态做进产品、不靠换模型提升正确率。
10. **确认前零副作用**：差异清单未显式确认时，`ops` / `disk_writes` / `writebacks` / `generations` 计数器恒 0。
11. 每完成一个模块，跑**自己所有权范围内**的单测文件；不要跑全量 pytest（主 agent 收口时统一跑）。
12. 代码注释与文档用中文可以，但**字符串/标识符/JSON key 一律 ASCII 直引号**；文件统一 UTF-8。

## 1. 文件所有权矩阵（唯一写入范围）

| Agent | 角色 | 独占可写文件（相对 `<ROOT>`） |
|---|---|---|
| **A** | 规格地基 | `plc_engine/af/greenfield_ir.py`、`hw_topology.py`、`greenfield_spec.py`、`greenfield_validator.py`、`greenfield_edges.py`；`gateway/app/services/plc/greenfield_service.py`、`greenfield_session.py`；`gateway/app/routers/greenfield.py`；`tests/unit/test_greenfield_ir.py`、`test_greenfield_gate.py`、`test_greenfield_hardware.py`、`test_greenfield_edges.py`、`test_greenfield_views.py` |
| **B** | 校验器（纯新增为主） | **新建** `plc_engine/af/spec_diff.py`、`reverse_guard.py`、`fidelity.py`；**新建** `tests/unit/test_greenfield_spec_diff.py`、`test_greenfield_reverse_guard.py`、`test_greenfield_fidelity.py`；增量扩展 `plc_engine/af/greenfield_delivery.py`（保持现有公开函数签名不变，只追加字段/产物） |
| **C** | 编译判定与文档 | `gateway/app/services/plc/tia_delivery.py`、`docs/greenfield/01-greenfield-prd.md`、`02-architecture.md`、本文件 `04-parallel-wp-contract.md`（仅追加状态）、`README.md`、`tests/unit/test_greenfield_tia_delivery.py` |
| **D** | 前端 | `frontend/src/shell/GreenfieldPanel.tsx`、`GreenfieldChannel.tsx`、`GreenfieldLinkPanel.tsx`、`GreenfieldGateBar.tsx`、`GreenfieldChatFeed.tsx`、`greenfield.css`、`ProjectLaunchScreen.tsx`、`SclPane.tsx`；`frontend/src/state/greenfield.ts`、`greenfield.test.ts`；**新建** `frontend/src/shell/NewProjectWizard.tsx` |

> 交集检查：4 组文件集合**两两不相交**。若发现必须写他人文件，见 §0.1。

## 2. 共享接口签名（A 产出，B/D 消费；并行期间按此契约开发）

### 2.1 `FrozenSpec`（A：`greenfield_spec.py`）

```python
@dataclass(frozen=True)
class FrozenSpec:
    project_id: str
    version: int
    ir_snapshot: dict          # GreenfieldIR.canonical_json()，必须含 hw_nodes / hw_links
    spec_hash: str             # sha256，覆盖 拓扑+节点+边+步序+资料 全域
    framework_baseline_version: str
    open_questions: tuple[str, ...]
    created_at: str
```

- 不变量：同一画布状态两次 `freeze()` 的 `spec_hash` 必须一致；`FrozenSpec` 必须可**仅凭 `specs/vN.json` 完整重建画布**（含拓扑），不依赖会话内存态。
- A 必须提供 `load_spec(path)` 且支持传入 `project_id`。

### 2.2 `CanvasPatch`（A：`greenfield_ir.py` / `greenfield_validator.py`）

- **复用并扩展现有 `IRPatch` / `apply_patch` 4-op 白名单机制，禁止另起炉灶**；新增统一入口 `apply_canvas_patch(session, patch) -> PatchResult`。
- `chat_turn` / `/links` / `/hardware` / `/patch` 全部收敛到该入口；**禁止**任何模块直接赋值 `session.ir.*`。
- 支持 op：`add_unit` / `add_em` / `add_cm` / `remove_node` / `rename_node` / `relabel_node` / `reparent_node`，以及现有边/变量/步序 op（含 `bind_var`，必须保留撤销语义）。
- 原子拒绝：任一 op 非法则整批回滚，`validate_ir` 通过后才提交；变更事件入账。
- 单测必须包含「绕过 patch 直接写 IR 时测试失败」的负例。

### 2.3 `SpecDiff`（B：`spec_diff.py`）

```python
@dataclass(frozen=True)
class SourceBlock:
    source_id: str
    kind: str
    payload: dict

@dataclass(frozen=True)
class SpecDiff:
    base_spec_version: int
    target_spec_version: int
    changed: tuple[SourceBlock, ...]
    added: tuple[SourceBlock, ...]
    removed: tuple[SourceBlock, ...]
    changed_source_ids: tuple[str, ...]
```

### 2.4 `ReverseGuardVerdict`（B：`reverse_guard.py`）

```python
@dataclass(frozen=True)
class ReverseGuardVerdict:
    allowed: bool
    drift_count: int
    tia_side_drift: int
    blocked_source_ids: tuple[str, ...]
    reason: str
```

- `allowed=False` 时调用方**必须**阻止（D10），禁止「先覆盖再提示」。
- B 只做哈希比对逻辑，输入为 mock 块快照，**不调用** TIA / CLI。

### 2.5 `FidelityReport`（B：`fidelity.py`）

```python
class FidelityChecker:
    def check(
        self,
        spec: "FrozenSpecLike",                # typing.Protocol，仅要求 project_id/version/ir_snapshot/spec_hash
        artifacts: Mapping[str, bytes | str],  # 产物定位 -> 内容
        *,
        mode: str = "full",                    # "full" | "incremental"
        base_spec_version: int | None = None,
        diff: "SpecDiff | None" = None,
        tia_side_snapshot: Mapping[str, str] | None = None,  # source_id -> sha256
    ) -> "FidelityReport": ...
```

`FidelityReport` 字段：`fidelity_ok`、`coverage`、`orphan`、`drift`、`tia_side_drift`、`mode`、`base_spec_version`、`changed_source_ids`、`reverse_protection`、`coverage_matrix`（`source_id → 产物定位`）、`orphan_blocks`、`drift_items`、`unmapped_spec_objects`、`ob_number_deviations`。

- `fidelity_ok = (coverage == 1.0 and orphan == 0 and drift == 0 and tia_side_drift == 0)`。
- `ob_number_deviations` 属不纳入 1:1 的域但**必须留痕，禁止静默**。
- 只读实现：不写盘、不调 LLM、不碰 Openness、不侵入生成链。
- B 用 `typing.Protocol` 解耦 `FrozenSpec`，**不得 import A 正在修改的模块的具体类**，避免并行期签名漂移。

### 2.6 `source_id` 与基线清单（B：`greenfield_delivery.py` 增量扩展）

- 每个派生产物写唯一 `source_id`；产物分栏 `derived/` 与 `framework_baseline/`。
- 生成 `baseline_manifest.json`：列基线条目 + `framework_baseline_version` + 内容 sha256。
- **不修改 `planner.py`**（sha256 冻结）；映射在新通道自有派生层内完成。
- 保持现有公开函数签名向后兼容，A/C 的调用不得 break。

## 3. API 契约（A 实现，D 消费）

统一前缀 `/api/v1/plc/canvas/greenfield`，统一 `ApiResponse` 信封。

| 方法 | 路径 | 请求 | 响应要点 |
|---|---|---|---|
| GET | `/state?project_id=` | — | 增 `project_id`、`framework_baseline_version`、`fidelity` 状态、副作用计数器 |
| POST | `/patch` | `{project_id, ops: [...], base_spec_version}` | `{ir, spec_hash, violations, stage}`；原子拒绝时 422 |
| POST | `/diff` | `{project_id, from_version, to_version}` | `SpecDiff` JSON（带 `source_id`） |
| POST | `/confirm-diff` | `{project_id, diff_id, confirmed: bool}` | 未确认时零副作用计数器恒 0；确认后才允许后续写入 |
| GET | `/specs/{v}?project_id=` | — | 完整 `FrozenSpec` 快照（可重建画布） |

- `POST /confirm`：确认按钮文案「确认设备逻辑并锁定还原契约」；前置门禁 = 拓扑定稿 ∧ `open_questions` 清零 ∧ 节点/连线校验 ∧ 等价性预检 ∧ 基线版本锁定；任一未满足返回具体原因，按钮不可用（D 负责 UI，A 负责服务端校验）。
- 所有新端点**不得**触发存量链、不得建 PCEC 事务。
- D 对 4xx 不重试、5xx 最多重试 3 次、fetch 失败显示离线提示；API 错误必须映射为可读中文文案。

## 4. 术语（Q6 正式口径）

用户语言「工站 / 执行单元 / 执行件 / 设备交互」；AF 术语 `Unit / EM / CM` **只允许出现在工程视角面板**。前端展示层改造为主，**禁止改 IR 语义**。`business_label` 是现成载体；`GFSpecMeta.open_questions` 与 `GFInterlock.source == "inferred"` 机制必须复用，禁止另起炉灶。

## 5. 验收命令（主 agent 收口统一执行）

```
cd <ROOT> && python -m pytest tests/unit -q
cd <ROOT> && python -m pytest tests/unit/test_greenfield_legacy_guard.py -q
cd <ROOT>/frontend && npm run test
cd <ROOT>/frontend && npm run build
```

- `test_frozen_legacy_files_have_zero_diff()` 必须保持 PASS（任何冻结文件 diff 直接 FAIL）。
- 前端构建零 TS 错误；`F13` 的 Monaco 依赖当前**未安装**（`package.json` 无 `monaco`），按 DEP-08 走「纯文本 + 关键字高亮」降级，**禁止**擅自新增第三方依赖。
- 计划 F15 写的 `tests/greenfield/test_fidelity.py` 目录不存在，本批次落 `tests/unit/`。

## 6. 本批次明确不做

WP-00（G0 档位实测，需用户拍板）、WP-02（SessionServer 并线 / P0-G 三次增量，真机）、WP-06（Action A/B/C 三动作产品化，真机）、WP-10（全量验收）、C# `FastWriteback.cs` 改动、在线下载 / online / run-stop / compare-to-PLC、F-block 与 Safety 写入、全局库、UI 自动化。

---

## 7. 批次执行状态（Agent C 追加，2026-11-06）

> 本节为**状态追加**，不修改 §0–§6 任何条款；所有权矩阵、全局规则、验收命令一律以 §0 / §1 / §5 原文为准。

| 项 | 状态 |
|---|---|
| 分支 / 基线 | `dev/greenfield-wp` / `f9d4a3d`；**未执行任何 git 操作** |
| Agent C 交付 | WP-01 的 P0-A（编译判定口径）+ P0-C（文档口径）；UC-02 / UC-03 离线口径验证 |
| 改动文件 | `gateway/app/services/plc/tia_delivery.py`、`tests/unit/test_greenfield_tia_delivery.py`、`docs/greenfield/01-greenfield-prd.md`、`docs/greenfield/02-architecture.md`、`docs/greenfield/04-parallel-wp-contract.md`（仅本节）、`README.md` |
| `compile_ok` 判定式 | `(error_count == 0 and static_gate_passed)`；warning 单列、禁止并入成功；四层静态门禁任一拦截即不算通过（UC-02） |
| TIA 不可用 | 显式失败：`GF_TIA_UNAVAILABLE`（探测不可用）/ `GF_TIA_EXEC_ERROR`（执行中断）→ `ok=false` + 非 HTTP 200；**禁止** 200 静默成功（UC-03） |
| `tia_unavailable` vs 真机未跑 | 报告显式区分：`tia_unavailable`（探测失败）/ `pending_real_machine`（`package` 模式与离线批次），二者 `compile_ok=false` |
| 结构化编译报告 | 回执 `compile_diagnostics`：error 数 / warning 单列清单 / 块清单 / 耗时 / TIA 版本 / 项目路径 / 静态门禁 / `compile_ok`，供 EvidenceBundle 归档 |
| `xml_package_unverified` | 保持 `true`（6 处标注未删、未改 False）；报告与 manifest 统一标 `pending_real_machine`；K1 探针（P0-B）不在本批次 |
| 验收命令结果 | `./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_tia_delivery.py tests/unit/test_greenfield_legacy_guard.py -q` → **18 passed**；`test_frozen_legacy_files_have_zero_diff` **PASS** |
| 冻结清单 / sanctioned 白名单 | 未触碰；`tia_delivery.py` 未新增任何 `forbidden_modules` import，未 import Agent B 的 `fidelity.py` / `spec_diff.py`；仅新增标准库 `dataclasses` |
| L2 / L4 / M4 状态 | 本批次为离线可推进部分；L2 / L4 相关验收项 `pending_real_machine`，**M4 发布门禁在 pending 清零前保持未通过**；禁止以离线单测宣称 L2 通过或「编译零错误」 |
| 「真机全绿」归属 | `L1 ∧ L2 ∧ L3 ∧ L4` 全绿，归属 WP-10 / M4；**尚未达成** |
| AF 档位（P0-D） | 结论待 G0 真机实测后拍板；结论前映射层维持「档位无关」 |
| 待他人收口 | ① `gateway/app/routers/greenfield.py`（Agent A）：`_error_status` 建议把 `GF_TIA_UNAVAILABLE` / `GF_TIA_EXEC_ERROR` 显式映射为 **503**；`/deliver-tia` docstring 中「HTTP 200，ZIP 交付不受影响」需改为显式失败口径。② 前端（Agent D）：编译门禁条 / `CompileDrawer` 文案需随 P0-A「warning 单列、不并入成功」口径同步。本批次均不改动，集成由主 agent 收口。 |
