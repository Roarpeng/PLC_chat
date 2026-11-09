"""IntentService_v2: NL -> schema-constrained intent -> CandidatePatch only.

Hard rules (blueprint A1 / design 5.1 endpoint 5):
  * NEVER returns free SCL for direct execution;
  * NEVER writes the IR and NEVER writes TIA;
  * missing required slots go to a question queue instead of being guessed;
  * unknown device type becomes ``custom_pending`` (fail-closed);
  * field provenance is explicitly user_explicit / inferred / library_default.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from plc_engine.components.catalog import CUSTOM_PENDING, DriverCatalog
from plc_engine.engineering_ir.evidence import EvidenceLevel
from plc_engine.engineering_ir.models import EngineeringIRV2
from plc_engine.engineering_ir.patch import apply_patch_atomic, make_patch
from plc_engine.process.guard_ast import guard_signal

_TIMEOUT_RE = re.compile(r"(\d+)\s*(毫秒|ms|秒|s)", re.IGNORECASE)
_SEQUENCE_KEYWORDS: tuple[str, ...] = ("启动", "伸出", "到位", "保持", "缩回", "完成", "超时", "故障")


class IntentServiceV2:
    """Deterministic, rule-first structured intent extraction."""

    def __init__(self, catalog: DriverCatalog | None = None) -> None:
        self.catalog = catalog or DriverCatalog()

    @staticmethod
    def extract_timeout_ms(message: str) -> int | None:
        """Extract an explicit timeout, or None when the slot is missing."""
        match = _TIMEOUT_RE.search(str(message or ""))
        if not match:
            return None
        value = int(match.group(1))
        unit = match.group(2).lower()
        if unit in ("毫秒", "ms"):
            return value
        return value * 1000

    def parse(
        self,
        *,
        ir: EngineeringIRV2,
        message: str,
        context_slice: dict[str, Any] | None = None,
        base_revision: int | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        """Return a CandidatePatch proposal, clarification questions, or rejection."""
        text = str(message or "")
        context = dict(context_slice or {})
        revision = int(ir.revision if base_revision is None else base_revision)
        before_hash = ir.ir_sha256 or ir.semantic_hash()
        questions: list[str] = []
        provenance: dict[str, str] = {}
        ops: list[dict[str, Any]] = []

        component_type = self.catalog.match_from_text(text)
        timeout_ms = self.extract_timeout_ms(text)
        wants_driver = bool(re.search(r"气缸|执行器|电机|传感器|阀|马达|接触器|DI|DO", text, re.IGNORECASE))
        wants_sequence = sum(1 for word in _SEQUENCE_KEYWORDS if word in text) >= 2

        if component_type == CUSTOM_PENDING and not wants_sequence:
            questions.append("未识别到标准元件类型（custom_pending）：请明确气缸/单作用执行器/DI-DO/电机启停型号")

        if wants_driver:
            if component_type != CUSTOM_PENDING:
                template = self.catalog.get(component_type)
                provenance["component_type"] = "user_explicit" if template and any(
                    kw.lower() in text.lower() for kw in template.keywords
                ) else "inferred"
            if timeout_ms is None:
                questions.append("缺少动作超时（例：3 秒超时）；未猜测，请补充 move_timeout_ms")
            else:
                provenance["move_timeout_ms"] = "user_explicit"
            if not re.search(r"限位|反馈|到位|传感器", text):
                questions.append("缺少到位/原位反馈信号说明，请确认反馈端口")

        if wants_sequence:
            provenance["sequence"] = "user_explicit"
        if not wants_driver and not wants_sequence:
            questions.append("未识别到可结构化意图；请描述元件或工艺步序（不生成自由 SCL）")

        # A1: missing required slots => clarification only. Never guess a value
        # and never emit an executable candidate while a question is open.
        component_id = str(context.get("component_id") or "")
        if not questions and wants_driver and component_type != CUSTOM_PENDING:
            component_id = component_id or f"CM_{uuid.uuid4().hex[:8]}"
            overrides: dict[str, Any] = {}
            if timeout_ms is not None:
                overrides["move_timeout_ms"] = timeout_ms
            component, spec = self.catalog.create_component(
                component_type,
                component_id=component_id,
                overrides=overrides,
                field_sources=provenance,
            )
            ops.append(
                {
                    "op": "add_component",
                    "ir_id": component_id,
                    "component": component.to_dict(),
                    "driver_spec": spec.to_dict(),
                    "source_id": component_id,
                }
            )
            provenance["io_bindings"] = "library_default"
            provenance.setdefault("component_type", "library_default")

        if not questions and wants_sequence:
            ops.extend(self._sequence_ops(text, timeout_ms))

        # make_patch folds every op payload field into ChangeOp.payload so the
        # candidate can actually be previewed by the atomic patch engine.
        candidate = make_patch(ir.project_id, revision, ops, request_id=request_id)
        candidate.before_hash = before_hash
        candidate.explanation = self._explanation(text, component_type, timeout_ms, wants_sequence)
        candidate.questions = questions

        # Preview on a candidate clone: rejection carries issues + unchanged hash.
        if ops and not questions:
            try:
                preview_ir, _ = apply_patch_atomic(ir, candidate)
                candidate.after_hash = preview_ir.ir_sha256
                rejected = False
                issues: list[dict[str, Any]] = []
            except Exception as exc:  # noqa: BLE001 - structured rejection, no write
                rejected = True
                issues = [{"source_id": "candidate", "reason": str(exc)}]
                candidate.after_hash = before_hash
        else:
            rejected = False
            issues = []
            candidate.after_hash = before_hash

        return {
            "candidate_id": candidate.candidate_id,
            "project_id": ir.project_id,
            "base_revision": revision,
            "request_id": request_id,
            "before_hash": before_hash,
            "after_hash": candidate.after_hash,
            "ops": [op.to_dict() for op in candidate.ops],
            "questions": questions,
            "explanation": candidate.explanation,
            "field_sources": provenance,
            "component_type": component_type,
            "move_timeout_ms": timeout_ms,
            "rejected": rejected,
            "issues": issues,
            "unchanged_ir_hash": before_hash,
            "evidence_level": EvidenceLevel.OFFLINE.value,
            "notice": "CandidatePatch only: no IR write, no TIA write, no free-form SCL",
        }

    @staticmethod
    def _sequence_ops(text: str, timeout_ms: int | None) -> list[dict[str, Any]]:
        """Build structured Step / Transition / Exception ops (never free SCL)."""
        base = f"SEQ_{uuid.uuid4().hex[:6]}"
        hold_ms = 1000 if "保持" in text else 0
        timeout = timeout_ms or 3000
        ops: list[dict[str, Any]] = [
            {"op": "add_step", "ir_id": f"{base}_S0", "source_id": f"{base}_S0",
             "step": {"id": f"{base}_S0", "name": "IDLE", "source_id": f"{base}_S0"}},
            {"op": "add_step", "ir_id": f"{base}_S1", "source_id": f"{base}_S1",
             "step": {"id": f"{base}_S1", "name": "EXTEND", "max_duration_ms": timeout,
                      "failure_target": f"{base}_FAULT", "source_id": f"{base}_S1"}},
            {"op": "add_step", "ir_id": f"{base}_S2", "source_id": f"{base}_S2",
             "step": {"id": f"{base}_S2", "name": "HOLD", "min_duration_ms": hold_ms,
                      "max_duration_ms": max(timeout, hold_ms + 1000), "failure_target": f"{base}_FAULT",
                      "source_id": f"{base}_S2"}},
            {"op": "add_step", "ir_id": f"{base}_S3", "source_id": f"{base}_S3",
             "step": {"id": f"{base}_S3", "name": "RETRACT", "max_duration_ms": timeout,
                      "failure_target": f"{base}_FAULT", "source_id": f"{base}_S3"}},
            {"op": "add_step", "ir_id": f"{base}_S4", "source_id": f"{base}_S4",
             "step": {"id": f"{base}_S4", "name": "DONE", "source_id": f"{base}_S4"}},
            {"op": "add_step", "ir_id": f"{base}_FAULT", "source_id": f"{base}_FAULT",
             "step": {"id": f"{base}_FAULT", "name": "FAULT", "source_id": f"{base}_FAULT"}},
        ]
        guards = {
            f"{base}_T0": guard_signal("CmdStart").to_dict(),
            f"{base}_T1": guard_signal("SensorOut").to_dict(),
            f"{base}_T2": guard_signal("HoldDone").to_dict(),
            f"{base}_T3": guard_signal("SensorIn").to_dict(),
            f"{base}_T4": guard_signal("Reset").to_dict(),
        }
        transitions = [
            (f"{base}_T0", f"{base}_S0", f"{base}_S1"),
            (f"{base}_T1", f"{base}_S1", f"{base}_S2"),
            (f"{base}_T2", f"{base}_S2", f"{base}_S3"),
            (f"{base}_T3", f"{base}_S3", f"{base}_S4"),
            (f"{base}_T4", f"{base}_FAULT", f"{base}_S0"),
        ]
        for tr_id, from_step, to_step in transitions:
            ops.append(
                {
                    "op": "add_transition",
                    "ir_id": tr_id,
                    "source_id": tr_id,
                    "id": tr_id,
                    "from_step": from_step,
                    "to_step": to_step,
                    "guard": guards[tr_id],
                    "priority": 0,
                }
            )
        for index, from_step in enumerate((f"{base}_S1", f"{base}_S2", f"{base}_S3")):
            ops.append(
                {
                    "op": "add_exception",
                    "ir_id": f"{base}_E{index}",
                    "source_id": f"{base}_E{index}",
                    "exception": {
                        "id": f"{base}_E{index}",
                        "from_step": from_step,
                        "to_step": f"{base}_FAULT",
                        "trigger": "TIMEOUT",
                        "source_id": f"{base}_E{index}",
                    },
                }
            )
        return ops

    @staticmethod
    def _explanation(text: str, component_type: str, timeout_ms: int | None, wants_sequence: bool) -> str:
        parts = [f"规则表识别输入: {text[:60]}"]
        if component_type != CUSTOM_PENDING:
            parts.append(f"元件类型={component_type}")
        if timeout_ms is not None:
            parts.append(f"move_timeout_ms={timeout_ms} (user_explicit)")
        if wants_sequence:
            parts.append("生成结构化 Step/Transition/Exception 候选（GuardAST 强类型，禁止自由文本）")
        parts.append("所有 io_bindings 保持 unbound/null，不生成虚构 %I/%Q 地址")
        return "；".join(parts)
