"""Deterministic driver finite-state machine (WP-02 / blueprint A2).

IDLE -> EXTENDING -> EXTENDED -> RETRACTING -> RETRACTED, plus FAULT.
Manual/Auto commands pass through ONE arbitrator and can never bypass the
SafetyPermit software interlock. Reverse outputs are mutually exclusive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from plc_engine.components.driver_spec import DriverSpec


class DriverState(str, Enum):
    IDLE = "IDLE"
    EXTENDING = "EXTENDING"
    EXTENDED = "EXTENDED"
    RETRACTING = "RETRACTING"
    RETRACTED = "RETRACTED"
    FAULT = "FAULT"


class DriverMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


@dataclass
class DriverRuntime:
    """Runtime snapshot of one driver instance."""

    component_id: str = ""
    state: DriverState = DriverState.IDLE
    elapsed_ms: int = 0
    error_id: str = ""
    q_extend: bool = False
    q_retract: bool = False
    mode: DriverMode = DriverMode.AUTO
    safety_permit: bool = True
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "state": self.state.value if isinstance(self.state, DriverState) else str(self.state),
            "elapsed_ms": int(self.elapsed_ms),
            "error_id": self.error_id,
            "q_extend": bool(self.q_extend),
            "q_retract": bool(self.q_retract),
            "mode": self.mode.value if isinstance(self.mode, DriverMode) else str(self.mode),
            "safety_permit": bool(self.safety_permit),
        }


def arbitrate_mode(
    *,
    auto_extend: bool,
    auto_retract: bool,
    manual_extend: bool,
    manual_retract: bool,
    mode: DriverMode,
    safety_permit: bool,
) -> tuple[bool, bool]:
    """Single command arbitrator with SafetyPermit as the last gate.

    Returns ``(cmd_extend, cmd_retract)``. In MANUAL only manual commands are
    honoured; in AUTO only automatic ones. Reverse outputs are interlocked and
    SafetyPermit=false forces both off (software interlock only).
    """
    if mode is DriverMode.MANUAL:
        extend, retract = bool(manual_extend), bool(manual_retract)
    else:
        extend, retract = bool(auto_extend), bool(auto_retract)
    if extend and retract:
        extend, retract = False, False
    if not safety_permit:
        extend, retract = False, False
    return extend, retract


class DriverFSM:
    """Stateful, deterministic driver instance used by the scan simulator."""

    def __init__(self, spec: DriverSpec, component_id: str = "") -> None:
        self.spec = spec
        self.component_id = component_id or spec.id
        allowed = {state for state in spec.states}
        self.allowed_states: set[str] = allowed or {state.value for state in DriverState}
        self.runtime = DriverRuntime(component_id=self.component_id)

    def reset(self) -> DriverRuntime:
        """Clear fault and elapsed time; returns a fresh IDLE runtime."""
        self.runtime = DriverRuntime(component_id=self.component_id)
        return self.runtime

    def _set_state(self, state: DriverState, cycle_ms: int, event: str) -> None:
        self.runtime.state = state
        self.runtime.elapsed_ms = 0
        self.runtime.history.append(
            {"state": state.value, "event": event, "cycle_ms": int(cycle_ms)}
        )

    def step(
        self,
        *,
        auto_extend: bool = False,
        auto_retract: bool = False,
        manual_extend: bool = False,
        manual_retract: bool = False,
        mode: DriverMode = DriverMode.AUTO,
        safety_permit: bool = True,
        sensor_out: bool = False,
        sensor_in: bool = False,
        reset: bool = False,
        cycle_ms: int = 10,
    ) -> DriverRuntime:
        """Advance the FSM by exactly one deterministic scan cycle."""
        rt = self.runtime
        rt.mode = mode
        rt.safety_permit = safety_permit
        timeout = max(1, int(self.spec.move_timeout_ms))

        cmd_extend, cmd_retract = arbitrate_mode(
            auto_extend=auto_extend,
            auto_retract=auto_retract,
            manual_extend=manual_extend,
            manual_retract=manual_retract,
            mode=mode,
            safety_permit=safety_permit,
        )
        rt.q_extend = cmd_extend and rt.state in (DriverState.IDLE, DriverState.EXTENDING)
        rt.q_retract = cmd_retract and rt.state in (DriverState.EXTENDED, DriverState.RETRACTING)
        if rt.q_extend and rt.q_retract:  # defensive: reverse outputs never coexist
            rt.q_extend, rt.q_retract = False, False

        if rt.state is DriverState.FAULT:
            if reset:
                self._set_state(DriverState.IDLE, cycle_ms, "reset")
                rt.error_id = ""
            return rt

        rt.elapsed_ms += int(cycle_ms)
        if reset:
            self._set_state(DriverState.IDLE, cycle_ms, "reset")
            rt.error_id = ""
            return rt

        if not safety_permit and rt.state in (DriverState.EXTENDING, DriverState.RETRACTING):
            # Software interlock: stop motion, wait for an explicit reset.
            self._set_state(DriverState.FAULT, cycle_ms, "safety_permit_lost")
            rt.error_id = "SAFETY_PERMIT_LOST"
            return rt

        if rt.state is DriverState.IDLE or rt.state is DriverState.RETRACTED:
            if cmd_extend:
                self._set_state(DriverState.EXTENDING, cycle_ms, "cmd_extend")
            return rt

        if rt.state is DriverState.EXTENDING:
            if sensor_out:
                self._set_state(DriverState.EXTENDED, cycle_ms, "sensor_out")
            elif rt.elapsed_ms >= timeout:
                self._set_state(DriverState.FAULT, cycle_ms, "extend_timeout")
                rt.error_id = "EXTEND_TIMEOUT"
            return rt

        if rt.state is DriverState.EXTENDED:
            if cmd_retract:
                self._set_state(DriverState.RETRACTING, cycle_ms, "cmd_retract")
            return rt

        if rt.state is DriverState.RETRACTING:
            if sensor_in:
                self._set_state(DriverState.RETRACTED, cycle_ms, "sensor_in")
            elif rt.elapsed_ms >= timeout:
                self._set_state(DriverState.FAULT, cycle_ms, "retract_timeout")
                rt.error_id = "RETRACT_TIMEOUT"
            return rt

        return rt
