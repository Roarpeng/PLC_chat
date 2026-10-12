"""Engineer handover prompts — three questions, no auto SCL writeback.

Q1 hardware/sensors → Q2 run logic → Q3 how to adjust HITL.
These templates live on the Gateway PLC / Knowledge Canvas path, not LangGraph TaskState.
"""

from __future__ import annotations

from typing import Any

ENGINEER_PROMPTS: list[dict[str, str]] = [
    {
        "id": "q1_hardware",
        "label": "硬件/传感器",
        "prompt": (
            "这个工程有哪些硬件和传感器？"
            "请按已导出证据列出；未导出或未建索引的标「未导出/未索引」，不要编造。"
        ),
    },
    {
        "id": "q2_run_logic",
        "label": "运行逻辑",
        "prompt": (
            "主循环怎么跑？入口 OB 和顶层调用链是什么？"
            "请引用块名与网络/行，并附源片段。"
        ),
    },
    {
        "id": "q3_hitl_adjust",
        "label": "如何调整",
        "prompt": (
            "如果要改这段运行逻辑，HITL 该怎么确认调整？"
            "不要自动写回 SCL，只说明确认路径。"
        ),
    },
]

_Q1_KEYS = (
    "硬件",
    "传感器",
    "设备清单",
    "有哪些设备",
    "有哪些硬件",
    "device card",
    "sensor",
)
_Q2_KEYS = (
    "主循环",
    "运行逻辑",
    "怎么跑",
    "入口 ob",
    "顶层调用",
    "主扫描",
    "scan cycle",
    "run logic",
)
_Q3_KEYS = (
    "如何调整",
    "怎么调整",
    "怎么改",
    "hitl",
    "确认调整",
    "怎么确认",
    "如何确认反写",
    "how to adjust",
)


def handover_prompts() -> list[dict[str, str]]:
    return [dict(item) for item in ENGINEER_PROMPTS]


def _norm(message: str) -> str:
    return (message or "").strip().lower()


def wants_handover_hardware(message: str) -> bool:
    msg = _norm(message)
    return any(k in msg for k in _Q1_KEYS)


def wants_handover_run_logic(message: str) -> bool:
    msg = _norm(message)
    if wants_handover_hitl(message):
        return False
    return any(k in msg for k in _Q2_KEYS)


def wants_handover_hitl(message: str) -> bool:
    msg = _norm(message)
    if "确认反写" in msg or "执行反写" in msg:
        return False
    return any(k in msg for k in _Q3_KEYS)


def wants_handover_question(message: str) -> bool:
    return (
        wants_handover_hardware(message)
        or wants_handover_run_logic(message)
        or wants_handover_hitl(message)
    )


def format_hitl_adjust_answer(job: dict[str, Any], *, focus: str | None = None) -> str:
    """Deterministic HITL path — never stages SCL writeback."""
    name = job.get("project_name") or job.get("id") or "本工程"
    focus_bit = f"当前焦点块 `{focus}`。" if focus else "未指定块时按整工程 changeset 审阅。"
    gaps = []
    for item in job.get("body_pull_queue") or []:
        if isinstance(item, dict) and item.get("block"):
            gaps.append(str(item["block"]))
        elif isinstance(item, str):
            gaps.append(item)
    gap_line = (
        "以下块仍为未导出/未索引，不能编造改法：" + "、".join(f"`{n}`" for n in gaps[:8])
        if gaps
        else "程序体已索引的块才可生成优化预览。"
    )
    return "\n".join(
        [
            f"**如何调整（HITL，不自动写回 SCL）** — {name}",
            focus_bit,
            "1. 先打开 Project Brief / 画布，确认入口 OB 与调用链引用。",
            "2. 对要动的块说「理解逻辑」或「这个块干什么」，核对块名 + 网络/行 + 源片段。",
            "3. 需要改写时**显式**说「优化SCL」——只生成预览与 changeset，不会导入 .apxx。",
            "4. 审阅 SCL diff 与跳过列表后，再点「确认反写」才会 Openness 导入。",
            "5. 厂商库 / 不要动 / 未导出块：拒绝写程序体，只允许接口级理解。",
            gap_line,
            "_本回答不启用自动 SCL 写回。_",
        ]
    )
