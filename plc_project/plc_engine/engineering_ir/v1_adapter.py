"""Zero-field-loss v1 -> v2 adapter (G1 / design 3.2).

Strategy (frozen):
  1. The COMPLETE ``GreenfieldIR.to_dict()`` payload is stored verbatim in
     ``EngineeringIRV2.legacy_raw`` (opaque, never interpreted, never dropped).
  2. Structured entities are projected to v2 semantic objects using the v1
     stable IDs unchanged (id immutable, name mutable).
  3. Free-text v1 expressions (``transition_condition`` / ``actions`` /
     ``interlocks[].expression``) are NOT invented into GuardAST nodes; they
     stay in ``legacy_raw`` and are listed in the receipt as unmapped.
  4. ``to_v1_view()`` is a read-only compatibility view, never a write-back.

Source audit note: the design document says "20 top-level fields", but a line
by line read of ``plc_engine/af/greenfield_ir.py:844-873`` shows **21**. The
constant below follows the real source code, not the prose.
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from plc_engine.components.driver_spec import (
    CompileMode,
    ComponentDefinition,
    DriverSpec,
    FailurePolicy,
    FieldSource,
    PortDataType,
    PortDirection,
    PortRole,
    TypedPort,
)
from plc_engine.engineering_ir.hashing import canonical_dumps, sha256_prefixed
from plc_engine.engineering_ir.models import EngineeringIRV2, SourceBinding
from plc_engine.process.guard_ast import guard_true
from plc_engine.process.sequence_ir import (
    ExceptionTrigger,
    Mode,
    SequenceException,
    Step,
    Transition,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime dependency
    from plc_engine.af.greenfield_ir import GreenfieldIR

#: The real 21 top-level fields of ``GreenfieldIR`` (source audited).
V1_TOP_LEVEL_FIELDS: tuple[str, ...] = (
    "project",
    "ir_version",
    "units",
    "ems",
    "cms",
    "control_nodes",
    "jobs",
    "steps",
    "modes",
    "interlocks",
    "io_bindings",
    "compat_refs",
    "edges",
    "views",
    "spec_meta",
    "project_id",
    "baseline_version",
    "hw_nodes",
    "hw_links",
    "cm_mounts",
    "var_bindings",
)

#: v1 CM types -> v2 component type / driver template / official LBC name.
V1_CM_TYPE_MAP: dict[str, dict[str, str]] = {
    "LBC_TwoWayActuator": {
        "component_type": "double_acting_cylinder",
        "driver_template": "double_acting_cylinder",
        "lbc_name": "LBC_TwoWayActuator",
    },
    "LBC_OneWayActuator": {
        "component_type": "single_acting_actuator",
        "driver_template": "single_acting_actuator",
        "lbc_name": "LBC_OneWayActuator",
    },
    "LBC_MotorStarter": {
        "component_type": "motor_starter",
        "driver_template": "motor_starter",
        "lbc_name": "LBC_MotorStarter",
    },
    "LBC_DigitalSignal": {
        "component_type": "di_do",
        "driver_template": "di_do",
        "lbc_name": "LBC_DigitalSignal",
    },
}

#: PLCOpen five signals become typed status ports (never physical addresses).
PLCOPEN_PORT_SPECS: tuple[tuple[str, PortRole], ...] = (
    ("enable", PortRole.MODE),
    ("valid", PortRole.STATUS),
    ("busy", PortRole.STATUS),
    ("error", PortRole.STATUS),
    ("status", PortRole.FEEDBACK),
)


def _v1_dict(v1_ir: Any) -> dict[str, Any]:
    """Accept a GreenfieldIR instance, any to_dict() object, or a plain dict."""
    if isinstance(v1_ir, dict):
        return copy.deepcopy(v1_ir)
    to_dict = getattr(v1_ir, "to_dict", None)
    if callable(to_dict):
        return copy.deepcopy(to_dict())
    raise TypeError("v1_ir must be a GreenfieldIR-like object or a dict")


def _driver_spec_for_cm(cm: dict[str, Any], mapping: dict[str, str]) -> DriverSpec:
    """Build a typed DriverSpec from a v1 GFCm record."""
    spec_id = f"DRV_{cm.get('id') or 'CM'}"
    ports: dict[str, TypedPort] = {}
    for signal, role in PLCOPEN_PORT_SPECS:
        ports[signal] = TypedPort(
            name=signal,
            data_type=PortDataType.BOOL,
            direction=PortDirection.INPUT if role is PortRole.MODE else PortDirection.OUTPUT,
            role=role,
            required=True,
            source=FieldSource.IMPORTED,
            binding=None,
            description=f"v1 PLCOpen signal {signal} (unbound)",
        )
    raw_params = cm.get("parameters") or {}
    timeout = 3000
    for key in ("timeout_ms", "move_timeout_ms", "TimeOut"):
        if isinstance(raw_params.get(key), int):
            timeout = int(raw_params[key])
            break
    ports["CmdExtend"] = TypedPort(
        name="CmdExtend", data_type=PortDataType.BOOL, direction=PortDirection.INPUT,
        role=PortRole.COMMAND, required=True, source=FieldSource.IMPORTED, binding=None,
        writer="FB_Sequence", description="extend command (unbound)",
    )
    ports["CmdRetract"] = TypedPort(
        name="CmdRetract", data_type=PortDataType.BOOL, direction=PortDirection.INPUT,
        role=PortRole.COMMAND, required=True, source=FieldSource.IMPORTED, binding=None,
        writer="FB_Sequence", description="retract command (unbound)",
    )
    return DriverSpec(
        id=spec_id,
        component_type=mapping["component_type"],
        typed_ports=ports,
        parameters=dict(raw_params),
        states=["IDLE", "EXTENDING", "EXTENDED", "RETRACTING", "RETRACTED", "FAULT"],
        transitions=[
            {"from": "IDLE", "to": "EXTENDING", "on": "CmdExtend AND SafetyPermit"},
            {"from": "EXTENDING", "to": "EXTENDED", "on": "SensorOut"},
            {"from": "EXTENDED", "to": "RETRACTING", "on": "CmdRetract"},
            {"from": "RETRACTING", "to": "RETRACTED", "on": "SensorIn"},
            {"from": "EXTENDING", "to": "FAULT", "on": "timeout"},
            {"from": "RETRACTING", "to": "FAULT", "on": "timeout"},
            {"from": "FAULT", "to": "IDLE", "on": "Reset"},
        ],
        failure_policy=FailurePolicy.ENTER_FAULT_REQUIRE_RESET,
        compile_mode=CompileMode.OFFICIAL_LBC,
        safety_permit_required=True,
        move_timeout_ms=timeout,
        lbc_name=mapping["lbc_name"],
        field_sources={"component_type": FieldSource.IMPORTED.value, "move_timeout_ms": FieldSource.IMPORTED.value},
    )


class V1ToV2Adapter:
    """One-way, zero-field-loss adapter from v1 ``GreenfieldIR`` to v2 IR."""

    @staticmethod
    def to_v2(v1_ir: GreenfieldIR | dict[str, Any], *, project_id: str = "") -> EngineeringIRV2:
        """Convert v1 IR to v2, preserving every v1 field in ``legacy_raw``."""
        raw = _v1_dict(v1_ir)
        legacy_raw_sha256 = sha256_prefixed(canonical_dumps(raw))
        pid = project_id or str(raw.get("project_id") or "") or f"prj_v1_{legacy_raw_sha256[7:19]}"

        ir = EngineeringIRV2(project_id=pid, revision=0)
        ir.legacy_raw = raw
        ir.legacy_raw_sha256 = legacy_raw_sha256

        # --- components + driver specs ------------------------------------ #
        for cm in raw.get("cms") or []:
            if not isinstance(cm, dict):
                continue
            cm_id = str(cm.get("id") or "")
            if not cm_id:
                continue
            cm_type = str(cm.get("cm_type") or "")
            mapping = V1_CM_TYPE_MAP.get(
                cm_type,
                {"component_type": "custom_pending", "driver_template": "custom_pending", "lbc_name": cm_type},
            )
            component = ComponentDefinition(
                id=cm_id,
                name=str(cm.get("business_label") or cm_id),
                component_type=mapping["component_type"],
                driver_template=mapping["driver_template"],
                driver_spec_id=f"DRV_{cm_id}",
                source=FieldSource.IMPORTED,
                io_bindings=None,
                parameters=dict(cm.get("parameters") or {}),
                metadata={"v1_cm_type": cm_type, "v1_em_id": str(cm.get("em_id") or "")},
            )
            ir.components.append(component)
            ir.driver_specs[component.driver_spec_id] = _driver_spec_for_cm(cm, mapping)

        # --- steps / transitions / exceptions ------------------------------ #
        v1_steps = [s for s in (raw.get("steps") or []) if isinstance(s, dict)]
        step_by_number: dict[int, str] = {}
        unmapped_free_text: list[str] = []
        for raw_step in v1_steps:
            step_id = str(raw_step.get("id") or "")
            if not step_id:
                continue
            number = int(raw_step.get("step_id") or 0)
            step_by_number[number] = step_id
            ir.process.steps.append(
                Step(
                    id=step_id,
                    name=str(raw_step.get("name") or step_id),
                    min_duration_ms=0,
                    max_duration_ms=int(raw_step.get("timeout_ms") or 0),
                    failure_target="",
                    source_id=step_id,
                )
            )
            for action in raw_step.get("actions") or []:
                unmapped_free_text.append(f"steps[{step_id}].actions: {action}")
            if raw_step.get("transition_condition"):
                unmapped_free_text.append(f"steps[{step_id}].transition_condition: {raw_step['transition_condition']}")

        for raw_step in v1_steps:
            step_id = str(raw_step.get("id") or "")
            next_number = int(raw_step.get("next_step_id") or 0)
            error_number = int(raw_step.get("error_step_id") or 0)
            next_step = step_by_number.get(next_number, "")
            error_step = step_by_number.get(error_number, "")
            if next_step:
                ir.process.transitions.append(
                    Transition(
                        id=f"TR_{step_id}__{next_step}",
                        from_step=step_id,
                        to_step=next_step,
                        guard_ast=guard_true(),
                        priority=0,
                        source_id=step_id,
                    )
                )
            if error_step:
                ir.process.transitions.append(
                    Transition(
                        id=f"TR_EXC_{step_id}__{error_step}",
                        from_step=step_id,
                        to_step=error_step,
                        guard_ast=guard_true(),
                        priority=100,
                        source_id=step_id,
                    )
                )
                ir.process.exceptions.append(
                    SequenceException(
                        id=f"EXC_{step_id}",
                        from_step=step_id,
                        to_step=error_step,
                        trigger=ExceptionTrigger.TIMEOUT,
                        source_id=step_id,
                    )
                )
        for step in ir.process.steps:
            if step.max_duration_ms and not step.failure_target:
                candidates = [
                    exc.to_step for exc in ir.process.exceptions if exc.from_step == step.id
                ]
                step.failure_target = candidates[0] if candidates else ""

        # --- modes / initial step ------------------------------------------ #
        for raw_mode in raw.get("modes") or []:
            if isinstance(raw_mode, dict):
                ir.process.modes.append(
                    Mode(
                        id=str(raw_mode.get("id") or ""),
                        name=str(raw_mode.get("name") or ""),
                        enabled=True,
                    )
                )
        v1_jobs = [j for j in (raw.get("jobs") or []) if isinstance(j, dict)]
        if v1_jobs:
            initial_number = int(v1_jobs[0].get("initial_step_id") or 0)
            ir.process.initial_step = step_by_number.get(initial_number, "")
        if not ir.process.initial_step and ir.process.steps:
            ir.process.initial_step = ir.process.steps[0].id

        # --- interlocks: free text, deliberately not turned into Guards ---- #
        for interlock in raw.get("interlocks") or []:
            if isinstance(interlock, dict) and interlock.get("expression"):
                unmapped_free_text.append(
                    f"interlocks[{interlock.get('id')}].expression: {interlock['expression']}"
                )

        # --- source bindings (interface only, never writable) -------------- #
        for ref in raw.get("compat_refs") or []:
            if not isinstance(ref, dict):
                continue
            ir.source_bindings.append(
                SourceBinding(
                    source_id=str(ref.get("id") or ""),
                    tia_path=str(ref.get("raw_ref") or ""),
                    block_type=str(ref.get("kind") or "UNKNOWN"),
                    original_xml_sha256=str(ref.get("contract_sha") or ""),
                    original_hash=str(ref.get("contract_sha") or ""),
                    ir_entities=[],
                    referenced_by=[],
                    writable="requires_review",
                    fidelity="imported_reference",
                )
            )

        # --- receipt / views / spec_meta ----------------------------------- #
        ir.views = {"layout": {}, "projection_version": "v2-view-1.0", "v1_views": raw.get("views") or {}}
        ir.spec_meta = {
            "origin": "v1_adapter",
            "stage": "DRAFT",
            "spec_version": str((raw.get("spec_meta") or {}).get("spec_version") or "v0"),
            "v1_spec_hash": str((raw.get("spec_meta") or {}).get("spec_hash") or ""),
        }
        ir.receipt = {
            "adapter": "V1ToV2Adapter/1.0",
            "v1_top_level_field_count": len(V1_TOP_LEVEL_FIELDS),
            "unmapped_free_text": unmapped_free_text,
            "note": "free-text v1 expressions are preserved in legacy_raw; structured GuardAST requires human review",
        }
        ir.refresh_hash()
        return ir

    @staticmethod
    def to_v1_view(v2_ir: EngineeringIRV2) -> dict[str, Any]:
        """Return a READ-ONLY v1 compatibility view; never writes back."""
        if isinstance(v2_ir.legacy_raw, dict):
            view = copy.deepcopy(v2_ir.legacy_raw)
            view["_v2_readonly_view"] = True
            view["_v2_ir_sha256"] = v2_ir.ir_sha256
            return view
        return {
            "_v2_readonly_view": True,
            "_v2_ir_sha256": v2_ir.ir_sha256,
            "project_id": v2_ir.project_id,
            "components": [c.to_dict() for c in v2_ir.components],
            "process": v2_ir.process.to_dict(),
        }

    @staticmethod
    def assert_zero_field_loss(v1_ir: GreenfieldIR | dict[str, Any], v2_ir: EngineeringIRV2) -> bool:
        """True when every v1 top-level field and sub-field survived verbatim."""
        return V1ToV2Adapter.zero_field_loss_report(v1_ir, v2_ir)["zero_loss"]

    @staticmethod
    def zero_field_loss_report(
        v1_ir: GreenfieldIR | dict[str, Any], v2_ir: EngineeringIRV2
    ) -> dict[str, Any]:
        """Detailed, deterministic comparison of v1 payload vs ``legacy_raw``."""
        original = _v1_dict(v1_ir)
        stored = v2_ir.legacy_raw
        missing_keys = [key for key in original if key not in (stored or {})]
        extra_keys = [key for key in (stored or {}) if key not in original]
        differing_keys = [
            key for key in original
            if key in (stored or {}) and canonical_dumps(original[key]) != canonical_dumps(stored[key])
        ]
        expected_hash = sha256_prefixed(canonical_dumps(original))
        hash_match = expected_hash == v2_ir.legacy_raw_sha256
        zero_loss = (
            not missing_keys
            and not extra_keys
            and not differing_keys
            and hash_match
            and all(key in (stored or {}) for key in V1_TOP_LEVEL_FIELDS)
        )
        return {
            "zero_loss": bool(zero_loss),
            "v1_top_level_field_count": len(original),
            "expected_top_level_field_count": len(V1_TOP_LEVEL_FIELDS),
            "missing_keys": sorted(missing_keys),
            "extra_keys": sorted(extra_keys),
            "differing_keys": sorted(differing_keys),
            "legacy_raw_sha256": v2_ir.legacy_raw_sha256,
            "expected_sha256": expected_hash,
            "hash_match": bool(hash_match),
        }
