"""Greenfield 连线白名单执行器（§3.7 / §4.3 G4）。

唯一的 IR 编辑入口：``apply_patch(ir, patch)``。四种结构化 ``IRPatch``
（add/remove/redirect edge + set_ir_only_field）均**先在候选副本上校验**，
通过才原子写回；非法 patch 前后 ``ir.ir_sha256()`` 完全相同。

后端是唯一裁定（前端乐观提示不算数）。每条 ``EdgeViolation`` 都带
``{code, view, node_id, edge_id, message}``，可定位到具体视图与节点。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from plc_engine.af.greenfield_edges import (
    ALLOWED_EDGES,
    BRANCH_TERMINAL_STATES,
    ILLEGAL_EDGE_CATALOG,
    MODE_SWITCH_PAIRS,
    PACKML_STATES,
    PLCOPEN_SIGNALS,
    VIEW_FLOW,
    VIEW_SEQ,
    VIEW_STATE,
    EdgeKind,
    NodeKind,
    VIRTUAL_NODE_IDS,
    edge_id,
    is_packml_transition,
    matches_namespace,
)
from plc_engine.af.greenfield_ir import (
    CANVAS_PATCH_OPS,
    HW_PATCH_OPS,
    NODE_PATCH_OPS,
    CanvasPatch,
    GFEdge,
    GFEm,
    GFCm,
    GFUnit,
    GreenfieldIR,
    IRPatch,
    PatchResult,
)
from plc_engine.af.greenfield_ports import EdgeRejectedError, GreenfieldStage
from plc_engine.af.greenfield_views import assert_roundtrip, project_views


@dataclass
class EdgeViolation:
    """一条连线违规：错误码 + 视图 + 节点 + 边 + 解释性原因。"""

    code: str = "GF_EDGE_RULE_VIOLATION"
    view: str = VIEW_FLOW
    node_id: str = ""
    edge_id: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "view": self.view,
            "node_id": self.node_id,
            "edge_id": self.edge_id,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EdgeViolation":
        return cls(
            code=str(data.get("code") or "GF_EDGE_RULE_VIOLATION"),
            view=str(data.get("view") or VIEW_FLOW),
            node_id=str(data.get("node_id") or ""),
            edge_id=str(data.get("edge_id") or ""),
            message=str(data.get("message") or ""),
        )


@dataclass
class ValidationReport:
    """校验报告；``ok`` = 无违规，``open_questions`` 单独作为确认阻断项。"""

    ok: bool = True
    violations: list[EdgeViolation] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    checked_at: str = ""
    ir_sha256: str = ""

    @property
    def blocking_questions(self) -> list[str]:
        """待确认问题（未补齐不得进入确认 / 冻结）。"""
        return list(self.open_questions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": [v.to_dict() for v in self.violations],
            "open_questions": list(self.open_questions),
            "checked_at": self.checked_at,
            "ir_sha256": self.ir_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationReport":
        return cls(
            ok=bool(data.get("ok", True)),
            violations=[
                EdgeViolation.from_dict(v) for v in (data.get("violations") or [])
            ],
            open_questions=[str(x) for x in (data.get("open_questions") or [])],
            checked_at=str(data.get("checked_at") or ""),
            ir_sha256=str(data.get("ir_sha256") or ""),
        )


def _now_iso() -> str:
    """ISO 8601 UTC 时间戳（§8）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _violation(
    catalog_key: str, node_id: str, edge: GFEdge, detail: str = ""
) -> EdgeViolation:
    """按非法边目录构造一条定位准确的违规。"""
    rule = ILLEGAL_EDGE_CATALOG[catalog_key]
    message = rule.reason if not detail else f"{rule.reason}；{detail}"
    return EdgeViolation(
        code=rule.code,
        view=rule.view,
        node_id=node_id,
        edge_id=edge.id,
        message=message,
    )


def _generic_violation(
    code: str, node_id: str, edge: GFEdge, message: str, view: str = VIEW_FLOW
) -> EdgeViolation:
    """构造非目录类（通用规则 / 命名空间）违规。"""
    return EdgeViolation(
        code=code, view=view, node_id=node_id, edge_id=edge.id, message=message
    )


def _node_kind(node_id: str, index: dict[str, dict[str, Any]]) -> NodeKind:
    """取节点类型；未知节点返回 UNKNOWN。"""
    return NodeKind(index.get(node_id, {}).get("kind", NodeKind.UNKNOWN.value))


def _validate_node_namespace(
    node_id: str,
    kind: NodeKind,
    index: dict[str, dict[str, Any]],
    ir: GreenfieldIR,
) -> str:
    """校验节点 ID 命名空间；返回错误说明（空串表示通过）。"""
    if node_id in VIRTUAL_NODE_IDS:
        return ""
    if node_id in PACKML_STATES or node_id.startswith("ST_"):
        return "" if matches_namespace("packml_state_id", f"ST_{node_id}") or node_id in PACKML_STATES else "状态节点命名不合规"
    category_map: dict[NodeKind, str] = {
        NodeKind.UNIT: "unit_id",
        NodeKind.EM: "em_id",
        NodeKind.CM: "cm_id",
        NodeKind.CONTROL_NODE: "control_node_id",
        NodeKind.MODE: "mode_id",
        NodeKind.COMPAT_REF: "compat_ref_id",
        NodeKind.IO_BINDING: "io_binding_id",
        NodeKind.STEP: "step_id",
        NodeKind.JOB: "job_id",
        NodeKind.INTERLOCK: "interlock_id",
    }
    category = category_map.get(kind)
    if category is None:
        return f"节点 {node_id} 类型 {kind.value} 不允许作为连线端点"
    if not matches_namespace(category, node_id):
        return f"节点 ID {node_id!r} 不符合命名空间规则 {category}"
    if kind == NodeKind.CM:
        em_id = str(index.get(node_id, {}).get("em_id") or "")
        if em_id and not (node_id.startswith(f"{em_id}_") or node_id.startswith(em_id)):
            return f"设备 {node_id} 未以其工序前缀开头"
    return ""


def validate_edge(edge: GFEdge, ir: GreenfieldIR) -> list[EdgeViolation]:
    """白名单 + 十类非法边 + 命名空间 + 冻结契约 + 五信号 + PackML 校验。

    Returns:
        违规列表；空列表表示该边合法。不抛异常，便于前端一次拿到全部原因。
    """
    violations: list[EdgeViolation] = []
    index = ir.node_index()
    kind_value = edge.kind_value()
    src_kind = _node_kind(edge.src_id, index)
    dst_kind = _node_kind(edge.dst_id, index)

    # --- I9 命名空间 / 未知节点 / 契约符号冲突 ---
    if not matches_namespace("edge_id", edge.id):
        violations.append(
            _violation("I9", edge.src_id, edge, f"边 ID {edge.id!r} 不符合 E_{{KIND}}_{{src}}__{{dst}}")
        )
    for node_id, kind in ((edge.src_id, src_kind), (edge.dst_id, dst_kind)):
        if node_id not in index:
            violations.append(_violation("I9", node_id, edge, f"未知节点 {node_id!r}"))
            continue
        reason = _validate_node_namespace(node_id, kind, index, ir)
        if reason:
            violations.append(_violation("I9", node_id, edge, reason))
    for ref in ir.compat_refs:
        if edge.src_id == ref.raw_ref or edge.dst_id == ref.raw_ref:
            violations.append(
                _violation("I9", edge.dst_id, edge,
                           f"直接使用冻结契约物理地址 {ref.raw_ref!r} 作为连线端点")
            )
    if not edge.label:
        violations.append(
            _generic_violation("GF_EDGE_RULE_VIOLATION", edge.src_id, edge, "边缺少可见标签")
        )

    # --- 十类非法边（优先判定，保证错误码定位准确） ---
    if src_kind == NodeKind.UNIT and dst_kind == NodeKind.CM:
        violations.append(_violation("I1", edge.dst_id, edge))
    if src_kind == NodeKind.CM and dst_kind == NodeKind.CM:
        violations.append(_violation("I2", edge.dst_id, edge))
    if src_kind == NodeKind.EM and dst_kind == NodeKind.EM:
        violations.append(_violation("I3", edge.dst_id, edge))
    # I4 只禁止「序列/命令语义」绕过控制节点；L2 层级骨架边是唯一例外。
    if (
        src_kind == NodeKind.EM
        and dst_kind == NodeKind.CM
        and kind_value != EdgeKind.E_HIER_EM_CM.value
    ):
        violations.append(_violation("I4", edge.dst_id, edge))
    if dst_kind == NodeKind.COMPAT_REF:
        if kind_value != EdgeKind.E_IO_READ.value:
            violations.append(_violation("I5", edge.dst_id, edge, "只读契约不允许写入边"))
        else:
            violations.append(_violation("I6", edge.dst_id, edge, "必须经适配节点访问"))
    if kind_value == EdgeKind.E_PACKML_TRANSITION.value and not is_packml_transition(
        edge.src_id, edge.dst_id
    ):
        violations.append(
            _violation("I7", edge.dst_id, edge,
                       f"迁移 {edge.src_id} → {edge.dst_id} 不在许可表"),
        )
    if kind_value == EdgeKind.E_MODE_SWITCH.value and (
        f"{edge.src_id}->{edge.dst_id}" not in MODE_SWITCH_PAIRS
    ):
        violations.append(
            _violation("I7", edge.dst_id, edge,
                       f"模式切换仅允许自动模式 ↔ 手动模式，实际 {edge.src_id} → {edge.dst_id}")
        )
    if kind_value in {EdgeKind.E_CN_TO_CM.value, EdgeKind.E_CM_TO_CN.value}:
        cm_id = edge.dst_id if dst_kind == NodeKind.CM else edge.src_id
        cm = next((c for c in ir.cms if c.id == cm_id), None)
        if cm is None or not cm.has_plcopen_five():
            violations.append(
                _violation("I8", cm_id, edge,
                           f"设备 {cm_id} 缺 PLCOpen 五信号 {list(PLCOPEN_SIGNALS)}")
            )
    if kind_value == EdgeKind.E_BRANCH_ALT_OPT.value and edge.dst_id not in BRANCH_TERMINAL_STATES:
        violations.append(
            _violation("I10", edge.dst_id, edge,
                       f"异常分支须收敛到 {sorted(BRANCH_TERMINAL_STATES)}")
        )

    # --- 白名单端点 / 视图掩码 / 层级唯一父 / 数据流单向 ---
    rule = ALLOWED_EDGES.get(kind_value)
    if rule is None:
        violations.append(
            _generic_violation("GF_EDGE_RULE_VIOLATION", edge.src_id, edge,
                               f"边类型 {kind_value!r} 不在 12 类合法边白名单内")
        )
    else:
        if src_kind not in rule.src_kinds or dst_kind not in rule.dst_kinds:
            violations.append(
                _generic_violation(
                    "GF_EDGE_RULE_VIOLATION", edge.dst_id, edge,
                    f"{kind_value} 要求 {sorted(k.value for k in rule.src_kinds)} → "
                    f"{sorted(k.value for k in rule.dst_kinds)}，"
                    f"实际 {src_kind.value} → {dst_kind.value}",
                    view=rule.views[0] if rule.views else VIEW_FLOW,
                )
            )
        if not set(edge.view_mask).issubset(set(rule.views)):
            violations.append(
                _generic_violation(
                    "GF_EDGE_VIEW_MASK", edge.src_id, edge,
                    f"view_mask {edge.view_mask} 超出该边允许的视图 {list(rule.views)}",
                )
            )
        if kind_value == EdgeKind.E_HIER_UNIT_EM.value:
            em = next((e for e in ir.ems if e.id == edge.dst_id), None)
            if em is None or em.unit_id != edge.src_id:
                violations.append(
                    _generic_violation(
                        "GF_EDGE_RULE_VIOLATION", edge.dst_id, edge,
                        "层级唯一父：工序的 unit_id 必须等于边的起点",
                    )
                )
        if kind_value == EdgeKind.E_HIER_EM_CM.value:
            cm = next((c for c in ir.cms if c.id == edge.dst_id), None)
            if cm is None or cm.em_id != edge.src_id:
                violations.append(
                    _generic_violation(
                        "GF_EDGE_RULE_VIOLATION", edge.dst_id, edge,
                        "层级唯一父：设备的 em_id 必须等于边的起点",
                    )
                )
        if kind_value == EdgeKind.E_SC_UP.value and dst_kind != NodeKind.INTERFACE_DB:
            violations.append(
                _generic_violation(
                    "GF_EDGE_RULE_VIOLATION", edge.dst_id, edge,
                    "数据流单向：完成汇总只能上行到接口数据区",
                )
            )
        if kind_value == EdgeKind.E_IO_READ.value and dst_kind != NodeKind.IO_MAPPING:
            violations.append(
                _violation("I6", edge.dst_id, edge, "只读信号必须经适配层")
            )
    return violations


def _branch_balance_violations(ir: GreenfieldIR) -> list[EdgeViolation]:
    """alt / opt / end 配对与异常分支收敛（I10）。"""
    violations: list[EdgeViolation] = []
    text = ir.views.seq.mermaid
    branch_edges = [e for e in ir.edges if e.kind_value() == EdgeKind.E_BRANCH_ALT_OPT.value]
    for edge in branch_edges:
        if edge.dst_id not in BRANCH_TERMINAL_STATES:
            violations.append(
                _violation("I10", edge.dst_id, edge, "异常臂未落到已定义异常态")
            )
    if text:
        opens = sum(1 for line in text.splitlines() if line.strip().startswith(("alt ", "opt ")))
        ends = sum(1 for line in text.splitlines() if line.strip() == "end")
        elses = sum(1 for line in text.splitlines() if line.strip().startswith("else "))
        if opens != ends or elses > opens:
            violations.append(
                EdgeViolation(
                    code=ILLEGAL_EDGE_CATALOG["I10"].code,
                    view=VIEW_SEQ,
                    node_id="",
                    edge_id="",
                    message=f"步序视图 alt/opt 与 end 不配对（开 {opens} / 闭 {ends} / else {elses}）",
                )
            )
    return violations


def validate_ir(ir: GreenfieldIR) -> ValidationReport:
    """全量校验：逐边白名单 + 层级唯一父 + 待确认问题汇总。"""
    violations: list[EdgeViolation] = []
    for edge in ir.edges:
        violations.extend(validate_edge(edge, ir))
    violations.extend(_branch_balance_violations(ir))

    unit_ids = {u.id for u in ir.units}
    em_ids = {e.id for e in ir.ems}
    for em in ir.ems:
        if em.unit_id not in unit_ids:
            violations.append(
                EdgeViolation(
                    code="GF_EDGE_RULE_VIOLATION", view=VIEW_FLOW, node_id=em.id,
                    edge_id="", message=f"工序 {em.id} 的唯一父 {em.unit_id!r} 不存在",
                )
            )
    for cm in ir.cms:
        if cm.em_id not in em_ids:
            violations.append(
                EdgeViolation(
                    code="GF_EDGE_RULE_VIOLATION", view=VIEW_FLOW, node_id=cm.id,
                    edge_id="", message=f"设备 {cm.id} 的唯一父 {cm.em_id!r} 不存在",
                )
            )

    open_questions: list[str] = list(ir.spec_meta.open_questions)
    for interlock in ir.interlocks:
        if interlock.source == "inferred":
            open_questions.append(
                f"联锁 {interlock.id} 为推断来源，请人工确认表达式：{interlock.expression}"
            )
    deduplicated: list[str] = []
    seen: set[str] = set()
    for question in open_questions:
        if question in seen:
            continue
        seen.add(question)
        deduplicated.append(question)
    return ValidationReport(
        ok=not violations,
        violations=violations,
        open_questions=deduplicated,
        checked_at=_now_iso(),
        ir_sha256=ir.ir_sha256(),
    )


# ---------------------------------------------------------------------------
# 结构化 IRPatch（唯一编辑入口）
# ---------------------------------------------------------------------------

#: 明确禁止由 patch 触碰的灰锁 / 契约字段前缀。
FORBIDDEN_PATCH_PREFIXES: tuple[str, ...] = (
    "compat_refs", "units", "ems", "control_nodes", "project",
    "spec_meta", "views", "contract", "db_structs", "io_entries",
    "ob_entries", "safety_entries", "symbols",
)


def _find_by_id(collection: list[Any], obj_id: str) -> Any | None:
    """按 id 在扁平注册表中查找实体。"""
    return next((item for item in collection if item.id == obj_id), None)


def _set_ir_only_field(
    ir: GreenfieldIR, field_path: str, value: Any
) -> list[EdgeViolation]:
    """只改 §3.6.4 允许编辑的不上图字段；触碰契约灰锁一律拒绝。"""
    parts = [p for p in field_path.split(".") if p]
    if len(parts) < 3:
        return [
            _generic_violation("GF_EDGE_RULE_VIOLATION", "", GFEdge(),
                               f"field_path {field_path!r} 格式应为 <组>.<id>.<字段>")
        ]
    group, obj_id, tail = parts[0], parts[1], parts[2:]
    if group in FORBIDDEN_PATCH_PREFIXES:
        return [
            _generic_violation(
                "GF_CONTRACT_IMMUTABLE", obj_id, GFEdge(),
                f"{field_path} 属只读冻结契约 / 结构灰锁字段，禁止写入",
            )
        ]

    def reject(message: str, code: str = "GF_EDGE_RULE_VIOLATION") -> list[EdgeViolation]:
        return [_generic_violation(code, obj_id, GFEdge(), message)]

    if group == "cms":
        cm = _find_by_id(ir.cms, obj_id)
        if cm is None:
            return reject(f"设备 {obj_id} 不存在")
        if tail[0] == "plcopen":
            if len(tail) != 2 or tail[1] not in PLCOPEN_SIGNALS:
                return reject(f"未知五信号字段 {'.'.join(tail)}")
            if not isinstance(value, bool):
                return reject("五信号字段必须是布尔值")
            cm.plcopen[tail[1]] = value
            return []
        if tail[0] == "parameters":
            if len(tail) != 2:
                return reject("参数字段路径不合法")
            if tail[1] == "timeout_ms" and (not isinstance(value, int) or value < 0):
                return reject("timeout_ms 必须是非负整数")
            cm.parameters[tail[1]] = value
            return []
        return reject(f"设备 {obj_id} 的 {'.'.join(tail)} 不是可编辑的不上图字段")

    if group == "steps":
        step = _find_by_id(ir.steps, obj_id)
        if step is None:
            return reject(f"步序 {obj_id} 不存在")
        key = tail[0]
        if key not in {
            "actions",
            "transition_condition",
            "timeout_ms",
            "error_step_id",
            "next_step_id",
            "name",
            "branch",
        }:
            return reject(f"步序字段 {key} 不可编辑")
        if key in {"timeout_ms", "error_step_id", "next_step_id"} and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            return reject(f"{key} 必须是非负整数")
        if key == "name" and (not isinstance(value, str) or not value.strip()):
            return reject("name 必须是非空字符串")
        if key == "actions" and not isinstance(value, list):
            return reject("actions 必须是字符串列表")
        if key == "branch" and not isinstance(value, dict):
            return reject("branch 必须是对象")
        setattr(step, key, value)
        return []

    if group == "interlocks":
        interlock = _find_by_id(ir.interlocks, obj_id)
        if interlock is None:
            return reject(f"联锁 {obj_id} 不存在")
        key = tail[0]
        if key not in {"expression", "source", "applies_to"}:
            return reject(f"联锁字段 {key} 不可编辑")
        if key == "source" and value not in {"user", "contract", "inferred"}:
            return reject("联锁来源只能是 user / contract / inferred")
        if key == "applies_to" and not isinstance(value, list):
            return reject("applies_to 必须是列表")
        setattr(interlock, key, value)
        return []

    if group == "jobs":
        job = _find_by_id(ir.jobs, obj_id)
        if job is None:
            return reject(f"作业 {obj_id} 不存在")
        key = tail[0]
        if key not in {"start_condition", "single_cycle_job"}:
            return reject(f"作业字段 {key} 不可编辑")
        if key == "single_cycle_job" and not isinstance(value, bool):
            return reject("single_cycle_job 必须是布尔值")
        setattr(job, key, value)
        return []

    if group == "modes":
        mode = _find_by_id(ir.modes, obj_id)
        if mode is None:
            return reject(f"模式 {obj_id} 不存在")
        key = tail[0]
        if key not in {"enabled_states", "enabled_transitions", "enable_hold", "enable_complete"}:
            return reject(f"模式字段 {key} 不可编辑")
        if key in {"enable_hold", "enable_complete"} and not isinstance(value, bool):
            return reject(f"{key} 必须是布尔值")
        if key in {"enabled_states", "enabled_transitions"} and not isinstance(value, list):
            return reject(f"{key} 必须是列表")
        setattr(mode, key, value)
        return []

    if group == "io_bindings":
        binding = _find_by_id(ir.io_bindings, obj_id)
        if binding is None:
            return reject(f"映射条目 {obj_id} 不存在")
        key = tail[0]
        if key == "direction":
            return [
                _generic_violation(
                    "GF_CONTRACT_IMMUTABLE", obj_id, GFEdge(),
                    "direction 恒为 IO_READ（只读契约），禁止改写为写向",
                )
            ]
        if key not in {"field_path", "compat_ref_id", "channel"}:
            return reject(f"映射字段 {key} 不可编辑")
        if key == "channel" and value not in {"IO-Mapping", "DB-Adapter"}:
            return reject("channel 只能是 IO-Mapping / DB-Adapter")
        setattr(binding, key, value)
        return []

    return reject(f"未知的不上图字段组 {group!r}")


def apply_patch(ir: GreenfieldIR, patch: IRPatch) -> ValidationReport:
    """原子应用一个结构化 IRPatch；非法 patch **不改 IR**（前后哈希相同）。

    流程：深拷贝候选 → 在候选上应用 → 全量校验 → 通过才整体替换原 IR。
    """
    if patch.op not in CANVAS_PATCH_OPS:
        return ValidationReport(
            ok=False,
            violations=[
                _generic_violation("GF_EDGE_RULE_VIOLATION", "", GFEdge(),
                                   f"未知 patch 操作 {patch.op!r}，仅允许 {sorted(CANVAS_PATCH_OPS)}")
            ],
            checked_at=_now_iso(),
            ir_sha256=ir.ir_sha256(),
        )

    candidate = GreenfieldIR.from_dict(ir.to_dict())
    local_violations: list[EdgeViolation] = []

    if patch.op == "add_edge":
        if patch.edge is None:
            local_violations.append(
                _generic_violation("GF_EDGE_RULE_VIOLATION", "", GFEdge(), "add_edge 缺少 edge 负载")
            )
        else:
            edge = patch.edge
            if any(existing.id == edge.id for existing in candidate.edges):
                local_violations.append(
                    _generic_violation("GF_EDGE_RULE_VIOLATION", edge.src_id, edge,
                                       f"边 ID {edge.id!r} 已存在")
                )
            else:
                candidate.edges.append(edge)
    elif patch.op == "remove_edge":
        target = next((e for e in candidate.edges if e.id == patch.edge_id), None)
        if target is None:
            local_violations.append(
                _generic_violation("GF_EDGE_RULE_VIOLATION", "", GFEdge(),
                                   f"待删除边 {patch.edge_id!r} 不存在")
            )
        elif target.immutable:
            local_violations.append(
                _generic_violation("GF_EDGE_IMMUTABLE", target.dst_id, target,
                                   "系统层级骨架边不可删除（层级唯一父铁律）")
            )
        else:
            candidate.edges.remove(target)
    elif patch.op == "redirect_edge":
        target = next((e for e in candidate.edges if e.id == patch.edge_id), None)
        if target is None:
            local_violations.append(
                _generic_violation("GF_EDGE_RULE_VIOLATION", "", GFEdge(),
                                   f"待改向边 {patch.edge_id!r} 不存在")
            )
        elif target.immutable:
            local_violations.append(
                _generic_violation("GF_EDGE_IMMUTABLE", target.dst_id, target,
                                   "系统层级骨架边不可改向")
            )
        elif not patch.src_id or not patch.dst_id:
            local_violations.append(
                _generic_violation("GF_EDGE_RULE_VIOLATION", "", target,
                                   "redirect_edge 需要同时提供 src_id 与 dst_id")
            )
        else:
            target.src_id = patch.src_id
            target.dst_id = patch.dst_id
            target.id = edge_id(target.kind, target.src_id, target.dst_id)
            if any(e is not target and e.id == target.id for e in candidate.edges):
                local_violations.append(
                    _generic_violation("GF_EDGE_RULE_VIOLATION", target.dst_id, target,
                                       "改向后的边 ID 与已有边冲突")
                )
    elif patch.op == "set_ir_only_field":
        local_violations.extend(_set_ir_only_field(candidate, patch.field_path, patch.value))
    elif patch.op in NODE_PATCH_OPS:
        # WP-07 / D6 节点编辑：在候选副本上改结构，随后由 apply_canvas_patch 重投影。
        local_violations.extend(_apply_node_op(candidate, patch))
    elif patch.op in HW_PATCH_OPS:
        # WP-03 / D4 逻辑拓扑与变量绑定（含 bind_var 撤销语义）。
        local_violations.extend(_apply_hw_op(candidate, patch))

    if local_violations:
        return ValidationReport(
            ok=False,
            violations=local_violations,
            open_questions=validate_ir(ir).open_questions,
            checked_at=_now_iso(),
            ir_sha256=ir.ir_sha256(),
        )

    report = validate_ir(candidate)
    if not report.ok:
        report.ir_sha256 = ir.ir_sha256()  # 原子拒绝：IR 未被改动
        return report

    ir._replace_from(candidate)
    report.ir_sha256 = ir.ir_sha256()
    return report


# ---------------------------------------------------------------------------
# WP-07 / D6 节点编辑 op 与 WP-03 / D4 逻辑拓扑 op（复用 apply_patch 原子框架）
# ---------------------------------------------------------------------------

def _nv(code: str, message: str, node_id: str = "", view: str = VIEW_FLOW) -> EdgeViolation:
    """构造一条不依赖具体 GFEdge 负载的节点编辑违规。"""
    return EdgeViolation(code=code, view=view, node_id=node_id, edge_id="", message=message)


def _next_id(prefix: str, existing: set[str], *, start: int = 1, cap: int = 99) -> str | None:
    """按 ``prefix+N`` 生成不与 existing 冲突的确定性 id；超出 cap 返回 None。"""
    for n in range(start, cap + 1):
        candidate = f"{prefix}{n}"
        if candidate not in existing:
            return candidate
    return None


def _sync_parent_edge(ir: GreenfieldIR, dst_id: str, new_parent: str, kind: EdgeKind) -> None:
    """reparent_node：同步层级骨架边起点并重建边 ID，保证 validate_ir 仍通过。"""
    for edge in ir.edges:
        if edge.kind_value() == kind.value and edge.dst_id == dst_id:
            edge.src_id = new_parent
            edge.id = edge_id(edge.kind, edge.src_id, edge.dst_id)


def _apply_node_op(ir: GreenfieldIR, patch: IRPatch) -> list[EdgeViolation]:
    """七类节点编辑 op，全部在候选副本上操作；合法性最终由 apply_patch 的
    ``validate_ir`` + ``apply_canvas_patch`` 的四视图重投影裁定。"""
    node = dict(patch.node or {})
    node_id = str(patch.node_id or node.get("id") or "").strip()

    if patch.op == "add_unit":
        unit_ids = {u.id for u in ir.units}
        uid = node_id or _next_id("U", unit_ids, start=1, cap=9)
        if not uid:
            return [_nv("GF_EDGE_NAMESPACE_INVALID", "工站数量已达命名空间上限 U1..U9")]
        if not matches_namespace("unit_id", uid):
            return [_nv("GF_EDGE_NAMESPACE_INVALID", f"新工站 id {uid!r} 不符合 U[1-9] 规则", uid)]
        if uid in unit_ids:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"工站 {uid} 已存在", uid)]
        ir.units.append(
            GFUnit(
                id=uid, unit_idx=int(uid[1:]),
                name=str(node.get("name") or uid),
                business_label=str(node.get("business_label") or node.get("label") or uid),
                namespace_prefix=f"{uid}_", parent_id=None, ob_numbers={},
            )
        )
        return []

    if patch.op == "add_em":
        unit_ids = {u.id for u in ir.units}
        parent = str(node.get("unit_id") or patch.parent_id or "").strip()
        if parent not in unit_ids:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"新增执行单元缺少有效父工站 {parent!r}", parent)]
        em_ids = {e.id for e in ir.ems}
        eid = node_id or _next_id(f"{parent}EM", em_ids, start=1, cap=99)
        if not eid or not matches_namespace("em_id", eid):
            return [_nv("GF_EDGE_NAMESPACE_INVALID", f"新执行单元 id {eid!r} 不符合命名空间规则", eid or "")]
        if eid in em_ids:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"执行单元 {eid} 已存在", eid)]
        ir.ems.append(
            GFEm(
                id=eid, em_idx=int(eid.split("EM")[-1]), unit_id=parent,
                name=str(node.get("name") or eid),
                business_label=str(node.get("business_label") or node.get("label") or eid),
                namespace_prefix=f"{eid}_", control_node_id="", job_ids=[],
                initial_step_id=10, ob_numbers={}, sc_policy="SC_ON_COMPLETE",
            )
        )
        return []

    if patch.op == "add_cm":
        em_ids = {e.id for e in ir.ems}
        parent = str(node.get("em_id") or patch.parent_id or "").strip()
        if parent not in em_ids:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"新增执行件缺少有效父执行单元 {parent!r}", parent)]
        cm_ids = {c.id for c in ir.cms}
        cid = node_id or _next_id(f"{parent}_CM", cm_ids, start=1, cap=999)
        if not cid or not matches_namespace("cm_id", cid):
            return [_nv("GF_EDGE_NAMESPACE_INVALID", f"新执行件 id {cid!r} 不符合命名空间规则", cid or "")]
        if cid in cm_ids:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"执行件 {cid} 已存在", cid)]
        ir.cms.append(
            GFCm(
                id=cid, em_id=parent,
                cm_type=str(node.get("cm_type") or "GENERIC"),
                business_label=str(node.get("business_label") or node.get("label") or cid),
                plcopen={sig: True for sig in PLCOPEN_SIGNALS},
                io_binding_ids=[], parameters=dict(node.get("parameters") or {}),
            )
        )
        return []

    if patch.op == "remove_node":
        if not node_id:
            return [_nv("GF_EDGE_RULE_VIOLATION", "remove_node 缺少 node_id")]
        if node_id == "U1":
            return [_nv("GF_EDGE_IMMUTABLE", "根工站 U1 为系统骨架，不可删除", node_id)]
        unit_ids = {u.id for u in ir.units}
        em_ids = {e.id for e in ir.ems}
        cm_ids = {c.id for c in ir.cms}
        cn_ids = {c.id for c in ir.control_nodes}
        job_ids = {j.id for j in ir.jobs}
        step_ids = {s.id for s in ir.steps}
        il_ids = {x.id for x in ir.interlocks}
        hw_ids = {str(n.get("id") or "") for n in ir.hw_nodes}

        to_delete: set[str] = set()
        if node_id in unit_ids:
            child_ems = {e.id for e in ir.ems if e.unit_id == node_id}
            to_delete = (
                {node_id} | child_ems
                | {c.id for c in ir.cms if c.em_id in child_ems}
                | {c.id for c in ir.control_nodes if c.em_id in child_ems}
                | {j.id for j in ir.jobs if j.em_id in child_ems}
                | {s.id for s in ir.steps if s.em_id in child_ems}
            )
        elif node_id in em_ids:
            to_delete = (
                {node_id}
                | {c.id for c in ir.cms if c.em_id == node_id}
                | {c.id for c in ir.control_nodes if c.em_id == node_id}
                | {j.id for j in ir.jobs if j.em_id == node_id}
                | {s.id for s in ir.steps if s.em_id == node_id}
            )
        elif node_id in cm_ids:
            to_delete = {node_id}
        elif node_id in (cn_ids | job_ids | step_ids | il_ids):
            to_delete = {node_id}
        elif node_id in hw_ids:
            ir.hw_nodes = [n for n in ir.hw_nodes if str(n.get("id") or "") != node_id]
            ir.cm_mounts = {cm: hw for cm, hw in ir.cm_mounts.items() if hw != node_id}
            ir.hw_links = [
                l for l in ir.hw_links
                if node_id not in (str(l.get("src_hw_id") or ""), str(l.get("dst_hw_id") or ""))
            ]
            return []
        else:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"待删除节点 {node_id!r} 不存在", node_id)]

        for edge in ir.edges:
            if edge.immutable and (edge.src_id in to_delete or edge.dst_id in to_delete):
                return [_nv("GF_EDGE_IMMUTABLE",
                            f"节点 {node_id} 被系统层级骨架边 {edge.id} 引用，不可删除", node_id)]

        ir.units = [u for u in ir.units if u.id not in to_delete]
        ir.ems = [e for e in ir.ems if e.id not in to_delete]
        ir.cms = [c for c in ir.cms if c.id not in to_delete]
        ir.control_nodes = [c for c in ir.control_nodes if c.id not in to_delete]
        ir.jobs = [j for j in ir.jobs if j.id not in to_delete]
        ir.steps = [s for s in ir.steps if s.id not in to_delete]
        ir.interlocks = [x for x in ir.interlocks if x.id not in to_delete]
        ir.io_bindings = [b for b in ir.io_bindings if b.cm_id not in to_delete]
        ir.edges = [e for e in ir.edges if e.src_id not in to_delete and e.dst_id not in to_delete]
        ir.cm_mounts = {cm: hw for cm, hw in ir.cm_mounts.items() if cm not in to_delete}
        ir.var_bindings = [b for b in ir.var_bindings if str(b.get("target_id") or "") not in to_delete]
        return []

    if patch.op in ("rename_node", "relabel_node"):
        if not node_id:
            return [_nv("GF_EDGE_RULE_VIOLATION", f"{patch.op} 缺少 node_id")]
        entity: Any = None
        for coll in (ir.units, ir.ems, ir.cms, ir.control_nodes, ir.jobs, ir.steps, ir.modes, ir.interlocks):
            entity = next((x for x in coll if getattr(x, "id", None) == node_id), None)
            if entity is not None:
                break
        if entity is None:
            logical = next((n for n in ir.hw_nodes if str(n.get("id") or "") == node_id), None)
            if isinstance(logical, dict):
                if patch.op == "rename_node":
                    logical["label"] = str(patch.name or logical.get("label") or "")
                else:
                    logical["label"] = str(patch.label or logical.get("label") or "")
                return []
            return [_nv("GF_EDGE_RULE_VIOLATION", f"待编辑节点 {node_id!r} 不存在", node_id)]
        if patch.op == "rename_node":
            value = str(patch.name or "").strip()
            if not value:
                return [_nv("GF_EDGE_RULE_VIOLATION", "rename_node 需要非空 name", node_id)]
            if not hasattr(entity, "name"):
                return [_nv("GF_EDGE_RULE_VIOLATION", f"节点 {node_id} 无 name 字段", node_id)]
            entity.name = value
        else:
            value = str(patch.label or "")
            if not hasattr(entity, "business_label"):
                return [_nv("GF_EDGE_RULE_VIOLATION", f"节点 {node_id} 无 business_label 字段", node_id)]
            entity.business_label = value
        return []

    if patch.op == "reparent_node":
        if not node_id or not str(patch.parent_id or "").strip():
            return [_nv("GF_EDGE_RULE_VIOLATION", "reparent_node 需要 node_id 与 parent_id")]
        new_parent = str(patch.parent_id).strip()
        em = next((e for e in ir.ems if e.id == node_id), None)
        cm = next((c for c in ir.cms if c.id == node_id), None)
        if em is not None:
            if new_parent not in {u.id for u in ir.units}:
                return [_nv("GF_EDGE_RULE_VIOLATION", f"目标父工站 {new_parent!r} 不存在", node_id)]
            em.unit_id = new_parent
            _sync_parent_edge(ir, node_id, new_parent, EdgeKind.E_HIER_UNIT_EM)
        elif cm is not None:
            if new_parent not in {e.id for e in ir.ems}:
                return [_nv("GF_EDGE_RULE_VIOLATION", f"目标父执行单元 {new_parent!r} 不存在", node_id)]
            cm.em_id = new_parent
            _sync_parent_edge(ir, node_id, new_parent, EdgeKind.E_HIER_EM_CM)
        else:
            return [_nv("GF_EDGE_RULE_VIOLATION",
                        "reparent_node 仅支持执行单元（换工站）或执行件（换执行单元）", node_id)]
        return []

    return [_nv("GF_EDGE_RULE_VIOLATION", f"未知节点编辑 op：{patch.op}")]


def _restore_step_binding(ir: GreenfieldIR, entry: dict[str, Any]) -> None:
    """按绑定记录还原步序字段（仅当当前值仍是绑定写入的符号时才还原，保留撤销语义）。"""
    step = next((s for s in ir.steps if s.id == str(entry.get("target_id") or "")), None)
    if step is None:
        return
    written_cond = entry.get("written_transition_condition")
    if written_cond and step.transition_condition == written_cond:
        step.transition_condition = str(entry.get("prev_transition_condition") or "")
    appended = entry.get("appended_action")
    if appended and appended in step.actions:
        step.actions = [a for a in step.actions if a != appended]


def _apply_hw_op(ir: GreenfieldIR, patch: IRPatch) -> list[EdgeViolation]:
    """逻辑拓扑与变量绑定 op（D4）。真值全部写入 IR，替代 session.custom_hw 平行状态。"""
    p = dict(patch.payload or {})
    op = patch.op

    if op == "mount_cm":
        cm_id = str(p.get("cm_id") or patch.node_id or "").strip()
        hw_id = str(p.get("hw_node_id") or "").strip()
        if not cm_id or not hw_id:
            return [_nv("GF_HW_OP_INVALID", "mount_cm 需要 cm_id 与 hw_node_id", cm_id)]
        ir.cm_mounts[cm_id] = hw_id
        return []

    if op == "unmount_cm":
        cm_id = str(p.get("cm_id") or patch.node_id or "").strip()
        ir.cm_mounts.pop(cm_id, None)
        return []

    if op == "bind_var":
        var_key = str(p.get("var_key") or "").strip()
        target_id = str(p.get("target_id") or patch.node_id or "").strip()
        role = str(p.get("role") or "auto")
        if not var_key or not target_id:
            return [_nv("GF_HW_OP_INVALID", "bind_var 需要 var_key 与 target_id", target_id)]
        if any(b.get("var_key") == var_key and b.get("target_id") == target_id for b in ir.var_bindings):
            return []
        entry: dict[str, Any] = {"var_key": var_key, "target_id": target_id, "role": role}
        step = next((s for s in ir.steps if s.id == target_id), None)
        if step is not None:
            short_sym = var_key.split(":", 1)[-1]
            entry["prev_transition_condition"] = step.transition_condition
            entry["prev_actions"] = list(step.actions)
            if role == "condition" or "%I" in var_key or "Ack" in var_key or "Recv" in var_key:
                step.transition_condition = short_sym
                entry["written_transition_condition"] = short_sym
            elif short_sym not in step.actions:
                step.actions.append(short_sym)
                entry["appended_action"] = short_sym
        ir.var_bindings.append(entry)
        return []

    if op == "unbind_var":
        var_key = str(p.get("var_key") or "").strip()
        target_id = str(p.get("target_id") or patch.node_id or "").strip()
        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for b in ir.var_bindings:
            if var_key and b.get("var_key") == var_key and (not target_id or b.get("target_id") == target_id):
                removed.append(b)
            else:
                kept.append(b)
        ir.var_bindings = kept
        for entry in removed:
            _restore_step_binding(ir, entry)
        return []

    if op == "add_hw_node":
        raw = patch.node if isinstance(patch.node, dict) else (
            p.get("node") if isinstance(p.get("node"), dict) else {}
        )
        if not str(raw.get("id") or "").strip():
            return [_nv("GF_HW_OP_INVALID", "add_hw_node 需要带 id 的 node")]
        from plc_engine.af.hw_topology import normalize_logical_node

        logical = normalize_logical_node(raw)
        ir.hw_nodes = [n for n in ir.hw_nodes if str(n.get("id") or "") != logical["id"]]
        ir.hw_nodes.append(logical)
        return []

    if op == "remove_hw_node":
        hw_id = str(p.get("hw_node_id") or patch.node_id or "").strip()
        if not hw_id:
            return [_nv("GF_HW_OP_INVALID", "remove_hw_node 需要 hw_node_id")]
        ir.hw_nodes = [n for n in ir.hw_nodes if str(n.get("id") or "") != hw_id]
        ir.cm_mounts = {cm: hw for cm, hw in ir.cm_mounts.items() if hw != hw_id}
        ir.hw_links = [
            l for l in ir.hw_links
            if hw_id not in (str(l.get("src_hw_id") or ""), str(l.get("dst_hw_id") or ""))
        ]
        return []

    if op == "reset_topology":
        for entry in list(ir.var_bindings):
            _restore_step_binding(ir, entry)
        ir.cm_mounts = {}
        ir.hw_nodes = []
        ir.hw_links = []
        ir.var_bindings = []
        return []

    return [_nv("GF_HW_OP_UNKNOWN", f"未知硬件/拓扑 op：{op}")]


# ---------------------------------------------------------------------------
# 统一受控写入口 CanvasPatch（§2.2）
# ---------------------------------------------------------------------------

def _normalize_canvas_patch(patch: Any) -> CanvasPatch | None:
    """把 dict / 单个 IRPatch / op 列表归一为 CanvasPatch。"""
    if isinstance(patch, CanvasPatch):
        return patch
    if isinstance(patch, dict):
        return CanvasPatch.from_dict(patch)
    if isinstance(patch, IRPatch):
        return CanvasPatch(ops=[patch])
    if isinstance(patch, (list, tuple)):
        ops = [IRPatch.from_dict(x) if isinstance(x, dict) else x for x in patch]
        return CanvasPatch(ops=[o for o in ops if isinstance(o, IRPatch)])
    return None


def _op_target(op: IRPatch) -> str:
    """变更事件里对单个 op 的可读定位。"""
    if op.op == "add_edge" and op.edge is not None:
        return f"{op.edge.kind_value()} {op.edge.src_id} -> {op.edge.dst_id}"
    if op.op in ("remove_edge", "redirect_edge"):
        return str(op.edge_id or "")
    if op.op == "set_ir_only_field":
        return str(op.field_path or "")
    p = dict(op.payload or {})
    return str(
        op.node_id or op.name
        or p.get("cm_id") or p.get("hw_node_id") or p.get("var_key")
        or (op.node or {}).get("id") or op.op
    )


def _stage_value(session: Any) -> str:
    stage = getattr(session, "stage", "")
    return stage.value if hasattr(stage, "value") else str(stage)


def apply_canvas_patch(
    session: Any,
    patch: Any,
    *,
    gate_action: str | None = None,
    advance_stage: bool = False,
) -> PatchResult:
    """统一受控写入口（§2.2）：chat_turn / /links / /hardware / /patch 全部收敛于此。

    会话 IR **只能通过本函数修改**；任一 op 非法则整批回滚（IR 字节不变），
    ``validate_ir`` 通过且四视图重投影一致才提交，并提交变更事件入账。
    ``chat_turn`` 因走同一底层 ``apply_patch`` 白名单（其源不属本工作包）亦受同一机制约束。
    """
    cp = _normalize_canvas_patch(patch)
    stage_value = _stage_value(session)
    if cp is None:
        return PatchResult(ok=False, reason="不支持的 patch 类型", stage=stage_value)

    if gate_action:
        session.assert_gate(gate_action)

    if getattr(session, "ir", None) is None:
        return PatchResult(ok=False, reason="尚无首版规格（IR 未就绪）", stage=stage_value)

    ir = session.ir
    before = ir.ir_sha256()

    # 绕过 patch 直写检测：调用方可带上一次合法状态的 ir_sha256（乐观并发）。
    if cp.expected_ir_sha256 and cp.expected_ir_sha256 != before:
        return PatchResult(
            ok=False, ir_sha256=before, spec_hash=ir.spec_hash(), stage=stage_value,
            reason="IR 指纹漂移：检测到绕过 patch 的直接写入",
        )

    # project_id 一等公民绑定
    if cp.project_id:
        bound = str(getattr(session, "project_id", "") or "")
        if bound and bound != cp.project_id:
            return PatchResult(
                ok=False, ir_sha256=before, spec_hash=ir.spec_hash(), stage=stage_value,
                reason=f"project_id 冲突：会话已绑定 {bound}，请求 {cp.project_id}",
            )

    candidate = GreenfieldIR.from_dict(ir.to_dict())
    if cp.project_id:
        candidate.project_id = cp.project_id

    violations: list[dict[str, Any]] = []
    applied = 0
    for op in cp.ops:
        report = apply_patch(candidate, op)
        if not report.ok:
            violations.extend(v.to_dict() for v in report.violations)
            return PatchResult(
                ok=False, violations=violations, ir_sha256=before, spec_hash=ir.spec_hash(),
                stage=stage_value, applied_ops=applied,
                reason="任一 op 非法，整批回滚（IR 未改动）",
            )
        applied += 1

    # 契约：validate_ir 通过才提交
    final_report = validate_ir(candidate)
    if not final_report.ok:
        violations.extend(v.to_dict() for v in final_report.violations)
        return PatchResult(
            ok=False, violations=violations, ir_sha256=before, spec_hash=ir.spec_hash(),
            stage=stage_value, applied_ops=applied,
            reason="validate_ir 未通过，整批回滚",
        )

    # 四视图重投影同步（D6 节点编辑后必须一致）
    try:
        new_views = project_views(candidate)
        assert_roundtrip(candidate, new_views)
    except Exception as exc:  # noqa: BLE001 - 投影不一致一律原子拒绝
        return PatchResult(
            ok=False, ir_sha256=before, spec_hash=ir.spec_hash(), stage=stage_value,
            applied_ops=applied, reason=f"四视图重投影不一致：{exc}",
        )

    # 唯一写入点：整体替换字段（不直接赋值 session.ir.<attr>）
    session.ir._replace_from(candidate)
    session.views = new_views
    session.report = validate_ir(session.ir)
    if cp.project_id and not str(getattr(session, "project_id", "") or ""):
        session.project_id = cp.project_id
    if advance_stage and session.stage is GreenfieldStage.LINKABLE:
        session.transition_stage(GreenfieldStage.VALIDATING)

    # 变更事件入账（结构化账本；对话消息由各写入口按原文案追加）
    events: list[dict[str, Any]] = [
        {"op": op.op, "target": _op_target(op), "ts": _now_iso()} for op in cp.ops
    ]
    bucket = getattr(session, "change_events", None)
    if isinstance(bucket, list):
        bucket.extend(events)

    return PatchResult(
        ok=True, violations=[], ir_sha256=session.ir.ir_sha256(),
        spec_hash=session.ir.spec_hash(), stage=_stage_value(session),
        applied_ops=applied, change_events=events, ir=session.ir.to_dict(),
    )


def assert_edge_accepted(edge: GFEdge, ir: GreenfieldIR) -> None:
    """前端乐观校验的可抛异常版本；后端仍以 ``apply_patch`` 为唯一裁定。

    Raises:
        EdgeRejectedError: 任一条违规（携带首条违规的完整定位信息）。
    """
    violations = validate_edge(edge, ir)
    if violations:
        first = violations[0]
        raise EdgeRejectedError(
            first.message,
            code=first.code,
            details=first.to_dict(),
        )
