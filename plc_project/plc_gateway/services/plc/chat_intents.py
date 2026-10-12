"""Intent detection for PLC block chat."""

from __future__ import annotations

import re


def _strip_at_hint(message: str) -> str:
    """Extract `@…` mention body without trailing Chinese question phrases."""
    import re

    msg = message or ""
    at = re.search(r"@(.+)", msg)
    if not at:
        return ""
    remainder = at.group(1).strip()
    for sep in (
        " 这个",
        " 请描述",
        " 描述",
        " 有什么",
        " 做什么",
        " 作用",
        "？",
        "?",
        "\n",
        "。",
        "，",
    ):
        idx = remainder.find(sep)
        if idx > 0:
            remainder = remainder[:idx].strip()
            break
    return remainder.strip().strip("@").strip()


def _normalize_fb_type_name(raw: str) -> str:
    """Strip quotes from SimaticML data_type like `\"FB5009_AnalOut\"`."""
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
        s = s[1:-1].strip()
    return s
def _wants_full_scl(message: str) -> bool:
    msg = message or ""
    # Canvas deep-dive says「不要…完整 SCL」— that must NOT trigger a dump
    if re.search(r"不要.{0,16}(完整\s*SCL|粘贴|复述|只贴)", msg):
        return "展开 SCL" in msg or "贴出 SCL" in msg
    return any(
        k in msg
        for k in ("完整 SCL", "展开 SCL", "全部 SCL", "源码全文", "完整源码", "贴出 SCL", "全部代码")
    )


def _wants_brief_card(message: str) -> bool:
    """Canvas-style「简述 / 不要贴源码」stays the ≤12-line card."""
    msg = message or ""
    if "简述" in msg:
        return True
    if re.search(r"不要.{0,16}(贴源码|完整\s*SCL|粘贴|复述|只贴)", msg):
        return True
    return False


def _wants_nest_chains(message: str) -> bool:
    msg = message or ""
    return any(k in msg for k in ("嵌套链", "FB-as-type", "TYPED_AS 链", "TYPED_AS链"))


def _wants_node_analyze(message: str) -> bool:
    """Inspector/chip phrases that must dump runtime logic (not the short card)."""
    msg = message or ""
    return any(k in msg for k in ("分析节点", "分析逻辑", "这个块干什么", "运行逻辑"))


def _wants_understand_logic(message: str) -> bool:
    """Engineer interview about this node's runtime — not the IR dump of 分析逻辑."""
    msg = message or ""
    return any(k in msg for k in ("理解逻辑", "理解这块", "确认逻辑", "这块逻辑"))


def _wants_optimize_scl(message: str) -> bool:
    compact = re.sub(r"\s+", "", message or "")
    return "优化SCL" in compact or "改写SCL" in compact


def _wants_confirm_writeback(message: str) -> bool:
    """Explicit HITL confirm. Never true for 「优化SCL」 / 准备反写."""
    if _wants_optimize_scl(message):
        return False
    compact = re.sub(r"\s+", "", message or "")
    if any(k in compact for k in ("确认反写", "执行反写")):
        return True
    lower = compact.lower()
    return any(
        k in lower
        for k in ("confirmwriteback", "executewriteback", "confirm-writeback")
    )


def _wants_optimize_logic(message: str) -> bool:
    msg = message or ""
    if _wants_optimize_scl(msg) or _wants_confirm_writeback(msg):
        return False
    return any(k in msg for k in ("优化逻辑", "优化建议"))


def _wants_block_explain(message: str) -> bool:
    msg = message or ""
    if _wants_brief_card(msg) or _wants_full_scl(msg) or _wants_nest_chains(msg):
        return False
    if _wants_understand_logic(msg) or _wants_optimize_logic(msg) or _wants_optimize_scl(msg):
        return False
    if _wants_confirm_writeback(msg):
        return False
    return any(
        k in msg
        for k in (
            "描述",
            "作用",
            "理解",
            "解释",
            "逻辑",
            "做什么",
            "干嘛",
            "干什么",
            "功能",
            "深入",
            "分析",
            "分析节点",
            "运行逻辑",
        )
    )








def _wants_optimize_hints(message: str) -> bool:
    msg = message or ""
    if _wants_optimize_scl(msg) or _wants_confirm_writeback(msg):
        return False
    return any(
        k in msg
        for k in ("优化", "改进", "风险", "死代码", "不可达", "建议改", "怎么改")
    )


def _wants_project_interview(message: str) -> bool:
    """Whole-project 'understand architecture' asks — interview, don't dump as truth."""
    msg = message or ""
    if any(k in msg for k in ("水平", "垂直", "向上", "向下")):
        return False
    return any(
        k in msg
        for k in (
            "整体结构",
            "深入理解整个项目",
            "整个项目",
            "工程架构",
            "本工程整体",
            "主扫描调用",
            "根据图谱深入",
        )
    )


def _wants_signal_trace(message: str) -> bool:
    msg = message or ""
    return any(
        k in msg
        for k in ("谁读写", "读写这些", "信号读写", "谁读", "谁写", "READS", "WRITES", "信号子图")
    )


def _wants_handover_prompt(message: str) -> bool:
    from gateway.app.services.plc.handover import wants_handover_question

    return wants_handover_question(message)
