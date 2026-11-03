"""Step 5 上下文切片器（docs/plc_chat_v3_0.html Tab 2 / Tab 4）。

文档约束：当工程师输入自然语言修改需求时，路由器**仅**提取目标工站的
Slot 3 (@SEQ_AUTO)、Slot 4 (@INTERLOCK) 与关联元件签名（通常 < 1500 Tokens）
发送给 LLM。严禁把底层状态机外壳、Slot 2 模板、物理 Q 映射塞进上下文。

本模块只做切片与预算控制，不调 LLM、不改模型、不写盘。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from plc_engine.contracts import (
    BoschStationAfModel,
    PatchedSlotDelta,
    StationContextSlice,
    to_dict,
)

#: 默认预算，与文档 Tab2 Step5 的 "< 1500 Tokens" 一致
DEFAULT_TOKEN_BUDGET = 1500

#: 允许进入上下文的槽位。Slot 2 是 LOCKED_BOSCH_TEMPLATE，绝不下发。
EDITABLE_SLOT_KEYS = ("slot3_SeqAuto", "slot4_Interlock", "slot5_ElementCall")

#: 元件签名里允许保留的字段（文档所说的"关联元件签名"）
_ELEMENT_SIGNATURE_FIELDS = ("instanceName", "fbType", "ioMap", "timeout", "interlock")

#: 物理 Q 符号：切片里出现即视为越界（防止把物理映射泄露给 LLM）
_PHYSICAL_Q = re.compile(r'"Q[_\w]*"|%Q[\d.]+', re.IGNORECASE)


class ContextBudgetExceeded(ValueError):
    """即使裁剪后仍无法压进预算。"""

    def __init__(self, estimated: int, budget: int) -> None:
        super().__init__(
            f"切片估算 {estimated} tokens，仍超出预算 {budget}；"
            "请缩小目标工站范围或提高预算，不要用截断的 JSON 去调 LLM。"
        )
        self.estimated = estimated
        self.budget = budget


@dataclass
class SliceResult:
    """切片结果 + 裁剪审计，便于前端解释"为什么上下文少了字段"。"""

    context: StationContextSlice
    estimated_tokens: int
    token_budget: int
    #: 实际切出的槽位内容（Slot 3/4/5），是发给 LLM 的主载荷
    slots: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    dropped_fields: list[str] = field(default_factory=list)
    included_slots: list[str] = field(default_factory=list)

    @property
    def within_budget(self) -> bool:
        return self.estimated_tokens <= self.token_budget

    def to_payload(self) -> dict[str, Any]:
        """契约字段 + 切出的槽位，合并成真正下发 LLM 的 JSON。"""
        return {**to_dict(self.context), "slots": self.slots}


# ---------------------------------------------------------------------------
# Token 估算
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """无第三方 tokenizer 的保守估算。

    中文按 1 字 1 token，ASCII 按 4 字符 1 token；取两者较大值再乘 1.15
    安全系数并向上取整。宁可高估，也不要让上下文超预算。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_chars = len(text) - cjk
    raw = cjk + ascii_chars / 4.0
    return int(raw * 1.15) + 1


def _json_tokens(value: Any) -> int:
    return estimate_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


# ---------------------------------------------------------------------------
# 切片
# ---------------------------------------------------------------------------

def _slim_element(element: Any, dropped: list[str]) -> dict[str, Any]:
    """只保留元件签名，剥掉注释/描述等非必要字段。"""
    if not isinstance(element, dict):
        return {"value": element}
    kept = {k: v for k, v in element.items() if k in _ELEMENT_SIGNATURE_FIELDS}
    for key in element:
        if key not in _ELEMENT_SIGNATURE_FIELDS:
            dropped.append(f"element.{key}")
    return kept


def _slim_slot(key: str, value: Any, dropped: list[str]) -> Any:
    if key == "slot5_ElementCall" and isinstance(value, list):
        return [_slim_element(item, dropped) for item in value]
    if key == "slot3_SeqAuto" and isinstance(value, list):
        # 步序里 comment 最容易撑爆预算，优先保留 stepNo / actions / transitions
        return [
            {k: v for k, v in (item.items() if isinstance(item, dict) else {}) if k != "comment"}
            for item in value
        ]
    return value


def slice_station_context(
    model: BoschStationAfModel,
    user_prompt: str,
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    include_slots: Iterable[str] = EDITABLE_SLOT_KEYS,
) -> SliceResult:
    """从 BoschStationAfModel 切出目标工站的受控上下文。

    裁剪顺序（逐级降级，直到压进预算）：
      1. 元件签名里非白名单字段
      2. Slot 3 步序的 comment
      3. Slot 3 整段（保留 Slot 4 / 5，因为互锁与元件签名是修改主战场）
      4. 仍超预算 -> 抛 ContextBudgetExceeded，绝不返回被腰斩的 JSON
    """
    if token_budget <= 0:
        raise ValueError("token_budget 必须为正整数")

    wanted = [k for k in EDITABLE_SLOT_KEYS if k in include_slots]
    dropped: list[str] = []

    def build(level: int, dropped: list[str]) -> tuple[StationContextSlice, dict[str, Any]]:
        slots: dict[str, Any] = {}
        for key in wanted:
            if level >= 3 and key == "slot3_SeqAuto":
                dropped.append("slot3_SeqAuto")
                continue
            raw = model.slots.get(key)
            if raw is None:
                continue
            if level >= 2 and key == "slot3_SeqAuto":
                dropped.append("slot3_SeqAuto.comment")
            slots[key] = _slim_slot(key, raw, dropped) if level >= 1 else raw

        elements = [
            str(e.get("instanceName", e)) if isinstance(e, dict) else str(e)
            for e in (model.slots.get("slot5_ElementCall") or [])
        ]
        interlock = model.slots.get("slot4_Interlock") or {}
        current: dict[str, str] = (
            {str(k): str(v) for k, v in interlock.items()} if isinstance(interlock, dict) else {}
        )

        context = StationContextSlice(
            user_prompt=user_prompt,
            target_station=model.station_id,
            available_elements=elements,
            current_slot4_interlock=current,
        )
        # 其余槽位作为受控载荷挂到 instruction 之外；用私有属性不污染契约，
        # 因此这里把可编辑槽位序列化后放进 current_slot4_interlock 的同级提示里。
        return context, slots

    # level 0 不裁剪，仅用于对比；正式从 level 1 开始（元件签名瘦身）
    last_estimate = 0
    for level in (1, 2, 3):
        dropped: list[str] = []
        context, slots = build(level, dropped)
        payload = {
            "userPrompt": context.user_prompt,
            "targetStation": context.target_station,
            "availableElements": context.available_elements,
            "currentSlot4_Interlock": context.current_slot4_interlock,
            "slots": slots,
        }
        estimated = _json_tokens(payload)
        last_estimate = estimated
        if estimated <= token_budget:
            return SliceResult(
                context=context,
                estimated_tokens=estimated,
                token_budget=token_budget,
                slots=slots,
                truncated=level > 1 or bool(dropped),
                dropped_fields=sorted(set(dropped)),
                included_slots=[k for k in wanted if k in slots],
            )

    raise ContextBudgetExceeded(last_estimate, token_budget)


# ---------------------------------------------------------------------------
# 越界防护
# ---------------------------------------------------------------------------

def assert_context_safe(slice_result: SliceResult) -> None:
    """切片里不得出现物理 Q 映射或 Slot 2 锁定模板。

    这是文档「严禁触碰底层状态机外壳与物理 Q 映射」的机器可检版本。
    """
    text = json.dumps(slice_result.to_payload(), ensure_ascii=False).replace('\\"', '"')
    if "slot2_OpMode" in text or "LOCKED_BOSCH_TEMPLATE" in text:
        raise ValueError("上下文切片泄露了 Slot 2 锁定模板")
    hit = _PHYSICAL_Q.search(text)
    if hit:
        raise ValueError(f"上下文切片泄露了物理输出符号 {hit.group()!r}，禁止下发给 LLM")


def validate_slot_patch(delta: PatchedSlotDelta, *, check_physical_q: bool = True) -> None:
    """LLM 回传的补丁校验：契约校验 + 物理 Q 越界检查。"""
    delta.validate()
    if not check_physical_q:
        return
    for key, value in delta.patch.items():
        blob = f"{key} {value}"
        if _PHYSICAL_Q.search(blob):
            raise ValueError(
                f"补丁 {key!r} 触碰了物理输出映射；LLM 只允许修改 Slot 3/4 的条件表达式"
            )
