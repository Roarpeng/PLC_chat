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
    IR_PATCH_OPS,
    GFEdge,
    GreenfieldIR,
    IRPatch,
)
from plc_engine.af.greenfield_ports import EdgeRejectedError


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
        if key not in {"actions", "transition_condition", "timeout_ms", "error_step_id", "branch"}:
            return reject(f"步序字段 {key} 不可编辑")
        if key in {"timeout_ms", "error_step_id"} and (not isinstance(value, int) or value < 0):
            return reject(f"{key} 必须是非负整数")
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
    if patch.op not in IR_PATCH_OPS:
        return ValidationReport(
            ok=False,
            violations=[
                _generic_violation("GF_EDGE_RULE_VIOLATION", "", GFEdge(),
                                   f"未知 patch 操作 {patch.op!r}，仅允许 {sorted(IR_PATCH_OPS)}")
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
    else:  # set_ir_only_field
        local_violations.extend(_set_ir_only_field(candidate, patch.field_path, patch.value))

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
