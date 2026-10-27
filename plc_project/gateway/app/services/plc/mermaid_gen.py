"""Mermaid 时序图生成（docs/24 C 线）：对话 + 画布 → LLM → Mermaid sequenceDiagram 文本。

LLM 配置沿用 llm_explain 的 PLC_LLM_* / DEEPSEEK_API_KEY 体系：
未配置抛 LlmNotConfigured（路由层转 400 LLM_NOT_CONFIGURED）；
调用失败或输出非法（缺 sequenceDiagram 声明）抛 RuntimeError（路由层转 502 LLM_CALL_FAILED）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from plc_engine.canvas_model import CanvasState

# ```mermaid 围栏（LLM 违反"不要围栏"约束时的防御性剥离）
_FENCE_RE = re.compile(r"^```[\w-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)

# participant X [as 别名] / actor X —— 提取参与方（中文/字母数字/下划线）
_PARTICIPANT_RE = re.compile(
    r"^\s*(?:participant|actor)\s+([\w\u4e00-\u9fff]+)", re.MULTILINE
)

_SEQUENCE_DECL_RE = re.compile(r"^\s*sequenceDiagram\b", re.MULTILINE)

# 提示词里的画布摘要上限：参与方推断优先块名/设备名，IO 标签名作参数线索
_MAX_BLOCKS = 40
_MAX_DEVICES = 20
_MAX_TAG_NAMES = 30

_SYSTEM_PROMPT = (
    "你是工艺时序图专家。根据用户的工艺描述与画布信息，输出一张合法的 Mermaid "
    "sequenceDiagram 文本，用于表达工业控制流程。规则：\n"
    "- 参与方(participant)＝设备/工位：优先使用画布中已有的块名与 HMI 设备名；"
    "画布没有时从用户描述推断，命名简洁明确（如 输送带、机器人、压机、操作员）。\n"
    "- 消息(->>/-->)＝动作或条件，如「启动请求」「工件到位=true」。\n"
    "- alt/else 表达正常与异常分支（如 正常流转 vs 超时/急停），"
    "必要时用 opt/loop 表达可选步骤与循环工步。\n"
    "- note over 表达关键工艺参数（节拍、压力、超时时间等），有明确数值才写数值。\n"
    "- 只输出 Mermaid 代码，以 sequenceDiagram 声明开头；"
    "不要任何解释文字，不要 markdown 代码围栏（```）。"
)


def _canvas_summary(canvas: CanvasState | dict[str, Any] | None) -> dict[str, Any]:
    """画布 → 提示词摘要：块名/类型/注释 + HMI 设备名 + IO 标签名（均限量）。"""
    if not isinstance(canvas, CanvasState):
        canvas = CanvasState.from_dict(canvas or {})
    blocks = [
        {
            "name": b.name,
            "type": b.block_type,
            "comment": (b.comment or "")[:60],
        }
        for b in list(canvas.blocks.values())[:_MAX_BLOCKS]
    ]
    devices = [
        d.name for d in canvas.hmi_devices[:_MAX_DEVICES] if getattr(d, "name", "")
    ]
    tag_names = list(canvas.tags.keys())[:_MAX_TAG_NAMES]
    return {"blocks": blocks, "devices": devices, "io_tag_names": tag_names}


def build_mermaid_messages(
    prompt: str, canvas: CanvasState | dict[str, Any] | None
) -> list[dict[str, str]]:
    """时序图提示词：系统角色 + 画布摘要 + 工艺描述（问题在末尾，前缀缓存友好）。"""
    user = json.dumps(
        {"canvas": _canvas_summary(canvas), "工艺描述": prompt}, ensure_ascii=False
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _strip_fences(text: str) -> str:
    """剥离 LLM 误加的 ``` / ```mermaid 围栏（内层代码保持原样）。"""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def sanitize_mermaid_sequence(text: str) -> str:
    """清理并校验 LLM 输出：必须是 sequenceDiagram 代码，否则抛 RuntimeError。"""
    stripped = _strip_fences(text)
    if not stripped:
        raise RuntimeError("LLM 返回内容为空，无法生成时序图")
    if not _SEQUENCE_DECL_RE.search(stripped):
        raise RuntimeError(
            "LLM 输出不是合法的 Mermaid sequenceDiagram（缺少 sequenceDiagram 声明）"
        )
    return stripped


def mermaid_participants(mermaid: str) -> list[str]:
    """从 participant/actor 声明提取参与方名（保序去重），供 description 汇总。"""
    names: list[str] = []
    for match in _PARTICIPANT_RE.finditer(mermaid):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def describe_mermaid(mermaid: str, prompt: str) -> str:
    """确定性 description：参与方数 + 名单（截断），不额外调用 LLM。"""
    participants = mermaid_participants(mermaid)
    if not participants:
        return f"工艺时序图：{prompt[:40]}"
    joined = "、".join(participants[:6])
    suffix = " 等" if len(participants) > 6 else ""
    return f"工艺时序图（{len(participants)} 个参与方：{joined}{suffix}）"


def generate_mermaid_sequence(
    prompt: str, canvas: CanvasState | dict[str, Any] | None
) -> dict[str, str]:
    """入口：LLM 生成 Mermaid sequenceDiagram，返回 {mermaid, description}。

    未配置 LLM 抛 LlmNotConfigured；调用失败/输出非法以 RuntimeError 携带可读信息。
    """
    from gateway.app.services.plc.llm_explain import (
        LlmNotConfigured,
        chat_completion_raw,
        llm_settings,
    )

    clean_prompt = (prompt or "").strip()
    settings = llm_settings()
    if settings is None:
        raise LlmNotConfigured(
            "未配置 LLM：请设置 PLC_LLM_BASE_URL / PLC_LLM_API_KEY / PLC_LLM_MODEL，"
            "或用 setx DEEPSEEK_API_KEY <key> 配置 DeepSeek 后重启网关。"
        )
    text, _usage = chat_completion_raw(
        build_mermaid_messages(clean_prompt, canvas),
        settings,
        timeout_s=90.0,
        max_tokens=2048,
    )
    mermaid = sanitize_mermaid_sequence(text)
    return {"mermaid": mermaid, "description": describe_mermaid(mermaid, clean_prompt)}
