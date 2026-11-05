"""Greenfield 三视图确定性投影（§3.6 / §3.6.2 M1–M4）。

**单向真相**：IR 是唯一权威规格，三视图文本只是 ``project_views(ir)`` 的
返回值；**不存在「Mermaid 文本 → IR」的反向覆盖通道**（S2 / S4 / S5）。
外部粘贴的 Mermaid 只经 ``inspect_external_mermaid()`` 作草稿建议输入，
不可表达字段一律标 ``unresolved`` 进「待确认问题」，绝不整段反向写 IR。

三视图共享同一 ID 命名空间：节点 ID 直接取 IR 实体 ``id``，边 ID 直接取
``GFEdge.id``；``view_mask`` 决定一条 IR 边投影到哪几个视图，实现联动。
"""
from __future__ import annotations

import re
from typing import Any

from plc_engine.af.greenfield_edges import (
    ALL_VIEWS,
    BRANCH_TERMINAL_STATES,
    PACKML_STATES,
    VIEW_FLOW,
    VIEW_SEQ,
    VIEW_STATE,
    EdgeKind,
    NodeKind,
)
from plc_engine.af.greenfield_ir import (
    PROJECTION_VERSION,
    GFEdge,
    GFViewSnapshot,
    GFViews,
    GreenfieldIR,
)
from plc_engine.af.greenfield_ports import ViewProjectionError

#: 三视图文本里承载边 ID 集合的 Mermaid 行注释（不渲染，仅供结构层 roundtrip）。
EDGE_IDS_MARKER = "%% edge_ids:"
_FLOW_NODE_RE = re.compile(r"^\s{4}([A-Za-z0-9_]+)[\[\(]")
_SEQ_NODE_RE = re.compile(r"^\s*(?:participant|actor)\s+([A-Za-z0-9_]+)\s+as\b")
_STATE_NODE_RE = re.compile(r'^\s*state\s+"[^"]*"\s+as\s+([A-Za-z0-9_]+)')
_EDGE_IDS_RE = re.compile(r"^\s*%%\s*edge_ids:\s*(.*)$")

#: stateDiagram 初始展示的 14 态（Suspending/Suspended/Unsuspending 留 IR）。
DEFAULT_VISIBLE_STATES: tuple[str, ...] = (
    "Stopped", "Resetting", "Idle", "Starting", "Execute", "Holding", "Held",
    "Unholding", "Completing", "Completed", "Stopping", "Aborting", "Aborted", "Clearing",
)

#: 业务化状态名（R7：用户可见文案零 AF / 架构 / 软件单元 / Unit / EM / CM）。
STATE_LABELS: dict[str, str] = {
    "Stopped": "停机", "Resetting": "复位中", "Idle": "待机", "Starting": "启动中",
    "Execute": "执行", "Holding": "保持中", "Held": "已保持", "Unholding": "解除保持",
    "Completing": "完成中", "Completed": "已完成", "Stopping": "停止中",
    "Aborting": "中止中", "Aborted": "已中止", "Clearing": "清理中",
    "Suspending": "挂起中", "Suspended": "已挂起", "Unsuspending": "解除挂起",
}


def _safe_label(value: str) -> str:
    """清理 Mermaid 节点标签中的双引号 / 换行，保证语法可渲染。"""
    return str(value or "").replace('"', "'").replace("\n", " ").replace("\r", " ").strip()


def _tag(edge: GFEdge) -> str:
    """边标签后缀：系统骨架 / 建议边（与 03-first-mermaid.md 统一图例一致）。"""
    return "骨架" if edge.immutable else "建议"


def _edge_ids_line(ids: list[str]) -> str:
    """生成承载边 ID 集合的 Mermaid 注释行。"""
    return f"    {EDGE_IDS_MARKER} {','.join(sorted(ids))}"


def _build_flow(ir: GreenfieldIR) -> GFViewSnapshot:
    """flowchart TB：层级唯一父、数据流单向、控制节点中枢、只读契约边界。"""
    lines: list[str] = ["flowchart TB"]
    node_ids: list[str] = []

    def declare(node_id: str, shape: str, label: str) -> None:
        lines.append(f"    {node_id}{shape[0]}{_safe_label(label)}{shape[1]}")
        node_ids.append(node_id)

    for unit in ir.units:
        declare(unit.id, ('["', '"]'), f"{unit.id} {unit.business_label}<br/>{unit.name}")
    for em in ir.ems:
        declare(em.id, ('["', '"]'), f"{em.id} {em.business_label}<br/>{em.name}")
    for cn in ir.control_nodes:
        declare(cn.id, ('[["', '"]]'),
                f"{cn.id} 控制节点<br/>ControlNodes")
    for cm in ir.cms:
        declare(cm.id, ('["', '"]'), f"{cm.id} {cm.business_label}<br/>{cm.cm_type}")
    declare("DB_UNITS", ('[("', '")]'), "DB_UNITS 接口数据区<br/>只读契约引用")
    declare("IOMAP", ('["', '"]'), "IOMAP 信号适配层<br/>只读冻结契约边界")

    edge_ids: list[str] = []
    for edge in ir.edges:
        if VIEW_FLOW not in edge.view_mask:
            continue
        arrow = "-.->" if edge.kind_value() == EdgeKind.E_IO_READ.value else "-->"
        lines.append(
            f"    {edge.src_id} {arrow}|{edge.kind_value()} {_tag(edge)}| {edge.dst_id}"
        )
        edge_ids.append(edge.id)
    lines.append("")
    lines.append("    %% ===== 留给用户手动连线的位置（首版不预置，见 §4）=====")
    lines.append("    %% [留白 A] 跨工序联锁放行 · [留白 B] 手动点动 · [留白 C] 工序交接")
    lines.append(_edge_ids_line(edge_ids))
    return GFViewSnapshot(mermaid="\n".join(lines), node_ids=node_ids, edge_ids=edge_ids)


def _build_seq(ir: GreenfieldIR) -> GFViewSnapshot:
    """sequenceDiagram：步序、消息、``alt/else`` 异常分支、``opt`` 手动模式。"""
    index = ir.node_index()
    participant_ids: list[str] = ["OP"]
    for group in (ir.units, ir.ems, ir.control_nodes, ir.cms):
        for entity in group:
            if entity.id not in participant_ids:
                participant_ids.append(entity.id)
    seq_edges = [e for e in ir.edges if VIEW_SEQ in e.view_mask]
    for edge in seq_edges:
        for node_id in (edge.src_id, edge.dst_id):
            if node_id in index and index[node_id]["kind"] == NodeKind.PACKML_STATE.value:
                continue  # 状态节点由 Note 表达，不作时序参与方
            if node_id not in participant_ids and node_id in index:
                participant_ids.append(node_id)

    lines: list[str] = ["sequenceDiagram", "    autonumber"]
    lines.append("    actor OP as 操作员")
    for node_id in participant_ids[1:]:
        label = _safe_label(index.get(node_id, {}).get("label") or node_id)
        lines.append(f"    participant {node_id} as {label}")
    lines.append("")
    lines.append("    Note over OP: 以下消息均为建议边，可增删改向；异常分支需收敛到已定义异常态")

    for edge in seq_edges:
        kind = edge.kind_value()
        if kind == EdgeKind.E_BRANCH_ALT_OPT.value:
            lines.append(
                f"    Note over {edge.src_id}: 异常分支收敛到 {edge.dst_id}（建议）"
            )
            continue
        if edge.src_id not in participant_ids or edge.dst_id not in participant_ids:
            # 端点不在白名单参与方内：不产出消息行，仍计入 edge_ids 由校验器裁定。
            continue
        arrow = "-->>" if kind in {
            EdgeKind.E_CM_TO_CN.value, EdgeKind.E_SC_UP.value
        } else "->>"
        lines.append(f"    {edge.src_id}{arrow}{edge.dst_id}: {_safe_label(edge.label)}（建议）")

    normal_steps = [s for s in ir.steps if s.branch.get("kind") != "else"]
    abnormal_steps = [s for s in ir.steps if s.branch.get("kind") == "else"]
    primary_cn = next((cn.id for cn in ir.control_nodes), "OP")
    lines.append("    alt 正常路径（建议）")
    if normal_steps:
        for step in normal_steps:
            lines.append(
                f"        {step.em_id}->>{primary_cn}: {_safe_label(step.name)} 步序 {step.step_id}（建议）"
            )
    else:
        lines.append("        OP->>U1: 启动自动流程（建议）")
    lines.append("    else 压装超时或急停（建议·异常分支）")
    if abnormal_steps:
        for step in abnormal_steps:
            lines.append(
                f"        {step.em_id}-->>{primary_cn}: 异常上报 9xx 错误步 {step.step_id}（建议）"
            )
    else:
        lines.append("        OP-->>U1: 报警并请求复位（建议）")
    lines.append("    end")
    lines.append("    opt 手动模式（建议）")
    lines.append("        OP->>U1: 切换到手动模式（建议）")
    lines.append(f"        U1->>{primary_cn}: 开放点动 仅经控制节点（建议）")
    lines.append("    end")
    lines.append(f"    Note over {primary_cn}: 超时与联锁表达式为不上图字段，右侧校验面板可编辑")
    lines.append(_edge_ids_line([e.id for e in seq_edges]))
    return GFViewSnapshot(
        mermaid="\n".join(lines),
        node_ids=participant_ids,
        edge_ids=[e.id for e in seq_edges],
    )


def _build_state(ir: GreenfieldIR) -> GFViewSnapshot:
    """stateDiagram-v2：PackML 状态与合法迁移、模式切换。"""
    visible = list(DEFAULT_VISIBLE_STATES)
    state_edges = [e for e in ir.edges if VIEW_STATE in e.view_mask]
    for edge in state_edges:
        for node_id in (edge.src_id, edge.dst_id):
            if node_id in PACKML_STATES and node_id not in visible:
                visible.append(node_id)

    lines: list[str] = ["stateDiagram-v2", "    direction TB", ""]
    node_ids: list[str] = []
    for state in visible:
        label = f"{STATE_LABELS.get(state, state)} {state}"
        lines.append(f'    state "{_safe_label(label)}" as {state}')
        node_ids.append(state)
    for mode in ir.modes:
        label = f"{mode.business_label} {mode.packml_mode}"
        lines.append(f'    state "{_safe_label(label)}" as {mode.id}')
        node_ids.append(mode.id)
    lines.append("")
    lines.append("    [*] --> Stopped")
    lines.append("")

    for edge in state_edges:
        lines.append(
            f"    {edge.src_id} --> {edge.dst_id} : {_safe_label(edge.label)} {_tag(edge)}"
        )
    lines.append("")
    lines.append("    note right of Execute")
    lines.append("        自动模式下由状态机统一裁决命令；")
    lines.append("        手动模式仅开放点动。")
    lines.append("        完整迁移许可表、每模式使能位集、")
    lines.append("        超时与命名空间均属不上图字段，在右侧校验面板可见可编辑。")
    lines.append("    end note")
    lines.append(_edge_ids_line([e.id for e in state_edges]))
    return GFViewSnapshot(
        mermaid="\n".join(lines),
        node_ids=node_ids,
        edge_ids=[e.id for e in state_edges],
    )


def project_views(ir: GreenfieldIR, layout: dict[str, Any] | None = None) -> GFViews:
    """IR → 三视图确定性投影（纯函数，无副作用、不落盘）。"""
    return GFViews(
        flow=_build_flow(ir),
        seq=_build_seq(ir),
        state=_build_state(ir),
        shared_id_namespace=True,
        projection_version=PROJECTION_VERSION,
        layout=dict(layout or {}),
    )


def render_flow(ir: GreenfieldIR) -> str:
    """flowchart 文本（``project_views`` 的只读切片）。"""
    return project_views(ir).flow.mermaid


def render_sequence(ir: GreenfieldIR) -> str:
    """sequenceDiagram 文本（``project_views`` 的只读切片）。"""
    return project_views(ir).seq.mermaid


def render_state(ir: GreenfieldIR) -> str:
    """stateDiagram-v2 文本（``project_views`` 的只读切片）。"""
    return project_views(ir).state.mermaid


def _extract_ids(view: str, text: str) -> tuple[set[str], set[str]]:
    """只做**结构层** ID 提取，不用文本重建语义（M4 / S4 防线）。"""
    node_re = {
        VIEW_FLOW: _FLOW_NODE_RE,
        VIEW_SEQ: _SEQ_NODE_RE,
        VIEW_STATE: _STATE_NODE_RE,
    }[view]
    nodes: set[str] = set()
    edges: set[str] = set()
    for line in text.splitlines():
        node_match = node_re.match(line)
        if node_match:
            nodes.add(node_match.group(1))
        edge_match = _EDGE_IDS_RE.match(line)
        if edge_match:
            edges.update(part for part in edge_match.group(1).split(",") if part.strip())
    return nodes, edges


def assert_roundtrip(ir: GreenfieldIR, views: GFViews) -> None:
    """结构层 roundtrip 回归（§3.6.2 M4）：只比 ID 集合，冲突以 IR 裁定。

    Raises:
        ViewProjectionError: 文本 ↔ 快照 ↔ IR 任一 ID 集合不一致，或
            sequenceDiagram 无法被既有解析器解析（``alt/end`` 不配对等）。
    """
    index = ir.node_index()
    for view in ALL_VIEWS:
        snapshot = views.snapshot(view)
        text_nodes, text_edges = _extract_ids(view, snapshot.mermaid)
        snap_nodes, snap_edges = set(snapshot.node_ids), set(snapshot.edge_ids)
        if text_nodes != snap_nodes:
            raise ViewProjectionError(
                f"{view} 视图节点 ID 集合与快照不一致（文本 {sorted(text_nodes - snap_nodes)} / "
                f"快照 {sorted(snap_nodes - text_nodes)}）",
                details={"view": view},
            )
        if text_edges != snap_edges:
            raise ViewProjectionError(
                f"{view} 视图边 ID 集合与快照不一致",
                details={"view": view, "text_only": sorted(text_edges - snap_edges),
                         "snapshot_only": sorted(snap_edges - text_edges)},
            )
        ir_edges = {e.id for e in ir.edges if view in e.view_mask}
        if snap_edges != ir_edges:
            raise ViewProjectionError(
                f"{view} 视图边 ID 未与 IR.edges[view_mask] 对齐（三视图必须共享同一边 ID）",
                details={"view": view, "view_only": sorted(snap_edges - ir_edges),
                         "ir_only": sorted(ir_edges - snap_edges)},
            )
        unknown = snap_nodes - set(index)
        if unknown:
            raise ViewProjectionError(
                f"{view} 视图出现不在 IR 全局 ID 命名空间的节点：{sorted(unknown)}",
                details={"view": view},
            )

    # sequenceDiagram 额外交给既有解析器做语法可解析性校验（剥离 %% 注释行）。
    clean_seq = "\n".join(
        line for line in views.seq.mermaid.splitlines() if not line.strip().startswith("%%")
    )
    try:
        from plc_engine.af.mermaid_parser import MermaidParseError, parse_mermaid_sequence

        parsed = parse_mermaid_sequence(clean_seq)
    except Exception as exc:  # 含 MermaidParseError / 导入失败，一律 fail-closed
        raise ViewProjectionError(
            f"步序视图无法被既有解析器解析：{exc}",
            details={"view": VIEW_SEQ},
        ) from exc
    if not parsed.get("steps"):
        raise ViewProjectionError("步序视图没有任何消息步骤", details={"view": VIEW_SEQ})


def inspect_external_mermaid(text: str) -> dict[str, Any]:
    """S4：外部粘贴 Mermaid **只作草稿建议输入**，绝不反向覆盖 IR。

    Returns:
        ``{parseable, participants, steps, unresolved, applies_to_ir: False, note}``；
        ``unresolved`` 中的项必须进「待确认问题」，补齐前不得冻结。
    """
    result: dict[str, Any] = {
        "parseable": False,
        "participants": [],
        "steps": [],
        "unresolved": [],
        "applies_to_ir": False,
        "note": "外部图仅作建议输入；不可表达字段须补齐后才可进入确认，绝不整段反向覆盖规格",
    }
    clean = "\n".join(
        line for line in (text or "").splitlines() if not line.strip().startswith("%%")
    )
    try:
        from plc_engine.af.mermaid_parser import parse_mermaid_sequence

        parsed = parse_mermaid_sequence(clean)
    except Exception as exc:
        result["unresolved"].append(f"外部步序图结构校验失败：{exc}")
        return result
    result["parseable"] = True
    result["participants"] = list(parsed.get("participants") or [])
    result["steps"] = list(parsed.get("steps") or [])
    result["unresolved"].append("超时、联锁表达式、命名空间、五信号等不上图字段需人工补齐")
    return result


def render_export_md(
    ir: GreenfieldIR,
    views: GFViews | None = None,
    *,
    title: str = "Greenfield 首版三视图留痕",
    frozen_note: str = "",
) -> str:
    """导出 ``.md`` 留痕（AC-7）：三视图快照 + 不上图字段说明 + 冻结信息。"""
    snapshot = views if views is not None else project_views(ir)
    parts: list[str] = [
        f"# {title}",
        "",
        "> 权威规格是强类型 IR；本文是只读投影快照，不是规格真值。",
        "> 连线编辑作用于规格的边，三视图联动刷新；确认前零写盘 / 零写回 / 零生成。",
        "",
    ]
    if frozen_note:
        parts.extend([f"> {frozen_note}", ""])
    for view, heading in (
        (VIEW_FLOW, "视图一 · 层级与数据流"),
        (VIEW_SEQ, "视图二 · 步序与异常分支"),
        (VIEW_STATE, "视图三 · 模式状态与迁移"),
    ):
        parts.extend([f"## {heading}", "", "```mermaid", snapshot.snapshot(view).mermaid, "```", ""])
    parts.extend(
        [
            "## 只在上图之外保留的字段（右侧校验面板可见可编辑）",
            "",
        ]
    )
    for item in ir.ir_only_catalog():
        parts.append(
            f"- **{item['label']}**（{item['panel']} / "
            f"{'可编辑' if item['editable'] else '灰锁只读'}）：{item['note']}"
        )
    parts.extend(
        [
            "",
            "## 规格标识",
            "",
            f"- 规格版本：`{ir.spec_meta.spec_version}`",
            f"- 规格内容哈希：`{ir.spec_meta.spec_hash or '（尚未冻结）'}`",
            f"- 档位标识：`{ir.project.af_profile}`",
            f"- 规格模式版本：`{ir.ir_version}`",
            "",
        ]
    )
    return "\n".join(parts)
