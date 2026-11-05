"""Greenfield 业务编排（T05）：上传 → 冻结契约 → 首版 IR → 连线 → 校验 → 确认。

**范围铁律**：本模块不含任何生成标准工程 / SCL / XML / TIA 回写代码。
``DeliveryPort`` 只在 ``greenfield_ports.py`` 以 Protocol 形式预留（Q7）。
"""
from __future__ import annotations

import base64
import os
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
)
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
    session.assert_gate("confirm", explicit=explicit)
    session.assert_no_side_effects()
    if session.ir is None or session.views is None:
        raise GateLockedError("规格与三视图尚未就绪", code="GF_GATE_LOCKED")
    version, prev = next_version(session.specs)
    spec = freeze(
        session.ir,
        session.views,
        session.contract,
        session_id=session.session_id,
        spec_version=version,
        prev_spec_hash=prev,
        frozen_by=frozen_by,
    )
    session.transition_stage(GreenfieldStage.FROZEN)
    target = write_spec(spec, base_dir or _work_dir(), session.session_id)
    session.count("disk_writes")
    session.specs.append(spec)
    session.notes.append(f"规格 {spec.version_label} 已冻结：{spec.spec_hash}")
    return {"spec": spec.to_dict(), "path": str(target), "markdown": export_md(spec)}


def begin_edit(session: GreenfieldSession) -> dict[str, Any]:
    """冻结后再次编辑 → 生成 vN+1 草稿，旧版字节不变。"""
    session.assert_gate("begin_edit")
    session.transition_stage(GreenfieldStage.LINKABLE)
    session.engineering_summary_shown = False
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
    """统一状态响应；附带 IR / 校验报告摘要，供三视图与右侧面板联动。"""
    data = session.snapshot()
    data["ir"] = session.ir.to_dict() if session.ir else None
    data["views"] = get_views(session) if session.ir else None
    data["summary"] = {
        "units": len(session.ir.units) if session.ir else 0,
        "ems": len(session.ir.ems) if session.ir else 0,
        "cms": len(session.ir.cms) if session.ir else 0,
        "edges": len(session.ir.edges) if session.ir else 0,
    }
    data["ir_only_fields"] = session.ir.ir_only_catalog() if session.ir else []
    return data


def load_frozen_spec(session_id: str, version: int, base_dir: Path | None = None):
    """按版本号装载已冻结 spec 并复现哈希（AC-5）。"""
    from plc_engine.af.greenfield_spec import FrozenSpec

    placeholder = FrozenSpec(spec_version=version, session_id=session_id)
    return load_spec(spec_path(base_dir or _work_dir(), session_id, placeholder))


def session_for(session_id: str | None) -> GreenfieldSession:
    return registry.get(session_id)
