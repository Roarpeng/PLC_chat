# UC-16 真实规格链 `specs/v1 → v2` 与增量 fidelity 闭环（离线侧）

| 项 | 值 |
|---|---|
| 批次 | 批次 4 · 阶段 A（离线侧） |
| Agent | **V**（UC-16 真实规格链 + 增量 fidelity 离线闭环） |
| 日期 | 2026-11-07 |
| 分支 | `dev/greenfield-wp`，基线 `3596fb9` |
| 依据 | `14-batch4-contract.md` §0 UC-16 / §1 全局规则 / §2 所有权 / §3 UC-16 判据；`04-parallel-wp-contract.md` §0；`13-batch3-contract.md` §1/§5 |
| 性质 | **离线侧闭环**；真机 Action C 增量由阶段 B 的 **Agent W** 独占完成 |
| 本轮独占新增文件 | `tools/run_incremental_spec_chain.py`、`tests/unit/test_greenfield_incremental_chain.py`、`evidence/uc16_incremental_spec_chain.json`、`evidence/uc16_incremental_evidence_bundle.json`、本文件 |

---

## §1 批次 3 `base_spec_version=null` 的根因（已勘查，不重新推导）

批次 3 `evidence/uc16_incremental_real.json` 已由 Agent R 在 V19 真机拿到 `/open`=1、3× 编译 0/0、
PCEC 3 条、六字段真实值（`mode=incremental` / `changed_source_ids` / `reverse_protection` /
`tia_side_drift=0` / `ob_number_deviations` 留痕），但存在两处离线侧缺口：

1. **`base_spec_version=null`**：R 走的是**纯 CLI 块级覆盖**（`R_FC_Inc1/2/3` 三次增量 SCL 外部源变体），
   **没有真实 Greenfield 冻结规格链 `specs/v1.json → specs/v2.json`**，因此无真实
   `spec_version` 产物可比，诚实标 `None`（该证据文件已明确 `six_field_notes.base_spec_version`
   与 `honest_boundary` 说明，不冒充）。
2. **增量 `FidelityChecker(mode="incremental")` 未闭环**：该证据的 `fidelity_ok` 引用
   `evidence/uc15_evidence_bundle.json#fidelity_ok`（Agent Q 的**离线 L1 全量**逻辑等价真值），
   并在 `honest_note` 明确「本次无真实 Greenfield 冻结规格链产物，增量
   `FidelityChecker(mode=incremental)` 未闭环，不冒充、不宣称 L4 正式通过」。

契约 `14-batch4-contract.md` §0 已判定：已具备 `compute_spec_diff`、
`FidelityChecker.check(mode="incremental", ...)`、`run_nine_steps.py` 的 v1 冻结落盘能力、
`/begin-edit` `/patch` `/diff` `/confirm-diff` `/action-c` 端点，**不要重写**；本轮只需补齐
**离线侧真实规格链 + 增量 fidelity 报告**。真机增量仍由 W 做。

---

## §2 本轮真实 v1→v2 规格链（TestClient 进程内 ASGI，不连真机）

`tools/run_incremental_spec_chain.py` 用 `fastapi.testclient.TestClient` 挂载
`gateway.app.main:app`（**进程内 ASGI，不启动任何监听端口**），复用
`run_nine_steps.py` 的 `_disable_external_llm`（`greenfield_chat.llm_settings → None`，
使 `/chat` 走零 LLM 依赖的确定性 planner 兜底）、`_call`、`PLC_WORK_DIR` 与 `specs/vN.json`
落盘机制，**真实**走 14 步（每步原始响应关键字段 + `repro_command` 见
`evidence/uc16_incremental_spec_chain.json#steps`）：

| 步 | 真实端点 / 直调 | 作用 |
|---|---|---|
| V-01 | `GET /state?project_id=GF-V-UC16` | 建会话 + 逻辑拓扑占位（**不上传 IO 表，D7**） |
| V-02 | `POST /chat` | 确定性 planner 兜底生成首版 IR + 四视图 + 连线清单 |
| V-03 | `POST /engineering-summary` | v1 `/confirm` 前置（Q9 工程视角摘要） |
| V-04 | `POST /confirm(explicit=true)` | **冻结 v1** → 落盘 `specs/v1.json` |
| V-05 | `POST /begin-edit` | FROZEN → LINKABLE，回到可编辑态（v1 字节不变） |
| V-06 | `POST /patch(add_cm)` + `POST /validate` | **真实增量编辑**：新增 1 个执行件，走 `apply_canvas_patch` 统一入口；目标 `em_id=U1EM1` 取自真实 IR |
| V-07 | `POST /engineering-summary` | v2 `/confirm` 前置（`begin_edit` 重置了 shown 标志） |
| V-08 | `POST /confirm(explicit=true)` | **冻结 v2** → 落盘 `specs/v2.json` |
| V-09 | `load_frozen_spec(sid, 1/2, ...)` 直调 | **从磁盘**装载两版（不依赖会话内存态），核对一致性 |
| V-10 | `POST /diff(from_version=1, to_version=2)` | 服务端 `diff_placeholder` → `compute_spec_diff` 真实 SpecDiff |
| V-11 | `compute_spec_diff(v1, v2)` 直调 | 产出 `SpecDiff` 对象，供增量 `FidelityChecker` 的 `diff` 入参 |
| V-12 | `POST /action-a` | 在 v2 FROZEN 下 `run_action_a` / `generate_project_package` 缓存 `last_delivery`（含 `zip_bytes` + `blocks_manifest`）作为 **v2 真实派生产物** |
| V-13 | `FidelityChecker.check(mode="incremental", ...)` 直调 | 复用 `_build_artifacts` / `_action_spec_like` 的真实 artifacts + 真实 diff → 增量报告 |
| V-14 | 纯计算 | 组装增量 EvidenceBundle 六字段 + `bundle_sha256` 可复算 |

**规格链真实结果**（`spec_hash` 不含 `frozen_at` / `session_id` / `work_dir`，同输入可稳定复现；
`work_dir` / `session_id` / `bundle_sha256` 因 `mkdtemp` + `registry.reset()` 每次运行刷新，
以产物字段为准）：

| 字段 | v1 | v2 |
|---|---|---|
| `spec_hash` | `sha256:9bc022427c5bdb0e1b69f1fa89cdc459de4a121f157395b8ddbd7eebbc994e60` | `sha256:52190cc0b1e0769d79f400d6b72ed8d59472f09dc20d7e0c69222a030a7b8605` |
| `spec_version` | `1` | `2` |
| `project_id` | `GF-V-UC16` | `GF-V-UC16`（一致） |
| `prev_spec_hash` | `""` | = v1 的 `spec_hash` |
| 磁盘路径 | `<PLC_WORK_DIR>/greenfield/<sid>/specs/v1.json` | `.../specs/v2.json` |

两版 `spec_hash` 不同、`project_id` 一致、`spec_version` 为 1/2，且 `specs/v1.json` /
`specs/v2.json` 均真实落盘、可被 `load_frozen_spec` 仅凭磁盘重建（`FrozenSpec.from_dict`
哈希复现通过）。**这就是批次 3 缺失、本轮补齐的规格链地基。**

---

## §3 真实 `spec_diff` 与增量 `FidelityReport`

### 3.1 `spec_diff`（`POST /diff` 与直调 `compute_spec_diff(v1, v2)` 一致）

| 字段 | 真实值 |
|---|---|
| `base_spec_version` | `1`（补齐批次 3 的 `null`） |
| `target_spec_version` | `2` |
| `changed` | `count=0`, `source_ids=[]` |
| `added` | `count=1`, `source_ids=["U1EM1_CM3"]`（V-06 真实新增执行件） |
| `removed` | `count=0`, `source_ids=[]` |
| `changed_source_ids` | `["U1EM1_CM3"]`（**非空**） |
| `http_vs_direct_ids_match` | `true` |

### 3.2 增量 `FidelityReport`（`FidelityChecker.check` 真实 `to_dict()` 全字段）

调用参数：`spec=v2 FrozenSpecLike`（经 `_action_spec_like`，`expected_source_ids` = v2 派生产物
17 个 `source_id`）、`artifacts=_build_artifacts(v2 last_delivery)`（26 个产物块）、
`mode="incremental"`、`base_spec_version=1`、`diff=compute_spec_diff(v1, v2)`、
`tia_side_snapshot=None`。

| 字段 | 真实值 |
|---|---|
| `fidelity_ok` | `true` |
| `coverage` | `1.0` |
| `orphan` | `0` |
| `drift` | `0` |
| `tia_side_drift` | `0` |
| `mode` | `"incremental"` |
| `base_spec_version` | `1` |
| `changed_source_ids` | `["U1EM1_CM3"]`（非空，来自真实 diff） |
| `reverse_protection` | `{"status": "pending_real_machine", "allowed": null, "drift_count": 0, "tia_side_drift": 0, "blocked_source_ids": [], "reason": "未提供 TIA 侧块快照..."}` |
| `coverage_matrix` | 17 项真实派生产物映射（`DB::` / `FB::` / `FC::` / `OB::` 开头） |
| `orphan_blocks` / `drift_items` / `unmapped_spec_objects` | 均空 |
| `ob_number_deviations` | `[]`（**显式留痕**，`notes` 含「ob_number_deviations 为空(仍显式留痕,不静默)」） |
| `spec_hash` / `spec_version` | v2 的 `spec_hash` / `2` |
| `product_hash` | 真实产物规范化 sha256 |
| `pending_real_machine` | `true` |
| `notes` | 含离线口径 / 增量模式全量四指标复核 / ob 留痕 4 条 |

**判据达成**：`fidelity_ok=true / coverage=1.0 / orphan=0 / drift=0 / tia_side_drift=0`
（契约 §3.2），且为**本链真实 `FidelityChecker(mode="incremental")` 产出**，不再引用 Q 的
离线 L1 全量真值。

> **命名空间诚实说明**：`SpecDiff.changed_source_ids` 来自 `compute_spec_diff` 对
> `ir_snapshot` 的 **IR 层** source block 提取（新增执行件 id `U1EM1_CM3`），而
> `FidelityChecker` 的 `artifacts` / `expected_source_ids` 来自 **v2 派生产物层**
> （`DB::` / `FB::` / `OB::` 等）。两者命名空间不同；产品 `FidelityChecker` 增量模式按
> `fidelity.py` 既有实现「全量四指标复核（安全侧更严）」处理，故 `coverage=1.0` 指 v2
> 派生产物 1:1 全覆盖，**不等价于「逐个 IR 层变更块单独校验」**。如实记录，不掩盖。

### 3.3 `tia_side_snapshot` 的诚实处理

本轮为离线侧，**无真实 TIA 块哈希快照，不虚构**。按 `FidelityChecker` 现有约定传
`tia_side_snapshot=None`：`tia_side_drift` 记 `0`、`pending_real_machine=true`、
`reverse_protection.status="pending_real_machine"`（`allowed=null`）。
真机 D10 反向保护 `allowed=true` 的真值由 Agent W 在 V19 上验证（批次 3 R 的
`reverse_guard_verdict.allowed=true` 是另一条真机证据，本轮不复用冒充）。

---

## §4 增量 EvidenceBundle 六字段真实值 + `bundle_sha256`

`evidence/uc16_incremental_evidence_bundle.json` 为离线增量 EvidenceBundle 实例化，
六字段取自本链真实增量 `FidelityReport`：

| 六字段 | 真实值 |
|---|---|
| `mode` | `"incremental"` |
| `base_spec_version` | `1`（**真实值**，补齐批次 3 `null`） |
| `changed_source_ids` | `["U1EM1_CM3"]`（非空） |
| `reverse_protection` | `pending_real_machine` / `allowed=null`（离线诚实值，真机由 W 补 `allowed=true`） |
| `tia_side_drift` | `0` |
| `ob_number_deviations` | `[]`（显式留痕 + `ob_number_deviations_note`，禁止静默） |

`bundle_sha256` = `canonical_hash({k:v for k,v in bundle.items() if k not in
('bundle_sha256','bundle_sha256_recomputed','bundle_sha256_match')})`，并在产物内附
`bundle_sha256_recomputed` / `bundle_sha256_match=true` 供复算（单测
`test_bundle_sha256_recomputable` 对 live 与 evidence 两份均复算通过）。
具体 sha256 值见产物字段（随 `work_dir` / `session_id` 刷新，判定恒 `match=true`）。

**与批次 3 六字段的对比**：

| 字段 | 批次 3 `uc16_incremental_real.json`（真机 CLI 块级覆盖） | 本轮（离线真实规格链） |
|---|---|---|
| `base_spec_version` | `null`（诚实标 None，无规格链） | `1`（真实 `specs/v1.json`） |
| `changed_source_ids` | `R_FC_Inc1/2/3`（CLI 块名） | `U1EM1_CM3`（IR 层新增执行件） |
| `reverse_protection` | `allowed=true`（`check_reverse_guard` 对真实 TIA 块哈希） | `pending_real_machine` / `allowed=null`（无 TIA 数据，不虚构） |
| `fidelity_ok` | 引用 Q 离线 L1 全量真值 | 真实 `FidelityChecker(mode=incremental)` 产出 |
| `tia_side_drift` | `0`（真机） | `0`（离线 pending 口径） |
| `ob_number_deviations` | `[]` 留痕 | `[]` 留痕 |

两者互补：批次 3 提供真机 Action C 的编译/PCEC/反向保护真值，本轮提供
**Greenfield 冻结规格链 + 增量 fidelity 的离线侧闭环**。

---

## §5 与 Agent W 真机证据的接线方式

W 是阶段 B **唯一**允许连真机 / TIA / SessionServer 的 agent。接线要点（写入
`evidence/uc16_incremental_spec_chain.json#repro_commands.agent_w_real_machine_action_c`）：

1. **同一 `PLC_WORK_DIR`**：取本产物 `work_dir` 字段（或按 `--work-dir` 固定目录复现），
   使 W 直接复用磁盘上同一份 `specs/v1.json` / `specs/v2.json` 与同一 `session_id`，
   不依赖会话内存态。
2. **差异清单显式确认（D11）**：以 `spec_diff.changed_source_ids` 为差异清单，经
   `POST /api/v1/plc/canvas/greenfield/confirm-diff` 逐条 `confirmed=true` 后才允许写入。
3. **真机 Action C 增量覆盖**：`POST /action-c` 传入
   - `diff`（本链真实 `spec_diff`）、
   - `last_generated`（v2 派生产物哈希）、
   - `tia_side_snapshot`（**真机读回**的真实 TIA 块哈希，替换本轮的 `None`）、
   - `confirmed=true`；
   走 §13.5 八步：会话复用 `/open` 一次 → 反向保护 D10 → 差异确认 → 写前备份 →
   块级覆盖 → 编译 0/0 → 增量 fidelity + PCEC 账本。
4. **W 产出**：`evidence/uc16_incremental_closed_real.json`（真机）、
   `docs/greenfield/16-batch4-real-machine.md`，并按真机结果给 `reverse_protection.allowed=true`
   / `tia_side_drift=0` / `compile_ok` 等真值。
5. **本离线链不代替真机 Action C**：离线 `fidelity_ok` 与真机 `compile_ok` 严格分离（N9），
   真机 L4 结论只在 W 的真实 CLI/HTTP 原始返回出来后成立。

---

## §6 复现命令

```bash
cd <R>

# 离线单测（本轮新增 + 既有验收编排器，不连真机）
./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_incremental_chain.py tests/unit/test_greenfield_acceptance.py -q

# 实例化两份证据产物（TestClient 进程内 ASGI，不起端口）
./.venv/Scripts/python.exe tools/run_incremental_spec_chain.py \
    --out evidence/uc16_incremental_spec_chain.json \
    --bundle evidence/uc16_incremental_evidence_bundle.json

# 供 W 复现：固定 work_dir，使 specs/vN.json 落盘路径确定
./.venv/Scripts/python.exe tools/run_incremental_spec_chain.py \
    --out evidence/uc16_incremental_spec_chain.json \
    --bundle evidence/uc16_incremental_evidence_bundle.json \
    --work-dir <PLC_WORK_DIR>
```

> 复现会刷新 `work_dir` / `session_id` / `bundle_sha256`（`mkdtemp` + `registry.reset()`），
> 但 `spec_hash` / `spec_diff` / 四指标 / 六字段 / `bundle_sha256_match` 稳定；以产物字段为准。
> **不跑全量 pytest**（主 agent 收口统一跑）。

---

## §7 诚实边界（N9 / D12 / 契约 §1、§5）

- **本轮为离线侧闭环**：用 TestClient 进程内 ASGI，**未连真机**、未启动 SessionServer、
  未跑 TIA CLI / `--cli`、未占用 8791/8000 端口；未改任何产品代码
  （`gateway/` / `plc_engine/` / `agents/` / `frontend/` / `industrial/` 一律不碰）、
  未改 `tools/run_nine_steps.py` / `tools/greenfield_acceptance.py`、未改台账与既有真机证据。
- **离线增量 fidelity ≠ 真机 L4 通过**：真机 Action C 增量（会话复用 / 编译 0/0 / PCEC /
  `tia_side_drift=0`）由 Agent W 独占验证；本轮不宣称 UC-16 整体通过。
- **`fidelity_ok` ≠ `compile_ok`**：本轮 `fidelity_ok=true` 仅为 L1 离线 1:1 逻辑等价，
  `compile_ok` 恒 `null`；**不宣称编译零错误**、不标 L2/L4 pass。
- **不虚构 TIA 数据**：`tia_side_snapshot=None` 按 `FidelityChecker` 现有约定处理，
  `reverse_protection` 为 `pending_real_machine`；真机 D10 反向保护由 W 验证。
- **`ob_number_deviations` 显式留痕**（即使为空也写 note，禁止静默），不参与 `fidelity_ok`。
- **不宣称 `L1∧L2∧L3∧L4` 全绿、不宣称 M4 通过或代签**；M4 签署栏始终「待用户签署」，
  本批次最多推进到「证据齐备 / 待用户签署」。
- 跑不通的步骤如实记 `fail` + 原因；`/diff` 或增量 `FidelityChecker` 若失败则如实标
  `pending`、不伪造报告（本轮 14 步实跑全 `pass`，见产物 `summary`）。

---

## §8 本轮新增文件清单

| 文件 | 作用 |
|---|---|
| `tools/run_incremental_spec_chain.py` | 参数化离线规格链驱动（供 W 用同一 `PLC_WORK_DIR` 复现） |
| `tests/unit/test_greenfield_incremental_chain.py` | 15 条离线单测（tmp_path + TestClient） |
| `evidence/uc16_incremental_spec_chain.json` | 14 步真实响应 + v1/v2 规格 + spec_diff + 增量 FidelityReport + 六字段 + repro_command |
| `evidence/uc16_incremental_evidence_bundle.json` | 离线增量 EvidenceBundle 实例化（六字段 + `bundle_sha256` 可复算） |
| `docs/greenfield/15-uc16-spec-chain.md` | 本文件 |
