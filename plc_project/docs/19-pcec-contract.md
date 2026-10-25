# 19 · PCEC 契约(带证据的工程变更事务)——四方并行实现唯一依据

日期:2026-10-24 · 依据:演进方案 §06-10(带证据工程变更)+ 用户批准的开工范围。
原则:**每次写回都是一个可审计事务**,change_id 贯穿 UI→确认→写回→编译→账本;基线变化即过期拒绝;验证状态分级展示,未知≠通过。

## 1. 变更事务对象(纯 dict,JSON 可序列化)

```json
{
  "change_id": "chg-<hex12>",
  "created_at": 1790000000.0,
  "updated_at": 1790000000.0,
  "project_baseline": {"project_hash": "sha256:...", "tia_version": "V19", "parser_version": "0.x"},
  "intent": {"kind": "writeback|nl_edit|fix|import", "request": "<用户意图原文>", "summary": "<一句话>"},
  "ops": [<canvas op 列表,与现有 op 协议一致>],
  "touched_blocks": ["FB_X", "DB_Y"],
  "preconditions": [{"name": "目标块存在", "ok": true}, {"name": "基线未变化", "ok": true}],
  "impact": {"blocks": ["FB_X"], "signals": [], "hmi_widgets": []},
  "verification": {
    "v0_parsed": "pass|fail|pending|skipped",
    "v1_static": "pass|fail|pending|skipped",
    "v2_tia_compile": "pass|fail|pending|skipped",
    "v3_behavior": "pass|fail|pending|skipped",
    "detail": {"compile_job_id": "...", "error_count": 0, "diagnostics": []}
  },
  "approval": {"reviewer": "engineer", "approved_at": 1790000001.0, "scope": "本次回写清单"},
  "rollback": {"backup_path": "...", "backup_hash": "...", "restore_verified": false},
  "status": "proposed|analyzed|validated|approved|applied|failed|expired|rejected|rolled_back",
  "events": [{"ts": 1790000000.0, "event": "created|analyzed|approved|write_started|compile_ok|compile_failed|applied|expired|..."}]
}
```

## 2. 状态机(非法迁移必须抛 `PcecTransitionError`)

```
proposed → analyzed → validated → approved → applied
                ↓          ↓          ↓
             rejected    failed     failed
任意非终态 → expired(仅当基线比对失败时,由基线检查触发)
applied → rolled_back(回滚执行后)
终态:applied/failed/expired/rejected/rolled_back(终态不可再迁移)
```

## 3. 模块 `plc_engine/pcec.py`(并行 A 交付,签名固定)

```python
VERSION = "0.1"                      # parser/engine 语义版本(写入 baseline)

def new_change(intent_kind: str, request: str, ops: list, touched_blocks: list,
               baseline: dict) -> dict                        # status=proposed, events=[created]
def transition(change: dict, to_status: str, *, event: str = "", **patch) -> dict
    # 合法性校验+追加事件+updated_at;patch 合并顶层字段(如 verification/approval)
def project_baseline(project_path: str | Path) -> dict
    # {"project_hash": "sha256:<工程树清单哈希>", "tia_version": "<描述符读出或'unknown'>", "parser_version": VERSION}
    # 哈希=遍历工程根(跳过 Logs/TMP/XRef/_researchos*),对 相对路径+文件大小+内容sha256 的清单再 sha256
def baseline_matches(change: dict, project_path) -> bool      # 比对 project_hash
def changes_root(settings=None) -> Path                       # <PLC_WORK_DIR>/changes(自动建)
def put_change(change: dict, settings=None) -> dict           # 原子写 changes/<id>/change.json + meta.json(id/kind/summary/status/updated_at/touched 计数)
def get_change(change_id: str, settings=None) -> dict | None
def list_changes(settings=None) -> list[dict]                 # 仅 meta,updated_at 降序,坏文件跳过
```

约束:文件写入 temp+rename;`change_id` 正则 `^chg-[0-9a-f]{12}$`;`_MAX_CHANGE_BYTES = 10MB`(ops 快照可截断存储为 touched 清单+哈希,若超限只存摘要并在 events 记 `ops_truncated`)。

## 4. 网关接入(并行 B 交付)

- **确认即建事务**:`POST /api/v1/plc/canvas/confirm-writeback` 在创建编译作业**之前**:`baseline = pcec.project_baseline(project_path)` → `chg = pcec.new_change("writeback", <本次块清单摘要>, ops=[], touched_blocks=pending块清单, baseline)` → 先做预检(通过→v1_static=pass, status=analyzed→validated 中的静态部分)→ **approval 由请求本身承载**(用户点了确认弹窗):approval={reviewer:"engineer", approved_at:now, scope:块清单} → transition approved → 写账本 → 编译作业携带 `change_id`。
- **编译作业回写事务**:compile_jobs 各阶段收敛时更新事务:write_plc+compile_plc ok → `v2_tia_compile=pass`、status applied、rollback.backup_path/hash 记录;任一 error → status failed、v2=fail、diagnostics 摘要入 verification.detail(≤20 条)。
- **基线门禁**:写回执行前 `pcec.baseline_matches` 失败 → 事务置 expired,作业 fail-closed,stage message 注明「工程基线已变化,变更过期拒绝」。
- **API**:
  - `GET /api/v1/plc/canvas/changes` → meta 列表
  - `GET /api/v1/plc/canvas/changes/{id}` → 完整事务
  - confirm-writeback 响应 data 增加 `"change_id"` 字段
- 兼容:不传/异常时**绝不阻塞写回主流程**(事务失败只记 warning 日志,写回照旧)——PCEC 先做"记账员",不做"新故障点"。

## 5. 前端(并行 C 交付)

- **确认弹窗增强**:显示「基线指纹」(project_hash 前 12 位)与 V 等级四行(V0 结构解析 ✓/V1 静态预检 ✓/V2 TIA 编译 ·待执行/V3 行为验证 ·未运行——文案:`已通过/未通过/待执行/未运行`)。
- **变更记录面板**:顶栏新增次级入口「变更记录」→ 抽屉(学 SourceCompareDrawer 交互):列出事务(id 短码/时间/意图摘要/状态徽章/四 V 徽章/影响块数),点条目展开完整事务 JSON 摘要;轮询或打开时拉取 `GET /canvas/changes`。
- **编译作业结束**后刷新变更记录(成功/失败都记)。
- Mock-first:API 未就绪/404 时显示内置示例事务,标注「示例」。

## 6. 治理(并行 D 交付,只动文档与检查,不动行为)

- 修正 README/关键文档中的过期路径(以实际目录为准:解析核心=`agents/plc/tia`,画布引擎=`plc_engine`,唯一网关=`gateway/app`);
- `plc_engine/tia/__init__.py` 与 `plc_gateway/__init__.py` 顶部加弃用说明 docstring(指明权威路径);
- 新增 `tests/unit/test_arch_governance.py`:断言文档不再引用已废弃路径(`plc_engine/tia` 作为解析核心、`tia_openness_mcp`),权威模块文件存在;**禁止删除任何代码**。

## 7. 边界与验收

- 收口验收:真实流程「导入工程→改块→回写博图」产生一条完整事务:proposed→…→applied,V2=pass、approval/rollback 字段齐全、账本可查;人为改动工程文件后再触发同事务 → expired 拒绝。
- 全部测试绿(后端+前端);契约偏差在收口时以本文件为准裁定。
