"""Greenfield 会话态：纯内存草稿、阶段状态机与确认前副作用计数（T05 / §4.3）。

Q1 裁定：确认前工程写盘恒为 0；草稿仅驻留内存，防刷新丢失通过
**用户主动导出 / 导入草稿 JSON** 解决（不是自动落盘）。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from plc_engine.af.greenfield_contract import CompatContract, ParseReceipt
from plc_engine.af.greenfield_ir import GFViews, GreenfieldIR
from plc_engine.af.greenfield_ports import (
    FORBIDDEN_PREGATE_ACTIONS,
    LOCKED_HINT,
    STAGE_ALLOWED_ACTIONS,
    STAGE_BADGES,
    GateLockedError,
    GreenfieldStage,
)
from plc_engine.af.greenfield_spec import FrozenSpec
from plc_engine.af.greenfield_validator import ValidationReport

#: 允许的状态迁移（§4.2），非法迁移一律抛 GateLockedError。
_TRANSITIONS: dict[GreenfieldStage, frozenset[GreenfieldStage]] = {
    GreenfieldStage.DRAFT: frozenset({GreenfieldStage.DRAFT, GreenfieldStage.LINKABLE}),
    GreenfieldStage.LINKABLE: frozenset(
        {GreenfieldStage.LINKABLE, GreenfieldStage.VALIDATING, GreenfieldStage.DRAFT}
    ),
    GreenfieldStage.VALIDATING: frozenset(
        {GreenfieldStage.VALIDATING, GreenfieldStage.LINKABLE, GreenfieldStage.FROZEN}
    ),
    GreenfieldStage.FROZEN: frozenset({GreenfieldStage.FROZEN, GreenfieldStage.LINKABLE}),
    GreenfieldStage.LOCKED: frozenset(),
}


@dataclass
class GreenfieldSession:
    """一次 Greenfield 会话的全部状态；无任何自动持久化。"""

    session_id: str = ""
    stage: GreenfieldStage = GreenfieldStage.DRAFT
    ir: GreenfieldIR | None = None
    views: GFViews | None = None
    receipt: ParseReceipt | None = None
    contract: CompatContract | None = None
    report: ValidationReport | None = None
    specs: list[FrozenSpec] = field(default_factory=list)
    engineering_summary_shown: bool = False
    #: AC-4 三计数：确认前必须恒为 0。
    counters: dict[str, int] = field(
        default_factory=lambda: {"ops": 0, "disk_writes": 0, "writebacks": 0, "generations": 0}
    )
    notes: list[str] = field(default_factory=list)
    custom_hw: dict[str, Any] = field(default_factory=dict)
    last_delivery: dict[str, Any] | None = None
    #: 对话流消息（chat 化主入口）。纯内存（Q1 口径），随草稿导出/导入。
    #: 结构：{id, role: user|assistant|event, kind, text, payload, ts}
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = uuid.uuid4().hex[:12]

    # -------------------------------------------------------------- 对话消息
    def add_message(
        self,
        role: str,
        kind: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """追加一条对话消息并返回它（前端不自建消息真值，全部以会话为源）。"""
        message: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "role": role,
            "kind": kind,
            "text": text,
            "payload": payload or {},
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.messages.append(message)
        if len(self.messages) > 500:  # 防御性上限，超限丢最旧
            self.messages = self.messages[-500:]
        return message

    def recent_messages(self, limit: int = 8) -> list[dict[str, Any]]:
        """最近若干条消息摘要（供 LLM 上下文；事件消息也纳入以感知画布改动）。"""
        picked = self.messages[-limit:]
        out = []
        for m in picked:
            out.append(
                {
                    "role": m.get("role"),
                    "kind": m.get("kind"),
                    "text": str(m.get("text") or "")[:400],
                }
            )
        return out

    # ------------------------------------------------------------------ 门禁
    def assert_gate(self, action: str, *, explicit: bool = False) -> None:
        """G1 唯一裁定入口；越阶段一律给解释性提示，禁止静默失败。"""
        if action in FORBIDDEN_PREGATE_ACTIONS and self.stage is not GreenfieldStage.FROZEN:
            raise GateLockedError(
                f"{LOCKED_HINT}（拒绝动作 {action}）",
                details={"action": action, "stage": self.stage.value},
            )
        allowed = STAGE_ALLOWED_ACTIONS.get(self.stage, frozenset())
        if action not in allowed:
            raise GateLockedError(
                f"当前阶段「{STAGE_BADGES.get(self.stage, self.stage.value)}」不允许「{action}」；{LOCKED_HINT}",
                details={"action": action, "stage": self.stage.value, "allowed": sorted(allowed)},
            )
        if action == "confirm":
            if not explicit:
                raise GateLockedError(
                    "确认必须由用户显式点击产生，系统不得代劳或超时自动推进",
                    code="GF_GATE_NOT_CONFIRMED",
                    details={"explicit": False},
                )
            if self.report is None or not self.report.ok:
                raise GateLockedError(
                    "校验未全部通过，不能确认图中架构与功能",
                    details={"report_ok": self.report.ok if self.report else None},
                )
            if self.receipt is not None and not self.receipt.user_confirmed:
                raise GateLockedError(
                    "上传解析回执尚未经用户确认，兼容契约不得冻结",
                    details={"receipt_id": self.receipt.receipt_id},
                )
            if not self.engineering_summary_shown:
                raise GateLockedError(
                    "确认弹窗须先展示一次工程视角摘要（Q9）",
                    code="GF_GATE_NOT_CONFIRMED",
                    details={"engineering_summary_shown": False},
                )

    def assert_no_side_effects(self) -> None:
        """确认前零副作用；已冻结过的会话允许「每次确认恰好一次 spec 写盘」的历史累计。

        ``disk_writes`` 的合法上限 = 已冻结版本数；其余三类计数恒为 0。
        """
        if self.stage is GreenfieldStage.FROZEN:
            return
        baseline = len(self.specs)
        excess = {
            key: value - (baseline if key == "disk_writes" else 0)
            for key, value in self.counters.items()
            if value > (baseline if key == "disk_writes" else 0)
        }
        if excess:
            raise GateLockedError(
                f"确认前出现副作用：{excess}",
                details={"counters": dict(self.counters), "stage": self.stage.value},
            )

    def transition_stage(self, target: GreenfieldStage | str) -> GreenfieldStage:
        new_stage = GreenfieldStage(target) if isinstance(target, str) else target
        if new_stage not in _TRANSITIONS.get(self.stage, frozenset()):
            raise GateLockedError(
                f"非法阶段迁移 {self.stage.value} → {new_stage.value}",
                details={"from": self.stage.value, "to": new_stage.value},
            )
        self.stage = new_stage
        return new_stage

    def count(self, key: str, delta: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + delta

    # ------------------------------------------------------------ 草稿导出/导入
    def export_draft(self) -> dict[str, Any]:
        """用户主动导出（纯内存 → JSON），不计入任何副作用。"""
        return {
            "format": "greenfield-draft-v1",
            "session_id": self.session_id,
            "source_stage": self.stage.value,
            "engineering_summary_shown": self.engineering_summary_shown,
            "ir": self.ir.to_dict() if self.ir else None,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "contract": self.contract.to_dict() if self.contract else None,
            "custom_hw": dict(self.custom_hw),
            "counters": dict(self.counters),
            "messages": [dict(m) for m in self.messages],
        }

    def import_draft(self, payload: dict[str, Any]) -> None:
        """用户主动导入恢复草稿；确认前禁用，且不接受已冻结会话。"""
        self.assert_gate("draft")
        if payload.get("format") != "greenfield-draft-v1":
            raise GateLockedError("草稿格式不匹配", code="GF_DRAFT_FORMAT")
        ir_data = payload.get("ir")
        if ir_data:
            self.ir = GreenfieldIR.from_dict(dict(ir_data))
        receipt_data = payload.get("receipt")
        if receipt_data:
            self.receipt = ParseReceipt.from_dict(dict(receipt_data))
        contract_data = payload.get("contract")
        if contract_data:
            self.contract = CompatContract.from_dict(dict(contract_data))
        if isinstance(payload.get("custom_hw"), dict):
            self.custom_hw = dict(payload["custom_hw"])
        if isinstance(payload.get("messages"), list):
            self.messages = [dict(m) for m in payload["messages"] if isinstance(m, dict)]
        # 导入后统一回到「可连线」：草稿不继承来源会话的阶段（避免非法迁移），
        # 也不继承任何副作用计数（确认前恒为 0）。
        self.engineering_summary_shown = False
        self.views = None
        self.report = None
        self.counters = {"ops": 0, "disk_writes": 0, "writebacks": 0, "generations": 0}
        self.transition_stage(GreenfieldStage.LINKABLE if self.ir else GreenfieldStage.DRAFT)

    # -------------------------------------------------------------- 状态快照
    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stage": self.stage.value,
            "stage_label": STAGE_BADGES.get(self.stage, self.stage.value),
            "locked_hint": LOCKED_HINT if self.stage is not GreenfieldStage.FROZEN else "",
            "has_ir": self.ir is not None,
            "has_contract": self.contract is not None,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "report": self.report.to_dict() if self.report else None,
            "specs": [
                {
                    "spec_version": s.spec_version,
                    "spec_hash": s.spec_hash,
                    "frozen_at": s.frozen_at,
                }
                for s in self.specs
            ],
            "counters": dict(self.counters),
            "engineering_summary_shown": self.engineering_summary_shown,
            "notes": list(self.notes),
        }


class SessionRegistry:
    """进程内会话表；服务重启即清空（Q1 纯内存口径）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, GreenfieldSession] = {}

    def get(self, session_id: str | None = None, *, create: bool = True) -> GreenfieldSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        if not create:
            raise KeyError(session_id or "")
        session = GreenfieldSession(session_id=session_id or "")
        self._sessions[session.session_id] = session
        return session

    def reset(self) -> None:
        self._sessions.clear()


registry = SessionRegistry()
