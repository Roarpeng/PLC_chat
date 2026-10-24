"""Natural-language → typed canvas ops (LLM + rule fallback)."""

from __future__ import annotations

import json
import re
from typing import Any

from plc_engine.canvas_model import CanvasState

ALLOWED_OPS = {
    "add_block",
    "update_block",
    "update_block_scl",
    "remove_block",
    "add_network",
    "update_network",
    "add_variable",
    "remove_variable",
    "add_hmi_widget",
    "update_hmi_widget",
    "remove_hmi_widget",
    "add_screen",
    "add_tag",
    "clear_errors",
}


def _normalize_llm_op(op_item: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize common LLM op variants to the canonical patch schema.

    LLM 有时自创载荷（实测 DeepSeek：``update_block`` + ``vars_add`` + ``type``），
    未归一直接放行会出现“已执行”但 apply 静默无效的假成功。返回
    (normalized_ops, error)；error 非空表示该 op 无有效载荷，应剔除并报错。
    """
    op = str(op_item.get("op") or "")
    if op in {"update_block", "update_block_scl"}:
        out: list[dict[str, Any]] = []
        has_payload = any(
            k in op_item for k in ("patch", "scl_body", "comment", "interface", "networks")
        )
        if has_payload:
            out.append(op_item)
        for key in ("vars_add", "add_vars", "vars", "variables_add"):
            for v in op_item.get(key) or []:
                if not isinstance(v, dict) or not str(v.get("name") or "").strip():
                    continue
                var = {
                    "name": str(v["name"]).strip(),
                    "data_type": str(
                        v.get("data_type") or v.get("type") or v.get("datatype") or "Bool"
                    ),
                }
                if v.get("section"):
                    var["section"] = v["section"]
                if v.get("comment"):
                    var["comment"] = v["comment"]
                out.append(
                    {
                        "op": "add_variable",
                        "block": op_item.get("name") or op_item.get("block") or "",
                        "variable": var,
                    }
                )
        if out:
            return out, None
        return [], f"update_block without payload: {op_item.get('name') or '?'}"
    if op == "add_variable":
        var = dict(op_item.get("variable") or {})
        if not var and op_item.get("name") and op_item.get("type"):
            # 变体：把块名/变量名平铺在 op 顶层
            var = {"name": op_item["name"], "data_type": op_item.get("type")}
        if var.get("type") and not var.get("data_type"):
            var["data_type"] = var.pop("type")
        if not str(var.get("name") or "").strip():
            return [], "add_variable missing variable.name"
        block = op_item.get("block") or op_item.get("block_name") or ""
        return [{**op_item, "block": block, "variable": var}], None
    return [op_item], None


def _validate_one(
    canvas: CanvasState, op_item: dict[str, Any], cleaned: list[dict[str, Any]], errors: list[str]
) -> None:
    op = str(op_item.get("op") or "")
    if op not in ALLOWED_OPS:
        errors.append(f"op unsupported: {op}")
        return
    if op in {"update_block", "update_block_scl", "add_network", "update_network", "add_variable", "remove_variable"}:
        name = op_item.get("name") or op_item.get("block")
        if name and name not in canvas.blocks:
            errors.append(f"op {op} unknown block: {name}")
            return
    if op in {"update_hmi_widget", "remove_hmi_widget"}:
        wid = op_item.get("id")
        if wid and wid not in canvas.hmi_widgets:
            errors.append(f"op {op} unknown hmi widget: {wid}")
            return
    if op == "add_block":
        # LLM 生成的 add_block 可能缺 name/块体——放行会导致前端"已执行"
        # 但 applyOpsLocally 静默忽略，块根本没建。缺关键字段直接剔除。
        blk = op_item.get("block")
        name = str(blk.get("name") or "").strip() if isinstance(blk, dict) else ""
        if not name:
            errors.append("op add_block missing block.name")
            return
    cleaned.append(op_item)


def validate_ops(canvas: CanvasState, ops: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Filter/validate ops against whitelist and canvas references."""
    cleaned: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, op_item in enumerate(ops):
        if not isinstance(op_item, dict):
            errors.append(f"op[{i}] not an object")
            continue
        normalized, norm_err = _normalize_llm_op(op_item)
        if norm_err:
            errors.append(f"op[{i}] {norm_err}")
            continue
        # 归一化可能一拆多（update_block+vars_add → update_block + N×add_variable）
        for item in normalized:
            _validate_one(canvas, item, cleaned, errors)
    return cleaned, errors


def ops_touched_blocks(ops: list[dict[str, Any]]) -> list[str]:
    """提取 ops 触及的块名（add_variable/add_network 的 block、add_block 的新块名、
    update_block/remove_block 的 name），供预检按需收窄范围。"""
    names: list[str] = []
    for op in ops or []:
        if not isinstance(op, dict):
            continue
        if isinstance(op.get("block"), str) and op["block"].strip():
            names.append(op["block"].strip())
        elif isinstance(op.get("block"), dict):
            name = str(op["block"].get("name") or "").strip()
            if name:
                names.append(name)
        elif op.get("op") in {"update_block", "remove_block"} and isinstance(op.get("name"), str):
            if op["name"].strip():
                names.append(op["name"].strip())
    return list(dict.fromkeys(names))


_QUESTION_MARKERS = (
    "？", "?", "什么是", "是什么", "为什么", "怎么", "怎样", "如何", "哪些", "哪个",
    "哪条", "几个", "多少", "介绍", "解释", "说明", "描述", "分析", "评价", "评估",
    "总结", "梳理", "审查", "检查", "排查", "对比", "区别", "关系", "列出", "列举",
    "讲讲", "讲一下", "说一下", "说说", "聊聊", "了解", "看看", "有没有", "是不是",
    "能不能", "可不可以", "干嘛", "干什么", "啥意思", "含义", "作用", "用途",
    "运行逻辑", "控制逻辑", "工作原理", "原理", "功能",
)


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    if t.endswith(("？", "?")):
        return True
    if re.search(r"[吗嘛么]\s*[？?]?\s*$", t):
        return True
    return any(m in t for m in _QUESTION_MARKERS)


def _question_without_edit_intent(text: str) -> bool:
    """问句且不含编辑动词——才视为纯提问（「怎么创建 FB X?」是带问号的编辑指令）。"""
    return _looks_like_question(text) and not re.search(
        r"(新建|添加|创建|删除|移除|重命名|改名|绑定|增加)", text or ""
    )


def build_ops_from_rules(prompt: str, canvas: CanvasState) -> list[dict[str, Any]]:
    text = (prompt or "").strip()
    low = text.lower()
    ops: list[dict[str, Any]] = []

    # 提问/分析类输入不当编辑处理——守卫在关键词规则之前（与前端
    # canvasOps.buildOpsFromPrompt 同款；否则问「分析报警逻辑」会误建急停变量）。
    # 带编辑动词的问句（「怎么创建 FB X?」）仍走结构化意图。
    if _question_without_edit_intent(text):
        return []

    # Emergency stop / alarm button
    if any(k in text for k in ("急停", "紧急停止", "e-stop", "estop", "alarm")):
        ops.append(
            {
                "op": "add_variable",
                "block": next(iter(canvas.blocks), "MainDB"),
                "variable": {
                    "name": "EmergencyStop",
                    "data_type": "Bool",
                    "section": "VAR",
                    "comment": "急停",
                },
            }
        )
        ops.append(
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": "btn_estop",
                    "widget_type": "button",
                    "title": "急停",
                    "x": 50,
                    "y": 220,
                    "width": 120,
                    "height": 50,
                    "plc_tag": f"{next(iter(canvas.blocks), 'MainDB')}.EmergencyStop",
                    "data_type": "Bool",
                    "properties": {"color": "rose"},
                    "supported": True,
                },
            }
        )

    # Add FB from description
    m = re.search(r"(?:新建|添加|创建)\s*(?:一个)?\s*(?:FB|功能块)\s*[「\"']?([A-Za-z_][A-Za-z0-9_]*)", text)
    if m:
        name = m.group(1)
        if name not in canvas.blocks:
            ops.append(
                {
                    "op": "add_block",
                    "block": {
                        "name": name,
                        "block_type": "FB",
                        "language": "SCL",
                        "number": max((b.number for b in canvas.blocks.values()), default=0) + 1,
                        "comment": text[:80],
                        "interface": [
                            {"name": "Enable", "data_type": "Bool", "section": "VAR_INPUT"},
                            {"name": "Done", "data_type": "Bool", "section": "VAR_OUTPUT"},
                        ],
                        "scl_body": "IF #Enable THEN\n    #Done := TRUE;\nELSE\n    #Done := FALSE;\nEND_IF;",
                        "networks": [],
                    },
                }
            )

    # Add HMI button bound to tag
    m2 = re.search(
        r"(?:添加|新建)\s*(?:一个)?\s*(?:按钮|button).{0,20}?(?:绑定|绑定到|bind)?\s*[「\"']?([A-Za-z_][A-Za-z0-9_\.]*)",
        text,
        flags=re.IGNORECASE,
    )
    if m2:
        tag = m2.group(1)
        wid = f"btn_{tag.replace('.', '_')}"
        ops.append(
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": wid,
                    "widget_type": "button",
                    "title": tag,
                    "x": 80,
                    "y": 80,
                    "width": 120,
                    "height": 48,
                    "plc_tag": tag if "." in tag else tag,
                    "data_type": "Bool",
                    "supported": True,
                },
            }
        )

    # Indicator for pump / cooling
    if any(k in text for k in ("指示灯", "indicator", "冷却", "水泵", "泵运行")):
        blk = next(iter(canvas.blocks), "MainDB")
        ops.append(
            {
                "op": "add_hmi_widget",
                "widget": {
                    "id": "lamp_status",
                    "widget_type": "indicator",
                    "title": "状态指示",
                    "x": 220,
                    "y": 80,
                    "width": 80,
                    "height": 80,
                    "plc_tag": f"{blk}.MotorRunning" if blk in canvas.blocks else "",
                    "data_type": "Bool",
                    "properties": {"shape": "circle", "color": "green"},
                    "supported": True,
                },
            }
        )

    # Migrate hint: if user asks to convert LAD
    if any(k in low for k in ("转成 scl", "转为 scl", "migrate", "迁移为 scl", "改成 scl")):
        # Caller should use lad_migrate separately; emit no destructive ops here.
        pass

    return ops


_LLM_OPS_SYSTEM = (
    "You are a PLC/HMI editor that outputs ONLY a json object "
    '{{"ops": [...]}} with canvas ops. '
    "Allowed op names: {allowed}. "
    "Payload schemas (follow EXACTLY, do not invent fields like vars_add): "
    '{{"op":"add_variable","block":"<existing block>","variable":{{"name":"...","data_type":"Bool|Int|Real|...","section":"VAR_INPUT|VAR_OUTPUT|VAR|VAR_STAT","comment":"..."}}}}; '
    '{{"op":"update_block","name":"<existing block>","patch":{{"comment":"..."| "scl_body":"..." | "interface":[...] | "networks":[...]}}}}; '
    '{{"op":"add_network","block":"<existing block>","network":{{"title":"...","scl_text":"..."}}}}; '
    '{{"op":"add_block","block":{{"name":"...","block_type":"FB|FC|DB","language":"SCL","interface":[...],"networks":[...]}}}}. '
    "For block body changes prefer update_block_scl with full SCL statements between BEGIN/END. "
    "Only reference blocks present in the context unless op is add_block. "
    "If the request is a question, analysis, or meta request (e.g. read/analyze/explain/"
    "compile the project) rather than a CONCRETE edit instruction, return "
    '{{"ops": []}} exactly — do not fabricate edits. '
    "Reply with raw json object, no markdown."
)


def _llm_ops(prompt: str, canvas: CanvasState, context: dict[str, Any]) -> list[dict[str, Any]]:
    from gateway.app.services.plc.llm_explain import chat_completion_raw, llm_settings

    settings = llm_settings()
    if settings is None:
        return []

    # 精准上下文：稳定骨架（缓存前缀）+ 与指令相关的块详情；指令放最后
    focus = str((context or {}).get("selected_block") or "").strip()
    relevant = []
    for name in select_relevant_blocks(prompt, canvas, focus, k=8):
        b = canvas.blocks[name]
        relevant.append(
            {
                "name": name,
                "type": b.block_type,
                "vars": [v.name for v in b.interface[:16]],
            }
        )
    widgets = [
        {"id": w.id, "type": w.widget_type, "plc_tag": w.plc_tag, "title": w.title}
        for w in sorted(canvas.hmi_widgets.values(), key=lambda w: w.id)[:40]
    ]
    system = _LLM_OPS_SYSTEM.format(allowed=sorted(ALLOWED_OPS))
    user = json.dumps(
        {
            "project": canvas.project_name,
            "blocks": _block_skeleton(canvas),  # 稳定前缀（排序，缓存命中）
            "hmi_widgets": widgets,
            "relevant_blocks": relevant,
            "selected": context,
            "request": prompt,  # 变化内容放最后
        },
        ensure_ascii=False,
    )
    text, _usage = chat_completion_raw(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        settings,
        timeout_s=60.0,
        max_tokens=1024,
        json_mode=True,
    )
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # try extract array
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict) and "ops" in data:
        data = data["ops"]
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------- 精准上下文（省 token）

def _block_skeleton(canvas: CanvasState) -> list[dict[str, Any]]:
    """全画布骨架：每块一行，按块名排序保证字节级稳定。

    稳定前缀跨请求一致 → DeepSeek 磁盘缓存命中，命中部分按低价计费。
    """
    rows = []
    for name in sorted(canvas.blocks):
        b = canvas.blocks[name]
        rows.append(
            {
                "name": name,
                "type": b.block_type,
                "language": b.language,
                "comment": (b.comment or "")[:60],
                "networks": [n.title or f"Net{n.id}" for n in b.networks[:4]],
                "var_count": len(b.interface),
            }
        )
    return rows


def _cjk_terms(text: str) -> set[str]:
    """提取匹配用词元：英文标识符 + 中文 2-4 字滑窗。"""
    terms = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for n in (2, 3, 4):
            for i in range(len(run) - n + 1):
                terms.add(run[i : i + n])
    return terms


def _block_refs(block: Any) -> set[str]:
    """块 SCL 中引用的其他块名（"Other".xxx 形态）。"""
    refs = set()
    for n in block.networks:
        refs.update(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.', n.scl_text or ""))
    if block.scl_body:
        refs.update(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.', block.scl_body))
    refs.discard(block.name)
    return refs


def select_relevant_blocks(
    prompt: str, canvas: CanvasState, focus_block: str = "", k: int = 8
) -> list[str]:
    """按问题挑相关块：名字命中 > 变量命中 > 标题/注释关键词 > 选中块的调用邻居。

    只把少数相关块的详情交给 LLM，替代“整包画布”式投喂。
    """
    lowered = (prompt or "").lower()
    terms = _cjk_terms(prompt or "")
    scores: dict[str, int] = {}
    for name, b in canvas.blocks.items():
        s = 0
        if name and name.lower() in lowered:
            s += 100
        for v in b.interface:
            if v.name and v.name.lower() in lowered:
                s += 40
                break
        blob = " ".join(
            filter(None, [b.comment or "", " ".join(n.title or "" for n in b.networks)])
        )
        if blob:
            s += min(sum(1 for t in terms if t in blob) * 5, 20)
        if s:
            scores[name] = s
    if focus_block and focus_block in canvas.blocks:
        scores[focus_block] = scores.get(focus_block, 0) + 60
        for ref in _block_refs(canvas.blocks[focus_block]):
            if ref in canvas.blocks:
                scores[ref] = scores.get(ref, 0) + 25
    if len(scores) < k:
        # 泛化提问（“该项目的运行逻辑”类，无块名/变量命中）时补结构锚点：
        # OB 调度块优先，再按网络规模取主要 FB/FC，保证回答有真实逻辑可依据。
        anchors = sorted(
            canvas.blocks,
            key=lambda n: (
                not (canvas.blocks[n].name or "").upper().startswith("OB"),
                -len(canvas.blocks[n].networks or []),
                n,
            ),
        )
        for n in anchors:
            if len(scores) >= k:
                break
            scores.setdefault(n, 1)
    return sorted(scores, key=lambda n: (-scores[n], n))[:k]


def build_question_messages(
    prompt: str, canvas: CanvasState, context: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """提问 → LLM 消息。成本结构（DeepSeek 前缀缓存友好）：

    稳定骨架在前（跨问题字节一致 → 缓存命中），随问题变化的相关块详情居中，
    问题本身放最后。回答人设与块深度解释同风格。
    """
    ctx = context or {}
    focus_block = str(ctx.get("selected_block") or "").strip()

    relevant = []
    scl_budget = 24000  # 相关块 SCL 预览总预算（字符），防止 prompt 失控
    for name in select_relevant_blocks(prompt, canvas, focus_block, k=8):
        b = canvas.blocks[name]
        row: dict[str, Any] = {
            "name": name,
            "type": b.block_type,
            "language": b.language,
            "comment": (b.comment or "")[:80],
            "vars": [v.name for v in b.interface[:16]],
            "networks": [n.title or f"Net{n.id}" for n in b.networks[:4]],
            "refs": sorted(_block_refs(b)),
        }
        # 每个相关块都带 SCL 预览（此前只有选中块才带，导入工程的问答只剩
        # 骨架级“猜架构”）；选中块给更长窗口，其余块从预算内截取。
        cap = 4000 if name == focus_block else 1500
        take = min(cap, scl_budget)
        if take > 0:
            row["scl_preview"] = b.get_full_scl()[:take]
            scl_budget -= take
        relevant.append(row)

    widgets = [
        {"id": w.id, "type": w.widget_type, "plc_tag": w.plc_tag, "title": w.title}
        for w in sorted(canvas.hmi_widgets.values(), key=lambda w: w.id)[:40]
    ]

    system = (
        "你是资深工业自动化工程师，熟悉西门子 TIA Portal / SCL / HMI。"
        "用户给出 PLC 画布的块骨架清单、与问题相关的块详情和 HMI 控件清单，并提出问题；"
        "请基于给定信息用中文回答，面向工程师、结构化、务实"
        "（控制逻辑、数据流、联锁关系、风险点、改进建议）。"
        "给定信息里没有的内容不要编造，需要更多信息时明确指出应查看哪些块"
        "（块骨架清单里有全部块名可供引用）。"
        "若用户要的是操作而非分析（如“修改/编译项目”），明确告诉他们怎么做："
        "修改请给出具体编辑指令（例：创建 FB ConveyorCtrl / 在 MainDB 中添加变量 "
        "PumpRun Bool），编译与回写 TIA 用界面右上角的「回写博图」按钮，"
        "单块深度分析可选中块后点「深度解释」。"
    )
    user = json.dumps(
        {
            "project": canvas.project_name,
            "blocks": _block_skeleton(canvas),  # 稳定前缀：全量骨架（排序）
            "hmi_widgets": widgets,  # 稳定（按 id 排序）
            "relevant_blocks": relevant,  # 随问题检索的详情
            "selected": ctx,
            "question": prompt,  # 变化内容放最后，保住前缀缓存
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def answer_project_question(
    prompt: str, canvas: CanvasState, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """回答项目级/分析类问题；未配置 LLM 时抛 LlmNotConfigured。

    返回 {answer, usage}——usage 含 prompt_cache_hit_tokens 等缓存计费字段，
    供前端展示本次 token 消耗与缓存命中。
    """
    from gateway.app.services.plc.llm_explain import (
        LlmNotConfigured,
        chat_completion_raw,
        llm_settings,
    )

    settings = llm_settings()
    if settings is None:
        raise LlmNotConfigured("未配置 LLM（PLC_LLM_* 或 DEEPSEEK_API_KEY）")
    text, usage = chat_completion_raw(
        build_question_messages(prompt, canvas, context),
        settings,
        timeout_s=90.0,
        max_tokens=3072,
    )
    return {"answer": text, "usage": usage}


def stream_project_answer(
    prompt: str, canvas: CanvasState, context: dict[str, Any] | None = None
):
    """流式回答：yield (delta, None) 逐段，结束 yield ("", usage)；未配置抛 LlmNotConfigured。"""
    from gateway.app.services.plc.llm_explain import (
        LlmNotConfigured,
        chat_completion_stream,
        llm_settings,
    )

    settings = llm_settings()
    if settings is None:
        raise LlmNotConfigured("未配置 LLM（PLC_LLM_* 或 DEEPSEEK_API_KEY）")
    yield from chat_completion_stream(
        build_question_messages(prompt, canvas, context),
        settings,
        timeout_s=90.0,
        max_tokens=3072,
    )


def build_chat_ops(
    prompt: str,
    canvas: CanvasState,
    *,
    context: dict[str, Any] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Build validated ops from natural language."""
    ctx = context or {}
    # 纯提问永不出编辑 ops——LLM 对问句偶尔幻觉出 add_variable，这条
    # 守卫是最后防线（前端 canvasOps 与 rules 路径有同款守卫；带编辑
    # 动词的问句仍放行给结构化意图/LLM）。
    if _question_without_edit_intent(prompt):
        return {"ops": [], "errors": [], "source": "question", "preview": []}
    ops: list[dict[str, Any]] = []
    source = "rules"
    if use_llm:
        try:
            ops = _llm_ops(prompt, canvas, ctx)
            if ops:
                source = "llm"
        except Exception:  # noqa: BLE001
            ops = []
    if not ops:
        ops = build_ops_from_rules(prompt, canvas)
        source = "rules"
    cleaned, errors = validate_ops(canvas, ops)
    # One LLM retry on validation errors
    if errors and source == "llm" and use_llm:
        try:
            retry_prompt = prompt + "\n\nPrevious ops invalid: " + "; ".join(errors)
            ops2 = _llm_ops(retry_prompt, canvas, ctx)
            cleaned2, errors2 = validate_ops(canvas, ops2)
            if cleaned2:
                cleaned, errors = cleaned2, errors2
                source = "llm_retry"
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": len(cleaned) > 0 and not errors,
        "ops": cleaned,
        "errors": errors,
        "source": source,
        "preview": _preview_ops(canvas, cleaned),
    }


def _preview_ops(canvas: CanvasState, ops: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for op in ops:
        name = op.get("op", "")
        if name == "add_block":
            out.append({"kind": "block+", "summary": f"新增块 {(op.get('block') or {}).get('name')}"})
        elif name in {"update_block", "update_block_scl"}:
            out.append({"kind": "block~", "summary": f"修改块 {op.get('name')} SCL"})
        elif name == "add_hmi_widget":
            w = op.get("widget") or {}
            out.append({"kind": "hmi+", "summary": f"新增控件 {w.get('title') or w.get('id')}"})
        elif name == "update_hmi_widget":
            out.append({"kind": "hmi~", "summary": f"修改控件 {op.get('id')}"})
        elif name == "add_variable":
            v = op.get("variable") or {}
            out.append({"kind": "var+", "summary": f"{op.get('block')}.{v.get('name')}"})
        else:
            out.append({"kind": name, "summary": json.dumps(op, ensure_ascii=False)[:120]})
    return out
