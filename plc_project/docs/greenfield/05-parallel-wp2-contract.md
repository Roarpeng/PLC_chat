# Greenfield 并行工作包接口契约（批次 2 · 收官）

| 项 | 值 |
|---|---|
| 范围 | WP-00（G0 准入）/ WP-02（会话并线）/ WP-06（Action A·B·C）/ WP-10（全量验收与证据链）+ F20 前端接线 + 批次 1 遗留补齐 |
| 分支 | `dev/greenfield-wp`，基线 `9f7186b` |
| 依据 | Plan v1.0 §3 G0–G3 / §5 / §6.2 / §7 / §9；基线报告 v2.1 §13.5、§13.8、§13.9 |
| 真机路线 | **主线**（探测见 §0）；STEP 7 许可有效性待一次真实编译确认 |
| 路径前缀 | `<R>` = `C:/Users/vboxuser/Desktop/Project/Code/PLC_chat/plc_project` |
| 前序契约 | `04-parallel-wp-contract.md` 的 §0 全局规则继续生效 |

---

## 0. 真机环境实测（2026-11-06 21:2x）

探针：`industrial/tia_openness_cli/src/TiaOpenness.Server/bin/Release/net481/TiaOpenness.Server.exe --cli status`

```json
{"ok":true,"tiaRunning":false,"processCount":0,"opennessAvailable":true,
 "opennessGroupInToken":true,"tiaVersion":"V19",
 "engineeringDll":"C:\\Program Files\\Siemens\\Automation\\Portal V19\\PublicAPI\\V19\\Siemens.Engineering.dll",
 "connected":false,"projectOpen":false,
 "message":"TIA Portal process not detected (Openness can still start WithoutUserInterface)."}
```

| 预检项（Plan §6.1） | 实测 | 判定 |
|---|---|---|
| 1 TIA V19 + 有效 STEP 7 许可 | `Portal V19\Bin\Siemens.Automation.Portal.exe` 存在；`almservice`/`LicenseManager` Running；**许可有效性未由编译验证** | 部分通过，待 UC-01 实测 |
| 2 Openness 用户组 token + 防火墙白名单 | 本地组 `Siemens TIA Openness` 成员含 `WIN\vboxuser`；探针 `opennessGroupInToken=true`；未见显式命名防火墙规则但 DCOM 探测可用 | 通过 |
| 3 V19 版 `Siemens.Engineering.dll` + F-block 拒绝边界 | `PublicAPI/V19/Siemens.Engineering.dll` 存在且版本匹配；CLI 已实现 F-SCL/F-XML hard refuse（README §Out of scope） | 通过 |
| 4 项目文件锁归属（D9 专用后台实例） | `tiaRunning=false`，可用 `WithoutUserInterface` 后台实例独占项目 | 通过 |

**结论**：走 §6.2 主线。但 **L2/L4 在真实编译报告产出前一律 `pending_real_machine`**；`xml_package_unverified` 在 K1 探针导入成功前保持 `True`。

## 1. 全局规则（在 04 契约 §0 之上追加）

1. **真机操作只允许在临时副本上进行**：复制到 `C:/Users/vboxuser/AppData/Local/Temp/gf_real_*` 后再打开；**禁止**打开/修改 `PLC_Openness_data/` 下任何原始 `.ap19`/`.zap19`，禁止 `Project.Save()` 写回原始路径。
2. **不改 C# 冻结文件** `industrial/.../FastWriteback.cs`（sha256 冻结清单）。SessionServer 并线走 **Python 侧现有 HTTP 路由**（`/open`、`/fast-writeback`、`/compile-plc`、`/save`），不改 C# 源码。
3. **P0-D AF 档位结论由用户拍板**。Agent 只产出「档位对照表 + V19 最小样例导入编译结果 + 推荐结论 + 依据」，**不得代用户拍板**；结论前映射层维持「档位无关」。
4. **禁止以 mock / 离线单测宣称 L2/L4 通过或「编译零错误」**。真机证据必须是 CLI 或 SessionServer HTTP 的真实返回结构，含 `error_count`/`warning` 清单/`tia_version`/`project_path`/耗时。
5. **fail-closed**：`ExclusiveAccess` / 文件锁 / 许可 / token 任一失败即显式报错并终止，不降级为「尽力而为」；`tia_side_drift > 0` 阻止写入；`fidelity_ok=false` 拒绝 Action B；差异清单未确认时零副作用计数器恒 0。
6. **禁止任何 git 操作**（主 agent 统一操作）；**禁止修改** `legacy_baseline.json`、`test_greenfield_legacy_guard.py` 及 sha256 冻结清单 41 个文件。
7. **禁止**在线下载 / online / run-stop / compare-to-PLC、F-block 与 Safety 写入、全局库、UI 自动化（D12 hard refuse）；N1–N9 全程约束。
8. `fidelity_ok` 与 `compile_ok` 严格分离（N9）；warning 单列不并入成功；`tia_unavailable` 显式非 200。
9. 系统 `python` 无 pytest，一律用 `<R>/.venv/Scripts/python.exe -m pytest`。

## 2. 文件所有权矩阵（批次 2，两两不相交）

| Agent | 角色 | 独占可写文件（相对 `<R>`） |
|---|---|---|
| **F** | G0 准入 / 档位实测 / 事实核验 | **新增** `research/Gate0_环境与档位实测_2026-11-06.md`、`tools/gate0_precheck.py`、`docs/greenfield/06-gate0-report.md`；**不改任何产品代码**；真机副本只允许写在临时目录 |
| **G** | WP-02 会话并线 + 编译保存 | `agents/plc/tia/openness_cli.py`、`gateway/app/services/plc/openness_session.py`、`gateway/app/services/plc/tia_delivery.py`；**新增** `tests/unit/test_greenfield_session_mode.py` |
| **H** | WP-06 Action A/B/C + D11 | `gateway/app/routers/greenfield.py`、`gateway/app/services/plc/greenfield_service.py`、`gateway/app/services/plc/greenfield_session.py`；**新增** `tests/unit/test_greenfield_action_abc.py` |
| **I** | WP-10 验收证据链 | **新增** `tools/greenfield_acceptance.py`、`tests/unit/test_greenfield_acceptance.py`、`docs/greenfield/07-acceptance-matrix.md`、`evidence/` 目录模板与 `README.md`；**不改任何产品代码** |
| **J** | 前端 F20 + 三动作 UI + 遗留补齐 | `frontend/src/shell/GreenfieldPanel.tsx`、`GreenfieldGateBar.tsx`、`GreenfieldChannel.tsx`、`frontend/src/state/greenfield.ts`、`greenfield.test.ts`；`plc_engine/af/greenfield_delivery.py`（zip 时间戳确定性 + `coverage_matrix` 结构对齐） |

> G 与 H 通过 §3 接口契约解耦：H **不 import** G 正在修改的模块的新函数，收口阶段由主 agent 接线。

## 3. 接口契约（G ⇄ H）

### 3.1 G 提供的会话端口（消费方按 `Protocol` 解耦）

```python
class TiaSessionPort(Protocol):
    def open_project(self, ap_path: str) -> dict: ...          # /open 一次，返回 session_handle
    def fast_writeback(self, blocks: list[dict], *, overwrite: bool = True) -> dict: ...
    def compile_plc(self) -> dict: ...                          # 结构化诊断，error_count/warnings/blocks/elapsed_ms
    def save_project(self) -> dict: ...                        # 不归档、不重载、不新建项目
    def close(self) -> dict: ...
```

- 会话句柄在**同一进程/同一 HTTP 会话**内复用；连续增量不调用 `create-project`，项目不关闭、不重载、不新建。
- 每次成功增量写 1 条 PCEC 账本；三次增量 = 3 条。
- `ExclusiveAccess` 获取失败返回 `{"ok": false, "code": "GF_EXCLUSIVE_ACCESS_DENIED"}`，调用方 fail-closed。
- 所有方法返回结构化 dict，含 `ok` / `error_count` / `warnings` / `tia_version` / `project_path` / `elapsed_ms`；**不得**把 `tia_unavailable` 包装成 `ok=true`。

### 3.2 H 提供的三动作端点（统一前缀 `/api/v1/plc/canvas/greenfield`）

| 动作 | 端点 | 前置 | 语义 |
|---|---|---|---|
| **A** 导出工程包 | `POST /action-a` | 已 FROZEN | 产出 `fidelity_report.json` + EvidenceBundle + `.zip`；可离线校验；不改 TIA |
| **B** 首次写入博途编译 | `POST /action-b` | **A 的 `fidelity_ok == true`** | 首次 `open_project` → 导入 → `compile_plc` → `save_project`；`fidelity_ok=false` 时拒绝并给明确原因 |
| **C** 调试期增量回写 | `POST /action-c` | 差异清单显式确认（D11）+ 反向保护通过 | §13.5 八步：会话复用 → 规格差异 → 反向保护 → 差异清单确认 → 写前备份 → 块级覆盖 → 编译+保存（不归档不重载）→ 增量 fidelity + PCEC |

- **D11**：`confirmed != true` 时 `ops/disk_writes/writebacks/generations` 恒 0；服务端强制 fail-closed，不能只靠前端拦截。
- **D10**：`reverse_guard.allowed == false` 时阻止并提示，禁止「先覆盖再提示」。
- Action C 的响应必须含 `mode=incremental`、`base_spec_version`、`changed_source_ids`、`reverse_protection`、`tia_side_drift`、`ob_number_deviations`。
- 会话归属冲突时提示关闭用户 UI 或转只读观察。

## 4. 验收用例归属（Plan §7.1）

| UC | 场景 | 归属 |
|---|---|---|
| UC-01 | 档位兼容性最小样例导入编译 | **F**（真机） |
| UC-04 | K1 探针消 `xml_package_unverified` | **F**（真机）→ G 接线 |
| UC-05 | 三次增量不重载（3× `error_count==0` + PCEC 3 条 + 句柄复用） | **G**（真机地基）+ 收口实测 |
| UC-12 | D10 反向保护被阻止 | H + 收口实测 |
| UC-13 | 失败导入后回滚 | H + 收口实测 |
| UC-15 | §9.2 九步端到端 | **I**（编排脚本）+ 收口实测 |
| UC-16 | §13.9 六条增量用例 | **I** + 收口实测 |
| UC-17 | `fidelity_ok=false` 时 B 被拒绝 | **H** |
| UC-19 | 确认前零副作用 | **H** |
| M4 | `L1∧L2∧L3∧L4` 复核 + 证据包归档 | **I** |

## 5. 验收命令（收口统一执行）

```
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_af_import.py
cd <R> && ./.venv/Scripts/python.exe -m pytest tests/unit/test_greenfield_legacy_guard.py -q
cd <R>/frontend && npm run test && npm run build
```
`test_frozen_legacy_files_have_zero_diff()` 必须 PASS。已知基线既有失败 `test_af_import.py::test_hr001_real_import_roles_and_freeze`（已在 `main@f9d4a3d` worktree 实证），排除且不得修复。

## 6. 本批次必须交付的「诚实口径」

- 真机跑通 → 附真实结构化报告，逐条勾 UC，M4 可签署。
- 真机任一步失败 → 该项标 `pending_real_machine`，写明失败码/原因/复现命令，**禁止**宣称 L2/L4 通过或「编译零错误」。
- P0-D 档位结论：产出对照表与推荐，但**最终拍板留给用户**（Plan §0 Q5 / §9.3）。
