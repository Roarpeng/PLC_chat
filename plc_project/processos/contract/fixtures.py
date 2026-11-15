"""The canonical clamp-cycle fixture — the first acceptance scenario.

Blueprint §9 "P0—P2 的第一个唯一验收场景": one Unit + clamp EM + cylinder CM,
extend → hold 2s → retract, 3s timeouts, latched fault, safe reset. Used by every
workstream's tests so the whole platform agrees on one concrete process.
"""
from __future__ import annotations

from .model import (
    Action,
    FailurePolicy,
    Invariant,
    OpenQuestion,
    Operation,
    ProcessContract,
    Provenance,
    Resource,
    Scenario,
    Step,
)


def clamp_resource() -> Resource:
    return Resource(
        id="CM_CLAMP_CYL",
        name="夹紧气缸（双作用）",
        kind="cylinder",
        commands=["Extend", "Retract"],
        feedback=["Extended", "Retracted"],
        status=["Busy", "Done", "Error"],
        exclusive=True,
    )


def clamp_steps() -> list[Step]:
    return [
        Step(id="S_WAIT", name="等待启动", guard="Start AND SafetyPermit", next="S_EXTEND"),
        Step(
            id="S_EXTEND", name="伸出夹紧",
            entry=[Action("CM_CLAMP_CYL", "Extend", True)],
            exit=[Action("CM_CLAMP_CYL", "Extend", False)],
            guard="Extended", timeout_ms=3000, failure_target="S_FAULT", next="S_HOLD",
        ),
        Step(id="S_HOLD", name="保持夹紧", duration_ms=2000, next="S_RETRACT"),
        Step(
            id="S_RETRACT", name="缩回释放",
            entry=[Action("CM_CLAMP_CYL", "Retract", True)],
            exit=[Action("CM_CLAMP_CYL", "Retract", False)],
            guard="Retracted", timeout_ms=3000, failure_target="S_FAULT", next="S_DONE",
        ),
        Step(id="S_DONE", name="完成", next="S_WAIT"),
        Step(
            id="S_FAULT", name="故障保持", is_fault=True,
            reset_guard="Reset AND Retracted AND NOT Extended", next="S_WAIT",
        ),
    ]


def clamp_operation() -> Operation:
    return Operation(
        id="OP_CLAMP",
        name="夹紧循环",
        unit="U_ASSEMBLY",
        em="EM_CLAMP",
        resource_ids=["CM_CLAMP_CYL"],
        preconditions=["unit.auto_permit", "air.ok", "guard.closed"],
        steps=clamp_steps(),
        fault_policy=FailurePolicy(
            detection=["timeout", "feedback_conflict", "permit_lost"],
            latch=True,
            block_auto=True,
            reset_qualification="Reset AND Retracted AND NOT Extended",
        ),
        acceptance=[
            "normal_cycle", "extend_timeout", "retract_timeout",
            "conflicting_feedback", "permit_loss", "fault_reset",
        ],
    )


def clamp_scenarios() -> list[Scenario]:
    return [
        Scenario(
            id="normal_cycle", name="正常循环", kind="normal",
            description="所有许可满足，反馈依序到位",
            inputs=[
                {"t_ms": 0, "signal": "Start", "value": True},
                {"t_ms": 100, "signal": "Start", "value": False},
                {"t_ms": 0, "signal": "Retracted", "value": True},
                {"t_ms": 500, "signal": "Extended", "value": True},
                {"t_ms": 500, "signal": "Retracted", "value": False},
                {"t_ms": 3100, "signal": "Extended", "value": False},
                {"t_ms": 3100, "signal": "Retracted", "value": True},
            ],
            expect={"completed": True, "fault": False, "reached": ["S_EXTEND", "S_HOLD", "S_RETRACT", "S_DONE"]},
        ),
        Scenario(
            id="extend_timeout", name="伸出超时", kind="fault",
            description="3 秒未收到伸出反馈",
            inputs=[
                {"t_ms": 0, "signal": "Start", "value": True},
                {"t_ms": 100, "signal": "Start", "value": False},
                {"t_ms": 0, "signal": "Retracted", "value": True},
            ],
            expect={"fault": True, "fault_reason": "TIMEOUT", "reached": ["S_EXTEND", "S_FAULT"]},
        ),
        Scenario(
            id="retract_timeout", name="缩回超时", kind="fault",
            description="缩回 3 秒未到位",
            inputs=[
                {"t_ms": 0, "signal": "Start", "value": True},
                {"t_ms": 100, "signal": "Start", "value": False},
                {"t_ms": 0, "signal": "Retracted", "value": True},
                {"t_ms": 500, "signal": "Extended", "value": True},
                {"t_ms": 500, "signal": "Retracted", "value": False},
            ],
            expect={"fault": True, "fault_reason": "TIMEOUT", "reached": ["S_RETRACT", "S_FAULT"]},
        ),
        Scenario(
            id="conflicting_feedback", name="矛盾反馈", kind="fault",
            description="伸出/缩回反馈同时有效",
            inputs=[
                {"t_ms": 0, "signal": "Start", "value": True},
                {"t_ms": 100, "signal": "Start", "value": False},
                {"t_ms": 0, "signal": "Retracted", "value": True},
                {"t_ms": 600, "signal": "Extended", "value": True},
            ],
            expect={"fault": True, "fault_reason": "FEEDBACK_FAULT", "reached": ["S_FAULT"]},
        ),
        Scenario(
            id="permit_loss", name="运行许可丢失", kind="fault",
            description="保持中全局许可撤销",
            inputs=[
                {"t_ms": 0, "signal": "Start", "value": True},
                {"t_ms": 100, "signal": "Start", "value": False},
                {"t_ms": 0, "signal": "Retracted", "value": True},
                {"t_ms": 500, "signal": "Extended", "value": True},
                {"t_ms": 500, "signal": "Retracted", "value": False},
                {"t_ms": 1500, "signal": "SafetyPermit", "value": False},
            ],
            expect={"fault": True, "fault_reason": "PERMIT_LOST", "reached": ["S_HOLD", "S_FAULT"]},
        ),
        Scenario(
            id="fault_reset", name="故障复位", kind="normal",
            description="超时故障后满足安全条件复位",
            inputs=[
                {"t_ms": 0, "signal": "Start", "value": True},
                {"t_ms": 100, "signal": "Start", "value": False},
                {"t_ms": 0, "signal": "Retracted", "value": True},
                {"t_ms": 4000, "signal": "Retracted", "value": True},
                {"t_ms": 4500, "signal": "Reset", "value": True},
                {"t_ms": 4600, "signal": "Reset", "value": False},
            ],
            expect={"fault": False, "reset_ok": True, "reached": ["S_FAULT", "S_WAIT"]},
        ),
    ]


def clamp_contract(with_blocking_question: bool = True) -> ProcessContract:
    questions = []
    if with_blocking_question:
        questions.append(
            OpenQuestion(
                id="Q_SAFETY_STOP",
                question="全局安全许可撤销时气缸应保持还是退回？须现场工程决策。",
                affects=["OP_CLAMP", "CM_CLAMP_CYL"],
                severity="blocking",
            )
        )
    return ProcessContract(
        id="PRJ_CLAMP",
        name="夹紧工站工艺契约",
        target_framework="siemens-af-basic@unverified",
        unit="U_ASSEMBLY",
        resources=[clamp_resource()],
        operations=[clamp_operation()],
        invariants=[
            Invariant(
                id="INV_NO_SIMULTANEOUS",
                expr="NOT (Extend AND Retract)",
                scope="CM_CLAMP_CYL",
                severity="error",
            ),
        ],
        open_questions=questions,
        scenarios=clamp_scenarios(),
        provenance=Provenance(origin="user", evidence_refs=["blueprint§9"]),
    )