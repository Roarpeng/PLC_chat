"""Greenfield 对话编排：chat ↔ 画布 双向联动的 LLM 增量修改管线。

主链（用户拍板口径）：
- chat 是唯一输入入口：自然语言指令 + 上传资料都在对话流完成；
- LLM 只产出结构化 IRPatch（4 op 白名单），逐条过 ``greenfield_validator.apply_patch``
  原子校验；任一违规整批拒绝（IR 哈希不变），违规明细反馈 LLM 自纠重试（上限 2 次）；
- intent=answer 仅问答零改动；FROZEN 阶段一律拒编辑（先「继续调整」回 LINKABLE）；
- 无 IR 时（DRAFT）消息作为工艺描述优先经 ``greenfield_draft_llm`` LLM 结构化解析出
  丰富首版；LLM 未配置 / 输出非法 / 重试耗尽则诚实回退确定性 planner（零 LLM 依赖兜底）；
- LLM 配置复用 ``llm_explain`` 的 PLC_LLM_* 体系；全程零副作用计数、零写盘。

铁律（legacy_guard AST 闭包）：本模块不得 import 存量重构/回写链模块。
"""
from __future__ import annotations

import json
import re
from typing import Any

from gateway.app.services.plc import greenfield_draft_llm as draft_llm
from gateway.app.services.plc import greenfield_service as svc
from gateway.app.services.plc.llm_explain import (
    LlmNotConfigured,
    chat_completion_raw,
    llm_settings,
)
from plc_engine.af.greenfield_ir import (
    IR_PATCH_OPS,
    IRPatch,
    GreenfieldIR,
)
from plc_engine.af.greenfield_ports import GreenfieldError, GreenfieldStage
from plc_engine.af.greenfield_validator import apply_patch, validate_ir
from plc_engine.af.greenfield_views import assert_roundtrip, project_views

#: 单轮最多 patch 数（防 LLM 输出风暴）。
MAX_PATCHES_PER_TURN = 20

#: 违规自纠重试上限（总尝试 = 1 + 该值）。
MAX_LLM_RETRIES = 2

#: 无首版规格时，命中此模式的短消息按「使用引导」回复而非当作工艺描述。
_GUIDE_HINT_RE = re.compile(
    r"[?？]|怎么|如何|你好|您好|hi|hello|帮助|help|上传|资料|开始|用法|介绍", re.IGNORECASE
)

_GUIDE_TEXT = (
    "从这里开始：\n"
    "1. **上传资料**：点输入框 📎（或直接拖文件进来）上传旧项目的 PLC 变量表 / DB 打印 PDF、"
    "PLCTags.xlsx/csv、SCL 文本；解析回执确认后即冻结为只读兼容契约。\n"
    "2. **描述工艺**：直接发一句工艺描述（单元 / 工序 / 设备 / 异常），例如"
    "「视觉引导与KUKA机器人上下料涂胶打磨工位，气缸夹紧配合，急停触发中止」，我会生成首版规格与三视图。\n"
    "3. **修改方式**：在画布上拖拽连线，或直接对话说「把首步超时改成 5000ms」这类指令。\n"
    "确认架构与功能前不会有任何写盘 / 生成动作。"
)


def summarize_ir_for_llm(ir: GreenfieldIR) -> dict[str, Any]:
    """IR 紧凑摘要：供 LLM 引用节点 id / 步序字段 / 边，避免整份 IR 灌入。"""
    return {
        "project": {
            "name": ir.project.name,
            "business_label": ir.project.business_label,
            "namespace_prefix": ir.project.namespace_prefix,
        },
        "units": [
            {"id": u.id, "name": u.name, "business_label": u.business_label}
            for u in ir.units
        ],
        "ems": [
            {
                "id": e.id,
                "unit_id": e.unit_id,
                "name": e.name,
                "business_label": e.business_label,
            }
            for e in ir.ems
        ],
        "cms": [
            {
                "id": c.id,
                "em_id": c.em_id,
                "cm_type": c.cm_type,
                "business_label": c.business_label,
            }
            for c in ir.cms
        ],
        "control_nodes": [{"id": n.id, "em_id": n.em_id} for n in ir.control_nodes],
        "steps": [
            {
                "id": s.id,
                "em_id": s.em_id,
                "step_id": s.step_id,
                "name": s.name,
                "actions": list(s.actions),
                "transition_condition": s.transition_condition,
                "timeout_ms": s.timeout_ms,
                "next_step_id": s.next_step_id,
                "error_step_id": s.error_step_id,
            }
            for s in ir.steps
        ],
        "edges": [
            {"id": e.id, "kind": e.kind_value(), "src_id": e.src_id, "dst_id": e.dst_id}
            for e in ir.edges
        ],
        "modes": [{"id": m.id, "packml_mode": m.packml_mode} for m in ir.modes],
    }


def _contract_summary(contract: Any) -> dict[str, Any]:
    """契约只给名字目录（物理值只读不可改，LLM 无需细节）。"""
    io_names = [e.name for e in contract.io_entries]
    dbs = []
    for d in contract.db_structs:
        member_names = [str(m.get("name") if isinstance(m, dict) else getattr(m, "name", "")) for m in d.members]
        dbs.append(
            {
                "name": d.name,
                "member_count": len(d.members),
                "member_names_preview": member_names[:60],
            }
        )
    return {
        "immutable": True,
        "io_count": len(contract.io_entries),
        "io_names": io_names[:120],
        "dbs": dbs,
    }


_SYSTEM_PROMPT = """你是「绿地工程助手」：工程师通过对话编辑一份西门子 AF 标准工程规格（IR，强类型 JSON）。
你会收到当前会话上下文（stage / ir / contract / recent_messages / feedback）与用户消息 message。

只输出一个 JSON 对象（不要 Markdown 围栏、不要多余文字），结构：
{"intent":"edit 或 answer","reply":"给工程师的中文说明","patches":[...]}

判断规则：
- 用户在提问、请求解释、闲聊，或修改无法用 patches 表达 → intent="answer"，patches=[]
- 用户在下达修改指令（改步序字段/超时/条件/动作、增删改连线）→ intent="edit" 并给出 patches
- 一次可给多个 patch，但必须都必要；宁可少改不要多改

patches 的 op 只有 4 种：
1. {"op":"add_edge","edge":{"kind","src_id","dst_id","label"}} —— 新增连线
   kind 合法值：E_HIER_UNIT_EM, E_HIER_EM_CM, E_MODE_STATE_DOWN, E_CMD_UNIT_EM, E_SC_UP,
   E_SEQ_TO_CN, E_CN_TO_CM, E_CM_TO_CN, E_IO_READ, E_MSG_STEP, E_BRANCH_ALT_OPT,
   E_PACKML_TRANSITION, E_MODE_SWITCH；src_id/dst_id 必须是上下文 ir 中已存在的节点 id
2. {"op":"remove_edge","edge_id":"..."} —— 删除连线（immutable 骨架边不可删）
3. {"op":"redirect_edge","edge_id":"...","src_id":"...","dst_id":"..."} —— 改向
4. {"op":"set_ir_only_field","field_path":"...","value":...} —— 改字段，
   field_path 形如 "steps.<step的id>.<字段>" 或 "cms.<cm的id>.plcopen.enable"
   可编辑：steps: name/actions/transition_condition/timeout_ms/next_step_id/error_step_id；
   cms: plcopen.enable|valid|busy|error|status、parameters.<key>；
   jobs: start_condition/single_cycle_job；modes: enabled_states/enabled_transitions/enable_hold/enable_complete；
   interlocks: expression/source/applies_to；io_bindings: field_path/compat_ref_id/channel

硬性约束：
- 所有 id / 字段路径必须来自上下文 ir，不得编造
- 只读冻结契约（contract 的 %I/%Q、DB、符号名、OB 号）绝对不可改；units/ems/control_nodes/project/views 也不可改
- 非法 patch 会被整批拒绝且 IR 不变；feedback 字段会给出上次违规原因，请修正后重新输出
- actions 是字符串数组；timeout_ms 等数值字段保持数值类型
- reply 简洁工程化：说明改了什么，或直接给出答案"""


def _parse_json_object(raw: str) -> tuple[dict[str, Any] | None, str]:
    """解析 LLM 输出：容忍 ```json 围栏与前后杂文字（requirement_store 范式）。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline >= 0 else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj, ""
        return None, "顶层不是 JSON 对象"
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj, ""
        except json.JSONDecodeError:
            pass
    return None, "无法解析为 JSON 对象"


def _normalize_patches(
    raw: Any,
) -> tuple[list[dict[str, Any]] | None, str]:
    """把 LLM 的 patches 归一为 IRPatch.from_dict 可接受的形状；结构不符返回错误。"""
    if raw in (None, ""):
        return [], ""
    if not isinstance(raw, list):
        return None, "patches 必须是数组"
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, f"patches[{i}] 必须是对象"
        op = str(item.get("op") or "")
        if op not in IR_PATCH_OPS:
            return None, f"patches[{i}].op 非法：{op or '(空)'}（允许 {sorted(IR_PATCH_OPS)}）"
        if op == "add_edge":
            edge = item.get("edge")
            if not isinstance(edge, dict):
                return None, f"patches[{i}] 缺少 edge 对象"
            kind = str(edge.get("kind") or "")
            src_id = str(edge.get("src_id") or "")
            dst_id = str(edge.get("dst_id") or "")
            if not (kind and src_id and dst_id):
                return None, f"patches[{i}].edge 缺 kind/src_id/dst_id"
            edge_id = str(edge.get("id") or "") or f"E_{kind}_{src_id}__{dst_id}"
            out.append(
                {
                    "op": "add_edge",
                    "edge": {
                        "id": edge_id,
                        "kind": kind,
                        "src_id": src_id,
                        "dst_id": dst_id,
                        "view_mask": [str(x) for x in (edge.get("view_mask") or ["flow"])],
                        "origin": "user",
                        "label": str(edge.get("label") or ""),
                    },
                }
            )
        elif op == "remove_edge":
            if not item.get("edge_id"):
                return None, f"patches[{i}] 缺 edge_id"
            out.append({"op": "remove_edge", "edge_id": str(item["edge_id"])})
        elif op == "redirect_edge":
            if not (item.get("edge_id") and item.get("src_id") and item.get("dst_id")):
                return None, f"patches[{i}] 缺 edge_id/src_id/dst_id"
            out.append(
                {
                    "op": "redirect_edge",
                    "edge_id": str(item["edge_id"]),
                    "src_id": str(item["src_id"]),
                    "dst_id": str(item["dst_id"]),
                }
            )
        else:  # set_ir_only_field
            if not item.get("field_path"):
                return None, f"patches[{i}] 缺 field_path"
            out.append(
                {
                    "op": "set_ir_only_field",
                    "field_path": str(item["field_path"]),
                    "value": item.get("value"),
                }
            )
    if len(out) > MAX_PATCHES_PER_TURN:
        return None, f"patches 数量超限（>{MAX_PATCHES_PER_TURN}）"
    return out, ""


def _parse_and_normalize(
    raw: str,
) -> tuple[tuple[str, str, list[dict[str, Any]]] | None, str]:
    obj, err = _parse_json_object(raw)
    if err:
        return None, err
    intent = str(obj.get("intent") or "").strip().lower()
    if intent not in {"edit", "answer"}:
        intent = "edit" if obj.get("patches") else "answer"
    reply = str(obj.get("reply") or "").strip()
    patches, err = _normalize_patches(obj.get("patches") if intent == "edit" else [])
    if err:
        return None, err
    return (intent, reply, patches), ""


def _apply_patches_atomically(
    ir: GreenfieldIR, patches: list[dict[str, Any]]
) -> tuple[bool, Any, GreenfieldIR | None]:
    """候选副本上逐条应用；任一违规整批放弃（对会话 IR 而言原子）。"""
    candidate = GreenfieldIR.from_dict(ir.to_dict())
    report = None
    for patch_data in patches:
        report = apply_patch(candidate, IRPatch.from_dict(patch_data))
        if not report.ok:
            return False, report, None
    return True, report, candidate


def _patch_summary(patch: dict[str, Any]) -> str:
    if patch.get("op") == "add_edge":
        edge = patch.get("edge") or {}
        return f"新增连线 {edge.get('kind')} {edge.get('src_id')}→{edge.get('dst_id')}"
    if patch.get("op") == "remove_edge":
        return f"删除连线 {patch.get('edge_id')}"
    if patch.get("op") == "redirect_edge":
        return f"改向 {patch.get('edge_id')} 为 {patch.get('src_id')}→{patch.get('dst_id')}"
    return f"设置 {patch.get('field_path')} = {json.dumps(patch.get('value'), ensure_ascii=False)}"


def _install_llm_draft(session: Any, ir: Any) -> dict[str, Any]:
    """把 LLM 解析出的首版 IR 安装进会话（镜像 ``draft_from_prompt`` 的接线与门禁）。"""
    if session.stage is GreenfieldStage.LINKABLE:
        session.transition_stage(GreenfieldStage.DRAFT)
    session.assert_gate("draft")
    session.ir = ir
    session.views = project_views(ir)
    assert_roundtrip(ir, session.views)
    session.report = validate_ir(ir)
    session.transition_stage(GreenfieldStage.LINKABLE)
    summary = {
        "units": len(ir.units),
        "ems": len(ir.ems),
        "cms": len(ir.cms),
        "steps": len(ir.steps),
    }
    session.notes.append("首版规格由 AI 结构化解析生成；推断项（联锁等）已标注待确认")
    session.add_message(
        "event",
        "views",
        f"AI 解析生成首版规格：{summary['units']} 工位 / {summary['ems']} 工序 / "
        f"{summary['cms']} 设备 / {summary['steps']} 步序；可在画布连线，或直接对话修改",
        summary,
    )
    reply_text = (
        f"AI 解析生成首版：{summary['units']} 工位 / {summary['ems']} 工序 / "
        f"{summary['cms']} 设备 / {summary['steps']} 步序。"
        "\n请在画布上核对连线，或直接在对话里告诉我要调整什么。"
    )
    return session.add_message(
        "assistant", "views", reply_text, {"summary": summary, "source": "ai_draft"}
    )


def chat_turn(session: Any, message: str) -> dict[str, Any]:
    """对话一轮：问答 / 增量修改 / 首版生成三分支；返回 {state, reply, message}。"""
    session.assert_gate("chat")
    text = (message or "").strip()
    if not text:
        raise GreenfieldError("消息内容为空", code="GF_CHAT_EMPTY")
    session.add_message("user", "text", text)

    # 分支一：尚无首版规格 —— 短问句/问候按使用引导回复；否则消息即工艺描述，
    # 优先 LLM 结构化解析出丰富首版；未配置/失败则回退确定性 planner（零 LLM 依赖）。
    if session.ir is None:
        if len(text) <= 30 and _GUIDE_HINT_RE.search(text):
            msg = session.add_message("assistant", "text", _GUIDE_TEXT)
            return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}
        ir, llm_reason = None, ""
        if llm_settings() is not None:
            ir, llm_reason = draft_llm.llm_draft_ir(text, session.contract)
        if ir is not None:
            msg = _install_llm_draft(session, ir)
            return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}
        state = svc.draft_from_prompt(session, text)
        summary = state.get("summary") or {}
        fallback = session.notes and "回退" in session.notes[-1]
        if llm_reason:
            # LLM 已配置但解析失败：诚实回退说明（不静默降级），note 供留痕。
            session.notes.append(f"AI 结构化解析未成功（{llm_reason}），已回退确定性解析生成首版")
        reply_text = (
            f"已按你的描述生成首版规格：{summary.get('units', 0)} 工位 / {summary.get('ems', 0)} 工序 / "
            f"{summary.get('cms', 0)} 设备 / {summary.get('steps', 0)} 步序。"
            + ("（描述未能结构化解析，暂用示例骨架，请继续补充工艺细节）" if fallback else "")
            + (f"（AI 结构化解析未成功，已回退确定性解析：{llm_reason}）" if llm_reason else "")
            + "\n请在画布上核对连线，或直接在对话里告诉我要调整什么。"
        )
        msg = session.add_message("assistant", "views", reply_text, {"summary": summary})
        # state 在 add_message 前已生成，重取以保证响应内含最新消息流
        return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}

    # 分支二/三：LLM 编排（问答 or 增量修改）
    settings = llm_settings()
    if settings is None:
        raise GreenfieldError(
            "LLM 未配置：请设置 PLC_LLM_BASE_URL / PLC_LLM_API_KEY / PLC_LLM_MODEL 环境变量后重启网关",
            code="LLM_NOT_CONFIGURED",
        )
    context: dict[str, Any] = {
        "stage": session.stage.value,
        "has_contract": session.contract is not None,
        "recent_messages": session.recent_messages(8),
        "open_questions": list(session.report.open_questions[:6]) if session.report else [],
        "ir": summarize_ir_for_llm(session.ir),
    }
    if session.contract is not None:
        context["contract"] = _contract_summary(session.contract)

    feedback = ""
    last_violations: list[dict[str, Any]] = []
    for _attempt in range(1 + MAX_LLM_RETRIES):
        user_payload = {**context, "feedback": feedback, "message": text}
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        try:
            raw, _usage = chat_completion_raw(
                messages, settings, timeout_s=90, max_tokens=2048, json_mode=True
            )
        except LlmNotConfigured as exc:  # pragma: no cover - 配置中途被清
            raise GreenfieldError(str(exc), code="LLM_NOT_CONFIGURED") from exc
        except RuntimeError as exc:
            raise GreenfieldError(str(exc), code="LLM_CALL_FAILED") from exc

        parsed, err = _parse_and_normalize(raw)
        if err:
            feedback = f"上次输出不合规：{err}。请只输出规定结构的 JSON 对象。"
            last_violations = [{"code": "GF_CHAT_LLM_SCHEMA", "message": err}]
            continue

        intent, reply, patches = parsed

        # 分支二：纯问答 —— 零改动
        if intent != "edit" or not patches:
            msg = session.add_message("assistant", "text", reply or "（模型未给出回复）")
            return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}

        # FROZEN：编辑一律拒绝（须先「继续调整」回 LINKABLE）
        if session.stage is GreenfieldStage.FROZEN:
            msg = session.add_message(
                "assistant",
                "edit",
                "当前规格已冻结，不能直接修改；请先点击「继续调整(v+1)」开启新草稿，再告诉我修改内容。",
                {"applied": False, "reason": "FROZEN"},
            )
            return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}

        # 分支三：增量修改 —— 原子批量应用
        ok, report, candidate = _apply_patches_atomically(session.ir, patches)
        if ok and candidate is not None:
            session.ir = candidate
            session.report = report
            session.views = project_views(candidate)
            if session.stage is GreenfieldStage.LINKABLE:
                session.transition_stage(GreenfieldStage.VALIDATING)
            applied = "；".join(_patch_summary(p) for p in patches)
            verdict = (
                "（全部校验通过）"
                if report.ok
                else f"（注意：校验存在 {len(report.violations)} 项待处理问题）"
            )
            msg = session.add_message(
                "assistant",
                "edit",
                (reply or "已按你的要求修改规格。") + f"\n已应用：{applied}{verdict}",
                {"applied": True, "patches": patches, "report_ok": report.ok},
            )
            return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}

        # 校验拒绝 → 违规明细反馈 LLM 自纠重试
        last_violations = [v.to_dict() for v in report.violations[:8]]
        feedback = (
            "上次的 patches 被规格白名单整批拒绝，IR 未变动。违规明细："
            + json.dumps(last_violations, ensure_ascii=False)
            + "。请修正 patches（或改 intent=answer 向工程师解释原因）后重新输出。"
        )

    reasons = "；".join(str(v.get("message") or v) for v in last_violations[:3])
    msg = session.add_message(
        "assistant",
        "edit",
        f"本次修改未能通过规格校验，规格保持不变。原因：{reasons}。"
        "可以换个说法再试，或在画布上手动编辑。",
        {"applied": False, "violations": last_violations},
    )
    return {"state": svc.state_payload(session), "reply": msg["text"], "message": msg}
