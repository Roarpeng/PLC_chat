"""Greenfield 业务编排（T05）：上传 → 冻结契约 → 首版 IR → 连线 → 校验 → 确认。

**范围铁律**：本模块不含任何生成标准工程 / SCL / XML / TIA 回写代码。
``DeliveryPort`` 只在 ``greenfield_ports.py`` 以 Protocol 形式预留（Q7）。
"""
from __future__ import annotations

import base64
import io
import os
import re
import tempfile
import zipfile
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
    HW_PATCH_OPS,
    CanvasPatch,
    GFEdge,
    GreenfieldIR,
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
from plc_engine.af.greenfield_validator import apply_canvas_patch, validate_ir
from plc_engine.af.spec_diff import compute_spec_diff
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
    """A4 手动连线：收敛到统一 ``apply_canvas_patch``（§2.2），非法整批原子拒绝。"""
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
    result = apply_canvas_patch(session, CanvasPatch(ops=[patch]), advance_stage=True)
    session.report = validate_ir(session.ir)
    if not result.ok:
        assert result.ir_sha256 == session.ir.ir_sha256(), "非法 patch 不得改动 IR"
    if patch.op == "add_edge" and patch.edge is not None:
        target_desc = f"{patch.edge.kind} {patch.edge.src_id} → {patch.edge.dst_id}"
    elif patch.op == "remove_edge":
        target_desc = str(patch.edge_id or "")
    elif patch.op == "redirect_edge":
        target_desc = f"{patch.edge_id} 改为 {patch.src_id} → {patch.dst_id}"
    else:
        target_desc = str(patch.field_path or "")
    first_msg = (
        (result.violations[0].get("message") if result.violations else result.reason)
        if not result.ok else ""
    )
    verdict = "校验通过" if result.ok else f"被拦截：{first_msg or '非法 patch'}"
    session.add_message(
        "event",
        "edit",
        f"画布编辑（{patch.op}）：{target_desc}（{verdict}）",
        {
            "op": patch.op,
            "ok": result.ok,
            "violations": result.violations[:5],
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


#: 确认五项前置 → 前端 ``GF_ERROR_TEXT`` 认识的具体错误码（契约 §3 收口接线）。
#: 服务端返回的 code 必须是前端可映射出具体中文原因的键，不能只有中文 reason。
_CONFIRM_CHECK_CODES: dict[str, str] = {
    "topology_finalized": "GF_TOPOLOGY_NOT_FINALIZED",
    "open_questions_cleared": "GF_OPEN_QUESTIONS_PENDING",
    "nodes_links_valid": "GF_NODE_EDGE_INVALID",
    "equivalence_precheck": "GF_EQUIVALENCE_PRECHECK_FAILED",
    "baseline_locked": "GF_BASELINE_NOT_LOCKED",
}


def check_confirm_prerequisites(session: GreenfieldSession) -> dict[str, Any]:
    """确认硬门禁前置（§3 / 任务 7）：逐项判定并返回**具体原因 + 具体 code**。

    五项：拓扑定稿 ∧ ``open_questions`` 清零 ∧ 节点/连线校验 ∧ 等价性预检 ∧
    基线版本锁定。纯只读：不写盘、不计副作用、不改阶段、不建事务。
    ``codes`` / ``code`` 供 ``/confirm`` 抛错时透传给前端 ``mapConfirmError``。
    """
    ir = session.ir
    if ir is None:
        return {
            "ok": False,
            "checks": {"ir_ready": False},
            "reasons": ["首版规格（IR）尚未生成"],
            "open_questions": [],
            "codes": ["GF_TOPOLOGY_NOT_FINALIZED"],
            "code": "GF_TOPOLOGY_NOT_FINALIZED",
        }

    checks: dict[str, bool] = {"ir_ready": True}
    reasons: list[str] = []

    # 1) 拓扑定稿
    checks["topology_finalized"] = bool(getattr(session, "topology_finalized", True))
    if not checks["topology_finalized"]:
        reasons.append("逻辑拓扑尚未定稿：请在画布上确认设备逻辑拓扑")

    # 2) open_questions 清零（含 inferred 来源联锁，复用 GFSpecMeta / report 机制）
    report = session.report or validate_ir(ir)
    questions = list(dict.fromkeys(
        list(report.open_questions) + list(ir.spec_meta.open_questions or [])
    ))
    checks["open_questions_cleared"] = not questions
    if questions:
        reasons.append(f"仍有 {len(questions)} 项待确认问题未清零：{questions[:3]}")

    # 3) 节点 / 连线校验
    checks["nodes_links_valid"] = bool(report.ok)
    if not report.ok:
        first = report.violations[0].message if report.violations else "未知校验违规"
        reasons.append(f"节点/连线校验未通过：{first}")

    # 4) 等价性预检（IR 内容哈希可复现 + 与校验报告一致）
    reproducible = GreenfieldIR.from_dict(ir.to_dict()).ir_sha256() == ir.ir_sha256()
    hash_match = bool(report.ir_sha256) and report.ir_sha256 == ir.ir_sha256()
    checks["equivalence_precheck"] = bool(reproducible and hash_match)
    if not checks["equivalence_precheck"]:
        reasons.append("等价性预检未通过：IR 内容哈希不可复现或与校验报告不一致")

    # 5) 基线版本锁定
    checks["baseline_locked"] = bool(str(ir.baseline_version or "").strip())
    if not checks["baseline_locked"]:
        reasons.append("框架基线版本未锁定（IR.baseline_version 为空）")

    failed_codes = [
        _CONFIRM_CHECK_CODES[key]
        for key in _CONFIRM_CHECK_CODES
        if checks.get(key) is False
    ]
    return {
        "ok": not reasons,
        "checks": checks,
        "reasons": reasons,
        "open_questions": questions,
        "codes": failed_codes,
        "code": failed_codes[0] if failed_codes else "",
    }


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
    # 硬门禁前置（§3 / 任务 7）：任一未满足即返回具体原因，按钮不可用（D 负责 UI）。
    prereq = check_confirm_prerequisites(session)
    if not prereq["ok"]:
        raise GateLockedError(
            "确认前置未满足：" + "；".join(prereq["reasons"]),
            code=prereq.get("code") or "GF_CONFIRM_PREREQUISITE",
            details={
                "checks": prereq["checks"],
                "reasons": prereq["reasons"],
                "codes": prereq.get("codes", []),
            },
        )
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
        project_id=(session.ir.project_id or str(getattr(session, "project_id", "") or "")),
        framework_baseline_version=session.ir.baseline_version,
    )
    # 落盘只发生在 FROZEN 之后、按版本落到 specs/vN.json（契约 §3 / 任务 7）。
    # 写盘失败则回退到 LINKABLE，保证阶段不被污染、可重试（fail-closed）。
    session.transition_stage(GreenfieldStage.FROZEN)
    try:
        target = write_spec(spec, work_dir, session.session_id)
    except Exception:
        session.transition_stage(GreenfieldStage.LINKABLE)
        raise
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
        delivery_summary = {
            k: v for k, v in session.last_delivery.items() if k != "zip_bytes"
        }
        # 前端读取的两个字段恒存在：无真实数据时给 null，不虚构通过状态。
        delivery_summary.setdefault("compile_diagnostics", None)
        delivery_summary.setdefault("scl_sources", None)
        data["delivery_summary"] = delivery_summary
    else:
        data["delivery_summary"] = None
    prereq = check_confirm_prerequisites(session)
    data["confirm_prerequisites"] = prereq

    # —— 收口接线：对齐前端 GFState 字段（增量追加，保留 A 已有字段）——
    # gate_checks 按前端 GFGateChecks 形状给：后端 nodes_links_valid → nodes_edges_valid。
    checks = prereq["checks"]
    data["gate_checks"] = {
        "ir_ready": bool(checks.get("ir_ready", False)),
        "topology_finalized": bool(checks.get("topology_finalized", False)),
        "open_questions_cleared": bool(checks.get("open_questions_cleared", False)),
        "nodes_edges_valid": bool(checks.get("nodes_links_valid", False)),
        "equivalence_precheck": bool(checks.get("equivalence_precheck", False)),
        "baseline_locked": bool(checks.get("baseline_locked", False)),
    }
    # diff_confirmed / framework_baseline_version 已由 session.snapshot() 提供。
    data["pending_real_machine"] = True
    data["spec_diff"] = None
    data["reverse_protection"] = None
    summary = data["delivery_summary"] or {}
    data["compile_diagnostics"] = summary.get("compile_diagnostics")
    data["scl_sources"] = summary.get("scl_sources")
    return data


def update_hardware(session: GreenfieldSession, payload: dict[str, Any]) -> dict[str, Any]:
    """硬件拓扑（逻辑级占位）与变量面板交互：全部收敛到统一 ``apply_canvas_patch``。

    逻辑拓扑真值写入 ``IR.hw_nodes / cm_mounts / var_bindings``；``bind_var`` 的
    撤销语义由 ``greenfield_validator`` 在候选副本上实现。本函数不再直接赋值
    ``session.ir.*``，也不再维护 ``custom_hw`` 平行状态（其仅为只读兼容视图）。
    """
    session.assert_gate("hardware")
    op = str(payload.get("op") or "mount_cm")
    if op not in HW_PATCH_OPS:
        raise GateLockedError(f"未知硬件操作：{op}", code="GF_HW_OP_UNKNOWN")

    cm_id = str(payload.get("cm_id") or "")
    hw_node_id = str(payload.get("hw_node_id") or "")
    var_key = str(payload.get("var_key") or "")
    target_id = str(payload.get("target_id") or "")
    role = str(payload.get("role") or "auto")
    node = payload.get("node") if isinstance(payload.get("node"), dict) else None

    patch_payload = {
        k: v for k, v in (
            ("cm_id", cm_id), ("hw_node_id", hw_node_id),
            ("var_key", var_key), ("target_id", target_id), ("role", role),
        ) if v
    }
    patch = IRPatch(op=op, node=node, payload=patch_payload)
    result = apply_canvas_patch(session, CanvasPatch(ops=[patch]))

    event_text_map = {
        "mount_cm": f"硬件挂载：{cm_id} → {hw_node_id}",
        "unmount_cm": f"硬件卸载：{cm_id}（回到自动推导挂载）",
        "bind_var": f"变量绑定：{var_key} → {target_id}（{role}）",
        "unbind_var": f"变量解绑：{var_key or target_id}（步序字段已还原）",
        "add_hw_node": f"新增硬件节点：{(node or {}).get('id')}",
        "remove_hw_node": f"移除硬件节点：{hw_node_id}（仅手工新增节点可删）",
        "reset_topology": "硬件拓扑已重置为自动推导（撤销全部挂载 / 绑定 / 手工节点）",
    }
    event_text = event_text_map.get(op, "")
    has_target = bool(cm_id or hw_node_id or var_key or target_id or node)
    if event_text and (has_target or op == "reset_topology"):
        session.add_message("event", "edit", event_text, {"op": op, "ok": result.ok})
    return state_payload(session)


def collect_scl_sources(delivery: dict[str, Any]) -> dict[str, str] | None:
    """只读 SCL 预览源（F13 降级）：从真实生成产物 ZIP 按 ``blocks_manifest`` 逐块读源码。

    键为块名、值为 ``.scl`` 全文，无任何写回入口。产物缺失 / ZIP 不可读 / 无
    SCL 块时返回 ``None``，**禁止虚构**内容或地址。
    """
    raw = delivery.get("zip_bytes")
    entries = delivery.get("blocks_manifest") or []
    if not raw or not entries:
        return None
    sources: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(bytes(raw))) as zf:
            for entry in entries:
                path = str(entry.get("path") or "")
                if not path.lower().endswith(".scl"):
                    continue
                try:
                    text = zf.read(path).decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    continue
                sources[str(entry.get("name") or path)] = text
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return sources or None


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
    # F13 降级：只读 SCL 预览源随交付摘要回流 /state，无产物时给 null（禁止虚构）。
    delivery["scl_sources"] = collect_scl_sources(delivery)
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


def load_frozen_spec(
    session_id: str,
    version: int,
    base_dir: Path | None = None,
    project_id: str = "",
):
    """按版本号装载已冻结 spec 并复现哈希（AC-5）；支持 ``project_id`` 归属校验。"""
    from plc_engine.af.greenfield_spec import FrozenSpec

    placeholder = FrozenSpec(spec_version=version, session_id=session_id)
    return load_spec(
        spec_path(base_dir or _work_dir(), session_id, placeholder),
        project_id=project_id,
    )


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


def session_for(session_id: str | None, project_id: str = "") -> GreenfieldSession:
    """取（或建）会话；传入 ``project_id`` 时绑定项目一等公民标识（§8）。"""
    session = registry.get(session_id)
    if project_id:
        bind_project_id(session, project_id)
    return session


def bind_project_id(session: GreenfieldSession, project_id: str) -> str:
    """把 ``project_id`` 绑定到会话（§8 一等公民）；重复绑定不一致则拒绝。

    只读绑定会话标识，不直接写 IR；``IR.project_id`` 由 ``/patch`` 或 ``freeze`` 落定。
    """
    pid = str(project_id or "").strip()
    if not pid:
        return session.project_id
    existing = str(getattr(session, "project_id", "") or "")
    if existing and existing != pid:
        raise GateLockedError(
            f"会话已绑定项目 {existing}，不能改绑 {pid}",
            code="GF_PROJECT_ID_CONFLICT",
        )
    session.project_id = pid
    return pid


def apply_patch_action(session: GreenfieldSession, payload: dict[str, Any]) -> dict[str, Any]:
    """POST /patch：统一受控写入（§2.2 / §3）。

    返回 ``PatchResult`` 形状 ``{ir, spec_hash, violations, stage, ...}``；原子
    拒绝时 router 以 422 返回，IR 字节不变。不触发存量链、不建 PCEC 事务。
    """
    session.assert_gate("link")
    if session.ir is None:
        raise GateLockedError("尚无首版规格，请先生成", code="GF_GATE_LOCKED")
    cp = CanvasPatch.from_dict(payload)
    result = apply_canvas_patch(
        session, cp, advance_stage=(session.stage is GreenfieldStage.LINKABLE)
    )
    session.report = validate_ir(session.ir)
    if result.ok:
        session.add_message(
            "event", "edit",
            f"受控 patch 已应用 {result.applied_ops} 项（spec_hash={result.spec_hash}）",
            {"ops": result.applied_ops, "spec_hash": result.spec_hash},
        )
    return result.to_dict()


def _spec_like(spec: Any) -> Any:
    """把 A 的 FrozenSpec 适配成契约 §2.3 SpecLike 的四个属性。

    FrozenSpec 用 ``spec_version``，协议要 ``version``；在此显式映射，避免依赖
    ``spec_version_of`` 的容错分支，保证形状与契约一致。
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        project_id=str(getattr(spec, "project_id", "") or ""),
        version=int(getattr(spec, "spec_version", 0) or 0),
        ir_snapshot=dict(getattr(spec, "ir_snapshot", {}) or {}),
        spec_hash=str(getattr(spec, "spec_hash", "") or ""),
    )


def _source_block_dict(block: Any) -> dict[str, Any]:
    return {
        "source_id": str(block.source_id),
        "kind": str(block.kind),
        "payload": dict(block.payload),
    }


def _empty_diff(base: int, target: int, note: str) -> dict[str, Any]:
    """优雅降级：空 diff + 明确说明，禁止臆造（无 placeholder 伪装）。"""
    return {
        "base_spec_version": base,
        "target_spec_version": target,
        "changed": [],
        "added": [],
        "removed": [],
        "changed_source_ids": [],
        "note": note,
    }


def diff_placeholder(session: GreenfieldSession, payload: dict[str, Any]) -> dict[str, Any]:
    """POST /diff：调用 B 的 ``compute_spec_diff`` 产出带 source_id 的真实 SpecDiff（§2.3）。

    用 ``load_frozen_spec`` 装载 base/target 两版 FrozenSpec，适配成 SpecLike 后计算
    changed / added / removed / changed_source_ids。版本缺失或任一版规格无法装载时
    优雅降级为空 diff + 明确说明，禁止臆造。零副作用、不触发存量链、不建 PCEC 事务。
    """
    try:
        from_version = int(payload.get("from_version") or 0)
        to_version = int(payload.get("to_version") or 0)
    except (TypeError, ValueError):
        return _empty_diff(0, 0, "版本号无法解析为整数，未计算差异（禁止臆造）")

    if from_version <= 0 or to_version <= 0:
        return _empty_diff(
            from_version, to_version,
            "缺少有效的两版版本号（from_version / to_version 须为正整数），未计算差异",
        )

    try:
        base_spec = load_frozen_spec(session.session_id, from_version)
        target_spec = load_frozen_spec(session.session_id, to_version)
    except Exception as exc:  # noqa: BLE001 - 规格缺失/哈希不符一律降级，不臆造
        return _empty_diff(
            from_version, to_version,
            f"无法装载 v{from_version} / v{to_version} 冻结规格，未计算差异：{exc}",
        )

    diff = compute_spec_diff(_spec_like(base_spec), _spec_like(target_spec))
    return {
        "base_spec_version": diff.base_spec_version,
        "target_spec_version": diff.target_spec_version,
        "changed": [_source_block_dict(b) for b in diff.changed],
        "added": [_source_block_dict(b) for b in diff.added],
        "removed": [_source_block_dict(b) for b in diff.removed],
        "changed_source_ids": list(diff.changed_source_ids),
    }


def confirm_diff_action(session: GreenfieldSession, payload: dict[str, Any]) -> dict[str, Any]:
    """POST /confirm-diff（D11）：``confirmed != true`` 时零副作用计数器恒 0。

    确认后才置 ``diff_confirmed`` 允许后续写入；本函数自身不增加任何
    ops / disk_writes / writebacks / generations，也不写盘、不建事务。
    """
    diff_id = str(payload.get("diff_id") or "")
    confirmed = payload.get("confirmed") is True
    before = dict(session.counters)
    if not confirmed:
        return {
            "confirmed": False,
            "diff_id": diff_id,
            "side_effect_counters": dict(session.counters),
            "zero_side_effects": dict(session.counters) == before,
            "write_allowed": False,
            "note": "差异清单未显式确认；ops/disk_writes/writebacks/generations 保持不变（确认前恒 0）",
        }
    session.diff_confirmed = True
    if diff_id and diff_id not in session.confirmed_diff_ids:
        session.confirmed_diff_ids.append(diff_id)
        session.add_message("event", "diff", f"差异清单 {diff_id} 已显式确认", {"diff_id": diff_id})
    return {
        "confirmed": True,
        "diff_id": diff_id,
        "side_effect_counters": dict(session.counters),
        "zero_side_effects": dict(session.counters) == before,
        "write_allowed": True,
    }
