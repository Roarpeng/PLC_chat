"""Greenfield 业务编排（T05）：上传 → 冻结契约 → 首版 IR → 连线 → 校验 → 确认。

**范围铁律**：本模块不含任何生成标准工程 / SCL / XML / TIA 回写代码。
``DeliveryPort`` 只在 ``greenfield_ports.py`` 以 Protocol 形式预留（Q7）。
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from gateway.app.services.plc.greenfield_session import GreenfieldSession, registry
from gateway.app.services.plc.greenfield_upload import (
    LIMITS,
    UPLOAD_ERROR_CODES,
    UploadItem,
    parse_upload_batch,
)
from plc_engine.af.greenfield_contract import (
    IoEntry,
    DbStruct,
    ObEntry,
    SafetyEntry,
    SymbolEntry,
    CompatContract,
    confirm_receipt,
    freeze_contract,
)
from plc_engine.af.greenfield_edges import (
    ALLOWED_EDGES,
    ILLEGAL_EDGE_CATALOG,
    PACKML_STATES,
    PLCOPEN_SIGNALS,
    EdgeKind,
)
from plc_engine.af.greenfield_ir import (
    GFEdge,
    IRPatch,
    build_sample_ir,
)
from plc_engine.af.greenfield_ports import (
    FORBIDDEN_PREGATE_ACTIONS,
    LOCKED_HINT,
    STAGE_BADGES,
    GateLockedError,
    GreenfieldStage,
)
from plc_engine.af.greenfield_spec import (
    export_md,
    freeze,
    load_spec,
    next_version,
    spec_path,
    write_spec,
)
from plc_engine.af.greenfield_validator import apply_patch, validate_ir
from plc_engine.af.greenfield_views import (
    assert_roundtrip,
    project_views,
    render_export_md,
    render_step_flowchart,
)
from plc_engine.af.greenfield_delivery import AfGreenfieldDelivery
from plc_engine.af.hw_topology import derive_hardware_topology
from plc_engine.af.planner import plan_af_project_from_spec


def _work_dir() -> Path:
    return Path(os.environ.get("PLC_WORK_DIR") or tempfile.gettempdir())


def _to_upload_item(raw: dict[str, Any]) -> UploadItem:
    data = b""
    content = raw.get("content_base64") or ""
    if content:
        try:
            data = base64.b64decode(content, validate=True)
        except Exception as exc:  # noqa: BLE001 - 转为业务错误
            raise GateLockedError(
                f"上传内容不是合法 base64：{raw.get('filename', '')}",
                code="GF_UPLOAD_BASE64_INVALID",
            ) from exc
    return UploadItem(
        filename=str(raw.get("filename") or ""),
        data=data,
        text=str(raw.get("text") or ""),
        kind=str(raw.get("kind") or ""),
    )


def upload(session: GreenfieldSession, items: list[dict[str, Any]]) -> dict[str, Any]:
    """A2 对话上传：fail-closed 整批原子拒绝 + 明细回执；不写盘。"""
    session.assert_gate("upload")
    receipt = parse_upload_batch([_to_upload_item(x) for x in items])
    session.receipt = receipt
    session.contract = None
    session.add_message(
        "event",
        "receipt",
        f"上传 {len(items)} 个文件：{'解析成功' if receipt.status == 'parsed' else '整批拒绝'}"
        f"（共 {receipt.items_total} 条目）",
        {
            "receipt_id": receipt.receipt_id,
            "status": receipt.status,
            "items_total": receipt.items_total,
        },
    )
    return receipt.to_dict()


def confirm_receipt_action(session: GreenfieldSession, by: str = "user") -> dict[str, Any]:
    """Q3：解析回执必须用户确认后才冻结兼容契约。"""
    session.assert_gate("receipt_confirm")
    if session.receipt is None or session.receipt.status != "parsed":
        raise GateLockedError(
            "没有可确认的解析回执（批次被整批拒绝或尚未上传）",
            code="GF_UPLOAD_BATCH_REJECTED",
        )
    session.receipt = confirm_receipt(session.receipt, by=by)
    session.contract = freeze_contract(session.receipt)
    session.notes.append(f"兼容契约已冻结：{session.contract.contract_id}")
    session.add_message(
        "event",
        "contract",
        f"兼容契约已冻结（IO {len(session.contract.io_entries)} 条 / DB {len(session.contract.db_structs)} 个），灰锁只读",
        {"contract_id": session.contract.contract_id, "immutable": True},
    )
    return session.contract.to_dict()


def _contract_from_dict(payload: dict[str, Any]) -> CompatContract:
    """从 draft 还原契约实体（导入草稿路径复用）。"""
    return CompatContract(
        receipt_id=str(payload.get("receipt_id") or ""),
        frozen_at=str(payload.get("frozen_at") or ""),
        io_entries=[IoEntry.from_dict(x) for x in (payload.get("io_entries") or [])],
        db_structs=[DbStruct.from_dict(x) for x in (payload.get("db_structs") or [])],
        ob_entries=[ObEntry.from_dict(x) for x in (payload.get("ob_entries") or [])],
        safety_entries=[SafetyEntry.from_dict(x) for x in (payload.get("safety_entries") or [])],
        symbols=[SymbolEntry.from_dict(x) for x in (payload.get("symbols") or [])],
        compat_notes=list(payload.get("compat_notes") or []),
    )


def draft_from_prompt(
    session: GreenfieldSession, prompt: str = "", project_name: str = "AssemblyCell"
) -> dict[str, Any]:
    """A3 自然语言 → 首版 IR（Q2 确定性 planner，零 LLM 依赖）。

    prompt 为空时用 ``build_sample_ir()`` 产出与 ``03-first-mermaid.md``
    完全一致的基准首版，供用户直接手动连线。
    """
    if session.stage is GreenfieldStage.LINKABLE:
        session.transition_stage(GreenfieldStage.DRAFT)
    session.assert_gate("draft")
    if prompt.strip():
        try:
            af_project = plan_af_project_from_spec(prompt, project_name=project_name)
            ir = type(build_sample_ir()).from_af_project(
                af_project, prompt=prompt, contract=session.contract
            )
            if not ir.units:
                raise ValueError("planner 未产出任何单元")
        except Exception:  # noqa: BLE001 - 确定性规划失败时诚实回退并标注
            ir = build_sample_ir()
            session.notes.append("描述未能结构化解析，已回退到示例首版骨架，请手动连线调整")
    else:
        ir = build_sample_ir()
    session.ir = ir
    session.views = project_views(ir)
    assert_roundtrip(ir, session.views)
    session.report = validate_ir(ir)
    session.transition_stage(GreenfieldStage.LINKABLE)
    session.add_message(
        "event",
        "views",
        f"首版规格已生成：{len(ir.units)} 工位 / {len(ir.ems)} 工序 / {len(ir.cms)} 设备 / {len(ir.steps)} 步序；"
        "可在画布连线，或直接对话修改",
        {"units": len(ir.units), "ems": len(ir.ems), "cms": len(ir.cms), "steps": len(ir.steps)},
    )
    return state_payload(session)


def apply_link_patch(session: GreenfieldSession, payload: dict[str, Any]) -> dict[str, Any]:
    """A4 手动连线：编辑 IR.edges（不是 Mermaid 文本），非法 patch 原子拒绝。"""
    session.assert_gate("link")
    if session.ir is None:
        raise GateLockedError("尚无首版规格，请先生成", code="GF_GATE_LOCKED")
    edge_data = payload.get("edge")
    edge = GFEdge.from_dict(dict(edge_data)) if edge_data else None
    patch = IRPatch(
        op=str(payload.get("op") or "add_edge"),
        edge=edge,
        edge_id=payload.get("edge_id"),
        src_id=str(payload.get("src_id") or ""),
        dst_id=str(payload.get("dst_id") or ""),
        field_path=str(payload.get("field_path") or ""),
        value=payload.get("value"),
    )
    before = session.ir.ir_sha256()
    report = apply_patch(session.ir, patch)
    session.report = report
    if not report.ok:
        assert session.ir.ir_sha256() == before, "非法 patch 不得改动 IR"
    session.views = project_views(session.ir)
    if session.stage is GreenfieldStage.LINKABLE:
        session.transition_stage(GreenfieldStage.VALIDATING)
    if patch.op == "add_edge" and patch.edge is not None:
        target_desc = f"{patch.edge.kind} {patch.edge.src_id} → {patch.edge.dst_id}"
    elif patch.op == "remove_edge":
        target_desc = str(patch.edge_id or "")
    elif patch.op == "redirect_edge":
        target_desc = f"{patch.edge_id} 改为 {patch.src_id} → {patch.dst_id}"
    else:
        target_desc = str(patch.field_path or "")
    verdict = "校验通过" if report.ok else f"被拦截：{report.violations[0].message if report.violations else '非法 patch'}"
    session.add_message(
        "event",
        "edit",
        f"画布编辑（{patch.op}）：{target_desc}（{verdict}）",
        {
            "op": patch.op,
            "ok": report.ok,
            "violations": [v.to_dict() for v in report.violations][:5],
        },
    )
    return state_payload(session)


def revalidate(session: GreenfieldSession) -> dict[str, Any]:
    session.assert_gate("validate")
    if session.ir is None:
        raise GateLockedError("尚无首版规格，请先生成", code="GF_GATE_LOCKED")
    session.report = validate_ir(session.ir)
    session.views = project_views(session.ir)
    if session.stage is GreenfieldStage.LINKABLE:
        session.transition_stage(GreenfieldStage.VALIDATING)
    return state_payload(session)


def get_views(session: GreenfieldSession) -> dict[str, Any]:
    session.assert_gate("views")
    if session.ir is None:
        return {"flow": "", "seq": "", "state": "", "node_ids": {}}
    views = session.views or project_views(session.ir)
    session.views = views
    return {
        "flow": views.flow.mermaid,
        "seq": views.seq.mermaid,
        "state": views.state.mermaid,
        "step_flow": render_step_flowchart(session.ir),
        "node_ids": {
            "flow": list(views.flow.node_ids),
            "seq": list(views.seq.node_ids),
            "state": list(views.state.node_ids),
        },
        "edge_ids": {
            "flow": list(views.flow.edge_ids),
            "seq": list(views.seq.edge_ids),
            "state": list(views.state.edge_ids),
        },
    }


def whitelist_payload() -> dict[str, Any]:
    """连线白名单与 IR-only 字段目录，供右侧面板展示（R5 / §3.6.4）。"""
    legal = []
    for key, rule in ALLOWED_EDGES.items():
        legal.append(
            {
                "kind": key,
                "src_kinds": list(getattr(rule, "src_kinds", []) or []),
                "dst_kinds": list(getattr(rule, "dst_kinds", []) or []),
                "views": list(getattr(rule, "views", []) or []),
                "note": str(getattr(rule, "note", "") or ""),
            }
        )
    illegal = []
    for code, rule in ILLEGAL_EDGE_CATALOG.items():
        illegal.append({"code": code, "reason": str(getattr(rule, "reason", "") or "")})
    return {
        "legal_edges": legal,
        "illegal_edges": illegal,
        "edge_kinds": [e.value for e in EdgeKind],
        "packml_states": list(PACKML_STATES),
        "plcopen_signals": list(PLCOPEN_SIGNALS),
        "limits": dict(LIMITS),
        "upload_error_codes": sorted(UPLOAD_ERROR_CODES),
        "forbidden_pregate_actions": sorted(FORBIDDEN_PREGATE_ACTIONS),
        "locked_hint": LOCKED_HINT,
    }


def engineering_summary(session: GreenfieldSession) -> dict[str, Any]:
    """Q9 确认弹窗强制展示一次工程视角摘要；调用即标记已展示（纯 UI 态，不进哈希）。"""
    ir = session.ir
    summary = {
        "units": len(ir.units) if ir else 0,
        "ems": len(ir.ems) if ir else 0,
        "cms": len(ir.cms) if ir else 0,
        "control_nodes": len(ir.control_nodes) if ir else 0,
        "steps": len(ir.steps) if ir else 0,
        "edges": len(ir.edges) if ir else 0,
        "af_profile": ir.project.af_profile if ir else "",
        "namespace_prefixes": sorted({e.namespace_prefix for e in ir.ems}) if ir else [],
        "packml_states": list(PACKML_STATES),
        "ir_only_fields": ir.ir_only_catalog() if ir else [],
        "contract_sha": session.contract.contract_sha if session.contract else "",
        "note": "确认后仅冻结规格；生成标准工程与 TIA V19 回写零错误属下一阶段。",
    }
    session.engineering_summary_shown = True
    return summary


def confirm_and_freeze(
    session: GreenfieldSession,
    *,
    explicit: bool,
    base_dir: Path | None = None,
    frozen_by: str = "user",
) -> dict[str, Any]:
    """A9 确认硬门禁 → 冻结 spec（Phase 1 唯一合法副作用）。

    前置：阶段 VALIDATING、report.ok、回执已确认、工程视角摘要已展示、显式点击。
    确认前 ``assert_no_side_effects()`` 三计数必须为 0。
    """
    # LINKABLE 直接确认（未连线/未手动校验）时先自动做一次全量校验推进到
    # VALIDATING——确认动作本身触发校验，不放宽门禁矩阵，仍须用户显式点击。
    if session.stage is GreenfieldStage.LINKABLE:
        revalidate(session)
    session.assert_gate("confirm", explicit=explicit)
    session.assert_no_side_effects()
    if session.ir is None or session.views is None:
        raise GateLockedError("规格与三视图尚未就绪", code="GF_GATE_LOCKED")
    # 版本号取「内存 ∪ 磁盘」最大：网关重启后同一 session_id 再确认时，
    # 内存 registry 已清但磁盘 specs/ 可能已有旧冻结版本，撞号会 SpecImmutableError。
    work_dir = base_dir or _work_dir()
    spec_dir = work_dir / "greenfield" / session.session_id / "specs"
    disk_max = 0
    if spec_dir.is_dir():
        for spec_file in spec_dir.glob("v*.json"):
            m = re.match(r"v(\d+)\.json$", spec_file.name)
            if m:
                disk_max = max(disk_max, int(m.group(1)))
    version, prev = next_version(session.specs)
    if disk_max >= version:
        version = disk_max + 1
    spec = freeze(
        session.ir,
        session.views,
        session.contract,
        session_id=session.session_id,
        spec_version=version,
        prev_spec_hash=prev,
        frozen_by=frozen_by,
    )
    # 先写盘后迁移阶段：写盘失败（如磁盘只读）时阶段不被污染，可重试。
    target = write_spec(spec, work_dir, session.session_id)
    session.transition_stage(GreenfieldStage.FROZEN)
    session.count("disk_writes")
    session.specs.append(spec)
    session.notes.append(f"规格 {spec.version_label} 已冻结：{spec.spec_hash}")
    session.add_message(
        "event",
        "freeze",
        f"规格 {spec.version_label} 已冻结：{spec.spec_hash}",
        {"spec_version": spec.spec_version, "spec_hash": spec.spec_hash, "path": str(target)},
    )
    return {"spec": spec.to_dict(), "path": str(target), "markdown": export_md(spec)}


def begin_edit(session: GreenfieldSession) -> dict[str, Any]:
    """冻结后再次编辑 → 生成 vN+1 草稿，旧版字节不变。"""
    session.assert_gate("begin_edit")
    session.transition_stage(GreenfieldStage.LINKABLE)
    session.engineering_summary_shown = False
    session.add_message("event", "edit", "已开启新版本草稿编辑（已冻结版本保持不变）")
    return state_payload(session)


def export_first_mermaid(session: GreenfieldSession) -> str:
    """AC-7 首版 / 当前版 Mermaid 导出留痕；校验未过也允许导出供连线（Q5）。"""
    session.assert_gate("export")
    ir = session.ir or build_sample_ir()
    views = session.views or project_views(ir)
    frozen_note = (
        f"当前阶段 {STAGE_BADGES.get(session.stage, session.stage.value)}；确认前禁止任何生成与写回"
        if session.stage is not GreenfieldStage.FROZEN
        else "规格已冻结；生成标准工程属下一阶段"
    )
    return render_export_md(ir, views, frozen_note=frozen_note)


def state_payload(session: GreenfieldSession) -> dict[str, Any]:
    """统一状态响应；附带 IR / 校验报告摘要 / 硬件拓扑 / 变量目录，供三区域画布联动。"""
    data = session.snapshot()
    data["ir"] = session.ir.to_dict() if session.ir else None
    data["views"] = get_views(session) if session.ir else None
    data["messages"] = [dict(m) for m in session.messages]
    data["hardware"] = derive_hardware_topology(session.ir, session.contract, session.custom_hw)
    data["summary"] = {
        "units": len(session.ir.units) if session.ir else 0,
        "ems": len(session.ir.ems) if session.ir else 0,
        "cms": len(session.ir.cms) if session.ir else 0,
        "steps": len(session.ir.steps) if session.ir else 0,
        "edges": len(session.ir.edges) if session.ir else 0,
    }
    data["ir_only_fields"] = session.ir.ir_only_catalog() if session.ir else []
    if session.last_delivery is not None:
        data["delivery_summary"] = {
            k: v for k, v in session.last_delivery.items() if k != "zip_bytes"
        }
    else:
        data["delivery_summary"] = None
    return data


def _restore_step_binding(session: GreenfieldSession, entry: dict[str, Any]) -> None:
    """按绑定记录还原步序字段。

    仅当当前值仍是绑定写入的符号时才还原，避免覆盖绑定之后的画布/对话编辑。
    """
    if session.ir is None:
        return
    target_id = str(entry.get("target_id") or "")
    step = next((s for s in session.ir.steps if s.id == target_id), None)
    if step is None:
        return
    written_cond = entry.get("written_transition_condition")
    if written_cond and step.transition_condition == written_cond:
        step.transition_condition = str(entry.get("prev_transition_condition") or "")
    appended = entry.get("appended_action")
    if appended and appended in step.actions:
        step.actions = [a for a in step.actions if a != appended]


def update_hardware(session: GreenfieldSession, payload: dict[str, Any]) -> dict[str, Any]:
    """硬件拓扑（逻辑级占位）与变量面板的交互绑定。

    硬件拓扑只是占位：具体物理组态在博途中完成，这里支持挂载/卸载、绑定/解绑
    （含步序字段还原）、增删手工节点，以及一键重置为自动推导拓扑（可撤销）。
    """
    session.assert_gate("hardware")
    op = str(payload.get("op") or "mount_cm")
    event_text = ""
    touched_steps = False
    if op == "mount_cm":
        cm_id = str(payload.get("cm_id") or "")
        hw_node_id = str(payload.get("hw_node_id") or "")
        if cm_id and hw_node_id:
            mounts = dict(session.custom_hw.get("cm_mounts") or {})
            mounts[cm_id] = hw_node_id
            session.custom_hw["cm_mounts"] = mounts
            event_text = f"硬件挂载：{cm_id} → {hw_node_id}"
    elif op == "unmount_cm":
        cm_id = str(payload.get("cm_id") or "")
        mounts = dict(session.custom_hw.get("cm_mounts") or {})
        if cm_id in mounts:
            del mounts[cm_id]
            session.custom_hw["cm_mounts"] = mounts
            event_text = f"硬件卸载：{cm_id}（回到自动推导挂载）"
    elif op == "bind_var":
        var_key = str(payload.get("var_key") or "")
        target_id = str(payload.get("target_id") or "")
        role = str(payload.get("role") or "auto")
        if var_key and target_id:
            bindings = list(session.custom_hw.get("var_bindings") or [])
            already = any(
                b.get("var_key") == var_key and b.get("target_id") == target_id for b in bindings
            )
            if not already:
                entry: dict[str, Any] = {"var_key": var_key, "target_id": target_id, "role": role}
                bindings.append(entry)
                session.custom_hw["var_bindings"] = bindings
                # 若绑定目标是 Step，同步写入步序动作或转换条件，使 Mermaid 实时联动；
                # 记录原值供解绑/重置还原（可撤销语义）。
                if session.ir is not None and session.stage in {
                    GreenfieldStage.LINKABLE,
                    GreenfieldStage.VALIDATING,
                }:
                    step = next((s for s in session.ir.steps if s.id == target_id), None)
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
                        touched_steps = True
                event_text = f"变量绑定：{var_key} → {target_id}（{role}）"
    elif op == "unbind_var":
        var_key = str(payload.get("var_key") or "")
        target_id = str(payload.get("target_id") or "")
        bindings = list(session.custom_hw.get("var_bindings") or [])
        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for b in bindings:
            if var_key and b.get("var_key") == var_key and (not target_id or b.get("target_id") == target_id):
                removed.append(b)
            else:
                kept.append(b)
        session.custom_hw["var_bindings"] = kept
        for entry in removed:
            _restore_step_binding(session, entry)
            touched_steps = touched_steps or any(
                k in entry for k in ("written_transition_condition", "appended_action")
            )
        if removed:
            event_text = f"变量解绑：{var_key or target_id}（步序字段已还原）"
    elif op == "add_hw_node":
        node = payload.get("node")
        if isinstance(node, dict) and node.get("id"):
            extra = list(session.custom_hw.get("extra_nodes") or [])
            extra = [n for n in extra if n.get("id") != node["id"]]
            extra.append(dict(node))
            session.custom_hw["extra_nodes"] = extra
            event_text = f"新增硬件节点：{node.get('id')}"
    elif op == "remove_hw_node":
        hw_node_id = str(payload.get("hw_node_id") or "")
        if hw_node_id:
            extra = [n for n in (session.custom_hw.get("extra_nodes") or []) if n.get("id") != hw_node_id]
            session.custom_hw["extra_nodes"] = extra
            mounts = {
                cm: hw
                for cm, hw in dict(session.custom_hw.get("cm_mounts") or {}).items()
                if hw != hw_node_id
            }
            session.custom_hw["cm_mounts"] = mounts
            event_text = f"移除硬件节点：{hw_node_id}（仅手工新增节点可删）"
    elif op == "reset_topology":
        # 撤销全部拓扑编辑：还原绑定写入的步序字段 → 清空三键 → 回到自动推导态
        for entry in list(session.custom_hw.get("var_bindings") or []):
            _restore_step_binding(session, entry)
            touched_steps = touched_steps or any(
                k in entry for k in ("written_transition_condition", "appended_action")
            )
        session.custom_hw["cm_mounts"] = {}
        session.custom_hw["extra_nodes"] = []
        session.custom_hw["var_bindings"] = []
        event_text = "硬件拓扑已重置为自动推导（撤销全部挂载 / 绑定 / 手工节点）"
    else:
        raise GateLockedError(f"未知硬件操作：{op}", code="GF_HW_OP_UNKNOWN")
    if event_text:
        session.add_message("event", "edit", event_text, {"op": op})
        if touched_steps and session.ir is not None:
            session.views = project_views(session.ir)
            session.report = validate_ir(session.ir)
    return state_payload(session)


def generate_project_package(session: GreenfieldSession) -> dict[str, Any]:
    """确认冻结后（``stage == FROZEN``）生成标准 AF V1.2 博途工程包并校验。"""
    session.assert_gate("generate")
    if not session.specs:
        raise GateLockedError("尚未生成冻结规格，无法生成博途工程包", code="GF_GATE_LOCKED")
    latest_spec = session.specs[-1]
    delivery = AfGreenfieldDelivery().deliver(
        latest_spec,
        contract=session.contract,
        custom_hw=session.custom_hw,
    )
    session.count("generations")
    session.last_delivery = delivery
    session.notes.append(
        f"已生成 AF V1.2 标准博途工程包：{delivery['zip_filename']} ({delivery['block_count']} blocks)"
    )
    session.add_message(
        "event",
        "delivery",
        f"博途工程包已生成：{delivery['zip_filename']}（{delivery['block_count']} blocks，"
        f"校验{'通过' if delivery.get('ok') else '未通过'}），可下载",
        {
            "zip_filename": delivery.get("zip_filename"),
            "block_count": delivery.get("block_count"),
            "ok": delivery.get("ok"),
        },
    )
    return {k: v for k, v in delivery.items() if k != "zip_bytes"}


def get_project_package_zip(session: GreenfieldSession) -> tuple[str, bytes]:
    """获取已生成的博途工程 `.zip` 字节流（若已冻结但尚未缓存则现场生成）。"""
    session.assert_gate("generate")
    if session.last_delivery is None:
        generate_project_package(session)
    assert session.last_delivery is not None
    return str(session.last_delivery["zip_filename"]), bytes(session.last_delivery["zip_bytes"])


def load_frozen_spec(session_id: str, version: int, base_dir: Path | None = None):
    """按版本号装载已冻结 spec 并复现哈希（AC-5）。"""
    from plc_engine.af.greenfield_spec import FrozenSpec

    placeholder = FrozenSpec(spec_version=version, session_id=session_id)
    return load_spec(spec_path(base_dir or _work_dir(), session_id, placeholder))


def load_reference_fixture(session: GreenfieldSession, prompt: str = "") -> dict[str, Any]:
    """一键载入内置参考实例（PLC_IO.pdf + KUKA_DATA.pdf + PC_DATA.pdf + 机器人视觉工位工艺逻辑）。

    全程内存解析与标准访问偏移核验，确认前零写盘/零副作用。
    """
    if session.stage in {GreenfieldStage.FROZEN, GreenfieldStage.VALIDATING}:
        # FROZEN/VALIDATING 均合法回到 LINKABLE，否则 upload 门禁会在 VALIDATING 拒绝
        session.transition_stage(GreenfieldStage.LINKABLE)
        session.engineering_summary_shown = False
    fixture_dir = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "greenfield" / "legacy_pdf"
    items: list[dict[str, Any]] = []
    for fname in ("PLC_IO.pdf", "KUKA_DATA.pdf", "PC_DATA.pdf"):
        fpath = fixture_dir / fname
        if fpath.exists():
            items.append(
                {
                    "filename": fname,
                    "content_base64": base64.b64encode(fpath.read_bytes()).decode("ascii"),
                    "kind": "pdf",
                }
            )
    if items:
        upload(session, items)
        confirm_receipt_action(session, by="user")
    default_prompt = (
        prompt.strip()
        or "视觉引导与KUKA机器人上下料涂胶打磨工位：上位机PC下发配方与视觉拍照完成信号，"
        "KUKA机器人执行上料抓取、涂胶作业、打磨加工与下料步序，气缸夹紧与真空吸盘配合，光幕或急停触发安全中止"
    )
    return draft_from_prompt(session, default_prompt, project_name="KukaVisionStation")


def session_for(session_id: str | None) -> GreenfieldSession:
    return registry.get(session_id)
