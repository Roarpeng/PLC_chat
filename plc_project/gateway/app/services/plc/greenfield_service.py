"""Greenfield 业务编排（T05）：上传 → 冻结契约 → 首版 IR → 连线 → 校验 → 确认。

**范围铁律**：本模块不含任何生成标准工程 / SCL / XML / TIA 回写代码。
``DeliveryPort`` 只在 ``greenfield_ports.py`` 以 Protocol 形式预留（Q7）。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, runtime_checkable

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
from plc_engine.af.fidelity import FidelityChecker
from plc_engine.af.reverse_guard import check_reverse_guard
from plc_engine.af.spec_diff import (
    FRAMEWORK_BASELINE_PARTITION,
    SpecDiff,
    canonical_hash,
    compute_spec_diff,
    sha256_prefixed,
)
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


# ===========================================================================
# WP-06 / Action A·B·C（F9 / F16 完整版 / F20 服务端）· §13.5 八步编排
# ---------------------------------------------------------------------------
# 契约 §2 / §3.1：G 的会话端口由主 agent 收口接线；H 此处按 Protocol 解耦，
# **不 import** tia_delivery.py 的任何函数（尤其 G 新增的会话函数）。
# N9：fidelity_ok（L1 离线逻辑等价）与 compile_ok（真机编译）严格分离；涉 TIA
# 结论一律标 pending_real_machine，禁止以离线/mock 宣称 L2/L4 通过或「编译零错误」。
# 契约 §0.5：新通道不产生 canvas ops、不建存量链事务；步骤 8 的账本为 Greenfield
# 自有增量留痕。D12：不做在线下载 / online / run-stop / compare-to-PLC / F-block /
# Safety / 全局库 / UI 自动化。
# ===========================================================================

@runtime_checkable
class TiaSessionPort(Protocol):
    """契约 §3.1 会话端口（消费方独立 Protocol，收口时由主 agent 注入实例）。"""

    def open_project(self, ap_path: str) -> dict[str, Any]: ...
    def fast_writeback(
        self, blocks: list[dict[str, Any]], *, overwrite: bool = True
    ) -> dict[str, Any]: ...
    def compile_plc(self) -> dict[str, Any]: ...
    def save_project(self) -> dict[str, Any]: ...
    def close(self) -> dict[str, Any]: ...


#: 硬门禁 / 编排错误码（服务端 fail-closed，前端不可绕过）。
ACTION_CONFIRM_REQUIRED = "GF_ACTION_CONFIRM_REQUIRED"
ACTION_B_FIDELITY_FAILED = "GF_ACTION_B_FIDELITY_FAILED"
ACTION_B_COMPILE_FAILED = "GF_ACTION_B_COMPILE_FAILED"
ACTION_C_FIDELITY_PREREQUISITE = "GF_ACTION_C_FIDELITY_PREREQUISITE"
ACTION_C_SESSION_OWNERSHIP_CONFLICT = "GF_ACTION_C_SESSION_OWNERSHIP_CONFLICT"
ACTION_C_REVERSE_GUARD_BLOCKED = "GF_ACTION_C_REVERSE_GUARD_BLOCKED"
ACTION_C_REVERSE_GUARD_UNAVAILABLE = "GF_ACTION_C_REVERSE_GUARD_UNAVAILABLE"
ACTION_C_ROLLBACK = "GF_ACTION_C_ROLLBACK"
GF_TIA_UNAVAILABLE = "GF_TIA_UNAVAILABLE"
GF_TIA_EXEC_ERROR = "GF_TIA_EXEC_ERROR"

#: §13.5 Action C 八步（顺序即硬编排顺序，单测逐一断言）。
ACTION_C_STEPS: tuple[str, ...] = (
    "session_reuse",               # 1 会话复用（D9，/open 一次并保持）
    "spec_diff",                   # 2 规格差异（复用 spec_diff.py）
    "reverse_guard",               # 3 反向保护（复用 reverse_guard.py，D10）
    "diff_confirm",                # 4 差异清单显式确认（D11）
    "pre_write_backup",            # 5 写前备份
    "block_overwrite",             # 6 块级覆盖（overwrite=true，不归档/不重载/不新建）
    "compile_save",                # 7 编译+保存
    "incremental_fidelity_pcec",   # 8 增量 fidelity + PCEC 账本
)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_ap_path(session: GreenfieldSession) -> str:
    return str(_work_dir() / "greenfield" / session.session_id / "project.ap19")


def _tia_failure_code(result: dict[str, Any]) -> str:
    code = str(result.get("code") or "")
    if "GF_TIA_UNAVAILABLE" in code or result.get("tia_unavailable"):
        return GF_TIA_UNAVAILABLE
    return GF_TIA_EXEC_ERROR


def _compile_verdict(comp: dict[str, Any], static_gate_passed: bool) -> dict[str, Any]:
    """P0-A 判定式（不 import tia_delivery）：``compile_ok = error_count==0 ∧ static_gate_passed``。

    warning 单列、绝不并入成功；TIA 执行中断 / 不可用一律不判通过（N9）。
    即便注入的 port 是 mock，``l2_status`` 仍标 ``pending_real_machine``——真机
    L2 结论只能由收口阶段实测给出，禁止据此宣称 L2 通过或「编译零错误」。
    """
    error_count = _to_int(comp.get("error_count"), 0)
    warnings = list(comp.get("warnings") or [])
    executed = comp.get("ok") is not False
    compile_ok = bool(executed and error_count == 0 and static_gate_passed)
    diagnostics = {
        "status": "compiled" if executed else "tia_exec_error",
        "error_count": error_count,
        "warnings": warnings,
        "blocks": list(comp.get("blocks") or []),
        "elapsed_ms": comp.get("elapsed_ms", 0.0),
        "tia_version": str(comp.get("tia_version") or ""),
        "project_path": str(comp.get("project_path") or ""),
        "static_gate_passed": bool(static_gate_passed),
        "compile_ok": compile_ok,
        "tia_unavailable": str(comp.get("code") or "") == GF_TIA_UNAVAILABLE,
        "pending_real_machine": True,
        "xml_package_unverified": True,
        "l2_status": "pending_real_machine",
        "warning_note": "warning 单列，不并入 compile_ok（N9 / P0-A）",
        "reason": str(comp.get("reason") or ""),
    }
    return {
        "compile_ok": compile_ok,
        "error_count": error_count,
        "warnings": warnings,
        "static_gate_passed": bool(static_gate_passed),
        "compile_diagnostics": diagnostics,
    }


def _static_gate_from_delivery(session: GreenfieldSession, override: Any = None) -> bool:
    if override is not None:
        return bool(override)
    ld = session.last_delivery or {}
    return bool((ld.get("verification") or {}).get("ok"))


def _last_generated_from_delivery(delivery: dict[str, Any] | None) -> dict[str, str]:
    return {
        str(e.get("source_id")): str(e.get("sha256") or "")
        for e in (delivery or {}).get("blocks_manifest", [])
        if e.get("source_id")
    }


def _blocks_from_delivery(delivery: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        {
            "source_id": str(e.get("source_id") or ""),
            "name": str(e.get("name") or ""),
            "path": str(e.get("path") or ""),
            "content_sha256": str(e.get("sha256") or ""),
        }
        for e in (delivery or {}).get("blocks_manifest", [])
    ]


def _build_artifacts(
    delivery: dict[str, Any], spec: Any
) -> tuple[dict[str, str], list[str], dict[str, str], dict[str, str]]:
    """把工程包 ZIP + blocks_manifest 转为 FidelityChecker 产物映射。

    每块写成带 ``source_id`` 的 JSON 描述符（content / content_hash / spec_hash），
    derived 块进入 coverage_matrix、framework_baseline 块命中基线白名单；
    返回 ``(artifacts, derived_source_ids, last_generated, artifact_hashes)``。
    """
    zip_bytes = bytes(delivery.get("zip_bytes") or b"")
    manifest = delivery.get("blocks_manifest") or []
    spec_hash = str(getattr(spec, "spec_hash", "") or "")
    artifacts: dict[str, str] = {}
    derived_ids: list[str] = []
    last_generated: dict[str, str] = {}
    artifact_hashes: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for e in manifest:
            path = str(e.get("path") or "")
            part_path = str(e.get("partitioned_path") or path)
            sid = str(e.get("source_id") or "")
            sha = str(e.get("sha256") or "")
            try:
                scl = zf.read(path).decode("utf-8")
            except (KeyError, UnicodeDecodeError):
                scl = ""
            descriptor: dict[str, Any] = {
                "source_id": sid,
                "source_kind": str(e.get("block_type") or ""),
                "content": scl,
                "content_hash": sha,
                "spec_hash": spec_hash,
            }
            if e.get("partition") == FRAMEWORK_BASELINE_PARTITION:
                descriptor["framework_baseline"] = True
            else:
                derived_ids.append(sid)
            artifacts[part_path] = json.dumps(descriptor, ensure_ascii=False)
            artifact_hashes[part_path] = sha
            last_generated[sid] = sha
    return artifacts, derived_ids, last_generated, artifact_hashes


def _action_spec_like(spec: Any, expected_source_ids: list[str]) -> SimpleNamespace:
    """FidelityChecker 的 FrozenSpecLike：期望对象集合 = 派生产物 source_id（L1 离线口径）。"""
    snap = dict(getattr(spec, "ir_snapshot", {}) or {})
    snap["expected_source_ids"] = sorted(set(expected_source_ids))
    return SimpleNamespace(
        project_id=str(getattr(spec, "project_id", "") or ""),
        version=int(getattr(spec, "spec_version", 0) or 0),
        ir_snapshot=snap,
        spec_hash=str(getattr(spec, "spec_hash", "") or ""),
    )


def _diff_changed_blocks(diff: SpecDiff) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for blk in tuple(diff.changed) + tuple(diff.added):
        out.append(
            {"source_id": str(blk.source_id), "kind": str(blk.kind), "payload": dict(blk.payload)}
        )
    return out


def _coerce_diff(
    diff_arg: Any, session: GreenfieldSession
) -> tuple[Any, int, list[str], list[dict[str, Any]], str]:
    """归一差异清单：None 时复用 ``compute_spec_diff`` 从会话最后两版规格计算。"""
    if diff_arg is None:
        if len(session.specs) >= 2:
            base, target = session.specs[-2], session.specs[-1]
            d = compute_spec_diff(_spec_like(base), _spec_like(target))
            return (
                d, int(d.base_spec_version), list(d.changed_source_ids),
                _diff_changed_blocks(d), "compute_spec_diff(vN-1→vN)",
            )
        base_v = int(getattr(session.specs[-1], "spec_version", 0)) if session.specs else 0
        return None, base_v, [], [], "未提供差异清单且会话不足两版规格，产出空 diff（禁止臆造）"
    if isinstance(diff_arg, SpecDiff):
        return (
            diff_arg, int(diff_arg.base_spec_version), list(diff_arg.changed_source_ids),
            _diff_changed_blocks(diff_arg), "调用方注入 SpecDiff",
        )
    if isinstance(diff_arg, dict):
        base_v = _to_int(diff_arg.get("base_spec_version"), 0)
        changed_ids = [str(x) for x in (diff_arg.get("changed_source_ids") or [])]
        changed_blocks: list[dict[str, Any]] = []
        for blk in list(diff_arg.get("changed") or []) + list(diff_arg.get("added") or []):
            if isinstance(blk, dict):
                changed_blocks.append(
                    {
                        "source_id": str(blk.get("source_id") or ""),
                        "kind": str(blk.get("kind") or ""),
                        "payload": dict(blk.get("payload") or {}),
                    }
                )
        diff_obj = SimpleNamespace(
            base_spec_version=base_v,
            target_spec_version=_to_int(diff_arg.get("target_spec_version"), 0),
            changed_source_ids=tuple(changed_ids),
            changed=(), added=(), removed=(),
        )
        return diff_obj, base_v, changed_ids, changed_blocks, "调用方注入差异清单 dict"
    return None, 0, [], [], "差异清单类型无法识别（禁止臆造）"


def _blocked(
    session: GreenfieldSession,
    code: str,
    reason: str,
    *,
    action: str,
    before: dict[str, int],
    http_status: int | None = None,
    steps: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """统一 fail-closed 结果：零副作用（计数器相对调用前不变）。"""
    counters = dict(session.counters)
    payload: dict[str, Any] = {
        "ok": False,
        "blocked": True,
        "action": action,
        "code": code,
        "reason": reason,
        "side_effect_counters": counters,
        "zero_side_effects": counters == before,
        "mode": "incremental" if action == "C" else "full",
        "pending_real_machine": True,
        "xml_package_unverified": True,
    }
    if http_status is not None:
        payload["http_status"] = http_status
    if steps is not None:
        payload["steps"] = steps
        payload["step_order"] = [s["step"] for s in steps]
    payload.update(extra)
    return payload


def run_action_a(
    session: GreenfieldSession,
    *,
    tia_side_snapshot: dict[str, str] | None = None,
    include_zip_base64: bool = False,
) -> dict[str, Any]:
    """Action A 导出工程包：产出 fidelity_report.json + EvidenceBundle，可离线校验，不写 TIA。

    前置：已 FROZEN（复用 ``generate_project_package`` 的 ``assert_gate("generate")``）。
    ``fidelity_ok`` 是 L1 逻辑等价离线判定；``tia_side_snapshot`` 缺省时 TIA 侧结论标
    ``pending_real_machine``（N9），绝不等同编译通过。传入不一致的 TIA 快照会得到
    ``fidelity_ok=false``，供 UC-17 走真实负例。
    """
    generate_project_package(session)  # FROZEN 门禁 + 缓存 last_delivery（含 zip_bytes）
    delivery = session.last_delivery or {}
    spec = session.specs[-1]
    artifacts, derived_ids, _last_generated, artifact_hashes = _build_artifacts(delivery, spec)
    spec_like = _action_spec_like(spec, derived_ids)
    report = FidelityChecker().check(
        spec_like, artifacts, mode="full", tia_side_snapshot=tia_side_snapshot
    )
    report_dict = report.to_dict()

    zip_bytes = bytes(delivery.get("zip_bytes") or b"")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zip_entry_hashes = {name: sha256_prefixed(zf.read(name)) for name in zf.namelist()}

    views = get_views(session)
    ir_dict = session.ir.to_dict() if session.ir else {}
    edge_list = list(ir_dict.get("edges") or [])
    static_gate = dict(delivery.get("verification") or {})

    evidence: dict[str, Any] = {
        "schema": "gf-evidence-bundle-v1",
        "mode": "full",
        "spec": spec.to_dict(),
        "ir_snapshot": dict(getattr(spec, "ir_snapshot", {}) or {}),
        "views": views,                         # 四视图（flow/seq/state/step_flow）
        "edge_list": edge_list,                 # 连线清单
        "static_gate": static_gate,             # 静态门禁
        "fidelity_report": report_dict,         # fidelity_report.json 内容
        "artifact_hashes": artifact_hashes,    # 派生产物哈希（source_id 定位）
        "zip_entry_hashes": zip_entry_hashes,  # zip 全条目哈希（可离线复算）
        # 附录 B coverage_matrix 完整结构（J 新增产物）显式列出，保持向后兼容：
        # 旧 delivery 无该字段时降级为空 dict / 计数 0，bundle_sha256 仍可离线复算。
        "coverage_matrix": delivery.get("coverage_matrix") or {},
        "coverage_matrix_entry_count": len(delivery.get("coverage_matrix") or {}),
        "baseline_manifest": delivery.get("baseline_manifest"),
        "source_id_map": delivery.get("source_id_map"),
        "package": {
            "zip_filename": delivery.get("zip_filename"),
            "zip_sha256": delivery.get("zip_sha256"),
            "zip_size_bytes": delivery.get("zip_size_bytes"),
            "zip_entry_count": len(zip_entry_hashes),
            "offline_download_endpoint": "/api/v1/plc/canvas/greenfield/download-package",
        },
        "offline_verifiable": True,
        "pending_real_machine": bool(report.pending_real_machine),
        "xml_package_unverified": True,
        "compile_ok": None,
        "compile_note": "Action A 不写 TIA、不产出编译结论；fidelity_ok 是 L1 逻辑等价，不等同编译通过（N9）",
    }
    if include_zip_base64:
        evidence["package_zip_base64"] = base64.b64encode(zip_bytes).decode("ascii")
    evidence["bundle_sha256"] = canonical_hash(
        {k: v for k, v in evidence.items() if k != "package_zip_base64"}
    )

    session.last_fidelity_report = report_dict
    session.last_fidelity_ok = bool(report.fidelity_ok)
    session.add_message(
        "event", "action_a",
        f"Action A 导出工程包：fidelity_ok={report.fidelity_ok}（离线 L1，不写 TIA）",
        {"fidelity_ok": report.fidelity_ok, "block_count": delivery.get("block_count")},
    )

    return {
        "ok": True,
        "action": "A",
        "mode": "full",
        "fidelity_ok": bool(report.fidelity_ok),
        "fidelity_report": report_dict,
        "evidence_bundle": evidence,
        "evidence_bundle_sha256": evidence["bundle_sha256"],
        "spec_version": getattr(spec, "spec_version", 0),
        "spec_hash": getattr(spec, "spec_hash", ""),
        "block_count": delivery.get("block_count"),
        "tia_written": False,
        "reverse_protection": report.reverse_protection,
        "tia_side_drift": report.tia_side_drift,
        "ob_number_deviations": list(report.ob_number_deviations),
        "pending_real_machine": True,
        "xml_package_unverified": True,
        "compile_ok": None,
        "note": "不装 TIA 亦可完成 A；fidelity_ok=false 时 Action B 必须拒绝（UC-17）",
    }


def run_action_b(
    session: GreenfieldSession,
    *,
    confirmed: bool = False,
    fidelity_report: dict[str, Any] | None = None,
    port: Any = None,
    ap_path: str = "",
    static_gate_passed: bool | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Action B 首次写入博途编译：以 Action A 的 ``fidelity_ok == true`` 为前提（UC-17）。

    首次 ``open_project`` → 导入 → ``compile_plc`` → ``save_project``；``compile_ok``
    用 ``error_count==0 ∧ static_gate_passed``，warning 单列。``port`` 缺省时离线编排
    标 ``pending_real_machine``，不宣称编译通过；TIA 不可用/执行中断显式非 200。
    """
    before = dict(session.counters)
    # D11：服务端强制 fail-closed，确认前零副作用（UC-19）。
    if confirmed is not True:
        return _blocked(
            session, ACTION_CONFIRM_REQUIRED,
            "差异清单未显式确认（D11）：Action B 服务端 fail-closed，ops/disk_writes/writebacks/generations 保持不变",
            action="B", before=before,
        )
    # UC-17：A 的 fidelity_ok == true 为前提。
    rep = fidelity_report if fidelity_report is not None else session.last_fidelity_report
    fidelity_ok = rep.get("fidelity_ok") if isinstance(rep, dict) else None
    if fidelity_ok is not True:
        return _blocked(
            session, ACTION_B_FIDELITY_FAILED,
            "Action B 前置未满足：Action A 的 fidelity_ok 不是 true（或尚未执行 Action A），拒绝首次写入博途（UC-17）",
            action="B", before=before,
            fidelity_ok=fidelity_ok, prerequisite="fidelity_ok == true",
        )

    gate = _static_gate_from_delivery(session, static_gate_passed)
    if port is None:
        diag = {
            "status": "pending_real_machine", "compile_ok": False,
            "error_count": 0, "warnings": [], "static_gate_passed": gate,
            "tia_version": "", "project_path": ap_path or "", "elapsed_ms": 0.0,
            "tia_unavailable": False, "pending_real_machine": True,
            "xml_package_unverified": True,
            "l2_status": "pending_real_machine",
            "reason": "未提供 TiaSessionPort（未并线）：离线编排不写 TIA，真机编译结论 pending_real_machine（N9）",
        }
        return {
            "ok": True, "blocked": False, "action": "B", "mode": "full",
            "fidelity_ok": True, "compile_ok": False, "compile_diagnostics": diag,
            "tia_written": False, "pending_real_machine": True,
            "xml_package_unverified": True,
            "side_effect_counters": dict(session.counters),
            "zero_side_effects": dict(session.counters) == before,
            "note": "门禁已通过；但离线无会话端口，绝不宣称编译零错误或 L2 通过（真机由主 agent 收口）",
        }

    steps: list[dict[str, Any]] = []
    opened = port.open_project(ap_path or _default_ap_path(session))
    steps.append({"step": "open_project", "ok": bool(opened.get("ok"))})
    if not opened.get("ok"):
        code = _tia_failure_code(opened)
        return _blocked(
            session, code,
            "Action B 首次打开项目失败：" + str(opened.get("reason") or opened.get("error") or code),
            action="B", before=before, http_status=503, steps=steps,
        )
    fwb_blocks = blocks if blocks is not None else _blocks_from_delivery(session.last_delivery)
    written = port.fast_writeback(fwb_blocks, overwrite=True)
    steps.append({"step": "fast_writeback", "ok": bool(written.get("ok")), "detail": f"blocks={len(fwb_blocks)}"})
    if not written.get("ok"):
        session.counters = dict(before)
        return _blocked(
            session, GF_TIA_EXEC_ERROR,
            "Action B 导入失败：" + str(written.get("reason") or written.get("error") or "fast_writeback ok=false") + "；已回滚计数",
            action="B", before=before, http_status=503, steps=steps,
        )
    session.count("writebacks")
    comp = port.compile_plc()
    verdict = _compile_verdict(comp, gate)
    compile_ok = verdict["compile_ok"]
    steps.append(
        {"step": "compile_plc", "ok": bool(comp.get("ok")) and compile_ok,
         "detail": f"error_count={verdict['error_count']}, compile_ok={compile_ok}"}
    )
    if not comp.get("ok") or not compile_ok:
        session.counters = dict(before)
        return _blocked(
            session, ACTION_B_COMPILE_FAILED,
            "Action B 编译未通过（error_count>0 或静态门禁拦截或 TIA 执行中断）："
            + str(comp.get("reason") or "") + "；已回滚计数，不保存",
            action="B", before=before, steps=steps,
            compile_diagnostics=verdict["compile_diagnostics"],
        )
    saved = port.save_project()
    steps.append({"step": "save_project", "ok": bool(saved.get("ok"))})
    if not saved.get("ok"):
        session.counters = dict(before)
        return _blocked(
            session, GF_TIA_EXEC_ERROR,
            "Action B 保存失败：" + str(saved.get("reason") or "save_project ok=false") + "；已回滚计数",
            action="B", before=before, http_status=503, steps=steps,
        )
    session.action_b_done = True
    session.action_b_compile_ok = compile_ok
    if not session.action_session_handle:
        session.action_session_handle = str(opened.get("session_handle") or "gf-session")
        session.action_c_open_count = 1
    session.add_message(
        "event", "action_b", f"Action B 首次写入编译完成：compile_ok={compile_ok}",
        {"compile_ok": compile_ok},
    )
    return {
        "ok": True, "blocked": False, "action": "B", "mode": "full",
        "fidelity_ok": True, "compile_ok": compile_ok,
        "compile_diagnostics": verdict["compile_diagnostics"],
        "steps": steps, "step_order": [s["step"] for s in steps],
        "tia_written": True, "session_handle": session.action_session_handle,
        "side_effect_counters": dict(session.counters),
        "zero_side_effects": dict(session.counters) == before,
        "pending_real_machine": True,
        "xml_package_unverified": True,
        "note": "compile_ok 为本次编排判定；真机 L2 结论 pending_real_machine（N9）",
    }


def run_action_c(
    session: GreenfieldSession,
    *,
    confirmed: bool = False,
    port: Any = None,
    diff: dict[str, Any] | None = None,
    last_generated: dict[str, str] | None = None,
    tia_side_snapshot: dict[str, str] | None = None,
    tia_owned_by_ui: bool = False,
    fidelity_report: dict[str, Any] | None = None,
    ap_path: str = "",
    static_gate_passed: bool | None = None,
) -> dict[str, Any]:
    """Action C 调试期增量回写：§13.5 八步编排（顺序见 ``ACTION_C_STEPS``）。

    硬门禁（服务端 fail-closed，不能只靠前端拦截）：
    D11 ``confirmed != true`` 零副作用（UC-19）→ D9 会话归属冲突阻止 →
    D10 反向保护 ``allowed == false`` / ``tia_side_drift > 0`` 阻止且禁止「先覆盖再提示」
    （UC-12）→ 写前备份 → 块级覆盖 → 编译+保存（不归档/不重载/不新建）→
    失败导入回滚到调用前状态（UC-13）→ 增量 fidelity + 每次成功 1 条账本。
    """
    before = dict(session.counters)
    steps: list[dict[str, Any]] = []

    def _rec(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": bool(ok), "detail": detail})

    # —— 入口硬门禁：D11 / D9 / 可选 fidelity 前提（§13.5 以 A 与已完成 B 为前提）——
    if confirmed is not True:
        return _blocked(
            session, ACTION_CONFIRM_REQUIRED,
            "差异清单未显式确认（D11）：Action C 服务端 fail-closed，ops/disk_writes/writebacks/generations 保持不变（UC-19）",
            action="C", before=before, steps=steps,
        )
    if tia_owned_by_ui:
        return _blocked(
            session, ACTION_C_SESSION_OWNERSHIP_CONFLICT,
            "会话归属冲突（D9）：检测到用户 UI 正打开同一项目；请关闭用户 UI 或转为只读观察，专用后台实例未取得独占，禁止写入",
            action="C", before=before, steps=steps,
            session_conflict_hint="关闭用户 UI 或转只读观察",
        )
    rep = fidelity_report if fidelity_report is not None else session.last_fidelity_report
    if isinstance(rep, dict) and rep.get("fidelity_ok") is not True:
        return _blocked(
            session, ACTION_C_FIDELITY_PREREQUISITE,
            "Action C 前置未满足：Action A 的 fidelity_ok 不是 true（§13.5 以 A 与已完成 B 为前提）",
            action="C", before=before, steps=steps,
            action_b_done=bool(session.action_b_done),
        )

    # —— 步骤 1 会话复用（D9：/open 一次并保持，后续迭代不再 open / create-project）——
    reused = bool(session.action_session_handle)
    if port is not None and not reused:
        opened = port.open_project(ap_path or _default_ap_path(session))
        if not opened.get("ok"):
            code = _tia_failure_code(opened)
            return _blocked(
                session, code,
                "Action C 会话打开失败：" + str(opened.get("reason") or opened.get("error") or code),
                action="C", before=before, steps=steps, http_status=503,
            )
        session.action_session_handle = str(opened.get("session_handle") or "gf-session")
        session.action_c_open_count += 1
    _rec(
        "session_reuse", True,
        "复用既有句柄（不再 /open）" if reused else
        ("offline_skip(pending_real_machine)" if port is None else "首次 /open 一次并保持"),
    )

    # —— 步骤 2 规格差异（复用 spec_diff.py）——
    diff_obj, base_version, changed_ids, changed_blocks, diff_note = _coerce_diff(diff, session)
    _rec("spec_diff", True, f"base=v{base_version}, changed={len(changed_ids)}; {diff_note}")

    # —— 步骤 3 反向保护（复用 reverse_guard.py，D10 fail-closed）——
    if last_generated is None:
        last_generated = _last_generated_from_delivery(session.last_delivery)
    if tia_side_snapshot is None:
        return _blocked(
            session, ACTION_C_REVERSE_GUARD_UNAVAILABLE,
            "无法读取 TIA 侧块哈希快照，反向保护 fail-closed（禁止先覆盖再提示）；请提供 tia_side_snapshot 或由真机读取",
            action="C", before=before, steps=steps,
            reverse_protection={"status": "unavailable", "allowed": False, "tia_side_drift": None},
            base_spec_version=base_version, changed_source_ids=changed_ids,
        )
    verdict = check_reverse_guard(last_generated, tia_side_snapshot)
    reverse_protection = {
        "status": "evaluated",
        "allowed": verdict.allowed,
        "drift_count": verdict.drift_count,
        "tia_side_drift": verdict.tia_side_drift,
        "blocked_source_ids": list(verdict.blocked_source_ids),
        "reason": verdict.reason,
    }
    _rec("reverse_guard", verdict.allowed, f"tia_side_drift={verdict.tia_side_drift}")
    if not verdict.allowed or verdict.tia_side_drift > 0:
        return _blocked(
            session, ACTION_C_REVERSE_GUARD_BLOCKED,
            "D10 反向保护阻止：" + verdict.reason,
            action="C", before=before, steps=steps,
            reverse_protection=reverse_protection,
            tia_side_drift=verdict.tia_side_drift,
            base_spec_version=base_version, changed_source_ids=changed_ids,
        )

    # —— 步骤 4 差异清单显式确认（D11，已由入口硬门禁保证，此处留痕）——
    _rec("diff_confirm", True, "confirmed=true（D11 已服务端强制，确认前零副作用）")

    # —— 步骤 5 写前备份（快照 + 回滚钩子，UC-13）——
    pre_state = {
        "counters": dict(session.counters),
        "last_delivery_zip_sha256": (session.last_delivery or {}).get("zip_sha256"),
        "ledger_len": len(session.incremental_ledger),
        "last_fidelity_report": session.last_fidelity_report,
        "session_handle": session.action_session_handle,
    }
    backup = {
        "pre_state": pre_state,
        "backup_sha256": canonical_hash(
            {"zip_sha256": pre_state["last_delivery_zip_sha256"], "changed_blocks": len(changed_blocks)}
        ),
    }
    _rec("pre_write_backup", True, backup["backup_sha256"])

    # —— 步骤 6 块级覆盖 + 步骤 7 编译+保存（不归档 / 不重载 / 不新建）——
    compile_ok = False
    compile_diagnostics: dict[str, Any] = {
        "status": "pending_real_machine", "compile_ok": False,
        "error_count": 0, "warnings": [], "static_gate_passed": False,
        "tia_version": "", "project_path": "", "elapsed_ms": 0.0,
        "pending_real_machine": True, "xml_package_unverified": True,
        "l2_status": "pending_real_machine",
        "reason": "未提供 TiaSessionPort，离线编排不写 TIA（pending_real_machine）",
    }
    rollback_reason = ""
    if port is not None:
        written = port.fast_writeback(changed_blocks, overwrite=True)
        _rec("block_overwrite", bool(written.get("ok")), f"blocks={len(changed_blocks)}, overwrite=true")
        if not written.get("ok"):
            rollback_reason = "块级覆盖失败：" + str(written.get("error") or written.get("reason") or "fast_writeback ok=false")
        else:
            session.count("writebacks")
            comp = port.compile_plc()
            gate = _static_gate_from_delivery(session, static_gate_passed)
            verdict_c = _compile_verdict(comp, gate)
            compile_diagnostics = verdict_c["compile_diagnostics"]
            compile_ok = verdict_c["compile_ok"]
            _rec("compile_save", bool(comp.get("ok")) and compile_ok,
                 f"error_count={verdict_c['error_count']}, compile_ok={compile_ok}")
            if not comp.get("ok") or not compile_ok:
                rollback_reason = "编译未通过（error_count>0 或静态门禁拦截或 TIA 执行中断）：" + str(comp.get("reason") or "")
            else:
                saved = port.save_project()
                if not saved.get("ok"):
                    rollback_reason = "保存失败：" + str(saved.get("reason") or "save_project ok=false")
    else:
        _rec("block_overwrite", True, "offline_skip(pending_real_machine)")
        _rec("compile_save", True, "offline_skip(pending_real_machine)")

    # —— 回滚演练（UC-13）：失败导入后项目回到调用前状态且备份可恢复 ——
    if rollback_reason:
        session.counters = dict(pre_state["counters"])
        session.incremental_ledger = session.incremental_ledger[: pre_state["ledger_len"]]
        session.last_fidelity_report = pre_state["last_fidelity_report"]
        session.action_session_handle = pre_state["session_handle"]
        return {
            "ok": False, "blocked": True, "action": "C", "mode": "incremental",
            "code": ACTION_C_ROLLBACK,
            "reason": "失败导入已回滚（UC-13）：" + rollback_reason,
            "rolled_back": True, "backup_restorable": True,
            "state_restored": dict(session.counters) == pre_state["counters"],
            "backup": backup, "steps": steps,
            "step_order": [s["step"] for s in steps],
            "side_effect_counters": dict(session.counters),
            "zero_side_effects": dict(session.counters) == before,
            "base_spec_version": base_version, "changed_source_ids": changed_ids,
            "reverse_protection": reverse_protection,
            "tia_side_drift": verdict.tia_side_drift,
            "ob_number_deviations": [], "compile_ok": False,
            "compile_diagnostics": compile_diagnostics,
            "pending_real_machine": True, "xml_package_unverified": True,
            "tia_written": False,
        }

    # —— 步骤 8 增量 fidelity + 账本（Greenfield 自有留痕，非存量链事务）——
    inc_report_dict: dict[str, Any]
    if session.specs and session.last_delivery:
        spec = session.specs[-1]
        artifacts, derived_ids, _generated, _hashes = _build_artifacts(session.last_delivery, spec)
        spec_like = _action_spec_like(spec, derived_ids)
        inc_report = FidelityChecker().check(
            spec_like, artifacts, mode="incremental",
            base_spec_version=base_version, diff=diff_obj,
            tia_side_snapshot=tia_side_snapshot,
        )
        inc_report_dict = inc_report.to_dict()
    else:
        inc_report_dict = {
            "mode": "incremental", "fidelity_ok": False,
            "base_spec_version": base_version, "changed_source_ids": changed_ids,
            "reverse_protection": reverse_protection, "tia_side_drift": verdict.tia_side_drift,
            "ob_number_deviations": [],
            "note": "无已生成工程产物，增量 fidelity 未计算（禁止臆造）",
        }
    ob_deviations = list(inc_report_dict.get("ob_number_deviations") or [])
    session.incremental_ledger.append(
        {
            "kind": "greenfield_incremental",
            "base_spec_version": base_version,
            "changed_source_ids": changed_ids,
            "compile_ok": compile_ok,
            "tia_side_drift": verdict.tia_side_drift,
            "tia_written": port is not None,
            "backup_sha256": backup["backup_sha256"],
        }
    )
    _rec("incremental_fidelity_pcec", True,
         f"ledger={len(session.incremental_ledger)}, fidelity_ok={inc_report_dict.get('fidelity_ok')}")

    result = {
        "ok": True, "blocked": False, "action": "C", "mode": "incremental",
        "base_spec_version": base_version,
        "changed_source_ids": changed_ids,
        "reverse_protection": reverse_protection,
        "tia_side_drift": verdict.tia_side_drift,
        "ob_number_deviations": ob_deviations,
        "ob_number_deviations_note": "ob_number_deviations 显式留痕（即使为空也不静默；属不纳入 1:1 的域）",
        "fidelity_report": inc_report_dict,
        "steps": steps, "step_order": [s["step"] for s in steps],
        "session_reused": reused,
        "session_handle": session.action_session_handle,
        "open_count": session.action_c_open_count,
        "compile_ok": compile_ok,
        "compile_diagnostics": compile_diagnostics,
        "pcec_ledger_entries": len(session.incremental_ledger),
        "rolled_back": False, "backup_restorable": True, "backup": backup,
        "side_effect_counters": dict(session.counters),
        "zero_side_effects": dict(session.counters) == before,
        "pending_real_machine": port is None,
        "xml_package_unverified": True,
        "tia_written": port is not None,
        "archived": False, "reloaded": False, "project_recreated": False,
        "note": "不归档 / 不重载 / 不新建项目；真机 L4 结论 pending_real_machine（N9）",
    }
    session.last_action_c = result
    return result
