"""Greenfield 通道独立 APIRouter（T05）。

前缀 ``/api/v1/plc/canvas/greenfield``；与既有 ``plc.router`` 完全隔离，
不注册进 smartRoute 七 tab、不产生 canvas ops、不建 PCEC 事务、
不触碰 §2.3 存量重构链与回写链。所有响应统一 ``ApiResponse`` 信封。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from gateway.app.schemas.common import ApiResponse, ErrorBody
from gateway.app.services.plc import greenfield_chat, tia_delivery
from gateway.app.services.plc import greenfield_service as svc
from plc_engine.af.greenfield_ports import GreenfieldError

router = APIRouter(prefix="/api/v1/plc/canvas/greenfield", tags=["greenfield"])


def _rid() -> str:
    return uuid.uuid4().hex[:12]


def _ok(data: Any) -> ApiResponse[dict[str, Any]]:
    return ApiResponse(ok=True, data=data, request_id=_rid())


def _error_status(code: str) -> int:
    """§3.8 错误码映射：门禁/不可变 409，连线/投影 422，LLM 网关错 502，其余 400。

    Phase 2 追加（§9.2 / P2-5 / P2-6）：``GF_PCEC_*`` 基线/账本 fail-closed → 409；
    ``GF_TIA_STATIC_GATE_FAILED`` / ``GF_TIA_OB_*`` 校验类 → 422；其余 ``GF_TIA_*``
    参数类 → 400。UC-03 收口：TIA 不可用 / 执行中断 → **503**（显式非成功、非 200）。
    """
    if code in ("GF_TIA_UNAVAILABLE", "GF_TIA_EXEC_ERROR"):
        return 503
    # WP-06：三动作硬门禁（D11 / D10 / UC-17 / UC-13 / D9）一律 409 fail-closed。
    if code.startswith("GF_ACTION"):
        return 409
    if code.startswith(("GF_GATE", "GF_SPEC_IMMUTABLE", "GF_PCEC_")):
        return 409
    if code.startswith(("GF_EDGE", "GF_VIEW", "GF_TIA_OB")) or code == "GF_TIA_STATIC_GATE_FAILED":
        return 422
    if code == "LLM_CALL_FAILED":
        return 502
    return 400


def _fail(exc: GreenfieldError) -> JSONResponse:
    """统一 ApiResponse 信封 + 正确 HTTP 语义状态码。"""
    body = ApiResponse(
        ok=False,
        data=None,
        error=ErrorBody(**exc.to_dict()),
        request_id=_rid(),
    )
    return JSONResponse(status_code=_error_status(exc.code), content=body.model_dump())


class SessionIn(BaseModel):
    session_id: str | None = None


class UploadIn(SessionIn):
    items: list[dict[str, Any]] = Field(default_factory=list)


class DraftIn(SessionIn):
    prompt: str = ""
    project_name: str = "AssemblyCell"


class LinkIn(SessionIn):
    op: str = "add_edge"
    edge: dict[str, Any] | None = None
    edge_id: str | None = None
    src_id: str = ""
    dst_id: str = ""
    field_path: str = ""
    value: Any = None


class ConfirmIn(SessionIn):
    explicit: bool = False
    frozen_by: str = "user"


class DraftImportIn(SessionIn):
    payload: dict[str, Any] = Field(default_factory=dict)


class HardwarePatchIn(SessionIn):
    op: str = "mount_cm"
    cm_id: str = ""
    hw_node_id: str = ""
    var_key: str = ""
    target_id: str = ""
    role: str = "auto"
    node: dict[str, Any] | None = None


class ChatIn(SessionIn):
    message: str = ""


class DeliverTiaIn(SessionIn):
    """POST /deliver-tia：mode=auto 尝试 Openness 自动导入编译（TIA 不可用时显式失败、
    非 200，禁止静默降级）；mode=package 只出 SCL+XML 补充包并标 pending_real_machine。
    §9 P2-4..P2-8。"""

    mode: str = "auto"


class PatchIn(SessionIn):
    """POST /patch：{project_id, ops, base_spec_version, expected_ir_sha256}。"""

    project_id: str = ""
    ops: list[dict[str, Any]] = Field(default_factory=list)
    base_spec_version: int | None = None
    expected_ir_sha256: str = ""


class DiffIn(SessionIn):
    """POST /diff：{project_id, from_version, to_version}。"""

    project_id: str = ""
    from_version: int = 0
    to_version: int = 0


class ConfirmDiffIn(SessionIn):
    """POST /confirm-diff：{project_id, diff_id, confirmed}。"""

    project_id: str = ""
    diff_id: str = ""
    confirmed: bool = False


class ActionAIn(SessionIn):
    """POST /action-a：导出工程包（离线可校验，不写 TIA）。"""

    tia_side_snapshot: dict[str, str] | None = None
    include_zip_base64: bool = False


class ActionBIn(SessionIn):
    """POST /action-b：首次写入博途编译（以 Action A 的 fidelity_ok==true 为前提，D11 确认）。"""

    confirmed: bool = False
    fidelity_report: dict[str, Any] | None = None
    ap_path: str = ""
    static_gate_passed: bool | None = None


class ActionCIn(SessionIn):
    """POST /action-c：调试期增量回写（§13.5 八步；D11 / D10 / D9 fail-closed）。"""

    confirmed: bool = False
    diff: dict[str, Any] | None = None
    tia_side_snapshot: dict[str, str] | None = None
    last_generated: dict[str, str] | None = None
    tia_owned_by_ui: bool = False
    fidelity_report: dict[str, Any] | None = None
    ap_path: str = ""
    static_gate_passed: bool | None = None


def _session(session_id: str | None, project_id: str = ""):
    return svc.session_for(session_id, project_id)


@router.get("/state")
def get_state(
    session_id: str | None = None, project_id: str | None = None
) -> ApiResponse[dict[str, Any]]:
    """GET /state?project_id=：附带项目标识 / 基线版本 / fidelity 状态 / 副作用计数器。"""
    return _ok(svc.state_payload(_session(session_id, project_id or "")))


@router.get("/whitelist")
def get_whitelist() -> ApiResponse[dict[str, Any]]:
    return _ok(svc.whitelist_payload())


@router.post("/upload")
def upload(body: UploadIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"receipt": svc.upload(_session(body.session_id), body.items)})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/receipt/confirm")
def receipt_confirm(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"contract": svc.confirm_receipt_action(_session(body.session_id))})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/draft")
def create_draft(body: DraftIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.draft_from_prompt(_session(body.session_id), body.prompt, body.project_name))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/links")
def apply_link(body: LinkIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        payload = body.model_dump(exclude={"session_id"})
        return _ok(svc.apply_link_patch(_session(body.session_id), payload))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/validate")
def validate(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.revalidate(_session(body.session_id)))
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/views")
def views(session_id: str | None = None) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.get_views(_session(session_id)))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/engineering-summary")
def engineering_summary(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    return _ok(svc.engineering_summary(_session(body.session_id)))


@router.post("/confirm")
def confirm(body: ConfirmIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(
            svc.confirm_and_freeze(
                _session(body.session_id),
                explicit=body.explicit,
                frozen_by=body.frozen_by,
            )
        )
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/begin-edit")
def begin_edit(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.begin_edit(_session(body.session_id)))
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/export/mermaid")
def export_mermaid(session_id: str | None = None) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"markdown": svc.export_first_mermaid(_session(session_id))})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/draft/export")
def export_draft(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    return _ok({"payload": _session(body.session_id).export_draft()})


@router.post("/draft/import")
def import_draft(body: DraftImportIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    session = _session(body.session_id)
    try:
        session.import_draft(body.payload)
        return _ok(svc.state_payload(session))
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/specs/{version}")
def get_spec(
    version: int, session_id: str | None = None, project_id: str | None = None
) -> ApiResponse[dict[str, Any]]:
    """GET /specs/{v}?project_id=：完整 FrozenSpec 快照（可独立重建画布含拓扑）。"""
    try:
        return _ok({
            "spec": svc.load_frozen_spec(
                session_id or "", version, project_id=project_id or ""
            ).to_dict()
        })
    except GreenfieldError as exc:
        return _fail(exc)
    except (OSError, KeyError, ValueError) as exc:
        return ApiResponse(
            ok=False,
            error=ErrorBody(code="GF_SPEC_NOT_FOUND", message=str(exc)),
            request_id=_rid(),
        )


@router.post("/hardware")
def update_hardware(body: HardwarePatchIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        payload = body.model_dump(exclude={"session_id"})
        return _ok(svc.update_hardware(_session(body.session_id), payload))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/chat")
def chat_message(body: ChatIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """chat ↔ 画布 双向联动的对话入口（问答 / LLM 增量修改 / 首版生成）。"""
    try:
        result = greenfield_chat.chat_turn(_session(body.session_id), body.message)
        return _ok(result)
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/generate")
def generate_project(body: SessionIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok({"delivery": svc.generate_project_package(_session(body.session_id))})
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/load-reference")
def load_reference(body: DraftIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    try:
        return _ok(svc.load_reference_fixture(_session(body.session_id), body.prompt))
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/deliver-tia")
def deliver_tia(body: DeliverTiaIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """Phase 2 最后一公里：XML 补充包 + 静态门禁 + PCEC 账本 +（auto）Openness 自动导入编译。

    Openness 不可用 / TIA 被占用 → ``GF_TIA_UNAVAILABLE`` / ``GF_TIA_EXEC_ERROR``
    显式失败（HTTP **503**、非 200，附结构化诊断与人工导入指引），禁止静默降级为 200 成功；
    静态门禁或 PCEC 基线 fail-closed → 4xx。``mode=package`` 不触真机，标 pending_real_machine。
    """
    try:
        result = tia_delivery.deliver_tia(_session(body.session_id), mode=body.mode)
        return _ok({k: v for k, v in result.items() if k != "zip_bytes"})
    except GreenfieldError as exc:
        return _fail(exc)


@router.get("/download-package")
def download_package(session_id: str | None = None) -> Response:
    try:
        filename, zip_bytes = svc.get_project_package_zip(_session(session_id))
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except GreenfieldError as exc:
        return _fail(exc)


# ---------------------------------------------------------------------------
# WP-03 / §3 新增端点：统一受控 patch / 差异占位 / 差异清单确认（零存量链、零 PCEC）
# ---------------------------------------------------------------------------

@router.post("/patch")
def patch_canvas(body: PatchIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """POST /patch：统一受控写入口；原子拒绝时 422，IR 字节不变。"""
    try:
        session = _session(body.session_id, body.project_id)
        payload = body.model_dump(exclude={"session_id"})
        result = svc.apply_patch_action(session, payload)
        if not result.get("ok"):
            error_body = ApiResponse(
                ok=False,
                data=result,
                error=ErrorBody(
                    code="GF_PATCH_ATOMIC_REJECTED",
                    message=result.get("reason") or "原子拒绝：任一 op 非法，整批回滚",
                    details={"violations": result.get("violations") or []},
                ),
                request_id=_rid(),
            )
            return JSONResponse(status_code=422, content=error_body.model_dump())
        return _ok(result)
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/diff")
def diff_spec(body: DiffIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """POST /diff：调用 B 的 spec_diff 产出带 source_id 的真实 SpecDiff（§2.3）；
    缺版本 / 缺规格时优雅降级为空 diff + 明确说明，禁止臆造。"""
    session = _session(body.session_id, body.project_id)
    payload = body.model_dump(exclude={"session_id", "project_id"})
    return _ok(svc.diff_placeholder(session, payload))


@router.post("/confirm-diff")
def confirm_diff(body: ConfirmDiffIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """POST /confirm-diff：``confirmed != true`` 时零副作用计数器恒 0。"""
    session = _session(body.session_id, body.project_id)
    payload = body.model_dump(exclude={"session_id", "project_id"})
    return _ok(svc.confirm_diff_action(session, payload))


# ---------------------------------------------------------------------------
# WP-06 / §3.2 三动作端点：Action A 导出工程包 / B 首次写入编译 / C 增量回写
# 旧端点 /generate /deliver-tia /download-package 一律保留、默认行为不变，
# D11 硬门禁只挂在新增的 /action-b /action-c（契约 §2 / 任务 5）。
# 收口接线（Agent L）：会话模式开启时由 _action_session_port() 注入 G 的
# SessionModeTiaPort；默认关闭时 port=None，仍走现有离线 / mock 路径
# （pending_real_machine），不改 TiaSessionPort 协议形状、不触真机。
# ---------------------------------------------------------------------------

def _action_session_port():
    """G ⇄ H 收口接线：按会话模式开关注入 G 的会话端口（默认关闭）。

    ``PLC_GREENFIELD_SESSION_MODE`` 未设置时 ``session_mode_enabled()`` 为 False，
    返回 None → H 的 run_action_b/c 走既有离线编排（pending_real_machine），
    与接线前逐字节一致，绝不 break 存量单测。开启后返回
    ``tia_delivery.SessionModeTiaPort``，由 H 消费（契约 §3.1 Protocol 解耦）。
    """
    if not tia_delivery.session_mode_enabled():
        return None
    return tia_delivery.SessionModeTiaPort()


def _action_result(result: dict[str, Any]) -> Any:
    """三动作统一出口：blocked → 非 200 错误信封（服务端 fail-closed）；否则 200。"""
    if result.get("blocked"):
        exc = GreenfieldError(
            result["reason"],
            code=result["code"],
            details={
                "action": result.get("action"),
                "blocked_reason": result.get("reason"),
                "side_effect_counters": result.get("side_effect_counters"),
                "zero_side_effects": result.get("zero_side_effects"),
                "step_order": result.get("step_order"),
            },
        )
        return _fail(exc)
    return _ok(result)


@router.post("/action-a")
def action_a(body: ActionAIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """Action A：产出 fidelity_report.json + EvidenceBundle（spec/ir_snapshot/四视图/
    连线清单/静态门禁/产物哈希/.zip 摘要）可离线校验；不写 TIA；返回 fidelity_ok。
    """
    try:
        return _ok(
            svc.run_action_a(
                _session(body.session_id),
                tia_side_snapshot=body.tia_side_snapshot,
                include_zip_base64=body.include_zip_base64,
            )
        )
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/action-b")
def action_b(body: ActionBIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """Action B：以 Action A 的 fidelity_ok==true 为前提（UC-17）+ D11 确认（UC-19）。"""
    try:
        return _action_result(
            svc.run_action_b(
                _session(body.session_id),
                confirmed=body.confirmed,
                fidelity_report=body.fidelity_report,
                ap_path=body.ap_path,
                static_gate_passed=body.static_gate_passed,
                port=_action_session_port(),
            )
        )
    except GreenfieldError as exc:
        return _fail(exc)


@router.post("/action-c")
def action_c(body: ActionCIn = Body(...)) -> ApiResponse[dict[str, Any]]:
    """Action C：§13.5 八步增量回写；D11 / D10 / D9 服务端 fail-closed。"""
    try:
        return _action_result(
            svc.run_action_c(
                _session(body.session_id),
                confirmed=body.confirmed,
                diff=body.diff,
                tia_side_snapshot=body.tia_side_snapshot,
                last_generated=body.last_generated,
                tia_owned_by_ui=body.tia_owned_by_ui,
                fidelity_report=body.fidelity_report,
                ap_path=body.ap_path,
                static_gate_passed=body.static_gate_passed,
                port=_action_session_port(),
            )
        )
    except GreenfieldError as exc:
        return _fail(exc)
